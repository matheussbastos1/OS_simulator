"""Unit tests for Virtual File System (VFS) and Node hierarchy (Incremento 1)."""

import unittest

from os_simulator.core.exceptions import (
    DirectoryNotEmptyException,
    FileAlreadyExistsException,
    FileNotFoundException,
    IsADirectoryException,
    NotADirectoryException,
)
from os_simulator.core.types import NodeType
from os_simulator.filesystem.node import DirectoryNode, FileNode
from os_simulator.filesystem.vfs import VirtualFileSystem


class DummyInode:
    """Mock Inode for testing tree formatting."""
    def __init__(self, file_size: int):
        self.file_size = file_size


class TestVirtualFileSystem(unittest.TestCase):
    """Test suite for VFS and Node hierarchy."""

    def setUp(self):
        self.vfs = VirtualFileSystem(root_inode_id=1)

    def test_root_initialization(self):
        self.assertEqual(self.vfs.root.name, "/")
        self.assertEqual(self.vfs.root.get_path(), "/")
        self.assertEqual(self.vfs.root.node_type, NodeType.DIRECTORY)
        self.assertTrue(self.vfs.root.is_empty())

    def test_path_normalization(self):
        self.assertEqual(self.vfs.normalize_path("/"), "/")
        self.assertEqual(self.vfs.normalize_path("/sistema/logs/"), "/sistema/logs")
        self.assertEqual(self.vfs.normalize_path("logs", cwd="/sistema"), "/sistema/logs")
        self.assertEqual(self.vfs.normalize_path("../sistema/logs", cwd="/var"), "/sistema/logs")
        self.assertEqual(self.vfs.normalize_path("///sistema///logs/../logs//app.log"), "/sistema/logs/app.log")

    def test_mkdir_and_create_file(self):
        dir_sistema = self.vfs.mkdir("/sistema", inode_id=2)
        self.assertEqual(dir_sistema.name, "sistema")
        self.assertEqual(dir_sistema.get_path(), "/sistema")

        dir_logs = self.vfs.mkdir("/sistema/logs", inode_id=3)
        self.assertEqual(dir_logs.get_path(), "/sistema/logs")

        file_app = self.vfs.create_file("/sistema/logs/app.log", inode_id=4)
        self.assertEqual(file_app.name, "app.log")
        self.assertEqual(file_app.get_path(), "/sistema/logs/app.log")

        # Verify lookup
        self.assertIs(self.vfs.get_node("/sistema/logs/app.log"), file_app)
        self.assertIs(self.vfs.get_node("app.log", cwd="/sistema/logs"), file_app)
        self.assertIs(self.vfs.get_file("/sistema/logs/app.log"), file_app)
        self.assertIs(self.vfs.get_directory("/sistema/logs"), dir_logs)

    def test_duplicate_prevention(self):
        self.vfs.mkdir("/sistema", inode_id=2)
        with self.assertRaises(FileAlreadyExistsException):
            self.vfs.mkdir("/sistema", inode_id=3)

        self.vfs.create_file("/sistema/file.txt", inode_id=4)
        with self.assertRaises(FileAlreadyExistsException):
            self.vfs.create_file("/sistema/file.txt", inode_id=5)

    def test_non_existent_parent(self):
        with self.assertRaises(FileNotFoundException):
            self.vfs.mkdir("/nao/existe/pasta", inode_id=10)

        with self.assertRaises(FileNotFoundException):
            self.vfs.create_file("/nao/existe/arq.txt", inode_id=11)

    def test_file_as_parent_error(self):
        self.vfs.create_file("/arquivo.txt", inode_id=2)
        with self.assertRaises(NotADirectoryException):
            self.vfs.mkdir("/arquivo.txt/subpasta", inode_id=3)

    def test_delete_file_and_directory(self):
        self.vfs.mkdir("/sistema", inode_id=2)
        self.vfs.mkdir("/sistema/logs", inode_id=3)
        self.vfs.create_file("/sistema/logs/app.log", inode_id=4)

        # Deleting non-empty dir raises DirectoryNotEmptyException
        with self.assertRaises(DirectoryNotEmptyException):
            self.vfs.delete_directory("/sistema/logs")

        # Delete file
        freed_inode = self.vfs.delete_file("/sistema/logs/app.log")
        self.assertEqual(freed_inode, 4)
        self.assertFalse(self.vfs.exists("/sistema/logs/app.log"))

        # Now delete empty directory
        freed_dir_inode = self.vfs.delete_directory("/sistema/logs")
        self.assertEqual(freed_dir_inode, 3)
        self.assertFalse(self.vfs.exists("/sistema/logs"))

    def test_academic_tree_formatting(self):
        """Validates reproduction of professor's Example 1.1 tree output."""
        self.vfs.mkdir("/sistema", inode_id=2)
        self.vfs.mkdir("/sistema/logs", inode_id=3)
        self.vfs.create_file("/sistema/logs/app.log", inode_id=4)

        mock_inode_table = {4: DummyInode(file_size=10240)}
        tree_output = self.vfs.root.format_tree(inode_table=mock_inode_table)

        expected_lines = [
            "[ÁRVORE DO SISTEMA DE ARQUIVOS]",
            "/",
            "└── sistema/ [DIR]",
            "    └── logs/ [DIR]",
            "        └── app.log (10 KB) [ARQ]"
        ]
        expected_output = "\n".join(expected_lines)
        self.assertEqual(tree_output, expected_output)


if __name__ == "__main__":
    unittest.main()
