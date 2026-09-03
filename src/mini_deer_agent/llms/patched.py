"""捕获并回传 DeepSeek 推理内容的 ChatOpenAI 适配器。

DeepSeek 在 thinking 模式下通过 OpenAI-compatible 接口返回
``choices[].delta.reasoning_content``（流式）或 ``choices[].message.reasoning_content``
（非流式）。标准 ``ChatOpenAI`` 会忽略这个 provider 专属字段，导致思考过程
静默丢失；同时多轮工具调用时若不把历史的 ``reasoning_content`` 回传给 API，
DeepSeek 会返回 400。

本模块的 ``PatchedChatOpenAI`` 复用 DeerFlow 的思路，把 reasoning_content
捕获进 ``additional_kwargs``，并在构造请求 payload 时回写历史 assistant 消息。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

_MISSING = object()


def _extract_reasoning_content(value: Any) -> str | object:
    """从 delta/message 中提取 reasoning_content，缺省时返回哨兵对象。"""
    if isinstance(value, Mapping):
        if value.get("reasoning_content") is not None:
            return value["reasoning_content"]
        return _MISSING

    attr = getattr(value, "reasoning_content", _MISSING)
    if attr is not _MISSING and attr is not None:
        return attr

    # 部分 SDK 版本把额外字段放在 model_extra，而不是显式属性。
    model_extra = getattr(value, "model_extra", None)
    if isinstance(model_extra, Mapping) and model_extra.get("reasoning_content") is not None:
        return model_extra["reasoning_content"]

    return _MISSING


def _with_reasoning_content(
    message: AIMessage | AIMessageChunk,
    reasoning: str,
) -> AIMessage | AIMessageChunk:
    """把 reasoning_content 写入 additional_kwargs，返回不可变副本。"""
    additional_kwargs = dict(message.additional_kwargs)
    additional_kwargs["reasoning_content"] = reasoning
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


def _restore_reasoning_content(
    payload_msg: dict[str, Any],
    orig_msg: AIMessage,
) -> None:
    """把历史 AIMessage 的 reasoning_content 回写到序列化 payload。"""
    value = orig_msg.additional_kwargs.get("reasoning_content")
    if value is not None:
        payload_msg["reasoning_content"] = value


class PatchedChatOpenAI(ChatOpenAI):
    """捕获并回传 ``reasoning_content`` 的 ChatOpenAI 适配器。

    流式路径从 ``delta.reasoning_content`` 捕获，非流式路径从
    ``message.reasoning_content`` 捕获，二者都写入消息的
    ``additional_kwargs.reasoning_content``；多轮请求时再把这些内容回写到
    assistant payload，避免 DeepSeek 因缺失历史推理字段而拒绝请求。
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """构造请求 payload 并回写历史 assistant 消息的 reasoning_content。"""
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        payload_messages = payload.get("messages", [])

        if len(payload_messages) == len(original_messages):
            for payload_msg, orig_msg in zip(payload_messages, original_messages):
                if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                    _restore_reasoning_content(payload_msg, orig_msg)
            return payload

        # 消息数量不一致时按 assistant 顺序回写，避免 summary/动态上下文注入
        # 中间消息后仍能把推理字段对齐到正确的历史回答。
        ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
        ai_index = 0
        for payload_msg in payload_messages:
            if payload_msg.get("role") != "assistant":
                continue
            if ai_index >= len(ai_messages):
                break
            _restore_reasoning_content(payload_msg, ai_messages[ai_index])
            ai_index += 1
        return payload

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        """从流式 delta 捕获 reasoning_content。"""
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None

        choices = chunk.get("choices", [])
        if not choices:
            return generation_chunk

        delta = choices[0].get("delta") or {}
        reasoning = _extract_reasoning_content(delta)
        if reasoning is _MISSING or not isinstance(generation_chunk.message, AIMessageChunk):
            return generation_chunk

        return ChatGenerationChunk(
            message=_with_reasoning_content(generation_chunk.message, str(reasoning)),
            generation_info=generation_chunk.generation_info,
        )

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        """从非流式响应捕获 reasoning_content。"""
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices", [])

        patched_generations: list[ChatGeneration] | None = None
        for index, generation in enumerate(result.generations):
            choice = choices[index] if index < len(choices) else {}
            choice_message = choice.get("message", {}) if isinstance(choice, Mapping) else {}
            reasoning = _extract_reasoning_content(choice_message)

            message = generation.message
            if reasoning is _MISSING or not isinstance(message, AIMessage):
                continue

            if patched_generations is None:
                patched_generations = list(result.generations)
            patched_generations[index] = ChatGeneration(
                message=_with_reasoning_content(message, str(reasoning)),
                generation_info=generation.generation_info,
            )

        return ChatResult(
            generations=patched_generations or result.generations,
            llm_output=result.llm_output,
        )
