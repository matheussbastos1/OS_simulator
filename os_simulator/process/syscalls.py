"""System call dispatching, I/O profiles, deterministic random I/O, and block registry."""

from dataclasses import dataclass, field
import math
import random
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from os_simulator.core.context import ExecutionContext
from os_simulator.core.events import EventManager, SimulationEvent
from os_simulator.core.exceptions import (
    InvalidStateTransitionException,
    OSSimulatorException,
    ThreadNotFoundException,
)
from os_simulator.core.ports import BlockDevicePort
from os_simulator.core.types import (
    AuditEventType,
    BlockReason,
    IOProfileType,
    ProcessState,
    SimulationEventType,
    SyscallType,
)
from os_simulator.filesystem.service import FileSystemService
from os_simulator.io.service import IOManager
from os_simulator.process.manager import ProcessManager
from os_simulator.process.thread import SimulatedThread, WorkloadStep
from os_simulator.security.audit import AuditLog


# Compatibility alias matching Stage 5 architectural blueprint
SyscallSpec = WorkloadStep

BLOCKING_SYSCALL_TYPES = frozenset({
    SyscallType.IO_READ,
    SyscallType.IO_WRITE,
    SyscallType.FS_READ,
    SyscallType.FS_WRITE,
    SyscallType.SLEEP_WAIT,
})

VALID_BLOCK_REASONS = frozenset({
    BlockReason.IO_WAIT,
    BlockReason.FS_IO,
    BlockReason.SLEEP_WAIT,
    BlockReason.MUTEX_WAIT,
})

_SYSCALL_TO_BLOCK_REASON: Dict[SyscallType, BlockReason] = {
    SyscallType.IO_READ: BlockReason.IO_WAIT,
    SyscallType.IO_WRITE: BlockReason.IO_WAIT,
    SyscallType.FS_READ: BlockReason.FS_IO,
    SyscallType.FS_WRITE: BlockReason.FS_IO,
    SyscallType.SLEEP_WAIT: BlockReason.SLEEP_WAIT,
}


def _validate_int(
    value: Any,
    field_name: str,
    min_val: Optional[int] = None,
    allow_none: bool = False,
) -> Optional[int]:
    """Validate strict integer parameter (rejecting booleans and non-ints)."""
    if allow_none and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} deve ser um inteiro válido (recebido: {value!r}).")
    if min_val is not None and value < min_val:
        raise ValueError(f"{field_name} deve ser >= {min_val} (recebido: {value}).")
    return value


