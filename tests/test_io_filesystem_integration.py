"""Integration tests verifying full stack: Filesystem -> IOBlockDeviceAdapter -> IOManager -> RAID/SSD (Incremento 5)."""

import unittest

from os_simulator.core.types import AllocationStrategy
from os_simulator.filesystem.service import FileSystemService
from os_simulator.io.scheduler import CSCANScheduler, FCFSScheduler, SCANScheduler, SSTFScheduler
from os_simulator.io.service import IOManager
from os_simulator.io.ssd import SSDDevice
from os_simulator.storage.adapter import IOBlockDeviceAdapter
from os_simulator.storage.physical_disk import PhysicalDisk
from os_simulator.storage.raid import RAIDFactory, RAIDLevel, RAIDStatus


class TestIOFilesystemIntegration(unittest.TestCase):
    """End-to-end integration tests between Filesystem and I/O-RAID storage layer."""

    def test_filesystem_with_raw_physical_disk_and_sstf(self):
        """Filesystem operating over a single physical disk with SSTF scheduler."""
        disk = PhysicalDisk(disk_id=0, capacity_blocks=16, block_size=4096)
        io_manager = IOManager(storage_backend=disk, scheduler=SSTFScheduler(initial_head=0))
        adapter = IOBlockDeviceAdapter(io_manager=io_manager, logical_capacity=16, block_size=4096)
        fs = FileSystemService(block_device=adapter, default_strategy=AllocationStrategy.INDEXED)

        fs.mkdir("/dados")
        payload = "Conteúdo gravado via IOManager e PhysicalDisk puro."
        fs.write_file("/dados/log.txt", payload)

        read_back = fs.read_file("/dados/log.txt")
        self.assertEqual(read_back, payload)
        self.assertGreater(io_manager.total_writes, 0)
        self.assertGreater(io_manager.total_reads, 0)
        self.assertEqual(disk.write_count, io_manager.total_writes)

    def test_filesystem_with_raid0(self):
        """Filesystem operating over RAID 0 array."""
        raid0 = RAIDFactory.create(RAIDLevel.RAID_0, num_disks=2, disk_capacity=8, block_size=4096)
        io_manager = IOManager(storage_backend=raid0, scheduler=FCFSScheduler())
        adapter = IOBlockDeviceAdapter(io_manager=io_manager)
        fs = FileSystemService(block_device=adapter, default_strategy=AllocationStrategy.CONTIGUOUS)

        payload = "Arquivo distribuído em striping RAID 0"
        fs.write_file("/raid0.txt", payload)

        self.assertEqual(fs.read_file("/raid0.txt"), payload)
        self.assertEqual(raid0.status, RAIDStatus.OPTIMAL)

    def test_filesystem_with_raid1_and_fault_tolerance(self):
        """Filesystem operating over RAID 1; survives member disk failure and rebuilds."""
        raid1 = RAIDFactory.create(RAIDLevel.RAID_1, num_disks=2, disk_capacity=8, block_size=4096)
        io_manager = IOManager(storage_backend=raid1)
        adapter = IOBlockDeviceAdapter(io_manager=io_manager)
        fs = FileSystemService(block_device=adapter, default_strategy=AllocationStrategy.INDEXED)

        payload = "Dados protegidos por espelhamento RAID 1."
        fs.write_file("/espelho.txt", payload)

        # Fail Disk 0 -> File must still be read cleanly from Disk 1
        raid1.fail_disk(0)
        self.assertEqual(raid1.status, RAIDStatus.DEGRADED)
        self.assertEqual(fs.read_file("/espelho.txt"), payload)

        # Rebuild Disk 0 -> Array recovers to OPTIMAL
        raid1.rebuild_disk(0)
        self.assertEqual(raid1.status, RAIDStatus.OPTIMAL)
        self.assertEqual(fs.read_file("/espelho.txt"), payload)

    def test_filesystem_with_raid4_and_reconstruction(self):
        """Filesystem operating over RAID 4 with dedicated parity."""
        raid4 = RAIDFactory.create(RAIDLevel.RAID_4, num_disks=3, disk_capacity=8, block_size=4096)
        io_manager = IOManager(storage_backend=raid4)
        adapter = IOBlockDeviceAdapter(io_manager=io_manager)
        fs = FileSystemService(block_device=adapter, default_strategy=AllocationStrategy.LINKED_FAT)

        payload = "Dados protegidos por paridade dedicada RAID 4."
        fs.write_file("/raid4.txt", payload)

        # Fail data disk 0
        raid4.fail_disk(0)
        self.assertEqual(raid4.status, RAIDStatus.DEGRADED)
        self.assertEqual(fs.read_file("/raid4.txt"), payload)

        # Rebuild data disk 0
        raid4.rebuild_disk(0)
        self.assertEqual(raid4.status, RAIDStatus.OPTIMAL)
        self.assertEqual(fs.read_file("/raid4.txt"), payload)

    def test_filesystem_with_raid5_and_on_the_fly_rebuild(self):
        """Filesystem operating over RAID 5; survives disk failure and rebuilds."""
        raid5 = RAIDFactory.create(RAIDLevel.RAID_5, num_disks=3, disk_capacity=8, block_size=4096)
        io_manager = IOManager(storage_backend=raid5, scheduler=SSTFScheduler())
        adapter = IOBlockDeviceAdapter(io_manager=io_manager)
        fs = FileSystemService(block_device=adapter, default_strategy=AllocationStrategy.INDEXED)

        fs.mkdir("/sistema")
        payload = "Dados críticos com paridade distribuída RAID 5."
        fs.write_file("/sistema/banco.db", payload)

        # Fail disk 1
        raid5.fail_disk(1)
        self.assertEqual(raid5.status, RAIDStatus.DEGRADED)

        # Read must reconstruct on-the-fly via XOR
        self.assertEqual(fs.read_file("/sistema/banco.db"), payload)

        # Rebuild disk 1
        raid5.rebuild_disk(1)
        self.assertEqual(raid5.status, RAIDStatus.OPTIMAL)
        self.assertEqual(fs.read_file("/sistema/banco.db"), payload)

    def test_filesystem_with_ssd_wear_leveling(self):
        """Filesystem operating over an SSD device with active Wear Leveling."""
        ssd = SSDDevice(logical_capacity=16, overprovisioning=4, block_size=4096)
        io_manager = IOManager(storage_backend=ssd)
        adapter = IOBlockDeviceAdapter(io_manager=io_manager, logical_capacity=16, block_size=4096)
        fs = FileSystemService(block_device=adapter, default_strategy=AllocationStrategy.INDEXED)

        # Multiple overwrites to test wear leveling under filesystem operations
        for i in range(10):
            fs.write_file("/log.txt", f"Registro de log número {i:03d}")

        self.assertEqual(fs.read_file("/log.txt"), "Registro de log número 009")
        stats = ssd.get_wear_stats()
        self.assertGreater(stats["total_writes"], 5)
        self.assertLess(stats["std_dev_wear"], 2.0)
        # Verify SSD does not accumulate mechanical seek tracks (Hotfix item 3)
        self.assertEqual(io_manager.total_seek_tracks, 0)

    def test_io_manager_queue_cleanup_and_completed_history(self):
        """Verify that IOManager cleans up pending queue and records completed requests (Hotfix item 2)."""
        disk = PhysicalDisk(disk_id=0, capacity_blocks=8, block_size=1024)
        io_mgr = IOManager(storage_backend=disk)

        self.assertEqual(len(io_mgr.queue), 0)
        self.assertEqual(len(io_mgr.queue.get_completed_requests()), 0)

        # Dispatch write
        io_mgr.dispatch_write(0, b"TEST_PAYLOAD")
        self.assertEqual(len(io_mgr.queue), 0)
        self.assertEqual(len(io_mgr.queue.get_pending_requests()), 0)
        completed = io_mgr.queue.get_completed_requests()
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].block_id, 0)

        # Dispatch read
        data = io_mgr.dispatch_read(0)
        self.assertTrue(data.startswith(b"TEST_PAYLOAD"))
        self.assertEqual(len(io_mgr.queue), 0)
        self.assertEqual(len(io_mgr.queue.get_pending_requests()), 0)
        self.assertEqual(len(io_mgr.queue.get_completed_requests()), 2)

    def test_io_adapter_is_available_with_physical_disk_offline(self):
        """Verify that IOBlockDeviceAdapter.is_available() detects offline PhysicalDisk (Hotfix item 4)."""
        disk = PhysicalDisk(disk_id=0, capacity_blocks=8, block_size=1024)
        io_mgr = IOManager(storage_backend=disk)
        adapter = IOBlockDeviceAdapter(io_manager=io_mgr, logical_capacity=8, block_size=1024)

        self.assertTrue(adapter.is_available(0))

        # Fail disk
        disk.fail()
        self.assertFalse(adapter.is_available(0))

        # Recover disk
        disk.recover()
        self.assertTrue(adapter.is_available(0))


if __name__ == "__main__":
    unittest.main()
