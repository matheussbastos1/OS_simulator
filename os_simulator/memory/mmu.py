"""Memory Management Unit (MMU) for logical-to-physical address translation."""

from typing import Any, Dict, Optional, Tuple

from os_simulator.core.exceptions import InvalidAddressException, InvalidProcessStateException, PageFaultException
from os_simulator.core.types import ProcessState
from os_simulator.memory.paging import PageTableEntry
from os_simulator.process.pcb import Process


class MMU:
    """Simulates hardware MMU address translation and Page Fault detection."""

    def __init__(self, page_size: int = 4096):
        self.page_size = page_size

    def translate_page(self, process: Process, logical_page: int) -> Dict[str, Any]:
        """Translate a logical page number to its mapped physical frame.

        Raises:
            InvalidProcessStateException: if process is terminated.
            InvalidAddressException: if page is out of bounds for the process.
            PageFaultException: if page is not currently present in RAM.
        """
        if process.state == ProcessState.TERMINATED:
            raise InvalidProcessStateException(
                f"Operação inválida: processo '{process.name}' (PID {process.pid}) está encerrado (TERMINATED)."
            )

        if not process.page_table:
            raise InvalidAddressException(
                f"Processo '{process.name}' (PID {process.pid}) não possui tabela de páginas (não paginado)."
            )

        entry = process.page_table.get_entry(logical_page)

        if not entry.present or entry.frame_id is None:
            raise PageFaultException(
                pid=process.pid,
                logical_page=logical_page,
                page_origin=entry.page_origin.value,
            )

        frame_id = entry.frame_id
        base_address = frame_id * self.page_size
        end_address = base_address + self.page_size - 1

        return {
            "pid": process.pid,
            "process_name": process.name,
            "logical_page": logical_page,
            "frame_id": frame_id,
            "base_address": base_address,
            "end_address": end_address,
            "entry": entry,
        }

    def translate_address(self, process: Process, logical_address: int) -> Dict[str, Any]:
        """Translate a full logical virtual address (p, d) to physical address (f, d).

        Raises:
            InvalidAddressException: if address is negative or beyond process size.
            PageFaultException: if the corresponding page is not present in RAM.
        """
        if logical_address < 0 or logical_address >= process.size_bytes:
            raise InvalidAddressException(
                f"Endereço lógico {logical_address} inválido para processo '{process.name}' "
                f"(espaço de endereçamento: 0 a {process.size_bytes - 1} bytes)."
            )

        logical_page = logical_address // self.page_size
        offset = logical_address % self.page_size

        trans = self.translate_page(process, logical_page)
        physical_address = (trans["frame_id"] * self.page_size) + offset

        return {
            "pid": process.pid,
            "process_name": process.name,
            "logical_address": logical_address,
            "logical_page": logical_page,
            "offset": offset,
            "frame_id": trans["frame_id"],
            "physical_address": physical_address,
            "entry": trans["entry"],
        }
