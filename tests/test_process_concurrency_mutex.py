"""Unit tests for Stage 5 Wave 2: Mutex synchronization, FIFO queues, Buffer_Video, and Deadlock detection."""

from collections import deque
import unittest

from os_simulator.core.exceptions import (
    DeadlockDetectedException,
    InvalidStateTransitionException,
    MutexAlreadyExistsException,
    MutexNotFoundException,
    MutexOwnershipException,
    SynchronizationException,
)
from os_simulator.core.types import BlockReason, ProcessState, SyscallType
from os_simulator.process.manager import ProcessManager
from os_simulator.process.sync import Mutex, SynchronizationManager


class TestMutexCreationAndValidation(unittest.TestCase):
    """Verify Mutex CRUD, attribute defaults, serialization, and validation."""

    def setUp(self) -> None:
        self.pm = ProcessManager()
        self.sync = SynchronizationManager(self.pm)

    def test_create_get_list_and_to_dict(self):
        m = self.sync.create_mutex("Buffer_Video")
        self.assertIsInstance(m, Mutex)
        self.assertEqual(m.name, "Buffer_Video")
        self.assertFalse(m.locked)
        self.assertIsNone(m.owner_tid)
        self.assertIsNone(m.owner_pid)
        self.assertIsInstance(m.wait_queue, deque)
        self.assertEqual(len(m.wait_queue), 0)
        self.assertEqual((m.acquire_count, m.release_count, m.contention_count), (0, 0, 0))
        self.assertEqual(m.history, [])

        self.assertIs(self.sync.get_mutex("Buffer_Video"), m)
        self.assertIs(self.sync.get_or_create_mutex("Buffer_Video"), m)
        m2 = self.sync.get_or_create_mutex("Audio_Out")
        self.assertEqual([x.name for x in self.sync.list_mutexes()], ["Buffer_Video", "Audio_Out"])

        d = m.to_dict()
        self.assertEqual(d["name"], "Buffer_Video")
        self.assertFalse(d["locked"])
        self.assertEqual(d["wait_queue"], [])
        self.assertEqual(d["wait_queue_size"], 0)
        self.assertIn("LIVRE", self.sync.format_status())

    def test_empty_duplicate_and_missing_mutex_errors(self):
        with self.assertRaises(ValueError):
            self.sync.create_mutex("")
        with self.assertRaises(ValueError):
            self.sync.create_mutex("   ")
        with self.assertRaises(ValueError):
            self.sync.get_or_create_mutex("  ")
        with self.assertRaises(ValueError):
            Mutex(name="")

        self.sync.create_mutex("M1")
        with self.assertRaises(MutexAlreadyExistsException) as ctx:
            self.sync.create_mutex("M1")
        self.assertIsInstance(ctx.exception, SynchronizationException)

        with self.assertRaises(MutexNotFoundException):
            self.sync.get_mutex("Inexistente")


