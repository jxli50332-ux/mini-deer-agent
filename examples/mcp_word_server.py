"""在独立环境中启动 Word MCP，并把普通 print 留在 stderr。"""

from __future__ import annotations

import builtins
import os
from pathlib import Path
import sys


def main() -> None:
    # 上游启动信息使用 print；stdio 的 stdout 只能传输 MCP JSON-RPC。
    original_print = builtins.print

    def diagnostic_print(*args: object, **kwargs: object) -> None:
        kwargs.setdefault("file", sys.stderr)
        original_print(*args, **kwargs)

    builtins.print = diagnostic_print
    output_directory = Path(__file__).resolve().parents[1] / "data" / "word-documents"
    output_directory.mkdir(parents=True, exist_ok=True)
    os.chdir(output_directory)

    from word_document_server.main import run_server

    run_server()


if __name__ == "__main__":
    main()
