"""Unit tests for Stage 5 Wave 1: LogicalClock, EventManager, StateMachine, Thread, PCB, and ProcessManager."""

import unittest

from os_simulator.core.clock import LogicalClock
from os_simulator.core.events import EVENT_PRIORITY_MAP, EventManager, SimulationEvent
from os_simulator.core.exceptions import (
    DeadlockDetectedException,
    InvalidProcessStateException,
    InvalidStateTransitionException,
    MutexAlreadyExistsException,
    MutexNotFoundException,
    MutexOwnershipException,
    PermissionDeniedException,
    ProcessException,
    SchedulerException,
    SimulationStallException,
    SynchronizationException,
    ThreadAlreadyExistsException,
    ThreadNotFoundException,
)
from os_simulator.core.types import (
    AuditEventType,
    BlockReason,
    IOProfileType,
    ProcessState,
    ProcessType,
    SimulationEventType,
    SyscallType,
)
from os_simulator.process.manager import ProcessManager
from os_simulator.process.pcb import Process
from os_simulator.process.state_machine import ProcessStateMachine
from os_simulator.process.thread import SimulatedThread, WorkloadStep


class TestStage5TypesAndExceptions(unittest.TestCase):
    """Verify backward compatibility and new Stage 5 enums and exceptions."""

    def test_process_state_aliases_and_legacy_waiting(self):
        self.assertEqual(ProcessState.NEW.value, "NEW")
        self.assertEqual(ProcessState.READY.value, "READY")
        self.assertEqual(ProcessState.RUNNING.value, "RUNNING")
        self.assertEqual(ProcessState.BLOCKED.value, "BLOCKED")
        self.assertEqual(ProcessState.WAITING.value, "WAITING")
        self.assertEqual(ProcessState.TERMINATED.value, "TERMINATED")

        self.assertIs(ProcessState.NOVO, ProcessState.NEW)
        self.assertIs(ProcessState.PRONTO, ProcessState.READY)
        self.assertIs(ProcessState.EXECUTANDO, ProcessState.RUNNING)
        self.assertIs(ProcessState.BLOQUEADO, ProcessState.BLOCKED)
        self.assertIs(ProcessState.CONCLUIDO, ProcessState.TERMINATED)

        self.assertEqual(ProcessState.normalize(ProcessState.WAITING), ProcessState.BLOCKED)
        self.assertEqual(ProcessState.from_string("bloqueado"), ProcessState.BLOCKED)
        self.assertEqual(ProcessState.from_string("concluído"), ProcessState.TERMINATED)

    def test_stage5_enums_and_audit_types(self):
        self.assertEqual(SyscallType.from_string("sleep"), SyscallType.SLEEP_WAIT)
        self.assertEqual(SyscallType.from_string("io_read"), SyscallType.IO_READ)
        self.assertEqual(IOProfileType.from_string("periodic"), IOProfileType.PERIODIC)
        self.assertEqual(BlockReason.MUTEX_WAIT.value, "MUTEX_WAIT")
        self.assertEqual(SimulationEventType.IO_COMPLETION.value, "IO_COMPLETION")
        self.assertEqual(AuditEventType.PROCESS_LIFECYCLE.value, "PROCESS_LIFECYCLE")
        self.assertEqual(AuditEventType.DEADLOCK_DETECTED.value, "DEADLOCK_DETECTED")
        self.assertEqual(AuditEventType.USER_MANAGEMENT.value, "USER_MANAGEMENT")

    def test_exception_hierarchy(self):
        err = InvalidStateTransitionException("inválida", from_state="BLOCKED", to_state="RUNNING", entity_id="TID:1")
        self.assertIsInstance(err, InvalidProcessStateException)
        self.assertIsInstance(err, ProcessException)
        self.assertEqual(err.from_state, "BLOCKED")
        self.assertEqual(err.to_state, "RUNNING")

        dl = DeadlockDetectedException("ciclo detectado", cycle=["T1", "T2", "T1"])
        self.assertIsInstance(dl, SynchronizationException)
        self.assertIsInstance(dl, ProcessException)
        self.assertEqual(dl.cycle, ["T1", "T2", "T1"])

        for cls in (
            ThreadNotFoundException,
            ThreadAlreadyExistsException,
            SchedulerException,
            SimulationStallException,
        ):
            self.assertTrue(issubclass(cls, ProcessException))
        for cls in (
            MutexNotFoundException,
            MutexAlreadyExistsException,
            MutexOwnershipException,
        ):
            self.assertTrue(issubclass(cls, SynchronizationException))


