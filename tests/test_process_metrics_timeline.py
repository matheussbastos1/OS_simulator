"""Unit tests for Stage 5 Wave 2 MetricsCollector, Timeline, Gantt, and Live Frame Summary."""

import unittest

from os_simulator.core.types import BlockReason, ProcessState, ProcessType, ReplacementAlgorithm
from os_simulator.memory.service import MemoryManager
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


class TestTimelineAndGanttDataclasses(unittest.TestCase):
    """Verify TimelineEntry, GanttSlice, and FrameAccessRecord construction and validation."""

    def test_timeline_entry_and_gantt_slice_to_dict(self):
        entry = TimelineEntry(
            seq=1,
            timestamp_ms=10,
            event_type="DISPATCH",
            pid=100,
            tid=1,
            process_name="App",
            thread_name="main",
            state=ProcessState.RUNNING,
            priority=2,
            cpu_consumed_ms=4,
            quantum_used_ms=0,
            details="Despacho inicial",
        )
        d = entry.to_dict()
        self.assertEqual(d["seq"], 1)
        self.assertEqual(d["timestamp_ms"], 10)
        self.assertEqual(d["state"], "RUNNING")
        self.assertEqual(d["details"], "Despacho inicial")

        slc = GanttSlice(
            start_ms=10,
            end_ms=16,
            pid=100,
            tid=1,
            process_name="App",
            thread_name="main",
            label="EXEC",
        )
        self.assertEqual(slc.duration_ms, 6)
        self.assertFalse(slc.is_idle)
        self.assertEqual(slc.to_dict()["duration_ms"], 6)

        with self.assertRaises(ValueError):
            GanttSlice(start_ms=10, end_ms=5)
        with self.assertRaises(ValueError):
            TimelineEntry(seq=1, timestamp_ms=-1, event_type="ERR")

    def test_gantt_coalescing_and_idle_coalescing(self):
        pm = ProcessManager()
        p1 = pm.create_process("P1", size_bytes=4096, cpu_burst_ms=10)
        p2 = pm.create_process("P2", size_bytes=4096, cpu_burst_ms=10)
        t1 = pm.get_thread_by_name(p1, "main")
        t2 = pm.get_thread_by_name(p2, "main")

        collector = MetricsCollector()
        # Contiguous EXEC slices for t1 coalesce into [0, 4]
        collector.record_cpu_slice(0, 2, t1, "P1", label="EXEC")
        collector.record_cpu_slice(2, 4, t1, "P1", label="EXEC")
        # Different label on same thread does NOT coalesce -> [4, 6]
        collector.record_cpu_slice(4, 6, t1, "P1", label="MUTEX_CS")
        # Zero-width slice is ignored
        self.assertIsNone(collector.record_cpu_slice(6, 6, t1, "P1", label="EXEC"))
        # Different thread does NOT coalesce -> [6, 9]
        collector.record_cpu_slice(6, 9, t2, "P2", label="EXEC")
        # Contiguous idle slices coalesce into [9, 14]
        collector.record_idle_slice(9, 11)
        collector.record_idle_slice(11, 14)
        # Returning to t1 after gap stays separate -> [14, 17]
        collector.record_cpu_slice(14, 17, t1, "P1", label="EXEC")

        gantt = collector.get_gantt()
        self.assertEqual(len(gantt), 5)
        self.assertEqual((gantt[0].start_ms, gantt[0].end_ms, gantt[0].tid, gantt[0].label), (0, 4, t1.tid, "EXEC"))
        self.assertEqual((gantt[1].start_ms, gantt[1].end_ms, gantt[1].tid, gantt[1].label), (4, 6, t1.tid, "MUTEX_CS"))
        self.assertEqual((gantt[2].start_ms, gantt[2].end_ms, gantt[2].tid, gantt[2].label), (6, 9, t2.tid, "EXEC"))
        self.assertEqual((gantt[3].start_ms, gantt[3].end_ms, gantt[3].is_idle), (9, 14, True))
        self.assertEqual((gantt[4].start_ms, gantt[4].end_ms, gantt[4].tid, gantt[4].label), (14, 17, t1.tid, "EXEC"))

        # Overlapping slice must raise ValueError
        with self.assertRaises(ValueError):
            collector.record_cpu_slice(16, 18, t1, "P1")
        with self.assertRaises(ValueError):
            collector.record_idle_slice(15, 18)

    def test_timeline_chronological_ordering_and_limits(self):
        collector = MetricsCollector()
        collector.record_event(timestamp_ms=20, event_type="QUANTUM_EXPIRE", pid=100, tid=1, details="q=4")
        collector.record_event(timestamp_ms=0, event_type="ARRIVAL", pid=100, tid=1, details="inicio")
        collector.record_event(timestamp_ms=20, event_type="DISPATCH", pid=101, tid=2, details="segundo")
        collector.record_event(timestamp_ms=25, event_type="EXIT", pid=100, tid=1, details="fim")

        tl = collector.get_timeline()
        self.assertEqual([e.timestamp_ms for e in tl], [0, 20, 20, 25])
        # Same timestamp_ms tie-broken by monotonic seq
        self.assertEqual([e.event_type for e in tl], ["ARRIVAL", "QUANTUM_EXPIRE", "DISPATCH", "EXIT"])
        self.assertEqual([e.seq for e in tl], [2, 1, 3, 4])

        self.assertEqual(len(collector.get_timeline(limit=2)), 2)
        self.assertEqual([e.event_type for e in collector.get_timeline(limit=2)], ["DISPATCH", "EXIT"])
        self.assertEqual(collector.get_timeline(limit=0), [])

        with self.assertRaises(ValueError):
            collector.get_timeline(limit=-1)


