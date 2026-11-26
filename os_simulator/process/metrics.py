"""Execution metrics, chronological timeline, CPU Gantt chart, and live frame summaries for Stage 5."""

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Union

from os_simulator.core.exceptions import InvalidAddressException, ProcessNotFoundException
from os_simulator.core.types import ProcessState
from os_simulator.process.manager import ProcessManager
from os_simulator.process.pcb import Process
from os_simulator.process.thread import SimulatedThread

if TYPE_CHECKING:
    from os_simulator.memory.service import MemoryManager


def _validate_non_negative_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} deve ser inteiro >= 0 (recebido: {value!r}).")
    return value


def _normalize_counter_key(name: str) -> str:
    clean = str(name).strip()
    if not clean:
        raise ValueError("Nome do contador não pode ser vazio.")
    if clean.endswith("_total"):
        return clean[:-6]
    return clean


@dataclass
class TimelineEntry:
    """Single chronological event record in the Stage 5 simulation timeline."""

    seq: int
    timestamp_ms: int
    event_type: str
    pid: Optional[int] = None
    tid: Optional[int] = None
    process_name: str = ""
    thread_name: str = ""
    state: str = ""
    priority: Optional[int] = None
    cpu_consumed_ms: int = 0
    quantum_used_ms: int = 0
    details: str = ""

    def __post_init__(self) -> None:
        _validate_non_negative_int(self.timestamp_ms, "timestamp_ms")
        _validate_non_negative_int(self.cpu_consumed_ms, "cpu_consumed_ms")
        _validate_non_negative_int(self.quantum_used_ms, "quantum_used_ms")
        if isinstance(self.event_type, Enum):
            self.event_type = str(self.event_type.value)
        else:
            self.event_type = str(self.event_type)
        if isinstance(self.state, Enum):
            self.state = str(self.state.value)
        else:
            self.state = str(self.state)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize timeline entry to dictionary."""
        return {
            "seq": self.seq,
            "timestamp_ms": self.timestamp_ms,
            "event_type": self.event_type,
            "pid": self.pid,
            "tid": self.tid,
            "process_name": self.process_name,
            "thread_name": self.thread_name,
            "state": self.state,
            "priority": self.priority,
            "cpu_consumed_ms": self.cpu_consumed_ms,
            "quantum_used_ms": self.quantum_used_ms,
            "details": self.details,
        }


@dataclass
class GanttSlice:
    """Contiguous CPU execution or idle interval for Gantt chart visualization."""

    start_ms: int
    end_ms: int
    pid: Optional[int] = None
    tid: Optional[int] = None
    process_name: str = ""
    thread_name: str = ""
    label: str = "EXEC"
    is_idle: bool = False

    def __post_init__(self) -> None:
        _validate_non_negative_int(self.start_ms, "start_ms")
        _validate_non_negative_int(self.end_ms, "end_ms")
        if self.end_ms < self.start_ms:
            raise ValueError(
                f"end_ms deve ser maior ou igual a start_ms ({self.start_ms}) (recebido: {self.end_ms})."
            )

    @property
    def duration_ms(self) -> int:
        """Duration of this Gantt interval in milliseconds."""
        return self.end_ms - self.start_ms

    def to_dict(self) -> Dict[str, Any]:
        """Serialize Gantt slice to dictionary."""
        return {
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "pid": self.pid,
            "tid": self.tid,
            "process_name": self.process_name,
            "thread_name": self.thread_name,
            "label": self.label,
            "is_idle": self.is_idle,
        }


@dataclass
class FrameAccessRecord:
    """Record of a simulated memory access (HIT or PAGE_FAULT) mapped to a physical frame."""

    timestamp_ms: int
    pid: int
    tid: Optional[int]
    logical_page: int
    frame_id: int
    hit: bool
    page_origin: Optional[str] = None
    algorithm: str = "LRU"
    seq: int = 0

    def __post_init__(self) -> None:
        _validate_non_negative_int(self.timestamp_ms, "timestamp_ms")
        if isinstance(self.page_origin, Enum):
            self.page_origin = str(self.page_origin.value)
        if isinstance(self.algorithm, Enum):
            self.algorithm = str(self.algorithm.value)
        else:
            self.algorithm = str(self.algorithm)

    @property
    def event_label(self) -> str:
        """Return 'HIT' when resident or 'PAGE_FAULT' on miss."""
        return "HIT" if self.hit else "PAGE_FAULT"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize frame access record to dictionary."""
        return {
            "seq": self.seq,
            "timestamp_ms": self.timestamp_ms,
            "pid": self.pid,
            "tid": self.tid,
            "logical_page": self.logical_page,
            "frame_id": self.frame_id,
            "hit": self.hit,
            "event": self.event_label,
            "page_origin": self.page_origin,
            "algorithm": self.algorithm,
        }


