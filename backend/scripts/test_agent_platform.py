"""Smoke test for agent_platform registry and agent loop."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main() -> None:
    from agent_platform.agent.agent_loop import AgentLoop
    from agent_platform.core.registry import skill_registry
    from agent_platform.db_init import init_platform_tables

    init_platform_tables()
    n = skill_registry.reload()
    assert n >= 7, f"expected >=7 skills, got {n}"
    print(f"OK registry: {n} skills")

    loop = AgentLoop(db=None)
    out = await loop.run("平台有哪些 Skill？")
    assert out.get("answer"), "agent should return answer"
    print(f"OK agent: {out['answer'][:120]}...")


if __name__ == "__main__":
    asyncio.run(main())
