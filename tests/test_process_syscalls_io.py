"""Unit and integration tests for syscalls, I/O profiles, deterministic random I/O, and block registry."""

import random
import unittest

from os_simulator.core.clock import LogicalClock
from os_simulator.core.context import ExecutionContext
from os_simulator.core.events import EventManager
from os_simulator.core.exceptions import (
    InvalidProcessStateException,
    InvalidStateTransitionException,
    PermissionDeniedException,
)
from os_simulator.core.types import (
    BlockReason,
    IOProfileType,
    PrivilegeMode,
    ProcessState,
    SimulationEventType,
    SyscallType,
)
from os_simulator.filesystem.service import FileSystemService
from os_simulator.io.scheduler import FCFSScheduler, SSTFScheduler
from os_simulator.io.service import IOManager
from os_simulator.process.manager import ProcessManager
from os_simulator.process.syscalls import (
    BlockRecord,
    BlockRegistry,
    IOProfile,
    SyscallDispatcher,
    SyscallExecutionRecord,
    SyscallSpec,
)
from os_simulator.process.thread import SimulatedThread, WorkloadStep
from os_simulator.security.audit import AuditLog
from os_simulator.security.auth import AuthenticationService
from os_simulator.security.service import SecurityManager
from os_simulator.security.user import UserManager
from os_simulator.storage.adapter import IOBlockDeviceAdapter
from os_simulator.storage.memory_block_device import InMemoryBlockDevice
from os_simulator.storage.physical_disk import PhysicalDisk


