"""验证市场 Provider 投影、缓存与断网回退。"""

from io import BytesIO
import hashlib
from pathlib import Path
from zipfile import ZipFile

import httpx

from mini_deer_agent.skills.market_tool import create_skill_market_search_tool
from mini_deer_agent.skills.marketplace import SkillMarketplaceService
from mini_deer_agent.skills.management import SkillManagementService
from mini_deer_agent.skills.registries import ClawHubRegistryProvider
from mini_deer_agent.skills.user import UserSkillManager


def _skill_archive() -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(
            "meeting-notes/SKILL.md",
            "---\nname: meeting-notes\ndescription: 整理会议决定。\n---\n提取行动项。\n",
        )
    return stream.getvalue()


def _skill_text() -> str:
    return "---\nname: meeting-notes\ndescription: 整理会议决定。\n---\n提取行动项。\n"


def _response(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/download"):
        assert request.url.params.get("version") == "1.1.0"
        return httpx.Response(
            200,
            request=request,
            content=_skill_archive(),
            headers={"Content-Type": "application/zip"},
        )
    if request.url.path.endswith("/versions"):
        return httpx.Response(
            200,
            request=request,
            json={
                "items": [{
                    "version": "1.1.0",
                    "changelog": "增加行动项提取。",
                    "createdAt": 1785719991059,
                }],
                "nextCursor": None,
            },
        )
    if "/versions/" in request.url.path:
        return httpx.Response(
            200,
            request=request,
            json={
                "skill": {"slug": "meeting-notes"},
                "version": {
                    "version": "1.1.0",
                    "license": "MIT",
                    "changelog": "增加行动项提取。",
                    "createdAt": 1785719991059,
                    "files": [{
                        "path": "SKILL.md",
                        "size": len(_skill_text().encode()),
                        "sha256": hashlib.sha256(_skill_text().encode()).hexdigest(),
                        "contentType": "text/markdown",
                    }],
                    "security": {"status": "clean"},
                },
            },
        )
    if "/api/v1/skills/" in request.url.path:
        return httpx.Response(
            200,
            request=request,
            json={
                "skill": {
                    "slug": "meeting-notes",
                    "summary": "整理会议决定与行动项。",
                    "tags": {"latest": "1.1.0", "meeting": "1.1.0"},
                },
                "latestVersion": {
                    "version": "1.1.0",
                    "license": "MIT",
                    "changelog": "增加行动项提取。",
                    "createdAt": 1785719991059,
                },
                "metadata": {"setup": [], "systems": []},
                "moderation": {"status": "clean"},
            },
        )
    return httpx.Response(
        200,
        request=request,
        json={
            "results": [{
                "slug": "meeting-notes",
                "summary": "整理会议决定与行动项。",
                "ownerHandle": "publisher",
                "install": {"reference": "publisher/meeting-notes", "sourceUrl": None},
                "trust": {"installability": "installable", "clawHubVerdict": "clean"},
                "updatedAt": 1785719991059,
                "native": {"skill": {
                    "slug": "meeting-notes",
                    "categories": ["productivity"],
                    "topics": ["meeting"],
                    "isSuspicious": False,
                }},
            }]
        },
    )


def test_clawhub_projection_and_offline_cache(tmp_path: Path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(_response))
    provider = ClawHubRegistryProvider(base_url="https://registry.test", client=client)
    cache = tmp_path / "market.json"
    service = SkillMarketplaceService(cache, (provider,))

    items, synced_at, from_cache = service.search("meeting", refresh=True)
    assert from_cache is False
    assert synced_at is not None
    assert items[0].remote_id == "publisher/meeting-notes"
    assert items[0].compatible is True
    assert items[0].canonical_url == "https://registry.test/publisher/skills/meeting-notes"
    versions = service.list_versions("clawhub", "publisher/meeting-notes")
    assert versions[0].version == "1.1.0"

    offline = ClawHubRegistryProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
        )
    )
    fallback = SkillMarketplaceService(cache, (offline,))
    cached, cached_at, cached_flag = fallback.search("meeting", refresh=True)
    assert cached_flag is True
    assert cached_at == synced_at
    assert cached == items

    projected = create_skill_market_search_tool(service).invoke(
        {"query": "meeting", "refresh": False}
    )
    assert '"remote_id": "publisher/meeting-notes"' in projected
    assert "仅返回市场元数据" in projected


def test_market_install_update_and_uninstall_preserve_remote_identity(
    tmp_path: Path,
) -> None:
    client = httpx.Client(transport=httpx.MockTransport(_response))
    provider = ClawHubRegistryProvider(base_url="https://registry.test", client=client)
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    manager = UserSkillManager(tmp_path / "managed", builtin_root=builtin)
    management = SkillManagementService(manager)
    service = SkillMarketplaceService(tmp_path / "market.json", (provider,), management)
    service.search("meeting", refresh=True)

    install_preview = service.preview_change(
        "clawhub", "publisher/meeting-notes", action="install"
    )
    assert install_preview.allowed_tools_after is None
    assert install_preview.target_version == "1.1.0"
    assert install_preview.content_hash
    installed = service.install(
        "clawhub",
        "publisher/meeting-notes",
        confirmation_token=install_preview.confirmation_token,
    )
    assert installed.source == "market"
    assert installed.editable is False
    stale_update_preview = service.preview_change(
        "clawhub", "publisher/meeting-notes", action="update"
    )
    manager.set_managed_enabled(
        "meeting-notes",
        False,
        expected_revision=manager.revision,
    )
    with __import__("pytest").raises(
        RuntimeError,
        match="revision conflict",
    ):
        service.install(
            "clawhub",
            "publisher/meeting-notes",
            replace_existing=True,
            confirmation_token=stale_update_preview.confirmation_token,
        )
    update_preview = service.preview_change(
        "clawhub", "publisher/meeting-notes", action="update"
    )
    updated = service.install(
        "clawhub",
        "publisher/meeting-notes",
        replace_existing=True,
        confirmation_token=update_preview.confirmation_token,
    )
    assert updated.source == "market"
    assert updated.enabled is False
    assert management.list_history("meeting-notes")[0].action == "update"

    with __import__("pytest").raises(ValueError, match="already used"):
        service.install(
            "clawhub",
            "publisher/meeting-notes",
            replace_existing=True,
            confirmation_token=update_preview.confirmation_token,
        )

    service.uninstall(
        "clawhub",
        "publisher/meeting-notes",
        expected_revision=manager.revision,
    )
    assert manager.list_all() == ()
    deleted_version = management.list_history("meeting-notes")[0]
    restored = service.rollback(
        "clawhub",
        "publisher/meeting-notes",
        deleted_version.history_id,
        expected_revision=manager.revision,
    )
    assert restored.source == "market"
    assert manager.market_origin("meeting-notes") is not None
