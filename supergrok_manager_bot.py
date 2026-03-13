"""
═══════════════════════════════════════════════════════════════
  SUPERGROK MANAGER BOT
  Mengelola & menduplikat supergrok_one_bot.py per user
  ─ Tambah, Hapus, Edit user
  ─ Jalankan / Stop via shell (PID tracking)
═══════════════════════════════════════════════════════════════

USAGE:
  python supergrok_manager_bot.py
"""

import os
import sys
import json
import shutil
import subprocess
import logging
import time
from datetime import datetime, timedelta

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
    ConversationHandler,
)
from telegram.constants import ParseMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("SGV_Manager")

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
APP_DIR = r"C:\tiktok_automation"
MANAGER_BOT_TOKEN = "8373360293:AAFVV-ebBFTVOTRAKTtnfFnbICqqCyuiBPA"
USER_DATA_BASE = os.path.join(APP_DIR, "user_data")
PARENT_USER_DATA = os.path.join(USER_DATA_BASE, "parent")  # Folder sumber untuk duplikasi
TEMPLATE_FILE = os.path.join(APP_DIR, "supergrok_one_bot.py")
USERS_DIR = os.path.join(APP_DIR, "sgv_users")
DB_FILE = os.path.join(APP_DIR, "sgv_manager_db.json")

# Parts yang perlu di-copy ke folder user agar bisa import
PART_FILES = ["sgv_config.py", "sgv_selenium.py", "sgv_bot.py"]

os.makedirs(USERS_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
#  DATABASE (JSON)
# ═══════════════════════════════════════════════════════════════
def load_db() -> dict:
    """Load user database. Returns {nama_user: {...}}."""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}


def save_db(data: dict):
    """Save user database."""
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_user(nama: str) -> dict | None:
    db = load_db()
    return db.get(nama)


def add_user(nama: str, info: dict):
    db = load_db()
    db[nama] = info
    save_db(db)


def remove_user(nama: str):
    db = load_db()
    db.pop(nama, None)
    save_db(db)


def update_user(nama: str, info: dict):
    db = load_db()
    if nama in db:
        db[nama].update(info)
        save_db(db)


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def escape_html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def expand_user_data(value: str) -> str:
    """Expand shorthand user data input. e.g. '1' -> 'C:\\tiktok_automation\\user_data\\1'."""
    value = value.strip()
    # If it's just a number or short name (no backslash/colon), treat as subfolder
    if not os.sep in value and ":" not in value and "/" not in value:
        return os.path.join(USER_DATA_BASE, value)
    return value


def get_used_ports() -> list:
    """Get list of ports already in use by users."""
    db = load_db()
    return [u.get("port", "") for u in db.values()]


def get_used_user_data() -> list:
    """Get list of user data dirs already in use."""
    db = load_db()
    return [u.get("user_data_chrome", "") for u in db.values()]


def get_script_name(nama_user: str) -> str:
    """Get the script filename for a user."""
    return f"{nama_user}-supergrok-one-bot.py"


def get_script_path(nama_user: str) -> str:
    """Get full path to user's bot script."""
    return os.path.join(USERS_DIR, get_script_name(nama_user))


def create_user_script(nama_user: str) -> bool:
    """Copy template + parts to USERS_DIR as [nama]-supergrok-one-bot.py."""
    try:
        # Copy the main entry point
        src = TEMPLATE_FILE
        dst = get_script_path(nama_user)
        shutil.copy2(src, dst)

        # Copy part files so the script can import them
        for part in PART_FILES:
            part_src = os.path.join(APP_DIR, part)
            part_dst = os.path.join(USERS_DIR, part)
            if os.path.exists(part_src):
                shutil.copy2(part_src, part_dst)

        logger.info(f"✅ Script dibuat: {dst}")
        return True
    except Exception as e:
        logger.error(f"❌ Gagal buat script: {e}")
        return False


def delete_user_script(nama_user: str):
    """Delete user's bot script."""
    path = get_script_path(nama_user)
    if os.path.exists(path):
        try:
            os.remove(path)
            logger.info(f"🗑️ Script dihapus: {path}")
        except Exception as e:
            logger.error(f"❌ Gagal hapus script: {e}")


def run_user_bot(nama_user: str) -> int | None:
    """Run a user's bot script via shell. Returns PID or None."""
    user_info = get_user(nama_user)
    if not user_info:
        return None

    script_path = get_script_path(nama_user)
    if not os.path.exists(script_path):
        return None

    bot_token = user_info.get("bot_token", "")
    no_wa = user_info.get("no_wa", "")
    port = user_info.get("port", "9245")
    user_data = user_info.get("user_data_chrome", "")

    cmd = [
        sys.executable,
        script_path,
        nama_user,
        bot_token,
        no_wa,
        port,
        user_data,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=USERS_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid = proc.pid
        logger.info(f"🚀 Bot {nama_user} dijalankan, PID={pid}")
        return pid
    except Exception as e:
        logger.error(f"❌ Gagal jalankan bot {nama_user}: {e}")
        return None


def kill_user_bot(nama_user: str) -> bool:
    """Kill user's bot process by PID using taskkill."""
    user_info = get_user(nama_user)
    if not user_info:
        return False

    pid = user_info.get("pid")
    if not pid:
        return False

    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid), "/T"],
            capture_output=True, text=True, timeout=10
        )
        success = result.returncode == 0
        if success:
            logger.info(f"🛑 Bot {nama_user} (PID={pid}) dihentikan")
            update_user(nama_user, {"pid": None, "status": "stopped"})
        else:
            logger.warning(f"⚠️ taskkill gagal: {result.stderr.strip()}")
            # PID might already be dead
            update_user(nama_user, {"pid": None, "status": "stopped"})
        return True
    except Exception as e:
        logger.error(f"❌ Gagal kill PID {pid}: {e}")
        # Set stopped anyway
        update_user(nama_user, {"pid": None, "status": "stopped"})
        return False