@dataclass
class IOProfile:
    """Thread I/O generation profile supporting NONE, FIXED, PERIODIC, and seeded RANDOM modes."""

    profile_type: IOProfileType = IOProfileType.NONE
    interval_cpu_ms: Optional[int] = None
    default_duration_ms: int = 4
    min_duration_ms: int = 2
    max_duration_ms: int = 6
    io_probability: float = 0.25
    max_random_events: int = 3
    seed: int = 42
    syscall_type: SyscallType = SyscallType.IO_READ
    block_id: int = 0
    fixed_steps: List[WorkloadStep] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.profile_type, IOProfileType):
            self.profile_type = IOProfileType.from_string(str(self.profile_type))
        if not isinstance(self.syscall_type, SyscallType):
            self.syscall_type = SyscallType.from_string(str(self.syscall_type))

        _validate_int(self.default_duration_ms, "default_duration_ms", min_val=1)
        _validate_int(self.min_duration_ms, "min_duration_ms", min_val=1)
        _validate_int(self.max_duration_ms, "max_duration_ms", min_val=1)

        if self.min_duration_ms > self.max_duration_ms:
            raise ValueError(
                f"min_duration_ms ({self.min_duration_ms}) não pode exceder max_duration_ms ({self.max_duration_ms})."
            )

        if (
            isinstance(self.io_probability, bool)
            or not isinstance(self.io_probability, (int, float))
            or math.isnan(float(self.io_probability))
        ):
            raise ValueError(f"io_probability inválido: {self.io_probability!r}.")
        self.io_probability = float(self.io_probability)
        if not (0.0 <= self.io_probability <= 1.0):
            raise ValueError(
                f"io_probability deve estar entre 0.0 e 1.0 (recebido: {self.io_probability})."
            )

        _validate_int(self.max_random_events, "max_random_events", min_val=0)
        _validate_int(self.seed, "seed")
        _validate_int(self.block_id, "block_id", min_val=0)

        if self.profile_type == IOProfileType.PERIODIC:
            if self.interval_cpu_ms is None:
                raise ValueError("Perfil PERIODIC exige interval_cpu_ms > 0.")
            _validate_int(self.interval_cpu_ms, "interval_cpu_ms", min_val=1)
        elif self.interval_cpu_ms is not None:
            _validate_int(self.interval_cpu_ms, "interval_cpu_ms", min_val=1)

    def create_rng(self, pid: int, tid: int) -> random.Random:
        """Create an isolated deterministic Random instance scoped to a specific thread."""
        _validate_int(pid, "pid", min_val=0)
        _validate_int(tid, "tid", min_val=0)
        return random.Random(self.seed + pid * 1009 + tid)

    @classmethod
    def from_value(cls, value: Any, default_seed: int = 42) -> "IOProfile":
        """Normalize an IOProfile, IOProfileType, string, or None into an IOProfile instance."""
        if isinstance(value, cls):
            return value
        if value is None:
            return cls(profile_type=IOProfileType.NONE, seed=default_seed)
        if isinstance(value, IOProfileType):
            ptype = value
        else:
            ptype = IOProfileType.from_string(str(value))
        if ptype == IOProfileType.PERIODIC:
            return cls(profile_type=ptype, interval_cpu_ms=4, seed=default_seed)
        return cls(profile_type=ptype, seed=default_seed)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize IOProfile configuration to dictionary."""
        return {
            "profile_type": self.profile_type.value,
            "interval_cpu_ms": self.interval_cpu_ms,
            "default_duration_ms": self.default_duration_ms,
            "min_duration_ms": self.min_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "io_probability": self.io_probability,
            "max_random_events": self.max_random_events,
            "seed": self.seed,
            "syscall_type": self.syscall_type.value,
            "block_id": self.block_id,
            "fixed_steps": [step.to_dict() for step in self.fixed_steps],
        }


@dataclass
class BlockRecord:
    """Audit record describing a thread blocking episode and its subsequent unblock."""

    tid: int
    pid: int
    thread_name: str
    process_name: str
    reason: BlockReason
    resource_id: Optional[str] = None
    blocked_at_ms: int = 0
    expected_unblock_at_ms: Optional[int] = None
    unblocked_at_ms: Optional[int] = None
    previous_state: ProcessState = ProcessState.RUNNING
    next_state: Optional[ProcessState] = None
    syscall_type: Optional[SyscallType] = None

    @property
    def is_active(self) -> bool:
        """Return True while the thread remains blocked."""
        return self.unblocked_at_ms is None

    @property
    def blocked_duration_ms(self) -> Optional[int]:
        """Return actual blocked duration in ms once unblocked, else None."""
        if self.unblocked_at_ms is None:
            return None
        return max(0, self.unblocked_at_ms - self.blocked_at_ms)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize block record to dictionary."""
        return {
            "tid": self.tid,
            "pid": self.pid,
            "thread_name": self.thread_name,
            "process_name": self.process_name,
            "reason": self.reason.value,
            "resource_id": self.resource_id,
            "blocked_at_ms": self.blocked_at_ms,
            "expected_unblock_at_ms": self.expected_unblock_at_ms,
            "unblocked_at_ms": self.unblocked_at_ms,
            "blocked_duration_ms": self.blocked_duration_ms,
            "previous_state": self.previous_state.value,
            "next_state": self.next_state.value if self.next_state is not None else None,
            "syscall_type": self.syscall_type.value if self.syscall_type is not None else None,
            "active": self.is_active,
        }


