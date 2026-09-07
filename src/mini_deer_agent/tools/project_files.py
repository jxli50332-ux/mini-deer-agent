"""把通用文件访问上下文适配成 LangChain 工具。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from mini_deer_agent.domain.workspaces import FileAccessScope, ProjectError

if TYPE_CHECKING:
    from mini_deer_agent.application.workspaces import FileAccess, ProjectService


class FileAccessProtocol(Protocol):
    """工具层只依赖通用文件操作，不反向加载应用包。"""

    scope: FileAccessScope

    def list_files(self, *, path: str = "", limit: int = 200) -> dict:
        """列出当前 Scope 的直接子项。"""

    def read_file(
        self, *, path: str, start_line: int = 1, limit: int = 200
    ) -> dict:
        """读取当前 Scope 内的有界文本。"""

    def glob_files(
        self, *, pattern: str, path: str = "", limit: int = 100
    ) -> dict:
        """在当前 Scope 内有界匹配文件名。"""

    def search_files(
        self,
        *,
        query: str,
        path: str = "",
        file_pattern: str | None = None,
        case_sensitive: bool = False,
        limit: int = 100,
    ) -> dict:
        """在当前 Scope 内有界搜索文件正文。"""

    def create_file(self, *, path: str, content: str) -> dict:
        """在当前 Scope 内创建新文本文件。"""

    def str_replace(self, *, path: str, old_str: str, new_str: str) -> dict:
        """精确替换当前 Scope 内已有文本文件的唯一匹配。"""

    def rename_file(self, *, path: str, new_name: str) -> dict:
        """在当前目录范围内重命名文件。"""

    def move_file(self, *, path: str, new_path: str) -> dict:
        """在当前目录范围内移动文件。"""

    def delete_file(self, *, path: str) -> dict:
        """删除当前范围内的一个普通文件。"""

    def create_directory(self, *, path: str) -> dict:
        """创建当前目录范围内的子目录。"""

    def write_file(self, *, path: str, content: str) -> dict:
        """使用完整文本覆盖当前 Scope 内已有文本文件。"""


class RenameFileInput(BaseModel):
    """新名称只能是同目录文件名。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=2048, description="原文件路径")
    new_name: str = Field(min_length=1, max_length=255, description="新文件名，不含目录")


class MoveFileInput(BaseModel):
    """移动路径必须保持在同一个文件范围与允许根内。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=2048, description="原文件路径")
    new_path: str = Field(
        min_length=1,
        max_length=2048,
        description="目标文件完整路径；目标父目录必须已经存在",
    )


class DeleteFileInput(BaseModel):
    """删除操作只接受一个明确的普通文件路径。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        min_length=1,
        max_length=2048,
        description="要删除的普通文件路径；不能传入目录",
    )


class CreateDirectoryInput(BaseModel):
    """创建目录只接收当前文件范围内的路径。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=2048,
                      description="目录路径；项目相对路径、workspace-N/... 或本轮明确根外目录的绝对子路径")


class ListProjectFilesInput(BaseModel):
    """模型指定当前 Scope 内路径，不接收根身份。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        default="",
        max_length=2048,
        description=(
            "当前文件范围内的相对目录，空字符串表示根；"
            "Project Thread 本轮若明确给出根外绝对路径，也可原样使用"
        ),
    )
    limit: int = Field(
        default=100, ge=1, le=200, description="最多列出的直接子项数"
    )


