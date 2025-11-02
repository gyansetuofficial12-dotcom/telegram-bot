#!/usr/bin/env python3
import logging
import asyncio
import threading
import websockets
import json
import os
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.helpers import escape_markdown
from datetime import datetime, timedelta

# -----------------------------
# CONFIG (you can also switch these to env vars)
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "7803458221:AAFIhgShyY8S1nVfhPn3ct7OID1SXVpxKtk")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "8064043725"))
UPLOAD_KEY = os.getenv("UPLOAD_KEY", "admin000")

# Supabase (from your site)
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://fanufzmbbuupdlvlitvn.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZhbnVmem1iYnV1cGRsdmxpdHZuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTgwODI3MzksImV4cCI6MjA3MzY1ODczOX0.oxEbq-e1O9OENm_oo11Thgs6ebtYNGGGJzA9uJaDjdQ")

# Supabase table we are listening to
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "homework_files")

FAQ_QUESTIONS = {
    "time for homework demand": "You can demand homework at any time.",
    "when homework is uploaded to website or app": "Time: 7:00 to 8:00 PM."
}
WHATSAPP_CHANNEL = os.getenv("WHATSAPP_CHANNEL", "https://whatsapp.com/channel/0029Vb7EwfHGk1FryYMPm33x")

logging.basicConfig(level=logging.INFO)

# -----------------------------
# GLOBAL STATE
# -----------------------------
all_users = set()
user_waiting_for_update = set()
user_warnings = {}
blocked_users = {}            # user_id -> unblock_time
authorized_upload_users = {}  # user_id -> {'state':'awaiting_key'/'authorized'/'awaiting_filename'}
user_unusual_count = {}

# -----------------------------
# HELPERS
# -----------------------------
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Website Link", callback_data="website")],
        [InlineKeyboardButton("📩 Demand Update", callback_data="update")],
        [InlineKeyboardButton("ℹ️ About Gyan Setu", callback_data="about")],
        [InlineKeyboardButton("📚 Homework", callback_data="homework")],
        [InlineKeyboardButton("❓ FAQ", callback_data="faq")]
    ])

def remaining_block_time(unblock_time):
    now = datetime.now()
    remaining = unblock_time - now
    if remaining.total_seconds() <= 0:
        return "0s"
    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"

