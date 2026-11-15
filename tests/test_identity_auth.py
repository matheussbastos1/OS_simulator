"""Unit tests for Identity, User/Group Management, and Authentication Service (Etapa 3).

Validates:
- User and Group dataclasses and methods.
- UserManager CRUD operations, constraints, and default state.
- AuthenticationService PBKDF2-HMAC-SHA256 password hashing (600,000 iterations, 16B salt).
- Resistance against user enumeration (generic error message, dummy hash computation).
- Privilege ring transitions (USER_MODE <-> KERNEL_MODE).
- AuditLog integration for authentication and elevation events.
- Compliance with Scenario SEC-001 from tests/GROUND_TRUTH.md.
"""

from __future__ import annotations

import unittest
from os_simulator.core.context import ExecutionContext
from os_simulator.core.exceptions import (
    AuthenticationFailedException,
    GroupAlreadyExistsException,
    GroupNotFoundException,
    PermissionDeniedException,
    PrivilegeViolationException,
    SecurityException,
    UserAlreadyExistsException,
    UserNotFoundException,
)
from os_simulator.core.types import AuditEventType, PrivilegeMode
from os_simulator.security.audit import AuditLog
from os_simulator.security.auth import AuthenticationService
from os_simulator.security.user import Group, User, UserManager


class TestUserAndGroupEntities(unittest.TestCase):
    """Test User and Group data structures and properties."""

    def test_group_dataclass_and_membership(self) -> None:
        group = Group(group_id=1001, name="developers", members=["alice"])
        self.assertEqual(group.group_id, 1001)
        self.assertEqual(group.name, "developers")
        self.assertTrue(group.has_member("alice"))
        self.assertFalse(group.has_member("bob"))

        group.add_member("bob")
        self.assertTrue(group.has_member("bob"))
        self.assertEqual(group.members, ["alice", "bob"])

        # Duplicate addition is idempotent
        group.add_member("bob")
        self.assertEqual(len(group.members), 2)

        group.remove_member("alice")
        self.assertFalse(group.has_member("alice"))
        self.assertEqual(group.members, ["bob"])

        d = group.to_dict()
        self.assertEqual(d["group_id"], 1001)
        self.assertEqual(d["name"], "developers")
        self.assertEqual(d["members"], ["bob"])

    def test_user_dataclass_and_properties(self) -> None:
        user = User(
            user_id=1000,
            username="carlos",
            primary_group="devs",
            supplementary_groups=["docker", "testers", "devs"],  # note 'devs' duplicate
            salt=b"0123456789abcdef",
            password_hash="fakehashhex",
            iterations=600_000,
        )
        self.assertEqual(user.user_id, 1000)
        self.assertEqual(user.username, "carlos")
        self.assertEqual(user.primary_group, "devs")
        # groups property should place primary group first and eliminate duplicates
        self.assertEqual(user.groups, ["devs", "docker", "testers"])
        self.assertTrue(user.has_group("devs"))
        self.assertTrue(user.has_group("docker"))
        self.assertFalse(user.has_group("root"))
        self.assertFalse(user.is_root())

        # Protected dictionary representation
        safe_dict = user.to_dict(include_protected=False)
        self.assertEqual(safe_dict["password_hash"], "[PROTECTED]")
        self.assertEqual(safe_dict["salt"], "[PROTECTED]")
        self.assertEqual(safe_dict["username"], "carlos")

        full_dict = user.to_dict(include_protected=True)
        self.assertEqual(full_dict["password_hash"], "fakehashhex")
        self.assertEqual(full_dict["salt"], b"0123456789abcdef".hex())

    def test_root_user_identification(self) -> None:
        root_by_id = User(user_id=0, username="superuser", primary_group="root")
        self.assertTrue(root_by_id.is_root())

        root_by_name = User(user_id=999, username="root", primary_group="root")
        self.assertTrue(root_by_name.is_root())

        normal_user = User(user_id=1000, username="alice", primary_group="users")
        self.assertFalse(normal_user.is_root())


