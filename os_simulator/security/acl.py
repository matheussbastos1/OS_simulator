"""POSIX Access Control List (ACL) and permission evaluation engine.

Implements the standard POSIX rwx permission model (Owner, Group, Others)
with support for octal (0o755, 755) and symbolic (rwxr-xr-x) representations.
"""

from __future__ import annotations

import re
from enum import IntFlag
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class Permission(IntFlag):
    """POSIX permission bits."""
    NONE = 0
    EXECUTE = 1
    WRITE = 2
    READ = 4
    READ_WRITE = 6
    READ_EXECUTE = 5
    WRITE_EXECUTE = 3
    ALL = 7

    @classmethod
    def from_char(cls, char: str) -> "Permission":
        """Parse single permission character ('r', 'w', 'x', '-')."""
        c = char.lower()
        if c == "r":
            return cls.READ
        if c == "w":
            return cls.WRITE
        if c == "x":
            return cls.EXECUTE
        if c == "-":
            return cls.NONE
        raise ValueError(f"Caractere de permissão inválido: '{char}' (esperado 'r', 'w', 'x' ou '-')")


class PermissionTriple:
    """Represents a set of 3 permission bits (read, write, execute) for a single entity."""

    __slots__ = ("read", "write", "execute")

    def __init__(self, read: bool = False, write: bool = False, execute: bool = False) -> None:
        self.read = bool(read)
        self.write = bool(write)
        self.execute = bool(execute)

    @classmethod
    def from_octal_digit(cls, digit: int) -> "PermissionTriple":
        """Instantiate from a single octal digit (0-7)."""
        if not (0 <= digit <= 7):
            raise ValueError(f"Dígito octal de permissão inválido: {digit} (deve estar entre 0 e 7)")
        return cls(
            read=bool(digit & Permission.READ),
            write=bool(digit & Permission.WRITE),
            execute=bool(digit & Permission.EXECUTE),
        )

    @classmethod
    def from_symbolic(cls, sym: str) -> "PermissionTriple":
        """Instantiate from a 3-character symbolic string like 'rwx', 'r-x', '---'."""
        if len(sym) != 3:
            raise ValueError(f"Fragmento simbólico deve conter exatamente 3 caracteres: '{sym}'")
        r = sym[0].lower()
        w = sym[1].lower()
        x = sym[2].lower()

        if r not in ("r", "-"):
            raise ValueError(f"Bit de leitura inválido: '{r}' (esperado 'r' ou '-')")
        if w not in ("w", "-"):
            raise ValueError(f"Bit de escrita inválido: '{w}' (esperado 'w' ou '-')")
        if x not in ("x", "-"):
            raise ValueError(f"Bit de execução inválido: '{x}' (esperado 'x' ou '-')")

        return cls(read=(r == "r"), write=(w == "w"), execute=(x == "x"))

    def to_octal_digit(self) -> int:
        """Convert to single octal digit (0-7)."""
        val = 0
        if self.read:
            val |= Permission.READ
        if self.write:
            val |= Permission.WRITE
        if self.execute:
            val |= Permission.EXECUTE
        return val

    def to_symbolic(self) -> str:
        """Convert to 3-character symbolic string (e.g. 'rwx', 'r-x', '---')."""
        return (
            ("r" if self.read else "-")
            + ("w" if self.write else "-")
            + ("x" if self.execute else "-")
        )

    def has_permission(self, perm: Union[Permission, str, int]) -> bool:
        """Check if this triple grants the requested permission."""
        if isinstance(perm, str):
            clean = perm.strip().lower()
            if clean in ("r", "read"):
                return self.read
            if clean in ("w", "write"):
                return self.write
            if clean in ("x", "exec", "execute"):
                return self.execute
            # If string of permissions like 'rw' or 'rx'
            req_perm = 0
            for char in clean:
                req_perm |= Permission.from_char(char)
            perm = req_perm

        val = int(perm)
        if (val & Permission.READ) and not self.read:
            return False
        if (val & Permission.WRITE) and not self.write:
            return False
        if (val & Permission.EXECUTE) and not self.execute:
            return False
        return True

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PermissionTriple):
            return (
                self.read == other.read
                and self.write == other.write
                and self.execute == other.execute
            )
        if isinstance(other, int):
            return self.to_octal_digit() == other
        return False

    def __repr__(self) -> str:
        return f"PermissionTriple('{self.to_symbolic()}', octal={self.to_octal_digit()})"