def is_pid_running(pid: int) -> bool:
    """Check if a PID is still running."""
    if not pid:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=5
        )
        return str(pid) in result.stdout
    except:
        return False


def is_user_expired(user_info: dict) -> bool:
    """Check if user subscription is expired."""
    expiry = user_info.get("expiry", "")
    if not expiry:
        return True
    try:
        exp_dt = datetime.fromisoformat(expiry)
        return datetime.now() > exp_dt
    except:
        return True


# ═══════════════════════════════════════════════════════════════
#  CONVERSATION STATES
# ═══════════════════════════════════════════════════════════════
TAMBAH_INPUT = 1
TAMBAH_CONFIRM = 2
EDIT_SELECT = 10
EDIT_INPUT = 11
HAPUS_SELECT = 20

# ═══════════════════════════════════════════════════════════════
#  /START - Main Menu
# ═══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu with inline buttons."""
    db = load_db()
    total_users = len(db)
    running = sum(1 for u in db.values() if u.get("pid") and is_pid_running(u["pid"]))
    expired = sum(1 for u in db.values() if is_user_expired(u))

    text = (
        f"══════════════════════════════\n"
        f"  🛠️ <b>SGV MANAGER BOT</b> 🛠️\n"
        f"══════════════════════════════\n\n"
        f"👥 Total User: <b>{total_users}</b>\n"
        f"🟢 Running: <b>{running}</b>\n"
        f"🔴 Expired: <b>{expired}</b>\n\n"
    )

    keyboard = [
        [InlineKeyboardButton("➕ Tambah User", callback_data="menu_tambah")],
        [InlineKeyboardButton("🗑️ Hapus User", callback_data="menu_hapus")],
        [InlineKeyboardButton("✏️ Edit User", callback_data="menu_edit")],
        [InlineKeyboardButton("🔌 Port Terpakai", callback_data="menu_ports")],
        [InlineKeyboardButton("📁 User Data Terpakai", callback_data="menu_userdata")],
        [InlineKeyboardButton("📋 Daftar User", callback_data="menu_list")],
        [InlineKeyboardButton("🔄 Kelola User Data", callback_data="menu_kelola_ud")],
    ]

    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
    )


