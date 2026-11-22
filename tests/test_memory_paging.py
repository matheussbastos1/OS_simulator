"""Unit tests for Paging, MMU, LRU, Second Chance, and Swap (MEM-003, MEM-004A, MEM-004B, MEM-005)."""

import unittest

from os_simulator.core.exceptions import (
    InvalidAddressException,
    PageFaultException,
)
from os_simulator.core.types import PageOrigin, ProcessType, ReplacementAlgorithm
from os_simulator.memory.mmu import MMU
from os_simulator.memory.paging import PageTable, PhysicalMemory
from os_simulator.memory.replacement import LRUReplacement, SecondChanceReplacement
from os_simulator.memory.service import MemoryManager
from os_simulator.memory.swap import SwapManager
from os_simulator.process.pcb import Process


class TestMemoryPagingSubsystem(unittest.TestCase):
    """Test scenarios MEM-003, MEM-004A, MEM-004B, and MEM-005."""

    def test_mem_003_virtual_memory_and_internal_fragmentation(self):
        """Scenario MEM-003: Virtual memory, page table, and internal fragmentation."""
        # Process of 10 KB with 4 KB pages
        proc = Process(
            pid=101,
            name="App_Navegador",
            size_bytes=10 * 1024,  # 10,240 bytes
            process_type=ProcessType.NORMAL,
        )
        pt = PageTable(pid=proc.pid, process_size_bytes=proc.size_bytes, page_size=4096)
        proc.page_table = pt

        # Check total pages
        self.assertEqual(pt.total_pages, 3)
        self.assertIn(0, pt.entries)
        self.assertIn(1, pt.entries)
        self.assertIn(2, pt.entries)

        # Check bytes used per page
        self.assertEqual(pt.entries[0].bytes_used, 4096)
        self.assertEqual(pt.entries[1].bytes_used, 4096)
        self.assertEqual(pt.entries[2].bytes_used, 2048)

        # Check internal fragmentation (waste in final page: 4096 - 2048 = 2048 bytes)
        self.assertEqual(pt.internal_fragmentation, 2048)

    def test_mem_004a_translation_professor_example(self):
        """Scenario MEM-004A: translate_address --process App_Navegador --page 1."""
        proc = Process(
            pid=102,
            name="App_Navegador",
            size_bytes=10 * 1024,
            process_type=ProcessType.NORMAL,
        )
        pt = PageTable(pid=proc.pid, process_size_bytes=proc.size_bytes, page_size=4096)
        proc.page_table = pt

        # Map Page 1 to Frame 12
        entry1 = pt.get_entry(1)
        entry1.present = True
        entry1.frame_id = 12

        mmu = MMU(page_size=4096)
        result = mmu.translate_page(proc, 1)

        self.assertEqual(result["frame_id"], 12)
        self.assertEqual(result["base_address"], 49152)  # 12 * 4096
        self.assertEqual(result["end_address"], 53247)   # 49152 + 4096 - 1

    def test_mem_004b_translation_logical_address_with_offset(self):
        """Scenario MEM-004B: translate_address --pid <PID> --address 4100."""
        proc = Process(
            pid=103,
            name="App_Navegador",
            size_bytes=10 * 1024,
            process_type=ProcessType.NORMAL,
        )
        pt = PageTable(pid=proc.pid, process_size_bytes=proc.size_bytes, page_size=4096)
        proc.page_table = pt

        # Map Page 1 to Frame 5
        entry1 = pt.get_entry(1)
        entry1.present = True
        entry1.frame_id = 5

        mmu = MMU(page_size=4096)
        result = mmu.translate_address(proc, 4100)

        # p = 4100 // 4096 = 1; d = 4100 % 4096 = 4
        self.assertEqual(result["logical_page"], 1)
        self.assertEqual(result["offset"], 4)
        self.assertEqual(result["frame_id"], 5)
        # physical_address = (5 * 4096) + 4 = 20480 + 4 = 20484
        self.assertEqual(result["physical_address"], 20484)

    def test_mem_005_deterministic_cycle_page_fault_lru_swap(self):
        """Scenario MEM-005: Deterministic cycle of Page Fault, Zero-Fill, LRU, and Swap."""
        processes = {}

        def lookup(pid: int):
            return processes.get(pid)

        # Restricted to 2 dynamic frames for replacement testing
        mem_mgr = MemoryManager(
            dynamic_frames=2,
            page_size=4096,
            swap_slots=16,
            replacement_algorithm=ReplacementAlgorithm.LRU,
            process_lookup=lookup,
        )

        proc = Process(
            pid=104,
            name="App_Navegador",
            size_bytes=16 * 1024,  # 4 pages (0, 1, 2, 3)
            process_type=ProcessType.NORMAL,
        )
        mem_mgr.allocate_process_memory(proc)
        processes[104] = proc

        pt = proc.page_table

        # Setup initial state for MEM-005:
        # Frame 0: Page 0 (last_access=100.0, dirty=False, origin=PROCESS_IMAGE)
        # Frame 1: Page 1 (last_access=200.0, dirty=False, origin=PROCESS_IMAGE)
        mem_mgr.physical_memory.allocate_frame(0, proc.pid, 0)
        e0 = pt.get_entry(0)
        e0.present = True
        e0.frame_id = 0
        e0.last_access = 100.0
        e0.dirty = False
        e0.referenced = True
        e0.page_origin = PageOrigin.PROCESS_IMAGE

        mem_mgr.physical_memory.allocate_frame(1, proc.pid, 1)
        e1 = pt.get_entry(1)
        e1.present = True
        e1.frame_id = 1
        e1.last_access = 200.0
        e1.dirty = False
        e1.referenced = True
        e1.page_origin = PageOrigin.PROCESS_IMAGE

        # --- Phase A: Page Fault with Zero-Fill and Clean Page Eviction ---
        # Instruction: LOAD_DATA Página 2
        res_a = mem_mgr.execute_instruction(proc, "LOAD_DATA Página 2", current_time=250.0)

        self.assertTrue(res_a["page_fault"])
        # Victim: Page 0 in Frame 0 (t=100 vs t=200)
        victim_a = res_a["fault_details"]["victim"]
        self.assertIsNotNone(victim_a)
        self.assertEqual(victim_a["logical_page"], 0)
        self.assertEqual(victim_a["frame_id"], 0)
        self.assertFalse(victim_a["dirty"])
        self.assertEqual(victim_a["action"], "DISCARD")
        self.assertIsNone(victim_a["swap_slot_id"])
        self.assertEqual(mem_mgr.swap_manager.get_used_slots_count(), 0)  # No swap used for clean discard!

        # Target Page 2 loaded into Frame 0
        e2 = pt.get_entry(2)
        self.assertTrue(e2.present)
        self.assertEqual(e2.frame_id, 0)
        self.assertFalse(e2.dirty)

        # --- Phase B: Modification and Swap-Out of Dirty Page ---
        # Instruction: WRITE_DATA Página 2 at t=300.0
        res_b1 = mem_mgr.execute_instruction(proc, "WRITE_DATA Página 2", current_time=300.0)
        self.assertFalse(res_b1["page_fault"])
        self.assertTrue(e2.dirty)
        self.assertEqual(e2.last_access, 300.0)

        # Instruction: LOAD_DATA Página 0 at t=350.0
        # Page 0 faults. Candidates: Frame 1 (Page 1, t=200), Frame 0 (Page 2, t=300).
        # Victim: Page 1 (t=200, clean -> discarded)
        res_b2 = mem_mgr.execute_instruction(proc, "LOAD_DATA Página 0", current_time=350.0)
        self.assertTrue(res_b2["page_fault"])
        victim_b2 = res_b2["fault_details"]["victim"]
        self.assertEqual(victim_b2["logical_page"], 1)
        self.assertEqual(victim_b2["frame_id"], 1)
        self.assertFalse(victim_b2["dirty"])

        # Page 0 is now in Frame 1
        self.assertTrue(e0.present)
        self.assertEqual(e0.frame_id, 1)

        # Instruction: LOAD_DATA Página 3 at t=400.0
        # Page 3 faults. Candidates: Frame 0 (Page 2, dirty=True, t=300), Frame 1 (Page 0, t=350).
        # Victim: Page 2 (t=300, dirty=True -> MUST BE SWAPPED OUT!)
        res_b3 = mem_mgr.execute_instruction(proc, "LOAD_DATA Página 3", current_time=400.0)
        self.assertTrue(res_b3["page_fault"])
        victim_b3 = res_b3["fault_details"]["victim"]
        self.assertEqual(victim_b3["logical_page"], 2)
        self.assertEqual(victim_b3["frame_id"], 0)
        self.assertTrue(victim_b3["dirty"])
        self.assertEqual(victim_b3["action"], "SWAP_OUT")
        self.assertEqual(victim_b3["swap_slot_id"], 0)

        # Page 2 state after swap-out:
        self.assertFalse(e2.present)
        self.assertIsNone(e2.frame_id)
        self.assertEqual(e2.page_origin, PageOrigin.SWAP_STORAGE)
        self.assertEqual(e2.swap_slot_id, 0)
        self.assertEqual(mem_mgr.swap_manager.get_used_slots_count(), 1)

        # --- Phase C: Deterministic Swap-In ---
        # Instruction: LOAD_DATA Página 2 at t=450.0
        # Page 2 faults with SWAP_STORAGE origin! Must swap-in and free slot 0!
        res_c = mem_mgr.execute_instruction(proc, "LOAD_DATA Página 2", current_time=450.0)
        self.assertTrue(res_c["page_fault"])
        self.assertEqual(res_c["fault_details"]["page_origin"], PageOrigin.SWAP_STORAGE.value)

        # Page 2 restored to RAM and slot 0 freed!
        self.assertTrue(e2.present)
        self.assertIsNone(e2.swap_slot_id)
        self.assertEqual(mem_mgr.swap_manager.get_used_slots_count(), 0)

        # --- Phase D: Re-eviction of clean swapped-in page ---
        # Cause evictions so Page 2 (now clean) is evicted again.
        # It must be written to Swap partition rather than discarded!
        mem_mgr.execute_instruction(proc, "LOAD_DATA Página 1", current_time=500.0)
        mem_mgr.execute_instruction(proc, "LOAD_DATA Página 3", current_time=550.0)

        # Page 2 was evicted: must be in swap again!
        self.assertFalse(e2.present)
        self.assertEqual(e2.page_origin, PageOrigin.SWAP_STORAGE)
        self.assertIsNotNone(e2.swap_slot_id)
        self.assertGreater(mem_mgr.swap_manager.get_used_slots_count(), 0)

        # Page 2 can be accessed and swapped in once more without error!
        res_d = mem_mgr.execute_instruction(proc, "LOAD_DATA Página 2", current_time=600.0)
        self.assertTrue(res_d["page_fault"])
        self.assertTrue(e2.present)

    def test_second_chance_clock_algorithm(self):
        """Test Second Chance (Clock) algorithm behavior."""
        sc = SecondChanceReplacement()

        # Create dummy entries with referenced bits
        e0 = pt_entry = type("MockEntry", (), {"referenced": True, "last_access": 10.0})()
        e1 = type("MockEntry", (), {"referenced": True, "last_access": 20.0})()
        e2 = type("MockEntry", (), {"referenced": False, "last_access": 30.0})()

        candidates = [(0, e0), (1, e1), (2, e2)]

        # Candidate 0 has R=1 -> second chance (R=0)
        # Candidate 1 has R=1 -> second chance (R=0)
        # Candidate 2 has R=0 -> selected as victim!
        victim_frame, victim_entry = sc.select_victim(candidates)
        self.assertEqual(victim_frame, 2)
        self.assertEqual(e0.referenced, False)
        self.assertEqual(e1.referenced, False)

        # Next call starting from pointer: candidate 0 now has R=0 -> selected!
        victim_frame_2, _ = sc.select_victim(candidates)
        self.assertEqual(victim_frame_2, 0)


if __name__ == "__main__":
    unittest.main()
