import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.helpers import escape_markdown
from flask import Flask
import threading

# -----------------------------
# CONFIG
# -----------------------------
BOT_TOKEN = os.getenv(7803458221:"7803458221:AAFIhgShyY8S1nVfhPn3ct7OID1SXVpxKtk")
ADMIN_CHAT_ID = 8064043725
UPLOAD_KEY = "admin000"

FAQ_QUESTIONS = {
    "time for homework demand": "You can demand homework at any time.",
    "when homework is uploaded to website or app": "Time: 7:00 to 8:00 PM."
}
WHATSAPP_CHANNEL = "https://whatsapp.com/channel/0029Vb7EwfHGk1FryYMPm33x"

logging.basicConfig(level=logging.INFO)

# -----------------------------
# GLOBAL STATE
# -----------------------------
all_users = set()
user_waiting_for_update = set()
user_warnings = {}
blocked_users = {}
authorized_upload_users = {}
user_unusual_count = {}

# -----------------------------
# KEEP-ALIVE WEB SERVER
# -----------------------------
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Gyan Setu Bot is alive and running!"

def run_server():
    app_web.run(host="0.0.0.0", port=3000)

threading.Thread(target=run_server).start()

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
# UPLOAD COMMAND
# -----------------------------
async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    authorized_upload_users[user_id] = {'state': 'awaiting_key'}
    await update.message.reply_text("🔑 Send the key to proceed with upload.")

# -----------------------------
# ADMIN COMMAND
# -----------------------------
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Only admin can use this command.")
        return
    text = "👥 Users:
"
    for uid in all_users:
        rem = remaining_block_time(blocked_users.get(uid, datetime.now())) if uid in blocked_users else "0s"
        text += f"{uid} - Block remaining: {rem}\n"
    await update.message.reply_text(text)

# -----------------------------
# BUTTON HANDLER
# -----------------------------
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "website":
        await query.edit_message_text("🌐 Visit: [www.setugyan.live](https://www.setugyan.live)", parse_mode="Markdown")
    elif data == "update":
        user_waiting_for_update.add(user_id)
        await query.edit_message_text("📩 Type your update request below:")
    elif data == "about":
        await query.edit_message_text("ℹ️ *Gyan Setu* is an educational platform by *Team Hackers*.", parse_mode="Markdown")
    elif data == "homework":
        keyboard = [
            [InlineKeyboardButton("Physics", callback_data="sub_physics")],
            [InlineKeyboardButton("Chemistry", callback_data="sub_chemistry")],
            [InlineKeyboardButton("Maths", callback_data="sub_maths")],
            [InlineKeyboardButton("⬅️ Back", callback_data="main")]
        ]
        await query.edit_message_text("📚 Select a subject:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "faq":
        keyboard = [[InlineKeyboardButton(q.capitalize(), callback_data=f"faq_{q}")] for q in FAQ_QUESTIONS]
        await query.edit_message_text("❓ Select a question:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("faq_"):
        question = data[4:]
        answer = FAQ_QUESTIONS.get(question, "No answer found.")
        await query.edit_message_text(f"💡 {answer}\n\nJoin our WhatsApp: {WHATSAPP_CHANNEL}")
    elif data == "main":
        await query.edit_message_text("👋 Hi, welcome to Gyan Setu!", reply_markup=main_menu_keyboard())

# -----------------------------
# MESSAGE HANDLER
# -----------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    all_users.add(user_id)
    text = update.message.text.lower()

    if user_id in user_waiting_for_update:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"📩 Update Request from {user_id}: {update.message.text}")
        await update.message.reply_text("✅ Your request has been sent to admin Vishal.", reply_markup=main_menu_keyboard())
        user_waiting_for_update.remove(user_id)
        return

    if "gyan setu" in text:
        await start(update, context)

# -----------------------------
# MAIN ENTRY
# -----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("users", admin_command))
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Gyan Setu Bot is running on Railway with keep-alive web server...")
    app.run_polling()

if __name__ == "__main__":
    main()
