"""Discrete-event simulation ExecutionEngine for Stage 5 processes, threads, I/O, sync, and memory."""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union

from os_simulator.core.clock import LogicalClock
from os_simulator.core.context import ExecutionContext
from os_simulator.core.events import EventManager, SimulationEvent
from os_simulator.core.exceptions import (
    DeadlockDetectedException,
    InvalidAddressException,
    InvalidProcessStateException,
    InvalidStateTransitionException,
    PermissionDeniedException,
    SimulationStallException,
)
from os_simulator.core.ports import AuthorizationPort, BlockDevicePort
from os_simulator.core.types import (
    AuditEventType,
    IOProfileType,
    ProcessState,
    ProcessType,
    SimulationEventType,
    SyscallType,
)
from os_simulator.process.manager import ProcessManager
from os_simulator.process.metrics import MetricsCollector, SimulationMetrics, TimelineEntry, GanttSlice
from os_simulator.process.pcb import Process
from os_simulator.process.scheduler import PriorityRoundRobinScheduler
from os_simulator.process.sync import SynchronizationManager
from os_simulator.process.syscalls import SyscallDispatcher
from os_simulator.process.thread import SimulatedThread, WorkloadStep

if TYPE_CHECKING:
    from os_simulator.filesystem.service import FileSystemService
    from os_simulator.io.service import IOManager
    from os_simulator.memory.service import MemoryManager
    from os_simulator.security.audit import AuditLog


def _validate_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} deve ser um inteiro >= 0 (recebido: {value!r}).")
    return value