# -----------------------------
# TELEGRAM HANDLERS (kept from your original bot)
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    all_users.add(user_id)
    text = "👋 Hi, welcome to Gyan Setu! What do you want me to do?"
    await update.message.reply_text(
        escape_markdown(text, version=2),
        reply_markup=main_menu_keyboard(),
        parse_mode="MarkdownV2"
    )

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    authorized_upload_users[user_id] = {'state': 'awaiting_key'}
    await update.message.reply_text("🔑 Send the key to proceed with upload (any user with correct key can upload).")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Only admin can use this command.")
        return
    if update.message.text.startswith("/users"):
        text = "👥 Users:\n"
        keyboard = []
        for uid in all_users:
            rem = remaining_block_time(blocked_users.get(uid, datetime.now())) if uid in blocked_users else "0s"
            text += f"{uid} - Block remaining: {rem}\n"
            buttons = [InlineKeyboardButton("Block", callback_data=f"block_{uid}"),
                       InlineKeyboardButton("Unblock", callback_data=f"unblock_{uid}")]
            keyboard.append(buttons)
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    now = datetime.now()

    # blocked-user check
    if user_id in blocked_users:
        unblock_time = blocked_users[user_id]
        if now >= unblock_time:
            del blocked_users[user_id]
            user_warnings[user_id] = 0
            user_unusual_count[user_id] = 0
            await context.bot.send_message(chat_id=user_id, text="✅ Your 24-hour block expired. You can now use the bot again.")
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"✅ User {user_id} has been auto-unblocked.")
        else:
            rem = remaining_block_time(unblock_time)
            await query.answer(f"⛔ You are blocked. Remaining: {rem}", show_alert=True)
            return

    # Main menu interactions (kept simple)
    if data == "website":
        await query.edit_message_text("🌐 Visit: [www.setugyan.live](https://www.setugyan.live)",
                                      parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main")]]))
    elif data == "update":
        user_waiting_for_update.add(user_id)
        await query.edit_message_text("📩 Type your update request below:",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main")]]))
    elif data == "about":
        await query.edit_message_text("ℹ️ *Gyan Setu* is an educational platform by *Team Hackers*.",
                                      parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main")]]))
    elif data == "homework":
        keyboard = [
            [InlineKeyboardButton("Physics", callback_data="sub_physics")],
            [InlineKeyboardButton("Chemistry", callback_data="sub_chemistry")],
            [InlineKeyboardButton("Maths", callback_data="sub_maths")],
            [InlineKeyboardButton("English", callback_data="sub_english")],
            [InlineKeyboardButton("Biology", callback_data="sub_biology")],
            [InlineKeyboardButton("Physical Education", callback_data="sub_pe")],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main")]
        ]
        await query.edit_message_text("📚 Select a subject:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("sub_"):
        subject = data.split("_")[1]
        keyboard = [
            [InlineKeyboardButton("Notes", callback_data=f"{subject}_notes")],
            [InlineKeyboardButton("Assignment", callback_data=f"{subject}_assignment")],
            [InlineKeyboardButton("Extra Work", callback_data=f"{subject}_extrawork")],
            [InlineKeyboardButton("⬅️ Back to Subjects", callback_data="homework")],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main")]
        ]
        await query.edit_message_text(f"📖 {subject.capitalize()} - Choose an option:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif any(suffix in data for suffix in ["_notes", "_assignment", "_extrawork"]):
        user = query.from_user
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID,
            text=f"📩 New Homework Request\nUser: {user.full_name}\nID: {user.id}\nRequest: {data}\nTime: {datetime.now()}"
        )
        await query.edit_message_text("✅ Your report has been sent.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Subjects", callback_data="homework")],
                                                                        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main")]]))
    elif data == "faq":
        keyboard = [[InlineKeyboardButton(q.capitalize(), callback_data=f"faq_{q}")] for q in FAQ_QUESTIONS]
        keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main")])
        await query.edit_message_text("❓ Select a question:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("faq_"):
        question = data[4:]
        answer = FAQ_QUESTIONS.get(question)
        if answer:
            await query.edit_message_text(
                f"💡 Answer:\n{answer}\n\nFor more info join our WhatsApp channel:\n{WHATSAPP_CHANNEL}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to FAQ", callback_data="faq")],
                                                   [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main")]]),
            )
    elif data == "main":
        await query.edit_message_text("👋 Hi, welcome to Gyan Setu! What do you want me to do?", reply_markup=main_menu_keyboard())

    # Block/unblock from admin
    elif data.startswith("block_") or data.startswith("unblock_"):
        if user_id != ADMIN_CHAT_ID:
            await query.edit_message_text("❌ Only admin can perform this action.")
            return
        action, uid_str = data.split("_")
        uid = int(uid_str)
        if action == "block":
            blocked_users[uid] = datetime.now() + timedelta(hours=24)
            await query.edit_message_text(f"⛔ User {uid} blocked for 24 hours.")
        else:
            blocked_users.pop(uid, None)
            await query.edit_message_text(f"✅ User {uid} unblocked.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    all_users.add(user_id)
    now = datetime.now()
    text_lower = update.message.text.lower() if update.message.text else ""

    # Blocked user check
    if user_id in blocked_users:
        unblock_time = blocked_users[user_id]
        if now >= unblock_time:
            del blocked_users[user_id]
            user_unusual_count[user_id] = 0
            await update.message.reply_text("✅ Your 24-hour block expired. You can now use the bot.")
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"✅ User {user_id} has been auto-unblocked.")
        else:
            rem = remaining_block_time(unblock_time)
            await update.message.reply_text(f"⛔ You are blocked.\nRemaining time: {rem}")
            return

    # Upload broadcast flow (preserve original behavior)
    if user_id in authorized_upload_users:
        state = authorized_upload_users[user_id].get('state')
        # waiting for filename after sending document
        if state == 'awaiting_filename':
            file_id = authorized_upload_users[user_id]['file_id']
            file_name = update.message.text.strip()
            for uid in all_users:
                try:
                    await context.bot.send_document(uid, file_id, filename=file_name)
                except Exception:
                    pass
            await update.message.reply_text(f"✅ Document '{file_name}' sent to all users.")
            authorized_upload_users[user_id]['state'] = 'authorized'
            authorized_upload_users[user_id].pop('file_id', None)
            return
        # waiting for key
        elif state == 'awaiting_key':
            if text_lower == UPLOAD_KEY:
                authorized_upload_users[user_id]['state'] = 'authorized'
                await update.message.reply_text(
                    "✅ Access granted. Send a photo or document to broadcast to all users."
                )
            else:
                await update.message.reply_text("❌ Wrong key. Access denied.")
            return
        # authorized: accept photo/document
        elif state == 'authorized':
            if update.message.photo:
                photo_file_id = update.message.photo[-1].file_id
                for uid in all_users:
                    try:
                        await context.bot.send_photo(uid, photo_file_id)
                    except Exception:
                        pass
                await update.message.reply_text("✅ Photo sent to all users.")
                return
            elif update.message.document:
                authorized_upload_users[user_id]['state'] = 'awaiting_filename'
                authorized_upload_users[user_id]['file_id'] = update.message.document.file_id
                await update.message.reply_text("📄 Document received. Please type the file name to broadcast it to all users.")
                return
            else:
                await update.message.reply_text("❌ Send a valid photo or document.")
                return

    # Start trigger
    if "gyan setu" in text_lower:
        await start(update, context)
        return

    # Update request routing to admin
    if user_id in user_waiting_for_update:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID,
            text=f"📩 Update Request from {update.message.from_user.full_name} (ID: {user_id}): {update.message.text}"
        )
        await update.message.reply_text("✅ Your request has been sent to admin Vishal.", reply_markup=main_menu_keyboard())
        user_waiting_for_update.remove(user_id)
        return

    # Unusual messages handling
    valid_texts = [q.lower() for q in FAQ_QUESTIONS]
    if text_lower not in valid_texts:
        user_unusual_count[user_id] = user_unusual_count.get(user_id, 0) + 1
        count = user_unusual_count[user_id]

        if count == 5:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID,
                text=f"⚠️ User {update.message.from_user.full_name} (ID: {user_id}) sent 5 unusual messages."
            )
            await update.message.reply_text(f"⚠️ Please use the FAQ or buttons. Warning {count}/10.", reply_markup=main_menu_keyboard())
        elif count >= 10:
            blocked_users[user_id] = datetime.now() + timedelta(hours=24)
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID,
                text=f"⛔ User {update.message.from_user.full_name} (ID: {user_id}) blocked for 24 hours (10 unusual messages)."
            )
            await update.message.reply_text(f"⛔ You have been blocked for 24 hours due to repeated unusual messages.")
        else:
            await update.message.reply_text(f"⚠️ Please use the FAQ or buttons. Warning {count}/10.", reply_markup=main_menu_keyboard())

