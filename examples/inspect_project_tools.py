"""检查项目只读工具；显式 --ask 时运行主 Agent 图验证模型工具闭环。"""

import argparse
import asyncio
import json

from langchain_core.messages import HumanMessage

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.application.workspaces import ProjectService
from mini_deer_agent.core import Settings
from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.persistence.conversations import (
    open_sqlite_conversation_repository,
)
from mini_deer_agent.tools.project_files import create_project_tools
from mini_deer_agent.workspace.paths import ProjectRootPolicy


async def ask_project(service: ProjectService, project_id: str, question: str) -> None:
    """运行无持久化的主图，逐节点打印真实工具调用、结果和模型回答。"""
    # 使用正式主图而非另写一个示例 Agent；不创建产品 Thread/Run 或 checkpoint。
    graph = build_agent_graph(project_service=service, project_id=project_id)
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
    """使用当前本地配置查询已有登记，显式文件参数才读取正文。"""
    parser = argparse.ArgumentParser(
        description="检查项目只读工具；--ask 会调用当前配置的模型并发送所读取的项目内容"
    )
    parser.add_argument("project_id", help="已登记项目 UUID")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--path", help="可选：直接读取项目内相对文件路径，不调用模型")
    mode.add_argument("--ask", help="向主 Agent 提问，观察列目录/读文件/回答闭环")
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
        with open_sqlite_conversation_repository(
            settings.application_database_path
        ) as repository:
            service = ProjectService(repository.projects, policy)
            if args.ask is not None:
                if not args.ask.strip():
                    parser.error("--ask 不能为空")
                asyncio.run(ask_project(service, args.project_id, args.ask))
                return
            listing, reading, *_ = create_project_tools(service, args.project_id)
            print("list_files:")
            print(
                json.dumps(
                    json.loads(listing.invoke({"limit": args.limit})),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if args.path:
                print("read_file:")
                result = asyncio.run(
                    reading.ainvoke(
                        {
                            "path": args.path,
                            "start_line": args.start_line,
                            "limit": args.limit,
                        }
                    )
                )
                print(json.dumps(json.loads(result), ensure_ascii=False, indent=2))
    except ProjectError as error:
        parser.exit(1, f"{error.code}: {error.message}\n")
    except TimeoutError:
        parser.exit(1, "主 Agent 验证超过 180 秒，已取消等待。\n")


if __name__ == "__main__":
    main()