class TestUserManager(unittest.TestCase):
    """Test UserManager functionality including CRUD and default system state."""

    def setUp(self) -> None:
        # Use fast iterations for bulk manager tests
        self.user_manager = UserManager(default_root_password="rootpassword", default_iterations=1_000)

    def test_default_initialization(self) -> None:
        # Check system groups
        root_group = self.user_manager.get_group("root")
        self.assertIsNotNone(root_group)
        self.assertEqual(root_group.group_id, 0)
        self.assertIn("root", root_group.members)

        admin_group = self.user_manager.get_group("admin")
        self.assertIsNotNone(admin_group)
        self.assertEqual(admin_group.group_id, 1)
        self.assertIn("root", admin_group.members)

        users_group = self.user_manager.get_group("users")
        self.assertIsNotNone(users_group)
        self.assertEqual(users_group.group_id, 100)

        # Check default root user
        root_user = self.user_manager.get_user("root")
        self.assertIsNotNone(root_user)
        self.assertEqual(root_user.user_id, 0)
        self.assertEqual(root_user.primary_group, "root")
        self.assertIn("admin", root_user.supplementary_groups)
        self.assertTrue(root_user.is_root())
        self.assertEqual(len(root_user.salt), 16)
        self.assertTrue(len(root_user.password_hash) > 0)

        # Lookup by ID
        self.assertEqual(self.user_manager.get_user_by_id(0), root_user)
        self.assertEqual(self.user_manager.get_group_by_id(0), root_group)

    def test_groupadd_and_groupdel(self) -> None:
        grp = self.user_manager.groupadd("developers")
        self.assertEqual(grp.name, "developers")
        self.assertGreaterEqual(grp.group_id, 1000)
        self.assertTrue(self.user_manager.group_exists("developers"))

        # Duplicate group name raises
        with self.assertRaises(GroupAlreadyExistsException):
            self.user_manager.groupadd("developers")

        # Explicit GID
        grp2 = self.user_manager.groupadd("qa", group_id=2000)
        self.assertEqual(grp2.group_id, 2000)

        # Duplicate GID raises
        with self.assertRaises(GroupAlreadyExistsException):
            self.user_manager.groupadd("qa2", group_id=2000)

        # Cannot delete essential groups
        with self.assertRaises(SecurityException):
            self.user_manager.groupdel("root")
        with self.assertRaises(SecurityException):
            self.user_manager.groupdel("admin")
        with self.assertRaises(SecurityException):
            self.user_manager.groupdel("users")

        # Normal group deletion
        self.user_manager.groupdel("qa")
        self.assertFalse(self.user_manager.group_exists("qa"))
        self.assertIsNone(self.user_manager.get_group("qa"))

        # Deleting non-existent group raises
        with self.assertRaises(GroupNotFoundException):
            self.user_manager.groupdel("nonexistent_group")

    def test_useradd_validation_and_creation(self) -> None:
        self.user_manager.groupadd("staff")
        user = self.user_manager.useradd(
            username="bob",
            password="secretpassword",
            primary_group="staff",
            supplementary_groups=["users"],
        )
        self.assertEqual(user.username, "bob")
        self.assertGreaterEqual(user.user_id, 1000)
        self.assertEqual(user.primary_group, "staff")
        self.assertEqual(user.supplementary_groups, ["users"])
        self.assertEqual(user.groups, ["staff", "users"])
        self.assertEqual(len(user.salt), 16)
        self.assertTrue(len(user.password_hash) > 0)

        # Check group membership lists
        self.assertIn("bob", self.user_manager.get_group("staff").members)
        self.assertIn("bob", self.user_manager.get_group("users").members)

        # Duplicate user raises
        with self.assertRaises(UserAlreadyExistsException):
            self.user_manager.useradd("bob", password="123")

        # Invalid username raises
        with self.assertRaises(SecurityException):
            self.user_manager.useradd("invalid username with spaces!")

        # Non-existent primary group raises
        with self.assertRaises(GroupNotFoundException):
            self.user_manager.useradd("charlie", primary_group="ghost_group")

        # Non-existent supplementary group raises
        with self.assertRaises(GroupNotFoundException):
            self.user_manager.useradd("charlie", primary_group="staff", supplementary_groups=["ghost_group"])

    def test_userdel(self) -> None:
        self.user_manager.groupadd("testers")
        self.user_manager.useradd("dave", password="123", primary_group="testers")
        self.assertTrue(self.user_manager.user_exists("dave"))
        self.assertIn("dave", self.user_manager.get_group("testers").members)

        # Cannot delete root
        with self.assertRaises(PermissionDeniedException):
            self.user_manager.userdel("root")

        # Delete dave
        self.user_manager.userdel("dave")
        self.assertFalse(self.user_manager.user_exists("dave"))
        self.assertIsNone(self.user_manager.get_user("dave"))
        self.assertNotIn("dave", self.user_manager.get_group("testers").members)

        # Deleting non-existent user raises
        with self.assertRaises(UserNotFoundException):
            self.user_manager.userdel("dave")

    def test_cannot_delete_group_if_primary_group_of_user(self) -> None:
        self.user_manager.groupadd("finance")
        self.user_manager.useradd("eva", password="123", primary_group="finance")

        with self.assertRaises(SecurityException):
            self.user_manager.groupdel("finance")

    def test_usermod_operations(self) -> None:
        self.user_manager.groupadd("dev")
        self.user_manager.groupadd("ops")
        self.user_manager.groupadd("sec")

        user = self.user_manager.useradd("frank", password="oldpass", primary_group="dev", supplementary_groups=["ops"])
        self.assertIn("frank", self.user_manager.get_group("dev").members)
        self.assertIn("frank", self.user_manager.get_group("ops").members)

        # Change primary group
        self.user_manager.usermod("frank", primary_group="ops")
        self.assertEqual(user.primary_group, "ops")
        self.assertNotIn("frank", self.user_manager.get_group("dev").members)
        self.assertIn("frank", self.user_manager.get_group("ops").members)

        # Add supplementary group
        self.user_manager.usermod("frank", add_groups=["sec"])
        self.assertIn("sec", user.supplementary_groups)
        self.assertIn("frank", self.user_manager.get_group("sec").members)

        # Remove group
        self.user_manager.usermod("frank", remove_groups=["sec"])
        self.assertNotIn("sec", user.supplementary_groups)
        self.assertNotIn("frank", self.user_manager.get_group("sec").members)

        # Update password
        old_hash = user.password_hash
        self.user_manager.usermod("frank", password="newpassword123")
        self.assertNotEqual(user.password_hash, old_hash)