# ═══════════════════════════════════════════════════════════════
#  MENU CALLBACKS
# ═══════════════════════════════════════════════════════════════
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu button presses."""
    query = update.callback_query
    await query.answer()

    if query.data == "menu_ports":
        ports = get_used_ports()
        if ports:
            port_list = "\n".join([f"  🔌 <code>{p}</code>" for p in ports])
            text = f"🔌 <b>PORT TERPAKAI</b>\n\n{port_list}"
        else:
            text = "🔌 <b>Belum ada port terpakai.</b>"
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
        return

    if query.data == "menu_userdata":
        uds = get_used_user_data()
        if uds:
            ud_list = "\n".join([f"  📁 <code>{u}</code>" for u in uds])
            text = f"📁 <b>USER DATA TERPAKAI</b>\n\n{ud_list}"
        else:
            text = "📁 <b>Belum ada user data terpakai.</b>"
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
        return

    if query.data == "menu_list":
        db = load_db()
        if not db:
            await query.edit_message_text(
                "📋 <b>Belum ada user terdaftar.</b>", parse_mode=ParseMode.HTML)
            return

        text = "📋 <b>DAFTAR USER</b>\n\n"
        for i, (nama, info) in enumerate(db.items(), 1):
            pid = info.get("pid")
            running = is_pid_running(pid) if pid else False
            expired = is_user_expired(info)
            status_icon = "🟢" if running else ("🔴" if expired else "⚪")
            status_text = "Running" if running else ("Expired" if expired else "Stopped")
            expiry = info.get("expiry", "?")[:10]

            text += (
                f"{status_icon} <b>{i}. {escape_html(nama)}</b>\n"
                f"   📅 Expiry: <code>{expiry}</code>\n"
                f"   🔌 Port: <code>{info.get('port', '?')}</code>\n"
                f"   📁 Data: <code>{info.get('user_data_chrome', '?')}</code>\n"
                f"   📊 Status: <b>{status_text}</b>"
            )
            if pid and running:
                text += f" (PID: {pid})"
            text += "\n\n"

        await query.edit_message_text(text[:4096], parse_mode=ParseMode.HTML)
        return

    # For tambah/hapus/edit, we need to enter conversation, so just show instructions
    if query.data == "menu_tambah":
        await query.edit_message_text(
            "➕ <b>TAMBAH USER</b>\n\n"
            "Kirim data user dengan format (pisah enter):\n\n"
            "<code>nama user</code>\n"
            "<code>BOT_TOKEN</code>\n"
            "<code>no.wa</code>\n"
            "<code>default port</code>\n"
            "<code>user data chrome (cukup isi angka, misal: 1)</code>\n\n"
            f"📌 Default path: <code>{escape_html(USER_DATA_BASE)}\\[angka]</code>\n"
            "📌 <i>Expiry otomatis 30 hari ke depan</i>\n"
            "⚠️ <i>Port & user data harus unique</i>\n\n"
            "Contoh:\n"
            "<code>Budi\n"
            "8781330231:AAxxxxxxxx\n"
            "081234567890\n"
            "9250\n"
            "5</code>",
            parse_mode=ParseMode.HTML
        )
        context.user_data["awaiting"] = "tambah_input"
        return

    if query.data == "menu_hapus":
        db = load_db()
        if not db:
            await query.edit_message_text(
                "🗑️ <b>Belum ada user untuk dihapus.</b>", parse_mode=ParseMode.HTML)
            return

        keyboard = []
        for nama, info in db.items():
            expired = is_user_expired(info)
            pid = info.get("pid")
            running = is_pid_running(pid) if pid else False
            label = f"{'🔴' if expired else '🟢'} {nama}"
            if running:
                label += " (Running)"
            if expired:
                label += " (Expired)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"hapus_{nama}")])
        keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="hapus_cancel")])

        await query.edit_message_text(
            "🗑️ <b>HAPUS USER</b>\n\n"
            "Pilih user yang ingin dihapus:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return

    if query.data == "menu_edit":
        db = load_db()
        if not db:
            await query.edit_message_text(
                "✏️ <b>Belum ada user untuk diedit.</b>", parse_mode=ParseMode.HTML)
            return

        keyboard = []
        for nama in db:
            keyboard.append([InlineKeyboardButton(f"✏️ {nama}", callback_data=f"edit_{nama}")])
        keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="edit_cancel")])

        await query.edit_message_text(
            "✏️ <b>EDIT USER</b>\n\nPilih user yang ingin diedit:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return


# ═══════════════════════════════════════════════════════════════
#  HAPUS CALLBACKS
# ═══════════════════════════════════════════════════════════════
async def hapus_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user deletion."""
    query = update.callback_query
    await query.answer()

    if query.data == "hapus_cancel":
        await query.edit_message_text("❌ Dibatalkan.", parse_mode=ParseMode.HTML)
        return

    nama = query.data[len("hapus_"):]
    user_info = get_user(nama)

    if not user_info:
        await query.edit_message_text(
            f"⚠️ User <b>{escape_html(nama)}</b> tidak ditemukan.",
            parse_mode=ParseMode.HTML)
        return

    # Kill process if running
    pid = user_info.get("pid")
    kill_msg = ""
    if pid and is_pid_running(pid):
        kill_user_bot(nama)
        kill_msg = f"\n🛑 Proses (PID: {pid}) dihentikan via taskkill"

    # Delete script
    delete_user_script(nama)

    # Delete user folders
    for folder_prefix in ["bahan-", "video-", "prompt-"]:
        folder = os.path.join(APP_DIR, f"{folder_prefix}{nama}")
        if os.path.isdir(folder):
            try:
                shutil.rmtree(folder, ignore_errors=True)
            except:
                pass

    # Delete config file
    cfg_file = os.path.join(APP_DIR, f"sgv_config_{nama}.json")
    if os.path.exists(cfg_file):
        try:
            os.remove(cfg_file)
        except:
            pass

    # Remove from database
    remove_user(nama)

    await query.edit_message_text(
        f"✅ <b>User {escape_html(nama)} berhasil dihapus!</b>{kill_msg}\n\n"
        f"🗑️ Script dihapus\n"
        f"🗑️ Folder bahan/video/prompt dihapus\n"
        f"🗑️ Data dari database dihapus",
        parse_mode=ParseMode.HTML
    )


