"""
═══════════════════════════════════════════════════════════════
  PART 3: SGV_BOT - Telegram Bot Handlers
  SuperGrok One Video Bot - All command & callback handlers
═══════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import shutil
import asyncio
import threading
import logging
import time
import random
import subprocess

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
    ConversationHandler,
)
from telegram.constants import ParseMode

from sgv_config import (
    NAMA_USER, BOT_TOKEN, WA_GROUP_LINK,
    is_subscription_active, get_subscription_end_date, get_days_remaining,
    SUBSCRIPTION_EXPIRED_MSG, escape_html,
    load_prompts, save_prompts,
    list_bahan_folders, list_bahan_images, get_random_bahan_image,
    get_bahan_folder_path, ensure_bahan_dir,
)
import sgv_config
from sgv_selenium import generate_one_video_grok, generate_two_videos_multitab_grok, merge_video_pair

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONVERSATION STATES
# ═══════════════════════════════════════════════════════════════
(
    GEN_CHOOSE_DURATION,
    GEN_CHOOSE_MODE,
    GEN_WAITING_IMAGE,
    GEN_WAITING_PROMPT,
) = range(4)

(
    PROMPT_MENU,
    PROMPT_WAITING_NAME,
    PROMPT_WAITING_TEXT,
    PROMPT_EDIT_WAITING_TEXT,
) = range(10, 14)

(
    BAHAN_MENU,
    BAHAN_WAITING_FOLDER_NAME,
    BAHAN_WAITING_PHOTO,
) = range(20, 23)

# ═══════════════════════════════════════════════════════════════
#  ACTIVE TASKS
# ═══════════════════════════════════════════════════════════════
active_gen_tasks = {}   # uid -> {"stop": Event, "thread": Thread}


# ═══════════════════════════════════════════════════════════════
#  PROGRESS BAR HELPER
# ═══════════════════════════════════════════════════════════════
def build_progress_bar(percent: int) -> str:
    """Build a visually appealing animated-style progress bar."""
    total_blocks = 20
    filled = int(percent / 100 * total_blocks)
    empty = total_blocks - filled

    # Dynamic emoji based on progress
    if percent < 25:
        emoji = "🔴"
        bar_fill = "█"
        status_text = "⚡ Memulai generasi..."
    elif percent < 50:
        emoji = "🟠"
        bar_fill = "█"
        status_text = "🎨 Merender video..."
    elif percent < 75:
        emoji = "🟡"
        bar_fill = "█"
        status_text = "✨ Memproses detail..."
    elif percent < 100:
        emoji = "🟢"
        bar_fill = "█"
        status_text = "🔥 Hampir selesai!"
    else:
        emoji = "✅"
        bar_fill = "█"
        status_text = "🎉 Video selesai!"

    bar = bar_fill * filled + "░" * empty

    # Spinning indicator
    spin_chars = ["◐", "◓", "◑", "◒"]
    spin = spin_chars[percent % 4] if percent < 100 else "●"

    text = (
        f"{emoji} <b>GENERATING VIDEO</b> {emoji}\n\n"
        f"  {spin} [{bar}] {percent}%\n\n"
        f"  {status_text}\n"
    )
    return text


# ═══════════════════════════════════════════════════════════════
#  /START COMMAND
# ═══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu with user info, subscription, and guide."""
    if not is_subscription_active():
        await update.message.reply_text(SUBSCRIPTION_EXPIRED_MSG, parse_mode=ParseMode.HTML)
        return

    days_left = get_days_remaining()
    end_date = get_subscription_end_date()

    text = (
        f"══════════════════════════\n"
        f"  🤖 <b>SUPERGROK VIDEO BOT</b> 🤖\n"
        f"══════════════════════════\n\n"
        f"👤 <b>Nama User:</b> {escape_html(sgv_config.NAMA_USER)}\n"
        f"📅 <b>Berakhir:</b> {end_date}\n"
        f"⏳ <b>Sisa:</b> {days_left} hari\n\n"
        f"══════════════════════════\n"
        f"  📖 <b>PANDUAN COMMAND</b>\n"
        f"══════════════════════════\n\n"
        f"🎬 /generate\n"
        f"   ➜ Generate 1 video SuperGrok\n"
        f"   ➜ Pilih durasi 10s atau 20s\n"
        f"   ➜ Pilih mode: Image+Text atau Text only\n\n"
        f"📝 /prompt\n"
        f"   ➜ Kelola daftar prompt\n"
        f"   ➜ Tambah, edit, hapus prompt\n\n"
        f"📁 /bahan\n"
        f"   ➜ Kelola folder & gambar bahan\n"
        f"   ➜ Tambah folder, upload gambar\n\n"
        f"❓ /help\n"
        f"   ➜ Bantuan & grup WhatsApp\n\n"
        f"🛑 /stop\n"
        f"   ➜ Hentikan generasi yang berjalan\n"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  /HELP COMMAND
# ═══════════════════════════════════════════════════════════════
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redirect to WhatsApp group."""
    text = (
        f"❓ <b>BUTUH BANTUAN?</b>\n\n"
        f"Hubungi kami melalui grup WhatsApp:\n"
        f"👉 <a href=\"{WA_GROUP_LINK}\">Klik untuk bergabung</a>\n\n"
        f"📱 Atau salin link:\n"
        f"<code>{WA_GROUP_LINK}</code>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# ═══════════════════════════════════════════════════════════════
#  /STOP COMMAND
# ═══════════════════════════════════════════════════════════════
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop active generation task."""
    uid = update.effective_user.id
    if uid in active_gen_tasks:
        active_gen_tasks[uid]["stop"].set()
        await update.message.reply_text("🛑 <b>Menghentikan generasi...</b>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("ℹ️ Tidak ada generasi yang berjalan.", parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  /GENERATE CONVERSATION
# ═══════════════════════════════════════════════════════════════
async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start generate flow: choose duration first."""
    if not is_subscription_active():
        await update.message.reply_text(SUBSCRIPTION_EXPIRED_MSG, parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    uid = update.effective_user.id
    if uid in active_gen_tasks:
        await update.message.reply_text(
            "⚠️ Masih ada generasi berjalan. Ketik /stop untuk menghentikan dulu.",
            parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("⚡ 10 Detik", callback_data="gen_dur_10"),
         InlineKeyboardButton("🎬 20 Detik", callback_data="gen_dur_20")],
        [InlineKeyboardButton("❌ Batal", callback_data="gen_cancel")]
    ]
    await update.message.reply_text(
        "🎬 <b>GENERATE VIDEO</b>\n\n"
        "Pilih durasi video:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return GEN_CHOOSE_DURATION


async def gen_choose_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle duration selection."""
    query = update.callback_query
    await query.answer()

    if query.data == "gen_cancel":
        await query.edit_message_text("❌ Dibatalkan.", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    duration = 10 if query.data == "gen_dur_10" else 20
    context.user_data["gen_duration"] = duration

    keyboard = [
        [InlineKeyboardButton("🖼️ Image + Text to Video", callback_data="gen_mode_image"),
         InlineKeyboardButton("📝 Text to Video", callback_data="gen_mode_text")],
        [InlineKeyboardButton("❌ Batal", callback_data="gen_cancel")]
    ]
    await query.edit_message_text(
        f"🎬 <b>GENERATE VIDEO</b>\n\n"
        f"⏱️ Durasi: <b>{duration} detik</b>\n\n"
        f"Pilih mode generate:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return GEN_CHOOSE_MODE


async def gen_choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mode selection (image+text or text only)."""
    query = update.callback_query
    await query.answer()

    if query.data == "gen_cancel":
        await query.edit_message_text("❌ Dibatalkan.", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    duration = context.user_data.get("gen_duration", 10)

    if query.data == "gen_mode_image":
        context.user_data["gen_mode"] = "image_text"
        await query.edit_message_text(
            f"🎬 <b>GENERATE VIDEO</b>\n\n"
            f"⏱️ Durasi: <b>{duration} detik</b>\n"
            f"🖼️ Mode: <b>Image + Text to Video</b>\n\n"
            f"📷 Kirim gambar sekarang:",
            parse_mode=ParseMode.HTML
        )
        return GEN_WAITING_IMAGE
    else:
        context.user_data["gen_mode"] = "text"
        context.user_data["gen_image_path"] = None
        await query.edit_message_text(
            f"🎬 <b>GENERATE VIDEO</b>\n\n"
            f"⏱️ Durasi: <b>{duration} detik</b>\n"
            f"📝 Mode: <b>Text to Video</b>\n\n"
            f"✏️ Ketik prompt sekarang:",
            parse_mode=ParseMode.HTML
        )
        return GEN_WAITING_PROMPT


async def gen_receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image upload from user."""
    if not update.message.photo:
        await update.message.reply_text(
            "⚠️ Kirim sebagai <b>foto/gambar</b>, bukan file.",
            parse_mode=ParseMode.HTML)
        return GEN_WAITING_IMAGE

    # Download the photo
    photo = update.message.photo[-1]  # Highest resolution
    file = await context.bot.get_file(photo.file_id)

    # Save to bahan folder
    ensure_bahan_dir()
    temp_dir = os.path.join(sgv_config.BAHAN_DIR, "_temp_gen")
    os.makedirs(temp_dir, exist_ok=True)
    img_path = os.path.join(temp_dir, f"gen_{int(time.time())}.jpg")
    await file.download_to_drive(img_path)

    context.user_data["gen_image_path"] = img_path

    duration = context.user_data.get("gen_duration", 10)
    await update.message.reply_text(
        f"✅ <b>Gambar berhasil disimpan!</b>\n\n"
        f"🎬 <b>GENERATE VIDEO</b>\n"
        f"⏱️ Durasi: <b>{duration} detik</b>\n"
        f"🖼️ Mode: <b>Image + Text to Video</b>\n\n"
        f"✏️ Ketik prompt sekarang:",
        parse_mode=ParseMode.HTML
    )
    return GEN_WAITING_PROMPT


async def gen_receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle prompt text and start generation."""
    prompt_text = update.message.text.strip()
    if not prompt_text:
        await update.message.reply_text("⚠️ Prompt tidak boleh kosong. Ketik ulang:")
        return GEN_WAITING_PROMPT

    context.user_data["gen_prompt"] = prompt_text
    duration = context.user_data.get("gen_duration", 10)
    mode = context.user_data.get("gen_mode", "text")
    image_path = context.user_data.get("gen_image_path")

    uid = update.effective_user.id
    chat_id = update.effective_chat.id

    # Send initial progress message
    progress_msg = await update.message.reply_text(
        build_progress_bar(0),
        parse_mode=ParseMode.HTML
    )

    # Start generation in thread
    stop_event = threading.Event()
    bot = context.bot
    main_loop = asyncio.get_event_loop()

    active_gen_tasks[uid] = {"stop": stop_event}

    thread = threading.Thread(
        target=_run_generation,
        args=(uid, chat_id, bot, main_loop, prompt_text, image_path,
              duration, stop_event, progress_msg.message_id),
        daemon=True
    )
    active_gen_tasks[uid]["thread"] = thread
    thread.start()

    return ConversationHandler.END


async def gen_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel generation conversation."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Dibatalkan.", parse_mode=ParseMode.HTML)
    elif update.message:
        await update.message.reply_text("❌ Dibatalkan.", parse_mode=ParseMode.HTML)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#  GENERATION THREAD
# ═══════════════════════════════════════════════════════════════

def compress_video_if_needed(video_path, max_size_mb, log_fn):
    """Bypass Telegram 50MB file limit by compressing it."""
    try:
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if size_mb > max_size_mb:
            log_fn(f"⚠️ Ukuran video ({size_mb:.1f} MB) melebihi limit. Mengompresi video ke 720p...")
            out_path = video_path.replace(".mp4", "_compressed.mp4")
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", "scale=-2:720", "-c:v", "libx264", "-crf", "28", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k", out_path
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            if os.path.exists(out_path):
                new_size_mb = os.path.getsize(out_path) / (1024 * 1024)
                log_fn(f"✅ Video dikompresi: {size_mb:.1f} MB -> {new_size_mb:.1f} MB")
                return out_path, video_path  # Kembalikan file hasil, beserta original untuk dibersihkan
    except Exception as e:
        log_fn(f"❌ Kompresi gagal: {e}")
    return video_path, None

def _run_generation(uid, chat_id, bot, main_loop, prompt_text, image_path,
                    duration, stop_event, progress_msg_id):
    """Run video generation in background thread."""
    import sgv_config

    last_progress_pct = -1
    progress_update_lock = threading.Lock()

    def send(text):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    def update_progress(pct):
        nonlocal last_progress_pct
        with progress_update_lock:
            # Only update if percentage changed significantly (every 5%)
            if pct == last_progress_pct:
                return
            if pct < 100 and abs(pct - last_progress_pct) < 5:
                return
            last_progress_pct = pct

        bar_text = build_progress_bar(pct)
        async def _update():
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg_id,
                    text=bar_text,
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        asyncio.run_coroutine_threadsafe(_update(), main_loop)

    def log_fn(msg):
        logger.info(msg)

    output_dir = sgv_config.VIDEO_DIR
    files_to_delete = []

    try:
        if duration == 20:
            # Generate 2 videos and merge (Multitab)
            log_fn("🎬 Mode 20 detik: generate 2 video MULTITAB + merge...")

            update_progress(0)
            def progress_multi(pct):
                update_progress(int(pct * 0.90))  # 0-90% for generation

            vid1, vid2 = generate_two_videos_multitab_grok(
                image_path=image_path,
                prompt_text=prompt_text,
                log_fn=log_fn,
                stop_event=stop_event,
                output_dir=output_dir,
                user_data_dir=sgv_config.USER_DATA_CHROME,
                port=sgv_config.DEFAULT_PORT,
                progress_callback=progress_multi
            )

            if vid1 and os.path.exists(vid1): files_to_delete.append(vid1)
            if vid2 and os.path.exists(vid2): files_to_delete.append(vid2)

            if not vid1 or not vid2 or stop_event.is_set():
                if not stop_event.is_set():
                    send("❌ <b>Gagal generate video (salah satu/keduanya gagal)</b>")
                # Hapus file mentah jika proses dihentikan atau gagal
                for f in files_to_delete:
                    try:
                        if os.path.exists(f): os.remove(f)
                    except: pass
                active_gen_tasks.pop(uid, None)
                return

            # Merge
            update_progress(95)
            log_fn("🎬 Merging 2 video...")
            merged = merge_video_pair(vid1, vid2, output_dir, log_fn)

            if not merged:
                send("❌ <b>Gagal merge video</b>")
                for f in files_to_delete:
                    try:
                        if os.path.exists(f): os.remove(f)
                    except: pass
                active_gen_tasks.pop(uid, None)
                return

            final_video = merged
            files_to_delete.append(final_video)
            update_progress(100)

        else:
            # Single 10s video
            def progress_single(pct):
                update_progress(pct)

            final_video = generate_one_video_grok(
                image_path=image_path,
                prompt_text=prompt_text,
                log_fn=log_fn,
                stop_event=stop_event,
                output_dir=output_dir,
                user_data_dir=sgv_config.USER_DATA_CHROME,
                port=sgv_config.DEFAULT_PORT,
                progress_callback=progress_single
            )

            if not final_video or stop_event.is_set():
                if not stop_event.is_set():
                    send("❌ <b>Gagal generate video</b>")
                active_gen_tasks.pop(uid, None)
                return

        # Cek size dan kompresi jika over 45 MB (Telegram limit 50MB)
        final_video, original_video = compress_video_if_needed(final_video, 45.0, log_fn)

        if final_video not in files_to_delete:
            files_to_delete.append(final_video)
        if original_video and original_video not in files_to_delete:
            files_to_delete.append(original_video)

        # Send video to Telegram (video only, no caption)
        async def _send_video():
            try:
                # Update progress message to done
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=progress_msg_id,
                        text=build_progress_bar(100),
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass

                with open(final_video, 'rb') as vf:
                    await bot.send_video(
                        chat_id,
                        video=vf,
                        supports_streaming=True
                    )

                # Send "Generate Again" button
                keyboard = [[
                    InlineKeyboardButton("🔄 Generate Lagi", callback_data="gen_again")
                ]]
                await bot.send_message(
                    chat_id,
                    "✅ <b>Video berhasil dikirim!</b>",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )

                # Delete all accumulated video files after sending
                deleted_files = 0
                for f in set(files_to_delete):
                    try:
                        if os.path.exists(f):
                            os.remove(f)
                            deleted_files += 1
                    except Exception as del_e:
                        logger.error(f"Gagal hapus video {f}: {del_e}")
                
                if deleted_files > 0:
                    logger.info(f"🗑️ {deleted_files} file video dibersihkan.")

            except Exception as e:
                logger.error(f"Gagal kirim video: {e}")
                await bot.send_message(
                    chat_id,
                    f"❌ <b>Gagal mengirim video ke Telegram</b>\n{escape_html(str(e)[:100])}",
                    parse_mode=ParseMode.HTML
                )

        asyncio.run_coroutine_threadsafe(_send_video(), main_loop).result(timeout=120)

        # Clean up temp image
        if image_path and "_temp_gen" in str(image_path):
            try:
                os.remove(image_path)
            except:
                pass

    except Exception as e:
        logger.error(f"Generation error: {e}")
        send(f"❌ <b>Error:</b> {escape_html(str(e)[:200])}")
    finally:
        active_gen_tasks.pop(uid, None)


# ═══════════════════════════════════════════════════════════════
#  GENERATE AGAIN CALLBACK
# ═══════════════════════════════════════════════════════════════
async def callback_gen_again(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Generate Again' button press."""
    query = update.callback_query
    await query.answer()

    if not is_subscription_active():
        await query.edit_message_text(SUBSCRIPTION_EXPIRED_MSG, parse_mode=ParseMode.HTML)
        return

    uid = update.effective_user.id
    if uid in active_gen_tasks:
        await query.edit_message_text(
            "⚠️ Masih ada generasi berjalan. Ketik /stop dulu.",
            parse_mode=ParseMode.HTML)
        return

    keyboard = [
        [InlineKeyboardButton("⚡ 10 Detik", callback_data="gen_dur_10"),
         InlineKeyboardButton("🎬 20 Detik", callback_data="gen_dur_20")],
        [InlineKeyboardButton("❌ Batal", callback_data="gen_cancel")]
    ]
    await query.edit_message_text(
        "🎬 <b>GENERATE VIDEO</b>\n\n"
        "Pilih durasi video:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


# ═══════════════════════════════════════════════════════════════
#  /PROMPT CONVERSATION
# ═══════════════════════════════════════════════════════════════
async def cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show prompt management menu."""
    if not is_subscription_active():
        await update.message.reply_text(SUBSCRIPTION_EXPIRED_MSG, parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    return await _show_prompt_menu(update, context)


async def _show_prompt_menu(update, context, edit=False):
    """Display prompt management menu with list of prompts."""
    prompts = load_prompts()

    text = "📝 <b>KELOLA PROMPT</b>\n\n"
    if prompts:
        for i, (name, ptext) in enumerate(prompts.items(), 1):
            preview = ptext[:50] + "..." if len(ptext) > 50 else ptext
            text += f"  {i}. <b>{escape_html(name)}</b>\n     <i>{escape_html(preview)}</i>\n\n"
    else:
        text += "  <i>Belum ada prompt tersimpan.</i>\n\n"

    keyboard = [
        [InlineKeyboardButton("➕ Tambah Prompt", callback_data="prompt_add")],
    ]

    # Add edit/delete buttons for each prompt
    if prompts:
        for name in prompts:
            keyboard.append([
                InlineKeyboardButton(f"✏️ {name}", callback_data=f"prompt_edit_{name}"),
                InlineKeyboardButton(f"🗑️ {name}", callback_data=f"prompt_del_{name}")
            ])

    keyboard.append([InlineKeyboardButton("❌ Tutup", callback_data="prompt_close")])

    markup = InlineKeyboardMarkup(keyboard)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    else:
        msg = update.message if update.message else update.callback_query.message
        await msg.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

    return PROMPT_MENU


async def prompt_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle prompt menu button presses."""
    query = update.callback_query
    await query.answer()

    if query.data == "prompt_close":
        await query.edit_message_text("📝 Menu prompt ditutup.", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if query.data == "prompt_add":
        await query.edit_message_text(
            "📝 <b>TAMBAH PROMPT</b>\n\n"
            "Ketik nama prompt baru:",
            parse_mode=ParseMode.HTML
        )
        return PROMPT_WAITING_NAME

    if query.data.startswith("prompt_edit_"):
        name = query.data[len("prompt_edit_"):]
        context.user_data["prompt_edit_name"] = name
        prompts = load_prompts()
        current = prompts.get(name, "")
        await query.edit_message_text(
            f"✏️ <b>EDIT PROMPT: {escape_html(name)}</b>\n\n"
            f"Prompt saat ini:\n<i>{escape_html(current)}</i>\n\n"
            f"Ketik prompt baru:",
            parse_mode=ParseMode.HTML
        )
        return PROMPT_EDIT_WAITING_TEXT

    if query.data.startswith("prompt_del_"):
        name = query.data[len("prompt_del_"):]
        prompts = load_prompts()
        if name in prompts:
            del prompts[name]
            save_prompts(prompts)
        await query.answer(f"✅ Prompt '{name}' dihapus!")
        return await _show_prompt_menu(update, context, edit=True)

    return PROMPT_MENU


async def prompt_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive new prompt name."""
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("⚠️ Nama tidak boleh kosong. Ketik ulang:")
        return PROMPT_WAITING_NAME

    context.user_data["prompt_new_name"] = name
    await update.message.reply_text(
        f"📝 <b>Nama prompt:</b> {escape_html(name)}\n\n"
        f"Ketik isi prompt:",
        parse_mode=ParseMode.HTML
    )
    return PROMPT_WAITING_TEXT


async def prompt_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive prompt text for new prompt."""
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("⚠️ Prompt tidak boleh kosong. Ketik ulang:")
        return PROMPT_WAITING_TEXT

    name = context.user_data.get("prompt_new_name", "Untitled")
    prompts = load_prompts()
    prompts[name] = text
    save_prompts(prompts)

    await update.message.reply_text(
        f"✅ <b>Prompt disimpan!</b>\n\n"
        f"📝 <b>{escape_html(name)}:</b>\n"
        f"<i>{escape_html(text[:200])}</i>",
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END


async def prompt_receive_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive edited prompt text."""
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("⚠️ Prompt tidak boleh kosong. Ketik ulang:")
        return PROMPT_EDIT_WAITING_TEXT

    name = context.user_data.get("prompt_edit_name", "Untitled")
    prompts = load_prompts()
    prompts[name] = text
    save_prompts(prompts)

    await update.message.reply_text(
        f"✅ <b>Prompt diperbarui!</b>\n\n"
        f"📝 <b>{escape_html(name)}:</b>\n"
        f"<i>{escape_html(text[:200])}</i>",
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#  /BAHAN CONVERSATION
# ═══════════════════════════════════════════════════════════════
async def cmd_bahan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bahan management menu."""
    if not is_subscription_active():
        await update.message.reply_text(SUBSCRIPTION_EXPIRED_MSG, parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    return await _show_bahan_menu(update, context)


async def _show_bahan_menu(update, context, edit=False):
    """Display bahan folder list with management options."""
    folders = list_bahan_folders()

    text = "📁 <b>KELOLA BAHAN</b>\n\n"
    if folders:
        for i, folder in enumerate(folders, 1):
            images = list_bahan_images(folder)
            text += f"  {i}. 📁 <b>{escape_html(folder)}</b> ({len(images)} gambar)\n"
        text += "\n"
    else:
        text += "  <i>Belum ada folder bahan.</i>\n\n"

    keyboard = [
        [InlineKeyboardButton("➕ Buat Folder Baru", callback_data="bahan_add_folder")],
    ]

    if folders:
        for folder in folders:
            keyboard.append([
                InlineKeyboardButton(f"📷 Upload ke {folder}", callback_data=f"bahan_upload_{folder}"),
                InlineKeyboardButton(f"🗑️ Hapus {folder}", callback_data=f"bahan_del_{folder}")
            ])

    keyboard.append([InlineKeyboardButton("❌ Tutup", callback_data="bahan_close")])

    markup = InlineKeyboardMarkup(keyboard)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    else:
        msg = update.message if update.message else update.callback_query.message
        await msg.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)

    return BAHAN_MENU


async def bahan_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bahan menu button presses."""
    query = update.callback_query
    await query.answer()

    if query.data == "bahan_close":
        await query.edit_message_text("📁 Menu bahan ditutup.", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if query.data == "bahan_add_folder":
        await query.edit_message_text(
            "📁 <b>BUAT FOLDER BARU</b>\n\n"
            "Ketik nama folder baru:",
            parse_mode=ParseMode.HTML
        )
        return BAHAN_WAITING_FOLDER_NAME

    if query.data.startswith("bahan_upload_"):
        folder = query.data[len("bahan_upload_"):]
        context.user_data["bahan_target_folder"] = folder
        await query.edit_message_text(
            f"📷 <b>UPLOAD GAMBAR</b>\n\n"
            f"📁 Folder: <b>{escape_html(folder)}</b>\n\n"
            f"Kirim gambar sekarang.\n"
            f"Ketik /done jika selesai.",
            parse_mode=ParseMode.HTML
        )
        return BAHAN_WAITING_PHOTO

    if query.data.startswith("bahan_del_"):
        folder = query.data[len("bahan_del_"):]
        folder_path = get_bahan_folder_path(folder)
        if os.path.isdir(folder_path):
            shutil.rmtree(folder_path, ignore_errors=True)
        await query.answer(f"✅ Folder '{folder}' dihapus!")
        return await _show_bahan_menu(update, context, edit=True)

    return BAHAN_MENU


async def bahan_receive_folder_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive new folder name."""
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("⚠️ Nama folder tidak boleh kosong.")
        return BAHAN_WAITING_FOLDER_NAME

    # Create the folder
    folder_path = get_bahan_folder_path(name)
    os.makedirs(folder_path, exist_ok=True)

    await update.message.reply_text(
        f"✅ <b>Folder '{escape_html(name)}' berhasil dibuat!</b>\n\n"
        f"Gunakan /bahan untuk mengelola.",
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END


async def bahan_receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive photo for bahan folder."""
    if update.message.text and update.message.text.strip().lower() == "/done":
        await update.message.reply_text(
            "✅ <b>Selesai upload gambar.</b>",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    if not update.message.photo:
        await update.message.reply_text(
            "⚠️ Kirim sebagai <b>foto/gambar</b>.\nKetik /done jika selesai.",
            parse_mode=ParseMode.HTML)
        return BAHAN_WAITING_PHOTO

    folder = context.user_data.get("bahan_target_folder", "default")
    folder_path = get_bahan_folder_path(folder)
    os.makedirs(folder_path, exist_ok=True)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    img_name = f"img_{int(time.time())}_{random.randint(100,999)}.jpg"
    img_path = os.path.join(folder_path, img_name)
    await file.download_to_drive(img_path)

    images_count = len(list_bahan_images(folder))

    await update.message.reply_text(
        f"✅ <b>Gambar disimpan!</b>\n"
        f"📁 {escape_html(folder)} ({images_count} gambar)\n\n"
        f"Kirim lagi atau ketik /done.",
        parse_mode=ParseMode.HTML
    )
    return BAHAN_WAITING_PHOTO


# ═══════════════════════════════════════════════════════════════
#  BUILD HANDLERS
# ═══════════════════════════════════════════════════════════════
def get_generate_conversation_handler():
    """Build and return the /generate ConversationHandler."""
    return ConversationHandler(
        entry_points=[CommandHandler("generate", cmd_generate)],
        states={
            GEN_CHOOSE_DURATION: [
                CallbackQueryHandler(gen_choose_duration, pattern=r"^gen_dur_|gen_cancel$")
            ],
            GEN_CHOOSE_MODE: [
                CallbackQueryHandler(gen_choose_mode, pattern=r"^gen_mode_|gen_cancel$")
            ],
            GEN_WAITING_IMAGE: [
                MessageHandler(filters.PHOTO, gen_receive_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, gen_receive_image),
            ],
            GEN_WAITING_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, gen_receive_prompt),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", gen_cancel),
            CallbackQueryHandler(gen_cancel, pattern=r"^gen_cancel$"),
        ],
        per_user=True,
        per_chat=True,
    )


def get_prompt_conversation_handler():
    """Build and return the /prompt ConversationHandler."""
    return ConversationHandler(
        entry_points=[CommandHandler("prompt", cmd_prompt)],
        states={
            PROMPT_MENU: [
                CallbackQueryHandler(prompt_menu_handler, pattern=r"^prompt_")
            ],
            PROMPT_WAITING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, prompt_receive_name),
            ],
            PROMPT_WAITING_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, prompt_receive_text),
            ],
            PROMPT_EDIT_WAITING_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, prompt_receive_edit_text),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", gen_cancel),
            CallbackQueryHandler(gen_cancel, pattern=r"^prompt_close$"),
        ],
        per_user=True,
        per_chat=True,
    )


def get_bahan_conversation_handler():
    """Build and return the /bahan ConversationHandler."""
    return ConversationHandler(
        entry_points=[CommandHandler("bahan", cmd_bahan)],
        states={
            BAHAN_MENU: [
                CallbackQueryHandler(bahan_menu_handler, pattern=r"^bahan_")
            ],
            BAHAN_WAITING_FOLDER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bahan_receive_folder_name),
            ],
            BAHAN_WAITING_PHOTO: [
                MessageHandler(filters.PHOTO, bahan_receive_photo),
                MessageHandler(filters.TEXT, bahan_receive_photo),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", gen_cancel),
            CallbackQueryHandler(gen_cancel, pattern=r"^bahan_close$"),
        ],
        per_user=True,
        per_chat=True,
    )
