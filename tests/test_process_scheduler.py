"""Unit tests for PriorityRoundRobinScheduler (Stage 5 Wave 2 Author A)."""

import unittest

from os_simulator.core.exceptions import SchedulerException
from os_simulator.core.types import BlockReason, ProcessState
from os_simulator.process.manager import ProcessManager
from os_simulator.process.scheduler import PriorityRoundRobinScheduler
from os_simulator.process.thread import SimulatedThread


class TestPriorityRoundRobinSchedulerConfig(unittest.TestCase):
    """Verify scheduler initialization, quantum configuration, and validation."""

    def test_defaults_and_valid_quantum_updates(self):
        pm = ProcessManager()
        scheduler = PriorityRoundRobinScheduler(pm)

        self.assertEqual(scheduler.quantum_ms, 4)
        self.assertEqual(scheduler.context_switch_overhead_ms, 0)
        self.assertEqual(sorted(scheduler.queues.keys()), [1, 2, 3, 4, 5])
        self.assertIsNone(scheduler.running_tid)
        self.assertIsNone(scheduler.last_dispatched_tid)
        self.assertTrue(scheduler.is_ready_empty())

        scheduler.set_quantum(8)
        self.assertEqual(scheduler.quantum_ms, 8)
        scheduler.set_quantum(1)
        self.assertEqual(scheduler.quantum_ms, 1)
        scheduler.set_context_switch_overhead(2)
        self.assertEqual(scheduler.context_switch_overhead_ms, 2)

    def test_invalid_quantum_and_config_rejected(self):
        pm = ProcessManager()
        for invalid in (0, -1, -10, True, False, 2.5, "4", None):
            with self.subTest(quantum=invalid):
                with self.assertRaises(SchedulerException):
                    PriorityRoundRobinScheduler(pm, quantum_ms=invalid)  # type: ignore[arg-type]

        scheduler = PriorityRoundRobinScheduler(pm, quantum_ms=4)
        for invalid in (0, -3, True, False, 1.2, "2"):
            with self.subTest(quantum=invalid):
                with self.assertRaises(SchedulerException):
                    scheduler.set_quantum(invalid)  # type: ignore[arg-type]
        self.assertEqual(scheduler.quantum_ms, 4)

        for invalid_overhead in (-1, True, 0.5, "1"):
            with self.assertRaises(SchedulerException):
                scheduler.set_context_switch_overhead(invalid_overhead)  # type: ignore[arg-type]

        with self.assertRaises(SchedulerException):
            PriorityRoundRobinScheduler(None)  # type: ignore[arg-type]

        for invalid_delta in (-1, True, False, 1.5):
            with self.assertRaises(SchedulerException):
                scheduler.tick_quantum(invalid_delta)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            scheduler.dispatch_next(timestamp_ms=-1)
        with self.assertRaises(ValueError):
            scheduler.on_quantum_expired(timestamp_ms=True)  # type: ignore[arg-type]


