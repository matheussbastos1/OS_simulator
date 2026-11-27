"""Mutex synchronization, strict FIFO wait queues, and Wait-For Graph deadlock detection."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set, Tuple, Union

from os_simulator.core.exceptions import (
    DeadlockDetectedException,
    InvalidStateTransitionException,
    MutexAlreadyExistsException,
    MutexNotFoundException,
    MutexOwnershipException,
)
from os_simulator.core.types import BlockReason, ProcessState, ProcessType, SyscallType
from os_simulator.process.manager import ProcessManager
from os_simulator.process.thread import SimulatedThread, WorkloadStep


@dataclass
class Mutex:
    """Simulated mutual exclusion lock with strict FIFO wait queue and event history."""

    name: str
    locked: bool = False
    owner_tid: Optional[int] = None
    owner_pid: Optional[int] = None
    wait_queue: Deque[int] = field(default_factory=deque)
    acquire_count: int = 0
    release_count: int = 0
    contention_count: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name or not str(self.name).strip():
            raise ValueError("Nome do mutex não pode ser vazio.")
        self.name = str(self.name).strip()
        if not isinstance(self.wait_queue, deque):
            self.wait_queue = deque(self.wait_queue)

    def record_event(
        self,
        event: str,
        timestamp_ms: int,
        tid: Optional[int] = None,
        pid: Optional[int] = None,
        details: str = "",
        **extra: Any,
    ) -> Dict[str, Any]:
        """Append a structured synchronization event to this mutex's history."""
        entry: Dict[str, Any] = {
            "timestamp_ms": timestamp_ms,
            "mutex_name": self.name,
            "event": event,
            "tid": tid,
            "pid": pid,
            "details": details,
        }
        if extra:
            entry.update(extra)
        self.history.append(entry)
        return entry

    def to_dict(self) -> Dict[str, Any]:
        """Serialize mutex state, wait queue, counters, and history to a dictionary."""
        return {
            "name": self.name,
            "locked": self.locked,
            "owner_tid": self.owner_tid,
            "owner_pid": self.owner_pid,
            "wait_queue": list(self.wait_queue),
            "wait_queue_size": len(self.wait_queue),
            "acquire_count": self.acquire_count,
            "release_count": self.release_count,
            "contention_count": self.contention_count,
            "history": [dict(item) for item in self.history],
        }

    def __repr__(self) -> str:
        status = f"LOCKED(owner_tid={self.owner_tid})" if self.locked else "UNLOCKED"
        return f"<Mutex name='{self.name}' {status} waiting={list(self.wait_queue)}>"