class FilePermissions:
    """Represents full 9-bit POSIX permissions (Owner, Group, Others)."""

    def __init__(
        self,
        owner: Optional[PermissionTriple] = None,
        group: Optional[PermissionTriple] = None,
        others: Optional[PermissionTriple] = None,
    ) -> None:
        self.owner = owner or PermissionTriple()
        self.group = group or PermissionTriple()
        self.others = others or PermissionTriple()

    @classmethod
    def from_octal(cls, mode: Union[int, str]) -> "FilePermissions":
        """Create FilePermissions from an octal integer (e.g. 0o755) or octal string (e.g. '755')."""
        if isinstance(mode, int):
            oct_val = mode & 0o777
            owner_d = (oct_val >> 6) & 0o7
            group_d = (oct_val >> 3) & 0o7
            others_d = oct_val & 0o7
            return cls(
                owner=PermissionTriple.from_octal_digit(owner_d),
                group=PermissionTriple.from_octal_digit(group_d),
                others=PermissionTriple.from_octal_digit(others_d),
            )

        if isinstance(mode, str):
            clean = mode.strip()
            if clean.startswith("0o") or clean.startswith("0O"):
                clean = clean[2:]
            elif len(clean) == 4 and clean.startswith("0"):
                clean = clean[1:]

            if not re.match(r"^[0-7]{3}$", clean):
                raise ValueError(
                    f"Modo octal inválido: '{mode}'. Esperado valor numérico octal com 3 dígitos (ex.: '755', '750', '644')."
                )

            return cls(
                owner=PermissionTriple.from_octal_digit(int(clean[0])),
                group=PermissionTriple.from_octal_digit(int(clean[1])),
                others=PermissionTriple.from_octal_digit(int(clean[2])),
            )

        raise TypeError(f"Tipo não suportado para modo octal: {type(mode).__name__}")

    @classmethod
    def from_symbolic(cls, sym: str) -> "FilePermissions":
        """Create FilePermissions from symbolic string (9 or 10 characters).
        
        Examples: 'rwxr-xr-x', '-rwxr-xr-x', 'drwxr-x---'.
        """
        clean = sym.strip()
        if len(clean) == 10:
            clean = clean[1:]  # Discard file type indicator ('-', 'd', etc.)

        if len(clean) != 9:
            raise ValueError(
                f"Modo simbólico inválido: '{sym}'. Esperado string de 9 caracteres (ex.: 'rwxr-xr-x') ou 10 caracteres (ex.: '-rwxr-xr-x')."
            )

        return cls(
            owner=PermissionTriple.from_symbolic(clean[0:3]),
            group=PermissionTriple.from_symbolic(clean[3:6]),
            others=PermissionTriple.from_symbolic(clean[6:9]),
        )

    @classmethod
    def parse(cls, val: Union[int, str, "FilePermissions"]) -> "FilePermissions":
        """Universal parser accepting int (0o755), octal str ('755'), or symbolic str ('rwxr-xr-x')."""
        if isinstance(val, FilePermissions):
            return cls(
                owner=PermissionTriple.from_octal_digit(val.owner.to_octal_digit()),
                group=PermissionTriple.from_octal_digit(val.group.to_octal_digit()),
                others=PermissionTriple.from_octal_digit(val.others.to_octal_digit()),
            )
        if isinstance(val, int):
            return cls.from_octal(val)
        if isinstance(val, str):
            clean = val.strip()
            if re.match(r"^(0o|0O)?[0-7]{3,4}$", clean):
                return cls.from_octal(clean)
            if len(clean) in (9, 10) and any(c in clean for c in ("r", "w", "x", "-")):
                return cls.from_symbolic(clean)
            raise ValueError(f"Não foi possível interpretar a permissão: '{val}'")
        raise TypeError(f"Tipo não suportado para permissões: {type(val).__name__}")

    def to_octal_int(self) -> int:
        """Return octal integer representation (e.g. 0o755)."""
        return (
            (self.owner.to_octal_digit() << 6)
            | (self.group.to_octal_digit() << 3)
            | self.others.to_octal_digit()
        )

    def to_octal_str(self) -> str:
        """Return standard 3-digit octal string (e.g. '755', '750', '644')."""
        return (
            f"{self.owner.to_octal_digit()}"
            f"{self.group.to_octal_digit()}"
            f"{self.others.to_octal_digit()}"
        )

    def to_short_symbolic(self) -> str:
        """Return standard 9-character symbolic string (e.g. 'rwxr-xr-x')."""
        return (
            self.owner.to_symbolic()
            + self.group.to_symbolic()
            + self.others.to_symbolic()
        )

    def to_symbolic(self, is_directory: bool = False) -> str:
        """Return standard 10-character symbolic string (e.g. '-rwxr-xr-x' or 'drwxr-xr-x')."""
        prefix = "d" if is_directory else "-"
        return prefix + self.to_short_symbolic()

    def apply_chmod(self, spec: Union[str, int]) -> "FilePermissions":
        """Apply a chmod specification (either octal or relative +/-/=) and return a new instance.
        
        Supports:
        - Octal strings or ints: '755', '0750', 0o644
        - Relative specs: 'u+x', 'g-w', 'o=r', 'a+rx', '+x'
        """
        if isinstance(spec, int):
            return FilePermissions.from_octal(spec)

        clean = spec.strip()
        if re.match(r"^(0o|0O)?[0-7]{3,4}$", clean):
            return FilePermissions.from_octal(clean)

        # Relative chmod specification: [ugoa]*[+-=][rwx]* (e.g. 'u+x', 'go-w', 'a+r', '+x')
        match = re.match(r"^([ugoa]*)([+\-=])([rwx]*)$", clean.lower())
        if not match:
            raise ValueError(f"Sintaxe chmod inválida: '{spec}' (exemplos válidos: 755, u+x, g-w, a=rx)")

        targets, op, perms = match.groups()
        if not targets:
            targets = "a"

        target_classes: Set[str] = set()
        if "a" in targets:
            target_classes.update(["u", "g", "o"])
        else:
            if "u" in targets:
                target_classes.add("u")
            if "g" in targets:
                target_classes.add("g")
            if "o" in targets:
                target_classes.add("o")

        req_r = "r" in perms
        req_w = "w" in perms
        req_x = "x" in perms

        def update_triple(triple: PermissionTriple) -> PermissionTriple:
            r = triple.read
            w = triple.write
            x = triple.execute
            if op == "+":
                if req_r:
                    r = True
                if req_w:
                    w = True
                if req_x:
                    x = True
            elif op == "-":
                if req_r:
                    r = False
                if req_w:
                    w = False
                if req_x:
                    x = False
            elif op == "=":
                r = req_r
                w = req_w
                x = req_x
            return PermissionTriple(read=r, write=w, execute=x)

        new_owner = update_triple(self.owner) if "u" in target_classes else PermissionTriple.from_octal_digit(self.owner.to_octal_digit())
        new_group = update_triple(self.group) if "g" in target_classes else PermissionTriple.from_octal_digit(self.group.to_octal_digit())
        new_others = update_triple(self.others) if "o" in target_classes else PermissionTriple.from_octal_digit(self.others.to_octal_digit())

        return FilePermissions(owner=new_owner, group=new_group, others=new_others)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FilePermissions):
            return (
                self.owner == other.owner
                and self.group == other.group
                and self.others == other.others
            )
        if isinstance(other, int):
            return self.to_octal_int() == (other & 0o777)
        if isinstance(other, str):
            try:
                parsed = FilePermissions.parse(other)
                return self == parsed
            except Exception:
                return False
        return False

    def __str__(self) -> str:
        return self.to_short_symbolic()

    def __repr__(self) -> str:
        return f"FilePermissions({self.to_octal_str()}, '{self.to_short_symbolic()}')"