class ExecutionEngine:
    """Discrete-event CPU, syscall, synchronization, and virtual-memory execution engine."""

    _MAX_ZERO_TIME_ITERATIONS = 10_000

    def __init__(
        self,
        process_manager: Optional[ProcessManager] = None,
        memory_manager: Optional["MemoryManager"] = None,
        clock: Optional[LogicalClock] = None,
        event_manager: Optional[EventManager] = None,
        cpu_scheduler: Optional[PriorityRoundRobinScheduler] = None,
        sync_manager: Optional[SynchronizationManager] = None,
        syscall_dispatcher: Optional[SyscallDispatcher] = None,
        metrics_collector: Optional[MetricsCollector] = None,
        io_manager: Optional["IOManager"] = None,
        block_device: Optional[BlockDevicePort] = None,
        fs_service: Optional["FileSystemService"] = None,
        auth_port: Optional[AuthorizationPort] = None,
        auth_context: Optional[ExecutionContext] = None,
        audit_log: Optional["AuditLog"] = None,
        quantum_ms: int = 4,
        default_seed: int = 42,
        context_provider: Optional[Callable[[], ExecutionContext]] = None,
        storage_provider: Optional[Callable[[], Tuple[Optional["IOManager"], Optional[BlockDevicePort], Optional["FileSystemService"]]]] = None,
    ) -> None:
        if isinstance(default_seed, bool) or not isinstance(default_seed, int):
            raise ValueError(f"default_seed deve ser um inteiro válido (recebido: {default_seed!r}).")

        self.process_manager: ProcessManager = (
            process_manager if process_manager is not None else ProcessManager()
        )
        if memory_manager is None:
            from os_simulator.memory.service import MemoryManager as _MemoryManager
            self.memory_manager: "MemoryManager" = _MemoryManager(
                process_lookup=self.process_manager.get_process
            )
        else:
            self.memory_manager = memory_manager
        self.memory_manager.set_process_lookup(self.process_manager.get_process)

        self.clock: LogicalClock = clock if clock is not None else LogicalClock()
        self.event_manager: EventManager = (
            event_manager if event_manager is not None else EventManager(clock=self.clock)
        )
        self.cpu_scheduler: PriorityRoundRobinScheduler = (
            cpu_scheduler
            if cpu_scheduler is not None
            else PriorityRoundRobinScheduler(self.process_manager, quantum_ms=quantum_ms)
        )
        self.sync_manager: SynchronizationManager = (
            sync_manager
            if sync_manager is not None
            else SynchronizationManager(self.process_manager)
        )
        self.metrics_collector: MetricsCollector = (
            metrics_collector if metrics_collector is not None else MetricsCollector()
        )

        self.io_manager = io_manager
        self.block_device = block_device
        self.fs_service = fs_service
        self.auth_port = auth_port
        self.auth_context = auth_context
        self.audit_log = audit_log
        self.default_seed: int = default_seed
        self._context_provider = context_provider
        self._last_provided_context = auth_context
        self._storage_provider = storage_provider
        self._last_provided_storage = (io_manager, block_device, fs_service)

        self.syscall_dispatcher: SyscallDispatcher = (
            syscall_dispatcher
            if syscall_dispatcher is not None
            else SyscallDispatcher(
                process_manager=self.process_manager,
                event_manager=self.event_manager,
                io_manager=self.io_manager,
                block_device=self.block_device,
                fs_service=self.fs_service,
                auth_context=self.auth_context,
                default_seed=self.default_seed,
                audit_log=self.audit_log,
            )
        )

        self._memory_access_cursors: Dict[int, int] = {}
        self._peak_frames_used: int = 0

    def _sync_dynamic_providers(self) -> None:
        """Keep auth_context and storage backend references synced if wired to SimulationKernel."""
        if self._context_provider is not None:
            current_ctx = self._context_provider()
            if current_ctx is not self._last_provided_context:
                self._last_provided_context = current_ctx
                self.auth_context = current_ctx
                self.syscall_dispatcher.set_auth_context(current_ctx)

        if self._storage_provider is not None:
            current_storage = self._storage_provider()
            if current_storage != self._last_provided_storage:
                self._last_provided_storage = current_storage
                io_mgr, blk_dev, fs_svc = current_storage
                self.io_manager = io_mgr
                self.block_device = blk_dev
                self.fs_service = fs_svc
                self.syscall_dispatcher.io_manager = io_mgr
                self.syscall_dispatcher.block_device = blk_dev
                self.syscall_dispatcher.fs_service = fs_svc

    def set_quantum(self, quantum_ms: int) -> None:
        """Configure CPU Round-Robin quantum in milliseconds."""
        self.cpu_scheduler.set_quantum(quantum_ms)

    def set_default_seed(self, seed: int) -> None:
        """Configure default deterministic seed for random I/O profiles."""
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError(f"seed deve ser um inteiro válido (recebido: {seed!r}).")
        self.default_seed = seed
        self.syscall_dispatcher.set_default_seed(seed)

    @staticmethod
    def _normalize_process_type(process_type: Union[ProcessType, str]) -> ProcessType:
        if isinstance(process_type, ProcessType):
            return process_type
        return ProcessType(str(process_type).strip().upper())

    def _record_audit(
        self,
        event_type: AuditEventType,
        action: str,
        result: str = "SUCCESS",
        path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.audit_log is None:
            return
        self._sync_dynamic_providers()
        username = self.auth_context.username if self.auth_context is not None else "kernel"
        self.audit_log.log_event(
            event_type=event_type,
            username=username,
            path=path,
            action=action,
            result=result,
            details=details or {},
        )

    def _enqueue_ready_thread(
        self,
        thread: SimulatedThread,
        timestamp_ms: int,
    ) -> Optional[SimulatedThread]:
        """Enqueue a READY thread into the CPU scheduler and log any priority preemption."""
        preempted = self.cpu_scheduler.enqueue_ready(thread, timestamp_ms=timestamp_ms)
        if preempted is not None:
            preempted_proc = self.process_manager.processes.get(preempted.pid)
            self.metrics_collector.record_event(
                timestamp_ms=timestamp_ms,
                event_type="PREEMPTION",
                pid=preempted.pid,
                tid=preempted.tid,
                process_name=preempted_proc.name if preempted_proc else "",
                thread_name=preempted.name,
                state=preempted.state.value,
                priority=preempted.priority,
                cpu_consumed_ms=preempted.cpu_consumed_ms,
                quantum_used_ms=preempted.quantum_used_ms,
                details=(
                    f"Preempção: TID {thread.tid} ({thread.name}, prio {thread.priority}) "
                    f"preemptou TID {preempted.tid} ({preempted.name}, prio {preempted.priority})."
                ),
            )
        return preempted

    def _admit_and_enqueue_now(
        self,
        proc: Process,
        timestamp_ms: int,
        reason: str = "Admissão do processo na fila de prontos",
    ) -> None:
        """Transition a NEW process to READY and enqueue its READY threads."""
        if ProcessState.normalize(proc.state) == ProcessState.NEW:
            self.process_manager.admit_process(proc, timestamp_ms=timestamp_ms, reason=reason)
            self.metrics_collector.record_event(
                timestamp_ms=timestamp_ms,
                event_type="PROCESS_ADMITTED",
                pid=proc.pid,
                process_name=proc.name,
                state=proc.state.value,
                priority=proc.priority,
                details=reason,
            )

        for thread in proc.threads.values():
            norm_state = ProcessState.normalize(thread.state)
            if norm_state == ProcessState.READY:
                self._enqueue_ready_thread(thread, timestamp_ms=timestamp_ms)

    def submit_process(
        self,
        name: str,
        size_bytes: int,
        process_type: Union[ProcessType, str] = ProcessType.NORMAL,
        owner: str = "root",
        priority: int = 3,
        cpu_burst_ms: int = 0,
        arrival_time_ms: Optional[int] = None,
        io_profile: Any = IOProfileType.NONE,
        workload_steps: Optional[List[WorkloadStep]] = None,
        memory_access_pattern: Optional[List[Tuple[int, bool]]] = None,
        admit_immediately: bool = True,
    ) -> Process:
        """Create a process, allocate memory with rollback on failure, and admit or schedule arrival."""
        norm_type = self._normalize_process_type(process_type)
        now_ms = self.clock.now_ms
        eff_arrival = now_ms if arrival_time_ms is None else arrival_time_ms
        _validate_non_negative_int(eff_arrival, "arrival_time_ms")

        clean_name = "" if name is None else str(name).strip()
        prev_pid_for_name = self.process_manager.name_to_pid.get(clean_name) if clean_name else None
        should_have_main = (cpu_burst_ms > 0) or bool(workload_steps)

        proc = self.process_manager.create_process(
            name=name,
            size_bytes=size_bytes,
            process_type=norm_type,
            owner=owner,
            priority=priority,
            cpu_burst_ms=cpu_burst_ms,
            arrival_time_ms=eff_arrival,
            initial_state=ProcessState.NEW,
            io_profile=io_profile,
            memory_access_pattern=memory_access_pattern,
            create_default_thread=should_have_main,
        )

        try:
            if workload_steps and should_have_main:
                main_thread = self.process_manager.get_thread_by_name(proc, "main")
                for step in workload_steps:
                    self.syscall_dispatcher.validate_workload_step(main_thread, step)
                    main_thread.add_workload_step(step)

            self.memory_manager.allocate_process_memory(proc)
        except Exception:
            for tid in list(proc.threads.keys()):
                self.process_manager.threads.pop(tid, None)
            proc.terminate()
            self.process_manager.processes.pop(proc.pid, None)
            if clean_name:
                if prev_pid_for_name is not None:
                    self.process_manager.name_to_pid[clean_name] = prev_pid_for_name
                else:
                    self.process_manager.name_to_pid.pop(clean_name, None)
            raise

        self.metrics_collector.record_event(
            timestamp_ms=now_ms,
            event_type="PROCESS_CREATED",
            pid=proc.pid,
            process_name=proc.name,
            state=proc.state.value,
            priority=proc.priority,
            details=(
                f"Processo '{proc.name}' criado (PID {proc.pid}, tipo={proc.process_type.value}, "
                f"burst={proc.cpu_burst_ms}ms, arrival={eff_arrival}ms)."
            ),
        )
        self._record_audit(
            AuditEventType.PROCESS_LIFECYCLE,
            action="SUBMIT_PROCESS",
            details={
                "pid": proc.pid,
                "name": proc.name,
                "type": proc.process_type.value,
                "priority": proc.priority,
                "cpu_burst_ms": proc.cpu_burst_ms,
                "arrival_time_ms": eff_arrival,
            },
        )

        if not admit_immediately:
            return proc

        if eff_arrival > now_ms:
            self.event_manager.schedule_at(
                timestamp_ms=eff_arrival,
                event_type=SimulationEventType.PROCESS_ARRIVAL,
                pid=proc.pid,
                payload={"name": proc.name},
            )
            return proc

        self._admit_and_enqueue_now(proc, timestamp_ms=now_ms)
        return proc

    def admit_process(self, identifier: Union[Process, str, int]) -> Process:
        """Admit a NEW process into READY immediately or schedule future arrival if arrival_time_ms > now_ms."""
        proc = self.process_manager._resolve_process(identifier)
        now_ms = self.clock.now_ms

        if ProcessState.normalize(proc.state) != ProcessState.NEW:
            # Delegate to ProcessManager to raise consistent InvalidStateTransitionException
            self.process_manager.admit_process(proc, timestamp_ms=now_ms)
            return proc

        if proc.cpu_burst_ms > 0 and not proc.threads:
            self.process_manager.ensure_main_thread(proc)

        if proc.arrival_time_ms > now_ms:
            already_scheduled = any(
                ev.event_type == SimulationEventType.PROCESS_ARRIVAL and ev.pid == proc.pid
                for ev in self.event_manager.pending_events()
            )
            if not already_scheduled:
                self.event_manager.schedule_at(
                    timestamp_ms=proc.arrival_time_ms,
                    event_type=SimulationEventType.PROCESS_ARRIVAL,
                    pid=proc.pid,
                    payload={"name": proc.name},
                )
            return proc

        self._admit_and_enqueue_now(proc, timestamp_ms=now_ms)
        return proc

    def create_thread(
        self,
        process_identifier: Union[Process, str, int],
        name: str,
        priority: Optional[int] = None,
        cpu_burst_ms: int = 0,
        arrival_time_ms: Optional[int] = None,
        io_profile: Any = IOProfileType.NONE,
        workload_steps: Optional[List[WorkloadStep]] = None,
        memory_access_pattern: Optional[List[Tuple[int, bool]]] = None,
    ) -> SimulatedThread:
        """Create a schedulable thread on an existing process and enqueue or schedule arrival."""
        proc = self.process_manager._resolve_process(process_identifier)
        now_ms = self.clock.now_ms
        eff_arrival = now_ms if arrival_time_ms is None else arrival_time_ms
        _validate_non_negative_int(eff_arrival, "arrival_time_ms")

        is_future = eff_arrival > now_ms
        target_state = ProcessState.NEW if is_future else ProcessState.READY

        if workload_steps:
            # Validate steps before mutating ProcessManager state
            eff_prio = proc.priority if priority is None else priority
            probe = SimulatedThread(
                tid=0,
                pid=proc.pid,
                name="probe",
                state=target_state,
                priority=eff_prio,
                cpu_burst_ms=cpu_burst_ms,
                arrival_time_ms=eff_arrival,
            )
            for step in workload_steps:
                self.syscall_dispatcher.validate_workload_step(probe, step)

        thread = self.process_manager.create_thread(
            process_identifier=proc,
            name=name,
            priority=priority,
            cpu_burst_ms=cpu_burst_ms,
            arrival_time_ms=eff_arrival,
            initial_state=target_state,
            io_profile=io_profile,
            memory_access_pattern=memory_access_pattern,
            workload_steps=workload_steps,
            sync_parent=True,
        )

        self.metrics_collector.record_event(
            timestamp_ms=now_ms,
            event_type="THREAD_CREATED",
            pid=proc.pid,
            tid=thread.tid,
            process_name=proc.name,
            thread_name=thread.name,
            state=thread.state.value,
            priority=thread.priority,
            details=f"Thread '{thread.name}' criada em '{proc.name}' (burst={thread.cpu_burst_ms}ms, arrival={eff_arrival}ms).",
        )

        if is_future:
            self.event_manager.schedule_at(
                timestamp_ms=eff_arrival,
                event_type=SimulationEventType.THREAD_ARRIVAL,
                pid=proc.pid,
                tid=thread.tid,
                payload={"process_name": proc.name, "thread_name": thread.name},
            )
        else:
            self._enqueue_ready_thread(thread, timestamp_ms=now_ms)

        return thread

    def enqueue_process(self, identifier: Union[Process, str, int]) -> List[SimulatedThread]:
        """Enqueue READY threads of an existing process into the CPU scheduler."""
        proc = self.process_manager._resolve_process(identifier)
        if proc.pid == 0 or proc.name == "Nucleo_Base":
            raise PermissionDeniedException(
                "Nucleo_Base (PID 0) não pode ser enfileirado no escalonador de CPU."
            )

        norm_proc_state = ProcessState.normalize(proc.state)
        if norm_proc_state == ProcessState.TERMINATED:
            raise InvalidProcessStateException(
                f"Processo '{proc.name}' (PID {proc.pid}) já está encerrado (TERMINATED)."
            )
        if norm_proc_state == ProcessState.NEW:
            raise InvalidProcessStateException(
                f"Processo '{proc.name}' (PID {proc.pid}) está em estado NEW; admita-o antes de enfileirar."
            )

        if not proc.threads and proc.cpu_burst_ms > 0:
            self.process_manager.ensure_main_thread(proc)

        now_ms = self.clock.now_ms
        enqueued: List[SimulatedThread] = []
        for thread in proc.threads.values():
            if ProcessState.normalize(thread.state) == ProcessState.READY:
                self._enqueue_ready_thread(thread, timestamp_ms=now_ms)
                enqueued.append(thread)

        return enqueued

    def _resolve_target_thread(
        self,
        proc: Process,
        thread_identifier: Optional[Union[SimulatedThread, int, str]] = None,
    ) -> SimulatedThread:
        if thread_identifier is not None:
            if isinstance(thread_identifier, SimulatedThread):
                if thread_identifier.pid != proc.pid:
                    raise ValueError(
                        f"Thread TID {thread_identifier.tid} não pertence ao processo '{proc.name}' (PID {proc.pid})."
                    )
                return thread_identifier
            return self.process_manager.get_thread(thread_identifier, process_identifier=proc)
        return self.process_manager.ensure_main_thread(proc)

    def _build_workload_step(
        self,
        syscall_type: Union[SyscallType, str],
        trigger_cpu_ms: int,
        duration_ms: int = 0,
        block_id: Optional[int] = None,
        path: Optional[str] = None,
        data: Optional[Union[bytes, str]] = None,
        mutex_name: Optional[str] = None,
        logical_page: Optional[int] = None,
        is_write: bool = False,
    ) -> WorkloadStep:
        stype = (
            syscall_type
            if isinstance(syscall_type, SyscallType)
            else SyscallType.from_string(str(syscall_type))
        )
        if stype in (SyscallType.MUTEX_LOCK, SyscallType.MUTEX_UNLOCK):
            if not mutex_name or not str(mutex_name).strip():
                raise ValueError(f"Syscall {stype.value} requer o parâmetro mutex_name.")
            mutex_name = str(mutex_name).strip()

        eff_write = True if stype == SyscallType.MEMORY_WRITE else bool(is_write)
        return WorkloadStep(
            trigger_cpu_ms=trigger_cpu_ms,
            syscall_type=stype,
            duration_ms=duration_ms,
            block_id=block_id,
            path=path,
            data=data,
            mutex_name=mutex_name,
            logical_page=logical_page,
            is_write=eff_write,
        )

    def schedule_syscall(
        self,
        process_identifier: Union[Process, str, int],
        syscall_type: Union[SyscallType, str],
        trigger_cpu_ms: int = 0,
        duration_ms: int = 0,
        thread_identifier: Optional[Union[SimulatedThread, int, str]] = None,
        block_id: Optional[int] = None,
        path: Optional[str] = None,
        data: Optional[Union[bytes, str]] = None,
        mutex_name: Optional[str] = None,
        logical_page: Optional[int] = None,
        is_write: bool = False,
    ) -> WorkloadStep:
        """Schedule a WorkloadStep on a process/thread triggered by thread CPU consumption."""
        proc = self.process_manager._resolve_process(process_identifier)
        if proc.pid == 0 or proc.name == "Nucleo_Base":
            raise PermissionDeniedException("Nucleo_Base (PID 0) não aceita syscalls de usuário.")
        if ProcessState.normalize(proc.state) == ProcessState.TERMINATED:
            raise InvalidProcessStateException(
                f"Não é possível agendar syscall em processo encerrado '{proc.name}' (PID {proc.pid})."
            )

        thread = self._resolve_target_thread(proc, thread_identifier)
        if ProcessState.normalize(thread.state) == ProcessState.TERMINATED:
            raise InvalidProcessStateException(
                f"Thread '{thread.name}' (TID {thread.tid}) já está encerrada."
            )

        step = self._build_workload_step(
            syscall_type=syscall_type,
            trigger_cpu_ms=trigger_cpu_ms,
            duration_ms=duration_ms,
            block_id=block_id,
            path=path,
            data=data,
            mutex_name=mutex_name,
            logical_page=logical_page,
            is_write=is_write,
        )
        self.syscall_dispatcher.validate_workload_step(thread, step)
        thread.add_workload_step(step)

        self.metrics_collector.record_event(
            timestamp_ms=self.clock.now_ms,
            event_type="SYSCALL_SCHEDULED",
            pid=proc.pid,
            tid=thread.tid,
            process_name=proc.name,
            thread_name=thread.name,
            state=thread.state.value,
            priority=thread.priority,
            cpu_consumed_ms=thread.cpu_consumed_ms,
            quantum_used_ms=thread.quantum_used_ms,
            details=f"Syscall {step.syscall_type.value} agendada para cpu_consumed_ms={step.trigger_cpu_ms}ms.",
        )
        return step

    def execute_syscall_now(
        self,
        process_identifier: Union[Process, str, int],
        syscall_type: Union[SyscallType, str],
        duration_ms: int = 0,
        thread_identifier: Optional[Union[SimulatedThread, int, str]] = None,
        block_id: Optional[int] = None,
        path: Optional[str] = None,
        data: Optional[Union[bytes, str]] = None,
        mutex_name: Optional[str] = None,
        logical_page: Optional[int] = None,
        is_write: bool = False,
    ) -> Dict[str, Any]:
        """Execute a syscall immediately at clock.now_ms on a RUNNING or READY thread."""
        proc = self.process_manager._resolve_process(process_identifier)
        if proc.pid == 0 or proc.name == "Nucleo_Base":
            raise PermissionDeniedException("Nucleo_Base (PID 0) não executa syscalls de usuário.")
        if ProcessState.normalize(proc.state) == ProcessState.TERMINATED:
            raise InvalidProcessStateException(
                f"Processo '{proc.name}' (PID {proc.pid}) está encerrado (TERMINATED)."
            )

        thread = self._resolve_target_thread(proc, thread_identifier)
        norm_state = ProcessState.normalize(thread.state)
        if norm_state in (ProcessState.NEW, ProcessState.BLOCKED, ProcessState.TERMINATED):
            raise InvalidStateTransitionException(
                f"Thread '{thread.name}' (TID {thread.tid}) no estado '{norm_state.value}' "
                f"não pode executar syscall imediata.",
                from_state=norm_state.value,
                to_state=ProcessState.RUNNING.value,
                entity_id=f"TID:{thread.tid}",
            )

        step = self._build_workload_step(
            syscall_type=syscall_type,
            trigger_cpu_ms=thread.cpu_consumed_ms,
            duration_ms=duration_ms,
            block_id=block_id,
            path=path,
            data=data,
            mutex_name=mutex_name,
            logical_page=logical_page,
            is_write=is_write,
        )
        self.syscall_dispatcher.validate_workload_step(thread, step)

        now_ms = self.clock.now_ms
        if norm_state == ProcessState.READY:
            current_running = self.cpu_scheduler.get_running_thread()
            if current_running is not None and current_running.tid != thread.tid:
                preempted = self.cpu_scheduler.preempt_current(
                    timestamp_ms=now_ms,
                    reason=f"Preempção para syscall imediata em TID {thread.tid}",
                )
                if preempted is not None:
                    p_proc = self.process_manager.processes.get(preempted.pid)
                    self.metrics_collector.record_event(
                        timestamp_ms=now_ms,
                        event_type="PREEMPTION",
                        pid=preempted.pid,
                        tid=preempted.tid,
                        process_name=p_proc.name if p_proc else "",
                        thread_name=preempted.name,
                        state=preempted.state.value,
                        priority=preempted.priority,
                        cpu_consumed_ms=preempted.cpu_consumed_ms,
                        quantum_used_ms=preempted.quantum_used_ms,
                        details="Preempção para despacho de syscall imediata.",
                    )

            self.cpu_scheduler.remove(thread.tid)
            self.process_manager.transition_thread_state(
                thread,
                ProcessState.RUNNING,
                timestamp_ms=now_ms,
                reason=f"Despacho imediato para syscall {step.syscall_type.value}",
            )
            thread.quantum_used_ms = 0
            self.cpu_scheduler.running_tid = thread.tid
            self.cpu_scheduler.dispatches_total += 1
            if (
                self.cpu_scheduler.last_dispatched_tid is not None
                and self.cpu_scheduler.last_dispatched_tid != thread.tid
            ):
                self.cpu_scheduler.context_switches_total += 1
            self.cpu_scheduler.last_dispatched_tid = thread.tid
            self.metrics_collector.record_event(
                timestamp_ms=now_ms,
                event_type="DISPATCH",
                pid=proc.pid,
                tid=thread.tid,
                process_name=proc.name,
                thread_name=thread.name,
                state=thread.state.value,
                priority=thread.priority,
                cpu_consumed_ms=thread.cpu_consumed_ms,
                quantum_used_ms=thread.quantum_used_ms,
                details=f"Despacho imediato para syscall {step.syscall_type.value}.",
            )

        return self._execute_workload_step(proc, thread, step, now_ms=now_ms)

    def _perform_memory_access(
        self,
        proc: Process,
        thread: SimulatedThread,
        logical_page: int,
        is_write: bool,
        now_ms: int,
    ) -> Dict[str, Any]:
        """Execute a paged memory access through Stage 4 MemoryManager and record HIT/PAGE_FAULT."""
        if proc.page_table is None:
            raise InvalidAddressException(
                f"Processo '{proc.name}' (PID {proc.pid}) não possui memória paginada."
            )

        inst = (
            f"WRITE_DATA Página {logical_page}"
            if is_write
            else f"LOAD_DATA Página {logical_page}"
        )
        res = self.memory_manager.execute_instruction(
            proc,
            inst,
            current_time=float(now_ms),
        )
        hit = not bool(res["page_fault"])
        frame_id = int(res["frame_id"])
        fault_details = res.get("fault_details")
        if fault_details is not None:
            page_origin = fault_details.get("page_origin")
        else:
            page_origin = proc.page_table.get_entry(logical_page).page_origin.value

        self.metrics_collector.record_memory_access(
            timestamp_ms=now_ms,
            pid=proc.pid,
            tid=thread.tid,
            logical_page=logical_page,
            frame_id=frame_id,
            hit=hit,
            page_origin=page_origin,
            algorithm=self.memory_manager.algorithm.value,
            update_counters=True,
        )

        occ = self.memory_manager.physical_memory.get_occupied_count()
        if occ > self._peak_frames_used:
            self._peak_frames_used = occ

        victim_desc = ""
        if fault_details and fault_details.get("victim"):
            v = fault_details["victim"]
            victim_desc = (
                f" | vítima PID:{v['pid']} pág:{v['logical_page']} ({v['action']})"
            )

        self.metrics_collector.record_event(
            timestamp_ms=now_ms,
            event_type="MEMORY_HIT" if hit else "PAGE_FAULT",
            pid=proc.pid,
            tid=thread.tid,
            process_name=proc.name,
            thread_name=thread.name,
            state=thread.state.value,
            priority=thread.priority,
            cpu_consumed_ms=thread.cpu_consumed_ms,
            quantum_used_ms=thread.quantum_used_ms,
            details=(
                f"{'HIT' if hit else 'PAGE_FAULT'} {'WRITE' if is_write else 'LOAD'} "
                f"página={logical_page} -> moldura={frame_id} ({page_origin}){victim_desc}"
            ),
        )
        return res

    def _access_process_memory_tick(
        self,
        proc: Process,
        thread: SimulatedThread,
        now_ms: int,
    ) -> Optional[Dict[str, Any]]:
        """Perform automatic paged memory access during a NORMAL process's CPU tick."""
        if proc.process_type != ProcessType.NORMAL or proc.page_table is None:
            return None
        total_pages = proc.page_table.total_pages
        if total_pages <= 0:
            return None

        pattern = thread.memory_access_pattern or proc.memory_access_pattern
        if pattern:
            idx = self._memory_access_cursors.get(thread.tid, 0)
            spec = pattern[idx % len(pattern)]
            self._memory_access_cursors[thread.tid] = idx + 1
            if isinstance(spec, (tuple, list)):
                logical_page = int(spec[0])
                is_write = bool(spec[1])
            else:
                logical_page = int(spec)
                is_write = False
        else:
            logical_page = thread.cpu_consumed_ms % total_pages
            is_write = False

        return self._perform_memory_access(
            proc=proc,
            thread=thread,
            logical_page=logical_page,
            is_write=is_write,
            now_ms=now_ms,
        )

    def _release_thread_mutexes_and_wake(
        self,
        thread: SimulatedThread,
        now_ms: int,
    ) -> List[SimulatedThread]:
        """Release all mutexes held by a thread and re-enqueue any woken FIFO waiters."""
        woken_threads = self.sync_manager.release_all_for_thread(
            thread.tid,
            timestamp_ms=now_ms,
        )
        for woken in woken_threads:
            woken_proc = self.process_manager.processes.get(woken.pid)
            self.metrics_collector.record_event(
                timestamp_ms=now_ms,
                event_type="MUTEX_WAKEUP",
                pid=woken.pid,
                tid=woken.tid,
                process_name=woken_proc.name if woken_proc else "",
                thread_name=woken.name,
                state=woken.state.value,
                priority=woken.priority,
                cpu_consumed_ms=woken.cpu_consumed_ms,
                quantum_used_ms=woken.quantum_used_ms,
                details=f"Mutex transferido para TID {woken.tid} ({woken.name}) após término/liberação.",
            )
            if ProcessState.normalize(woken.state) == ProcessState.READY:
                self._enqueue_ready_thread(woken, timestamp_ms=now_ms)
        return woken_threads

    def _complete_running_thread(
        self,
        thread: SimulatedThread,
        now_ms: int,
        reason: str = "Conclusão do burst de CPU",
    ) -> None:
        """Terminate a finished running thread, release its mutexes, and free process memory if done."""
        proc = self.process_manager.processes.get(thread.pid)
        if ProcessState.normalize(thread.state) != ProcessState.TERMINATED:
            self.process_manager.transition_thread_state(
                thread,
                ProcessState.TERMINATED,
                timestamp_ms=now_ms,
                reason=reason,
                sync_parent=True,
            )
        self.cpu_scheduler.on_current_suspended()

        self.metrics_collector.record_event(
            timestamp_ms=now_ms,
            event_type="THREAD_TERMINATED",
            pid=thread.pid,
            tid=thread.tid,
            process_name=proc.name if proc else "",
            thread_name=thread.name,
            state=thread.state.value,
            priority=thread.priority,
            cpu_consumed_ms=thread.cpu_consumed_ms,
            quantum_used_ms=thread.quantum_used_ms,
            details=reason,
        )

        self._release_thread_mutexes_and_wake(thread, now_ms=now_ms)

        if proc is not None and ProcessState.normalize(proc.state) == ProcessState.TERMINATED:
            self.event_manager.cancel_for_entity(pid=proc.pid)
            self.memory_manager.free_process_memory(proc)
            self.metrics_collector.record_event(
                timestamp_ms=now_ms,
                event_type=SimulationEventType.PROCESS_TERMINATED.value,
                pid=proc.pid,
                process_name=proc.name,
                state=proc.state.value,
                priority=proc.priority,
                cpu_consumed_ms=proc.cpu_consumed_ms,
                details=f"Processo '{proc.name}' (PID {proc.pid}) concluído e memória liberada.",
            )
            self._record_audit(
                AuditEventType.PROCESS_LIFECYCLE,
                action="PROCESS_COMPLETED",
                details={"pid": proc.pid, "name": proc.name, "finish_time_ms": proc.finish_time_ms},
            )

    def _execute_workload_step(
        self,
        proc: Process,
        thread: SimulatedThread,
        step: WorkloadStep,
        now_ms: int,
    ) -> Dict[str, Any]:
        """Execute a single due WorkloadStep on a currently RUNNING thread."""
        self._sync_dynamic_providers()
        stype = step.syscall_type

        if stype in (
            SyscallType.IO_READ,
            SyscallType.IO_WRITE,
            SyscallType.FS_READ,
            SyscallType.FS_WRITE,
            SyscallType.SLEEP_WAIT,
        ):
            rec = self.syscall_dispatcher.dispatch_syscall(thread, step, now_ms=now_ms)
            self.metrics_collector.increment_counter("syscalls_total", pid=proc.pid, tid=thread.tid)
            self.metrics_collector.record_event(
                timestamp_ms=now_ms,
                event_type="SYSCALL",
                pid=proc.pid,
                tid=thread.tid,
                process_name=proc.name,
                thread_name=thread.name,
                state=thread.state.value,
                priority=thread.priority,
                cpu_consumed_ms=thread.cpu_consumed_ms,
                quantum_used_ms=thread.quantum_used_ms,
                details=(
                    f"Syscall {stype.value} ({rec.resource_id or '-'})"
                    + (f" -> BLOCKED ({rec.block_reason.value}, {rec.duration_ms}ms)" if rec.blocked else "")
                ),
            )
            if rec.blocked:
                self.cpu_scheduler.on_current_suspended()
                self.metrics_collector.increment_counter("io_blocks_total", pid=proc.pid, tid=thread.tid)
                self.metrics_collector.record_event(
                    timestamp_ms=now_ms,
                    event_type="THREAD_BLOCKED",
                    pid=proc.pid,
                    tid=thread.tid,
                    process_name=proc.name,
                    thread_name=thread.name,
                    state=thread.state.value,
                    priority=thread.priority,
                    cpu_consumed_ms=thread.cpu_consumed_ms,
                    quantum_used_ms=thread.quantum_used_ms,
                    details=f"Bloqueada em {rec.block_reason.value}: {rec.resource_id}",
                )
            return {
                "syscall_type": stype.value,
                "blocked": rec.blocked,
                "record": rec.to_dict(),
                "thread_state": thread.state.value,
                "memory_accessed": False,
            }

        if stype == SyscallType.YIELD:
            rec = self.syscall_dispatcher.dispatch_syscall(thread, step, now_ms=now_ms)
            self.metrics_collector.increment_counter("syscalls_total", pid=proc.pid, tid=thread.tid)
            self.process_manager.transition_thread_state(
                thread,
                ProcessState.READY,
                timestamp_ms=now_ms,
                reason="Syscall YIELD (cessão voluntária de CPU)",
            )
            self.cpu_scheduler.on_current_suspended()
            self._enqueue_ready_thread(thread, timestamp_ms=now_ms)
            self.metrics_collector.record_event(
                timestamp_ms=now_ms,
                event_type="SYSCALL_YIELD",
                pid=proc.pid,
                tid=thread.tid,
                process_name=proc.name,
                thread_name=thread.name,
                state=thread.state.value,
                priority=thread.priority,
                cpu_consumed_ms=thread.cpu_consumed_ms,
                quantum_used_ms=thread.quantum_used_ms,
                details="Thread cedeu a CPU voluntariamente (YIELD).",
            )
            return {
                "syscall_type": stype.value,
                "blocked": False,
                "yielded": True,
                "record": rec.to_dict(),
                "thread_state": thread.state.value,
                "memory_accessed": False,
            }

        if stype == SyscallType.MUTEX_LOCK:
            if not step.mutex_name:
                raise ValueError("Syscall MUTEX_LOCK requer mutex_name.")
            step.executed = True
            self.metrics_collector.increment_counter("syscalls_total", pid=proc.pid, tid=thread.tid)
            try:
                acquired = self.sync_manager.acquire(step.mutex_name, thread, timestamp_ms=now_ms)
            except DeadlockDetectedException as exc:
                step.status = "DEADLOCK"
                if ProcessState.normalize(thread.state) == ProcessState.BLOCKED:
                    self.cpu_scheduler.on_current_suspended()
                    self.metrics_collector.increment_counter(
                        "mutex_blocks_total", pid=proc.pid, tid=thread.tid
                    )
                self.metrics_collector.record_event(
                    timestamp_ms=now_ms,
                    event_type="DEADLOCK_DETECTED",
                    pid=proc.pid,
                    tid=thread.tid,
                    process_name=proc.name,
                    thread_name=thread.name,
                    state=thread.state.value,
                    priority=thread.priority,
                    cpu_consumed_ms=thread.cpu_consumed_ms,
                    quantum_used_ms=thread.quantum_used_ms,
                    details=str(exc),
                )
                self._record_audit(
                    AuditEventType.DEADLOCK_DETECTED,
                    action="MUTEX_DEADLOCK",
                    result="DEADLOCK",
                    details={"mutex": step.mutex_name, "cycle": list(exc.cycle)},
                )
                raise

            if acquired:
                step.status = "COMPLETED"
                self.metrics_collector.record_event(
                    timestamp_ms=now_ms,
                    event_type="MUTEX_ACQUIRED",
                    pid=proc.pid,
                    tid=thread.tid,
                    process_name=proc.name,
                    thread_name=thread.name,
                    state=thread.state.value,
                    priority=thread.priority,
                    cpu_consumed_ms=thread.cpu_consumed_ms,
                    quantum_used_ms=thread.quantum_used_ms,
                    details=f"Mutex '{step.mutex_name}' adquirido.",
                )
                self._record_audit(
                    AuditEventType.MUTEX_EVENT,
                    action="MUTEX_ACQUIRE",
                    details={"mutex": step.mutex_name, "pid": proc.pid, "tid": thread.tid},
                )
            else:
                step.status = "BLOCKED"
                self.cpu_scheduler.on_current_suspended()
                self.metrics_collector.increment_counter("mutex_blocks_total", pid=proc.pid, tid=thread.tid)
                self.metrics_collector.record_event(
                    timestamp_ms=now_ms,
                    event_type="MUTEX_CONTENTION",
                    pid=proc.pid,
                    tid=thread.tid,
                    process_name=proc.name,
                    thread_name=thread.name,
                    state=thread.state.value,
                    priority=thread.priority,
                    cpu_consumed_ms=thread.cpu_consumed_ms,
                    quantum_used_ms=thread.quantum_used_ms,
                    details=f"Thread bloqueada aguardando mutex '{step.mutex_name}'.",
                )
            return {
                "syscall_type": stype.value,
                "blocked": not acquired,
                "acquired": acquired,
                "mutex_name": step.mutex_name,
                "thread_state": thread.state.value,
                "memory_accessed": False,
            }

        if stype == SyscallType.MUTEX_UNLOCK:
            if not step.mutex_name:
                raise ValueError("Syscall MUTEX_UNLOCK requer mutex_name.")
            step.executed = True
            self.metrics_collector.increment_counter("syscalls_total", pid=proc.pid, tid=thread.tid)
            woken = self.sync_manager.release(step.mutex_name, thread, timestamp_ms=now_ms)
            step.status = "COMPLETED"
            self.metrics_collector.record_event(
                timestamp_ms=now_ms,
                event_type="MUTEX_RELEASED",
                pid=proc.pid,
                tid=thread.tid,
                process_name=proc.name,
                thread_name=thread.name,
                state=thread.state.value,
                priority=thread.priority,
                cpu_consumed_ms=thread.cpu_consumed_ms,
                quantum_used_ms=thread.quantum_used_ms,
                details=f"Mutex '{step.mutex_name}' liberado.",
            )
            self._record_audit(
                AuditEventType.MUTEX_EVENT,
                action="MUTEX_RELEASE",
                details={"mutex": step.mutex_name, "pid": proc.pid, "tid": thread.tid},
            )
            if woken is not None:
                woken_proc = self.process_manager.processes.get(woken.pid)
                self.metrics_collector.record_event(
                    timestamp_ms=now_ms,
                    event_type="MUTEX_WAKEUP",
                    pid=woken.pid,
                    tid=woken.tid,
                    process_name=woken_proc.name if woken_proc else "",
                    thread_name=woken.name,
                    state=woken.state.value,
                    priority=woken.priority,
                    cpu_consumed_ms=woken.cpu_consumed_ms,
                    quantum_used_ms=woken.quantum_used_ms,
                    details=f"Handoff de '{step.mutex_name}' para TID {woken.tid} ({woken.name}).",
                )
                if ProcessState.normalize(woken.state) == ProcessState.READY:
                    self._enqueue_ready_thread(woken, timestamp_ms=now_ms)
            return {
                "syscall_type": stype.value,
                "blocked": False,
                "mutex_name": step.mutex_name,
                "woken_tid": woken.tid if woken is not None else None,
                "thread_state": thread.state.value,
                "memory_accessed": False,
            }

        if stype in (SyscallType.MEMORY_LOAD, SyscallType.MEMORY_WRITE):
            step.executed = True
            self.metrics_collector.increment_counter("syscalls_total", pid=proc.pid, tid=thread.tid)
            if step.logical_page is not None:
                target_page = step.logical_page
            elif proc.page_table is not None and proc.page_table.total_pages > 0:
                target_page = thread.cpu_consumed_ms % proc.page_table.total_pages
            else:
                target_page = 0

            mem_res = self._perform_memory_access(
                proc=proc,
                thread=thread,
                logical_page=target_page,
                is_write=(stype == SyscallType.MEMORY_WRITE or step.is_write),
                now_ms=now_ms,
            )
            step.status = "COMPLETED"
            step.result = mem_res
            return {
                "syscall_type": stype.value,
                "blocked": False,
                "memory_result": mem_res,
                "thread_state": thread.state.value,
                "memory_accessed": True,
            }

        if stype == SyscallType.EXIT:
            step.executed = True
            step.status = "COMPLETED"
            self.metrics_collector.increment_counter("syscalls_total", pid=proc.pid, tid=thread.tid)
            self._complete_running_thread(thread, now_ms=now_ms, reason="Syscall EXIT")
            return {
                "syscall_type": stype.value,
                "blocked": False,
                "terminated": True,
                "thread_state": thread.state.value,
                "memory_accessed": False,
            }

        raise ValueError(f"Syscall não suportada: {stype.value}")

    def _process_due_syscalls(
        self,
        proc: Process,
        thread: SimulatedThread,
        now_ms: int,
    ) -> bool:
        """Check and execute due WorkloadSteps/IOProfile syscalls; return True if memory accessed."""
        due_steps = self.syscall_dispatcher.check_due_syscalls(thread, now_ms=now_ms)
        memory_accessed = False
        for step in due_steps:
            if ProcessState.normalize(thread.state) != ProcessState.RUNNING:
                break
            outcome = self._execute_workload_step(proc, thread, step, now_ms=now_ms)
            if outcome.get("memory_accessed"):
                memory_accessed = True
            if ProcessState.normalize(thread.state) != ProcessState.RUNNING:
                break
        return memory_accessed

    def _drain_due_events(
        self,
        now_ms: int,
        target_event: Optional[SimulationEventType] = None,
    ) -> bool:
        """Pop and apply all scheduled discrete events at or before now_ms in priority order."""
        events = self.event_manager.pop_ready_at(now_ms)
        hit_target = False
        for ev in events:
            if target_event is not None and ev.event_type == target_event:
                hit_target = True
            self._handle_single_event(ev, now_ms)
        return hit_target

    def _handle_single_event(self, ev: SimulationEvent, now_ms: int) -> None:
        if ev.cancelled:
            return

        if ev.event_type == SimulationEventType.PROCESS_TERMINATED:
            if ev.pid is not None:
                proc = self.process_manager.processes.get(ev.pid)
                if proc is not None and proc.pid != 0 and ProcessState.normalize(proc.state) != ProcessState.TERMINATED:
                    self.terminate_process(proc.pid)
            return

        if ev.event_type in (SimulationEventType.IO_COMPLETION, SimulationEventType.SLEEP_WAKEUP):
            woken = self.syscall_dispatcher.handle_completion_event(ev, now_ms=now_ms)
            if woken is not None:
                woken_proc = self.process_manager.processes.get(woken.pid)
                self.metrics_collector.record_event(
                    timestamp_ms=now_ms,
                    event_type=ev.event_type.value,
                    pid=woken.pid,
                    tid=woken.tid,
                    process_name=woken_proc.name if woken_proc else "",
                    thread_name=woken.name,
                    state=woken.state.value,
                    priority=woken.priority,
                    cpu_consumed_ms=woken.cpu_consumed_ms,
                    quantum_used_ms=woken.quantum_used_ms,
                    details=f"Desbloqueio por {ev.event_type.value} ({ev.payload.get('resource_id', '-')}).",
                )
                self._enqueue_ready_thread(woken, timestamp_ms=now_ms)
            return

        if ev.event_type == SimulationEventType.MUTEX_WAKEUP:
            if ev.tid is not None:
                thread = self.process_manager.threads.get(ev.tid)
                if thread is not None and ProcessState.normalize(thread.state) != ProcessState.TERMINATED:
                    if ProcessState.normalize(thread.state) == ProcessState.BLOCKED:
                        self.process_manager.transition_thread_state(
                            thread,
                            ProcessState.READY,
                            timestamp_ms=now_ms,
                            reason="Desbloqueio de mutex agendado",
                        )
                    if ProcessState.normalize(thread.state) == ProcessState.READY:
                        t_proc = self.process_manager.processes.get(thread.pid)
                        self.metrics_collector.record_event(
                            timestamp_ms=now_ms,
                            event_type=SimulationEventType.MUTEX_WAKEUP.value,
                            pid=thread.pid,
                            tid=thread.tid,
                            process_name=t_proc.name if t_proc else "",
                            thread_name=thread.name,
                            state=thread.state.value,
                            priority=thread.priority,
                            cpu_consumed_ms=thread.cpu_consumed_ms,
                            quantum_used_ms=thread.quantum_used_ms,
                            details="Thread pronta após liberação de mutex.",
                        )
                        self._enqueue_ready_thread(thread, timestamp_ms=now_ms)
            return

        if ev.event_type == SimulationEventType.PROCESS_ARRIVAL:
            if ev.pid is not None:
                proc = self.process_manager.processes.get(ev.pid)
                if proc is not None and ProcessState.normalize(proc.state) == ProcessState.NEW:
                    self._admit_and_enqueue_now(
                        proc,
                        timestamp_ms=now_ms,
                        reason=f"Chegada programada do processo em t={now_ms}ms",
                    )
            return

        if ev.event_type == SimulationEventType.THREAD_ARRIVAL:
            if ev.tid is not None:
                thread = self.process_manager.threads.get(ev.tid)
                if thread is not None:
                    proc = self.process_manager.processes.get(thread.pid)
                    if proc is not None and ProcessState.normalize(proc.state) != ProcessState.TERMINATED:
                        if ProcessState.normalize(thread.state) == ProcessState.NEW:
                            self.process_manager.transition_thread_state(
                                thread,
                                ProcessState.READY,
                                timestamp_ms=now_ms,
                                reason=f"Chegada programada da thread em t={now_ms}ms",
                                sync_parent=True,
                            )
                            self.metrics_collector.record_event(
                                timestamp_ms=now_ms,
                                event_type=SimulationEventType.THREAD_ARRIVAL.value,
                                pid=proc.pid,
                                tid=thread.tid,
                                process_name=proc.name,
                                thread_name=thread.name,
                                state=thread.state.value,
                                priority=thread.priority,
                                cpu_consumed_ms=thread.cpu_consumed_ms,
                                quantum_used_ms=thread.quantum_used_ms,
                                details=f"Chegada programada da thread '{thread.name}'.",
                            )
                            self._enqueue_ready_thread(thread, timestamp_ms=now_ms)
            return

        if ev.event_type == SimulationEventType.QUANTUM_EXPIRE:
            running = self.cpu_scheduler.get_running_thread()
            if running is not None and (ev.tid is None or running.tid == ev.tid):
                rotated = self.cpu_scheduler.on_quantum_expired(timestamp_ms=now_ms)
                if rotated is not None:
                    r_proc = self.process_manager.processes.get(rotated.pid)
                    self.metrics_collector.record_event(
                        timestamp_ms=now_ms,
                        event_type=SimulationEventType.QUANTUM_EXPIRE.value,
                        pid=rotated.pid,
                        tid=rotated.tid,
                        process_name=r_proc.name if r_proc else "",
                        thread_name=rotated.name,
                        state=rotated.state.value,
                        priority=rotated.priority,
                        cpu_consumed_ms=rotated.cpu_consumed_ms,
                        quantum_used_ms=rotated.quantum_used_ms,
                        details="Quantum expirado por evento agendado.",
                    )
            return

    def _check_no_progress(self, now_ms: int) -> None:
        """Verify deadlock/stall invariants when CPU, ready queues, and events are empty."""
        has_running = self.cpu_scheduler.get_running_thread() is not None
        has_ready = not self.cpu_scheduler.is_ready_empty()
        has_pending = not self.event_manager.is_empty()

        diag = self.sync_manager.check_no_progress(
            has_ready=has_ready,
            has_running=has_running,
            has_pending_events=has_pending,
        )
        if diag is None:
            return

        if diag.get("deadlock_detected"):
            cycles = diag.get("cycles") or []
            first_cycle = cycles[0] if cycles else []
            self.metrics_collector.record_event(
                timestamp_ms=now_ms,
                event_type="DEADLOCK_DETECTED",
                details=diag["message"],
            )
            self._record_audit(
                AuditEventType.DEADLOCK_DETECTED,
                action="NO_PROGRESS_DEADLOCK",
                result="DEADLOCK",
                details={"cycles": cycles, "blocked_tids": diag.get("blocked_tids", [])},
            )
            raise DeadlockDetectedException(diag["message"], cycle=first_cycle)

        self.metrics_collector.record_event(
            timestamp_ms=now_ms,
            event_type="SIMULATION_STALL",
            details=diag["message"],
        )
        raise SimulationStallException(diag["message"])

    def _dispatch_next_thread(self, now_ms: int) -> Optional[SimulatedThread]:
        running = self.cpu_scheduler.dispatch_next(timestamp_ms=now_ms)
        if running is not None:
            proc = self.process_manager.processes.get(running.pid)
            self.metrics_collector.record_event(
                timestamp_ms=now_ms,
                event_type="DISPATCH",
                pid=running.pid,
                tid=running.tid,
                process_name=proc.name if proc else "",
                thread_name=running.name,
                state=running.state.value,
                priority=running.priority,
                cpu_consumed_ms=running.cpu_consumed_ms,
                quantum_used_ms=running.quantum_used_ms,
                details=f"Thread '{running.name}' despachada para CPU (prio={running.priority}).",
            )
        return running

    def _advance_single_tick_or_idle(
        self,
        cap_ms: Optional[int],
        target_event: Optional[SimulationEventType] = None,
    ) -> Tuple[bool, bool]:
        """Advance simulation by at most one CPU tick or an idle jump capped at cap_ms.

        Returns:
            Tuple of ``(progressed, target_event_hit)``.
        """
        now_ms = self.clock.now_ms
        target_hit = self._drain_due_events(now_ms, target_event=target_event)
        if target_hit:
            return True, True

        running = self.cpu_scheduler.get_running_thread()
        if running is None:
            if not self.cpu_scheduler.is_ready_empty():
                running = self._dispatch_next_thread(now_ms)
            else:
                next_ev = self.event_manager.peek_next()
                if next_ev is None:
                    self._check_no_progress(now_ms)
                    return False, False

                jump_to = next_ev.timestamp_ms if cap_ms is None else min(next_ev.timestamp_ms, cap_ms)
                if jump_to > now_ms:
                    self.metrics_collector.record_idle_slice(now_ms, jump_to)
                    self.metrics_collector.record_event(
                        timestamp_ms=now_ms,
                        event_type="CPU_IDLE",
                        details=f"CPU ociosa de {now_ms}ms até {jump_to}ms.",
                    )
                    self.clock.advance_to(jump_to)

                if self.clock.now_ms >= next_ev.timestamp_ms:
                    target_hit = self._drain_due_events(self.clock.now_ms, target_event=target_event)
                return True, target_hit

        assert running is not None
        proc = self.process_manager.get_process(running.pid)

        # Pre-tick syscall check (handles trigger_cpu_ms == 0 or pending steps at current cpu_consumed_ms)
        explicit_mem_ran = self._process_due_syscalls(proc, running, now_ms=now_ms)
        if ProcessState.normalize(running.state) != ProcessState.RUNNING:
            return True, target_hit

        if running.remaining_burst_ms <= 0:
            self._complete_running_thread(running, now_ms=now_ms)
            if (
                target_event == SimulationEventType.PROCESS_TERMINATED
                and ProcessState.normalize(proc.state) == ProcessState.TERMINATED
            ):
                target_hit = True
            if self._drain_due_events(now_ms, target_event=target_event):
                target_hit = True
            return True, target_hit

        # Dynamic virtual memory access on CPU execution tick (Stage 4 integration)
        if not explicit_mem_ran:
            self._access_process_memory_tick(proc, running, now_ms=now_ms)

        # Advance 1ms of simulated CPU execution
        running.cpu_consumed_ms += 1
        self.cpu_scheduler.tick_quantum(1)
        self.metrics_collector.record_cpu_slice(now_ms, now_ms + 1, running, proc.name)
        self.clock.advance_by(1)
        after_ms = self.clock.now_ms

        # Post-tick syscall check at new cpu_consumed_ms
        self._process_due_syscalls(proc, running, now_ms=after_ms)

        # Completion check
        if (
            ProcessState.normalize(running.state) == ProcessState.RUNNING
            and running.remaining_burst_ms <= 0
        ):
            self._complete_running_thread(running, now_ms=after_ms)
            if (
                target_event == SimulationEventType.PROCESS_TERMINATED
                and ProcessState.normalize(proc.state) == ProcessState.TERMINATED
            ):
                target_hit = True

        # Drain events at new clock.now_ms BEFORE checking quantum expiration
        if self._drain_due_events(after_ms, target_event=target_event):
            target_hit = True

        # Check quantum expiration if thread is still RUNNING on CPU
        if (
            ProcessState.normalize(running.state) == ProcessState.RUNNING
            and self.cpu_scheduler.running_tid == running.tid
            and running.quantum_used_ms >= self.cpu_scheduler.quantum_ms
        ):
            rotated = self.cpu_scheduler.on_quantum_expired(timestamp_ms=after_ms)
            if rotated is not None:
                if target_event == SimulationEventType.QUANTUM_EXPIRE:
                    target_hit = True
                self.metrics_collector.record_event(
                    timestamp_ms=after_ms,
                    event_type=SimulationEventType.QUANTUM_EXPIRE.value,
                    pid=proc.pid,
                    tid=rotated.tid,
                    process_name=proc.name,
                    thread_name=rotated.name,
                    state=rotated.state.value,
                    priority=rotated.priority,
                    cpu_consumed_ms=rotated.cpu_consumed_ms,
                    quantum_used_ms=rotated.quantum_used_ms,
                    details=f"Quantum ({self.cpu_scheduler.quantum_ms}ms) expirado; thread retornou à fila de prontos.",
                )

        return True, target_hit

    def step(self, ms: int = 1) -> Dict[str, Any]:
        """Advance logical simulation by up to ``ms`` milliseconds (never exceeding start_ms + ms)."""
        _validate_non_negative_int(ms, "ms")
        start_ms = self.clock.now_ms
        target_end_ms = start_ms + ms
        zero_time_iters = 0
        stop_reason = "STEP_COMPLETE"

        while self.clock.now_ms < target_end_ms:
            before_ms = self.clock.now_ms
            progressed, _ = self._advance_single_tick_or_idle(cap_ms=target_end_ms)
            if not progressed:
                stop_reason = "IDLE_EMPTY"
                break

            if self.clock.now_ms == before_ms:
                zero_time_iters += 1
                if zero_time_iters > self._MAX_ZERO_TIME_ITERATIONS:
                    raise SimulationStallException(
                        f"Loop de iteração sem avanço de relógio detectado em t={self.clock.now_ms}ms."
                    )
            else:
                zero_time_iters = 0

        return {
            "start_ms": start_ms,
            "end_ms": self.clock.now_ms,
            "elapsed_ms": self.clock.now_ms - start_ms,
            "stop_reason": stop_reason,
            "running_tid": self.cpu_scheduler.running_tid,
            "pending_events": len(self.event_manager),
            "ready_count": self.cpu_scheduler.get_stats()["ready_count"],
        }

    def run(
        self,
        max_ms: Optional[int] = None,
        until_process: Optional[Union[str, int]] = None,
        until_event: Optional[Union[SimulationEventType, str]] = None,
    ) -> Dict[str, Any]:
        """Run discrete-event simulation until completion, max_ms, target process, or target event."""
        if max_ms is not None:
            _validate_non_negative_int(max_ms, "max_ms")

        target_proc: Optional[Process] = None
        if until_process is not None:
            target_proc = self.process_manager.get_process(until_process)

        target_ev: Optional[SimulationEventType] = None
        if until_event is not None:
            target_ev = (
                until_event
                if isinstance(until_event, SimulationEventType)
                else SimulationEventType(str(until_event).strip().upper())
            )

        start_ms = self.clock.now_ms
        deadline_ms = (start_ms + max_ms) if max_ms is not None else None
        stop_reason = "COMPLETED"
        zero_time_iters = 0

        while True:
            if target_proc is not None and ProcessState.normalize(target_proc.state) == ProcessState.TERMINATED:
                stop_reason = "TARGET_PROCESS_TERMINATED"
                break

            if deadline_ms is not None and self.clock.now_ms >= deadline_ms:
                stop_reason = "MAX_MS_REACHED"
                break

            before_ms = self.clock.now_ms
            progressed, target_hit = self._advance_single_tick_or_idle(
                cap_ms=deadline_ms,
                target_event=target_ev,
            )

            if target_hit:
                stop_reason = "TARGET_EVENT_REACHED"
                break

            if not progressed:
                stop_reason = "COMPLETED"
                break

            if self.clock.now_ms == before_ms:
                zero_time_iters += 1
                if zero_time_iters > self._MAX_ZERO_TIME_ITERATIONS:
                    raise SimulationStallException(
                        f"Loop de iteração sem avanço de relógio detectado em t={self.clock.now_ms}ms."
                    )
            else:
                zero_time_iters = 0

        return {
            "start_ms": start_ms,
            "end_ms": self.clock.now_ms,
            "elapsed_ms": self.clock.now_ms - start_ms,
            "stop_reason": stop_reason,
            "metrics": self.get_metrics().to_dict(),
        }

    def terminate_process(self, identifier: Union[Process, str, int]) -> Process:
        """Cancel pending events, remove scheduler entries, release mutexes, free memory, and terminate."""
        proc = self.process_manager._resolve_process(identifier)
        if proc.pid == 0 or proc.name == "Nucleo_Base":
            raise PermissionDeniedException(
                "O núcleo base do sistema operacional não pode ser encerrado."
            )
        if ProcessState.normalize(proc.state) == ProcessState.TERMINATED:
            raise InvalidProcessStateException(
                f"Processo '{proc.name}' (PID {proc.pid}) já está encerrado."
            )

        now_ms = self.clock.now_ms
        tids = list(proc.threads.keys())

        self.event_manager.cancel_for_entity(pid=proc.pid)
        for tid in tids:
            self.event_manager.cancel_for_entity(tid=tid)
            self.cpu_scheduler.remove(tid)
            if self.syscall_dispatcher.block_registry.is_blocked(tid):
                self.syscall_dispatcher.block_registry.record_unblock(
                    tid,
                    timestamp_ms=now_ms,
                    next_state=ProcessState.TERMINATED,
                )

        self.process_manager.terminate_process(
            proc.pid,
            timestamp_ms=now_ms,
            reason="Encerramento forçado pelo ExecutionEngine",
        )

        for tid in tids:
            thread = self.process_manager.threads.get(tid)
            if thread is not None:
                self._release_thread_mutexes_and_wake(thread, now_ms=now_ms)

        self.memory_manager.free_process_memory(proc)

        self.metrics_collector.record_event(
            timestamp_ms=now_ms,
            event_type=SimulationEventType.PROCESS_TERMINATED.value,
            pid=proc.pid,
            process_name=proc.name,
            state=proc.state.value,
            priority=proc.priority,
            cpu_consumed_ms=proc.cpu_consumed_ms,
            details=f"Processo '{proc.name}' (PID {proc.pid}) encerrado e recursos liberados.",
        )
        self._record_audit(
            AuditEventType.PROCESS_LIFECYCLE,
            action="TERMINATE_PROCESS",
            details={"pid": proc.pid, "name": proc.name},
        )
        return proc

    def get_status(self) -> Dict[str, Any]:
        """Return structured snapshot of clock, scheduler, threads, mutexes, events, memory, and metrics."""
        running = self.cpu_scheduler.get_running_thread()
        ready_queues = self.cpu_scheduler.get_ready_queues()
        return {
            "clock_ms": self.clock.now_ms,
            "quantum_ms": self.cpu_scheduler.quantum_ms,
            "default_seed": self.default_seed,
            "peak_frames_used": self._peak_frames_used,
            "running_thread": running.to_dict() if running is not None else None,
            "scheduler": self.cpu_scheduler.get_stats(),
            "ready_queues": {
                prio: [t.to_dict() for t in threads]
                for prio, threads in ready_queues.items()
            },
            "active_blocks": [
                rec.to_dict()
                for rec in self.syscall_dispatcher.block_registry.get_active_blocks()
            ],
            "pending_events_count": len(self.event_manager),
            "pending_events": [ev.to_dict() for ev in self.event_manager.pending_events()],
            "synchronization": self.sync_manager.get_status(),
            "processes": [p.to_dict() for p in self.process_manager.list_processes()],
            "memory": self.memory_manager.get_status(),
            "frames_summary": self.get_frames_summary(),
            "syscalls_stats": self.syscall_dispatcher.get_stats(),
            "metrics": self.get_metrics().to_dict(),
        }

    def get_metrics(self) -> SimulationMetrics:
        """Compute current global, per-process, and per-thread metrics."""
        return self.metrics_collector.compute_global_metrics(
            process_manager=self.process_manager,
            clock_now_ms=self.clock.now_ms,
            scheduler_stats=self.cpu_scheduler,
        )

    def get_timeline(self, limit: Optional[int] = None) -> List[TimelineEntry]:
        """Return chronological timeline entries (optionally the last ``limit`` entries)."""
        return self.metrics_collector.get_timeline(limit=limit)

    def get_gantt(self) -> List[GanttSlice]:
        """Return recorded CPU execution and idle Gantt slices."""
        return self.metrics_collector.get_gantt()

    def get_frames_summary(self) -> List[Dict[str, Any]]:
        """Return live physical RAM frame summary synced with MemoryManager."""
        return self.metrics_collector.build_frames_summary(
            memory_manager=self.memory_manager,
            process_lookup=self.process_manager.get_process,
        )

    def run_buffer_video_demo(self, quantum_ms: int = 2) -> Dict[str, Any]:
        """Execute the Buffer_Video producer/consumer mutex scenario end-to-end."""
        self.set_quantum(quantum_ms)
        now_ms = self.clock.now_ms

        existing = self.process_manager.name_to_pid.get("Player_Video")
        if existing is not None:
            existing_proc = self.process_manager.processes.get(existing)
            if existing_proc is not None and ProcessState.normalize(existing_proc.state) != ProcessState.TERMINATED:
                self.terminate_process(existing_proc.pid)

        scenario = self.sync_manager.setup_buffer_video_scenario(
            process_manager=self.process_manager,
            arrival_time_ms=now_ms,
            initial_state=ProcessState.READY,
            replace_existing=True,
        )
        proc = scenario["process"]
        mutex = scenario["mutex"]
        t1 = scenario["t1"]
        t2 = scenario["t2"]

        try:
            self.memory_manager.allocate_process_memory(proc)
        except Exception:
            for tid in list(proc.threads.keys()):
                self.process_manager.threads.pop(tid, None)
            proc.terminate()
            self.process_manager.processes.pop(proc.pid, None)
            self.process_manager.name_to_pid.pop(proc.name, None)
            raise

        self.metrics_collector.record_event(
            timestamp_ms=now_ms,
            event_type="DEMO_BUFFER_VIDEO_START",
            pid=proc.pid,
            process_name=proc.name,
            state=proc.state.value,
            priority=proc.priority,
            details=f"Cenário Buffer_Video iniciado com quantum={quantum_ms}ms (T1 e T2).",
        )

        self.enqueue_process(proc)
        run_summary = self.run(until_process=proc.pid)

        # Verify mutual exclusion invariant across mutex acquire/handoff -> release intervals
        active_owner: Optional[int] = None
        disjoint = True
        for entry in mutex.history:
            ev = entry.get("event")
            if ev in ("ACQUIRE", "HANDOFF"):
                if active_owner is not None:
                    disjoint = False
                active_owner = entry.get("tid")
            elif ev == "RELEASE":
                if active_owner != entry.get("tid"):
                    disjoint = False
                active_owner = None
        if active_owner is not None or mutex.locked:
            disjoint = False

        return {
            "quantum_ms": quantum_ms,
            "mutex": mutex.to_dict(),
            "process": proc.to_dict(),
            "t1": t1.to_dict(),
            "t2": t2.to_dict(),
            "critical_sections_disjoint": disjoint,
            "run_summary": run_summary,
            "metrics": self.get_metrics().to_dict(),
            "gantt": [s.to_dict() for s in self.get_gantt()],
            "timeline": [e.to_dict() for e in self.get_timeline()],
            "frames_summary": self.get_frames_summary(),
        }

    def reset(self) -> None:
        """Reset all Stage 5 simulation state in-place while preserving kernel subsystem references."""
        self.event_manager.clear()
        self.clock.reset(0)
        self.cpu_scheduler.reset()
        self.sync_manager.clear()
        self.syscall_dispatcher.reset()
        self.metrics_collector.reset()
        self._memory_access_cursors.clear()
        self._peak_frames_used = 0

        for proc in list(self.process_manager.processes.values()):
            if proc.pid != 0:
                self.memory_manager.free_process_memory(proc)

        for key in self.memory_manager.stats:
            self.memory_manager.stats[key] = 0
        self.memory_manager.set_replacement_policy(self.memory_manager.algorithm)

        kernel_proc = self.process_manager.kernel_process
        self.process_manager.processes.clear()
        self.process_manager.processes[0] = kernel_proc
        self.process_manager.name_to_pid.clear()
        self.process_manager.name_to_pid[kernel_proc.name] = 0
        self.process_manager.threads.clear()
        self.process_manager._next_pid = 100
        self.process_manager._next_tid = 1
        self.process_manager.state_machine.clear_history()
