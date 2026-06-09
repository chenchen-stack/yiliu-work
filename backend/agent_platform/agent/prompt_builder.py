"""Build Agent system prompt with available Skill catalog."""

from __future__ import annotations

from agent_platform.core.registry import skill_registry
from agent_platform.models.skill import SkillMeta


def build_system_prompt(*, extra_instructions: str = "") -> str:
    """Inject Skill list from Registry into Agent system prompt."""
    lines = [
        "你是企业级智能体平台的对话助手。你不直接拥有业务能力，只能通过调用 Skill（工具）完成任务。",
        "遵循 ReAct：先思考 (Thought)，再行动 (Action)，观察结果 (Observation)，循环直至可回答用户。",
        "可用 Skill 列表：",
    ]
    for meta in skill_registry.list_all():
        lines.append(_format_skill_line(meta))
    lines.append(
        "额外工具：query_trace(trace_id|diff_id) — 查询执行链路与差异详情。"
    )
    lines.append(
        "规则：用户询问平台能力/有哪些 Skill 时，直接概括列表，不要检索知识库。"
        "只有明确要查案例、制度、历史经验时才使用知识型 Skill 或 RAG。"
    )
    lines.append(
        "禁止输出 Markdown 表格（不要使用 | 列 | 表 | 或 --- 分隔线）。"
        "能力/Skill 清单由前端卡片展示，你只需 1–2 句导语，勿逐条罗列表格。"
    )
    if extra_instructions:
        lines.append(extra_instructions)
    return "\n".join(lines)


def _format_skill_line(meta: SkillMeta) -> str:
    inputs = ", ".join(meta.input_schema.keys()) if meta.input_schema else "见 skill.md"
    return (
        f"- [{meta.package_code}] {meta.name}（{meta.type_label}）"
        f" id={meta.skill_id} 分类={meta.category} 输入≈{inputs}"
    )