class ACL:
    """Access Control List evaluation engine matching POSIX semantics."""

    def __init__(
        self,
        owner: str = "root",
        group: str = "root",
        mode: Union[FilePermissions, int, str] = "755",
    ) -> None:
        self.owner = owner
        self.group = group
        self.mode = FilePermissions.parse(mode)

    def check_access(
        self,
        user: str,
        user_groups: List[str],
        required_perm: Union[Permission, str, int],
        is_kernel_or_root: bool = False,
        is_directory: bool = False,
    ) -> bool:
        """Evaluate access according to standard POSIX permission resolution rules.
        
        Rules:
        1. If user is root or execution is in KERNEL_MODE -> access granted unconditionally.
        2. Else if user == file.owner -> evaluate ONLY owner permissions.
        3. Else if file.group in user's groups -> evaluate ONLY group permissions.
        4. Else -> evaluate others permissions.
        """
        # Rule 1: Root / Kernel Mode bypass
        if is_kernel_or_root or user == "root":
            return True

        # Rule 2: User matches owner
        if user == self.owner:
            return self.mode.owner.has_permission(required_perm)

        # Rule 3: User belongs to resource group
        if self.group in user_groups:
            return self.mode.group.has_permission(required_perm)

        # Rule 4: Others
        return self.mode.others.has_permission(required_perm)

    @classmethod
    def evaluate(
        cls,
        owner: str,
        group: str,
        permissions: Union[FilePermissions, int, str],
        user: str,
        user_groups: List[str],
        required_perm: Union[Permission, str, int],
        is_kernel_or_root: bool = False,
        is_directory: bool = False,
    ) -> bool:
        """Static helper to evaluate permissions without persisting an ACL instance."""
        acl = cls(owner=owner, group=group, mode=permissions)
        return acl.check_access(
            user=user,
            user_groups=user_groups,
            required_perm=required_perm,
            is_kernel_or_root=is_kernel_or_root,
            is_directory=is_directory,
        )

    def __repr__(self) -> str:
        return f"<ACL owner={self.owner} group={self.group} mode={self.mode.to_octal_str()} ({self.mode.to_short_symbolic()})>"
