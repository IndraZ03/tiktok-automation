"""
⚡ GROK VIDEO AUTOMATION — Telegram Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mirrors grok_gui.py AutomationEngine functionality via Telegram.
Features:
  • Full configuration: tabs, cycles, port, headless, image mode, dirs, prompts
  • Real-time log streaming
  • Tab monitor with progress bars
  • Latest output file viewer
  • Multiple prompts support
"""

import os
import sys
import time
import glob
import re
import json
import queue
import threading
import asyncio
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# ── Import AutomationEngine from grok_gui ──
sys.path.insert(0, r"c:\tiktok_automation")
from grok_gui import AutomationEngine, DEFAULT_PROMPT_1, DEFAULT_PROMPT_2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8620226581:AAG_AZ8ekcG3WY-a3HZnRpJscHKQYOJRRWY"  # Ganti token
ALLOWED_USER_IDS = []  # Kosong = semua user boleh

APP_DIR = r"C:\tiktok_automation"

DEFAULTS = {
    "n_tabs": 5,
    "n_cycles": 3,
    "debug_port": 9222,
    "headless": False,
    "alternate_image": True,    # True = selang-seling, False = lihat use_image_all
    "use_image_all": False,     # Jika alternate_image False, apakah semua pakai image
    "output_dir": os.path.join(APP_DIR, "Output"),
    "tab_bahan_dir": os.path.join(APP_DIR, "tab_bahan"),
    "save_local": True,
    "user_data_dir": os.path.join(APP_DIR, "user_data", "1"),
    "prompts": [DEFAULT_PROMPT_1, DEFAULT_PROMPT_2],
}

# Per-user state
user_settings = {}
user_locks = {}
log_buffers = {}
tab_statuses = {}   # uid -> {tab_idx: {pct, status}}
cycle_info = {}     # uid -> {"cycle": n, "done": bool}
stop_events = {}    # uid -> threading.Event

# Conversation states
(
    SETTING_MENU, SET_TABS, SET_CYCLES, SET_PORT, SET_OUTPUT_DIR,
    SET_BAHAN_DIR, SET_USER_DATA_DIR, ADD_PROMPT, EDIT_PROMPT_IDX,
    EDIT_PROMPT_TEXT
) = range(10)

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def get_cfg(uid):
    if uid not in user_settings:
        import copy
        user_settings[uid] = copy.deepcopy(DEFAULTS)
    return user_settings[uid]


def is_allowed(uid):
    return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS


def get_lock(uid):
    if uid not in user_locks:
        user_locks[uid] = threading.Lock()
    return user_locks[uid]


# ═══════════════════════════════════════════════════════════════
#  LOG SYSTEM
# ═══════════════════════════════════════════════════════════════
MAX_LOG_LINES = 30


def make_log_queue(uid):
    """Returns (log_q, status_q) for use by AutomationEngine."""
    log_buffers[uid] = []
    tab_statuses[uid] = {}
    cycle_info[uid] = {"cycle": 0, "done": False}
    return queue.Queue(), queue.Queue()


def drain_queues(uid, log_q, stat_q):
    """Drain queues into per-user buffers. Call periodically."""
    # Log queue
    while not log_q.empty():
        try:
            msg = log_q.get_nowait()
            log_buffers.setdefault(uid, []).append(msg)
            if len(log_buffers[uid]) > 200:
                log_buffers[uid] = log_buffers[uid][-200:]
        except queue.Empty:
            break

    # Status queue
    while not stat_q.empty():
        try:
            data = stat_q.get_nowait()
            if "tab" in data:
                tab_statuses.setdefault(uid, {})[data["tab"]] = {
                    "pct": data.get("pct", 0),
                    "status": data.get("status", "idle")
                }
            if "cycle" in data:
                cycle_info.setdefault(uid, {})["cycle"] = data["cycle"]
            if "done" in data:
                cycle_info.setdefault(uid, {})["done"] = True
        except queue.Empty:
            break


# ═══════════════════════════════════════════════════════════════
#  STATUS EMOJI MAP
# ═══════════════════════════════════════════════════════════════
STATUS_ICON = {
    "idle": "⚪",
    "generating": "🟡",
    "waiting": "🔵",
    "downloading": "🟢",
    "success": "✅",
    "error": "❌",
    "stopped": "🛑",
    "login": "🔐",
}


