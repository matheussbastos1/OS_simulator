"""Deterministic discrete-event queue and priority tie-breaking for Stage 5 simulation."""

from dataclasses import dataclass, field
import heapq
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from os_simulator.core.clock import LogicalClock
from os_simulator.core.types import SimulationEventType


EVENT_PRIORITY_MAP: Dict[SimulationEventType, int] = {
    SimulationEventType.PROCESS_TERMINATED: 0,
    SimulationEventType.IO_COMPLETION: 1,
    SimulationEventType.MUTEX_WAKEUP: 2,
    SimulationEventType.SLEEP_WAKEUP: 2,
    SimulationEventType.PROCESS_ARRIVAL: 3,
    SimulationEventType.THREAD_ARRIVAL: 3,
    SimulationEventType.QUANTUM_EXPIRE: 4,
    SimulationEventType.SYSCALL_REQUEST: 5,
    SimulationEventType.DISPATCH_RESCHEDULE: 6,
}


@dataclass
class SimulationEvent:
    """Discrete simulation event scheduled at a logical millisecond timestamp."""

    timestamp_ms: int
    priority: int
    seq: int
    event_type: SimulationEventType
    pid: Optional[int] = None
    tid: Optional[int] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False

    @property
    def sort_key(self) -> Tuple[int, int, int]:
        """Deterministic heap ordering key: (timestamp_ms, priority, seq)."""
        return (self.timestamp_ms, self.priority, self.seq)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize event metadata to dictionary."""
        return {
            "timestamp_ms": self.timestamp_ms,
            "priority": self.priority,
            "seq": self.seq,
            "event_type": self.event_type.value,
            "pid": self.pid,
            "tid": self.tid,
            "payload": dict(self.payload),
            "cancelled": self.cancelled,
        }


class EventManager:
    """Priority min-heap discrete-event manager with deterministic tie-breaking."""

    def __init__(self, clock: Optional[LogicalClock] = None) -> None:
        self._clock = clock
        self._heap: List[Tuple[int, int, int, SimulationEvent]] = []
        self._events_by_seq: Dict[int, SimulationEvent] = {}
        self._next_seq: int = 1

    @staticmethod
    def _validate_non_negative_int(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name} deve ser um inteiro em milissegundos (recebido: {value!r}).")
        if value < 0:
            raise ValueError(f"{field_name} não pode ser negativo (recebido: {value}).")
        return value

    @staticmethod
    def _normalize_event_type(event_type: Union[SimulationEventType, str]) -> SimulationEventType:
        if isinstance(event_type, SimulationEventType):
            return event_type
        return SimulationEventType(str(event_type).strip().upper())

    def schedule_at(
        self,
        timestamp_ms: int,
        event_type: Union[SimulationEventType, str],
        pid: Optional[int] = None,
        tid: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
        priority: Optional[int] = None,
    ) -> SimulationEvent:
        """Schedule an event at an absolute logical timestamp_ms >= 0."""
        ts = self._validate_non_negative_int(timestamp_ms, "timestamp_ms")
        ev_type = self._normalize_event_type(event_type)
        if priority is None:
            prio = EVENT_PRIORITY_MAP[ev_type]
        else:
            if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0:
                raise ValueError(f"Prioridade de evento inválida: {priority!r}")
            prio = priority

        seq = self._next_seq
        self._next_seq += 1

        event = SimulationEvent(
            timestamp_ms=ts,
            priority=prio,
            seq=seq,
            event_type=ev_type,
            pid=pid,
            tid=tid,
            payload=dict(payload) if payload is not None else {},
            cancelled=False,
        )
        heapq.heappush(self._heap, (ts, prio, seq, event))
        self._events_by_seq[seq] = event
        return event

    def schedule(
        self,
        delay_ms: int,
        event_type: Union[SimulationEventType, str],
        pid: Optional[int] = None,
        tid: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
        now_ms: Optional[int] = None,
        priority: Optional[int] = None,
    ) -> SimulationEvent:
        """Schedule an event after delay_ms >= 0 relative to now_ms or attached clock."""
        delay = self._validate_non_negative_int(delay_ms, "delay_ms")
        if now_ms is not None:
            base = self._validate_non_negative_int(now_ms, "now_ms")
        elif self._clock is not None:
            base = self._clock.now_ms
        else:
            base = 0
        return self.schedule_at(
            timestamp_ms=base + delay,
            event_type=event_type,
            pid=pid,
            tid=tid,
            payload=payload,
            priority=priority,
        )

    def cancel_event(self, seq: int) -> bool:
        """Cancel a pending event by its monotonic sequence ID."""
        ev = self._events_by_seq.get(seq)
        if ev is None or ev.cancelled:
            return False
        ev.cancelled = True
        return True

    def cancel_for_entity(
        self,
        pid: Optional[int] = None,
        tid: Optional[int] = None,
        event_types: Optional[Iterable[Union[SimulationEventType, str]]] = None,
    ) -> int:
        """Cancel all pending events matching pid/tid and optional event_types filter."""
        if pid is None and tid is None and event_types is None:
            return 0

        type_filter: Optional[set[SimulationEventType]] = None
        if event_types is not None:
            type_filter = {self._normalize_event_type(et) for et in event_types}

        cancelled_count = 0
        for ev in self._events_by_seq.values():
            if ev.cancelled:
                continue
            if pid is not None and ev.pid != pid:
                continue
            if tid is not None and ev.tid != tid:
                continue
            if type_filter is not None and ev.event_type not in type_filter:
                continue
            ev.cancelled = True
            cancelled_count += 1
        return cancelled_count

    def _prune_cancelled_top(self) -> None:
        while self._heap and self._heap[0][3].cancelled:
            _, _, seq, _ = heapq.heappop(self._heap)
            self._events_by_seq.pop(seq, None)

    def peek_next(self) -> Optional[SimulationEvent]:
        """Return the next non-cancelled event without removing it."""
        self._prune_cancelled_top()
        if not self._heap:
            return None
        return self._heap[0][3]

    def pop_next(self) -> Optional[SimulationEvent]:
        """Remove and return the next non-cancelled event in deterministic order."""
        self._prune_cancelled_top()
        if not self._heap:
            return None
        _, _, seq, event = heapq.heappop(self._heap)
        self._events_by_seq.pop(seq, None)
        return event

    def pop_ready_at(self, now_ms: int) -> List[SimulationEvent]:
        """Pop all non-cancelled events with timestamp_ms <= now_ms in deterministic order."""
        limit = self._validate_non_negative_int(now_ms, "now_ms")
        ready: List[SimulationEvent] = []
        while True:
            nxt = self.peek_next()
            if nxt is None or nxt.timestamp_ms > limit:
                break
            popped = self.pop_next()
            if popped is not None:
                ready.append(popped)
        return ready

    def is_empty(self) -> bool:
        """Return True when no non-cancelled events remain pending."""
        self._prune_cancelled_top()
        return len(self._heap) == 0

    def pending_events(self) -> List[SimulationEvent]:
        """Return all pending non-cancelled events ordered by (timestamp_ms, priority, seq)."""
        active = [ev for ev in self._events_by_seq.values() if not ev.cancelled]
        active.sort(key=lambda ev: ev.sort_key)
        return active

    def clear(self) -> None:
        """Discard all scheduled events and reset sequence counter."""
        self._heap.clear()
        self._events_by_seq.clear()
        self._next_seq = 1

    def __len__(self) -> int:
        return sum(1 for ev in self._events_by_seq.values() if not ev.cancelled)
