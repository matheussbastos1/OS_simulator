"""Tests for CLI I/O, SSD, and RAID commands (Incremento 6)."""

import unittest

from os_simulator.cli.commands import CommandDispatcher
from os_simulator.core.simulation_kernel import SimulationKernel
from os_simulator.io.ssd import WearLevelingMode
from os_simulator.storage.raid import RAIDLevel, RAIDStatus


class TestCLIIOCommands(unittest.TestCase):
    """Test suite for CLI dispatching of IO, SSD, and RAID commands."""

    def setUp(self):
        self.kernel = SimulationKernel()
        self.dispatcher = CommandDispatcher(self.kernel)

    def test_io_status(self):
        res = self.dispatcher.execute_line("io_status")
        self.assertTrue(res.success)
        self.assertIn("DIAGNÓSTICO DO SUBSISTEMA DE E/S", res.output)
        self.assertIn("Trilha 53", res.output)
        self.assertIn("Escalonador Ativo", res.output)

    def test_io_scheduler_query_and_set(self):
        # Query current
        r1 = self.dispatcher.execute_line("io_scheduler")
        self.assertTrue(r1.success)
        self.assertIn("SSTF", r1.output)

        # Switch to SCAN
        r2 = self.dispatcher.execute_line("io_scheduler --set scan")
        self.assertTrue(r2.success)
        self.assertIn("alterado com sucesso para: SCAN", r2.output)

        # Query again
        r3 = self.dispatcher.execute_line("io_scheduler")
        self.assertTrue(r3.success)
        self.assertIn("SCAN", r3.output)

        # Switch to C-SCAN
        r4 = self.dispatcher.execute_line("io_scheduler cscan")
        self.assertTrue(r4.success)
        self.assertIn("CSCAN", r4.output)

        # Switch to invalid
        r_inv = self.dispatcher.execute_line("io_scheduler --set algoritmo_invalido")
        self.assertFalse(r_inv.success)
        self.assertIn("Algoritmo de escalonamento inválido", r_inv.error)

    def test_io_benchmark_single_sstf(self):
        """Ground truth scenario IO-001: [98, 183, 37, 122, 14] starting at 53 -> 208 tracks."""
        cmd = "io_benchmark --algorithm sstf --queue 98,183,37,122,14 --head 53"
        res = self.dispatcher.execute_line(cmd)
        self.assertTrue(res.success)
        self.assertIn("208 trilhas", res.output)
        self.assertIn("37", res.output)

    def test_io_benchmark_comparative(self):
        cmd = "io_benchmark --queue 98,183,37,122,14 --head 53"
        res = self.dispatcher.execute_line(cmd)
        self.assertTrue(res.success)
        self.assertIn("BENCHMARK COMPARATIVO DE ESCALONAMENTO DE DISCO", res.output)
        self.assertIn("FCFS", res.output)
        self.assertIn("SSTF", res.output)
        self.assertIn("SCAN", res.output)
        self.assertIn("C-SCAN", res.output)
        self.assertIn("Melhor Desempenho", res.output)
        self.assertIn("SSTF", res.output)
        self.assertEqual(res.data["best"], "SSTF")
        self.assertEqual(res.data["best_distance"], 208)

    def test_ssd_status(self):
        # Query initial SSD status
        r1 = self.dispatcher.execute_line("ssd_status")
        self.assertTrue(r1.success)
        self.assertIn("DIAGNÓSTICO DE WEAR LEVELING DO SSD", r1.output)
        self.assertIn("DYNAMIC", r1.output)

        # Switch wear mode to STATIC
        r2 = self.dispatcher.execute_line("ssd_status --mode static")
        self.assertTrue(r2.success)
        self.assertIn("STATIC", r2.output)
        self.assertEqual(self.kernel.ssd_device.wear_mode, WearLevelingMode.STATIC)

    def test_raid_status_and_lifecycle(self):
        # 1. Initial status (OPTIMAL)
        r1 = self.dispatcher.execute_line("raid_status")
        self.assertTrue(r1.success)
        self.assertIn("DIAGNÓSTICO DO ARRANJO RAID 5", r1.output)
        self.assertIn("OPTIMAL", r1.output)

        # 2. Write file on healthy RAID
        self.dispatcher.execute_line("mkdir /dados")
        w1 = self.dispatcher.execute_line('write_file /dados/teste.txt "Conteudo Protegido por RAID 5"')
        self.assertTrue(w1.success)

        # 3. Inject disk failure
        r_fail = self.dispatcher.execute_line("raid_fail --disk 1")
        self.assertTrue(r_fail.success)
        self.assertIn("Falha física injetada", r_fail.output)
        self.assertIn("DEGRADED", r_fail.output)

        # 4. Read file on degraded array (on-the-fly XOR reconstruction!)
        r_read = self.dispatcher.execute_line("read_file /dados/teste.txt")
        self.assertTrue(r_read.success)
        self.assertEqual(r_read.output, "Conteudo Protegido por RAID 5")

        # 5. Rebuild disk 1
        r_reb = self.dispatcher.execute_line("raid_rebuild --disk 1")
        self.assertTrue(r_reb.success)
        self.assertIn("Reconstrução dos dados do Disco #01 concluída", r_reb.output)
        self.assertIn("OPTIMAL", r_reb.output)

        # 6. Verify raid_status is OPTIMAL again
        r_final = self.dispatcher.execute_line("raid_status")
        self.assertTrue(r_final.success)
        self.assertIn("OPTIMAL", r_final.output)

    def test_raid_init(self):
        # Initialize RAID 1 with 2 disks
        res = self.dispatcher.execute_line("raid_init --level 1 --disks 2 --capacity 8")
        self.assertTrue(res.success)
        self.assertIn("Arranjo RAID 1 inicializado com sucesso", res.output)

        status = self.dispatcher.execute_line("raid_status")
        self.assertTrue(status.success)
        self.assertIn("DIAGNÓSTICO DO ARRANJO RAID 1", status.output)

    def test_help_command_displays_all_categories(self):
        res = self.dispatcher.execute_line("help")
        self.assertTrue(res.success)
        self.assertIn("SISTEMA DE ARQUIVOS", res.output)
        self.assertIn("GERENCIAMENTO DE E/S", res.output)
        self.assertIn("DISCO DE ESTADO SÓLIDO (SSD)", res.output)
        self.assertIn("ARRANJOS RAID", res.output)

    def test_io_status_pending_queue_zero_after_operations(self):
        """Verify that io_status reports 0 pending requests after synchronous I/O operations (Hotfix item 2)."""
        self.dispatcher.execute_line('write_file /test_io.log "Payload de teste para io_status"')
        self.dispatcher.execute_line("read_file /test_io.log")

        res = self.dispatcher.execute_line("io_status")
        self.assertTrue(res.success)
        self.assertIn("Requisições Pendentes na Fila: 0", res.output)
        self.assertEqual(res.data["pending_queue_size"], 0)
        self.assertGreater(res.data["total_requests"], 0)


if __name__ == "__main__":
    unittest.main()
