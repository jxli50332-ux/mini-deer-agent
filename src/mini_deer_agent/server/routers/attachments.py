"""通过普通 HTTP 下载已保存的附件，兼容内嵌浏览器及中文文件名。"""

import base64
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from mini_deer_agent.application import ConversationHistoryService
from mini_deer_agent.server.dependencies import get_conversation_history_service
from mini_deer_agent.server.workspace_access import require_local_request


router = APIRouter(
    prefix="/api/v1/attachments", tags=["attachments"],
    dependencies=[Depends(require_local_request)],
)


@router.get("/{message_id}/{position}/download")
def download_attachment(
    message_id: UUID,
    position: Annotated[int, Path(ge=0, le=2)],
    service: Annotated[ConversationHistoryService, Depends(get_conversation_history_service)],
) -> Response:
    """下载原始字节，不把用户文件名解释成路径或在下载时调用模型。"""
    attachment = service.get_attachment(str(message_id), position)
    if attachment is None:
        raise HTTPException(status_code=404, detail="附件不存在或消息已删除")
    content = (
        base64.b64decode(attachment.content.split(",", 1)[1], validate=True)
        if attachment.media_type.startswith("image/")
        else attachment.content.encode("utf-8")
    )
    return Response(content, media_type=attachment.media_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(attachment.filename, safe='')}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
