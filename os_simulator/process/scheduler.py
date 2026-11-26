"""Combined preemptive priority and per-level Round-Robin CPU scheduler."""

from collections import deque
from typing import Any, Deque, Dict, Iterable, List, Optional

from os_simulator.core.exceptions import SchedulerException
from os_simulator.core.types import ProcessState
from os_simulator.process.manager import ProcessManager
from os_simulator.process.thread import SimulatedThread


class PriorityRoundRobinScheduler:
    """Multi-level preemptive priority CPU scheduler with Round-Robin per priority level.

    Priority level ``1`` is the highest priority, while larger integer numbers represent
    lower priorities. Each priority level maintains a FIFO ``deque`` of ready TIDs
    rotated whenever a running thread exhausts its configurable time quantum.
    """

    DEFAULT_PRIORITIES: tuple[int, ...] = (1, 2, 3, 4, 5)

    def __init__(
        self,
        process_manager: ProcessManager,
        quantum_ms: int = 4,
        context_switch_overhead_ms: int = 0,
        default_priorities: Iterable[int] = DEFAULT_PRIORITIES,
    ) -> None:
        if process_manager is None:
            raise SchedulerException("ProcessManager é obrigatório para inicializar o escalonador.")

        self.process_manager: ProcessManager = process_manager
        self.quantum_ms: int = 4
        self.context_switch_overhead_ms: int = 0
        self.set_quantum(quantum_ms)
        self.set_context_switch_overhead(context_switch_overhead_ms)

        priorities = sorted({self._validate_priority(p) for p in default_priorities})
        if not priorities:
            priorities = list(self.DEFAULT_PRIORITIES)
        self._default_priorities: tuple[int, ...] = tuple(priorities)

        self.queues: Dict[int, Deque[int]] = {prio: deque() for prio in self._default_priorities}
        self.running_tid: Optional[int] = None
        self.last_dispatched_tid: Optional[int] = None

        self.dispatches_total: int = 0
        self.context_switches_total: int = 0
        self.preemptions_total: int = 0
        self.quantum_expirations_total: int = 0

    @staticmethod
    def _validate_priority(priority: int) -> int:
        if isinstance(priority, bool) or not isinstance(priority, int) or priority < 1:
            raise SchedulerException(
                f"Prioridade inválida: deve ser inteiro >= 1 (recebido: {priority!r})."
            )
        return priority

    @staticmethod
    def _validate_non_negative_int(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"{field_name} deve ser um inteiro >= 0 (recebido: {value!r})."
            )
        return value

    def set_quantum(self, quantum_ms: int) -> None:
        """Configure the Round-Robin time slice in integer milliseconds (>= 1)."""
        if isinstance(quantum_ms, bool) or not isinstance(quantum_ms, int) or quantum_ms < 1:
            raise SchedulerException(
                f"Quantum inválido: deve ser um inteiro >= 1 ms (recebido: {quantum_ms!r})."
            )
        self.quantum_ms = quantum_ms

    def set_context_switch_overhead(self, overhead_ms: int) -> None:
        """Configure simulated context switch overhead in milliseconds (>= 0)."""
        if isinstance(overhead_ms, bool) or not isinstance(overhead_ms, int) or overhead_ms < 0:
            raise SchedulerException(
                f"Overhead de troca de contexto inválido: deve ser inteiro >= 0 ms (recebido: {overhead_ms!r})."
            )
        self.context_switch_overhead_ms = overhead_ms

    def _sync_running_state(self) -> Optional[SimulatedThread]:
        """Return currently running thread, clearing stale running_tid if suspended/terminated."""
        if self.running_tid is None:
            return None
        thread = self.process_manager.threads.get(self.running_tid)
        if thread is None or ProcessState.normalize(thread.state) != ProcessState.RUNNING:
            self.running_tid = None
            return None
        return thread

    def _remove_tid_from_queues(self, tid: int) -> bool:
        """Remove all occurrences of tid from all ready queues without touching running_tid."""
        removed = False
        for queue in self.queues.values():
            if tid in queue:
                filtered = deque(item for item in queue if item != tid)
                queue.clear()
                queue.extend(filtered)
                removed = True
        return removed

    def _prune_queues(self) -> None:
        """Remove non-READY, running, missing, or duplicate TIDs from ready queues."""
        active_running = self._sync_running_state()
        running_tid = active_running.tid if active_running is not None else None
        seen_tids: set[int] = set()
        misplaced: List[SimulatedThread] = []

        for prio in sorted(self.queues.keys()):
            queue = self.queues[prio]
            cleaned: Deque[int] = deque()
            for tid in queue:
                if tid in seen_tids or tid == running_tid:
                    continue
                thread = self.process_manager.threads.get(tid)
                if thread is None:
                    continue
                if ProcessState.normalize(thread.state) != ProcessState.READY:
                    continue
                seen_tids.add(tid)
                if thread.priority != prio:
                    misplaced.append(thread)
                else:
                    cleaned.append(tid)
            queue.clear()
            queue.extend(cleaned)

        for thread in misplaced:
            target_prio = self._validate_priority(thread.priority)
            self.queues.setdefault(target_prio, deque()).append(thread.tid)

    def _append_ready_tid(self, thread: SimulatedThread) -> None:
        """Insert a READY thread's TID at the tail of its priority queue without duplication."""
        prio = self._validate_priority(thread.priority)
        target_queue = self.queues.setdefault(prio, deque())
        for existing_prio, queue in self.queues.items():
            if existing_prio != prio and thread.tid in queue:
                filtered = deque(item for item in queue if item != thread.tid)
                queue.clear()
                queue.extend(filtered)
        if thread.tid not in target_queue:
            target_queue.append(thread.tid)

    def enqueue_ready(
        self,
        thread: SimulatedThread,
        timestamp_ms: int = 0,
    ) -> Optional[SimulatedThread]:
        """Insert a READY thread into its priority queue, preempting a lower-priority runner if any.

        Args:
            thread: Simulated thread in READY state to enqueue.
            timestamp_ms: Current logical clock timestamp in milliseconds.

        Returns:
            The preempted ``SimulatedThread`` if preemption occurred, otherwise ``None``.

        Raises:
            SchedulerException: If the thread is invalid, unregistered, or not in READY state.
            ValueError: If ``timestamp_ms`` is not a non-negative integer.
        """
        ts = self._validate_non_negative_int(timestamp_ms, "timestamp_ms")
        if not isinstance(thread, SimulatedThread):
            raise SchedulerException("Objeto inválido informado ao escalonador: esperado SimulatedThread.")
        if thread.tid not in self.process_manager.threads:
            raise SchedulerException(
                f"Thread TID {thread.tid} ('{thread.name}') não está registrada no ProcessManager."
            )

        self._prune_queues()
        norm_state = ProcessState.normalize(thread.state)
        if norm_state != ProcessState.READY:
            self._remove_tid_from_queues(thread.tid)
            raise SchedulerException(
                f"Apenas threads no estado READY podem entrar na fila de prontos "
                f"(TID {thread.tid} está em '{norm_state.value}')."
            )

        self._append_ready_tid(thread)

        running = self._sync_running_state()
        if running is not None and running.priority > thread.priority:
            return self.preempt_current(
                timestamp_ms=ts,
                reason=(
                    f"Preempção por prioridade (TID {thread.tid} prio {thread.priority} "
                    f"sobrepõe TID {running.tid} prio {running.priority})"
                ),
            )
        return None

    def remove(self, tid: int) -> bool:
        """Remove a TID from all ready queues and clear ``running_tid`` if it matches."""
        if isinstance(tid, bool) or not isinstance(tid, int):
            return False
        removed = self._remove_tid_from_queues(tid)
        if self.running_tid == tid:
            self.running_tid = None
            removed = True
        return removed

    def select_next(self) -> Optional[SimulatedThread]:
        """Inspect priority queues in ascending order and return the head READY thread without side effects."""
        self._prune_queues()
        for prio in sorted(self.queues.keys()):
            queue = self.queues[prio]
            if queue:
                return self.process_manager.threads.get(queue[0])
        return None

    def dispatch_next(self, timestamp_ms: int = 0) -> Optional[SimulatedThread]:
        """Pop the highest-priority READY thread, transition it to RUNNING, and update switch stats."""
        ts = self._validate_non_negative_int(timestamp_ms, "timestamp_ms")
        active = self._sync_running_state()
        if active is not None:
            raise SchedulerException(
                f"Não é possível despachar nova thread enquanto TID {active.tid} ('{active.name}') está RUNNING."
            )

        self._prune_queues()
        next_thread: Optional[SimulatedThread] = None
        for prio in sorted(self.queues.keys()):
            queue = self.queues[prio]
            while queue:
                tid = queue.popleft()
                candidate = self.process_manager.threads.get(tid)
                if candidate is not None and ProcessState.normalize(candidate.state) == ProcessState.READY:
                    next_thread = candidate
                    break
            if next_thread is not None:
                break

        if next_thread is None:
            return None

        self.process_manager.transition_thread_state(
            next_thread,
            ProcessState.RUNNING,
            timestamp_ms=ts,
            reason="Escalonamento de CPU (Dispatch)",
        )
        next_thread.quantum_used_ms = 0
        self.running_tid = next_thread.tid
        self.dispatches_total += 1

        if self.last_dispatched_tid is not None and next_thread.tid != self.last_dispatched_tid:
            self.context_switches_total += 1
        self.last_dispatched_tid = next_thread.tid
        return next_thread

    def tick_quantum(self, delta_ms: int = 1) -> bool:
        """Increment ``quantum_used_ms`` on the active runner and return True if ``>= quantum_ms``."""
        if isinstance(delta_ms, bool) or not isinstance(delta_ms, int) or delta_ms < 0:
            raise SchedulerException(
                f"Incremento de quantum inválido: deve ser inteiro >= 0 ms (recebido: {delta_ms!r})."
            )
        running = self._sync_running_state()
        if running is None:
            return False
        running.quantum_used_ms += delta_ms
        return running.quantum_used_ms >= self.quantum_ms

    def on_quantum_expired(self, timestamp_ms: int = 0) -> Optional[SimulatedThread]:
        """Rotate the currently running thread back to the tail of its priority queue."""
        ts = self._validate_non_negative_int(timestamp_ms, "timestamp_ms")
        running = self._sync_running_state()
        if running is None:
            return None

        self.process_manager.transition_thread_state(
            running,
            ProcessState.READY,
            timestamp_ms=ts,
            reason="Expiração de quantum (Round-Robin)",
        )
        running.quantum_used_ms = 0
        self._append_ready_tid(running)
        self.quantum_expirations_total += 1
        self.running_tid = None
        return running

    def preempt_current(
        self,
        timestamp_ms: int = 0,
        reason: str = "Preempção por prioridade",
    ) -> Optional[SimulatedThread]:
        """Preempt the currently running thread (RUNNING -> READY) and append it to its queue tail."""
        ts = self._validate_non_negative_int(timestamp_ms, "timestamp_ms")
        running = self._sync_running_state()
        if running is None:
            return None

        self.process_manager.transition_thread_state(
            running,
            ProcessState.READY,
            timestamp_ms=ts,
            reason=reason,
        )
        running.quantum_used_ms = 0
        self._append_ready_tid(running)
        self.preemptions_total += 1
        self.running_tid = None
        return running

    def on_current_suspended(self) -> None:
        """Clear ``running_tid`` when the active thread becomes BLOCKED or TERMINATED.

        Preserves ``last_dispatched_tid`` so subsequent dispatches accurately account for
        thread-to-thread context switches.
        """
        if self.running_tid is not None:
            self._remove_tid_from_queues(self.running_tid)
            self.running_tid = None

    def get_running_thread(self) -> Optional[SimulatedThread]:
        """Return the currently running ``SimulatedThread``, or ``None`` if CPU is idle."""
        return self._sync_running_state()

    def get_ready_queues(self) -> Dict[int, List[SimulatedThread]]:
        """Return a snapshot mapping each priority level to its ordered list of READY threads."""
        self._prune_queues()
        snapshot: Dict[int, List[SimulatedThread]] = {}
        for prio in sorted(self.queues.keys()):
            snapshot[prio] = [
                self.process_manager.threads[tid]
                for tid in self.queues[prio]
                if tid in self.process_manager.threads
            ]
        return snapshot

    def get_ready_list(self) -> List[SimulatedThread]:
        """Return a flat list of all READY threads in dispatch order (priority asc, FIFO)."""
        queues = self.get_ready_queues()
        ordered: List[SimulatedThread] = []
        for prio in sorted(queues.keys()):
            ordered.extend(queues[prio])
        return ordered

    def is_ready_empty(self) -> bool:
        """Return True when no READY threads remain in any priority queue."""
        self._prune_queues()
        return all(len(queue) == 0 for queue in self.queues.values())

    def get_stats(self) -> Dict[str, Any]:
        """Return scheduler counters and current queue occupancy summary."""
        self._prune_queues()
        active = self._sync_running_state()
        return {
            "quantum_ms": self.quantum_ms,
            "context_switch_overhead_ms": self.context_switch_overhead_ms,
            "running_tid": active.tid if active is not None else None,
            "last_dispatched_tid": self.last_dispatched_tid,
            "dispatches_total": self.dispatches_total,
            "context_switches_total": self.context_switches_total,
            "preemptions_total": self.preemptions_total,
            "quantum_expirations_total": self.quantum_expirations_total,
            "ready_count": sum(len(q) for q in self.queues.values()),
            "ready_queues": {prio: list(q) for prio, q in sorted(self.queues.items())},
        }

    def reset(self) -> None:
        """Clear all queues, running/last-dispatched state, and counters while preserving config."""
        self.queues = {prio: deque() for prio in self._default_priorities}
        self.running_tid = None
        self.last_dispatched_tid = None
        self.dispatches_total = 0
        self.context_switches_total = 0
        self.preemptions_total = 0
        self.quantum_expirations_total = 0

    def format_queues(self) -> str:
        """Format current scheduler queues, running thread, and counters in Portuguese."""
        queues = self.get_ready_queues()
        running = self._sync_running_state()

        lines = [
            "======================================================================",
            "        FILAS DO ESCALONADOR DE CPU (PRIORIDADE + ROUND-ROBIN)        ",
            "======================================================================",
            f"Quantum configurado          : {self.quantum_ms} ms",
            f"Overhead troca de contexto   : {self.context_switch_overhead_ms} ms",
        ]
        if running is not None:
            lines.append(
                f"Thread em Execução (RUNNING) : TID {running.tid} '{running.name}' "
                f"(PID {running.pid}, Prio {running.priority}, "
                f"Quantum {running.quantum_used_ms}/{self.quantum_ms} ms, "
                f"Restante {running.remaining_burst_ms} ms)"
            )
        else:
            lines.append("Thread em Execução (RUNNING) : Nenhuma (CPU ociosa)")

        lines.append("----------------------------------------------------------------------")
        lines.append("Filas de Prontos (1 = maior prioridade):")
        for prio in sorted(queues.keys()):
            threads = queues[prio]
            if threads:
                items = ", ".join(
                    f"TID:{t.tid} {t.name} (PID {t.pid}, Restante {t.remaining_burst_ms}ms)"
                    for t in threads
                )
                lines.append(f"  Prioridade {prio}: [{items}]")
            else:
                lines.append(f"  Prioridade {prio}: [vazia]")

        lines.extend([
            "----------------------------------------------------------------------",
            (
                f"Despachos: {self.dispatches_total} | "
                f"Trocas de Contexto: {self.context_switches_total} | "
                f"Preempções: {self.preemptions_total} | "
                f"Expirações de Quantum: {self.quantum_expirations_total}"
            ),
            "======================================================================",
        ])
        return "\n".join(lines)
