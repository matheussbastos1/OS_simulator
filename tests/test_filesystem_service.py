"""Unit and integration tests for FileSystemService (Incremento 4 - FS-001, FS-002)."""

import unittest

from os_simulator.core.exceptions import DiskFullException, FileNotFoundException
from os_simulator.core.types import AllocationStrategy, NodeType
from os_simulator.filesystem.service import FileSystemService
from os_simulator.storage.memory_block_device import InMemoryBlockDevice


class TestFileSystemService(unittest.TestCase):
    """Test suite for FileSystemService, fragmentation, and Ground Truth scenarios."""

    def setUp(self):
        # 16 blocks of 4096 bytes = 65,536 bytes
        self.device = InMemoryBlockDevice(capacity=16, block_size=4096)
        self.service = FileSystemService(
            block_device=self.device,
            default_strategy=AllocationStrategy.INDEXED,
        )

    def test_scenario_fs_001_hierarchy(self):
        """Scenario FS-001: Create /sistema, /sistema/logs, /sistema/logs/app.log and inspect tree."""
        dir_sistema = self.service.mkdir("/sistema")
        dir_logs = self.service.mkdir("/sistema/logs")
        file_app = self.service.create_file("/sistema/logs/app.log", size_bytes=10240)

        self.assertTrue(self.service.vfs.exists("/sistema"))
        self.assertTrue(self.service.vfs.exists("/sistema/logs"))
        self.assertTrue(self.service.vfs.exists("/sistema/logs/app.log"))

        tree_str = self.service.get_tree_string()
        expected_lines = [
            "[ÁRVORE DO SISTEMA DE ARQUIVOS]",
            "/",
            "└── sistema/ [DIR]",
            "    └── logs/ [DIR]",
            "        └── app.log (10 KB) [ARQ]",
        ]
        self.assertEqual(tree_str, "\n".join(expected_lines))

    def test_scenario_fs_002_internal_fragmentation(self):
        """Scenario FS-002: 10 KB file in 4 KB blocks:
        - Real size: 10,240 bytes
        - Blocks needed: 3 data blocks
        - Index blocks needed: 1 block
        - Allocated data space: 12,288 bytes
        - Internal fragmentation: 2,048 bytes
        - External fragmentation: 0 bytes
        """
        self.service.mkdir("/sistema")
        self.service.mkdir("/sistema/logs")

        payload = "A" * 10240  # Exactly 10,240 bytes
        result = self.service.write_file("/sistema/logs/app.log", payload)

        self.assertEqual(result["real_size"], 10240)
        self.assertEqual(len(result["allocated_blocks"]), 3)
        self.assertIsNotNone(result["index_block_id"])
        self.assertEqual(result["allocated_capacity"], 12288)
        self.assertEqual(result["internal_fragmentation"], 2048)
        self.assertEqual(result["external_fragmentation"], 0)

        # Status check
        status = self.service.get_fs_status(details=True)
        self.assertEqual(status["data_blocks_count"], 3)
        self.assertEqual(status["index_blocks_count"], 1)
        self.assertEqual(status["occupied_blocks"], 4)
        self.assertEqual(status["free_blocks"], 12)  # 16 - 4 = 12
        self.assertEqual(status["data_space_used"], 10240)
        self.assertEqual(status["metadata_overhead"], 4096)
        self.assertEqual(status["internal_fragmentation"], 2048)

    def test_read_and_write_content_integrity(self):
        self.service.mkdir("/dados")
        text = "Linha 1: Registro de simulação.\nLinha 2: Mais dados."
        self.service.write_file("/dados/info.txt", text)

        read_content = self.service.read_file("/dados/info.txt")
        self.assertEqual(read_content, text)

        # Append
        extra = "\nLinha 3: Apêndice."
        self.service.write_file("/dados/info.txt", extra, append=True)
        self.assertEqual(self.service.read_file("/dados/info.txt"), text + extra)

    def test_delete_frees_blocks_and_inodes(self):
        self.service.mkdir("/dados")
        initial_free_blocks = self.device.get_free_count()
        initial_free_inodes = len(self.service.inode_table)

        self.service.write_file("/dados/temp.dat", "X" * 8192)  # 2 data blocks + 1 index block = 3 blocks
        self.assertEqual(self.device.get_free_count(), initial_free_blocks - 3)
        self.assertEqual(len(self.service.inode_table), initial_free_inodes + 1)

        self.service.delete_file("/dados/temp.dat")
        self.assertEqual(self.device.get_free_count(), initial_free_blocks)
        self.assertEqual(len(self.service.inode_table), initial_free_inodes)

    def test_formatted_report_output(self):
        self.service.mkdir("/sistema")
        self.service.write_file("/sistema/teste.txt", "Dados")
        report = self.service.format_fs_status(details=True)
        self.assertIn("DIAGNÓSTICO DO SISTEMA DE ARQUIVOS", report)
        self.assertIn("INDEXADA (i-node)", report)
        self.assertIn("MAPA DE OCUPAÇÃO DOS BLOCOS", report)
        self.assertIn("[00:I]", report)
        self.assertIn("[01:D]", report)
        self.assertIn("Legenda: . = Livre, D = Dados, I = Índice, X = Danificado", report)


if __name__ == "__main__":
    unittest.main()
