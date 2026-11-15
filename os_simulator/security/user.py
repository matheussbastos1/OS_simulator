"""User and Group management entities for OS Simulator (Etapa 3).

Provides POSIX-like user and group models, persistent state management in memory,
and secure credentials storage conforming to OWASP guidelines.
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from os_simulator.core.exceptions import (
    GroupAlreadyExistsException,
    GroupNotFoundException,
    PermissionDeniedException,
    SecurityException,
    UserAlreadyExistsException,
    UserNotFoundException,
)


@dataclass
class Group:
    """Represents a POSIX group."""
    group_id: int
    name: str
    members: List[str] = field(default_factory=list)

    def add_member(self, username: str) -> None:
        """Add a user to this group if not already present."""
        if username not in self.members:
            self.members.append(username)

    def remove_member(self, username: str) -> None:
        """Remove a user from this group."""
        if username in self.members:
            self.members.remove(username)

    def has_member(self, username: str) -> bool:
        """Check if user belongs to this group."""
        return username in self.members

    def to_dict(self) -> Dict[str, Any]:
        """Convert group to dictionary representation."""
        return {
            "group_id": self.group_id,
            "name": self.name,
            "members": list(self.members),
        }


@dataclass
class User:
    """Represents a POSIX user entity with cryptographic credential metadata."""
    user_id: int
    username: str
    primary_group: str
    supplementary_groups: List[str] = field(default_factory=list)
    salt: bytes = field(default_factory=lambda: secrets.token_bytes(16))
    password_hash: str = ""
    created_at: float = field(default_factory=time.time)
    iterations: int = 600_000

    @property
    def groups(self) -> List[str]:
        """Return combined list of primary and supplementary groups without duplicates."""
        result = [self.primary_group]
        for g in self.supplementary_groups:
            if g not in result:
                result.append(g)
        return result

    def is_root(self) -> bool:
        """Return True if user has administrative root privileges (UID 0 or name 'root')."""
        return self.user_id == 0 or self.username == "root"

    def has_group(self, group_name: str) -> bool:
        """Check if user belongs to the specified group."""
        return group_name in self.groups

    def to_dict(self, include_protected: bool = False) -> Dict[str, Any]:
        """Convert user to dictionary representation, protecting cryptographic secrets."""
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "username": self.username,
            "primary_group": self.primary_group,
            "supplementary_groups": list(self.supplementary_groups),
            "groups": self.groups,
            "created_at": self.created_at,
            "iterations": self.iterations,
        }
        if include_protected:
            data["salt"] = self.salt.hex()
            data["password_hash"] = self.password_hash
        else:
            data["salt"] = "[PROTECTED]"
            data["password_hash"] = "[PROTECTED]"
        return data


class UserManager:
    """In-memory POSIX user and group manager."""

    USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_.][a-zA-Z0-9_.-]{0,31}$")
    GROUPNAME_REGEX = re.compile(r"^[a-zA-Z0-9_.][a-zA-Z0-9_.-]{0,31}$")

    def __init__(
        self,
        default_root_password: str = "root",
        default_iterations: int = 600_000,
        fs_service: Optional[Any] = None,
    ) -> None:
        self._users: Dict[str, User] = {}
        self._users_by_id: Dict[int, User] = {}
        self._groups: Dict[str, Group] = {}
        self._groups_by_id: Dict[int, Group] = {}
        self._next_uid: int = 1000
        self._next_gid: int = 1000
        self._default_iterations: int = default_iterations
        self._fs_service: Optional[Any] = fs_service

        self._initialize_defaults(default_root_password)

    def _initialize_defaults(self, root_password: str) -> None:
        """Create baseline root user and system groups (root, admin, users)."""
        # Default system groups
        self._groups["root"] = Group(group_id=0, name="root", members=["root"])
        self._groups_by_id[0] = self._groups["root"]

        self._groups["admin"] = Group(group_id=1, name="admin", members=["root"])
        self._groups_by_id[1] = self._groups["admin"]

        self._groups["users"] = Group(group_id=100, name="users", members=[])
        self._groups_by_id[100] = self._groups["users"]

        # Default root user (UID 0)
        import hashlib
        root_salt = secrets.token_bytes(16)
        root_hash = hashlib.pbkdf2_hmac(
            "sha256",
            root_password.encode("utf-8"),
            root_salt,
            self._default_iterations,
        ).hex()

        root_user = User(
            user_id=0,
            username="root",
            primary_group="root",
            supplementary_groups=["admin"],
            salt=root_salt,
            password_hash=root_hash,
            created_at=time.time(),
            iterations=self._default_iterations,
        )
        self._users["root"] = root_user
        self._users_by_id[0] = root_user

    def set_filesystem(self, fs_service: Any) -> None:
        """Bind filesystem service for automated home directory provisioning."""
        self._fs_service = fs_service

    # =========================================================================
    # Group Management
    # =========================================================================

    def groupadd(self, name: str, group_id: Optional[int] = None) -> Group:
        """Create a new group."""
        name = name.strip()
        if not self.GROUPNAME_REGEX.match(name):
            raise SecurityException(f"Nome de grupo inválido: '{name}'. Deve ser alfanumérico e ter até 32 caracteres.")

        if name in self._groups:
            raise GroupAlreadyExistsException(f"Grupo '{name}' já existe.")

        if group_id is not None:
            if group_id in self._groups_by_id:
                raise GroupAlreadyExistsException(f"GID {group_id} já está em uso pelo grupo '{self._groups_by_id[group_id].name}'.")
            gid = group_id
            if gid >= self._next_gid:
                self._next_gid = gid + 1
        else:
            while self._next_gid in self._groups_by_id:
                self._next_gid += 1
            gid = self._next_gid
            self._next_gid += 1

        group = Group(group_id=gid, name=name, members=[])
        self._groups[name] = group
        self._groups_by_id[gid] = group
        return group

    def groupdel(self, name: str) -> None:
        """Delete an existing group."""
        name = name.strip()
        if name in ("root", "admin", "users"):
            raise SecurityException(f"Não é permitido remover o grupo essencial de sistema '{name}'.")

        group = self._groups.get(name)
        if group is None:
            raise GroupNotFoundException(f"Grupo '{name}' não encontrado.")

        # Check if group is the primary group of any user
        for user in self._users.values():
            if user.primary_group == name:
                raise SecurityException(
                    f"Não é possível remover o grupo '{name}': é o grupo primário do usuário '{user.username}'."
                )

        # Remove group from supplementary lists of users
        for user in self._users.values():
            if name in user.supplementary_groups:
                user.supplementary_groups.remove(name)

        del self._groups[name]
        del self._groups_by_id[group.group_id]

    def get_group(self, name: str) -> Optional[Group]:
        """Retrieve group by name."""
        return self._groups.get(name)

    def get_group_by_id(self, group_id: int) -> Optional[Group]:
        """Retrieve group by GID."""
        return self._groups_by_id.get(group_id)

    def group_exists(self, name: str) -> bool:
        """Check if group exists."""
        return name in self._groups

    def list_groups(self) -> List[Group]:
        """List all groups sorted by GID."""
        return sorted(self._groups.values(), key=lambda g: g.group_id)

    # =========================================================================
    # User Management
    # =========================================================================

    def useradd(
        self,
        username: str,
        password: Optional[str] = None,
        primary_group: str = "users",
        supplementary_groups: Optional[List[str]] = None,
        user_id: Optional[int] = None,
        salt: Optional[bytes] = None,
        password_hash: Optional[str] = None,
        iterations: Optional[int] = None,
        create_home: bool = True,
    ) -> User:
        """Create a new user."""
        username = username.strip()
        if not self.USERNAME_REGEX.match(username):
            raise SecurityException(
                f"Nome de usuário inválido: '{username}'. Deve ser alfanumérico e ter até 32 caracteres."
            )

        if username in self._users:
            raise UserAlreadyExistsException(f"Usuário '{username}' já existe.")

        # Validate primary group
        if primary_group not in self._groups:
            # Auto-create group if it matches username, else raise
            if primary_group == username:
                self.groupadd(username)
            else:
                raise GroupNotFoundException(f"Grupo primário '{primary_group}' não encontrado.")

        # Validate supplementary groups
        clean_supp: List[str] = []
        if supplementary_groups:
            for g in supplementary_groups:
                g_clean = g.strip()
                if not g_clean or g_clean == primary_group:
                    continue
                if g_clean not in self._groups:
                    raise GroupNotFoundException(f"Grupo suplementar '{g_clean}' não encontrado.")
                if g_clean not in clean_supp:
                    clean_supp.append(g_clean)

        # Allocate UID
        if user_id is not None:
            if user_id in self._users_by_id:
                raise UserAlreadyExistsException(
                    f"UID {user_id} já está em uso pelo usuário '{self._users_by_id[user_id].username}'."
                )
            uid = user_id
            if uid >= self._next_uid:
                self._next_uid = uid + 1
        else:
            while self._next_uid in self._users_by_id:
                self._next_uid += 1
            uid = self._next_uid
            self._next_uid += 1

        # Resolve credentials
        user_iter = iterations if iterations is not None else self._default_iterations
        import hashlib
        if password is not None:
            user_salt = salt or secrets.token_bytes(16)
            user_hash = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                user_salt,
                user_iter,
            ).hex()
        elif password_hash is not None and salt is not None:
            user_salt = salt
            user_hash = password_hash
        else:
            user_salt = secrets.token_bytes(16)
            user_hash = ""

        user = User(
            user_id=uid,
            username=username,
            primary_group=primary_group,
            supplementary_groups=clean_supp,
            salt=user_salt,
            password_hash=user_hash,
            created_at=time.time(),
            iterations=user_iter,
        )

        self._users[username] = user
        self._users_by_id[uid] = user

        # Update group memberships
        self._groups[primary_group].add_member(username)
        for g in clean_supp:
            self._groups[g].add_member(username)

        # Automated home directory creation if filesystem is bound
        if create_home and self._fs_service is not None:
            self._provision_home_dir(username, primary_group)

        return user

    def userdel(self, username: str) -> None:
        """Delete an existing user."""
        username = username.strip()
        if username == "root":
            raise PermissionDeniedException("Não é permitido remover o usuário administrador 'root'.")

        user = self._users.get(username)
        if user is None:
            raise UserNotFoundException(f"Usuário '{username}' não encontrado.")

        # Remove from groups
        for group in self._groups.values():
            group.remove_member(username)

        del self._users[username]
        del self._users_by_id[user.user_id]

    def usermod(
        self,
        username: str,
        primary_group: Optional[str] = None,
        supplementary_groups: Optional[List[str]] = None,
        add_groups: Optional[List[str]] = None,
        remove_groups: Optional[List[str]] = None,
        password: Optional[str] = None,
        iterations: Optional[int] = None,
    ) -> User:
        """Modify an existing user's attributes."""
        username = username.strip()
        user = self._users.get(username)
        if user is None:
            raise UserNotFoundException(f"Usuário '{username}' não encontrado.")

        # Update primary group
        if primary_group is not None:
            primary_group = primary_group.strip()
            if primary_group not in self._groups:
                raise GroupNotFoundException(f"Grupo primário '{primary_group}' não encontrado.")

            old_primary = user.primary_group
            if old_primary != primary_group:
                # Remove from old primary group members if not in supplementary
                if old_primary not in user.supplementary_groups:
                    self._groups[old_primary].remove_member(username)
                user.primary_group = primary_group
                self._groups[primary_group].add_member(username)

        # Replace supplementary groups
        if supplementary_groups is not None:
            clean_supp: List[str] = []
            for g in supplementary_groups:
                g_clean = g.strip()
                if not g_clean or g_clean == user.primary_group:
                    continue
                if g_clean not in self._groups:
                    raise GroupNotFoundException(f"Grupo suplementar '{g_clean}' não encontrado.")
                if g_clean not in clean_supp:
                    clean_supp.append(g_clean)

            # Remove from old groups that are no longer present
            for old_g in list(user.supplementary_groups):
                if old_g not in clean_supp and old_g != user.primary_group:
                    if old_g in self._groups:
                        self._groups[old_g].remove_member(username)

            user.supplementary_groups = clean_supp
            for g in clean_supp:
                self._groups[g].add_member(username)

        # Add specific groups
        if add_groups:
            for g in add_groups:
                g_clean = g.strip()
                if not g_clean:
                    continue
                if g_clean not in self._groups:
                    raise GroupNotFoundException(f"Grupo '{g_clean}' não encontrado.")
                if g_clean != user.primary_group and g_clean not in user.supplementary_groups:
                    user.supplementary_groups.append(g_clean)
                self._groups[g_clean].add_member(username)

        # Remove specific groups
        if remove_groups:
            for g in remove_groups:
                g_clean = g.strip()
                if g_clean in user.supplementary_groups:
                    user.supplementary_groups.remove(g_clean)
                if g_clean != user.primary_group and g_clean in self._groups:
                    self._groups[g_clean].remove_member(username)

        # Update password
        if password is not None:
            import hashlib
            user_iter = iterations or user.iterations or self._default_iterations
            new_salt = secrets.token_bytes(16)
            new_hash = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                new_salt,
                user_iter,
            ).hex()
            user.salt = new_salt
            user.password_hash = new_hash
            user.iterations = user_iter

        return user

    def get_user(self, username: str) -> Optional[User]:
        """Retrieve user by username."""
        return self._users.get(username)

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Retrieve user by UID."""
        return self._users_by_id.get(user_id)

    def user_exists(self, username: str) -> bool:
        """Check if user exists."""
        return username in self._users

    def list_users(self) -> List[User]:
        """List all users sorted by UID."""
        return sorted(self._users.values(), key=lambda u: u.user_id)

    def _provision_home_dir(self, username: str, group: str) -> None:
        """Helper to create /home/<username> in simulated filesystem if available."""
        if not self._fs_service or not hasattr(self._fs_service, "create_directory"):
            return
        home_path = f"/home/{username}"
        try:
            self._fs_service.create_directory(home_path)
            if hasattr(self._fs_service, "change_owner"):
                self._fs_service.change_owner(home_path, username, group)
            if hasattr(self._fs_service, "change_permissions"):
                self._fs_service.change_permissions(home_path, "750")
        except Exception:
            # Home directory provisioning is best-effort and non-fatal
            pass
