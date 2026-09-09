"""公开内置技能发现、显式激活与受控自主激活入口。"""

from mini_deer_agent.skills.automatic import (
    SKILL_ACTIVATION_TOOL_NAME,
    create_skill_activation_tool,
    find_automatic_skill_name,
)

from mini_deer_agent.skills.activation import (
    parse_slash_skill_reference,
    project_skill_activation,
)
from mini_deer_agent.skills.catalog import (
    DEFAULT_BUILTIN_SKILLS_ROOT,
    BuiltInSkillCatalog,
    SkillCatalogError,
    load_skill_package,
)
from mini_deer_agent.skills.contracts import (
    BuiltInSkill,
    SkillActivationProjection,
    SkillResource,
    SkillSummary,
    SlashSkillReference,
)
from mini_deer_agent.skills.tool_policy import (
    ALWAYS_AVAILABLE_SKILL_TOOL_NAMES,
    SkillToolPolicyDecision,
    project_skill_tool_policy,
    resolve_skill_tool_policy,
    validate_skill_tool_policies,
)
from mini_deer_agent.skills.user import (
    ManagedSkillRecord,
    SkillState,
    UserSkillManager,
    UserSkillRecord,
)
from mini_deer_agent.skills.management import (
    SkillArchiveInspection,
    SkillCheckResult,
    SkillDetailRecord,
    SkillDraftPayload,
    SkillDraftRecord,
    SkillHistoryRecord,
    SkillInstallAuthorization,
    SkillAgentSettings,
    RecoverableSkillRecord,
    SkillManagementService,
)
from mini_deer_agent.skills.manage_tool import create_skill_manage_tool
from mini_deer_agent.skills.market_tool import create_skill_market_search_tool


__all__ = [
    "DEFAULT_BUILTIN_SKILLS_ROOT",
    "BuiltInSkill",
    "BuiltInSkillCatalog",
    "SkillActivationProjection",
    "SkillCatalogError",
    "SkillResource",
    "SkillSummary",
    "ALWAYS_AVAILABLE_SKILL_TOOL_NAMES",
    "SkillToolPolicyDecision",
    "SlashSkillReference",
    "SKILL_ACTIVATION_TOOL_NAME",
    "create_skill_activation_tool",
    "find_automatic_skill_name",
    "load_skill_package",
    "parse_slash_skill_reference",
    "project_skill_activation",
    "project_skill_tool_policy",
    "resolve_skill_tool_policy",
    "validate_skill_tool_policies",
    "UserSkillManager",
    "UserSkillRecord",
    "ManagedSkillRecord",
    "SkillCheckResult",
    "SkillArchiveInspection",
    "SkillDetailRecord",
    "SkillDraftPayload",
    "SkillDraftRecord",
    "SkillHistoryRecord",
    "SkillInstallAuthorization",
    "SkillAgentSettings",
    "RecoverableSkillRecord",
    "SkillManagementService",
    "SkillState",
    "create_skill_manage_tool",
    "create_skill_market_search_tool",
]
