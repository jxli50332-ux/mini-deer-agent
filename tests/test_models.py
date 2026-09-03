"""验证模型工厂的配置边界和 SDK 参数映射，全程不访问真实模型。"""

import pytest
from langchain_core.messages import AIMessage

from mini_deer_agent.core import Settings
from mini_deer_agent.llms import factory as models


class FakeChatModel:
    """记录单轮输入并返回固定消息，避免测试访问真实模型服务。"""

    def __init__(self, reply: str = "测试回复") -> None:
        """保存测试回复，并在调用前保持输入为空。"""
        self.reply = reply
        self.received_message: str | None = None

    def invoke(self, message: str) -> AIMessage:
        """模拟 LangChain 模型的 invoke 接口。"""
        self.received_message = message
        return AIMessage(content=self.reply)


def test_factory_requires_model_name() -> None:
    settings = Settings(model_name=None, api_key="test-key", _env_file=None)

    with pytest.raises(ValueError, match="MINI_DEER_MODEL_NAME"):
        models.create_chat_model(settings)


def test_factory_requires_api_key() -> None:
    settings = Settings(model_name="test-model", api_key=None, _env_file=None)

    with pytest.raises(ValueError, match="MINI_DEER_API_KEY"):
        models.create_chat_model(settings)


def test_factory_rejects_unknown_provider() -> None:
    settings = Settings(
        model_provider="unknown",
        model_name="test-model",
        api_key="test-key",
        _env_file=None,
    )

    with pytest.raises(ValueError, match="unknown"):
        models.create_chat_model(settings)


def test_compatible_provider_requires_base_url() -> None:
    settings = Settings(
        model_provider="openai-compatible",
        model_name="test-model",
        api_key="test-key",
        api_base_url=None,
        _env_file=None,
    )

    with pytest.raises(ValueError, match="MINI_DEER_API_BASE_URL"):
        models.create_chat_model(settings)


def test_factory_builds_official_openai_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    fake_model = object()

    # 用轻量函数替换真实 SDK 类，只捕获工厂传入的构造参数。
    def fake_chat_openai(**kwargs: object) -> object:
        captured.update(kwargs)
        return fake_model

    monkeypatch.setattr(models, "ChatOpenAI", fake_chat_openai)
    settings = Settings(
        model_provider="OPENAI",
        model_name="test-model",
        api_key="test-key",
        _env_file=None,
    )

    result = models.create_chat_model(settings)

    assert result is fake_model
    assert captured["model"] == "test-model"
    assert captured["api_key"] == settings.api_key
    assert captured["use_responses_api"] is True
    assert "base_url" not in captured


def test_factory_builds_openai_compatible_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    # 兼容提供方测试同样不创建客户端，避免任何网络或密钥依赖。
    def fake_chat_openai(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(models, "PatchedChatOpenAI", fake_chat_openai)
    settings = Settings(
        model_provider="openai-compatible",
        model_name="test-model",
        api_key="test-key",
        api_base_url="https://example.invalid/v1",
        _env_file=None,
    )

    models.create_chat_model(settings)

    assert captured["model"] == "test-model"
    assert captured["api_key"] == settings.api_key
    assert captured["base_url"] == "https://example.invalid/v1"
    assert captured["use_responses_api"] is False


def test_invoke_once_rejects_blank_message() -> None:
    """空白输入应在本地失败，不能产生无意义的模型请求。"""
    with pytest.raises(ValueError, match="message"):
        models.invoke_once("   ", model=FakeChatModel())


def test_invoke_once_returns_model_text() -> None:
    """单轮入口应把原始输入交给模型，并返回消息中的纯文本。"""
    fake_model = FakeChatModel(reply="你好，我是测试模型。")

    reply = models.invoke_once("你好", model=fake_model)

    assert fake_model.received_message == "你好"
    assert reply == "你好，我是测试模型。"


def test_invoke_once_creates_model_when_not_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常运行未传模型时，应通过统一工厂创建模型。"""
    fake_model = FakeChatModel()

    # 替换模型工厂，验证调用路径但不读取真实 .env 或访问网络。
    monkeypatch.setattr(models, "create_chat_model", lambda: fake_model)

    assert models.invoke_once("测试") == "测试回复"
    assert fake_model.received_message == "测试"
