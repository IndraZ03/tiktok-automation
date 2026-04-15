"""
📸 Instagram Reels Downloader + Full Auto TikTok Upload — Telegram Bot
======================================================================
Mirip yt_bot_v2.py namun stok video adalah profil Instagram.
Video diunduh via gallery-dl menggunakan cookies sessionid Instagram.

Fitur:
  • Simpan stok username/URL profil Instagram per User Data (UD)
  • Download reels via gallery-dl (cookie di-hardcode / bisa diset via bot)
  • Upload ke TikTok otomatis (Full Auto) — jadwal per UD
  • Kelola cookie Instagram dari dalam bot (/set cookie <sessionid>)
"""

import os, sys, re, math, time, shutil, asyncio, subprocess, logging, json, copy, threading
from datetime import datetime, timedelta

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# ── Import TikTok upload functions ──
sys.path.insert(0, r"c:\tiktok_automation")
from tiktok_gui import (
    open_chrome_debug, connect_selenium, navigate_upload_page,
    do_upload_file, do_post_video
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8394891510:AAFemWGpHvuvwqT3CEJ1a0O7WWaV9LYP3hU"  # ganti jika perlu
ALLOWED_USER_IDS = []  # kosong = semua user boleh

APP_DIR        = r"C:\tiktok_automation"
LOGO_PATH      = os.path.join(APP_DIR, "logo.png")
TEMP_DIR       = os.path.join(APP_DIR, "ig_temp")
FINAL_DIR      = os.path.join(APP_DIR, "video_ig")

# File cookie gallery-dl (Netscape format)
COOKIE_TXT_FILE = os.path.join(APP_DIR, "instagram_cookies.txt")
COOKIE_RAW_FILE = os.path.join(APP_DIR, ".ig_cookie.txt")

STOK_PER_UD_FILE   = os.path.join(APP_DIR, "ig_stok_per_ud.json")
SCHEDULE_PER_UD_FILE = os.path.join(APP_DIR, "ig_schedule_per_ud.json")
ACTIVE_UD_FILE     = os.path.join(APP_DIR, "ig_auto_userdata.json")
USER_SETTINGS_FILE = os.path.join(APP_DIR, "ig_user_settings.json")
SCHEDULE_STATE_FILE = os.path.join(APP_DIR, "ig_schedule_state.json")

DEFAULT_ACTIVE_UD = [2, 5, 6]
UD_PORT_MAP = {i: str(9221 + i) for i in range(1, 21)}   # UD 1-20 → port 9222-9241

UPLOAD_BATCH_SIZE = 20   # maks video per loop
GALLERY_DL_LIMIT  = 50   # maks reels yang diunduh per profil

# ── Hardcoded Instagram sessionid ──────────────────────────────
# Ganti dengan sessionid kamu. Bisa juga diubah via /set cookie <sessionid>
INSTAGRAM_SESSIONID = ""  # isi jika ingin hardcode

# ═══════════════════════════════════════════════════════════════
#  COOKIE HELPERS
# ═══════════════════════════════════════════════════════════════
def save_raw_cookie(sessionid: str):
    """Simpan sessionid mentah ke file."""
    with open(COOKIE_RAW_FILE, "w", encoding="utf-8") as f:
        f.write(sessionid.strip())

def load_saved_cookie() -> str | None:
    # Prioritas: hardcode → file tersimpan
    if INSTAGRAM_SESSIONID:
        return INSTAGRAM_SESSIONID.strip()
    if os.path.exists(COOKIE_RAW_FILE):
        with open(COOKIE_RAW_FILE, "r", encoding="utf-8") as f:
            c = f.read().strip()
            if c:
                return c
    return None

def generate_netscape_cookie_file(sessionid: str):
    """Buat file cookies.txt format Netscape untuk gallery-dl."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated automatically by ig_bot_v1.py",
        f".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\t{sessionid.strip()}"
    ]
    with open(COOKIE_TXT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

def ensure_cookie_file():
    """Pastikan cookie file ada. Return True jika berhasil."""
    sid = load_saved_cookie()
    if not sid:
        return False
    generate_netscape_cookie_file(sid)
    return True

# ═══════════════════════════════════════════════════════════════
#  USERNAME HELPERS
# ═══════════════════════════════════════════════════════════════
def extract_username(profile_input: str) -> str:
    profile_input = profile_input.strip().rstrip("/")
    profile_input = re.split(r"[?#]", profile_input)[0]
    profile_input = re.sub(r"/(reels|posts|tagged|saved|followers|following)/?$", "", profile_input)
    url_pattern = r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)"
    m = re.match(url_pattern, profile_input)
    if m:
        return m.group(1)
    username = profile_input.lstrip("@")
    if re.match(r"^[A-Za-z0-9_.]+$", username):
        return username
    raise ValueError(f"Username/URL tidak valid: '{profile_input}'")

# ═══════════════════════════════════════════════════════════════
#  JSON HELPERS
# ═══════════════════════════════════════════════════════════════
def _load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default if default is not None else {}

def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ═══════════════════════════════════════════════════════════════
#  SCHEDULE STATE
# ═══════════════════════════════════════════════════════════════
_INITIAL_SCHEDULE = {
    "tanggal": datetime.now().strftime("%Y-%m-%d"),
    "jam":     f"{datetime.now().hour:02d}",
    "menit":   f"{datetime.now().minute:02d}"
}

def load_schedule_state():
    if os.path.exists(SCHEDULE_STATE_FILE):
        try:
            with open(SCHEDULE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if all(k in data for k in ("tanggal", "jam", "menit")):
                return data
        except:
            pass
    save_schedule_state(_INITIAL_SCHEDULE["tanggal"], _INITIAL_SCHEDULE["jam"], _INITIAL_SCHEDULE["menit"])
    return dict(_INITIAL_SCHEDULE)

def save_schedule_state(tanggal, jam, menit):
    try:
        with open(SCHEDULE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"tanggal": tanggal, "jam": jam, "menit": menit,
                       "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f, indent=2)
    except Exception as e:
        logger.warning(f"Gagal simpan schedule_state: {e}")

# ═══════════════════════════════════════════════════════════════
#  PER-UD STOK (username Instagram)
# ═══════════════════════════════════════════════════════════════
def load_stok_per_ud(ud_num):
    return _load_json(STOK_PER_UD_FILE, {}).get(str(ud_num), [])

def save_stok_per_ud(ud_num, items):
    all_stok = _load_json(STOK_PER_UD_FILE, {})
    all_stok[str(ud_num)] = items
    _save_json(STOK_PER_UD_FILE, all_stok)

def add_stok_per_ud(ud_num, new_items):
    items = load_stok_per_ud(ud_num)
    items.extend(new_items)
    save_stok_per_ud(ud_num, items)

def remove_stok_per_ud(ud_num, item):
    items = load_stok_per_ud(ud_num)
    items = [i for i in items if i != item]
    save_stok_per_ud(ud_num, items)

# ═══════════════════════════════════════════════════════════════
#  PER-UD SCHEDULE
# ═══════════════════════════════════════════════════════════════
def load_schedule_per_ud(ud_num):
    all_sched = _load_json(SCHEDULE_PER_UD_FILE, {})
    s = all_sched.get(str(ud_num))
    if s and all(k in s for k in ("tanggal", "jam", "menit")):
        return s
    now = datetime.now()
    return {"tanggal": now.strftime("%Y-%m-%d"), "jam": f"{now.hour:02d}", "menit": f"{now.minute:02d}"}

def save_schedule_per_ud(ud_num, tanggal, jam, menit):
    all_sched = _load_json(SCHEDULE_PER_UD_FILE, {})
    all_sched[str(ud_num)] = {"tanggal": tanggal, "jam": jam, "menit": menit,
                               "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _save_json(SCHEDULE_PER_UD_FILE, all_sched)

# ═══════════════════════════════════════════════════════════════
#  ACTIVE UD
# ═══════════════════════════════════════════════════════════════
def load_active_ud():
    data = _load_json(ACTIVE_UD_FILE)
    if isinstance(data, list): return data
    if isinstance(data, dict) and "active" in data: return data["active"]
    return list(DEFAULT_ACTIVE_UD)

def save_active_ud(ud_list):
    _save_json(ACTIVE_UD_FILE, {"active": ud_list})

# ═══════════════════════════════════════════════════════════════
#  DEFAULTS & STATE
# ═══════════════════════════════════════════════════════════════
_ss = load_schedule_state()
try:
    _def_dt = datetime.strptime(f"{_ss['tanggal']} {_ss['jam']}:{_ss['menit']}", "%Y-%m-%d %H:%M")
except:
    _def_dt = datetime.now()

DEFAULTS = {
    "deskripsi":  "",
    "hashtags":   [],
    "tanggal":    _def_dt.strftime("%Y-%m-%d"),
    "jam":        f"{_def_dt.hour:02d}",
    "menit":      f"{_def_dt.minute:02d}",
    "interval":   "60",
    "ig_limit":   str(GALLERY_DL_LIMIT),
}

user_locks      = {}
log_buffers     = {}
full_auto_tasks = {}
active_tasks    = {}
_ud_current_folder = {}

# ── Persistent user settings ──
def _load_all_settings():
    if os.path.exists(USER_SETTINGS_FILE):
        try:
            with open(USER_SETTINGS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
        except:
            pass
    return {}

def _save_all_settings():
    try:
        with open(USER_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(user_settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")

user_settings = _load_all_settings()

def get_cfg(uid):
    if uid not in user_settings:
        user_settings[uid] = copy.deepcopy(DEFAULTS)
    return user_settings[uid]

def save_cfg(uid=None):
    _save_all_settings()

def is_allowed(uid):
    return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS

def get_lock(uid):
    if uid not in user_locks:
        user_locks[uid] = threading.Lock()
    return user_locks[uid]

# ═══════════════════════════════════════════════════════════════
#  LOG SYSTEM
# ═══════════════════════════════════════════════════════════════
MAX_LOG_LINES = 25

def make_log_fn(uid):
    if uid not in log_buffers:
        log_buffers[uid] = []
    def log_fn(msg, tag=None):
        ts   = datetime.now().strftime("%H:%M:%S")
        icon = {"success": "✅", "error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(tag, "▪️")
        log_buffers[uid].append(f"<code>[{ts}]</code> {icon} {msg}")
        if len(log_buffers[uid]) > MAX_LOG_LINES:
            log_buffers[uid] = log_buffers[uid][-MAX_LOG_LINES:]
    return log_fn

async def live_log_updater(bot, chat_id, msg_id, uid, stop_evt):
    last_text = ""
    while not stop_evt.is_set():
        lines = log_buffers.get(uid, [])
        text  = "\n".join(lines[-MAX_LOG_LINES:]) if lines else "<i>Menunggu log...</i>"
        text  = f"📊 <b>Live Log</b>\n\n{text}"
        if text != last_text:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                    text=text[:4096], parse_mode=ParseMode.HTML)
                last_text = text
            except:
                pass
        await asyncio.sleep(3)
    lines = log_buffers.get(uid, [])
    text  = "\n".join(lines[-MAX_LOG_LINES:]) if lines else ""
    text  = f"📊 <b>Log Selesai</b>\n\n{text}\n\n✅ <b>Proses selesai.</b>"
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
            text=text[:4096], parse_mode=ParseMode.HTML)
    except:
        pass

async def _notify(bot, chat_id, text):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"_notify failed: {e}")

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def sanitize_filename(title):
    title = re.sub(r'[<>:"/\\|?*!,;\[\]{}()\']', '', title)
    title = re.sub(r'\s+', ' ', title).strip('. ')
    return title[:60].rstrip('. ') if len(title) > 60 else (title or "video")

def _natural_sort_key(filepath):
    basename = os.path.basename(filepath).lower()
    return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', basename)]

def _get_pending_videos(folder_path):
    if not folder_path or not os.path.isdir(folder_path):
        return []
    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path)
             if f.lower().endswith(".mp4") and os.path.isfile(os.path.join(folder_path, f))]
    files.sort(key=_natural_sort_key)
    return files

# ═══════════════════════════════════════════════════════════════
#  CORE: DOWNLOAD INSTAGRAM REELS (gallery-dl)
# ═══════════════════════════════════════════════════════════════
def download_ig_reels_sync(username: str, output_dir: str, limit: int = None, log_fn=None) -> list[str]:
    """
    Download reels dari profil Instagram ke output_dir.
    Mengembalikan list path file .mp4 yang berhasil diunduh.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Pastikan cookie file ada
    if not ensure_cookie_file():
        msg = "Cookie Instagram belum diset! Gunakan /set cookie <sessionid>"
        if log_fn:
            log_fn(msg, "error")
        raise RuntimeError(msg)

    target_url = f"https://www.instagram.com/{username}/reels/"

    cmd = [
        "gallery-dl",
        "--cookies", COOKIE_TXT_FILE,
        "--directory", output_dir,
        "--filename", "{shortcode}.{extension}",
        "--filter", "extension == 'mp4'",
        "--abort", "5",
    ]

    if limit:
        cmd.extend(["--range", f"1-{limit}"])

    cmd.append(target_url)

    if log_fn:
        log_fn(f"📥 Download reels @{username} (limit={limit or 'semua'})...", "info")
        log_fn(f"   URL: {target_url}", "info")

    downloaded = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if line.endswith(".mp4") and os.path.isfile(line):
                if log_fn:
                    log_fn(f"  ✓ {os.path.basename(line)}", "success")
                downloaded.append(line)
            elif line.startswith("#") or line.startswith("[gallery"):
                if log_fn:
                    log_fn(f"  > {line}", "info")
        proc.wait()
        if proc.returncode not in (0, 1):
            raise Exception(f"gallery-dl exit code {proc.returncode}")
    except FileNotFoundError:
        raise RuntimeError("gallery-dl tidak ditemukan. Install: pip install gallery-dl")

    if log_fn:
        log_fn(f"✅ Download selesai: {len(downloaded)} video", "success")

    # Fallback: scan folder kalau stdout tidak mencantumkan path
    if not downloaded:
        for f in os.listdir(output_dir):
            fp = os.path.join(output_dir, f)
            if f.lower().endswith(".mp4") and os.path.isfile(fp):
                downloaded.append(fp)

    return sorted(downloaded, key=_natural_sort_key)

# ═══════════════════════════════════════════════════════════════
#  CORE: DOWNLOAD + PINDAH KE FINAL_DIR
# ═══════════════════════════════════════════════════════════════
def _download_ig_to_final(ud_num, username, log_fn, stop_evt):
    """
    Download reels dari username ke FINAL_DIR/<username>/.
    Return path folder, atau None jika gagal.
    """
    safe_name = sanitize_filename(username)
    video_folder = os.path.join(FINAL_DIR, safe_name)

    # Jika folder sudah ada & punya video, skip download
    existing = _get_pending_videos(video_folder)
    if existing:
        log_fn(f"⏩ [UD {ud_num}] Folder @{username} sudah ada ({len(existing)} video), skip download.", "info")
        return video_folder

    os.makedirs(video_folder, exist_ok=True)
    cfg = get_cfg(ud_num)  # pakai ud_num sebagai uid pada saat download; nanti bisa diganti
    limit_str = cfg.get("ig_limit", str(GALLERY_DL_LIMIT))
    try:
        limit = int(limit_str)
    except:
        limit = GALLERY_DL_LIMIT

    job_temp = os.path.join(TEMP_DIR, f"auto_ud{ud_num}_{int(time.time())}")
    try:
        files = download_ig_reels_sync(username, job_temp, limit=limit, log_fn=log_fn)
        if stop_evt.is_set():
            return None

        if not files:
            log_fn(f"❌ [UD {ud_num}] Tidak ada video yang terunduh dari @{username}", "error")
            return None

        # Pindahkan ke FINAL_DIR/<username>/
        moved = 0
        for fp in files:
            dest = os.path.join(video_folder, os.path.basename(fp))
            try:
                shutil.move(fp, dest)
                moved += 1
            except Exception as e:
                log_fn(f"  ⚠️ Gagal pindah {os.path.basename(fp)}: {e}", "warn")

        log_fn(f"✓ [UD {ud_num}] {moved} video dipindah ke {video_folder}", "success")
        return video_folder

    except Exception as e:
        log_fn(f"❌ [UD {ud_num}] Error download IG: {e}", "error")
        return None
    finally:
        try:
            if os.path.exists(job_temp):
                shutil.rmtree(job_temp)
        except:
            pass

# ═══════════════════════════════════════════════════════════════
#  CORE: UPLOAD BATCH
# ═══════════════════════════════════════════════════════════════
def _upload_batch(cfg, log_fn, stop_evt, ud_num, video_files):
    """
    Upload hingga UPLOAD_BATCH_SIZE video ke TikTok.
    Return (uploaded_count, schedules_used).
    """
    if not video_files:
        return 0, 0

    userdata  = os.path.join(APP_DIR, "user_data", str(ud_num))
    port      = UD_PORT_MAP.get(ud_num, str(9222 + ud_num - 1))
    ss        = load_schedule_per_ud(ud_num)
    hour      = int(ss["jam"])
    minute    = int(ss["menit"])
    date_str  = ss["tanggal"]
    interval  = int(cfg.get("interval", "60"))
    deskripsi = cfg.get("deskripsi", "")
    hashtags  = cfg.get("hashtags", [])

    start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)

    # Auto-koreksi jadwal jika sudah lewat
    MIN_FUTURE_MINUTES = 60
    now = datetime.now()
    min_start = now + timedelta(minutes=MIN_FUTURE_MINUTES)
    if start_dt < min_start:
        old_dt   = start_dt
        start_dt = min_start.replace(second=0, microsecond=0)
        rounded_min = ((start_dt.minute + 4) // 5) * 5
        if rounded_min >= 60:
            start_dt = start_dt.replace(minute=0) + timedelta(hours=1)
        else:
            start_dt = start_dt.replace(minute=rounded_min)
        log_fn(f"⚠️ [UD {ud_num}] Schedule {old_dt.strftime('%Y-%m-%d %H:%M')} lewat!", "warn")
        log_fn(f"   → Digeser ke {start_dt.strftime('%Y-%m-%d %H:%M')}", "warn")
        save_schedule_per_ud(ud_num, start_dt.strftime("%Y-%m-%d"),
                             f"{start_dt.hour:02d}", f"{start_dt.minute:02d}")

    batch = video_files[:UPLOAD_BATCH_SIZE]
    total = len(batch)

    log_fn(f"📅 [UD {ud_num}] Schedule mulai: {start_dt.strftime('%Y-%m-%d %H:%M')}", "info")
    log_fn(f"🎬 [UD {ud_num}] Akan upload {total} video (dari {len(video_files)} sisa)...", "info")
    if hashtags:
        log_fn(f"🏷 [UD {ud_num}] Hashtags: {', '.join('#'+h for h in hashtags)}", "info")
    log_fn(f"🌐 [UD {ud_num}] Membuka Chrome (port {port})...", "info")

    chrome_proc = open_chrome_debug(userdata, port)
    driver      = connect_selenium(port)
    log_fn(f"✓ [UD {ud_num}] Chrome terhubung!", "success")

    uploaded = 0
    try:
        for idx, out_path in enumerate(batch):
            if stop_evt.is_set():
                break
            if not os.path.exists(out_path):
                log_fn(f"  ⚠️ File tidak ada, skip: {os.path.basename(out_path)}", "warn")
                continue
            sched_dt = start_dt + timedelta(minutes=interval * idx)
            log_fn(f"[UD {ud_num}] [{idx+1}/{total}] Upload: {os.path.basename(out_path)}", "info")
            log_fn(f"  Schedule: {sched_dt.strftime('%Y-%m-%d %H:%M')}", "info")
            try:
                navigate_upload_page(driver, force=(idx > 0))
                time.sleep(3)
                do_upload_file(driver, os.path.normpath(out_path), log_fn)
                time.sleep(5)
                do_post_video(driver, deskripsi, "", "", log_fn, sched_dt, stop_evt,
                              add_sound=False, add_product=False, skip_switches=True,
                              hashtags=hashtags if hashtags else None)
                try:
                    os.remove(out_path)
                except:
                    pass
                uploaded += 1
                log_fn(f"  ✅ [{idx+1}/{total}] Upload sukses, file dihapus.", "success")
            except Exception as e:
                log_fn(f"  ❌ Error upload [{idx+1}]: {e}", "error")
            if idx < total - 1 and not stop_evt.is_set():
                log_fn("  ⏳ Menunggu 10 detik...", "info")
                time.sleep(10)
    finally:
        try:
            driver.quit()
        except:
            pass
        try:
            chrome_proc.terminate()
        except:
            pass

    # Update schedule untuk batch berikutnya
    if uploaded > 0:
        last_sched = start_dt + timedelta(minutes=interval * (uploaded - 1))
        next_dt    = last_sched + timedelta(minutes=interval)
        save_schedule_per_ud(ud_num, next_dt.strftime("%Y-%m-%d"),
                             f"{next_dt.hour:02d}", f"{next_dt.minute:02d}")
        log_fn(f"💾 [UD {ud_num}] Next schedule: {next_dt.strftime('%Y-%m-%d %H:%M')}", "success")

    log_fn(f"🎉 [UD {ud_num}] Batch selesai! {uploaded}/{total} video terupload.", "success")
    return uploaded, uploaded

# ═══════════════════════════════════════════════════════════════
#  STOK TEXT (tampilan di menu)
# ═══════════════════════════════════════════════════════════════
def stok_text():
    active = load_active_ud()
    cookie_ok = bool(load_saved_cookie())
    cookie_status = "🟢 Cookie OK" if cookie_ok else "🔴 Cookie belum diset"
    t  = f"📸 <b>IG Bot — Stok Profil Per User Data</b>\n"
    t += f"🍪 {cookie_status}\n"
    t += f"🟢 Aktif: <b>{', '.join(str(x) for x in active)}</b>\n\n"
    for ud in sorted(set(active + list(range(1, 8)))):
        items = load_stok_per_ud(ud)
        if not items and ud not in active:
            continue
        marker = "🟢" if ud in active else "⚪"
        ss = load_schedule_per_ud(ud)
        t += f"{marker} <b>UD {ud}</b>: {len(items)} profil | Sched: <code>{ss['tanggal']} {ss['jam']}:{ss['menit']}</code>\n"
    return t

# ═══════════════════════════════════════════════════════════════
#  MENU KEYBOARDS
# ═══════════════════════════════════════════════════════════════
def main_menu_kb(uid=None):
    is_auto = bool(uid and full_auto_tasks.get(uid))
    rows = [
        [InlineKeyboardButton("📋 Stok Profil", callback_data="act_stok")],
        [InlineKeyboardButton(
            "⏹ Stop Full Auto" if is_auto else "🤖 Full Auto",
            callback_data="stop_full_auto" if is_auto else "act_full_auto"
        )],
        [InlineKeyboardButton("📂 Kelola Video", callback_data="fm_list")],
        [InlineKeyboardButton("↻ Refresh", callback_data="refresh")],
    ]
    return InlineKeyboardMarkup(rows)

def _settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Deskripsi", callback_data="set_desc"),
         InlineKeyboardButton("⏱ Interval", callback_data="set_interval")],
        [InlineKeyboardButton("📱 Active UD", callback_data="set_active_ud"),
         InlineKeyboardButton("🏷 Hashtags", callback_data="set_hashtags")],
        [InlineKeyboardButton("🔢 Limit Reels", callback_data="set_limit"),
         InlineKeyboardButton("🍪 Cookie IG", callback_data="set_cookie_info")],
        [InlineKeyboardButton("➕ Tambah Stok", callback_data="set_stok_pick"),
         InlineKeyboardButton("📋 Lihat Stok", callback_data="set_view_pick")],
        [InlineKeyboardButton("📅 Edit Schedule", callback_data="set_sched_pick"),
         InlineKeyboardButton("🗑 Hapus Stok", callback_data="set_del_pick")],
        [InlineKeyboardButton("❌ Tutup", callback_data="close_settings")],
    ])

