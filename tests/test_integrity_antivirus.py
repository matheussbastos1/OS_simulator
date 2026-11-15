"""Unit tests for Integrity Verification and Simulated Antivirus subsystem (Etapa 3).

Covers:
1. Baseline generation and verification with SHA-256 and Kernel HMAC signatures.
2. Tamper detection when a physical storage block is modified (e.g. flip 1 byte).
3. HMAC protection against catalog and record tampering.
4. Malware signature detection in plain and nested directory trees.
5. Proper classification of all statuses: OK, OK_ENCRYPTED, MODIFIED, SUSPICIOUS, INACCESSIBLE.
6. Scenario SEC-003 end-to-end execution and report formatting.
7. Audit log integration on tamper/threat detection.
"""

import time
import unittest

from os_simulator.core.context import ExecutionContext
from os_simulator.core.exceptions import FileNotFoundException
from os_simulator.core.types import (
    AllocationStrategy,
    AuditEventType,
    FileScanStatus,
    NodeType,
    PrivilegeMode,
)
from os_simulator.filesystem.service import FileSystemService
from os_simulator.security.acl import ACL, FilePermissions
from os_simulator.security.audit import AuditEvent, AuditLog
from os_simulator.security.crypto import encrypt_file
from os_simulator.security.integrity import (
    DEFAULT_MALWARE_SIGNATURES,
    SIMULATED_MALWARE_SIGNATURES,
    AntivirusScanReport,
    AntivirusScanner,
    BaselineCatalog,
    FileScanResult,
    IntegrityChecker,
    IntegrityRecord,
    ScanStatus,
)
from os_simulator.security.service import SecurityManager
from os_simulator.security.user import UserManager
from os_simulator.storage.memory_block_device import InMemoryBlockDevice