def record_memory_access(
    timestamp_ms: int,
    pid: int,
    tid: Optional[int],
    logical_page: int,
    frame_id: int,
    hit: bool,
    page_origin: Optional[Union[str, Enum]] = None,
    algorithm: Union[str, Enum] = "LRU",
    seq: int = 0,
) -> FrameAccessRecord:
    """Construct a normalized FrameAccessRecord for a memory access event."""
    origin_val = page_origin.value if isinstance(page_origin, Enum) else page_origin
    algo_val = algorithm.value if isinstance(algorithm, Enum) else str(algorithm)
    return FrameAccessRecord(
        timestamp_ms=timestamp_ms,
        pid=pid,
        tid=tid,
        logical_page=logical_page,
        frame_id=frame_id,
        hit=bool(hit),
        page_origin=origin_val,
        algorithm=algo_val,
        seq=seq,
    )


def _lookup_process(lookup: Any, pid: int) -> Optional[Process]:
    """Resolve PID to Process instance safely across dict, ProcessManager, or callable."""
    if lookup is None:
        return None
    if isinstance(lookup, dict):
        return lookup.get(pid)
    if hasattr(lookup, "get_process"):
        try:
            return lookup.get_process(pid)
        except ProcessNotFoundException:
            return None
    if callable(lookup):
        try:
            return lookup(pid)
        except ProcessNotFoundException:
            return None
    return None


def build_frames_summary(
    memory_manager: "MemoryManager",
    process_lookup: Optional[Any] = None,
    frame_records: Optional[Union[Dict[int, FrameAccessRecord], Iterable[FrameAccessRecord]]] = None,
) -> List[Dict[str, Any]]:
    """Build live physical frame summary synchronized with Stage 4 PhysicalMemory and PageTable."""
    lookup = process_lookup if process_lookup is not None else getattr(memory_manager, "_process_lookup", None)

    records_by_frame: Dict[int, FrameAccessRecord] = {}
    if isinstance(frame_records, dict):
        records_by_frame = dict(frame_records)
    elif frame_records is not None:
        for rec in frame_records:
            records_by_frame[rec.frame_id] = rec

    algo_name = (
        memory_manager.algorithm.value
        if isinstance(memory_manager.algorithm, Enum)
        else str(memory_manager.algorithm)
    )

    summary: List[Dict[str, Any]] = []
    for frame in memory_manager.physical_memory.frames:
        if not frame.occupied:
            summary.append(
                {
                    "frame_id": frame.frame_id,
                    "occupied": False,
                    "pid": None,
                    "logical_page": None,
                    "state": "LIVRE",
                    "last_event": "N/A",
                    "last_access": None,
                    "dirty": False,
                    "referenced": False,
                    "algorithm": algo_name,
                }
            )
            continue

        pid = frame.owner_pid
        logical_page = frame.logical_page
        last_access: Optional[float] = None
        dirty = False
        referenced = False

        if pid is not None and logical_page is not None:
            proc = _lookup_process(lookup, pid)
            if proc is not None and getattr(proc, "page_table", None) is not None:
                try:
                    entry = proc.page_table.get_entry(logical_page)
                    last_access = entry.last_access
                    dirty = bool(entry.dirty)
                    referenced = bool(entry.referenced)
                except InvalidAddressException:
                    pass

        rec = records_by_frame.get(frame.frame_id)
        if rec is not None and rec.pid == pid and rec.logical_page == logical_page:
            last_event = "HIT" if rec.hit else "PAGE_FAULT"
        else:
            last_event = "N/A"

        summary.append(
            {
                "frame_id": frame.frame_id,
                "occupied": True,
                "pid": pid,
                "logical_page": logical_page,
                "state": "OCUPADA",
                "last_event": last_event,
                "last_access": last_access,
                "dirty": dirty,
                "referenced": referenced,
                "algorithm": algo_name,
            }
        )

    return summary


