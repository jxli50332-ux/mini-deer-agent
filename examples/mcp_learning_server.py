"""用于本地验收 Mini Deer MCP 接入的最小 stdio Server。"""

from mcp.server.fastmcp import FastMCP


server = FastMCP("mini-deer-learning")


@server.tool()
def add_numbers(left: int, right: int) -> int:
    """把两个整数相加。"""
    return left + right


@server.tool()
def reverse_text(text: str) -> str:
    """把输入文本按字符倒序返回。"""
    return text[::-1]


if __name__ == "__main__":
    # stdio 的 stdout 属于 MCP 协议通道，示例中不能向 stdout 打印调试文本。
    server.run(transport="stdio")
