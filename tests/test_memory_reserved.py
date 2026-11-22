"""Unit tests for Reserved Memory Manager, Contiguous Allocation, and Compaction."""

import unittest

from os_simulator.core.exceptions import (
    MemoryFragmentationException,
    OutOfMemoryException,
    PermissionDeniedException,
)
from os_simulator.memory.compaction import compact_reserved_memory
from os_simulator.memory.segment import ReservedMemoryManager


class TestReservedMemoryManager(unittest.TestCase):
    """Test scenarios MEM-001 and MEM-002."""

    def setUp(self):
        self.rm = ReservedMemoryManager(total_capacity_kb=4096, base_kernel_size_kb=1024)

    def test_initial_state(self):
        self.assertEqual(self.rm.total_capacity_kb, 4096)
        self.assertEqual(self.rm.get_total_allocated_kb(), 1024)
        self.assertEqual(self.rm.get_total_free_kb(), 3072)
        self.assertEqual(self.rm.get_max_contiguous_free_kb(), 3072)
        self.assertEqual(self.rm.get_external_fragmentation_kb(), 0)

    def test_mem_001_allocation_and_fragmentation(self):
        """Scenario MEM-001: Contiguous allocation and external fragmentation."""
        # 1. Allocate Kernel_DiskDriver (512 KB)
        seg1 = self.rm.allocate("Kernel_DiskDriver", 512)
        self.assertEqual(seg1.start_address, 1024)
        self.assertEqual(seg1.end_address, 1535)

        # 2. Allocate Kernel_NetDriver (1024 KB)
        seg2 = self.rm.allocate("Kernel_NetDriver", 1024)
        self.assertEqual(seg2.start_address, 1536)
        self.assertEqual(seg2.end_address, 2559)

        # 3. Allocate Kernel_CryptoEngine (512 KB)
        seg3 = self.rm.allocate("Kernel_CryptoEngine", 512)
        self.assertEqual(seg3.start_address, 2560)
        self.assertEqual(seg3.end_address, 3071)

        # 4. Terminate Kernel_NetDriver (free 1024 KB in middle)
        self.rm.free("Kernel_NetDriver")

        # 5. Check fragmentation
        total_free = self.rm.get_total_free_kb()
        max_contig = self.rm.get_max_contiguous_free_kb()
        ext_frag = self.rm.get_external_fragmentation_kb()

        self.assertEqual(total_free, 2048)
        self.assertEqual(max_contig, 1024)
        self.assertEqual(ext_frag, 1024)

        # 6. Allocation of 1536 KB must fail with MemoryFragmentationException
        with self.assertRaises(MemoryFragmentationException) as ctx:
            self.rm.allocate("Kernel_NewService", 1536)
        self.assertIn("fragmentação externa", str(ctx.exception).lower())

    def test_mem_002_compaction(self):
        """Scenario MEM-002: Sliding compaction consolidating free space."""
        # Setup MEM-001 state
        self.rm.allocate("Kernel_DiskDriver", 512)
        self.rm.allocate("Kernel_NetDriver", 1024)
        self.rm.allocate("Kernel_CryptoEngine", 512)
        self.rm.free("Kernel_NetDriver")

        # Perform compaction
        moved, consolidated_free = compact_reserved_memory(self.rm)

        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["process_name"], "Kernel_CryptoEngine")
        self.assertEqual(moved[0]["old_range"], (2560, 3071))
        self.assertEqual(moved[0]["new_range"], (1536, 2047))
        self.assertEqual(consolidated_free, 2048)

        # Post-compaction state
        self.assertEqual(self.rm.get_total_free_kb(), 2048)
        self.assertEqual(self.rm.get_max_contiguous_free_kb(), 2048)
        self.assertEqual(self.rm.get_external_fragmentation_kb(), 0)

        # Now 1536 KB allocation succeeds!
        new_seg = self.rm.allocate("Kernel_NewService", 1536)
        self.assertEqual(new_seg.start_address, 2048)
        self.assertEqual(new_seg.end_address, 3583)
        self.assertEqual(self.rm.get_total_free_kb(), 512)

    def test_cannot_free_base_kernel(self):
        with self.assertRaises(PermissionDeniedException):
            self.rm.free("Nucleo_Base")


if __name__ == "__main__":
    unittest.main()
