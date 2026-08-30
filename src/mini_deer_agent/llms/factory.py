"""集中创建聊天模型，隔离业务代码与具体 SDK 构造参数。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from mini_deer_agent.core import Settings


def create_chat_model(settings: Settings | None = None) -> ChatOpenAI:
    """根据项目配置创建聊天模型；此过程只构造对象，不发送网络请求。"""
    # 显式传入配置便于测试；正常运行时则从环境变量和 .env 自动读取。
    settings = settings or Settings()

    # Settings 允许模型字段为空，以保证健康检查等无模型功能仍能启动；
    # 真正创建模型时必须在这个边界拒绝不完整配置。
    model_name = (settings.model_name or "").strip()
    if not model_name:
        raise ValueError("MINI_DEER_MODEL_NAME is required to create a chat model")

    # SecretStr 需要显式取值才能检查内容，但真实密钥不能写入日志或错误信息。
    if settings.api_key is None or not settings.api_key.get_secret_value().strip():
        raise ValueError("MINI_DEER_API_KEY is required to create a chat model")

    # 统一大小写和首尾空格，让提供方分支只处理标准形式。
    provider = settings.model_provider.strip().lower()
    model_kwargs: dict[str, object] = {
        "model": model_name,
        "api_key": settings.api_key,
    }

    if provider == "openai":
        # 官方 OpenAI 的新文本生成调用优先使用 Responses API。
        model_kwargs["use_responses_api"] = True
    elif provider == "openai-compatible":
        # 第三方兼容网关没有统一默认地址，也未必支持 Responses API。
        if settings.api_base_url is None:
            raise ValueError(
                "MINI_DEER_API_BASE_URL is required for openai-compatible models"
            )
        model_kwargs["base_url"] = str(settings.api_base_url)
        model_kwargs["use_responses_api"] = False
    else:
        raise ValueError(f"Unsupported model provider: {settings.model_provider}")

    # ChatOpenAI 在这里仅保存客户端配置；调用 invoke/stream 时才会访问网络。
    return ChatOpenAI(**model_kwargs)


def invoke_once(message: str, model: BaseChatModel | None = None) -> str:
    """向聊天模型发送一条用户消息，并返回响应中的纯文本。"""
    # 空白输入没有有效语义，应在本地拒绝，避免产生无意义的计费请求。
    if not message.strip():
        raise ValueError("message must not be blank")

    # 测试可以传入替身模型；正常运行时统一通过工厂读取 .env 并创建模型。
    chat_model = model or create_chat_model()
    response = chat_model.invoke(message)

    # LangChain 的 text 属性兼容字符串和文本内容块，比直接读取 content 更稳妥。
    return str(response.text)
