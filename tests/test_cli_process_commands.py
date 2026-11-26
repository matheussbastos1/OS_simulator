"""End-to-end CLI tests for Stage 5 processes, threads, scheduling, syscalls, concurrency, and metrics."""

import unittest

from os_simulator.cli.commands import CommandDispatcher
from os_simulator.core.simulation_kernel import SimulationKernel
from os_simulator.core.types import PrivilegeMode, ProcessState


class TestCLIProcessCommands(unittest.TestCase):
    """Comprehensive end-to-end verification of Stage 5 CLI commands and regressions."""

    def setUp(self) -> None:
        self.kernel = SimulationKernel(dynamic_frames=4, block_size=4096, quantum_ms=4, default_seed=42)
        self.dispatcher = CommandDispatcher(self.kernel)

    def test_create_process_stage5_flags_privileges_and_oom_rollback(self):
        """Verify create_process Stage 5 flags, Stage 4 fields, root privilege check, and OOM rollback."""
        r_ok = self.dispatcher.execute_line(
            'create_process --name "AppStage5" --size 8KB --type normal '
            '--priority 2 --burst 6 --arrival 1 --io-profile periodic --io-every 2 --io-duration 3 --pages 0,1'
        )
        self.assertTrue(r_ok.success, r_ok.error)
        # Stage 4 fields remain intact
        self.assertIn("Páginas Lógicas: 2 páginas", r_ok.output)
        self.assertIn("Frag. Interna  : 0 bytes", r_ok.output)
        # Stage 5 summary lines appended
        self.assertIn("Prioridade     : 2", r_ok.output)
        self.assertIn("Burst de CPU   : 6 ms", r_ok.output)
        self.assertIn("Chegada        : 1 ms", r_ok.output)
        self.assertIn("PERIODIC", r_ok.output)
        self.assertEqual(r_ok.data["process"]["state"], "NEW")  # arrival=1 > now=0

        # Audit log still includes CREATE_PROCESS
        actions = [ev.action for ev in self.kernel.audit_log.get_events()]
        self.assertIn("CREATE_PROCESS", actions)

        # OOM rollback on critical process with Stage 5 flags
        r_oom = self.dispatcher.execute_line(
            'create_process --name "Crit_OOM" --size 8192KB --type critical --priority 1 --burst 4'
        )
        self.assertFalse(r_oom.success)
        self.assertNotIn("Crit_OOM", self.kernel.process_manager.name_to_pid)

        # Non-root cannot create critical process with Stage 5 flags
        self.kernel.context.user_id = 1000
        self.kernel.context.username = "carlos"
        self.kernel.context.groups = ["devs"]
        self.kernel.context.privilege_mode = PrivilegeMode.USER_MODE
        r_denied = self.dispatcher.execute_line(
            'create_process --name "Crit_Denied" --size 512KB --type critical --priority 1 --burst 2'
        )
        self.assertFalse(r_denied.success)
        self.assertIn("Acesso negado", r_denied.error)

    def test_scenario_b_no_admit_admit_step_block_unblock_and_completion(self):
        """Scenario B: --no-admit -> NEW -> process_admit -> READY -> step -> BLOCKED -> unblock -> TERMINATED."""
        r_new = self.dispatcher.execute_line(
            'create_process --name "WorkerB" --size 8KB --type normal '
            '--priority 2 --burst 5 --io-profile periodic --io-every 2 --io-duration 3 --no-admit'
        )
        self.assertTrue(r_new.success, r_new.error)
        self.assertEqual(r_new.data["process"]["state"], "NEW")

        # ps shows NEW
        r_ps1 = self.dispatcher.execute_line("ps")
        self.assertTrue(r_ps1.success)
        self.assertIn("WorkerB", r_ps1.output)
        self.assertIn("NEW", r_ps1.output)

        # Admit process: NEW -> READY
        r_admit = self.dispatcher.execute_line("process_admit --process WorkerB")
        self.assertTrue(r_admit.success, r_admit.error)
        self.assertEqual(r_admit.data["state"], "READY")

        # Re-admitting READY process fails cleanly
        r_admit_dup = self.dispatcher.execute_line("process_admit --process WorkerB")
        self.assertFalse(r_admit_dup.success)

        # Step 2ms -> consumes 2ms CPU and blocks on periodic I/O for 3ms (unblock at t=5)
        r_s1 = self.dispatcher.execute_line("sched_step --ms 2")
        self.assertTrue(r_s1.success, r_s1.error)
        self.assertEqual(r_s1.data["end_ms"], 2)

        r_ps2 = self.dispatcher.execute_line("process_status")
        self.assertTrue(r_ps2.success)
        self.assertIn("BLOCKED", r_ps2.output)
        self.assertIn("IO_WAIT", r_ps2.output)

        r_sched_st = self.dispatcher.execute_line("sched_status")
        self.assertTrue(r_sched_st.success)
        self.assertIn("IO_WAIT", r_sched_st.output)
        self.assertIn("desbloqueio previsto em 5ms", r_sched_st.output)

        # Step 3ms -> reaches t=5ms and unblocks BLOCKED -> READY
        r_s2 = self.dispatcher.execute_line("sched_step --ms 3")
        self.assertTrue(r_s2.success, r_s2.error)
        self.assertEqual(self.kernel.process_manager.get_process("WorkerB").state, ProcessState.READY)

        # Run to completion (another periodic I/O at cpu=4 blocks [7..10], finishes at 11)
        r_run = self.dispatcher.execute_line("sched_run")
        self.assertTrue(r_run.success, r_run.error)
        self.assertEqual(self.kernel.process_manager.get_process("WorkerB").state, ProcessState.TERMINATED)

        # ps without --all hides terminated; ps --all shows TERMINATED
        r_ps_active = self.dispatcher.execute_line("ps")
        self.assertNotIn("WorkerB", r_ps_active.output)
        r_ps_all = self.dispatcher.execute_line("ps --all")
        self.assertIn("WorkerB", r_ps_all.output)
        self.assertIn("TERMINATED", r_ps_all.output)

    def test_priority_round_robin_threads_and_sched_stop_conditions(self):
        """Test sched_config, priority preemption, Round-Robin, thread_create, thread_status, and stop conditions."""
        # Inspect default config
        r_cfg0 = self.dispatcher.execute_line("sched_config")
        self.assertTrue(r_cfg0.success)
        self.assertEqual(r_cfg0.data["quantum_ms"], 4)
        self.assertIn("priority_rr", r_cfg0.output)

        # Configure quantum=2
        r_cfg1 = self.dispatcher.execute_line("sched_config --algorithm priority_rr --quantum 2")
        self.assertTrue(r_cfg1.success, r_cfg1.error)
        self.assertEqual(r_cfg1.data["quantum_ms"], 2)

        # Create equal-priority processes and higher-priority dynamic arrival
        self.assertTrue(
            self.dispatcher.execute_line("create_process --name P_A --size 4KB --priority 3 --burst 4").success
        )
        self.assertTrue(
            self.dispatcher.execute_line("create_process --name P_B --size 4KB --priority 3 --burst 3").success
        )
        self.assertTrue(
            self.dispatcher.execute_line(
                "create_process --name P_High --size 4KB --priority 1 --burst 2 --arrival 3"
            ).success
        )

        # Add extra thread to P_A
        r_tc = self.dispatcher.execute_line(
            "thread_create --process P_A --name worker --priority 2 --burst 2 --arrival 1"
        )
        self.assertTrue(r_tc.success, r_tc.error)
        self.assertEqual(r_tc.data["thread"]["name"], "worker")

        r_ts = self.dispatcher.execute_line("thread_status --process P_A")
        self.assertTrue(r_ts.success)
        self.assertEqual(r_ts.data["count"], 2)
        self.assertIn("main", r_ts.output)
        self.assertIn("worker", r_ts.output)

        # Run until PROCESS_ARRIVAL event at t=3
        r_ev = self.dispatcher.execute_line("sched_run --until-event PROCESS_ARRIVAL")
        self.assertTrue(r_ev.success, r_ev.error)
        self.assertEqual(r_ev.data["stop_reason"], "TARGET_EVENT_REACHED")
        self.assertEqual(self.kernel.clock.now_ms, 3)

        # Run until P_High finishes
        r_proc = self.dispatcher.execute_line("sched_run --until-process P_High")
        self.assertTrue(r_proc.success, r_proc.error)
        self.assertEqual(r_proc.data["stop_reason"], "TARGET_PROCESS_TERMINATED")
        self.assertEqual(self.kernel.process_manager.get_process("P_High").state, ProcessState.TERMINATED)

        # Finish all
        r_all = self.dispatcher.execute_line("sched_run")
        self.assertTrue(r_all.success, r_all.error)
        self.assertEqual(r_all.data["metrics"]["completed_processes"], 3)

    def test_syscalls_cli_io_fs_acl_sleep_yield_memory_and_exit(self):
        """Test process_syscall across scheduled and immediate (--now) modes plus FS ACL enforcement."""
        self.assertTrue(self.dispatcher.execute_line('write_file /publico.txt "dado-inicial"').success)
        self.assertTrue(
            self.dispatcher.execute_line("create_process --name SysApp --size 8KB --priority 2 --burst 6").success
        )

        # Schedule yield, io_read, io_write, sleep, fs_write, fs_read, memory_load, memory_write
        r1 = self.dispatcher.execute_line("process_syscall --process SysApp --type yield --at-cpu 0")
        self.assertTrue(r1.success, r1.error)
        r2 = self.dispatcher.execute_line(
            "process_syscall --process SysApp --type io_read --at-cpu 1 --duration 2 --block 3"
        )
        self.assertTrue(r2.success, r2.error)
        r2w = self.dispatcher.execute_line(
            "process_syscall --process SysApp --type io_write --at-cpu 2 --duration 1 --block 4"
        )
        self.assertTrue(r2w.success, r2w.error)
        r3 = self.dispatcher.execute_line(
            "process_syscall --process SysApp --type sleep --at-cpu 2 --duration 2"
        )
        self.assertTrue(r3.success, r3.error)
        r4 = self.dispatcher.execute_line(
            'process_syscall --process SysApp --type fs_write --at-cpu 3 --duration 1 --path /publico.txt --data "atualizado"'
        )
        self.assertTrue(r4.success, r4.error)
        r4r = self.dispatcher.execute_line(
            "process_syscall --process SysApp --type fs_read --at-cpu 4 --duration 1 --path /publico.txt"
        )
        self.assertTrue(r4r.success, r4r.error)
        r5l = self.dispatcher.execute_line(
            "process_syscall --process SysApp --type memory_load --at-cpu 4 --page 0"
        )
        self.assertTrue(r5l.success, r5l.error)
        r5 = self.dispatcher.execute_line(
            "process_syscall --process SysApp --type memory_write --at-cpu 5 --page 1 --write"
        )
        self.assertTrue(r5.success, r5.error)

        r_run = self.dispatcher.execute_line("sched_run")
        self.assertTrue(r_run.success, r_run.error)
        self.assertEqual(self.dispatcher.execute_line("read_file /publico.txt").output, "atualizado")
        self.assertGreaterEqual(r_run.data["metrics"]["syscalls_total"], 8)

        # Immediate --now syscall (exit) terminates process cleanly
        self.assertTrue(
            self.dispatcher.execute_line("create_process --name ExitApp --size 4KB --burst 5").success
        )
        r_exit = self.dispatcher.execute_line("process_syscall --process ExitApp --type exit --now")
        self.assertTrue(r_exit.success, r_exit.error)
        self.assertTrue(r_exit.data["terminated"])
        self.assertEqual(self.kernel.process_manager.get_process("ExitApp").state, ProcessState.TERMINATED)

        # FS ACL denial when non-root schedules fs_read on root-only file
        self.assertTrue(self.dispatcher.execute_line('write_file /secreto.txt "topsecret"').success)
        self.assertTrue(self.dispatcher.execute_line("chmod 600 /secreto.txt").success)
        self.assertTrue(
            self.dispatcher.execute_line("useradd bob --group users --password BobStrongPass1!").success
        )
        self.assertTrue(
            self.dispatcher.execute_line("login --user bob --password BobStrongPass1!").success
        )
        self.assertTrue(
            self.dispatcher.execute_line("create_process --name BobApp --size 4KB --burst 3").success
        )
        self.assertTrue(
            self.dispatcher.execute_line(
                "process_syscall --process BobApp --type fs_read --at-cpu 1 --duration 2 --path /secreto.txt"
            ).success
        )
        r_acl = self.dispatcher.execute_line("sched_run")
        self.assertFalse(r_acl.success)
        self.assertIn("[NEGADO]", r_acl.error)
        self.assertIn("permissão de leitura", r_acl.error)

    def test_seeded_random_io_reproducibility_and_sim_reset(self):
        """Test seeded random I/O determinism via CLI and full reset via sim_reset."""
        def run_with_seed(seed: int):
            self.assertTrue(self.dispatcher.execute_line("sim_reset").success)
            self.assertTrue(self.dispatcher.execute_line(f"sched_config --quantum 4 --seed {seed}").success)
            self.assertTrue(
                self.dispatcher.execute_line(
                    f"create_process --name RndA --size 4KB --priority 2 --burst 10 --io-profile random --seed {seed}"
                ).success
            )
            self.assertTrue(
                self.dispatcher.execute_line(
                    f"create_process --name RndB --size 4KB --priority 2 --burst 10 --io-profile random --seed {seed}"
                ).success
            )
            r_run = self.dispatcher.execute_line("sched_run")
            self.assertTrue(r_run.success, r_run.error)
            r_tl = self.dispatcher.execute_line("sim_timeline --gantt")
            self.assertTrue(r_tl.success)
            return r_run.data["metrics"], r_tl.data["gantt"]

        m1, g1 = run_with_seed(123)
        m2, g2 = run_with_seed(123)
        m3, g3 = run_with_seed(999)

        self.assertEqual(m1, m2)
        self.assertEqual(g1, g2)
        # Different seeds should produce different timing or Gantt slices
        self.assertTrue(m1 != m3 or g1 != g3)

        # Reset leaves clock=0 and only Nucleo_Base
        r_rst = self.dispatcher.execute_line("sim_reset")
        self.assertTrue(r_rst.success)
        self.assertEqual(r_rst.data["clock_ms"], 0)
        self.assertEqual(r_rst.data["processes_count"], 1)

    def test_memory_frames_live_sync_paging_and_metrics(self):
        """Test --pages pattern, real Stage 4 frame occupation, memory_frames, and cleanup."""
        kernel = SimulationKernel(dynamic_frames=2, block_size=4096, quantum_ms=4)
        dispatcher = CommandDispatcher(kernel)

        r_c = dispatcher.execute_line(
            "create_process --name MemCLI --size 16KB --type normal --burst 6 --pages 0,1,0:w,2,3,0"
        )
        self.assertTrue(r_c.success, r_c.error)

        # Step 3ms -> p0 fault, p1 fault, p0 write hit (dirty=True)
        r_s1 = dispatcher.execute_line("sched_step --ms 3")
        self.assertTrue(r_s1.success, r_s1.error)

        r_mf1 = dispatcher.execute_line("memory_frames")
        self.assertTrue(r_mf1.success, r_mf1.error)
        self.assertEqual(r_mf1.data["occupied_count"], 2)
        self.assertIn("OCUPADA", r_mf1.output)
        self.assertIn("HIT", r_mf1.output)
        self.assertIn("PAGE_FAULT", r_mf1.output)
        self.assertIn("Sim", r_mf1.output)

        # Complete execution -> frames freed automatically
        r_run = dispatcher.execute_line("sched_run")
        self.assertTrue(r_run.success, r_run.error)

        r_mf2 = dispatcher.execute_line("memory_frames")
        self.assertTrue(r_mf2.success)
        self.assertEqual(r_mf2.data["occupied_count"], 0)
        self.assertIn("LIVRE", r_mf2.output)

        r_met = dispatcher.execute_line("sim_metrics")
        self.assertTrue(r_met.success)
        self.assertIn("RELATÓRIO DE MÉTRICAS DE EXECUÇÃO E ESCALONAMENTO", r_met.output)
        self.assertGreater(r_met.data["page_faults_total"], 0)
        self.assertGreater(r_met.data["page_hits_total"], 0)

    def test_mutex_buffer_video_manual_lock_unlock_and_terminate_cleanup(self):
        """Test mutex_demo Buffer_Video plus manual mutex_create/lock/unlock/status and terminate cleanup."""
        r_demo = self.dispatcher.execute_line("mutex_demo --scenario buffer_video --quantum 2")
        self.assertTrue(r_demo.success, r_demo.error)
        self.assertTrue(r_demo.data["critical_sections_disjoint"])
        self.assertEqual(r_demo.data["mutex"]["name"], "Buffer_Video")
        self.assertFalse(r_demo.data["mutex"]["locked"])
        self.assertGreaterEqual(r_demo.data["mutex"]["contention_count"], 1)
        self.assertIn("Exclusão Mútua       : SIM", r_demo.output)

        # Manual mutex_create / mutex_lock / contention / mutex_unlock / terminate_process
        self.assertTrue(self.dispatcher.execute_line("sim_reset").success)
        self.assertTrue(self.dispatcher.execute_line("mutex_create --name RecursoA").success)
        self.assertTrue(
            self.dispatcher.execute_line("create_process --name Holder --size 4KB --burst 5").success
        )
        self.assertTrue(
            self.dispatcher.execute_line("create_process --name Waiter --size 4KB --burst 5").success
        )

        r_l1 = self.dispatcher.execute_line("mutex_lock --mutex RecursoA --process Holder")
        self.assertTrue(r_l1.success, r_l1.error)
        self.assertTrue(r_l1.data["acquired"])

        r_l2 = self.dispatcher.execute_line("mutex_lock --mutex RecursoA --process Waiter")
        self.assertTrue(r_l2.success, r_l2.error)
        self.assertFalse(r_l2.data["acquired"])
        self.assertTrue(r_l2.data["blocked"])

        r_ms = self.dispatcher.execute_line("mutex_status")
        self.assertTrue(r_ms.success)
        self.assertIn("TRAVADO", r_ms.output)
        self.assertIn("RecursoA", r_ms.output)

        # Terminate Holder -> releases RecursoA and wakes Waiter (BLOCKED -> READY)
        r_term = self.dispatcher.execute_line("terminate_process --name Holder")
        self.assertTrue(r_term.success, r_term.error)
        self.assertEqual(self.kernel.process_manager.get_process("Waiter").state, ProcessState.READY)

        # Waiter now owns RecursoA and can unlock it cleanly
        r_ul = self.dispatcher.execute_line("mutex_unlock --mutex RecursoA --process Waiter")
        self.assertTrue(r_ul.success, r_ul.error)
        self.assertFalse(r_ul.data["mutex"]["locked"])

    def test_deadlock_detection_and_stall_diagnostics_via_cli(self):
        """Test Wait-For deadlock in mutex_lock, sched_run, deadlock_check, and stall detection."""
        self.assertTrue(self.dispatcher.execute_line("mutex_create M1").success)
        self.assertTrue(self.dispatcher.execute_line("mutex_create M2").success)
        self.assertTrue(self.dispatcher.execute_line("create_process --name P1 --size 4KB --burst 6").success)
        self.assertTrue(self.dispatcher.execute_line("create_process --name P2 --size 4KB --burst 6").success)

        # Healthy check initially
        r_dc0 = self.dispatcher.execute_line("deadlock_check")
        self.assertTrue(r_dc0.success)
        self.assertFalse(r_dc0.data["deadlock_detected"])
        self.assertIn("SAUDÁVEL", r_dc0.output)

        # Build cycle via mutex_lock: P1 holds M1, P2 holds M2, P1 waits M2, P2 tries M1 -> DEADLOCK
        self.assertTrue(self.dispatcher.execute_line("mutex_lock --mutex M1 --process P1").success)
        self.assertTrue(self.dispatcher.execute_line("mutex_lock --mutex M2 --process P2").success)
        r_block_p1 = self.dispatcher.execute_line("mutex_lock --mutex M2 --process P1")
        self.assertTrue(r_block_p1.success)
        self.assertTrue(r_block_p1.data["blocked"])

        r_dl = self.dispatcher.execute_line("mutex_lock --mutex M1 --process P2")
        self.assertFalse(r_dl.success)
        self.assertTrue(r_dl.data.get("deadlock"))
        self.assertIn("DEADLOCK", r_dl.error)

        # deadlock_check reports cycle
        r_dc1 = self.dispatcher.execute_line("deadlock_check")
        self.assertTrue(r_dc1.success)
        self.assertTrue(r_dc1.data["deadlock_detected"])
        self.assertGreaterEqual(len(r_dc1.data["cycles"]), 1)
        self.assertIn("DEADLOCK DETECTADO", r_dc1.output)

        # sched_run also catches DeadlockDetectedException cleanly with data["deadlock"]=True
        r_run_dl = self.dispatcher.execute_line("sched_run")
        self.assertFalse(r_run_dl.success)
        self.assertTrue(r_run_dl.data.get("deadlock"))

        # Test scheduled deadlock via sched_run
        self.assertTrue(self.dispatcher.execute_line("sim_reset").success)
        self.assertTrue(self.dispatcher.execute_line("sched_config --quantum 1").success)
        self.assertTrue(self.dispatcher.execute_line("mutex_create MA").success)
        self.assertTrue(self.dispatcher.execute_line("mutex_create MB").success)
        self.assertTrue(self.dispatcher.execute_line("create_process --name A --size 4KB --burst 5").success)
        self.assertTrue(self.dispatcher.execute_line("create_process --name B --size 4KB --burst 5").success)
        self.assertTrue(
            self.dispatcher.execute_line("process_syscall --process A --type mutex_lock --mutex MA --at-cpu 0").success
        )
        self.assertTrue(
            self.dispatcher.execute_line("process_syscall --process A --type mutex_lock --mutex MB --at-cpu 2").success
        )
        self.assertTrue(
            self.dispatcher.execute_line("process_syscall --process B --type mutex_lock --mutex MB --at-cpu 0").success
        )
        self.assertTrue(
            self.dispatcher.execute_line("process_syscall --process B --type mutex_lock --mutex MA --at-cpu 2").success
        )
        r_sched_dl = self.dispatcher.execute_line("sched_run")
        self.assertFalse(r_sched_dl.success)
        self.assertTrue(r_sched_dl.data.get("deadlock"))
        self.assertTrue(len(r_sched_dl.data.get("cycle", [])) >= 2)

        # Test SimulationStallException caught cleanly in sched_run
        self.assertTrue(self.dispatcher.execute_line("sim_reset").success)
        self.assertTrue(self.dispatcher.execute_line("create_process --name Stall --size 4KB --burst 4").success)
        self.assertTrue(
            self.dispatcher.execute_line(
                "process_syscall --process Stall --type io_read --at-cpu 1 --duration 10 --block 0"
            ).success
        )
        self.assertTrue(self.dispatcher.execute_line("sched_step --ms 1").success)
        self.kernel.event_manager.cancel_for_entity(
            pid=self.kernel.process_manager.get_process("Stall").pid
        )
        r_dc_stall = self.dispatcher.execute_line("deadlock_check")
        self.assertTrue(r_dc_stall.success)
        self.assertTrue(r_dc_stall.data["stalled"])
        self.assertIn("ESTAGNAÇÃO", r_dc_stall.output)

        r_run_stall = self.dispatcher.execute_line("sched_run")
        self.assertFalse(r_run_stall.success)
        self.assertTrue(r_run_stall.data.get("stall"))

    def test_metrics_timeline_gantt_help_and_error_validation(self):
        """Test sim_metrics, sim_timeline [--limit] [--gantt], help headers, and invalid flag validation."""
        self.assertTrue(
            self.dispatcher.execute_line("create_process --name M1 --size 4KB --priority 2 --burst 4").success
        )
        self.assertTrue(self.dispatcher.execute_line("sched_run").success)

        r_tl = self.dispatcher.execute_line("sim_timeline --limit 3")
        self.assertTrue(r_tl.success, r_tl.error)
        self.assertEqual(r_tl.data["count"], 3)
        self.assertIn("LINHA DO TEMPO DA SIMULAÇÃO", r_tl.output)

        r_gantt = self.dispatcher.execute_line("sim_timeline --limit 4 --gantt")
        self.assertTrue(r_gantt.success, r_gantt.error)
        self.assertIn("DIAGRAMA DE GANTT DA CPU", r_gantt.output)
        self.assertGreater(len(r_gantt.data["gantt"]), 0)

        r_help = self.dispatcher.execute_line("help")
        self.assertTrue(r_help.success)
        # Preserve Stage 1-4 headers
        for header in (
            "SISTEMA DE ARQUIVOS (ETAPA 1):",
            "GERENCIAMENTO DE E/S E ESCALONAMENTO (ETAPA 2):",
            "DISCO DE ESTADO SÓLIDO (SSD) E WEAR LEVELING (ETAPA 2):",
            "ARRANJOS RAID (ETAPA 2):",
            "SEGURANÇA E PROTEÇÃO (ETAPA 3):",
            "GERENCIAMENTO DE MEMÓRIA E PROCESSOS (ETAPA 4):",
            "PROCESSOS, THREADS, ESCALONAMENTO E CONCORRÊNCIA (ETAPA 5):",
        ):
            self.assertIn(header, r_help.output)
        for cmd_name in (
            "process_status",
            "process_admit",
            "thread_create",
            "thread_status",
            "sched_config",
            "sched_status",
            "sched_step",
            "sched_run",
            "process_syscall",
            "mutex_create",
            "mutex_lock",
            "mutex_unlock",
            "mutex_status",
            "mutex_demo",
            "deadlock_check",
            "memory_frames",
            "sim_metrics",
            "sim_timeline",
            "sim_reset",
        ):
            self.assertIn(cmd_name, r_help.output)

        # Comprehensive error validation checks
        invalid_commands = [
            "create_process --name BadPrio --size 4KB --priority 0",
            "create_process --name BadBurst --size 4KB --burst -1",
            "create_process --name BadArrival --size 4KB --arrival -3",
            "create_process --name BadProf --size 4KB --io-profile bogus",
            "create_process --name BadPages --size 4KB --pages 0,-1",
            "create_process --name BadFlag --size 4KB --unknown-flag 1",
            "process_admit",
            "process_admit --process Inexistente",
            "thread_create --process M1",
            "thread_create --process Nucleo_Base --name t1 --burst 2",
            "sched_config --algorithm fifo",
            "sched_config --quantum 0",
            "sched_config --seed nao_int",
            "sched_step --ms -2",
            "sched_run --until-event EVENTO_INVALIDO",
            "process_syscall --process M1 --type invalid_sys",
            "process_syscall --process M1 --type yield --now --at-cpu 0",
            "process_syscall --process M1 --type fs_read --now",
            "process_syscall --process M1 --type mutex_lock --now",
            "mutex_create",
            "mutex_lock --mutex NaoExiste --process M1",
            "mutex_unlock --mutex NaoExiste --process M1",
            "mutex_demo --scenario desconhecido",
            "mutex_demo --quantum 0",
            "sim_timeline --limit -1",
        ]
        for bad in invalid_commands:
            res = self.dispatcher.execute_line(bad)
            self.assertFalse(res.success, f"Esperava falha para comando inválido: {bad}")
            self.assertTrue(bool(res.error), f"Esperava mensagem de erro para: {bad}")


if __name__ == "__main__":
    unittest.main()
