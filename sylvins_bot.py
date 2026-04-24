#!/usr/bin/env python3
"""
Big Marta — Sylvins Bot avec intégration Notion
Bot Telegram connecté à Claude + Notion pour Geoffroy / Sylvins
"""

import os
import logging
import httpx
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ── Configuration ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")

ALLOWED_CHAT_IDS = {7562707563}

# ── IDs des bases Notion ────────────────────────────────────────────────────────
NOTION_DBS = {
    "vignerons":     "2643dc87a651813a8ceed8bcd55ef908",
    "clients":       "25f3dc87a651812f918ae6a277bfccdf",
    "log_emails":    "f89fcc2d89264ac08a5944cf3456b754",
    "notes_terrain": "996af890-8ec0-4aaf-bddd-860a0b7acc0a",
    "tarifs":        "90a46dc5190a4f1fabe000d0fa41e2d8",
    "devis":         "4587c0b9c6a64acc9d033b4ddeaf551a",
}

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Clients ────────────────────────────────────────────────────────────────────
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
notion_headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ── Fonctions Notion ────────────────────────────────────────────────────────────

async def notion_query(database_id: str, query: str = "", page_size: int = 10) -> list:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload = {"page_size": page_size}
    if query:
        payload["filter"] = {
            "or": [
                {"property": "Nom", "title": {"contains": query}},
                {"property": "Name", "title": {"contains": query}},
            ]
        }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=notion_headers, json=payload)
        if resp.status_code == 200:
            return resp.json().get("results", [])
        logger.error(f"Notion error: {resp.status_code} {resp.text[:200]}")
        return []

async def notion_create_note(content: str, client_name: str = "", vigneron_name: str = "") -> bool:
    url = "https://api.notion.com/v1/pages"
    title = content[:80] + ("..." if len(content) > 80 else "")
    if client_name:
        title = f"{client_name} — {title}"
    elif vigneron_name:
        title = f"{vigneron_name} — {title}"
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": NOTION_DBS["notes_terrain"]},
        "properties": {
            "Nom": {"title": [{"text": {"content": title}}]},
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}
            }
        ]
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=notion_headers, json=payload)
        return resp.status_code in (200, 201)

def extract_title(page: dict) -> str:
    props = page.get("properties", {})
    for key in ["Nom", "Name", "Titre", "Title"]:
        if key in props:
            arr = props[key].get("title", [])
            if arr:
                return arr[0].get("text", {}).get("content", "")
    return "(sans nom)"

def format_results(results: list, label: str) -> str:
    if not results:
        return f"Aucun résultat dans {label}."
    lines = [f"📋 *{label}* ({len(results)} résultats)\n"]
    for page in results:
        lines.append(f"• {extract_title(page)}")
    return "\n".join(lines)

# ── Outils Claude ───────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "chercher_client",
        "description": "Recherche un client ou prospect dans Notion",
        "input_schema": {
            "type": "object",
            "properties": {"nom": {"type": "string"}},
            "required": ["nom"]
        }
    },
    {
        "name": "chercher_vigneron",
        "description": "Recherche un vigneron ou domaine dans Notion",
        "input_schema": {
            "type": "object",
            "properties": {"nom": {"type": "string"}},
            "required": ["nom"]
        }
    },
    {
        "name": "lister_clients",
        "description": "Liste les clients/prospects dans Notion",
        "input_schema": {
            "type": "object",
            "properties": {"limite": {"type": "integer", "default": 8}}
        }
    },
    {
        "name": "lister_vignerons",
        "description": "Liste les vignerons dans Notion",
        "input_schema": {
            "type": "object",
            "properties": {"limite": {"type": "integer", "default": 8}}
        }
    },
    {
        "name": "ajouter_note_terrain",
        "description": "Ajoute une note terrain dans Notion",
        "input_schema": {
            "type": "object",
            "properties": {
                "contenu": {"type": "string"},
                "client": {"type": "string"},
                "vigneron": {"type": "string"}
            },
            "required": ["contenu"]
        }
    },
    {
        "name": "lister_devis",
        "description": "Liste les devis dans Notion",
        "input_schema": {
            "type": "object",
            "properties": {"limite": {"type": "integer", "default": 5}}
        }
    },
]

