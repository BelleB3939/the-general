"""Führt registrierte Agents als Subprocess aus."""

import subprocess
from pathlib import Path
from typing import Callable

GENERAL_DIR = Path(__file__).parent.parent
ROOT_DIR = GENERAL_DIR.parent


class AgentExecutor:
    def __init__(self, registry):
        self.registry = registry

    def _resolve_path(self, agent: dict) -> Path:
        raw = agent.get("path", agent["id"])
        p = Path(raw)
        if not p.is_absolute():
            p = (GENERAL_DIR / p).resolve()
        return p

    def invoke(
        self,
        agent_id: str,
        action: str,
        file: str = None,
        save_to_notion: bool = False,
        on_line: Callable = None,
    ) -> dict:
        agent = self.registry.get(agent_id)
        if not agent:
            return {"success": False, "error": f"Agent '{agent_id}' nicht gefunden."}

        agent_dir = self._resolve_path(agent)
        script = agent_dir / agent.get("entry_point", "agent.py")

        if not script.exists():
            return {"success": False, "error": f"Skript nicht gefunden: {script}"}

        cmd = ["python3", str(script), action]
        if file:
            cmd.append(file)
        if not save_to_notion:
            cmd.append("--no-notion")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                cwd=str(agent_dir),
            )
            output_lines = []
            for line in proc.stdout:
                output_lines.append(line)
                if on_line:
                    on_line(line.rstrip())
            proc.wait()

            output = "".join(output_lines)
            if proc.returncode != 0:
                return {"success": False, "output": output,
                        "error": f"Exit-Code {proc.returncode}"}
            return {"success": True, "output": output}

        except Exception as e:
            return {"success": False, "error": str(e)}