class TestMutexAcquireReleaseFIFOAndOwnership(unittest.TestCase):
    """Verify acquire, ownership enforcement, FIFO wait queue, and ownership handoff."""

    def setUp(self) -> None:
        self.pm = ProcessManager()
        self.sync = SynchronizationManager(self.pm)
        self.proc = self.pm.create_process("App", size_bytes=8192, create_default_thread=False)
        self.t1 = self.pm.create_thread(self.proc, "T1", priority=2, cpu_burst_ms=10)
        self.t2 = self.pm.create_thread(self.proc, "T2", priority=2, cpu_burst_ms=10)
        self.t3 = self.pm.create_thread(self.proc, "T3", priority=2, cpu_burst_ms=10)
        self.t4 = self.pm.create_thread(self.proc, "T4", priority=2, cpu_burst_ms=10)
        self.sync.create_mutex("M_FIFO")

    def test_acquire_release_and_ownership_enforcement(self):
        # Cannot release unlocked mutex
        with self.assertRaises(MutexOwnershipException):
            self.sync.release("M_FIFO", self.t1, timestamp_ms=0)

        # T1 acquires free mutex
        self.pm.transition_thread_state(self.t1, ProcessState.RUNNING, timestamp_ms=0)
        acquired = self.sync.acquire("M_FIFO", self.t1, timestamp_ms=1)
        self.assertTrue(acquired)

        m = self.sync.get_mutex("M_FIFO")
        self.assertTrue(m.locked)
        self.assertEqual(m.owner_tid, self.t1.tid)
        self.assertEqual(m.owner_pid, self.t1.pid)
        self.assertEqual(m.acquire_count, 1)
        self.assertEqual(self.t1.held_mutexes, ["M_FIFO"])

        # T2 cannot release mutex owned by T1
        with self.assertRaises(MutexOwnershipException):
            self.sync.release("M_FIFO", self.t2, timestamp_ms=2)

        # T1 releases with empty queue -> unlocked
        handoff = self.sync.release("M_FIFO", self.t1, timestamp_ms=3)
        self.assertIsNone(handoff)
        self.assertFalse(m.locked)
        self.assertIsNone(m.owner_tid)
        self.assertIsNone(m.owner_pid)
        self.assertEqual(m.release_count, 1)
        self.assertEqual(self.t1.held_mutexes, [])

    def test_fifo_queue_ordering_and_ownership_handoff(self):
        self.pm.transition_thread_state(self.t1, ProcessState.RUNNING, timestamp_ms=0)
        self.assertTrue(self.sync.acquire("M_FIFO", self.t1, timestamp_ms=0))

        # Contending threads enter wait_queue in strict FIFO order: T2, T3, T4
        # Test both RUNNING and READY initial states (READY transitions READY->RUNNING->BLOCKED)
        self.pm.transition_thread_state(self.t1, ProcessState.READY, timestamp_ms=2)
        self.pm.transition_thread_state(self.t2, ProcessState.RUNNING, timestamp_ms=2)
        self.assertFalse(self.sync.acquire("M_FIFO", self.t2, timestamp_ms=3))
        self.assertFalse(self.sync.acquire("M_FIFO", self.t3.tid, timestamp_ms=4))
        self.assertFalse(self.sync.acquire("M_FIFO", self.t4, timestamp_ms=5))

        m = self.sync.get_mutex("M_FIFO")
        self.assertEqual(list(m.wait_queue), [self.t2.tid, self.t3.tid, self.t4.tid])
        self.assertEqual(m.contention_count, 3)

        for waiter in (self.t2, self.t3, self.t4):
            self.assertEqual(waiter.state, ProcessState.BLOCKED)
            self.assertEqual(waiter.block_reason, BlockReason.MUTEX_WAIT)
            self.assertEqual(waiter.blocked_on, "M_FIFO")

        # T1 releases -> immediate handoff to T2 (head of FIFO)
        next_t = self.sync.release("M_FIFO", self.t1, timestamp_ms=6)
        self.assertIs(next_t, self.t2)
        self.assertTrue(m.locked)
        self.assertEqual(m.owner_tid, self.t2.tid)
        self.assertEqual(m.owner_pid, self.t2.pid)
        self.assertIn("M_FIFO", self.t2.held_mutexes)
        self.assertNotIn("M_FIFO", self.t1.held_mutexes)
        self.assertEqual(self.t2.state, ProcessState.READY)
        self.assertEqual(self.t2.block_reason, BlockReason.NONE)
        self.assertIsNone(self.t2.blocked_on)
        self.assertEqual(list(m.wait_queue), [self.t3.tid, self.t4.tid])

        # Terminate T3 while waiting -> T2 release must skip T3 and hand off to T4
        self.pm.transition_thread_state(self.t3, ProcessState.TERMINATED, timestamp_ms=7)
        next_t2 = self.sync.release("M_FIFO", self.t2, timestamp_ms=8)
        self.assertIs(next_t2, self.t4)
        self.assertEqual(m.owner_tid, self.t4.tid)
        self.assertEqual(self.t4.state, ProcessState.READY)
        self.assertEqual(list(m.wait_queue), [])

        # Final release leaves mutex unlocked
        self.assertIsNone(self.sync.release("M_FIFO", self.t4, timestamp_ms=10))
        self.assertFalse(m.locked)

        # Release skips all-TERMINATED wait_queue and unlocks cleanly
        self.assertTrue(self.sync.acquire("M_FIFO", self.t1, timestamp_ms=11))
        t5 = self.pm.create_thread(self.proc, "T5", priority=2, cpu_burst_ms=10)
        self.assertFalse(self.sync.acquire("M_FIFO", t5, timestamp_ms=12))
        self.pm.transition_thread_state(t5, ProcessState.TERMINATED, timestamp_ms=13)
        self.assertIsNone(self.sync.release("M_FIFO", self.t1, timestamp_ms=14))
        self.assertFalse(m.locked)
        self.assertIsNone(m.owner_tid)
        self.assertEqual(list(m.wait_queue), [])

    def test_acquire_rejects_blocked_new_and_terminated_threads(self):
        new_proc = self.pm.create_process(
            "NovoProc",
            size_bytes=4096,
            initial_state=ProcessState.NEW,
            create_default_thread=False,
        )
        t_new = self.pm.create_thread(new_proc, "T_new", cpu_burst_ms=5)
        with self.assertRaises(InvalidStateTransitionException):
            self.sync.acquire("M_FIFO", t_new, timestamp_ms=0)

        self.assertTrue(self.sync.acquire("M_FIFO", self.t1, timestamp_ms=0))
        self.assertFalse(self.sync.acquire("M_FIFO", self.t2, timestamp_ms=1))
        # Already BLOCKED T2 cannot call acquire again
        with self.assertRaises(InvalidStateTransitionException):
            self.sync.acquire("M_FIFO", self.t2, timestamp_ms=2)

        self.pm.transition_thread_state(self.t3, ProcessState.TERMINATED, timestamp_ms=2)
        with self.assertRaises(InvalidStateTransitionException):
            self.sync.acquire("M_FIFO", self.t3, timestamp_ms=3)

    def test_release_all_for_thread_unblocks_waiters_and_cleans_wait_queues(self):
        self.sync.create_mutex("M_A")
        self.sync.create_mutex("M_B")
        self.sync.create_mutex("M_C")

        # T1 holds M_A and M_B; T2 holds M_C
        self.assertTrue(self.sync.acquire("M_A", self.t1, timestamp_ms=0))
        self.assertTrue(self.sync.acquire("M_B", self.t1, timestamp_ms=0))
        self.assertTrue(self.sync.acquire("M_C", self.t2, timestamp_ms=0))

        # T3 waits on M_A; T4 waits on M_B; T1 waits on M_C (no cycle because T2 doesn't wait)
        self.assertFalse(self.sync.acquire("M_A", self.t3, timestamp_ms=1))
        self.assertFalse(self.sync.acquire("M_B", self.t4, timestamp_ms=1))
        self.assertFalse(self.sync.acquire("M_C", self.t1, timestamp_ms=2))

        # Kill T1 and release all its resources
        self.pm.transition_thread_state(self.t1, ProcessState.TERMINATED, timestamp_ms=5)
        unblocked = self.sync.release_all_for_thread(self.t1.tid, timestamp_ms=5)

        self.assertEqual({t.tid for t in unblocked}, {self.t3.tid, self.t4.tid})
        self.assertEqual(self.sync.get_mutex("M_A").owner_tid, self.t3.tid)
        self.assertEqual(self.sync.get_mutex("M_B").owner_tid, self.t4.tid)
        self.assertEqual(self.t3.state, ProcessState.READY)
        self.assertEqual(self.t4.state, ProcessState.READY)
        self.assertNotIn(self.t1.tid, self.sync.get_mutex("M_C").wait_queue)