# ═══════════════════════════════════════════════════════════════
#  EDIT CALLBACKS
# ═══════════════════════════════════════════════════════════════
async def edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle edit user selection."""
    query = update.callback_query
    await query.answer()

    if query.data == "edit_cancel":
        await query.edit_message_text("❌ Dibatalkan.", parse_mode=ParseMode.HTML)
        return

    nama = query.data[len("edit_"):]
    user_info = get_user(nama)

    if not user_info:
        await query.edit_message_text(
            f"⚠️ User <b>{escape_html(nama)}</b> tidak ditemukan.",
            parse_mode=ParseMode.HTML)
        return

    context.user_data["edit_user"] = nama

    await query.edit_message_text(
        f"✏️ <b>EDIT USER: {escape_html(nama)}</b>\n\n"
        f"Data saat ini:\n"
        f"  🔑 Token: <code>{user_info.get('bot_token', '?')[:25]}...</code>\n"
        f"  📱 WA: <code>{user_info.get('no_wa', '?')}</code>\n"
        f"  🔌 Port: <code>{user_info.get('port', '?')}</code>\n"
        f"  📁 Data: <code>{user_info.get('user_data_chrome', '?')}</code>\n"
        f"  📅 Expiry: <code>{user_info.get('expiry', '?')[:10]}</code>\n\n"
        f"Kirim data baru (pisah enter, kosongkan baris = tidak diubah):\n\n"
        f"<code>BOT_TOKEN (atau kosong)</code>\n"
        f"<code>no.wa (atau kosong)</code>\n"
        f"<code>default port (atau kosong)</code>\n"
        f"<code>user data chrome (angka/path, atau kosong)</code>",
        parse_mode=ParseMode.HTML
    )
    context.user_data["awaiting"] = "edit_input"


# ═══════════════════════════════════════════════════════════════
#  RUN/STOP BOT CALLBACKS
# ═══════════════════════════════════════════════════════════════
async def run_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle run/stop bot button."""
    query = update.callback_query
    await query.answer()

    if query.data.startswith("run_"):
        nama = query.data[len("run_"):]
        user_info = get_user(nama)
        if not user_info:
            await query.edit_message_text(f"⚠️ User {escape_html(nama)} tidak ditemukan.", parse_mode=ParseMode.HTML)
            return

        pid = run_user_bot(nama)
        if pid:
            update_user(nama, {"pid": pid, "status": "running"})
            await query.edit_message_text(
                f"🚀 <b>Bot {escape_html(nama)} berhasil dijalankan!</b>\n\n"
                f"📊 PID: <code>{pid}</code>\n"
                f"🔌 Port: <code>{user_info.get('port', '?')}</code>\n"
                f"📁 Script: <code>{get_script_name(nama)}</code>",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text(
                f"❌ <b>Gagal menjalankan bot {escape_html(nama)}</b>",
                parse_mode=ParseMode.HTML
            )
        return

    if query.data.startswith("stop_"):
        nama = query.data[len("stop_"):]
        kill_user_bot(nama)
        await query.edit_message_text(
            f"🛑 <b>Bot {escape_html(nama)} dihentikan.</b>",
            parse_mode=ParseMode.HTML
        )
        return


# ═══════════════════════════════════════════════════════════════
#  MESSAGE HANDLER (for state-based input)
# ═══════════════════════════════════════════════════════════════
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages based on current state."""
    awaiting = context.user_data.get("awaiting")

    if awaiting == "tambah_input":
        await _handle_tambah_input(update, context)
        return

    if awaiting == "tambah_confirm":
        await _handle_tambah_confirm(update, context)
        return

    if awaiting == "edit_input":
        await _handle_edit_input(update, context)
        return


async def _handle_tambah_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process tambah user multi-line input."""
    text = update.message.text.strip()
    lines = [l.strip() for l in text.split("\n")]

    if len(lines) < 5:
        await update.message.reply_text(
            "⚠️ <b>Format salah!</b> Harus 5 baris:\n\n"
            "<code>nama user\nBOT_TOKEN\nno.wa\ndefault port\nuser data chrome</code>",
            parse_mode=ParseMode.HTML
        )
        return

    nama_user = lines[0]
    bot_token = lines[1]
    no_wa = lines[2]
    port = lines[3]
    user_data_chrome = expand_user_data(lines[4])

    # Validate uniqueness
    used_ports = get_used_ports()
    used_uds = get_used_user_data()

    errors = []
    if port in used_ports:
        errors.append(f"🔌 Port <code>{port}</code> sudah dipakai user lain!")
    if user_data_chrome in used_uds:
        errors.append(f"📁 User data <code>{escape_html(user_data_chrome)}</code> sudah dipakai user lain!")
    if get_user(nama_user):
        errors.append(f"👤 User <b>{escape_html(nama_user)}</b> sudah terdaftar!")

    if errors:
        error_text = "\n".join(errors)
        await update.message.reply_text(
            f"❌ <b>Gagal menambahkan user:</b>\n\n{error_text}\n\n"
            f"Kirim ulang data yang benar.",
            parse_mode=ParseMode.HTML
        )
        return

    # Calculate expiry (30 days from now)
    expiry = (datetime.now() + timedelta(days=30)).isoformat()

    # Store pending data
    context.user_data["pending_user"] = {
        "nama_user": nama_user,
        "bot_token": bot_token,
        "no_wa": no_wa,
        "port": port,
        "user_data_chrome": user_data_chrome,
        "expiry": expiry,
    }

    expiry_date = (datetime.now() + timedelta(days=30)).strftime("%d %B %Y, %H:%M")

    keyboard = [
        [InlineKeyboardButton("✅ Ya, Jalankan", callback_data=f"confirm_run_{nama_user}")],
        [InlineKeyboardButton("📦 Simpan Saja", callback_data=f"confirm_save_{nama_user}")],
        [InlineKeyboardButton("❌ Batal", callback_data="confirm_cancel")],
    ]

    await update.message.reply_text(
        f"✅ <b>{escape_html(nama_user)}-supergrok-one-bot.py sudah dibuat.</b>\n\n"
        f"📋 <b>Detail User:</b>\n"
        f"  👤 Nama: <b>{escape_html(nama_user)}</b>\n"
        f"  🔑 Token: <code>{bot_token[:25]}...</code>\n"
        f"  📱 WA: <code>{no_wa}</code>\n"
        f"  🔌 Port: <code>{port}</code>\n"
        f"  📁 Data: <code>{escape_html(user_data_chrome)}</code>\n"
        f"  📅 Expiry: <code>{expiry_date}</code>\n\n"
        f"Apakah mau jalankan?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    context.user_data["awaiting"] = "tambah_confirm"


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirm tambah user buttons."""
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_cancel":
        context.user_data.pop("pending_user", None)
        context.user_data.pop("awaiting", None)
        await query.edit_message_text("❌ Dibatalkan.", parse_mode=ParseMode.HTML)
        return

    pending = context.user_data.get("pending_user")
    if not pending:
        await query.edit_message_text("⚠️ Data user tidak ditemukan.", parse_mode=ParseMode.HTML)
        return

    nama_user = pending["nama_user"]

    # Create script
    if not create_user_script(nama_user):
        await query.edit_message_text(
            f"❌ Gagal membuat script untuk {escape_html(nama_user)}",
            parse_mode=ParseMode.HTML)
        context.user_data.pop("pending_user", None)
        context.user_data.pop("awaiting", None)
        return

    # Save to database
    user_info = {
        "bot_token": pending["bot_token"],
        "no_wa": pending["no_wa"],
        "port": pending["port"],
        "user_data_chrome": pending["user_data_chrome"],
        "expiry": pending["expiry"],
        "created_at": datetime.now().isoformat(),
        "pid": None,
        "status": "stopped",
    }
    add_user(nama_user, user_info)

    # Auto-duplicate Default + Local State from parent (user_data/parent) to new user data
    ud_chrome = pending["user_data_chrome"]
    dup_msg = ""
    if os.path.isdir(PARENT_USER_DATA) and ud_chrome != PARENT_USER_DATA:
        os.makedirs(ud_chrome, exist_ok=True)
        # Determine folder names for _copy_user_data
        # Extract relative folder name if inside USER_DATA_BASE, else use full path copy
        parent_name = os.path.basename(PARENT_USER_DATA)  # "parent"
        dest_name = os.path.basename(ud_chrome)
        # Check if dest is inside USER_DATA_BASE
        if os.path.dirname(ud_chrome) == USER_DATA_BASE:
            ok, copy_result = _copy_user_data(parent_name, dest_name, mode="duplicate")
        else:
            # Manual copy for paths outside USER_DATA_BASE
            ok = False
            copy_result = ""
            src_def = os.path.join(PARENT_USER_DATA, "Default")
            dst_def = os.path.join(ud_chrome, "Default")
            src_ls = os.path.join(PARENT_USER_DATA, "Local State")
            dst_ls = os.path.join(ud_chrome, "Local State")
            parts = []
            if os.path.isdir(src_def) and not os.path.isdir(dst_def):
                try:
                    shutil.copytree(src_def, dst_def)
                    parts.append("✅ Default")
                    ok = True
                except Exception as e:
                    parts.append(f"❌ Default: {str(e)[:60]}")
            if os.path.isfile(src_ls) and not os.path.isfile(dst_ls):
                try:
                    shutil.copy2(src_ls, dst_ls)
                    parts.append("✅ Local State")
                    ok = True
                except Exception as e:
                    parts.append(f"❌ Local State: {str(e)[:60]}")
            copy_result = "\n".join(parts) if parts else "ℹ️ Sudah ada"
        dup_msg = f"\n\n📋 <b>Auto-Duplicate dari user_data/parent:</b>\n{escape_html(copy_result)}"
        logger.info(f"Auto-dup {PARENT_USER_DATA} → {ud_chrome}: {copy_result}")

    if query.data.startswith("confirm_run_"):
        # Run the bot
        pid = run_user_bot(nama_user)
        if pid:
            update_user(nama_user, {"pid": pid, "status": "running"})
            await query.edit_message_text(
                f"🚀 <b>Bot {escape_html(nama_user)} berhasil disimpan & dijalankan!</b>\n\n"
                f"📊 PID: <code>{pid}</code>\n"
                f"📁 Script: <code>{get_script_name(nama_user)}</code>\n"
                f"🔌 Port: <code>{pending['port']}</code>"
                f"{dup_msg}",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text(
                f"✅ <b>User {escape_html(nama_user)} disimpan.</b>\n"
                f"❌ <b>Tapi gagal menjalankan bot.</b>\n"
                f"📁 Script: <code>{get_script_name(nama_user)}</code>"
                f"{dup_msg}",
                parse_mode=ParseMode.HTML
            )
    else:
        # Save only
        await query.edit_message_text(
            f"✅ <b>User {escape_html(nama_user)} disimpan!</b>\n\n"
            f"📁 Script: <code>{get_script_name(nama_user)}</code>\n"
            f"🔌 Port: <code>{pending['port']}</code>"
            f"{dup_msg}\n\n"
            f"Gunakan /start untuk mengelola.",
            parse_mode=ParseMode.HTML
        )

    context.user_data.pop("pending_user", None)
    context.user_data.pop("awaiting", None)


async def _handle_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process edit user multi-line input."""
    nama = context.user_data.get("edit_user")
    if not nama:
        await update.message.reply_text("⚠️ User tidak ditemukan.")
        context.user_data.pop("awaiting", None)
        return

    user_info = get_user(nama)
    if not user_info:
        await update.message.reply_text(f"⚠️ User {escape_html(nama)} tidak ditemukan.", parse_mode=ParseMode.HTML)
        context.user_data.pop("awaiting", None)
        return

    text = update.message.text.strip()
    lines = [l.strip() for l in text.split("\n")]

    updates = {}

    # Parse each line (empty = skip)
    if len(lines) >= 1 and lines[0]:
        updates["bot_token"] = lines[0]
    if len(lines) >= 2 and lines[1]:
        updates["no_wa"] = lines[1]
    if len(lines) >= 3 and lines[2]:
        new_port = lines[2]
        used_ports = [p for p in get_used_ports() if p != user_info.get("port")]
        if new_port in used_ports:
            await update.message.reply_text(
                f"❌ Port <code>{new_port}</code> sudah dipakai user lain!",
                parse_mode=ParseMode.HTML)
            return
        updates["port"] = new_port
    if len(lines) >= 4 and lines[3]:
        new_ud = expand_user_data(lines[3])
        used_uds = [u for u in get_used_user_data() if u != user_info.get("user_data_chrome")]
        if new_ud in used_uds:
            await update.message.reply_text(
                f"❌ User data <code>{escape_html(new_ud)}</code> sudah dipakai user lain!",
                parse_mode=ParseMode.HTML)
            return
        updates["user_data_chrome"] = new_ud

    if not updates:
        await update.message.reply_text("ℹ️ Tidak ada perubahan.", parse_mode=ParseMode.HTML)
    else:
        # If bot is running, restart it
        was_running = False
        pid = user_info.get("pid")
        if pid and is_pid_running(pid):
            was_running = True
            kill_user_bot(nama)

        update_user(nama, updates)

        # Recreate script (copies latest template)
        create_user_script(nama)

        restart_msg = ""
        if was_running:
            new_pid = run_user_bot(nama)
            if new_pid:
                update_user(nama, {"pid": new_pid, "status": "running"})
                restart_msg = f"\n\n🔄 Bot di-restart, PID baru: <code>{new_pid}</code>"
            else:
                restart_msg = "\n\n⚠️ Gagal restart bot"

        changes = "\n".join([f"  ✏️ {k}: <code>{escape_html(str(v)[:50])}</code>" for k, v in updates.items()])
        await update.message.reply_text(
            f"✅ <b>User {escape_html(nama)} diperbarui!</b>\n\n{changes}{restart_msg}",
            parse_mode=ParseMode.HTML
        )

    context.user_data.pop("awaiting", None)
    context.user_data.pop("edit_user", None)


# ═══════════════════════════════════════════════════════════════
#  /TAMBAH COMMAND (shortcut)
# ═══════════════════════════════════════════════════════════════
async def cmd_tambah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut for adding user."""
    await update.message.reply_text(
        "➕ <b>TAMBAH USER</b>\n\n"
        "Kirim data user dengan format (pisah enter):\n\n"
        "<code>nama user</code>\n"
        "<code>BOT_TOKEN</code>\n"
        "<code>no.wa</code>\n"
        "<code>default port</code>\n"
        "<code>user data chrome (cukup isi angka, misal: 1)</code>\n\n"
        f"📌 Default path: <code>{escape_html(USER_DATA_BASE)}\\[angka]</code>\n"
        "📌 <i>Expiry otomatis 30 hari ke depan</i>\n"
        "⚠️ <i>Port & user data harus unique</i>\n\n"
        "Contoh:\n"
        "<code>Budi\n"
        "8781330231:AAxxxxxxxx\n"
        "081234567890\n"
        "9250\n"
        "5</code>",
        parse_mode=ParseMode.HTML
    )
    context.user_data["awaiting"] = "tambah_input"


# ═══════════════════════════════════════════════════════════════
#  /HAPUS COMMAND (shortcut)
# ═══════════════════════════════════════════════════════════════
async def cmd_hapus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shortcut for deleting user."""
    db = load_db()
    if not db:
        await update.message.reply_text(
            "🗑️ <b>Belum ada user untuk dihapus.</b>", parse_mode=ParseMode.HTML)
        return

    keyboard = []
    for nama, info in db.items():
        expired = is_user_expired(info)
        pid = info.get("pid")
        running = is_pid_running(pid) if pid else False
        label = f"{'🔴' if expired else '🟢'} {nama}"
        if running:
            label += " (Running)"
        if expired:
            label += " (Expired)"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"hapus_{nama}")])
    keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="hapus_cancel")])

    await update.message.reply_text(
        "🗑️ <b>HAPUS USER</b>\n\nPilih user yang ingin dihapus:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


# ═══════════════════════════════════════════════════════════════
#  /USERDATA COMMAND + USER DATA MANAGEMENT
# ═══════════════════════════════════════════════════════════════
def _list_user_data_folders() -> list:
    """List all subdirectories in USER_DATA_BASE."""
    if not os.path.isdir(USER_DATA_BASE):
        return []
    return sorted(
        [d for d in os.listdir(USER_DATA_BASE)
         if os.path.isdir(os.path.join(USER_DATA_BASE, d))],
        key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x)
    )