@dataclass
class ThreadMetrics:
    """Computed timing and resource metrics for a single SimulatedThread."""

    tid: int
    pid: int
    name: str
    state: str
    priority: int
    cpu_burst_ms: int
    arrival_time_ms: int
    start_time_ms: Optional[int]
    finish_time_ms: Optional[int]
    cpu_time_ms: int
    waiting_time_ms: int
    blocked_time_ms: int
    turnaround_time_ms: Optional[int]
    response_time_ms: Optional[int]
    syscalls_count: int = 0
    io_blocks_count: int = 0
    mutex_blocks_count: int = 0
    page_hits: int = 0
    page_faults: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize thread metrics to dictionary."""
        return {
            "tid": self.tid,
            "pid": self.pid,
            "name": self.name,
            "state": self.state,
            "priority": self.priority,
            "cpu_burst_ms": self.cpu_burst_ms,
            "arrival_time_ms": self.arrival_time_ms,
            "start_time_ms": self.start_time_ms,
            "finish_time_ms": self.finish_time_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "waiting_time_ms": self.waiting_time_ms,
            "blocked_time_ms": self.blocked_time_ms,
            "turnaround_time_ms": self.turnaround_time_ms,
            "response_time_ms": self.response_time_ms,
            "syscalls_count": self.syscalls_count,
            "io_blocks_count": self.io_blocks_count,
            "mutex_blocks_count": self.mutex_blocks_count,
            "page_hits": self.page_hits,
            "page_faults": self.page_faults,
        }


@dataclass
class ProcessMetrics:
    """Computed timing and resource metrics for a Process (PCB)."""

    pid: int
    name: str
    process_type: str
    state: str
    priority: int
    cpu_burst_ms: int
    arrival_time_ms: int
    start_time_ms: Optional[int]
    finish_time_ms: Optional[int]
    cpu_time_ms: int
    waiting_time_ms: int
    blocked_time_ms: int
    turnaround_time_ms: Optional[int]
    response_time_ms: Optional[int]
    syscalls_count: int = 0
    io_blocks_count: int = 0
    mutex_blocks_count: int = 0
    page_hits: int = 0
    page_faults: int = 0
    thread_metrics: List[ThreadMetrics] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize process metrics to dictionary."""
        return {
            "pid": self.pid,
            "name": self.name,
            "process_type": self.process_type,
            "state": self.state,
            "priority": self.priority,
            "cpu_burst_ms": self.cpu_burst_ms,
            "arrival_time_ms": self.arrival_time_ms,
            "start_time_ms": self.start_time_ms,
            "finish_time_ms": self.finish_time_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "waiting_time_ms": self.waiting_time_ms,
            "blocked_time_ms": self.blocked_time_ms,
            "turnaround_time_ms": self.turnaround_time_ms,
            "response_time_ms": self.response_time_ms,
            "syscalls_count": self.syscalls_count,
            "io_blocks_count": self.io_blocks_count,
            "mutex_blocks_count": self.mutex_blocks_count,
            "page_hits": self.page_hits,
            "page_faults": self.page_faults,
            "thread_metrics": [tm.to_dict() for tm in self.thread_metrics],
        }