class SynchronizationManager:
    """Manages mutexes, FIFO contention blocking/handoff, and Wait-For Graph deadlock detection."""

    def __init__(self, process_manager: ProcessManager) -> None:
        self.process_manager = process_manager
        self.mutexes: Dict[str, Mutex] = {}
        self.history: List[Dict[str, Any]] = []

    @staticmethod
    def _validate_timestamp(timestamp_ms: int) -> None:
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
            raise ValueError(f"timestamp_ms deve ser inteiro >= 0 (recebido: {timestamp_ms!r}).")

    def _resolve_thread(self, thread_or_tid: Union[SimulatedThread, int, str]) -> SimulatedThread:
        if isinstance(thread_or_tid, SimulatedThread):
            return thread_or_tid
        return self.process_manager.get_thread(thread_or_tid)

    def _format_thread_label(self, tid: int) -> str:
        thread = self.process_manager.threads.get(tid)
        if thread is not None:
            return f"TID:{tid}({thread.name})"
        return f"TID:{tid}(desconhecida)"

    def _record_event(
        self,
        mutex: Mutex,
        event: str,
        timestamp_ms: int,
        tid: Optional[int] = None,
        pid: Optional[int] = None,
        details: str = "",
        **extra: Any,
    ) -> Dict[str, Any]:
        entry = mutex.record_event(
            event=event,
            timestamp_ms=timestamp_ms,
            tid=tid,
            pid=pid,
            details=details,
            **extra,
        )
        self.history.append(dict(entry))
        return entry

    def create_mutex(self, name: str) -> Mutex:
        """Create and register a new named mutex."""
        clean_name = "" if name is None else str(name).strip()
        if not clean_name:
            raise ValueError("Nome do mutex não pode ser vazio.")
        if clean_name in self.mutexes:
            raise MutexAlreadyExistsException(f"Mutex '{clean_name}' já existe.")
        mutex = Mutex(name=clean_name)
        self.mutexes[clean_name] = mutex
        return mutex

    def get_mutex(self, name: str) -> Mutex:
        """Return an existing mutex by name or raise MutexNotFoundException."""
        clean_name = "" if name is None else str(name).strip()
        if not clean_name or clean_name not in self.mutexes:
            raise MutexNotFoundException(f"Mutex '{name}' não encontrado.")
        return self.mutexes[clean_name]

    def get_or_create_mutex(self, name: str) -> Mutex:
        """Return an existing mutex or create a new one if absent."""
        clean_name = "" if name is None else str(name).strip()
        if not clean_name:
            raise ValueError("Nome do mutex não pode ser vazio.")
        if clean_name in self.mutexes:
            return self.mutexes[clean_name]
        return self.create_mutex(clean_name)

    def list_mutexes(self) -> List[Mutex]:
        """Return all registered mutexes."""
        return list(self.mutexes.values())

    def acquire(
        self,
        mutex_name: str,
        thread_or_tid: Union[SimulatedThread, int, str],
        timestamp_ms: int = 0,
    ) -> bool:
        """Attempt to acquire a mutex; blocks the thread on contention and checks for deadlocks."""
        self._validate_timestamp(timestamp_ms)
        mutex = self.get_mutex(mutex_name)
        thread = self._resolve_thread(thread_or_tid)

        current_state = self.process_manager.state_machine.normalize_state(thread.state)
        if current_state in (ProcessState.TERMINATED, ProcessState.BLOCKED, ProcessState.NEW):
            raise InvalidStateTransitionException(
                f"Thread '{thread.name}' (TID {thread.tid}) no estado '{current_state.value}' "
                f"não pode adquirir o mutex '{mutex.name}'.",
                from_state=current_state.value,
                to_state=ProcessState.BLOCKED.value,
                entity_id=f"TID:{thread.tid}",
            )

        if not mutex.locked:
            mutex.locked = True
            mutex.owner_tid = thread.tid
            mutex.owner_pid = thread.pid
            if mutex.name not in thread.held_mutexes:
                thread.held_mutexes.append(mutex.name)
            mutex.acquire_count += 1
            self._record_event(
                mutex,
                event="ACQUIRE",
                timestamp_ms=timestamp_ms,
                tid=thread.tid,
                pid=thread.pid,
                thread_name=thread.name,
                details=f"Thread '{thread.name}' (TID {thread.tid}) adquiriu '{mutex.name}'.",
            )
            return True

        if mutex.owner_tid == thread.tid:
            cycle = [
                f"TID:{thread.tid}({thread.name}) -> Mutex:{mutex.name} -> TID:{thread.tid}({thread.name})"
            ]
            self._record_event(
                mutex,
                event="SELF_DEADLOCK",
                timestamp_ms=timestamp_ms,
                tid=thread.tid,
                pid=thread.pid,
                thread_name=thread.name,
                cycle=list(cycle),
                details=f"Auto-deadlock: thread '{thread.name}' (TID {thread.tid}) já possui '{mutex.name}'.",
            )
            raise DeadlockDetectedException(
                f"Auto-deadlock detectado na thread '{thread.name}' (TID {thread.tid}) "
                f"ao tentar readquirir o mutex '{mutex.name}'.",
                cycle=cycle,
            )

        # Mutex is locked by another thread: record contention and enqueue FIFO
        mutex.contention_count += 1
        if thread.tid not in mutex.wait_queue:
            mutex.wait_queue.append(thread.tid)

        # Respect state machine invariants: READY must enter RUNNING before BLOCKED
        if current_state == ProcessState.READY:
            self.process_manager.transition_thread_state(
                thread,
                ProcessState.RUNNING,
                timestamp_ms=timestamp_ms,
                reason=f"Despacho implícito para tentativa de lock em '{mutex.name}'",
            )

        self.process_manager.transition_thread_state(
            thread,
            ProcessState.BLOCKED,
            timestamp_ms=timestamp_ms,
            reason=f"Aguardando mutex '{mutex.name}' (dono TID:{mutex.owner_tid})",
            block_reason=BlockReason.MUTEX_WAIT,
            blocked_on=mutex.name,
        )

        self._record_event(
            mutex,
            event="CONTENTION",
            timestamp_ms=timestamp_ms,
            tid=thread.tid,
            pid=thread.pid,
            thread_name=thread.name,
            owner_tid=mutex.owner_tid,
            queue_position=len(mutex.wait_queue),
            details=(
                f"Thread '{thread.name}' (TID {thread.tid}) bloqueada aguardando '{mutex.name}' "
                f"(pos={len(mutex.wait_queue)}, dono=TID:{mutex.owner_tid})."
            ),
        )

        cycles = self.detect_deadlocks()
        if cycles:
            tid_marker = f"TID:{thread.tid}("
            selected_cycle = next(
                (cycle for cycle in cycles if any(tid_marker in edge for edge in cycle)),
                cycles[0],
            )
            self._record_event(
                mutex,
                event="DEADLOCK",
                timestamp_ms=timestamp_ms,
                tid=thread.tid,
                pid=thread.pid,
                thread_name=thread.name,
                cycle=list(selected_cycle),
                details=f"Deadlock detectado envolvendo '{mutex.name}': {' ; '.join(selected_cycle)}",
            )
            raise DeadlockDetectedException(
                f"Deadlock detectado ao aguardar mutex '{mutex.name}': {' ; '.join(selected_cycle)}",
                cycle=selected_cycle,
            )

        return False

    def release(
        self,
        mutex_name: str,
        thread_or_tid: Union[SimulatedThread, int, str],
        timestamp_ms: int = 0,
    ) -> Optional[SimulatedThread]:
        """Release a mutex owned by thread and immediately hand off ownership to the next FIFO waiter."""
        self._validate_timestamp(timestamp_ms)
        mutex = self.get_mutex(mutex_name)
        thread = self._resolve_thread(thread_or_tid)

        if not mutex.locked or mutex.owner_tid != thread.tid:
            owner_desc = f"TID:{mutex.owner_tid}" if mutex.locked else "ninguém (livre)"
            raise MutexOwnershipException(
                f"Thread '{thread.name}' (TID {thread.tid}) não possui o mutex '{mutex.name}' "
                f"(dono atual: {owner_desc})."
            )

        while mutex.name in thread.held_mutexes:
            thread.held_mutexes.remove(mutex.name)
        mutex.release_count += 1

        self._record_event(
            mutex,
            event="RELEASE",
            timestamp_ms=timestamp_ms,
            tid=thread.tid,
            pid=thread.pid,
            thread_name=thread.name,
            details=f"Thread '{thread.name}' (TID {thread.tid}) liberou '{mutex.name}'.",
        )

        return self._handoff_to_next_waiter(
            mutex=mutex,
            previous_owner_tid=thread.tid,
            timestamp_ms=timestamp_ms,
            reason=f"Mutex '{mutex.name}' transferido de TID:{thread.tid} para TID:{{next_tid}}",
            previous_owner_name=thread.name,
        )

    def release_all_for_thread(
        self,
        tid: int,
        timestamp_ms: int = 0,
    ) -> List[SimulatedThread]:
        """Release all mutexes held by tid and remove tid from any wait queues."""
        self._validate_timestamp(timestamp_ms)
        unblocked_threads: List[SimulatedThread] = []

        # Purge tid from any wait queues it may have been waiting in
        for mutex in self.mutexes.values():
            if tid in mutex.wait_queue:
                mutex.wait_queue = deque(w_tid for w_tid in mutex.wait_queue if w_tid != tid)

        thread = self.process_manager.threads.get(tid)
        owned_names: List[str] = []
        if thread is not None:
            for m_name in thread.held_mutexes:
                if m_name in self.mutexes and m_name not in owned_names:
                    m = self.mutexes[m_name]
                    if m.locked and m.owner_tid == tid:
                        owned_names.append(m_name)

        for mutex in self.mutexes.values():
            if mutex.locked and mutex.owner_tid == tid and mutex.name not in owned_names:
                owned_names.append(mutex.name)

        for mutex_name in owned_names:
            if thread is not None:
                unblocked = self.release(mutex_name, thread, timestamp_ms=timestamp_ms)
            else:
                # Defensive fallback if thread object is no longer registered
                mutex = self.mutexes[mutex_name]
                mutex.release_count += 1
                self._record_event(
                    mutex,
                    event="RELEASE",
                    timestamp_ms=timestamp_ms,
                    tid=tid,
                    details=f"Mutex '{mutex.name}' liberado após encerramento de TID:{tid}.",
                )
                unblocked = self._handoff_to_next_waiter(
                    mutex=mutex,
                    previous_owner_tid=tid,
                    timestamp_ms=timestamp_ms,
                    reason=f"Mutex '{mutex.name}' transferido após saída de TID:{tid}",
                )
            if unblocked is not None:
                unblocked_threads.append(unblocked)

        return unblocked_threads

    def _handoff_to_next_waiter(
        self,
        mutex: Mutex,
        previous_owner_tid: int,
        timestamp_ms: int,
        reason: str,
        previous_owner_name: Optional[str] = None,
    ) -> Optional[SimulatedThread]:
        """Pop the first non-terminated FIFO waiter and hand off mutex ownership, or unlock."""
        next_thread: Optional[SimulatedThread] = None
        while mutex.wait_queue:
            candidate_tid = mutex.wait_queue.popleft()
            candidate = self.process_manager.threads.get(candidate_tid)
            if candidate is None:
                continue
            cand_state = self.process_manager.state_machine.normalize_state(candidate.state)
            if cand_state == ProcessState.TERMINATED:
                continue
            next_thread = candidate
            break

        if next_thread is None:
            mutex.locked = False
            mutex.owner_tid = None
            mutex.owner_pid = None
            return None

        mutex.locked = True
        mutex.owner_tid = next_thread.tid
        mutex.owner_pid = next_thread.pid
        if mutex.name not in next_thread.held_mutexes:
            next_thread.held_mutexes.append(mutex.name)
        mutex.acquire_count += 1

        if self.process_manager.state_machine.normalize_state(next_thread.state) == ProcessState.BLOCKED:
            self.process_manager.transition_thread_state(
                next_thread,
                ProcessState.READY,
                timestamp_ms=timestamp_ms,
                reason=reason.format(next_tid=next_thread.tid, next_name=next_thread.name),
            )

        from_label = (
            f"TID:{previous_owner_tid}({previous_owner_name})"
            if previous_owner_name is not None
            else f"TID:{previous_owner_tid}"
        )
        self._record_event(
            mutex,
            event="HANDOFF",
            timestamp_ms=timestamp_ms,
            tid=next_thread.tid,
            pid=next_thread.pid,
            thread_name=next_thread.name,
            previous_owner_tid=previous_owner_tid,
            details=f"Handoff de '{mutex.name}': {from_label} -> TID:{next_thread.tid}({next_thread.name}).",
        )
        return next_thread

    def detect_deadlocks(self) -> List[List[str]]:
        """Build Wait-For Graph (waiting_tid -> owner_tid) and detect cycles and terminated-owner waits."""
        adj: Dict[int, List[Tuple[int, str]]] = defaultdict(list)
        special_deadlocks: List[List[str]] = []

        for mutex in sorted(self.mutexes.values(), key=lambda m: m.name):
            if not mutex.locked or mutex.owner_tid is None:
                continue

            owner_tid = mutex.owner_tid
            owner_thread = self.process_manager.threads.get(owner_tid)
            owner_terminated = (
                owner_thread is None
                or self.process_manager.state_machine.normalize_state(owner_thread.state)
                == ProcessState.TERMINATED
            )

            for waiting_tid in mutex.wait_queue:
                waiter = self.process_manager.threads.get(waiting_tid)
                if waiter is None:
                    continue
                waiter_state = self.process_manager.state_machine.normalize_state(waiter.state)
                if waiter_state == ProcessState.TERMINATED:
                    continue

                if owner_terminated:
                    special_deadlocks.append(
                        [
                            f"{self._format_thread_label(waiting_tid)} -> Mutex:{mutex.name} -> "
                            f"{self._format_thread_label(owner_tid)}[TERMINATED]"
                        ]
                    )
                    continue

                if waiting_tid == owner_tid:
                    special_deadlocks.append(
                        [
                            f"{self._format_thread_label(waiting_tid)} -> Mutex:{mutex.name} -> "
                            f"{self._format_thread_label(owner_tid)}"
                        ]
                    )
                    continue

                adj[waiting_tid].append((owner_tid, mutex.name))

        for tid in adj:
            adj[tid].sort(key=lambda edge: (edge[0], edge[1]))

        cycles: List[List[str]] = []
        nodes = sorted(adj.keys())

        # Johnson-style canonical DFS from minimum TID per cycle for deterministic deduplication
        for start_tid in nodes:
            blocked: Set[int] = set()
            block_map: Dict[int, Set[int]] = defaultdict(set)
            edge_stack: List[Tuple[int, int, str]] = []

            def unblock(node: int) -> None:
                stack = [node]
                while stack:
                    curr = stack.pop()
                    if curr in blocked:
                        blocked.remove(curr)
                        for dep in block_map.get(curr, ()):
                            if dep in blocked:
                                stack.append(dep)
                        block_map.pop(curr, None)

            def dfs(curr: int) -> bool:
                found_cycle = False
                blocked.add(curr)
                for nxt, mutex_name in adj.get(curr, ()):
                    if nxt < start_tid:
                        continue
                    if nxt == start_tid:
                        cycle_edges = edge_stack + [(curr, nxt, mutex_name)]
                        cycles.append(
                            [
                                f"{self._format_thread_label(u)} -> Mutex:{m} -> {self._format_thread_label(v)}"
                                for u, v, m in cycle_edges
                            ]
                        )
                        found_cycle = True
                    elif nxt not in blocked:
                        edge_stack.append((curr, nxt, mutex_name))
                        if dfs(nxt):
                            found_cycle = True
                        edge_stack.pop()
                if found_cycle:
                    unblock(curr)
                else:
                    for nxt, _ in adj.get(curr, ()):
                        if nxt >= start_tid:
                            block_map[nxt].add(curr)
                return found_cycle

            dfs(start_tid)

        cycles.extend(special_deadlocks)
        return cycles

    def check_no_progress(
        self,
        has_ready: bool,
        has_running: bool,
        has_pending_events: bool,
    ) -> Optional[Dict[str, Any]]:
        """Diagnose deadlock or no-progress stall when CPU/ready/events are idle with blocked threads."""
        if has_ready or has_running or has_pending_events:
            return None

        blocked_threads = [
            thread
            for thread in self.process_manager.list_threads(active_only=True)
            if self.process_manager.state_machine.normalize_state(thread.state) == ProcessState.BLOCKED
        ]
        if not blocked_threads:
            return None

        cycles = self.detect_deadlocks()
        blocked_info = [
            {
                "tid": t.tid,
                "pid": t.pid,
                "name": t.name,
                "block_reason": t.block_reason.value,
                "blocked_on": t.blocked_on,
            }
            for t in blocked_threads
        ]

        if cycles:
            formatted_cycles = " | ".join(" ; ".join(c) for c in cycles)
            return {
                "stalled": True,
                "type": "DEADLOCK",
                "deadlock_detected": True,
                "cycles": cycles,
                "blocked_threads": blocked_info,
                "blocked_tids": [t.tid for t in blocked_threads],
                "message": (
                    f"Sem progresso (Deadlock): {len(blocked_threads)} thread(s) bloqueada(s) "
                    f"sem threads prontas ou eventos pendentes. Ciclos: {formatted_cycles}"
                ),
            }

        wait_details = ", ".join(
            f"TID:{t.tid}({t.name})[{t.block_reason.value}:{t.blocked_on or '-'}]"
            for t in blocked_threads
        )
        return {
            "stalled": True,
            "type": "STALL",
            "deadlock_detected": False,
            "cycles": [],
            "blocked_threads": blocked_info,
            "blocked_tids": [t.tid for t in blocked_threads],
            "message": (
                f"Estagnação da simulação (No-Progress): {len(blocked_threads)} thread(s) bloqueada(s) "
                f"sem eventos de desbloqueio pendentes: {wait_details}"
            ),
        }

    def setup_buffer_video_scenario(
        self,
        process_manager: Optional[ProcessManager] = None,
        mutex_name: str = "Buffer_Video",
        process_name: str = "Player_Video",
        size_bytes: int = 8192,
        priority: int = 2,
        t1_burst_ms: int = 8,
        t2_burst_ms: int = 8,
        lock_at_cpu_ms: int = 1,
        unlock_at_cpu_ms: int = 6,
        arrival_time_ms: int = 0,
        initial_state: ProcessState = ProcessState.READY,
        replace_existing: bool = False,
    ) -> Dict[str, Any]:
        """Build the Buffer_Video producer/consumer contention scenario with Player_Video (T1, T2)."""
        target_pm = process_manager or self.process_manager

        if min(t1_burst_ms, t2_burst_ms) <= 0:
            raise ValueError("Bursts de T1 e T2 devem ser maiores que zero.")
        if lock_at_cpu_ms < 0 or unlock_at_cpu_ms <= lock_at_cpu_ms:
            raise ValueError("Janela crítica inválida: lock_at_cpu_ms deve ser >= 0 e < unlock_at_cpu_ms.")
        if unlock_at_cpu_ms >= min(t1_burst_ms, t2_burst_ms):
            raise ValueError("unlock_at_cpu_ms deve ser menor que o burst de T1 e T2.")

        if replace_existing and process_name in target_pm.name_to_pid:
            existing_pid = target_pm.name_to_pid[process_name]
            existing_proc = target_pm.processes.get(existing_pid)
            if existing_proc is not None and existing_proc.state != ProcessState.TERMINATED:
                for thread in existing_proc.threads.values():
                    self.release_all_for_thread(thread.tid, timestamp_ms=arrival_time_ms)
                target_pm.terminate_process(
                    existing_pid,
                    timestamp_ms=arrival_time_ms,
                    reason="Reset cenário Buffer_Video",
                )

        mutex = self.get_or_create_mutex(mutex_name)
        process = target_pm.create_process(
            name=process_name,
            size_bytes=size_bytes,
            process_type=ProcessType.NORMAL,
            priority=priority,
            cpu_burst_ms=0,
            arrival_time_ms=arrival_time_ms,
            initial_state=initial_state,
            create_default_thread=False,
        )

        created_threads: List[SimulatedThread] = []
        for thread_name, burst_ms in (("T1", t1_burst_ms), ("T2", t2_burst_ms)):
            steps = [
                WorkloadStep(
                    trigger_cpu_ms=lock_at_cpu_ms,
                    syscall_type=SyscallType.MUTEX_LOCK,
                    mutex_name=mutex.name,
                ),
                WorkloadStep(
                    trigger_cpu_ms=unlock_at_cpu_ms,
                    syscall_type=SyscallType.MUTEX_UNLOCK,
                    mutex_name=mutex.name,
                ),
            ]
            created_threads.append(
                target_pm.create_thread(
                    process_identifier=process,
                    name=thread_name,
                    priority=priority,
                    cpu_burst_ms=burst_ms,
                    arrival_time_ms=arrival_time_ms,
                    initial_state=initial_state,
                    workload_steps=steps,
                )
            )
        t1, t2 = created_threads

        return {
            "mutex": mutex,
            "process": process,
            "threads": [t1, t2],
            "t1": t1,
            "t2": t2,
        }

    def get_status(self) -> Dict[str, Any]:
        """Return structured synchronization diagnostics and detected deadlock cycles."""
        return {
            "mutex_count": len(self.mutexes),
            "mutexes": [m.to_dict() for m in self.mutexes.values()],
            "deadlocks": self.detect_deadlocks(),
        }

    def format_status(self) -> str:
        """Render Portuguese diagnostic report of all mutexes, FIFO queues, and deadlocks."""
        lines = ["=== STATUS DE SINCRONIZAÇÃO (MUTEXES) ==="]
        if not self.mutexes:
            lines.append("Nenhum mutex registrado no subsistema de sincronização.")
            return "\n".join(lines)

        for mutex in self.mutexes.values():
            estado = "TRAVADO" if mutex.locked else "LIVRE"
            if mutex.locked and mutex.owner_tid is not None:
                owner_label = self._format_thread_label(mutex.owner_tid)
                dono_str = f"{owner_label} (PID {mutex.owner_pid})"
            else:
                dono_str = "Nenhum"

            if mutex.wait_queue:
                fila_str = " -> ".join(self._format_thread_label(tid) for tid in mutex.wait_queue)
            else:
                fila_str = "Vazia"

            lines.append(
                f"Mutex '{mutex.name}' | Estado: {estado} | Dono: {dono_str}\n"
                f"  Fila de Espera (FIFO): [{fila_str}]\n"
                f"  Métricas: aquisições={mutex.acquire_count}, liberações={mutex.release_count}, "
                f"contenções={mutex.contention_count}"
            )

        cycles = self.detect_deadlocks()
        if cycles:
            lines.append("ALERTA DE DEADLOCK (Grafo Wait-For):")
            for idx, cycle in enumerate(cycles, start=1):
                lines.append(f"  Ciclo #{idx}: {' ; '.join(cycle)}")
        else:
            lines.append("Deadlocks detectados: Nenhum.")

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all registered mutexes and synchronization history."""
        self.mutexes.clear()
        self.history.clear()
