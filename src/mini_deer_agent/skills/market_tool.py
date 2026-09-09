"""Agent 只读 Skill 市场搜索工具。"""

import json

from langchain_core.tools import BaseTool, tool

from mini_deer_agent.skills.marketplace import SkillMarketplaceService


def create_skill_market_search_tool(service: SkillMarketplaceService) -> BaseTool:
    @tool("skill_market_search")
    def skill_market_search(query: str, refresh: bool = False) -> str:
        """搜索 Skill 市场并返回非执行元数据；不能安装、更新或删除 Skill。"""
        items, synced_at, from_cache = service.search(query, refresh=refresh)
        return json.dumps(
            {
                "synced_at": synced_at,
                "from_cache": from_cache,
                "items": [
                    {
                        "provider": item.provider,
                        "remote_id": item.remote_id,
                        "name": item.name,
                        "version": item.version,
                        "description": item.description,
                        "publisher": item.publisher,
                        "canonical_url": item.canonical_url,
                        "tags": item.tags,
                        "required_tools": item.required_tools,
                        "runtime_requirements": item.runtime_requirements,
                        "scan_status": item.scan_status,
                        "compatible": item.compatible,
                        "compatibility_reason": item.compatibility_reason,
                    }
                    for item in items[:10]
                ],
                "message": "仅返回市场元数据；安装必须由用户在设置界面确认。",
            },
            ensure_ascii=False,
        )

    return skill_market_search


__all__ = ["create_skill_market_search_tool"]
