from telegram import Update, InputFile
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest, TelegramError
import asyncio
import io

from app.database import (
    register_user,
    set_searching,
    join_queue,
    leave_queue,
    find_partner,
    stop_chat,
    get_partner,
    remove_user,
    is_searching,
    save_feedback,
    clear_user_status,
    get_user_status
)
from app.keyboards import feedback_keyboard

PARTNER_FOUND_MESSAGE = (
    "Partner found 😺\n\n"
    "/next — find a new partner\n"
    "/stop — stop this chat\n\n"
    "https://t.me/Annonymous_Chat_Bot"
)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user_id = update.effective_user.id
    register_user(user_id)
    try:
        await update.message.reply_text("👋 Welcome!\n\nType /search to find a partner.")
    except TelegramError as e:
        print(e)

# ================= SEARCH =================

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user_id = update.effective_user.id
    register_user(user_id)
    clear_user_status(user_id)
    
    if get_partner(user_id):
        await update.message.reply_text("💬 You are already chatting.\nUse /next or /stop.")
        return
    
    set_searching(user_id, 1)
    join_queue(user_id)
    
    # Cari partner dengan retry (10 kali percobaan dengan delay 1 detik)
    partner = None
    for attempt in range(10):
        partner = find_partner(user_id)
        if partner:
            break
        print(f"🔄 Attempt {attempt+1}/10: Waiting for partner for user {user_id}")
        await asyncio.sleep(1)
    
    if partner is None:
        await update.message.reply_text("🔍 Waiting for another user...")
        return
    
    await context.bot.send_message(chat_id=user_id, text=PARTNER_FOUND_MESSAGE)
    await context.bot.send_message(chat_id=partner, text=PARTNER_FOUND_MESSAGE)

# ================= NEXT =================

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user_id = update.effective_user.id
    register_user(user_id)
    
    # Dapatkan partner lama
    old_partner = get_partner(user_id)
    
    # Stop chat dengan lock
    stop_chat(user_id)
    clear_user_status(user_id)
    
    # Kirim pesan ke partner lama
    if old_partner:
        try:
            await context.bot.send_message(
                chat_id=old_partner, 
                text="😞 Your partner has left the chat."
            )
        except Forbidden:
            print(f"⚠️ Partner {old_partner} blocked the bot. Cleaning up...")
            remove_user(old_partner)
        except Exception as e:
            print(f"⚠️ Error sending to old partner: {e}")
    
    # Tunggu agar database sinkron
    await asyncio.sleep(0.5)
    
    # Set searching
    set_searching(user_id, 1)
    join_queue(user_id)
    
    # Cari partner dengan retry (10 kali percobaan dengan delay 1 detik)
    partner = None
    for attempt in range(10):
        partner = find_partner(user_id)
        if partner:
            break
        print(f"🔄 Attempt {attempt+1}/10: Waiting for partner for user {user_id}")
        await asyncio.sleep(1)
    
    if partner is None:
        await update.message.reply_text("🔍 Waiting for another user...")
        return
    
    # Kirim pesan ke kedua user
    await context.bot.send_message(
        chat_id=user_id,
        text=PARTNER_FOUND_MESSAGE
    )
    await context.bot.send_message(
        chat_id=partner,
        text=PARTNER_FOUND_MESSAGE
    )

# ================= STOP =================

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user_id = update.effective_user.id
    
    partner_id = stop_chat(user_id)
    clear_user_status(user_id)
    
    if not partner_id:
        try:
            await update.message.reply_text("❌ You are not in a chat.")
        except TelegramError:
            pass
        return
    
    try:
        await context.bot.send_message(
            chat_id=partner_id, 
            text="😞 Your partner has ended the chat."
        )
    except Forbidden:
        print(f"⚠️ Partner {partner_id} blocked the bot. Cleaning up...")
        remove_user(partner_id)
    except TelegramError as e:
        print(e)
    
    try:
        await update.message.reply_text(
            "Chat ended 😞", 
            reply_markup=feedback_keyboard()
        )
    except TelegramError as e:
        print(e)