async def execute_tool(name: str, inp: dict) -> str:
    try:
        if name == "chercher_client":
            r = await notion_query(NOTION_DBS["clients"], inp.get("nom", ""))
            return format_results(r, "Clients")
        elif name == "chercher_vigneron":
            r = await notion_query(NOTION_DBS["vignerons"], inp.get("nom", ""))
            return format_results(r, "Vignerons")
        elif name == "lister_clients":
            r = await notion_query(NOTION_DBS["clients"], page_size=inp.get("limite", 8))
            return format_results(r, "Clients")
        elif name == "lister_vignerons":
            r = await notion_query(NOTION_DBS["vignerons"], page_size=inp.get("limite", 8))
            return format_results(r, "Vignerons")
        elif name == "ajouter_note_terrain":
            ok = await notion_create_note(inp.get("contenu", ""), inp.get("client", ""), inp.get("vigneron", ""))
            return "✅ Note terrain ajoutée dans Notion." if ok else "❌ Erreur lors de l'ajout."
        elif name == "lister_devis":
            r = await notion_query(NOTION_DBS["devis"], page_size=inp.get("limite", 5))
            return format_results(r, "Devis")
        return f"Outil inconnu : {name}"
    except Exception as e:
        logger.error(f"Erreur outil {name}: {e}")
        return f"Erreur : {str(e)}"

# ── System prompt ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es Big Marta, l'assistante commerciale intelligente de Geoffroy, agent commercial indépendant spécialisé vins, champagnes et spiritueux sous l'enseigne Sylvins, région PACA.

Tu as accès à ses bases Notion via des outils :
- chercher_client / lister_clients : base Clients/Prospects
- chercher_vigneron / lister_vignerons : base Vignerons
- ajouter_note_terrain : sauvegarder une note de visite ou remarque terrain
- lister_devis : base Devis

Utilise toujours les outils Notion pour répondre avec des données réelles quand Geoffroy pose des questions sur ses clients, vignerons ou devis.
Quand il dicte une note terrain, sauvegarde-la immédiatement avec ajouter_note_terrain.

Ton ton est professionnel mais chaleureux, efficace et concis. Tu réponds en français."""

# ── État des conversations ──────────────────────────────────────────────────────
conversation_history: dict[int, list[dict]] = {}

# ── Handlers Telegram ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Accès non autorisé.")
        return
    conversation_history[chat_id] = []
    await update.message.reply_text(
        "👋 Bonjour Geoffroy\\! Je suis *Big Marta*, ton assistante Sylvins\\.\n\n"
        "J'ai accès à tes bases Notion 📋\n\n"
        "Tu peux me demander :\n"
        "• _Cherche le client X_\n"
        "• _Liste mes vignerons_\n"
        "• _Note terrain : visité untel, intéressé par\\.\\.\\._\n"
        "• _Montre mes derniers devis_\n\n"
        "Dis\\-moi ce que tu veux faire \\! 🍷",
        parse_mode="MarkdownV2"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("🔄 Conversation réinitialisée.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Accès non autorisé.")
        return

    user_text = update.message.text
    logger.info(f"Message de {chat_id}: {user_text[:80]}")

    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    conversation_history[chat_id].append({"role": "user", "content": user_text})
    if len(conversation_history[chat_id]) > 40:
        conversation_history[chat_id] = conversation_history[chat_id][-40:]

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        messages = list(conversation_history[chat_id])

        while True:
            response = anthropic_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info(f"Tool: {block.name} {block.input}")
                        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                        result = await execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                messages.append({"role": "user", "content": tool_results})
            else:
                final_text = "".join(b.text for b in response.content if hasattr(b, "text"))
                conversation_history[chat_id].append({"role": "assistant", "content": final_text})
                if len(final_text) > 4096:
                    for i in range(0, len(final_text), 4096):
                        await update.message.reply_text(final_text[i:i+4096])
                else:
                    await update.message.reply_text(final_text)
                break

    except anthropic.APIError as e:
        logger.error(f"Erreur API Anthropic: {e}")
        await update.message.reply_text(f"❌ Erreur API Claude : {str(e)}")
    except Exception as e:
        logger.error(f"Erreur: {e}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite.")

# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 Big Marta Bot (Notion) démarré...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