class TestLogicalClock(unittest.TestCase):
    """Verify strict integer millisecond logical clock behavior."""

    def test_clock_progression_and_reset(self):
        clock = LogicalClock()
        self.assertEqual(clock.now_ms, 0)

        self.assertEqual(clock.advance_by(0), 0)
        self.assertEqual(clock.advance_by(15), 15)
        self.assertEqual(clock.now_ms, 15)

        self.assertEqual(clock.advance_to(15), 15)
        self.assertEqual(clock.advance_to(40), 40)
        self.assertEqual(clock.now_ms, 40)

        clock.reset()
        self.assertEqual(clock.now_ms, 0)

    def test_clock_rejects_negative_backwards_and_non_int(self):
        with self.assertRaises(ValueError):
            LogicalClock(-1)
        with self.assertRaises(ValueError):
            LogicalClock(True)  # type: ignore[arg-type]

        clock = LogicalClock(20)
        with self.assertRaises(ValueError):
            clock.advance_by(-5)
        with self.assertRaises(ValueError):
            clock.advance_to(19)
        with self.assertRaises(ValueError):
            clock.advance_by(1.5)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            clock.advance_to(False)  # type: ignore[arg-type]


class TestEventManager(unittest.TestCase):
    """Verify deterministic discrete-event scheduling, tie-breaking, and cancellation."""

    def test_simultaneous_priority_and_seq_tie_breaking(self):
        em = EventManager()
        # Schedule in reverse priority order at identical timestamp t=100
        em.schedule_at(100, SimulationEventType.DISPATCH_RESCHEDULE, pid=1)
        em.schedule_at(100, SimulationEventType.SYSCALL_REQUEST, pid=2)
        em.schedule_at(100, SimulationEventType.QUANTUM_EXPIRE, pid=3)
        em.schedule_at(100, SimulationEventType.THREAD_ARRIVAL, pid=4)
        em.schedule_at(100, SimulationEventType.PROCESS_ARRIVAL, pid=5)
        em.schedule_at(100, SimulationEventType.SLEEP_WAKEUP, pid=6)
        em.schedule_at(100, SimulationEventType.MUTEX_WAKEUP, pid=7)
        em.schedule_at(100, SimulationEventType.IO_COMPLETION, pid=8)
        em.schedule_at(100, SimulationEventType.PROCESS_TERMINATED, pid=9)

        popped = em.pop_ready_at(100)
        self.assertEqual(
            [e.event_type for e in popped],
            [
                SimulationEventType.PROCESS_TERMINATED,
                SimulationEventType.IO_COMPLETION,
                SimulationEventType.SLEEP_WAKEUP,   # prio 2, earlier seq than MUTEX_WAKEUP
                SimulationEventType.MUTEX_WAKEUP,   # prio 2, later seq
                SimulationEventType.THREAD_ARRIVAL, # prio 3, earlier seq than PROCESS_ARRIVAL
                SimulationEventType.PROCESS_ARRIVAL,# prio 3, later seq
                SimulationEventType.QUANTUM_EXPIRE,
                SimulationEventType.SYSCALL_REQUEST,
                SimulationEventType.DISPATCH_RESCHEDULE,
            ],
        )
        self.assertTrue(em.is_empty())

    def test_relative_schedule_uses_clock_and_cancel_works(self):
        clock = LogicalClock(50)
        em = EventManager(clock=clock)

        e1 = em.schedule(10, SimulationEventType.IO_COMPLETION, pid=100, tid=1)
        e2 = em.schedule(5, SimulationEventType.QUANTUM_EXPIRE, pid=100, tid=1)
        e3 = em.schedule(20, SimulationEventType.SLEEP_WAKEUP, pid=101, tid=2)

        self.assertEqual(e1.timestamp_ms, 60)
        self.assertEqual(e2.timestamp_ms, 55)
        self.assertEqual(len(em), 3)

        # Cancel earliest event e2
        self.assertTrue(em.cancel_event(e2.seq))
        self.assertFalse(em.cancel_event(e2.seq))
        self.assertEqual(len(em), 2)
        self.assertIs(em.peek_next(), e1)

        # Cancel by entity pid=100
        cancelled = em.cancel_for_entity(pid=100)
        self.assertEqual(cancelled, 1)
        self.assertIs(em.peek_next(), e3)

        # Pop remaining and verify clear resets seq
        self.assertIs(em.pop_next(), e3)
        self.assertIsNone(em.pop_next())
        self.assertTrue(em.is_empty())

        em.schedule_at(10, SimulationEventType.PROCESS_ARRIVAL, pid=100)
        em.clear()
        fresh = em.schedule_at(0, SimulationEventType.PROCESS_ARRIVAL, pid=100)
        self.assertEqual(fresh.seq, 1)

    def test_pending_events_and_validation(self):
        em = EventManager()
        a = em.schedule_at(30, SimulationEventType.IO_COMPLETION, pid=1)
        b = em.schedule_at(10, SimulationEventType.IO_COMPLETION, pid=2)
        c = em.schedule_at(20, SimulationEventType.IO_COMPLETION, pid=3)
        em.cancel_event(c.seq)
        self.assertEqual(em.pending_events(), [b, a])

        with self.assertRaises(ValueError):
            em.schedule_at(-1, SimulationEventType.IO_COMPLETION)
        with self.assertRaises(ValueError):
            em.schedule(-3, SimulationEventType.IO_COMPLETION)