# ================= REPLY HANDLER =================

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user_id = update.effective_user.id
    partner_id = get_partner(user_id)
    
    if partner_id is None:
        await update.message.reply_text("❌ You are not in a chat. Use /search to find a partner.")
        return
    
    try:
        message = update.message
        reply_to = message.reply_to_message
        
        replied_text = ""
        if reply_to:
            if reply_to.text:
                replied_text = reply_to.text
            elif reply_to.caption:
                replied_text = reply_to.caption
            elif reply_to.photo:
                replied_text = "📸 Photo"
            elif reply_to.video:
                replied_text = "🎬 Video"
            elif reply_to.document:
                replied_text = f"📄 {reply_to.document.file_name}"
            elif reply_to.sticker:
                replied_text = "🎨 Sticker"
            elif reply_to.voice:
                replied_text = "🎵 Voice"
            elif reply_to.audio:
                replied_text = "🎵 Audio"
            elif reply_to.animation:
                replied_text = "🎬 GIF"
            else:
                replied_text = "📎 Media"
        
        if replied_text:
            await context.bot.send_message(chat_id=partner_id, text=f"⬆️ {replied_text}")
        
        await context.bot.send_message(chat_id=partner_id, text=message.text)
        print("↩️ Reply sent")
        
    except Forbidden:
        print(f"⚠️ Partner {partner_id} blocked the bot. Cleaning up...")
        stop_chat(user_id)
        remove_user(partner_id)
        await update.message.reply_text("❌ Your partner has left the chat. Use /search to find a new partner.")
    except Exception as e:
        print(f"❌ Reply error: {e}")
        await update.message.reply_text("❌ Failed to send reply. Please try again.")

# ================= MEDIA HANDLER =================

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user_id = update.effective_user.id
    partner_id = get_partner(user_id)
    
    if partner_id is None:
        await update.message.reply_text("❌ You are not in a chat. Use /search to find a partner.")
        return
    
    try:
        message = update.message
        is_reply = message.reply_to_message is not None
        
        if is_reply:
            reply_to = message.reply_to_message
            replied_text = ""
            if reply_to.text:
                replied_text = reply_to.text
            elif reply_to.caption:
                replied_text = reply_to.caption
            elif reply_to.photo:
                replied_text = "📸 Photo"
            elif reply_to.video:
                replied_text = "🎬 Video"
            elif reply_to.document:
                replied_text = f"📄 {reply_to.document.file_name}"
            elif reply_to.sticker:
                replied_text = "🎨 Sticker"
            elif reply_to.voice:
                replied_text = "🎵 Voice"
            elif reply_to.audio:
                replied_text = "🎵 Audio"
            elif reply_to.animation:
                replied_text = "🎬 GIF"
            else:
                replied_text = "📎 Media"
            
            if replied_text:
                await context.bot.send_message(chat_id=partner_id, text=f"⬆️ {replied_text}")
        
        if message.photo:
            photo = message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            file_bytes = await file.download_as_bytearray()
            await context.bot.send_photo(chat_id=partner_id, photo=io.BytesIO(file_bytes), caption=message.caption)
        elif message.video:
            video = message.video
            file = await context.bot.get_file(video.file_id)
            file_bytes = await file.download_as_bytearray()
            await context.bot.send_video(chat_id=partner_id, video=io.BytesIO(file_bytes), caption=message.caption, supports_streaming=True)
        elif message.document:
            document = message.document
            file = await context.bot.get_file(document.file_id)
            file_bytes = await file.download_as_bytearray()
            mime_type = document.mime_type or ""
            is_image = mime_type.startswith('image/') or document.file_name.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'))
            if is_image:
                await context.bot.send_photo(chat_id=partner_id, photo=io.BytesIO(file_bytes), caption=message.caption)
            else:
                await context.bot.send_document(chat_id=partner_id, document=io.BytesIO(file_bytes), filename=document.file_name, caption=message.caption)
        elif message.sticker:
            await context.bot.send_sticker(chat_id=partner_id, sticker=message.sticker.file_id)
        elif message.voice:
            voice = message.voice
            file = await context.bot.get_file(voice.file_id)
            file_bytes = await file.download_as_bytearray()
            await context.bot.send_voice(chat_id=partner_id, voice=io.BytesIO(file_bytes), caption=message.caption)
        elif message.audio:
            audio = message.audio
            file = await context.bot.get_file(audio.file_id)
            file_bytes = await file.download_as_bytearray()
            await context.bot.send_audio(chat_id=partner_id, audio=io.BytesIO(file_bytes), caption=message.caption, title=audio.title, performer=audio.performer)
        elif message.animation:
            animation = message.animation
            file = await context.bot.get_file(animation.file_id)
            file_bytes = await file.download_as_bytearray()
            await context.bot.send_animation(chat_id=partner_id, animation=io.BytesIO(file_bytes), caption=message.caption)
        elif message.video_note:
            video_note = message.video_note
            file = await context.bot.get_file(video_note.file_id)
            file_bytes = await file.download_as_bytearray()
            await context.bot.send_video_note(chat_id=partner_id, video_note=io.BytesIO(file_bytes))
        else:
            await update.message.reply_text("❌ Tipe media tidak didukung.")
            
    except Forbidden:
        print(f"⚠️ Partner {partner_id} blocked the bot. Cleaning up...")
        stop_chat(user_id)
        remove_user(partner_id)
        await update.message.reply_text("❌ Your partner has left the chat. Use /search to find a new partner.")
    except Exception as e:
        print(f"❌ Media error: {e}")
        await update.message.reply_text("❌ Gagal mengirim media. Silakan coba lagi.")

