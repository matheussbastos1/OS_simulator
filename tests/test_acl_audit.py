"""Unit and integration tests for POSIX ACL, AuditLog, and SecurityManager (Etapa 3).

Validates:
1. Permission and PermissionTriple conversions (octal digits, symbolic, bitwise).
2. FilePermissions (octal 755/750/644, symbolic rwxr-xr-x, relative chmod +/-/=).
3. ACL resolution rules (Root bypass, Owner priority, Group priority, Others).
4. AuditEvent formatting and thread-safe AuditLog with filtering and max limits.
5. SecurityManager authorization checks (check_read, check_write, check_execute, check_traverse).
6. Enforcement methods (enforce_read, enforce_write, enforce_execute, enforce_traverse).
7. Scenario SEC-002: Carlos (devs) denied on /sistema/config.sys (750 root:admin) with AuditLog.
8. Directory traversal enforcement requiring 'x' on all ancestor paths.
9. Permission modification (chmod) and ownership transfer (chown) with privilege checks.
"""

import threading
import unittest

from os_simulator.core.context import ExecutionContext
from os_simulator.core.exceptions import (
    FileNotFoundException,
    PermissionDeniedException,
)
from os_simulator.core.types import (
    AllocationStrategy,
    AuditEventType,
    NodeType,
    PrivilegeMode,
)
from os_simulator.filesystem.inode import Inode
from os_simulator.filesystem.service import FileSystemService
from os_simulator.security.acl import (
    ACL,
    FilePermissions,
    Permission,
    PermissionTriple,
)
from os_simulator.security.audit import AuditEvent, AuditLog
from os_simulator.security.service import SecurityManager
from os_simulator.storage.memory_block_device import InMemoryBlockDevice


class TestPermissionAndTriple(unittest.TestCase):
    """Test lower-level Permission enum and PermissionTriple bits."""

    def test_permission_from_char(self):
        self.assertEqual(Permission.from_char("r"), Permission.READ)
        self.assertEqual(Permission.from_char("w"), Permission.WRITE)
        self.assertEqual(Permission.from_char("x"), Permission.EXECUTE)
        self.assertEqual(Permission.from_char("-"), Permission.NONE)
        with self.assertRaises(ValueError):
            Permission.from_char("z")

    def test_permission_triple_from_octal(self):
        t7 = PermissionTriple.from_octal_digit(7)
        self.assertTrue(t7.read and t7.write and t7.execute)
        self.assertEqual(t7.to_octal_digit(), 7)
        self.assertEqual(t7.to_symbolic(), "rwx")

        t5 = PermissionTriple.from_octal_digit(5)
        self.assertTrue(t5.read and not t5.write and t5.execute)
        self.assertEqual(t5.to_octal_digit(), 5)
        self.assertEqual(t5.to_symbolic(), "r-x")

        t0 = PermissionTriple.from_octal_digit(0)
        self.assertFalse(t0.read or t0.write or t0.execute)
        self.assertEqual(t0.to_octal_digit(), 0)
        self.assertEqual(t0.to_symbolic(), "---")

        with self.assertRaises(ValueError):
            PermissionTriple.from_octal_digit(8)

    def test_permission_triple_from_symbolic(self):
        t = PermissionTriple.from_symbolic("rw-")
        self.assertTrue(t.read and t.write and not t.execute)
        self.assertEqual(t.to_octal_digit(), 6)

        with self.assertRaises(ValueError):
            PermissionTriple.from_symbolic("rwx-extra")
        with self.assertRaises(ValueError):
            PermissionTriple.from_symbolic("abc")

    def test_permission_triple_has_permission(self):
        t = PermissionTriple(read=True, write=False, execute=True)
        self.assertTrue(t.has_permission("r"))
        self.assertFalse(t.has_permission("w"))
        self.assertTrue(t.has_permission("x"))
        self.assertTrue(t.has_permission(Permission.READ))
        self.assertFalse(t.has_permission(Permission.WRITE))
        self.assertTrue(t.has_permission(Permission.EXECUTE))
        self.assertTrue(t.has_permission("rx"))
        self.assertFalse(t.has_permission("rw"))


