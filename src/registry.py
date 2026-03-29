"""Agent-Registry: lädt und verwaltet bekannte Agents."""

import json
from pathlib import Path

AGENTS_DIR = Path(__file__).parent.parent / "agents"


class AgentRegistry:
    def __init__(self):
        AGENTS_DIR.mkdir(exist_ok=True)

    def get_all(self) -> list:
        agents = []
        for f in sorted(AGENTS_DIR.glob("*.json")):
            try:
                agents.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        return agents

    def get(self, agent_id: str) -> dict:
        f = AGENTS_DIR / f"{agent_id}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        return None

    def register(self, agent: dict):
        f = AGENTS_DIR / f"{agent['id']}.json"
        f.write_text(json.dumps(agent, ensure_ascii=False, indent=2), encoding="utf-8")

    def agents_description(self) -> str:
        agents = self.get_all()
        if not agents:
            return "Noch keine Agents registriert."
        lines = []
        for a in agents:
            lines.append(f"- **{a['name']}** (ID: `{a['id']}`): {a['description']}")
            for action in a.get("actions", []):
                lines.append(f"  - Aktion `{action['id']}`: {action['description']}")
        return "\n".join(lines)