class TestMathematicalMetricsConsistency(unittest.TestCase):
    """Verify WT, TAT, RT, CPU, BLK, utilization, and idle time mathematical consistency."""

    def test_thread_and_process_metrics_satisfy_tat_equals_cpu_wt_blk(self):
        pm = ProcessManager()
        proc = pm.create_process(
            "VideoEncoder",
            size_bytes=8192,
            priority=2,
            cpu_burst_ms=10,
            arrival_time_ms=5,
            initial_state=ProcessState.NEW,
        )
        t = pm.get_thread_by_name(proc, "main")
        collector = MetricsCollector()

        # Before admission / start: TAT and RT must be None
        pre = collector.compute_thread_metrics(t)
        self.assertIsNone(pre.turnaround_time_ms)
        self.assertIsNone(pre.response_time_ms)

        # t=5: admitted to READY
        pm.admit_process(proc, timestamp_ms=5)
        # t=9: dispatched (WT = 4ms, RT = 9 - 5 = 4ms)
        pm.transition_thread_state(t, ProcessState.RUNNING, timestamp_ms=9)
        # Runs 4ms -> t=13
        t.cpu_consumed_ms += 4
        collector.record_cpu_slice(9, 13, t, proc.name)
        # t=13: blocked on I/O
        pm.transition_thread_state(
            t,
            ProcessState.BLOCKED,
            timestamp_ms=13,
            block_reason=BlockReason.IO_WAIT,
            blocked_on="block:0",
        )
        collector.increment_counter("syscalls_total", pid=proc.pid, tid=t.tid)
        collector.increment_counter("io_blocks_total", pid=proc.pid, tid=t.tid)

        # t=19: I/O completes (BLK = 6ms)
        pm.transition_thread_state(t, ProcessState.READY, timestamp_ms=19)
        # t=21: re-dispatched (WT += 2ms -> total 6ms)
        pm.transition_thread_state(t, ProcessState.RUNNING, timestamp_ms=21)
        # Runs remaining 6ms -> t=27
        t.cpu_consumed_ms += 6
        collector.record_cpu_slice(21, 27, t, proc.name)
        pm.terminate_process(proc.pid, timestamp_ms=27)

        tm = collector.compute_thread_metrics(t)
        self.assertEqual(tm.cpu_time_ms, 10)
        self.assertEqual(tm.waiting_time_ms, 6)
        self.assertEqual(tm.blocked_time_ms, 6)
        self.assertEqual(tm.response_time_ms, 4)
        self.assertEqual(tm.turnaround_time_ms, 22)
        self.assertEqual(tm.turnaround_time_ms, tm.cpu_time_ms + tm.waiting_time_ms + tm.blocked_time_ms)
        self.assertEqual(tm.syscalls_count, 1)
        self.assertEqual(tm.io_blocks_count, 1)

        pm_metrics = collector.compute_process_metrics(proc)
        self.assertEqual(pm_metrics.cpu_time_ms, 10)
        self.assertEqual(pm_metrics.waiting_time_ms, 6)
        self.assertEqual(pm_metrics.blocked_time_ms, 6)
        self.assertEqual(pm_metrics.response_time_ms, 4)
        self.assertEqual(pm_metrics.turnaround_time_ms, 22)
        self.assertEqual(
            pm_metrics.turnaround_time_ms,
            pm_metrics.cpu_time_ms + pm_metrics.waiting_time_ms + pm_metrics.blocked_time_ms,
        )

    def test_multithreaded_metrics_and_global_utilization_invariants(self):
        pm = ProcessManager()
        p_multi = pm.create_process(
            "Player_Video",
            size_bytes=16384,
            arrival_time_ms=0,
            initial_state=ProcessState.READY,
            create_default_thread=False,
        )
        t1 = pm.create_thread(p_multi, "T1", priority=1, cpu_burst_ms=6, arrival_time_ms=0)
        t2 = pm.create_thread(p_multi, "T2", priority=2, cpu_burst_ms=4, arrival_time_ms=0)

        p_other = pm.create_process(
            "Background",
            size_bytes=4096,
            priority=3,
            cpu_burst_ms=5,
            arrival_time_ms=2,
            initial_state=ProcessState.READY,
        )
        t3 = pm.get_thread_by_name(p_other, "main")

        collector = MetricsCollector()

        # [0..6]: T1 runs 6ms and finishes
        pm.transition_thread_state(t1, ProcessState.RUNNING, timestamp_ms=0)
        t1.cpu_consumed_ms = 6
        collector.record_cpu_slice(0, 6, t1, p_multi.name)
        pm.transition_thread_state(t1, ProcessState.TERMINATED, timestamp_ms=6)

        # [6..8]: IDLE 2ms (suppose T2 was mutex-blocked or idle gap) -> let's block T2 [0..8] then run [8..12]
        #Wait: test real transition on T2: T2 was READY [0..6], runs [6..7], blocks [7..10], runs [10..13]
        pm.transition_thread_state(t2, ProcessState.RUNNING, timestamp_ms=6)
        t2.cpu_consumed_ms = 1
        collector.record_cpu_slice(6, 7, t2, p_multi.name)
        pm.transition_thread_state(t2, ProcessState.BLOCKED, timestamp_ms=7, block_reason=BlockReason.MUTEX_WAIT, blocked_on="M")
        collector.increment_counter("mutex_blocks_total", pid=p_multi.pid, tid=t2.tid)

        # [7..10]: idle 3ms while t3 also arrived at 2 -> let's run t3 [7..12]
        pm.transition_thread_state(t3, ProcessState.RUNNING, timestamp_ms=7)
        t3.cpu_consumed_ms = 5
        collector.record_cpu_slice(7, 12, t3, p_other.name)
        pm.terminate_process(p_other.pid, timestamp_ms=12)

        # T2 unblocks at 10 (blocked=3), waits [10..12] (wait += 2 -> 6+2=8), runs [12..15] (cpu += 3 -> 4)
        pm.transition_thread_state(t2, ProcessState.READY, timestamp_ms=10)
        pm.transition_thread_state(t2, ProcessState.RUNNING, timestamp_ms=12)
        t2.cpu_consumed_ms = 4
        collector.record_cpu_slice(12, 15, t2, p_multi.name)
        pm.transition_thread_state(t2, ProcessState.TERMINATED, timestamp_ms=15)

        # [15..20]: idle 5ms
        collector.record_idle_slice(15, 20)

        # Verify every single thread satisfies TAT == CPU + WT + BLK
        for thread in (t1, t2, t3):
            tm = collector.compute_thread_metrics(thread)
            self.assertEqual(tm.turnaround_time_ms, tm.cpu_time_ms + tm.waiting_time_ms + tm.blocked_time_ms)

        m_multi = collector.compute_process_metrics(p_multi)
        self.assertEqual(m_multi.cpu_time_ms, 10)
        self.assertEqual(m_multi.blocked_time_ms, 3)
        self.assertEqual(m_multi.turnaround_time_ms, 15)
        self.assertEqual(m_multi.response_time_ms, 0)
        self.assertEqual(m_multi.mutex_blocks_count, 1)

        sched_stats = {"context_switches_total": 3, "dispatches_total": 4, "preemptions_total": 0}
        gm = collector.compute_global_metrics(pm, clock_now_ms=20, scheduler_stats=sched_stats)

        # Nucleo_Base (PID 0) must be excluded from process totals
        self.assertEqual(gm.total_processes, 2)
        self.assertEqual(gm.completed_processes, 2)
        self.assertEqual(gm.total_simulation_ms, 20)
        self.assertEqual(gm.cpu_busy_ms, 15)
        self.assertEqual(gm.idle_time_ms, 5)
        self.assertEqual(gm.cpu_busy_ms + gm.idle_time_ms, gm.total_simulation_ms)
        self.assertAlmostEqual(gm.cpu_utilization_pct, (15 / 20) * 100.0)
        self.assertEqual(gm.context_switches_total, 3)
        self.assertEqual(gm.dispatches_total, 4)
        self.assertEqual(gm.mutex_blocks_total, 1)
        self.assertAlmostEqual(gm.avg_turnaround_time_ms, (15 + 10) / 2.0)

        # Zero-time simulation utilization must be 0.0 (no ZeroDivisionError)
        empty_pm = ProcessManager()
        empty_gm = MetricsCollector().compute_global_metrics(empty_pm, clock_now_ms=0)
        self.assertEqual(empty_gm.cpu_utilization_pct, 0.0)
        self.assertEqual(empty_gm.total_processes, 0)
        self.assertEqual(empty_gm.completed_processes, 0)