class TestFilePermissions(unittest.TestCase):
    """Test 9-bit FilePermissions parsing, formatting, and chmod mutations."""

    def test_from_octal_int_and_str(self):
        p755 = FilePermissions.from_octal(0o755)
        self.assertEqual(p755.to_octal_str(), "755")
        self.assertEqual(p755.to_octal_int(), 0o755)
        self.assertEqual(p755.to_short_symbolic(), "rwxr-xr-x")
        self.assertEqual(p755.to_symbolic(is_directory=True), "drwxr-xr-x")
        self.assertEqual(p755.to_symbolic(is_directory=False), "-rwxr-xr-x")

        p750 = FilePermissions.from_octal("750")
        self.assertEqual(p750.to_octal_str(), "750")
        self.assertEqual(p750.to_short_symbolic(), "rwxr-x---")

        p644 = FilePermissions.from_octal("0644")
        self.assertEqual(p644.to_octal_str(), "644")
        self.assertEqual(p644.to_short_symbolic(), "rw-r--r--")

    def test_from_symbolic(self):
        p = FilePermissions.from_symbolic("rwxr-xr-x")
        self.assertEqual(p.to_octal_str(), "755")

        p_with_dash = FilePermissions.from_symbolic("-rwxr-x---")
        self.assertEqual(p_with_dash.to_octal_str(), "750")

        p_dir = FilePermissions.from_symbolic("drwxr-xr-x")
        self.assertEqual(p_dir.to_octal_str(), "755")

    def test_parse_universal(self):
        self.assertEqual(FilePermissions.parse(0o755).to_octal_str(), "755")
        self.assertEqual(FilePermissions.parse("755").to_octal_str(), "755")
        self.assertEqual(FilePermissions.parse("rwxr-xr-x").to_octal_str(), "755")
        self.assertEqual(FilePermissions.parse("-rwxr-xr-x").to_octal_str(), "755")

        with self.assertRaises(ValueError):
            FilePermissions.parse("invalid_perm")

    def test_apply_chmod_octal_and_relative(self):
        p = FilePermissions.from_octal("644")  # rw-r--r--

        # chmod +x on all
        p_exec = p.apply_chmod("+x")
        self.assertEqual(p_exec.to_octal_str(), "755")

        # chmod u+x
        p_u_exec = p.apply_chmod("u+x")
        self.assertEqual(p_u_exec.to_octal_str(), "744")

        # chmod g-r
        p_g_sub = p.apply_chmod("g-r")
        self.assertEqual(p_g_sub.to_octal_str(), "604")

        # chmod o=
        p_o_clear = p.apply_chmod("o=")
        self.assertEqual(p_o_clear.to_octal_str(), "640")

        # direct octal replacement
        p_new = p.apply_chmod("750")
        self.assertEqual(p_new.to_octal_str(), "750")


