import logging
import asyncio
import websockets
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.helpers import escape_markdown
from datetime import datetime, timedelta

# -----------------------------
# CONFIG
# -----------------------------
BOT_TOKEN = "7803458221:AAFIhgShyY8S1nVfhPn3ct7OID1SXVpxKtk"
ADMIN_CHAT_ID = 8064043725
UPLOAD_KEY = "admin000"

# Supabase config (confirmed from your site)
SUPABASE_URL = "https://fanufzmbbuupdlvlitvn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZhbnVmem1iYnV1cGRsdmxpdHZuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTgwODI3MzksImV4cCI6MjA3MzY1ODczOX0.oxEbq-e1O9OENm_oo11Thgs6ebtYNGGGJzA9uJaDjdQ"

FAQ_QUESTIONS = {
    "time for homework demand": "You can demand homework at any time.",
    "when homework is uploaded to website or app": "Time: 7:00 to 8:00 PM."
}
WHATSAPP_CHANNEL = "https://whatsapp.com/channel/0029Vb7EwfHGk1FryYMPm33x"
MAX_QUESTIONS = 10

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
# START
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

# -----------------------------
# UPLOAD COMMAND (any user)
# -----------------------------
async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    authorized_upload_users[user_id] = {'state': 'awaiting_key'}
    await update.message.reply_text("🔑 Send the key to proceed with upload (any user with correct key can upload).")

# -----------------------------
# ADMIN COMMANDS
# -----------------------------
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

# -----------------------------
# BUTTON HANDLER
# -----------------------------
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    now = datetime.now()

    # ---------------------------
    # Blocked user check
    # ---------------------------
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

    # --- Main Menu ---
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

    # --- Admin Block/Unblock ---
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

# -----------------------------
# MESSAGE HANDLER
# -----------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    all_users.add(user_id)
    now = datetime.now()
    text_lower = update.message.text.lower() if update.message.text else ""

    # ---------------------------
    # Blocked user check
    # ---------------------------
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

    # ---------------------------
    # Upload filename handling
    # ---------------------------
    if user_id in authorized_upload_users:
        state = authorized_upload_users[user_id].get('state')
        # Waiting for filename
        if state == 'awaiting_filename':
            file_id = authorized_upload_users[user_id]['file_id']
            file_name = update.message.text.strip()
            for uid in all_users:
                try:
                    await context.bot.send_document(uid, file_id, filename=file_name)
                except:
                    pass
            await update.message.reply_text(f"✅ Document '{file_name}' sent to all users.")
            authorized_upload_users[user_id]['state'] = 'authorized'
            authorized_upload_users[user_id].pop('file_id', None)
            return
        # Waiting for key
        elif state == 'awaiting_key':
            if text_lower == UPLOAD_KEY:
                authorized_upload_users[user_id]['state'] = 'authorized'
                await update.message.reply_text(
                    "✅ Access granted. Send a photo or document to broadcast to all users."
                )
            else:
                await update.message.reply_text("❌ Wrong key. Access denied.")
            return
        # Authorized
        elif state == 'authorized':
            if update.message.photo:
                photo_file_id = update.message.photo[-1].file_id
                for uid in all_users:
                    try:
                        await context.bot.send_photo(uid, photo_file_id)
                    except:
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

    # Update request
    if user_id in user_waiting_for_update:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID,
            text=f"📩 Update Request from {update.message.from_user.full_name} (ID: {user_id}): {update.message.text}"
        )
        await update.message.reply_text("✅ Your request has been sent to admin Vishal.", reply_markup=main_menu_keyboard())
        user_waiting_for_update.remove(user_id)
        return

    # Unusual message handling
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
    uri = f"wss://{SUPABASE_URL.replace('https://', '')}/realtime/v1/websocket?apikey={SUPABASE_KEY}&vsn=1.0.0"
    try:
        async with websockets.connect(uri) as ws:
            # Join the channel for the homework_files table
            await ws.send(json.dumps({
                "topic": "realtime:public:homework_files",
                "event": "phx_join",
                "payload": {},
                "ref": 1
            }))
            logging.info("👂 Listening for new uploads in Supabase (homework_files)...")
            while True:
                msg = await ws.recv()
                # Supabase realtime messages are JSON strings; check for INSERT events
                if '"event":"INSERT"' in msg or '"type":"INSERT"' in msg:
                    try:
                        data = json.loads(msg)
                        # payload structure may vary; try to extract record safely
                        payload = data.get("payload") or {}
                        record = payload.get("record") or payload.get("new") or {}
                        # index.html inserts record with field 'name'
                        filename = record.get("name") or record.get("file_name") or record.get("filename") or "Unknown File"
                        # Build notification message
                        message = (
                            f"📢 *New File Uploaded!*\\n\\n"
                            f"📄 *{filename}*\\n"
                            f"🔗 View File in Website: https://www.setugyan.live"
                        )
                        # Send to all known users (best-effort)
                        for uid in list(all_users):
                            try:
                                await app.bot.send_message(uid, message, parse_mode="Markdown")
                            except Exception as e:
                                logging.warning(f"Failed to send upload notification to {uid}: {e}")
                    except Exception as e:
                        logging.error(f"Error parsing Supabase message: {e} -- raw: {msg}")
    except Exception as e:
        logging.error(f"Supabase listener connection error: {e}")
        # Simple retry mechanism: wait and reconnect
        await asyncio.sleep(5)
        await listen_for_supabase_uploads(app)

# -----------------------------
# MAIN
# -----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers (keeps original bot behavior)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("users", admin_command))
    app.add_handler(CommandHandler("upload", upload_command))  # any user with key
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start the Supabase listener as a background task
    loop = asyncio.get_event_loop()
    loop.create_task(listen_for_supabase_uploads(app))

    print("✅ Gyan Setu Bot running with Supabase realtime notifications...")
    app.run_polling()

if __name__ == "__main__":
    main()