def _ud_picker_kb(prefix):
    rows = []
    row  = []
    for i in range(1, 21):
        row.append(InlineKeyboardButton(f"UD {i}", callback_data=f"{prefix}_{i}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅ Kembali", callback_data="set_back")])
    return InlineKeyboardMarkup(rows)

def _settings_text(uid):
    cfg    = get_cfg(uid)
    active = load_active_ud()
    hashtags_display = ', '.join(f'#{h}' for h in cfg.get('hashtags', [])[:5]) or '(kosong)'
    cookie_ok = bool(load_saved_cookie())
    return (
        "⚙️ <b>Settings IG Bot</b>\n\n"
        f"📝 Deskripsi: <code>{escape_html(cfg['deskripsi'][:60]) or '(kosong)'}</code>\n"
        f"⏱ Interval: <code>{cfg['interval']} menit</code>\n"
        f"🔢 Limit reels: <code>{cfg.get('ig_limit', GALLERY_DL_LIMIT)}</code>\n"
        f"📱 Active UD: <b>{', '.join(str(x) for x in active)}</b>\n"
        f"🏷 Hashtags: <code>{escape_html(hashtags_display)}</code>\n"
        f"🍪 Cookie: {'🟢 OK' if cookie_ok else '🔴 Belum diset'}\n\n"
        "Pilih tombol di bawah untuk mengubah:"
    )

