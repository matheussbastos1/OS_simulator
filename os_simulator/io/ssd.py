"""Solid State Drive (SSD) simulation with Flash Translation Layer (FTL) and Wear Leveling."""

from enum import Enum
import math
from typing import Any, Dict, List, Optional


class WearLevelingMode(str, Enum):
    """Wear leveling strategy modes."""
    NONE = "NONE"        # No wear leveling: LBA maps directly to PBA (concentrates wear)
    DYNAMIC = "DYNAMIC"  # Dynamic wear leveling: writes route to free blocks with lowest wear
    STATIC = "STATIC"    # Static wear leveling: also migrates cold static data to worn blocks


class SSDBlock:
    """Represents a physical NAND flash block with wear tracking."""

    def __init__(self, physical_id: int, block_size: int = 4096):
        self.physical_id = physical_id
        self.block_size = block_size
        self.data = bytearray(block_size)
        self.write_count: int = 0
        self.is_valid: bool = False
        self.is_free: bool = True
        self.logical_id: Optional[int] = None

    def write(self, data: bytes | bytearray, logical_id: int) -> None:
        """Write data to block, advancing write count and setting valid state."""
        payload_len = len(data)
        if payload_len > self.block_size:
            raise ValueError(
                f"Tamanho do dado ({payload_len} bytes) excede tamanho do bloco ({self.block_size} bytes)."
            )
        self.data[:payload_len] = data
        if payload_len < self.block_size:
            self.data[payload_len:] = b"\x00" * (self.block_size - payload_len)

        self.write_count += 1
        self.is_valid = True
        self.is_free = False
        self.logical_id = logical_id

    def invalidate(self) -> None:
        """Mark content as stale/obsolete (ready for garbage collection/recycling)."""
        self.is_valid = False
        self.is_free = True
        self.logical_id = None

    def read(self) -> bytearray:
        """Return raw data stored in this physical block."""
        return bytearray(self.data)

    def __repr__(self) -> str:
        return (
            f"<SSDBlock pba={self.physical_id} lba={self.logical_id} "
            f"writes={self.write_count} valid={self.is_valid} free={self.is_free}>"
        )


