"""
🚀 TikTok Multi-Upload Scheduler — Telegram Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mirrors tiktok_gui.py functionality via Telegram.
Features:
  • Video settings: folder, start from, upload count
  • Product settings: radio name, title, description, sound toggle
  • Schedule settings: date, time, interval
  • Chrome settings: user data dir, debug port
  • Real-time progress bar & log streaming
  • Upload history tracking
"""

import os
import sys
import time
import json
import threading
import asyncio
import logging
import copy
from datetime import datetime, timedelta

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# ── Import core functions from tiktok_gui ──
sys.path.insert(0, r"c:\tiktok_automation")
from tiktok_gui import (
    open_chrome_debug, connect_selenium, navigate_upload_page,
    do_upload_file, do_post_video,
    load_db, save_db, get_uploaded_videos, mark_uploaded,
    DB_FILE
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8204668233:AAHL9gFSJaCPEuUlDENwI4xYkk-IKmOw_kU"
ALLOWED_USER_IDS = []  # Kosong = semua user boleh

APP_DIR = r"C:\tiktok_automation"

DEFAULTS = {
    # Video settings
    "folder": os.path.join(APP_DIR, "Output"),
    "start_from": 0,       # 0-indexed
    "upload_count": 20,
    # Product settings
    "product_radio": "",
    "product_title": "beli sebelum promonya habis",
    "deskripsi": "Segera Try out di speedu.online",
    "add_sound": False,
    # Schedule settings
    "schedule_date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
    "schedule_hour": "01",
    "schedule_minute": "00",
    "interval": 60,
    # Chrome settings
    "user_data_dir": os.path.join(APP_DIR, "user_data", "1"),
    "debug_port": "9222",
}

# Per-user state
user_settings = {}
user_locks = {}
log_buffers = {}
progress_info = {}   # uid -> {current, total, status, video_name}
stop_events = {}

# Conversation states
SETTING_MENU = 0

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv")


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def get_cfg(uid):
    if uid not in user_settings:
        user_settings[uid] = copy.deepcopy(DEFAULTS)
        # Refresh date default
        user_settings[uid]["schedule_date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return user_settings[uid]


def is_allowed(uid):
    return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS


def get_lock(uid):
    if uid not in user_locks:
        user_locks[uid] = threading.Lock()
    return user_locks[uid]


def list_videos(folder):
    """List video files from folder, sorted by modification time."""
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(
        [f for f in os.listdir(folder) if f.lower().endswith(VIDEO_EXTS)],
        key=lambda x: os.path.getmtime(os.path.join(folder, x))
    )


# ═══════════════════════════════════════════════════════════════
#  LOG SYSTEM
# ═══════════════════════════════════════════════════════════════
MAX_LOG_LINES = 30


def make_log_fn(uid):
    """Returns a log function for thread-safe logging."""
    log_buffers[uid] = []

    def log_fn(msg, tag=None):
        ts = datetime.now().strftime("%H:%M:%S")
        icon = {"success": "✅", "error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(tag, "▪️")
        # Auto-detect tag from content
        if not tag:
            if "✓" in msg or "berhasil" in msg.lower():
                icon = "✅"
            elif "⚠" in msg or "gagal" in msg.lower():
                icon = "⚠️"
            elif "❌" in msg or "error" in msg.lower():
                icon = "❌"
        line = f"[{ts}] {icon} {msg}"
        log_buffers[uid].append(line)
        if len(log_buffers[uid]) > 200:
            log_buffers[uid] = log_buffers[uid][-200:]

    return log_fn


def progress_bar(current, total, width=15):
    """Unicode progress bar."""
    if total == 0:
        pct = 0
    else:
        pct = int(current / total * 100)
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled), pct


def build_progress_text(uid):
    """Build progress message."""
    pi = progress_info.get(uid, {"current": 0, "total": 0, "status": "idle", "video_name": ""})
    bar, pct = progress_bar(pi["current"], pi["total"])
    lines = [
        "📊 <b>Upload Progress</b>\n",
        f"  {bar} <b>{pct}%</b>  ({pi['current']}/{pi['total']})",
        f"  📹 <i>{pi.get('video_name', '-')}</i>",
        f"  📌 Status: <b>{pi['status']}</b>",
    ]
    return "\n".join(lines)


def build_log_text(uid, n=MAX_LOG_LINES):
    """Build latest log lines message."""
    lines = log_buffers.get(uid, [])
    recent = lines[-n:] if lines else ["<i>Belum ada log...</i>"]
    safe = []
    for l in recent:
        l = l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe.append(f"<code>{l}</code>")
    return "📝 <b>Live Log</b>\n\n" + "\n".join(safe)


# ═══════════════════════════════════════════════════════════════
#  LIVE UPDATER (asyncio task)
# ═══════════════════════════════════════════════════════════════
async def live_updater(bot, chat_id, progress_msg_id, log_msg_id, uid, stop_evt):
    """Periodically edits progress + log messages."""
    last_prog = ""
    last_log = ""

    while not stop_evt.is_set():
        # Progress
        prog_text = build_progress_text(uid)
        if prog_text != last_prog:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=progress_msg_id,
                    text=prog_text[:4096], parse_mode=ParseMode.HTML
                )
                last_prog = prog_text
            except Exception:
                pass

        # Log
        log_text = build_log_text(uid)
        if log_text != last_log:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=log_msg_id,
                    text=log_text[:4096], parse_mode=ParseMode.HTML
                )
                last_log = log_text
            except Exception:
                pass

        await asyncio.sleep(3)

    # Final updates
    prog_text = build_progress_text(uid) + "\n\n✅ <b>Proses selesai.</b>"
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=progress_msg_id,
            text=prog_text[:4096], parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    log_text = build_log_text(uid)
    log_text += "\n\n✅ <b>Proses selesai.</b>"
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=log_msg_id,
            text=log_text[:4096], parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Mulai Upload", callback_data="act_upload")],
        [InlineKeyboardButton("📂 Video Settings", callback_data="menu_video"),
         InlineKeyboardButton("🏷️ Product Settings", callback_data="menu_product")],
        [InlineKeyboardButton("📅 Schedule Settings", callback_data="menu_schedule"),
         InlineKeyboardButton("🌐 Chrome Settings", callback_data="menu_chrome")],
        [InlineKeyboardButton("📊 Progress", callback_data="act_progress"),
         InlineKeyboardButton("📝 Log", callback_data="act_log")],
        [InlineKeyboardButton("📋 Upload History", callback_data="act_history")],
        [InlineKeyboardButton("⏹ Stop", callback_data="act_stop")],
    ])