class TestPriorityOrderingAndPreemption(unittest.TestCase):
    """Verify multi-level priority dispatch order, FIFO tie-breaking, and preemption."""

    def setUp(self):
        self.pm = ProcessManager()
        self.scheduler = PriorityRoundRobinScheduler(self.pm, quantum_ms=4)

    def _make_thread(
        self,
        proc_name: str,
        priority: int = 3,
        burst: int = 10,
        arrival: int = 0,
        state: ProcessState = ProcessState.READY,
    ) -> SimulatedThread:
        proc = self.pm.create_process(
            name=proc_name,
            size_bytes=4096,
            priority=priority,
            cpu_burst_ms=burst,
            arrival_time_ms=arrival,
            initial_state=state,
            create_default_thread=True,
        )
        return self.pm.get_thread_by_name(proc, "main")

    def test_priority_ordering_and_fifo_within_same_level(self):
        t_p5 = self._make_thread("P5", priority=5)
        t_p3_a = self._make_thread("P3_A", priority=3)
        t_p1 = self._make_thread("P1", priority=1)
        t_p3_b = self._make_thread("P3_B", priority=3)
        t_p2 = self._make_thread("P2", priority=2)
        t_p7 = self._make_thread("P7", priority=7)

        for t in (t_p5, t_p3_a, t_p1, t_p3_b, t_p2, t_p7):
            preempted = self.scheduler.enqueue_ready(t, timestamp_ms=0)
            self.assertIsNone(preempted)

        # select_next does not modify state or pop from queue
        self.assertIs(self.scheduler.select_next(), t_p1)
        self.assertEqual(t_p1.state, ProcessState.READY)
        self.assertEqual(
            [t.name for t in self.scheduler.get_ready_list()],
            ["main", "main", "main", "main", "main", "main"],
        )
        self.assertEqual(
            [t.tid for t in self.scheduler.get_ready_list()],
            [t_p1.tid, t_p2.tid, t_p3_a.tid, t_p3_b.tid, t_p5.tid, t_p7.tid],
        )

        # Dispatch in exact priority + FIFO order
        dispatched_tids = []
        while not self.scheduler.is_ready_empty():
            running = self.scheduler.dispatch_next(timestamp_ms=0)
            self.assertIsNotNone(running)
            assert running is not None
            dispatched_tids.append(running.tid)
            self.assertEqual(running.state, ProcessState.RUNNING)
            self.pm.transition_thread_state(running, ProcessState.TERMINATED, timestamp_ms=1)
            self.scheduler.on_current_suspended()

        self.assertEqual(
            dispatched_tids,
            [t_p1.tid, t_p2.tid, t_p3_a.tid, t_p3_b.tid, t_p5.tid, t_p7.tid],
        )
        self.assertIsNone(self.scheduler.select_next())
        self.assertIsNone(self.scheduler.dispatch_next(timestamp_ms=10))

    def test_cross_priority_preemption_resets_quantum_and_appends_to_tail(self):
        t_low_1 = self._make_thread("Low1", priority=3, burst=12)
        t_low_2 = self._make_thread("Low2", priority=3, burst=12)
        t_same = self._make_thread("Same", priority=3, burst=12)
        t_very_low = self._make_thread("VeryLow", priority=5, burst=12)
        t_high = self._make_thread("High", priority=1, burst=4)

        self.scheduler.enqueue_ready(t_low_1, timestamp_ms=0)
        self.scheduler.enqueue_ready(t_low_2, timestamp_ms=0)

        # Dispatch Low1
        current = self.scheduler.dispatch_next(timestamp_ms=0)
        self.assertIs(current, t_low_1)
        self.assertFalse(self.scheduler.tick_quantum(2))
        self.assertEqual(t_low_1.quantum_used_ms, 2)

        # Enqueueing same or lower priority does NOT preempt
        self.assertIsNone(self.scheduler.enqueue_ready(t_same, timestamp_ms=2))
        self.assertIsNone(self.scheduler.enqueue_ready(t_very_low, timestamp_ms=2))
        self.assertIs(self.scheduler.get_running_thread(), t_low_1)
        self.assertEqual(self.scheduler.preemptions_total, 0)

        # Enqueueing higher priority (1 < 3) preempts Low1 immediately
        preempted = self.scheduler.enqueue_ready(t_high, timestamp_ms=2)
        self.assertIs(preempted, t_low_1)
        self.assertEqual(t_low_1.state, ProcessState.READY)
        self.assertEqual(t_low_1.quantum_used_ms, 0)
        self.assertIsNone(self.scheduler.running_tid)
        self.assertEqual(self.scheduler.preemptions_total, 1)

        # Low1 was placed at the tail of priority 3 queue behind Low2 and Same
        queues = self.scheduler.get_ready_queues()
        self.assertEqual([t.tid for t in queues[1]], [t_high.tid])
        self.assertEqual([t.tid for t in queues[3]], [t_low_2.tid, t_same.tid, t_low_1.tid])

        # Next dispatch runs High; context switches increments (Low1 -> High)
        dispatched_high = self.scheduler.dispatch_next(timestamp_ms=2)
        self.assertIs(dispatched_high, t_high)
        self.assertEqual(self.scheduler.context_switches_total, 1)

        # Terminate High, then dispatch Low2 -> Same -> Low1 (with fresh quantum 0)
        self.pm.transition_thread_state(t_high, ProcessState.TERMINATED, timestamp_ms=6)
        self.scheduler.on_current_suspended()

        next_run = self.scheduler.dispatch_next(timestamp_ms=6)
        self.assertIs(next_run, t_low_2)
        self.assertEqual(self.scheduler.context_switches_total, 2)


