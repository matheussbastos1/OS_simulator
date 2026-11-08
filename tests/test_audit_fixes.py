"""Comprehensive verification tests for Etapa 1 audit corrections.

Covers:
1. Transactional write_file with atomic rollback on DiskFullException across all 3 strategies.
2. Safe block reuse on nearly-full disks (in-place expansion / delta allocation).
3. Normal growth and shrinkage lifecycle.
4. Decoupling of allocation from storage internals (no hasattr, no DiskBlock access).
5. Visual block map distinction ([I] for index, [D] for data, [.] for free, [X] for bad).
"""

import unittest

from os_simulator.core.exceptions import DiskFullException, DiskFragmentationException
from os_simulator.core.types import AllocationStrategy, BlockStatus, NodeType
from os_simulator.filesystem.allocation import (
    AllocationStrategyFactory,
    ContiguousAllocation,
    IndexedAllocation,
    LinkedFATAllocation,
)
from os_simulator.filesystem.inode import Inode
from os_simulator.filesystem.service import FileSystemService
from os_simulator.storage.memory_block_device import InMemoryBlockDevice


class TestAuditCorrections(unittest.TestCase):
    """Rigorous validation of the 3 audit corrections."""

    def test_transactional_write_rollback_contiguous(self):
        """Test rollback on ContiguousAllocation when expansion exceeds disk capacity."""
        device = InMemoryBlockDevice(capacity=8, block_size=1024)
        inode = Inode(1, NodeType.FILE, allocation_strategy=AllocationStrategy.CONTIGUOUS)
        strat = ContiguousAllocation()

        # Step 1: Initial write (2 blocks)
        initial_data = b"CONTIGUOUS_ORIGINAL_DATA"
        strat.write_data(device, inode, initial_data)
        initial_blocks = list(inode.allocated_blocks)
        self.assertEqual(len(initial_blocks), 1)
        self.assertEqual(strat.read_data(device, inode), initial_data)
        free_before = device.get_free_count()

        # Step 2: Attempt expansion beyond total disk capacity (needs 12 blocks, device has 8)
        huge_payload = b"Z" * (12 * 1024)
        with self.assertRaises(DiskFullException):
            strat.write_data(device, inode, huge_payload)

        # Step 3: Verify original content and metadata are 100% intact
        self.assertEqual(strat.read_data(device, inode), initial_data)
        self.assertEqual(inode.allocated_blocks, initial_blocks)
        self.assertEqual(inode.file_size, len(initial_data))

        # Step 4: Verify no orphaned or leaked blocks
        self.assertEqual(device.get_free_count(), free_before)

    def test_transactional_write_rollback_linked_fat(self):
        """Test rollback on LinkedFATAllocation when expansion exceeds disk capacity."""
        device = InMemoryBlockDevice(capacity=6, block_size=1024)
        inode = Inode(2, NodeType.FILE, allocation_strategy=AllocationStrategy.LINKED_FAT)
        strat = LinkedFATAllocation()

        # Step 1: Initial write (2 blocks)
        initial_data = b"F" * 1500
        strat.write_data(device, inode, initial_data)
        initial_blocks = list(inode.allocated_blocks)
        self.assertEqual(len(initial_blocks), 2)
        free_before = device.get_free_count()

        # Step 2: Attempt expansion beyond capacity (needs 8 blocks, capacity is 6)
        huge_payload = b"W" * (8 * 1024)
        with self.assertRaises(DiskFullException):
            strat.write_data(device, inode, huge_payload)

        # Step 3: Verify original content and metadata are 100% intact
        self.assertEqual(strat.read_data(device, inode), initial_data)
        self.assertEqual(inode.allocated_blocks, initial_blocks)
        self.assertEqual(inode.file_size, len(initial_data))
        self.assertEqual(device.get_free_count(), free_before)

    def test_transactional_write_rollback_indexed(self):
        """Test rollback on IndexedAllocation when expansion exceeds disk capacity."""
        device = InMemoryBlockDevice(capacity=6, block_size=1024)
        inode = Inode(3, NodeType.FILE, allocation_strategy=AllocationStrategy.INDEXED)
        strat = IndexedAllocation()

        # Step 1: Initial write (2 data blocks + 1 index block = 3 blocks)
        initial_data = b"INDEXED_ORIGINAL" * 100  # 1600 bytes -> 2 data blocks
        strat.write_data(device, inode, initial_data)
        initial_blocks = list(inode.allocated_blocks)
        initial_index_block = inode.index_block_id
        self.assertEqual(len(initial_blocks), 2)
        self.assertIsNotNone(initial_index_block)
        free_before = device.get_free_count()

        # Step 2: Attempt expansion beyond capacity (needs 10 data blocks, capacity is 6)
        huge_payload = b"K" * (10 * 1024)
        with self.assertRaises(DiskFullException):
            strat.write_data(device, inode, huge_payload)

        # Step 3: Verify original content and metadata are 100% intact
        self.assertEqual(strat.read_data(device, inode), initial_data)
        self.assertEqual(inode.allocated_blocks, initial_blocks)
        self.assertEqual(inode.index_block_id, initial_index_block)
        self.assertEqual(inode.file_size, len(initial_data))
        self.assertEqual(device.get_free_count(), free_before)

    def test_safe_block_reuse_nearly_full_disk_indexed(self):
        """Verify that expanding a file on a nearly-full disk reuses existing blocks.

        Device: 6 blocks.
        File initially occupies: 1 index block + 3 data blocks = 4 blocks.
        Free blocks remaining: 2 blocks.
        User expands file by 1 data block (needs 4 data blocks + 1 index = 5 blocks total).
        If naive reallocation required 5 *fresh* blocks, it would fail.
        With safe reuse (allocating only the 1 delta block), it succeeds.
        """
        device = InMemoryBlockDevice(capacity=6, block_size=1024)
        inode = Inode(4, NodeType.FILE, allocation_strategy=AllocationStrategy.INDEXED)
        strat = IndexedAllocation()

        # Initial write: 3 data blocks + 1 index = 4 blocks
        data_3k = b"A" * 3000
        strat.write_data(device, inode, data_3k)
        self.assertEqual(device.get_free_count(), 2)
        self.assertEqual(len(inode.allocated_blocks), 3)

        # Expand to 4 data blocks (needs 4000 bytes)
        # Delta = 1 block. 2 free blocks available. MUST SUCCEED!
        data_4k = b"B" * 4000
        strat.write_data(device, inode, data_4k)
        self.assertEqual(len(inode.allocated_blocks), 4)
        self.assertEqual(device.get_free_count(), 1)
        self.assertEqual(strat.read_data(device, inode), data_4k)

    def test_safe_block_reuse_nearly_full_disk_fat(self):
        """Verify safe block reuse on nearly full disk for LinkedFAT."""
        device = InMemoryBlockDevice(capacity=6, block_size=1024)
        inode = Inode(5, NodeType.FILE, allocation_strategy=AllocationStrategy.LINKED_FAT)
        strat = LinkedFATAllocation()

        # Initial write: 4 blocks
        strat.write_data(device, inode, b"F" * 4000)
        self.assertEqual(device.get_free_count(), 2)

        # Expand to 5 blocks (Delta = 1, available = 2) -> must succeed!
        strat.write_data(device, inode, b"G" * 5000)
        self.assertEqual(len(inode.allocated_blocks), 5)
        self.assertEqual(device.get_free_count(), 1)
        self.assertEqual(strat.read_data(device, inode), b"G" * 5000)

    def test_safe_block_reuse_nearly_full_disk_contiguous(self):
        """Verify in-place expansion for ContiguousAllocation when subsequent block is free."""
        device = InMemoryBlockDevice(capacity=6, block_size=1024)
        inode = Inode(6, NodeType.FILE, allocation_strategy=AllocationStrategy.CONTIGUOUS)
        strat = ContiguousAllocation()

        # Initial write: blocks [0, 1, 2, 3] (4 blocks)
        strat.write_data(device, inode, b"C" * 4000)
        self.assertEqual(inode.allocated_blocks, [0, 1, 2, 3])
        self.assertEqual(device.get_free_count(), 2)  # Blocks 4 and 5 free

        # Expand to 5 blocks: block 4 is free immediately following block 3 -> expands in place!
        strat.write_data(device, inode, b"D" * 5000)
        self.assertEqual(inode.allocated_blocks, [0, 1, 2, 3, 4])
        self.assertEqual(device.get_free_count(), 1)
        self.assertEqual(strat.read_data(device, inode), b"D" * 5000)

    def test_growth_and_shrinkage_lifecycle(self):
        """Test normal growth and shrinkage cycle across all 3 strategies."""
        for strat_type in [AllocationStrategy.CONTIGUOUS, AllocationStrategy.LINKED_FAT, AllocationStrategy.INDEXED]:
            device = InMemoryBlockDevice(capacity=10, block_size=1024)
            inode = Inode(10, NodeType.FILE, allocation_strategy=strat_type)
            strat = AllocationStrategyFactory.get_strategy(strat_type)

            # 1. Initial write: 2 blocks
            payload_2k = b"1" * 2000
            strat.write_data(device, inode, payload_2k)
            self.assertEqual(len(inode.allocated_blocks), 2)
            self.assertEqual(strat.read_data(device, inode), payload_2k)

            # 2. Grow to 4 blocks
            payload_4k = b"2" * 4000
            strat.write_data(device, inode, payload_4k)
            self.assertEqual(len(inode.allocated_blocks), 4)
            self.assertEqual(strat.read_data(device, inode), payload_4k)

            # 3. Shrink to 1 block
            payload_500b = b"3" * 500
            strat.write_data(device, inode, payload_500b)
            self.assertEqual(len(inode.allocated_blocks), 1)
            self.assertEqual(strat.read_data(device, inode), payload_500b)

            # 4. Free completely
            strat.free(device, inode)
            self.assertEqual(device.get_free_count(), 10)

    def test_visual_block_map_differentiation(self):
        """Verify fs_status --details distinguishes [I] (Index), [D] (Data), [.] (Free), and [X] (Bad)."""
        device = InMemoryBlockDevice(capacity=8, block_size=4096)
        service = FileSystemService(block_device=device, default_strategy=AllocationStrategy.INDEXED)

        # Mark block 7 as BAD for testing
        device.blocks[7].block_status = BlockStatus.BAD

        # Create a file with 2 data blocks + 1 index block
        service.write_file("/teste.txt", "X" * 6000)

        report = service.format_fs_status(details=True)

        # Assert index block renders as [I]
        self.assertIn("[00:I]", report)
        # Assert data blocks render as [D]
        self.assertIn("[01:D]", report)
        self.assertIn("[02:D]", report)
        # Assert free block renders as [.]
        self.assertIn("[03:.]", report)
        # Assert bad block renders as [X]
        self.assertIn("[07:X]", report)
        # Assert legend contains I = Índice
        self.assertIn("Legenda: . = Livre, D = Dados, I = Índice, X = Danificado", report)

    def test_block_device_port_decoupling_primitives(self):
        """Verify is_block_free and allocate_specific_blocks on BlockDevicePort."""
        device = InMemoryBlockDevice(capacity=4, block_size=1024)

        self.assertTrue(device.is_block_free(0))
        self.assertTrue(device.is_block_free(1))

        # Allocate specific blocks [1, 2]
        device.allocate_specific_blocks([1, 2])
        self.assertFalse(device.is_block_free(1))
        self.assertFalse(device.is_block_free(2))
        self.assertTrue(device.is_block_free(0))
        self.assertTrue(device.is_block_free(3))

        # Trying to allocate block 1 again should fail
        with self.assertRaises(DiskFullException):
            device.allocate_specific_blocks([1])

        # Free block 1
        device.free_block(1)
        self.assertTrue(device.is_block_free(1))


if __name__ == "__main__":
    unittest.main()
