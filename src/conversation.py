"""Konversations-Engine: Verarbeitet Nachrichten, streamt Claude, führt Tools aus."""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

# Memory-Modul aus buch-agent laden (liegt eine Ebene höher)
_BUCH_AGENT_SRC = Path(__file__).parent.parent.parent / "buch-agent" / "src"
if str(_BUCH_AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(_BUCH_AGENT_SRC))

TOOL_CALL_RE = re.compile(r"<TOOL_CALL>\s*(.*?)\s*</TOOL_CALL>", re.DOTALL)

SYSTEM_PROMPT = """\
Du bist "The General" – Isabelles persönlicher Master-Agent-Koordinator.
Du sprichst IMMER auf Deutsch, bist präzise, freundlich und direkt.

## Deine Fähigkeiten
1. Mit Isabelle auf Deutsch chatten und ihre Anfragen verstehen
2. Aufgaben an die passenden Agents delegieren
3. Neue Agents erstellen wenn Isabelle das wünscht
4. Ergebnisse der Agents präsentieren und koordinieren
5. Gedächtnis lesen und nutzen um personalisierte Empfehlungen zu geben

## Verfügbare Agents
{agents_description}

{memory_context}

## Tools – so rufst du sie auf

### Agent aufrufen:
<TOOL_CALL>
{{"tool": "invoke_agent", "agent_id": "<id>", "action": "<action>", "file": "<absoluter_pfad_oder_null>", "save_to_notion": false}}
</TOOL_CALL>

### Neuen Agent erstellen:
<TOOL_CALL>
{{"tool": "create_agent", "agent_id": "<kebab-case-id>", "name": "<Name>", "description": "<Beschreibung>", "icon": "<emoji>", "actions": [{{"id": "<id>", "description": "<Beschreibung>"}}], "system_prompts": {{"<action_id>": "<ausführlicher Anweisungstext>"}}}}
</TOOL_CALL>

### Alle Agents auflisten:
<TOOL_CALL>
{{"tool": "list_agents"}}
</TOOL_CALL>

### Gedächtnis-Eintrag speichern:
<TOOL_CALL>
{{"tool": "save_memory", "category": "<stil|projekte|muster|feedback|agents|laufend>", "entry": "<kurzer präziser Eintrag auf Deutsch>"}}
</TOOL_CALL>

## Regeln
- Antworte IMMER auf Deutsch
- Nutze das Gedächtnis aktiv: erwähne relevante frühere Infos wenn passend
- Erkläre kurz was du tust, bevor du ein Tool aufrufst
- Wenn du einen Dateipfad brauchst und keiner angegeben wurde: frage nach
- Das JSON in TOOL_CALL muss valide sein
- Nach einem Tool-Aufruf bekommst du das Ergebnis und fasst es für Isabelle zusammen
- Speichere wichtige neue Informationen über Isabelles Projekte und Präferenzen im Gedächtnis
"""