# ═══════════════════════════════════════════════════════════════
#  FOLDER/FILE MANAGER HELPERS
# ═══════════════════════════════════════════════════════════════
def _list_ig_folders():
    if not os.path.isdir(FINAL_DIR):
        return []
    folders = []
    for name in sorted(os.listdir(FINAL_DIR)):
        path = os.path.join(FINAL_DIR, name)
        if os.path.isdir(path):
            files      = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
            total_size = sum(os.path.getsize(os.path.join(path, f)) for f in files)
            folders.append({"name": name, "path": path, "files": len(files),
                            "size_mb": total_size / (1024 * 1024)})
    return folders

def _list_folder_files(folder_name):
    path = os.path.join(FINAL_DIR, folder_name)
    if not os.path.isdir(path):
        return []
    files = []
    for f in sorted(os.listdir(path)):
        fp = os.path.join(path, f)
        if os.path.isfile(fp):
            files.append({"name": f, "path": fp, "size_mb": os.path.getsize(fp) / (1024 * 1024)})
    return files

# ═══════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    ctx.user_data["in_settings"]  = False
    ctx.user_data["setting_field"] = None
    cfg = get_cfg(uid)
    text = (
        f"📸 <b>Instagram Reels Bot + Full Auto Upload</b>\n\n"
        f"{stok_text()}\n"
        f"📝 Deskripsi: <code>{cfg['deskripsi'][:50] or '(kosong)'}</code>\n"
        f"⏱ Interval: <b>{cfg['interval']} menit</b>\n"
        f"🔢 Limit reels: <b>{cfg.get('ig_limit', GALLERY_DL_LIMIT)}</b>"
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    await update.message.reply_text(_settings_text(uid), parse_mode=ParseMode.HTML,
                                    reply_markup=_settings_kb())


async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /set command — semua konfigurasi lewat command."""
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    raw  = update.message.text.strip()
    args = raw.split(None, 1)
    if len(args) < 2:
        await update.message.reply_text(
            "⚙️ <b>Format /set:</b>\n\n"
            "<code>/set desc Teks deskripsi TikTok</code>\n"
            "<code>/set interval 60</code>\n"
            "<code>/set ud 2,5,6</code>\n"
            "<code>/set hashtags fyp, viral</code>\n"
            "<code>/set limit 30</code>\n"
            "<code>/set cookie SESSIONID_VALUE</code>\n"
            "<code>/set stok 2 username_instagram</code>\n"
            "<code>/set sched 2 2026-03-02 14:30</code>\n"
            "<code>/set del 2 all</code>",
            parse_mode=ParseMode.HTML)
        return

    parts = args[1].split(None, 1)
    sub   = parts[0].lower()
    val   = parts[1].strip() if len(parts) > 1 else ""

    if sub == "desc":
        if not val:
            await update.message.reply_text("❌ Contoh: <code>/set desc Cek link di bio!</code>", parse_mode=ParseMode.HTML)
            return
        cfg["deskripsi"] = val
        save_cfg()
        await update.message.reply_text(f"✅ Deskripsi: <code>{escape_html(val[:60])}</code>", parse_mode=ParseMode.HTML)

    elif sub == "interval":
        if not val:
            await update.message.reply_text("❌ Contoh: <code>/set interval 60</code>", parse_mode=ParseMode.HTML)
            return
        cfg["interval"] = val
        save_cfg()
        await update.message.reply_text(f"✅ Interval: <code>{val} menit</code>", parse_mode=ParseMode.HTML)

    elif sub == "ud":
        nums = [int(x) for x in re.split(r'[,\s]+', val) if x.strip().isdigit()]
        nums = [n for n in nums if 1 <= n <= 20]
        if not nums:
            await update.message.reply_text("❌ Contoh: <code>/set ud 2,5,6</code>", parse_mode=ParseMode.HTML)
            return
        save_active_ud(nums)
        await update.message.reply_text(f"✅ Active UD: <b>{', '.join(str(x) for x in nums)}</b>", parse_mode=ParseMode.HTML)

    elif sub == "hashtags":
        if not val:
            await update.message.reply_text("❌ Contoh: <code>/set hashtags fyp, viral</code>", parse_mode=ParseMode.HTML)
            return
        tags = [t.strip().lstrip('#').strip() for t in re.split(r'[,\n]+', val) if t.strip().lstrip('#').strip()]
        cfg["hashtags"] = tags
        save_cfg()
        await update.message.reply_text(f"✅ Hashtags: <code>{escape_html(', '.join('#'+t for t in tags))}</code>", parse_mode=ParseMode.HTML)

    elif sub == "limit":
        if not val or not val.strip().isdigit():
            await update.message.reply_text("❌ Contoh: <code>/set limit 30</code>", parse_mode=ParseMode.HTML)
            return
        cfg["ig_limit"] = val.strip()
        save_cfg()
        await update.message.reply_text(f"✅ Limit reels: <code>{val.strip()}</code>", parse_mode=ParseMode.HTML)

    elif sub == "cookie":
        if not val:
            await update.message.reply_text(
                "❌ Contoh:\n<code>/set cookie 12345678%3AABCDEFG...</code>\n\n"
                "Ambil dari browser → DevTools → Application → Cookies → instagram.com → sessionid",
                parse_mode=ParseMode.HTML)
            return
        sessionid = val.strip().strip("\"'")
        save_raw_cookie(sessionid)
        generate_netscape_cookie_file(sessionid)
        masked = sessionid[:8] + "..." + sessionid[-4:] if len(sessionid) > 12 else sessionid
        await update.message.reply_text(
            f"✅ Cookie IG tersimpan!\n🍪 <code>{escape_html(masked)}</code>\n\n"
            f"File: <code>{COOKIE_TXT_FILE}</code>",
            parse_mode=ParseMode.HTML)

    elif sub == "stok":
        stok_parts = val.split(None, 1)
        if len(stok_parts) < 2 or not stok_parts[0].isdigit():
            await update.message.reply_text("❌ Contoh: <code>/set stok 2 username_ig</code>", parse_mode=ParseMode.HTML)
            return
        ud_num  = int(stok_parts[0])
        entries = [u.strip().lstrip("@") for u in stok_parts[1].split("\n") if u.strip()]
        # Validasi agar hanya username valid
        valid = []
        for e in entries:
            try:
                valid.append(extract_username(e))
            except ValueError:
                pass
        if not valid:
            await update.message.reply_text("❌ Tidak ada username valid.", parse_mode=ParseMode.HTML)
            return
        add_stok_per_ud(ud_num, valid)
        total = len(load_stok_per_ud(ud_num))
        await update.message.reply_text(
            f"✅ {len(valid)} profil ditambahkan ke UD {ud_num}.\n"
            f"Total: <b>{total}</b>", parse_mode=ParseMode.HTML)

    elif sub == "sched":
        sched_parts = val.split()
        if len(sched_parts) < 3 or not sched_parts[0].isdigit():
            await update.message.reply_text("❌ Contoh: <code>/set sched 2 2026-03-02 14:30</code>", parse_mode=ParseMode.HTML)
            return
        ud_num   = int(sched_parts[0])
        date_str = sched_parts[1]
        time_str = sched_parts[2].replace(".", ":")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            tp = time_str.split(":")
            if len(tp) != 2:
                raise ValueError
            jam, menit = tp[0].zfill(2), tp[1].zfill(2)
            save_schedule_per_ud(ud_num, date_str, jam, menit)
            await update.message.reply_text(f"✅ Schedule UD {ud_num}: {date_str} {jam}:{menit}")
        except:
            await update.message.reply_text("❌ Format salah.\nContoh: <code>/set sched 2 2026-03-02 14:30</code>", parse_mode=ParseMode.HTML)

    elif sub == "del":
        del_parts = val.split(None, 1)
        if len(del_parts) < 2 or not del_parts[0].isdigit():
            await update.message.reply_text("❌ Contoh: <code>/set del 2 all</code>", parse_mode=ParseMode.HTML)
            return
        ud_num = int(del_parts[0])
        what   = del_parts[1].strip()
        if what.lower() == "all":
            save_stok_per_ud(ud_num, [])
            await update.message.reply_text(f"✅ Stok UD {ud_num} dikosongkan!")
        else:
            try:
                idx   = int(what) - 1
                items = load_stok_per_ud(ud_num)
                if 0 <= idx < len(items):
                    removed = items.pop(idx)
                    save_stok_per_ud(ud_num, items)
                    await update.message.reply_text(f"✅ Dihapus: @{removed}")
                else:
                    await update.message.reply_text("❌ Nomor tidak valid.")
            except:
                await update.message.reply_text("❌ Kirim nomor atau 'all'.")
    else:
        await update.message.reply_text(
            "❌ Sub-command tidak dikenal.\nKetik <code>/set</code> untuk lihat daftar.",
            parse_mode=ParseMode.HTML)


async def cmd_download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Download reels dari username secara manual."""
    uid     = update.effective_user.id
    chat_id = update.message.chat_id
    if not is_allowed(uid):
        await update.message.reply_text("❌ Tidak diizinkan.")
        return
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "❌ <b>Format:</b> <code>/download &lt;username_atau_url_instagram&gt;</code>\n"
            "Contoh: <code>/download natgeo</code>",
            parse_mode=ParseMode.HTML)
        return

    try:
        username = extract_username(args[0])
    except ValueError as e:
        await update.message.reply_text(f"❌ {escape_html(str(e))}", parse_mode=ParseMode.HTML)
        return

    if active_tasks.get(chat_id):
        await update.message.reply_text("⏳ Ada proses berjalan.")
        return

    if not ensure_cookie_file():
        await update.message.reply_text(
            "❌ Cookie Instagram belum diset!\n"
            "Gunakan: <code>/set cookie &lt;sessionid&gt;</code>",
            parse_mode=ParseMode.HTML)
        return

    active_tasks[chat_id] = True
    progress_msg = await update.message.reply_text(
        f"📥 <b>Memulai download reels @{username}...</b>",
        parse_mode=ParseMode.HTML)

    uid_key = uid
    log_buffers[uid_key] = []
    log_fn  = make_log_fn(uid_key)
    stop_evt = threading.Event()

    def _do():
        try:
            cfg   = get_cfg(uid)
            limit = int(cfg.get("ig_limit", GALLERY_DL_LIMIT))
            files = download_ig_reels_sync(username, os.path.join(TEMP_DIR, f"manual_{int(time.time())}"),
                                           limit=limit, log_fn=log_fn)

            safe_name    = sanitize_filename(username)
            video_folder = os.path.join(FINAL_DIR, safe_name)
            os.makedirs(video_folder, exist_ok=True)
            moved = 0
            for fp in files:
                dest = os.path.join(video_folder, os.path.basename(fp))
                try:
                    shutil.move(fp, dest)
                    moved += 1
                except:
                    pass
            log_fn(f"✅ {moved} video disimpan ke {video_folder}", "success")
        except Exception as e:
            log_fn(f"❌ Error: {e}", "error")
        finally:
            active_tasks.pop(chat_id, None)
            stop_evt.set()

    t = threading.Thread(target=_do, daemon=True)
    t.start()

    main_loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(
        live_log_updater(update.get_bot(), chat_id, progress_msg.message_id, uid_key, stop_evt),
        main_loop)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["in_settings"]   = False
    ctx.user_data["setting_field"] = None
    await update.message.reply_text("⚙️ Dibatalkan.", reply_markup=main_menu_kb(update.effective_user.id))


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>Instagram Reels Bot + Full Auto TikTok</b>\n\n"
        "<b>Perintah:</b>\n"
        "/start — Menu utama\n"
        "/download &lt;username&gt; — Download reels manual\n"
        "/settings — Konfigurasi bot (tombol)\n"
        "/set — Ubah setting via command\n"
        "/help — Panduan ini\n"
        "/cancel — Batalkan\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ <b>Panduan /set:</b>\n\n"
        "<code>/set desc Cek link di bio!</code>\n"
        "<code>/set interval 60</code>\n"
        "<code>/set limit 30</code>  ← maks reels per profil\n"
        "<code>/set ud 2,5,6</code>\n"
        "<code>/set hashtags fyp, viral</code>\n"
        "<code>/set cookie &lt;sessionid&gt;</code>  ← cookie Instagram\n"
        "<code>/set stok 2 username_ig</code>\n"
        "<code>/set sched 2 2026-03-02 14:30</code>\n"
        "<code>/set del 2 all</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🍪 <b>Cara dapat sessionid:</b>\n"
        "Browser → DevTools (F12) → Application\n"
        "→ Cookies → https://www.instagram.com\n"
        "→ Cari <code>sessionid</code> → salin value-nya\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>Full Auto:</b>\n"
        "Download reels → upload TikTok (terjadwal)\n"
        "• Stok = username Instagram per UD\n"
        "• Setelah semua terdownload, upload otomatis"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  TEXT MESSAGE FALLBACK