def summary_text(cfg):
    """Build a config summary."""
    folder_name = os.path.basename(cfg["folder"]) if cfg["folder"] else "-"
    videos = list_videos(cfg["folder"])
    n_vids = len(videos)
    return (
        "🚀 <b>TikTok Multi-Upload Scheduler Bot</b>\n\n"
        f"📂 Folder: <code>{folder_name}</code> ({n_vids} video)\n"
        f"📹 Mulai dari: <b>#{cfg['start_from']+1}</b>  •  "
        f"Jumlah: <b>{cfg['upload_count']}</b>\n"
        f"🏷️ Produk: <code>{cfg['product_radio'][:30] or '-'}</code>\n"
        f"📝 Judul: <code>{cfg['product_title'][:30]}</code>\n"
        f"💬 Deskripsi: <code>{cfg['deskripsi'][:40]}...</code>\n"
        f"🔊 Sound: <b>{'✅ Ya' if cfg['add_sound'] else '❌ Tidak'}</b>\n"
        f"📅 Schedule: <b>{cfg['schedule_date']} {cfg['schedule_hour']}:{cfg['schedule_minute']}</b>\n"
        f"⏱ Interval: <b>{cfg['interval']} menit</b>\n"
        f"🌐 Port: <b>{cfg['debug_port']}</b>\n"
    )


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    cfg = get_cfg(update.effective_user.id)
    await update.message.reply_text(
        summary_text(cfg) + "\nPilih aksi:",
        reply_markup=main_menu_kb(),
        parse_mode=ParseMode.HTML
    )


# ═══════════════════════════════════════════════════════════════
#  SETTINGS SUB-MENUS
# ═══════════════════════════════════════════════════════════════

