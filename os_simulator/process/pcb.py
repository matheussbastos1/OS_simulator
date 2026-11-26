"""Process Control Block (PCB) representation for OS Simulator."""

import time
from typing import Any, Dict, List, Optional, Tuple, Union

from os_simulator.core.exceptions import ThreadAlreadyExistsException
from os_simulator.core.types import IOProfileType, ProcessState, ProcessType
from os_simulator.process.thread import SimulatedThread


class Process:
    """Represents a simulated process with its PCB attributes and thread registry."""

    def __init__(
        self,
        pid: int,
        name: str,
        size_bytes: int,
        process_type: ProcessType = ProcessType.NORMAL,
        owner: str = "root",
        state: ProcessState = ProcessState.READY,
        priority: int = 3,
        cpu_burst_ms: int = 0,
        arrival_time_ms: int = 0,
        io_profile: Any = IOProfileType.NONE,
        memory_access_pattern: Optional[List[Tuple[int, bool]]] = None,
        create_default_thread: bool = False,
    ):
        for field_name, val, min_val in (
            ("priority", priority, 1),
            ("cpu_burst_ms", cpu_burst_ms, 0),
            ("arrival_time_ms", arrival_time_ms, 0),
        ):
            if isinstance(val, bool) or not isinstance(val, int) or val < min_val:
                raise ValueError(
                    f"{field_name} deve ser inteiro >= {min_val} (recebido: {val!r})."
                )

        self.pid = pid
        self.name = name
        self.size_bytes = size_bytes
        self.process_type = process_type
        self.owner = owner
        self.state = state
        self.created_at = time.time()
        self.page_table: Optional[Any] = None
        self.segment_id: Optional[int] = None

        # Stage 5 scheduling and concurrency attributes
        self.priority: int = priority
        self.cpu_burst_ms: int = cpu_burst_ms
        self.arrival_time_ms: int = arrival_time_ms
        self.io_profile: Any = io_profile
        self.memory_access_pattern: List[Tuple[int, bool]] = (
            list(memory_access_pattern) if memory_access_pattern else []
        )
        self.start_time_ms: Optional[int] = None
        self.finish_time_ms: Optional[int] = None
        self.threads: Dict[int, SimulatedThread] = {}
        self.thread_name_to_tid: Dict[str, int] = {}

        if create_default_thread:
            default_tid = max(1, self.pid * 1000 + 1)
            self.add_thread(
                SimulatedThread(
                    tid=default_tid,
                    pid=self.pid,
                    name="main",
                    state=self.state,
                    priority=self.priority,
                    cpu_burst_ms=self.cpu_burst_ms,
                    arrival_time_ms=self.arrival_time_ms,
                    io_profile=self.io_profile,
                    memory_access_pattern=list(self.memory_access_pattern),
                )
            )

    @property
    def size_kb(self) -> int:
        """Process size in kilobytes."""
        return self.size_bytes // 1024

    @property
    def is_critical(self) -> bool:
        """Check if process is critical (allocated in reserved memory)."""
        return self.process_type == ProcessType.CRITICAL

    @property
    def cpu_consumed_ms(self) -> int:
        """Total CPU milliseconds consumed across all threads of this process."""
        return sum(t.cpu_consumed_ms for t in self.threads.values())

    @property
    def remaining_burst_ms(self) -> int:
        """Remaining CPU burst milliseconds across threads (or process burst if unthreaded)."""
        if self.threads:
            return sum(t.remaining_burst_ms for t in self.threads.values())
        return self.cpu_burst_ms

    @property
    def total_wait_ms(self) -> int:
        """Accumulated READY wait time across all threads of this process."""
        return sum(t.total_wait_ms for t in self.threads.values())

    @property
    def total_blocked_ms(self) -> int:
        """Accumulated BLOCKED time across all threads of this process."""
        return sum(t.total_blocked_ms for t in self.threads.values())

    def add_thread(self, thread: SimulatedThread) -> SimulatedThread:
        """Register a SimulatedThread on this PCB."""
        if thread.pid != self.pid:
            raise ValueError(
                f"Thread '{thread.name}' (PID {thread.pid}) não pertence ao processo PID {self.pid}."
            )
        if thread.tid in self.threads:
            raise ThreadAlreadyExistsException(
                f"Thread com TID {thread.tid} já existe no processo '{self.name}' (PID {self.pid})."
            )
        if thread.name in self.thread_name_to_tid:
            existing = self.threads[self.thread_name_to_tid[thread.name]]
            if existing.state != ProcessState.TERMINATED:
                raise ThreadAlreadyExistsException(
                    f"Thread '{thread.name}' já existe e está ativa no processo '{self.name}' (PID {self.pid})."
                )
        self.threads[thread.tid] = thread
        self.thread_name_to_tid[thread.name] = thread.tid
        return thread

    def get_thread(self, identifier: Union[int, str]) -> Optional[SimulatedThread]:
        """Find thread belonging to this process by TID or name."""
        if isinstance(identifier, int) and not isinstance(identifier, bool):
            return self.threads.get(identifier)

        id_str = str(identifier).strip()
        if id_str.isdigit() and int(id_str) in self.threads:
            return self.threads[int(id_str)]
        if id_str in self.thread_name_to_tid:
            return self.threads[self.thread_name_to_tid[id_str]]
        for thread in self.threads.values():
            if thread.name.lower() == id_str.lower():
                return thread
        return None

    def list_threads(self, active_only: bool = False) -> List[SimulatedThread]:
        """List threads belonging to this process."""
        if active_only:
            return [t for t in self.threads.values() if t.state != ProcessState.TERMINATED]
        return list(self.threads.values())

    def terminate(self) -> None:
        """Mark process state (and any attached threads) as TERMINATED."""
        self.state = ProcessState.TERMINATED
        for thread in self.threads.values():
            thread.state = ProcessState.TERMINATED
            thread.ready_since_ms = None
            thread.blocked_since_ms = None
            thread.quantum_used_ms = 0

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
            "priority": self.priority,
            "cpu_burst_ms": self.cpu_burst_ms,
            "cpu_consumed_ms": self.cpu_consumed_ms,
            "arrival_time_ms": self.arrival_time_ms,
            "start_time_ms": self.start_time_ms,
            "finish_time_ms": self.finish_time_ms,
            "threads_count": len(self.threads),
            "threads": [t.to_dict() for t in self.threads.values()],
        }

    def __repr__(self) -> str:
        return (
            f"<Process pid={self.pid} name='{self.name}' "
            f"type={self.process_type.value} state={self.state.value} size={self.size_kb}KB>"
        )
