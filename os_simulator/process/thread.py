"""Simulated thread and workload step models (atomic CPU scheduling unit)."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from os_simulator.core.types import BlockReason, IOProfileType, ProcessState, SyscallType


@dataclass
class WorkloadStep:
    """Scheduled system call or memory operation triggered by thread CPU time consumed."""

    trigger_cpu_ms: int
    syscall_type: SyscallType
    duration_ms: int = 0
    block_id: Optional[int] = None
    path: Optional[str] = None
    data: Optional[Union[bytes, str]] = None
    mutex_name: Optional[str] = None
    logical_page: Optional[int] = None
    is_write: bool = False
    executed: bool = False
    status: str = "PENDING"
    result: Optional[Any] = None

    def __post_init__(self) -> None:
        if isinstance(self.trigger_cpu_ms, bool) or not isinstance(self.trigger_cpu_ms, int) or self.trigger_cpu_ms < 0:
            raise ValueError(f"trigger_cpu_ms deve ser inteiro >= 0 (recebido: {self.trigger_cpu_ms!r}).")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            raise ValueError(f"duration_ms deve ser inteiro >= 0 (recebido: {self.duration_ms!r}).")
        if not isinstance(self.syscall_type, SyscallType):
            self.syscall_type = SyscallType.from_string(str(self.syscall_type))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize workload step to dictionary."""
        return {
            "trigger_cpu_ms": self.trigger_cpu_ms,
            "syscall_type": self.syscall_type.value,
            "duration_ms": self.duration_ms,
            "block_id": self.block_id,
            "path": self.path,
            "mutex_name": self.mutex_name,
            "logical_page": self.logical_page,
            "is_write": self.is_write,
            "executed": self.executed,
            "status": self.status,
            "result": self.result,
        }


@dataclass
class SimulatedThread:
    """Simulated execution thread belonging to a parent Process (PCB)."""

    tid: int
    pid: int
    name: str
    state: ProcessState = ProcessState.READY
    priority: int = 3
    cpu_burst_ms: int = 0
    cpu_consumed_ms: int = 0
    quantum_used_ms: int = 0
    arrival_time_ms: int = 0
    start_time_ms: Optional[int] = None
    finish_time_ms: Optional[int] = None
    ready_since_ms: Optional[int] = None
    total_wait_ms: int = 0
    total_blocked_ms: int = 0
    blocked_since_ms: Optional[int] = None
    block_reason: BlockReason = BlockReason.NONE
    blocked_on: Optional[str] = None
    held_mutexes: List[str] = field(default_factory=list)
    workload_steps: List[WorkloadStep] = field(default_factory=list)
    memory_access_pattern: List[Tuple[int, bool]] = field(default_factory=list)
    io_profile: Any = IOProfileType.NONE

    def __post_init__(self) -> None:
        if not self.name or not str(self.name).strip():
            raise ValueError("Nome da thread não pode ser vazio.")
        self.name = str(self.name).strip()

        for field_name, val, min_val in (
            ("tid", self.tid, 0),
            ("pid", self.pid, 0),
            ("priority", self.priority, 1),
            ("cpu_burst_ms", self.cpu_burst_ms, 0),
            ("cpu_consumed_ms", self.cpu_consumed_ms, 0),
            ("quantum_used_ms", self.quantum_used_ms, 0),
            ("arrival_time_ms", self.arrival_time_ms, 0),
            ("total_wait_ms", self.total_wait_ms, 0),
            ("total_blocked_ms", self.total_blocked_ms, 0),
        ):
            if isinstance(val, bool) or not isinstance(val, int) or val < min_val:
                raise ValueError(
                    f"{field_name} deve ser inteiro >= {min_val} (recebido: {val!r})."
                )

        if not isinstance(self.state, ProcessState):
            self.state = ProcessState.from_string(str(self.state))
        self.state = ProcessState.normalize(self.state)

        if not isinstance(self.block_reason, BlockReason):
            self.block_reason = BlockReason(str(self.block_reason).strip().upper())

        if self.state == ProcessState.READY and self.ready_since_ms is None:
            self.ready_since_ms = self.arrival_time_ms

    @property
    def remaining_burst_ms(self) -> int:
        """Remaining CPU burst time in milliseconds."""
        return max(0, self.cpu_burst_ms - self.cpu_consumed_ms)

    @property
    def is_active(self) -> bool:
        """Return True if thread has not terminated."""
        return self.state != ProcessState.TERMINATED

    def add_workload_step(self, step: WorkloadStep) -> None:
        """Register a scheduled workload step for this thread."""
        self.workload_steps.append(step)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize thread attributes to dictionary."""
        if hasattr(self.io_profile, "to_dict"):
            io_profile_val = self.io_profile.to_dict()
        elif isinstance(self.io_profile, Enum):
            io_profile_val = self.io_profile.value
        else:
            io_profile_val = str(self.io_profile)

        return {
            "tid": self.tid,
            "pid": self.pid,
            "name": self.name,
            "state": self.state.value,
            "priority": self.priority,
            "cpu_burst_ms": self.cpu_burst_ms,
            "cpu_consumed_ms": self.cpu_consumed_ms,
            "remaining_burst_ms": self.remaining_burst_ms,
            "quantum_used_ms": self.quantum_used_ms,
            "arrival_time_ms": self.arrival_time_ms,
            "start_time_ms": self.start_time_ms,
            "finish_time_ms": self.finish_time_ms,
            "ready_since_ms": self.ready_since_ms,
            "total_wait_ms": self.total_wait_ms,
            "total_blocked_ms": self.total_blocked_ms,
            "blocked_since_ms": self.blocked_since_ms,
            "block_reason": self.block_reason.value,
            "blocked_on": self.blocked_on,
            "held_mutexes": list(self.held_mutexes),
            "workload_steps": [step.to_dict() for step in self.workload_steps],
            "memory_access_pattern": list(self.memory_access_pattern),
            "io_profile": io_profile_val,
        }

    def __repr__(self) -> str:
        return (
            f"<SimulatedThread tid={self.tid} pid={self.pid} name='{self.name}' "
            f"state={self.state.value} prio={self.priority} "
            f"cpu={self.cpu_consumed_ms}/{self.cpu_burst_ms}ms>"
        )
