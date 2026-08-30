"""公开聊天模型工厂，隐藏具体模型 SDK 的文件位置。"""

from mini_deer_agent.llms.factory import create_chat_model, invoke_once


__all__ = ["create_chat_model", "invoke_once"]