# ── Video Settings ──
def video_settings_text(cfg):
    folder = cfg["folder"]
    videos = list_videos(folder)
    n = len(videos)
    # Show first few videos
    preview = ""
    if videos:
        db = load_db()
        folder_name = os.path.basename(folder)
        uploaded = get_uploaded_videos(folder_name, db)
        for i, v in enumerate(videos[:10]):
            mark = "✅" if v in uploaded else "⬜"
            sel = " 👈" if i == cfg["start_from"] else ""
            preview += f"  {i+1}. {mark} <code>{v}</code>{sel}\n"
        if n > 10:
            preview += f"  ... +{n-10} lainnya\n"

    return (
        "📂 <b>Video Settings</b>\n\n"
        f"📁 Folder: <code>{folder}</code>\n"
        f"📹 Total video: <b>{n}</b>\n"
        f"▶️ Mulai dari: <b>#{cfg['start_from']+1}</b>\n"
        f"🔢 Jumlah upload: <b>{cfg['upload_count']}</b>\n\n"
        f"📋 <b>Daftar Video:</b>\n{preview or '<i>Folder kosong</i>'}\n"
        "Kirim nomor setting untuk ubah:\n"
        "1 = Folder  •  2 = Mulai dari  •  3 = Jumlah upload\n"
        "Atau /cancel untuk kembali"
    )

def video_settings_kb(cfg):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Video", callback_data="vs_refresh")],
        [InlineKeyboardButton("🏠 Menu", callback_data="back_menu")],
    ])


# ── Product Settings ──
def product_settings_text(cfg):
    return (
        "🏷️ <b>Product Settings</b>\n\n"
        f"1️⃣ Nama Produk (Radio): <code>{cfg['product_radio'] or '<belum diisi>'}</code>\n"
        f"2️⃣ Judul Produk: <code>{cfg['product_title']}</code>\n"
        f"3️⃣ Deskripsi: <code>{cfg['deskripsi'][:80]}</code>\n"
        f"4️⃣ Sound Favorites: <b>{'✅ Ya' if cfg['add_sound'] else '❌ Tidak'}</b>\n\n"
        "Kirim nomor (1-3) untuk ubah, atau gunakan tombol.\n"
        "/cancel untuk kembali"
    )

def product_settings_kb(cfg):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'🔊 Sound: ON' if cfg['add_sound'] else '🔇 Sound: OFF'}",
            callback_data="ps_toggle_sound"
        )],
        [InlineKeyboardButton("🏠 Menu", callback_data="back_menu")],
    ])


# ── Schedule Settings ──
def schedule_settings_text(cfg):
    return (
        "📅 <b>Schedule Settings</b>\n\n"
        f"1️⃣ Tanggal: <code>{cfg['schedule_date']}</code>\n"
        f"2️⃣ Jam: <code>{cfg['schedule_hour']}:{cfg['schedule_minute']}</code>\n"
        f"3️⃣ Interval: <b>{cfg['interval']} menit</b>\n\n"
        "Kirim nomor (1-3) untuk ubah.\n"
        "/cancel untuk kembali"
    )

def schedule_settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Menu", callback_data="back_menu")],
    ])


# ── Chrome Settings ──
def chrome_settings_text(cfg):
    return (
        "🌐 <b>Chrome Settings</b>\n\n"
        f"1️⃣ User Data Dir: <code>{cfg['user_data_dir']}</code>\n"
        f"2️⃣ Debug Port: <b>{cfg['debug_port']}</b>\n\n"
        "Kirim nomor (1-2) untuk ubah.\n"
        "/cancel untuk kembali"
    )

def chrome_settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Menu", callback_data="back_menu")],
    ])