def _get_ud_info(folder_name: str) -> dict:
    """Get info about a user_data subfolder."""
    path = os.path.join(USER_DATA_BASE, folder_name)
    has_default = os.path.isdir(os.path.join(path, "Default"))
    has_local_state = os.path.isfile(os.path.join(path, "Local State"))
    # Check which bot user is using this folder
    full_path = path
    db = load_db()
    used_by = [n for n, u in db.items() if u.get("user_data_chrome") == full_path]
    return {
        "path": path,
        "has_default": has_default,
        "has_local_state": has_local_state,
        "used_by": used_by,
    }


def _copy_user_data(source_folder: str, dest_folder: str, mode: str = "replace") -> tuple:
    """
    Copy Default folder + Local State from source to dest.
    mode: 'replace' = overwrite, 'duplicate' = skip if exists.
    Returns (success: bool, message: str)
    """
    src_path = os.path.join(USER_DATA_BASE, source_folder)
    dst_path = os.path.join(USER_DATA_BASE, dest_folder)
    os.makedirs(dst_path, exist_ok=True)

    results = []

    # Copy Default folder
    src_default = os.path.join(src_path, "Default")
    dst_default = os.path.join(dst_path, "Default")
    if os.path.isdir(src_default):
        if os.path.isdir(dst_default):
            if mode == "duplicate":
                results.append("⏭️ Default sudah ada, skip (duplicate mode)")
            else:
                try:
                    shutil.rmtree(dst_default, ignore_errors=True)
                    shutil.copytree(src_default, dst_default)
                    results.append("✅ Default folder di-replace")
                except Exception as e:
                    results.append(f"❌ Gagal replace Default: {str(e)[:80]}")
        else:
            try:
                shutil.copytree(src_default, dst_default)
                results.append("✅ Default folder di-copy")
            except Exception as e:
                results.append(f"❌ Gagal copy Default: {str(e)[:80]}")
    else:
        results.append("⚠️ Source tidak punya folder Default")

    # Copy Local State
    src_ls = os.path.join(src_path, "Local State")
    dst_ls = os.path.join(dst_path, "Local State")
    if os.path.isfile(src_ls):
        if os.path.isfile(dst_ls):
            if mode == "duplicate":
                results.append("⏭️ Local State sudah ada, skip (duplicate mode)")
            else:
                try:
                    shutil.copy2(src_ls, dst_ls)
                    results.append("✅ Local State di-replace")
                except Exception as e:
                    results.append(f"❌ Gagal replace Local State: {str(e)[:80]}")
        else:
            try:
                shutil.copy2(src_ls, dst_ls)
                results.append("✅ Local State di-copy")
            except Exception as e:
                results.append(f"❌ Gagal copy Local State: {str(e)[:80]}")
    else:
        results.append("⚠️ Source tidak punya Local State")

    success = any("✅" in r for r in results)
    return success, "\n".join(results)