def progress_bar(pct, width=10):
    """Unicode progress bar."""
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def build_tab_monitor_text(uid):
    """Build tab monitor message."""
    tabs = tab_statuses.get(uid, {})
    ci = cycle_info.get(uid, {"cycle": 0, "done": False})

    lines = [f"📊 <b>Tab Monitor</b>  •  Siklus: <b>{ci['cycle']}</b>\n"]

    if not tabs:
        lines.append("<i>Belum ada data tab...</i>")
    else:
        for idx in sorted(tabs.keys()):
            t = tabs[idx]
            icon = STATUS_ICON.get(t["status"], "⚪")
            bar = progress_bar(t["pct"])
            lines.append(
                f"  Tab {idx+1}: {icon} {bar} <b>{t['pct']}%</b> — <i>{t['status']}</i>"
            )

    if ci.get("done"):
        lines.append("\n🎉 <b>SEMUA SIKLUS SELESAI!</b>")

    return "\n".join(lines)


def build_log_text(uid, n=MAX_LOG_LINES):
    """Build latest log lines message."""
    lines = log_buffers.get(uid, [])
    recent = lines[-n:] if lines else ["<i>Belum ada log...</i>"]
    # Escape HTML
    safe = []
    for l in recent:
        l = l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe.append(f"<code>{l}</code>")
    return "📝 <b>Live Log</b>\n\n" + "\n".join(safe)


