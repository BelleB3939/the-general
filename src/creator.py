"""Erstellt neue Agents aus einer Spezifikation."""

import json
import textwrap
from pathlib import Path

GENERAL_DIR = Path(__file__).parent.parent
ROOT_DIR = GENERAL_DIR.parent

AGENT_PY_TEMPLATE = '''\
"""CLI-Agent: {name}"""

import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(ROOT_DIR := Path(__file__).parent.parent / ".env")

from src.claude_handler import analysiere

console = Console()

AUFGABEN = {action_ids}

@click.group()
def cli():
    """{name} – {description}"""

{commands}

def _analysiere(aufgabe: str, text: str, dateiname: str) -> str:
    result_text = []

    def on_text(delta: str):
        console.print(delta, end="", markup=False)
        result_text.append(delta)

    console.print()
    analysiere(aufgabe, text, dateiname, on_text)
    console.print()
    return "".join(result_text)

if __name__ == "__main__":
    cli()
'''

HANDLER_TEMPLATE = '''\
"""Claude-Handler für {name}."""

import json
import subprocess


SYSTEM_PROMPTS = {system_prompts}


def _run(system_prompt: str, document_text: str, dateiname: str, on_text) -> str:
    prompt = f"Datei: **{{dateiname}}**\\n\\n---\\n\\n{{document_text}}"
    cmd = [
        "claude", "--print", "--verbose",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--allowed-tools", "",
        "--append-system-prompt", system_prompt,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8")
    proc.stdin.write(prompt)
    proc.stdin.close()

    full_text = []
    last_text = ""
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {{}}).get("content", []):
                if block.get("type") == "text":
                    new_text = block.get("text", "")
                    if new_text.startswith(last_text):
                        delta = new_text[len(last_text):]
                        if delta:
                            on_text(delta)
                            full_text.append(delta)
                        last_text = new_text
                    else:
                        on_text(new_text)
                        full_text.append(new_text)
                        last_text = new_text
        elif event.get("type") == "result":
            result = event.get("result", "")
            if event.get("is_error"):
                raise RuntimeError(f"Claude Fehler: {{result}}")
            if not full_text and result:
                on_text(result)
                full_text.append(result)
    proc.wait()
    return "".join(full_text)


def analysiere(aufgabe: str, document_text: str, dateiname: str,
               on_text=lambda t: None) -> str:
    prompt = SYSTEM_PROMPTS.get(aufgabe, SYSTEM_PROMPTS.get("default", ""))
    return _run(prompt, document_text, dateiname, on_text)
'''

REQUIREMENTS_TEMPLATE = """\
python-dotenv>=1.0.0
rich>=13.7.0
click>=8.1.7
"""


class AgentCreator:
    def __init__(self, registry):
        self.registry = registry

    def create(self, spec: dict) -> dict:
        agent_id = spec.get("agent_id", "").strip()
        name = spec.get("name", "").strip()
        description = spec.get("description", "").strip()
        actions = spec.get("actions", [{"id": "analysiere", "description": "Analyse durchführen"}])
        system_prompts = spec.get("system_prompts", {})

        # If only one system_prompt given, use it as default
        if not system_prompts and spec.get("system_prompt"):
            system_prompts = {a["id"]: spec["system_prompt"] for a in actions}
            system_prompts["default"] = spec["system_prompt"]

        if not agent_id or not name:
            return {"success": False, "error": "agent_id und name sind Pflichtfelder."}

        agent_dir = ROOT_DIR / agent_id
        if agent_dir.exists():
            return {"success": False, "error": f"Verzeichnis '{agent_dir}' existiert bereits."}

        agent_dir.mkdir(parents=True)
        (agent_dir / "src").mkdir()
        (agent_dir / "src" / "__init__.py").write_text("")

        # Write claude_handler.py
        handler_code = HANDLER_TEMPLATE.format(
            name=name,
            system_prompts=json.dumps(system_prompts, ensure_ascii=False, indent=4),
        )
        (agent_dir / "src" / "claude_handler.py").write_text(handler_code, encoding="utf-8")

        # Write agent.py
        action_ids = repr([a["id"] for a in actions])
        commands = "\n\n".join(self._make_command(a) for a in actions)
        agent_code = AGENT_PY_TEMPLATE.format(
            name=name,
            description=description,
            action_ids=action_ids,
            commands=commands,
        )
        (agent_dir / "agent.py").write_text(agent_code, encoding="utf-8")

        # Write requirements.txt
        (agent_dir / "requirements.txt").write_text(REQUIREMENTS_TEMPLATE)

        # Write .env.example
        (agent_dir / ".env.example").write_text(
            "# Umgebungsvariablen (in ../.env oder hier)\n"
        )

        # Register agent
        agent_entry = {
            "id": agent_id,
            "name": name,
            "description": description,
            "icon": spec.get("icon", "🤖"),
            "path": f"../{agent_id}",
            "entry_point": "agent.py",
            "accepts": spec.get("accepts", [".txt", ".md", ".pdf", ".docx"]),
            "actions": actions,
            "requires_file": spec.get("requires_file", True),
        }
        self.registry.register(agent_entry)

        return {
            "success": True,
            "agent_id": agent_id,
            "path": str(agent_dir),
            "message": f"Agent '{name}' erfolgreich erstellt unter {agent_dir}",
        }

    def _make_command(self, action: dict) -> str:
        aid = action["id"]
        desc = action.get("description", "")
        return textwrap.dedent(f"""\
            @cli.command()
            @click.argument("datei", type=click.Path(exists=True))
            @click.option("--no-notion", is_flag=True, help="Nicht in Notion speichern")
            def {aid}(datei, no_notion):
                \"\"\"{desc}\"\"\"
                from src.document_reader import read_document
                text, dateiname = read_document(datei)
                _analysiere("{aid}", text, dateiname)
        """)