class Conversation:
    def __init__(self, registry, executor, creator):
        self.registry = registry
        self.executor = executor
        self.creator = creator
        self.history: list = []

    # ─── Memory ───────────────────────────────────────────────────────────────

    def _get_memory(self):
        try:
            from memory import get_general_memory
            return get_general_memory()
        except Exception:
            return None

    # ─── System Prompt ────────────────────────────────────────────────────────

    def _system_prompt(self) -> str:
        memory = self._get_memory()
        mem_ctx = memory.als_prompt() if memory else ""
        return SYSTEM_PROMPT.format(
            agents_description=self.registry.agents_description(),
            memory_context=mem_ctx,
        )

    # ─── Prompt Building ──────────────────────────────────────────────────────

    def _build_prompt(self, user_message: str) -> str:
        parts = []
        if self.history:
            parts.append("<gespraechsverlauf>")
            for turn in self.history:
                tag = "benutzer" if turn["role"] == "user" else "general"
                parts.append(f"<{tag}>{turn['content']}</{tag}>")
            parts.append("</gespraechsverlauf>")
            parts.append("")
        parts.append(f"<neue_nachricht>{user_message}</neue_nachricht>")
        return "\n".join(parts)

    # ─── Claude CLI ───────────────────────────────────────────────────────────

    def _call_claude(self, prompt: str, on_delta: Callable) -> str:
        cmd = [
            "claude",
            "--print", "--verbose",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--allowed-tools", "",
            "--append-system-prompt", self._system_prompt(),
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        proc.stdin.write(prompt)
        proc.stdin.close()

        full_text = []
        last_text = ""
        display_buf = ""
        in_tool_call = False

        def flush_display(text: str):
            """Stream text to display, suppressing TOOL_CALL blocks."""
            nonlocal display_buf, in_tool_call
            display_buf += text
            while True:
                if in_tool_call:
                    end = display_buf.find("</TOOL_CALL>")
                    if end >= 0:
                        in_tool_call = False
                        display_buf = display_buf[end + len("</TOOL_CALL>"):]
                    else:
                        display_buf = ""
                        break
                else:
                    start = display_buf.find("<TOOL_CALL>")
                    if start >= 0:
                        if start > 0:
                            on_delta(display_buf[:start])
                        in_tool_call = True
                        display_buf = display_buf[start + len("<TOOL_CALL>"):]
                    else:
                        safe = max(0, len(display_buf) - len("<TOOL_CALL>"))
                        if safe > 0:
                            on_delta(display_buf[:safe])
                            display_buf = display_buf[safe:]
                        break

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        new_text = block.get("text", "")
                        if new_text.startswith(last_text):
                            delta = new_text[len(last_text):]
                            if delta:
                                full_text.append(delta)
                                flush_display(delta)
                            last_text = new_text
                        else:
                            full_text.append(new_text)
                            flush_display(new_text)
                            last_text = new_text

            elif event.get("type") == "result":
                result = event.get("result", "")
                if event.get("is_error"):
                    raise RuntimeError(f"Claude Fehler: {result}")
                if not full_text and result:
                    full_text.append(result)
                    flush_display(result)

        # Flush remaining display buffer
        if display_buf and not in_tool_call:
            on_delta(display_buf)

        proc.wait()
        return "".join(full_text)

    # ─── Tool Execution ───────────────────────────────────────────────────────

    def _execute_tool(self, tc: dict, on_tool_line: Callable) -> str:
        tool = tc.get("tool")

        if tool == "invoke_agent":
            agent_id = tc.get("agent_id", "")
            action = tc.get("action", "")
            file = tc.get("file") or None
            save_notion = tc.get("save_to_notion", False)
            result = self.executor.invoke(
                agent_id, action, file, save_notion,
                on_line=on_tool_line,
            )
            # Trim output for context window
            out = result.get("output", "")
            if len(out) > 4000:
                out = out[:4000] + "\n...[gekürzt]"
            result["output"] = out
            return json.dumps(result, ensure_ascii=False)

        elif tool == "create_agent":
            result = self.creator.create(tc)
            # Memory: neuen Agent vermerken
            try:
                memory = self._get_memory()
                if memory and result.get("success"):
                    memory.schreibe("agents",
                        f"Agent '{result.get('agent_id')}' erstellt: {tc.get('description', '')}"
                    )
            except Exception:
                pass
            return json.dumps(result, ensure_ascii=False)

        elif tool == "list_agents":
            return json.dumps({"agents": self.registry.get_all()}, ensure_ascii=False)

        elif tool == "save_memory":
            # Expliziter Memory-Eintrag aus dem Chat
            cat   = tc.get("category", "muster")
            entry = tc.get("entry", "")
            try:
                memory = self._get_memory()
                if memory and entry:
                    memory.schreibe(cat, entry)
                    return json.dumps({"success": True, "saved": entry})
            except Exception as e:
                return json.dumps({"error": str(e)})
            return json.dumps({"success": False, "error": "Memory nicht verfügbar"})

        else:
            return json.dumps({"error": f"Unbekanntes Tool: {tool}"})

    # ─── Main Chat Loop ───────────────────────────────────────────────────────

    def chat(
        self,
        user_message: str,
        on_delta: Callable,
        on_tool_header: Callable,
        on_tool_line: Callable,
    ):
        """Verarbeitet eine Benutzernachricht (mit bis zu 3 Tool-Runden)."""
        current_user_msg = user_message
        prompt = self._build_prompt(user_message)

        for iteration in range(3):
            response = self._call_claude(prompt, on_delta)

            tool_calls_raw = TOOL_CALL_RE.findall(response)
            if not tool_calls_raw:
                # No tools – add to history and done
                self._add_history(user_message if iteration == 0 else current_user_msg,
                                  response)
                return

            # Execute tools
            tool_results_parts = []
            for tc_str in tool_calls_raw:
                try:
                    tc = json.loads(tc_str)
                except json.JSONDecodeError as e:
                    tool_results_parts.append(
                        f'<TOOL_RESULT>{{"error": "Ungültiges JSON: {e}"}}</TOOL_RESULT>'
                    )
                    continue
                on_tool_header(tc)
                result_str = self._execute_tool(tc, on_tool_line)
                tool_results_parts.append(
                    f"<TOOL_RESULT>\n{result_str}\n</TOOL_RESULT>"
                )

            # Add this exchange to history (with results)
            clean = TOOL_CALL_RE.sub("", response).strip()
            combined_assistant = (clean + "\n\n" + "\n".join(tool_results_parts)).strip()
            self._add_history(
                user_message if iteration == 0 else current_user_msg,
                combined_assistant,
            )

            # Ask Claude to summarize the results for the user
            follow_up = (
                "Hier sind die Ergebnisse der Tool-Aufrufe:\n\n"
                + "\n".join(tool_results_parts)
                + "\n\nFasse das Ergebnis kurz auf Deutsch für Isabelle zusammen."
            )
            current_user_msg = follow_up
            prompt = self._build_prompt(follow_up)

        # Final answer after tool loop
        on_delta("\n")

    # ─── History ──────────────────────────────────────────────────────────────

    def _add_history(self, user: str, assistant: str):
        self.history.append({"role": "user", "content": user})
        self.history.append({"role": "assistant", "content": assistant})
        # Keep context manageable
        if len(self.history) > 30:
            self.history = self.history[-30:]