@dataclass
class SimulationMetrics:
    """Global Stage 5 simulation performance summary."""

    total_simulation_ms: int
    cpu_busy_ms: int
    idle_time_ms: int
    cpu_utilization_pct: float
    context_switches_total: int
    dispatches_total: int
    preemptions_total: int
    syscalls_total: int
    io_blocks_total: int
    mutex_blocks_total: int
    page_hits_total: int
    page_faults_total: int
    avg_waiting_time_ms: float
    avg_turnaround_time_ms: float
    completed_processes: int
    total_processes: int
    throughput_per_sec: float = 0.0
    process_metrics: List[ProcessMetrics] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize global simulation metrics to dictionary."""
        return {
            "total_simulation_ms": self.total_simulation_ms,
            "cpu_busy_ms": self.cpu_busy_ms,
            "idle_time_ms": self.idle_time_ms,
            "cpu_utilization_pct": self.cpu_utilization_pct,
            "context_switches_total": self.context_switches_total,
            "dispatches_total": self.dispatches_total,
            "preemptions_total": self.preemptions_total,
            "syscalls_total": self.syscalls_total,
            "io_blocks_total": self.io_blocks_total,
            "mutex_blocks_total": self.mutex_blocks_total,
            "page_hits_total": self.page_hits_total,
            "page_faults_total": self.page_faults_total,
            "avg_waiting_time_ms": self.avg_waiting_time_ms,
            "avg_turnaround_time_ms": self.avg_turnaround_time_ms,
            "completed_processes": self.completed_processes,
            "total_processes": self.total_processes,
            "throughput_per_sec": self.throughput_per_sec,
            "process_metrics": [pm.to_dict() for pm in self.process_metrics],
        }


class MetricsCollector:
    """Collects timeline events, Gantt intervals, memory accesses, counters, and metrics."""

    def __init__(self) -> None:
        self._timeline: List[TimelineEntry] = []
        self._next_seq: int = 1
        self._gantt: List[GanttSlice] = []
        self._memory_history: List[FrameAccessRecord] = []
        self._memory_seq: int = 0
        self._latest_frame_access: Dict[int, FrameAccessRecord] = {}
        self._counters: Dict[str, int] = defaultdict(int)
        self._pid_counters: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._pid_only_counters: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._tid_counters: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record_event(
        self,
        timestamp_ms: int,
        event_type: Union[str, Enum],
        pid: Optional[int] = None,
        tid: Optional[int] = None,
        process_name: str = "",
        thread_name: str = "",
        state: Union[str, Enum] = "",
        priority: Optional[int] = None,
        cpu_consumed_ms: Optional[int] = None,
        quantum_used_ms: Optional[int] = None,
        details: str = "",
        thread: Optional[SimulatedThread] = None,
    ) -> TimelineEntry:
        """Record a chronological event entry in the simulation timeline."""
        ts = _validate_non_negative_int(timestamp_ms, "timestamp_ms")

        eff_pid = pid if pid is not None else (thread.pid if thread is not None else None)
        eff_tid = tid if tid is not None else (thread.tid if thread is not None else None)
        eff_thread_name = thread_name or (thread.name if thread is not None else "")
        eff_state = state if state != "" else (thread.state.value if thread is not None else "")
        eff_priority = priority if priority is not None else (thread.priority if thread is not None else None)
        eff_cpu = (
            cpu_consumed_ms
            if cpu_consumed_ms is not None
            else (thread.cpu_consumed_ms if thread is not None else 0)
        )
        eff_quantum = (
            quantum_used_ms
            if quantum_used_ms is not None
            else (thread.quantum_used_ms if thread is not None else 0)
        )

        entry = TimelineEntry(
            seq=self._next_seq,
            timestamp_ms=ts,
            event_type=event_type.value if isinstance(event_type, Enum) else str(event_type),
            pid=eff_pid,
            tid=eff_tid,
            process_name=process_name,
            thread_name=eff_thread_name,
            state=eff_state.value if isinstance(eff_state, Enum) else str(eff_state),
            priority=eff_priority,
            cpu_consumed_ms=eff_cpu,
            quantum_used_ms=eff_quantum,
            details=details,
        )
        self._next_seq += 1
        self._timeline.append(entry)
        return entry

    def record_cpu_slice(
        self,
        start_ms: int,
        end_ms: int,
        thread: Union[SimulatedThread, int],
        process_name: str,
        label: str = "EXEC",
    ) -> Optional[GanttSlice]:
        """Record a CPU execution interval, coalescing contiguous slices for same TID and label."""
        _validate_non_negative_int(start_ms, "start_ms")
        _validate_non_negative_int(end_ms, "end_ms")
        if end_ms < start_ms:
            raise ValueError(f"end_ms ({end_ms}) não pode ser menor que start_ms ({start_ms}).")
        if end_ms == start_ms:
            return None

        if self._gantt and start_ms < self._gantt[-1].end_ms:
            raise ValueError(
                f"Intervalo Gantt sobreposto: start_ms={start_ms} < último end_ms={self._gantt[-1].end_ms}."
            )

        if isinstance(thread, SimulatedThread):
            pid: Optional[int] = thread.pid
            tid: Optional[int] = thread.tid
            thread_name = thread.name
        elif hasattr(thread, "tid"):
            pid = getattr(thread, "pid", None)
            tid = getattr(thread, "tid")
            thread_name = str(getattr(thread, "name", f"TID:{tid}"))
        else:
            pid = None
            tid = int(thread)
            thread_name = f"TID:{tid}"

        if self._gantt:
            last = self._gantt[-1]
            if (
                not last.is_idle
                and last.end_ms == start_ms
                and last.tid == tid
                and last.pid == pid
                and last.label == label
            ):
                last.end_ms = end_ms
                return last

        slc = GanttSlice(
            start_ms=start_ms,
            end_ms=end_ms,
            pid=pid,
            tid=tid,
            process_name=process_name,
            thread_name=thread_name,
            label=label,
            is_idle=False,
        )
        self._gantt.append(slc)
        return slc

    def record_idle_slice(self, start_ms: int, end_ms: int) -> Optional[GanttSlice]:
        """Record an idle CPU interval, coalescing contiguous idle intervals."""
        _validate_non_negative_int(start_ms, "start_ms")
        _validate_non_negative_int(end_ms, "end_ms")
        if end_ms < start_ms:
            raise ValueError(f"end_ms ({end_ms}) não pode ser menor que start_ms ({start_ms}).")
        if end_ms == start_ms:
            return None

        if self._gantt and start_ms < self._gantt[-1].end_ms:
            raise ValueError(
                f"Intervalo ocioso Gantt sobreposto: start_ms={start_ms} < último end_ms={self._gantt[-1].end_ms}."
            )

        if self._gantt:
            last = self._gantt[-1]
            if last.is_idle and last.end_ms == start_ms:
                last.end_ms = end_ms
                return last

        slc = GanttSlice(
            start_ms=start_ms,
            end_ms=end_ms,
            pid=None,
            tid=None,
            process_name="IDLE",
            thread_name="IDLE",
            label="IDLE",
            is_idle=True,
        )
        self._gantt.append(slc)
        return slc

    def record_memory_access(
        self,
        timestamp_ms: int,
        pid: int,
        tid: Optional[int],
        logical_page: int,
        frame_id: int,
        hit: bool,
        page_origin: Optional[Union[str, Enum]] = None,
        algorithm: Union[str, Enum] = "LRU",
        update_counters: bool = True,
    ) -> FrameAccessRecord:
        """Record a memory HIT or PAGE_FAULT event, update frame history, and increment counters."""
        self._memory_seq += 1
        rec = record_memory_access(
            timestamp_ms=timestamp_ms,
            pid=pid,
            tid=tid,
            logical_page=logical_page,
            frame_id=frame_id,
            hit=hit,
            page_origin=page_origin,
            algorithm=algorithm,
            seq=self._memory_seq,
        )
        self._memory_history.append(rec)
        self._latest_frame_access[frame_id] = rec
        if update_counters:
            counter_name = "page_hits_total" if rec.hit else "page_faults_total"
            self.increment_counter(counter_name, delta=1, pid=pid, tid=tid)
        return rec

    def increment_counter(
        self,
        name: str,
        delta: int = 1,
        pid: Optional[int] = None,
        tid: Optional[int] = None,
    ) -> int:
        """Increment global and optional per-PID / per-TID metric counters."""
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Nome do contador não pode ser vazio.")
        _validate_non_negative_int(delta, "delta")

        norm_key = _normalize_counter_key(clean_name)
        self._counters[norm_key] += delta

        if pid is not None:
            self._pid_counters[pid][norm_key] += delta
            if tid is None:
                self._pid_only_counters[pid][norm_key] += delta
        if tid is not None:
            self._tid_counters[tid][norm_key] += delta

        return self._counters[norm_key]

    def get_counter(
        self,
        name: str,
        pid: Optional[int] = None,
        tid: Optional[int] = None,
    ) -> int:
        """Return counter value globally or scoped to a PID or TID."""
        norm_key = _normalize_counter_key(name)
        if tid is not None:
            return self._tid_counters[tid].get(norm_key, 0)
        if pid is not None:
            return self._pid_counters[pid].get(norm_key, 0)
        return self._counters.get(norm_key, 0)

    def _resolve_process_counter(self, proc: Process, norm_key: str) -> int:
        pid_total = self._pid_counters[proc.pid].get(norm_key, 0)
        pid_only = self._pid_only_counters[proc.pid].get(norm_key, 0)
        tid_sum = sum(self._tid_counters[tid].get(norm_key, 0) for tid in proc.threads.keys())
        return max(pid_total, tid_sum + pid_only)

    def compute_thread_metrics(self, thread: SimulatedThread) -> ThreadMetrics:
        """Compute mathematically consistent metrics for a single SimulatedThread."""
        cpu_time_ms = thread.cpu_consumed_ms
        blocked_time_ms = thread.total_blocked_ms
        waiting_time_ms = thread.total_wait_ms
        turnaround_time_ms = (
            thread.finish_time_ms - thread.arrival_time_ms
            if thread.finish_time_ms is not None
            else None
        )
        response_time_ms = (
            thread.start_time_ms - thread.arrival_time_ms
            if thread.start_time_ms is not None
            else None
        )
        tid_map = self._tid_counters[thread.tid]

        return ThreadMetrics(
            tid=thread.tid,
            pid=thread.pid,
            name=thread.name,
            state=thread.state.value,
            priority=thread.priority,
            cpu_burst_ms=thread.cpu_burst_ms,
            arrival_time_ms=thread.arrival_time_ms,
            start_time_ms=thread.start_time_ms,
            finish_time_ms=thread.finish_time_ms,
            cpu_time_ms=cpu_time_ms,
            waiting_time_ms=waiting_time_ms,
            blocked_time_ms=blocked_time_ms,
            turnaround_time_ms=turnaround_time_ms,
            response_time_ms=response_time_ms,
            syscalls_count=tid_map.get("syscalls", 0),
            io_blocks_count=tid_map.get("io_blocks", 0),
            mutex_blocks_count=tid_map.get("mutex_blocks", 0),
            page_hits=tid_map.get("page_hits", 0),
            page_faults=tid_map.get("page_faults", 0),
        )

    def compute_process_metrics(self, proc: Process) -> ProcessMetrics:
        """Compute aggregated metrics for a Process PCB and its SimulatedThreads."""
        threads = proc.list_threads()
        thread_metrics = [self.compute_thread_metrics(t) for t in threads]

        if threads:
            cpu_time_ms = sum(tm.cpu_time_ms for tm in thread_metrics)
            waiting_time_ms = sum(tm.waiting_time_ms for tm in thread_metrics)
            blocked_time_ms = sum(tm.blocked_time_ms for tm in thread_metrics)
            eff_burst = sum(t.cpu_burst_ms for t in threads) or proc.cpu_burst_ms

            starts = [t.start_time_ms for t in threads if t.start_time_ms is not None]
            start_time_ms = (
                proc.start_time_ms
                if proc.start_time_ms is not None
                else (min(starts) if starts else None)
            )

            all_finished = all(t.state == ProcessState.TERMINATED for t in threads)
            if proc.state == ProcessState.TERMINATED or all_finished:
                finishes = [t.finish_time_ms for t in threads if t.finish_time_ms is not None]
                finish_time_ms = (
                    proc.finish_time_ms
                    if proc.finish_time_ms is not None
                    else (max(finishes) if len(finishes) == len(threads) else None)
                )
            else:
                finish_time_ms = None
        else:
            cpu_time_ms = proc.cpu_consumed_ms
            waiting_time_ms = proc.total_wait_ms
            blocked_time_ms = proc.total_blocked_ms
            eff_burst = proc.cpu_burst_ms
            start_time_ms = proc.start_time_ms
            finish_time_ms = proc.finish_time_ms if proc.state == ProcessState.TERMINATED else None

        turnaround_time_ms = (
            finish_time_ms - proc.arrival_time_ms
            if finish_time_ms is not None
            else None
        )
        response_time_ms = (
            start_time_ms - proc.arrival_time_ms
            if start_time_ms is not None
            else None
        )

        return ProcessMetrics(
            pid=proc.pid,
            name=proc.name,
            process_type=proc.process_type.value,
            state=proc.state.value,
            priority=proc.priority,
            cpu_burst_ms=eff_burst,
            arrival_time_ms=proc.arrival_time_ms,
            start_time_ms=start_time_ms,
            finish_time_ms=finish_time_ms,
            cpu_time_ms=cpu_time_ms,
            waiting_time_ms=waiting_time_ms,
            blocked_time_ms=blocked_time_ms,
            turnaround_time_ms=turnaround_time_ms,
            response_time_ms=response_time_ms,
            syscalls_count=self._resolve_process_counter(proc, "syscalls"),
            io_blocks_count=self._resolve_process_counter(proc, "io_blocks"),
            mutex_blocks_count=self._resolve_process_counter(proc, "mutex_blocks"),
            page_hits=self._resolve_process_counter(proc, "page_hits"),
            page_faults=self._resolve_process_counter(proc, "page_faults"),
            thread_metrics=thread_metrics,
        )

    def compute_global_metrics(
        self,
        process_manager: ProcessManager,
        clock_now_ms: int,
        scheduler_stats: Optional[Any] = None,
    ) -> SimulationMetrics:
        """Compute consistent global simulation metrics across processes, Gantt, and scheduler."""
        clock_ms = _validate_non_negative_int(clock_now_ms, "clock_now_ms")

        if scheduler_stats is None:
            stats_dict: Dict[str, Any] = {}
        elif hasattr(scheduler_stats, "get_stats"):
            stats_dict = dict(scheduler_stats.get_stats())
        else:
            stats_dict = dict(scheduler_stats)

        user_procs = [p for p in process_manager.list_processes() if p.pid != 0]
        proc_metrics_list = [self.compute_process_metrics(p) for p in user_procs]

        threads_cpu = sum(t.cpu_consumed_ms for t in process_manager.list_threads())
        gantt_busy = sum(s.duration_ms for s in self._gantt if not s.is_idle)
        gantt_idle = sum(s.duration_ms for s in self._gantt if s.is_idle)

        cpu_busy_ms = max(threads_cpu, gantt_busy)
        explicit_idle = gantt_idle if gantt_idle > 0 else int(stats_dict.get("idle_time_ms", 0))
        total_simulation_ms = max(clock_ms, cpu_busy_ms + explicit_idle)
        idle_time_ms = total_simulation_ms - cpu_busy_ms
        cpu_utilization_pct = (
            (cpu_busy_ms / total_simulation_ms) * 100.0 if total_simulation_ms > 0 else 0.0
        )

        total_processes = len(proc_metrics_list)
        completed_procs = [pm for pm in proc_metrics_list if pm.state == ProcessState.TERMINATED.value]
        completed_processes = len(completed_procs)

        avg_waiting_time_ms = (
            sum(pm.waiting_time_ms for pm in proc_metrics_list) / total_processes
            if total_processes > 0
            else 0.0
        )
        finished_tats = [pm.turnaround_time_ms for pm in completed_procs if pm.turnaround_time_ms is not None]
        avg_turnaround_time_ms = (
            sum(finished_tats) / len(finished_tats) if finished_tats else 0.0
        )
        throughput_per_sec = (
            (completed_processes / (total_simulation_ms / 1000.0))
            if total_simulation_ms > 0
            else 0.0
        )

        context_switches_total = int(
            stats_dict.get("context_switches_total", self._counters.get("context_switches", 0))
        )
        dispatches_total = int(
            stats_dict.get("dispatches_total", self._counters.get("dispatches", 0))
        )
        preemptions_total = int(
            stats_dict.get("preemptions_total", self._counters.get("preemptions", 0))
        )

        return SimulationMetrics(
            total_simulation_ms=total_simulation_ms,
            cpu_busy_ms=cpu_busy_ms,
            idle_time_ms=idle_time_ms,
            cpu_utilization_pct=cpu_utilization_pct,
            context_switches_total=context_switches_total,
            dispatches_total=dispatches_total,
            preemptions_total=preemptions_total,
            syscalls_total=self._counters.get("syscalls", 0),
            io_blocks_total=self._counters.get("io_blocks", 0),
            mutex_blocks_total=self._counters.get("mutex_blocks", 0),
            page_hits_total=self._counters.get("page_hits", 0),
            page_faults_total=self._counters.get("page_faults", 0),
            avg_waiting_time_ms=avg_waiting_time_ms,
            avg_turnaround_time_ms=avg_turnaround_time_ms,
            completed_processes=completed_processes,
            total_processes=total_processes,
            throughput_per_sec=throughput_per_sec,
            process_metrics=proc_metrics_list,
        )

    def build_frames_summary(
        self,
        memory_manager: "MemoryManager",
        process_lookup: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Return live physical frame summary enriched with latest HIT/PAGE_FAULT event."""
        return build_frames_summary(
            memory_manager=memory_manager,
            process_lookup=process_lookup,
            frame_records=self._latest_frame_access,
        )

    def get_timeline(self, limit: Optional[int] = None) -> List[TimelineEntry]:
        """Return timeline entries in chronological order (optionally the last `limit` entries)."""
        ordered = sorted(self._timeline, key=lambda e: (e.timestamp_ms, e.seq))
        if limit is None:
            return ordered
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError(f"limit deve ser inteiro >= 0 (recebido: {limit!r}).")
        if limit == 0:
            return []
        return ordered[-limit:]

    def get_gantt(self) -> List[GanttSlice]:
        """Return a copy of all recorded CPU and idle Gantt slices."""
        return list(self._gantt)

    def get_memory_history(self) -> List[FrameAccessRecord]:
        """Return a copy of all recorded memory frame access events."""
        return list(self._memory_history)

    def format_metrics_report(
        self,
        process_manager: Optional[ProcessManager] = None,
        clock_now_ms: int = 0,
        scheduler_stats: Optional[Any] = None,
        simulation_metrics: Optional[SimulationMetrics] = None,
    ) -> str:
        """Format complete execution and scheduling metrics report in Portuguese."""
        if simulation_metrics is not None:
            m = simulation_metrics
        elif process_manager is not None:
            m = self.compute_global_metrics(process_manager, clock_now_ms, scheduler_stats=scheduler_stats)
        else:
            raise ValueError("Informe simulation_metrics ou process_manager para formatar o relatório.")

        lines = [
            "======================================================================",
            "          RELATÓRIO DE MÉTRICAS DE EXECUÇÃO E ESCALONAMENTO",
            "======================================================================",
            f"Tempo Total de Simulação  : {m.total_simulation_ms} ms",
            f"Tempo de CPU Ocupada      : {m.cpu_busy_ms} ms",
            f"Tempo de CPU Ociosa (Idle): {m.idle_time_ms} ms",
            f"Utilização da CPU         : {m.cpu_utilization_pct:.2f}%",
            f"Trocas de Contexto        : {m.context_switches_total}",
            f"Despachos / Preempções    : {m.dispatches_total} / {m.preemptions_total}",
            f"Syscalls Executadas       : {m.syscalls_total}",
            f"Bloqueios (E/S / Mutex)   : {m.io_blocks_total} / {m.mutex_blocks_total}",
            f"Memória (Hits / Faults)   : {m.page_hits_total} / {m.page_faults_total}",
            f"Processos Concluídos      : {m.completed_processes} / {m.total_processes}",
            f"Tempo Médio de Espera (WT): {m.avg_waiting_time_ms:.2f} ms",
            f"Turnaround Médio (TAT)    : {m.avg_turnaround_time_ms:.2f} ms",
            f"Vazão (Throughput)        : {m.throughput_per_sec:.2f} proc/s",
        ]

        if m.process_metrics:
            lines.extend(
                [
                    "----------------------------------------------------------------------",
                    "MÉTRICAS POR PROCESSO:",
                    (
                        f"{'PID':<5} | {'Processo':<15} | {'Estado':<10} | {'Prio':<4} | "
                        f"{'CPU':<6} | {'WT':<6} | {'BLK':<6} | {'TAT':<6} | {'RT':<6} | {'Hits/Faults'}"
                    ),
                    "-" * 92,
                ]
            )
            for pm in m.process_metrics:
                tat_str = f"{pm.turnaround_time_ms}ms" if pm.turnaround_time_ms is not None else "-"
                rt_str = f"{pm.response_time_ms}ms" if pm.response_time_ms is not None else "-"
                lines.append(
                    f"{pm.pid:<5} | {pm.name[:15]:<15} | {pm.state:<10} | {pm.priority:<4} | "
                    f"{pm.cpu_time_ms:<4}ms | {pm.waiting_time_ms:<4}ms | {pm.blocked_time_ms:<4}ms | "
                    f"{tat_str:<6} | {rt_str:<6} | {pm.page_hits}/{pm.page_faults}"
                )
                for tm in pm.thread_metrics:
                    t_tat = f"{tm.turnaround_time_ms}ms" if tm.turnaround_time_ms is not None else "-"
                    t_rt = f"{tm.response_time_ms}ms" if tm.response_time_ms is not None else "-"
                    lines.append(
                        f"  └─ TID {tm.tid:<3} ({tm.name[:10]:<10}) [{tm.state:<10}] "
                        f"CPU={tm.cpu_time_ms}ms WT={tm.waiting_time_ms}ms "
                        f"BLK={tm.blocked_time_ms}ms TAT={t_tat} RT={t_rt}"
                    )

        lines.append("======================================================================")
        return "\n".join(lines)

    def format_timeline(self, limit: Optional[int] = None) -> str:
        """Format chronological simulation timeline in Portuguese."""
        entries = self.get_timeline(limit=limit)
        lines = [
            "======================================================================",
            "                 LINHA DO TEMPO DA SIMULAÇÃO (TIMELINE)",
            "======================================================================",
        ]
        if not entries:
            lines.append("Nenhum evento registrado na linha do tempo.")
            lines.append("======================================================================")
            return "\n".join(lines)

        lines.append(
            f"{'Seq':<4} | {'Tempo':<7} | {'Evento':<18} | {'PID/TID':<10} | "
            f"{'Alvo':<18} | {'Estado':<10} | {'Detalhes'}"
        )
        lines.append("-" * 92)
        for ev in entries:
            id_str = (
                f"{ev.pid}:{ev.tid}"
                if ev.pid is not None and ev.tid is not None
                else (str(ev.pid) if ev.pid is not None else "-")
            )
            target = f"{ev.process_name}/{ev.thread_name}".strip("/") or "-"
            lines.append(
                f"{ev.seq:<4} | {ev.timestamp_ms:<5}ms | {ev.event_type[:18]:<18} | "
                f"{id_str:<10} | {target[:18]:<18} | {ev.state[:10]:<10} | {ev.details}"
            )
        lines.append("======================================================================")
        return "\n".join(lines)

    def format_gantt(self) -> str:
        """Format CPU Gantt chart in Portuguese."""
        slices = self.get_gantt()
        lines = [
            "======================================================================",
            "                      DIAGRAMA DE GANTT DA CPU",
            "======================================================================",
        ]
        if not slices:
            lines.append("Nenhuma fatia de execução registrada no diagrama de Gantt.")
            lines.append("======================================================================")
            return "\n".join(lines)

        bar_parts: List[str] = []
        for idx, slc in enumerate(slices):
            tag = "IDLE" if slc.is_idle else f"{slc.process_name}:{slc.thread_name}[{slc.label}]"
            if idx == 0:
                bar_parts.append(f"[{slc.start_ms}ms]--{tag}--[{slc.end_ms}ms]")
            else:
                bar_parts.append(f"--{tag}--[{slc.end_ms}ms]")
        lines.append("".join(bar_parts))
        lines.append("----------------------------------------------------------------------")

        for slc in slices:
            if slc.is_idle:
                desc = "CPU OCIOSA (IDLE)"
            else:
                desc = f"PID {slc.pid} / TID {slc.tid} | {slc.process_name} ({slc.thread_name}) [{slc.label}]"
            lines.append(f"  [{slc.start_ms:>4} - {slc.end_ms:>4} ms] ({slc.duration_ms:>3} ms) : {desc}")

        lines.append("======================================================================")
        return "\n".join(lines)

    def format_frames_summary(
        self,
        memory_manager: Optional["MemoryManager"] = None,
        process_lookup: Optional[Any] = None,
        frames_summary: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Format synchronized physical memory frame summary in Portuguese."""
        if frames_summary is not None:
            rows = frames_summary
        elif memory_manager is not None:
            rows = self.build_frames_summary(memory_manager, process_lookup=process_lookup)
        else:
            raise ValueError("Informe memory_manager ou frames_summary para formatar o resumo de molduras.")

        algo = rows[0]["algorithm"] if rows else (
            memory_manager.algorithm.value if memory_manager is not None else "N/A"
        )
        lines = [
            "======================================================================",
            "            RESUMO SINCRONIZADO DAS MOLDURAS FÍSICAS (FRAMES)",
            "======================================================================",
            f"Algoritmo de Substituição Ativo: {algo}",
            "-" * 78,
            f"{'Moldura':<8} | {'Estado':<8} | {'PID':<5} | {'Página':<7} | {'Evento':<11} | {'Últ.Acesso':<10} | {'Dirty':<5} | {'Ref'}",
            "-" * 78,
        ]
        for row in rows:
            pid_str = str(row["pid"]) if row["pid"] is not None else "-"
            page_str = str(row["logical_page"]) if row["logical_page"] is not None else "-"
            access_str = f"{row['last_access']:.1f}" if row["last_access"] is not None else "-"
            dirty_str = "Sim" if row["dirty"] else "Não"
            ref_str = "Sim" if row["referenced"] else "Não"
            lines.append(
                f"{row['frame_id']:<8} | {row['state']:<8} | {pid_str:<5} | {page_str:<7} | "
                f"{row['last_event']:<11} | {access_str:<10} | {dirty_str:<5} | {ref_str}"
            )
        lines.append("======================================================================")
        return "\n".join(lines)

    def reset(self) -> None:
        """Clear all recorded timeline, Gantt, memory history, and counter state."""
        self._timeline.clear()
        self._next_seq = 1
        self._gantt.clear()
        self._memory_history.clear()
        self._memory_seq = 0
        self._latest_frame_access.clear()
        self._counters.clear()
        self._pid_counters.clear()
        self._pid_only_counters.clear()
        self._tid_counters.clear()