class ReadProjectFileInput(BaseModel):
    """读取一段源码，行号从 1 开始；模型没有写入参数。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        min_length=1,
        max_length=2048,
        description=(
            "list_files 返回的路径；Project Thread 本轮若明确给出根外绝对路径，"
            "也可原样使用"
        ),
    )
    start_line: int = Field(
        default=1, ge=1, le=1000000, description="起始行号，从 1 开始"
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=200,
        description="最多读取的行数；使用 next_line 继续",
    )


class GlobProjectFilesInput(BaseModel):
    """按相对 glob 查找文件；不接受绝对根或目录匹配开关。"""

    model_config = ConfigDict(extra="forbid")
    pattern: str = Field(
        min_length=1,
        max_length=256,
        description="相对于搜索目录的文件 glob，例如 **/*.py",
    )
    path: str = Field(
        default="",
        max_length=2048,
        description=(
            "当前文件范围内的相对搜索目录；普通 Thread 可传 workspace-N；"
            "Project Thread 可使用用户本轮明确给出的根外绝对路径"
        ),
    )
    limit: int = Field(default=100, ge=1, le=200, description="最多返回的路径数")


class SearchProjectFilesInput(BaseModel):
    """搜索字面量正文；路径和过滤模式都不能改变当前 Scope。"""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(
        min_length=1,
        max_length=256,
        description="要查找的单行字面量文本，不作为正则表达式解释",
    )
    path: str = Field(
        default="",
        max_length=2048,
        description=(
            "当前文件范围内的相对文件或目录；普通 Thread 可传 workspace-N；"
            "Project Thread 可使用用户本轮明确给出的根外绝对路径"
        ),
    )
    file_pattern: str | None = Field(
        default=None,
        max_length=256,
        description="可选候选文件 glob，例如 **/*.py",
    )
    case_sensitive: bool = Field(default=False, description="是否区分大小写")
    limit: int = Field(default=100, ge=1, le=200, description="最多返回的匹配行数")


class CreateProjectFileInput(BaseModel):
    """创建一个新 UTF-8 文本文件；不允许覆盖已有目标。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        min_length=1,
        max_length=2048,
        description=(
            "新文件在当前范围内的路径；Project 使用相对路径，"
            "普通 Thread 使用 workspace-N/..."
        ),
    )
    content: str = Field(
        max_length=81920,
        description="要写入的新文件完整 UTF-8 文本，最多 80 KiB",
    )


