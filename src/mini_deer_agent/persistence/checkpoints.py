"""管理 Mini Deer Agent 的 checkpoint 存储资源。"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


@contextmanager
def open_sqlite_checkpointer(
    database_path: str | Path,
) -> Iterator[SqliteSaver]:
    """打开并初始化 SQLite Checkpointer，在退出上下文时关闭连接。"""
    path = Path(database_path)
    # 运行目录可能尚不存在；只创建数据库的直接父目录，不触碰其他路径。
    path.parent.mkdir(parents=True, exist_ok=True)

    # graph 的 invoke/get_state 必须发生在 with 内，避免使用已关闭的连接。
    with SqliteSaver.from_conn_string(str(path)) as checkpointer:
        # setup() 幂等创建 checkpoint 表，已有数据库不会丢失原线程状态。
        checkpointer.setup()
        yield checkpointer


@asynccontextmanager
async def open_async_sqlite_checkpointer(
    database_path: str | Path,
) -> AsyncIterator[AsyncSqliteSaver]:
    """使用原生异步 SQLite saver 支撑可取消的 LangGraph Web Run。"""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # AsyncSqliteSaver 的 aget/aput 可在 graph.astream 中直接等待并响应任务取消。
    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
