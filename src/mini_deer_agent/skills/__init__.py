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
)
from mini_deer_agent.skills.contracts import (
    BuiltInSkill,
    SkillActivationProjection,
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


__all__ = [
    "DEFAULT_BUILTIN_SKILLS_ROOT",
    "BuiltInSkill",
    "BuiltInSkillCatalog",
    "SkillActivationProjection",
    "SkillCatalogError",
    "SkillSummary",
    "ALWAYS_AVAILABLE_SKILL_TOOL_NAMES",
    "SkillToolPolicyDecision",
    "SlashSkillReference",
    "SKILL_ACTIVATION_TOOL_NAME",
    "create_skill_activation_tool",
    "find_automatic_skill_name",
    "parse_slash_skill_reference",
    "project_skill_activation",
    "project_skill_tool_policy",
    "resolve_skill_tool_policy",
    "validate_skill_tool_policies",
]
