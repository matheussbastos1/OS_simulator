"""Unit tests for disk arm scheduling algorithms: FCFS, SSTF, SCAN, and C-SCAN (Incremento 2)."""

import unittest

from os_simulator.io.request import IOOperationType, IORequest
from os_simulator.io.scheduler import (
    CSCANScheduler,
    DiskDirection,
    FCFSScheduler,
    SCANScheduler,
    SSTFScheduler,
)


class TestDiskSchedulers(unittest.TestCase):
    """Test suite for disk arm schedulers and seek metrics."""

    def test_sstf_ground_truth_scenario(self):
        """Official Scenario IO-001 (Ground Truth):
        - Initial Head: 53
        - Queue: [98, 183, 37, 122, 14]
        - Expected Order: 53 → 37 → 14 → 98 → 122 → 183
        - Expected Total Seek: 208 tracks
        """
        queue = [98, 183, 37, 122, 14]
        scheduler = SSTFScheduler(initial_head=53, min_track=0, max_track=199)
        metrics = scheduler.schedule_tracks(queue)

        self.assertEqual(metrics.initial_head, 53)
        self.assertEqual(metrics.service_order, [37, 14, 98, 122, 183])
        self.assertEqual(metrics.total_seek_distance, 208)
        self.assertEqual(metrics.final_head, 183)
        self.assertEqual(metrics.requests_serviced, 5)

        # Verify individual step distances: 16, 23, 84, 24, 61
        step_dists = [s.distance for s in metrics.steps]
        self.assertEqual(step_dists, [16, 23, 84, 24, 61])
        self.assertEqual(sum(step_dists), 208)

    def test_fcfs_scheduler(self):
        """FCFS must process requests in strict arrival order."""
        queue = [98, 183, 37, 122, 14]
        scheduler = FCFSScheduler(initial_head=53)
        metrics = scheduler.schedule_tracks(queue)

        self.assertEqual(metrics.service_order, [98, 183, 37, 122, 14])
        # |98-53|=45, |183-98|=85, |37-183|=146, |122-37|=85, |14-122|=108 -> 469
        self.assertEqual(metrics.total_seek_distance, 469)
        self.assertEqual(metrics.final_head, 14)
        self.assertEqual(metrics.requests_serviced, 5)

    def test_scan_scheduler(self):
        """SCAN moves up to 199, reverses, and services remaining down to 14."""
        queue = [98, 183, 37, 122, 14]
        scheduler = SCANScheduler(initial_head=53, min_track=0, max_track=199, direction=DiskDirection.UP)
        metrics = scheduler.schedule_tracks(queue)

        # Above 53: 98, 122, 183, reaches max boundary 199, then reverses: 37, 14
        self.assertEqual(metrics.service_order, [98, 122, 183, 37, 14])
        # (199 - 53) + (199 - 14) = 146 + 185 = 331
        self.assertEqual(metrics.total_seek_distance, 331)
        self.assertEqual(metrics.final_head, 14)

    def test_cscan_scheduler(self):
        """C-SCAN moves up to 199, jumps to 0 without servicing, and continues up to 37."""
        queue = [98, 183, 37, 122, 14]
        scheduler = CSCANScheduler(initial_head=53, min_track=0, max_track=199)
        metrics = scheduler.schedule_tracks(queue)

        # Above 53: 98, 122, 183, hits 199, jumps to 0, then services: 14, 37
        self.assertEqual(metrics.service_order, [98, 122, 183, 14, 37])
        # (199 - 53) + (199 - 0) + (37 - 0) = 146 + 199 + 37 = 382
        self.assertEqual(metrics.total_seek_distance, 382)
        self.assertEqual(metrics.final_head, 37)

    def test_sstf_tie_breaking(self):
        """SSTF must deterministically break ties by preferring the lower track number."""
        # Head at 50, requests at 40 and 60 (both distance 10)
        queue = [60, 40]
        scheduler = SSTFScheduler(initial_head=50)
        metrics = scheduler.schedule_tracks(queue)

        # 40 has smaller track number -> services 40 first, then 60
        self.assertEqual(metrics.service_order, [40, 60])
        # |40 - 50| = 10, |60 - 40| = 20 -> total: 30
        self.assertEqual(metrics.total_seek_distance, 30)

    def test_empty_queue_all_schedulers(self):
        """All schedulers should cleanly handle an empty request queue."""
        for sched_cls in [FCFSScheduler, SSTFScheduler, SCANScheduler, CSCANScheduler]:
            scheduler = sched_cls(initial_head=50)
            metrics = scheduler.schedule([])
            self.assertEqual(metrics.total_seek_distance, 0)
            self.assertEqual(metrics.requests_serviced, 0)
            self.assertEqual(metrics.service_order, [])
            self.assertEqual(metrics.final_head, 50)

    def test_formatted_metrics_summary(self):
        scheduler = SSTFScheduler(initial_head=53)
        metrics = scheduler.schedule_tracks([98, 183, 37, 122, 14])
        report = metrics.format_summary()

        self.assertIn("RELATÓRIO DE ESCALONAMENTO DE DISCO", report)
        self.assertIn("208 trilhas", report)
        self.assertIn("53 → 37 → 14 → 98 → 122 → 183", report)


if __name__ == "__main__":
    unittest.main()