# ================= MESSAGE HANDLER =================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user_id = update.effective_user.id
    
    if update.message.reply_to_message is not None:
        await reply_handler(update, context)
        return
    
    # Retry get_partner (3 attempts)
    partner_id = None
    for attempt in range(3):
        partner_id = get_partner(user_id)
        if partner_id:
            break
        await asyncio.sleep(0.3)
    
    if partner_id is None:
        await update.message.reply_text("❌ You are not in a chat. Use /search to find a partner.")
        return
    
    try:
        await context.bot.send_message(chat_id=partner_id, text=update.message.text)
        print("✅ Message sent")
    except Forbidden:
        print(f"⚠️ Partner {partner_id} blocked the bot. Cleaning up...")
        stop_chat(user_id)
        remove_user(partner_id)
        await update.message.reply_text("❌ Your partner has left the chat. Use /search to find a new partner.")
    except Exception as e:
        print(f"❌ Send error: {e}")
        # Check if partner still valid
        partner_check = get_partner(partner_id)
        if not partner_check:
            stop_chat(user_id)
            await update.message.reply_text("❌ Partner has left the chat. Use /search to find a new partner.")
        else:
            await update.message.reply_text("❌ Failed to send message. Please try again.")

# ================= BUTTON HANDLER =================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return
    try:
        await query.answer()
        user_id = query.from_user.id
        partner_id = get_partner(user_id)
        feedback = query.data
        if partner_id:
            try:
                save_feedback(from_user=user_id, to_user=partner_id, feedback=feedback)
            except Exception as e:
                print(e)
        await query.edit_message_text("✅ Thank you for your feedback!")
    except BadRequest:
        pass
    except TelegramError as e:
        print(e)

# ================= ERROR HANDLER =================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("=" * 50)
    print(f"Update: {update}")
    print(f"Error: {context.error}")
    print("=" * 50)
    
    if update and update.effective_user:
        user_id = update.effective_user.id
        try:
            clear_user_status(user_id)
        except Exception as e:
            print(f"❌ Error clearing status: {e}")
    
    if update and update.effective_user:
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="❌ Maaf, terjadi kesalahan. Silakan coba /search lagi."
            )
        except Forbidden:
            print(f"⚠️ User {update.effective_user.id} blocked the bot")
        except:
            pass