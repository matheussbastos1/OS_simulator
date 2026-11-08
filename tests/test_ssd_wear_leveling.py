"""Unit tests for SSD simulation and Wear Leveling policies (Incremento 3)."""

import unittest

from os_simulator.io.ssd import SSDDevice, WearLevelingMode


class TestSSDWearLeveling(unittest.TestCase):
    """Test suite for SSD FTL mapping and Wear Leveling."""

    def test_wear_leveling_disabled_concentrates_wear(self):
        """Without wear leveling (NONE), updates to LBA 0 always hit PBA 0."""
        ssd = SSDDevice(
            logical_capacity=4,
            overprovisioning=2,
            wear_mode=WearLevelingMode.NONE,
        )

        # 30 writes to LBA 0
        for i in range(30):
            ssd.write(0, f"Update_{i}".encode("utf-8"))

        stats = ssd.get_wear_stats()
        # PBA 0 has 30 writes, other PBAs have 0
        self.assertEqual(stats["wear_map"][0], 30)
        self.assertEqual(stats["wear_map"][1], 0)
        self.assertEqual(stats["max_wear"], 30)
        self.assertEqual(stats["min_wear"], 0)
        self.assertGreater(stats["std_dev_wear"], 10.0)

        # Verify data readback
        self.assertTrue(ssd.read(0).startswith(b"Update_29"))

    def test_dynamic_wear_leveling_spreads_writes(self):
        """With dynamic wear leveling, 30 writes to LBA 0 are evenly distributed across physical blocks."""
        ssd = SSDDevice(
            logical_capacity=4,
            overprovisioning=2,  # 6 physical blocks total
            wear_mode=WearLevelingMode.DYNAMIC,
        )

        for i in range(30):
            ssd.write(0, f"Payload_{i}".encode("utf-8"))

        stats = ssd.get_wear_stats()
        # 30 writes distributed among 6 physical blocks -> each block should have ~5 writes
        self.assertEqual(stats["total_writes"], 30)
        self.assertLessEqual(stats["max_wear"], 6)
        self.assertGreaterEqual(stats["min_wear"], 4)
        self.assertLess(stats["std_dev_wear"], 1.0)

        # Content must match the last write
        read_back = ssd.read(0)
        self.assertTrue(read_back.startswith(b"Payload_29"))

    def test_multiple_lbas_data_integrity(self):
        """Verify data integrity across multiple LBAs with interleaved writes."""
        ssd = SSDDevice(logical_capacity=4, overprovisioning=2)

        data_map = {
            0: b"Alpha",
            1: b"Beta",
            2: b"Gamma",
            3: b"Delta",
        }

        # Initial write
        for lba, val in data_map.items():
            ssd.write(lba, val)

        # Overwrites
        ssd.write(1, b"Beta_Updated")
        ssd.write(3, b"Delta_Updated")

        self.assertTrue(ssd.read(0).startswith(b"Alpha"))
        self.assertTrue(ssd.read(1).startswith(b"Beta_Updated"))
        self.assertTrue(ssd.read(2).startswith(b"Gamma"))
        self.assertTrue(ssd.read(3).startswith(b"Delta_Updated"))

    def test_static_wear_leveling_migration(self):
        """Verify static wear leveling moves cold data to higher wear blocks."""
        ssd = SSDDevice(
            logical_capacity=4,
            overprovisioning=2,
            wear_mode=WearLevelingMode.STATIC,
            static_threshold=3,
        )

        # LBA 0 gets written once (cold data)
        ssd.write(0, b"Cold_Static_Data")

        # LBA 1 gets written frequently (hot data)
        for i in range(15):
            ssd.write(1, f"Hot_{i}".encode("utf-8"))

        stats = ssd.get_wear_stats()
        # Ensure wear is distributed and static data was relocated
        self.assertEqual(stats["total_writes"], 16)
        # Content of both cold and hot data must remain 100% correct
        self.assertTrue(ssd.read(0).startswith(b"Cold_Static_Data"))
        self.assertTrue(ssd.read(1).startswith(b"Hot_14"))

    def test_formatted_wear_report(self):
        ssd = SSDDevice(logical_capacity=4, overprovisioning=2)
        ssd.write(0, b"Teste")
        report = ssd.format_wear_report()

        self.assertIn("DIAGNÓSTICO DE WEAR LEVELING DO SSD", report)
        self.assertIn("DYNAMIC", report)
        self.assertIn("Total de Ciclos de Escrita", report)


if __name__ == "__main__":
    unittest.main()