class TestAuthenticationService(unittest.TestCase):
    """Test PBKDF2 authentication, anti-enumeration, session context, and privilege rings."""

    def setUp(self) -> None:
        self.audit_log = AuditLog()
        # Fast iterations for general auth tests
        self.user_manager = UserManager(default_root_password="rootpassword", default_iterations=1_000)
        self.auth_service = AuthenticationService(
            user_manager=self.user_manager,
            audit_log=self.audit_log,
            default_iterations=1_000,
        )

    def test_hash_password_and_verify_pbkdf2(self) -> None:
        pwd = "MinhaSenhaSuperSecreta!#2026"
        hash_hex, salt = AuthenticationService.hash_password(pwd, iterations=2_000)
        self.assertEqual(len(salt), 16)
        self.assertIsInstance(hash_hex, str)
        self.assertEqual(len(hash_hex), 64)  # 256 bits = 32 bytes = 64 hex characters

        # Verification succeeds with matching password
        self.assertTrue(AuthenticationService.verify_password(pwd, hash_hex, salt, iterations=2_000))
        # Verification fails with incorrect password
        self.assertFalse(AuthenticationService.verify_password("SenhaErrada!", hash_hex, salt, iterations=2_000))
        # Verification fails with tampered hash
        tampered_hash = ("0" if hash_hex[0] != "0" else "1") + hash_hex[1:]
        self.assertFalse(AuthenticationService.verify_password(pwd, tampered_hash, salt, iterations=2_000))

    def test_login_successful_regular_user(self) -> None:
        self.user_manager.groupadd("developers")
        self.user_manager.useradd(
            username="alice",
            password="alicepassword",
            primary_group="developers",
            supplementary_groups=["users"],
        )

        ctx = self.auth_service.login("alice", "alicepassword")
        self.assertEqual(ctx.username, "alice")
        self.assertEqual(ctx.primary_group, "developers")
        self.assertIn("users", ctx.groups)
        self.assertEqual(ctx.privilege_mode, PrivilegeMode.USER_MODE)
        self.assertTrue(ctx.is_user_mode())
        self.assertFalse(ctx.is_root())
        self.assertFalse(ctx.is_kernel_mode())
        self.assertEqual(ctx.cwd, "/home/alice")

        # Verify audit event
        events = self.audit_log.get_events()
        self.assertTrue(any(e.event_type == AuditEventType.LOGIN_SUCCESS and e.username == "alice" for e in events))

    def test_login_successful_root_user(self) -> None:
        ctx = self.auth_service.login("root", "rootpassword")
        self.assertEqual(ctx.username, "root")
        self.assertEqual(ctx.user_id, 0)
        self.assertEqual(ctx.privilege_mode, PrivilegeMode.KERNEL_MODE)
        self.assertTrue(ctx.is_root())
        self.assertTrue(ctx.is_kernel_mode())
        self.assertEqual(ctx.cwd, "/")

    def test_anti_enumeration_nonexistent_user_and_wrong_password(self) -> None:
        # Both must raise AuthenticationFailedException with generic identical message
        with self.assertRaises(AuthenticationFailedException) as cm_ghost:
            self.auth_service.login("ghost_user", "somepassword")

        with self.assertRaises(AuthenticationFailedException) as cm_wrong_pwd:
            self.auth_service.login("root", "wrongpassword")

        self.assertEqual(str(cm_ghost.exception), "Falha na autenticação: credenciais inválidas.")
        self.assertEqual(str(cm_wrong_pwd.exception), "Falha na autenticação: credenciais inválidas.")

        # Check that LOGIN_FAILED events were recorded
        events = self.audit_log.get_events()
        login_fails = [e for e in events if e.event_type == AuditEventType.LOGIN_FAILED]
        self.assertGreaterEqual(len(login_fails), 2)
        # Verify no plaintext password was written into audit log
        for e in events:
            self.assertNotIn("somepassword", str(e.details))
            self.assertNotIn("wrongpassword", str(e.details))

    def test_logout(self) -> None:
        ctx = self.auth_service.login("root", "rootpassword")
        guest_ctx = self.auth_service.logout(ctx)

        self.assertEqual(guest_ctx.username, "guest")
        self.assertEqual(guest_ctx.user_id, 65534)
        self.assertEqual(guest_ctx.privilege_mode, PrivilegeMode.USER_MODE)
        self.assertFalse(guest_ctx.is_root())

        events = self.audit_log.get_events()
        self.assertTrue(any(e.event_type == AuditEventType.LOGOUT for e in events))

    def test_privilege_elevation_and_drop(self) -> None:
        # User in admin group can elevate with valid password
        self.user_manager.useradd(
            username="admin_user",
            password="adminpassword",
            primary_group="users",
            supplementary_groups=["admin"],
        )

        user_ctx = self.auth_service.login("admin_user", "adminpassword")
        self.assertEqual(user_ctx.privilege_mode, PrivilegeMode.USER_MODE)

        # Elevation requires correct password
        with self.assertRaises(AuthenticationFailedException):
            self.auth_service.elevate_privileges(user_ctx, password="wrongpassword")

        # Elevation without password raises
        with self.assertRaises(AuthenticationFailedException):
            self.auth_service.elevate_privileges(user_ctx, password=None)

        # Successful elevation
        kernel_ctx = self.auth_service.elevate_privileges(user_ctx, password="adminpassword")
        self.assertEqual(kernel_ctx.privilege_mode, PrivilegeMode.KERNEL_MODE)
        self.assertTrue(kernel_ctx.is_kernel_mode())
        self.assertTrue(kernel_ctx.is_root())

        # Unconditional drop to USER_MODE
        dropped_ctx = self.auth_service.drop_privileges(kernel_ctx)
        self.assertEqual(dropped_ctx.privilege_mode, PrivilegeMode.USER_MODE)
        self.assertFalse(dropped_ctx.is_kernel_mode())

    def test_privilege_elevation_denied_for_non_admin_user(self) -> None:
        # Standard user without 'admin' or 'root' group cannot elevate
        self.user_manager.useradd(
            username="normal_user",
            password="normalpassword",
            primary_group="users",
        )
        user_ctx = self.auth_service.login("normal_user", "normalpassword")

        with self.assertRaises(PrivilegeViolationException):
            self.auth_service.elevate_privileges(user_ctx, password="normalpassword")

        # Check audit event for denied elevation
        events = self.audit_log.get_events()
        self.assertTrue(any(
            e.event_type == AuditEventType.ACCESS_DENIED and e.action == "PRIVILEGE_ELEVATION"
            for e in events
        ))

    def test_switch_user_su_behavior(self) -> None:
        self.user_manager.useradd("target_user", password="targetpassword")

        # 1. Root can switch to target_user without password
        root_ctx = self.auth_service.login("root", "rootpassword")
        switched_ctx = self.auth_service.switch_user(root_ctx, "target_user")
        self.assertEqual(switched_ctx.username, "target_user")
        self.assertEqual(switched_ctx.privilege_mode, PrivilegeMode.USER_MODE)

        # 2. Regular user cannot switch to another user without password
        alice = self.user_manager.useradd("alice", password="alicepass")
        alice_ctx = self.auth_service.login("alice", "alicepass")
        with self.assertRaises(AuthenticationFailedException):
            self.auth_service.switch_user(alice_ctx, "target_user", password=None)

        # 3. Regular user with correct password switches successfully
        alice_switched = self.auth_service.switch_user(alice_ctx, "target_user", password="targetpassword")
        self.assertEqual(alice_switched.username, "target_user")

    def test_change_password(self) -> None:
        user = self.user_manager.useradd("george", password="initialpassword")
        ctx = self.auth_service.login("george", "initialpassword")

        # User changing own password requires correct old password
        with self.assertRaises(AuthenticationFailedException):
            self.auth_service.change_password(ctx, "george", "newpass", old_password="wrongold")

        self.auth_service.change_password(ctx, "george", "newpass123", old_password="initialpassword")

        # Old password no longer works
        with self.assertRaises(AuthenticationFailedException):
            self.auth_service.login("george", "initialpassword")

        # New password works
        new_ctx = self.auth_service.login("george", "newpass123")
        self.assertEqual(new_ctx.username, "george")

        # Root can change george's password without old password
        root_ctx = self.auth_service.login("root", "rootpassword")
        self.auth_service.change_password(root_ctx, "george", "root_set_this_pass")
        self.auth_service.login("george", "root_set_this_pass")