# -----------------------------
# SUPABASE REALTIME LISTENER
# -----------------------------
async def listen_for_supabase_uploads(app):
    """
    Connect to Supabase Realtime websocket and listen for INSERTs on the chosen table.
    When a new row is inserted, send a notification to all known users.
    This function auto-reconnects on errors.
    """
    host = SUPABASE_URL.replace("https://", "").replace("http://", "")
    uri = f"wss://{host}/realtime/v1/websocket?apikey={SUPABASE_KEY}&vsn=1.0.0"

    while True:
        try:
            logging.info("Connecting to Supabase realtime websocket...")
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                # join the specific table channel
                topic = f"realtime:public:{SUPABASE_TABLE}"
                join_msg = {
                    "topic": topic,
                    "event": "phx_join",
                    "payload": {},
                    "ref": 1
                }
                await ws.send(json.dumps(join_msg))
                logging.info("Joined Supabase realtime topic: %s", topic)

                while True:
                    raw = await ws.recv()
                    # Some messages are heartbeat/acks; parse only those that include payload/new/record
                    if '"event":"INSERT"' in raw or '"type":"INSERT"' in raw or '"event":"postgres_changes"' in raw:
                        try:
                            data = json.loads(raw)
                        except Exception:
                            # sometimes raw isn't strict JSON; skip on parse error
                            logging.debug("Non-JSON raw message from Supabase: %s", raw)
                            continue

                        # try to locate the inserted record in common fields
                        payload = data.get("payload") or {}
                        record = payload.get("record") or payload.get("new") or {}
                        # fallback: sometimes nested differently
                        if not record and isinstance(payload, dict):
                            record = payload

                        filename = record.get("name") or record.get("file_name") or record.get("filename") or record.get("file_url") or "Unknown File"

                        # Build the message — user asked to only show website link (no direct file)
                        message = (
                            f"📢 *New File Uploaded!*\\n\\n"
                            f"📄 *{filename}*\\n"
                            f"🔗 View File in Website: https://www.setugyan.live"
                        )

                        # Send the message to all known users (best-effort)
                        for uid in list(all_users):
                            try:
                                await app.bot.send_message(uid, message, parse_mode="Markdown")
                            except Exception as e:
                                logging.warning("Failed to send upload notification to %s: %s", uid, e)

                    # small sleep to avoid busy-loop
                    await asyncio.sleep(0.05)

        except Exception as exc:
            logging.error("Supabase listener error: %s", exc)
            # wait a bit then reconnect
            await asyncio.sleep(5)

# -----------------------------
# HEALTH SERVER (aiohttp)
# -----------------------------
async def health(request):
    return web.Response(text="OK - Gyan Setu Bot is running")

async def start_health_server(port: int = 8080):
    app = web.Application()
    app.add_routes([web.get('/', health)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info("Health server running on port %s", port)
    # keep running until cancelled
    while True:
        await asyncio.sleep(3600)

# -----------------------------
# Run Telegram bot in thread (non-blocking for Railway)
# -----------------------------
def run_bot_in_thread():
    """
    Run Application.run_polling() in a separate thread so the main asyncio loop
    can run the Supabase listener and the health server.
    """
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers (same as earlier)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("users", admin_command))
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Blocking call, so run in its own thread
    def _run():
        logging.info("Starting Telegram bot (polling) in thread...")
        try:
            app.run_polling()
        except Exception as e:
            logging.exception("Telegram polling thread stopped: %s", e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t, app

# -----------------------------
# ENTRY POINT
# -----------------------------
def main():
    # Start telegram bot thread first (so app.bot exists for listener)
    bot_thread, app = run_bot_in_thread()

    # Start the asyncio loop for listener + health server
    loop = asyncio.get_event_loop()
    try:
        # Create tasks for health server and supabase listener
        tasks = [
            listen_for_supabase_uploads(app),
            start_health_server(int(os.getenv("PORT", "8080")))
        ]
        loop.run_until_complete(asyncio.gather(*tasks))
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    except Exception as e:
        logging.exception("Main loop exception: %s", e)
    finally:
        logging.info("Exiting.")

if __name__ == "__main__":
    main()