class TestRoundRobinAndContextSwitches(unittest.TestCase):
    """Verify Round-Robin rotation, quantum accounting, and context switch counting."""

    def setUp(self):
        self.pm = ProcessManager()
        self.scheduler = PriorityRoundRobinScheduler(self.pm, quantum_ms=3)

    def _create_ready_threads(self, count: int, priority: int = 2) -> list[SimulatedThread]:
        proc = self.pm.create_process("App", size_bytes=8192, initial_state=ProcessState.READY)
        threads = []
        for idx in range(1, count + 1):
            t = self.pm.create_thread(proc, f"T{idx}", priority=priority, cpu_burst_ms=10)
            self.scheduler.enqueue_ready(t, timestamp_ms=0)
            threads.append(t)
        return threads

    def test_round_robin_quantum_rotation_across_equal_priority_threads(self):
        t1, t2, t3 = self._create_ready_threads(3, priority=2)
        now = 0
        run_order = []

        for _ in range(6):
            running = self.scheduler.dispatch_next(timestamp_ms=now)
            self.assertIsNotNone(running)
            assert running is not None
            run_order.append(running.name)
            self.assertEqual(running.quantum_used_ms, 0)

            self.assertFalse(self.scheduler.tick_quantum(1))
            self.assertFalse(self.scheduler.tick_quantum(1))
            self.assertTrue(self.scheduler.tick_quantum(1))
            now += 3

            rotated = self.scheduler.on_quantum_expired(timestamp_ms=now)
            self.assertIs(rotated, running)
            self.assertEqual(running.state, ProcessState.READY)
            self.assertEqual(running.quantum_used_ms, 0)
            self.assertIsNone(self.scheduler.running_tid)

        self.assertEqual(run_order, ["T1", "T2", "T3", "T1", "T2", "T3"])
        self.assertEqual(self.scheduler.dispatches_total, 6)
        self.assertEqual(self.scheduler.context_switches_total, 5)
        self.assertEqual(self.scheduler.quantum_expirations_total, 6)
        self.assertEqual(self.scheduler.preemptions_total, 0)

    def test_sole_thread_redispatch_and_cold_start_do_not_count_context_switch(self):
        [t1] = self._create_ready_threads(1, priority=1)

        # Cold dispatch: None -> T1
        d1 = self.scheduler.dispatch_next(timestamp_ms=0)
        self.assertIs(d1, t1)
        self.assertEqual(self.scheduler.dispatches_total, 1)
        self.assertEqual(self.scheduler.context_switches_total, 0)

        # Quantum expires -> T1 back to queue -> T1 re-dispatched
        self.assertTrue(self.scheduler.tick_quantum(3))
        self.scheduler.on_quantum_expired(timestamp_ms=3)
        d2 = self.scheduler.dispatch_next(timestamp_ms=3)
        self.assertIs(d2, t1)
        self.assertEqual(self.scheduler.dispatches_total, 2)
        self.assertEqual(self.scheduler.context_switches_total, 0)

        # Block and re-unblock with no intermediate thread -> still no context switch
        self.assertFalse(self.scheduler.tick_quantum(2))
        self.assertEqual(t1.quantum_used_ms, 2)
        self.pm.transition_thread_state(
            t1,
            ProcessState.BLOCKED,
            timestamp_ms=5,
            reason="I/O",
            block_reason=BlockReason.IO_WAIT,
            blocked_on="block:0",
        )
        self.scheduler.on_current_suspended()
        self.assertEqual(t1.quantum_used_ms, 0)
        self.assertIsNone(self.scheduler.running_tid)
        self.assertEqual(self.scheduler.last_dispatched_tid, t1.tid)

        self.pm.transition_thread_state(t1, ProcessState.READY, timestamp_ms=9, reason="io_done")
        self.scheduler.enqueue_ready(t1, timestamp_ms=9)
        d3 = self.scheduler.dispatch_next(timestamp_ms=9)
        self.assertIs(d3, t1)
        self.assertEqual(t1.quantum_used_ms, 0)
        self.assertEqual(self.scheduler.dispatches_total, 3)
        self.assertEqual(self.scheduler.context_switches_total, 0)

    def test_dynamic_quantum_change_applies_immediately(self):
        [t1] = self._create_ready_threads(1, priority=1)
        self.scheduler.dispatch_next(timestamp_ms=0)
        self.assertFalse(self.scheduler.tick_quantum(2))
        self.scheduler.set_quantum(2)
        self.assertTrue(self.scheduler.tick_quantum(0))

    def test_dispatch_while_already_running_raises_and_idle_ops_return_none(self):
        self.assertFalse(self.scheduler.tick_quantum(1))
        self.assertIsNone(self.scheduler.on_quantum_expired(0))
        self.assertIsNone(self.scheduler.preempt_current(0))

        t1, _t2 = self._create_ready_threads(2, priority=2)
        self.scheduler.dispatch_next(0)
        self.assertIs(self.scheduler.get_running_thread(), t1)
        with self.assertRaises(SchedulerException):
            self.scheduler.dispatch_next(1)