# ═══════════════════════════════════════════════════════════════
async def handle_text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    uid   = update.effective_user.id
    if not is_allowed(uid):
        return
    field = ctx.user_data.get("setting_field")
    if not field:
        return
    # Delegate to settings processor
    await _process_settings_text(update, ctx, field)


async def _process_settings_text(update, ctx, field):
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    txt = update.message.text.strip()

    if field == "desc":
        cfg["deskripsi"] = txt
        save_cfg()
    elif field == "interval":
        cfg["interval"] = txt
        save_cfg()
    elif field == "active_ud":
        nums = [int(x) for x in re.split(r'[,\s]+', txt) if x.strip().isdigit()]
        nums = [n for n in nums if 1 <= n <= 20]
        if nums:
            save_active_ud(nums)
        else:
            await update.message.reply_text("❌ Format salah. Contoh: <code>2,5,6</code>", parse_mode=ParseMode.HTML)
            return
    elif field == "hashtags":
        tags = [t.strip().lstrip('#').strip() for t in re.split(r'[,\n]+', txt) if t.strip().lstrip('#').strip()]
        cfg["hashtags"] = tags
        save_cfg()
    elif field == "ig_limit":
        if txt.isdigit():
            cfg["ig_limit"] = txt
            save_cfg()
        else:
            await update.message.reply_text("❌ Masukkan angka.", parse_mode=ParseMode.HTML)
            return
    elif field == "cookie":
        sessionid = txt.strip().strip("\"'")
        save_raw_cookie(sessionid)
        generate_netscape_cookie_file(sessionid)
    elif field == "stok_ud":
        ud_num = ctx.user_data.get("stok_ud_num")
        entries = [e.strip().lstrip("@") for e in txt.split("\n") if e.strip()]
        valid = []
        for e in entries:
            try:
                valid.append(extract_username(e))
            except ValueError:
                pass
        if valid:
            add_stok_per_ud(ud_num, valid)
        else:
            await update.message.reply_text("❌ Tidak ada username valid.", parse_mode=ParseMode.HTML)
            return
    elif field == "sched_ud_date":
        ud_num = ctx.user_data.get("sched_ud_num")
        try:
            datetime.strptime(txt, "%Y-%m-%d")
            ctx.user_data["sched_ud_date_val"] = txt
            ctx.user_data["setting_field"] = "sched_ud_time"
            await update.message.reply_text(
                f"Kirim jam (HH:MM):\n<code>/set sched {ud_num} {txt} 14:30</code>",
                parse_mode=ParseMode.HTML)
            return
        except:
            await update.message.reply_text("❌ Format: YYYY-MM-DD", parse_mode=ParseMode.HTML)
            return
    elif field == "sched_ud_time":
        ud_num   = ctx.user_data.get("sched_ud_num")
        date_val = ctx.user_data.get("sched_ud_date_val")
        tp = txt.replace(".", ":").split(":")
        if len(tp) == 2:
            save_schedule_per_ud(ud_num, date_val, tp[0].zfill(2), tp[1].zfill(2))
        else:
            await update.message.reply_text("❌ Format: HH:MM", parse_mode=ParseMode.HTML)
            return
    elif field == "hapus_stok_ud":
        ud_num = ctx.user_data.get("hapus_ud_num")
        if txt.lower() == "all":
            save_stok_per_ud(ud_num, [])
        else:
            try:
                idx   = int(txt) - 1
                items = load_stok_per_ud(ud_num)
                if 0 <= idx < len(items):
                    items.pop(idx)
                    save_stok_per_ud(ud_num, items)
                else:
                    await update.message.reply_text("❌ Nomor tidak valid.")
                    return
            except:
                await update.message.reply_text("❌ Kirim nomor atau 'all'.")
                return

    ctx.user_data["setting_field"] = None
    await update.message.reply_text("✅ Tersimpan!", reply_markup=_settings_kb())


