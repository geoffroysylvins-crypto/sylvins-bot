#!/usr/bin/env python3
"""
Big Marta — Sylvins Bot
Bot Telegram connecté à Claude (claude-sonnet-4-5) pour Geoffroy / Sylvins
"""

import os
import logging
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ── Configuration ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "REMPLACE_PAR_TON_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "REMPLACE_PAR_TA_CLE")

# Optionnel : restreindre l'accès à ton seul Chat ID (recommandé)
ALLOWED_CHAT_IDS = {7562707563}  # ton Chat ID Telegram

SYSTEM_PROMPT = """Tu es Big Marta, l'assistante commerciale intelligente de Geoffroy, agent commercial indépendant spécialisé vins, champagnes et spiritueux sous l'enseigne Sylvins, opérant en région PACA.

Tu l'aides dans :
- La gestion de ses emails clients/vignerons (classification, rédaction de réponses)
- La prise de notes terrain sur ses clients, prospects et vignerons (CRM vocal)
- La gestion des tarifs vignerons et la création de devis
- Tout conseil commercial et logistique

Ton ton est professionnel mais chaleureux, efficace et concis. Tu réponds en français sauf si Geoffroy écrit dans une autre langue. Tu connais son secteur : CHR (cafés, hôtels, restaurants) et cavistes."""

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── État des conversations (mémoire par session) ────────────────────────────────
conversation_history: dict[int, list[dict]] = {}

# ── Client Anthropic ────────────────────────────────────────────────────────────
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Handlers ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Accès non autorisé.")
        return
    conversation_history[chat_id] = []
    await update.message.reply_text(
        "👋 Bonjour Geoffroy ! Je suis **Big Marta**, ton assistante Sylvins.\n\n"
        "Dis-moi ce que tu veux faire — email, note terrain, devis, tarif… je suis là ! 🍷",
        parse_mode="Markdown"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("🔄 Conversation réinitialisée. Nouvelle session démarrée.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Contrôle d'accès
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("⛔ Accès non autorisé.")
        return

    user_text = update.message.text
    logger.info(f"Message de {chat_id}: {user_text[:80]}")

    # Initialiser l'historique si nécessaire
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    # Ajouter le message utilisateur
    conversation_history[chat_id].append({"role": "user", "content": user_text})

    # Limiter l'historique à 20 échanges (40 messages)
    if len(conversation_history[chat_id]) > 40:
        conversation_history[chat_id] = conversation_history[chat_id][-40:]

    # Indicateur de frappe
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=conversation_history[chat_id],
        )

        assistant_reply = response.content[0].text

        # Ajouter la réponse à l'historique
        conversation_history[chat_id].append({"role": "assistant", "content": assistant_reply})

        # Telegram limite à 4096 caractères par message
        if len(assistant_reply) > 4096:
            for i in range(0, len(assistant_reply), 4096):
                await update.message.reply_text(assistant_reply[i:i+4096])
        else:
            await update.message.reply_text(assistant_reply)

    except anthropic.APIError as e:
        logger.error(f"Erreur API Anthropic: {e}")
        await update.message.reply_text(f"❌ Erreur API Claude : {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite.")


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🚀 Big Marta Bot démarré — en attente de messages Telegram...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