class BlockRegistry:
    """Tracks active thread blocks and complete historical block/unblock audit records."""

    def __init__(self) -> None:
        self._active_blocks: Dict[int, BlockRecord] = {}
        self._history: List[BlockRecord] = []

    @staticmethod
    def _normalize_reason(reason: Union[BlockReason, str]) -> BlockReason:
        if isinstance(reason, BlockReason):
            resolved = reason
        else:
            resolved = BlockReason(str(reason).strip().upper())
        if resolved not in VALID_BLOCK_REASONS:
            raise ValueError(f"Motivo de bloqueio inválido: '{resolved.value}'.")
        return resolved

    @staticmethod
    def _normalize_state(state: Union[ProcessState, str]) -> ProcessState:
        if isinstance(state, ProcessState):
            return ProcessState.normalize(state)
        return ProcessState.normalize(ProcessState.from_string(str(state)))

    def record_block(
        self,
        tid: int,
        pid: int,
        reason: Union[BlockReason, str],
        blocked_at_ms: int,
        resource_id: Optional[str] = None,
        expected_unblock_at_ms: Optional[int] = None,
        thread_name: str = "",
        process_name: str = "",
        previous_state: Union[ProcessState, str] = ProcessState.RUNNING,
        syscall_type: Optional[Union[SyscallType, str]] = None,
    ) -> BlockRecord:
        """Register an active block entry for a thread."""
        _validate_int(tid, "tid", min_val=0)
        _validate_int(pid, "pid", min_val=0)
        _validate_int(blocked_at_ms, "blocked_at_ms", min_val=0)
        if expected_unblock_at_ms is not None:
            _validate_int(expected_unblock_at_ms, "expected_unblock_at_ms", min_val=0)
            if expected_unblock_at_ms < blocked_at_ms:
                raise ValueError(
                    f"expected_unblock_at_ms ({expected_unblock_at_ms}) não pode ser menor que blocked_at_ms ({blocked_at_ms})."
                )

        if tid in self._active_blocks:
            raise InvalidStateTransitionException(
                f"Thread TID {tid} já possui um bloqueio ativo.",
                from_state=ProcessState.BLOCKED.value,
                to_state=ProcessState.BLOCKED.value,
                entity_id=f"TID:{tid}",
            )

        norm_reason = self._normalize_reason(reason)
        norm_prev = self._normalize_state(previous_state)
        norm_syscall: Optional[SyscallType] = None
        if syscall_type is not None:
            norm_syscall = (
                syscall_type
                if isinstance(syscall_type, SyscallType)
                else SyscallType.from_string(str(syscall_type))
            )

        record = BlockRecord(
            tid=tid,
            pid=pid,
            thread_name=thread_name,
            process_name=process_name,
            reason=norm_reason,
            resource_id=resource_id,
            blocked_at_ms=blocked_at_ms,
            expected_unblock_at_ms=expected_unblock_at_ms,
            unblocked_at_ms=None,
            previous_state=norm_prev,
            next_state=None,
            syscall_type=norm_syscall,
        )
        self._active_blocks[tid] = record
        self._history.append(record)
        return record

    def record_unblock(
        self,
        tid: int,
        timestamp_ms: int,
        next_state: Union[ProcessState, str] = ProcessState.READY,
    ) -> BlockRecord:
        """Close an active block record when a thread unblocks or terminates."""
        _validate_int(tid, "tid", min_val=0)
        _validate_int(timestamp_ms, "timestamp_ms", min_val=0)
        norm_next = self._normalize_state(next_state)

        if tid not in self._active_blocks:
            raise InvalidStateTransitionException(
                f"Thread TID {tid} não está bloqueada no registro de bloqueios.",
                from_state="NOT_BLOCKED",
                to_state=norm_next.value,
                entity_id=f"TID:{tid}",
            )

        if norm_next not in (ProcessState.READY, ProcessState.TERMINATED):
            raise InvalidStateTransitionException(
                f"Estado de destino inválido ao desbloquear TID {tid}: '{norm_next.value}'.",
                from_state=ProcessState.BLOCKED.value,
                to_state=norm_next.value,
                entity_id=f"TID:{tid}",
            )

        record = self._active_blocks[tid]
        if timestamp_ms < record.blocked_at_ms:
            raise ValueError(
                f"timestamp_ms ({timestamp_ms}) não pode ser anterior a blocked_at_ms ({record.blocked_at_ms})."
            )

        del self._active_blocks[tid]
        record.unblocked_at_ms = timestamp_ms
        record.next_state = norm_next
        return record

    def get_active_block(self, tid: int) -> Optional[BlockRecord]:
        """Return active BlockRecord for tid, or None if not blocked."""
        return self._active_blocks.get(tid)

    def get_active_blocks(self) -> List[BlockRecord]:
        """Return all currently active BlockRecords."""
        return list(self._active_blocks.values())

    def get_history(
        self,
        tid: Optional[int] = None,
        pid: Optional[int] = None,
    ) -> List[BlockRecord]:
        """Return full block/unblock audit history, optionally filtered by tid/pid."""
        records = self._history
        if tid is not None:
            records = [rec for rec in records if rec.tid == tid]
        if pid is not None:
            records = [rec for rec in records if rec.pid == pid]
        return list(records)

    def is_blocked(self, tid: int) -> bool:
        """Return True if tid currently holds an active block record."""
        return tid in self._active_blocks

    def clear(self) -> None:
        """Clear all active and historical block records."""
        self._active_blocks.clear()
        self._history.clear()