# ═══════════════════════════════════════════════════════════════
#  LIVE LOG UPDATER (runs in asyncio)
# ═══════════════════════════════════════════════════════════════
async def live_updater(bot, chat_id, log_msg_id, monitor_msg_id, uid, log_q, stat_q, stop_evt):
    """
    Periodically drains queues and edits two messages:
      1. Log message (latest log lines)
      2. Monitor message (tab status + progress)
    """
    last_log_text = ""
    last_mon_text = ""

    while not stop_evt.is_set():
        drain_queues(uid, log_q, stat_q)

        # Update log message
        log_text = build_log_text(uid)
        if log_text != last_log_text:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=log_msg_id,
                    text=log_text[:4096], parse_mode=ParseMode.HTML
                )
                last_log_text = log_text
            except Exception:
                pass

        # Update monitor message
        mon_text = build_tab_monitor_text(uid)
        if mon_text != last_mon_text:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=monitor_msg_id,
                    text=mon_text[:4096], parse_mode=ParseMode.HTML
                )
                last_mon_text = mon_text
            except Exception:
                pass

        await asyncio.sleep(3)

    # Final drain
    drain_queues(uid, log_q, stat_q)

    # Final log update
    log_text = build_log_text(uid)
    log_text += "\n\n✅ <b>Proses selesai.</b>"
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=log_msg_id,
            text=log_text[:4096], parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    # Final monitor update
    mon_text = build_tab_monitor_text(uid)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=monitor_msg_id,
            text=mon_text[:4096], parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Mulai Generate", callback_data="act_generate")],
        [InlineKeyboardButton("📊 Tab Monitor", callback_data="act_monitor"),
         InlineKeyboardButton("📝 Log Terakhir", callback_data="act_log")],
        [InlineKeyboardButton("📂 Output Terbaru", callback_data="act_output")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="act_settings")],
        [InlineKeyboardButton("⏹ Stop", callback_data="act_stop")],
    ])


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    cfg = get_cfg(update.effective_user.id)
    text = (
        "⚡ <b>Grok Video Automation Bot</b>\n\n"
        "Automated multi-tab video generation via Telegram.\n\n"
        f"📁 Output: <code>{cfg['output_dir']}</code>\n"
        f"🖥 Tabs: <b>{cfg['n_tabs']}</b>  •  Siklus: <b>{cfg['n_cycles']}</b>\n"
        f"🌐 Port: <b>{cfg['debug_port']}</b>  •  Headless: <b>{'Ya' if cfg['headless'] else 'Tidak'}</b>\n"
        f"🖼 Image: <b>{'Selang-seling' if cfg['alternate_image'] else ('Semua' if cfg['use_image_all'] else 'Tidak')}</b>\n"
        f"📋 Prompts: <b>{len(cfg['prompts'])}</b>\n\n"
        "Pilih aksi:"
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  SETTINGS
# ═══════════════════════════════════════════════════════════════
def settings_text(cfg):
    img_mode = "Selang-seling" if cfg["alternate_image"] else ("Semua pakai gambar" if cfg["use_image_all"] else "Tanpa gambar")
    prompts_preview = "\n".join(
        [f"   {i+1}. <code>{p[:50]}{'...' if len(p)>50 else ''}</code>" for i, p in enumerate(cfg["prompts"])]
    )
    return (
        "⚙️ <b>Settings</b>\n\n"
        f"1️⃣ Tabs per Siklus: <b>{cfg['n_tabs']}</b>\n"
        f"2️⃣ Jumlah Siklus: <b>{cfg['n_cycles']}</b>\n"
        f"3️⃣ Debug Port: <b>{cfg['debug_port']}</b>\n"
        f"4️⃣ Headless Chrome: <b>{'✅ Ya' if cfg['headless'] else '❌ Tidak'}</b>\n"
        f"5️⃣ Mode Image: <b>{img_mode}</b>\n"
        f"6️⃣ Output Dir: <code>{cfg['output_dir']}</code>\n"
        f"7️⃣ Bahan Dir: <code>{cfg['tab_bahan_dir']}</code>\n"
        f"8️⃣ Simpan Lokal: <b>{'✅ Ya' if cfg['save_local'] else '❌ Tidak'}</b>\n"
        f"9️⃣ User Data Dir: <code>{cfg['user_data_dir']}</code>\n"
        f"🔟 Prompts ({len(cfg['prompts'])}):\n{prompts_preview}\n\n"
        "Kirim nomor (1-9) untuk ubah, atau gunakan tombol di bawah.\n"
        "Kirim /cancel untuk tutup."
    )


def settings_kb(cfg):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'☑' if cfg['headless'] else '☐'} Headless",
            callback_data="stg_toggle_headless"
        ),
         InlineKeyboardButton(
            f"{'☑' if cfg['save_local'] else '☐'} Simpan Lokal",
            callback_data="stg_toggle_local"
        )],
        [InlineKeyboardButton("🔄 Selang-seling Image", callback_data="stg_img_alternate"),
         InlineKeyboardButton("🖼 Semua Image", callback_data="stg_img_all"),
         InlineKeyboardButton("🚫 Tanpa Image", callback_data="stg_img_none")],
        [InlineKeyboardButton("➕ Tambah Prompt", callback_data="stg_add_prompt"),
         InlineKeyboardButton("✏️ Edit Prompt", callback_data="stg_edit_prompt")],
        [InlineKeyboardButton("🗑 Hapus Prompt Terakhir", callback_data="stg_del_prompt"),
         InlineKeyboardButton("🔄 Reset Default", callback_data="stg_reset")],
        [InlineKeyboardButton("❌ Tutup", callback_data="stg_close")],
    ])


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return ConversationHandler.END
    cfg = get_cfg(update.effective_user.id)
    await update.message.reply_text(
        settings_text(cfg),
        reply_markup=settings_kb(cfg),
        parse_mode=ParseMode.HTML
    )
    return SETTING_MENU


