"""Process manager orchestrating process and thread lifecycles and tracking PCBs."""

from typing import Any, Dict, List, Optional, Tuple, Union

from os_simulator.core.exceptions import (
    InvalidProcessStateException,
    PermissionDeniedException,
    ProcessAlreadyExistsException,
    ProcessNotFoundException,
    ThreadAlreadyExistsException,
    ThreadNotFoundException,
)
from os_simulator.core.types import BlockReason, IOProfileType, ProcessState, ProcessType
from os_simulator.process.pcb import Process
from os_simulator.process.state_machine import ProcessStateMachine, StateTransitionRecord
from os_simulator.process.thread import SimulatedThread, WorkloadStep


class ProcessManager:
    """Manages process and thread creation, lookup, state transitions, and termination."""

    def __init__(
        self,
        start_pid: int = 100,
        start_tid: int = 1,
        state_machine: Optional[ProcessStateMachine] = None,
    ):
        self.processes: Dict[int, Process] = {}
        self.name_to_pid: Dict[str, int] = {}
        self.threads: Dict[int, SimulatedThread] = {}
        self._next_pid: int = start_pid
        self._next_tid: int = start_tid
        self.state_machine: ProcessStateMachine = state_machine or ProcessStateMachine()

        # Initialize Base Kernel (PID 0)
        self.kernel_process = Process(
            pid=0,
            name="Nucleo_Base",
            size_bytes=1024 * 1024,
            process_type=ProcessType.CRITICAL,
            owner="root",
            state=ProcessState.RUNNING,
            priority=1,
        )
        self.processes[0] = self.kernel_process
        self.name_to_pid["Nucleo_Base"] = 0

    def _allocate_tid(self) -> int:
        tid = self._next_tid
        self._next_tid += 1
        return tid

    def _resolve_process(self, identifier: Union[Process, str, int]) -> Process:
        if isinstance(identifier, Process):
            return identifier
        return self.get_process(identifier)

    def create_process(
        self,
        name: str,
        size_bytes: int,
        process_type: ProcessType = ProcessType.NORMAL,
        owner: str = "root",
        priority: int = 3,
        cpu_burst_ms: int = 0,
        arrival_time_ms: int = 0,
        initial_state: Optional[ProcessState] = None,
        io_profile: Any = IOProfileType.NONE,
        memory_access_pattern: Optional[List[Tuple[int, bool]]] = None,
        create_default_thread: Optional[bool] = None,
    ) -> Process:
        """Create and register a new process (defaulting to READY for Stage 4 compatibility)."""
        if not name or not name.strip():
            raise ValueError("Nome do processo não pode ser vazio.")

        name = name.strip()
        if name in self.name_to_pid:
            existing_pid = self.name_to_pid[name]
            existing_proc = self.processes[existing_pid]
            if existing_proc.state != ProcessState.TERMINATED:
                raise ProcessAlreadyExistsException(
                    f"Processo '{name}' já existe e está ativo (PID {existing_pid})."
                )

        if size_bytes <= 0:
            raise ValueError(f"Tamanho do processo deve ser maior que zero (recebido: {size_bytes} bytes).")

        resolved_state = (
            ProcessState.READY
            if initial_state is None
            else self.state_machine.normalize_state(initial_state)
        )

        pid = self._next_pid
        self._next_pid += 1

        proc = Process(
            pid=pid,
            name=name,
            size_bytes=size_bytes,
            process_type=process_type,
            owner=owner,
            state=resolved_state,
            priority=priority,
            cpu_burst_ms=cpu_burst_ms,
            arrival_time_ms=arrival_time_ms,
            io_profile=io_profile,
            memory_access_pattern=memory_access_pattern,
            create_default_thread=False,
        )
        self.processes[pid] = proc
        self.name_to_pid[name] = pid

        should_create_main = (
            create_default_thread
            if create_default_thread is not None
            else (cpu_burst_ms > 0)
        )
        if should_create_main:
            self.create_thread(
                process_identifier=proc,
                name="main",
                priority=proc.priority,
                cpu_burst_ms=proc.cpu_burst_ms,
                arrival_time_ms=proc.arrival_time_ms,
                initial_state=proc.state,
                io_profile=proc.io_profile,
                memory_access_pattern=proc.memory_access_pattern,
                sync_parent=False,
            )

        return proc

    def ensure_main_thread(self, process_identifier: Union[Process, str, int]) -> SimulatedThread:
        """Ensure a process has a primary schedulable thread (creating 'main' if unthreaded)."""
        proc = self._resolve_process(process_identifier)
        if proc.pid == 0:
            raise PermissionDeniedException("Nucleo_Base (PID 0) não possui thread escalonável de usuário.")
        if "main" in proc.thread_name_to_tid:
            return proc.threads[proc.thread_name_to_tid["main"]]
        if proc.threads:
            return next(iter(proc.threads.values()))
        return self.create_thread(
            process_identifier=proc,
            name="main",
            priority=proc.priority,
            cpu_burst_ms=proc.cpu_burst_ms,
            arrival_time_ms=proc.arrival_time_ms,
            initial_state=proc.state if proc.state != ProcessState.RUNNING else ProcessState.READY,
            io_profile=proc.io_profile,
            memory_access_pattern=proc.memory_access_pattern,
            sync_parent=False,
        )

    def get_process(self, identifier: Union[str, int]) -> Process:
        """Find process by PID or name."""
        if isinstance(identifier, int) and not isinstance(identifier, bool):
            if identifier in self.processes:
                return self.processes[identifier]
            raise ProcessNotFoundException(f"Processo com PID {identifier} não encontrado.")

        id_str = str(identifier).strip()
        if id_str.isdigit() and int(id_str) in self.processes:
            return self.processes[int(id_str)]

        if id_str in self.name_to_pid:
            pid = self.name_to_pid[id_str]
            return self.processes[pid]

        for proc in self.processes.values():
            if proc.name.lower() == id_str.lower():
                return proc

        raise ProcessNotFoundException(f"Processo '{identifier}' não encontrado.")

    def admit_process(
        self,
        identifier: Union[Process, str, int],
        timestamp_ms: int = 0,
        reason: str = "Admissão do processo na fila de prontos",
    ) -> Process:
        """Transition a NEW process (and its NEW threads) to READY."""
        proc = self._resolve_process(identifier)
        self.state_machine.transition(
            proc,
            ProcessState.READY,
            timestamp_ms=timestamp_ms,
            reason=reason,
            entity_id=f"PID:{proc.pid}",
        )
        for thread in proc.threads.values():
            if self.state_machine.normalize_state(thread.state) == ProcessState.NEW:
                self.transition_thread_state(
                    thread,
                    ProcessState.READY,
                    timestamp_ms=timestamp_ms,
                    reason=reason,
                    sync_parent=False,
                )
        return proc

    def transition_process_state(
        self,
        identifier: Union[Process, str, int],
        to_state: Union[ProcessState, str],
        timestamp_ms: int = 0,
        reason: str = "",
    ) -> StateTransitionRecord:
        """Validate and execute a state transition directly on a Process PCB."""
        proc = self._resolve_process(identifier)
        record = self.state_machine.transition(
            proc,
            to_state,
            timestamp_ms=timestamp_ms,
            reason=reason,
            entity_id=f"PID:{proc.pid}",
        )
        if record.to_state == ProcessState.RUNNING and proc.start_time_ms is None:
            proc.start_time_ms = timestamp_ms
        elif record.to_state == ProcessState.TERMINATED and proc.finish_time_ms is None:
            proc.finish_time_ms = timestamp_ms
        return record

    def create_thread(
        self,
        process_identifier: Union[Process, str, int],
        name: str,
        priority: Optional[int] = None,
        cpu_burst_ms: int = 0,
        arrival_time_ms: Optional[int] = None,
        initial_state: Optional[ProcessState] = None,
        io_profile: Any = IOProfileType.NONE,
        memory_access_pattern: Optional[List[Tuple[int, bool]]] = None,
        workload_steps: Optional[List[WorkloadStep]] = None,
        sync_parent: bool = True,
    ) -> SimulatedThread:
        """Create and attach a new SimulatedThread to an active process."""
        proc = self._resolve_process(process_identifier)
        if proc.pid == 0 or proc.name == "Nucleo_Base":
            raise PermissionDeniedException("Não é permitido criar threads no núcleo base (PID 0).")
        if proc.state == ProcessState.TERMINATED:
            raise InvalidProcessStateException(
                f"Não é possível criar thread em processo encerrado '{proc.name}' (PID {proc.pid})."
            )

        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Nome da thread não pode ser vazio.")
        if clean_name in proc.thread_name_to_tid:
            existing = proc.threads[proc.thread_name_to_tid[clean_name]]
            if existing.state != ProcessState.TERMINATED:
                raise ThreadAlreadyExistsException(
                    f"Thread '{clean_name}' já existe e está ativa no processo '{proc.name}' (PID {proc.pid})."
                )

        eff_priority = proc.priority if priority is None else priority
        eff_arrival = proc.arrival_time_ms if arrival_time_ms is None else arrival_time_ms
        if initial_state is None:
            eff_state = ProcessState.NEW if proc.state == ProcessState.NEW else ProcessState.READY
        else:
            eff_state = self.state_machine.normalize_state(initial_state)

        tid = self._allocate_tid()
        thread = SimulatedThread(
            tid=tid,
            pid=proc.pid,
            name=clean_name,
            state=eff_state,
            priority=eff_priority,
            cpu_burst_ms=cpu_burst_ms,
            arrival_time_ms=eff_arrival,
            io_profile=io_profile,
            memory_access_pattern=list(memory_access_pattern) if memory_access_pattern else [],
            workload_steps=list(workload_steps) if workload_steps else [],
        )
        proc.add_thread(thread)
        self.threads[tid] = thread

        if sync_parent:
            self.sync_process_state(proc, timestamp_ms=eff_arrival, reason=f"Criação da thread '{clean_name}'")

        return thread

    def get_thread(
        self,
        identifier: Union[int, str],
        process_identifier: Optional[Union[Process, str, int]] = None,
    ) -> SimulatedThread:
        """Locate a thread by TID or name (optionally scoped to a parent process)."""
        if process_identifier is not None:
            proc = self._resolve_process(process_identifier)
            thread = proc.get_thread(identifier)
            if thread is None:
                raise ThreadNotFoundException(
                    f"Thread '{identifier}' não encontrada no processo '{proc.name}' (PID {proc.pid})."
                )
            return thread

        if isinstance(identifier, int) and not isinstance(identifier, bool):
            if identifier in self.threads:
                return self.threads[identifier]
            raise ThreadNotFoundException(f"Thread com TID {identifier} não encontrada.")

        id_str = str(identifier).strip()
        if id_str.isdigit() and int(id_str) in self.threads:
            return self.threads[int(id_str)]

        for thread in self.threads.values():
            if thread.name == id_str and thread.state != ProcessState.TERMINATED:
                return thread
        for thread in self.threads.values():
            if thread.name.lower() == id_str.lower() and thread.state != ProcessState.TERMINATED:
                return thread
        for thread in self.threads.values():
            if thread.name.lower() == id_str.lower():
                return thread

        raise ThreadNotFoundException(f"Thread '{identifier}' não encontrada.")

    def get_thread_by_name(
        self,
        process_identifier: Union[Process, str, int],
        name: str,
    ) -> SimulatedThread:
        """Locate a thread by name within a specific parent process."""
        proc = self._resolve_process(process_identifier)
        thread = proc.get_thread(name)
        if thread is None:
            raise ThreadNotFoundException(
                f"Thread '{name}' não encontrada no processo '{proc.name}' (PID {proc.pid})."
            )
        return thread

    def transition_thread_state(
        self,
        thread_or_tid: Union[SimulatedThread, int, str],
        to_state: Union[ProcessState, str],
        timestamp_ms: int = 0,
        reason: str = "",
        block_reason: BlockReason = BlockReason.NONE,
        blocked_on: Optional[str] = None,
        sync_parent: bool = True,
    ) -> StateTransitionRecord:
        """Validate and apply a state transition on a SimulatedThread, updating timing accumulators."""
        thread = (
            thread_or_tid
            if isinstance(thread_or_tid, SimulatedThread)
            else self.get_thread(thread_or_tid)
        )
        src, dst = self.state_machine.validate_transition(
            thread.state,
            to_state,
            entity_id=f"TID:{thread.tid}",
        )

        # Accumulate time spent in previous state
        if src == ProcessState.READY and thread.ready_since_ms is not None:
            thread.total_wait_ms += max(0, timestamp_ms - thread.ready_since_ms)
            thread.ready_since_ms = None
        elif src == ProcessState.BLOCKED and thread.blocked_since_ms is not None:
            thread.total_blocked_ms += max(0, timestamp_ms - thread.blocked_since_ms)
            thread.blocked_since_ms = None
            thread.block_reason = BlockReason.NONE
            thread.blocked_on = None

        if src == ProcessState.RUNNING and dst in (ProcessState.READY, ProcessState.BLOCKED):
            thread.quantum_used_ms = 0

        # Initialize metadata for target state
        if dst == ProcessState.READY:
            thread.ready_since_ms = timestamp_ms
        elif dst == ProcessState.RUNNING:
            if thread.start_time_ms is None:
                thread.start_time_ms = timestamp_ms
        elif dst == ProcessState.BLOCKED:
            thread.blocked_since_ms = timestamp_ms
            thread.block_reason = block_reason
            thread.blocked_on = blocked_on
        elif dst == ProcessState.TERMINATED:
            thread.finish_time_ms = timestamp_ms
            thread.ready_since_ms = None
            thread.blocked_since_ms = None
            thread.block_reason = BlockReason.NONE
            thread.blocked_on = None
            thread.quantum_used_ms = 0

        record = self.state_machine.transition(
            thread,
            dst,
            timestamp_ms=timestamp_ms,
            reason=reason,
            entity_id=f"TID:{thread.tid}",
        )

        if sync_parent and thread.pid in self.processes:
            self.sync_process_state(
                self.processes[thread.pid],
                timestamp_ms=timestamp_ms,
                reason=reason or f"Atualização da thread '{thread.name}'",
            )

        return record

    def sync_process_state(
        self,
        process_or_pid: Union[Process, int, str],
        timestamp_ms: int = 0,
        reason: str = "Sincronização com estado das threads",
    ) -> ProcessState:
        """Synchronize parent Process.state from its child SimulatedThreads."""
        proc = self._resolve_process(process_or_pid)
        if not proc.threads:
            return proc.state

        states = [self.state_machine.normalize_state(t.state) for t in proc.threads.values()]
        if all(s == ProcessState.TERMINATED for s in states):
            target = ProcessState.TERMINATED
        elif any(s == ProcessState.RUNNING for s in states):
            target = ProcessState.RUNNING
        elif any(s == ProcessState.READY for s in states):
            target = ProcessState.READY
        elif any(s == ProcessState.BLOCKED for s in states):
            target = ProcessState.BLOCKED
        else:
            target = ProcessState.NEW

        current = self.state_machine.normalize_state(proc.state)
        if current == target:
            return proc.state

        if self.state_machine.can_transition(current, target):
            self.state_machine.transition(
                proc,
                target,
                timestamp_ms=timestamp_ms,
                reason=reason,
                entity_id=f"PID:{proc.pid}",
            )
        else:
            # Derived multi-thread aggregate edge case (e.g., READY thread exited leaving only BLOCKED sibling)
            proc.state = target

        if target == ProcessState.RUNNING and proc.start_time_ms is None:
            proc.start_time_ms = timestamp_ms
        elif target == ProcessState.TERMINATED and proc.finish_time_ms is None:
            proc.finish_time_ms = timestamp_ms

        return proc.state

    def terminate_process(
        self,
        identifier: Union[str, int],
        timestamp_ms: Optional[int] = None,
        reason: str = "Encerramento do processo",
    ) -> Process:
        """Terminate a process (and all its active threads) by name or PID."""
        proc = self.get_process(identifier)

        if proc.pid == 0 or proc.name == "Nucleo_Base":
            raise PermissionDeniedException("O núcleo base do sistema operacional não pode ser encerrado.")

        if proc.state == ProcessState.TERMINATED:
            raise InvalidProcessStateException(f"Processo '{proc.name}' (PID {proc.pid}) já está encerrado.")

        ts = 0 if timestamp_ms is None else timestamp_ms
        for thread in proc.threads.values():
            if thread.state != ProcessState.TERMINATED:
                self.transition_thread_state(
                    thread,
                    ProcessState.TERMINATED,
                    timestamp_ms=ts,
                    reason=reason,
                    sync_parent=False,
                )

        if proc.state != ProcessState.TERMINATED:
            self.state_machine.transition(
                proc,
                ProcessState.TERMINATED,
                timestamp_ms=ts,
                reason=reason,
                entity_id=f"PID:{proc.pid}",
            )
        if timestamp_ms is not None:
            proc.finish_time_ms = timestamp_ms
        return proc

    def list_processes(self, active_only: bool = False) -> List[Process]:
        """List all tracked processes."""
        if active_only:
            return [p for p in self.processes.values() if p.state != ProcessState.TERMINATED]
        return list(self.processes.values())

    def list_threads(
        self,
        process_identifier: Optional[Union[Process, str, int]] = None,
        active_only: bool = False,
    ) -> List[SimulatedThread]:
        """List threads globally or for a specific parent process."""
        if process_identifier is not None:
            proc = self._resolve_process(process_identifier)
            return proc.list_threads(active_only=active_only)
        if active_only:
            return [t for t in self.threads.values() if t.state != ProcessState.TERMINATED]
        return list(self.threads.values())