class StrReplaceInput(BaseModel):
    """精确替换已有 UTF-8 文本中的唯一匹配。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        min_length=1,
        max_length=2048,
        description=(
            "要编辑的文件路径；Project 使用相对路径，普通 Thread 使用 "
            "workspace-N/...，本轮明确给出的根外绝对路径可原样使用"
        ),
    )
    old_str: str = Field(
        min_length=1,
        max_length=2097152,
        description="文件中预期只出现一次的原始精确文本",
    )
    new_str: str = Field(
        max_length=2097152,
        description="替换后的文本；可为空字符串",
    )


class WriteProjectFileInput(BaseModel):
    """使用完整 UTF-8 文本覆盖已有文件，不创建新目标。"""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        min_length=1,
        max_length=2048,
        description=(
            "已有文件的路径；Project 使用相对路径，普通 Thread 使用 "
            "workspace-N/...，本轮明确给出的根外绝对路径可原样使用"
        ),
    )
    content: str = Field(
        max_length=81920,
        description="替换文件全部内容的 UTF-8 文本，最多 80 KiB",
    )


def create_file_tools(
    access: FileAccessProtocol,
    *,
    validation_error_code: str = "file_tool_arguments_invalid",
) -> tuple[BaseTool, ...]:
    """为已冻结 Scope 创建工具；项目与明确路径调用相同实现。"""

    def execute(operation: Callable[[], dict]) -> str:
        """工具只返回稳定数据或操作错误，绝对根和底层异常不进入模型。"""
        try:
            result = operation()
            payload = {"ok": result.get("status", "text") == "text", **result}
        except ProjectError as error:
            payload = {
                "ok": False,
                "error": {"code": error.code, "message": error.message},
            }
        except Exception:
            payload = {
                "ok": False,
                "error": {
                    "code": "file_tool_failed",
                    "message": "文件操作失败，请稍后重试。",
                },
            }
        return json.dumps(payload, ensure_ascii=False)

    def list_files(path: str = "", limit: int = 100) -> str:
        """列出当前 Scope 的直接子项，返回截断信息和访问状态。"""
        return execute(lambda: access.list_files(path=path, limit=limit))

    def read_file(path: str, start_line: int = 1, limit: int = 100) -> str:
        """读取当前 Scope 的有界文本片段，返回真实行号和版本摘要。"""
        return execute(
            lambda: access.read_file(
                path=path,
                start_line=start_line,
                limit=limit,
            )
        )

    def glob_files(pattern: str, path: str = "", limit: int = 100) -> str:
        """递归匹配当前 Scope 内的文件路径，不读取文件内容。"""
        return execute(
            lambda: access.glob_files(pattern=pattern, path=path, limit=limit)
        )

    def search_files(
        query: str,
        path: str = "",
        file_pattern: str | None = None,
        case_sensitive: bool = False,
        limit: int = 100,
    ) -> str:
        """搜索匹配正文，返回文件路径、真实行号和有界行摘要。"""
        return execute(
            lambda: access.search_files(
                query=query,
                path=path,
                file_pattern=file_pattern,
                case_sensitive=case_sensitive,
                limit=limit,
            )
        )

    def create_file(path: str, content: str) -> str:
        """在当前目录范围创建新文本文件，不覆盖已有目标。"""
        return execute(lambda: access.create_file(path=path, content=content))

    def str_replace(path: str, old_str: str, new_str: str) -> str:
        """仅当原始文本恰好出现一次时替换已有文件。"""
        return execute(
            lambda: access.str_replace(path=path, old_str=old_str, new_str=new_str)
        )

    def write_file(path: str, content: str) -> str:
        """使用给定完整文本覆盖当前已有文件。"""
        return execute(lambda: access.write_file(path=path, content=content))

    async def list_files_async(path: str = "", limit: int = 100) -> str:
        """在线程池做有界只读 IO；取消等待向上层传播，不包装为成功。"""
        return await asyncio.to_thread(list_files, path, limit)

    async def read_file_async(
        path: str, start_line: int = 1, limit: int = 100
    ) -> str:
        """异步入口与同步入口使用同一绑定和读取策略。"""
        return await asyncio.to_thread(read_file, path, start_line, limit)

    async def glob_files_async(
        pattern: str, path: str = "", limit: int = 100
    ) -> str:
        """异步入口在线程池执行同一有界文件名搜索。"""
        return await asyncio.to_thread(glob_files, pattern, path, limit)

    async def search_files_async(
        query: str,
        path: str = "",
        file_pattern: str | None = None,
        case_sensitive: bool = False,
        limit: int = 100,
    ) -> str:
        """异步入口在线程池执行同一有界正文搜索。"""
        return await asyncio.to_thread(
            search_files,
            query,
            path,
            file_pattern,
            case_sensitive,
            limit,
        )

    async def create_file_async(path: str, content: str) -> str:
        """异步入口在线程池执行同一新文件创建操作。"""
        return await asyncio.to_thread(create_file, path, content)

    async def str_replace_async(path: str, old_str: str, new_str: str) -> str:
        """异步入口在线程池执行同一精确替换操作。"""
        return await asyncio.to_thread(str_replace, path, old_str, new_str)

    async def write_file_async(path: str, content: str) -> str:
        """异步入口在线程池执行同一完整文本更新。"""
        return await asyncio.to_thread(write_file, path, content)

    def create_directory(path: str) -> str:
        return execute(lambda: access.create_directory(path=path))

    async def create_directory_async(path: str) -> str:
        return await asyncio.to_thread(create_directory, path)

    def rename_file(path: str, new_name: str) -> str:
        return execute(lambda: access.rename_file(path=path, new_name=new_name))

    async def rename_file_async(path: str, new_name: str) -> str:
        return await asyncio.to_thread(rename_file, path, new_name)

    def move_file(path: str, new_path: str) -> str:
        return execute(lambda: access.move_file(path=path, new_path=new_path))

    async def move_file_async(path: str, new_path: str) -> str:
        return await asyncio.to_thread(move_file, path, new_path)

    def delete_file(path: str) -> str:
        return execute(lambda: access.delete_file(path=path))

    async def delete_file_async(path: str) -> str:
        return await asyncio.to_thread(delete_file, path)

    validation_error = json.dumps(
        {
            "ok": False,
            "error": {
                "code": validation_error_code,
                "message": "只允许当前范围内的路径、文本和有界参数。",
            },
        },
        ensure_ascii=False,
    )
    tools = (
        StructuredTool.from_function(
            func=list_files,
            coroutine=list_files_async,
            name="list_files",
            args_schema=ListProjectFilesInput,
            handle_validation_error=validation_error,
            description=(
                "列出当前文件范围的单层目录。通常使用项目相对路径；"
                "若用户本轮明确写出根外绝对路径，可原样传入该路径。"
                "先从根发现路径，按需展开；truncated 表示未列完整。"
            ),
        ),
        StructuredTool.from_function(
            func=read_file,
            coroutine=read_file_async,
            name="read_file",
            args_schema=ReadProjectFileInput,
            handle_validation_error=validation_error,
            description=(
                "读取当前文件范围内的 UTF-8 源码。项目文件使用相对路径；"
                "用户本轮明确写出的根外绝对路径可原样使用。返回 "
                "lines/start_line/next_line/revision，并引用实际路径与行号。"
            ),
        ),
        StructuredTool.from_function(
            func=glob_files,
            coroutine=glob_files_async,
            name="glob_files",
            args_schema=GlobProjectFilesInput,
            handle_validation_error=validation_error,
            description=(
                "按 glob 递归查找当前文件范围内的文件名，例如 **/*.py。"
                "返回路径、扫描数量和明确截断原因；不读取正文，"
                "不匹配被忽略或链接中的文件。"
            ),
        ),
        StructuredTool.from_function(
            func=search_files,
            coroutine=search_files_async,
            name="search_files",
            args_schema=SearchProjectFilesInput,
            handle_validation_error=validation_error,
            description=(
                "在当前文件或目录范围内搜索字面量正文。可用 file_pattern "
                "限定候选文件；返回路径、真实行号、单行摘要和明确截断原因。"
                "默认不区分大小写，不支持任意正则。"
            ),
        ),
    )
    replace_tool = StructuredTool.from_function(
        func=str_replace,
        coroutine=str_replace_async,
        name="str_replace",
        args_schema=StrReplaceInput,
        handle_validation_error=validation_error,
        description=(
            "精确编辑当前范围内已有的 UTF-8 文本文件。old_str 必须在文件中"
            "恰好出现一次；未找到或出现多次时不修改文件。成功后用 read_file 核对。"
        ),
    )
    write_tool = StructuredTool.from_function(
        func=write_file,
        coroutine=write_file_async,
        name="write_file",
        args_schema=WriteProjectFileInput,
        handle_validation_error=validation_error,
        description=(
            "用完整 UTF-8 文本更新当前范围内已经存在的文件，不创建新目标。"
            "局部改动优先使用 str_replace；完整更新成功后用 read_file 核对。"
        ),
    )
    delete_tool = StructuredTool.from_function(
        func=delete_file,
        coroutine=delete_file_async,
        name="delete_file",
        args_schema=DeleteFileInput,
        handle_validation_error=validation_error,
        description=(
            "删除一个明确路径的普通文件，不能删除目录或递归删除。"
            "只有用户明确要求删除该文件时才调用；成功后用 list_files 确认路径已不存在。"
        ),
    )
    if access.scope.target_kind == "file":
        return (*tools, replace_tool, write_tool, delete_tool)
    create_tool = StructuredTool.from_function(
        func=create_file,
        coroutine=create_file_async,
        name="create_file",
        args_schema=CreateProjectFileInput,
        handle_validation_error=validation_error,
        description=(
            "在当前文件范围内创建一个新的 UTF-8 文本文件。"
            "Project 使用相对路径，普通 Thread 使用 workspace-N/...；"
            "父目录必须存在，目标已存在时不会覆盖。"
        ),
    )
    directory_tool = StructuredTool.from_function(
        func=create_directory,
        coroutine=create_directory_async,
        name="create_directory",
        args_schema=CreateDirectoryInput,
        handle_validation_error=validation_error,
        description="创建单层目录，父目录必须存在；嵌套目录请逐层创建。已有目录返回 created=false，不改其内容。创建后用 list_files 核对。",
    )
    rename_tool = StructuredTool.from_function(
        func=rename_file,
        coroutine=rename_file_async,
        name="rename_file",
        args_schema=RenameFileInput,
        handle_validation_error=validation_error,
        description="在同一目录内重命名普通文件。new_name 仅为文件名；目标已存在时不覆盖。成功后使用返回的新 path 读取或列目录核对。",
    )
    move_tool = StructuredTool.from_function(
        func=move_file,
        coroutine=move_file_async,
        name="move_file",
        args_schema=MoveFileInput,
        handle_validation_error=validation_error,
        description=(
            "把普通文件移动到同一文件范围内的另一个已有目录。"
            "目标路径已存在时不覆盖；成功后使用返回的新 path 读取并列目录核对。"
        ),
    )
    return (
        *tools,
        create_tool,
        replace_tool,
        write_tool,
        directory_tool,
        rename_tool,
        move_tool,
        delete_tool,
    )


def create_project_tools(
    service: ProjectService, project_id: str
) -> tuple[BaseTool, ...]:
    """兼容现有项目主图；内部已复用通用文件访问 Scope。"""
    # 局部导入维持 tools → application 的模块加载边界，避免 application.run_stream
    # 经 agents 反向导入本模块时形成初始化循环。
    from mini_deer_agent.application.workspaces import FileAccess

    access = FileAccess.for_project(service, project_id)
    return create_file_tools(
        access, validation_error_code="project_tool_arguments_invalid"
    )
