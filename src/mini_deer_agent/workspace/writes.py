"""在已解析的文件范围内创建新的 UTF-8 文本文件。"""

import hashlib
import stat
from pathlib import Path

from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.workspace.directory import ignored, valid_name
from mini_deer_agent.workspace.paths import _inspect_directory


MAX_CREATE_FILE_BYTES = 80 * 1024
MAX_EDIT_FILE_BYTES = 2 * 1024 * 1024
MAX_WRITE_FILE_BYTES = 80 * 1024
MAX_DIFF_PREVIEW_CHARACTERS = 4000


def create_text_file(root: Path, path: str, content: str) -> dict:
    """创建一个新文件；父目录必须存在，已有文件不会被覆盖。"""
    parts = path.split("/") if path else []
    encoded = content.encode("utf-8")
    if (
        not parts
        or len(path) > 2048
        or len(parts) > 64
        or len(encoded) > MAX_CREATE_FILE_BYTES
        or any(not valid_name(part) or ignored(part) for part in parts)
    ):
        raise ProjectError("file_create_invalid", "新文件路径或正文无效。")

    parent = root.joinpath(*parts[:-1])
    parent_before = _inspect_directory(parent)
    if not parent_before.path.is_relative_to(root):
        raise ProjectError("file_create_invalid", "新文件路径超出当前范围。")
    target = parent / parts[-1]
    try:
        with target.open("xb") as stream:
            stream.write(encoded)
        metadata = target.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ProjectError("file_create_failed", "创建结果不是普通文件。")
        if _inspect_directory(parent).identity != parent_before.identity:
            raise ProjectError("file_create_failed", "父目录在创建期间发生变化。")
    except FileExistsError:
        raise ProjectError("file_already_exists", "目标文件已经存在。") from None
    except ProjectError:
        raise
    except OSError:
        raise ProjectError("file_create_failed", "文件创建失败。") from None

    return {
        "path": path,
        "created": True,
        "size_bytes": len(encoded),
        "revision": hashlib.sha256(encoded).hexdigest(),
    }


def replace_text(root: Path, path: str, old_str: str, new_str: str) -> dict:
    """精确替换唯一一处文本；零处或多处匹配时不修改文件。"""
    parts = path.split("/") if path else []
    if (
        not parts
        or len(path) > 2048
        or len(parts) > 64
        or not old_str
        or old_str == new_str
        or len(old_str.encode("utf-8")) > MAX_EDIT_FILE_BYTES
        or len(new_str.encode("utf-8")) > MAX_EDIT_FILE_BYTES
        or any(not valid_name(part) or ignored(part) for part in parts)
    ):
        raise ProjectError("file_replace_invalid", "文件路径或替换文本无效。")

    target = root.joinpath(*parts)
    parent = _inspect_directory(target.parent)
    if not parent.path.is_relative_to(root):
        raise ProjectError("file_replace_invalid", "文件路径超出当前范围。")
    try:
        metadata = target.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & 0x400
        ):
            raise ProjectError(
                "file_replace_unsupported", "仅支持编辑普通 UTF-8 文本文件。"
            )
        if metadata.st_size > MAX_EDIT_FILE_BYTES:
            raise ProjectError("file_replace_too_large", "文件过大，无法精确编辑。")
        data = target.read_bytes()
    except ProjectError:
        raise
    except OSError:
        raise ProjectError(
            "file_replace_unavailable", "文件不存在或当前无法编辑。"
        ) from None

    if len(data) > MAX_EDIT_FILE_BYTES or b"\x00" in data:
        raise ProjectError(
            "file_replace_unsupported", "仅支持编辑普通 UTF-8 文本文件。"
        )
    has_bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ProjectError(
            "file_replace_unsupported", "仅支持编辑普通 UTF-8 文本文件。"
        ) from None

    occurrences = text.count(old_str)
    if occurrences == 0:
        raise ProjectError("file_replace_not_found", "未找到要替换的精确文本。")
    if occurrences > 1:
        raise ProjectError(
            "file_replace_ambiguous", "要替换的文本出现多次，请提供更精确的内容。"
        )

    replaced = text.replace(old_str, new_str, 1)
    encoded = replaced.encode("utf-8")
    if has_bom:
        encoded = b"\xef\xbb\xbf" + encoded
    if len(encoded) > MAX_EDIT_FILE_BYTES:
        raise ProjectError("file_replace_too_large", "替换后的文件过大。")
    try:
        target.write_bytes(encoded)
    except OSError:
        raise ProjectError("file_replace_failed", "文件编辑失败。") from None

    return {
        "path": path,
        "replaced": True,
        "occurrences": 1,
        "size_bytes": len(encoded),
        "previous_revision": hashlib.sha256(data).hexdigest(),
        "revision": hashlib.sha256(encoded).hexdigest(),
    }


