"""CLI integration tests for Etapa 4 - Memory Management and Process Lifecycle."""

import unittest

from os_simulator.cli.commands import CommandDispatcher
from os_simulator.core.simulation_kernel import SimulationKernel
from os_simulator.core.types import PrivilegeMode


class TestCLIMemoryCommands(unittest.TestCase):
    """Test CLI commands for Memory Management and Ground Truth scenarios."""

    def setUp(self):
        self.kernel = SimulationKernel()
        self.dispatcher = CommandDispatcher(self.kernel)

    def test_cli_mem_001_and_mem_002_reserved_and_compact(self):
        """Scenarios MEM-001 and MEM-002 executed via CLI."""
        # MEM-001: Create critical processes
        r1 = self.dispatcher.execute_line('create_process --name "Kernel_DiskDriver" --size 512KB --type critical')
        self.assertTrue(r1.success, r1.error)
        self.assertIn("1024 - 1535 KB", r1.output)

        r2 = self.dispatcher.execute_line('create_process --name "Kernel_NetDriver" --size 1024KB --type critical')
        self.assertTrue(r2.success, r2.error)
        self.assertIn("1536 - 2559 KB", r2.output)

        r3 = self.dispatcher.execute_line('create_process --name "Kernel_CryptoEngine" --size 512KB --type critical')
        self.assertTrue(r3.success, r3.error)
        self.assertIn("2560 - 3071 KB", r3.output)

        # Terminate intermediate driver
        r4 = self.dispatcher.execute_line('terminate_process --name "Kernel_NetDriver"')
        self.assertTrue(r4.success, r4.error)

        # Check status: 2048 KB free, 1024 KB max contiguous, 1024 KB external fragmentation
        r5 = self.dispatcher.execute_line("memory_status --reserved")
        self.assertTrue(r5.success, r5.error)
        self.assertIn("Espaço Livre Total          : 2.048 KB", r5.output)
        self.assertIn("Maior Bloco Livre Contíguo  : 1.024 KB", r5.output)
        self.assertIn("Fragmentação Externa        : 1.024 KB", r5.output)

        # Attempt to allocate 1536 KB: fails due to external fragmentation
        r6 = self.dispatcher.execute_line('create_process --name "Kernel_BigService" --size 1536KB --type critical')
        self.assertFalse(r6.success)
        self.assertIn("fragmentação externa", r6.error.lower())

        # MEM-002: Sliding compaction
        r7 = self.dispatcher.execute_line("memory_compact --reserved")
        self.assertTrue(r7.success, r7.error)
        self.assertIn("Fragmentação Externa        : 0 KB", r7.output)
        self.assertIn("Capacidade máxima contígua: 2.048 KB", r7.output)
        self.assertIn("1536 - 2047 KB", r7.output)  # Kernel_CryptoEngine moved here
        self.assertIn("2048 - 4095 KB", r7.output)  # Consolidated free block

        # Post-compaction: 1536 KB allocation now succeeds!
        r8 = self.dispatcher.execute_line('create_process --name "Kernel_BigService" --size 1536KB --type critical')
        self.assertTrue(r8.success, r8.error)
        self.assertIn("2048 - 3583 KB", r8.output)

    def test_cli_mem_003_normal_process_and_page_table(self):
        """Scenario MEM-003: create_process --name App_Navegador --size 10KB --type normal."""
        r1 = self.dispatcher.execute_line('create_process --name "App_Navegador" --size 10KB --type normal')
        self.assertTrue(r1.success, r1.error)
        self.assertIn("3 páginas", r1.output)
        self.assertIn("2048 bytes", r1.output)

        r2 = self.dispatcher.execute_line('page_table --process "App_Navegador"')
        self.assertTrue(r2.success, r2.error)
        self.assertIn("Fragmentação Interna : 2048 bytes", r2.output)
        self.assertIn("Total de Páginas     : 3 páginas", r2.output)

    def test_cli_mem_004a_and_mem_004b_translate_address(self):
        """Scenarios MEM-004A and MEM-004B via CLI."""
        r_create = self.dispatcher.execute_line('create_process --name "App_Navegador" --size 10KB --type normal')
        self.assertTrue(r_create.success)

        proc = self.kernel.process_manager.get_process("App_Navegador")
        pt = proc.page_table

        # Scenario MEM-004A: Page 1 mapped to Frame 12
        pt.entries[1].present = True
        pt.entries[1].frame_id = 12

        r_trans_a = self.dispatcher.execute_line('translate_address --process App_Navegador --page 1')
        self.assertTrue(r_trans_a.success, r_trans_a.error)
        self.assertIn("Moldura Física      : 12", r_trans_a.output)
        self.assertIn("Endereço Base Físico: 49152", r_trans_a.output)

        # Scenario MEM-004B: Page 1 mapped to Frame 5, address 4100
        pt.entries[1].frame_id = 5
        r_trans_b = self.dispatcher.execute_line(f'translate_address --pid {proc.pid} --address 4100')
        self.assertTrue(r_trans_b.success, r_trans_b.error)
        self.assertIn("Página Lógica (p): 1", r_trans_b.output)
        self.assertIn("Deslocamento (d) : 4", r_trans_b.output)
        self.assertIn("Moldura Física (f): 5", r_trans_b.output)
        self.assertIn("Endereço Físico  : 20484", r_trans_b.output)

    def test_cli_mem_005_deterministic_execute_step_cycle(self):
        """Scenario MEM-005 via CLI."""
        # Configure kernel with 2 dynamic frames for replacement
        kernel = SimulationKernel(dynamic_frames=2)
        dispatcher = CommandDispatcher(kernel)

        r_create = dispatcher.execute_line('create_process --name "App_Navegador" --size 16KB --type normal')
        self.assertTrue(r_create.success)

        proc = kernel.process_manager.get_process("App_Navegador")
        pt = proc.page_table

        # Setup initial state: Frame 0 with Page 0 (t=100), Frame 1 with Page 1 (t=200)
        kernel.memory_manager.physical_memory.allocate_frame(0, proc.pid, 0)
        e0 = pt.get_entry(0)
        e0.present = True
        e0.frame_id = 0
        e0.last_access = 100.0
        e0.dirty = False

        kernel.memory_manager.physical_memory.allocate_frame(1, proc.pid, 1)
        e1 = pt.get_entry(1)
        e1.present = True
        e1.frame_id = 1
        e1.last_access = 200.0
        e1.dirty = False

        # Phase A: LOAD_DATA Página 2 -> Page Fault, clean Page 0 discarded without swap
        r_step_a = dispatcher.execute_line('execute_step --process App_Navegador --instruction "LOAD_DATA Página 2"')
        self.assertTrue(r_step_a.success, r_step_a.error)
        self.assertIn("Falta de Página: SIM", r_step_a.output)
        self.assertIn("DISCARD", r_step_a.output)

        # Phase B: WRITE_DATA Página 2 -> sets dirty=True
        r_step_b1 = dispatcher.execute_line('execute_step --process App_Navegador --instruction "WRITE_DATA Página 2"')
        self.assertTrue(r_step_b1.success, r_step_b1.error)
        self.assertIn("ESCRITA (dirty=True)", r_step_b1.output)

        # Access Page 0 -> faults, Page 1 evicted
        r_step_b2 = dispatcher.execute_line('execute_step --process App_Navegador --instruction "LOAD_DATA Página 0"')
        self.assertTrue(r_step_b2.success, r_step_b2.error)

        # Access Page 3 -> faults, dirty Page 2 evicted to Swap!
        r_step_b3 = dispatcher.execute_line('execute_step --process App_Navegador --instruction "LOAD_DATA Página 3"')
        self.assertTrue(r_step_b3.success, r_step_b3.error)
        self.assertIn("SWAP_OUT", r_step_b3.output)

        # Phase C: Swap-In deterministic
        r_step_c = dispatcher.execute_line('execute_step --process App_Navegador --instruction "LOAD_DATA Página 2"')
        self.assertTrue(r_step_c.success, r_step_c.error)
        self.assertIn("SWAP_STORAGE", r_step_c.output)

    def test_cli_page_replacement_switch_and_memory_map(self):
        """Test page_replacement and memory_map commands."""
        r1 = self.dispatcher.execute_line("page_replacement")
        self.assertTrue(r1.success)
        self.assertIn("LRU", r1.output)

        r2 = self.dispatcher.execute_line("page_replacement --algorithm second_chance")
        self.assertTrue(r2.success)
        self.assertIn("SECOND_CHANCE", r2.output)

        r3 = self.dispatcher.execute_line("memory_map")
        self.assertTrue(r3.success)
        self.assertIn("ÁREA RESERVADA CONTÍGUA", r3.output)
        self.assertIn("ÁREA DINÂMICA PAGINADA", r3.output)

    def test_non_root_cannot_create_critical_process(self):
        """Verify privilege enforcement for critical processes."""
        # Switch to normal user context
        self.kernel.context.user_id = 1000
        self.kernel.context.username = "carlos"
        self.kernel.context.groups = ["devs"]
        self.kernel.context.privilege_mode = PrivilegeMode.USER_MODE
        r = self.dispatcher.execute_line('create_process --name "Kernel_Fake" --size 512KB --type critical')
        self.assertFalse(r.success)
        self.assertIn("Acesso negado", r.error)

    def test_non_root_cannot_compact_reserved_memory(self):
        """Verify privilege enforcement for memory compaction."""
        self.kernel.context.user_id = 1000
        self.kernel.context.username = "carlos"
        self.kernel.context.groups = ["devs"]
        self.kernel.context.privilege_mode = PrivilegeMode.USER_MODE
        r = self.dispatcher.execute_line("memory_compact --reserved")
        self.assertFalse(r.success)
        self.assertIn("Acesso negado", r.error)

    def test_non_root_cannot_terminate_critical_or_other_users_process(self):
        """Verify privilege enforcement for terminating critical or foreign processes."""
        # Create critical process as root
        r_create = self.dispatcher.execute_line('create_process --name "Kernel_SecDriver" --size 512KB --type critical')
        self.assertTrue(r_create.success)

        # Switch to carlos
        self.kernel.context.user_id = 1000
        self.kernel.context.username = "carlos"
        self.kernel.context.groups = ["devs"]
        self.kernel.context.privilege_mode = PrivilegeMode.USER_MODE

        # Carlos attempts to terminate critical driver -> blocked
        r_term_crit = self.dispatcher.execute_line('terminate_process --name "Kernel_SecDriver"')
        self.assertFalse(r_term_crit.success)
        self.assertIn("Acesso negado", r_term_crit.error)

        # Carlos attempts to terminate root-owned process -> blocked
        r_term_root = self.dispatcher.execute_line('terminate_process --name "Nucleo_Base"')
        self.assertFalse(r_term_root.success)
        self.assertIn("Acesso negado", r_term_root.error)

    def test_cannot_execute_or_translate_terminated_process(self):
        """Ensure terminated processes cannot execute instructions or leak physical memory."""
        r_create = self.dispatcher.execute_line('create_process --name "App_Dead" --size 4KB --type normal')
        self.assertTrue(r_create.success)

        r_step = self.dispatcher.execute_line('execute_step --process App_Dead --instruction "LOAD_DATA Página 0"')
        self.assertTrue(r_step.success)

        proc = self.kernel.process_manager.get_process("App_Dead")
        self.assertTrue(proc.page_table.entries[0].present)

        # Terminate
        r_term = self.dispatcher.execute_line('terminate_process --name App_Dead')
        self.assertTrue(r_term.success)

        # Page table entries must be invalidated
        self.assertFalse(proc.page_table.entries[0].present)
        self.assertIsNone(proc.page_table.entries[0].frame_id)

        # Translating or executing on terminated process must fail
        r_trans = self.dispatcher.execute_line('translate_address --process App_Dead --page 0')
        self.assertFalse(r_trans.success)
        self.assertIn("encerrado", r_trans.error)

        r_exec = self.dispatcher.execute_line('execute_step --process App_Dead --instruction "LOAD_DATA Página 0"')
        self.assertFalse(r_exec.success)
        self.assertIn("encerrado", r_exec.error)

    def test_audit_log_records_process_creation_and_termination(self):
        """Ensure process lifecycle is recorded in AuditLog."""
        r_create = self.dispatcher.execute_line('create_process --name "App_Audited" --size 4KB --type normal')
        self.assertTrue(r_create.success)

        r_term = self.dispatcher.execute_line('terminate_process --name "App_Audited"')
        self.assertTrue(r_term.success)

        events = self.kernel.audit_log.get_events()
        actions = [ev.action for ev in events]
        self.assertIn("CREATE_PROCESS", actions)
        self.assertIn("TERMINATE_PROCESS", actions)



if __name__ == "__main__":
    unittest.main()