class TestScenarioSEC001(unittest.TestCase):
    """Ground Truth Scenario SEC-001: Autenticação Criptográfica com PBKDF2 e Salt.

    Specification from tests/GROUND_TRUTH.md:
    - User 'carlos' registered with 16-byte random salt and PBKDF2 hash with 600,000 iterations in group 'devs'.
    - Command executed: login --user carlos (with password provided).
    - Expected result: calculates PBKDF2 with 600,000 iterations and registered salt, compares via hmac.compare_digest.
    - Approval criteria: context.username == "carlos" and event recorded in AuditLog.
    """

    def test_scenario_sec_001_ground_truth_full_iterations(self) -> None:
        audit_log = AuditLog()
        user_mgr = UserManager(default_root_password="root_password", default_iterations=600_000)
        user_mgr.groupadd("devs")

        # Setup state: carlos in group 'devs' with 600,000 iterations and 16-byte random salt
        user_carlos = user_mgr.useradd(
            username="carlos",
            password="SenhaForteDoCarlos!2026",
            primary_group="devs",
            iterations=600_000,
        )

        self.assertEqual(user_carlos.username, "carlos")
        self.assertEqual(user_carlos.primary_group, "devs")
        self.assertEqual(user_carlos.iterations, 600_000)
        self.assertEqual(len(user_carlos.salt), 16)
        self.assertEqual(len(user_carlos.password_hash), 64)

        auth_service = AuthenticationService(
            user_manager=user_mgr,
            audit_log=audit_log,
            default_iterations=600_000,
        )

        # Execution: login as carlos
        context = auth_service.login("carlos", "SenhaForteDoCarlos!2026")

        # Approval criteria 1: context.username == "carlos"
        self.assertEqual(context.username, "carlos")
        self.assertEqual(context.primary_group, "devs")
        self.assertEqual(context.privilege_mode, PrivilegeMode.USER_MODE)
        self.assertFalse(context.is_root())

        # Approval criteria 2: Event recorded in AuditLog
        events = audit_log.get_events()
        login_events = [e for e in events if e.event_type == AuditEventType.LOGIN_SUCCESS and e.username == "carlos"]
        self.assertEqual(len(login_events), 1)
        event = login_events[0]
        self.assertEqual(event.username, "carlos")
        self.assertEqual(event.result, "SUCCESS")
        self.assertEqual(event.details.get("primary_group"), "devs")


if __name__ == "__main__":
    unittest.main()