class TestLiveFrameSummaryIntegration(unittest.TestCase):
    """Verify live synchronized build_frames_summary against real Stage 4 MemoryManager."""

    def test_build_frames_summary_stays_synced_with_memory_manager(self):
        pm = ProcessManager()
        mm = MemoryManager(
            dynamic_frames=2,
            page_size=4096,
            swap_slots=8,
            replacement_algorithm=ReplacementAlgorithm.LRU,
            process_lookup=pm.get_process,
        )
        proc = pm.create_process("Browser", size_bytes=12 * 1024, process_type=ProcessType.NORMAL)
        mm.allocate_process_memory(proc)
        collector = MetricsCollector()

        # Initially both frames are LIVRE
        init_summary = collector.build_frames_summary(mm)
        self.assertEqual(len(init_summary), 2)
        for row in init_summary:
            self.assertFalse(row["occupied"])
            self.assertEqual(row["state"], "LIVRE")
            self.assertEqual(row["last_event"], "N/A")
            self.assertIsNone(row["last_access"])
            self.assertEqual(row["algorithm"], "LRU")

        # Execute LOAD Página 0 -> Page Fault into Frame 0
        res0 = mm.execute_instruction(proc, "LOAD_DATA Página 0", current_time=10.0)
        collector.record_memory_access(
            timestamp_ms=10,
            pid=proc.pid,
            tid=1,
            logical_page=0,
            frame_id=res0["frame_id"],
            hit=not res0["page_fault"],
            page_origin=res0["fault_details"]["page_origin"],
            algorithm=mm.algorithm.value,
        )

        # Execute WRITE Página 0 -> Hit on Frame 0 (dirty=True, last_access=20.0)
        res_w = mm.execute_instruction(proc, "WRITE_DATA Página 0", current_time=20.0)
        collector.record_memory_access(
            timestamp_ms=20,
            pid=proc.pid,
            tid=1,
            logical_page=0,
            frame_id=res_w["frame_id"],
            hit=not res_w["page_fault"],
            page_origin=None,
            algorithm=mm.algorithm.value,
        )

        # Execute LOAD Página 1 -> Page Fault into Frame 1
        res1 = mm.execute_instruction(proc, "LOAD_DATA Página 1", current_time=25.0)
        collector.record_memory_access(
            timestamp_ms=25,
            pid=proc.pid,
            tid=1,
            logical_page=1,
            frame_id=res1["frame_id"],
            hit=not res1["page_fault"],
            page_origin=res1["fault_details"]["page_origin"],
            algorithm=mm.algorithm.value,
        )

        live = collector.build_frames_summary(mm)
        self.assertEqual(live[0]["state"], "OCUPADA")
        self.assertEqual(live[0]["logical_page"], 0)
        self.assertEqual(live[0]["last_event"], "HIT")
        self.assertEqual(live[0]["last_access"], 20.0)
        self.assertTrue(live[0]["dirty"])
        self.assertTrue(live[0]["referenced"])
        self.assertEqual(live[1]["logical_page"], 1)
        self.assertEqual(live[1]["last_event"], "PAGE_FAULT")
        self.assertEqual(live[1]["last_access"], 25.0)

        # Evict Page 0 (LRU t=20 < t=25) by loading Page 2 into Frame 0 WITHOUT recording in collector yet:
        # build_frames_summary MUST reflect live Frame 0 (page 2) and NOT stale HIT from evicted page 0!
        res2 = mm.execute_instruction(proc, "LOAD_DATA Página 2", current_time=30.0)
        self.assertEqual(res2["frame_id"], 0)
        standalone = build_frames_summary(mm, process_lookup=pm.get_process)
        self.assertEqual(standalone[0]["logical_page"], 2)
        self.assertEqual(standalone[0]["last_access"], 30.0)
        self.assertFalse(standalone[0]["dirty"])
        self.assertEqual(standalone[0]["last_event"], "N/A")

        stale_guard = collector.build_frames_summary(mm)
        self.assertEqual(stale_guard[0]["logical_page"], 2)
        self.assertEqual(stale_guard[0]["last_event"], "N/A")

        # Now record access for Page 2 and switch policy to SECOND_CHANCE
        collector.record_memory_access(
            timestamp_ms=30,
            pid=proc.pid,
            tid=1,
            logical_page=2,
            frame_id=0,
            hit=False,
            page_origin=res2["fault_details"]["page_origin"],
            algorithm=mm.algorithm.value,
        )
        mm.set_replacement_policy(ReplacementAlgorithm.SECOND_CHANCE)
        updated = collector.build_frames_summary(mm)
        self.assertEqual(updated[0]["last_event"], "PAGE_FAULT")
        self.assertEqual(updated[0]["algorithm"], "SECOND_CHANCE")
        self.assertEqual(len(collector.get_memory_history()), 4)

        # Counters incremented by record_memory_access: 1 hit, 3 faults
        gm = collector.compute_global_metrics(pm, clock_now_ms=30)
        self.assertEqual(gm.page_hits_total, 1)
        self.assertEqual(gm.page_faults_total, 3)

        # Free process memory -> frames immediately reset to LIVRE
        mm.free_process_memory(proc)
        after_free = collector.build_frames_summary(mm)
        for row in after_free:
            self.assertEqual(row["state"], "LIVRE")
            self.assertEqual(row["last_event"], "N/A")
            self.assertIsNone(row["last_access"])