# ═══════════════════════════════════════════════════════════════
#  SETTINGS CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════
async def _handle_settings_callback(q, ctx, data, bot):
    uid     = q.from_user.id
    cfg     = get_cfg(uid)
    chat_id = q.message.chat_id

    if data == "close_settings":
        ctx.user_data["in_settings"]   = False
        ctx.user_data["setting_field"] = None
        await q.edit_message_text("⚙️ Settings ditutup.")
        return True

    if data == "set_back":
        await q.edit_message_text(_settings_text(uid), parse_mode=ParseMode.HTML,
                                  reply_markup=_settings_kb())
        return True

    if data == "set_desc":
        await bot.send_message(chat_id,
            f"📝 Deskripsi: <code>{escape_html(cfg['deskripsi'][:60]) or '(kosong)'}</code>\n\n"
            "Kirim:\n<code>/set desc Cek link di bio!</code>",
            parse_mode=ParseMode.HTML)
        return True

    if data == "set_interval":
        await bot.send_message(chat_id,
            f"⏱ Interval: <code>{cfg['interval']} menit</code>\n\n"
            "Kirim:\n<code>/set interval 60</code>",
            parse_mode=ParseMode.HTML)
        return True

    if data == "set_active_ud":
        active = load_active_ud()
        await bot.send_message(chat_id,
            f"📱 Active UD: <b>{', '.join(str(x) for x in active)}</b>\n\n"
            "Kirim:\n<code>/set ud 2,5,6</code>",
            parse_mode=ParseMode.HTML)
        return True

    if data == "set_hashtags":
        current  = cfg.get("hashtags", [])
        disp     = ', '.join(f'#{t}' for t in current) if current else '(kosong)'
        await bot.send_message(chat_id,
            f"🏷 Hashtags: <code>{escape_html(disp)}</code>\n\n"
            "Kirim:\n<code>/set hashtags fyp, viral, tiktok</code>",
            parse_mode=ParseMode.HTML)
        return True

    if data == "set_limit":
        await bot.send_message(chat_id,
            f"🔢 Limit reels: <code>{cfg.get('ig_limit', GALLERY_DL_LIMIT)}</code>\n\n"
            "Kirim:\n<code>/set limit 30</code>",
            parse_mode=ParseMode.HTML)
        return True

    if data == "set_cookie_info":
        cookie_ok = bool(load_saved_cookie())
        await bot.send_message(chat_id,
            f"🍪 Cookie Instagram: {'🟢 OK' if cookie_ok else '🔴 Belum diset'}\n\n"
            "Kirim sessionid Instagram:\n"
            "<code>/set cookie SESSIONID_VALUE_HERE</code>\n\n"
            "<b>Cara ambil sessionid:</b>\n"
            "1. Buka instagram.com di browser\n"
            "2. Tekan F12 → Application → Cookies\n"
            "3. Cari <code>sessionid</code> → salin value\n"
            "4. Kirim via /set cookie",
            parse_mode=ParseMode.HTML)
        return True

    # UD pickers
    if data in ("set_stok_pick", "set_view_pick", "set_sched_pick", "set_del_pick"):
        labels   = {"set_stok_pick": "➕ Tambah Stok — Pilih UD:",
                    "set_view_pick": "📋 Lihat Stok — Pilih UD:",
                    "set_sched_pick": "📅 Edit Schedule — Pilih UD:",
                    "set_del_pick": "🗑 Hapus Stok — Pilih UD:"}
        prefixes = {"set_stok_pick": "set_stok", "set_view_pick": "set_view",
                    "set_sched_pick": "set_sched", "set_del_pick": "set_del"}
        await q.edit_message_text(labels[data], reply_markup=_ud_picker_kb(prefixes[data]))
        return True

    if data.startswith("set_stok_"):
        ud_num = int(data.split("_")[-1])
        await bot.send_message(chat_id,
            f"Kirim username Instagram (satu per baris):\n"
            f"<code>/set stok {ud_num} username1\nusername2</code>",
            parse_mode=ParseMode.HTML)
        return True

    if data.startswith("set_view_"):
        ud_num = int(data.split("_")[-1])
        items  = load_stok_per_ud(ud_num)
        ss     = load_schedule_per_ud(ud_num)
        t  = f"📦 <b>Stok UD {ud_num}</b> ({len(items)} profil)\n"
        t += f"📅 Schedule: <code>{ss['tanggal']} {ss['jam']}:{ss['menit']}</code>\n\n"
        for i, item in enumerate(items[:15]):
            t += f"  {i+1}. <code>@{item}</code>\n"
        if len(items) > 15:
            t += f"  ... +{len(items)-15} lainnya\n"
        if not items:
            t += "  <i>(kosong)</i>\n"
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Kembali", callback_data="set_back")]])
        await q.edit_message_text(t, parse_mode=ParseMode.HTML, reply_markup=back_kb)
        return True

    if data.startswith("set_sched_"):
        ud_num = int(data.split("_")[-1])
        ss     = load_schedule_per_ud(ud_num)
        await bot.send_message(chat_id,
            f"📅 Schedule UD {ud_num}: <code>{ss['tanggal']} {ss['jam']}:{ss['menit']}</code>\n\n"
            f"Kirim:\n<code>/set sched {ud_num} 2026-03-02 14:30</code>",
            parse_mode=ParseMode.HTML)
        return True

    if data.startswith("set_del_"):
        ud_num = int(data.split("_")[-1])
        items  = load_stok_per_ud(ud_num)
        if not items:
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Kembali", callback_data="set_back")]])
            await q.edit_message_text(f"Stok UD {ud_num} kosong.", reply_markup=back_kb)
            return True
        t = f"🗑 <b>Hapus Stok UD {ud_num}</b> ({len(items)} profil)\n\n"
        for i, item in enumerate(items[:15]):
            t += f"  {i+1}. <code>@{item}</code>\n"
        await bot.send_message(chat_id,
            t + f"\nKirim:\n<code>/set del {ud_num} all</code>\natau hapus 1:\n<code>/set del {ud_num} 3</code>",
            parse_mode=ParseMode.HTML)
        return True

    return False