@dataclass
class SyscallExecutionRecord:
    """Record of an executed system call and its blocking/storage effects."""

    seq: int
    timestamp_ms: int
    pid: int
    tid: int
    process_name: str
    thread_name: str
    syscall_type: SyscallType
    cpu_consumed_ms: int
    duration_ms: int = 0
    blocked: bool = False
    block_reason: BlockReason = BlockReason.NONE
    resource_id: Optional[str] = None
    block_id: Optional[int] = None
    path: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    result_summary: Optional[str] = None
    event_seq: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize syscall execution record to dictionary."""
        return {
            "seq": self.seq,
            "timestamp_ms": self.timestamp_ms,
            "pid": self.pid,
            "tid": self.tid,
            "process_name": self.process_name,
            "thread_name": self.thread_name,
            "syscall_type": self.syscall_type.value,
            "cpu_consumed_ms": self.cpu_consumed_ms,
            "duration_ms": self.duration_ms,
            "blocked": self.blocked,
            "block_reason": self.block_reason.value,
            "resource_id": self.resource_id,
            "block_id": self.block_id,
            "path": self.path,
            "success": self.success,
            "error": self.error,
            "result_summary": self.result_summary,
            "event_seq": self.event_seq,
        }


class SyscallDispatcher:
    """Dispatches thread syscalls, evaluates I/O profiles, and handles completion wakeups."""

    def __init__(
        self,
        process_manager: ProcessManager,
        event_manager: EventManager,
        io_manager: Optional[IOManager] = None,
        block_device: Optional[BlockDevicePort] = None,
        fs_service: Optional[FileSystemService] = None,
        auth_context: Optional[ExecutionContext] = None,
        default_seed: int = 42,
        block_registry: Optional[BlockRegistry] = None,
        audit_log: Optional[AuditLog] = None,
    ) -> None:
        _validate_int(default_seed, "default_seed")
        self.process_manager = process_manager
        self.event_manager = event_manager
        self.io_manager = io_manager
        self.block_device = block_device
        self.fs_service = fs_service
        self.auth_context = auth_context
        self.default_seed = default_seed
        self.block_registry = block_registry or BlockRegistry()
        self.audit_log = audit_log

        self._history: List[SyscallExecutionRecord] = []
        self._next_seq: int = 1
        self._thread_rngs: Dict[Tuple[int, int], random.Random] = {}
        self._evaluated_profile_cpus: Dict[int, Set[int]] = {}
        self._random_event_counts: Dict[int, int] = {}
        self._pending_steps_by_event_seq: Dict[int, WorkloadStep] = {}

    def set_default_seed(self, seed: int) -> None:
        """Update default deterministic RNG seed."""
        _validate_int(seed, "seed")
        self.default_seed = seed

    def set_auth_context(self, context: Optional[ExecutionContext]) -> None:
        """Update execution context used for filesystem syscalls."""
        self.auth_context = context

    def _get_storage_capacity(self) -> Optional[int]:
        """Determine usable logical block capacity from configured device or IOManager."""
        if self.block_device is not None:
            cap = self.block_device.get_capacity()
            return cap if cap > 0 else None
        if self.io_manager is not None:
            backend = self.io_manager.storage_backend
            for attr in ("logical_capacity", "capacity_blocks", "capacity"):
                val = getattr(backend, attr, None)
                if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                    return val
            if hasattr(backend, "get_capacity"):
                cap = backend.get_capacity()
                if isinstance(cap, int) and cap > 0:
                    return cap
        return None

    def _resolve_block_id(self, raw_block_id: Optional[int]) -> int:
        if raw_block_id is None:
            resolved = 0
        else:
            _validate_int(raw_block_id, "block_id", min_val=0)
            resolved = raw_block_id
        capacity = self._get_storage_capacity()
        if capacity is not None and capacity > 0:
            return resolved % capacity
        return resolved

    def _get_or_create_rng(self, thread: SimulatedThread, profile: IOProfile) -> random.Random:
        key = (thread.tid, profile.seed)
        if key not in self._thread_rngs:
            self._thread_rngs[key] = profile.create_rng(thread.pid, thread.tid)
        return self._thread_rngs[key]

    @staticmethod
    def is_blocking_step(step: WorkloadStep) -> bool:
        """Return True if a WorkloadStep blocks the executing thread."""
        if step.syscall_type in BLOCKING_SYSCALL_TYPES and step.duration_ms > 0:
            return True
        if step.syscall_type == SyscallType.MUTEX_LOCK:
            return True
        return False

    def validate_workload_step(self, thread: SimulatedThread, step: WorkloadStep) -> None:
        """Validate WorkloadStep parameters and trigger_cpu_ms bounds against thread burst."""
        if not isinstance(step, WorkloadStep):
            raise ValueError(f"step deve ser uma instância de WorkloadStep (recebido: {step!r}).")
        _validate_int(step.trigger_cpu_ms, "trigger_cpu_ms", min_val=0)
        _validate_int(step.duration_ms, "duration_ms", min_val=0)
        if step.block_id is not None:
            _validate_int(step.block_id, "block_id", min_val=0)

        blocking = self.is_blocking_step(step)
        if thread.cpu_burst_ms > 0:
            if blocking:
                if not (0 <= step.trigger_cpu_ms < thread.cpu_burst_ms):
                    raise ValueError(
                        f"WorkloadStep bloqueante inválido: trigger_cpu_ms={step.trigger_cpu_ms} "
                        f"deve satisfazer 0 <= trigger_cpu_ms < cpu_burst_ms ({thread.cpu_burst_ms})."
                    )
            else:
                if not (0 <= step.trigger_cpu_ms <= thread.cpu_burst_ms):
                    raise ValueError(
                        f"WorkloadStep inválido: trigger_cpu_ms={step.trigger_cpu_ms} "
                        f"excede cpu_burst_ms ({thread.cpu_burst_ms})."
                    )
        else:
            if step.trigger_cpu_ms > 0:
                raise ValueError(
                    f"WorkloadStep com trigger_cpu_ms={step.trigger_cpu_ms} inválido para thread com cpu_burst_ms=0."
                )

    def _resolve_profile(self, thread: SimulatedThread) -> IOProfile:
        return IOProfile.from_value(thread.io_profile, default_seed=self.default_seed)

    def check_due_syscalls(self, thread: SimulatedThread, now_ms: int) -> List[WorkloadStep]:
        """Return WorkloadSteps due strictly according to thread.cpu_consumed_ms (never now_ms)."""
        _validate_int(now_ms, "now_ms", min_val=0)
        norm_state = ProcessState.normalize(thread.state)
        if norm_state in (ProcessState.TERMINATED, ProcessState.BLOCKED):
            return []

        profile = self._resolve_profile(thread)

        # Gather scheduled fixed steps from thread and optional FIXED IOProfile
        candidate_steps: List[WorkloadStep] = []
        seen_ids: Set[int] = set()
        for step in thread.workload_steps:
            if id(step) not in seen_ids:
                candidate_steps.append(step)
                seen_ids.add(id(step))
        if profile.profile_type == IOProfileType.FIXED:
            for step in profile.fixed_steps:
                if id(step) not in seen_ids:
                    candidate_steps.append(step)
                    seen_ids.add(id(step))

        due_steps: List[WorkloadStep] = []
        past_completion = thread.cpu_burst_ms > 0 and thread.cpu_consumed_ms > thread.cpu_burst_ms
        at_or_past_completion = thread.cpu_burst_ms > 0 and thread.remaining_burst_ms <= 0

        for step in candidate_steps:
            if step.executed:
                continue
            self.validate_workload_step(thread, step)
            if past_completion:
                continue
            if at_or_past_completion:
                # Only allow an explicit non-blocking step triggered exactly at completion
                if self.is_blocking_step(step) or step.trigger_cpu_ms < thread.cpu_burst_ms:
                    continue
            if step.trigger_cpu_ms <= thread.cpu_consumed_ms:
                due_steps.append(step)

        due_steps.sort(key=lambda s: s.trigger_cpu_ms)

        # Profile-driven PERIODIC / RANDOM I/O only while 0 < cpu_consumed_ms < cpu_burst_ms
        if (
            profile.profile_type in (IOProfileType.PERIODIC, IOProfileType.RANDOM)
            and 0 < thread.cpu_consumed_ms < thread.cpu_burst_ms
            and thread.remaining_burst_ms > 0
        ):
            evaluated = self._evaluated_profile_cpus.setdefault(thread.tid, set())
            if thread.cpu_consumed_ms not in evaluated:
                evaluated.add(thread.cpu_consumed_ms)
                generated = self._maybe_generate_profile_step(thread, profile)
                if generated is not None:
                    due_steps.append(generated)

        return due_steps

    def _maybe_generate_profile_step(
        self,
        thread: SimulatedThread,
        profile: IOProfile,
    ) -> Optional[WorkloadStep]:
        if profile.profile_type == IOProfileType.PERIODIC:
            assert profile.interval_cpu_ms is not None
            if thread.cpu_consumed_ms % profile.interval_cpu_ms == 0:
                block_id = (
                    profile.block_id
                    if profile.syscall_type in (SyscallType.IO_READ, SyscallType.IO_WRITE)
                    else None
                )
                return WorkloadStep(
                    trigger_cpu_ms=thread.cpu_consumed_ms,
                    syscall_type=profile.syscall_type,
                    duration_ms=profile.default_duration_ms,
                    block_id=block_id,
                )
            return None

        if profile.profile_type == IOProfileType.RANDOM:
            interval = profile.interval_cpu_ms or 1
            if thread.cpu_consumed_ms % interval != 0:
                return None

            count = self._random_event_counts.get(thread.tid, 0)
            if count >= profile.max_random_events:
                return None

            rng = self._get_or_create_rng(thread, profile)
            if rng.random() >= profile.io_probability:
                return None

            duration_ms = rng.randint(profile.min_duration_ms, profile.max_duration_ms)
            block_id: Optional[int] = None
            if profile.syscall_type in (SyscallType.IO_READ, SyscallType.IO_WRITE):
                cap = self._get_storage_capacity() or 16
                block_id = rng.randint(0, cap - 1)

            self._random_event_counts[thread.tid] = count + 1
            return WorkloadStep(
                trigger_cpu_ms=thread.cpu_consumed_ms,
                syscall_type=profile.syscall_type,
                duration_ms=duration_ms,
                block_id=block_id,
            )

        return None

    def _read_existing_block_safely(self, target_block: int) -> bytes:
        """Read current block payload without mutating IOManager read counters."""
        if self.io_manager is not None:
            backend = self.io_manager.storage_backend
            if hasattr(backend, "read_block"):
                return bytes(backend.read_block(target_block))
            if hasattr(backend, "read"):
                return bytes(backend.read(target_block))
            return b"\x00"
        if self.block_device is not None:
            return bytes(self.block_device.read_block(target_block))
        return b""

    def _execute_io_or_fs(
        self,
        thread: SimulatedThread,
        step: WorkloadStep,
    ) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[str]]:
        """Execute underlying I/O or Filesystem operation and return resource metadata."""
        stype = step.syscall_type

        if stype == SyscallType.IO_READ:
            target_block = self._resolve_block_id(step.block_id)
            resource_id = f"block:{target_block}"
            if self.io_manager is not None:
                data = self.io_manager.dispatch_read(target_block)
                step.result = bytes(data)
                return resource_id, target_block, None, f"read {len(data)} bytes"
            if self.block_device is not None:
                data = self.block_device.read_block(target_block)
                step.result = bytes(data)
                return resource_id, target_block, None, f"read {len(data)} bytes"
            return resource_id, target_block, None, "simulated io_read"

        if stype == SyscallType.IO_WRITE:
            target_block = self._resolve_block_id(step.block_id)
            resource_id = f"block:{target_block}"
            if step.data is not None:
                payload = step.data.encode("utf-8") if isinstance(step.data, str) else bytes(step.data)
            else:
                payload = self._read_existing_block_safely(target_block)

            if self.io_manager is not None:
                self.io_manager.dispatch_write(target_block, payload)
                step.result = len(payload)
                return resource_id, target_block, None, f"wrote {len(payload)} bytes"
            if self.block_device is not None:
                self.block_device.write_block(target_block, payload)
                step.result = len(payload)
                return resource_id, target_block, None, f"wrote {len(payload)} bytes"
            step.result = len(payload)
            return resource_id, target_block, None, "simulated io_write"

        if stype == SyscallType.FS_READ:
            if self.fs_service is not None:
                if not step.path or not str(step.path).strip():
                    raise ValueError("Syscall FS_READ requer um caminho (path) válido.")
                ctx = self.auth_context
                cwd = ctx.cwd if ctx is not None else "/"
                content = self.fs_service.read_file(step.path, cwd=cwd, context=ctx)
                step.result = content
                return step.path, None, step.path, f"fs_read {len(content)} chars"
            resource_id = step.path or "fs:read"
            return resource_id, None, step.path, "simulated fs_read"

        if stype == SyscallType.FS_WRITE:
            if self.fs_service is not None:
                if not step.path or not str(step.path).strip():
                    raise ValueError("Syscall FS_WRITE requer um caminho (path) válido.")
                ctx = self.auth_context
                cwd = ctx.cwd if ctx is not None else "/"
                if step.data is not None:
                    payload_fs: Union[str, bytes] = step.data
                else:
                    existing_node = self.fs_service.vfs.get_node(step.path, cwd=cwd)
                    if existing_node is not None:
                        payload_fs = bytes(self.fs_service.read_file_bytes(step.path, cwd=cwd, context=ctx))
                    else:
                        payload_fs = ""
                write_info = self.fs_service.write_file(step.path, payload_fs, cwd=cwd, context=ctx)
                step.result = write_info
                return step.path, None, step.path, f"fs_write {write_info.get('real_size', 0)} bytes"
            resource_id = step.path or "fs:write"
            return resource_id, None, step.path, "simulated fs_write"

        if stype == SyscallType.SLEEP_WAIT:
            return f"sleep:{step.duration_ms}ms", None, None, f"sleep {step.duration_ms}ms"

        if stype == SyscallType.YIELD:
            return "cpu:yield", None, None, "yield"

        return step.mutex_name or step.path, step.block_id, step.path, stype.value.lower()

    def _get_process_name(self, pid: int) -> str:
        proc = self.process_manager.processes.get(pid)
        return proc.name if proc is not None else f"PID:{pid}"

    def _log_audit(
        self,
        record: SyscallExecutionRecord,
        result_status: str,
    ) -> None:
        if self.audit_log is None:
            return
        username = self.auth_context.username if self.auth_context is not None else "kernel"
        self.audit_log.log_event(
            event_type=AuditEventType.SYSCALL_EXECUTED,
            username=username,
            path=record.path or record.resource_id,
            action=record.syscall_type.value,
            result=result_status,
            details={
                "pid": record.pid,
                "tid": record.tid,
                "cpu_consumed_ms": record.cpu_consumed_ms,
                "duration_ms": record.duration_ms,
                "blocked": record.blocked,
            },
        )

    def dispatch_syscall(
        self,
        thread: SimulatedThread,
        step: WorkloadStep,
        now_ms: int,
    ) -> SyscallExecutionRecord:
        """Validate and dispatch a syscall for a currently RUNNING thread."""
        _validate_int(now_ms, "now_ms", min_val=0)
        norm_state = ProcessState.normalize(thread.state)
        if norm_state != ProcessState.RUNNING:
            raise InvalidStateTransitionException(
                f"Apenas threads em execução (RUNNING) podem invocar syscalls (estado atual de TID {thread.tid}: {norm_state.value}).",
                from_state=norm_state.value,
                to_state=ProcessState.BLOCKED.value,
                entity_id=f"TID:{thread.tid}",
            )

        if step.executed:
            raise ValueError(
                f"WorkloadStep já foi executado anteriormente (trigger_cpu_ms={step.trigger_cpu_ms}, syscall={step.syscall_type.value})."
            )

        self.validate_workload_step(thread, step)
        process_name = self._get_process_name(thread.pid)
        seq = self._next_seq
        self._next_seq += 1

        try:
            resource_id, resolved_block_id, path, result_summary = self._execute_io_or_fs(thread, step)
        except OSSimulatorException as exc:
            step.executed = True
            step.status = "FAILED"
            failed_rec = SyscallExecutionRecord(
                seq=seq,
                timestamp_ms=now_ms,
                pid=thread.pid,
                tid=thread.tid,
                process_name=process_name,
                thread_name=thread.name,
                syscall_type=step.syscall_type,
                cpu_consumed_ms=thread.cpu_consumed_ms,
                duration_ms=step.duration_ms,
                blocked=False,
                block_reason=BlockReason.NONE,
                resource_id=step.path or (f"block:{step.block_id}" if step.block_id is not None else None),
                block_id=step.block_id,
                path=step.path,
                success=False,
                error=str(exc),
            )
            self._history.append(failed_rec)
            self._log_audit(failed_rec, "DENIED" if "permissão" in str(exc).lower() else "FAILURE")
            raise

        should_block = step.syscall_type in _SYSCALL_TO_BLOCK_REASON and step.duration_ms > 0
        block_reason = BlockReason.NONE
        event_seq: Optional[int] = None

        if should_block:
            block_reason = _SYSCALL_TO_BLOCK_REASON[step.syscall_type]
            completion_event_type = (
                SimulationEventType.SLEEP_WAKEUP
                if step.syscall_type == SyscallType.SLEEP_WAIT
                else SimulationEventType.IO_COMPLETION
            )
            self.process_manager.transition_thread_state(
                thread,
                ProcessState.BLOCKED,
                timestamp_ms=now_ms,
                reason=f"Syscall {step.syscall_type.value} ({resource_id})",
                block_reason=block_reason,
                blocked_on=resource_id,
            )
            self.block_registry.record_block(
                tid=thread.tid,
                pid=thread.pid,
                reason=block_reason,
                blocked_at_ms=now_ms,
                resource_id=resource_id,
                expected_unblock_at_ms=now_ms + step.duration_ms,
                thread_name=thread.name,
                process_name=process_name,
                previous_state=ProcessState.RUNNING,
                syscall_type=step.syscall_type,
            )
            scheduled = self.event_manager.schedule_at(
                timestamp_ms=now_ms + step.duration_ms,
                event_type=completion_event_type,
                pid=thread.pid,
                tid=thread.tid,
                payload={
                    "syscall_type": step.syscall_type.value,
                    "block_reason": block_reason.value,
                    "resource_id": resource_id,
                    "duration_ms": step.duration_ms,
                    "syscall_seq": seq,
                },
            )
            event_seq = scheduled.seq
            step.status = "BLOCKED"
            self._pending_steps_by_event_seq[event_seq] = step
        else:
            step.status = "COMPLETED"

        step.executed = True

        record = SyscallExecutionRecord(
            seq=seq,
            timestamp_ms=now_ms,
            pid=thread.pid,
            tid=thread.tid,
            process_name=process_name,
            thread_name=thread.name,
            syscall_type=step.syscall_type,
            cpu_consumed_ms=thread.cpu_consumed_ms,
            duration_ms=step.duration_ms,
            blocked=should_block,
            block_reason=block_reason,
            resource_id=resource_id,
            block_id=resolved_block_id,
            path=path,
            success=True,
            error=None,
            result_summary=result_summary,
            event_seq=event_seq,
        )
        self._history.append(record)
        self._log_audit(record, "SUCCESS")
        return record

    def handle_completion_event(
        self,
        event: SimulationEvent,
        now_ms: int,
    ) -> Optional[SimulatedThread]:
        """Process IO_COMPLETION or SLEEP_WAKEUP event, transitioning BLOCKED -> READY."""
        _validate_int(now_ms, "now_ms", min_val=0)
        if event.cancelled:
            return None
        if event.event_type not in (
            SimulationEventType.IO_COMPLETION,
            SimulationEventType.SLEEP_WAKEUP,
        ):
            return None
        if event.tid is None:
            return None

        pending_step = self._pending_steps_by_event_seq.pop(event.seq, None)

        try:
            thread = self.process_manager.get_thread(event.tid)
        except ThreadNotFoundException:
            if self.block_registry.is_blocked(event.tid):
                self.block_registry.record_unblock(
                    event.tid,
                    timestamp_ms=now_ms,
                    next_state=ProcessState.TERMINATED,
                )
            return None

        norm_state = ProcessState.normalize(thread.state)
        if norm_state != ProcessState.BLOCKED:
            if self.block_registry.is_blocked(thread.tid):
                target_state = (
                    ProcessState.TERMINATED
                    if norm_state == ProcessState.TERMINATED
                    else ProcessState.READY
                )
                self.block_registry.record_unblock(
                    thread.tid,
                    timestamp_ms=now_ms,
                    next_state=target_state,
                )
            return None

        self.process_manager.transition_thread_state(
            thread,
            ProcessState.READY,
            timestamp_ms=now_ms,
            reason=f"Conclusão de {event.event_type.value}",
        )
        if self.block_registry.is_blocked(thread.tid):
            self.block_registry.record_unblock(
                thread.tid,
                timestamp_ms=now_ms,
                next_state=ProcessState.READY,
            )
        if pending_step is not None:
            pending_step.status = "COMPLETED"
        return thread

    def get_history(
        self,
        pid: Optional[int] = None,
        tid: Optional[int] = None,
    ) -> List[SyscallExecutionRecord]:
        """Return executed syscall records, optionally filtered by pid or tid."""
        records = self._history
        if pid is not None:
            records = [rec for rec in records if rec.pid == pid]
        if tid is not None:
            records = [rec for rec in records if rec.tid == tid]
        return list(records)

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregated statistics of syscalls, blocks, and connected I/O counters."""
        by_type: Dict[str, int] = {}
        successful = 0
        failed = 0
        blocking = 0
        non_blocking = 0

        for rec in self._history:
            key = rec.syscall_type.value
            by_type[key] = by_type.get(key, 0) + 1
            if rec.success:
                successful += 1
            else:
                failed += 1
            if rec.blocked:
                blocking += 1
            else:
                non_blocking += 1

        return {
            "total_syscalls": len(self._history),
            "successful_syscalls": successful,
            "failed_syscalls": failed,
            "blocking_syscalls": blocking,
            "non_blocking_syscalls": non_blocking,
            "by_type": by_type,
            "active_blocks_count": len(self.block_registry.get_active_blocks()),
            "total_blocks_recorded": len(self.block_registry.get_history()),
            "random_events_generated": sum(self._random_event_counts.values()),
            "io_manager_reads": self.io_manager.total_reads if self.io_manager is not None else 0,
            "io_manager_writes": self.io_manager.total_writes if self.io_manager is not None else 0,
            "io_manager_seek_tracks": (
                self.io_manager.total_seek_tracks if self.io_manager is not None else 0
            ),
        }

    def reset(self) -> None:
        """Clear dispatcher history, RNG caches, and block registry state."""
        self._history.clear()
        self._next_seq = 1
        self._thread_rngs.clear()
        self._evaluated_profile_cpus.clear()
        self._random_event_counts.clear()
        self._pending_steps_by_event_seq.clear()
        self.block_registry.clear()