class TestIOProfileValidation(unittest.TestCase):
    """Verify IOProfile parameter validation and serialization."""

    def test_valid_profiles_and_to_dict(self):
        none_p = IOProfile()
        self.assertEqual(none_p.profile_type, IOProfileType.NONE)
        self.assertEqual(none_p.to_dict()["profile_type"], "NONE")

        per_p = IOProfile(
            profile_type="periodic",
            interval_cpu_ms=3,
            default_duration_ms=5,
            syscall_type="io_write",
            block_id=2,
        )
        self.assertEqual(per_p.profile_type, IOProfileType.PERIODIC)
        self.assertEqual(per_p.syscall_type, SyscallType.IO_WRITE)
        self.assertEqual(per_p.interval_cpu_ms, 3)

        rnd_p = IOProfile(
            profile_type=IOProfileType.RANDOM,
            min_duration_ms=2,
            max_duration_ms=6,
            io_probability=0.5,
            max_random_events=4,
            seed=99,
        )
        self.assertEqual(rnd_p.seed, 99)
        self.assertEqual(rnd_p.to_dict()["max_random_events"], 4)

    def test_invalid_inputs_rejected(self):
        # Zero / negative durations
        for kwargs in (
            {"default_duration_ms": 0},
            {"default_duration_ms": -2},
            {"min_duration_ms": 0},
            {"max_duration_ms": -1},
            {"default_duration_ms": True},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    IOProfile(**kwargs)

        # min > max
        with self.assertRaises(ValueError):
            IOProfile(min_duration_ms=7, max_duration_ms=4)

        # io_probability out of [0.0, 1.0] or non-numeric / bool / nan
        for bad_prob in (-0.01, 1.01, float("nan"), True, "high"):
            with self.subTest(bad_prob=bad_prob):
                with self.assertRaises(ValueError):
                    IOProfile(profile_type=IOProfileType.RANDOM, io_probability=bad_prob)  # type: ignore[arg-type]

        # Invalid interval_cpu_ms for PERIODIC and non-PERIODIC
        with self.assertRaises(ValueError):
            IOProfile(profile_type=IOProfileType.PERIODIC, interval_cpu_ms=None)
        with self.assertRaises(ValueError):
            IOProfile(profile_type=IOProfileType.PERIODIC, interval_cpu_ms=0)
        with self.assertRaises(ValueError):
            IOProfile(profile_type=IOProfileType.PERIODIC, interval_cpu_ms=-5)
        with self.assertRaises(ValueError):
            IOProfile(profile_type=IOProfileType.RANDOM, interval_cpu_ms=0)

        # Negative max_random_events or block_id
        with self.assertRaises(ValueError):
            IOProfile(profile_type=IOProfileType.RANDOM, max_random_events=-1)
        with self.assertRaises(ValueError):
            IOProfile(block_id=-1)


class TestBlockRegistry(unittest.TestCase):
    """Verify BlockRecord and BlockRegistry tracking and error guards."""

    def test_block_unblock_audit_lifecycle(self):
        reg = BlockRegistry()
        self.assertFalse(reg.is_blocked(1))
        self.assertIsNone(reg.get_active_block(1))

        rec = reg.record_block(
            tid=1,
            pid=100,
            thread_name="main",
            process_name="App",
            reason=BlockReason.IO_WAIT,
            resource_id="block:4",
            blocked_at_ms=10,
            expected_unblock_at_ms=15,
            previous_state=ProcessState.RUNNING,
            syscall_type=SyscallType.IO_READ,
        )
        self.assertIsInstance(rec, BlockRecord)
        self.assertTrue(reg.is_blocked(1))
        self.assertEqual(len(reg.get_active_blocks()), 1)
        self.assertIs(reg.get_active_block(1), rec)
        self.assertTrue(rec.is_active)
        self.assertIsNone(rec.blocked_duration_ms)

        # Double blocking same TID rejected
        with self.assertRaises(InvalidStateTransitionException):
            reg.record_block(
                tid=1,
                pid=100,
                reason=BlockReason.SLEEP_WAIT,
                blocked_at_ms=11,
            )

        closed = reg.record_unblock(1, timestamp_ms=15, next_state=ProcessState.READY)
        self.assertIs(closed, rec)
        self.assertFalse(reg.is_blocked(1))
        self.assertEqual(reg.get_active_blocks(), [])
        self.assertEqual(closed.unblocked_at_ms, 15)
        self.assertEqual(closed.blocked_duration_ms, 5)
        self.assertEqual(closed.next_state, ProcessState.READY)
        self.assertFalse(closed.is_active)
        self.assertEqual(len(reg.get_history()), 1)
        self.assertEqual(closed.to_dict()["reason"], "IO_WAIT")

    def test_rejects_unblocking_non_blocked_and_invalid_inputs(self):
        reg = BlockRegistry()
        with self.assertRaises(InvalidStateTransitionException) as ctx:
            reg.record_unblock(99, timestamp_ms=10)
        self.assertIsInstance(ctx.exception, InvalidProcessStateException)

        reg.record_block(tid=2, pid=100, reason=BlockReason.FS_IO, blocked_at_ms=20)
        # Unblock timestamp before blocked_at_ms rejected
        with self.assertRaises(ValueError):
            reg.record_unblock(2, timestamp_ms=19)
        # Invalid target state (e.g. RUNNING directly from BLOCKED) rejected
        with self.assertRaises(InvalidStateTransitionException):
            reg.record_unblock(2, timestamp_ms=25, next_state=ProcessState.RUNNING)
        # Reject BlockReason.NONE
        with self.assertRaises(ValueError):
            reg.record_block(tid=3, pid=100, reason=BlockReason.NONE, blocked_at_ms=20)


class TestSyscallDispatcherCoreAndIO(unittest.TestCase):
    """Verify CPU-time trigger vs global clock, IOManager/FS integration, and completion wakeups."""

    def setUp(self) -> None:
        self.pm = ProcessManager()
        self.clock = LogicalClock(0)
        self.em = EventManager(clock=self.clock)

    def test_scheduled_syscall_triggers_by_cpu_consumed_never_global_clock(self):
        proc = self.pm.create_process("Worker", size_bytes=4096, cpu_burst_ms=10)
        thread = self.pm.get_thread_by_name(proc, "main")
        step = SyscallSpec(
            trigger_cpu_ms=3,
            syscall_type=SyscallType.SLEEP_WAIT,
            duration_ms=5,
        )
        thread.add_workload_step(step)
        self.pm.transition_thread_state(thread, ProcessState.RUNNING, timestamp_ms=100)

        dispatcher = SyscallDispatcher(self.pm, self.em)

        # Global clock is already 500ms, but thread only consumed 2ms CPU -> MUST NOT trigger
        self.clock.advance_to(500)
        thread.cpu_consumed_ms = 2
        self.assertEqual(dispatcher.check_due_syscalls(thread, now_ms=self.clock.now_ms), [])

        # Thread reaches cpu_consumed_ms == 3 -> triggers
        thread.cpu_consumed_ms = 3
        due = dispatcher.check_due_syscalls(thread, now_ms=self.clock.now_ms)
        self.assertEqual(due, [step])

        rec = dispatcher.dispatch_syscall(thread, due[0], now_ms=500)
        self.assertIsInstance(rec, SyscallExecutionRecord)
        self.assertTrue(rec.blocked)
        self.assertEqual(rec.block_reason, BlockReason.SLEEP_WAIT)
        self.assertEqual(thread.state, ProcessState.BLOCKED)
        self.assertTrue(step.executed)

        # Scheduled SLEEP_WAKEUP at 500 + 5 = 505ms
        next_ev = self.em.peek_next()
        self.assertIsNotNone(next_ev)
        assert next_ev is not None
        self.assertEqual(next_ev.event_type, SimulationEventType.SLEEP_WAKEUP)
        self.assertEqual(next_ev.timestamp_ms, 505)

        # Step cannot be repeated after wakeup while cpu_consumed_ms is still 3
        popped = self.em.pop_next()
        assert popped is not None
        unblocked = dispatcher.handle_completion_event(popped, now_ms=505)
        self.assertIs(unblocked, thread)
        self.assertEqual(thread.state, ProcessState.READY)
        self.assertEqual(thread.total_blocked_ms, 5)
        self.assertFalse(dispatcher.block_registry.is_blocked(thread.tid))
        self.assertEqual(dispatcher.check_due_syscalls(thread, now_ms=505), [])

        with self.assertRaises(ValueError):
            self.pm.transition_thread_state(thread, ProcessState.RUNNING, timestamp_ms=505)
            dispatcher.dispatch_syscall(thread, step, now_ms=505)

    def test_io_read_and_generic_io_write_update_real_io_manager_without_corrupting_data(self):
        disk = PhysicalDisk(disk_id=0, capacity_blocks=16, block_size=256, sectors_per_track=4)
        io_manager = IOManager(storage_backend=disk, scheduler=SSTFScheduler(initial_head=0), sectors_per_track=4)
        adapter = IOBlockDeviceAdapter(io_manager=io_manager, logical_capacity=16, block_size=256)
        fs = FileSystemService(block_device=adapter)

        # Write a real file via FS (occupies block(s) with real payload)
        fs.write_file("/integridade.txt", "DADO_CRITICO_PRESERVADO")
        inode = fs.inode_table[fs.vfs.get_file("/integridade.txt").inode_id]
        target_block = inode.allocated_blocks[0]

        reads_before = io_manager.total_reads
        writes_before = io_manager.total_writes
        seeks_before = io_manager.total_seek_tracks

        proc = self.pm.create_process("IOApp", size_bytes=4096, cpu_burst_ms=10)
        thread = self.pm.get_thread_by_name(proc, "main")
        self.pm.transition_thread_state(thread, ProcessState.RUNNING, timestamp_ms=0)

        dispatcher = SyscallDispatcher(
            process_manager=self.pm,
            event_manager=self.em,
            io_manager=io_manager,
            block_device=adapter,
            fs_service=fs,
        )

        # 1. Generic IO_WRITE (data=None) to file's block on track >= 1 (choose block 8 -> track 2 if possible, else target_block)
        write_step = WorkloadStep(
            trigger_cpu_ms=1,
            syscall_type=SyscallType.IO_WRITE,
            duration_ms=4,
            block_id=target_block,
            data=None,
        )
        thread.cpu_consumed_ms = 1
        rec_w = dispatcher.dispatch_syscall(thread, write_step, now_ms=1)
        self.assertTrue(rec_w.blocked)
        self.assertEqual(rec_w.block_reason, BlockReason.IO_WAIT)
        self.assertEqual(io_manager.total_writes, writes_before + 1)
        self.assertEqual(io_manager.total_reads, reads_before)
        # Existing filesystem data must remain intact!
        self.assertEqual(fs.read_file("/integridade.txt"), "DADO_CRITICO_PRESERVADO")

        # Complete IO_WRITE
        ev_w = self.em.pop_next()
        assert ev_w is not None
        self.assertEqual(ev_w.event_type, SimulationEventType.IO_COMPLETION)
        dispatcher.handle_completion_event(ev_w, now_ms=5)

        # 2. IO_READ on block 12 (track 3) -> updates total_reads & total_seek_tracks genuinely
        self.pm.transition_thread_state(thread, ProcessState.RUNNING, timestamp_ms=5)
        thread.cpu_consumed_ms = 2
        read_step = WorkloadStep(
            trigger_cpu_ms=2,
            syscall_type=SyscallType.IO_READ,
            duration_ms=3,
            block_id=12,
        )
        reads_mid = io_manager.total_reads
        seeks_mid = io_manager.total_seek_tracks
        rec_r = dispatcher.dispatch_syscall(thread, read_step, now_ms=6)
        self.assertEqual(rec_r.block_id, 12)
        self.assertEqual(io_manager.total_reads, reads_mid + 1)
        self.assertGreater(io_manager.total_seek_tracks, seeks_mid)
        self.assertGreater(io_manager.total_seek_tracks, seeks_before)

        ev_r = self.em.pop_next()
        assert ev_r is not None
        dispatcher.handle_completion_event(ev_r, now_ms=9)
        self.assertEqual(dispatcher.get_stats()["blocking_syscalls"], 2)

    def test_block_device_fallback_and_fs_syscalls_with_auth_context(self):
        dev = InMemoryBlockDevice(capacity=8, block_size=128)
        audit = AuditLog()
        um = UserManager(default_iterations=1000)
        alice_user = um.useradd("alice", password="Secret@123", primary_group="users", create_home=False)
        auth_service = AuthenticationService(um, audit)
        sec = SecurityManager(um, auth_service, audit)
        fs = FileSystemService(block_device=dev, auth_port=sec)
        sec.set_filesystem(fs)

        root_ctx = ExecutionContext(user_id=0, username="root", groups=["root"], privilege_mode=PrivilegeMode.KERNEL_MODE)
        fs.write_file("/segredo.txt", "top-secret", context=root_ctx)
        sec.chmod(root_ctx, "/segredo.txt", "600")

        alice_ctx = ExecutionContext(
            user_id=alice_user.user_id,
            username="alice",
            groups=alice_user.groups,
            privilege_mode=PrivilegeMode.USER_MODE,
        )

        proc = self.pm.create_process("FSProc", size_bytes=4096, cpu_burst_ms=10)
        thread = self.pm.get_thread_by_name(proc, "main")
        self.pm.transition_thread_state(thread, ProcessState.RUNNING, timestamp_ms=0)

        dispatcher = SyscallDispatcher(
            process_manager=self.pm,
            event_manager=self.em,
            block_device=dev,
            fs_service=fs,
            auth_context=alice_ctx,
            audit_log=audit,
        )

        # Alice cannot read root's 600 file
        denied_step = WorkloadStep(trigger_cpu_ms=1, syscall_type=SyscallType.FS_READ, duration_ms=3, path="/segredo.txt")
        with self.assertRaises(PermissionDeniedException):
            dispatcher.dispatch_syscall(thread, denied_step, now_ms=1)
        self.assertEqual(thread.state, ProcessState.RUNNING)
        self.assertFalse(dispatcher.block_registry.is_blocked(thread.tid))
        self.assertGreater(len(audit.filter_by_type("SYSCALL_EXECUTED")), 0)

        # Alice can write and read her own public file
        fs.write_file("/publico.txt", "ola", context=root_ctx)
        sec.chmod(root_ctx, "/publico.txt", "666")

        ok_write = WorkloadStep(
            trigger_cpu_ms=2,
            syscall_type=SyscallType.FS_WRITE,
            duration_ms=2,
            path="/publico.txt",
            data="novo-conteudo",
        )
        rec = dispatcher.dispatch_syscall(thread, ok_write, now_ms=2)
        self.assertTrue(rec.blocked)
        self.assertEqual(rec.block_reason, BlockReason.FS_IO)
        self.assertEqual(fs.read_file("/publico.txt", context=root_ctx), "novo-conteudo")

        ev = self.em.pop_next()
        assert ev is not None
        dispatcher.handle_completion_event(ev, now_ms=4)
        self.assertEqual(thread.state, ProcessState.READY)

        # YIELD does not block or schedule wakeup
        self.pm.transition_thread_state(thread, ProcessState.RUNNING, timestamp_ms=4)
        yield_step = WorkloadStep(trigger_cpu_ms=3, syscall_type=SyscallType.YIELD)
        y_rec = dispatcher.dispatch_syscall(thread, yield_step, now_ms=4)
        self.assertFalse(y_rec.blocked)
        self.assertEqual(thread.state, ProcessState.RUNNING)
        self.assertTrue(self.em.is_empty())

    def test_periodic_and_deterministic_random_io_and_termination(self):
        # 1. PERIODIC profile
        p_per = self.pm.create_process(
            "PeriodicApp",
            size_bytes=4096,
            cpu_burst_ms=10,
            io_profile=IOProfile(
                profile_type=IOProfileType.PERIODIC,
                interval_cpu_ms=3,
                default_duration_ms=4,
                block_id=5,
            ),
        )
        t_per = self.pm.get_thread_by_name(p_per, "main")
        dispatcher_p = SyscallDispatcher(self.pm, self.em)

        triggered_cpus = []
        for cpu in range(0, t_per.cpu_burst_ms + 1):
            t_per.cpu_consumed_ms = cpu
            steps = dispatcher_p.check_due_syscalls(t_per, now_ms=cpu * 10)
            for s in steps:
                triggered_cpus.append((s.trigger_cpu_ms, s.duration_ms, s.block_id))
            # Calling again at same cpu_consumed_ms must NOT duplicate
            self.assertEqual(dispatcher_p.check_due_syscalls(t_per, now_ms=cpu * 10 + 1), [])

        # Fires at 3, 6, 9 only (never 0, never 10 == cpu_burst_ms)
        self.assertEqual(triggered_cpus, [(3, 4, 5), (6, 4, 5), (9, 4, 5)])

        # 2. RANDOM profile reproducibility & max_random_events cap
        def run_random_sequence(seed: int):
            pm = ProcessManager()
            em = EventManager()
            proc = pm.create_process(
                "RndApp",
                size_bytes=4096,
                cpu_burst_ms=20,
                io_profile=IOProfile(
                    profile_type=IOProfileType.RANDOM,
                    min_duration_ms=2,
                    max_duration_ms=6,
                    io_probability=0.5,
                    max_random_events=3,
                    seed=seed,
                ),
            )
            th = pm.get_thread_by_name(proc, "main")
            disp = SyscallDispatcher(pm, em)
            pm.transition_thread_state(th, ProcessState.RUNNING, timestamp_ms=0)
            now = 0
            results = []
            for cpu in range(1, th.cpu_burst_ms + 1):
                th.cpu_consumed_ms = cpu
                now += 1
                for step in disp.check_due_syscalls(th, now_ms=now):
                    results.append((step.trigger_cpu_ms, step.duration_ms, step.block_id))
                    disp.dispatch_syscall(th, step, now_ms=now)
                    ev = em.pop_next()
                    assert ev is not None
                    now = ev.timestamp_ms
                    disp.handle_completion_event(ev, now_ms=now)
                    pm.transition_thread_state(th, ProcessState.RUNNING, timestamp_ms=now)
            return results, disp.get_stats()

        global_state_before = random.getstate()
        seq_a1, stats_a1 = run_random_sequence(seed=77)
        seq_a2, stats_a2 = run_random_sequence(seed=77)
        seq_b, _ = run_random_sequence(seed=88)
        self.assertEqual(random.getstate(), global_state_before)

        self.assertEqual(seq_a1, seq_a2)
        self.assertEqual(stats_a1, stats_a2)
        self.assertNotEqual(seq_a1, seq_b)
        self.assertLessEqual(len(seq_a1), 3)
        for _, dur, bid in seq_a1:
            self.assertGreaterEqual(dur, 2)
            self.assertLessEqual(dur, 6)
            assert bid is not None
            self.assertGreaterEqual(bid, 0)
            self.assertLess(bid, 16)

        # Ensure max_random_events caps even with io_probability=1.0 so process completes
        pm_cap = ProcessManager()
        em_cap = EventManager()
        proc_cap = pm_cap.create_process(
            "CapApp",
            size_bytes=4096,
            cpu_burst_ms=10,
            io_profile=IOProfile(
                profile_type=IOProfileType.RANDOM,
                io_probability=1.0,
                max_random_events=2,
                seed=42,
            ),
        )
        t_cap = pm_cap.get_thread_by_name(proc_cap, "main")
        disp_cap = SyscallDispatcher(pm_cap, em_cap)
        cap_events = []
        for cpu in range(0, t_cap.cpu_burst_ms + 1):
            t_cap.cpu_consumed_ms = cpu
            cap_events.extend(disp_cap.check_due_syscalls(t_cap, now_ms=cpu))
        self.assertEqual(len(cap_events), 2)

    def test_workload_step_validation_and_completion_edge_cases(self):
        proc = self.pm.create_process("ValApp", size_bytes=4096, cpu_burst_ms=8)
        thread = self.pm.get_thread_by_name(proc, "main")
        self.pm.transition_thread_state(thread, ProcessState.RUNNING, timestamp_ms=0)
        dispatcher = SyscallDispatcher(self.pm, self.em)

        # Blocking syscall at or past cpu_burst_ms rejected
        bad_at_end = WorkloadStep(trigger_cpu_ms=8, syscall_type=SyscallType.IO_READ, duration_ms=3, block_id=0)
        with self.assertRaises(ValueError):
            dispatcher.dispatch_syscall(thread, bad_at_end, now_ms=8)

        bad_past_end = WorkloadStep(trigger_cpu_ms=10, syscall_type=SyscallType.SLEEP_WAIT, duration_ms=2)
        with self.assertRaises(ValueError):
            dispatcher.dispatch_syscall(thread, bad_past_end, now_ms=10)

        # Non-blocking step at completion (trigger_cpu_ms == cpu_burst_ms) is allowed
        exit_step = WorkloadStep(trigger_cpu_ms=8, syscall_type=SyscallType.YIELD, duration_ms=0)
        thread.cpu_consumed_ms = 8
        thread.add_workload_step(exit_step)
        self.assertEqual(dispatcher.check_due_syscalls(thread, now_ms=8), [exit_step])

        # 0-burst test allows trigger_cpu_ms == 0
        p0 = self.pm.create_process("ZeroBurst", size_bytes=4096, cpu_burst_ms=0)
        t0 = self.pm.ensure_main_thread(p0)
        self.pm.transition_thread_state(t0, ProcessState.RUNNING, timestamp_ms=0)
        step0 = WorkloadStep(trigger_cpu_ms=0, syscall_type=SyscallType.SLEEP_WAIT, duration_ms=2)
        rec0 = dispatcher.dispatch_syscall(t0, step0, now_ms=0)
        self.assertTrue(rec0.blocked)

        # If process is terminated while thread is blocked, completion event does not resurrect it
        self.pm.terminate_process(p0.pid, timestamp_ms=1)
        ev0 = self.em.pop_next()
        assert ev0 is not None
        self.assertIsNone(dispatcher.handle_completion_event(ev0, now_ms=2))
        self.assertEqual(t0.state, ProcessState.TERMINATED)
        self.assertFalse(dispatcher.block_registry.is_blocked(t0.tid))

    def test_fixed_profile_wrapping_reset_and_dispatcher_error_guards(self):
        dev = InMemoryBlockDevice(capacity=8, block_size=64)
        fixed_step = WorkloadStep(trigger_cpu_ms=2, syscall_type=SyscallType.IO_READ, duration_ms=3, block_id=19)
        proc = self.pm.create_process(
            "FixedApp",
            size_bytes=4096,
            cpu_burst_ms=6,
            io_profile=IOProfile(profile_type=IOProfileType.FIXED, fixed_steps=[fixed_step]),
        )
        t = self.pm.get_thread_by_name(proc, "main")
        dispatcher = SyscallDispatcher(self.pm, self.em, block_device=dev)

        # Cannot dispatch syscall while thread is READY
        with self.assertRaises(InvalidStateTransitionException):
            dispatcher.dispatch_syscall(t, fixed_step, now_ms=0)

        # Negative now_ms rejected
        with self.assertRaises(ValueError):
            dispatcher.check_due_syscalls(t, now_ms=-1)

        self.pm.transition_thread_state(t, ProcessState.RUNNING, timestamp_ms=0)
        t.cpu_consumed_ms = 2
        due = dispatcher.check_due_syscalls(t, now_ms=2)
        self.assertEqual(due, [fixed_step])
        rec = dispatcher.dispatch_syscall(t, due[0], now_ms=2)
        # block_id=19 % 8 == 3
        self.assertEqual(rec.block_id, 3)
        self.assertEqual(rec.resource_id, "block:3")
        self.assertEqual(len(dispatcher.get_history(pid=proc.pid, tid=t.tid)), 1)

        # Missing path on FS_READ with fs_service configured raises ValueError
        fs = FileSystemService(block_device=dev)
        dispatcher_fs = SyscallDispatcher(self.pm, self.em, block_device=dev, fs_service=fs)
        p_fs = self.pm.create_process("FSVal", size_bytes=4096, cpu_burst_ms=5)
        t_fs = self.pm.get_thread_by_name(p_fs, "main")
        self.pm.transition_thread_state(t_fs, ProcessState.RUNNING, timestamp_ms=2)
        with self.assertRaises(ValueError):
            dispatcher_fs.dispatch_syscall(
                t_fs,
                WorkloadStep(trigger_cpu_ms=1, syscall_type=SyscallType.FS_READ, duration_ms=2, path=""),
                now_ms=2,
            )

        # Reset clears history and block registry
        dispatcher.reset()
        self.assertEqual(dispatcher.get_history(), [])
        self.assertEqual(dispatcher.block_registry.get_history(), [])
        self.assertEqual(dispatcher.get_stats()["total_syscalls"], 0)


if __name__ == "__main__":
    unittest.main()