class SSDDevice:
    """Simulates a solid state drive with FTL mapping and Wear Leveling policies."""

    def __init__(
        self,
        logical_capacity: int = 16,
        overprovisioning: int = 4,
        block_size: int = 4096,
        wear_mode: WearLevelingMode = WearLevelingMode.DYNAMIC,
        static_threshold: int = 5,
    ):
        if logical_capacity <= 0:
            raise ValueError("Capacidade lógica do SSD deve ser > 0.")
        if overprovisioning < 0:
            raise ValueError("Overprovisioning deve ser >= 0.")

        self.logical_capacity = logical_capacity
        self.physical_capacity = logical_capacity + overprovisioning
        self.block_size = block_size
        self.wear_mode = wear_mode
        self.static_threshold = static_threshold

        # Flash Translation Layer (FTL): logical LBA -> physical PBA
        self.ftl_map: Dict[int, int] = {}
        self.physical_blocks: List[SSDBlock] = [
            SSDBlock(physical_id=i, block_size=block_size)
            for i in range(self.physical_capacity)
        ]

    def set_wear_mode(self, mode: WearLevelingMode) -> None:
        """Switch wear leveling mode dynamically."""
        self.wear_mode = mode

    def _validate_lba(self, lba: int) -> None:
        if not (0 <= lba < self.logical_capacity):
            raise IndexError(
                f"LBA {lba} fora dos limites. Limites válidos: [0, {self.logical_capacity - 1}]."
            )

    def read(self, lba: int) -> bytearray:
        """Read data for the given logical block address (LBA)."""
        self._validate_lba(lba)
        if lba not in self.ftl_map:
            # Unwritten block returns clean zeros
            return bytearray(self.block_size)
        pba = self.ftl_map[lba]
        return self.physical_blocks[pba].read()

    def write(self, lba: int, data: bytes | bytearray) -> int:
        """Write payload to logical address (LBA), applying wear leveling policy."""
        self._validate_lba(lba)

        if self.wear_mode == WearLevelingMode.NONE:
            # Naive 1:1 mapping directly to physical block (concentrates wear on frequently updated LBAs)
            target_pba = lba
            old_pba = self.ftl_map.get(lba)
            if old_pba is not None and old_pba != target_pba:
                self.physical_blocks[old_pba].invalidate()
            self.physical_blocks[target_pba].write(data, logical_id=lba)
            self.ftl_map[lba] = target_pba
            return target_pba

        # Dynamic / Static Wear Leveling:
        # 1. Identify free physical blocks
        free_pbas = [b.physical_id for b in self.physical_blocks if b.is_free]

        if not free_pbas:
            # If all blocks are marked occupied, force reclaim stale blocks
            free_pbas = [b.physical_id for b in self.physical_blocks if not b.is_valid]
            if not free_pbas:
                raise RuntimeError("Falha de FTL no SSD: sem blocos físicos disponíveis para escrita.")

        # 2. Pick candidate with LOWEST write_count to spread wear evenly
        best_pba = min(free_pbas, key=lambda pba: self.physical_blocks[pba].write_count)

        # 3. Static Wear Leveling check (if enabled):
        # If the gap between max wear and min wear exceeds threshold, migrate cold static data
        if self.wear_mode == WearLevelingMode.STATIC:
            self._apply_static_wear_leveling()

        # 4. Invalidate old PBA if this LBA was previously mapped elsewhere
        old_pba = self.ftl_map.get(lba)
        if old_pba is not None:
            self.physical_blocks[old_pba].invalidate()

        # 5. Program chosen physical block and update FTL mapping
        self.physical_blocks[best_pba].write(data, logical_id=lba)
        self.ftl_map[lba] = best_pba
        return best_pba

    def _apply_static_wear_leveling(self) -> None:
        """Migrate cold static data out of low-wear blocks into worn blocks."""
        valid_blocks = [b for b in self.physical_blocks if b.is_valid and b.logical_id is not None]
        if not valid_blocks:
            return

        min_wear_block = min(valid_blocks, key=lambda b: b.write_count)
        max_wear = max(b.write_count for b in self.physical_blocks)

        # If cold data is sitting in a block whose wear is significantly lower than max wear
        if max_wear - min_wear_block.write_count >= self.static_threshold:
            free_blocks = [b for b in self.physical_blocks if b.is_free]
            if free_blocks:
                # Find a more worn free block to receive this cold static data
                target_block = max(free_blocks, key=lambda b: b.write_count)
                if target_block.write_count > min_wear_block.write_count:
                    # Move data
                    cold_data = min_wear_block.read()
                    cold_lba = min_wear_block.logical_id
                    min_wear_block.invalidate()
                    target_block.write(cold_data, logical_id=cold_lba)
                    self.ftl_map[cold_lba] = target_block.physical_id

    def get_wear_stats(self) -> Dict[str, Any]:
        """Compute metrics of wear leveling and write count distribution."""
        wear_counts = [b.write_count for b in self.physical_blocks]
        min_wear = min(wear_counts) if wear_counts else 0
        max_wear = max(wear_counts) if wear_counts else 0
        total_writes = sum(wear_counts)
        avg_wear = total_writes / len(wear_counts) if wear_counts else 0.0

        variance = sum((w - avg_wear) ** 2 for w in wear_counts) / len(wear_counts) if wear_counts else 0.0
        std_dev = math.sqrt(variance)

        return {
            "mode": self.wear_mode.value,
            "logical_capacity": self.logical_capacity,
            "physical_capacity": self.physical_capacity,
            "total_writes": total_writes,
            "min_wear": min_wear,
            "max_wear": max_wear,
            "avg_wear": round(avg_wear, 2),
            "std_dev_wear": round(std_dev, 2),
            "wear_map": wear_counts,
        }

    get_wear_statistics = get_wear_stats

    def format_wear_report(self) -> str:
        """Format human-readable diagnostic report for SSD wear leveling."""
        stats = self.get_wear_stats()
        lines = [
            "======================================================================",
            "                DIAGNÓSTICO DE WEAR LEVELING DO SSD",
            "======================================================================",
            f"Política Ativa               : {stats['mode']}",
            f"Capacidade Lógica (LBAs)     : {stats['logical_capacity']} blocos",
            f"Capacidade Física Total (PBAs: {stats['physical_capacity']} blocos (Overprovisioning: {self.physical_capacity - self.logical_capacity})",
            f"Total de Ciclos de Escrita   : {stats['total_writes']} escritas",
            f"Desgaste Mínimo / Máximo     : {stats['min_wear']} / {stats['max_wear']} ciclos",
            f"Desgaste Médio               : {stats['avg_wear']} ciclos/bloco",
            f"Desvio Padrão do Desgaste    : {stats['std_dev_wear']} (menor = melhor distribuição)",
            "----------------------------------------------------------------------",
            "Mapa de Ciclos de Escrita por Bloco Físico (PBA):",
        ]
        row: List[str] = []
        for pba, count in enumerate(stats["wear_map"]):
            row.append(f"[{pba:02d}:{count:2d}]")
            if len(row) == 8:
                lines.append(" ".join(row))
                row = []
        if row:
            lines.append(" ".join(row))
        lines.append("======================================================================")
        return "\n".join(lines)
