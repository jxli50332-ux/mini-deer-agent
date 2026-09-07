"""检查普通对话明确路径的只读访问 Scope，不登记 Project 或调用模型。"""

import argparse
import asyncio
import json
from pathlib import Path

from langchain_core.messages import HumanMessage

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.application.workspaces import ReadOnlyFileAccess
from mini_deer_agent.core import Settings
from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.tools.project_files import create_file_tools
from mini_deer_agent.workspace.paths import ProjectRootPolicy


async def ask_file(access: ReadOnlyFileAccess, question: str) -> None:
    """运行无 Project、无持久化的普通主图并打印真实工具闭环。"""
    graph = build_agent_graph(file_access=access)
    async with asyncio.timeout(180):
        async for update in graph.astream(
            {"messages": [HumanMessage(content=question)]},
            config={"recursion_limit": 24},
            stream_mode="updates",
        ):
            for node, state in update.items():
                for message in state.get("messages", []):
                    print(f"\n[{node}/{message.type}]", flush=True)
                    if getattr(message, "tool_calls", None):
                        print(
                            json.dumps(message.tool_calls, ensure_ascii=False),
                            flush=True,
                        )
                    if message.text:
                        print(message.text, flush=True)


def main() -> None:
    """授权一个明确文件或目录，并打印模型实际可见的工具结果。"""
    parser = argparse.ArgumentParser(
        description="检查普通对话明确路径的只读访问；不登记 Project、不调用模型"
    )
    parser.add_argument("target", help="用户明确指定的本机绝对文件或目录")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--path", help="目录 Scope 内要读取的相对文件；单文件 Scope 可省略"
    )
    mode.add_argument("--ask", help="交给无 Project 的普通主图并观察真实模型工具闭环")
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    settings = Settings()
    try:
        policy = ProjectRootPolicy(
            allowed_roots=settings.workspace_allowed_roots,
            blocked_roots=(
                settings.application_database_path.resolve().parent,
                settings.checkpoint_database_path.resolve().parent,
            ),
        )
        access = ReadOnlyFileAccess.for_explicit_path(policy, args.target)
        if args.ask is not None:
            if not args.ask.strip():
                parser.error("--ask 不能为空")
            asyncio.run(ask_file(access, args.ask))
            return
        listing, reading, *_ = create_file_tools(access)
        # 只展示来源和目标类型；绝对路径与文件系统身份属于可信运行时上下文。
        print(
            json.dumps(
                {
                    "source": access.scope.source,
                    "target_kind": access.scope.target_kind,
                    "project_id": access.scope.project_id,
                    "access_mode": access.scope.access_mode,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        listed = json.loads(listing.invoke({"limit": args.limit}))
        print("list_files:")
        print(json.dumps(listed, ensure_ascii=False, indent=2))
        read_path = args.path
        if access.scope.target_kind == "file":
            read_path = Path(access.scope.target_path).name
        if read_path:
            result = asyncio.run(
                reading.ainvoke(
                    {
                        "path": read_path,
                        "start_line": args.start_line,
                        "limit": args.limit,
                    }
                )
            )
            print("read_file:")
            print(json.dumps(json.loads(result), ensure_ascii=False, indent=2))
    except ProjectError as error:
        parser.exit(1, f"{error.code}: {error.message}\n")
    except TimeoutError:
        parser.exit(1, "普通主图验证超过 180 秒，已取消等待。\n")


if __name__ == "__main__":
    main()
