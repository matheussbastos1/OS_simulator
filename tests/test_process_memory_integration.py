"""Comprehensive end-to-end integration tests for Stage 5 ExecutionEngine & SimulationKernel (Scenarios A-K)."""

import random
import unittest

from os_simulator.core.clock import LogicalClock
from os_simulator.core.context import ExecutionContext
from os_simulator.core.events import EventManager
from os_simulator.core.exceptions import (
    DeadlockDetectedException,
    InvalidProcessStateException,
    InvalidStateTransitionException,
    MemoryFragmentationException,
    OutOfMemoryException,
    PermissionDeniedException,
    SchedulerException,
    SimulationStallException,
)
from os_simulator.core.simulation_kernel import SimulationKernel
from os_simulator.core.types import (
    IOProfileType,
    PageOrigin,
    PrivilegeMode,
    ProcessState,
    ProcessType,
    ReplacementAlgorithm,
    SimulationEventType,
    SyscallType,
)
from os_simulator.process import ExecutionEngine, IOProfile, WorkloadStep
from os_simulator.storage.memory_block_device import InMemoryBlockDevice


class TestStage5ExecutionEngineScenarios(unittest.TestCase):
    """End-to-end verification of Scenarios A through K on SimulationKernel.execution_engine."""

    def test_scenario_a_process_creation_memory_rollback_and_deferred_admission(self):
        """Scenario A: Creation, OOM/fragmentation rollback, deferred arrival, and Nucleo_Base protection."""
        kernel = SimulationKernel(reserved_memory_kb=2048, dynamic_frames=4)
        engine = kernel.execution_engine

        # Verify Stage 5 attributes wired on SimulationKernel
        self.assertIsInstance(kernel.clock, LogicalClock)
        self.assertIsInstance(kernel.event_manager, EventManager)
        self.assertIsInstance(kernel.execution_engine, ExecutionEngine)
        self.assertEqual(kernel.cpu_scheduler.quantum_ms, 4)

        # Submit critical driver that succeeds in [1024..1535 KB]
        crit_ok = engine.submit_process(
            "Crit_A",
            size_bytes=512 * 1024,
            process_type=ProcessType.CRITICAL,
            priority=1,
            cpu_burst_ms=2,
        )
        self.assertEqual(crit_ok.state, ProcessState.READY)
        self.assertIsNotNone(crit_ok.segment_id)

        # Exceed remaining reserved capacity (only 512KB left): must raise and roll back cleanly
        with self.assertRaises(OutOfMemoryException):
            engine.submit_process(
                "Crit_TooBig",
                size_bytes=1024 * 1024,
                process_type=ProcessType.CRITICAL,
                cpu_burst_ms=3,
            )
        self.assertNotIn("Crit_TooBig", kernel.process_manager.name_to_pid)
        self.assertEqual(len(kernel.process_manager.list_processes()), 2)  # Nucleo_Base + Crit_A

        # Fragment reserved area and test rollback on MemoryFragmentationException
        kernel2 = SimulationKernel(reserved_memory_kb=4096)
        eng2 = kernel2.execution_engine
        eng2.submit_process("D1", 512 * 1024, ProcessType.CRITICAL)
        eng2.submit_process("D2", 1024 * 1024, ProcessType.CRITICAL)
        eng2.submit_process("D3", 512 * 1024, ProcessType.CRITICAL)
        eng2.terminate_process("D2")
        with self.assertRaises(MemoryFragmentationException):
            eng2.submit_process("D_Big", 1536 * 1024, ProcessType.CRITICAL, cpu_burst_ms=4)
        self.assertNotIn("D_Big", kernel2.process_manager.name_to_pid)

        # Deferred arrival + manual admit_process
        p_deferred = engine.submit_process(
            "Deferred",
            size_bytes=4096,
            cpu_burst_ms=3,
            arrival_time_ms=0,
            admit_immediately=False,
        )
        self.assertEqual(p_deferred.state, ProcessState.NEW)
        self.assertEqual(kernel.process_manager.get_thread_by_name(p_deferred, "main").state, ProcessState.NEW)
        engine.admit_process("Deferred")
        self.assertEqual(p_deferred.state, ProcessState.READY)

        # Future arrival automatically starts NEW and schedules PROCESS_ARRIVAL
        p_future = engine.submit_process(
            "FutureApp",
            size_bytes=4096,
            cpu_burst_ms=3,
            arrival_time_ms=10,
        )
        self.assertEqual(p_future.state, ProcessState.NEW)
        self.assertEqual(len(kernel.event_manager), 1)

        # Nucleo_Base (PID 0) cannot be enqueued or terminated
        with self.assertRaises(PermissionDeniedException):
            engine.enqueue_process(0)
        with self.assertRaises(PermissionDeniedException):
            engine.terminate_process("Nucleo_Base")

        # Enqueueing NEW process before admit raises InvalidProcessStateException
        p_new = engine.submit_process("Unadmitted", 4096, cpu_burst_ms=2, admit_immediately=False)
        with self.assertRaises(InvalidProcessStateException):
            engine.enqueue_process(p_new.pid)

    def test_scenario_b_lifecycle_step_cap_and_thread_creation(self):
        """Scenario B: 5-state transitions, capped step(ms) on idle jump, and future threads."""
        kernel = SimulationKernel(quantum_ms=4)
        engine = kernel.execution_engine

        p = engine.submit_process("FutureProc", size_bytes=8192, cpu_burst_ms=3, arrival_time_ms=5)
        self.assertEqual(p.state, ProcessState.NEW)

        # step(2) from t=0 with event at t=5 MUST NOT advance past t=2
        s1 = engine.step(2)
        self.assertEqual(kernel.clock.now_ms, 2)
        self.assertEqual(s1["elapsed_ms"], 2)
        self.assertEqual(p.state, ProcessState.NEW)

        # step(3) reaches t=5 and drains PROCESS_ARRIVAL -> READY
        engine.step(3)
        self.assertEqual(kernel.clock.now_ms, 5)
        self.assertEqual(p.state, ProcessState.READY)

        # step(1) dispatches and runs [5..6] -> RUNNING
        engine.step(1)
        self.assertEqual(kernel.clock.now_ms, 6)
        self.assertEqual(p.state, ProcessState.RUNNING)
        self.assertEqual(p.cpu_consumed_ms, 1)

        # Create future thread arriving at t=8 while main is RUNNING
        t_aux = engine.create_thread("FutureProc", "aux", priority=2, cpu_burst_ms=2, arrival_time_ms=8)
        self.assertEqual(t_aux.state, ProcessState.NEW)

        # Run to completion
        res = engine.run()
        self.assertEqual(res["stop_reason"], "COMPLETED")
        self.assertEqual(p.state, ProcessState.TERMINATED)
        self.assertEqual(t_aux.state, ProcessState.TERMINATED)
        self.assertEqual(p.finish_time_ms, 10)  # main: [5..8], aux: [8..10]

        states_seen = [
            (r.from_state, r.to_state)
            for r in kernel.process_manager.state_machine.get_history("TID:1")
        ]
        self.assertIn((ProcessState.NEW, ProcessState.READY), states_seen)
        self.assertIn((ProcessState.READY, ProcessState.RUNNING), states_seen)
        self.assertIn((ProcessState.RUNNING, ProcessState.TERMINATED), states_seen)

    def test_scenario_c_priority_scheduling_and_dynamic_preemption(self):
        """Scenario C: Multi-level priority order and cross-priority arrival preemption."""
        kernel = SimulationKernel(quantum_ms=4)
        engine = kernel.execution_engine

        p_low = engine.submit_process("Low", size_bytes=4096, priority=4, cpu_burst_ms=6, arrival_time_ms=0)
        p_mid = engine.submit_process("Mid", size_bytes=4096, priority=3, cpu_burst_ms=2, arrival_time_ms=0)
        p_high = engine.submit_process("High", size_bytes=4096, priority=1, cpu_burst_ms=3, arrival_time_ms=2)

        engine.run()

        # Mid (prio 3) finishes at t=2; High arrives at t=2 before Low (prio 4) is dispatched
        self.assertEqual(kernel.cpu_scheduler.preemptions_total, 0)
        self.assertEqual(p_mid.state, ProcessState.TERMINATED)
        self.assertEqual(p_high.state, ProcessState.TERMINATED)
        self.assertEqual(p_low.state, ProcessState.TERMINATED)
        self.assertEqual(
            [(s.process_name, s.start_ms, s.end_ms) for s in engine.get_gantt()],
            [("Mid", 0, 2), ("High", 2, 5), ("Low", 5, 11)],
        )

        # Explicit test where Low is actually RUNNING when High arrives at t=2 -> preempts Low!
        engine.reset()
        low = engine.submit_process("LowOnly", size_bytes=4096, priority=4, cpu_burst_ms=6, arrival_time_ms=0)
        high = engine.submit_process("Urgent", size_bytes=4096, priority=1, cpu_burst_ms=3, arrival_time_ms=2)
        engine.run()

        self.assertEqual(kernel.cpu_scheduler.preemptions_total, 1)
        self.assertEqual(low.start_time_ms, 0)
        self.assertEqual(high.start_time_ms, 2)
        self.assertEqual(high.finish_time_ms, 5)
        self.assertEqual(low.finish_time_ms, 9)

        gantt = [(s.process_name, s.start_ms, s.end_ms) for s in engine.get_gantt()]
        self.assertEqual(
            gantt,
            [("LowOnly", 0, 2), ("Urgent", 2, 5), ("LowOnly", 5, 9)],
        )

    def test_scenario_d_round_robin_quantum_and_context_switches(self):
        """Scenario D: Round-Robin equal-priority rotation, quantum=2, and context switches."""
        kernel = SimulationKernel(quantum_ms=2)
        engine = kernel.execution_engine

        p1 = engine.submit_process("A", size_bytes=4096, priority=2, cpu_burst_ms=5)
        p2 = engine.submit_process("B", size_bytes=4096, priority=2, cpu_burst_ms=4)
        p3 = engine.submit_process("C", size_bytes=4096, priority=2, cpu_burst_ms=2)

        engine.run()

        gantt = [(s.process_name, s.start_ms, s.end_ms) for s in engine.get_gantt()]
        # Quantum=2: A[0..2], B[2..4], C[4..6](done), A[6..8], B[8..10](done), A[10..11](done)
        self.assertEqual(
            gantt,
            [
                ("A", 0, 2),
                ("B", 2, 4),
                ("C", 4, 6),
                ("A", 6, 8),
                ("B", 8, 10),
                ("A", 10, 11),
            ],
        )
        self.assertEqual(kernel.cpu_scheduler.dispatches_total, 6)
        self.assertEqual(kernel.cpu_scheduler.context_switches_total, 5)
        self.assertEqual(p1.finish_time_ms, 11)
        self.assertEqual(p2.finish_time_ms, 10)
        self.assertEqual(p3.finish_time_ms, 6)

        with self.assertRaises(SchedulerException):
            engine.set_quantum(0)

    def test_scenario_e_cpu_triggered_syscalls_vs_global_clock_and_io_fs(self):
        """Scenario E: Syscalls trigger strictly by thread cpu_consumed_ms, integrating IOManager and FS ACLs."""
        kernel = SimulationKernel(quantum_ms=4, disk_capacity=16, block_size=256)
        engine = kernel.execution_engine

        # Seed a real FS file to verify generic IO_WRITE preserves VFS data
        kernel.fs_service.write_file("/dados.txt", "VFS_INTACTO", context=kernel.context)
        inode = kernel.fs_service.inode_table[kernel.fs_service.vfs.get_file("/dados.txt").inode_id]
        vfs_block = inode.allocated_blocks[0]

        reads_before = kernel.io_manager.total_reads
        writes_before = kernel.io_manager.total_writes

        # High-priority CPU hog occupies CPU for [0..6]
        p_hog = engine.submit_process("Hog", size_bytes=4096, priority=1, cpu_burst_ms=6)
        # Low-priority worker has syscall scheduled at trigger_cpu_ms=2 (must NOT fire at global clock=2!)
        p_worker = engine.submit_process("Worker", size_bytes=4096, priority=3, cpu_burst_ms=5)
        io_step = engine.schedule_syscall(
            "Worker",
            SyscallType.IO_READ,
            trigger_cpu_ms=2,
            duration_ms=4,
            block_id=12,
        )
        fs_step = engine.schedule_syscall(
            "Worker",
            SyscallType.FS_READ,
            trigger_cpu_ms=4,
            duration_ms=2,
            path="/dados.txt",
        )
        # Also test trigger_cpu_ms=0 (pre-tick YIELD)
        yield_step = engine.schedule_syscall("Worker", SyscallType.YIELD, trigger_cpu_ms=0)

        # Advance to global clock t=6 (Hog finishes at 6, Worker has cpu_consumed_ms == 0)
        engine.step(6)
        self.assertEqual(p_hog.state, ProcessState.TERMINATED)
        self.assertFalse(io_step.executed)
        self.assertFalse(yield_step.executed)

        # At t=8, Worker has run 2ms of CPU (from 6 to 8), triggering yield@0 and io_read@2!
        engine.step(2)
        self.assertTrue(yield_step.executed)
        self.assertTrue(io_step.executed)
        self.assertFalse(fs_step.executed)
        self.assertEqual(p_worker.state, ProcessState.BLOCKED)
        self.assertEqual(kernel.io_manager.total_reads, reads_before + 1)

        # Run to completion: IO completes at t=12, Worker runs [12..14] -> FS_READ@4 blocks [14..16], finishes at t=17
        engine.run()
        self.assertTrue(fs_step.executed)
        self.assertEqual(fs_step.result, "VFS_INTACTO")
        self.assertEqual(p_worker.state, ProcessState.TERMINATED)
        self.assertEqual(p_worker.total_blocked_ms, 6)
        self.assertEqual(p_worker.finish_time_ms, 17)

        # Execute immediate IO_WRITE on VFS block and confirm payload preservation
        p_imm = engine.submit_process("Imm", size_bytes=4096, cpu_burst_ms=3)
        res_imm = engine.execute_syscall_now(
            p_imm.pid,
            SyscallType.IO_WRITE,
            duration_ms=2,
            block_id=vfs_block,
        )
        self.assertTrue(res_imm["blocked"])
        self.assertEqual(kernel.io_manager.total_writes, writes_before + 1)
        self.assertEqual(kernel.fs_service.read_file("/dados.txt", context=kernel.context), "VFS_INTACTO")

        # Verify FS ACL enforcement when non-root context logs in
        engine.run()
        alice = kernel.user_manager.useradd("alice", password="Password@123", create_home=False)
        kernel.fs_service.write_file("/root_only.txt", "segredo", context=kernel.context)
        kernel.security_manager.chmod(kernel.context, "/root_only.txt", "600")
        kernel.context = ExecutionContext(
            user_id=alice.user_id,
            username="alice",
            groups=alice.groups,
            privilege_mode=PrivilegeMode.USER_MODE,
        )
        p_denied = engine.submit_process("AliceApp", size_bytes=4096, owner="alice", cpu_burst_ms=2)
        engine.schedule_syscall(
            p_denied.pid,
            SyscallType.FS_READ,
            trigger_cpu_ms=1,
            duration_ms=2,
            path="/root_only.txt",
        )
        with self.assertRaises(PermissionDeniedException):
            engine.run()

    def test_scenario_f_seeded_random_io_reproducibility(self):
        """Scenario F: Seeded random I/O is bit-for-bit reproducible and never mutates global random."""
        def execute_seeded(seed: int):
            kernel = SimulationKernel(quantum_ms=4, default_seed=seed)
            eng = kernel.execution_engine
            profile = IOProfile(
                profile_type=IOProfileType.RANDOM,
                min_duration_ms=2,
                max_duration_ms=5,
                io_probability=0.5,
                max_random_events=3,
                seed=seed,
            )
            p1 = eng.submit_process("Rnd1", size_bytes=4096, priority=2, cpu_burst_ms=12, io_profile=profile)
            p2 = eng.submit_process("Rnd2", size_bytes=4096, priority=2, cpu_burst_ms=10, io_profile=profile)
            eng.run()
            syscalls = [
                (r.timestamp_ms, r.pid, r.tid, r.cpu_consumed_ms, r.duration_ms, r.block_id)
                for r in kernel.syscall_dispatcher.get_history()
            ]
            gantt = [(s.start_ms, s.end_ms, s.pid, s.label) for s in eng.get_gantt()]
            return syscalls, gantt, eng.get_metrics().to_dict(), (p1.finish_time_ms, p2.finish_time_ms)

        rng_before = random.getstate()
        run_a1 = execute_seeded(seed=123)
        run_a2 = execute_seeded(seed=123)
        run_b = execute_seeded(seed=999)
        self.assertEqual(random.getstate(), rng_before)

        self.assertEqual(run_a1, run_a2)
        self.assertNotEqual(run_a1[0], run_b[0])

    def test_scenario_g_real_stage4_ram_lru_second_chance_swap_and_frames_summary(self):
        """Scenario G: Real Stage 4 RAM paging, LRU vs SecondChance, Swap-Out/In, and live frame summary."""
        # 1. LRU with 2 dynamic frames + dirty eviction -> SWAP_OUT + SWAP_IN
        kernel = SimulationKernel(dynamic_frames=2, block_size=4096, quantum_ms=4)
        engine = kernel.execution_engine

        pattern = [
            (0, False),  # t=0: Fault p0 (PROCESS_IMAGE) -> Frame 0
            (1, False),  # t=1: Fault p1 (ZERO_FILL)     -> Frame 1
            (0, True),   # t=2: Hit p0 (dirty=True)      -> Frame 0 (t=2)
            (2, False),  # t=3: Fault p2 -> evicts clean p1 (t=1 < t=2, DISCARD) -> Frame 1
            (3, False),  # t=4: Fault p3 -> evicts dirty p0 (t=2 < t=3, SWAP_OUT!) -> Frame 0
            (0, False),  # t=5: Fault p0 (SWAP_STORAGE!) -> swap_in -> Frame 1 (evicts clean p2 t=3)
            (0, False),  # t=6: Hit p0
        ]
        proc = engine.submit_process(
            "MemApp",
            size_bytes=16 * 1024,  # 4 pages (0..3)
            process_type=ProcessType.NORMAL,
            cpu_burst_ms=len(pattern),
            memory_access_pattern=pattern,
        )

        # Execute 6 ms (indices 0..5) so process is still RUNNING/READY and frames are live!
        engine.step(6)
        mm_stats = kernel.memory_manager.stats
        self.assertEqual(mm_stats["page_faults_total"], 5)
        self.assertEqual(mm_stats["page_faults_process_image"], 1)
        self.assertEqual(mm_stats["page_faults_zero_fill"], 3)
        self.assertEqual(mm_stats["page_faults_swap"], 1)
        self.assertEqual(mm_stats["swap_outs_total"], 1)
        self.assertEqual(mm_stats["swap_ins_total"], 1)
        self.assertEqual(mm_stats["evictions_clean"], 2)
        self.assertEqual(mm_stats["evictions_dirty"], 1)

        # Live frames summary reflects exact physical RAM state
        live_frames = engine.get_frames_summary()
        self.assertEqual(len(live_frames), 2)
        self.assertTrue(all(row["occupied"] and row["state"] == "OCUPADA" for row in live_frames))
        self.assertEqual(live_frames[0]["logical_page"], 3)
        self.assertEqual(live_frames[0]["last_event"], "PAGE_FAULT")
        self.assertEqual(live_frames[1]["logical_page"], 0)
        self.assertEqual(live_frames[1]["last_event"], "PAGE_FAULT")

        # Execute final 7th ms -> Hit on page 0, then process completes and frees frames
        engine.step(1)
        self.assertEqual(proc.state, ProcessState.TERMINATED)
        self.assertEqual(kernel.memory_manager.physical_memory.get_occupied_count(), 0)
        self.assertEqual(kernel.memory_manager.swap_manager.get_used_slots_count(), 0)

        post_frames = engine.get_frames_summary()
        self.assertTrue(all(not row["occupied"] and row["state"] == "LIVRE" for row in post_frames))

        gm = engine.get_metrics()
        self.assertEqual(gm.page_hits_total, 2)
        self.assertEqual(gm.page_faults_total, 5)

        # 2. Second Chance (Clock) + explicit MEMORY_LOAD / MEMORY_WRITE syscalls
        engine.reset()
        kernel.memory_manager.set_replacement_policy(ReplacementAlgorithm.SECOND_CHANCE)
        p_sc = engine.submit_process(
            "ClockApp",
            size_bytes=12 * 1024,  # 3 pages
            cpu_burst_ms=4,
            memory_access_pattern=[(0, False), (1, False), (0, False), (2, False)],
        )
        engine.schedule_syscall(p_sc.pid, SyscallType.MEMORY_WRITE, trigger_cpu_ms=4, logical_page=2)
        engine.step(3)
        summary_sc = engine.get_frames_summary()
        self.assertEqual(summary_sc[0]["algorithm"], "SECOND_CHANCE")
        self.assertEqual(summary_sc[0]["last_event"], "HIT")
        engine.run()
        self.assertEqual(p_sc.state, ProcessState.TERMINATED)
        self.assertEqual(kernel.memory_manager.physical_memory.get_occupied_count(), 0)

    def test_scenario_h_buffer_video_mutex_contention_and_termination_cleanup(self):
        """Scenario H: T1/T2 Buffer_Video mutual exclusion demo and clean mutex release on kill."""
        kernel = SimulationKernel(quantum_ms=4)
        engine = kernel.execution_engine

        demo = engine.run_buffer_video_demo(quantum_ms=2)
        self.assertTrue(demo["critical_sections_disjoint"])
        self.assertFalse(demo["mutex"]["locked"])
        self.assertEqual(demo["mutex"]["acquire_count"], 2)
        self.assertEqual(demo["mutex"]["release_count"], 2)
        self.assertGreaterEqual(demo["mutex"]["contention_count"], 1)
        self.assertEqual(demo["process"]["state"], "TERMINATED")
        self.assertEqual(demo["t1"]["state"], "TERMINATED")
        self.assertEqual(demo["t2"]["state"], "TERMINATED")
        self.assertEqual(kernel.memory_manager.physical_memory.get_occupied_count(), 0)

        # Terminate a process holding a mutex while another process is waiting -> wakes waiter
        engine.reset()
        kernel.sync_manager.create_mutex("M_Shared")
        p_holder = engine.submit_process(
            "Holder",
            size_bytes=4096,
            priority=2,
            cpu_burst_ms=10,
            workload_steps=[WorkloadStep(0, SyscallType.MUTEX_LOCK, mutex_name="M_Shared")],
        )
        p_waiter = engine.submit_process(
            "Waiter",
            size_bytes=4096,
            priority=2,
            cpu_burst_ms=4,
            workload_steps=[
                WorkloadStep(0, SyscallType.MUTEX_LOCK, mutex_name="M_Shared"),
                WorkloadStep(2, SyscallType.MUTEX_UNLOCK, mutex_name="M_Shared"),
            ],
        )
        # Run 3 ms with quantum=2: Holder acquires M_Shared [0..2], Waiter blocks on M_Shared at t=2
        engine.step(3)
        self.assertEqual(p_waiter.state, ProcessState.BLOCKED)
        self.assertEqual(kernel.sync_manager.get_mutex("M_Shared").owner_pid, p_holder.pid)

        # Force terminate Holder -> M_Shared handed off to Waiter (BLOCKED -> READY), Waiter completes!
        engine.terminate_process("Holder")
        self.assertEqual(p_holder.state, ProcessState.TERMINATED)
        self.assertEqual(p_waiter.state, ProcessState.READY)
        engine.run()
        self.assertEqual(p_waiter.state, ProcessState.TERMINATED)
        self.assertFalse(kernel.sync_manager.get_mutex("M_Shared").locked)

    def test_scenario_i_circular_deadlock_and_stall_detection_no_infinite_loop(self):
        """Scenario I: Circular mutex deadlock and no-progress IO stall raise immediately without hanging."""
        kernel = SimulationKernel(quantum_ms=1)
        engine = kernel.execution_engine

        kernel.sync_manager.create_mutex("M1")
        kernel.sync_manager.create_mutex("M2")

        # Quantum=1ms: A runs [0..1] (locks M1 at cpu=0), B runs [1..2] (locks M2 at cpu=0),
        # A runs [2..3] (tries M2 at cpu=2 -> blocks), B runs [3..4] (tries M1 at cpu=2 -> DEADLOCK!)
        engine.submit_process(
            "ProcA",
            size_bytes=4096,
            priority=2,
            cpu_burst_ms=5,
            workload_steps=[
                WorkloadStep(0, SyscallType.MUTEX_LOCK, mutex_name="M1"),
                WorkloadStep(2, SyscallType.MUTEX_LOCK, mutex_name="M2"),
            ],
        )
        engine.submit_process(
            "ProcB",
            size_bytes=4096,
            priority=2,
            cpu_burst_ms=5,
            workload_steps=[
                WorkloadStep(0, SyscallType.MUTEX_LOCK, mutex_name="M2"),
                WorkloadStep(2, SyscallType.MUTEX_LOCK, mutex_name="M1"),
            ],
        )

        with self.assertRaises(DeadlockDetectedException) as ctx:
            engine.run()
        self.assertTrue(len(ctx.exception.cycle) >= 2)

        # Stall detection when a thread is BLOCKED with no pending completion event
        engine.reset()
        p_stall = engine.submit_process(
            "StalledIO",
            size_bytes=4096,
            cpu_burst_ms=4,
            workload_steps=[WorkloadStep(1, SyscallType.IO_READ, duration_ms=10, block_id=0)],
        )
        engine.step(1)
        self.assertEqual(p_stall.state, ProcessState.BLOCKED)
        # Simulate lost interrupt / cancelled wakeup event
        kernel.event_manager.cancel_for_entity(pid=p_stall.pid)
        with self.assertRaises(SimulationStallException):
            engine.run()

    def test_scenario_j_metrics_mathematical_invariants(self):
        """Scenario J: Exact WT, TAT, RT, CPU utilization, idle time, and PID 0 exclusion."""
        kernel = SimulationKernel(quantum_ms=4)
        engine = kernel.execution_engine

        # P1 arrives at t=2 (idle [0..2]), burst=4, IO@2ms for 3ms
        # P2 arrives at t=3, burst=2, prio=3
        p1 = engine.submit_process(
            "P1",
            size_bytes=4096,
            priority=2,
            cpu_burst_ms=4,
            arrival_time_ms=2,
            workload_steps=[WorkloadStep(2, SyscallType.SLEEP_WAIT, duration_ms=3)],
        )
        p2 = engine.submit_process(
            "P2",
            size_bytes=4096,
            priority=3,
            cpu_burst_ms=2,
            arrival_time_ms=3,
        )

        engine.run()

        gm = engine.get_metrics()
        self.assertEqual(gm.total_processes, 2)
        self.assertEqual(gm.completed_processes, 2)
        self.assertEqual(gm.cpu_busy_ms + gm.idle_time_ms, gm.total_simulation_ms)
        self.assertEqual(gm.cpu_busy_ms, 6)
        self.assertGreater(gm.idle_time_ms, 0)
        self.assertAlmostEqual(
            gm.cpu_utilization_pct,
            (gm.cpu_busy_ms / gm.total_simulation_ms) * 100.0,
        )

        for pm in gm.process_metrics:
            self.assertNotEqual(pm.pid, 0)
            self.assertIsNotNone(pm.turnaround_time_ms)
            self.assertIsNotNone(pm.response_time_ms)
            self.assertEqual(
                pm.turnaround_time_ms,
                pm.cpu_time_ms + pm.waiting_time_ms + pm.blocked_time_ms,
            )
            for tm in pm.thread_metrics:
                self.assertEqual(
                    tm.turnaround_time_ms,
                    tm.cpu_time_ms + tm.waiting_time_ms + tm.blocked_time_ms,
                )

        # Idle [0..2], P1 [2..4] (blocks [4..7]), P2 [4..6] (done at 6), idle [6..7], P1 [7..9] (done at 9)
        self.assertEqual(p1.finish_time_ms, 9)
        self.assertEqual(p2.finish_time_ms, 6)
        self.assertEqual(gm.total_simulation_ms, 9)
        self.assertEqual(gm.idle_time_ms, 3)

    def test_scenario_k_timeline_gantt_until_stops_reset_and_kernel_compat(self):
        """Scenario K: Timeline ordering, Gantt contiguity, until_process/until_event, reset, and compat."""
        # Preserve legacy SimulationKernel construction args + new Stage 5 kwargs
        mem_dev = InMemoryBlockDevice(capacity=8, block_size=512)
        kernel = SimulationKernel(
            block_device=mem_dev,
            disk_capacity=8,
            block_size=512,
            dynamic_frames=4,
            quantum_ms=3,
            default_seed=77,
        )
        self.assertIs(kernel.device, mem_dev)
        self.assertEqual(kernel.cpu_scheduler.quantum_ms, 3)
        self.assertEqual(kernel.execution_engine.default_seed, 77)

        engine = kernel.execution_engine
        p1 = engine.submit_process("First", size_bytes=2048, priority=2, cpu_burst_ms=3, arrival_time_ms=0)
        p2 = engine.submit_process("Second", size_bytes=2048, priority=2, cpu_burst_ms=4, arrival_time_ms=5)

        # Stop when PROCESS_ARRIVAL fires for Second at t=5
        ev_run = engine.run(until_event=SimulationEventType.PROCESS_ARRIVAL)
        self.assertEqual(ev_run["stop_reason"], "TARGET_EVENT_REACHED")
        self.assertEqual(kernel.clock.now_ms, 5)
        self.assertEqual(p1.state, ProcessState.TERMINATED)
        self.assertEqual(p2.state, ProcessState.READY)

        # Stop when Second terminates
        proc_run = engine.run(until_process="Second")
        self.assertEqual(proc_run["stop_reason"], "TARGET_PROCESS_TERMINATED")
        self.assertEqual(p2.state, ProcessState.TERMINATED)
        self.assertEqual(kernel.clock.now_ms, 9)

        # Timeline ordering invariant
        timeline = engine.get_timeline()
        self.assertGreater(len(timeline), 0)
        keys = [(e.timestamp_ms, e.seq) for e in timeline]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(engine.get_timeline(limit=2)), 2)

        # Gantt contiguity and total span invariant
        gantt = engine.get_gantt()
        self.assertEqual(gantt[0].start_ms, 0)
        self.assertEqual(gantt[-1].end_ms, kernel.clock.now_ms)
        for prev, curr in zip(gantt, gantt[1:]):
            self.assertEqual(prev.end_ms, curr.start_ms)

        # Reset preserves object references and clears all state cleanly
        pm_ref = kernel.process_manager
        mm_ref = kernel.memory_manager
        sched_ref = kernel.cpu_scheduler
        engine.reset()
        self.assertIs(kernel.process_manager, pm_ref)
        self.assertIs(kernel.memory_manager, mm_ref)
        self.assertIs(kernel.cpu_scheduler, sched_ref)
        self.assertEqual(kernel.clock.now_ms, 0)
        self.assertEqual(len(kernel.process_manager.list_processes()), 1)  # Nucleo_Base only
        self.assertEqual(engine.get_timeline(), [])
        self.assertEqual(engine.get_gantt(), [])
        self.assertEqual(kernel.memory_manager.physical_memory.get_occupied_count(), 0)
        self.assertEqual(kernel.memory_manager.stats["page_faults_total"], 0)
        self.assertEqual(kernel.cpu_scheduler.quantum_ms, 3)

        # Verify until_event=QUANTUM_EXPIRE stops cleanly at exact quantum boundary
        engine.submit_process("QProc", size_bytes=4096, cpu_burst_ms=5)
        q_run = engine.run(until_event=SimulationEventType.QUANTUM_EXPIRE)
        self.assertEqual(q_run["stop_reason"], "TARGET_EVENT_REACHED")
        self.assertEqual(kernel.clock.now_ms, 3)


if __name__ == "__main__":
    unittest.main()