# ═══════════════════════════════════════════════════════════════
#  FULL AUTO LOOP
# ═══════════════════════════════════════════════════════════════
def _full_auto_daemon(uid, bot, chat_id, stop_auto, main_loop):
    def _send(text):
        asyncio.run_coroutine_threadsafe(_notify(bot, chat_id, text), main_loop)

    active = load_active_ud()
    _send(
        f"🤖 <b>Full Auto dimulai!</b>\n"
        f"Active UD: <b>{', '.join(str(x) for x in active)}</b>\n"
        f"Logika: Tunggu jadwal → download reels → upload <b>{UPLOAD_BATCH_SIZE} video/loop</b>"
    )

    while not stop_auto.is_set():
        active = load_active_ud()

        # ── Housekeeping: folder kosong ──
        for ud_num in active:
            current_folder = _ud_current_folder.get(ud_num)
            if current_folder and not _get_pending_videos(current_folder):
                _send(
                    f"🗑 <b>UD {ud_num}</b>: Semua video terupload!\n"
                    f"Menghapus folder: <code>{os.path.basename(current_folder)}</code>"
                )
                try:
                    if os.path.isdir(current_folder):
                        shutil.rmtree(current_folder)
                except Exception as e:
                    _send(f"⚠️ [UD {ud_num}] Gagal hapus folder: {e}")
                items = load_stok_per_ud(ud_num)
                if items:
                    remove_stok_per_ud(ud_num, items[0])
                    _send(f"✅ [UD {ud_num}] Profil selesai, lanjut ke berikutnya.")
                _ud_current_folder.pop(ud_num, None)

        # ── Kandidat UD yang punya kerjaan ──
        candidates = []
        for ud_num in active:
            has_pending = bool(_get_pending_videos(_ud_current_folder.get(ud_num)))
            has_stok    = bool(load_stok_per_ud(ud_num))
            if not has_pending and not has_stok:
                continue
            state = load_schedule_per_ud(ud_num)
            try:
                trigger_dt = datetime.strptime(
                    f"{state['tanggal']} {state['jam']}:{state['menit']}", "%Y-%m-%d %H:%M")
            except:
                _send(f"❌ Format schedule UD {ud_num} error, skip!")
                continue
            candidates.append((trigger_dt, ud_num, has_pending))

        if not candidates:
            if not stop_auto.is_set():
                _send("📦 Semua stok UD kosong. Menunggu 60 detik...")
                for _ in range(12):
                    if stop_auto.is_set():
                        break
                    time.sleep(5)
            continue

        # ── Pilih UD dengan jadwal terdekat ──
        candidates.sort(key=lambda x: x[0])
        trigger_dt, ud_num, has_pending = candidates[0]

        sched_info = "\n".join(
            f"  {'➡️' if c[1] == ud_num else '  '} UD {c[1]}: "
            f"<code>{c[0].strftime('%Y-%m-%d %H:%M')}</code>"
            f"{' (sisa video)' if c[2] else ''}"
            for c in candidates
        )
        _send(
            f"📅 <b>Jadwal UD:</b>\n{sched_info}\n\n"
            f"🎯 Terdekat: <b>UD {ud_num}</b> — "
            f"<code>{trigger_dt.strftime('%Y-%m-%d %H:%M')}</code>"
        )

        # ── Tunggu jadwal ──
        now      = datetime.now()
        wait_sec = (trigger_dt - now).total_seconds()
        if wait_sec > 0:
            _send(
                f"⏳ <b>UD {ud_num}</b>: Menunggu jadwal...\n"
                f"<code>{trigger_dt.strftime('%Y-%m-%d %H:%M')}</code>"
                f" ({int(wait_sec // 60)} menit lagi)"
            )
            elapsed = 0
            while elapsed < wait_sec and not stop_auto.is_set():
                time.sleep(min(30, wait_sec - elapsed))
                elapsed += 30
            if stop_auto.is_set():
                break

        # ── Cek ulang setelah tunggu ──
        pending = _get_pending_videos(_ud_current_folder.get(ud_num))

        if not pending:
            items = load_stok_per_ud(ud_num)
            if not items:
                _send(f"⚠️ [UD {ud_num}] Stok habis, skip.")
                continue

            username     = items[0]
            log_buffers[uid] = []
            log_fn = make_log_fn(uid)
            _send(f"📥 <b>UD {ud_num}</b>: Downloading @{username}...")

            new_folder = _download_ig_to_final(ud_num, username, log_fn, stop_auto)
            summary    = "\n".join(log_buffers.get(uid, [])[-6:])

            if not new_folder or stop_auto.is_set():
                _send(f"❌ <b>UD {ud_num}</b>: Download gagal.\n{summary}")
                time.sleep(10)
                continue

            _ud_current_folder[ud_num] = new_folder
            pending = _get_pending_videos(new_folder)
            _send(
                f"✅ <b>UD {ud_num}</b>: Download selesai!\n"
                f"{len(pending)} video siap di-upload.\n{summary}"
            )

        if not pending or stop_auto.is_set():
            continue

        # ── Upload batch ──
        folder_name = os.path.basename(_ud_current_folder.get(ud_num, ""))
        _send(
            f"🚀 <b>UD {ud_num}</b>: Upload batch {UPLOAD_BATCH_SIZE} video\n"
            f"📁 Folder: <code>{folder_name}</code>\n"
            f"📊 Sisa video: <b>{len(pending)}</b>"
        )

        lock = get_lock(uid)
        if not lock.acquire(blocking=True, timeout=60):
            _send("⚠️ Gagal acquire lock, skip...")
            continue

        log_buffers[uid] = []
        log_fn = make_log_fn(uid)
        cfg    = get_cfg(uid)
        try:
            uploaded, _ = _upload_batch(cfg, log_fn, stop_auto, ud_num, pending)
        except Exception as e:
            _send(f"❌ [UD {ud_num}] Error upload batch: {e}")
            uploaded = 0
        finally:
            lock.release()

        summary    = "\n".join(log_buffers.get(uid, [])[-8:])
        sisa_after = len(_get_pending_videos(_ud_current_folder.get(ud_num, "")))
        _send(
            f"✅ <b>UD {ud_num}: Batch selesai!</b>\n"
            f"Upload: <b>{uploaded}</b> video\n"
            f"Sisa video di folder: <b>{sisa_after}</b>\n{summary}"
        )

        if not stop_auto.is_set():
            time.sleep(10)

    full_auto_tasks.pop(uid, None)
    _send("⏹ <b>Full Auto dihentikan.</b>")


# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER (button_handler)
# ═══════════════════════════════════════════════════════════════
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not is_allowed(uid):
        return
    data = q.data

    # Route settings callbacks
    if data.startswith("set_") or data in ("close_settings", "set_back"):
        handled = await _handle_settings_callback(q, ctx, data, ctx.bot)
        if handled:
            return

    if data == "refresh":
        cfg  = get_cfg(uid)
        text = (
            f"📸 <b>Instagram Reels Bot + Full Auto Upload</b>\n\n"
            f"{stok_text()}\n"
            f"⏱ Interval: <b>{cfg['interval']} menit</b>"
        )
        await q.edit_message_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    if data == "act_stok":
        await q.edit_message_text(stok_text(), reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    # ── File Manager ──
    if data == "fm_list":
        folders = _list_ig_folders()
        if not folders:
            await q.edit_message_text("📂 <b>video_ig</b> kosong.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        text = f"📂 <b>Folder di video_ig</b> ({len(folders)} folder)\n\n"
        rows = []
        for i, f in enumerate(folders):
            text += f"{i+1}. <code>{f['name'][:40]}</code> — {f['files']} file ({f['size_mb']:.1f} MB)\n"
            rows.append([InlineKeyboardButton(f"📁 {f['name'][:30]}", callback_data=f"fm_open|{i}")])
        rows.append([InlineKeyboardButton("🗑 Hapus Semua", callback_data="fm_delall")])
        rows.append([InlineKeyboardButton("🏠 Menu", callback_data="refresh")])
        ctx.user_data["fm_folders"] = folders
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
        return

    if data.startswith("fm_open|"):
        idx     = int(data.split("|")[1])
        folders = ctx.user_data.get("fm_folders", [])
        if idx >= len(folders):
            await q.edit_message_text("❌ Folder tidak ditemukan.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        folder = folders[idx]
        files  = _list_folder_files(folder["name"])
        ctx.user_data["fm_current_folder"] = folder["name"]
        ctx.user_data["fm_files"]          = files
        text = f"📁 <b>{escape_html(folder['name'][:50])}</b>\n\n"
        if not files:
            text += "<i>Folder kosong</i>\n"
        rows = []
        for i, f in enumerate(files[:20]):
            text += f"{i+1}. <code>{f['name'][:40]}</code> ({f['size_mb']:.1f} MB)\n"
            rows.append([InlineKeyboardButton(f"🗑 {f['name'][:30]}", callback_data=f"fm_delfile|{i}")])
        if len(files) > 20:
            text += f"... +{len(files)-20} lainnya\n"
        rows.append([InlineKeyboardButton("🗑 Hapus Folder Ini", callback_data=f"fm_delfolder|{idx}")])
        rows.append([InlineKeyboardButton("⬅ Kembali", callback_data="fm_list")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
        return

    if data.startswith("fm_delfile|"):
        idx         = int(data.split("|")[1])
        files       = ctx.user_data.get("fm_files", [])
        folder_name = ctx.user_data.get("fm_current_folder", "")
        if idx >= len(files):
            await q.edit_message_text("❌ File tidak ditemukan.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        f = files[idx]
        try:
            if os.path.exists(f["path"]):
                os.remove(f["path"])
            text = f"✅ File <code>{escape_html(f['name'])}</code> dihapus!\n\n"
        except Exception as e:
            text = f"❌ Gagal hapus: {escape_html(str(e))}\n\n"
        new_files = _list_folder_files(folder_name)
        ctx.user_data["fm_files"] = new_files
        if not new_files:
            text += "<i>Folder kosong</i>"
        else:
            for i, nf in enumerate(new_files[:20]):
                text += f"{i+1}. <code>{nf['name'][:40]}</code> ({nf['size_mb']:.1f} MB)\n"
        rows = []
        for i, nf in enumerate(new_files[:20]):
            rows.append([InlineKeyboardButton(f"🗑 {nf['name'][:30]}", callback_data=f"fm_delfile|{i}")])
        all_folders = _list_ig_folders()
        fidx = next((i for i, ff in enumerate(all_folders) if ff["name"] == folder_name), 0)
        ctx.user_data["fm_folders"] = all_folders
        rows.append([InlineKeyboardButton("🗑 Hapus Folder Ini", callback_data=f"fm_delfolder|{fidx}")])
        rows.append([InlineKeyboardButton("⬅ Kembali", callback_data="fm_list")])
        await q.edit_message_text(f"📁 <b>{escape_html(folder_name[:50])}</b>\n\n" + text,
            reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
        return

    if data.startswith("fm_delfolder|"):
        idx     = int(data.split("|")[1])
        folders = ctx.user_data.get("fm_folders", _list_ig_folders())
        if idx >= len(folders):
            await q.edit_message_text("❌ Folder tidak ditemukan.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        folder = folders[idx]
        try:
            shutil.rmtree(folder["path"])
            text = f"✅ Folder <code>{escape_html(folder['name'][:50])}</code> dihapus! ({folder['files']} file)\n\n"
        except Exception as e:
            text = f"❌ Gagal hapus folder: {escape_html(str(e))}\n\n"
        new_folders = _list_ig_folders()
        ctx.user_data["fm_folders"] = new_folders
        text += f"📂 <b>Sisa folder:</b> {len(new_folders)}\n"
        rows = []
        for i, f in enumerate(new_folders):
            rows.append([InlineKeyboardButton(f"📁 {f['name'][:30]}", callback_data=f"fm_open|{i}")])
        if new_folders:
            rows.append([InlineKeyboardButton("🗑 Hapus Semua", callback_data="fm_delall")])
        rows.append([InlineKeyboardButton("🏠 Menu", callback_data="refresh")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
        return

    if data == "fm_delall":
        folders    = _list_ig_folders()
        deleted    = 0
        total_files = 0
        total_mb   = 0
        for f in folders:
            try:
                shutil.rmtree(f["path"])
                deleted     += 1
                total_files += f["files"]
                total_mb    += f["size_mb"]
            except:
                pass
        text = (f"🗑 <b>Semua folder dihapus!</b>\n\n"
                f"Folder: <b>{deleted}</b>\nFile: <b>{total_files}</b>\n"
                f"Ukuran: <b>{total_mb:.1f} MB</b>")
        await q.edit_message_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    # ── Full Auto START ──
    if data == "act_full_auto":
        if uid in full_auto_tasks:
            await q.edit_message_text("⚠️ Full Auto sudah berjalan.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        if not ensure_cookie_file():
            await q.edit_message_text(
                "❌ Cookie Instagram belum diset!\n"
                "Gunakan: /set cookie &lt;sessionid&gt;",
                reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return

        stop_auto = threading.Event()
        bot       = ctx.bot
        chat_id   = q.message.chat_id
        main_loop = asyncio.get_event_loop()

        t = threading.Thread(
            target=_full_auto_daemon,
            args=(uid, bot, chat_id, stop_auto, main_loop),
            daemon=True,
            name=f"ig_full_auto_{uid}"
        )
        full_auto_tasks[uid] = {"stop": stop_auto, "thread": t}
        t.start()

        active = load_active_ud()
        await q.edit_message_text(
            f"🤖 <b>Full Auto aktif!</b>\nActive UD: <b>{', '.join(str(x) for x in active)}</b>\n"
            f"Bot akan otomatis download reels → upload ke TikTok.\n\nTekan <b>Stop Full Auto</b> untuk menghentikan.",
            reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    # ── Full Auto STOP ──
    if data == "stop_full_auto":
        task = full_auto_tasks.get(uid)
        if task:
            task["stop"].set()
            full_auto_tasks.pop(uid, None)
        await q.edit_message_text(
            "⏹ <b>Full Auto dihentikan.</b>\n\n" + stok_text(),
            reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start",    "📋 Menu utama"),
        BotCommand("download", "⬇️ Download reels Instagram"),
        BotCommand("settings", "⚙️ Konfigurasi (tombol)"),
        BotCommand("set",      "⚙️ Ubah setting via command"),
        BotCommand("help",     "📖 Panduan"),
        BotCommand("cancel",   "❌ Batalkan"),
    ])
    # Pastikan cookie file tersedia saat startup
    ensure_cookie_file()


def main():
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(FINAL_DIR, exist_ok=True)

    # Inisialisasi cookie file dari hardcode jika ada
    if INSTAGRAM_SESSIONID:
        generate_netscape_cookie_file(INSTAGRAM_SESSIONID)
        logger.info("Cookie IG di-load dari INSTAGRAM_SESSIONID hardcoded.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("set",      cmd_set))
    app.add_handler(CommandHandler("cancel",   cmd_cancel))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("download", cmd_download))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("📸 Instagram Reels Bot + Full Auto TikTok is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