class TestBufferVideoScenario(unittest.TestCase):
    """Verify Buffer_Video producer/consumer scenario and deterministic mutual exclusion."""

    def test_buffer_video_builder_and_round_robin_contention(self):
        pm = ProcessManager()
        sync = SynchronizationManager(pm)

        scenario = sync.setup_buffer_video_scenario(pm)
        mutex = scenario["mutex"]
        proc = scenario["process"]
        t1 = scenario["t1"]
        t2 = scenario["t2"]

        self.assertEqual(mutex.name, "Buffer_Video")
        self.assertEqual(proc.name, "Player_Video")
        self.assertEqual(t1.name, "T1")
        self.assertEqual(t2.name, "T2")
        self.assertEqual(len(t1.workload_steps), 2)
        self.assertEqual(len(t2.workload_steps), 2)
        self.assertEqual(t1.workload_steps[0].syscall_type, SyscallType.MUTEX_LOCK)
        self.assertEqual(t1.workload_steps[1].syscall_type, SyscallType.MUTEX_UNLOCK)

        # Simulate deterministic Round-Robin execution (quantum = 4 ms) driving WorkloadSteps
        quantum = 4
        ready_queue = deque([t1, t2])
        now_ms = 0
        critical_section_owners = []

        while ready_queue or any(t.state == ProcessState.BLOCKED for t in (t1, t2)):
            curr = ready_queue.popleft()
            pm.transition_thread_state(curr, ProcessState.RUNNING, timestamp_ms=now_ms, reason="dispatch")

            blocked_or_finished = False
            while curr.quantum_used_ms < quantum and curr.remaining_burst_ms > 0:
                now_ms += 1
                curr.cpu_consumed_ms += 1
                curr.quantum_used_ms += 1

                # Mutual exclusion invariant: at most 1 thread owns Buffer_Video at any ms
                if mutex.locked:
                    critical_section_owners.append((now_ms, mutex.owner_tid))
                    self.assertEqual(len(curr.held_mutexes) + len((t2 if curr is t1 else t1).held_mutexes), 1)

                for step in curr.workload_steps:
                    if not step.executed and step.trigger_cpu_ms == curr.cpu_consumed_ms:
                        step.executed = True
                        if step.syscall_type == SyscallType.MUTEX_LOCK:
                            if not sync.acquire(step.mutex_name, curr, timestamp_ms=now_ms):
                                blocked_or_finished = True
                                break
                        elif step.syscall_type == SyscallType.MUTEX_UNLOCK:
                            unblocked = sync.release(step.mutex_name, curr, timestamp_ms=now_ms)
                            if unblocked is not None:
                                ready_queue.append(unblocked)

                if blocked_or_finished:
                    break

                if curr.remaining_burst_ms == 0:
                    pm.transition_thread_state(curr, ProcessState.TERMINATED, timestamp_ms=now_ms, reason="exit")
                    blocked_or_finished = True
                    break

            if not blocked_or_finished:
                pm.transition_thread_state(curr, ProcessState.READY, timestamp_ms=now_ms, reason="quantum_expire")
                ready_queue.append(curr)

        self.assertEqual(t1.state, ProcessState.TERMINATED)
        self.assertEqual(t2.state, ProcessState.TERMINATED)
        self.assertEqual(proc.state, ProcessState.TERMINATED)
        self.assertFalse(mutex.locked)
        self.assertGreaterEqual(mutex.contention_count, 1)
        self.assertEqual(mutex.acquire_count, 2)
        self.assertEqual(mutex.release_count, 2)

        # Verify T1's critical section completed strictly before T2 entered hers
        t1_ticks = [ts for ts, owner in critical_section_owners if owner == t1.tid]
        t2_ticks = [ts for ts, owner in critical_section_owners if owner == t2.tid]
        self.assertTrue(t1_ticks)
        self.assertTrue(t2_ticks)
        self.assertLess(max(t1_ticks), min(t2_ticks))

    def test_buffer_video_validation_and_replace(self):
        pm = ProcessManager()
        sync = SynchronizationManager(pm)
        with self.assertRaises(ValueError):
            sync.setup_buffer_video_scenario(pm, t1_burst_ms=0)
        with self.assertRaises(ValueError):
            sync.setup_buffer_video_scenario(pm, lock_at_cpu_ms=4, unlock_at_cpu_ms=4)
        with self.assertRaises(ValueError):
            sync.setup_buffer_video_scenario(pm, lock_at_cpu_ms=1, unlock_at_cpu_ms=8, t1_burst_ms=8)

        first = sync.setup_buffer_video_scenario(pm)
        second = sync.setup_buffer_video_scenario(pm, replace_existing=True)
        self.assertEqual(first["process"].state, ProcessState.TERMINATED)
        self.assertEqual(second["process"].state, ProcessState.READY)


