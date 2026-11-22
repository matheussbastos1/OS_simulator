"""Central MemoryManager orchestrating reserved memory, paging, MMU, replacement, and swap."""

import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from os_simulator.core.exceptions import (
    InvalidAddressException,
    InvalidProcessStateException,
    MemoryException,
    OutOfMemoryException,
    PageFaultException,
    ProcessNotFoundException,
    SwapException,
)
from os_simulator.core.ports import BlockDevicePort
from os_simulator.core.types import PageOrigin, ProcessState, ProcessType, ReplacementAlgorithm
from os_simulator.memory.compaction import compact_reserved_memory
from os_simulator.memory.mmu import MMU
from os_simulator.memory.paging import PageTable, PageTableEntry, PhysicalMemory
from os_simulator.memory.replacement import (
    LRUReplacement,
    PageReplacementPolicy,
    SecondChanceReplacement,
    create_replacement_policy,
)
from os_simulator.memory.segment import MemorySegment, ReservedMemoryManager
from os_simulator.memory.swap import SwapManager
from os_simulator.process.pcb import Process


class MemoryManager:
    """Integrated subsystem for hybrid memory management (Reserved Contiguous + Dynamic Paged)."""

    def __init__(
        self,
        reserved_capacity_kb: int = 4096,
        base_kernel_size_kb: int = 1024,
        dynamic_frames: int = 16,
        page_size: int = 4096,
        swap_slots: int = 64,
        swap_block_device: Optional[BlockDevicePort] = None,
        replacement_algorithm: ReplacementAlgorithm = ReplacementAlgorithm.LRU,
        process_lookup: Optional[Callable[[int], Optional[Process]]] = None,
    ):
        self.page_size = page_size
        self.reserved_memory = ReservedMemoryManager(
            total_capacity_kb=reserved_capacity_kb,
            base_kernel_size_kb=base_kernel_size_kb,
        )
        self.physical_memory = PhysicalMemory(
            num_frames=dynamic_frames,
            frame_size=page_size,
        )
        self.mmu = MMU(page_size=page_size)
        self.swap_manager = SwapManager(
            total_slots=swap_slots,
            slot_size=page_size,
            block_device=swap_block_device,
        )
        self.algorithm = replacement_algorithm
        self.replacement_policy: PageReplacementPolicy = create_replacement_policy(replacement_algorithm)
        self._process_lookup = process_lookup

        # Execution and diagnosis statistics
        self.stats = {
            "page_faults_total": 0,
            "page_faults_zero_fill": 0,
            "page_faults_process_image": 0,
            "page_faults_swap": 0,
            "swap_outs_total": 0,
            "swap_ins_total": 0,
            "evictions_clean": 0,
            "evictions_dirty": 0,
            "instructions_executed": 0,
        }

    def set_process_lookup(self, lookup: Callable[[int], Optional[Process]]) -> None:
        """Configure callback to resolve PID to Process instance."""
        self._process_lookup = lookup

    def _get_process(self, pid: int) -> Optional[Process]:
        if self._process_lookup:
            return self._process_lookup(pid)
        return None

    def set_replacement_policy(self, algorithm: Union[str, ReplacementAlgorithm]) -> None:
        """Switch active page replacement policy."""
        if isinstance(algorithm, str):
            algo_enum = ReplacementAlgorithm.from_string(algorithm)
        else:
            algo_enum = algorithm

        self.algorithm = algo_enum
        self.replacement_policy = create_replacement_policy(algo_enum)

    # -------------------------------------------------------------------------
    # Lifecycle Integration: Allocate and Free Memory
    # -------------------------------------------------------------------------

    def allocate_process_memory(self, process: Process) -> None:
        """Allocate memory based on process type (Contiguous vs Paged)."""
        if process.is_critical:
            # Critical process -> Contiguous allocation in Reserved Area
            seg = self.reserved_memory.allocate(process.name, process.size_kb)
            process.segment_id = seg.segment_id
        else:
            # Normal process -> Dynamic virtual page table initialization
            process.page_table = PageTable(
                pid=process.pid,
                process_size_bytes=process.size_bytes,
                page_size=self.page_size,
            )

    def free_process_memory(self, process: Process) -> None:
        """Release memory on process termination."""
        if process.is_critical:
            try:
                self.reserved_memory.free(process.name)
            except Exception:
                pass
            process.segment_id = None
        else:
            # Free physical RAM frames
            freed_frames = self.physical_memory.free_frames_for_process(process.pid)
            for fid in freed_frames:
                self.replacement_policy.on_frame_freed(fid)

            # Free Swap slots
            self.swap_manager.free_process_slots(process.pid)

            # Invalidate page table entries
            if process.page_table:
                for entry in process.page_table.entries.values():
                    entry.present = False
                    entry.frame_id = None
                    entry.dirty = False
                    entry.referenced = False
                    entry.swap_slot_id = None

    def compact_reserved(self) -> Tuple[List[Dict[str, Any]], int]:
        """Perform sliding compaction on the reserved memory area."""
        return compact_reserved_memory(self.reserved_memory)

    # -------------------------------------------------------------------------
    # Paging, Page Fault, and Address Translation
    # -------------------------------------------------------------------------

    def translate_page(self, process: Process, logical_page: int) -> Dict[str, Any]:
        """Translate logical page via MMU, reporting mapped frame or raising PageFaultException."""
        return self.mmu.translate_page(process, logical_page)

    def translate_address(self, process: Process, logical_address: int) -> Dict[str, Any]:
        """Translate logical byte address (p, d) to physical address (f, d)."""
        return self.mmu.translate_address(process, logical_address)

    def handle_page_fault(
        self,
        process: Process,
        logical_page: int,
        access_timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Full deterministic Page Fault resolution pipeline."""
        if not process.page_table:
            raise InvalidAddressException(f"Processo '{process.name}' não possui memória paginada.")

        entry = process.page_table.get_entry(logical_page)
        self.stats["page_faults_total"] += 1

        # Track fault provenance
        if entry.page_origin == PageOrigin.ZERO_FILL_ON_DEMAND:
            self.stats["page_faults_zero_fill"] += 1
        elif entry.page_origin == PageOrigin.PROCESS_IMAGE:
            self.stats["page_faults_process_image"] += 1
        elif entry.page_origin == PageOrigin.SWAP_STORAGE:
            self.stats["page_faults_swap"] += 1

        victim_info: Optional[Dict[str, Any]] = None
        free_frame_id = self.physical_memory.get_free_frame_id()

        if free_frame_id is not None:
            target_frame_id = free_frame_id
        else:
            # RAM is full: Page replacement required
            candidates: List[Tuple[int, PageTableEntry]] = []
            for frame in self.physical_memory.frames:
                if frame.occupied and frame.owner_pid is not None and frame.logical_page is not None:
                    victim_proc = self._get_process(frame.owner_pid)
                    if victim_proc and victim_proc.page_table:
                        v_entry = victim_proc.page_table.get_entry(frame.logical_page)
                        candidates.append((frame.frame_id, v_entry))

            if not candidates:
                raise OutOfMemoryException("Nenhuma moldura elegível para reposição na RAM dinâmica.")

            target_frame_id, victim_entry = self.replacement_policy.select_victim(candidates)
            victim_frame = self.physical_memory.get_frame(target_frame_id)
            victim_pid = victim_frame.owner_pid
            victim_page = victim_frame.logical_page

            needs_swap_out = victim_entry.dirty or (
                victim_entry.page_origin == PageOrigin.SWAP_STORAGE and victim_entry.swap_slot_id is None
            )
            if needs_swap_out:
                # Dirty victim or swapped page without backing: must be written to Swap partition
                slot_id = self.swap_manager.allocate_slot(victim_pid, victim_page)
                self.swap_manager.write_page(slot_id, bytes(victim_frame.data))
                victim_entry.present = False
                victim_entry.frame_id = None
                victim_entry.dirty = False
                victim_entry.page_origin = PageOrigin.SWAP_STORAGE
                victim_entry.swap_slot_id = slot_id

                self.stats["swap_outs_total"] += 1
                self.stats["evictions_dirty"] += 1
                victim_info = {
                    "pid": victim_pid,
                    "logical_page": victim_page,
                    "frame_id": target_frame_id,
                    "dirty": True,
                    "action": "SWAP_OUT",
                    "swap_slot_id": slot_id,
                }
            else:
                # Clean victim: discarded without writing to Swap
                victim_entry.present = False
                victim_entry.frame_id = None
                self.stats["evictions_clean"] += 1
                victim_info = {
                    "pid": victim_pid,
                    "logical_page": victim_page,
                    "frame_id": target_frame_id,
                    "dirty": False,
                    "action": "DISCARD",
                    "swap_slot_id": None,
                }

            victim_frame.free()

        # Load requested page into target_frame_id
        target_frame = self.physical_memory.get_frame(target_frame_id)

        if entry.page_origin == PageOrigin.ZERO_FILL_ON_DEMAND:
            # Preenchimento direto com zeros (sem I/O de swap ou disco)
            target_frame.allocate(pid=process.pid, logical_page=logical_page, data=b"\x00" * self.page_size)
        elif entry.page_origin == PageOrigin.PROCESS_IMAGE:
            # Imagem de processo
            code_stub = f"BIN_PID_{process.pid}_PAGE_{logical_page}".encode("utf-8")
            target_frame.allocate(pid=process.pid, logical_page=logical_page, data=code_stub.ljust(self.page_size, b"\x00"))
        elif entry.page_origin == PageOrigin.SWAP_STORAGE:
            # Recuperação determinística de swap
            slot_id = entry.swap_slot_id
            if slot_id is None:
                raise SwapException(f"Página {logical_page} marcada como SWAP_STORAGE mas sem swap_slot_id.")
            swap_data = self.swap_manager.read_page(slot_id)
            target_frame.allocate(pid=process.pid, logical_page=logical_page, data=swap_data)
            self.swap_manager.free_slot(slot_id)
            entry.swap_slot_id = None
            self.stats["swap_ins_total"] += 1

        now = time.time() if access_timestamp is None else access_timestamp
        entry.frame_id = target_frame_id
        entry.present = True
        entry.dirty = False
        entry.referenced = True
        entry.last_access = now

        self.replacement_policy.on_frame_allocated(target_frame_id, entry)
        self.replacement_policy.record_access(target_frame_id, entry, now)

        return {
            "logical_page": logical_page,
            "frame_id": target_frame_id,
            "page_origin": entry.page_origin.value,
            "victim": victim_info,
        }

    # -------------------------------------------------------------------------
    # Execution Simulation: execute_step
    # -------------------------------------------------------------------------

    def execute_instruction(
        self,
        process: Process,
        instruction: str,
        current_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute a simulated CPU/memory instruction on a process.

        Supported instructions:
          - "LOAD_DATA Página <N>" or "LOAD <N>" (Read access)
          - "WRITE_DATA Página <N>" or "WRITE <N>" (Write access)
        """
        if process.state == ProcessState.TERMINATED:
            raise InvalidProcessStateException(
                f"Operação inválida: processo '{process.name}' (PID {process.pid}) está encerrado (TERMINATED)."
            )

        self.stats["instructions_executed"] += 1
        inst_upper = instruction.strip().upper()

        # Parse instruction and target page
        is_write = "WRITE" in inst_upper or "STORE" in inst_upper
        page_match = re.search(r"(?:P[AÁ]GINA|PAGE|\b)\s*(\d+)", inst_upper)
        if not page_match:
            raise ValueError(
                f"Instrução inválida: '{instruction}'. Formato esperado: 'LOAD_DATA Página <N>' ou 'WRITE_DATA Página <N>'."
            )

        logical_page = int(page_match.group(1))

        if not process.page_table:
            raise InvalidAddressException(f"Processo '{process.name}' não possui memória virtual paginada.")

        page_fault_handled = False
        fault_details: Optional[Dict[str, Any]] = None

        # Check if page fault occurs
        try:
            self.mmu.translate_page(process, logical_page)
        except PageFaultException:
            # Handle Page Fault
            page_fault_handled = True
            fault_details = self.handle_page_fault(
                process=process,
                logical_page=logical_page,
                access_timestamp=current_time,
            )

        entry = process.page_table.get_entry(logical_page)
        frame_id = entry.frame_id
        if frame_id is None:
            raise MemoryException("Falha crítica: página presente mas frame_id é None.")

        now = time.time() if current_time is None else current_time
        self.replacement_policy.record_access(frame_id, entry, now)
        entry.referenced = True
        entry.last_access = now

        if is_write:
            entry.dirty = True
            frame = self.physical_memory.get_frame(frame_id)
            write_marker = f"MODIFIED_PID_{process.pid}_PAGE_{logical_page}_T_{now}".encode("utf-8")
            frame.write_data(write_marker)

        return {
            "instruction": instruction,
            "process_name": process.name,
            "pid": process.pid,
            "logical_page": logical_page,
            "frame_id": frame_id,
            "is_write": is_write,
            "page_fault": page_fault_handled,
            "fault_details": fault_details,
            "entry": entry.to_dict(),
        }

    # -------------------------------------------------------------------------
    # Diagnosis and Status Reporting
    # -------------------------------------------------------------------------

    def get_status(self, reserved_only: bool = False) -> Dict[str, Any]:
        """Generate comprehensive memory status diagnostics."""
        res_total = self.reserved_memory.total_capacity_kb
        res_alloc = self.reserved_memory.get_total_allocated_kb()
        res_free = self.reserved_memory.get_total_free_kb()
        res_max_contig = self.reserved_memory.get_max_contiguous_free_kb()
        res_ext_frag = self.reserved_memory.get_external_fragmentation_kb()

        status: Dict[str, Any] = {
            "reserved": {
                "total_capacity_kb": res_total,
                "allocated_kb": res_alloc,
                "free_kb": res_free,
                "max_contiguous_free_kb": res_max_contig,
                "external_fragmentation_kb": res_ext_frag,
                "segments": [seg.to_dict() for seg in self.reserved_memory.get_segments()],
            }
        }

        if reserved_only:
            return status

        # Dynamic RAM Status
        num_frames = self.physical_memory.num_frames
        occ_frames = self.physical_memory.get_occupied_count()
        free_frames = self.physical_memory.get_free_count()
        occ_pct = (occ_frames / num_frames * 100.0) if num_frames > 0 else 0.0

        # Swap Status
        swap_dict = self.swap_manager.to_dict()

        status["dynamic"] = {
            "total_frames": num_frames,
            "occupied_frames": occ_frames,
            "free_frames": free_frames,
            "occupancy_percent": occ_pct,
            "page_size": self.page_size,
            "replacement_algorithm": self.algorithm.value,
            "frames": [f.to_dict() for f in self.physical_memory.frames],
        }

        status["swap"] = swap_dict
        status["statistics"] = dict(self.stats)

        return status
