"""RAID Controller implementations: RAID 0, RAID 1, RAID 4, and RAID 5."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from os_simulator.core.exceptions import StorageException
from os_simulator.storage.physical_disk import DiskFailureException, PhysicalDisk


class RAIDLevel(str, Enum):
    """Supported RAID redundancy levels."""
    RAID_0 = "RAID_0"
    RAID_1 = "RAID_1"
    RAID_4 = "RAID_4"
    RAID_5 = "RAID_5"


class RAIDStatus(str, Enum):
    """Operational health status of the RAID array."""
    OPTIMAL = "OPTIMAL"    # All disks online and operational
    DEGRADED = "DEGRADED"  # One disk failed; operating with redundancy/reconstruction
    FAILED = "FAILED"      # Too many disks failed; array cannot read/write


class RAIDException(StorageException):
    """Base exception for RAID storage errors."""
    pass


class RAIDDegradedException(RAIDException):
    """Raised when an operation is performed on a degraded array."""
    pass


class RAIDFailedException(RAIDException):
    """Raised when an operation cannot be completed due to excessive disk failures."""
    pass


def xor_bytes(a: bytes | bytearray, b: bytes | bytearray) -> bytearray:
    """Perform byte-by-byte XOR between two byte sequences up to max length."""
    max_len = max(len(a), len(b))
    result = bytearray(max_len)
    for i in range(max_len):
        b1 = a[i] if i < len(a) else 0
        b2 = b[i] if i < len(b) else 0
        result[i] = b1 ^ b2
    return result


def xor_multiple(buffers: List[bytes | bytearray], size: int) -> bytearray:
    """XOR multiple byte sequences together."""
    result = bytearray(size)
    for buf in buffers:
        for i in range(min(len(buf), size)):
            result[i] ^= buf[i]
    return result


class RAIDController(ABC):
    """Abstract base class for all RAID array controllers."""

    def __init__(self, disks: List[PhysicalDisk], block_size: int = 4096):
        if not disks:
            raise ValueError("RAID requer pelo menos um disco físico.")
        self.disks = disks
        self.num_disks = len(disks)
        self.disk_capacity = disks[0].capacity_blocks
        self.block_size = block_size

    @property
    def online_disks_count(self) -> int:
        return sum(1 for d in self.disks if d.is_online)

    @property
    def failed_disks_count(self) -> int:
        return sum(1 for d in self.disks if not d.is_online)

    @property
    @abstractmethod
    def level(self) -> RAIDLevel:
        raise NotImplementedError

    @property
    @abstractmethod
    def logical_capacity(self) -> int:
        """Total usable logical blocks presented by the array."""
        raise NotImplementedError

    @property
    @abstractmethod
    def status(self) -> RAIDStatus:
        """Current operational health of the array."""
        raise NotImplementedError

    def fail_disk(self, disk_id: int) -> None:
        """Inject failure into specified member disk."""
        for d in self.disks:
            if d.disk_id == disk_id:
                d.fail()
                return
        raise ValueError(f"Disco {disk_id} não encontrado no arranjo.")

    def recover_disk(self, disk_id: int) -> None:
        """Mark member disk as online (repaired)."""
        for d in self.disks:
            if d.disk_id == disk_id:
                d.recover()
                return
        raise ValueError(f"Disco {disk_id} não encontrado no arranjo.")

    @abstractmethod
    def read_block(self, lba: int) -> bytearray:
        """Read data at logical block address (LBA)."""
        raise NotImplementedError

    @abstractmethod
    def write_block(self, lba: int, data: bytes | bytearray) -> None:
        """Write data to logical block address (LBA), updating parity if applicable."""
        raise NotImplementedError

    @abstractmethod
    def rebuild_disk(self, disk_id: int) -> None:
        """Reconstruct data onto a replacement disk after failure."""
        raise NotImplementedError

    def format_status(self) -> str:
        """Format detailed status report for CLI diagnostics."""
        lines = [
            "======================================================================",
            f"                     DIAGNÓSTICO DO ARRANJO {self.level.value}",
            "======================================================================",
            f"Nível RAID                   : {self.level.value}",
            f"Estado do Arranjo            : {self.status.value}",
            f"Total de Discos Membros      : {self.num_disks} discos",
            f"Discos Operacionais (Online) : {self.online_disks_count} discos",
            f"Discos Falhos (Offline)      : {self.failed_disks_count} discos",
            f"Capacidade de Cada Disco     : {self.disk_capacity} blocos ({self.disk_capacity * self.block_size // 1024} KB)",
            f"Capacidade Útil Total (LBA)  : {self.logical_capacity} blocos ({self.logical_capacity * self.block_size // 1024} KB)",
            "----------------------------------------------------------------------",
            "Discos Físicos do Arranjo:",
        ]
        for d in self.disks:
            state = "ONLINE [OK]" if d.is_online else "FAILED [X]"
            lines.append(
                f"  Disco {d.disk_id:02d}: {state} | Leituras: {d.read_count} | Escritas: {d.write_count}"
            )
        lines.append("======================================================================")
        return "\n".join(lines)


class RAID0Controller(RAIDController):
    """RAID 0 (Striping) controller.

    No redundancy; maximum throughput and storage capacity.
    Failure of any disk results in data loss.
    """

    def __init__(self, disks: List[PhysicalDisk], block_size: int = 4096):
        if len(disks) < 2:
            raise ValueError("RAID 0 requer no mínimo 2 discos físicos.")
        super().__init__(disks, block_size)

    @property
    def level(self) -> RAIDLevel:
        return RAIDLevel.RAID_0

    @property
    def logical_capacity(self) -> int:
        return self.num_disks * self.disk_capacity

    @property
    def status(self) -> RAIDStatus:
        return RAIDStatus.OPTIMAL if self.failed_disks_count == 0 else RAIDStatus.FAILED

    def read_block(self, lba: int) -> bytearray:
        if not (0 <= lba < self.logical_capacity):
            raise IndexError(f"LBA {lba} fora dos limites do RAID 0 [0, {self.logical_capacity - 1}].")
        disk_idx = lba % self.num_disks
        pba = lba // self.num_disks
        return self.disks[disk_idx].read_block(pba)

    def write_block(self, lba: int, data: bytes | bytearray) -> None:
        if not (0 <= lba < self.logical_capacity):
            raise IndexError(f"LBA {lba} fora dos limites do RAID 0 [0, {self.logical_capacity - 1}].")
        disk_idx = lba % self.num_disks
        pba = lba // self.num_disks
        self.disks[disk_idx].write_block(pba, data)

    def rebuild_disk(self, disk_id: int) -> None:
        raise RAIDFailedException("RAID 0 não possui redundância. Não é possível reconstruir dados de disco falho.")


class RAID1Controller(RAIDController):
    """RAID 1 (Mirroring) controller.

    Data is duplicated across all member disks.
    Tolerates up to N-1 disk failures.
    """

    def __init__(self, disks: List[PhysicalDisk], block_size: int = 4096):
        if len(disks) < 2:
            raise ValueError("RAID 1 requer no mínimo 2 discos físicos.")
        super().__init__(disks, block_size)

    @property
    def level(self) -> RAIDLevel:
        return RAIDLevel.RAID_1

    @property
    def logical_capacity(self) -> int:
        return self.disk_capacity

    @property
    def status(self) -> RAIDStatus:
        if self.online_disks_count == self.num_disks:
            return RAIDStatus.OPTIMAL
        if self.online_disks_count > 0:
            return RAIDStatus.DEGRADED
        return RAIDStatus.FAILED

    def read_block(self, lba: int) -> bytearray:
        if not (0 <= lba < self.logical_capacity):
            raise IndexError(f"LBA {lba} fora dos limites do RAID 1 [0, {self.logical_capacity - 1}].")
        # Read from any available online disk
        for disk in self.disks:
            if disk.is_online:
                return disk.read_block(lba)
        raise RAIDFailedException("Todos os discos do arranjo RAID 1 estão falhos. Leitura impossível.")

    def write_block(self, lba: int, data: bytes | bytearray) -> None:
        if not (0 <= lba < self.logical_capacity):
            raise IndexError(f"LBA {lba} fora dos limites do RAID 1 [0, {self.logical_capacity - 1}].")
        if self.online_disks_count == 0:
            raise RAIDFailedException("Todos os discos do arranjo RAID 1 estão falhos. Escrita impossível.")

        for disk in self.disks:
            if disk.is_online:
                disk.write_block(lba, data)

    def rebuild_disk(self, disk_id: int) -> None:
        """Reconstruct replacement disk by cloning from an online mirror."""
        target_disk = next((d for d in self.disks if d.disk_id == disk_id), None)
        if target_disk is None:
            raise ValueError(f"Disco {disk_id} não encontrado.")

        source_disk = next((d for d in self.disks if d.disk_id != disk_id and d.is_online), None)
        if source_disk is None:
            raise RAIDFailedException("Nenhum disco íntegro disponível para fonte de reconstrução no RAID 1.")

        target_disk.recover()
        for b_id in range(self.disk_capacity):
            data = source_disk.read_block(b_id)
            target_disk.write_block(b_id, data)


class RAID4Controller(RAIDController):
    """RAID 4 (Dedicated Parity) controller.

    Data is striped across N-1 disks. Disk N-1 is the dedicated XOR parity disk.
    Tolerates 1 disk failure.
    """

    def __init__(self, disks: List[PhysicalDisk], block_size: int = 4096):
        if len(disks) < 3:
            raise ValueError("RAID 4 requer no mínimo 3 discos físicos (dados + paridade dedicada).")
        super().__init__(disks, block_size)
        self.data_disks = self.disks[:-1]
        self.parity_disk = self.disks[-1]

    @property
    def level(self) -> RAIDLevel:
        return RAIDLevel.RAID_4

    @property
    def logical_capacity(self) -> int:
        return (self.num_disks - 1) * self.disk_capacity

    @property
    def status(self) -> RAIDStatus:
        if self.failed_disks_count == 0:
            return RAIDStatus.OPTIMAL
        if self.failed_disks_count == 1:
            return RAIDStatus.DEGRADED
        return RAIDStatus.FAILED

    def read_block(self, lba: int) -> bytearray:
        if not (0 <= lba < self.logical_capacity):
            raise IndexError(f"LBA {lba} fora dos limites do RAID 4 [0, {self.logical_capacity - 1}].")

        if self.failed_disks_count >= 2:
            raise RAIDFailedException("RAID 4 falhou: 2 ou mais discos estão offline.")

        data_disk_idx = lba % (self.num_disks - 1)
        stripe_idx = lba // (self.num_disks - 1)
        target_disk = self.data_disks[data_disk_idx]

        if target_disk.is_online:
            return target_disk.read_block(stripe_idx)

        # On-the-fly reconstruction: XOR of surviving data disks and parity disk
        surviving_buffers: List[bytearray] = []
        for idx, d in enumerate(self.data_disks):
            if idx != data_disk_idx:
                surviving_buffers.append(d.read_block(stripe_idx))
        surviving_buffers.append(self.parity_disk.read_block(stripe_idx))

        return xor_multiple(surviving_buffers, self.block_size)

    def write_block(self, lba: int, data: bytes | bytearray) -> None:
        if not (0 <= lba < self.logical_capacity):
            raise IndexError(f"LBA {lba} fora dos limites do RAID 4 [0, {self.logical_capacity - 1}].")

        if self.failed_disks_count >= 2:
            raise RAIDFailedException("RAID 4 falhou: 2 ou mais discos estão offline.")

        data_disk_idx = lba % (self.num_disks - 1)
        stripe_idx = lba // (self.num_disks - 1)
        target_disk = self.data_disks[data_disk_idx]

        # 1. Update data disk if online
        if target_disk.is_online:
            target_disk.write_block(stripe_idx, data)

        # 2. Recompute and write parity across stripe if parity disk is online
        if self.parity_disk.is_online:
            stripe_buffers: List[bytearray] = []
            for idx, d in enumerate(self.data_disks):
                if idx == data_disk_idx:
                    # Use new data
                    padded = bytearray(self.block_size)
                    padded[: len(data)] = data
                    stripe_buffers.append(padded)
                else:
                    if d.is_online:
                        stripe_buffers.append(d.read_block(stripe_idx))
                    else:
                        stripe_buffers.append(bytearray(self.block_size))

            parity = xor_multiple(stripe_buffers, self.block_size)
            self.parity_disk.write_block(stripe_idx, parity, is_parity=True)

    def rebuild_disk(self, disk_id: int) -> None:
        """Reconstruct failed disk data using XOR of all other disks."""
        if self.failed_disks_count > 1:
            raise RAIDFailedException("Não é possível reconstruir: mais de um disco falho no RAID 4.")

        target = next((d for d in self.disks if d.disk_id == disk_id), None)
        if target is None:
            raise ValueError(f"Disco {disk_id} não encontrado.")

        target.recover()
        for stripe_idx in range(self.disk_capacity):
            other_buffers = [
                d.read_block(stripe_idx) for d in self.disks if d.disk_id != disk_id
            ]
            reconstructed = xor_multiple(other_buffers, self.block_size)
            is_parity_disk = target == self.parity_disk
            target.write_block(stripe_idx, reconstructed, is_parity=is_parity_disk)


class RAID5Controller(RAIDController):
    """RAID 5 (Distributed Rotating Parity) controller.

    Data and XOR parity are distributed in a rotating fashion across all disks.
    Tolerates 1 disk failure.
    """

    def __init__(self, disks: List[PhysicalDisk], block_size: int = 4096):
        if len(disks) < 3:
            raise ValueError("RAID 5 requer no mínimo 3 discos físicos.")
        super().__init__(disks, block_size)

    @property
    def level(self) -> RAIDLevel:
        return RAIDLevel.RAID_5

    @property
    def logical_capacity(self) -> int:
        return (self.num_disks - 1) * self.disk_capacity

    @property
    def status(self) -> RAIDStatus:
        if self.failed_disks_count == 0:
            return RAIDStatus.OPTIMAL
        if self.failed_disks_count == 1:
            return RAIDStatus.DEGRADED
        return RAIDStatus.FAILED

    def _get_parity_disk_idx(self, stripe_idx: int) -> int:
        """Rotating parity placement: Left-Symmetric rotation."""
        return (self.num_disks - 1 - (stripe_idx % self.num_disks))

    def _map_lba(self, lba: int) -> Tuple[int, int, int]:
        """Map LBA to (disk_idx, physical_block_idx, parity_disk_idx)."""
        data_disks_per_stripe = self.num_disks - 1
        stripe_idx = lba // data_disks_per_stripe
        col = lba % data_disks_per_stripe

        parity_disk_idx = self._get_parity_disk_idx(stripe_idx)

        # Map data columns to non-parity disks in this stripe
        available_data_disks = [d for d in range(self.num_disks) if d != parity_disk_idx]
        disk_idx = available_data_disks[col]

        return disk_idx, stripe_idx, parity_disk_idx

    def read_block(self, lba: int) -> bytearray:
        if not (0 <= lba < self.logical_capacity):
            raise IndexError(f"LBA {lba} fora dos limites do RAID 5 [0, {self.logical_capacity - 1}].")

        if self.failed_disks_count >= 2:
            raise RAIDFailedException("RAID 5 falhou: 2 ou mais discos estão offline.")

        disk_idx, stripe_idx, _ = self._map_lba(lba)
        target_disk = self.disks[disk_idx]

        if target_disk.is_online:
            return target_disk.read_block(stripe_idx)

        # On-the-fly reconstruction: XOR of all surviving disks in this stripe
        surviving_buffers = [
            d.read_block(stripe_idx)
            for idx, d in enumerate(self.disks)
            if idx != disk_idx
        ]
        return xor_multiple(surviving_buffers, self.block_size)

    def write_block(self, lba: int, data: bytes | bytearray) -> None:
        if not (0 <= lba < self.logical_capacity):
            raise IndexError(f"LBA {lba} fora dos limites do RAID 5 [0, {self.logical_capacity - 1}].")

        if self.failed_disks_count >= 2:
            raise RAIDFailedException("RAID 5 falhou: 2 ou mais discos estão offline.")

        disk_idx, stripe_idx, parity_disk_idx = self._map_lba(lba)
        target_disk = self.disks[disk_idx]
        parity_disk = self.disks[parity_disk_idx]

        # 1. Write data if target disk is online
        if target_disk.is_online:
            target_disk.write_block(stripe_idx, data)

        # 2. Recalculate parity if parity disk is online
        if parity_disk.is_online:
            stripe_buffers: List[bytearray] = []
            for d_idx, d in enumerate(self.disks):
                if d_idx == parity_disk_idx:
                    continue
                if d_idx == disk_idx:
                    # New data payload
                    padded = bytearray(self.block_size)
                    padded[: len(data)] = data
                    stripe_buffers.append(padded)
                else:
                    if d.is_online:
                        stripe_buffers.append(d.read_block(stripe_idx))
                    else:
                        stripe_buffers.append(bytearray(self.block_size))

            parity = xor_multiple(stripe_buffers, self.block_size)
            parity_disk.write_block(stripe_idx, parity, is_parity=True)

    def rebuild_disk(self, disk_id: int) -> None:
        """Reconstruct failed disk in RAID 5 using XOR across surviving members."""
        if self.failed_disks_count > 1:
            raise RAIDFailedException("Não é possível reconstruir: mais de um disco falho no RAID 5.")

        target = next((d for d in self.disks if d.disk_id == disk_id), None)
        if target is None:
            raise ValueError(f"Disco {disk_id} não encontrado.")

        target_idx = self.disks.index(target)
        target.recover()

        for stripe_idx in range(self.disk_capacity):
            other_buffers = [
                d.read_block(stripe_idx)
                for idx, d in enumerate(self.disks)
                if idx != target_idx
            ]
            reconstructed = xor_multiple(other_buffers, self.block_size)
            is_parity = (target_idx == self._get_parity_disk_idx(stripe_idx))
            target.write_block(stripe_idx, reconstructed, is_parity=is_parity)


class RAIDFactory:
    """Factory to instantiate configured RAID controllers with simulated physical disks."""

    @staticmethod
    def create(
        level: RAIDLevel,
        num_disks: int,
        disk_capacity: int = 16,
        block_size: int = 4096,
    ) -> RAIDController:
        disks = [
            PhysicalDisk(disk_id=i, capacity_blocks=disk_capacity, block_size=block_size)
            for i in range(num_disks)
        ]
        if level == RAIDLevel.RAID_0:
            return RAID0Controller(disks, block_size=block_size)
        if level == RAIDLevel.RAID_1:
            return RAID1Controller(disks, block_size=block_size)
        if level == RAIDLevel.RAID_4:
            return RAID4Controller(disks, block_size=block_size)
        if level == RAIDLevel.RAID_5:
            return RAID5Controller(disks, block_size=block_size)
        raise ValueError(f"Nível RAID não suportado: {level}")
