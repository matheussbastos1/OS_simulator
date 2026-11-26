"""Process subsystem initialization and Stage 5 public exports."""

from os_simulator.process.engine import ExecutionEngine
from os_simulator.process.manager import ProcessManager
from os_simulator.process.metrics import (
    FrameAccessRecord,
    GanttSlice,
    MetricsCollector,
    ProcessMetrics,
    SimulationMetrics,
    ThreadMetrics,
    TimelineEntry,
    build_frames_summary,
    record_memory_access,
)
from os_simulator.process.pcb import Process
from os_simulator.process.scheduler import PriorityRoundRobinScheduler
from os_simulator.process.state_machine import ProcessStateMachine, StateTransitionRecord
from os_simulator.process.sync import Mutex, SynchronizationManager
from os_simulator.process.syscalls import (
    BlockRecord,
    BlockRegistry,
    IOProfile,
    SyscallDispatcher,
    SyscallExecutionRecord,
    SyscallSpec,
)
from os_simulator.process.thread import SimulatedThread, WorkloadStep

__all__ = [
    "BlockRecord",
    "BlockRegistry",
    "ExecutionEngine",
    "FrameAccessRecord",
    "GanttSlice",
    "IOProfile",
    "MetricsCollector",
    "Mutex",
    "PriorityRoundRobinScheduler",
    "Process",
    "ProcessManager",
    "ProcessMetrics",
    "ProcessStateMachine",
    "SimulatedThread",
    "SimulationMetrics",
    "StateTransitionRecord",
    "SynchronizationManager",
    "SyscallDispatcher",
    "SyscallExecutionRecord",
    "SyscallSpec",
    "ThreadMetrics",
    "TimelineEntry",
    "WorkloadStep",
    "build_frames_summary",
    "record_memory_access",
]
