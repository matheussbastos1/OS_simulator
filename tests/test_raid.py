"""Unit tests for Physical Disks and RAID controllers 0, 1, 4, and 5 (Incremento 4)."""

import unittest

from os_simulator.storage.physical_disk import DiskFailureException, PhysicalDisk
from os_simulator.storage.raid import (
    RAID0Controller,
    RAID1Controller,
    RAID4Controller,
    RAID5Controller,
    RAIDDegradedException,
    RAIDFactory,
    RAIDFailedException,
    RAIDLevel,
    RAIDStatus,
    xor_bytes,
)


class TestPhysicalDiskAndRAID(unittest.TestCase):
    """Test suite for physical disk hardware simulation and RAID levels."""

    def test_physical_disk_lifecycle(self):
        disk = PhysicalDisk(disk_id=0, capacity_blocks=16, block_size=1024, sectors_per_track=4)
        self.assertEqual(disk.total_tracks, 4)
        self.assertTrue(disk.is_online)

        disk.write_block(0, b"Sector_0")
        self.assertEqual(disk.read_block(0)[:8], b"Sector_0")
        self.assertEqual(disk.get_track_for_block(7), 1)

        # Failure simulation
        disk.fail()
        self.assertFalse(disk.is_online)
        with self.assertRaises(DiskFailureException):
            disk.read_block(0)
        with self.assertRaises(DiskFailureException):
            disk.write_block(0, b"Data")

        disk.recover()
        self.assertTrue(disk.is_online)
        self.assertEqual(disk.read_block(0)[:8], b"Sector_0")

    def test_raid0_striping_and_loss(self):
        """RAID 0 strips blocks across disks; fails if any disk fails."""
        raid = RAIDFactory.create(RAIDLevel.RAID_0, num_disks=2, disk_capacity=8, block_size=1024)
        self.assertEqual(raid.logical_capacity, 16)
        self.assertEqual(raid.status, RAIDStatus.OPTIMAL)

        d0_payload = b"Block0_on_Disk0"
        d1_payload = b"Block1_on_Disk1"

        raid.write_block(0, d0_payload)
        raid.write_block(1, d1_payload)

        # LBA 0 on disk 0; LBA 1 on disk 1
        self.assertEqual(raid.disks[0].read_block(0)[:len(d0_payload)], d0_payload)
        self.assertEqual(raid.disks[1].read_block(0)[:len(d1_payload)], d1_payload)

        # Fail Disk 1 -> Entire array fails, blocking further I/O
        raid.fail_disk(1)
        self.assertEqual(raid.status, RAIDStatus.FAILED)
        with self.assertRaises(RAIDFailedException):
            raid.read_block(0)  # Blocked
        with self.assertRaises(RAIDFailedException):
            raid.read_block(1)  # Blocked
        with self.assertRaises(RAIDFailedException):
            raid.write_block(0, b"New")  # Blocked

    def test_raid1_mirroring_and_redundancy(self):
        """RAID 1 duplicates data; tolerates failure of mirror disk."""
        raid = RAIDFactory.create(RAIDLevel.RAID_1, num_disks=2, disk_capacity=8, block_size=1024)
        self.assertEqual(raid.logical_capacity, 8)

        payload = b"Mirror_Payload"
        raid.write_block(3, payload)

        # Both disks hold the data
        self.assertEqual(raid.disks[0].read_block(3)[:len(payload)], payload)
        self.assertEqual(raid.disks[1].read_block(3)[:len(payload)], payload)

        # Fail Disk 0 -> Array is DEGRADED but reads succeed from Disk 1
        raid.fail_disk(0)
        self.assertEqual(raid.status, RAIDStatus.DEGRADED)
        self.assertEqual(raid.read_block(3)[:len(payload)], payload)

        # Rebuild Disk 0
        raid.rebuild_disk(0)
        self.assertEqual(raid.status, RAIDStatus.OPTIMAL)
        self.assertEqual(raid.disks[0].read_block(3)[:len(payload)], payload)

    def test_raid4_dedicated_parity_and_reconstruction(self):
        """RAID 4: 2 data disks + 1 dedicated parity disk."""
        raid = RAIDFactory.create(RAIDLevel.RAID_4, num_disks=3, disk_capacity=8, block_size=1024)
        self.assertEqual(raid.logical_capacity, 16)  # 2 data disks * 8

        data0 = b"A" * 100
        data1 = b"B" * 100

        raid.write_block(0, data0)  # Disk 0
        raid.write_block(1, data1)  # Disk 1

        # Expected parity: data0 ^ data1
        expected_parity = xor_bytes(data0, data1)
        actual_parity = raid.disks[2].read_block(0)  # Parity disk 2, stripe 0
        self.assertEqual(actual_parity[:100], expected_parity[:100])

        # Fail Data Disk 1
        raid.fail_disk(1)
        self.assertEqual(raid.status, RAIDStatus.DEGRADED)

        # Read reconstructed data1 on-the-fly via XOR of Disk 0 and Parity Disk 2
        reconstructed = raid.read_block(1)
        self.assertEqual(reconstructed[:100], data1)

        # Rebuild Disk 1
        raid.rebuild_disk(1)
        self.assertEqual(raid.status, RAIDStatus.OPTIMAL)
        self.assertEqual(raid.disks[1].read_block(0)[:100], data1)

    def test_raid5_ground_truth_scenario(self):
        """Official Scenario IO-002:
        - 3 disks, 4 KB blocks.
        - Stripe 0: Disk 0 = D0, Disk 1 = D1, Disk 2 = Parity = D0 ^ D1.
        - Inject failure: Disk 1 failed.
        - Read D1: reconstructed on-the-fly via D0 ^ P.
        - Rebuild Disk 1: recovered and identical.
        """
        raid = RAIDFactory.create(RAIDLevel.RAID_5, num_disks=3, disk_capacity=8, block_size=4096)
        self.assertEqual(raid.logical_capacity, 16)  # 2 data * 8 = 16

        d0 = b"D0_DATA_STREAM_" * 10
        d1 = b"D1_DATA_STREAM_" * 10

        raid.write_block(0, d0)
        raid.write_block(1, d1)

        # Verify parity calculation at stripe 0 (Disk 2 has parity)
        expected_p = xor_bytes(d0, d1)
        parity_on_disk2 = raid.disks[2].read_block(0)
        self.assertEqual(parity_on_disk2[:len(d0)], expected_p)

        # Inject failure on Disk 1
        raid.fail_disk(1)
        self.assertEqual(raid.status, RAIDStatus.DEGRADED)

        # Read D1 from degraded array -> MUST be reconstructed on-the-fly
        read_d1 = raid.read_block(1)
        self.assertEqual(read_d1[:len(d1)], d1)

        # Rebuild Disk 1
        raid.rebuild_disk(1)
        self.assertEqual(raid.status, RAIDStatus.OPTIMAL)
        self.assertEqual(raid.disks[1].read_block(0)[:len(d1)], d1)

    def test_raid5_multiple_stripes_rotation(self):
        """Verify parity rotation across stripes in RAID 5."""
        raid = RAIDFactory.create(RAIDLevel.RAID_5, num_disks=3, disk_capacity=6, block_size=1024)

        # Stripe 0 (LBA 0, 1): Parity on Disk 2 (Left-Symmetric)
        # Stripe 1 (LBA 2, 3): Parity on Disk 1
        # Stripe 2 (LBA 4, 5): Parity on Disk 0
        raid.write_block(0, b"LBA_0")
        raid.write_block(1, b"LBA_1")
        raid.write_block(2, b"LBA_2")
        raid.write_block(3, b"LBA_3")
        raid.write_block(4, b"LBA_4")
        raid.write_block(5, b"LBA_5")

        # Fail Disk 0
        raid.fail_disk(0)
        self.assertEqual(raid.status, RAIDStatus.DEGRADED)

        # Reading LBAs 0, 2, 4 must all succeed (LBA 0 and 4 were on Disk 0, reconstructed on-the-fly!)
        self.assertTrue(raid.read_block(0).startswith(b"LBA_0"))
        self.assertTrue(raid.read_block(2).startswith(b"LBA_2"))
        self.assertTrue(raid.read_block(4).startswith(b"LBA_4"))

        # Rebuild Disk 0
        raid.rebuild_disk(0)
        self.assertEqual(raid.status, RAIDStatus.OPTIMAL)

    def test_degraded_write_preserves_offline_data_raid4_and_raid5(self):
        """Verify that writing to an online disk in degraded mode does NOT corrupt
        the data of the offline disk in RAID 5 and RAID 4 (Hotfix item 1).
        """
        # --- RAID 5 ---
        r5 = RAIDFactory.create(RAIDLevel.RAID_5, num_disks=3, disk_capacity=8, block_size=1024)
        d0 = b"AAAA" * 20
        d1 = b"BBBB" * 20
        d1_updated = b"CCCC" * 20

        r5.write_block(0, d0)
        r5.write_block(1, d1)

        # Fail Disk 0
        r5.fail_disk(0)
        self.assertEqual(r5.status, RAIDStatus.DEGRADED)

        # Write to online Disk 1
        r5.write_block(1, d1_updated)
        self.assertTrue(r5.read_block(1).startswith(d1_updated))

        # Read offline Disk 0 on-the-fly -> MUST still be d0 (not wiped/zeroed!)
        reconstructed_d0 = r5.read_block(0)
        self.assertTrue(reconstructed_d0.startswith(d0), f"Expected d0 but got {reconstructed_d0[:20]}")

        # Rebuild Disk 0 -> must permanently restore d0
        r5.rebuild_disk(0)
        self.assertEqual(r5.status, RAIDStatus.OPTIMAL)
        self.assertTrue(r5.read_block(0).startswith(d0))
        self.assertTrue(r5.read_block(1).startswith(d1_updated))

        # --- RAID 4 ---
        r4 = RAIDFactory.create(RAIDLevel.RAID_4, num_disks=3, disk_capacity=8, block_size=1024)
        r4.write_block(0, d0)
        r4.write_block(1, d1)

        # Fail Disk 0
        r4.fail_disk(0)
        self.assertEqual(r4.status, RAIDStatus.DEGRADED)

        # Write to online Disk 1
        r4.write_block(1, d1_updated)
        self.assertTrue(r4.read_block(1).startswith(d1_updated))

        # Read offline Disk 0 on-the-fly -> MUST still be d0
        self.assertTrue(r4.read_block(0).startswith(d0))

        # Rebuild Disk 0
        r4.rebuild_disk(0)
        self.assertEqual(r4.status, RAIDStatus.OPTIMAL)
        self.assertTrue(r4.read_block(0).startswith(d0))

    def test_raid5_write_to_failed_disk_lba_updates_parity_and_rebuilds(self):
        """Verify that writing directly to an LBA whose target disk is offline updates parity,
        allowing on-the-fly read and subsequent rebuild of the newly written data (Hotfix item 1).
        """
        r5 = RAIDFactory.create(RAIDLevel.RAID_5, num_disks=3, disk_capacity=8, block_size=1024)
        r5.write_block(0, b"OLD_D0")
        r5.write_block(1, b"DATA_D1")

        # Fail Disk 0 (holds LBA 0)
        r5.fail_disk(0)
        self.assertEqual(r5.status, RAIDStatus.DEGRADED)

        # Write new data to LBA 0 while Disk 0 is offline
        new_payload = b"NEW_DATA_ON_FAILED_DISK"
        r5.write_block(0, new_payload)

        # Read on-the-fly must reconstruct the newly written payload via parity
        self.assertTrue(r5.read_block(0).startswith(new_payload))

        # Rebuild Disk 0
        r5.rebuild_disk(0)
        self.assertEqual(r5.status, RAIDStatus.OPTIMAL)
        self.assertTrue(r5.read_block(0).startswith(new_payload))


if __name__ == "__main__":
    unittest.main()
