"""Comprehensive validation for Memory Lifecycle Scenarios (Cenários A - J)."""

import unittest

from os_simulator.core.exceptions import (
    InvalidAddressException,
    InvalidProcessStateException,
    MemoryFragmentationException,
    OutOfMemoryException,
    PermissionDeniedException,
    ProcessAlreadyExistsException,
    ProcessNotFoundException,
)
from os_simulator.core.types import PageOrigin, ProcessState, ProcessType, ReplacementAlgorithm
from os_simulator.memory.service import MemoryManager
from os_simulator.process.manager import ProcessManager


class TestMemoryLifecycleScenarios(unittest.TestCase):
    """Deep validation of lifecycle, edge cases, and regression integration."""

    def setUp(self):
        self.pm = ProcessManager()
        self.mm = MemoryManager(
            reserved_capacity_kb=4096,
            base_kernel_size_kb=1024,
            dynamic_frames=4,
            page_size=4096,
            swap_slots=32,
            process_lookup=self.pm.get_process,
        )

    def test_cenario_a_critical_allocation_lifecycle(self):
        """Cenário A: Alocação crítica, consulta, encerramento e reaproveitamento."""
        # 1. Create critical process
        p1 = self.pm.create_process("Driver_A", size_bytes=512 * 1024, process_type=ProcessType.CRITICAL)
        self.mm.allocate_process_memory(p1)
        seg1 = self.mm.reserved_memory.get_segment_for_process("Driver_A")
        self.assertEqual(seg1.start_address, 1024)
        self.assertEqual(seg1.end_address, 1535)

        # 2. Create another critical process
        p2 = self.pm.create_process("Driver_B", size_bytes=512 * 1024, process_type=ProcessType.CRITICAL)
        self.mm.allocate_process_memory(p2)
        seg2 = self.mm.reserved_memory.get_segment_for_process("Driver_B")
        self.assertEqual(seg2.start_address, 1536)
        self.assertEqual(seg2.end_address, 2047)

        # 3. Terminate Driver_A and verify release
        self.pm.terminate_process("Driver_A")
        self.mm.free_process_memory(p1)
        self.assertIsNone(self.mm.reserved_memory.get_segment_for_process("Driver_A"))

        # 4. Re-allocation should reuse the released [1024 - 1535 KB] slot
        p3 = self.pm.create_process("Driver_C", size_bytes=512 * 1024, process_type=ProcessType.CRITICAL)
        self.mm.allocate_process_memory(p3)
        seg3 = self.mm.reserved_memory.get_segment_for_process("Driver_C")
        self.assertEqual(seg3.start_address, 1024)
        self.assertEqual(seg3.end_address, 1535)

    def test_cenario_i_common_process_termination_and_cleanup(self):
        """Cenário I: Encerramento de processos comuns, liberação de molduras e swap."""
        # 1. Create two common processes
        proc1 = self.pm.create_process("Proc_1", size_bytes=8 * 1024, process_type=ProcessType.NORMAL)
        proc2 = self.pm.create_process("Proc_2", size_bytes=8 * 1024, process_type=ProcessType.NORMAL)
        self.mm.allocate_process_memory(proc1)
        self.mm.allocate_process_memory(proc2)

        # 2. Load pages into RAM (4 frames total)
        # Proc_1 loads page 0 (frame 0) and page 1 (frame 1)
        self.mm.execute_instruction(proc1, "LOAD_DATA Página 0", current_time=10.0)
        self.mm.execute_instruction(proc1, "LOAD_DATA Página 1", current_time=20.0)

        # Proc_2 loads page 0 (frame 2) and page 1 (frame 3)
        self.mm.execute_instruction(proc2, "LOAD_DATA Página 0", current_time=30.0)
        self.mm.execute_instruction(proc2, "LOAD_DATA Página 1", current_time=40.0)

        self.assertEqual(self.mm.physical_memory.get_occupied_count(), 4)
        self.assertEqual(self.mm.physical_memory.get_free_count(), 0)

        # Modify page 0 of Proc_1 so it becomes dirty
        self.mm.execute_instruction(proc1, "WRITE_DATA Página 0", current_time=50.0)

        # Now cause a page fault in a 3rd process to force swap-out of Proc_1's dirty page
        proc3 = self.pm.create_process("Proc_3", size_bytes=4 * 1024, process_type=ProcessType.NORMAL)
        self.mm.allocate_process_memory(proc3)
        # Oldest page among all: frame 1 (Proc_1, page 1, t=20) is clean -> discarded
        self.mm.execute_instruction(proc3, "LOAD_DATA Página 0", current_time=60.0)

        # Next fault: oldest is frame 2 (Proc_2, page 0, t=30, clean) -> discarded
        # To force dirty page 0 to swap, load pages until t=50 becomes the minimum
        proc4 = self.pm.create_process("Proc_4", size_bytes=12 * 1024, process_type=ProcessType.NORMAL)
        self.mm.allocate_process_memory(proc4)
        self.mm.execute_instruction(proc4, "LOAD_DATA Página 0", current_time=70.0)  # evicts frame 2 (t=30)
        self.mm.execute_instruction(proc4, "LOAD_DATA Página 1", current_time=80.0)  # evicts frame 3 (t=40)
        self.mm.execute_instruction(proc4, "LOAD_DATA Página 2", current_time=90.0)  # evicts frame 0 (Proc 1, p0 dirty, t=50) -> SWAPPED OUT!

        # Verify Proc_1 page 0 is now in swap
        self.assertEqual(self.mm.swap_manager.get_used_slots_count(), 1)
        self.assertFalse(proc1.page_table.entries[0].present)
        self.assertEqual(proc1.page_table.entries[0].page_origin, PageOrigin.SWAP_STORAGE)

        # 3. Terminate Proc_1: Must free any resident frames AND its swap slot!
        self.pm.terminate_process(proc1.pid)
        self.mm.free_process_memory(proc1)

        # Verify swap slot freed
        self.assertEqual(self.mm.swap_manager.get_used_slots_count(), 0)

        # Terminate remaining processes
        self.pm.terminate_process(proc2.pid)
        self.mm.free_process_memory(proc2)
        self.pm.terminate_process(proc3.pid)
        self.mm.free_process_memory(proc3)
        self.pm.terminate_process(proc4.pid)
        self.mm.free_process_memory(proc4)

        # Verify all frames in RAM are now completely free
        self.assertEqual(self.mm.physical_memory.get_occupied_count(), 0)
        self.assertEqual(self.mm.physical_memory.get_free_count(), 4)

    def test_process_error_handling(self):
        """Test process exception conditions."""
        # Process already exists
        self.pm.create_process("Test_P", 1024, ProcessType.NORMAL)
        with self.assertRaises(ProcessAlreadyExistsException):
            self.pm.create_process("Test_P", 1024, ProcessType.NORMAL)

        # Process not found
        with self.assertRaises(ProcessNotFoundException):
            self.pm.get_process("Ghost_Process")

        # Terminating base kernel is forbidden
        with self.assertRaises(PermissionDeniedException):
            self.pm.terminate_process(0)

        # Terminating already terminated process
        self.pm.terminate_process("Test_P")
        with self.assertRaises(InvalidProcessStateException):
            self.pm.terminate_process("Test_P")

        # Invalid address / page
        p = self.pm.create_process("P_Small", 4096, ProcessType.NORMAL)
        self.mm.allocate_process_memory(p)
        with self.assertRaises(InvalidAddressException):
            self.mm.translate_page(p, 5)  # only page 0 exists

        with self.assertRaises(InvalidAddressException):
            self.mm.translate_address(p, 99999)


if __name__ == "__main__":
    unittest.main()