class TestACLEvaluation(unittest.TestCase):
    """Test POSIX standard permission resolution order."""

    def test_root_and_kernel_mode_bypass(self):
        acl = ACL(owner="alice", group="staff", mode="000")
        # Root bypasses all restrictions
        self.assertTrue(acl.check_access("root", [], Permission.READ, is_kernel_or_root=True))
        self.assertTrue(acl.check_access("root", [], Permission.WRITE, is_kernel_or_root=False))
        self.assertTrue(acl.check_access("bob", [], Permission.READ, is_kernel_or_root=True))

    def test_owner_priority_rule(self):
        # In POSIX, if user == owner, only owner bits apply even if group has wider access!
        acl = ACL(owner="carlos", group="devs", mode="075")  # owner: ---, group: rwx, others: r-x
        # Carlos is owner, but owner has 0 (no read)
        self.assertFalse(acl.check_access("carlos", ["devs"], Permission.READ))
        self.assertFalse(acl.check_access("carlos", ["devs"], Permission.WRITE))

    def test_group_priority_rule(self):
        # Alice is in group 'devs', not owner. Mode 750 (owner: rwx, group: r-x, others: ---)
        acl = ACL(owner="root", group="devs", mode="750")
        self.assertTrue(acl.check_access("alice", ["devs"], Permission.READ))
        self.assertFalse(acl.check_access("alice", ["devs"], Permission.WRITE))
        self.assertTrue(acl.check_access("alice", ["devs"], Permission.EXECUTE))

    def test_others_rule(self):
        # Bob is neither root, nor owner, nor in group 'admin'
        acl = ACL(owner="root", group="admin", mode="754")  # others: r--
        self.assertTrue(acl.check_access("bob", ["users"], Permission.READ))
        self.assertFalse(acl.check_access("bob", ["users"], Permission.WRITE))
        self.assertFalse(acl.check_access("bob", ["users"], Permission.EXECUTE))

    def test_static_evaluate_helper(self):
        granted = ACL.evaluate(
            owner="root",
            group="admin",
            permissions="750",
            user="carlos",
            user_groups=["devs"],
            required_perm=Permission.READ,
        )
        self.assertFalse(granted)


class TestAuditLog(unittest.TestCase):
    """Test structured audit event generation, filtering, formatting, and concurrency."""

    def setUp(self):
        self.audit = AuditLog(max_entries=100)

    def test_record_and_get_events(self):
        self.audit.log_login_success("carlos", details={"ip": "127.0.0.1"})
        self.audit.log_access_denied("carlos", path="/sistema/config.sys", action="READ")
        self.audit.log_access_granted("root", path="/sistema/config.sys", action="READ")

        self.assertEqual(self.audit.count(), 3)
        events = self.audit.get_events()
        self.assertEqual(len(events), 3)

        # Filter by type
        denied_events = self.audit.filter_by_type(AuditEventType.ACCESS_DENIED)
        self.assertEqual(len(denied_events), 1)
        self.assertEqual(denied_events[0].username, "carlos")
        self.assertEqual(denied_events[0].path, "/sistema/config.sys")

        # Filter by user
        carlos_events = self.audit.filter_by_user("carlos")
        self.assertEqual(len(carlos_events), 2)

    def test_max_entries_eviction(self):
        small_log = AuditLog(max_entries=3)
        for i in range(5):
            small_log.log_event(AuditEventType.ACCESS_GRANTED, username=f"user{i}")

        self.assertEqual(small_log.count(), 3)
        users = [e.username for e in small_log.get_events()]
        self.assertEqual(users, ["user2", "user3", "user4"])

    def test_formatting_output(self):
        self.audit.log_access_denied("carlos", path="/sistema/config.sys", action="READ")
        table_str = self.audit.format_events()
        self.assertIn("REGISTRO DE AUDITORIA DO SISTEMA", table_str)
        self.assertIn("ACCESS_DENIED", table_str)
        self.assertIn("carlos", table_str)
        self.assertIn("/sistema/config.sys", table_str)

    def test_thread_safety(self):
        log = AuditLog()

        def worker(user_id: int):
            for _ in range(50):
                log.log_access_granted(username=f"worker_{user_id}", path="/resource")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(log.count(), 250)


