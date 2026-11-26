"""Lifecycle state machine and transition validation for processes and threads."""

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, Union

from os_simulator.core.exceptions import InvalidStateTransitionException
from os_simulator.core.types import ProcessState


@dataclass(frozen=True)
class StateTransitionRecord:
    """Immutable record of a validated process or thread state transition."""

    entity_id: str
    timestamp_ms: int
    from_state: ProcessState
    to_state: ProcessState
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize transition record to dictionary."""
        return {
            "entity_id": self.entity_id,
            "timestamp_ms": self.timestamp_ms,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason,
        }


class ProcessStateMachine:
    """Enforces the 5-state process/thread lifecycle and tracks transition history."""

    VALID_TRANSITIONS: Dict[ProcessState, FrozenSet[ProcessState]] = {
        ProcessState.NEW: frozenset({ProcessState.READY, ProcessState.TERMINATED}),
        ProcessState.READY: frozenset({ProcessState.RUNNING, ProcessState.TERMINATED}),
        ProcessState.RUNNING: frozenset({ProcessState.READY, ProcessState.BLOCKED, ProcessState.TERMINATED}),
        ProcessState.BLOCKED: frozenset({ProcessState.READY, ProcessState.TERMINATED}),
        ProcessState.TERMINATED: frozenset(),
    }

    def __init__(self) -> None:
        self._history: List[StateTransitionRecord] = []

    @staticmethod
    def normalize_state(state: Union[ProcessState, str]) -> ProcessState:
        """Normalize state value (including Portuguese aliases and legacy WAITING -> BLOCKED)."""
        if isinstance(state, ProcessState):
            parsed = state
        else:
            parsed = ProcessState.from_string(str(state))
        return ProcessState.normalize(parsed)

    def can_transition(
        self,
        from_state: Union[ProcessState, str],
        to_state: Union[ProcessState, str],
    ) -> bool:
        """Return True if transitioning from from_state to to_state is valid."""
        src = self.normalize_state(from_state)
        dst = self.normalize_state(to_state)
        if src == dst:
            return False
        return dst in self.VALID_TRANSITIONS.get(src, frozenset())

    def validate_transition(
        self,
        from_state: Union[ProcessState, str],
        to_state: Union[ProcessState, str],
        entity_id: Optional[str] = None,
    ) -> Tuple[ProcessState, ProcessState]:
        """Validate transition and return normalized (src, dst), or raise InvalidStateTransitionException."""
        src = self.normalize_state(from_state)
        dst = self.normalize_state(to_state)
        target_label = f" para '{entity_id}'" if entity_id else ""

        if src == dst:
            raise InvalidStateTransitionException(
                f"Auto-transição de estado inválida{target_label}: '{src.value}' -> '{dst.value}'.",
                from_state=src.value,
                to_state=dst.value,
                entity_id=entity_id,
            )

        if dst not in self.VALID_TRANSITIONS.get(src, frozenset()):
            raise InvalidStateTransitionException(
                f"Transição de estado inválida{target_label}: '{src.value}' -> '{dst.value}'.",
                from_state=src.value,
                to_state=dst.value,
                entity_id=entity_id,
            )
        return src, dst

    @staticmethod
    def _resolve_entity_id(entity: Any, explicit_id: Optional[str]) -> str:
        if explicit_id is not None:
            return explicit_id
        if hasattr(entity, "tid"):
            return f"TID:{entity.tid}"
        if hasattr(entity, "pid"):
            return f"PID:{entity.pid}"
        return str(entity)

    def transition(
        self,
        entity: Any,
        to_state: Union[ProcessState, str],
        timestamp_ms: int = 0,
        reason: str = "",
        entity_id: Optional[str] = None,
    ) -> StateTransitionRecord:
        """Validate, apply state change on entity (.state), and record history."""
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
            raise ValueError(f"timestamp_ms inválido: {timestamp_ms!r}")

        eid = self._resolve_entity_id(entity, entity_id)
        src, dst = self.validate_transition(entity.state, to_state, entity_id=eid)
        entity.state = dst
        record = StateTransitionRecord(
            entity_id=eid,
            timestamp_ms=timestamp_ms,
            from_state=src,
            to_state=dst,
            reason=reason,
        )
        self._history.append(record)
        return record

    def record_transition(
        self,
        entity_id: str,
        from_state: Union[ProcessState, str],
        to_state: Union[ProcessState, str],
        timestamp_ms: int = 0,
        reason: str = "",
    ) -> StateTransitionRecord:
        """Validate and record a transition without mutating an external object."""
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
            raise ValueError(f"timestamp_ms inválido: {timestamp_ms!r}")

        src, dst = self.validate_transition(from_state, to_state, entity_id=entity_id)
        record = StateTransitionRecord(
            entity_id=entity_id,
            timestamp_ms=timestamp_ms,
            from_state=src,
            to_state=dst,
            reason=reason,
        )
        self._history.append(record)
        return record

    @property
    def history(self) -> List[StateTransitionRecord]:
        """Return a copy of all recorded state transitions."""
        return list(self._history)

    def get_history(self, entity_id: Optional[str] = None) -> List[StateTransitionRecord]:
        """Return transition history, optionally filtered by entity_id."""
        if entity_id is None:
            return list(self._history)
        return [rec for rec in self._history if rec.entity_id == entity_id]

    def clear_history(self) -> None:
        """Clear transition history."""
        self._history.clear()