def overwrite_text_file(root: Path, path: str, content: str) -> dict:
    """使用完整 UTF-8 文本覆盖已有普通文本文件，不创建新目标。"""
    parts = path.split("/") if path else []
    encoded_content = content.encode("utf-8")
    if (
        not parts
        or len(path) > 2048
        or len(parts) > 64
        or len(encoded_content) > MAX_WRITE_FILE_BYTES
        or any(not valid_name(part) or ignored(part) for part in parts)
    ):
        raise ProjectError("file_write_invalid", "文件路径或正文无效。")

    target = root.joinpath(*parts)
    parent = _inspect_directory(target.parent)
    if not parent.path.is_relative_to(root):
        raise ProjectError("file_write_invalid", "文件路径超出当前范围。")
    try:
        metadata = target.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & 0x400
        ):
            raise ProjectError(
                "file_write_unsupported", "仅支持覆盖普通 UTF-8 文本文件。"
            )
        if metadata.st_size > MAX_EDIT_FILE_BYTES:
            raise ProjectError("file_write_too_large", "原文件过大，无法完整更新。")
        previous = target.read_bytes()
    except FileNotFoundError:
        raise ProjectError(
            "file_write_missing", "目标文件不存在，请使用 create_file 创建。"
        ) from None
    except ProjectError:
        raise
    except OSError:
        raise ProjectError(
            "file_write_unavailable", "文件当前无法完整更新。"
        ) from None

    if len(previous) > MAX_EDIT_FILE_BYTES or b"\x00" in previous:
        raise ProjectError(
            "file_write_unsupported", "仅支持覆盖普通 UTF-8 文本文件。"
        )
    try:
        previous_content = previous.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ProjectError(
            "file_write_unsupported", "仅支持覆盖普通 UTF-8 文本文件。"
        ) from None

    encoded = encoded_content
    if previous.startswith(b"\xef\xbb\xbf") and not content.startswith("\ufeff"):
        encoded = b"\xef\xbb\xbf" + encoded
    try:
        target.write_bytes(encoded)
    except OSError:
        raise ProjectError("file_write_failed", "文件完整更新失败。") from None

    return {
        "path": path,
        "written": True,
        "created": False,
        "changed": encoded != previous,
        "size_bytes": len(encoded),
        "previous_revision": hashlib.sha256(previous).hexdigest(),
        "revision": hashlib.sha256(encoded).hexdigest(),
        "previous_content_preview": previous_content[:MAX_DIFF_PREVIEW_CHARACTERS],
        "previous_content_truncated": (
            len(previous_content) > MAX_DIFF_PREVIEW_CHARACTERS
        ),
    }


def create_directory(root: Path, path: str) -> dict:
    """创建单层目录；父目录必须存在，已有目录返回 created=False。"""
    parts = path.split("/") if path else []
    if (not parts or len(path) > 2048 or len(parts) > 64
            or any(not valid_name(part) or ignored(part) for part in parts)):
        raise ProjectError("directory_create_invalid", "目录路径无效。")
    target = root.joinpath(*parts)
    parent = _inspect_directory(target.parent)
    if not parent.path.is_relative_to(root):
        raise ProjectError("directory_create_invalid", "目录路径超出当前范围。")
    created = True
    try:
        target.mkdir()
    except FileExistsError:
        created = False
    except OSError:
        raise ProjectError("directory_create_failed", "目录创建失败。") from None
    _inspect_directory(target)
    return {"path": path, "kind": "directory", "created": created}