class TestQueueIntegrityAndDiagnostics(unittest.TestCase):
    """Ensure non-READY threads never enter/stay in queues, no duplicate TIDs, and diagnostics work."""

    def setUp(self):
        self.pm = ProcessManager()
        self.scheduler = PriorityRoundRobinScheduler(self.pm, quantum_ms=4)

    def test_non_ready_and_unregistered_threads_cannot_enter_queues(self):
        proc_new = self.pm.create_process(
            "NewProc",
            size_bytes=4096,
            cpu_burst_ms=5,
            initial_state=ProcessState.NEW,
        )
        t_new = self.pm.get_thread_by_name(proc_new, "main")
        with self.assertRaises(SchedulerException):
            self.scheduler.enqueue_ready(t_new, timestamp_ms=0)

        proc_active = self.pm.create_process("Active", size_bytes=4096)
        t_blk = self.pm.create_thread(proc_active, "Blk", priority=2, cpu_burst_ms=10)
        self.pm.transition_thread_state(t_blk, ProcessState.RUNNING, timestamp_ms=0)
        with self.assertRaises(SchedulerException):
            self.scheduler.enqueue_ready(t_blk, timestamp_ms=0)

        self.pm.transition_thread_state(
            t_blk,
            ProcessState.BLOCKED,
            timestamp_ms=1,
            block_reason=BlockReason.SLEEP_WAIT,
        )
        with self.assertRaises(SchedulerException):
            self.scheduler.enqueue_ready(t_blk, timestamp_ms=1)

        t_term = self.pm.create_thread(proc_active, "Term", priority=2, cpu_burst_ms=5)
        self.pm.transition_thread_state(t_term, ProcessState.TERMINATED, timestamp_ms=2)
        with self.assertRaises(SchedulerException):
            self.scheduler.enqueue_ready(t_term, timestamp_ms=2)

        unregistered = SimulatedThread(tid=9999, pid=999, name="Ghost", state=ProcessState.READY)
        with self.assertRaises(SchedulerException):
            self.scheduler.enqueue_ready(unregistered, timestamp_ms=2)

        self.assertTrue(self.scheduler.is_ready_empty())

    def test_duplicate_tids_prevented_and_terminated_or_blocked_pruned(self):
        proc1 = self.pm.create_process("Proc1", size_bytes=4096)
        t1 = self.pm.create_thread(proc1, "T1", priority=2, cpu_burst_ms=10)
        t2 = self.pm.create_thread(proc1, "T2", priority=2, cpu_burst_ms=10)

        proc2 = self.pm.create_process("Proc2", size_bytes=4096)
        t3 = self.pm.create_thread(proc2, "T3", priority=3, cpu_burst_ms=10)

        # Enqueue T1 twice -> no duplicate
        self.scheduler.enqueue_ready(t1, timestamp_ms=0)
        self.scheduler.enqueue_ready(t1, timestamp_ms=0)
        self.scheduler.enqueue_ready(t2, timestamp_ms=0)
        self.scheduler.enqueue_ready(t3, timestamp_ms=0)
        self.assertEqual([t.tid for t in self.scheduler.get_ready_list()], [t1.tid, t2.tid, t3.tid])

        # Terminate Proc1 externally without calling scheduler.remove
        self.pm.terminate_process(proc1.pid, timestamp_ms=5)

        # Terminated threads must be pruned automatically from queues
        self.assertIs(self.scheduler.select_next(), t3)
        self.assertEqual([t.tid for t in self.scheduler.get_ready_list()], [t3.tid])
        self.assertEqual(list(self.scheduler.queues[2]), [])

        # Dispatch T3, then externally block it without on_current_suspended()
        self.scheduler.dispatch_next(timestamp_ms=5)
        self.pm.transition_thread_state(t3, ProcessState.BLOCKED, timestamp_ms=6)
        self.assertIsNone(self.scheduler.get_running_thread())
        self.assertIsNone(self.scheduler.running_tid)
        self.assertTrue(self.scheduler.is_ready_empty())

        # Unblock T3 and verify remove() cleans ready queue and running_tid
        self.pm.transition_thread_state(t3, ProcessState.READY, timestamp_ms=10)
        self.scheduler.enqueue_ready(t3, timestamp_ms=10)
        self.assertTrue(self.scheduler.remove(t3.tid))
        self.assertFalse(self.scheduler.remove(t3.tid))
        self.assertTrue(self.scheduler.is_ready_empty())

        self.scheduler.enqueue_ready(t3, timestamp_ms=10)
        self.scheduler.dispatch_next(timestamp_ms=10)
        self.assertTrue(self.scheduler.remove(t3.tid))
        self.assertIsNone(self.scheduler.running_tid)

    def test_legacy_waiting_rejected_priority_relocation_and_snapshot_isolation(self):
        proc = self.pm.create_process("Reloc", size_bytes=4096)
        t_wait = self.pm.create_thread(proc, "Waiter", priority=2, cpu_burst_ms=5)
        self.pm.transition_thread_state(t_wait, ProcessState.RUNNING, timestamp_ms=0)
        self.pm.transition_thread_state(t_wait, ProcessState.BLOCKED, timestamp_ms=1)
        t_wait.state = ProcessState.WAITING  # Simulate legacy state directly
        with self.assertRaises(SchedulerException):
            self.scheduler.enqueue_ready(t_wait, timestamp_ms=1)

        t_reloc = self.pm.create_thread(proc, "Mover", priority=4, cpu_burst_ms=8)
        self.scheduler.enqueue_ready(t_reloc, timestamp_ms=2)
        self.assertEqual([t.tid for t in self.scheduler.get_ready_queues()[4]], [t_reloc.tid])

        # Mutate snapshot safely without touching internal deque
        snap = self.scheduler.get_ready_queues()
        snap[4].clear()
        self.assertEqual([t.tid for t in self.scheduler.get_ready_queues()[4]], [t_reloc.tid])

        # Priority change moves thread out of old queue without duplicating
        t_reloc.priority = 1
        self.scheduler.enqueue_ready(t_reloc, timestamp_ms=3)
        self.assertEqual(self.scheduler.get_ready_queues()[4], [])
        self.assertEqual([t.tid for t in self.scheduler.get_ready_queues()[1]], [t_reloc.tid])

    def test_direct_preempt_current_and_interleaved_block_context_switches(self):
        proc = self.pm.create_process("Interleave", size_bytes=4096)
        t1 = self.pm.create_thread(proc, "T1", priority=2, cpu_burst_ms=10)
        t2 = self.pm.create_thread(proc, "T2", priority=2, cpu_burst_ms=10)

        self.scheduler.enqueue_ready(t1, timestamp_ms=0)
        self.scheduler.enqueue_ready(t2, timestamp_ms=0)

        # T1 runs, blocks -> T2 runs -> T2 terminates -> T1 unblocks and runs
        self.scheduler.dispatch_next(timestamp_ms=0)
        self.scheduler.tick_quantum(2)
        self.pm.transition_thread_state(t1, ProcessState.BLOCKED, timestamp_ms=2)
        self.scheduler.on_current_suspended()
        self.assertEqual(t1.quantum_used_ms, 0)

        self.scheduler.dispatch_next(timestamp_ms=2)
        self.assertEqual(self.scheduler.context_switches_total, 1)  # T1 -> T2
        self.pm.transition_thread_state(t2, ProcessState.TERMINATED, timestamp_ms=4)
        self.scheduler.on_current_suspended()

        self.pm.transition_thread_state(t1, ProcessState.READY, timestamp_ms=5)
        self.scheduler.enqueue_ready(t1, timestamp_ms=5)
        self.scheduler.dispatch_next(timestamp_ms=5)
        self.assertEqual(self.scheduler.context_switches_total, 2)  # T2 -> T1

        # Direct preempt_current resets quantum and puts T1 back in queue
        self.scheduler.tick_quantum(1)
        preempted = self.scheduler.preempt_current(timestamp_ms=6, reason="Preempção manual")
        self.assertIs(preempted, t1)
        self.assertEqual(t1.state, ProcessState.READY)
        self.assertEqual(t1.quantum_used_ms, 0)
        self.assertEqual(self.scheduler.preemptions_total, 1)
        self.assertIsNone(self.scheduler.running_tid)
        self.assertEqual(self.scheduler.last_dispatched_tid, t1.tid)

    def test_stats_format_queues_and_reset(self):
        proc = self.pm.create_process("Video", size_bytes=4096)
        t1 = self.pm.create_thread(proc, "T1", priority=1, cpu_burst_ms=8)
        t2 = self.pm.create_thread(proc, "T2", priority=3, cpu_burst_ms=6)

        self.scheduler.enqueue_ready(t1, timestamp_ms=0)
        self.scheduler.enqueue_ready(t2, timestamp_ms=0)
        self.scheduler.dispatch_next(timestamp_ms=0)
        self.scheduler.tick_quantum(2)

        stats = self.scheduler.get_stats()
        self.assertEqual(stats["quantum_ms"], 4)
        self.assertEqual(stats["running_tid"], t1.tid)
        self.assertEqual(stats["last_dispatched_tid"], t1.tid)
        self.assertEqual(stats["dispatches_total"], 1)
        self.assertEqual(stats["context_switches_total"], 0)
        self.assertEqual(stats["ready_count"], 1)
        self.assertEqual(stats["ready_queues"][3], [t2.tid])

        formatted = self.scheduler.format_queues()
        self.assertIn("Quantum configurado", formatted)
        self.assertIn("T1", formatted)
        self.assertIn("T2", formatted)
        self.assertIn("Prioridade 1: [vazia]", formatted)

        self.scheduler.reset()
        self.assertIsNone(self.scheduler.running_tid)
        self.assertIsNone(self.scheduler.last_dispatched_tid)
        self.assertEqual(self.scheduler.dispatches_total, 0)
        self.assertEqual(self.scheduler.context_switches_total, 0)
        self.assertTrue(self.scheduler.is_ready_empty())
        self.assertEqual(self.scheduler.quantum_ms, 4)


if __name__ == "__main__":
    unittest.main()
