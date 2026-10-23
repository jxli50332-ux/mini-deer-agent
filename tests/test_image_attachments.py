"""保护图片上传、持久化与视觉消息边界，不调用外部模型或 OCR。"""

import base64
import io

import pytest
from PIL import Image
from langchain_core.messages import SystemMessage

from mini_deer_agent.domain import validate_attachment_batch
from mini_deer_agent.domain.image_attachments import MAX_IMAGE_ATTACHMENT_BYTES
from mini_deer_agent.application.run_stream import _human_message
from mini_deer_agent.agents.middleware import prepare_model_messages
from mini_deer_agent.agents.middleware.context_summary import _message_record


def image_content(format: str = "PNG", size: tuple[int, int] = (12, 8)) -> tuple[str, bytes]:
    """生成无敏感内容的真实图片，避免用伪文件头冒充有效图片。"""
    output = io.BytesIO()
    Image.new("RGB", size, "red").save(output, format=format)
    raw = output.getvalue()
    mime = "image/png" if format == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}", raw


@pytest.mark.parametrize(("format", "filename"), [("PNG", "截图.png"), ("JPEG", "photo.JPG")])
def test_image_metadata_uses_actual_bytes(format: str, filename: str) -> None:
    """大小按解码后的原图计算，不能按 Base64 字符数或客户端声明计算。"""
    content, raw = image_content(format)
    (image,) = validate_attachment_batch([(filename, content)])
    assert image.size_bytes == len(raw)
    assert image.media_type == ("image/png" if format == "PNG" else "image/jpeg")
    assert image.content == content


@pytest.mark.parametrize("kind", ["mismatch", "corrupt", "encoding", "oversized", "dimensions", "pdf"])
def test_invalid_image_is_rejected(kind: str) -> None:
    """伪装、损坏、错误编码、超限和 PDF 均在创建 Run 前拒绝。"""
    content, _ = image_content()
    filename = "image.png"
    if kind == "mismatch": filename = "image.jpg"
    elif kind == "corrupt": content = "data:image/png;base64," + base64.b64encode(b"not an image").decode()
    elif kind == "encoding": content = "data:image/png;base64,not!base64"
    elif kind == "oversized": content = "data:image/png;base64," + "A" * (4 * ((MAX_IMAGE_ATTACHMENT_BYTES + 2) // 3) + 40)
    elif kind == "dimensions": content, _ = image_content(size=(6001, 1))
    elif kind == "pdf": filename = "report.pdf"
    with pytest.raises(ValueError):
        validate_attachment_batch([(filename, content)])


def test_mixed_attachments_reach_model_as_distinct_visual_blocks() -> None:
    """视觉消息携带真实图片，原问题和 checkpoint 保持纯文本，旧文本规则仍生效。"""
    content, _ = image_content()
    attachments = validate_attachment_batch([("需求.md", "比较颜色"), ("截图.png", content)])
    original = _human_message("图中是什么颜色？", attachments)
    prepared = prepare_model_messages(SystemMessage(content="system"), [original])
    blocks = prepared[1].content
    assert isinstance(blocks, list)
    assert {"type": "image_url", "image_url": {"url": content}} in blocks
    text = prepared[1].text
    assert "比较颜色" in text and "图中是什么颜色" in text
    assert content not in text
    assert original.content == "图中是什么颜色？"
    assert len(original.additional_kwargs["text_attachments"]) == 1
    assert len(original.additional_kwargs["image_attachments"]) == 1
    assert content not in str(_message_record(original))
    assert "截图.png" in str(_message_record(original))


def test_mixed_attachment_count_stays_shared() -> None:
    """图片和文本不能各自绕过每条消息的 3 个附件上限。"""
    content, _ = image_content()
    with pytest.raises(ValueError, match="too many"):
        validate_attachment_batch([("a.png", content), ("b.png", content), ("a.txt", "x"), ("b.txt", "x")])


def test_image_bytes_do_not_consume_text_attachment_budget() -> None:
    """真实图片可超过旧文本体积上限，文本和图片按各自预算校验。"""
    output = io.BytesIO()
    Image.effect_noise((400, 400), 100).convert("RGB").save(output, format="PNG")
    raw = output.getvalue()
    assert len(raw) > 64 * 1024
    content = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    attachments = validate_attachment_batch([("noise.png", content), ("note.txt", "x" * 32_768)])
    assert attachments[0].size_bytes == len(raw)
    assert attachments[1].size_bytes == 32_768