def rename_file(root: Path, path: str, new_name: str) -> dict:
    """同目录重命名普通文件，不覆盖已有目标。"""
    parts = path.split("/") if path else []
    if (not parts or len(path) > 2048 or len(parts) > 64
            or any(not valid_name(part) or ignored(part) for part in parts)
            or not valid_name(new_name) or ignored(new_name)):
        raise ProjectError("file_rename_invalid", "文件路径或新文件名无效。")
    source = root.joinpath(*parts)
    parent = _inspect_directory(source.parent)
    if not parent.path.is_relative_to(root):
        raise ProjectError("file_rename_invalid", "文件路径超出当前范围。")
    target = source.with_name(new_name)
    try:
        metadata = source.lstat()
        if (not stat.S_ISREG(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & 0x400):
            raise ProjectError("file_rename_unsupported", "仅支持重命名普通文件。")
        if source.name == new_name:
            return {"path": path, "previous_path": path, "renamed": False}
        if target.exists() or target.is_symlink():
            raise ProjectError("file_already_exists", "新文件名已存在，未执行重命名。")
        source.rename(target)
    except ProjectError:
        raise
    except OSError:
        raise ProjectError("file_rename_failed", "文件不存在或无法重命名。") from None
    return {"path": "/".join([*parts[:-1], new_name]),
            "previous_path": path, "renamed": True}


def move_file(root: Path, path: str, new_path: str) -> dict:
    """把普通文件移动到同一根目录下的已有目录，不覆盖目标。"""
    source_parts = path.split("/") if path else []
    target_parts = new_path.split("/") if new_path else []
    if (
        not source_parts
        or not target_parts
        or len(path) > 2048
        or len(new_path) > 2048
        or len(source_parts) > 64
        or len(target_parts) > 64
        or any(
            not valid_name(part) or ignored(part)
            for part in (*source_parts, *target_parts)
        )
    ):
        raise ProjectError("file_move_invalid", "原路径或目标路径无效。")

    source = root.joinpath(*source_parts)
    target = root.joinpath(*target_parts)
    source_parent = _inspect_directory(source.parent)
    target_parent = _inspect_directory(target.parent)
    if not source_parent.path.is_relative_to(root) or not target_parent.path.is_relative_to(root):
        raise ProjectError("file_move_invalid", "文件移动路径超出当前范围。")
    try:
        metadata = source.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & 0x400
        ):
            raise ProjectError("file_move_unsupported", "仅支持移动普通文件。")
        if source == target:
            return {"path": new_path, "previous_path": path, "moved": False}
        if target.exists() or target.is_symlink():
            raise ProjectError("file_already_exists", "目标路径已存在，未执行移动。")
        source.rename(target)
    except ProjectError:
        raise
    except OSError:
        raise ProjectError("file_move_failed", "文件不存在或无法移动。") from None
    return {"path": new_path, "previous_path": path, "moved": True}


def delete_file(root: Path, path: str) -> dict:
    """删除一个普通文件；目录与重解析目标不会被删除。"""
    parts = path.split("/") if path else []
    if (
        not parts
        or len(path) > 2048
        or len(parts) > 64
        or any(not valid_name(part) or ignored(part) for part in parts)
    ):
        raise ProjectError("file_delete_invalid", "文件路径无效。")
    target = root.joinpath(*parts)
    parent = _inspect_directory(target.parent)
    if not parent.path.is_relative_to(root):
        raise ProjectError("file_delete_invalid", "文件路径超出当前范围。")
    try:
        metadata = target.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & 0x400
        ):
            raise ProjectError("file_delete_unsupported", "仅支持删除普通文件。")
        deleted_content: dict[str, object] = {}
        if metadata.st_size <= MAX_EDIT_FILE_BYTES:
            try:
                previous = target.read_bytes()
                if b"\x00" not in previous:
                    content = previous.decode("utf-8-sig")
                    deleted_content = {
                        "deleted_content_preview": content[
                            :MAX_DIFF_PREVIEW_CHARACTERS
                        ],
                        "deleted_content_truncated": (
                            len(content) > MAX_DIFF_PREVIEW_CHARACTERS
                        ),
                    }
            except (OSError, UnicodeDecodeError):
                # 正文预览是审阅增强；无法解码时仍按原契约删除普通文件。
                pass
        target.unlink()
    except ProjectError:
        raise
    except OSError:
        raise ProjectError("file_delete_failed", "文件不存在或无法删除。") from None
    return {
        "path": path,
        "deleted": True,
        "size_bytes": metadata.st_size,
        **deleted_content,
    }