class TestDeadlockAndNoProgressDetection(unittest.TestCase):
    """Verify circular deadlocks, self-deadlocks, terminated-owner waits, and stall diagnostics."""

    def setUp(self) -> None:
        self.pm = ProcessManager()
        self.sync = SynchronizationManager(self.pm)
        self.proc = self.pm.create_process("DeadlockApp", size_bytes=8192, create_default_thread=False)
        self.t1 = self.pm.create_thread(self.proc, "T1", priority=2, cpu_burst_ms=10)
        self.t2 = self.pm.create_thread(self.proc, "T2", priority=2, cpu_burst_ms=10)
        self.t3 = self.pm.create_thread(self.proc, "T3", priority=2, cpu_burst_ms=10)
        self.sync.create_mutex("M1")
        self.sync.create_mutex("M2")
        self.sync.create_mutex("M3")

    def test_self_deadlock_detected(self):
        self.pm.transition_thread_state(self.t1, ProcessState.RUNNING, timestamp_ms=0)
        self.assertTrue(self.sync.acquire("M1", self.t1, timestamp_ms=1))

        with self.assertRaises(DeadlockDetectedException) as ctx:
            self.sync.acquire("M1", self.t1, timestamp_ms=2)

        self.assertEqual(
            ctx.exception.cycle,
            [f"TID:{self.t1.tid}(T1) -> Mutex:M1 -> TID:{self.t1.tid}(T1)"],
        )
        self.assertEqual(self.sync.get_mutex("M1").history[-1]["event"], "SELF_DEADLOCK")

    def test_circular_two_thread_deadlock_m1_m2(self):
        self.assertTrue(self.sync.acquire("M1", self.t1, timestamp_ms=0))
        self.assertTrue(self.sync.acquire("M2", self.t2, timestamp_ms=1))

        # T1 requests M2 held by T2 -> blocks, no cycle yet
        self.assertFalse(self.sync.acquire("M2", self.t1, timestamp_ms=2))
        self.assertEqual(self.sync.detect_deadlocks(), [])

        # T2 requests M1 held by T1 -> cycle M1/M2 immediately detected!
        with self.assertRaises(DeadlockDetectedException) as ctx:
            self.sync.acquire("M1", self.t2, timestamp_ms=3)

        cycle_text = " ; ".join(ctx.exception.cycle)
        self.assertIn("M1", cycle_text)
        self.assertIn("M2", cycle_text)
        self.assertIn(f"TID:{self.t1.tid}(T1)", cycle_text)
        self.assertIn(f"TID:{self.t2.tid}(T2)", cycle_text)
        self.assertIn("ALERTA DE DEADLOCK", self.sync.format_status())

        diag = self.sync.check_no_progress(has_ready=False, has_running=False, has_pending_events=False)
        self.assertIsNotNone(diag)
        assert diag is not None
        self.assertTrue(diag["stalled"])
        self.assertTrue(diag["deadlock_detected"])
        self.assertEqual(diag["type"], "DEADLOCK")
        self.assertEqual(len(diag["cycles"]), 1)

    def test_three_thread_cycle_excludes_non_cycle_tail(self):
        # Verify both smaller-TID and larger-TID bystanders waiting on cycle members are excluded
        bystander_small = self.t1
        c1 = self.t2
        c2 = self.t3
        c3 = self.pm.create_thread(self.proc, "T4", priority=2, cpu_burst_ms=10)
        bystander_large = self.pm.create_thread(self.proc, "T5", priority=2, cpu_burst_ms=10)

        self.assertTrue(self.sync.acquire("M1", c1, timestamp_ms=0))
        self.assertTrue(self.sync.acquire("M2", c2, timestamp_ms=0))
        self.assertTrue(self.sync.acquire("M3", c3, timestamp_ms=0))

        self.assertFalse(self.sync.acquire("M1", bystander_small, timestamp_ms=1))
        self.assertFalse(self.sync.acquire("M1", bystander_large, timestamp_ms=1))
        self.assertFalse(self.sync.acquire("M2", c1, timestamp_ms=2))
        self.assertFalse(self.sync.acquire("M3", c2, timestamp_ms=3))

        with self.assertRaises(DeadlockDetectedException) as ctx:
            self.sync.acquire("M1", c3, timestamp_ms=4)

        self.assertEqual(len(ctx.exception.cycle), 3)
        joined = " ; ".join(ctx.exception.cycle)
        self.assertNotIn(f"TID:{bystander_small.tid}(", joined)
        self.assertNotIn(f"TID:{bystander_large.tid}(", joined)

    def test_status_clear_and_timestamp_validation(self):
        with self.assertRaises(ValueError):
            self.sync.acquire("M1", self.t1, timestamp_ms=-1)
        with self.assertRaises(ValueError):
            self.sync.release("M1", self.t1, timestamp_ms=True)  # type: ignore[arg-type]

        self.assertTrue(self.sync.acquire("M1", self.t1.tid, timestamp_ms=0))
        status = self.sync.get_status()
        self.assertEqual(status["mutex_count"], 3)
        self.assertEqual(status["deadlocks"], [])
        self.assertIn("TRAVADO", self.sync.format_status())

        self.sync.clear()
        self.assertEqual(self.sync.list_mutexes(), [])
        self.assertIn("Nenhum mutex registrado", self.sync.format_status())

    def test_terminated_owner_and_no_progress_stall_detection(self):
        # 1. Thread waiting on a TERMINATED owner (e.g. crash without release_all)
        self.assertTrue(self.sync.acquire("M1", self.t1, timestamp_ms=0))
        self.assertFalse(self.sync.acquire("M1", self.t2, timestamp_ms=1))
        self.pm.transition_thread_state(self.t1, ProcessState.TERMINATED, timestamp_ms=2)

        cycles = self.sync.detect_deadlocks()
        self.assertEqual(len(cycles), 1)
        self.assertIn("[TERMINATED]", cycles[0][0])
        self.assertIn(f"TID:{self.t2.tid}(T2)", cycles[0][0])

        # Clean up M1 for stall-without-cycle test
        self.sync.release_all_for_thread(self.t1.tid, timestamp_ms=3)
        self.pm.transition_thread_state(self.t2, ProcessState.TERMINATED, timestamp_ms=3)

        # 2. Active thread blocked on IO_WAIT with no pending wakeup events -> STALL
        self.pm.transition_thread_state(self.t3, ProcessState.RUNNING, timestamp_ms=4)
        self.pm.transition_thread_state(
            self.t3,
            ProcessState.BLOCKED,
            timestamp_ms=5,
            reason="io_sem_evento",
            block_reason=BlockReason.IO_WAIT,
            blocked_on="block:9",
        )
        # Progress still possible when ready/running/pending flags are True
        self.assertIsNone(self.sync.check_no_progress(has_ready=True, has_running=False, has_pending_events=False))
        self.assertIsNone(self.sync.check_no_progress(has_ready=False, has_running=True, has_pending_events=False))
        self.assertIsNone(self.sync.check_no_progress(has_ready=False, has_running=False, has_pending_events=True))

        stall = self.sync.check_no_progress(has_ready=False, has_running=False, has_pending_events=False)
        self.assertIsNotNone(stall)
        assert stall is not None
        self.assertTrue(stall["stalled"])
        self.assertFalse(stall["deadlock_detected"])
        self.assertEqual(stall["type"], "STALL")
        self.assertEqual(stall["blocked_tids"], [self.t3.tid])
        self.assertIn("IO_WAIT", stall["message"])

        # Once T3 terminates, no active blocked threads remain -> check_no_progress returns None
        self.pm.transition_thread_state(self.t3, ProcessState.TERMINATED, timestamp_ms=6)
        self.assertIsNone(self.sync.check_no_progress(has_ready=False, has_running=False, has_pending_events=False))


if __name__ == "__main__":
    unittest.main()
