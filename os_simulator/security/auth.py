"""Authentication Service with PBKDF2-HMAC-SHA256 and Privilege Ring transitions.

Implements cryptographically secure user authentication conforming to OWASP guidelines:
- 600,000 iterations PBKDF2-HMAC-SHA256
- 16-byte cryptographically secure random salt (secrets.token_bytes)
- Constant-time comparison (hmac.compare_digest)
- Resistance against user enumeration / timing attacks via dummy hashing
- ExecutionContext session creation with PrivilegeMode ring enforcement
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any, Dict, Optional, Tuple

from os_simulator.core.context import ExecutionContext
from os_simulator.core.exceptions import (
    AuthenticationFailedException,
    PermissionDeniedException,
    PrivilegeViolationException,
    UserNotFoundException,
)
from os_simulator.core.types import AuditEventType, PrivilegeMode
from os_simulator.security.audit import AuditLog
from os_simulator.security.user import User, UserManager


class AuthenticationService:
    """Provides authentication, session lifecycle, and privilege ring management."""

    DEFAULT_ITERATIONS: int = 600_000
    SALT_SIZE_BYTES: int = 16

    def __init__(
        self,
        user_manager: UserManager,
        audit_log: Optional[AuditLog] = None,
        default_iterations: int = 600_000,
    ) -> None:
        self.user_manager = user_manager
        self.audit_log = audit_log
        self.default_iterations = default_iterations
        # Dummy salt used for constant-time simulation on non-existent user login attempts
        self._dummy_salt: bytes = secrets.token_bytes(self.SALT_SIZE_BYTES)

    def set_audit_log(self, audit_log: AuditLog) -> None:
        """Set or update the audit log instance."""
        self.audit_log = audit_log

    # =========================================================================
    # Cryptographic Hash & Verification Helpers
    # =========================================================================

    @classmethod
    def hash_password(
        cls,
        password: str,
        salt: Optional[bytes] = None,
        iterations: Optional[int] = None,
    ) -> Tuple[str, bytes]:
        """Derive cryptographic hash from password using PBKDF2-HMAC-SHA256.

        Args:
            password: Plaintext password string.
            salt: Optional 16-byte cryptographic salt. If None, generated via secrets.
            iterations: Number of PBKDF2 iterations (defaults to 600,000).

        Returns:
            Tuple of (hash_hex: str, salt_bytes: bytes).
        """
        if not password:
            raise ValueError("A senha não pode ser vazia.")

        actual_salt = salt if salt is not None else secrets.token_bytes(cls.SALT_SIZE_BYTES)
        actual_iter = iterations if iterations is not None else cls.DEFAULT_ITERATIONS

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            actual_salt,
            actual_iter,
        )
        return digest.hex(), actual_salt

    @classmethod
    def verify_password(
        cls,
        password: str,
        expected_hash_hex: str,
        salt: bytes,
        iterations: Optional[int] = None,
    ) -> bool:
        """Verify plaintext password against stored hash using constant-time comparison.

        Args:
            password: Provided password string.
            expected_hash_hex: Expected hexadecimal hash string.
            salt: Salt bytes used during derivation.
            iterations: Number of PBKDF2 iterations.

        Returns:
            True if matching, False otherwise.
        """
        if not password or not expected_hash_hex or not salt:
            return False

        actual_iter = iterations if iterations is not None else cls.DEFAULT_ITERATIONS
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            actual_iter,
        )
        return hmac.compare_digest(derived.hex(), expected_hash_hex)

    # =========================================================================
    # Login & Logout (Session Lifecycle)
    # =========================================================================

    def login(
        self,
        username: str,
        password: str,
        cwd: str = "/",
    ) -> ExecutionContext:
        """Authenticate user credentials and initialize active execution context.

        Protects against timing attacks and user enumeration by running dummy
        derivation if username does not exist. Generic failure message is raised.

        Args:
            username: Target user identifier.
            password: Password string.
            cwd: Initial current working directory (defaults to '/').

        Returns:
            ExecutionContext initialized with user identity, groups, and privilege ring.

        Raises:
            AuthenticationFailedException: If credentials are invalid or user not found.
        """
        clean_user = username.strip() if username else ""
        user = self.user_manager.get_user(clean_user)

        # Protection against user enumeration: run dummy hash on non-existent user
        if user is None:
            # Constant-time dummy computation
            hashlib.pbkdf2_hmac(
                "sha256",
                (password or "").encode("utf-8"),
                self._dummy_salt,
                self.default_iterations,
            )
            if self.audit_log is not None:
                self.audit_log.log_login_failed(
                    username=clean_user or "unknown",
                    details={"reason": "Credenciais inválidas"},
                )
            raise AuthenticationFailedException("Falha na autenticação: credenciais inválidas.")

        # User exists: verify credentials
        iterations = user.iterations or self.default_iterations
        is_valid = self.verify_password(
            password=password,
            expected_hash_hex=user.password_hash,
            salt=user.salt,
            iterations=iterations,
        )

        if not is_valid:
            if self.audit_log is not None:
                self.audit_log.log_login_failed(
                    username=user.username,
                    details={"reason": "Credenciais inválidas"},
                )
            raise AuthenticationFailedException("Falha na autenticação: credenciais inválidas.")

        # Determine privilege mode: root -> KERNEL_MODE; regular user -> USER_MODE
        privilege_mode = PrivilegeMode.KERNEL_MODE if user.is_root() else PrivilegeMode.USER_MODE

        # Set default cwd to home directory for regular users if cwd is root
        session_cwd = cwd
        if session_cwd == "/" and not user.is_root():
            session_cwd = f"/home/{user.username}"

        context = ExecutionContext(
            user_id=user.user_id,
            username=user.username,
            groups=list(user.groups),
            privilege_mode=privilege_mode,
            cwd=session_cwd,
        )

        if self.audit_log is not None:
            self.audit_log.log_login_success(
                username=user.username,
                details={
                    "user_id": user.user_id,
                    "primary_group": user.primary_group,
                    "groups": list(user.groups),
                    "privilege_mode": privilege_mode.value,
                    "cwd": session_cwd,
                },
            )

        return context

    def logout(self, current_context: Optional[ExecutionContext] = None) -> ExecutionContext:
        """Terminate the active session and return an unprivileged guest context."""
        username = current_context.username if current_context else "anonymous"
        if self.audit_log is not None and current_context is not None:
            self.audit_log.log_event(
                event_type=AuditEventType.LOGOUT,
                username=username,
                action="LOGOUT",
                result="SUCCESS",
                details={"user_id": current_context.user_id},
            )

        # Return guest unprivileged session
        return ExecutionContext(
            user_id=65534,
            username="guest",
            groups=["guest"],
            privilege_mode=PrivilegeMode.USER_MODE,
            cwd="/",
        )

    # =========================================================================
    # Privilege Ring Management & Transitions
    # =========================================================================

    def elevate_privileges(
        self,
        context: ExecutionContext,
        password: Optional[str] = None,
    ) -> ExecutionContext:
        """Elevate execution context to KERNEL_MODE (Anel 0 / Modo Supervisor).

        Rules:
        1. If context is already in KERNEL_MODE, return unchanged.
        2. Non-root user must belong to administrative group ('admin' or 'root') or be UID 0.
           Users without administrative association cannot elevate under any circumstances.
        3. Valid password of the active user must be supplied for verification.

        Args:
            context: Active execution context.
            password: User password for verification.

        Returns:
            New ExecutionContext in KERNEL_MODE.

        Raises:
            PrivilegeViolationException: If user is not authorized to elevate.
            AuthenticationFailedException: If password verification fails.
        """
        if context.privilege_mode == PrivilegeMode.KERNEL_MODE:
            return ExecutionContext(
                user_id=context.user_id,
                username=context.username,
                groups=list(context.groups),
                privilege_mode=PrivilegeMode.KERNEL_MODE,
                cwd=context.cwd,
            )

        # Check authorization to elevate
        is_admin_candidate = (
            context.user_id == 0
            or context.username == "root"
            or "admin" in context.groups
            or "root" in context.groups
        )

        if not is_admin_candidate:
            if self.audit_log is not None:
                self.audit_log.log_access_denied(
                    username=context.username,
                    path=None,
                    action="PRIVILEGE_ELEVATION",
                    details={"reason": "Usuário não possui privilégios administrativos para elevação"},
                )
            raise PrivilegeViolationException(
                f"Acesso negado: usuário '{context.username}' não possui autorização para elevação ao Modo Kernel."
            )

        if not password:
            if self.audit_log is not None:
                self.audit_log.log_login_failed(
                    username=context.username,
                    details={"action": "PRIVILEGE_ELEVATION", "reason": "Senha não fornecida"},
                )
            raise AuthenticationFailedException("Senha obrigatória para elevação de privilégio.")

        # Verify password of the current user
        user = self.user_manager.get_user(context.username)
        if user is None:
            raise AuthenticationFailedException("Falha na autenticação: usuário não encontrado.")

        is_valid = self.verify_password(
            password=password,
            expected_hash_hex=user.password_hash,
            salt=user.salt,
            iterations=user.iterations,
        )

        if not is_valid:
            if self.audit_log is not None:
                self.audit_log.log_login_failed(
                    username=context.username,
                    details={"action": "PRIVILEGE_ELEVATION", "reason": "Senha incorreta"},
                )
            raise AuthenticationFailedException("Falha na elevação de privilégio: senha incorreta.")

        # Elevation granted
        new_context = ExecutionContext(
            user_id=context.user_id,
            username=context.username,
            groups=list(context.groups),
            privilege_mode=PrivilegeMode.KERNEL_MODE,
            cwd=context.cwd,
        )

        if self.audit_log is not None:
            self.audit_log.log_privilege_elevation(
                username=context.username,
                details={
                    "previous_mode": context.privilege_mode.value,
                    "target_mode": PrivilegeMode.KERNEL_MODE.value,
                },
            )

        return new_context

    def drop_privileges(self, context: ExecutionContext) -> ExecutionContext:
        """Drop execution context from KERNEL_MODE to USER_MODE (Anel 3).

        Allowed unconditionally at any time.
        """
        if context.privilege_mode == PrivilegeMode.USER_MODE:
            return context

        new_context = ExecutionContext(
            user_id=context.user_id,
            username=context.username,
            groups=list(context.groups),
            privilege_mode=PrivilegeMode.USER_MODE,
            cwd=context.cwd,
        )

        if self.audit_log is not None:
            self.audit_log.log_event(
                event_type=AuditEventType.PRIVILEGE_ELEVATION,
                username=context.username,
                action="DROP_PRIVILEGES",
                result="SUCCESS",
                details={
                    "previous_mode": context.privilege_mode.value,
                    "target_mode": PrivilegeMode.USER_MODE.value,
                },
            )

        return new_context

    def switch_privilege_mode(
        self,
        context: ExecutionContext,
        target_mode: PrivilegeMode,
        password: Optional[str] = None,
    ) -> ExecutionContext:
        """Switch between USER_MODE and KERNEL_MODE rings."""
        if target_mode == PrivilegeMode.KERNEL_MODE:
            return self.elevate_privileges(context, password=password)
        elif target_mode == PrivilegeMode.USER_MODE:
            return self.drop_privileges(context)
        else:
            raise ValueError(f"Modo de privilégio desconhecido: '{target_mode}'")

    def switch_user(
        self,
        current_context: ExecutionContext,
        target_username: str,
        password: Optional[str] = None,
    ) -> ExecutionContext:
        """Switch session to a different user identity (simulating POSIX 'su').

        - If active context is in KERNEL_MODE or is root, switching does not require password.
        - If active context is a regular user in USER_MODE, target user's password must be verified.
        """
        clean_target = target_username.strip()
        target_user = self.user_manager.get_user(clean_target)
        if target_user is None:
            raise UserNotFoundException(f"Usuário '{clean_target}' não encontrado.")

        # Superuser / Kernel Mode bypass POSIX
        if current_context.is_root() or current_context.privilege_mode == PrivilegeMode.KERNEL_MODE:
            target_priv = PrivilegeMode.KERNEL_MODE if target_user.is_root() else PrivilegeMode.USER_MODE
            session_cwd = "/" if target_user.is_root() else f"/home/{target_user.username}"
            new_context = ExecutionContext(
                user_id=target_user.user_id,
                username=target_user.username,
                groups=list(target_user.groups),
                privilege_mode=target_priv,
                cwd=session_cwd,
            )
            if self.audit_log is not None:
                self.audit_log.log_login_success(
                    username=target_user.username,
                    details={
                        "action": "SU_ROOT",
                        "initiated_by": current_context.username,
                        "privilege_mode": target_priv.value,
                    },
                )
            return new_context

        # Regular user switching requires target password
        if not password:
            raise AuthenticationFailedException(f"Senha obrigatória para alternar para o usuário '{clean_target}'.")

        return self.login(clean_target, password)

    def change_password(
        self,
        context: ExecutionContext,
        username: str,
        new_password: str,
        old_password: Optional[str] = None,
    ) -> None:
        """Change a user's password with proper authorization.

        - Root can change any user's password without supplying old password.
        - Non-root users can only change their own password and must supply old password.
        """
        target_user = self.user_manager.get_user(username)
        if target_user is None:
            raise UserNotFoundException(f"Usuário '{username}' não encontrado.")

        is_admin_caller = context.is_root() or context.privilege_mode == PrivilegeMode.KERNEL_MODE
        is_self = context.username == username

        if not is_admin_caller and not is_self:
            raise PermissionDeniedException(
                f"Usuário '{context.username}' não possui autorização para alterar a senha de '{username}'."
            )

        # Non-admin must verify old password
        if not is_admin_caller:
            if not old_password:
                raise AuthenticationFailedException("A senha atual é obrigatória.")
            if not self.verify_password(
                old_password,
                target_user.password_hash,
                target_user.salt,
                target_user.iterations,
            ):
                raise AuthenticationFailedException("A senha atual está incorreta.")

        # Update password
        self.user_manager.usermod(username=username, password=new_password)

        if self.audit_log is not None:
            self.audit_log.log_event(
                event_type=AuditEventType.USER_MANAGEMENT,
                username=context.username,
                action="CHANGE_PASSWORD",
                result="SUCCESS",
                details={"target_user": username, "by_admin": is_admin_caller},
            )
