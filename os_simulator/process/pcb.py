"""Process Control Block (PCB) representation for OS Simulator."""

import time
from typing import Any, Dict, Optional

from os_simulator.core.types import ProcessState, ProcessType


class Process:
    """Represents a simulated process with its PCB attributes."""

    def __init__(
        self,
        pid: int,
        name: str,
        size_bytes: int,
        process_type: ProcessType = ProcessType.NORMAL,
        owner: str = "root",
        state: ProcessState = ProcessState.READY,
    ):
        self.pid = pid
        self.name = name
        self.size_bytes = size_bytes
        self.process_type = process_type
        self.owner = owner
        self.state = state
        self.created_at = time.time()
        self.page_table: Optional[Any] = None
        self.segment_id: Optional[int] = None

    @property
    def size_kb(self) -> int:
        """Process size in kilobytes."""
        return self.size_bytes // 1024

    @property
    def is_critical(self) -> bool:
        """Check if process is critical (allocated in reserved memory)."""
        return self.process_type == ProcessType.CRITICAL

    def terminate(self) -> None:
        """Mark process state as TERMINATED."""
        self.state = ProcessState.TERMINATED

    def to_dict(self) -> Dict[str, Any]:
        """Serialize process state to dictionary."""
        return {
            "pid": self.pid,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "size_kb": self.size_kb,
            "type": self.process_type.value,
            "state": self.state.value,
            "owner": self.owner,
            "segment_id": self.segment_id,
            "pages_count": self.page_table.total_pages if self.page_table else 0,
        }

    def __repr__(self) -> str:
        return f"<Process pid={self.pid} name='{self.name}' type={self.process_type.value} state={self.state.value} size={self.size_kb}KB>"
