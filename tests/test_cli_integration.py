"""Integration tests for CLI commands and shell dispatcher (Incremento 5)."""

import unittest

from os_simulator.cli.commands import CommandDispatcher, parse_size_string
from os_simulator.core.simulation_kernel import SimulationKernel


class TestCLIIntegration(unittest.TestCase):
    """Test suite for CLI dispatch, commands, and interactive formatting."""

    def setUp(self):
        self.kernel = SimulationKernel(disk_capacity=16, block_size=4096)
        self.dispatcher = CommandDispatcher(self.kernel)

    def test_parse_size_string(self):
        self.assertEqual(parse_size_string("10KB"), 10240)
        self.assertEqual(parse_size_string("512B"), 512)
        self.assertEqual(parse_size_string("1MB"), 1048576)
        self.assertEqual(parse_size_string("2048"), 2048)
        with self.assertRaises(ValueError):
            parse_size_string("invalido")

    def test_official_professor_sequence(self):
        """Execute the exact official sequence:
        > mkdir /sistema
        > mkdir /sistema/logs
        > create /sistema/logs/app.log --size 10KB
        > write_file /sistema/logs/app.log "Novo Registro"
        > fs_status --details
        > read_file /sistema/logs/app.log
        """
        # 1. mkdir /sistema
        r1 = self.dispatcher.execute_line("mkdir /sistema")
        self.assertTrue(r1.success)
        self.assertIn("criado com sucesso", r1.output)

        # 2. mkdir /sistema/logs
        r2 = self.dispatcher.execute_line("mkdir /sistema/logs")
        self.assertTrue(r2.success)

        # 3. create /sistema/logs/app.log --size 10KB
        r3 = self.dispatcher.execute_line("create /sistema/logs/app.log --size 10KB")
        self.assertTrue(r3.success)
        self.assertIn("10240 bytes", r3.output)

        # 4. Tree verification
        r_tree = self.dispatcher.execute_line("tree")
        self.assertTrue(r_tree.success)
        expected_tree = (
            "[ÁRVORE DO SISTEMA DE ARQUIVOS]\n"
            "/\n"
            "└── sistema/ [DIR]\n"
            "    └── logs/ [DIR]\n"
            "        └── app.log (10 KB) [ARQ]"
        )
        self.assertEqual(r_tree.output, expected_tree)

        # 5. write_file /sistema/logs/app.log "Novo Registro"
        r4 = self.dispatcher.execute_line('write_file /sistema/logs/app.log "Novo Registro"')
        self.assertTrue(r4.success)
        self.assertIn("Arquivo gravado com sucesso", r4.output)
        self.assertIn("Fragmentação Interna", r4.output)

        # 6. read_file /sistema/logs/app.log
        r5 = self.dispatcher.execute_line("read_file /sistema/logs/app.log")
        self.assertTrue(r5.success)
        self.assertEqual(r5.output, "Novo Registro")

        # 7. fs_status --details
        r6 = self.dispatcher.execute_line("fs_status --details")
        self.assertTrue(r6.success)
        self.assertIn("DIAGNÓSTICO DO SISTEMA DE ARQUIVOS", r6.output)
        self.assertIn("MAPA DE OCUPAÇÃO DOS BLOCOS", r6.output)

    def test_navigation_and_deletions(self):
        self.dispatcher.execute_line("mkdir /docs")
        self.dispatcher.execute_line('write_file /docs/nota.txt "Texto"')

        # cd /docs
        r_cd = self.dispatcher.execute_line("cd /docs")
        self.assertTrue(r_cd.success)
        self.assertEqual(self.kernel.get_cwd(), "/docs")

        # pwd
        r_pwd = self.dispatcher.execute_line("pwd")
        self.assertEqual(r_pwd.output, "/docs")

        # ls
        r_ls = self.dispatcher.execute_line("ls")
        self.assertIn("nota.txt", r_ls.output)

        # delete_file nota.txt (relative path)
        r_del = self.dispatcher.execute_line("delete_file nota.txt")
        self.assertTrue(r_del.success)

        # cd /
        self.dispatcher.execute_line("cd /")
        # delete_directory /docs
        r_del_dir = self.dispatcher.execute_line("delete_directory /docs")
        self.assertTrue(r_del_dir.success)

    def test_error_handling(self):
        # File not found
        r_err = self.dispatcher.execute_line("read_file /inexistente.txt")
        self.assertFalse(r_err.success)
        self.assertIn("não encontrado", r_err.error)

        # Unknown command
        r_unknown = self.dispatcher.execute_line("comando_invalido")
        self.assertFalse(r_unknown.success)
        self.assertIn("não reconhecido", r_unknown.error)


if __name__ == "__main__":
    unittest.main()
