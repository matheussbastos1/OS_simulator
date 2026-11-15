"""Thread-safe structured Audit Log for security events."""

from __future__ import annotations

import datetime
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from os_simulator.core.types import AuditEventType


@dataclass
class AuditEvent:
    """Represents an individual immutable security audit record."""
    timestamp: float = field(default_factory=time.time)
    event_type: AuditEventType = AuditEventType.ACCESS_GRANTED
    username: str = "anonymous"
    path: Optional[str] = None
    action: str = ""
    result: str = "SUCCESS"  # "SUCCESS", "FAILURE", "DENIED", "ALERT"
    details: Dict[str, Any] = field(default_factory=dict)

    def formatted_time(self) -> str:
        """Format timestamp as standard ISO-like local date string."""
        dt = datetime.datetime.fromtimestamp(self.timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to serializable dictionary."""
        return {
            "timestamp": self.timestamp,
            "formatted_time": self.formatted_time(),
            "event_type": self.event_type.value if isinstance(self.event_type, AuditEventType) else str(self.event_type),
            "username": self.username,
            "path": self.path,
            "action": self.action,
            "result": self.result,
            "details": dict(self.details),
        }

    def format_line(self) -> str:
        """Format a single audit line for console inspection."""
        type_str = self.event_type.value if isinstance(self.event_type, AuditEventType) else str(self.event_type)
        res_str = self.path or "-"
        act_str = f"[{self.action}]" if self.action else ""
        detail_items = []
        for k, v in self.details.items():
            detail_items.append(f"{k}={v}")
        detail_str = f" ({', '.join(detail_items)})" if detail_items else ""
        return f"{self.formatted_time()} | {type_str:<19} | {self.username:<10} | {self.result:<7} | {res_str} {act_str}{detail_str}".strip()


class AuditLog:
    """Thread-safe, in-memory structured audit trail."""

    def __init__(self, max_entries: Optional[int] = None) -> None:
        self._events: List[AuditEvent] = []
        self._lock = threading.RLock()
        self._max_entries = max_entries

    def record(self, event: AuditEvent) -> AuditEvent:
        """Append an AuditEvent to the log safely."""
        with self._lock:
            self._events.append(event)
            if self._max_entries is not None and len(self._events) > self._max_entries:
                self._events.pop(0)
            return event

    def log_event(
        self,
        event_type: Union[AuditEventType, str],
        username: str,
        path: Optional[str] = None,
        action: str = "",
        result: str = "SUCCESS",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Create and record a structured audit event."""
        if isinstance(event_type, str):
            try:
                ev_type = AuditEventType(event_type.upper())
            except ValueError:
                # Custom or unrecognized event types are preserved
                ev_type = event_type  # type: ignore
        else:
            ev_type = event_type

        event = AuditEvent(
            timestamp=time.time(),
            event_type=ev_type,
            username=username,
            path=path,
            action=action,
            result=result,
            details=details or {},
        )
        return self.record(event)

    def log_access_granted(
        self,
        username: str,
        path: Optional[str] = None,
        action: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Convenience helper for authorized access events."""
        return self.log_event(
            event_type=AuditEventType.ACCESS_GRANTED,
            username=username,
            path=path,
            action=action,
            result="SUCCESS",
            details=details,
        )

    def log_access_denied(
        self,
        username: str,
        path: Optional[str] = None,
        action: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Convenience helper for unauthorized/blocked access attempts."""
        return self.log_event(
            event_type=AuditEventType.ACCESS_DENIED,
            username=username,
            path=path,
            action=action,
            result="DENIED",
            details=details,
        )

    def log_login_success(
        self,
        username: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record successful authentication event."""
        return self.log_event(
            event_type=AuditEventType.LOGIN_SUCCESS,
            username=username,
            path=None,
            action="LOGIN",
            result="SUCCESS",
            details=details,
        )

    def log_login_failed(
        self,
        username: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record failed authentication attempt."""
        return self.log_event(
            event_type=AuditEventType.LOGIN_FAILED,
            username=username,
            path=None,
            action="LOGIN",
            result="FAILED",
            details=details,
        )

    def log_logout(
        self,
        username: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record logout event."""
        return self.log_event(
            event_type=AuditEventType.LOGOUT,
            username=username,
            path=None,
            action="LOGOUT",
            result="SUCCESS",
            details=details,
        )

    def log_privilege_elevation(
        self,
        username: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record transition into kernel / administrative mode."""
        return self.log_event(
            event_type=AuditEventType.PRIVILEGE_ELEVATION,
            username=username,
            path=None,
            action="ELEVATE",
            result="SUCCESS",
            details=details,
        )

    def log_permission_changed(
        self,
        username: str,
        path: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record chmod permission modification."""
        return self.log_event(
            event_type=AuditEventType.PERMISSION_CHANGED,
            username=username,
            path=path,
            action="CHMOD",
            result="SUCCESS",
            details=details,
        )

    def log_ownership_changed(
        self,
        username: str,
        path: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record chown ownership modification."""
        return self.log_event(
            event_type=AuditEventType.OWNERSHIP_CHANGED,
            username=username,
            path=path,
            action="CHOWN",
            result="SUCCESS",
            details=details,
        )

    def log_tamper_detected(
        self,
        path: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record detected cryptographic hash or block tampering."""
        return self.log_event(
            event_type=AuditEventType.TAMPER_DETECTED,
            username="system",
            path=path,
            action="INTEGRITY_CHECK",
            result="ALERT",
            details=details,
        )

    def log_crypto_operation(
        self,
        action: str,
        username: str,
        path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record encryption/decryption execution."""
        return self.log_event(
            event_type=AuditEventType.CRYPTO_OPERATION,
            username=username,
            path=path,
            action=action,
            result="SUCCESS",
            details=details,
        )

    def get_events(
        self,
        limit: Optional[int] = None,
        event_type: Optional[Union[AuditEventType, str]] = None,
        username: Optional[str] = None,
    ) -> List[AuditEvent]:
        """Query stored events with optional filtering."""
        with self._lock:
            filtered = self._events
            if event_type is not None:
                match_val = event_type.value if isinstance(event_type, AuditEventType) else str(event_type).upper()
                filtered = [
                    e for e in filtered
                    if (e.event_type.value if isinstance(e.event_type, AuditEventType) else str(e.event_type)) == match_val
                ]
            if username is not None:
                filtered = [e for e in filtered if e.username == username]

            if limit is not None and limit > 0:
                return list(filtered[-limit:])
            return list(filtered)

    def get_recent(self, limit: int = 50) -> List[AuditEvent]:
        """Return the N most recent audit events."""
        return self.get_events(limit=limit)

    def get_recent_events(self, limit: int = 10) -> List[AuditEvent]:
        """Alias for get_recent."""
        return self.get_recent(limit=limit)

    def filter_by_type(self, event_type: Union[AuditEventType, str]) -> List[AuditEvent]:
        """Filter audit events by event type."""
        return self.get_events(event_type=event_type)

    def filter_by_user(self, username: str) -> List[AuditEvent]:
        """Filter audit events by username."""
        return self.get_events(username=username)

    def clear(self) -> None:
        """Wipe all recorded events."""
        with self._lock:
            self._events.clear()

    def count(self) -> int:
        """Return total number of events recorded."""
        with self._lock:
            return len(self._events)

    def format_events(self, limit: Optional[int] = None) -> str:
        """Format events table according to official academic formatting rules."""
        events = self.get_events(limit=limit)
        lines = [
            "======================================================================",
            "                   REGISTRO DE AUDITORIA DO SISTEMA                   ",
            "======================================================================",
            f"{'DATA/HORA':<19} | {'TIPO DE EVENTO':<19} | {'USUÁRIO':<10} | {'STATUS':<7} | RECURSO E AÇÃO",
            "----------------------------------------------------------------------",
        ]
        if not events:
            lines.append("Nenhum evento de auditoria registrado no período.")
        else:
            for ev in events:
                lines.append(ev.format_line())
        lines.append("======================================================================")
        return "\n".join(lines)
