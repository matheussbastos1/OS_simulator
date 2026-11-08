"""Unit tests for Inode and InMemoryBlockDevice (Incremento 2)."""

import unittest

from os_simulator.core.exceptions import DiskFullException, InvalidBlockException
from os_simulator.core.types import AllocationStrategy, BlockStatus, NodeType
from os_simulator.filesystem.inode import Inode
from os_simulator.storage.block_device import DiskBlock
from os_simulator.storage.memory_block_device import InMemoryBlockDevice


class TestStorageAndInode(unittest.TestCase):
    """Test suite for block device and inode abstractions."""

    def test_default_device_capacity(self):
        device = InMemoryBlockDevice()
        self.assertEqual(device.get_capacity(), 16)
        self.assertEqual(device.get_block_size(), 4096)
        self.assertEqual(device.get_total_bytes(), 65536)
        self.assertEqual(device.get_free_count(), 16)
        self.assertEqual(device.get_used_count(), 0)

    def test_read_write_block(self):
        device = InMemoryBlockDevice(capacity=4, block_size=512)
        payload = b"Hello, OS Simulator Storage Layer!"
        device.write_block(0, payload, owner_inode=10)

        block = device.get_block(0)
        self.assertEqual(block.block_status, BlockStatus.ALLOCATED)
        self.assertEqual(block.owner_inode, 10)
        self.assertEqual(block.used_space, len(payload))
        self.assertEqual(device.read_block(0), payload)
        self.assertTrue(len(block.checksum) > 0)

    def test_invalid_block_access(self):
        device = InMemoryBlockDevice(capacity=4)
        with self.assertRaises(InvalidBlockException):
            device.read_block(4)
        with self.assertRaises(InvalidBlockException):
            device.write_block(-1, b"dados")

    def test_allocation_and_freeing(self):
        device = InMemoryBlockDevice(capacity=4)
        b0 = device.allocate_block(owner_inode=1)
        b1 = device.allocate_block(owner_inode=1)
        self.assertEqual(b0, 0)
        self.assertEqual(b1, 1)
        self.assertEqual(device.get_used_count(), 2)
        self.assertEqual(device.get_free_count(), 2)

        device.free_block(b0)
        self.assertEqual(device.get_free_count(), 3)
        self.assertEqual(device.get_block(b0).block_status, BlockStatus.FREE)

        # Allocate multiple
        allocated = device.allocate_blocks(3)
        self.assertEqual(len(allocated), 3)
        self.assertEqual(device.get_free_count(), 0)

        # Disk full
        with self.assertRaises(DiskFullException):
            device.allocate_block()

    def test_inode_internal_fragmentation(self):
        """Scenario FS-002 calculation verification."""
        inode = Inode(
            inode_id=5,
            node_type=NodeType.FILE,
            file_size=10240,
            allocation_strategy=AllocationStrategy.INDEXED,
        )
        inode.allocated_blocks = [0, 1, 2]
        inode.index_block_id = 3

        self.assertEqual(inode.get_data_block_count(), 3)
        self.assertEqual(inode.get_total_allocated_blocks(), 4)
        self.assertEqual(inode.get_allocated_data_bytes(4096), 12288)
        self.assertEqual(inode.get_internal_fragmentation(4096), 2048)


if __name__ == "__main__":
    unittest.main()
