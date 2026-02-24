"""
SPEEDU Telegram Bot - Content Pipeline Controller
Mirrors speedu_gui.py: Generate → Overlay → Upload
"""
import os, sys, json, time, re, subprocess, textwrap, threading, asyncio, logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# ── Import core functions from speedu_gui ──
sys.path.insert(0, r"c:\tiktok_automation")
from speedu_gui import (
    run_gemini_generate, overlay_video,
    open_chrome_debug, connect_selenium, navigate_upload_page,
    do_upload_file, do_post_tiktok,
    JSON_PATH, OVERLAY_DIR, BASE_DIR, STOK_MINIMUM, VIDEO_COUNT, PROMPT_TEXT
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  SCHEDULE STATE — persistent across restarts
# ═══════════════════════════════════════════════════════════════
SCHEDULE_STATE_PATH = os.path.join(BASE_DIR, "schedule_state.json")

_INITIAL_SCHEDULE = {"tanggal": "2026-02-25", "jam": "14", "menit": "00"}

def load_schedule_state():
    """Load saved schedule state. Returns defaults if file missing/corrupt."""
    if os.path.exists(SCHEDULE_STATE_PATH):
        try:
            with open(SCHEDULE_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Validate keys
            if all(k in data for k in ("tanggal", "jam", "menit")):
                return data
        except Exception:
            pass
    # First run: initialize with 2026-02-25 14:00
    save_schedule_state(_INITIAL_SCHEDULE["tanggal"], _INITIAL_SCHEDULE["jam"], _INITIAL_SCHEDULE["menit"])
    return dict(_INITIAL_SCHEDULE)

def save_schedule_state(tanggal: str, jam: str, menit: str):
    """Persist the last/next schedule datetime so it survives restarts."""
    try:
        with open(SCHEDULE_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"tanggal": tanggal, "jam": jam, "menit": menit,
                       "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f, indent=2)
    except Exception as e:
        logger.warning(f"Gagal simpan schedule_state: {e}")

# Load state once at startup
_sched_state = load_schedule_state()
# Default for /settings = 1 jam setelah nilai di schedule_state.json
try:
    _sched_default_dt = datetime.strptime(
        f"{_sched_state['tanggal']} {_sched_state['jam']}:{_sched_state['menit']}",
        "%Y-%m-%d %H:%M"
    ) + timedelta(hours=1)
except Exception:
    _sched_default_dt = datetime.now() + timedelta(days=1)
logger.info(f"Schedule default (+1 jam): {_sched_default_dt.strftime('%Y-%m-%d %H:%M')}")

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8262051949:AAEbJHZ2Phk5m-kWbCxBWzqtfEFALf5Tcrc"  # Ganti dengan token bot kamu
ALLOWED_USER_IDS = []  # Kosong = semua user boleh. Isi [123456] untuk restrict

DEFAULTS = {
    "folder": os.path.join(BASE_DIR, "konten_speedu_final"),
    "deskripsi": "Siapkan diri kamu di sekolah kedinasan dengan baik demi masa depan cerah #kedinasan2026 #sekdin #stmkg",
    "tanggal": _sched_default_dt.strftime("%Y-%m-%d"),
    "jam":     f"{_sched_default_dt.hour:02d}",
    "menit":   f"{_sched_default_dt.minute:02d}",
    "interval": "120",
    "userdata_stok": os.path.join(BASE_DIR, "user_data", "1"),
    "port_stok": "9222",
    "userdata_upload": os.path.join(BASE_DIR, "user_data", "7"),
    "port_upload": "9223",
    "headless": False,
    "prompt": PROMPT_TEXT,
}

# Per-user settings & state
user_settings = {}
user_locks = {}  # prevent concurrent tasks
log_buffers = {}  # log lines per user
# Tracks items successfully scheduled in last Full Loop: {uid: {"overlay_files": [...], "tulisan_count": N}}
scheduled_items = {}
# Full Auto state: {uid: {"stop": threading.Event(), "thread": Thread}}
full_auto_tasks = {}

# Conversation states for /settings
(SET_FOLDER, SET_DESC, SET_DATE, SET_TIME, SET_INTERVAL,
 SET_USERDATA, SET_PORT) = range(7)


def get_cfg(uid):
    if uid not in user_settings:
        user_settings[uid] = dict(DEFAULTS)
    return user_settings[uid]


def is_allowed(uid):
    return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS


def get_lock(uid):
    if uid not in user_locks:
        user_locks[uid] = threading.Lock()
    return user_locks[uid]


# ═══════════════════════════════════════════════════════════════
#  LOG SYSTEM — buffer + periodic telegram message edit
# ═══════════════════════════════════════════════════════════════
MAX_LOG_LINES = 25

def make_log_fn(uid):
    """Returns a log function that appends to buffer."""
    if uid not in log_buffers:
        log_buffers[uid] = []

    def log_fn(msg, tag=None):
        ts = datetime.now().strftime("%H:%M:%S")
        icon = {"success": "✅", "error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(tag, "▪️")
        line = f"<code>[{ts}]</code> {icon} {msg}"
        log_buffers[uid].append(line)
        if len(log_buffers[uid]) > MAX_LOG_LINES:
            log_buffers[uid] = log_buffers[uid][-MAX_LOG_LINES:]
    return log_fn


async def live_log_updater(bot, chat_id, msg_id, uid, stop_evt):
    """Edits a message every 3s with latest log buffer."""
    last_text = ""
    while not stop_evt.is_set():
        lines = log_buffers.get(uid, [])
        text = "\n".join(lines[-MAX_LOG_LINES:]) if lines else "<i>Menunggu log...</i>"
        text = f"📊 <b>Live Log</b>\n\n{text}"
        if text != last_text:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=text[:4096], parse_mode=ParseMode.HTML
                )
                last_text = text
            except Exception:
                pass
        await asyncio.sleep(3)
    # Final update
    lines = log_buffers.get(uid, [])
    text = "\n".join(lines[-MAX_LOG_LINES:]) if lines else ""
    text = f"📊 <b>Log Selesai</b>\n\n{text}\n\n✅ <b>Proses selesai.</b>"
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text[:4096], parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  STOK HELPERS
# ═══════════════════════════════════════════════════════════════
def count_stok():
    tulisan = 0
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            tulisan = len([d for d in data if "tulisan 1" in d])
        except:
            pass
    overlay = 0
    if os.path.isdir(OVERLAY_DIR):
        overlay = len([f for f in os.listdir(OVERLAY_DIR) if f.lower().endswith("_overlay.mp4")])
    return tulisan, overlay


def stok_text():
    t, o = count_stok()
    ti = "✅" if t >= STOK_MINIMUM else "❌"
    oi = "✅" if o >= VIDEO_COUNT else "⚠️"
    return f"📦 <b>Stok Saat Ini</b>\n\nTulisan: <b>{t}</b> {ti}  (min {STOK_MINIMUM})\nOverlay: <b>{o}</b> {oi}  (target {VIDEO_COUNT})"


# ═══════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════
def main_menu_kb(uid=None):
    has_scheduled = bool(uid and scheduled_items.get(uid))
    is_auto = bool(uid and full_auto_tasks.get(uid))
    rows = [
        [InlineKeyboardButton("📋 Stok Konten", callback_data="act_stok"),
         InlineKeyboardButton("🎨 Buat Overlay", callback_data="act_overlay")],
        [InlineKeyboardButton("🚀 Full Loop", callback_data="act_full")],
        [InlineKeyboardButton(
            "⏹ Stop Full Auto" if is_auto else "🤖 Full Auto",
            callback_data="stop_full_auto" if is_auto else "act_full_auto"
        )],
        [InlineKeyboardButton("🗑 Hapus Tulisan", callback_data="del_tulisan"),
         InlineKeyboardButton("🗑 Hapus Overlay", callback_data="del_overlay")],
    ]
    if has_scheduled:
        rows.append([InlineKeyboardButton("🧹 Hapus Terjadwal", callback_data="del_scheduled")])
    rows.append([InlineKeyboardButton("↻ Refresh Stok", callback_data="refresh")])
    return InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    text = f"⚡ <b>SPEEDU Bot</b>\n\nContent Pipeline: Generate → Overlay → Upload\n\n{stok_text()}"
    await update.message.reply_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  SETTINGS CONVERSATION
# ═══════════════════════════════════════════════════════════════
async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return ConversationHandler.END
    cfg = get_cfg(update.effective_user.id)
    text = (
        "⚙️ <b>Settings</b>\n\n"
        f"1️⃣ Folder Video: <code>{cfg['folder']}</code>\n"
        f"2️⃣ Deskripsi: <code>{cfg['deskripsi'][:60]}...</code>\n"
        f"3️⃣ Tanggal: <code>{cfg['tanggal']}</code>\n"
        f"4️⃣ Jam: <code>{cfg['jam']}:{cfg['menit']}</code>\n"
        f"5️⃣ Interval: <code>{cfg['interval']} menit</code>\n"
        f"6️⃣ User Data Stok: <code>{cfg['userdata_stok']}</code>\n"
        f"7️⃣ Port Stok: <code>{cfg['port_stok']}</code>\n"
        f"8️⃣ User Data Upload: <code>{cfg['userdata_upload']}</code>\n"
        f"9️⃣ Port Upload: <code>{cfg['port_upload']}</code>\n"
        f"🔟 Prompt: <code>{cfg['prompt'][:60]}...</code>\n"
        f"🔲 Headless: <code>{cfg['headless']}</code>\n\n"
        "Kirim nomor setting yang mau diubah (1-10), atau /cancel"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'☑' if cfg['headless'] else '☐'} Headless", callback_data="toggle_headless")],
        [InlineKeyboardButton("❌ Tutup", callback_data="close_settings")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return SET_FOLDER  # waiting for number input


async def settings_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    txt = update.message.text.strip()

    state = ctx.user_data.get("setting_field")
    if state:
        # We're receiving a value
        field_map = {
            "folder": "folder", "desc": "deskripsi", "date": "tanggal",
            "time": None, "interval": "interval",
            "userdata_stok": "userdata_stok", "port_stok": "port_stok",
            "userdata_upload": "userdata_upload", "port_upload": "port_upload", 
            "prompt": "prompt"
        }
        if state == "time":
            parts = txt.replace(".", ":").split(":")
            if len(parts) == 2:
                cfg["jam"] = parts[0].zfill(2)
                cfg["menit"] = parts[1].zfill(2)
            else:
                await update.message.reply_text("Format salah. Kirim HH:MM")
                return SET_FOLDER
        elif state in field_map:
            cfg[field_map[state]] = txt
        ctx.user_data["setting_field"] = None
        await update.message.reply_text(f"✅ Setting diperbarui!\nKirim nomor lain untuk ubah, atau /cancel")
        return SET_FOLDER

    # Number selection
    prompts = {
        "1": ("folder", "Kirim path folder video:"),
        "2": ("desc", "Kirim deskripsi TikTok:"),
        "3": ("date", "Kirim tanggal (YYYY-MM-DD):"),
        "4": ("time", "Kirim jam (HH:MM):"),
        "5": ("interval", "Kirim interval (menit):"),
        "6": ("userdata_stok", "Kirim path user data Chrome untuk Stok (Gemini):"),
        "7": ("port_stok", "Kirim port Chrome untuk Stok (Gemini):"),
        "8": ("userdata_upload", "Kirim path user data Chrome untuk Upload (TikTok):"),
        "9": ("port_upload", "Kirim port Chrome untuk Upload (TikTok):"),
        "10": ("prompt", "Kirim teks prompt utuh untuk Gemini (pastikan aturan output JSON valid dan array isinya 2 item):"),
    }
    if txt in prompts:
        field, prompt = prompts[txt]
        ctx.user_data["setting_field"] = field
        await update.message.reply_text(prompt)
        return SET_FOLDER

    await update.message.reply_text("Kirim angka 1-10, atau /cancel")
    return SET_FOLDER


async def cancel_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("setting_field", None)
    ctx.user_data.pop("in_settings", None)
    await update.message.reply_text("Settings ditutup.", reply_markup=main_menu_kb())
    return ConversationHandler.END


async def toggle_headless_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cfg = get_cfg(q.from_user.id)
    cfg["headless"] = not cfg["headless"]
    await q.edit_message_text(
        f"Headless: <b>{'ON ✅' if cfg['headless'] else 'OFF ❌'}</b>\n\nKirim nomor 1-10 untuk ubah setting, /cancel untuk tutup.",
        parse_mode=ParseMode.HTML
    )
    return SET_FOLDER


async def close_settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Settings ditutup")
    await q.edit_message_text("⚙️ Settings ditutup.")
    ctx.user_data.pop("setting_field", None)
    ctx.user_data.pop("in_settings", None)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#  HELPERS FOR BACKGROUND THREADS
# ═══════════════════════════════════════════════════════════════
async def _notify(bot, chat_id: int, text: str):
    """Send a message to chat from a background thread via asyncio.run()."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"_notify failed: {e}")


# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER — actions
# ═══════════════════════════════════════════════════════════════
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not is_allowed(uid):
        return
    data = q.data

    if data == "refresh":
        await q.edit_message_text(stok_text(), reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    if data == "del_tulisan":
        try:
            with open(JSON_PATH, "w", encoding="utf-8") as f:
                json.dump([], f)
            await q.edit_message_text("🗑 Stok tulisan dihapus.\n\n" + stok_text(),
                                      reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=main_menu_kb(uid))
        return

    if data == "del_overlay":
        deleted = 0
        if os.path.isdir(OVERLAY_DIR):
            for f in os.listdir(OVERLAY_DIR):
                if f.lower().endswith("_overlay.mp4"):
                    try: os.remove(os.path.join(OVERLAY_DIR, f)); deleted += 1
                    except: pass
        await q.edit_message_text(f"🗑 {deleted} file overlay dihapus.\n\n" + stok_text(),
                                  reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    if data == "del_scheduled":
        info = scheduled_items.get(uid)
        if not info:
            await q.edit_message_text("❌ Tidak ada data terjadwal. Jalankan Full Loop dulu.",
                                      reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        # Delete overlay files that were scheduled
        del_overlay = 0
        for fpath in info.get("overlay_files", []):
            try:
                if os.path.exists(fpath):
                    os.remove(fpath)
                    del_overlay += 1
            except: pass
        # Delete tulisan from JSON (remove first N entries that were used)
        del_tulisan = 0
        n_tulisan = info.get("tulisan_count", 0)
        if n_tulisan > 0 and os.path.exists(JSON_PATH):
            try:
                with open(JSON_PATH, "r", encoding="utf-8") as f:
                    data_json = json.load(f)
                # Remove first n_tulisan entries
                data_json = data_json[n_tulisan:]
                del_tulisan = n_tulisan
                with open(JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(data_json, f, ensure_ascii=False, indent=2)
            except Exception as e:
                pass
        # Clear scheduled tracking
        scheduled_items.pop(uid, None)
        result = (
            f"🧹 <b>Cleanup Terjadwal Selesai!</b>\n\n"
            f"Overlay dihapus: <b>{del_overlay}</b>\n"
            f"Tulisan dihapus: <b>{del_tulisan}</b>\n\n"
            + stok_text()
        )
        await q.edit_message_text(result, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    # ── Task actions ──
    if data in ("act_stok", "act_overlay", "act_full"):
        lock = get_lock(uid)
        if not lock.acquire(blocking=False):
            await q.edit_message_text("⏳ Proses lain sedang berjalan. Tunggu selesai dulu.",
                                      reply_markup=main_menu_kb(uid))
            return

        log_buffers[uid] = []
        log_fn = make_log_fn(uid)
        cfg = get_cfg(uid)
        cfg["_uid"] = uid  # pass uid so _task_full_loop can record scheduled items
        stop_evt = threading.Event()
        ctx.user_data["stop_event"] = stop_evt

        # Send log message
        log_msg = await q.message.reply_text("📊 <b>Live Log</b>\n\n<i>Memulai...</i>",
                                              parse_mode=ParseMode.HTML)
        # Start live updater
        bot = ctx.bot
        updater_stop = asyncio.Event()
        loop = asyncio.get_event_loop()
        updater_task = loop.create_task(
            live_log_updater(bot, q.message.chat_id, log_msg.message_id, uid, updater_stop)
        )

        # Run task in thread
        def run_task():
            try:
                if data == "act_stok":
                    _task_stok(cfg, log_fn, stop_evt)
                elif data == "act_overlay":
                    _task_overlay(cfg, log_fn, stop_evt)
                elif data == "act_full":
                    _task_full_loop(cfg, log_fn, stop_evt)
            finally:
                updater_stop.set()
                lock.release()

        threading.Thread(target=run_task, daemon=True).start()

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹ Stop", callback_data="stop_task")],
        ])
        await q.edit_message_text("🚀 Proses dimulai!", reply_markup=kb)
        return

    if data == "stop_task":
        evt = ctx.user_data.get("stop_event")
        if evt:
            evt.set()
        await q.edit_message_text("⏹ Stop requested...\n\n" + stok_text(),
                                  reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    # ── Full Auto ──
    if data == "act_full_auto":
        if uid in full_auto_tasks:
            await q.edit_message_text("⚠️ Full Auto sudah berjalan.",
                                      reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        stop_auto = threading.Event()
        bot = ctx.bot
        chat_id = q.message.chat_id
        main_loop = asyncio.get_event_loop()

        def _send(text: str):
            """Thread-safe Telegram send menggunakan event loop utama."""
            asyncio.run_coroutine_threadsafe(_notify(bot, chat_id, text), main_loop)

        def _full_auto_daemon():
            """Loop: tunggu hingga 1 menit setelah schedule terakhir, lalu jalankan Full Loop."""
            _send("🤖 <b>Full Auto dimulai!</b>\nBot akan otomatis jalankan Full Loop 1 menit setelah schedule terakhir.")
            while not stop_auto.is_set():
                # Baca schedule terkini dari file
                state = load_schedule_state()
                try:
                    trigger_dt = datetime.strptime(
                        f"{state['tanggal']} {state['jam']}:{state['menit']}", "%Y-%m-%d %H:%M"
                    ) + timedelta(minutes=1)
                except Exception:
                    _send("❌ Full Auto: format schedule_state.json error!")
                    break

                now = datetime.now()
                wait_sec = (trigger_dt - now).total_seconds()
                next_str = trigger_dt.strftime('%Y-%m-%d %H:%M')

                if wait_sec > 0:
                    _send(
                        f"⏳ <b>Full Auto</b>: menunggu hingga <code>{next_str}</code> "
                        f"({int(wait_sec//60)} menit {int(wait_sec%60)} detik lagi)..."
                    )
                    # Tunggu dengan cek stop_auto setiap 30 detik
                    elapsed = 0
                    while elapsed < wait_sec and not stop_auto.is_set():
                        sleep_chunk = min(30, wait_sec - elapsed)
                        time.sleep(sleep_chunk)
                        elapsed += sleep_chunk
                    if stop_auto.is_set():
                        break

                # Saatnya jalankan Full Loop
                _send("🚀 <b>Full Auto</b>: memulai Full Loop...")
                lock = get_lock(uid)
                if not lock.acquire(blocking=True, timeout=60):
                    _send("⚠️ Full Auto: gagal acquire lock, coba lagi dalam 1 menit.")
                    time.sleep(60)
                    continue

                log_buffers[uid] = []
                log_fn = make_log_fn(uid)
                cfg = get_cfg(uid)
                # ── Selalu sinkronkan tanggal/jam/menit dari schedule_state.json ──
                # agar Full Loop menggunakan schedule yang tersimpan, bukan setting lama
                fresh_state = load_schedule_state()
                cfg["tanggal"] = fresh_state["tanggal"]
                cfg["jam"]     = fresh_state["jam"]
                cfg["menit"]   = fresh_state["menit"]
                cfg["_uid"]    = uid
                _send(
                    f"📅 <b>Full Auto</b>: Schedule diambil dari file → "
                    f"<code>{cfg['tanggal']} {cfg['jam']}:{cfg['menit']}</code>"
                )
                inner_stop = threading.Event()
                try:
                    _task_full_loop(cfg, log_fn, inner_stop)
                except Exception as e:
                    _send(f"❌ Full Auto error: {e}")
                finally:
                    lock.release()

                # Kirim ringkasan log setelah selesai
                lines = log_buffers.get(uid, [])
                summary = "\n".join(lines[-10:])
                _send(f"🎉 <b>Full Auto: Full Loop selesai!</b>\n\n{summary}\n\n{stok_text()}")

                if stop_auto.is_set():
                    break

                # Tunggu sebentar sebelum cek jadwal berikutnya
                time.sleep(10)

            full_auto_tasks.pop(uid, None)
            _send("⏹ <b>Full Auto dihentikan.</b>")

        t = threading.Thread(target=_full_auto_daemon, daemon=True, name=f"full_auto_{uid}")
        full_auto_tasks[uid] = {"stop": stop_auto, "thread": t}
        t.start()
        await q.edit_message_text(
            "🤖 <b>Full Auto aktif!</b>\nBot akan otomatis jalankan Full Loop tepat 1 menit setelah schedule terakhir di <code>schedule_state.json</code>.\n\nTekan <b>Stop Full Auto</b> untuk menghentikan.",
            reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML
        )
        return

    if data == "stop_full_auto":
        task = full_auto_tasks.get(uid)
        if task:
            task["stop"].set()
            full_auto_tasks.pop(uid, None)
        await q.edit_message_text(
            "⏹ <b>Full Auto dihentikan.</b>\n\n" + stok_text(),
            reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML
        )
        return


# ═══════════════════════════════════════════════════════════════
#  TASK IMPLEMENTATIONS (run in threads)
# ═══════════════════════════════════════════════════════════════
def _task_stok(cfg, log_fn, stop_evt):
    stok, _ = count_stok()
    log_fn(f"Stok konten saat ini: {stok}", "info")
    if stok >= STOK_MINIMUM:
        log_fn(f"Stok mencukupi ({stok} >= {STOK_MINIMUM}). Tidak perlu generate.", "success")
    else:
        needed = STOK_MINIMUM - stok
        loops = (needed + 1) // 2
        log_fn(f"Kurang {needed} konten, menjalankan {loops} loop Gemini...", "warn")
        total = run_gemini_generate(loops, log_fn, stop_evt, 
                                    headless=cfg.get("headless", False), 
                                    prompt_text=cfg.get("prompt", PROMPT_TEXT),
                                    user_data_dir=cfg.get("userdata_stok"),
                                    port=cfg.get("port_stok", "9222"))
        log_fn(f"Total konten sekarang: {total}", "success")
    log_fn("Stok selesai!", "success")


def _task_overlay(cfg, log_fn, stop_evt):
    folder = cfg["folder"]
    if not folder or not os.path.isdir(folder):
        log_fn("Folder video tidak valid!", "error"); return

    videos = sorted([f for f in os.listdir(folder) if f.lower().endswith(".mp4")])[:VIDEO_COUNT]
    if not videos:
        log_fn("Tidak ada video .mp4 di folder!", "error"); return

    stok, _ = count_stok()
    if stok < len(videos):
        log_fn(f"Stok konten ({stok}) kurang dari jumlah video ({len(videos)})!", "error"); return

    os.makedirs(OVERLAY_DIR, exist_ok=True)
    total = len(videos)
    log_fn(f"Memproses {total} video...", "info")

    for idx, vid in enumerate(videos):
        if stop_evt.is_set():
            log_fn("Overlay dihentikan.", "warn"); break
        vid_path = os.path.join(folder, vid)
        out_name = os.path.splitext(vid)[0] + "_overlay.mp4"
        out_path = os.path.join(OVERLAY_DIR, out_name)
        if os.path.exists(out_path):
            log_fn(f"[{idx+1}/{total}] {out_name} sudah ada, skip.", "info")
        else:
            log_fn(f"[{idx+1}/{total}] Overlay: {vid}...", "info")
            ok = overlay_video(vid_path, idx+1, out_path, log_fn)
            if ok:
                sz = os.path.getsize(out_path) / (1024*1024)
                log_fn(f"  ✓ Berhasil! ({sz:.1f} MB)", "success")
            else:
                log_fn(f"  ❌ Gagal overlay {vid}!", "error")
    log_fn(f"Overlay selesai! {total} video.", "success")


def _task_full_loop(cfg, log_fn, stop_evt):
    import psutil
    folder = cfg["folder"]
    if not folder or not os.path.isdir(folder):
        log_fn("Folder video tidak valid!", "error"); return

    videos = sorted([f for f in os.listdir(folder) if f.lower().endswith(".mp4")])[:VIDEO_COUNT]
    if not videos:
        log_fn("Tidak ada video .mp4 di folder!", "error"); return

    # ── PHASE 1: Konten ──
    log_fn("═══ PHASE 1: Memeriksa Stok Konten ═══", "info")
    stok, _ = count_stok()
    if stok < len(videos):
        needed = len(videos) - stok
        loops = (needed + 1) // 2
        log_fn(f"Stok kurang ({stok}/{len(videos)}), generate {loops} loop...", "warn")
        run_gemini_generate(loops, log_fn, stop_evt, 
                            headless=cfg.get("headless", False), 
                            prompt_text=cfg.get("prompt", PROMPT_TEXT),
                            user_data_dir=cfg.get("userdata_stok"),
                            port=cfg.get("port_stok", "9222"))
        stok, _ = count_stok()
        if stok < len(videos):
            log_fn(f"Stok masih kurang ({stok})!", "error"); return
    else:
        log_fn(f"Stok konten cukup: {stok}", "success")
    if stop_evt.is_set(): return

    # ── PHASE 2: Overlay ──
    log_fn("\n═══ PHASE 2: Video Overlay ═══", "info")
    os.makedirs(OVERLAY_DIR, exist_ok=True)
    overlay_files = []
    for idx, vid in enumerate(videos):
        if stop_evt.is_set(): break
        vid_path = os.path.join(folder, vid)
        out_name = os.path.splitext(vid)[0] + "_overlay.mp4"
        out_path = os.path.join(OVERLAY_DIR, out_name)
        if os.path.exists(out_path):
            log_fn(f"[{idx+1}/{len(videos)}] Sudah ada, skip.", "info")
        else:
            log_fn(f"[{idx+1}/{len(videos)}] Overlay: {vid}...", "info")
            ok = overlay_video(vid_path, idx+1, out_path, log_fn)
            log_fn(f"  {'✓ OK' if ok else '❌ Gagal'}!", "success" if ok else "error")
        overlay_files.append(out_path)
    if stop_evt.is_set(): return

    # ── PHASE 3: Upload TikTok ──
    log_fn("\n═══ PHASE 3: Upload ke TikTok ═══", "info")
    hour = int(cfg.get("jam", "6"))
    minute = int(cfg.get("menit", "0"))
    date_str = cfg.get("tanggal", (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
    interval = int(cfg.get("interval", "120"))
    userdata = cfg.get("userdata_upload", "")
    port = cfg.get("port_upload", "9223")
    deskripsi = cfg.get("deskripsi", "")
    headless = cfg.get("headless", False)

    start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
    log_fn(f"Membuka Chrome (port {port}, headless={headless})...", "info")
    chrome_proc = open_chrome_debug(userdata, port, headless)
    driver = connect_selenium(port)
    log_fn("Chrome terhubung!", "success")

    # Track scheduled results for this user
    uid = cfg.get("_uid")
    if uid:
        scheduled_items[uid] = {"overlay_files": [], "tulisan_count": 0}
    uploaded_count = 0

    try:
        for idx, out_path in enumerate(overlay_files):
            if stop_evt.is_set(): break
            if not os.path.exists(out_path):
                log_fn(f"[{idx+1}] File tidak ada, skip!", "warn"); continue
            sched_dt = start_dt + timedelta(minutes=interval * idx)
            log_fn(f"\n[{idx+1}/{len(overlay_files)}] Upload: {os.path.basename(out_path)}", "info")
            log_fn(f"  Schedule: {sched_dt.strftime('%Y-%m-%d %H:%M')}", "info")
            success = False
            try:
                navigate_upload_page(driver, force=(idx > 0))
                time.sleep(3)
                do_upload_file(driver, os.path.normpath(out_path), log_fn)
                time.sleep(5)
                do_post_tiktok(driver, deskripsi, sched_dt, log_fn)
                success = True
                uploaded_count += 1
            except Exception as e:
                log_fn(f"  ❌ Error: {e}", "error")
            # Record successful upload for cleanup later
            if success and uid:
                scheduled_items[uid]["overlay_files"].append(out_path)
            if idx < len(overlay_files) - 1 and not stop_evt.is_set():
                log_fn("  Menunggu 10 detik...", "info"); time.sleep(10)
    finally:
        try: driver.quit()
        except: pass
        try: chrome_proc.terminate()
        except: pass

    # Record tulisan count used (1 tulisan per video uploaded)
    if uid and scheduled_items.get(uid):
        scheduled_items[uid]["tulisan_count"] = uploaded_count

    # ── Save next schedule datetime if all videos uploaded successfully ──
    if uploaded_count == len(overlay_files) and len(overlay_files) > 0:
        last_sched_dt = start_dt + timedelta(minutes=interval * (len(overlay_files) - 1))
        next_dt = last_sched_dt + timedelta(minutes=interval)
        save_schedule_state(
            next_dt.strftime("%Y-%m-%d"),
            f"{next_dt.hour:02d}",
            f"{next_dt.minute:02d}",
        )
        # Also update the in-memory cfg for this user so /settings shows updated value
        if uid and uid in user_settings:
            user_settings[uid]["tanggal"] = next_dt.strftime("%Y-%m-%d")
            user_settings[uid]["jam"] = f"{next_dt.hour:02d}"
            user_settings[uid]["menit"] = f"{next_dt.minute:02d}"
        log_fn(
            f"💾 Schedule berikutnya disimpan: {next_dt.strftime('%Y-%m-%d %H:%M')}",
            "success"
        )

        # ── Auto-cleanup: hapus overlay & tulisan yang sudah di-schedule ──
        log_fn("🧹 Auto-cleanup: menghapus overlay & tulisan yang sudah di-schedule...", "info")

        # Hapus file overlay yang berhasil di-upload
        del_overlay = 0
        if uid and scheduled_items.get(uid):
            for fpath in scheduled_items[uid].get("overlay_files", []):
                try:
                    if os.path.exists(fpath):
                        os.remove(fpath)
                        del_overlay += 1
                except Exception:
                    pass

        # Hapus tulisan dari JSON (hapus N entry pertama yang sudah dipakai)
        del_tulisan = 0
        if uploaded_count > 0 and os.path.exists(JSON_PATH):
            try:
                with open(JSON_PATH, "r", encoding="utf-8") as f:
                    data_json = json.load(f)
                del_tulisan = min(uploaded_count, len(data_json))
                data_json = data_json[del_tulisan:]
                with open(JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(data_json, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log_fn(f"  ⚠️ Gagal hapus tulisan: {e}", "warn")

        # Bersihkan tracking
        if uid:
            scheduled_items.pop(uid, None)

        log_fn(
            f"  ✅ Cleanup selesai: {del_overlay} overlay, {del_tulisan} tulisan dihapus.",
            "success"
        )

    log_fn(f"\n{'═'*40}", "success")
    log_fn(f"🎉 SELESAI! Pipeline {len(videos)} video. ({uploaded_count} berhasil di-schedule)", "success")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
from telegram import BotCommand

async def post_init(application):
    """Register menu commands visible in Telegram UI."""
    await application.bot.set_my_commands([
        BotCommand("start", "📋 Menu utama"),
        BotCommand("menu", "📋 Tampilkan menu"),
        BotCommand("settings", "⚙️ Konfigurasi"),
        BotCommand("cancel", "❌ Batalkan setting"),
    ])

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Settings conversation
    settings_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", cmd_settings)],
        states={
            SET_FOLDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_input),
                CallbackQueryHandler(toggle_headless_cb, pattern="^toggle_headless$"),
                CallbackQueryHandler(close_settings_cb, pattern="^close_settings$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_settings),
            CommandHandler("settings", cmd_settings),  # allow re-entry via /settings
            CallbackQueryHandler(close_settings_cb, pattern="^close_settings$"),
        ],
        allow_reentry=True,  # /settings always re-enters conversation fresh
    )
    app.add_handler(settings_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 SPEEDU Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