class TestSecurityManager(unittest.TestCase):
    """Test SecurityManager integration with ACLs, Filesystem, and AuditLog."""

    def setUp(self):
        self.device = InMemoryBlockDevice(capacity=16, block_size=4096)
        self.audit_log = AuditLog()
        self.security_mgr = SecurityManager(audit_log=self.audit_log)
        self.fs = FileSystemService(
            block_device=self.device,
            auth_port=self.security_mgr,
            default_strategy=AllocationStrategy.INDEXED,
        )
        self.security_mgr.set_filesystem(self.fs)

    def test_scenario_sec_002_ground_truth(self):
        """Scenario SEC-002: Carlos (devs) attempts to read /sistema/config.sys (750 root:admin).
        
        Expected:
        - PermissionDeniedException raised on enforce_read / authorize_read.
        - check_read returns False.
        - Event ACCESS_DENIED recorded in AuditLog with user carlos, path /sistema/config.sys, action READ.
        """
        # 1. Setup filesystem hierarchy
        self.fs.mkdir("/sistema")
        file_node = self.fs.create_file("/sistema/config.sys")
        inode = self.fs.inode_table[file_node.inode_id]
        inode.owner = "root"
        inode.group = "admin"
        inode.permissions = "750"

        # 2. Context of non-privileged user Carlos (group devs)
        carlos_ctx = ExecutionContext(
            user_id=1001,
            username="carlos",
            groups=["devs"],
            privilege_mode=PrivilegeMode.USER_MODE,
            cwd="/",
        )

        # 3. Check read returns False
        allowed = self.security_mgr.check_read(carlos_ctx, "/sistema/config.sys", inode=inode)
        self.assertFalse(allowed)

        # 4. Enforce read raises PermissionDeniedException
        with self.assertRaises(PermissionDeniedException) as ctx:
            self.security_mgr.enforce_read(carlos_ctx, "/sistema/config.sys", inode=inode)
        self.assertIn("permissão de leitura", str(ctx.exception).lower())

        # 5. Verify AuditLog
        denied_events = self.audit_log.filter_by_type(AuditEventType.ACCESS_DENIED)
        self.assertEqual(len(denied_events), 2)
        event = denied_events[0]
        self.assertEqual(event.username, "carlos")
        self.assertEqual(event.path, "/sistema/config.sys")
        self.assertEqual(event.action, "READ")
        self.assertEqual(event.details["owner"], "root")
        self.assertEqual(event.details["group"], "admin")
        self.assertEqual(event.details["permissions"], "750")

        # 6. Admin user in 'admin' group has read access (750 grants r-x to group)
        admin_ctx = ExecutionContext(
            user_id=1002,
            username="ana",
            groups=["admin"],
            privilege_mode=PrivilegeMode.USER_MODE,
            cwd="/",
        )
        self.assertTrue(self.security_mgr.check_read(admin_ctx, "/sistema/config.sys", inode=inode))
        # But group 'admin' does NOT have write permission on 750
        self.assertFalse(self.security_mgr.check_write(admin_ctx, "/sistema/config.sys", inode=inode))

        # 7. Root user bypasses all restrictions
        root_ctx = ExecutionContext(
            user_id=0,
            username="root",
            groups=["root", "admin"],
            privilege_mode=PrivilegeMode.KERNEL_MODE,
            cwd="/",
        )
        self.assertTrue(self.security_mgr.check_read(root_ctx, "/sistema/config.sys", inode=inode))
        self.assertTrue(self.security_mgr.check_write(root_ctx, "/sistema/config.sys", inode=inode))

    def test_directory_traversal_enforcement(self):
        """Directory traversal requires 'x' on every parent directory in the path."""
        # Create /private/logs/app.log
        self.fs.mkdir("/private")
        self.fs.mkdir("/private/logs")
        file_node = self.fs.create_file("/private/logs/app.log")
        file_inode = self.fs.inode_table[file_node.inode_id]
        file_inode.owner = "carlos"
        file_inode.group = "devs"
        file_inode.permissions = "644"

        # Set /private to mode 700 owned by root
        private_node = self.fs.vfs.get_node("/private")
        private_inode = self.fs.inode_table[private_node.inode_id]
        private_inode.owner = "root"
        private_inode.group = "root"
        private_inode.permissions = "700"  # rwx------

        carlos_ctx = ExecutionContext(
            user_id=1001,
            username="carlos",
            groups=["devs"],
            privilege_mode=PrivilegeMode.USER_MODE,
        )

        # Carlos owns app.log, but cannot traverse /private!
        self.assertFalse(self.security_mgr.check_read(carlos_ctx, "/private/logs/app.log", inode=file_inode))
        with self.assertRaises(PermissionDeniedException):
            self.security_mgr.enforce_read(carlos_ctx, "/private/logs/app.log", inode=file_inode)

        # Make /private traversable (755)
        private_inode.permissions = "755"
        self.assertTrue(self.security_mgr.check_read(carlos_ctx, "/private/logs/app.log", inode=file_inode))

    def test_chmod_operations(self):
        """Test chmod privilege enforcement: owner or root only."""
        file_node = self.fs.create_file("/test.txt")
        inode = self.fs.inode_table[file_node.inode_id]
        inode.owner = "carlos"
        inode.group = "devs"
        inode.permissions = "644"

        carlos_ctx = ExecutionContext(user_id=1001, username="carlos", groups=["devs"], privilege_mode=PrivilegeMode.USER_MODE)
        intruder_ctx = ExecutionContext(user_id=1002, username="eve", groups=["users"], privilege_mode=PrivilegeMode.USER_MODE)
        root_ctx = ExecutionContext(user_id=0, username="root", groups=["root"], privilege_mode=PrivilegeMode.KERNEL_MODE)

        # Intruder cannot chmod
        with self.assertRaises(PermissionDeniedException):
            self.security_mgr.chmod(intruder_ctx, "/test.txt", "777", inode=inode)

        # Owner can chmod
        new_mode = self.security_mgr.chmod(carlos_ctx, "/test.txt", "600", inode=inode)
        self.assertEqual(new_mode, "600")
        self.assertEqual(inode.permissions, "600")

        # Root can chmod
        new_mode_root = self.security_mgr.chmod(root_ctx, "/test.txt", "755", inode=inode)
        self.assertEqual(new_mode_root, "755")
        self.assertEqual(inode.permissions, "755")

        # Relative chmod
        self.security_mgr.chmod(carlos_ctx, "/test.txt", "g-r", inode=inode)
        self.assertEqual(inode.permissions, "715")

    def test_chown_operations(self):
        """Test chown privilege enforcement: root for owner, owner/root for group."""
        file_node = self.fs.create_file("/doc.txt")
        inode = self.fs.inode_table[file_node.inode_id]
        inode.owner = "carlos"
        inode.group = "devs"

        carlos_ctx = ExecutionContext(user_id=1001, username="carlos", groups=["devs", "staff"], privilege_mode=PrivilegeMode.USER_MODE)
        intruder_ctx = ExecutionContext(user_id=1002, username="eve", groups=["users"], privilege_mode=PrivilegeMode.USER_MODE)
        root_ctx = ExecutionContext(user_id=0, username="root", groups=["root"], privilege_mode=PrivilegeMode.KERNEL_MODE)

        # Carlos (non-root) cannot transfer ownership to someone else
        with self.assertRaises(PermissionDeniedException):
            self.security_mgr.chown(carlos_ctx, "/doc.txt", owner="alice", inode=inode)

        # Carlos can change group to another group he belongs to
        self.security_mgr.chown(carlos_ctx, "/doc.txt", group="staff", inode=inode)
        self.assertEqual(inode.group, "staff")

        # Carlos cannot change group to a group he does NOT belong to
        with self.assertRaises(PermissionDeniedException):
            self.security_mgr.chown(carlos_ctx, "/doc.txt", group="admin", inode=inode)

        # Root can change both owner and group arbitrarily
        self.security_mgr.chown(root_ctx, "/doc.txt", owner="bob", group="finance", inode=inode)
        self.assertEqual(inode.owner, "bob")
        self.assertEqual(inode.group, "finance")


if __name__ == "__main__":
    unittest.main()
