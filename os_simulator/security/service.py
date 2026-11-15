"""Security Manager service implementing AuthorizationPort with POSIX ACLs and Audit Log."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from os_simulator.core.context import ExecutionContext
from os_simulator.core.exceptions import (
    FileNotFoundException,
    PermissionDeniedException,
)
from os_simulator.core.ports import AuthorizationPort
from os_simulator.core.types import AuditEventType, NodeType, PrivilegeMode
from os_simulator.filesystem.inode import Inode
from os_simulator.security.acl import ACL, FilePermissions, Permission
from os_simulator.security.audit import AuditEvent, AuditLog


class SecurityManager(AuthorizationPort):
    """Central access control, permission evaluation, and security auditing manager."""

    def __init__(
        self,
        user_manager: Optional[Any] = None,
        auth_service: Optional[Any] = None,
        audit_log: Optional[AuditLog] = None,
        fs_service: Optional[Any] = None,
    ) -> None:
        self.user_manager = user_manager
        self.auth_service = auth_service
        self.audit_log = audit_log or AuditLog()
        self.fs_service = fs_service

    def set_filesystem(self, fs_service: Any) -> None:
        """Bind or update filesystem service reference for path and inode resolution."""
        self.fs_service = fs_service

    def is_admin(self, context: ExecutionContext) -> bool:
        """Verify whether the active execution context holds administrative / kernel privileges."""
        return context.is_admin() or context.is_root()

    def _resolve_inode(self, path: str, cwd: str = "/") -> Optional[Inode]:
        """Resolve Inode for given canonical or relative path using registered fs_service."""
        if self.fs_service is None or not hasattr(self.fs_service, "vfs"):
            return None

        node = self.fs_service.vfs.get_node(path, cwd=cwd)
        if node is not None and hasattr(self.fs_service, "inode_table"):
            return self.fs_service.inode_table.get(node.inode_id)
        return None

    def _get_parent_dir_inode(self, path: str, cwd: str = "/") -> Optional[Inode]:
        """Resolve Inode of parent directory for file creation checks."""
        if self.fs_service is None or not hasattr(self.fs_service, "vfs"):
            return None

        canonical = self.fs_service.vfs.normalize_path(path, cwd=cwd)
        if canonical == "/":
            return None

        parent_path = "/" + "/".join([part for part in canonical.strip("/").split("/")[:-1]])
        if parent_path == "":
            parent_path = "/"

        parent_node = self.fs_service.vfs.get_node(parent_path)
        if parent_node is not None and hasattr(self.fs_service, "inode_table"):
            return self.fs_service.inode_table.get(parent_node.inode_id)
        return None

    def check_traverse(
        self,
        context: ExecutionContext,
        path: str,
        raise_on_denied: bool = False,
    ) -> bool:
        """Verify directory traversal permission ('x') along all parent directory components."""
        if self.is_admin(context):
            return True

        if self.fs_service is None or not hasattr(self.fs_service, "vfs"):
            return True

        canonical = self.fs_service.vfs.normalize_path(path, cwd=context.cwd)
        parts = [p for p in canonical.strip("/").split("/") if p]

        # 1. Check root directory '/'
        root_node = self.fs_service.vfs.root
        if root_node and hasattr(self.fs_service, "inode_table"):
            root_inode = self.fs_service.inode_table.get(root_node.inode_id)
            if root_inode is not None:
                has_x = ACL(root_inode.owner, root_inode.group, root_inode.permissions).check_access(
                    user=context.username,
                    user_groups=context.groups,
                    required_perm=Permission.EXECUTE,
                    is_kernel_or_root=False,
                    is_directory=True,
                )
                if not has_x:
                    self._log_and_maybe_raise_denial(
                        context=context,
                        path="/",
                        inode=root_inode,
                        action="TRAVERSE",
                        reason=f"Usuário '{context.username}' não possui permissão de execução ('x') para atravessar o diretório raiz '/'",
                        raise_on_denied=raise_on_denied,
                    )
                    return False

        # 2. Check each directory along the path excluding target file (if target is file)
        for i in range(len(parts) - 1):
            current_path = "/" + "/".join(parts[: i + 1])
            dir_node = self.fs_service.vfs.get_node(current_path)
            if dir_node is not None and hasattr(self.fs_service, "inode_table"):
                dir_inode = self.fs_service.inode_table.get(dir_node.inode_id)
                if dir_inode is not None:
                    has_x = ACL(dir_inode.owner, dir_inode.group, dir_inode.permissions).check_access(
                        user=context.username,
                        user_groups=context.groups,
                        required_perm=Permission.EXECUTE,
                        is_kernel_or_root=False,
                        is_directory=True,
                    )
                    if not has_x:
                        self._log_and_maybe_raise_denial(
                            context=context,
                            path=current_path,
                            inode=dir_inode,
                            action="TRAVERSE",
                            reason=f"Usuário '{context.username}' não possui permissão de execução ('x') para atravessar o diretório '{current_path}'",
                            raise_on_denied=raise_on_denied,
                        )
                        return False

        return True

    def check_traversal(
        self,
        context: ExecutionContext,
        path: str,
        raise_on_denied: bool = False,
    ) -> bool:
        """Alias for check_traverse for backwards compatibility."""
        return self.check_traverse(context, path, raise_on_denied=raise_on_denied)

    def check_read(
        self,
        context: ExecutionContext,
        path: str,
        inode: Optional[Any] = None,
        raise_on_denied: bool = False,
    ) -> bool:
        """Verify read permission for resource.
        
        Evaluates POSIX ACL rules and records access denial in AuditLog.
        """
        # Directory traversal check on ancestor path
        if not self.check_traverse(context, path, raise_on_denied=raise_on_denied):
            return False

        target_inode: Optional[Inode] = inode or self._resolve_inode(path, cwd=context.cwd)

        # If admin / root, full access is granted
        if self.is_admin(context):
            self.audit_log.log_access_granted(username=context.username, path=path, action="READ")
            return True

        if target_inode is None:
            # Resource does not exist or cannot be resolved
            return True

        granted = ACL(
            owner=target_inode.owner,
            group=target_inode.group,
            mode=target_inode.permissions,
        ).check_access(
            user=context.username,
            user_groups=context.groups,
            required_perm=Permission.READ,
            is_kernel_or_root=False,
            is_directory=(target_inode.node_type == NodeType.DIRECTORY),
        )

        if granted:
            self.audit_log.log_access_granted(username=context.username, path=path, action="READ")
            return True

        self._log_and_maybe_raise_denial(
            context=context,
            path=path,
            inode=target_inode,
            action="READ",
            reason=f"Usuário '{context.username}' não possui permissão de leitura em '{path}'",
            raise_on_denied=raise_on_denied,
        )
        return False

    def check_write(
        self,
        context: ExecutionContext,
        path: str,
        inode: Optional[Any] = None,
        raise_on_denied: bool = False,
    ) -> bool:
        """Verify write permission for resource or parent directory for new creations."""
        if not self.check_traverse(context, path, raise_on_denied=raise_on_denied):
            return False

        target_inode: Optional[Inode] = inode or self._resolve_inode(path, cwd=context.cwd)

        if self.is_admin(context):
            self.audit_log.log_access_granted(username=context.username, path=path, action="WRITE")
            return True

        # If file doesn't exist yet, check write permission on parent directory
        if target_inode is None:
            parent_dir_inode = self._get_parent_dir_inode(path, cwd=context.cwd)
            if parent_dir_inode is not None:
                parent_granted = ACL(
                    owner=parent_dir_inode.owner,
                    group=parent_dir_inode.group,
                    mode=parent_dir_inode.permissions,
                ).check_access(
                    user=context.username,
                    user_groups=context.groups,
                    required_perm=Permission.WRITE,
                    is_kernel_or_root=False,
                    is_directory=True,
                )
                if parent_granted:
                    self.audit_log.log_access_granted(
                        username=context.username, path=path, action="CREATE_FILE"
                    )
                    return True
                self._log_and_maybe_raise_denial(
                    context=context,
                    path=path,
                    inode=parent_dir_inode,
                    action="CREATE_FILE",
                    reason=f"Usuário '{context.username}' não possui permissão de escrita no diretório pai de '{path}'",
                    raise_on_denied=raise_on_denied,
                )
                return False
            return True

        granted = ACL(
            owner=target_inode.owner,
            group=target_inode.group,
            mode=target_inode.permissions,
        ).check_access(
            user=context.username,
            user_groups=context.groups,
            required_perm=Permission.WRITE,
            is_kernel_or_root=False,
            is_directory=(target_inode.node_type == NodeType.DIRECTORY),
        )

        if granted:
            self.audit_log.log_access_granted(username=context.username, path=path, action="WRITE")
            return True

        self._log_and_maybe_raise_denial(
            context=context,
            path=path,
            inode=target_inode,
            action="WRITE",
            reason=f"Usuário '{context.username}' não possui permissão de escrita em '{path}'",
            raise_on_denied=raise_on_denied,
        )
        return False

    def check_execute(
        self,
        context: ExecutionContext,
        path: str,
        inode: Optional[Any] = None,
        raise_on_denied: bool = False,
    ) -> bool:
        """Verify execute / directory search permission for resource."""
        if not self.check_traverse(context, path, raise_on_denied=raise_on_denied):
            return False

        target_inode: Optional[Inode] = inode or self._resolve_inode(path, cwd=context.cwd)

        if self.is_admin(context):
            self.audit_log.log_access_granted(username=context.username, path=path, action="EXECUTE")
            return True

        if target_inode is None:
            return True

        granted = ACL(
            owner=target_inode.owner,
            group=target_inode.group,
            mode=target_inode.permissions,
        ).check_access(
            user=context.username,
            user_groups=context.groups,
            required_perm=Permission.EXECUTE,
            is_kernel_or_root=False,
            is_directory=(target_inode.node_type == NodeType.DIRECTORY),
        )

        if granted:
            self.audit_log.log_access_granted(username=context.username, path=path, action="EXECUTE")
            return True

        self._log_and_maybe_raise_denial(
            context=context,
            path=path,
            inode=target_inode,
            action="EXECUTE",
            reason=f"Usuário '{context.username}' não possui permissão de execução em '{path}'",
            raise_on_denied=raise_on_denied,
        )
        return False

    def enforce_read(self, context: ExecutionContext, path: str, inode: Optional[Any] = None) -> None:
        """Enforce read permission, raising PermissionDeniedException if denied."""
        self.check_read(context, path, inode=inode, raise_on_denied=True)

    def enforce_write(self, context: ExecutionContext, path: str, inode: Optional[Any] = None) -> None:
        """Enforce write permission, raising PermissionDeniedException if denied."""
        self.check_write(context, path, inode=inode, raise_on_denied=True)

    def enforce_execute(self, context: ExecutionContext, path: str, inode: Optional[Any] = None) -> None:
        """Enforce execute permission, raising PermissionDeniedException if denied."""
        self.check_execute(context, path, inode=inode, raise_on_denied=True)

    def enforce_traverse(self, context: ExecutionContext, path: str) -> None:
        """Enforce directory traversal permission, raising PermissionDeniedException if denied."""
        self.check_traverse(context, path, raise_on_denied=True)

    def authorize_read(self, context: ExecutionContext, path: str, inode: Optional[Any] = None) -> None:
        """Alias for enforce_read."""
        self.enforce_read(context, path, inode=inode)

    def authorize_write(self, context: ExecutionContext, path: str, inode: Optional[Any] = None) -> None:
        """Alias for enforce_write."""
        self.enforce_write(context, path, inode=inode)

    def authorize_execute(self, context: ExecutionContext, path: str, inode: Optional[Any] = None) -> None:
        """Alias for enforce_execute."""
        self.enforce_execute(context, path, inode=inode)

    def chmod(
        self,
        context: ExecutionContext,
        path: str,
        mode: Union[int, str],
        inode: Optional[Any] = None,
    ) -> str:
        """Change permissions of resource.
        
        Requires active user to be owner of resource or superuser (root).
        Returns formatted octal string of new permissions.
        """
        target_inode: Optional[Inode] = inode or self._resolve_inode(path, cwd=context.cwd)
        if target_inode is None:
            raise FileNotFoundException(f"Arquivo ou diretório não encontrado: '{path}'")

        if not (self.is_admin(context) or context.username == target_inode.owner):
            self.audit_log.log_access_denied(
                username=context.username,
                path=path,
                action="CHMOD",
                details={
                    "path": path,
                    "owner": target_inode.owner,
                    "group": target_inode.group,
                    "permissions": str(target_inode.permissions),
                    "target_mode": str(mode),
                    "user": context.username,
                    "user_groups": list(context.groups),
                    "reason": f"Apenas o proprietário ('{target_inode.owner}') ou o root podem alterar permissões",
                },
            )
            raise PermissionDeniedException(
                f"Operação não permitida: apenas o proprietário ('{target_inode.owner}') ou o superusuário podem alterar as permissões de '{path}'."
            )

        current_perms = FilePermissions.parse(target_inode.permissions)
        new_perms = current_perms.apply_chmod(mode)
        old_mode_str = target_inode.permissions
        new_mode_str = new_perms.to_octal_str()

        target_inode.permissions = new_mode_str
        self.audit_log.log_permission_changed(
            username=context.username,
            path=path,
            details={
                "old_permissions": old_mode_str,
                "new_permissions": new_mode_str,
                "symbolic": new_perms.to_short_symbolic(),
            },
        )
        return new_mode_str

    def chown(
        self,
        context: ExecutionContext,
        path: str,
        owner: Optional[str] = None,
        group: Optional[str] = None,
        inode: Optional[Any] = None,
    ) -> Tuple[str, str]:
        """Change ownership and/or group of resource.
        
        Owner change requires root/admin. Group change requires root or owner who belongs to the target group.
        Returns tuple of (new_owner, new_group).
        """
        target_inode: Optional[Inode] = inode or self._resolve_inode(path, cwd=context.cwd)
        if target_inode is None:
            raise FileNotFoundException(f"Arquivo ou diretório não encontrado: '{path}'")

        is_admin_user = self.is_admin(context)

        # Enforce owner change privilege (root only)
        if owner is not None and owner != target_inode.owner:
            if not is_admin_user:
                self.audit_log.log_access_denied(
                    username=context.username,
                    path=path,
                    action="CHOWN",
                    details={
                        "path": path,
                        "owner": target_inode.owner,
                        "target_owner": owner,
                        "user": context.username,
                        "reason": "Apenas o superusuário pode alterar o proprietário de um recurso",
                    },
                )
                raise PermissionDeniedException(
                    f"Operação não permitida: apenas o superusuário pode alterar o proprietário de '{path}'."
                )

        # Enforce group change privilege
        if group is not None and group != target_inode.group:
            if not is_admin_user:
                if context.username != target_inode.owner or group not in context.groups:
                    self.audit_log.log_access_denied(
                        username=context.username,
                        path=path,
                        action="CHGRP",
                        details={
                            "path": path,
                            "group": target_inode.group,
                            "target_group": group,
                            "user": context.username,
                            "reason": "Permissão negada para alterar o grupo do arquivo",
                        },
                    )
                    raise PermissionDeniedException(
                        f"Operação não permitida: usuário '{context.username}' não possui privilégios para associar ao grupo '{group}'."
                    )

        old_owner = target_inode.owner
        old_group = target_inode.group

        if owner is not None:
            target_inode.owner = owner
        if group is not None:
            target_inode.group = group

        self.audit_log.log_ownership_changed(
            username=context.username,
            path=path,
            details={
                "old_owner": old_owner,
                "new_owner": target_inode.owner,
                "old_group": old_group,
                "new_group": target_inode.group,
            },
        )
        return target_inode.owner, target_inode.group

    def _log_and_maybe_raise_denial(
        self,
        context: ExecutionContext,
        path: str,
        inode: Inode,
        action: str,
        reason: str,
        raise_on_denied: bool,
    ) -> None:
        """Centralized helper to log denial event matching Scenario SEC-002 and optionally raise."""
        details = {
            "path": path,
            "owner": inode.owner,
            "group": inode.group,
            "permissions": str(inode.permissions),
            "user": context.username,
            "user_groups": list(context.groups),
            "requested_action": action,
            "reason": reason,
        }
        self.audit_log.log_access_denied(
            username=context.username,
            path=path,
            action=action,
            details=details,
        )
        if raise_on_denied:
            if action == "TRAVERSE":
                raise PermissionDeniedException(
                    f"Permissão negada: {reason} (proprietário: {inode.owner}, grupo: {inode.group}, modo: {inode.permissions})"
                )
            user_grp = context.groups[0] if context.groups else "none"
            try:
                sym_perms = FilePermissions.parse(str(inode.permissions)).to_symbolic()[1:]
            except Exception:
                sym_perms = "---"
            act_label = "LEITURA" if action == "READ" else ("ESCRITA" if action in ("WRITE", "CREATE_FILE") else action)
            action_desc = "leitura" if action == "READ" else ("escrita" if action in ("WRITE", "CREATE_FILE") else action.lower())
            msg = (
                f"\n[SISTEMA DE SEGURANÇA - VERIFICAÇÃO DE ACL]\n"
                f"Objeto      : {path}\n"
                f"Proprietário: {inode.owner} (Grupo: {inode.group})\n"
                f"Permissões  : {sym_perms} ({inode.permissions})\n"
                f"Ação Pedida : {act_label} por '{context.username}' (Grupo: {user_grp})\n\n"
                f"[NEGADO]: O usuário '{context.username}' não possui permissão de {action_desc} no objeto '{path}'.\n"
                f"Tentativa não autorizada registrada nos logs do sistema."
            )
            raise PermissionDeniedException(msg)