class TestIntegrityAndAntivirus(unittest.TestCase):
    """Rigorous test suite for Integrity and Antivirus subsystem."""

    def setUp(self):
        """Initialize clean virtual filesystem and security environment."""
        self.device = InMemoryBlockDevice(capacity=64, block_size=1024)
        self.audit_log = AuditLog()
        self.user_manager = UserManager()
        self.security_manager = SecurityManager(
            user_manager=self.user_manager,
            audit_log=self.audit_log,
        )
        self.fs = FileSystemService(
            block_device=self.device,
            auth_port=self.security_manager,
            default_strategy=AllocationStrategy.INDEXED,
        )
        self.security_manager.set_filesystem(self.fs)

        self.kernel_secret = b"kernel_master_secret_key_32_bytes!!"
        self.catalog = BaselineCatalog(kernel_secret=self.kernel_secret)
        self.checker = IntegrityChecker()
        self.scanner = AntivirusScanner(
            fs_service=self.fs,
            catalog=self.catalog,
            auth_port=self.security_manager,
            audit_log=self.audit_log,
            checker=self.checker,
            kernel_secret=self.kernel_secret,
        )

        self.root_ctx = ExecutionContext(
            user_id=0,
            username="root",
            groups=["root", "admin"],
            privilege_mode=PrivilegeMode.KERNEL_MODE,
        )

    # --------------------------------------------------------------------------
    # 1. Baseline Generation and Verification
    # --------------------------------------------------------------------------
    def test_baseline_generation_and_verification_single_file(self):
        """Test SHA-256 calculation and HMAC baseline registration for a single file."""
        self.fs.mkdir("/sistema")
        self.fs.write_file("/sistema/kernel.bin", "KERNEL_INITIAL_PAYLOAD_V1")

        record = self.checker.register_file_baseline(self.fs, "/sistema/kernel.bin", self.catalog)

        # 1. Verify record attributes
        self.assertEqual(record.resource_path, "/sistema/kernel.bin")
        expected_hash = IntegrityChecker.compute_sha256("KERNEL_INITIAL_PAYLOAD_V1")
        self.assertEqual(record.expected_sha256, expected_hash)
        self.assertTrue(record.verify_signature(self.kernel_secret))
        self.assertGreater(len(record.block_hashes), 0)

        # 2. Verify inode metadata updated
        node = self.fs.vfs.get_file("/sistema/kernel.bin")
        inode = self.fs.inode_table[node.inode_id]
        self.assertEqual(inode.integrity_hash, expected_hash)

        # 3. Verify file verification passes
        result = self.checker.verify_file(self.fs, "/sistema/kernel.bin", self.catalog)
        self.assertTrue(result.is_valid)
        self.assertTrue(result.hmac_valid)
        self.assertEqual(result.tampered_blocks, [])
        self.assertEqual(result.actual_hash, expected_hash)

    def test_baseline_generation_multi_block_file(self):
        """Test baseline generation for a multi-block file spanning multiple blocks."""
        self.fs.mkdir("/data")
        # 3.5 KB payload on 1 KB blocks -> 4 blocks
        large_payload = "A" * 3500
        self.fs.write_file("/data/bigfile.dat", large_payload)

        record = self.checker.register_file_baseline(self.fs, "/data/bigfile.dat", self.catalog)
        self.assertEqual(len(record.block_hashes), 4)

        result = self.checker.verify_file(self.fs, "/data/bigfile.dat", self.catalog)
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.tampered_blocks), 0)

    def test_baseline_generation_empty_file(self):
        """Test baseline generation for an empty 0-byte file."""
        self.fs.create_file("/empty.txt")
        record = self.checker.register_file_baseline(self.fs, "/empty.txt", self.catalog)

        empty_sha256 = IntegrityChecker.compute_sha256(b"")
        self.assertEqual(record.expected_sha256, empty_sha256)
        self.assertEqual(len(record.block_hashes), 0)

        result = self.checker.verify_file(self.fs, "/empty.txt", self.catalog)
        self.assertTrue(result.is_valid)

    def test_baseline_tree_registration(self):
        """Test recursive tree baseline registration."""
        self.fs.mkdir("/etc")
        self.fs.mkdir("/etc/network")
        self.fs.write_file("/etc/hosts", "127.0.0.1 localhost")
        self.fs.write_file("/etc/resolv.conf", "nameserver 8.8.8.8")
        self.fs.write_file("/etc/network/interfaces", "auto eth0")

        registered_count = self.checker.register_tree_baseline(self.fs, self.catalog, root_path="/etc")
        self.assertEqual(registered_count, 3)
        self.assertTrue(self.catalog.has_record("/etc/hosts"))
        self.assertTrue(self.catalog.has_record("/etc/resolv.conf"))
        self.assertTrue(self.catalog.has_record("/etc/network/interfaces"))

    # --------------------------------------------------------------------------
    # 2. Tamper Detection via Physical Block Modification
    # --------------------------------------------------------------------------
    def test_tamper_detection_flip_byte_in_physical_block(self):
        """Test detection of tamper when exactly 1 byte is modified on physical storage block."""
        self.fs.mkdir("/sistema")
        self.fs.write_file("/sistema/config.sys", "sys_setting=active;auth=strict;")

        node = self.fs.vfs.get_file("/sistema/config.sys")
        inode = self.fs.inode_table[node.inode_id]
        target_block_id = inode.allocated_blocks[0]

        # Register official baseline
        self.checker.register_file_baseline(self.fs, "/sistema/config.sys", self.catalog)

        # Inject physical anomaly: flip 1 byte directly on physical block device
        raw_block = self.device.read_block(target_block_id)
        raw_block[0] ^= 0x01  # Flip 1 bit/byte
        self.device.write_block(target_block_id, raw_block)

        # Verify integrity checker detects exact tampered block
        check_result = self.checker.verify_file(self.fs, "/sistema/config.sys", self.catalog)
        self.assertFalse(check_result.is_valid)
        self.assertIn(target_block_id, check_result.tampered_blocks)
        self.assertNotEqual(check_result.actual_hash, check_result.expected_hash)

        # Verify AntivirusScanner classifies as MODIFIED
        scan_result = self.scanner.scan_file("/sistema/config.sys", context=self.root_ctx)
        self.assertEqual(scan_result.status, FileScanStatus.MODIFIED)
        self.assertIn(target_block_id, scan_result.tampered_blocks)
        self.assertIn("divergência", (scan_result.details or scan_result.display_status).lower())

    def test_tamper_detection_encrypted_file(self):
        """Test tamper detection on an encrypted file with physical block tampering."""
        self.fs.mkdir("/home")
        self.fs.mkdir("/home/carlos")
        self.fs.write_file("/home/carlos/segredo.txt", "Texto confidencial protegido por AES-256-GCM")

        # Encrypt file in-place
        key = "chave_mestra_carlos_123"
        encrypt_file(self.fs, "/home/carlos/segredo.txt", key=key)

        node = self.fs.vfs.get_file("/home/carlos/segredo.txt")
        inode = self.fs.inode_table[node.inode_id]
        self.assertTrue(inode.is_encrypted)
        target_block_id = inode.allocated_blocks[0]

        # Register baseline after encryption
        self.checker.register_file_baseline(self.fs, "/home/carlos/segredo.txt", self.catalog)

        # Before tampering: scan should report OK_ENCRYPTED
        clean_scan = self.scanner.scan_file("/home/carlos/segredo.txt", context=self.root_ctx)
        self.assertEqual(clean_scan.status, FileScanStatus.OK_ENCRYPTED)

        # Inject anomaly: tamper 1 byte in physical block
        raw_block = self.device.read_block(target_block_id)
        raw_block[15] ^= 0xFF  # Corrupt byte
        self.device.write_block(target_block_id, raw_block)

        # Scan after tampering: MUST report MODIFIED and identify the tampered block
        tampered_scan = self.scanner.scan_file("/home/carlos/segredo.txt", context=self.root_ctx)
        self.assertEqual(tampered_scan.status, FileScanStatus.MODIFIED)
        self.assertIn(target_block_id, tampered_scan.tampered_blocks)

    # --------------------------------------------------------------------------
    # 3. HMAC Protection Against Catalog Tampering
    # --------------------------------------------------------------------------
    def test_catalog_tampering_record_altered(self):
        """Test that altering a record's expected hash invalidates the HMAC signature."""
        self.fs.write_file("/critical.bin", "IMPORTANT_PAYLOAD")
        record = self.checker.register_file_baseline(self.fs, "/critical.bin", self.catalog)

        # Attacker attempts to replace hash in memory
        record.expected_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"

        # Record HMAC verification must fail
        self.assertFalse(record.verify_signature(self.kernel_secret))
        self.assertFalse(self.catalog.verify_record_hmac("/critical.bin"))

        # Global catalog verification must fail
        all_valid, tampered = self.catalog.verify_catalog()
        self.assertFalse(all_valid)
        self.assertIn("/critical.bin", tampered)

        # Integrity check on file fails on HMAC
        result = self.checker.verify_file(self.fs, "/critical.bin", self.catalog)
        self.assertFalse(result.is_valid)
        self.assertFalse(result.hmac_valid)
        self.assertIn("HMAC", result.error_message or "")

    def test_catalog_tampering_record_forged_with_wrong_key(self):
        """Test that forging a record with a fake key is rejected."""
        fake_secret = b"attacker_secret_key_fake_12345"
        forged_record = IntegrityRecord(
            resource_path="/fake.bin",
            expected_sha256="abcdef1234567890",
            hmac_signature="",
            last_verified=time.time(),
        )
        forged_record.hmac_signature = forged_record.compute_expected_hmac(fake_secret)

        self.catalog.register_record(forged_record)
        self.assertFalse(self.catalog.verify_record_hmac("/fake.bin"))

        all_valid, tampered = self.catalog.verify_catalog()
        self.assertFalse(all_valid)
        self.assertIn("/fake.bin", tampered)

    def test_catalog_global_hmac_tamper_detection(self):
        """Test that modifying catalog records directly invalidates catalog-wide HMAC."""
        self.fs.write_file("/file1.txt", "Data 1")
        self.fs.write_file("/file2.txt", "Data 2")
        self.checker.register_file_baseline(self.fs, "/file1.txt", self.catalog)
        self.checker.register_file_baseline(self.fs, "/file2.txt", self.catalog)

        self.assertTrue(self.catalog.verify_catalog_hmac())

        # Unauthorized direct removal of record from dictionary bypasses catalog HMAC
        del self.catalog.records["/file1.txt"]
        self.assertFalse(self.catalog.verify_catalog_hmac())

    # --------------------------------------------------------------------------
    # 4. Malware Signature Detection
    # --------------------------------------------------------------------------
    def test_malware_detection_simulated_signatures(self):
        """Test detection of educational malware signatures in file payloads."""
        self.fs.mkdir("/tmp")

        # 1. Trojan payload
        self.fs.write_file("/tmp/trojan.sh", "echo 'executing' SIM_MALWARE_TROJAN_PAYLOAD")
        res1 = self.scanner.scan_file("/tmp/trojan.sh", context=self.root_ctx)
        self.assertEqual(res1.status, FileScanStatus.SUSPICIOUS)
        self.assertTrue(any("SIM_MALWARE_TROJAN_PAYLOAD" in s for s in res1.matched_signatures))

        # 2. Virus signature
        self.fs.write_file("/tmp/virus.bin", b"\x90\x90SIM_MALWARE_VIRUS_SIG_01\xcc")
        res2 = self.scanner.scan_file("/tmp/virus.bin", context=self.root_ctx)
        self.assertEqual(res2.status, FileScanStatus.SUSPICIOUS)
        self.assertTrue(any("SIM_MALWARE_VIRUS_SIG_01" in s for s in res2.matched_signatures))

        # 3. Ransomware test sample
        self.fs.write_file("/tmp/ransom.dat", "ENCRYPT_ALL_DRIVES SIM_RANSOM_SAMPLE_TEST")
        res3 = self.scanner.scan_file("/tmp/ransom.dat", context=self.root_ctx)
        self.assertEqual(res3.status, FileScanStatus.SUSPICIOUS)
        self.assertTrue(any("SIM_RANSOM_SAMPLE_TEST" in s for s in res3.matched_signatures))

    def test_malware_detection_in_nested_directories(self):
        """Test recursive scan finding malware in deep subdirectories."""
        self.fs.mkdir("/a")
        self.fs.mkdir("/a/b")
        self.fs.mkdir("/a/b/c")
        self.fs.write_file("/a/clean.txt", "Clean content")
        self.fs.write_file("/a/b/c/keylogger.exe", "HOOK_KEYBOARD SIM_SPYWARE_KEYLOGGER")

        report = self.scanner.scan_path("/a", context=self.root_ctx)
        self.assertEqual(report.total_files, 2)
        self.assertEqual(report.suspicious_count, 1)
        self.assertEqual(report.ok_count, 1)
        self.assertTrue(report.has_threats)

        suspicious_paths = [r.path for r in report.suspicious_files]
        self.assertIn("/a/b/c/keylogger.exe", suspicious_paths)

    def test_custom_signature_lifecycle(self):
        """Test adding and removing custom signatures dynamically."""
        custom_token = "CUSTOM_TEST_EXPLOIT_SIG_99"
        self.scanner.add_signature(custom_token, "Exploit.Custom.Test")

        self.fs.write_file("/exploit.txt", f"run exploit {custom_token}")
        res = self.scanner.scan_file("/exploit.txt", context=self.root_ctx)
        self.assertEqual(res.status, FileScanStatus.SUSPICIOUS)

        # Remove custom signature
        self.assertTrue(self.scanner.remove_signature(custom_token))
        res_after = self.scanner.scan_file("/exploit.txt", context=self.root_ctx)
        self.assertEqual(res_after.status, FileScanStatus.OK)

    # --------------------------------------------------------------------------
    # 5. Classification of All File Statuses
    # --------------------------------------------------------------------------
    def test_comprehensive_classification_all_statuses(self):
        """Test that all 5 statuses (OK, OK_ENCRYPTED, MODIFIED, SUSPICIOUS, INACCESSIBLE) are classified correctly."""
        # 1. OK file
        self.fs.mkdir("/home")
        self.fs.mkdir("/home/user")
        self.fs.write_file("/home/user/document.txt", "Normal clean document.")
        self.checker.register_file_baseline(self.fs, "/home/user/document.txt", self.catalog)

        # 2. OK_ENCRYPTED file
        self.fs.write_file("/home/user/safe.enc", "Confidential encrypted text.")
        encrypt_file(self.fs, "/home/user/safe.enc", key="safe_key_123")
        self.checker.register_file_baseline(self.fs, "/home/user/safe.enc", self.catalog)

        # 3. MODIFIED file
        self.fs.write_file("/home/user/tampered.txt", "Original uncorrupted text.")
        self.checker.register_file_baseline(self.fs, "/home/user/tampered.txt", self.catalog)
        # Tamper block
        t_node = self.fs.vfs.get_file("/home/user/tampered.txt")
        t_inode = self.fs.inode_table[t_node.inode_id]
        t_blk = self.device.read_block(t_inode.allocated_blocks[0])
        t_blk[2] ^= 0x42
        self.device.write_block(t_inode.allocated_blocks[0], t_blk)

        # 4. SUSPICIOUS file
        self.fs.write_file("/home/user/virus.bin", "Dangerous payload SIM_MALWARE_VIRUS_SIG_01")

        # 5. INACCESSIBLE file (root-only permissions 0o700, accessed by regular user)
        self.fs.mkdir("/root")
        self.fs.write_file("/root/shadow.db", "root:$6$secretpasswordhash")
        r_node = self.fs.vfs.get_file("/root/shadow.db")
        r_inode = self.fs.inode_table[r_node.inode_id]
        r_inode.owner = "root"
        r_inode.group = "root"
        r_inode.permissions = "700"  # rwx------

        user_ctx = ExecutionContext(
            user_id=1001,
            username="carlos",
            groups=["devs"],
            privilege_mode=PrivilegeMode.USER_MODE,
        )

        # Execute recursive scan under carlos user context
        report = self.scanner.scan_path("/", context=user_ctx)

        # Validate counts
        self.assertGreaterEqual(report.ok_count, 1)
        self.assertGreaterEqual(report.ok_encrypted_count, 1)
        self.assertGreaterEqual(report.modified_count, 1)
        self.assertGreaterEqual(report.suspicious_count, 1)
        self.assertGreaterEqual(report.inaccessible_count, 1)
        self.assertTrue(report.has_threats)

        # Verify visual formatting
        formatted = report.format_report()
        self.assertIn("RELATÓRIO DO ANTIVÍRUS E INTEGRIDADE", formatted)
        self.assertIn("[OK]", formatted)
        self.assertIn("[OK_ENCRYPTED]", formatted)
        self.assertIn("[MODIFICADO]", formatted)
        self.assertIn("[SUSPEITO]", formatted)
        self.assertIn("[INACESSIVEL]", formatted)

    # --------------------------------------------------------------------------
    # 6. Scenario SEC-003 End-to-End
    # --------------------------------------------------------------------------
    def test_scenario_sec_003_complete(self):
        """Execute Scenario SEC-003 from GROUND_TRUTH.md end-to-end.

        1. File created with checksum and Kernel HMAC signature.
        2. Anomaly: 1 byte altered in physical block.
        3. antivirus_scan / detects integrity violation, identifying tampered file and block.
        """
        self.fs.mkdir("/home")
        self.fs.mkdir("/home/carlos")
        file_path = "/home/carlos/segredo.txt"
        self.fs.write_file(file_path, "Segredo protegido pelo Kernel com HMAC e SHA-256")

        # 1. Register baseline with SHA-256 and Kernel HMAC signature
        baseline_record = self.checker.register_file_baseline(self.fs, file_path, self.catalog)
        self.assertTrue(baseline_record.verify_signature(self.kernel_secret))

        node = self.fs.vfs.get_file(file_path)
        inode = self.fs.inode_table[node.inode_id]
        tampered_block_id = inode.allocated_blocks[0]

        # 2. Injeção de Anomalia: Alterar 1 byte no bloco físico correspondente
        block_bytes = self.device.read_block(tampered_block_id)
        block_bytes[5] ^= 0xAA  # Flip byte
        self.device.write_block(tampered_block_id, block_bytes)

        # 3. Executar varredura completa
        report = self.scanner.scan_path("/", context=self.root_ctx)

        # 4. Critério de Aprovação: Detecção precisa do arquivo e bloco adulterado
        self.assertGreaterEqual(report.modified_count, 1)
        tampered_entry = next((r for r in report.results if r.path == file_path), None)
        self.assertIsNotNone(tampered_entry)
        self.assertEqual(tampered_entry.status, FileScanStatus.MODIFIED)
        self.assertIn(tampered_block_id, tampered_entry.tampered_blocks)

        # Report format check
        rep_text = report.format_report()
        self.assertIn(file_path, rep_text)
        self.assertIn(f"Bloco(s) Adulterado(s): [{tampered_block_id}]", rep_text)

    # --------------------------------------------------------------------------
    # 7. Audit Log Integration on Tamper / Threat
    # --------------------------------------------------------------------------
    def test_audit_log_records_tamper_event(self):
        """Test that detecting tampering records a TAMPER_DETECTED event in AuditLog."""
        self.fs.write_file("/audit_test.txt", "Payload for audit test")
        self.checker.register_file_baseline(self.fs, "/audit_test.txt", self.catalog)

        # Tamper block
        node = self.fs.vfs.get_file("/audit_test.txt")
        inode = self.fs.inode_table[node.inode_id]
        b_id = inode.allocated_blocks[0]
        blk = self.device.read_block(b_id)
        blk[0] ^= 0x55
        self.device.write_block(b_id, blk)

        events_before = len(self.audit_log.get_events())
        self.scanner.scan_file("/audit_test.txt", context=self.root_ctx)

        events_after = self.audit_log.get_events()
        self.assertGreater(len(events_after), events_before)
        tamper_events = [e for e in events_after if e.event_type == AuditEventType.TAMPER_DETECTED]
        self.assertGreaterEqual(len(tamper_events), 1)
        self.assertEqual(tamper_events[-1].path, "/audit_test.txt")


if __name__ == "__main__":
    unittest.main()