class TestFormattersAndReset(unittest.TestCase):
    """Verify Portuguese formatters and MetricsCollector.reset()."""

    def test_portuguese_formatters_and_reset(self):
        pm = ProcessManager()
        proc = pm.create_process("Web", size_bytes=4096, cpu_burst_ms=5)
        t = pm.get_thread_by_name(proc, "main")
        mm = MemoryManager(dynamic_frames=2, process_lookup=pm.get_process)

        collector = MetricsCollector()
        # Empty formatters return clear Portuguese messages
        self.assertIn("Nenhum evento", collector.format_timeline())
        self.assertIn("Nenhuma fatia", collector.format_gantt())

        collector.record_event(timestamp_ms=0, event_type="DISPATCH", thread=t, process_name="Web", details="exec")
        collector.record_cpu_slice(0, 5, t, "Web")
        collector.record_idle_slice(5, 8)
        t.cpu_consumed_ms = 5
        pm.terminate_process(proc.pid, timestamp_ms=5)

        report_txt = collector.format_metrics_report(pm, clock_now_ms=8, scheduler_stats={"dispatches_total": 1})
        self.assertIn("RELATÓRIO DE MÉTRICAS", report_txt)
        self.assertIn("Web", report_txt)
        self.assertIn("62.50%", report_txt)

        tl_txt = collector.format_timeline()
        self.assertIn("LINHA DO TEMPO", tl_txt)
        self.assertIn("DISPATCH", tl_txt)

        gantt_txt = collector.format_gantt()
        self.assertIn("DIAGRAMA DE GANTT", gantt_txt)
        self.assertIn("IDLE", gantt_txt)

        frames_txt = collector.format_frames_summary(memory_manager=mm)
        self.assertIn("RESUMO SINCRONIZADO DAS MOLDURAS FÍSICAS", frames_txt)
        self.assertIn("LIVRE", frames_txt)

        # Module-level record_memory_access helper works standalone
        rec = record_memory_access(10, proc.pid, t.tid, 0, 0, False, "PROCESS_IMAGE", "LRU")
        self.assertIsInstance(rec, FrameAccessRecord)
        self.assertEqual(rec.event_label, "PAGE_FAULT")
        self.assertEqual(rec.to_dict()["event"], "PAGE_FAULT")

        # Counter alias consistency & non-double-counting across pid/tid
        collector.increment_counter("syscalls", delta=2, pid=proc.pid, tid=t.tid)
        collector.increment_counter("syscalls_total", delta=1, pid=proc.pid)
        self.assertEqual(collector.get_counter("syscalls_total"), 3)
        self.assertEqual(collector.get_counter("syscalls"), 3)
        self.assertEqual(collector.get_counter("syscalls", tid=t.tid), 2)
        self.assertEqual(collector.get_counter("syscalls", pid=proc.pid), 3)
        pm_counts = collector.compute_process_metrics(proc)
        self.assertEqual(pm_counts.syscalls_count, 3)
        self.assertEqual(pm_counts.to_dict()["syscalls_count"], 3)

        gm_dict = collector.compute_global_metrics(pm, clock_now_ms=8).to_dict()
        self.assertEqual(gm_dict["syscalls_total"], 3)
        self.assertIsInstance(gm_dict["process_metrics"], list)

        # Unthreaded Stage 4 process metrics compatibility
        p_unthreaded = pm.create_process("LegacyProc", size_bytes=4096)
        legacy_m = collector.compute_process_metrics(p_unthreaded)
        self.assertEqual(legacy_m.cpu_time_ms, 0)
        self.assertIsNone(legacy_m.turnaround_time_ms)
        self.assertEqual(legacy_m.thread_metrics, [])

        # Reset wipes timeline, Gantt, memory history, and counters
        collector.reset()
        self.assertEqual(collector.get_timeline(), [])
        self.assertEqual(collector.get_gantt(), [])
        self.assertEqual(collector.get_memory_history(), [])
        self.assertEqual(collector.get_counter("page_faults_total"), 0)
        self.assertEqual(collector.get_counter("syscalls_total"), 0)
        new_ev = collector.record_event(timestamp_ms=0, event_type="RESET_CHECK")
        self.assertEqual(new_ev.seq, 1)


if __name__ == "__main__":
    unittest.main()
