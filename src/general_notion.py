"""Notion-Integration für The General: Aktivitäten, Übersicht, Koordination."""

import os
from datetime import datetime
from typing import Optional

# ─── Seiten-IDs (gecacht) ────────────────────────────────────────────────────

_subpage_ids: dict = {}


# ─── Notion-Client ────────────────────────────────────────────────────────────

def _client():
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        return None
    try:
        from notion_client import Client
        return Client(auth=token)
    except ImportError:
        return None


def _general_page_id() -> Optional[str]:
    return os.environ.get("NOTION_GENERAL_PAGE_ID", "").strip() or None


# ─── Unterseiten finden / erstellen ──────────────────────────────────────────

_SUBPAGES = {
    "aktivitaeten": ("📋", "📋 Aktivitäten"),
    "uebersicht":   ("📊", "📊 Übersicht"),
    "koordination": ("🗂", "🗂 Koordination"),
}


def _get_subpage(key: str) -> Optional[str]:
    if key in _subpage_ids:
        return _subpage_ids[key]

    client = _client()
    parent = _general_page_id()
    if not client or not parent:
        return None

    emoji, titel = _SUBPAGES[key]
    try:
        resp = client.blocks.children.list(block_id=parent)
        for b in resp.get("results", []):
            if b.get("type") == "child_page":
                t = b.get("child_page", {}).get("title", "")
                if key in t.lower() or titel.split()[-1] in t:
                    _subpage_ids[key] = b["id"]
                    return b["id"]

        page = client.pages.create(
            parent={"page_id": parent},
            icon={"type": "emoji", "emoji": emoji},
            properties={"title": {"title": [
                {"type": "text", "text": {"content": titel}}
            ]}},
        )
        _subpage_ids[key] = page["id"]
        return page["id"]
    except Exception:
        return None


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _text_block(text: str) -> dict:
    return {"type": "paragraph", "paragraph": {"rich_text": [
        {"type": "text", "text": {"content": text[:1900]}}
    ]}}


def _h2_block(text: str) -> dict:
    return {"type": "heading_2", "heading_2": {"rich_text": [
        {"type": "text", "text": {"content": text[:500]}}
    ]}}


def _bullet(text: str) -> dict:
    return {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
        {"type": "text", "text": {"content": text[:1900]}}
    ]}}


def _divider() -> dict:
    return {"type": "divider", "divider": {}}


# ─── Aktivitäten ─────────────────────────────────────────────────────────────

def log_aktivitaet(
    user_message: str,
    tool_calls: list,
    response_summary: str,
):
    """
    Erstellt einen neuen Eintrag auf der Aktivitäten-Seite.
    Wird nach jedem abgeschlossenen Gesprächs-Turn aufgerufen.
    """
    client = _client()
    pid = _get_subpage("aktivitaeten")
    if not client or not pid:
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    bloecke = [
        _h2_block(f"{ts}"),
        _bullet(f"👤 Anfrage: {user_message[:300]}"),
    ]

    for tc in tool_calls:
        tool = tc.get("tool", "")
        if tool == "invoke_agent":
            bloecke.append(_bullet(
                f"⚙ Delegiert an: {tc.get('agent_id', '')} → {tc.get('action', '')}"
            ))
        elif tool == "create_agent":
            bloecke.append(_bullet(f"🔧 Agent erstellt: {tc.get('name', '')} ({tc.get('agent_id', '')})"))
        elif tool == "list_agents":
            bloecke.append(_bullet("📋 Agents aufgelistet"))
        elif tool == "save_memory":
            bloecke.append(_bullet(f"🧠 Memory: [{tc.get('category', '')}] {tc.get('entry', '')[:100]}"))

    if response_summary:
        summary = response_summary[:500]
        bloecke.append(_text_block(f"💬 Antwort: {summary}"))

    bloecke.append(_divider())

    try:
        client.blocks.children.append(block_id=pid, children=bloecke)
    except Exception:
        pass


# ─── Koordination (Delegations-Log) ──────────────────────────────────────────

def log_delegation(
    agent_id: str,
    action: str,
    file: Optional[str],
    success: bool,
    result_snippet: str = "",
):
    """Loggt einen Delegations-Aufruf auf der Koordinations-Seite."""
    client = _client()
    pid = _get_subpage("koordination")
    if not client or not pid:
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    status = "✅" if success else "❌"
    datei = f" | Datei: {file}" if file else ""
    bloecke = [
        _bullet(f"{status} [{ts}] {agent_id} → {action}{datei}"),
    ]
    if result_snippet:
        bloecke.append(_text_block(f"   → {result_snippet[:300]}"))

    try:
        client.blocks.children.append(block_id=pid, children=bloecke)
    except Exception:
        pass


# ─── Übersicht aktualisieren ──────────────────────────────────────────────────

def aktualisiere_uebersicht(agents: list):
    """
    Aktualisiert die Übersichts-Seite mit der aktuellen Agentenliste.
    Wird nach list_agents und create_agent aufgerufen.
    """
    client = _client()
    pid = _get_subpage("uebersicht")
    if not client or not pid:
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Bestehenden Inhalt löschen
    try:
        resp = client.blocks.children.list(block_id=pid)
        for b in resp.get("results", []):
            try:
                client.blocks.delete(block_id=b["id"])
            except Exception:
                pass
    except Exception:
        pass

    bloecke = [
        _h2_block(f"Stand: {ts}"),
        _h2_block(f"Agents ({len(agents)})"),
    ]

    if agents:
        for a in agents:
            name = a.get("name", a.get("id", "?"))
            desc = a.get("description", "")
            icon = a.get("icon", "🤖")
            aktionen = ", ".join(
                act.get("id", "") for act in a.get("actions", [])
            )
            line = f"{icon} {name} — {desc}"
            if aktionen:
                line += f" | Aktionen: {aktionen}"
            bloecke.append(_bullet(line))
    else:
        bloecke.append(_text_block("Noch keine Agents registriert."))

    try:
        client.blocks.children.append(block_id=pid, children=bloecke)
    except Exception:
        pass