class TestProcessStateMachine(unittest.TestCase):
    """Verify valid, invalid, self, and legacy WAITING state transitions."""

    def test_all_valid_transitions_and_history(self):
        sm = ProcessStateMachine()
        proc = Process(pid=100, name="App", size_bytes=4096, state=ProcessState.NEW)

        r1 = sm.transition(proc, ProcessState.READY, timestamp_ms=0, reason="admissão")
        self.assertEqual((r1.from_state, r1.to_state), (ProcessState.NEW, ProcessState.READY))

        r2 = sm.transition(proc, ProcessState.RUNNING, timestamp_ms=5, reason="dispatch")
        self.assertEqual((r2.from_state, r2.to_state), (ProcessState.READY, ProcessState.RUNNING))

        r3 = sm.transition(proc, ProcessState.BLOCKED, timestamp_ms=9, reason="io")
        self.assertEqual((r3.from_state, r3.to_state), (ProcessState.RUNNING, ProcessState.BLOCKED))

        r4 = sm.transition(proc, ProcessState.READY, timestamp_ms=14, reason="io_done")
        self.assertEqual((r4.from_state, r4.to_state), (ProcessState.BLOCKED, ProcessState.READY))

        r5 = sm.transition(proc, ProcessState.RUNNING, timestamp_ms=14, reason="dispatch")
        r6 = sm.transition(proc, ProcessState.READY, timestamp_ms=18, reason="quantum")
        r7 = sm.transition(proc, ProcessState.TERMINATED, timestamp_ms=20, reason="kill")
        self.assertEqual(proc.state, ProcessState.TERMINATED)
        self.assertEqual(len(sm.history), 7)
        self.assertEqual(len(sm.get_history("PID:100")), 7)
        self.assertEqual(r5.to_state, ProcessState.RUNNING)
        self.assertEqual(r6.to_state, ProcessState.READY)
        self.assertEqual(r7.to_state, ProcessState.TERMINATED)

    def test_invalid_transitions_and_self_transitions_rejected(self):
        sm = ProcessStateMachine()

        invalid_pairs = [
            (ProcessState.NEW, ProcessState.NEW),
            (ProcessState.READY, ProcessState.READY),
            (ProcessState.RUNNING, ProcessState.RUNNING),
            (ProcessState.BLOCKED, ProcessState.BLOCKED),
            (ProcessState.TERMINATED, ProcessState.TERMINATED),
            (ProcessState.NEW, ProcessState.RUNNING),
            (ProcessState.NEW, ProcessState.BLOCKED),
            (ProcessState.READY, ProcessState.BLOCKED),
            (ProcessState.BLOCKED, ProcessState.RUNNING),
            (ProcessState.WAITING, ProcessState.RUNNING),
            (ProcessState.TERMINATED, ProcessState.READY),
            (ProcessState.TERMINATED, ProcessState.RUNNING),
            (ProcessState.TERMINATED, ProcessState.BLOCKED),
        ]
        for src, dst in invalid_pairs:
            with self.subTest(src=src, dst=dst):
                self.assertFalse(sm.can_transition(src, dst))
                with self.assertRaises(InvalidStateTransitionException) as ctx:
                    sm.validate_transition(src, dst, entity_id="PID:100")
                self.assertIsInstance(ctx.exception, InvalidProcessStateException)

    def test_legacy_waiting_normalizes_to_blocked(self):
        sm = ProcessStateMachine()
        proc = Process(pid=101, name="Legacy", size_bytes=4096, state=ProcessState.RUNNING)
        rec = sm.transition(proc, ProcessState.WAITING, timestamp_ms=10, reason="legacy_wait")
        self.assertEqual(rec.to_state, ProcessState.BLOCKED)
        self.assertEqual(proc.state, ProcessState.BLOCKED)

        rec2 = sm.transition(proc, ProcessState.PRONTO, timestamp_ms=20, reason="wakeup")
        self.assertEqual(rec2.to_state, ProcessState.READY)