async def cmd_userdata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user data folder list."""
    await _show_userdata_menu(update, context)


async def _show_userdata_menu(update, context, edit=False):
    """Display user data folder list with management options."""
    folders = _list_user_data_folders()

    text = "📂 <b>DAFTAR USER DATA</b>\n"
    text += f"📁 Base: <code>{escape_html(USER_DATA_BASE)}</code>\n\n"

    if folders:
        for f in folders:
            info = _get_ud_info(f)
            icons = ""
            icons += "📁" if info["has_default"] else "❌"
            icons += "📄" if info["has_local_state"] else "❌"
            used = f" ← <b>{', '.join(info['used_by'])}</b>" if info['used_by'] else ""
            text += f"  {icons} <code>{f}</code>{used}\n"
        text += "\n📁=Default  📄=LocalState\n\n"
    else:
        text += "  <i>Tidak ada folder user data.</i>\n\n"

    keyboard = [
        [InlineKeyboardButton("🔄 Replace (Timpa)", callback_data="ud_replace"),
         InlineKeyboardButton("📋 Duplicate (Copy)", callback_data="ud_duplicate")],
        [InlineKeyboardButton("❌ Tutup", callback_data="ud_close")],
    ]

    markup = InlineKeyboardMarkup(keyboard)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML)
    else:
        msg = update.message if update.message else update.callback_query.message
        await msg.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)


async def userdata_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user data management callbacks."""
    query = update.callback_query
    await query.answer()

    if query.data == "ud_close":
        await query.edit_message_text("📂 Menu user data ditutup.", parse_mode=ParseMode.HTML)
        return

    if query.data == "menu_kelola_ud":
        await _show_userdata_menu(update, context, edit=True)
        return

    # ── Select mode (replace/duplicate) → show source picker ──
    if query.data in ("ud_replace", "ud_duplicate"):
        mode = "replace" if query.data == "ud_replace" else "duplicate"
        context.user_data["ud_mode"] = mode
        mode_label = "🔄 REPLACE (Timpa)" if mode == "replace" else "📋 DUPLICATE (Copy)"

        folders = _list_user_data_folders()
        if not folders:
            await query.edit_message_text(
                "⚠️ Tidak ada folder user data.", parse_mode=ParseMode.HTML)
            return

        keyboard = []
        for f in folders:
            info = _get_ud_info(f)
            if not info["has_default"] and not info["has_local_state"]:
                continue  # Skip empty folders as source
            label = f"📁 {f}"
            if info["used_by"]:
                label += f" ({', '.join(info['used_by'])})"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"udsrc_{f}")])
        keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="ud_close")])

        await query.edit_message_text(
            f"{mode_label}\n\n"
            f"📤 <b>Pilih folder SUMBER:</b>\n"
            f"<i>(Default & Local State akan dicopy dari folder ini)</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
        return

    # ── Source selected → show destination picker (multi-select) ──
    if query.data.startswith("udsrc_"):
        source = query.data[len("udsrc_"):]
        context.user_data["ud_source"] = source
        context.user_data["ud_selected_dests"] = []
        await _show_dest_picker(update, context)
        return

    # ── Toggle destination selection ──
    if query.data.startswith("udtoggle_"):
        dest = query.data[len("udtoggle_"):]
        selected = context.user_data.get("ud_selected_dests", [])
        if dest in selected:
            selected.remove(dest)
        else:
            selected.append(dest)
        context.user_data["ud_selected_dests"] = selected
        await _show_dest_picker(update, context)
        return

    # ── Select all destinations ──
    if query.data == "ud_select_all":
        source = context.user_data.get("ud_source", "")
        folders = _list_user_data_folders()
        all_dests = [f for f in folders if f != source]
        context.user_data["ud_selected_dests"] = all_dests
        await _show_dest_picker(update, context)
        return

    # ── Deselect all ──
    if query.data == "ud_deselect_all":
        context.user_data["ud_selected_dests"] = []
        await _show_dest_picker(update, context)
        return

    # ── Execute copy ──
    if query.data == "ud_execute":
        source = context.user_data.get("ud_source", "")
        dests = context.user_data.get("ud_selected_dests", [])
        mode = context.user_data.get("ud_mode", "replace")

        if not source or not dests:
            await query.edit_message_text(
                "⚠️ Pilih minimal 1 folder tujuan.", parse_mode=ParseMode.HTML)
            return

        mode_label = "REPLACE" if mode == "replace" else "DUPLICATE"
        await query.edit_message_text(
            f"⏳ <b>Memproses {mode_label}...</b>\n"
            f"📤 Sumber: <code>{source}</code>\n"
            f"📥 Tujuan: {len(dests)} folder",
            parse_mode=ParseMode.HTML
        )

        results_text = f"📊 <b>HASIL {mode_label}</b>\n"
        results_text += f"📤 Sumber: <code>{source}</code>\n\n"

        total_ok = 0
        total_fail = 0
        for d in dests:
            ok, msg = _copy_user_data(source, d, mode)
            icon = "✅" if ok else "❌"
            results_text += f"{icon} <b>→ {d}</b>\n{msg}\n\n"
            if ok:
                total_ok += 1
            else:
                total_fail += 1

        results_text += f"\n📊 Total: ✅ {total_ok} berhasil, ❌ {total_fail} gagal"

        await query.message.reply_text(
            results_text[:4096], parse_mode=ParseMode.HTML)

        # Cleanup state
        context.user_data.pop("ud_source", None)
        context.user_data.pop("ud_selected_dests", None)
        context.user_data.pop("ud_mode", None)
        return


async def _show_dest_picker(update, context):
    """Show destination folder picker with checkboxes."""
    query = update.callback_query
    source = context.user_data.get("ud_source", "")
    selected = context.user_data.get("ud_selected_dests", [])
    mode = context.user_data.get("ud_mode", "replace")
    mode_label = "🔄 REPLACE" if mode == "replace" else "📋 DUPLICATE"

    folders = _list_user_data_folders()

    text = (
        f"{mode_label}\n\n"
        f"📤 Sumber: <code>{source}</code>\n\n"
        f"📥 <b>Pilih folder TUJUAN</b> (klik untuk toggle):\n"
        f"<i>Terpilih: {len(selected)} folder</i>"
    )

    keyboard = []
    for f in folders:
        if f == source:
            continue  # Exclude source
        check = "☑️" if f in selected else "⬜"
        info = _get_ud_info(f)
        label = f"{check} {f}"
        if info["used_by"]:
            label += f" ({', '.join(info['used_by'])})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"udtoggle_{f}")])

    # Select all / Deselect all row
    keyboard.append([
        InlineKeyboardButton("✅ Pilih Semua", callback_data="ud_select_all"),
        InlineKeyboardButton("❎ Batal Pilih", callback_data="ud_deselect_all"),
    ])

    # Execute button (only if something selected)
    if selected:
        keyboard.append([InlineKeyboardButton(
            f"🚀 Eksekusi ({len(selected)} folder)", callback_data="ud_execute")])

    keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="ud_close")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    manager_token = MANAGER_BOT_TOKEN

    logger.info("═" * 50)
    logger.info("  🛠️  SGV MANAGER BOT")
    logger.info("═" * 50)
    logger.info(f"  📁 Users Dir : {USERS_DIR}")
    logger.info(f"  📊 Database  : {DB_FILE}")
    logger.info(f"  📄 Template  : {TEMPLATE_FILE}")
    logger.info("═" * 50)

    app = Application.builder().token(manager_token).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("tambah", cmd_tambah))
    app.add_handler(CommandHandler("hapus", cmd_hapus))
    app.add_handler(CommandHandler("userdata", cmd_userdata))

    # Callbacks
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu_(?!kelola_ud)"))
    app.add_handler(CallbackQueryHandler(userdata_callback, pattern=r"^(ud_|udsrc_|udtoggle_|menu_kelola_ud)"))
    app.add_handler(CallbackQueryHandler(hapus_callback, pattern=r"^hapus_"))
    app.add_handler(CallbackQueryHandler(edit_callback, pattern=r"^edit_"))
    app.add_handler(CallbackQueryHandler(confirm_callback, pattern=r"^confirm_"))
    app.add_handler(CallbackQueryHandler(run_callback, pattern=r"^(run_|stop_)"))

    # Message handler for state-based input
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Set bot commands
    async def set_commands(app):
        await app.bot.set_my_commands([
            BotCommand("start", "📋 Menu utama"),
            BotCommand("tambah", "➕ Tambah user"),
            BotCommand("hapus", "🗑️ Hapus user"),
            BotCommand("userdata", "📂 Kelola user data"),
        ])

    app.post_init = set_commands

    logger.info("🚀 Manager Bot dimulai!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
