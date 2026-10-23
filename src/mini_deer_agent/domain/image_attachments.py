"""校验视觉附件的实际格式、解码大小和像素边界，不执行 OCR。"""

import base64
import binascii
import io
import warnings
from typing import Literal

from PIL import Image, UnidentifiedImageError


ImageAttachmentMediaType = Literal["image/png", "image/jpeg"]
MAX_IMAGE_ATTACHMENT_BYTES = 4 * 1024 * 1024
MAX_IMAGE_ATTACHMENTS_TOTAL_BYTES = 8 * 1024 * 1024
MAX_IMAGE_DATA_URL_LENGTH = 4 * ((MAX_IMAGE_ATTACHMENT_BYTES + 2) // 3) + 32


def validate_image_content(
    filename: str, content: str
) -> tuple[ImageAttachmentMediaType, int, str]:
    """只接受与扩展名一致的完整 PNG/JPEG，返回可信类型、原始字节数与标准 data URL。"""
    media_type: ImageAttachmentMediaType = (
        "image/png" if filename.lower().endswith(".png") else "image/jpeg"
    )
    prefix = f"data:{media_type};base64,"
    if len(content) > MAX_IMAGE_DATA_URL_LENGTH:
        raise ValueError("image attachment exceeds 4 MiB")
    if not content.startswith(prefix):
        raise ValueError("image attachment must use a matching PNG/JPEG data URL")
    try:
        raw = base64.b64decode(content[len(prefix) :], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid image attachment encoding") from exc
    if not raw or len(raw) > MAX_IMAGE_ATTACHMENT_BYTES:
        raise ValueError("image attachment must be nonempty and at most 4 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != ("PNG" if media_type == "image/png" else "JPEG"):
                    raise ValueError("image format does not match filename")
                width, height = image.size
                # 同时满足两个供应商的常用尺寸边界，限制解压后的内存占用。
                if max(width, height) > 6000 or width * height > 16_000_000:
                    raise ValueError("image exceeds 6000 pixels per side or 16 megapixels")
                image.load()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("image attachment is damaged or unsupported") from exc
    canonical = prefix + base64.b64encode(raw).decode("ascii")
    return media_type, len(raw), canonical