class TestThreadAndProcessManagerLifecycle(unittest.TestCase):
    """Verify thread model, ProcessManager Stage 4 compat, and multi-thread parent sync."""

    def test_stage4_compatibility_defaults(self):
        pm = ProcessManager()
        proc = pm.create_process("App_Stage4", size_bytes=8192, process_type=ProcessType.NORMAL)
        self.assertEqual(proc.state, ProcessState.READY)
        self.assertEqual(proc.priority, 3)
        self.assertEqual(proc.cpu_burst_ms, 0)
        self.assertEqual(proc.threads, {})

        # Nucleo_Base cannot be terminated or receive user threads
        with self.assertRaises(PermissionDeniedException):
            pm.terminate_process(0)
        with self.assertRaises(PermissionDeniedException):
            pm.create_thread(0, "evil")

        # ensure_main_thread lazily creates main when needed
        main_thread = pm.ensure_main_thread(proc)
        self.assertEqual(main_thread.name, "main")
        self.assertEqual(main_thread.state, ProcessState.READY)
        self.assertIs(pm.ensure_main_thread(proc), main_thread)

    def test_single_threaded_process_with_burst_creates_main_thread(self):
        pm = ProcessManager()
        proc = pm.create_process(
            "Worker",
            size_bytes=4096,
            priority=2,
            cpu_burst_ms=25,
            arrival_time_ms=10,
            initial_state=ProcessState.NEW,
        )
        self.assertEqual(proc.state, ProcessState.NEW)
        self.assertEqual(len(proc.threads), 1)
        main_t = pm.get_thread_by_name("Worker", "main")
        self.assertEqual(main_t.state, ProcessState.NEW)
        self.assertEqual(main_t.remaining_burst_ms, 25)
        self.assertIsNone(main_t.ready_since_ms)

        pm.admit_process(proc, timestamp_ms=10)
        self.assertEqual(proc.state, ProcessState.READY)
        self.assertEqual(main_t.state, ProcessState.READY)
        self.assertEqual(main_t.ready_since_ms, 10)

        # Re-admitting READY process must fail
        with self.assertRaises(InvalidStateTransitionException):
            pm.admit_process(proc, timestamp_ms=11)

    def test_multithreaded_lifecycle_and_parent_state_sync(self):
        pm = ProcessManager()
        proc = pm.create_process(
            "Player_Video",
            size_bytes=16384,
            initial_state=ProcessState.NEW,
            create_default_thread=False,
        )
        t1 = pm.create_thread(proc, "T1", priority=1, cpu_burst_ms=10, arrival_time_ms=0)
        t2 = pm.create_thread(proc, "T2", priority=2, cpu_burst_ms=12, arrival_time_ms=0)
        self.assertEqual(proc.state, ProcessState.NEW)

        pm.admit_process(proc, timestamp_ms=0)
        self.assertEqual(proc.state, ProcessState.READY)
        self.assertEqual(t1.state, ProcessState.READY)
        self.assertEqual(t2.state, ProcessState.READY)

        # T1 runs -> parent RUNNING
        pm.transition_thread_state(t1, ProcessState.RUNNING, timestamp_ms=2, reason="dispatch")
        self.assertEqual(proc.state, ProcessState.RUNNING)
        self.assertEqual(t1.start_time_ms, 2)
        self.assertEqual(t1.total_wait_ms, 2)

        # T1 blocks on mutex while T2 is READY -> parent stays READY
        t1.quantum_used_ms = 3
        pm.transition_thread_state(
            t1,
            ProcessState.BLOCKED,
            timestamp_ms=5,
            reason="mutex_wait",
            block_reason=BlockReason.MUTEX_WAIT,
            blocked_on="Buffer_Video",
        )
        self.assertEqual(t1.quantum_used_ms, 0)
        self.assertEqual(t1.block_reason, BlockReason.MUTEX_WAIT)
        self.assertEqual(t1.blocked_on, "Buffer_Video")
        self.assertEqual(proc.state, ProcessState.READY)

        # T2 runs and also blocks -> parent becomes BLOCKED
        pm.transition_thread_state(t2, ProcessState.RUNNING, timestamp_ms=5, reason="dispatch")
        pm.transition_thread_state(
            t2,
            ProcessState.BLOCKED,
            timestamp_ms=8,
            reason="io_wait",
            block_reason=BlockReason.IO_WAIT,
            blocked_on="block:3",
        )
        self.assertEqual(proc.state, ProcessState.BLOCKED)

        # T1 unblocks -> parent becomes READY and T1 block accumulators updated
        pm.transition_thread_state(t1, ProcessState.READY, timestamp_ms=12, reason="mutex_handoff")
        self.assertEqual(t1.total_blocked_ms, 7)
        self.assertEqual(t1.block_reason, BlockReason.NONE)
        self.assertIsNone(t1.blocked_on)
        self.assertEqual(proc.state, ProcessState.READY)

        # Terminate parent process -> cascades to all active threads
        pm.terminate_process(proc.pid, timestamp_ms=20)
        self.assertEqual(proc.state, ProcessState.TERMINATED)
        self.assertEqual(t1.state, ProcessState.TERMINATED)
        self.assertEqual(t2.state, ProcessState.TERMINATED)
        self.assertEqual(proc.finish_time_ms, 20)
        self.assertEqual(t1.finish_time_ms, 20)
        self.assertEqual(t2.finish_time_ms, 20)

    def test_thread_and_process_validation(self):
        pm = ProcessManager()
        proc = pm.create_process("App", size_bytes=4096)
        pm.create_thread(proc, "T1", priority=1, cpu_burst_ms=5)

        with self.assertRaises(ThreadAlreadyExistsException):
            pm.create_thread(proc, "T1", priority=1, cpu_burst_ms=5)

        with self.assertRaises(ThreadNotFoundException):
            pm.get_thread("Ghost", process_identifier=proc)

        with self.assertRaises(ValueError):
            pm.create_process("BadPrio", size_bytes=4096, priority=0)
        with self.assertRaises(ValueError):
            pm.create_process("BadBurst", size_bytes=4096, cpu_burst_ms=-1)
        with self.assertRaises(ValueError):
            pm.create_process("BadArr", size_bytes=4096, arrival_time_ms=-2)
        with self.assertRaises(ValueError):
            SimulatedThread(tid=1, pid=100, name="Bad", priority=0)
        with self.assertRaises(ValueError):
            WorkloadStep(trigger_cpu_ms=-1, syscall_type=SyscallType.YIELD)

        step = WorkloadStep(trigger_cpu_ms=2, syscall_type=SyscallType.IO_READ, duration_ms=5, block_id=3)
        t = pm.get_thread_by_name(proc, "T1")
        t.add_workload_step(step)
        d = t.to_dict()
        self.assertEqual(d["workload_steps"][0]["syscall_type"], "IO_READ")
        self.assertEqual(d["remaining_burst_ms"], 5)


if __name__ == "__main__":
    unittest.main()
