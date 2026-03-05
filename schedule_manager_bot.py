"""
📅 Schedule Manager Bot — Telegram Bot
Manages schedules across multiple JSON files, preventing conflicts.
Each schedule triggers a 1-hour automated loop.
"""
import os
import sys
import json
import logging
import copy
from datetime import datetime, timedelta

from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8522116126:AAGmnqceG7dHBHqVGkuh_bmEthARDiXS2RQ"  # Ganti dengan token bot kamu
APP_DIR = r"C:\tiktok_automation"
LOOP_DURATION_MINUTES = 60  # Each schedule occupies 1 hour

# Registry file: stores list of managed JSON files + metadata
REGISTRY_FILE = os.path.join(APP_DIR, "schedule_registry.json")

# ═══════════════════════════════════════════════════════════════
#  DEFAULT REGISTERED FILES
# ═══════════════════════════════════════════════════════════════
DEFAULT_REGISTRY = [
    {
        "id": "yt_sched",
        "name": "YT Bot Schedule",
        "file": os.path.join(APP_DIR, "yt_schedule_state.json"),
        "range_hours": 40,
        "multi": False,  # single schedule entry
        "description": "YouTube bot auto-upload schedule"
    },
    {
        "id": "tiktok_sched",
        "name": "TikTok Bot Schedule",
        "file": os.path.join(APP_DIR, "schedule_state.json"),
        "range_hours": 24,
        "multi": False,
        "description": "TikTok bot auto-upload schedule"
    },
]


# ═══════════════════════════════════════════════════════════════
#  REGISTRY MANAGEMENT
# ═══════════════════════════════════════════════════════════════
def load_registry():
    """Load the registry of managed schedule files."""
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    # First run: save defaults
    save_registry(DEFAULT_REGISTRY)
    return copy.deepcopy(DEFAULT_REGISTRY)


def save_registry(registry):
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def get_entry_by_id(reg_id):
    registry = load_registry()
    for entry in registry:
        if entry["id"] == reg_id:
            return entry
    return None


# ═══════════════════════════════════════════════════════════════
#  SCHEDULE FILE I/O
# ═══════════════════════════════════════════════════════════════
def _read_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _write_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_schedule_entry(entry):
    """Parse a single schedule dict {tanggal, jam, menit} → datetime or None."""
    try:
        t = entry.get("tanggal", "")
        j = str(entry.get("jam", "0")).zfill(2)
        m = str(entry.get("menit", "0")).zfill(2)
        return datetime.strptime(f"{t} {j}:{m}", "%Y-%m-%d %H:%M")
    except Exception:
        return None


def load_schedules_from_file(filepath, multi=False):
    """
    Returns list of (datetime, raw_dict, slot_key) from a file.
    Auto-detects whether the file is single or multi user-data format.
    """
    data = _read_json(filepath)
    if not data:
        return []

    results = []

    # Auto-detect structure
    if isinstance(data, dict):
        # Check if it's a single schedule (has 'tanggal' at top level)
        if "tanggal" in data:
            dt = parse_schedule_entry(data)
            if dt:
                results.append((dt, data, "0"))
        else:
            # It's a dict containing per-user-data schedules
            # e.g. {"1": {tanggal...}, "2": {tanggal...}}
            for key, val in data.items():
                if isinstance(val, dict) and "tanggal" in val:
                    dt = parse_schedule_entry(val)
                    if dt:
                        results.append((dt, val, str(key)))
    elif isinstance(data, list):
        for i, val in enumerate(data):
            if isinstance(val, dict) and "tanggal" in val:
                dt = parse_schedule_entry(val)
                if dt:
                    results.append((dt, val, str(i)))

    return results


def get_all_schedules():
    """
    Collect ALL schedules across all registered files.
    Returns: list of (datetime, reg_id, slot_key, entry_name)
    """
    registry = load_registry()
    all_scheds = []
    for reg in registry:
        scheds = load_schedules_from_file(reg["file"], reg.get("multi", False))
        for dt, raw, slot_key in scheds:
            all_scheds.append((dt, reg["id"], slot_key, reg["name"]))
    all_scheds.sort(key=lambda x: x[0])
    return all_scheds


