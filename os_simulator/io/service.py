"""I/O Manager orchestrating request queues, disk schedulers, and storage backends."""

from typing import Any, Dict, List, Optional

from os_simulator.io.queue import IOQueue
from os_simulator.io.request import (
    IOOperationType,
    IOPriority,
    IORequest,
    IORequestStatus,
)
from os_simulator.io.scheduler import (
    DiskScheduler,
    FCFSScheduler,
    SeekMetrics,
)


class IOManager:
    """Core I/O management service coordinating queues, schedulers, and device access."""

    def __init__(
        self,
        storage_backend: Any,
        scheduler: Optional[DiskScheduler] = None,
        sectors_per_track: int = 4,
    ):
        self.storage_backend = storage_backend
        self.scheduler: DiskScheduler = scheduler or FCFSScheduler(initial_head=0)
        self.queue = IOQueue()
        self.sectors_per_track = sectors_per_track

        # Cumulative metrics
        self.total_reads = 0
        self.total_writes = 0
        self.total_seek_tracks = 0
        self.history_metrics: List[SeekMetrics] = []

    def set_scheduler(self, scheduler: DiskScheduler) -> None:
        """Switch active disk arm scheduler."""
        scheduler.set_head(self.scheduler.current_head)
        self.scheduler = scheduler

    def dispatch_read(self, block_id: int, priority: IOPriority = IOPriority.NORMAL) -> bytearray:
        """Enqueue and execute a read request through scheduler and storage backend."""
        req = IORequest(
            operation=IOOperationType.READ,
            block_id=block_id,
            priority=priority,
            sectors_per_track=self.sectors_per_track,
        )
        self.queue.enqueue(req)

        # Process through active scheduler
        metrics = self.scheduler.schedule([req])
        self.total_seek_tracks += metrics.total_seek_distance
        self.total_reads += 1
        self.history_metrics.append(metrics)

        # Dispatch to storage backend
        try:
            if hasattr(self.storage_backend, "read_block"):
                data = self.storage_backend.read_block(block_id)
            elif hasattr(self.storage_backend, "read"):
                data = self.storage_backend.read(block_id)
            else:
                raise AttributeError("Storage backend não implementa read_block ou read.")

            req.mark_completed(result=data, seek_distance=metrics.total_seek_distance)
            return data
        except Exception as exc:
            req.mark_failed(str(exc))
            raise

    def dispatch_write(
        self,
        block_id: int,
        data: bytes | bytearray,
        priority: IOPriority = IOPriority.NORMAL,
    ) -> None:
        """Enqueue and execute a write request through scheduler and storage backend."""
        req = IORequest(
            operation=IOOperationType.WRITE,
            block_id=block_id,
            data=data,
            priority=priority,
            sectors_per_track=self.sectors_per_track,
        )
        self.queue.enqueue(req)

        # Process through active scheduler
        metrics = self.scheduler.schedule([req])
        self.total_seek_tracks += metrics.total_seek_distance
        self.total_writes += 1
        self.history_metrics.append(metrics)

        # Dispatch to storage backend
        try:
            if hasattr(self.storage_backend, "write_block"):
                self.storage_backend.write_block(block_id, data)
            elif hasattr(self.storage_backend, "write"):
                self.storage_backend.write(block_id, data)
            else:
                raise AttributeError("Storage backend não implementa write_block ou write.")

            req.mark_completed(seek_distance=metrics.total_seek_distance)
        except Exception as exc:
            req.mark_failed(str(exc))
            raise

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Return diagnostic metrics of I/O throughput and arm movements."""
        return {
            "scheduler": self.scheduler.__class__.__name__,
            "current_head": self.scheduler.current_head,
            "total_reads": self.total_reads,
            "total_writes": self.total_writes,
            "total_requests": self.total_reads + self.total_writes,
            "total_seek_tracks": self.total_seek_tracks,
            "pending_queue_size": len(self.queue),
        }

    def format_io_status(self) -> str:
        """Format human-readable diagnostic report for CLI."""
        metrics = self.get_metrics_summary()
        backend_name = self.storage_backend.__class__.__name__
        lines = [
            "======================================================================",
            "                     DIAGNÓSTICO DO SUBSISTEMA DE E/S",
            "======================================================================",
            f"Escalonador Ativo            : {metrics['scheduler']}",
            f"Posição Atual da Cabeça      : Trilha {metrics['current_head']}",
            f"Dispositivo de Armazenamento : {backend_name}",
            f"Total de Operações de Leitura: {metrics['total_reads']}",
            f"Total de Operações de Escrita: {metrics['total_writes']}",
            f"Total de Requisições de E/S  : {metrics['total_requests']}",
            f"Total de Trilhas Percorridas : {metrics['total_seek_tracks']} trilhas",
            f"Requisições Pendentes na Fila: {metrics['pending_queue_size']}",
            "======================================================================",
        ]
        return "\n".join(lines)
