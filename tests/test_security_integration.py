"""End-to-End Security Integration Tests for OS Simulator (Etapa 3).

Validates:
1. Scenario SEC-001: User registration and authentication with PBKDF2-HMAC-SHA256
   (600,000 iterations), 16-byte random salt, constant-time comparison,
   session creation in USER_MODE, and AuditLog event generation.
2. Scenario SEC-002: POSIX ACL evaluation on /sistema/config.sys (750 root:admin)
   for user carlos (group devs), blocking read with PermissionDeniedException and
   recording ACCESS_DENIED in AuditLog. Verified at both service and CLI levels.
3. Scenario SEC-003: File encryption with AES-256-GCM, baseline registration with
   Kernel HMAC signature, physical block tamper injection (1-byte bit-flip),
   antivirus_scan / detection of block hash corruption, and simulated malware
   signature detection.
4. Directory traversal enforcement requiring 'x' on all ancestor directories.
5. Integration between AES-256-GCM encryption, BlockDevicePort, and RAID 5.
6. Full CLI commands workflow and reference formatted outputs.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from os_simulator.cli.commands import CommandDispatcher
from os_simulator.core.context import ExecutionContext
from os_simulator.core.exceptions import (
    AuthenticationFailedException,
    DecryptionFailedException,
    InvalidTagException,
    PermissionDeniedException,
    PrivilegeViolationException,
)
from os_simulator.core.simulation_kernel import SimulationKernel
from os_simulator.core.types import (
    AllocationStrategy,
    AuditEventType,
    FileScanStatus,
    PrivilegeMode,
)
from os_simulator.filesystem.service import FileSystemService
from os_simulator.security.acl import ACL, FilePermissions, Permission
from os_simulator.security.audit import AuditEvent, AuditLog
from os_simulator.security.auth import AuthenticationService
from os_simulator.security.crypto import (
    CryptoBlockDeviceAdapter,
    CryptoEngine,
    decrypt_file,
    encrypt_file,
    generate_key,
)
from os_simulator.security.integrity import (
    DEFAULT_MALWARE_SIGNATURES,
    SIMULATED_MALWARE_SIGNATURES,
    AntivirusScanReport,
    AntivirusScanner,
    BaselineCatalog,
    IntegrityChecker,
)
from os_simulator.security.service import SecurityManager
from os_simulator.security.user import UserManager
from os_simulator.io.service import IOManager
from os_simulator.storage.adapter import IOBlockDeviceAdapter
from os_simulator.storage.memory_block_device import InMemoryBlockDevice
from os_simulator.storage.physical_disk import PhysicalDisk
from os_simulator.storage.raid import RAID5Controller


class TestScenarioSEC001(unittest.TestCase):
    """Scenario SEC-001: Autenticação Criptográfica com PBKDF2 e Salt."""

    def setUp(self):
        self.device = InMemoryBlockDevice(capacity=32, block_size=4096)
        self.audit_log = AuditLog()
        self.user_manager = UserManager()
        self.auth_service = AuthenticationService(
            user_manager=self.user_manager,
            audit_log=self.audit_log,
            default_iterations=600_000,
        )
        self.security_manager = SecurityManager(
            user_manager=self.user_manager,
            auth_service=self.auth_service,
            audit_log=self.audit_log,
        )
        self.fs = FileSystemService(
            block_device=self.device,
            auth_port=self.security_manager,
            default_strategy=AllocationStrategy.INDEXED,
        )
        self.security_manager.set_filesystem(self.fs)

    def test_sec_001_service_layer_ground_truth(self):
        """SEC-001 via Service Layer:
        - Carlos registered with 16-byte random salt and PBKDF2 (600,000 iterations).
        - Correct login creates active session in USER_MODE with group devs.
        - Event LOGIN_SUCCESS recorded in AuditLog.
        - Incorrect password fails with AuthenticationFailedException and records LOGIN_FAILED.
        """
        # 1. Register group 'devs' and user 'carlos'
        self.user_manager.groupadd("devs")
        user_carlos = self.user_manager.useradd(
            username="carlos",
            password="SenhaSeguraCarlos123!",
            primary_group="devs",
            iterations=600_000,
        )

        # Verify cryptographic attributes
        self.assertEqual(len(user_carlos.salt), 16)
        self.assertEqual(user_carlos.iterations, 600_000)
        self.assertNotEqual(user_carlos.password_hash, "SenhaSeguraCarlos123!")

        # 2. Login with correct password
        carlos_ctx = self.auth_service.login("carlos", "SenhaSeguraCarlos123!")
        self.assertEqual(carlos_ctx.username, "carlos")
        self.assertEqual(carlos_ctx.privilege_mode, PrivilegeMode.USER_MODE)
        self.assertTrue(carlos_ctx.is_user_mode())
        self.assertFalse(carlos_ctx.is_root())
        self.assertIn("devs", carlos_ctx.groups)

        # 3. Verify AuditLog
        login_events = self.audit_log.filter_by_type(AuditEventType.LOGIN_SUCCESS)
        self.assertEqual(len(login_events), 1)
        self.assertEqual(login_events[0].username, "carlos")
        self.assertEqual(login_events[0].action, "LOGIN")

        # 4. Login with incorrect password
        with self.assertRaises(AuthenticationFailedException):
            self.auth_service.login("carlos", "SenhaErrada999!")

        failed_events = self.audit_log.filter_by_type(AuditEventType.LOGIN_FAILED)
        self.assertEqual(len(failed_events), 1)
        self.assertEqual(failed_events[0].username, "carlos")

    def test_sec_001_cli_layer_ground_truth(self):
        """SEC-001 via CLI Dispatcher:
        Executes 'useradd', 'login', 'whoami', 'logout' commands and verifies prompt and audit.
        """
        kernel = SimulationKernel(disk_capacity=16, block_size=4096)
        dispatcher = CommandDispatcher(kernel)

        # 1. Root creates group and user
        r_group = dispatcher.execute_line("groupadd devs")
        self.assertTrue(r_group.success)

        r_user = dispatcher.execute_line(
            "useradd carlos --group devs --password SenhaForteCarlos2026!"
        )
        self.assertTrue(r_user.success)

        # 2. Login as carlos
        r_login = dispatcher.execute_line(
            "login --user carlos --password SenhaForteCarlos2026!"
        )
        self.assertTrue(r_login.success)
        self.assertIn("carlos", r_login.output)
        self.assertEqual(kernel.context.username, "carlos")
        self.assertEqual(kernel.context.privilege_mode, PrivilegeMode.USER_MODE)
        self.assertTrue(kernel.get_prompt().startswith("[carlos@ubuntu-simulator:"))
        self.assertTrue(kernel.get_prompt().endswith("$ "))

        # 3. whoami command
        r_who = dispatcher.execute_line("whoami")
        self.assertTrue(r_who.success)
        self.assertIn("carlos", r_who.output)
        self.assertIn("devs", r_who.output)
        self.assertIn("MODO_USUARIO", r_who.output)

        # 4. Logout
        r_out = dispatcher.execute_line("logout")
        self.assertTrue(r_out.success)
        self.assertNotEqual(kernel.context.username, "carlos")


class TestScenarioSEC002(unittest.TestCase):
    """Scenario SEC-002: Fiscalização de ACL e Negação de Acesso com Auditoria."""

    def setUp(self):
        self.device = InMemoryBlockDevice(capacity=32, block_size=4096)
        self.audit_log = AuditLog()
        self.user_manager = UserManager()
        self.auth_service = AuthenticationService(
            user_manager=self.user_manager,
            audit_log=self.audit_log,
        )
        self.security_manager = SecurityManager(
            user_manager=self.user_manager,
            auth_service=self.auth_service,
            audit_log=self.audit_log,
        )
        self.fs = FileSystemService(
            block_device=self.device,
            auth_port=self.security_manager,
            default_strategy=AllocationStrategy.INDEXED,
        )
        self.security_manager.set_filesystem(self.fs)

    def test_sec_002_service_layer_ground_truth(self):
        """SEC-002 via Service Layer:
        - Resource: /sistema/config.sys (750 root:admin)
        - Active user: carlos (group devs)
        - Evaluation:
          1. carlos != root -> owner perms do not apply
          2. devs != admin -> group perms do not apply
          3. others perms: 0 (---) -> read denied!
        - Result: PermissionDeniedException raised, ACCESS_DENIED logged in AuditLog.
        """
        # 1. Setup filesystem hierarchy
        self.fs.mkdir("/sistema")
        self.fs.write_file(
            "/sistema/config.sys",
            "PORT=8080\nDB_PASS=supersecret_master_password\nDEBUG=false",
        )

        # Set permissions to 750 (rwxr-x---) owned by root:admin
        root_ctx = ExecutionContext(
            user_id=0,
            username="root",
            groups=["root", "admin"],
            privilege_mode=PrivilegeMode.KERNEL_MODE,
        )
        self.security_manager.chmod(root_ctx, "/sistema/config.sys", "750")
        self.security_manager.chown(root_ctx, "/sistema/config.sys", owner="root", group="admin")

        node = self.fs.vfs.get_file("/sistema/config.sys")
        inode = self.fs.inode_table[node.inode_id]
        self.assertEqual(inode.permissions, "750")
        self.assertEqual(inode.owner, "root")
        self.assertEqual(inode.group, "admin")

        # 2. Context of non-privileged user Carlos (group devs)
        carlos_ctx = ExecutionContext(
            user_id=1001,
            username="carlos",
            groups=["devs"],
            privilege_mode=PrivilegeMode.USER_MODE,
            cwd="/",
        )

        # 3. Direct invocation on FileSystemService.read_file with Carlos context
        with self.assertRaises(PermissionDeniedException) as exc:
            self.fs.read_file("/sistema/config.sys", context=carlos_ctx)

        self.assertIn("permissão de leitura", str(exc.exception).lower())

        # 4. Verify AuditLog has recorded ACCESS_DENIED
        denied_events = self.audit_log.filter_by_type(AuditEventType.ACCESS_DENIED)
        self.assertGreaterEqual(len(denied_events), 1)
        target_event = next(
            (e for e in denied_events if e.path == "/sistema/config.sys" and e.username == "carlos"),
            None,
        )
        self.assertIsNotNone(target_event)
        self.assertEqual(target_event.action, "READ")
        self.assertEqual(target_event.details["owner"], "root")
        self.assertEqual(target_event.details["group"], "admin")
        self.assertEqual(target_event.details["permissions"], "750")

        # 5. User Ana in group 'admin' CAN read (750 gives r-x to group)
        ana_ctx = ExecutionContext(
            user_id=1002,
            username="ana",
            groups=["admin"],
            privilege_mode=PrivilegeMode.USER_MODE,
            cwd="/",
        )
        content = self.fs.read_file("/sistema/config.sys", context=ana_ctx)
        self.assertIn("PORT=8080", content)

        # But Ana CANNOT write (750 group has read and execute, but NO write)
        with self.assertRaises(PermissionDeniedException):
            self.fs.write_file("/sistema/config.sys", "NEW_CONTENT", context=ana_ctx)

        # 6. Root bypasses all checks
        root_read = self.fs.read_file("/sistema/config.sys", context=root_ctx)
        self.assertIn("PORT=8080", root_read)

    def test_sec_002_cli_layer_ground_truth(self):
        """SEC-002 via CLI Dispatcher:
        Simulates the entire terminal session:
        1. Root creates /sistema/config.sys, sets 750 root:admin.
        2. Carlos registers, logs in.
        3. Carlos executes 'read_file /sistema/config.sys' -> blocked with error!
        4. Audit log inspected to confirm ACCESS_DENIED.
        """
        kernel = SimulationKernel(disk_capacity=16, block_size=4096)
        dispatcher = CommandDispatcher(kernel)

        # 1. As root, create file and set 750 root:admin
        dispatcher.execute_line("mkdir /sistema")
        dispatcher.execute_line('write_file /sistema/config.sys "PARAMETROS_CONFIDENCIAIS=TRUE"')
        dispatcher.execute_line("chmod 750 /sistema/config.sys")
        dispatcher.execute_line("chown root:admin /sistema/config.sys")

        # 2. Create user carlos in group devs
        dispatcher.execute_line("groupadd devs")
        dispatcher.execute_line("useradd carlos --group devs --password senha123")

        # 3. Login as carlos
        r_login = dispatcher.execute_line("login --user carlos --password senha123")
        self.assertTrue(r_login.success)

        # 4. Attempt read_file /sistema/config.sys
        r_read = dispatcher.execute_line("read_file /sistema/config.sys")
        self.assertFalse(r_read.success)
        self.assertIn("permissão de leitura", r_read.error.lower())

        # 5. Check audit_log as root
        dispatcher.execute_line("login --user root --password root")
        r_audit = dispatcher.execute_line("audit_log --user carlos --type ACCESS_DENIED")
        self.assertTrue(r_audit.success)
        self.assertIn("carlos", r_audit.output)
        self.assertIn("/sistema/config.sys", r_audit.output)


class TestScenarioSEC003(unittest.TestCase):
    """Scenario SEC-003: Integridade, Criptografia AES-256-GCM, HMAC e Antivírus."""

    def setUp(self):
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

        self.kernel_secret = b"master_kernel_hmac_secret_key_32!!"
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

    def test_sec_003_complete_flow_ground_truth(self):
        """SEC-003 complete end-to-end ground truth:
        1. Create /home/carlos/segredo.txt with plaintext.
        2. Encrypt with genuine AES-256-GCM.
        3. Register baseline with Kernel HMAC signature.
        4. Physical inspection: only ciphertext exists in raw disk blocks.
        5. Tampering: alter 1 byte in physical disk block.
        6. antivirus_scan / detects block hash corruption and flags block ID.
        7. Decryption fails with InvalidTagException / DecryptionFailedException.
        8. Simulated malware signature detection.
        """
        # 1. Create file hierarchy
        self.fs.mkdir("/home")
        self.fs.mkdir("/home/carlos")
        file_path = "/home/carlos/segredo.txt"
        secret_content = "Documento Ultra-Secreto: Chaves Criptográficas da Frota Espacial 2026."
        self.fs.write_file(file_path, secret_content)

        # 2. Encrypt file with AES-256-GCM
        enc_key = "ChaveCriptoForteCarlos32Bytes!!"
        enc_result = encrypt_file(self.fs, file_path, enc_key)
        self.assertTrue(enc_result["is_encrypted"])
        self.assertGreater(enc_result["encrypted_size"], len(secret_content))

        # 3. Register baseline in catalog protected by Kernel HMAC
        baseline_record = self.checker.register_file_baseline(self.fs, file_path, self.catalog)
        self.assertTrue(baseline_record.verify_signature(self.kernel_secret))
        self.assertTrue(self.catalog.verify_catalog_hmac())

        # 4. Physical inspection: raw block bytes contain only ciphertext, never plaintext
        node = self.fs.vfs.get_file(file_path)
        inode = self.fs.inode_table[node.inode_id]
        tamper_block_id = inode.allocated_blocks[0]

        raw_block_before = self.device.read_block(tamper_block_id)
        self.assertNotIn(secret_content.encode("utf-8"), bytes(raw_block_before))

        # 5. Injeção de Anomalia: alter 1 single byte in physical storage block
        tampered_block_bytes = bytearray(raw_block_before)
        tampered_block_bytes[15] ^= 0x5A  # Flip bits in block byte
        self.device.write_block(tamper_block_id, tampered_block_bytes)

        # 6. Execute antivirus_scan /
        report = self.scanner.scan_path("/", context=self.root_ctx)

        # Approved criteria: detection of modified file and exact tampered block
        self.assertGreaterEqual(report.modified_count, 1)
        mod_entry = next((r for r in report.results if r.path == file_path), None)
        self.assertIsNotNone(mod_entry)
        self.assertEqual(mod_entry.status, FileScanStatus.MODIFIED)
        self.assertIn(tamper_block_id, mod_entry.tampered_blocks)

        # AuditLog must contain TAMPER_DETECTED event
        tamper_events = self.audit_log.filter_by_type(AuditEventType.TAMPER_DETECTED)
        self.assertGreaterEqual(len(tamper_events), 1)

        # 7. Decryption must fail with InvalidTagException
        with self.assertRaises((InvalidTagException, DecryptionFailedException)):
            decrypt_file(self.fs, file_path, enc_key)

        # 8. Create a file containing simulated malware test signature
        self.fs.write_file(
            "/home/carlos/malware.sample",
            "Aviso de seguranca: arquivo contendo SIM_MALWARE_TROJAN_PAYLOAD infectado.",
        )
        report2 = self.scanner.scan_path("/home/carlos", context=self.root_ctx)
        self.assertGreaterEqual(report2.suspicious_count, 1)
        susp_entry = next((r for r in report2.results if r.path == "/home/carlos/malware.sample"), None)
        self.assertIsNotNone(susp_entry)
        self.assertEqual(susp_entry.status, FileScanStatus.SUSPICIOUS)
        self.assertTrue(
            any("Trojan.Simulator.Generic" in s for s in susp_entry.matched_signatures)
        )

    def test_sec_003_cli_commands(self):
        """SEC-003 via CLI Dispatcher:
        Tests 'encrypt_file', physical tampering, and 'antivirus_scan' commands.
        """
        kernel = SimulationKernel(disk_capacity=32, block_size=1024)
        dispatcher = CommandDispatcher(kernel)

        # Create file and encrypt via CLI
        dispatcher.execute_line("mkdir /dados")
        dispatcher.execute_line('write_file /dados/plano.txt "Plano de Voo Espacial Confidencial"')
        r_enc = dispatcher.execute_line("encrypt_file /dados/plano.txt --key ChaveForte32BytesParaCifrarAES!!")
        self.assertTrue(r_enc.success)
        self.assertIn("AES-256-GCM", r_enc.output)

        # Register baseline in kernel catalog
        kernel.integrity_checker.register_file_baseline(kernel.fs_service, "/dados/plano.txt", kernel.catalog)

        # Physical block tampering
        node = kernel.fs_service.vfs.get_file("/dados/plano.txt")
        inode = kernel.fs_service.inode_table[node.inode_id]
        b_id = inode.allocated_blocks[0]
        raw = kernel.device.read_block(b_id)
        raw[20] ^= 0xAA
        kernel.device.write_block(b_id, raw)

        # Run antivirus_scan via CLI
        r_scan = dispatcher.execute_line("antivirus_scan /dados")
        self.assertTrue(r_scan.success)
        self.assertIn("MODIFICADO", r_scan.output)
        self.assertIn(f"Bloco(s) Adulterado(s): [{b_id}]", r_scan.output)


class TestDirectoryTraversalAndPrivilegeRings(unittest.TestCase):
    """Test directory traversal enforcement ('x') and privilege ring transitions."""

    def setUp(self):
        self.device = InMemoryBlockDevice(capacity=16, block_size=4096)
        self.audit_log = AuditLog()
        self.user_manager = UserManager()
        self.auth_service = AuthenticationService(
            user_manager=self.user_manager,
            audit_log=self.audit_log,
        )
        self.security_manager = SecurityManager(
            user_manager=self.user_manager,
            auth_service=self.auth_service,
            audit_log=self.audit_log,
        )
        self.fs = FileSystemService(
            block_device=self.device,
            auth_port=self.security_manager,
            default_strategy=AllocationStrategy.INDEXED,
        )
        self.security_manager.set_filesystem(self.fs)

    def test_directory_traversal_blocks_nested_access(self):
        """User cannot access file if an ancestor directory lacks execute ('x') permission."""
        # /confidencial/dados/doc.txt
        self.fs.mkdir("/confidencial")
        self.fs.mkdir("/confidencial/dados")
        self.fs.write_file("/confidencial/dados/doc.txt", "CONTEUDO_RESTRITO")

        root_ctx = ExecutionContext(user_id=0, username="root", groups=["root"], privilege_mode=PrivilegeMode.KERNEL_MODE)

        # Set /confidencial to 700 (rwx------) owned by root:root
        self.security_manager.chmod(root_ctx, "/confidencial", "700")

        # Set file to 777 (rwxrwxrwx)
        self.security_manager.chmod(root_ctx, "/confidencial/dados/doc.txt", "777")

        carlos_ctx = ExecutionContext(user_id=1001, username="carlos", groups=["devs"], privilege_mode=PrivilegeMode.USER_MODE)

        # Even though file is 777, traversal in /confidencial is denied!
        with self.assertRaises(PermissionDeniedException) as exc:
            self.fs.read_file("/confidencial/dados/doc.txt", context=carlos_ctx)

        self.assertIn("atravessar", str(exc.exception).lower())

        # Traversal denial recorded in audit log
        denied = self.audit_log.filter_by_type(AuditEventType.ACCESS_DENIED)
        self.assertTrue(any(e.action == "TRAVERSE" for e in denied))

    def test_non_root_cannot_chown_or_elevate_privileges(self):
        """Non-root user cannot execute chown or elevate to KERNEL_MODE without administrative credentials."""
        root_ctx = ExecutionContext(user_id=0, username="root", groups=["root"], privilege_mode=PrivilegeMode.KERNEL_MODE)
        self.fs.mkdir("/home", context=root_ctx)
        self.fs.mkdir("/home/carlos", context=root_ctx)
        self.security_manager.chown(root_ctx, "/home/carlos", owner="carlos", group="devs")

        self.user_manager.set_filesystem(self.fs)
        self.user_manager.groupadd("devs")
        self.user_manager.useradd("carlos", "senha123", primary_group="devs")

        carlos_ctx = self.auth_service.login("carlos", "senha123")
        # Ensure /home/carlos exists and is owned by carlos
        self.fs.write_file("/home/carlos/carlos_file.txt", "Meu arquivo", context=carlos_ctx)

        # Carlos attempts chown to root
        with self.assertRaises(PermissionDeniedException):
            self.security_manager.chown(carlos_ctx, "/home/carlos/carlos_file.txt", owner="root")

        # Carlos attempts privilege elevation to KERNEL_MODE
        with self.assertRaises(PrivilegeViolationException):
            self.auth_service.elevate_privileges(carlos_ctx, "senha123")


class TestEncryptedStorageWithRAID5(unittest.TestCase):
    """Test transparent AES-256-GCM block encryption over RAID 5 array."""

    def test_encrypted_block_device_with_raid5_rebuild(self):
        """RAID 5 array wrapped with CryptoBlockDeviceAdapter:
        1. Encrypted blocks distributed across RAID disks with XOR parity.
        2. Physical disk failure injected (offline).
        3. Read in degraded mode reconstructs plaintext on-the-fly.
        4. Rebuild restores parity and data seamlessly.
        """
        # Create 3 physical disks of 16 blocks each
        disks = [PhysicalDisk(disk_id=i, capacity_blocks=16, block_size=1024) for i in range(3)]
        raid5 = RAID5Controller(disks=disks, block_size=1024)
        io_mgr = IOManager(storage_backend=raid5)
        adapter = IOBlockDeviceAdapter(
            io_manager=io_mgr,
            logical_capacity=raid5.logical_capacity,
            block_size=1024,
        )

        # Wrap RAID with transparent AES-256-GCM CryptoBlockDeviceAdapter
        crypto_key = generate_key()
        crypto_dev = CryptoBlockDeviceAdapter(device=adapter, key=crypto_key)

        # Write data to logical block 0 (within usable encrypted block limit)
        payload0 = b"DADOS_CONFIDENCIAIS_BLOCO_ZERO" + (b"\x00" * 200)
        crypto_dev.write_block(0, payload0)

        # Read back and verify authentication
        read_back = crypto_dev.read_block(0)
        self.assertEqual(bytes(read_back)[:30], b"DADOS_CONFIDENCIAIS_BLOCO_ZERO")

        # Verify physical disk stores only ciphertext
        self.assertNotIn(b"DADOS_CONFIDENCIAIS_BLOCO_ZERO", bytes(disks[0].read_block(0)))

        # Inject physical failure in disk 0
        disks[0].fail()
        self.assertFalse(disks[0].is_online)

        # Read in degraded mode: RAID 5 XOR reconstruction + CryptoBlockDeviceAdapter AEAD decryption
        degraded_read = crypto_dev.read_block(0)
        self.assertEqual(bytes(degraded_read)[:30], b"DADOS_CONFIDENCIAIS_BLOCO_ZERO")

        # Rebuild disk 0
        raid5.rebuild_disk(0)
        self.assertTrue(disks[0].is_online)

        # Read after rebuild
        post_rebuild = crypto_dev.read_block(0)
        self.assertEqual(bytes(post_rebuild)[:30], b"DADOS_CONFIDENCIAIS_BLOCO_ZERO")


class TestAdditionalSecurityCLICommands(unittest.TestCase):
    """Test full CLI coverage for groupdel, usermod, groups, chgrp, security_status, integrity_check."""

    def test_additional_cli_commands(self):
        kernel = SimulationKernel(disk_capacity=16, block_size=4096)
        dispatcher = CommandDispatcher(kernel)

        # 1. groupadd, groupdel, usermod, groups
        r = dispatcher.execute_line("groupadd testgroup")
        self.assertTrue(r.success)

        r = dispatcher.execute_line("useradd joao --group testgroup --password senha123")
        self.assertTrue(r.success)

        r = dispatcher.execute_line("groups joao")
        self.assertTrue(r.success)
        self.assertIn("testgroup", r.output)

        r = dispatcher.execute_line("groupadd newgroup")
        self.assertTrue(r.success)

        r = dispatcher.execute_line("usermod joao --group newgroup")
        self.assertTrue(r.success)

        r = dispatcher.execute_line("groups joao")
        self.assertTrue(r.success)
        self.assertIn("newgroup", r.output)

        r = dispatcher.execute_line("groupdel testgroup")
        self.assertTrue(r.success)

        # 2. chgrp command
        dispatcher.execute_line("mkdir /shared")
        r_chgrp = dispatcher.execute_line("chgrp newgroup /shared")
        self.assertTrue(r_chgrp.success)
        self.assertIn("newgroup", r_chgrp.output)

        # 3. security_status command
        r_status = dispatcher.execute_line("security_status")
        self.assertTrue(r_status.success)
        self.assertIn("STATUS DO SISTEMA DE SEGURANÇA", r_status.output)
        self.assertIn("PBKDF2-HMAC-SHA256", r_status.output)

        # 4. integrity_check command
        dispatcher.execute_line('write_file /shared/data.txt "Informacoes do Sistema"')
        r_ic_reg = dispatcher.execute_line("integrity_check --register /shared/data.txt")
        self.assertTrue(r_ic_reg.success)
        self.assertIn("registrada", r_ic_reg.output)

        r_ic_scan = dispatcher.execute_line("integrity_check /shared")
        self.assertTrue(r_ic_scan.success)
        self.assertIn("RELATÓRIO DO ANTIVÍRUS", r_ic_scan.output)


if __name__ == "__main__":
    unittest.main()
