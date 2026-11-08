"""Disk arm scheduling algorithms: FCFS, SSTF, SCAN, and C-SCAN."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from os_simulator.io.request import IOOperationType, IORequest


class DiskDirection(str, Enum):
    """Direction of head movement."""
    UP = "UP"
    DOWN = "DOWN"


@dataclass
class SeekStep:
    """Represents a single head movement step."""
    from_track: int
    to_track: int
    distance: int
    request_id: Optional[int] = None
    is_return_jump: bool = False  # True for C-SCAN return to boundary without servicing


@dataclass
class SeekMetrics:
    """Metrics and statistics for a disk scheduling run."""
    initial_head: int
    final_head: int
    original_queue: List[int]
    service_order: List[int]
    steps: List[SeekStep] = field(default_factory=list)
    total_seek_distance: int = 0
    requests_serviced: int = 0

    def format_summary(self) -> str:
        """Render diagnostic report matching official academic format."""
        seq_str = " → ".join(str(t) for t in [self.initial_head] + self.service_order)
        lines = [
            "======================================================================",
            "                   RELATÓRIO DE ESCALONAMENTO DE DISCO",
            "======================================================================",
            f"Posição Inicial da Cabeça    : {self.initial_head}",
            f"Fila Original de Requisições : {self.original_queue}",
            f"Ordem de Atendimento         : {self.service_order}",
            f"Sequência Percorrida         : {seq_str}",
            f"Total de Trilhas Percorridas : {self.total_seek_distance} trilhas",
            f"Total de Requisições Servidas: {self.requests_serviced}",
            f"Posição Final da Cabeça      : {self.final_head}",
            "----------------------------------------------------------------------",
            "Passo a Passo de Movimentação:",
        ]
        for idx, step in enumerate(self.steps, 1):
            jump_tag = " (Retorno C-SCAN sem serviço)" if step.is_return_jump else ""
            lines.append(
                f"  Passo {idx:02d}: {step.from_track:3d} → {step.to_track:3d} | "
                f"Deslocamento: {step.distance:3d} trilhas{jump_tag}"
            )
        lines.append("======================================================================")
        return "\n".join(lines)


class DiskScheduler(ABC):
    """Abstract base class for disk head schedulers."""

    def __init__(
        self,
        initial_head: int = 0,
        min_track: int = 0,
        max_track: int = 199,
        direction: DiskDirection = DiskDirection.UP,
    ):
        self.initial_head = initial_head
        self.current_head = initial_head
        self.min_track = min_track
        self.max_track = max_track
        self.direction = direction

    @property
    def name(self) -> str:
        """Name of the scheduling algorithm."""
        return self.__class__.__name__.replace("Scheduler", "")

    def set_head(self, track: int) -> None:
        """Update current head position."""
        self.current_head = track

    @abstractmethod
    def schedule(self, requests: List[IORequest]) -> SeekMetrics:
        """Schedule and service list of IORequests, returning seek metrics."""
        raise NotImplementedError

    def schedule_tracks(self, tracks: List[int]) -> SeekMetrics:
        """Helper to schedule raw track numbers as synthetic read requests."""
        synthetic_requests = [
            IORequest(operation=IOOperationType.READ, block_id=t * 4, track=t, request_id=idx + 1)
            for idx, t in enumerate(tracks)
        ]
        return self.schedule(synthetic_requests)


class FCFSScheduler(DiskScheduler):
    """First-Come, First-Served (FCFS) disk scheduler."""

    def schedule(self, requests: List[IORequest]) -> SeekMetrics:
        curr = self.current_head
        total_dist = 0
        steps: List[SeekStep] = []
        service_order: List[int] = []
        original_queue = [r.track for r in requests]

        for req in requests:
            dist = abs(req.track - curr)
            total_dist += dist
            steps.append(SeekStep(from_track=curr, to_track=req.track, distance=dist, request_id=req.request_id))
            curr = req.track
            service_order.append(req.track)
            req.mark_completed(seek_distance=dist)

        self.current_head = curr
        return SeekMetrics(
            initial_head=self.initial_head,
            final_head=curr,
            original_queue=original_queue,
            service_order=service_order,
            steps=steps,
            total_seek_distance=total_dist,
            requests_serviced=len(requests),
        )


class SSTFScheduler(DiskScheduler):
    """Shortest Seek Time First (SSTF) disk scheduler.

    Deterministic tie-breaking rule:
    When two requests are equidistant from current head position, the one with
    the lower track number is serviced first; if still tied, original queue order.
    """

    def schedule(self, requests: List[IORequest]) -> SeekMetrics:
        curr = self.current_head
        total_dist = 0
        steps: List[SeekStep] = []
        service_order: List[int] = []
        original_queue = [r.track for r in requests]
        pending = list(requests)

        while pending:
            # Pick request with minimum distance to curr
            # Tie-breaker: (distance, track, arrival_index)
            best_req = min(
                pending,
                key=lambda r: (abs(r.track - curr), r.track, pending.index(r)),
            )
            pending.remove(best_req)

            dist = abs(best_req.track - curr)
            total_dist += dist
            steps.append(SeekStep(from_track=curr, to_track=best_req.track, distance=dist, request_id=best_req.request_id))
            curr = best_req.track
            service_order.append(best_req.track)
            best_req.mark_completed(seek_distance=dist)

        self.current_head = curr
        return SeekMetrics(
            initial_head=self.initial_head,
            final_head=curr,
            original_queue=original_queue,
            service_order=service_order,
            steps=steps,
            total_seek_distance=total_dist,
            requests_serviced=len(requests),
        )


class SCANScheduler(DiskScheduler):
    """SCAN (Elevator) disk scheduler.

    Moves in the active direction servicing requests. If there are requests
    in the opposite direction, moves to the physical disk boundary (max_track or min_track),
    reverses direction, and services remaining requests.
    """

    def schedule(self, requests: List[IORequest]) -> SeekMetrics:
        curr = self.current_head
        total_dist = 0
        steps: List[SeekStep] = []
        service_order: List[int] = []
        original_queue = [r.track for r in requests]

        if not requests:
            return SeekMetrics(
                initial_head=self.initial_head,
                final_head=curr,
                original_queue=original_queue,
                service_order=[],
                steps=[],
                total_seek_distance=0,
                requests_serviced=0,
            )

        if self.direction == DiskDirection.UP:
            above = sorted([r for r in requests if r.track >= curr], key=lambda r: r.track)
            below = sorted([r for r in requests if r.track < curr], key=lambda r: r.track, reverse=True)

            # Service ascending
            for req in above:
                dist = abs(req.track - curr)
                total_dist += dist
                steps.append(SeekStep(from_track=curr, to_track=req.track, distance=dist, request_id=req.request_id))
                curr = req.track
                service_order.append(req.track)
                req.mark_completed(seek_distance=dist)

            # If there are requests below, elevator hits max_track and reverses
            if below:
                if curr < self.max_track:
                    dist = abs(self.max_track - curr)
                    total_dist += dist
                    steps.append(SeekStep(from_track=curr, to_track=self.max_track, distance=dist))
                    curr = self.max_track

                for req in below:
                    dist = abs(req.track - curr)
                    total_dist += dist
                    steps.append(SeekStep(from_track=curr, to_track=req.track, distance=dist, request_id=req.request_id))
                    curr = req.track
                    service_order.append(req.track)
                    req.mark_completed(seek_distance=dist)

        else:  # DOWN
            below = sorted([r for r in requests if r.track <= curr], key=lambda r: r.track, reverse=True)
            above = sorted([r for r in requests if r.track > curr], key=lambda r: r.track)

            for req in below:
                dist = abs(req.track - curr)
                total_dist += dist
                steps.append(SeekStep(from_track=curr, to_track=req.track, distance=dist, request_id=req.request_id))
                curr = req.track
                service_order.append(req.track)
                req.mark_completed(seek_distance=dist)

            if above:
                if curr > self.min_track:
                    dist = abs(self.min_track - curr)
                    total_dist += dist
                    steps.append(SeekStep(from_track=curr, to_track=self.min_track, distance=dist))
                    curr = self.min_track

                for req in above:
                    dist = abs(req.track - curr)
                    total_dist += dist
                    steps.append(SeekStep(from_track=curr, to_track=req.track, distance=dist, request_id=req.request_id))
                    curr = req.track
                    service_order.append(req.track)
                    req.mark_completed(seek_distance=dist)

        self.current_head = curr
        return SeekMetrics(
            initial_head=self.initial_head,
            final_head=curr,
            original_queue=original_queue,
            service_order=service_order,
            steps=steps,
            total_seek_distance=total_dist,
            requests_serviced=len(requests),
        )


class CSCANScheduler(DiskScheduler):
    """Circular SCAN (C-SCAN) disk scheduler.

    Services requests in one direction (ascending by default). Upon reaching the
    boundary, jumps to the opposite boundary (0) without servicing requests,
    and resumes servicing in ascending order.
    """

    def schedule(self, requests: List[IORequest]) -> SeekMetrics:
        curr = self.current_head
        total_dist = 0
        steps: List[SeekStep] = []
        service_order: List[int] = []
        original_queue = [r.track for r in requests]

        if not requests:
            return SeekMetrics(
                initial_head=self.initial_head,
                final_head=curr,
                original_queue=original_queue,
                service_order=[],
                steps=[],
                total_seek_distance=0,
                requests_serviced=0,
            )

        above = sorted([r for r in requests if r.track >= curr], key=lambda r: r.track)
        below = sorted([r for r in requests if r.track < curr], key=lambda r: r.track)

        # 1. Service above in ascending order
        for req in above:
            dist = abs(req.track - curr)
            total_dist += dist
            steps.append(SeekStep(from_track=curr, to_track=req.track, distance=dist, request_id=req.request_id))
            curr = req.track
            service_order.append(req.track)
            req.mark_completed(seek_distance=dist)

        # 2. If requests exist below, go to max_track, jump to min_track, and continue ascending
        if below:
            if curr < self.max_track:
                dist = abs(self.max_track - curr)
                total_dist += dist
                steps.append(SeekStep(from_track=curr, to_track=self.max_track, distance=dist))
                curr = self.max_track

            # Return jump to min_track
            jump_dist = abs(self.min_track - curr)
            total_dist += jump_dist
            steps.append(SeekStep(from_track=curr, to_track=self.min_track, distance=jump_dist, is_return_jump=True))
            curr = self.min_track

            # Service below in ascending order
            for req in below:
                dist = abs(req.track - curr)
                total_dist += dist
                steps.append(SeekStep(from_track=curr, to_track=req.track, distance=dist, request_id=req.request_id))
                curr = req.track
                service_order.append(req.track)
                req.mark_completed(seek_distance=dist)

        self.current_head = curr
        return SeekMetrics(
            initial_head=self.initial_head,
            final_head=curr,
            original_queue=original_queue,
            service_order=service_order,
            steps=steps,
            total_seek_distance=total_dist,
            requests_serviced=len(requests),
        )
