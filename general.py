#!/usr/bin/env python3
"""The General – Master Agent Coordinator."""

import sys
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.registry import AgentRegistry
from src.executor import AgentExecutor
from src.creator import AgentCreator
from src.conversation import Conversation

console = Console()


def print_header():
    console.print()
    console.print(Panel.fit(
        "[bold purple]⚔  The General[/bold purple]\n"
        "[dim]Master Agent Coordinator[/dim]\n"
        "[dim]Tippe [bold]exit[/bold] zum Beenden[/dim]",
        border_style="purple",
        padding=(1, 4),
    ))
    console.print()


def on_delta(text: str):
    """Streamed text from The General."""
    console.print(text, end="", markup=False, highlight=False)


def on_tool_header(tc: dict):
    """Called before a tool is executed."""
    tool = tc.get("tool", "")
    console.print()
    if tool == "invoke_agent":
        console.print(Rule(
            f"[yellow]⚙ Agent: {tc.get('agent_id')} → {tc.get('action')}[/yellow]",
            style="yellow"
        ))
    elif tool == "create_agent":
        console.print(Rule(
            f"[cyan]🔧 Erstelle Agent: {tc.get('name')}[/cyan]",
            style="cyan"
        ))
    elif tool == "list_agents":
        console.print(Rule("[dim]📋 Agents auflisten[/dim]", style="dim"))


def on_tool_line(line: str):
    """Streaming output from an invoked agent."""
    console.print(f"  [dim]{line}[/dim]", markup=True, highlight=False)


def main():
    print_header()

    registry = AgentRegistry()
    executor = AgentExecutor(registry)
    creator = AgentCreator(registry)
    conversation = Conversation(registry, executor, creator)

    agent_count = len(registry.get_all())
    console.print(
        f"[dim]  {agent_count} Agent{'s' if agent_count != 1 else ''} registriert. "
        f"Frag mich alles – ich koordiniere den Rest.[/dim]\n"
    )

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]Du[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Auf Wiedersehen![/dim]")
            break

        cmd = user_input.strip().lower()
        if cmd in ("exit", "quit", "bye", "tschüss", "tschuss", "q"):
            console.print("[dim]Auf Wiedersehen![/dim]")
            break
        if not user_input.strip():
            continue

        console.print()
        console.print("[bold purple]The General[/bold purple]  ", end="")

        conversation.chat(
            user_input,
            on_delta=on_delta,
            on_tool_header=on_tool_header,
            on_tool_line=on_tool_line,
        )
        console.print()


if __name__ == "__main__":
    main()
