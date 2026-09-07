"""通过独立本机进程打开目录选择器，避免阻塞后端事件循环。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol


class DirectoryPickerError(RuntimeError):
    """表示本机目录选择器无法启动或异常退出。"""


class DirectoryPicker(Protocol):
    """定义项目路由依赖的最小目录选择端口。"""

    def pick(self) -> str | None:
        """返回用户选中的绝对目录；取消时返回 None。"""


_PICKER_SCRIPT = r"""
import sys
import tkinter as tk
from tkinter import filedialog

window = tk.Tk()
window.withdraw()
window.attributes("-topmost", True)
window.update()
selected = filedialog.askdirectory(
    parent=window,
    initialdir=sys.argv[1],
    title="选择 Mini Deer 项目文件夹",
    mustexist=True,
)
print(selected, flush=True)
window.destroy()
"""


class NativeDirectoryPicker:
    """在当前桌面会话显示系统目录选择器，并只回传用户选择。"""

    def __init__(self, initial_directory: Path) -> None:
        self._initial_directory = initial_directory.resolve()

    def pick(self) -> str | None:
        """让子进程拥有 GUI 主线程；隐藏控制台但保留原生对话框。"""
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _PICKER_SCRIPT,
                    str(self._initial_directory),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=600,
                creationflags=creation_flags if os.name == "nt" else 0,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise DirectoryPickerError("本机文件夹选择器无法启动。") from error
        if result.returncode != 0:
            raise DirectoryPickerError("本机文件夹选择器异常结束。")
        selected = result.stdout.strip()
        return selected or None