def check_conflict(new_dt, exclude_reg_id=None, exclude_slot=None):
    """
    Check if new_dt conflicts with ANY existing schedule.
    A conflict = two schedules overlap within their 1-hour duration.
    Returns: (has_conflict: bool, conflicting_info: str or None)
    """
    all_scheds = get_all_schedules()
    new_start = new_dt
    new_end = new_dt + timedelta(minutes=LOOP_DURATION_MINUTES)

    for dt, reg_id, slot_key, name in all_scheds:
        # Skip self
        if exclude_reg_id and exclude_slot is not None:
            if reg_id == exclude_reg_id and str(slot_key) == str(exclude_slot):
                continue

        existing_start = dt
        existing_end = dt + timedelta(minutes=LOOP_DURATION_MINUTES)

        # Overlap check
        if new_start < existing_end and new_end > existing_start:
            return True, (
                f"\u26a0\ufe0f Konflik dengan <b>{name}</b> (Slot: {slot_key})\n"
                f"  Waktu: {existing_start.strftime('%Y-%m-%d %H:%M')} \u2014 "
                f"{existing_end.strftime('%H:%M')}"
            )

    return False, None


def update_schedule_in_file(filepath, multi, slot_key, new_dt):
    """Update a specific schedule slot in a file."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_entry = {
        "tanggal": new_dt.strftime("%Y-%m-%d"),
        "jam": f"{new_dt.hour:02d}",
        "menit": f"{new_dt.minute:02d}",
        "updated_at": now_str
    }

    data = _read_json(filepath)
    if data is None:
        data = {}

    # Auto-detect if we should use single or multi format
    is_multi_format = False
    if isinstance(data, dict):
        if not data or ("tanggal" not in data and len(data) > 0) or str(slot_key) != "0":
            is_multi_format = True
    elif isinstance(data, list):
        is_multi_format = True

    # Enforce multi if registry says so
    if multi:
        is_multi_format = True

    if is_multi_format:
        if isinstance(data, list):
            try:
                idx = int(slot_key)
            except ValueError:
                idx = 0
            while len(data) <= idx:
                data.append({})
            data[idx] = new_entry
        else:
            if not isinstance(data, dict) or "tanggal" in data:
                # Upgrade path: single → multi dict
                data = {str(slot_key): new_entry}
            else:
                data[str(slot_key)] = new_entry
        _write_json(filepath, data)
    else:
        _write_json(filepath, new_entry)


def delete_schedule_in_file(filepath, multi, slot_key):
    """Delete a specific schedule slot from a file."""
    data = _read_json(filepath)
    if not data:
        return

    if isinstance(data, list):
        try:
            idx = int(slot_key)
            if 0 <= idx < len(data):
                data.pop(idx)
        except ValueError:
            pass
        _write_json(filepath, data)
    elif isinstance(data, dict):
        if "tanggal" in data:
            # Single format → clear
            _write_json(filepath, {})
        else:
            # Multi format → remove specific slot
            data.pop(str(slot_key), None)
            _write_json(filepath, data)


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def time_until(dt):
    diff = dt - datetime.now()
    total_sec = int(diff.total_seconds())
    if total_sec <= 0:
        return "⏰ sudah lewat"
    hours = total_sec // 3600
    mins = (total_sec % 3600) // 60
    if hours > 0:
        return f"{hours}j {mins}m lagi"
    return f"{mins}m lagi"


# ═══════════════════════════════════════════════════════════════
#  BOT COMMANDS
# ═══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    registry = load_registry()
    all_scheds = get_all_schedules()
    now = datetime.now()

    text = (
        "📅 <b>Schedule Manager Bot</b>\n\n"
        f"🕐 Waktu sekarang: <code>{now.strftime('%Y-%m-%d %H:%M')}</code>\n"
        f"📋 File terdaftar: <b>{len(registry)}</b>\n"
        f"📊 Total jadwal: <b>{len(all_scheds)}</b>\n\n"
    )

    if all_scheds:
        text += "📅 <b>Jadwal Terdekat:</b>\n"
        upcoming = [s for s in all_scheds if s[0] > now]
        past = [s for s in all_scheds if s[0] <= now]

        for dt, reg_id, slot, name in upcoming[:5]:
            end_dt = dt + timedelta(minutes=LOOP_DURATION_MINUTES)
            text += (
                f"  🟢 <code>{format_dt(dt)}</code> — "
                f"<code>{end_dt.strftime('%H:%M')}</code>  "
                f"<b>{name}</b>  ({time_until(dt)})\n"
            )
        if past:
            text += f"\n  ⚪ {len(past)} jadwal sudah lewat\n"
        if len(upcoming) > 5:
            text += f"  ... +{len(upcoming)-5} lagi\n"
    else:
        text += "<i>Belum ada jadwal.</i>\n"

    text += (
        "\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "📖 <b>Perintah:</b>\n"
        "/start — Menu utama\n"
        "/list — Lihat semua jadwal\n"
        "/files — Kelola file schedule\n"
        "/set — Ubah jadwal\n"
        "/add — Tambah file baru\n"
        "/conflict — Cek konflik\n"
        "/help — Panduan lengkap\n"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Lihat Semua Jadwal", callback_data="list_all")],
        [InlineKeyboardButton("� Slot Kosong", callback_data="slots_0"),
         InlineKeyboardButton("�📁 Kelola File", callback_data="files_list")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_start")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text, kb = _build_list_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


def _build_list_view():
    """Build the full schedule list text + keyboard."""
    registry = load_registry()
    now = datetime.now()

    text = f"📅 <b>Semua Jadwal</b>  ({now.strftime('%Y-%m-%d %H:%M')})\n\n"

    buttons = []
    total_count = 0

    for reg in registry:
        scheds = load_schedules_from_file(reg["file"], reg.get("multi", False))
        scheds.sort(key=lambda x: x[0])

        range_h = reg.get("range_hours", 24)
        text += (
            f"{'━'*30}\n"
            f"📁 <b>{reg['name']}</b>\n"
            f"   📄 <code>{os.path.basename(reg['file'])}</code>\n"
            f"   ⏱ Range: {range_h}h | Slots: {len(scheds)}\n"
        )

        if scheds:
            for dt, raw, slot_key in scheds:
                total_count += 1
                end_dt = dt + timedelta(minutes=LOOP_DURATION_MINUTES)
                is_past = dt <= now
                is_active = dt <= now < end_dt
                if is_active:
                    icon = "🔴"
                    status = " AKTIF"
                elif is_past:
                    icon = "⚪"
                    status = " lewat"
                else:
                    icon = "🟢"
                    status = f" {time_until(dt)}"

                text += (
                    f"   {icon} [{slot_key}] <code>{format_dt(dt)}</code>—"
                    f"<code>{end_dt.strftime('%H:%M')}</code>"
                    f"  {status}\n"
                )
        else:
            text += "   <i>(kosong)</i>\n"
        text += "\n"

        buttons.append([InlineKeyboardButton(
            f"✏️ {reg['name']}", callback_data=f"edit_file|{reg['id']}"
        )])

    text += f"📊 Total: <b>{total_count}</b> jadwal"

    # Check for conflicts
    conflicts = _find_all_conflicts()
    if conflicts:
        text += f"\n\n⚠️ <b>{len(conflicts)} KONFLIK ditemukan!</b>\n"
        for c in conflicts[:3]:
            text += f"  {c}\n"

    buttons.append([InlineKeyboardButton("🕐 Slot Kosong", callback_data="slots_0")])
    buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="refresh_start")])
    return text, InlineKeyboardMarkup(buttons)


def _find_all_conflicts():
    """Find all conflicting schedule pairs."""
    all_scheds = get_all_schedules()
    conflicts = []
    for i in range(len(all_scheds)):
        for j in range(i + 1, len(all_scheds)):
            dt_a, id_a, _, name_a = all_scheds[i]
            dt_b, id_b, _, name_b = all_scheds[j]
            end_a = dt_a + timedelta(minutes=LOOP_DURATION_MINUTES)
            end_b = dt_b + timedelta(minutes=LOOP_DURATION_MINUTES)
            if dt_a < end_b and dt_b < end_a:
                conflicts.append(
                    f"⚠️ {name_a} ({format_dt(dt_a)}) ↔ {name_b} ({format_dt(dt_b)})"
                )
    return conflicts


async def cmd_files(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text, kb = _build_files_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


def _build_files_view():
    registry = load_registry()
    text = "📁 <b>File Schedule Terdaftar</b>\n\n"
    buttons = []

    for i, reg in enumerate(registry):
        exists = os.path.exists(reg["file"])
        icon = "✅" if exists else "❌"
        scheds = load_schedules_from_file(reg["file"], reg.get("multi", False)) if exists else []
        text += (
            f"{i+1}. {icon} <b>{reg['name']}</b>\n"
            f"   📄 <code>{os.path.basename(reg['file'])}</code>\n"
            f"   ⏱ Range: {reg.get('range_hours', 24)}h | "
            f"Multi: {'Ya' if reg.get('multi') else 'Tidak'} | "
            f"Slots: {len(scheds)}\n"
            f"   📝 {reg.get('description', '-')}\n\n"
        )
        buttons.append([
            InlineKeyboardButton(f"✏️ {reg['name']}", callback_data=f"edit_file|{reg['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"remove_file|{reg['id']}")
        ])

    buttons.append([InlineKeyboardButton("➕ Tambah File Baru", callback_data="add_file_start")])
    buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="refresh_start")])
    return text, InlineKeyboardMarkup(buttons)


async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /set <file_id> <YYYY-MM-DD> <HH:MM> [slot_key]
    Example: /set yt_sched 2026-03-05 14:30
    """
    raw = update.message.text.strip()
    parts = raw.split()

    if len(parts) < 4:
        registry = load_registry()
        ids = "\n".join(f"  <code>{r['id']}</code> — {r['name']}" for r in registry)
        await update.message.reply_text(
            "📅 <b>Format /set:</b>\n\n"
            "<code>/set &lt;file_id&gt; &lt;YYYY-MM-DD&gt; &lt;HH:MM&gt; [slot_key]</code>\n\n"
            f"<b>File IDs:</b>\n{ids}\n\n"
            "<b>Contoh:</b>\n"
            "<code>/set yt_sched 2026-03-05 14:30</code>\n"
            "<code>/set tiktok_sched 2026-03-05 20:00</code>",
            parse_mode=ParseMode.HTML
        )
        return

    file_id = parts[1]
    date_str = parts[2]
    time_str = parts[3].replace(".", ":")
    slot_key = parts[4] if len(parts) > 4 else "0"

    reg = get_entry_by_id(file_id)
    if not reg:
        await update.message.reply_text(f"❌ File ID <code>{file_id}</code> tidak ditemukan.", parse_mode=ParseMode.HTML)
        return

    try:
        time_parts = time_str.split(":")
        new_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=int(time_parts[0]), minute=int(time_parts[1])
        )
    except Exception:
        await update.message.reply_text("❌ Format tanggal/waktu salah.\nContoh: <code>2026-03-05 14:30</code>",
                                         parse_mode=ParseMode.HTML)
        return

    # Validate: must be in the future
    now = datetime.now()
    if new_dt <= now:
        await update.message.reply_text(
            f"❌ Jadwal harus di masa depan!\n"
            f"Sekarang: <code>{now.strftime('%Y-%m-%d %H:%M')}</code>\n"
            f"Input: <code>{format_dt(new_dt)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # Validate: within range
    max_dt = now + timedelta(hours=reg.get("range_hours", 24))
    if new_dt > max_dt:
        await update.message.reply_text(
            f"❌ Jadwal melebihi range {reg['range_hours']}h!\n"
            f"Maksimum: <code>{format_dt(max_dt)}</code>\n"
            f"Input: <code>{format_dt(new_dt)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # Check conflicts
    has_conflict, conflict_msg = check_conflict(new_dt, file_id, slot_key)
    if has_conflict:
        await update.message.reply_text(
            f"❌ <b>Jadwal ditolak — konflik!</b>\n\n"
            f"Input: <code>{format_dt(new_dt)}</code> — <code>{(new_dt + timedelta(minutes=60)).strftime('%H:%M')}</code>\n\n"
            f"{conflict_msg}\n\n"
            f"Dua jadwal tidak boleh overlap dalam 1 jam.",
            parse_mode=ParseMode.HTML
        )
        return

    # Save
    update_schedule_in_file(reg["file"], reg.get("multi", False), slot_key, new_dt)
    end_dt = new_dt + timedelta(minutes=LOOP_DURATION_MINUTES)

    await update.message.reply_text(
        f"✅ <b>Jadwal disimpan!</b>\n\n"
        f"📁 {reg['name']}\n"
        f"📅 <code>{format_dt(new_dt)}</code> — <code>{end_dt.strftime('%H:%M')}</code>\n"
        f"⏱ {time_until(new_dt)}\n"
        f"🔑 Slot: <code>{slot_key}</code>",
        parse_mode=ParseMode.HTML
    )


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /add <file_id> <filename.json> <range_hours> <description>
    Example: /add grok_sched grok_schedule.json 48 Grok bot schedule
    """
    raw = update.message.text.strip()
    parts = raw.split(None, 4)

    if len(parts) < 4:
        await update.message.reply_text(
            "➕ <b>Tambah File Schedule:</b>\n\n"
            "<code>/add &lt;id&gt; &lt;filename.json&gt; &lt;range_hours&gt; [deskripsi]</code>\n\n"
            "<b>Contoh:</b>\n"
            "<code>/add grok_sched grok_schedule.json 48 Grok bot schedule</code>\n\n"
            "<b>Parameter:</b>\n"
            "• <b>id</b>: Unique identifier (tanpa spasi)\n"
            "• <b>filename.json</b>: Nama file JSON\n"
            "• <b>range_hours</b>: Range waktu (jam)\n"
            "• <b>deskripsi</b>: Keterangan (opsional)",
            parse_mode=ParseMode.HTML
        )
        return

    file_id = parts[1]
    filename = parts[2]
    try:
        range_hours = int(parts[3])
    except ValueError:
        await update.message.reply_text("❌ range_hours harus berupa angka.")
        return
    description = parts[4] if len(parts) > 4 else ""

    # Check duplicate
    if get_entry_by_id(file_id):
        await update.message.reply_text(f"❌ ID <code>{file_id}</code> sudah ada.", parse_mode=ParseMode.HTML)
        return

    filepath = os.path.join(APP_DIR, filename)

    # Create empty file if not exists
    if not os.path.exists(filepath):
        _write_json(filepath, {})

    new_entry = {
        "id": file_id,
        "name": file_id.replace("_", " ").title(),
        "file": filepath,
        "range_hours": range_hours,
        "multi": True,
        "description": description
    }

    registry = load_registry()
    registry.append(new_entry)
    save_registry(registry)

    await update.message.reply_text(
        f"✅ <b>File schedule ditambahkan!</b>\n\n"
        f"🔑 ID: <code>{file_id}</code>\n"
        f"📄 File: <code>{filename}</code>\n"
        f"⏱ Range: {range_hours}h\n"
        f"📝 {description or '-'}",
        parse_mode=ParseMode.HTML
    )


async def cmd_conflict(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Check all conflicts across all files."""
    conflicts = _find_all_conflicts()
    all_scheds = get_all_schedules()

    if not all_scheds:
        await update.message.reply_text("📅 Tidak ada jadwal.")
        return

    text = f"🔍 <b>Conflict Check</b>\n\n"
    text += f"📊 Total jadwal: <b>{len(all_scheds)}</b>\n\n"

    if conflicts:
        text += f"⚠️ <b>{len(conflicts)} konflik ditemukan!</b>\n\n"
        for c in conflicts:
            text += f"{c}\n"
        text += "\nGunakan /set untuk mengubah jadwal yang konflik."
    else:
        text += "✅ <b>Tidak ada konflik!</b>\n\nSemua jadwal tidak saling tumpang tindih."

    # Show timeline
    text += "\n\n📅 <b>Timeline:</b>\n"
    for dt, reg_id, slot, name in all_scheds:
        end_dt = dt + timedelta(minutes=LOOP_DURATION_MINUTES)
        now = datetime.now()
        if dt <= now < end_dt:
            icon = "🔴"
        elif dt > now:
            icon = "🟢"
        else:
            icon = "⚪"
        text += f"  {icon} <code>{format_dt(dt)}</code>—<code>{end_dt.strftime('%H:%M')}</code>  {name}\n"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>Schedule Manager Bot — Panduan</b>\n\n"
        "Bot ini mengelola jadwal scheduling dari berbagai file JSON, "
        "mencegah konflik antar jadwal (setiap jadwal = 1 jam).\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>Perintah:</b>\n\n"
        "/start — Menu utama + ringkasan jadwal\n"
        "/list — Lihat semua jadwal dari semua file\n"
        "/files — Kelola file schedule terdaftar\n"
        "/set — Ubah/tambah jadwal di file\n"
        "/add — Tambah file schedule baru\n"
        "/conflict — Cek apakah ada jadwal yang konflik\n"
        "/help — Panduan ini\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ <b>Format /set:</b>\n\n"
        "<code>/set file_id YYYY-MM-DD HH:MM [slot]</code>\n\n"
        "Contoh:\n"
        "<code>/set yt_sched 2026-03-05 14:30</code>\n"
        "<code>/set tiktok_sched 2026-03-05 20:00</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "➕ <b>Format /add:</b>\n\n"
        "<code>/add id nama_file.json range_hours deskripsi</code>\n\n"
        "Contoh:\n"
        "<code>/add grok_sched grok_schedule.json 48 Grok bot schedule</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <b>Aturan Konflik:</b>\n\n"
        "• Setiap jadwal menggunakan slot 1 jam\n"
        "• Dua jadwal TIDAK boleh overlap\n"
        "• Contoh: jika ada jadwal 14:00—15:00,\n"
        "  maka 14:30 akan ditolak (overlap!)\n"
        "• Jadwal harus di masa depan & dalam range file\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def _build_slots_view(day_offset=0):
    """
    Build a visual timeline showing occupied and free 1-hour slots.
    day_offset: 0 = today, 1 = tomorrow, etc.
    Shows 24 hourly slots for the selected day.
    """
    now = datetime.now()
    base_date = (now + timedelta(days=day_offset)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # If today, start from current hour
    if day_offset == 0:
        start_hour = now.hour
    else:
        start_hour = 0

    all_scheds = get_all_schedules()
    registry = load_registry()

    date_str = base_date.strftime("%Y-%m-%d")
    day_name = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"][base_date.weekday()]

    text = (
        f"🕐 <b>Slot Timeline — {day_name}, {date_str}</b>\n"
        f"   Sekarang: <code>{now.strftime('%H:%M')}</code>\n\n"
        f"   🟢 = Kosong   🔴 = Terisi   ⚪ = Lewat\n\n"
    )

    free_slots = []  # collect free slots for buttons

    for h in range(start_hour, 24):
        slot_start = base_date.replace(hour=h)
        slot_end = slot_start + timedelta(hours=1)

        # Skip past slots
        if slot_end <= now:
            continue

        # Check if any schedule occupies this hour
        occupants = []
        for dt, reg_id, slot_key, name in all_scheds:
            sched_end = dt + timedelta(minutes=LOOP_DURATION_MINUTES)
            # Overlap check: schedule [dt, sched_end) overlaps with [slot_start, slot_end)
            if dt < slot_end and sched_end > slot_start:
                occupants.append(name)

        hour_str = f"{h:02d}:00"
        end_str = f"{(h+1) % 24:02d}:00"

        if occupants:
            names = ", ".join(occupants)
            text += f"   🔴 <code>{hour_str}—{end_str}</code>  {names}\n"
        else:
            text += f"   🟢 <code>{hour_str}—{end_str}</code>  <i>kosong</i>\n"
            free_slots.append((slot_start, h))

    if not any(h >= start_hour for h in range(start_hour, 24)):
        text += "   <i>Tidak ada slot tersisa hari ini.</i>\n"

    # Summary
    total_slots = 24 - start_hour
    total_free = len(free_slots)
    total_busy = total_slots - total_free
    text += (
        f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Kosong: <b>{total_free}</b> | Terisi: <b>{total_busy}</b>\n"
    )

    # Buttons: show file IDs for quick /set commands
    if free_slots:
        # Show helper for available file IDs
        ids_str = ", ".join(f"<code>{r['id']}</code>" for r in registry)
        text += (
            f"\n📝 <b>Isi slot kosong:</b>\n"
            f"<code>/set FILE_ID {date_str} HH:MM</code>\n"
            f"File IDs: {ids_str}\n"
        )
        # Show up to 4 suggested commands for free slots
        text += "\n🔹 <b>Contoh cepat:</b>\n"
        for slot_dt, h in free_slots[:4]:
            for r in registry[:2]:  # show suggestion for first 2 files
                text += f"  <code>/set {r['id']} {date_str} {h:02d}:00</code>\n"
            break  # only show first free slot suggestions

    # Navigation buttons
    buttons = []

    # Quick-fill buttons for free slots (first 6)
    if free_slots and registry:
        for slot_dt, h in free_slots[:6]:
            row = []
            for r in registry[:3]:  # max 3 files per row
                cmd_text = f"/set {r['id']} {date_str} {h:02d}:00"
                row.append(InlineKeyboardButton(
                    f"{h:02d}:00 → {r['name'][:10]}",
                    callback_data=f"quickset|{r['id']}|{date_str}|{h:02d}:00"
                ))
            buttons.append(row)

    # Day navigation
    nav_row = []
    if day_offset > 0:
        nav_row.append(InlineKeyboardButton("◀ Sebelumnya", callback_data=f"slots_{day_offset - 1}"))
    if day_offset < 6:  # max 7 days ahead
        next_date = (now + timedelta(days=day_offset + 1)).strftime("%d/%m")
        nav_row.append(InlineKeyboardButton(f"▶ {next_date}", callback_data=f"slots_{day_offset + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="refresh_start")])

    return text, InlineKeyboardMarkup(buttons)


async def cmd_slots(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show available/occupied slots timeline."""
    # Check if user passed a day offset: /slots 1 = tomorrow
    raw = update.message.text.strip()
    parts = raw.split()
    day_offset = 0
    if len(parts) > 1:
        try:
            day_offset = max(0, min(6, int(parts[1])))
        except ValueError:
            pass

    text, kb = _build_slots_view(day_offset)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    bot = ctx.bot

    if data == "refresh_start":
        registry = load_registry()
        all_scheds = get_all_schedules()
        now = datetime.now()
        text = (
            "📅 <b>Schedule Manager Bot</b>\n\n"
            f"🕐 Waktu sekarang: <code>{now.strftime('%Y-%m-%d %H:%M')}</code>\n"
            f"📋 File terdaftar: <b>{len(registry)}</b>\n"
            f"📊 Total jadwal: <b>{len(all_scheds)}</b>\n\n"
        )
        if all_scheds:
            upcoming = [s for s in all_scheds if s[0] > now]
            text += "📅 <b>Jadwal Terdekat:</b>\n"
            for dt, reg_id, slot, name in upcoming[:5]:
                end_dt = dt + timedelta(minutes=LOOP_DURATION_MINUTES)
                text += (
                    f"  🟢 <code>{format_dt(dt)}</code> — "
                    f"<code>{end_dt.strftime('%H:%M')}</code>  "
                    f"<b>{name}</b>  ({time_until(dt)})\n"
                )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Lihat Semua Jadwal", callback_data="list_all")],
            [InlineKeyboardButton("🕐 Slot Kosong", callback_data="slots_0"),
             InlineKeyboardButton("📁 Kelola File", callback_data="files_list")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_start")],
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "list_all":
        text, kb = _build_list_view()
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "files_list":
        text, kb = _build_files_view()
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # ── Edit file detail: show slots + actions ──
    if data.startswith("edit_file|"):
        reg_id = data.split("|", 1)[1]
        reg = get_entry_by_id(reg_id)
        if not reg:
            await q.edit_message_text("❌ File tidak ditemukan.")
            return

        scheds = load_schedules_from_file(reg["file"], reg.get("multi", False))
        scheds.sort(key=lambda x: x[0])
        now = datetime.now()

        text = (
            f"✏️ <b>{reg['name']}</b>\n"
            f"📄 <code>{os.path.basename(reg['file'])}</code>\n"
            f"⏱ Range: {reg.get('range_hours', 24)}h\n\n"
        )

        buttons = []
        if scheds:
            text += "📅 <b>Jadwal:</b>\n"
            for dt, raw, slot_key in scheds:
                end_dt = dt + timedelta(minutes=LOOP_DURATION_MINUTES)
                is_past = dt <= now
                icon = "⚪" if is_past else "🟢"
                text += (
                    f"  {icon} [{slot_key}] <code>{format_dt(dt)}</code>—"
                    f"<code>{end_dt.strftime('%H:%M')}</code>"
                    f"  {time_until(dt)}\n"
                )
                buttons.append([
                    InlineKeyboardButton(f"✏️ Slot {slot_key}", callback_data=f"edit_slot|{reg_id}|{slot_key}"),
                    InlineKeyboardButton(f"🗑 Hapus", callback_data=f"del_slot|{reg_id}|{slot_key}")
                ])
        else:
            text += "<i>Belum ada jadwal.</i>\n"

        text += (
            f"\n\n📝 <b>Ubah jadwal via command:</b>\n"
            f"<code>/set {reg_id} 2026-03-05 14:30</code>"
        )

        buttons.append([InlineKeyboardButton("⬅ Kembali", callback_data="list_all")])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # ── Edit slot: suggest command ──
    if data.startswith("edit_slot|"):
        parts = data.split("|")
        reg_id, slot_key = parts[1], parts[2]
        reg = get_entry_by_id(reg_id)
        if not reg:
            await q.edit_message_text("❌ File tidak ditemukan.")
            return

        scheds = load_schedules_from_file(reg["file"], reg.get("multi", False))
        current = None
        for dt, raw, sk in scheds:
            if sk == slot_key:
                current = dt
                break

        now = datetime.now()
        suggested = now + timedelta(hours=2)
        suggested = suggested.replace(minute=(suggested.minute // 5) * 5, second=0, microsecond=0)

        text = (
            f"✏️ <b>Edit Slot {slot_key}</b> — {reg['name']}\n\n"
        )
        if current:
            text += f"📅 Saat ini: <code>{format_dt(current)}</code>\n"
        text += (
            f"\nKirim command untuk mengubah:\n"
            f"<code>/set {reg_id} {suggested.strftime('%Y-%m-%d %H:%M')}"
            f"{' ' + slot_key if slot_key != '0' else ''}</code>"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅ Kembali", callback_data=f"edit_file|{reg_id}")]
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # ── Delete slot ──
    if data.startswith("del_slot|"):
        parts = data.split("|")
        reg_id, slot_key = parts[1], parts[2]
        reg = get_entry_by_id(reg_id)
        if not reg:
            await q.edit_message_text("❌ File tidak ditemukan.")
            return

        delete_schedule_in_file(reg["file"], reg.get("multi", False), slot_key)

        await bot.send_message(
            q.message.chat_id,
            f"✅ Slot <code>{slot_key}</code> dihapus dari <b>{reg['name']}</b>",
            parse_mode=ParseMode.HTML
        )

        # Refresh file view
        scheds = load_schedules_from_file(reg["file"], reg.get("multi", False))
        scheds.sort(key=lambda x: x[0])
        now = datetime.now()
        text = f"✏️ <b>{reg['name']}</b>\n📄 <code>{os.path.basename(reg['file'])}</code>\n\n"
        buttons = []
        if scheds:
            text += "📅 <b>Jadwal:</b>\n"
            for dt, raw, sk in scheds:
                end_dt = dt + timedelta(minutes=LOOP_DURATION_MINUTES)
                icon = "⚪" if dt <= now else "🟢"
                text += f"  {icon} [{sk}] <code>{format_dt(dt)}</code>—<code>{end_dt.strftime('%H:%M')}</code>\n"
                buttons.append([
                    InlineKeyboardButton(f"✏️ Slot {sk}", callback_data=f"edit_slot|{reg_id}|{sk}"),
                    InlineKeyboardButton(f"🗑 Hapus", callback_data=f"del_slot|{reg_id}|{sk}")
                ])
        else:
            text += "<i>Kosong.</i>\n"
        buttons.append([InlineKeyboardButton("⬅ Kembali", callback_data="list_all")])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # ── Remove file from registry ──
    if data.startswith("remove_file|"):
        reg_id = data.split("|", 1)[1]
        registry = load_registry()
        new_reg = [r for r in registry if r["id"] != reg_id]
        if len(new_reg) == len(registry):
            await q.edit_message_text("❌ File tidak ditemukan.")
            return
        save_registry(new_reg)

        await bot.send_message(
            q.message.chat_id,
            f"✅ File <code>{reg_id}</code> dihapus dari registry.\n"
            f"(File JSON tidak dihapus dari disk)",
            parse_mode=ParseMode.HTML
        )
        text, kb = _build_files_view()
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # ── Add file: prompt ──
    if data == "add_file_start":
        text = (
            "➕ <b>Tambah File Schedule Baru</b>\n\n"
            "Gunakan command:\n\n"
            "<code>/add &lt;id&gt; &lt;filename.json&gt; &lt;range_hours&gt; [deskripsi]</code>\n\n"
            "<b>Contoh:</b>\n"
            "<code>/add grok_sched grok_schedule.json 48 Grok bot schedule</code>\n"
            "<code>/add my_bot my_bot_schedule.json 72 Custom bot schedule</code>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅ Kembali", callback_data="files_list")]
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # ── Slots timeline ──
    if data.startswith("slots_"):
        day_offset = int(data.split("_")[1])
        text, kb = _build_slots_view(day_offset)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # ── Quick-set from slots view ──
    if data.startswith("quickset|"):
        parts = data.split("|")
        reg_id, date_str, time_str = parts[1], parts[2], parts[3]
        reg = get_entry_by_id(reg_id)
        if not reg:
            await q.edit_message_text("❌ File tidak ditemukan.")
            return

        try:
            tp = time_str.split(":")
            new_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                hour=int(tp[0]), minute=int(tp[1])
            )
        except:
            await q.edit_message_text("❌ Format waktu salah.")
            return

        now = datetime.now()
        if new_dt <= now:
            await bot.send_message(
                q.message.chat_id,
                "❌ Slot ini sudah lewat!",
                parse_mode=ParseMode.HTML
            )
            return

        max_dt = now + timedelta(hours=reg.get("range_hours", 24))
        if new_dt > max_dt:
            await bot.send_message(
                q.message.chat_id,
                f"❌ Melebihi range {reg['range_hours']}h untuk {reg['name']}!",
                parse_mode=ParseMode.HTML
            )
            return

        has_conflict, conflict_msg = check_conflict(new_dt, reg_id, "0")
        if has_conflict:
            await bot.send_message(
                q.message.chat_id,
                f"❌ <b>Konflik!</b>\n\n{conflict_msg}",
                parse_mode=ParseMode.HTML
            )
            return

        update_schedule_in_file(reg["file"], reg.get("multi", False), "0", new_dt)
        end_dt = new_dt + timedelta(minutes=LOOP_DURATION_MINUTES)

        await bot.send_message(
            q.message.chat_id,
            f"✅ <b>Jadwal disimpan!</b>\n\n"
            f"📁 {reg['name']}\n"
            f"📅 <code>{format_dt(new_dt)}</code> — <code>{end_dt.strftime('%H:%M')}</code>\n"
            f"⏱ {time_until(new_dt)}",
            parse_mode=ParseMode.HTML
        )

        # Refresh slots view
        day_offset = (new_dt.date() - now.date()).days
        text, kb = _build_slots_view(max(0, day_offset))
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "📅 Menu utama"),
        BotCommand("list", "📋 Lihat semua jadwal"),
        BotCommand("slots", "🕐 Lihat slot kosong/terisi"),
        BotCommand("files", "📁 Kelola file schedule"),
        BotCommand("set", "📅 Ubah/tambah jadwal"),
        BotCommand("add", "➕ Tambah file schedule baru"),
        BotCommand("conflict", "🔍 Cek konflik jadwal"),
        BotCommand("help", "📖 Panduan"),
    ])


def main():
    # Ensure registry exists
    load_registry()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("files", cmd_files))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("slots", cmd_slots))
    app.add_handler(CommandHandler("conflict", cmd_conflict))
    app.add_handler(CommandHandler("help", cmd_help))

    app.add_handler(CallbackQueryHandler(button_handler))

    print("Schedule Manager Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
