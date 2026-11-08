"""Unit tests for storage allocation strategies (Incremento 3 - FS-003)."""

import unittest

from os_simulator.core.exceptions import DiskFragmentationException, DiskFullException
from os_simulator.core.types import AllocationStrategy, BlockStatus, NodeType
from os_simulator.filesystem.allocation import (
    AllocationStrategyFactory,
    ContiguousAllocation,
    IndexedAllocation,
    LinkedFATAllocation,
)
from os_simulator.filesystem.inode import Inode
from os_simulator.storage.memory_block_device import InMemoryBlockDevice


class TestAllocationStrategies(unittest.TestCase):
    """Test suite for Contiguous, Linked FAT, and Indexed allocation strategies."""

    def test_contiguous_allocation_success(self):
        device = InMemoryBlockDevice(capacity=10, block_size=1024)
        inode = Inode(1, NodeType.FILE)
        strat = ContiguousAllocation()

        data = b"A" * 3000  # 3 blocks needed (3000 / 1024 = 3 blocks)
        strat.write_data(device, inode, data)

        self.assertEqual(len(inode.allocated_blocks), 3)
        self.assertEqual(inode.allocated_blocks, [0, 1, 2])
        self.assertEqual(strat.read_data(device, inode), data)

        strat.free(device, inode)
        self.assertEqual(device.get_free_count(), 10)

    def test_contiguous_external_fragmentation(self):
        """Validates detection of external fragmentation when contiguous space is missing."""
        device = InMemoryBlockDevice(capacity=6, block_size=1024)
        # Artificially occupy blocks 1 and 3: [0:Free, 1:Used, 2:Free, 3:Used, 4:Free, 5:Free]
        device.get_block(1).block_status = BlockStatus.ALLOCATED
        device.get_block(3).block_status = BlockStatus.ALLOCATED

        self.assertEqual(device.get_free_count(), 4)  # Total 4 free blocks (0, 2, 4, 5)

        inode = Inode(1, NodeType.FILE)
        strat = ContiguousAllocation()

        # Request 3 contiguous blocks (spans available: [0:1], [2:1], [4:2]) -> Largest contiguous is 2!
        with self.assertRaises(DiskFragmentationException):
            strat.allocate(device, inode, size_bytes=3000)

    def test_linked_fat_allocation(self):
        device = InMemoryBlockDevice(capacity=6, block_size=1024)
        # Artificially occupy block 1: [0:Free, 1:Used, 2:Free, 3:Free, 4:Free, 5:Free]
        device.get_block(1).block_status = BlockStatus.ALLOCATED

        inode = Inode(1, NodeType.FILE)
        strat = LinkedFATAllocation()

        data = b"B" * 2500  # Needs 3 blocks
        strat.write_data(device, inode, data)

        self.assertEqual(len(inode.allocated_blocks), 3)
        self.assertEqual(inode.allocated_blocks, [0, 2, 3])  # Skips occupied block 1!
        self.assertEqual(strat.read_data(device, inode), data)

        strat.free(device, inode)
        self.assertEqual(device.get_free_count(), 5)

    def test_indexed_allocation(self):
        device = InMemoryBlockDevice(capacity=6, block_size=1024)
        inode = Inode(1, NodeType.FILE)
        strat = IndexedAllocation()

        data = b"C" * 2500  # 3 data blocks + 1 index block = 4 blocks total
        strat.write_data(device, inode, data)

        self.assertEqual(inode.index_block_id, 0)
        self.assertEqual(inode.allocated_blocks, [1, 2, 3])
        self.assertEqual(device.get_used_count(), 4)
        self.assertEqual(strat.read_data(device, inode), data)

        strat.free(device, inode)
        self.assertIsNone(inode.index_block_id)
        self.assertEqual(len(inode.allocated_blocks), 0)
        self.assertEqual(device.get_free_count(), 6)

    def test_scenario_fs_003_comparative(self):
        """Scenario FS-003: Compare all 3 strategies on a 10-block disk with blocks 1 and 5 occupied."""
        test_payload = b"X" * 3000  # 3 blocks of 1024 bytes

        for strat_type in [AllocationStrategy.CONTIGUOUS, AllocationStrategy.LINKED_FAT, AllocationStrategy.INDEXED]:
            device = InMemoryBlockDevice(capacity=10, block_size=1024)
            # Occupy blocks 1 and 5
            device.get_block(1).block_status = BlockStatus.ALLOCATED
            device.get_block(5).block_status = BlockStatus.ALLOCATED

            inode = Inode(10, NodeType.FILE, allocation_strategy=strat_type)
            strat = AllocationStrategyFactory.get_strategy(strat_type)

            strat.write_data(device, inode, test_payload)
            read_back = strat.read_data(device, inode)

            self.assertEqual(read_back, test_payload, f"Falha na recuperação de dados para {strat_type}")

            if strat_type == AllocationStrategy.CONTIGUOUS:
                # Spans available: [0:1], [2:3], [6:4]. First-fit chooses [2, 3, 4]
                self.assertEqual(inode.allocated_blocks, [2, 3, 4])
            elif strat_type == AllocationStrategy.LINKED_FAT:
                # Takes first 3 free: 0, 2, 3
                self.assertEqual(inode.allocated_blocks, [0, 2, 3])
            elif strat_type == AllocationStrategy.INDEXED:
                # 1 index block (0) + 3 data blocks (2, 3, 4)
                self.assertEqual(inode.index_block_id, 0)
                self.assertEqual(inode.allocated_blocks, [2, 3, 4])


if __name__ == "__main__":
    unittest.main()
