"""校验用户登记的本机绝对目录，不扫描、创建或修改项目文件。"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal

from mini_deer_agent.domain.workspaces import ProjectError


_SENSITIVE_PARTS = frozenset(
    {
        ".git",
        ".ssh",
        ".aws",
        ".azure",
        ".gnupg",
        ".kube",
        ".codex",
        ".env",
        ".venv",
        "node_modules",
    }
)


def _is_reserved(part: str) -> bool:
    """优先使用当前 Windows 设备名检查，并保留 Python 3.12 兼容。"""
    check = getattr(os.path, "isreserved", None)
    return check(part) if check is not None else PureWindowsPath(part).is_reserved()


@dataclass(frozen=True, slots=True)
class ProjectRoot:
    """返回规范路径与登记身份，供持久化和后续状态复核使用。"""

    path: Path
    identity: str


@dataclass(frozen=True, slots=True)
class FileAccessTarget:
    """返回明确文件或目录的规范身份，供一次访问 Scope 冻结。"""

    path: Path
    identity: str
    kind: Literal["directory", "file"]


def _parse_absolute(value: str) -> Path:
    """先做纯字符串检查，避免 UNC、设备名或相对路径触发意外文件访问。"""
    normalized = value.replace("\\", "/")
    if (
        not value
        or len(value) > 4096
        or any(ord(char) < 32 for char in value)
        or normalized.startswith("//")
        or ".." in normalized.split("/")
    ):
        raise ProjectError("project_root_invalid", "请输入本机已有项目的绝对目录。")
    path = Path(value)
    # 允许登记入口的正常盘符，但不允许 ADS、盘符相对路径和设备别名。
    parts = path.parts[1:]
    if (
        not path.is_absolute()
        or len(path.parts) > 128
        or any(":" in part for part in parts)
        or (
            os.name == "nt"
            and any(part.endswith((" ", ".")) or _is_reserved(part) for part in parts)
        )
    ):
        raise ProjectError("project_root_invalid", "项目路径不是明确的本机绝对目录。")
    return path


def _inspect_directory(path: Path) -> ProjectRoot:
    """逐层 lstat，首版对符号链接和所有 Windows reparse point 失败关闭。"""
    try:
        metadata = None
        for component in (*reversed(path.parents), path):
            metadata = component.lstat()
            if stat.S_ISLNK(metadata.st_mode) or (
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                raise ProjectError(
                    "project_root_link", "项目路径不能包含链接或重解析目录。"
                )
            if not stat.S_ISDIR(metadata.st_mode):
                raise ProjectError("project_root_not_directory", "项目路径必须是目录。")
        # 只打开目录验证枚举权限，不遍历目录内容，更不读取任何文件正文。
        with os.scandir(path):
            pass
        resolved = path.resolve(strict=True)
        final = resolved.lstat()
        if metadata is None or (metadata.st_dev, metadata.st_ino) != (
            final.st_dev,
            final.st_ino,
        ):
            raise ProjectError(
                "project_root_changed", "目录在校验期间发生变化，请重试。"
            )
        # 身份记录用于发现目录被替换，不等于消除了外部文件系统竞争。
        return ProjectRoot(resolved, f"{final.st_dev}:{final.st_ino}")
    except FileNotFoundError:
        raise ProjectError("project_root_missing", "项目目录不存在。") from None
    except (OSError, RuntimeError):
        raise ProjectError(
            "project_root_unavailable", "项目目录当前无法访问。"
        ) from None


def _inspect_regular_file(path: Path) -> FileAccessTarget:
    """检查明确文件及父目录，不跟随链接或接受特殊文件。"""
    try:
        parent = _inspect_directory(path.parent)
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or (
            getattr(before, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise ProjectError(
                "file_access_target_link", "文件访问目标不能是链接或重解析点。"
            )
        if not stat.S_ISREG(before.st_mode):
            raise ProjectError(
                "file_access_target_unsupported", "文件访问目标必须是普通文件或目录。"
            )
        resolved = path.resolve(strict=True)
        after = resolved.lstat()
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or resolved.parent != parent.path
        ):
            raise ProjectError(
                "file_access_target_changed", "文件访问目标在校验期间发生变化。"
            )
        return FileAccessTarget(
            resolved, f"{after.st_dev}:{after.st_ino}", "file"
        )
    except FileNotFoundError:
        raise ProjectError(
            "file_access_target_missing", "文件访问目标不存在。"
        ) from None
    except ProjectError:
        raise
    except (OSError, RuntimeError):
        raise ProjectError(
            "file_access_target_unavailable", "文件访问目标当前无法访问。"
        ) from None


class ProjectRootPolicy:
    """用显式允许根限制管理入口；模型和 HTTP 参数不能扩充这份允许列表。"""

    def __init__(
        self, *, allowed_roots: tuple[Path, ...], blocked_roots: tuple[Path, ...] = ()
    ) -> None:
        """冻结运维配置和允许根身份；不自动信任工作目录或整个磁盘。"""
        if not allowed_roots or len(allowed_roots) > 32:
            raise ProjectError(
                "project_roots_not_configured", "请配置 1—32 个允许目录。"
            )
        self._blocked_roots = tuple(path.resolve() for path in blocked_roots)
        self._allowed_roots: tuple[ProjectRoot, ...] = tuple(
            self._inspect_allowed_root(str(path)) for path in allowed_roots
        )

    def _check_sensitive(self, path: Path) -> None:
        """拒绝磁盘根、用户主目录及其上级、应用数据和常见凭据目录。"""
        home = Path.home().resolve()
        system_roots = tuple(
            Path(value)
            for name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)")
            if (value := os.environ.get(name))
        )
        if (
            path == Path(path.anchor)
            or path == home
            or path in home.parents
            or any(part.casefold() in _SENSITIVE_PARTS for part in path.parts)
            or any(
                path.is_relative_to(root)
                for root in (*self._blocked_roots, *system_roots)
            )
        ):
            raise ProjectError(
                "project_root_not_allowed", "该路径不能作为文件访问范围。"
            )

    def _inspect_allowed_root(self, value: str) -> ProjectRoot:
        """保留暂不可用的配置根，重启后仍能查询失效登记；实际访问继续失败关闭。"""
        path = _parse_absolute(value)
        self._check_sensitive(path)
        try:
            root = _inspect_directory(path)
        except ProjectError:
            # 目录丢失、拒绝访问或变成链接不能拖垮普通聊天。空身份只表示启动时
            # 未能核验；inspect 仍逐层检查，已有 Project 仍比对其持久化原身份。
            return ProjectRoot(path, "")
        self._check_sensitive(root.path)
        return root

    def inspect(self, value: str) -> ProjectRoot:
        """复核允许范围、路径和身份；只读登记后，未来每次文件访问仍须重新校验。"""
        path = _parse_absolute(value)
        self._check_sensitive(path)
        allowed = next(
            (root for root in self._allowed_roots if path.is_relative_to(root.path)),
            None,
        )
        if allowed is None:
            raise ProjectError(
                "project_root_not_allowed", "项目目录不在配置的允许范围内。"
            )
        current_allowed = _inspect_directory(allowed.path)
        if allowed.identity and current_allowed.identity != allowed.identity:
            raise ProjectError(
                "project_root_changed", "允许目录已被替换，请重新检查配置。"
            )
        root = _inspect_directory(path)
        if not root.path.is_relative_to(allowed.path):
            raise ProjectError(
                "project_root_not_allowed", "解析后的项目目录超出允许范围。"
            )
        self._check_sensitive(root.path)
        return root

    def inspect_target(self, value: str) -> FileAccessTarget:
        """授权一个明确文件或目录；文件目标不会隐式授权其父目录。"""
        path = _parse_absolute(value)
        self._check_sensitive(path)
        allowed = next(
            (root for root in self._allowed_roots if path.is_relative_to(root.path)),
            None,
        )
        if allowed is None:
            raise ProjectError(
                "project_root_not_allowed", "文件访问目标不在配置的允许范围内。"
            )
        current_allowed = _inspect_directory(allowed.path)
        if allowed.identity and current_allowed.identity != allowed.identity:
            raise ProjectError(
                "project_root_changed", "允许目录已被替换，请重新检查配置。"
            )
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            raise ProjectError(
                "file_access_target_missing", "文件访问目标不存在。"
            ) from None
        except OSError:
            raise ProjectError(
                "file_access_target_unavailable", "文件访问目标当前无法访问。"
            ) from None
        if stat.S_ISDIR(metadata.st_mode):
            root = self.inspect(value)
            return FileAccessTarget(root.path, root.identity, "directory")
        target = _inspect_regular_file(path)
        if not target.path.is_relative_to(allowed.path):
            raise ProjectError(
                "project_root_not_allowed", "解析后的文件访问目标超出允许范围。"
            )
        self._check_sensitive(target.path)
        return target

    def inspect_explicit_target(self, value: str) -> FileAccessTarget:
        """检查用户明确写出的任意本机文件或目录，不套用项目允许根。"""
        path = _parse_absolute(value)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            raise ProjectError(
                "file_access_target_missing", "文件访问目标不存在。"
            ) from None
        except OSError:
            raise ProjectError(
                "file_access_target_unavailable", "文件访问目标当前无法访问。"
            ) from None
        if stat.S_ISDIR(metadata.st_mode):
            root = _inspect_directory(path)
            return FileAccessTarget(root.path, root.identity, "directory")
        return _inspect_regular_file(path)

    def inspect_allowed_roots(self) -> tuple[ProjectRoot, ...]:
        """复核并返回全部配置根，供普通 Thread 建立常驻只读范围。"""
        return tuple(self.inspect(str(root.path)) for root in self._allowed_roots)
