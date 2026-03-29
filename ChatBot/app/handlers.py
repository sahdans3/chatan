from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import Forbidden

from app.database import (
    register_user, set_searching, find_partner,
    stop_chat, get_partner, save_feedback, connect_db
)
from app.keyboards import feedback_keyboard

# ================= CONSTANT MESSAGE =================
PARTNER_FOUND_MESSAGE = (
    "Partner found 😺\n\n"
    "/next — find a new partner\n"
    "/stop — stop this chat\n\n"
    "https://t.me/Annonymous_Chat_Bot"
)

# ================= COMMAND =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id)
    await update.message.reply_text(PARTNER_FOUND_MESSAGE)


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    register_user(user_id)
    set_searching(user_id, 1)

    partner = find_partner(user_id)
    if partner:
        await update.message.reply_text(PARTNER_FOUND_MESSAGE)
        try:
            await context.bot.send_message(
                chat_id=partner["user_id"],
                text=PARTNER_FOUND_MESSAGE
            )
        except Forbidden:
            stop_chat(partner["user_id"])
    else:
        await update.message.reply_text("🔍 Looking for a new partner...")


async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = stop_chat(user_id)

    if partner_id:
        try:
            await context.bot.send_message(
                chat_id=partner_id,
                text="Your partner has stopped the chat 😞\nType /search",
                reply_markup=feedback_keyboard()
            )
        except Forbidden:
            stop_chat(partner_id)

        await update.message.reply_text(
            "Leave feedback 👇",
            reply_markup=feedback_keyboard(normal=False)
        )

    set_searching(user_id, 1)
    await update.message.reply_text("Looking for a new partner...")

    partner = find_partner(user_id)
    if partner:
        await update.message.reply_text(PARTNER_FOUND_MESSAGE)
        try:
            await context.bot.send_message(
                chat_id=partner["user_id"],
                text=PARTNER_FOUND_MESSAGE
            )
        except Forbidden:
            stop_chat(partner["user_id"])


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = stop_chat(user_id)

    if not partner_id:
        await update.message.reply_text("Kamu tidak sedang dalam chat.")
        return

    for uid in (user_id, partner_id):
        try:
            await context.bot.send_message(
                chat_id=uid,
                text="Chat ended 😞",
                reply_markup=feedback_keyboard()
            )
        except Forbidden:
            stop_chat(uid)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    partner_id = get_partner(update.effective_user.id)
    if not partner_id:
        return

    try:
        await context.bot.send_message(
            chat_id=partner_id,
            text=update.message.text
        )
    except Forbidden:
        stop_chat(partner_id)


# ================= CALLBACK =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    feedback = query.data.replace("_next", "")

    db = connect_db()
    cursor = db.cursor()
    cursor.execute(
        "SELECT partner_id FROM feedback_temp WHERE user_id=%s",
        (user_id,)
    )
    row = cursor.fetchone()
    cursor.close()
    db.close()

    if row:
        save_feedback(user_id, row[0], feedback)
        await query.edit_message_text("✅ Feedback saved")
    else:
        await query.edit_message_text("⚠️ Feedback expired")