async def settings_number_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle numeric setting input (1-9) or a value for a pending field."""
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    txt = update.message.text.strip()

    # If we're waiting for a value
    pending = ctx.user_data.get("setting_pending")
    if pending:
        field_map = {
            "n_tabs": ("n_tabs", int),
            "n_cycles": ("n_cycles", int),
            "debug_port": ("debug_port", int),
            "output_dir": ("output_dir", str),
            "tab_bahan_dir": ("tab_bahan_dir", str),
            "user_data_dir": ("user_data_dir", str),
        }
        if pending in field_map:
            key, conv = field_map[pending]
            try:
                cfg[key] = conv(txt)
            except ValueError:
                await update.message.reply_text("❌ Format tidak valid. Coba lagi:")
                return SETTING_MENU
        ctx.user_data["setting_pending"] = None
        await update.message.reply_text(
            f"✅ Setting diperbarui!\n\n{settings_text(cfg)}",
            reply_markup=settings_kb(cfg),
            parse_mode=ParseMode.HTML
        )
        return SETTING_MENU

    # If we're waiting for a prompt text
    if ctx.user_data.get("awaiting_prompt"):
        cfg["prompts"].append(txt)
        ctx.user_data["awaiting_prompt"] = False
        await update.message.reply_text(
            f"✅ Prompt #{len(cfg['prompts'])} ditambahkan!\n\n{settings_text(cfg)}",
            reply_markup=settings_kb(cfg),
            parse_mode=ParseMode.HTML
        )
        return SETTING_MENU

    # If we're waiting for prompt edit index
    if ctx.user_data.get("awaiting_prompt_idx"):
        try:
            idx = int(txt) - 1
            if 0 <= idx < len(cfg["prompts"]):
                ctx.user_data["awaiting_prompt_idx"] = False
                ctx.user_data["editing_prompt_idx"] = idx
                await update.message.reply_text(
                    f"📋 Prompt #{idx+1} saat ini:\n<code>{cfg['prompts'][idx][:200]}...</code>\n\n"
                    "Kirim teks prompt baru:",
                    parse_mode=ParseMode.HTML
                )
                return SETTING_MENU
            else:
                await update.message.reply_text(f"❌ Index tidak valid (1-{len(cfg['prompts'])})")
                return SETTING_MENU
        except ValueError:
            await update.message.reply_text("❌ Kirim nomor prompt yang mau diedit")
            return SETTING_MENU

    # If we're editing a prompt text
    edit_idx = ctx.user_data.get("editing_prompt_idx")
    if edit_idx is not None:
        cfg["prompts"][edit_idx] = txt
        ctx.user_data["editing_prompt_idx"] = None
        await update.message.reply_text(
            f"✅ Prompt #{edit_idx+1} diperbarui!\n\n{settings_text(cfg)}",
            reply_markup=settings_kb(cfg),
            parse_mode=ParseMode.HTML
        )
        return SETTING_MENU

    # Number selection for settings
    prompts_map = {
        "1": ("n_tabs", "Kirim jumlah tabs per siklus (angka):"),
        "2": ("n_cycles", "Kirim jumlah siklus (angka):"),
        "3": ("debug_port", "Kirim debug port Chrome (angka):"),
        "6": ("output_dir", "Kirim path output directory:"),
        "7": ("tab_bahan_dir", "Kirim path bahan/image directory:"),
        "9": ("user_data_dir", "Kirim path user data Chrome:"),
    }

    if txt in prompts_map:
        field, prompt = prompts_map[txt]
        ctx.user_data["setting_pending"] = field
        await update.message.reply_text(prompt)
        return SETTING_MENU

    # Quick toggles via number
    if txt == "4":
        cfg["headless"] = not cfg["headless"]
        await update.message.reply_text(
            f"✅ Headless: <b>{'Ya' if cfg['headless'] else 'Tidak'}</b>\n\n{settings_text(cfg)}",
            reply_markup=settings_kb(cfg),
            parse_mode=ParseMode.HTML
        )
        return SETTING_MENU

    if txt == "5":
        await update.message.reply_text(
            "Pilih mode image dengan tombol di bawah:\n"
            "🔄 Selang-seling | 🖼 Semua | 🚫 Tanpa",
            reply_markup=settings_kb(cfg)
        )
        return SETTING_MENU

    if txt == "8":
        cfg["save_local"] = not cfg["save_local"]
        await update.message.reply_text(
            f"✅ Simpan Lokal: <b>{'Ya' if cfg['save_local'] else 'Tidak'}</b>\n\n{settings_text(cfg)}",
            reply_markup=settings_kb(cfg),
            parse_mode=ParseMode.HTML
        )
        return SETTING_MENU

    await update.message.reply_text("Kirim angka 1-9, atau /cancel")
    return SETTING_MENU


async def settings_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks within settings."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    cfg = get_cfg(uid)
    data = q.data

    if data == "stg_toggle_headless":
        cfg["headless"] = not cfg["headless"]

    elif data == "stg_toggle_local":
        cfg["save_local"] = not cfg["save_local"]

    elif data == "stg_img_alternate":
        cfg["alternate_image"] = True

    elif data == "stg_img_all":
        cfg["alternate_image"] = False
        cfg["use_image_all"] = True

    elif data == "stg_img_none":
        cfg["alternate_image"] = False
        cfg["use_image_all"] = False

    elif data == "stg_add_prompt":
        ctx.user_data["awaiting_prompt"] = True
        await q.edit_message_text("📋 Kirim teks prompt baru:")
        return SETTING_MENU

    elif data == "stg_edit_prompt":
        if not cfg["prompts"]:
            await q.edit_message_text("❌ Tidak ada prompt untuk diedit.")
            return SETTING_MENU
        ctx.user_data["awaiting_prompt_idx"] = True
        prompt_list = "\n".join(
            [f"  {i+1}. {p[:60]}..." for i, p in enumerate(cfg["prompts"])]
        )
        await q.edit_message_text(f"📋 Prompt yang ada:\n{prompt_list}\n\nKirim nomor prompt yang mau diedit:")
        return SETTING_MENU

    elif data == "stg_del_prompt":
        if len(cfg["prompts"]) > 1:
            removed = cfg["prompts"].pop()
            await q.edit_message_text(
                f"🗑 Prompt terakhir dihapus!\nSisa: {len(cfg['prompts'])} prompt\n\n{settings_text(cfg)}",
                reply_markup=settings_kb(cfg),
                parse_mode=ParseMode.HTML
            )
        else:
            await q.edit_message_text(
                "❌ Minimal harus ada 1 prompt!\n\n" + settings_text(cfg),
                reply_markup=settings_kb(cfg),
                parse_mode=ParseMode.HTML
            )
        return SETTING_MENU

    elif data == "stg_reset":
        import copy
        user_settings[uid] = copy.deepcopy(DEFAULTS)
        cfg = user_settings[uid]

    elif data == "stg_close":
        await q.edit_message_text("⚙️ Settings ditutup.")
        return ConversationHandler.END

    await q.edit_message_text(
        settings_text(cfg),
        reply_markup=settings_kb(cfg),
        parse_mode=ParseMode.HTML
    )
    return SETTING_MENU


async def cancel_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("setting_pending", None)
    ctx.user_data.pop("awaiting_prompt", None)
    ctx.user_data.pop("awaiting_prompt_idx", None)
    ctx.user_data.pop("editing_prompt_idx", None)
    await update.message.reply_text("⚙️ Settings ditutup.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#  GENERATE — start automation
# ═══════════════════════════════════════════════════════════════
async def start_generate(bot, chat_id, uid, cfg):
    """Launch AutomationEngine in a background thread with live updates."""
    lock = get_lock(uid)
    if not lock.acquire(blocking=False):
        await bot.send_message(chat_id, "⏳ Proses lain masih berjalan. Tunggu atau /stop dulu.")
        return

    log_q, stat_q = make_log_queue(uid)
    stop_evt = threading.Event()
    stop_events[uid] = stop_evt

    # Build engine config
    engine_cfg = {
        "n_tabs": cfg["n_tabs"],
        "n_cycles": cfg["n_cycles"],
        "prompts": cfg["prompts"],
        "output_dir": cfg["output_dir"],
        "tab_bahan_dir": cfg["tab_bahan_dir"],
        "debug_port": cfg["debug_port"],
        "headless": cfg["headless"],
        "alternate_image": cfg["alternate_image"],
        "use_image_all": cfg["use_image_all"],
        "save_local": cfg["save_local"],
        "user_data_dir": cfg["user_data_dir"],
        "target_url": "https://vidabot.markasai.com/generate-grok",
    }

    # Send monitor + log messages
    monitor_msg = await bot.send_message(
        chat_id,
        "📊 <b>Tab Monitor</b>\n\n<i>Memulai...</i>",
        parse_mode=ParseMode.HTML
    )
    log_msg = await bot.send_message(
        chat_id,
        "📝 <b>Live Log</b>\n\n<i>Memulai...</i>",
        parse_mode=ParseMode.HTML
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹ Stop", callback_data="act_stop")],
        [InlineKeyboardButton("📊 Monitor", callback_data="act_monitor"),
         InlineKeyboardButton("📝 Log", callback_data="act_log")],
    ])
    await bot.send_message(chat_id, "🚀 <b>Generate dimulai!</b>", reply_markup=kb, parse_mode=ParseMode.HTML)

    # Create engine
    engine = AutomationEngine(engine_cfg, log_q, stat_q)

    # Live updater coroutine
    updater_stop = asyncio.Event()

    loop = asyncio.get_event_loop()
    updater_task = loop.create_task(
        live_updater(bot, chat_id, log_msg.message_id, monitor_msg.message_id,
                     uid, log_q, stat_q, updater_stop)
    )

    def run_engine():
        try:
            engine.run()
        except Exception as e:
            log_q.put(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] Exception: {e}")
        finally:
            updater_stop.set()
            lock.release()
            stop_events.pop(uid, None)

    # Patch engine stop to use our stop_evt
    original_stop = engine._stop
    def check_stop():
        if stop_evt.is_set():
            original_stop.set()
        return original_stop.is_set()

    # Thread-safe stop bridge
    def stop_bridge():
        while not updater_stop.is_set():
            if stop_evt.is_set():
                original_stop.set()
                break
            time.sleep(0.5)

    threading.Thread(target=stop_bridge, daemon=True).start()
    threading.Thread(target=run_engine, daemon=True).start()


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

    if data == "act_generate":
        await q.edit_message_text("🚀 <b>Memulai generasi video...</b>", parse_mode=ParseMode.HTML)
        await start_generate(ctx.bot, q.message.chat_id, uid, cfg)
        return

    if data == "act_stop":
        evt = stop_events.get(uid)
        if evt:
            evt.set()
            await q.edit_message_text(
                "⏹ <b>Stop diminta.</b> Menunggu proses berhenti...",
                parse_mode=ParseMode.HTML
            )
        else:
            await q.edit_message_text(
                "ℹ️ Tidak ada proses yang berjalan.",
                reply_markup=main_menu_kb()
            )
        return

    if data == "act_monitor":
        text = build_tab_monitor_text(uid)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="act_monitor")],
            [InlineKeyboardButton("🏠 Menu", callback_data="act_menu")],
        ])
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if data == "act_log":
        text = build_log_text(uid)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="act_log")],
            [InlineKeyboardButton("🏠 Menu", callback_data="act_menu")],
        ])
        await q.edit_message_text(text[:4096], reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if data == "act_output":
        output_dir = cfg["output_dir"]
        if not os.path.isdir(output_dir):
            await q.edit_message_text(
                f"📂 Folder output belum ada:\n<code>{output_dir}</code>",
                reply_markup=main_menu_kb(),
                parse_mode=ParseMode.HTML
            )
            return
        files = sorted(
            glob.glob(os.path.join(output_dir, "*.mp4")),
            key=os.path.getmtime, reverse=True
        )
        if not files:
            await q.edit_message_text(
                "📂 <b>Output kosong.</b> Belum ada video yang dihasilkan.",
                reply_markup=main_menu_kb(),
                parse_mode=ParseMode.HTML
            )
            return

        lines = ["📂 <b>Output Terbaru</b>\n"]
        for f in files[:15]:
            name = os.path.basename(f)
            size = os.path.getsize(f) / (1024 * 1024)
            mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%H:%M:%S %d/%m")
            lines.append(f"  📹 <code>{name}</code> — {size:.1f}MB — {mtime}")
        lines.append(f"\nTotal: <b>{len(files)}</b> file")

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Kirim Video Terbaru", callback_data="send_latest")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="act_output")],
            [InlineKeyboardButton("🏠 Menu", callback_data="act_menu")],
        ])
        await q.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if data == "send_latest":
        output_dir = cfg["output_dir"]
        files = sorted(
            glob.glob(os.path.join(output_dir, "*.mp4")),
            key=os.path.getmtime, reverse=True
        )
        if files:
            latest = files[0]
            size = os.path.getsize(latest) / (1024 * 1024)
            if size <= 50:  # Telegram limit ~50MB
                await q.edit_message_text("📤 Mengirim video terbaru...")
                try:
                    with open(latest, 'rb') as vf:
                        await ctx.bot.send_video(
                            chat_id=q.message.chat_id,
                            video=vf,
                            caption=f"📹 {os.path.basename(latest)} ({size:.1f}MB)",
                            supports_streaming=True
                        )
                except Exception as e:
                    await ctx.bot.send_message(q.message.chat_id, f"❌ Gagal kirim: {e}")
            else:
                await q.edit_message_text(
                    f"❌ File terlalu besar ({size:.1f}MB). Telegram limit 50MB.",
                    reply_markup=main_menu_kb()
                )
        else:
            await q.edit_message_text("❌ Tidak ada file.", reply_markup=main_menu_kb())
        return

    if data == "act_menu":
        text = (
            "⚡ <b>Grok Video Automation Bot</b>\n\n"
            f"📁 Output: <code>{cfg['output_dir']}</code>\n"
            f"🖥 Tabs: <b>{cfg['n_tabs']}</b>  •  Siklus: <b>{cfg['n_cycles']}</b>\n"
            f"🌐 Port: <b>{cfg['debug_port']}</b>  •  Headless: <b>{'Ya' if cfg['headless'] else 'Tidak'}</b>\n"
        )
        await q.edit_message_text(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)
        return

    if data == "act_settings":
        await q.edit_message_text(
            settings_text(cfg),
            reply_markup=settings_kb(cfg),
            parse_mode=ParseMode.HTML
        )
        return


# ═══════════════════════════════════════════════════════════════
#  DIRECT COMMANDS
# ═══════════════════════════════════════════════════════════════
async def cmd_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    await update.message.reply_text("🚀 <b>Memulai generasi video...</b>", parse_mode=ParseMode.HTML)
    await start_generate(ctx.bot, update.message.chat_id, uid, cfg)


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    evt = stop_events.get(uid)
    if evt:
        evt.set()
        await update.message.reply_text("⏹ <b>Stop diminta.</b>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("ℹ️ Tidak ada proses yang berjalan.")


async def cmd_monitor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = build_tab_monitor_text(uid)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="act_monitor")],
        [InlineKeyboardButton("🏠 Menu", callback_data="act_menu")],
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def cmd_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = build_log_text(uid)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="act_log")],
        [InlineKeyboardButton("🏠 Menu", callback_data="act_menu")],
    ])
    await update.message.reply_text(text[:4096], reply_markup=kb, parse_mode=ParseMode.HTML)


async def cmd_output(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    output_dir = cfg["output_dir"]
    if not os.path.isdir(output_dir):
        await update.message.reply_text(f"📂 Folder output belum ada: <code>{output_dir}</code>",
                                         parse_mode=ParseMode.HTML)
        return
    files = sorted(
        glob.glob(os.path.join(output_dir, "*.mp4")),
        key=os.path.getmtime, reverse=True
    )
    if not files:
        await update.message.reply_text("📂 Output kosong.")
        return

    lines = ["📂 <b>Output Terbaru</b>\n"]
    for f in files[:10]:
        name = os.path.basename(f)
        size = os.path.getsize(f) / (1024 * 1024)
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%H:%M:%S %d/%m")
        lines.append(f"  📹 <code>{name}</code> — {size:.1f}MB — {mtime}")
    lines.append(f"\nTotal: <b>{len(files)}</b> file")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Kirim Video Terbaru", callback_data="send_latest")],
    ])
    await update.message.reply_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>Grok Bot — Panduan</b>\n\n"
        "<b>Perintah:</b>\n"
        "/start — Menu utama\n"
        "/settings — Konfigurasi lengkap\n"
        "/generate — Mulai generate video\n"
        "/stop — Hentikan proses\n"
        "/monitor — Lihat status tab realtime\n"
        "/log — Lihat log terakhir\n"
        "/output — Lihat file output terbaru\n"
        "/help — Panduan ini\n\n"
        "<b>Konfigurasi yang tersedia:</b>\n"
        "• Tabs per siklus (default: 5)\n"
        "• Jumlah siklus (default: 3)\n"
        "• Debug port Chrome (default: 9222)\n"
        "• Headless Chrome (default: Tidak)\n"
        "• Mode image: selang-seling / semua / tanpa\n"
        "• Output directory\n"
        "• Bahan/image directory\n"
        "• Simpan lokal\n"
        "• Multiple prompts (tambah/edit/hapus)\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
from telegram import BotCommand

async def post_init(application):
    """Register menu commands visible in Telegram UI."""
    await application.bot.set_my_commands([
        BotCommand("start", "📋 Menu utama"),
        BotCommand("generate", "▶️ Mulai generate video"),
        BotCommand("stop", "⏹ Hentikan proses"),
        BotCommand("monitor", "📊 Status tab realtime"),
        BotCommand("log", "📝 Lihat log terakhir"),
        BotCommand("output", "📂 Output terbaru"),
        BotCommand("settings", "⚙️ Konfigurasi"),
        BotCommand("help", "📖 Panduan"),
    ])

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Settings conversation
    settings_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", cmd_settings)],
        states={
            SETTING_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_number_input),
                CallbackQueryHandler(settings_callback, pattern="^stg_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_settings)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(settings_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("monitor", cmd_monitor))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("output", cmd_output))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("⚡ Grok Video Automation Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