# ═══════════════════════════════════════════════════════════════
#  SETTINGS CONVERSATION HANDLER
# ═══════════════════════════════════════════════════════════════
async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return ConversationHandler.END
    cfg = get_cfg(update.effective_user.id)
    await update.message.reply_text(
        summary_text(cfg) + "\nPilih kategori setting:",
        reply_markup=main_menu_kb(),
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END


async def settings_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle text input for settings."""
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    txt = update.message.text.strip()
    menu = ctx.user_data.get("current_menu")
    pending = ctx.user_data.get("setting_pending")

    # ── Receiving a value for a pending field ──
    if pending:
        if pending == "folder":
            if os.path.isdir(txt):
                cfg["folder"] = txt
                cfg["start_from"] = 0
                ctx.user_data["setting_pending"] = None
                await update.message.reply_text(
                    f"✅ Folder diubah!\n\n{video_settings_text(cfg)}",
                    reply_markup=video_settings_kb(cfg), parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text("❌ Folder tidak valid. Kirim path yang benar:")
            return SETTING_MENU

        elif pending == "start_from":
            try:
                val = int(txt) - 1
                videos = list_videos(cfg["folder"])
                if 0 <= val < len(videos):
                    cfg["start_from"] = val
                    ctx.user_data["setting_pending"] = None
                    await update.message.reply_text(
                        f"✅ Mulai dari video #{val+1}\n\n{video_settings_text(cfg)}",
                        reply_markup=video_settings_kb(cfg), parse_mode=ParseMode.HTML)
                else:
                    await update.message.reply_text(f"❌ Nomor tidak valid (1-{len(videos)})")
            except ValueError:
                await update.message.reply_text("❌ Kirim angka")
            return SETTING_MENU

        elif pending == "upload_count":
            try:
                cfg["upload_count"] = int(txt)
                ctx.user_data["setting_pending"] = None
                await update.message.reply_text(
                    f"✅ Jumlah upload: {cfg['upload_count']}\n\n{video_settings_text(cfg)}",
                    reply_markup=video_settings_kb(cfg), parse_mode=ParseMode.HTML)
            except ValueError:
                await update.message.reply_text("❌ Kirim angka")
            return SETTING_MENU

        elif pending == "product_radio":
            cfg["product_radio"] = txt
            ctx.user_data["setting_pending"] = None
            await update.message.reply_text(
                f"✅ Nama produk diubah!\n\n{product_settings_text(cfg)}",
                reply_markup=product_settings_kb(cfg), parse_mode=ParseMode.HTML)
            return SETTING_MENU

        elif pending == "product_title":
            cfg["product_title"] = txt
            ctx.user_data["setting_pending"] = None
            await update.message.reply_text(
                f"✅ Judul produk diubah!\n\n{product_settings_text(cfg)}",
                reply_markup=product_settings_kb(cfg), parse_mode=ParseMode.HTML)
            return SETTING_MENU

        elif pending == "deskripsi":
            cfg["deskripsi"] = txt
            ctx.user_data["setting_pending"] = None
            await update.message.reply_text(
                f"✅ Deskripsi diubah!\n\n{product_settings_text(cfg)}",
                reply_markup=product_settings_kb(cfg), parse_mode=ParseMode.HTML)
            return SETTING_MENU

        elif pending == "schedule_date":
            try:
                datetime.strptime(txt, "%Y-%m-%d")
                cfg["schedule_date"] = txt
                ctx.user_data["setting_pending"] = None
                await update.message.reply_text(
                    f"✅ Tanggal diubah!\n\n{schedule_settings_text(cfg)}",
                    reply_markup=schedule_settings_kb(), parse_mode=ParseMode.HTML)
            except ValueError:
                await update.message.reply_text("❌ Format tanggal: YYYY-MM-DD")
            return SETTING_MENU

        elif pending == "schedule_time":
            parts = txt.replace(".", ":").split(":")
            if len(parts) == 2:
                cfg["schedule_hour"] = parts[0].zfill(2)
                cfg["schedule_minute"] = parts[1].zfill(2)
                ctx.user_data["setting_pending"] = None
                await update.message.reply_text(
                    f"✅ Jam diubah!\n\n{schedule_settings_text(cfg)}",
                    reply_markup=schedule_settings_kb(), parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text("❌ Format: HH:MM")
            return SETTING_MENU

        elif pending == "interval":
            try:
                cfg["interval"] = int(txt)
                ctx.user_data["setting_pending"] = None
                await update.message.reply_text(
                    f"✅ Interval: {cfg['interval']} menit\n\n{schedule_settings_text(cfg)}",
                    reply_markup=schedule_settings_kb(), parse_mode=ParseMode.HTML)
            except ValueError:
                await update.message.reply_text("❌ Kirim angka (menit)")
            return SETTING_MENU

        elif pending == "user_data_dir":
            cfg["user_data_dir"] = txt
            ctx.user_data["setting_pending"] = None
            await update.message.reply_text(
                f"✅ User data dir diubah!\n\n{chrome_settings_text(cfg)}",
                reply_markup=chrome_settings_kb(), parse_mode=ParseMode.HTML)
            return SETTING_MENU

        elif pending == "debug_port":
            cfg["debug_port"] = txt
            ctx.user_data["setting_pending"] = None
            await update.message.reply_text(
                f"✅ Port diubah!\n\n{chrome_settings_text(cfg)}",
                reply_markup=chrome_settings_kb(), parse_mode=ParseMode.HTML)
            return SETTING_MENU

    # ── Number selection based on current menu ──
    if menu == "video":
        prompts = {
            "1": ("folder", "📁 Kirim path folder video:"),
            "2": ("start_from", "▶️ Mulai dari video ke-? (kirim nomor):"),
            "3": ("upload_count", "🔢 Kirim jumlah upload:"),
        }
        if txt in prompts:
            field, prompt = prompts[txt]
            ctx.user_data["setting_pending"] = field
            await update.message.reply_text(prompt)
            return SETTING_MENU

    elif menu == "product":
        prompts = {
            "1": ("product_radio", "🏷️ Kirim nama produk (radio name attribute):"),
            "2": ("product_title", "📋 Kirim judul produk:"),
            "3": ("deskripsi", "💬 Kirim deskripsi TikTok:"),
        }
        if txt in prompts:
            field, prompt = prompts[txt]
            ctx.user_data["setting_pending"] = field
            await update.message.reply_text(prompt)
            return SETTING_MENU

    elif menu == "schedule":
        prompts = {
            "1": ("schedule_date", "📅 Kirim tanggal (YYYY-MM-DD):"),
            "2": ("schedule_time", "⏰ Kirim jam (HH:MM):"),
            "3": ("interval", "⏱ Kirim interval (menit):"),
        }
        if txt in prompts:
            field, prompt = prompts[txt]
            ctx.user_data["setting_pending"] = field
            await update.message.reply_text(prompt)
            return SETTING_MENU

    elif menu == "chrome":
        prompts = {
            "1": ("user_data_dir", "📁 Kirim path user data Chrome:"),
            "2": ("debug_port", "🌐 Kirim debug port:"),
        }
        if txt in prompts:
            field, prompt = prompts[txt]
            ctx.user_data["setting_pending"] = field
            await update.message.reply_text(prompt)
            return SETTING_MENU

    await update.message.reply_text("Kirim nomor yang sesuai menu, atau /cancel untuk kembali.")
    return SETTING_MENU


async def settings_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks within settings menus."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    cfg = get_cfg(uid)
    data = q.data

    # ── Sub-menu navigation ──
    if data == "menu_video":
        ctx.user_data["current_menu"] = "video"
        ctx.user_data["setting_pending"] = None
        await q.edit_message_text(
            video_settings_text(cfg), reply_markup=video_settings_kb(cfg),
            parse_mode=ParseMode.HTML)
        return SETTING_MENU

    if data == "menu_product":
        ctx.user_data["current_menu"] = "product"
        ctx.user_data["setting_pending"] = None
        await q.edit_message_text(
            product_settings_text(cfg), reply_markup=product_settings_kb(cfg),
            parse_mode=ParseMode.HTML)
        return SETTING_MENU

    if data == "menu_schedule":
        ctx.user_data["current_menu"] = "schedule"
        ctx.user_data["setting_pending"] = None
        await q.edit_message_text(
            schedule_settings_text(cfg), reply_markup=schedule_settings_kb(),
            parse_mode=ParseMode.HTML)
        return SETTING_MENU

    if data == "menu_chrome":
        ctx.user_data["current_menu"] = "chrome"
        ctx.user_data["setting_pending"] = None
        await q.edit_message_text(
            chrome_settings_text(cfg), reply_markup=chrome_settings_kb(),
            parse_mode=ParseMode.HTML)
        return SETTING_MENU

    if data == "vs_refresh":
        await q.edit_message_text(
            video_settings_text(cfg), reply_markup=video_settings_kb(cfg),
            parse_mode=ParseMode.HTML)
        return SETTING_MENU

    if data == "ps_toggle_sound":
        cfg["add_sound"] = not cfg["add_sound"]
        await q.edit_message_text(
            product_settings_text(cfg), reply_markup=product_settings_kb(cfg),
            parse_mode=ParseMode.HTML)
        return SETTING_MENU

    if data == "back_menu":
        ctx.user_data["current_menu"] = None
        ctx.user_data["setting_pending"] = None
        await q.edit_message_text(
            summary_text(cfg) + "\nPilih aksi:",
            reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)
        return ConversationHandler.END


async def cancel_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("current_menu", None)
    ctx.user_data.pop("setting_pending", None)
    cfg = get_cfg(update.effective_user.id)
    await update.message.reply_text(
        "⚙️ Kembali ke menu.\n\n" + summary_text(cfg),
        reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#  UPLOAD — start automation
# ═══════════════════════════════════════════════════════════════
async def start_upload(bot, chat_id, uid, cfg):
    """Launch upload automation in a background thread."""
    lock = get_lock(uid)
    if not lock.acquire(blocking=False):
        await bot.send_message(chat_id, "⏳ Proses lain masih berjalan. Tunggu atau /stop dulu.")
        return

    # Validate
    folder = cfg["folder"]
    if not folder or not os.path.isdir(folder):
        lock.release()
        await bot.send_message(chat_id, "❌ Folder video tidak valid!")
        return

    if not cfg["product_radio"]:
        lock.release()
        await bot.send_message(chat_id, "❌ Nama Produk (Radio) belum diisi! Atur di Product Settings.")
        return

    log_fn = make_log_fn(uid)
    stop_evt = threading.Event()
    stop_events[uid] = stop_evt
    progress_info[uid] = {"current": 0, "total": 0, "status": "Starting...", "video_name": "-"}

    # Send progress + log messages
    progress_msg = await bot.send_message(
        chat_id, "📊 <b>Upload Progress</b>\n\n<i>Memulai...</i>",
        parse_mode=ParseMode.HTML)
    log_msg = await bot.send_message(
        chat_id, "📝 <b>Live Log</b>\n\n<i>Memulai...</i>",
        parse_mode=ParseMode.HTML)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹ Stop", callback_data="act_stop")],
        [InlineKeyboardButton("📊 Progress", callback_data="act_progress"),
         InlineKeyboardButton("📝 Log", callback_data="act_log")],
    ])
    await bot.send_message(chat_id, "🚀 <b>Upload dimulai!</b>", reply_markup=kb, parse_mode=ParseMode.HTML)

    # Live updater
    updater_stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    loop.create_task(
        live_updater(bot, chat_id, progress_msg.message_id, log_msg.message_id,
                     uid, updater_stop)
    )

    def run_upload():
        chrome_proc = None
        driver = None
        try:
            folder_name = os.path.basename(folder)
            start_from = cfg["start_from"]
            count = cfg["upload_count"]
            product_radio = cfg["product_radio"]
            product_title = cfg["product_title"]
            add_sound = cfg["add_sound"]
            deskripsi = cfg["deskripsi"]
            hour = int(cfg["schedule_hour"])
            minute = int(cfg["schedule_minute"])
            date_str = cfg["schedule_date"]
            interval = cfg["interval"]
            userdata = cfg["user_data_dir"]
            port = cfg["debug_port"]

            start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)

            # List videos
            all_videos = list_videos(folder)
            log_fn(f"📂 Folder: {folder} ({len(all_videos)} video)", "info")

            # Filter
            db = load_db()
            uploaded = get_uploaded_videos(folder_name, db)
            available = all_videos[start_from:]
            to_upload = [v for v in available if v not in uploaded][:count]

            if not to_upload:
                log_fn("❌ Tidak ada video untuk diupload!", "error")
                progress_info[uid]["status"] = "Tidak ada video"
                return

            total = len(to_upload)
            log_fn(f"🎬 {total} video akan diupload", "info")
            progress_info[uid]["total"] = total

            # Open Chrome
            log_fn(f"🌐 Membuka Chrome (port {port})...", "info")
            progress_info[uid]["status"] = "Opening Chrome..."
            chrome_proc = open_chrome_debug(userdata, port)
            time.sleep(2)
            driver = connect_selenium(port)
            log_fn("✓ Chrome terhubung!", "success")

            # Upload loop
            for idx, video_name in enumerate(to_upload):
                if stop_evt.is_set():
                    log_fn("⏹ Dihentikan oleh user", "warn")
                    break

                video_path = os.path.join(folder, video_name)
                current_dt = start_dt + timedelta(minutes=interval * idx)

                progress_info[uid].update({
                    "current": idx,
                    "video_name": video_name,
                    "status": f"Uploading {idx+1}/{total}"
                })

                log_fn(f"\n{'═'*40}", "info")
                log_fn(f"📹 [{idx+1}/{total}] {video_name}", "info")
                log_fn(f"⏰ Schedule: {current_dt.strftime('%Y-%m-%d %H:%M')}", "info")
                log_fn(f"📝 Deskripsi: {deskripsi[:50]}...", "info")

                try:
                    log_fn("Navigasi ke halaman upload baru...", "info")
                    navigate_upload_page(driver, force=(idx > 0))
                    time.sleep(3)

                    do_upload_file(driver, video_path, log_fn)
                    time.sleep(5)

                    do_post_video(driver, deskripsi, product_radio, product_title,
                                 log_fn, current_dt, stop_evt, add_sound=add_sound)

                    mark_uploaded(folder_name, video_name, db)
                    log_fn(f"✓ {video_name} berhasil di-schedule!", "success")

                except Exception as e:
                    log_fn(f"❌ Error pada {video_name}: {e}", "error")

                progress_info[uid]["current"] = idx + 1

                if idx < total - 1 and not stop_evt.is_set():
                    log_fn("Menunggu 10 detik...", "info")
                    time.sleep(10)

            log_fn(f"\n🎉 SELESAI! {total} video telah diproses.", "success")
            progress_info[uid]["status"] = "Selesai!"

        except Exception as e:
            log_fn(f"❌ Fatal error: {e}", "error")
            progress_info[uid]["status"] = f"Error: {e}"
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            if chrome_proc:
                try:
                    chrome_proc.terminate()
                except:
                    pass
            updater_stop.set()
            lock.release()
            stop_events.pop(uid, None)

    threading.Thread(target=run_upload, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER — main actions
# ═══════════════════════════════════════════════════════════════
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not is_allowed(uid):
        return
    data = q.data
    cfg = get_cfg(uid)

    if data == "act_upload":
        await q.edit_message_text("🚀 <b>Memulai upload...</b>", parse_mode=ParseMode.HTML)
        await start_upload(ctx.bot, q.message.chat_id, uid, cfg)
        return

    if data == "act_stop":
        evt = stop_events.get(uid)
        if evt:
            evt.set()
            await q.edit_message_text("⏹ <b>Stop diminta.</b>", parse_mode=ParseMode.HTML)
        else:
            await q.edit_message_text("ℹ️ Tidak ada proses yang berjalan.", reply_markup=main_menu_kb())
        return

    if data == "act_progress":
        text = build_progress_text(uid)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="act_progress")],
            [InlineKeyboardButton("🏠 Menu", callback_data="act_back_main")],
        ])
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if data == "act_log":
        text = build_log_text(uid)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="act_log")],
            [InlineKeyboardButton("🏠 Menu", callback_data="act_back_main")],
        ])
        await q.edit_message_text(text[:4096], reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if data == "act_history":
        db = load_db()
        if not db:
            text = "📋 <b>Upload History</b>\n\n<i>Belum ada riwayat upload.</i>"
        else:
            lines = ["📋 <b>Upload History</b>\n"]
            for folder_name, videos in db.items():
                lines.append(f"\n📁 <b>{folder_name}</b> ({len(videos)} video)")
                for i, v in enumerate(videos[-10:], 1):
                    lines.append(f"  {i}. <code>{v}</code>")
                if len(videos) > 10:
                    lines.append(f"  ... +{len(videos)-10} lainnya")
            text = "\n".join(lines)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Hapus History", callback_data="act_clear_history")],
            [InlineKeyboardButton("🏠 Menu", callback_data="act_back_main")],
        ])
        await q.edit_message_text(text[:4096], reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if data == "act_clear_history":
        save_db({})
        await q.edit_message_text(
            "🗑 <b>Upload history dihapus!</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="act_back_main")]
            ]),
            parse_mode=ParseMode.HTML
        )
        return

    if data == "act_back_main":
        await q.edit_message_text(
            summary_text(cfg) + "\nPilih aksi:",
            reply_markup=main_menu_kb(),
            parse_mode=ParseMode.HTML
        )
        return

    # ── Sub-menu navigation (also handled here for non-conversation flow) ──
    if data in ("menu_video", "menu_product", "menu_schedule", "menu_chrome",
                "vs_refresh", "ps_toggle_sound", "back_menu"):
        # Redirect to conversation handler
        ctx.user_data["current_menu"] = {
            "menu_video": "video",
            "menu_product": "product",
            "menu_schedule": "schedule",
            "menu_chrome": "chrome",
        }.get(data, ctx.user_data.get("current_menu"))

        if data == "menu_video" or data == "vs_refresh":
            ctx.user_data["current_menu"] = "video"
            ctx.user_data["setting_pending"] = None
            await q.edit_message_text(
                video_settings_text(cfg), reply_markup=video_settings_kb(cfg),
                parse_mode=ParseMode.HTML)
            return

        if data == "menu_product":
            ctx.user_data["current_menu"] = "product"
            ctx.user_data["setting_pending"] = None
            await q.edit_message_text(
                product_settings_text(cfg), reply_markup=product_settings_kb(cfg),
                parse_mode=ParseMode.HTML)
            return

        if data == "menu_schedule":
            ctx.user_data["current_menu"] = "schedule"
            ctx.user_data["setting_pending"] = None
            await q.edit_message_text(
                schedule_settings_text(cfg), reply_markup=schedule_settings_kb(),
                parse_mode=ParseMode.HTML)
            return

        if data == "menu_chrome":
            ctx.user_data["current_menu"] = "chrome"
            ctx.user_data["setting_pending"] = None
            await q.edit_message_text(
                chrome_settings_text(cfg), reply_markup=chrome_settings_kb(),
                parse_mode=ParseMode.HTML)
            return

        if data == "ps_toggle_sound":
            cfg["add_sound"] = not cfg["add_sound"]
            await q.edit_message_text(
                product_settings_text(cfg), reply_markup=product_settings_kb(cfg),
                parse_mode=ParseMode.HTML)
            return

        if data == "back_menu":
            await q.edit_message_text(
                summary_text(cfg) + "\nPilih aksi:",
                reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)
            return


# ═══════════════════════════════════════════════════════════════
#  DIRECT COMMANDS
# ═══════════════════════════════════════════════════════════════
async def cmd_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    await update.message.reply_text("🚀 <b>Memulai upload...</b>", parse_mode=ParseMode.HTML)
    await start_upload(ctx.bot, update.message.chat_id, uid, cfg)


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    evt = stop_events.get(uid)
    if evt:
        evt.set()
        await update.message.reply_text("⏹ <b>Stop diminta.</b>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("ℹ️ Tidak ada proses yang berjalan.")


async def cmd_progress(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = build_progress_text(uid)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="act_progress")],
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def cmd_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = build_log_text(uid)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="act_log")],
    ])
    await update.message.reply_text(text[:4096], reply_markup=kb, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>TikTok Upload Bot — Panduan</b>\n\n"
        "<b>Perintah:</b>\n"
        "/start — Menu utama\n"
        "/upload — Mulai upload\n"
        "/stop — Hentikan proses\n"
        "/progress — Lihat progress\n"
        "/log — Lihat log terakhir\n"
        "/settings — Pengaturan\n"
        "/help — Panduan ini\n\n"
        "<b>Setting yang tersedia:</b>\n"
        "📂 <b>Video:</b> folder, mulai dari, jumlah upload\n"
        "🏷️ <b>Product:</b> nama produk radio, judul, deskripsi, sound\n"
        "📅 <b>Schedule:</b> tanggal, jam, interval\n"
        "🌐 <b>Chrome:</b> user data dir, debug port\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
async def post_init(application):
    """Register menu commands visible in Telegram UI."""
    await application.bot.set_my_commands([
        BotCommand("start", "📋 Menu utama"),
        BotCommand("upload", "▶️ Mulai upload"),
        BotCommand("stop", "⏹ Hentikan proses"),
        BotCommand("progress", "📊 Lihat progress"),
        BotCommand("log", "📝 Log terakhir"),
        BotCommand("settings", "⚙️ Pengaturan"),
        BotCommand("help", "📖 Panduan"),
    ])


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Settings conversation — catches text input for settings + inline buttons
    settings_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(settings_callback,
                                 pattern="^(menu_video|menu_product|menu_schedule|menu_chrome)$"),
        ],
        states={
            SETTING_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_text_input),
                CallbackQueryHandler(settings_callback,
                                     pattern="^(menu_video|menu_product|menu_schedule|menu_chrome|"
                                             "vs_refresh|ps_toggle_sound|back_menu)$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_settings)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(settings_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CommandHandler("upload", cmd_upload))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("progress", cmd_progress))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🚀 TikTok Upload Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
