"""
🎬 YouTube Downloader & Splitter + Full Auto TikTok Upload — Telegram Bot
"""
import os, sys, re, math, time, shutil, asyncio, subprocess, logging, json, copy, threading
from datetime import datetime, timedelta

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    GDRIVE_OK = True
except ImportError:
    GDRIVE_OK = False

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
BOT_TOKEN = "8577651733:AAG69uuoImXQpe5qcEtMdlwgu3_6rQAvaBI"
ALLOWED_USER_IDS = []

APP_DIR = r"C:\tiktok_automation"
LOGO_PATH = os.path.join(APP_DIR, "logo.png")
TEMP_DIR = os.path.join(APP_DIR, "yt_temp")
FINAL_DIR = os.path.join(APP_DIR, "video_yt")
GDRIVE_SETTINGS_YAML = os.path.join(APP_DIR, "gdrive_settings.yaml")
GDRIVE_CREDS_FILE = os.path.join(APP_DIR, "gdrive_credentials.json")
SEGMENT_DURATION = 180
STOK_LINK_FILE = os.path.join(APP_DIR, "yt_stok_link.json")
SCHEDULE_STATE_FILE = os.path.join(APP_DIR, "yt_schedule_state.json")
STOK_PER_UD_FILE = os.path.join(APP_DIR, "yt_stok_per_ud.json")
SCHEDULE_PER_UD_FILE = os.path.join(APP_DIR, "yt_schedule_per_ud.json")
ACTIVE_UD_FILE = os.path.join(APP_DIR, "yt_auto_userdata.json")
DEFAULT_ACTIVE_UD = [2, 5, 6]
UD_PORT_MAP = {1:"9222",2:"9223",3:"9224",4:"9225",5:"9226",6:"9227",7:"9228"}

# FFmpeg
def _find_bin(name):
    found = shutil.which(name)
    if found: return found
    for c in [os.path.expanduser(rf"~\AppData\Local\Microsoft\WinGet\Links\{name}.exe"),
              rf"C:\ffmpeg\bin\{name}.exe", os.path.join(APP_DIR, f"{name}.exe")]:
        if os.path.isfile(c): return c
    return name

FFPROBE_PATH = _find_bin("ffprobe")
FFMPEG_PATH = _find_bin("ffmpeg")
WATERMARK_WIDTH_PCT = 25
WATERMARK_MARGIN_PCT = 2
TEXT_FONT = "Arial"
TEXT_SIZE_PCT = 2.5
TEXT_COLOR = "white"
TEXT_BORDER_COLOR = "black"
TEXT_BORDER_W = 4

# ═══════════════════════════════════════════════════════════════
#  SCHEDULE STATE
# ═══════════════════════════════════════════════════════════════
_INITIAL_SCHEDULE = {"tanggal": datetime.now().strftime("%Y-%m-%d"),
                     "jam": f"{datetime.now().hour:02d}",
                     "menit": f"{datetime.now().minute:02d}"}

def load_schedule_state():
    if os.path.exists(SCHEDULE_STATE_FILE):
        try:
            with open(SCHEDULE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if all(k in data for k in ("tanggal", "jam", "menit")):
                return data
        except: pass
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
#  STOK LINK
# ═══════════════════════════════════════════════════════════════
def load_stok_links():
    if os.path.exists(STOK_LINK_FILE):
        try:
            with open(STOK_LINK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return []

def save_stok_links(links):
    with open(STOK_LINK_FILE, "w", encoding="utf-8") as f:
        json.dump(links, f, indent=2, ensure_ascii=False)

def remove_stok_link(url):
    links = load_stok_links()
    links = [l for l in links if l != url]
    save_stok_links(links)

# ═══════════════════════════════════════════════════════════════
#  PER-USER-DATA STOK LINK
# ═══════════════════════════════════════════════════════════════
def _load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return default if default is not None else {}

def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)

def load_stok_per_ud(ud_num):
    all_stok = _load_json(STOK_PER_UD_FILE, {})
    return all_stok.get(str(ud_num), [])

def save_stok_per_ud(ud_num, links):
    all_stok = _load_json(STOK_PER_UD_FILE, {})
    all_stok[str(ud_num)] = links
    _save_json(STOK_PER_UD_FILE, all_stok)

def add_stok_per_ud(ud_num, new_links):
    links = load_stok_per_ud(ud_num)
    links.extend(new_links)
    save_stok_per_ud(ud_num, links)

def remove_stok_per_ud(ud_num, url):
    links = load_stok_per_ud(ud_num)
    links = [l for l in links if l != url]
    save_stok_per_ud(ud_num, links)

# ═══════════════════════════════════════════════════════════════
#  PER-USER-DATA SCHEDULE STATE
# ═══════════════════════════════════════════════════════════════
def load_schedule_per_ud(ud_num):
    all_sched = _load_json(SCHEDULE_PER_UD_FILE, {})
    s = all_sched.get(str(ud_num))
    if s and all(k in s for k in ("tanggal","jam","menit")):
        return s
    now = datetime.now()
    return {"tanggal": now.strftime("%Y-%m-%d"), "jam": f"{now.hour:02d}", "menit": f"{now.minute:02d}"}

def save_schedule_per_ud(ud_num, tanggal, jam, menit):
    all_sched = _load_json(SCHEDULE_PER_UD_FILE, {})
    all_sched[str(ud_num)] = {"tanggal": tanggal, "jam": jam, "menit": menit,
                               "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _save_json(SCHEDULE_PER_UD_FILE, all_sched)

# ═══════════════════════════════════════════════════════════════
#  ACTIVE USER DATA CONFIG
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
except: _def_dt = datetime.now()

DEFAULTS = {
    "save_mode": "local", "gdrive_folder_id": "",
    "deskripsi": "",
    "hashtags": [],
    "tanggal": _def_dt.strftime("%Y-%m-%d"),
    "jam": f"{_def_dt.hour:02d}", "menit": f"{_def_dt.minute:02d}",
    "interval": "60",
    "user_data_dir": os.path.join(APP_DIR, "user_data", "1"),
    "debug_port": "9222",
}

user_settings = {}
user_locks = {}
log_buffers = {}
full_auto_tasks = {}
active_tasks = {}

# Settings state tracked via user_data["in_settings"] flag

def get_cfg(uid):
    if uid not in user_settings:
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
MAX_LOG_LINES = 25

def make_log_fn(uid):
    if uid not in log_buffers: log_buffers[uid] = []
    def log_fn(msg, tag=None):
        ts = datetime.now().strftime("%H:%M:%S")
        icon = {"success":"✅","error":"❌","warn":"⚠️","info":"ℹ️"}.get(tag, "▪️")
        log_buffers[uid].append(f"<code>[{ts}]</code> {icon} {msg}")
        if len(log_buffers[uid]) > MAX_LOG_LINES:
            log_buffers[uid] = log_buffers[uid][-MAX_LOG_LINES:]
    return log_fn

async def live_log_updater(bot, chat_id, msg_id, uid, stop_evt):
    last_text = ""
    while not stop_evt.is_set():
        lines = log_buffers.get(uid, [])
        text = "\n".join(lines[-MAX_LOG_LINES:]) if lines else "<i>Menunggu log...</i>"
        text = f"📊 <b>Live Log</b>\n\n{text}"
        if text != last_text:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                    text=text[:4096], parse_mode=ParseMode.HTML)
                last_text = text
            except: pass
        await asyncio.sleep(3)
    lines = log_buffers.get(uid, [])
    text = "\n".join(lines[-MAX_LOG_LINES:]) if lines else ""
    text = f"📊 <b>Log Selesai</b>\n\n{text}\n\n✅ <b>Proses selesai.</b>"
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
            text=text[:4096], parse_mode=ParseMode.HTML)
    except: pass

async def _notify(bot, chat_id, text):
    try: await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
    except Exception as e: logger.warning(f"_notify failed: {e}")

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def escape_html(text):
    return text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def format_duration(seconds):
    seconds = int(seconds)
    if seconds >= 3600: return f"{seconds//3600}:{(seconds%3600)//60:02d}:{seconds%60:02d}"
    return f"{seconds//60:02d}:{seconds%60:02d}"

def format_size(b):
    if b >= 1024**3: return f"{b/1024**3:.1f}GB"
    if b >= 1024**2: return f"{b/1024**2:.1f}MB"
    if b >= 1024: return f"{b/1024:.1f}KB"
    return f"{b}B"

def get_video_duration(fp):
    try:
        r = subprocess.run([FFPROBE_PATH,"-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",fp], capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except: return 0

def get_video_info(fp):
    try:
        r = subprocess.run([FFPROBE_PATH,"-v","error","-select_streams","v:0",
            "-show_entries","stream=width,height","-of","csv=p=0:s=x",fp],
            capture_output=True, text=True, timeout=30)
        w,h = r.stdout.strip().split("x"); return int(w),int(h)
    except: return 1080,1920

def sanitize_filename(title):
    title = re.sub(r'[<>:"/\\|?*!,;\[\]{}()\']', '', title)
    title = re.sub(r'\s+', ' ', title).strip('. ')
    return title[:60].rstrip('. ') if len(title) > 60 else (title or "video")

def truncate_title(title, max_len=20):
    return title[:max_len-3]+"..." if len(title) > max_len else title

def progress_bar(pct, width=20):
    pct = max(0, min(100, pct))
    filled = int(width * pct / 100)
    return "█"*filled + "░"*(width-filled)

def build_progress_message(title, stages):
    STATUS_ICONS = {"pending":"⏳","running":"🔄","done":"✅","error":"❌","sending":"📤"}
    lines = [f"🎬 <b>{escape_html(title)}</b>\n"]
    for s in stages:
        icon = STATUS_ICONS.get(s["status"], "⏳")
        if s["status"] == "running":
            bar = progress_bar(s.get("pct",0))
            lines.append(f"{icon} <b>{s['name']}</b>  {bar} {s.get('pct',0)}%")
            if s.get("detail"): lines.append(f"    <i>{escape_html(s['detail'])}</i>")
        elif s["status"] == "done":
            lines.append(f"{icon} <b>{s['name']}</b> — Selesai")
            if s.get("detail"): lines.append(f"    <i>{escape_html(s['detail'])}</i>")
        elif s["status"] == "error":
            lines.append(f"{icon} <b>{s['name']}</b> — Error")
            if s.get("detail"): lines.append(f"    <i>{escape_html(s['detail'])}</i>")
        else: lines.append(f"{icon} {s['name']}")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
#  CORE: DOWNLOAD
# ═══════════════════════════════════════════════════════════════
async def download_video(url, temp_dir, progress_callback=None):
    os.makedirs(temp_dir, exist_ok=True)
    output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")
    cmd = ["yt-dlp","--no-playlist","-f","bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
           "--merge-output-format","mp4","-o",output_template,"--newline","--no-color",
           "--print","after_move:filepath",url]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    filepath = None; last_progress = 0
    while True:
        line = await proc.stdout.readline()
        if not line: break
        line = line.decode("utf-8", errors="replace").strip()
        pct_match = re.search(r'\[download\]\s+([\d.]+)%', line)
        if pct_match:
            pct = float(pct_match.group(1))
            if progress_callback and pct - last_progress >= 2:
                speed_m = re.search(r'at\s+([\d.]+\w+/s)', line)
                eta_m = re.search(r'ETA\s+(\S+)', line)
                detail = f"{pct:.0f}%"
                if speed_m: detail += f" • {speed_m.group(1)}"
                if eta_m: detail += f" • ETA {eta_m.group(1)}"
                await progress_callback(int(pct), detail)
                last_progress = pct
        if line and not line.startswith("[") and not line.startswith("Deleting") and os.path.isfile(line):
            filepath = line
    await proc.wait()
    if proc.returncode != 0: raise Exception(f"yt-dlp gagal (exit code {proc.returncode})")
    if not filepath:
        mp4s = [os.path.join(temp_dir,f) for f in os.listdir(temp_dir) if f.endswith(".mp4")]
        if mp4s: filepath = max(mp4s, key=os.path.getmtime)
        else: raise Exception("Tidak ada file video yang dihasilkan")
    title = os.path.splitext(os.path.basename(filepath))[0]
    return filepath, title

def download_video_sync(url, temp_dir, log_fn=None):
    """Synchronous download for use in threads."""
    os.makedirs(temp_dir, exist_ok=True)
    output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")
    cmd = ["yt-dlp","--no-playlist","-f","bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
           "--merge-output-format","mp4","-o",output_template,"--newline","--no-color",
           "--print","after_move:filepath",url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    filepath = None
    for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").strip()
        pct_match = re.search(r'\[download\]\s+([\d.]+)%', line)
        if pct_match and log_fn:
            log_fn(f"Download: {float(pct_match.group(1)):.0f}%", "info")
        if line and not line.startswith("[") and not line.startswith("Deleting") and os.path.isfile(line):
            filepath = line
    proc.wait()
    if proc.returncode != 0: raise Exception(f"yt-dlp gagal (exit code {proc.returncode})")
    if not filepath:
        mp4s = [os.path.join(temp_dir,f) for f in os.listdir(temp_dir) if f.endswith(".mp4")]
        if mp4s: filepath = max(mp4s, key=os.path.getmtime)
        else: raise Exception("Tidak ada file video yang dihasilkan")
    title = os.path.splitext(os.path.basename(filepath))[0]
    return filepath, title

# ═══════════════════════════════════════════════════════════════
#  CORE: SPLIT
# ═══════════════════════════════════════════════════════════════
def split_and_process_sync(input_file, output_dir, title, logo_path, log_fn=None):
    os.makedirs(output_dir, exist_ok=True)
    duration = get_video_duration(input_file)
    if duration <= 0: raise Exception("Tidak bisa baca durasi video")
    total_parts = max(1, int(duration // SEGMENT_DURATION))
    safe_title = sanitize_filename(title)
    display_title = truncate_title(title)
    vid_w, _ = get_video_info(input_file)
    output_files = []
    for part in range(1, total_parts + 1):
        start_sec = (part-1)*SEGMENT_DURATION
        output_file = os.path.join(output_dir, f"{safe_title}_Part{part}.mp4")
        if log_fn: log_fn(f"Split Part {part}/{total_parts}...", "info")
        overlay_title = display_title.replace("'","'\\\\'").replace(":","\\\\:").replace("%","%%")
        overlay_part = f"Part {part}/{total_parts}"
        if logo_path and os.path.exists(logo_path):
            wm_w = max(32, int(vid_w*WATERMARK_WIDTH_PCT/100))
            mx = max(4, int(vid_w*WATERMARK_MARGIN_PCT/100))
            fc = (f"[1:v]scale={wm_w}:-1[wm];[0:v][wm]overlay={mx}:{mx}[vid];"
                  f"[vid]drawtext=text='{overlay_title}':font='{TEXT_FONT}':fontsize=h*{TEXT_SIZE_PCT}/100:"
                  f"fontcolor={TEXT_COLOR}:borderw={TEXT_BORDER_W}:bordercolor={TEXT_BORDER_COLOR}:"
                  f"x=(w-text_w)/2:y=h-text_h*2.5-h*{WATERMARK_MARGIN_PCT*2}/100[vid2];"
                  f"[vid2]drawtext=text='{overlay_part}':font='{TEXT_FONT}':fontsize=h*{TEXT_SIZE_PCT}/100:"
                  f"fontcolor={TEXT_COLOR}:borderw={TEXT_BORDER_W}:bordercolor={TEXT_BORDER_COLOR}:"
                  f"x=(w-text_w)/2:y=h-text_h-h*{WATERMARK_MARGIN_PCT*2}/100[out]")
            cmd = [FFMPEG_PATH,"-y","-ss",str(start_sec),"-t",str(SEGMENT_DURATION),
                   "-i",input_file,"-i",logo_path,"-filter_complex",fc,"-map","[out]","-map","0:a?",
                   "-c:v","libx264","-preset","fast","-crf","23","-c:a","aac","-b:a","128k",
                   "-shortest","-movflags","+faststart",output_file]
        else:
            fs = (f"drawtext=text='{overlay_title}':font='{TEXT_FONT}':fontsize=h*{TEXT_SIZE_PCT}/100:"
                  f"fontcolor={TEXT_COLOR}:borderw={TEXT_BORDER_W}:bordercolor={TEXT_BORDER_COLOR}:"
                  f"x=(w-text_w)/2:y=h-text_h*2.5-h*{WATERMARK_MARGIN_PCT*2}/100,"
                  f"drawtext=text='{overlay_part}':font='{TEXT_FONT}':fontsize=h*{TEXT_SIZE_PCT}/100:"
                  f"fontcolor={TEXT_COLOR}:borderw={TEXT_BORDER_W}:bordercolor={TEXT_BORDER_COLOR}:"
                  f"x=(w-text_w)/2:y=h-text_h-h*{WATERMARK_MARGIN_PCT*2}/100")
            cmd = [FFMPEG_PATH,"-y","-ss",str(start_sec),"-t",str(SEGMENT_DURATION),
                   "-i",input_file,"-vf",fs,"-c:v","libx264","-preset","fast","-crf","23",
                   "-c:a","aac","-b:a","128k","-movflags","+faststart",output_file]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 10240:
            output_files.append(output_file)
            if log_fn: log_fn(f"  ✓ Part {part} selesai", "success")
        else:
            if log_fn: log_fn(f"  ❌ Part {part} gagal", "error")
    return output_files

# ═══════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════
def main_menu_kb(uid=None):
    is_auto = bool(uid and full_auto_tasks.get(uid))
    rows = [
        [InlineKeyboardButton("📋 Stok Link", callback_data="act_stok")],
        [InlineKeyboardButton(
            "⏹ Stop Full Auto" if is_auto else "🤖 Full Auto",
            callback_data="stop_full_auto" if is_auto else "act_full_auto"
        )],
        [InlineKeyboardButton("📂 Kelola Video", callback_data="fm_list")],
        [InlineKeyboardButton("↻ Refresh", callback_data="refresh")],
    ]
    return InlineKeyboardMarkup(rows)

def _list_video_yt_folders():
    """List subfolders in video_yt with file count and total size."""
    if not os.path.isdir(FINAL_DIR): return []
    folders = []
    for name in sorted(os.listdir(FINAL_DIR)):
        path = os.path.join(FINAL_DIR, name)
        if os.path.isdir(path):
            files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
            total_size = sum(os.path.getsize(os.path.join(path, f)) for f in files)
            folders.append({"name": name, "path": path, "files": len(files),
                           "size_mb": total_size / (1024*1024)})
    return folders

def _list_folder_files(folder_name):
    """List files inside a subfolder of video_yt."""
    path = os.path.join(FINAL_DIR, folder_name)
    if not os.path.isdir(path): return []
    files = []
    for f in sorted(os.listdir(path)):
        fp = os.path.join(path, f)
        if os.path.isfile(fp):
            files.append({"name": f, "path": fp, "size_mb": os.path.getsize(fp)/(1024*1024)})
    return files

def stok_text():
    active = load_active_ud()
    t = f"📦 <b>Stok Link Per User Data</b>\n"
    t += f"🟢 Aktif: <b>{', '.join(str(x) for x in active)}</b>\n\n"
    for ud in sorted(set(active + list(range(1,8)))):
        links = load_stok_per_ud(ud)
        if not links and ud not in active: continue
        marker = "🟢" if ud in active else "⚪"
        ss = load_schedule_per_ud(ud)
        t += f"{marker} <b>UD {ud}</b>: {len(links)} link | Sched: <code>{ss['tanggal']} {ss['jam']}:{ss['menit']}</code>\n"
    return t

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    ctx.user_data["in_settings"] = False
    ctx.user_data["setting_field"] = None
    cfg = get_cfg(uid)
    text = (f"🎬 <b>YouTube Bot + Full Auto Upload</b>\n\n"
            f"{stok_text()}\n"
            f"📝 Deskripsi: <code>{cfg['deskripsi'][:50] or '(kosong)'}</code>\n"
            f"⏱ Interval: <b>{cfg['interval']} menit</b>")
    await update.message.reply_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)

# ═══════════════════════════════════════════════════════════════
#  SETTINGS (inline buttons + ForceReply, works in groups)
# ═══════════════════════════════════════════════════════════════
def _settings_kb():
    """Build inline keyboard for settings menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Deskripsi", callback_data="set_desc"),
         InlineKeyboardButton("⏱ Interval", callback_data="set_interval")],
        [InlineKeyboardButton("📱 Active UD", callback_data="set_active_ud"),
         InlineKeyboardButton("🏷 Hashtags", callback_data="set_hashtags")],
        [InlineKeyboardButton("➕ Tambah Stok", callback_data="set_stok_pick"),
         InlineKeyboardButton("📋 Lihat Stok", callback_data="set_view_pick")],
        [InlineKeyboardButton("📅 Edit Schedule", callback_data="set_sched_pick"),
         InlineKeyboardButton("🗑 Hapus Stok", callback_data="set_del_pick")],
        [InlineKeyboardButton("❌ Tutup", callback_data="close_settings")],
    ])

def _ud_picker_kb(prefix):
    """Build UD picker (1-7) inline keyboard."""
    rows = []
    row = []
    for i in range(1, 8):
        row.append(InlineKeyboardButton(f"UD {i}", callback_data=f"{prefix}_{i}"))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅ Kembali", callback_data="set_back")])
    return InlineKeyboardMarkup(rows)

def _settings_text(uid):
    cfg = get_cfg(uid)
    active = load_active_ud()
    hashtags_list = cfg.get('hashtags', [])
    hashtags_display = ', '.join(f'#{h}' for h in hashtags_list[:5]) if hashtags_list else '(kosong)'
    return ("⚙️ <b>Settings</b>\n\n"
            f"📝 Deskripsi: <code>{escape_html(cfg['deskripsi'][:60]) or '(kosong)'}</code>\n"
            f"⏱ Interval: <code>{cfg['interval']} menit</code>\n"
            f"📱 Active UD: <b>{', '.join(str(x) for x in active)}</b>\n"
            f"🏷 Hashtags: <code>{escape_html(hashtags_display)}</code>\n\n"
            "Pilih tombol di bawah untuk mengubah:")

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    uid = update.effective_user.id
    text = _settings_text(uid)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_settings_kb())
    ctx.user_data["in_settings"] = True
    ctx.user_data["setting_field"] = None

async def handle_text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Global text handler — catches replies for settings input."""
    if not update.message or not update.message.text:
        return
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    field = ctx.user_data.get("setting_field")
    if not field:
        return  # not waiting for text input
    try:
        await _process_settings_text(update, ctx, field)
    except Exception as e:
        logger.error(f"[settings] error: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ Error: {escape_html(str(e)[:200])}\nKirim /settings untuk coba lagi.")
        except:
            pass

async def _process_settings_text(update, ctx, field):
    """Process text input for settings."""
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    txt = update.message.text.strip()
    logger.info(f"[settings_text] uid={uid}, field={field}, txt={txt!r}")

    if field == "desc":
        cfg["deskripsi"] = txt
        ctx.user_data["setting_field"] = None
        await update.message.reply_text(
            f"✅ Deskripsi diubah: <code>{escape_html(txt[:60])}</code>",
            parse_mode=ParseMode.HTML, reply_markup=_settings_kb())
    elif field == "interval":
        cfg["interval"] = txt
        ctx.user_data["setting_field"] = None
        await update.message.reply_text(
            f"✅ Interval diubah: <code>{txt} menit</code>",
            parse_mode=ParseMode.HTML, reply_markup=_settings_kb())
    elif field == "active_ud":
        nums = [int(x) for x in re.split(r'[,\s]+', txt) if x.strip().isdigit()]
        nums = [n for n in nums if 1 <= n <= 7]
        if nums:
            save_active_ud(nums)
            ctx.user_data["setting_field"] = None
            await update.message.reply_text(
                f"✅ Active UD: <b>{', '.join(str(x) for x in nums)}</b>",
                parse_mode=ParseMode.HTML, reply_markup=_settings_kb())
        else:
            await update.message.reply_text(
                "❌ Format salah. Kirim nomor 1-7 dipisah koma.\nContoh: <code>2,5,6</code>",
                parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
    elif field == "hashtags":
        raw_tags = re.split(r'[,\n]+', txt)
        tags = [t.strip().lstrip('#').strip() for t in raw_tags if t.strip().lstrip('#').strip()]
        cfg["hashtags"] = tags
        display = ', '.join(f'#{t}' for t in tags)
        ctx.user_data["setting_field"] = None
        await update.message.reply_text(
            f"✅ Hashtags: <code>{escape_html(display)}</code>",
            parse_mode=ParseMode.HTML, reply_markup=_settings_kb())
    elif field == "stok_ud":
        ud_num = ctx.user_data.get("stok_ud_num")
        urls = [u.strip() for u in txt.split("\n") if u.strip()]
        add_stok_per_ud(ud_num, urls)
        total = len(load_stok_per_ud(ud_num))
        ctx.user_data["setting_field"] = None
        await update.message.reply_text(
            f"✅ {len(urls)} link ditambahkan ke UD {ud_num}. Total: {total}",
            reply_markup=_settings_kb())
    elif field == "sched_ud_date":
        ud_num = ctx.user_data.get("sched_ud_num")
        try:
            datetime.strptime(txt, "%Y-%m-%d")
            ctx.user_data["sched_ud_date_val"] = txt
            ctx.user_data["setting_field"] = "sched_ud_time"
            await update.message.reply_text(
                f"Kirim jam untuk UD {ud_num} (HH:MM):\nContoh: <code>14:30</code>",
                parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
        except:
            await update.message.reply_text(
                "❌ Format salah. YYYY-MM-DD\nContoh: <code>2026-03-02</code>",
                parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
    elif field == "sched_ud_time":
        ud_num = ctx.user_data.get("sched_ud_num")
        date_val = ctx.user_data.get("sched_ud_date_val")
        parts_time = txt.replace(".",":").split(":")
        if len(parts_time) == 2:
            jam, menit = parts_time[0].zfill(2), parts_time[1].zfill(2)
            save_schedule_per_ud(ud_num, date_val, jam, menit)
            ctx.user_data["setting_field"] = None
            await update.message.reply_text(
                f"✅ Schedule UD {ud_num}: {date_val} {jam}:{menit}",
                reply_markup=_settings_kb())
        else:
            await update.message.reply_text(
                "❌ Format salah. HH:MM\nContoh: <code>14:30</code>",
                parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
    elif field == "hapus_stok_ud":
        ud_num = ctx.user_data.get("hapus_ud_num")
        if txt.lower() == "all":
            save_stok_per_ud(ud_num, [])
            ctx.user_data["setting_field"] = None
            await update.message.reply_text(
                f"✅ Stok UD {ud_num} dikosongkan!", reply_markup=_settings_kb())
        else:
            try:
                idx = int(txt) - 1
                links = load_stok_per_ud(ud_num)
                if 0 <= idx < len(links):
                    removed = links.pop(idx)
                    save_stok_per_ud(ud_num, links)
                    ctx.user_data["setting_field"] = None
                    await update.message.reply_text(
                        f"✅ Dihapus: {removed[:60]}", reply_markup=_settings_kb())
                else:
                    await update.message.reply_text("❌ Nomor tidak valid.",
                        reply_markup=ForceReply(selective=True))
            except:
                await update.message.reply_text("❌ Kirim nomor atau 'all'.",
                    reply_markup=ForceReply(selective=True))
    else:
        ctx.user_data["setting_field"] = None
        await update.message.reply_text("❌ Kirim /settings untuk mulai ulang.")

async def _handle_settings_callback(q, ctx, data):
    """Handle settings-related callback queries."""
    uid = q.from_user.id
    cfg = get_cfg(uid)
    chat_id = q.message.chat_id
    bot = q.bot

    if data == "close_settings":
        ctx.user_data["in_settings"] = False
        ctx.user_data["setting_field"] = None
        await q.edit_message_text("⚙️ Settings ditutup.")
        return True

    if data == "set_back":
        text = _settings_text(uid)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=_settings_kb())
        return True

    # Direct settings that need text input
    if data == "set_desc":
        ctx.user_data["setting_field"] = "desc"
        await bot.send_message(chat_id,
            f"📝 Deskripsi saat ini: <code>{escape_html(cfg['deskripsi'][:60]) or '(kosong)'}</code>\n\n"
            "Kirim deskripsi baru:",
            parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
        return True

    if data == "set_interval":
        ctx.user_data["setting_field"] = "interval"
        await bot.send_message(chat_id,
            f"⏱ Interval saat ini: <code>{cfg['interval']} menit</code>\n\n"
            "Kirim interval baru (menit):\nContoh: <code>60</code>",
            parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
        return True

    if data == "set_active_ud":
        ctx.user_data["setting_field"] = "active_ud"
        active = load_active_ud()
        await bot.send_message(chat_id,
            f"📱 Active UD saat ini: <b>{', '.join(str(x) for x in active)}</b>\n\n"
            "Kirim nomor UD yang diaktifkan (pisah koma):\nContoh: <code>2,5,6</code>",
            parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
        return True

    if data == "set_hashtags":
        ctx.user_data["setting_field"] = "hashtags"
        current = cfg.get('hashtags', [])
        current_display = ', '.join(f'#{t}' for t in current) if current else '(kosong)'
        await bot.send_message(chat_id,
            f"🏷 Hashtags saat ini: <code>{escape_html(current_display)}</code>\n\n"
            "Kirim hashtag baru (pisah koma):\nContoh: <code>fyp, viral, tiktok</code>",
            parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
        return True

    # UD pickers (show UD 1-7 buttons)
    if data in ("set_stok_pick", "set_view_pick", "set_sched_pick", "set_del_pick"):
        labels = {"set_stok_pick": "➕ Tambah Stok — Pilih UD:",
                  "set_view_pick": "📋 Lihat Stok — Pilih UD:",
                  "set_sched_pick": "📅 Edit Schedule — Pilih UD:",
                  "set_del_pick": "🗑 Hapus Stok — Pilih UD:"}
        prefixes = {"set_stok_pick": "set_stok",
                    "set_view_pick": "set_view",
                    "set_sched_pick": "set_sched",
                    "set_del_pick": "set_del"}
        await q.edit_message_text(labels[data], reply_markup=_ud_picker_kb(prefixes[data]))
        return True

    # UD selected: Tambah Stok
    if data.startswith("set_stok_"):
        ud_num = int(data.split("_")[-1])
        ctx.user_data["setting_field"] = "stok_ud"
        ctx.user_data["stok_ud_num"] = ud_num
        await bot.send_message(chat_id,
            f"Kirim link YouTube untuk <b>UD {ud_num}</b> (satu per baris):",
            parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
        return True

    # UD selected: Lihat Stok (no text input needed)
    if data.startswith("set_view_"):
        ud_num = int(data.split("_")[-1])
        links = load_stok_per_ud(ud_num)
        ss = load_schedule_per_ud(ud_num)
        t = f"📦 <b>Stok UD {ud_num}</b> ({len(links)} link)\n"
        t += f"📅 Schedule: <code>{ss['tanggal']} {ss['jam']}:{ss['menit']}</code>\n\n"
        for i, l in enumerate(links[:15]):
            t += f"  {i+1}. <code>{l[:60]}</code>\n"
        if len(links) > 15: t += f"  ... +{len(links)-15} lainnya\n"
        if not links: t += "  <i>(kosong)</i>\n"
        await q.edit_message_text(t, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Kembali", callback_data="set_back")]]))
        return True

    # UD selected: Edit Schedule
    if data.startswith("set_sched_"):
        ud_num = int(data.split("_")[-1])
        ctx.user_data["setting_field"] = "sched_ud_date"
        ctx.user_data["sched_ud_num"] = ud_num
        ss = load_schedule_per_ud(ud_num)
        await bot.send_message(chat_id,
            f"📅 Schedule UD {ud_num}: <code>{ss['tanggal']} {ss['jam']}:{ss['menit']}</code>\n\n"
            "Kirim tanggal baru (YYYY-MM-DD):\nContoh: <code>2026-03-02</code>",
            parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
        return True

    # UD selected: Hapus Stok
    if data.startswith("set_del_"):
        ud_num = int(data.split("_")[-1])
        links = load_stok_per_ud(ud_num)
        if not links:
            await q.edit_message_text(f"Stok UD {ud_num} kosong.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Kembali", callback_data="set_back")]]))
            return True
        ctx.user_data["setting_field"] = "hapus_stok_ud"
        ctx.user_data["hapus_ud_num"] = ud_num
        t = f"🗑 <b>Hapus Stok UD {ud_num}</b> ({len(links)} link)\n\n"
        for i, l in enumerate(links[:15]):
            t += f"  {i+1}. <code>{l[:60]}</code>\n"
        await bot.send_message(chat_id,
            t + "\nKirim nomor untuk hapus 1, atau <code>all</code> untuk hapus semua:",
            parse_mode=ParseMode.HTML, reply_markup=ForceReply(selective=True))
        return True

    return False  # not a settings callback

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["in_settings"] = False
    ctx.user_data["setting_field"] = None
    await update.message.reply_text("⚙️ Settings ditutup.", reply_markup=main_menu_kb(update.effective_user.id))

# ═══════════════════════════════════════════════════════════════
#  FULL AUTO UPLOAD (download from stok → split → upload TikTok)
# ═══════════════════════════════════════════════════════════════
def _full_auto_single_upload(cfg, log_fn, stop_evt, ud_num):
    """Download 1 link from UD stok, split, upload all parts to TikTok using that UD."""
    links = load_stok_per_ud(ud_num)
    if not links:
        log_fn(f"❌ Stok UD {ud_num} kosong!", "error"); return False

    url = links[0]
    log_fn(f"📥 [UD {ud_num}] Downloading: {url[:60]}...", "info")

    job_temp = os.path.join(TEMP_DIR, f"auto_ud{ud_num}_{int(time.time())}")
    job_out = os.path.join(TEMP_DIR, f"auto_ud{ud_num}_{int(time.time())}_out")

    userdata = os.path.join(APP_DIR, "user_data", str(ud_num))
    port = UD_PORT_MAP.get(ud_num, str(9222 + ud_num - 1))

    try:
        filepath, title = download_video_sync(url, job_temp, log_fn)
        log_fn(f"✓ Download selesai: {title[:40]}", "success")
        if stop_evt.is_set(): return False

        logo = LOGO_PATH if os.path.exists(LOGO_PATH) else None
        output_files = split_and_process_sync(filepath, job_out, title, logo, log_fn)
        if not output_files:
            log_fn("❌ Tidak ada part yang berhasil!", "error"); return False
        log_fn(f"✓ Split: {len(output_files)} parts", "success")
        if stop_evt.is_set(): return False

        # Read schedule from per-UD state
        ss = load_schedule_per_ud(ud_num)
        hour = int(ss["jam"]); minute = int(ss["menit"])
        date_str = ss["tanggal"]
        interval = int(cfg.get("interval", "60"))
        deskripsi = cfg.get("deskripsi", "")
        hashtags = cfg.get("hashtags", [])

        start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
        log_fn(f"📅 [UD {ud_num}] Schedule mulai: {start_dt.strftime('%Y-%m-%d %H:%M')}", "info")
        if hashtags:
            log_fn(f"🏷 [UD {ud_num}] Hashtags: {', '.join('#'+h for h in hashtags)}", "info")
        log_fn(f"🌐 [UD {ud_num}] Membuka Chrome (port {port})...", "info")

        chrome_proc = open_chrome_debug(userdata, port)
        driver = connect_selenium(port)
        log_fn(f"✓ [UD {ud_num}] Chrome terhubung!", "success")
        uploaded = 0

        try:
            for idx, out_path in enumerate(output_files):
                if stop_evt.is_set(): break
                if not os.path.exists(out_path): continue
                sched_dt = start_dt + timedelta(minutes=interval * idx)
                log_fn(f"[UD {ud_num}] [{idx+1}/{len(output_files)}] Upload: {os.path.basename(out_path)}", "info")
                log_fn(f"  Schedule: {sched_dt.strftime('%Y-%m-%d %H:%M')}", "info")
                try:
                    navigate_upload_page(driver, force=(idx > 0))
                    time.sleep(3)
                    do_upload_file(driver, os.path.normpath(out_path), log_fn)
                    time.sleep(5)
                    do_post_video(driver, deskripsi, "", "", log_fn, sched_dt, stop_evt,
                                 add_sound=False, add_product=False, skip_switches=True,
                                 hashtags=hashtags if hashtags else None)
                    uploaded += 1
                except Exception as e:
                    log_fn(f"  ❌ Error: {e}", "error")
                if idx < len(output_files)-1 and not stop_evt.is_set():
                    log_fn("  Menunggu 10 detik...", "info"); time.sleep(10)
        finally:
            try: driver.quit()
            except: pass
            try: chrome_proc.terminate()
            except: pass

        if uploaded > 0:
            last_sched = start_dt + timedelta(minutes=interval*(uploaded-1))
            next_dt = last_sched + timedelta(minutes=interval)
            save_schedule_per_ud(ud_num, next_dt.strftime("%Y-%m-%d"), f"{next_dt.hour:02d}", f"{next_dt.minute:02d}")
            log_fn(f"💾 [UD {ud_num}] Next schedule: {next_dt.strftime('%Y-%m-%d %H:%M')}", "success")
            remove_stok_per_ud(ud_num, url)
            log_fn(f"🗑 [UD {ud_num}] Link dihapus dari stok", "success")

        log_fn(f"🎉 [UD {ud_num}] Selesai! {uploaded}/{len(output_files)} parts uploaded", "success")
        return True

    except Exception as e:
        log_fn(f"❌ [UD {ud_num}] Error: {e}", "error")
        return False
    finally:
        for d in [job_temp, job_out]:
            try:
                if os.path.exists(d): shutil.rmtree(d)
            except: pass

# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not is_allowed(uid): return
    data = q.data

    # Route settings callbacks (set_*, close_settings, etc.)
    if data.startswith("set_") or data in ("close_settings", "set_back"):
        handled = await _handle_settings_callback(q, ctx, data)
        if handled:
            return

    if data == "refresh":
        cfg = get_cfg(uid)
        text = (f"🎬 <b>YouTube Bot + Full Auto Upload</b>\n\n{stok_text()}\n"
                f"⏱ Interval: <b>{cfg['interval']} menit</b>")
        await q.edit_message_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    if data == "act_stok":
        await q.edit_message_text(stok_text(), reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    # ── File Manager: List folders ──
    if data == "fm_list":
        folders = _list_video_yt_folders()
        if not folders:
            await q.edit_message_text("📂 <b>video_yt</b> kosong.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        text = f"📂 <b>Folder di video_yt</b> ({len(folders)} folder)\n\n"
        rows = []
        for i, f in enumerate(folders):
            text += f"{i+1}. <code>{f['name'][:40]}</code> — {f['files']} file ({f['size_mb']:.1f} MB)\n"
            rows.append([InlineKeyboardButton(f"📁 {f['name'][:30]}", callback_data=f"fm_open|{i}")])
        rows.append([InlineKeyboardButton("🗑 Hapus Semua", callback_data="fm_delall")])
        rows.append([InlineKeyboardButton("🏠 Menu", callback_data="refresh")])
        # Store folder list in user_data for reference
        ctx.user_data["fm_folders"] = folders
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
        return

    # ── File Manager: Open folder (show files) ──
    if data.startswith("fm_open|"):
        idx = int(data.split("|")[1])
        folders = ctx.user_data.get("fm_folders", [])
        if idx >= len(folders):
            await q.edit_message_text("❌ Folder tidak ditemukan.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        folder = folders[idx]
        files = _list_folder_files(folder["name"])
        ctx.user_data["fm_current_folder"] = folder["name"]
        ctx.user_data["fm_files"] = files
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

    # ── File Manager: Delete single file ──
    if data.startswith("fm_delfile|"):
        idx = int(data.split("|")[1])
        files = ctx.user_data.get("fm_files", [])
        folder_name = ctx.user_data.get("fm_current_folder", "")
        if idx >= len(files):
            await q.edit_message_text("❌ File tidak ditemukan.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        f = files[idx]
        try:
            if os.path.exists(f["path"]): os.remove(f["path"])
            text = f"✅ File <code>{escape_html(f['name'])}</code> dihapus!\n\n"
        except Exception as e:
            text = f"❌ Gagal hapus: {escape_html(str(e))}\n\n"
        # Refresh file list
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
        # Re-find folder index
        all_folders = _list_video_yt_folders()
        fidx = next((i for i, ff in enumerate(all_folders) if ff["name"] == folder_name), 0)
        ctx.user_data["fm_folders"] = all_folders
        rows.append([InlineKeyboardButton("🗑 Hapus Folder Ini", callback_data=f"fm_delfolder|{fidx}")])
        rows.append([InlineKeyboardButton("⬅ Kembali", callback_data="fm_list")])
        await q.edit_message_text(f"📁 <b>{escape_html(folder_name[:50])}</b>\n\n" + text,
            reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)
        return

    # ── File Manager: Delete entire folder ──
    if data.startswith("fm_delfolder|"):
        idx = int(data.split("|")[1])
        folders = ctx.user_data.get("fm_folders", _list_video_yt_folders())
        if idx >= len(folders):
            await q.edit_message_text("❌ Folder tidak ditemukan.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        folder = folders[idx]
        try:
            shutil.rmtree(folder["path"])
            text = f"✅ Folder <code>{escape_html(folder['name'][:50])}</code> dihapus! ({folder['files']} file, {folder['size_mb']:.1f} MB)\n\n"
        except Exception as e:
            text = f"❌ Gagal hapus folder: {escape_html(str(e))}\n\n"
        # Refresh & show folder list
        new_folders = _list_video_yt_folders()
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

    # ── File Manager: Delete ALL folders ──
    if data == "fm_delall":
        folders = _list_video_yt_folders()
        deleted = 0; total_files = 0; total_mb = 0
        for f in folders:
            try:
                shutil.rmtree(f["path"]); deleted += 1
                total_files += f["files"]; total_mb += f["size_mb"]
            except: pass
        text = (f"🗑 <b>Semua folder dihapus!</b>\n\n"
                f"Folder: <b>{deleted}</b>\nFile: <b>{total_files}</b>\n"
                f"Ukuran: <b>{total_mb:.1f} MB</b>")
        await q.edit_message_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    if data == "act_full_auto":
        if uid in full_auto_tasks:
            await q.edit_message_text("⚠️ Full Auto sudah berjalan.", reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
            return
        stop_auto = threading.Event()
        bot = ctx.bot; chat_id = q.message.chat_id; main_loop = asyncio.get_event_loop()

        def _send(text):
            asyncio.run_coroutine_threadsafe(_notify(bot, chat_id, text), main_loop)

        def _daemon():
            active = load_active_ud()
            _send(f"🤖 <b>Full Auto dimulai!</b>\nActive UD: <b>{', '.join(str(x) for x in active)}</b>\nBot akan download dari stok masing-masing UD → split → upload TikTok.")
            while not stop_auto.is_set():
                active = load_active_ud()
                any_has_stok = False

                for ud_num in active:
                    if stop_auto.is_set(): break
                    links = load_stok_per_ud(ud_num)
                    if not links:
                        continue
                    any_has_stok = True

                    state = load_schedule_per_ud(ud_num)
                    try:
                        trigger_dt = datetime.strptime(
                            f"{state['tanggal']} {state['jam']}:{state['menit']}", "%Y-%m-%d %H:%M"
                        ) + timedelta(minutes=1)
                    except:
                        _send(f"❌ Format schedule UD {ud_num} error!"); continue

                    now = datetime.now()
                    wait_sec = (trigger_dt - now).total_seconds()
                    if wait_sec > 0:
                        _send(f"⏳ <b>UD {ud_num}</b>: menunggu <code>{trigger_dt.strftime('%Y-%m-%d %H:%M')}</code> "
                              f"({int(wait_sec//60)} menit lagi)...")
                        elapsed = 0
                        while elapsed < wait_sec and not stop_auto.is_set():
                            time.sleep(min(30, wait_sec - elapsed)); elapsed += 30
                        if stop_auto.is_set(): break

                    _send(f"🚀 <b>UD {ud_num}</b>: memulai download & upload...")
                    lock = get_lock(uid)
                    if not lock.acquire(blocking=True, timeout=60):
                        _send("⚠️ Gagal acquire lock, skip..."); continue

                    log_buffers[uid] = []
                    log_fn = make_log_fn(uid)
                    cfg = get_cfg(uid)
                    inner_stop = threading.Event()
                    try:
                        _full_auto_single_upload(cfg, log_fn, inner_stop, ud_num)
                    except Exception as e:
                        _send(f"❌ [UD {ud_num}] Error: {e}")
                    finally:
                        lock.release()

                    buf_lines = log_buffers.get(uid, [])
                    summary = "\n".join(buf_lines[-8:])
                    _send(f"🎉 <b>UD {ud_num}: selesai!</b>\n\n{summary}")
                    if stop_auto.is_set(): break
                    time.sleep(10)

                if not any_has_stok and not stop_auto.is_set():
                    _send("📦 Semua stok UD kosong. Menunggu 60 detik...")
                    for _ in range(12):
                        if stop_auto.is_set(): break
                        time.sleep(5)

                if not stop_auto.is_set():
                    time.sleep(10)

            full_auto_tasks.pop(uid, None)
            _send("⏹ <b>Full Auto dihentikan.</b>")

        t = threading.Thread(target=_daemon, daemon=True, name=f"yt_full_auto_{uid}")
        full_auto_tasks[uid] = {"stop": stop_auto, "thread": t}
        t.start()
        active = load_active_ud()
        await q.edit_message_text(
            f"🤖 <b>Full Auto aktif!</b>\nActive UD: <b>{', '.join(str(x) for x in active)}</b>\n"
            f"Bot akan otomatis download stok per UD → split → upload ke TikTok.\n\nTekan <b>Stop Full Auto</b> untuk menghentikan.",
            reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    if data == "stop_full_auto":
        task = full_auto_tasks.get(uid)
        if task: task["stop"].set(); full_auto_tasks.pop(uid, None)
        await q.edit_message_text("⏹ <b>Full Auto dihentikan.</b>\n\n" + stok_text(),
            reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

# ═══════════════════════════════════════════════════════════════
#  /download (original feature preserved)
# ═══════════════════════════════════════════════════════════════
async def cmd_download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; chat_id = update.message.chat_id
    if not is_allowed(uid):
        await update.message.reply_text("❌ Tidak diizinkan."); return
    args = ctx.args
    if not args:
        await update.message.reply_text("❌ <b>Format:</b> <code>/download &lt;link_youtube&gt;</code>", parse_mode=ParseMode.HTML); return
    url = args[0]
    yt_pat = re.compile(r'(https?://)?(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/|m\.youtube\.com/watch\?v=)')
    if not yt_pat.search(url):
        await update.message.reply_text("❌ URL tidak valid!", parse_mode=ParseMode.HTML); return
    if active_tasks.get(chat_id):
        await update.message.reply_text("⏳ Ada proses berjalan.", parse_mode=ParseMode.HTML); return
    active_tasks[chat_id] = True
    job_temp = os.path.join(TEMP_DIR, f"{chat_id}_{int(time.time())}")
    job_out = os.path.join(TEMP_DIR, f"{chat_id}_{int(time.time())}_out")
    stages = [
        {"name":"📥 Download","status":"running","pct":0,"detail":"Memulai..."},
        {"name":"✂️ Split & Process","status":"pending","pct":0,"detail":""},
        {"name":"💾 Simpan","status":"pending","pct":0,"detail":""},
    ]
    progress_msg = await update.message.reply_text(build_progress_message("Memproses...", stages), parse_mode=ParseMode.HTML)
    last_edit = [time.time()]
    async def safe_edit(text, force=False):
        now=time.time()
        if not force and now-last_edit[0]<2: return
        try: await asyncio.wait_for(progress_msg.edit_text(text, parse_mode=ParseMode.HTML), timeout=5); last_edit[0]=time.time()
        except: pass
    try:
        async def dl_prog(pct,detail): stages[0]["pct"]=pct; stages[0]["detail"]=detail; await safe_edit(build_progress_message("Memproses...",stages))
        filepath,title = await download_video(url, job_temp, dl_prog)
        fsize=os.path.getsize(filepath); dur=get_video_duration(filepath)
        stages[0]["status"]="done"; stages[0]["detail"]=f"{format_size(fsize)} • {format_duration(dur)}"
        use_logo=os.path.exists(LOGO_PATH)
        await safe_edit(build_progress_message(title, stages))
        total_parts=max(1,int(dur//SEGMENT_DURATION))
        stages[1]["status"]="running"; stages[1]["detail"]=f"0/{total_parts} parts"
        await safe_edit(build_progress_message(title, stages))
        logo=LOGO_PATH if use_logo else None
        output_files = split_and_process_sync(filepath, job_out, title, logo)
        stages[1]["status"]="done"; stages[1]["detail"]=f"{len(output_files)} parts"
        await safe_edit(build_progress_message(title, stages))
        # Save locally
        stages[2]["status"]="running"
        safe_title=sanitize_filename(title); video_folder=os.path.join(FINAL_DIR, safe_title)
        os.makedirs(video_folder, exist_ok=True); saved=0
        for i,of in enumerate(output_files):
            dest=os.path.join(video_folder,os.path.basename(of))
            try: shutil.move(of, dest); saved+=1
            except: pass
            stages[2]["pct"]=int((i+1)/len(output_files)*100); stages[2]["detail"]=f"{saved}/{len(output_files)}"
            await safe_edit(build_progress_message(title, stages))
        stages[2]["status"]="done"; stages[2]["detail"]=f"{saved} ✅"
        summary=f"\n\n{'━'*28}\n✅ <b>SELESAI!</b>\n📹 {escape_html(truncate_title(title,50))}\n📌 {saved} parts\n📂 <code>{video_folder}</code>"
        await progress_msg.edit_text((build_progress_message(title,stages)+summary)[:4096], parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Download error: {e}")
        try: await progress_msg.edit_text(f"❌ <b>Error!</b>\n\n<code>{escape_html(str(e)[:500])}</code>", parse_mode=ParseMode.HTML)
        except: pass
    finally:
        for d in [job_temp, job_out]:
            try:
                if os.path.exists(d): shutil.rmtree(d)
            except: pass
        active_tasks.pop(chat_id, None)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = ("📖 <b>YouTube Bot + Full Auto</b>\n\n"
            "<b>Perintah:</b>\n"
            "/start — Menu utama\n"
            "/download &lt;url&gt; — Download &amp; split video\n"
            "/settings — Konfigurasi bot\n"
            "/help — Panduan ini\n"
            "/cancel — Batalkan settings\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚙️ <b>Panduan /settings:</b>\n\n"
            "<b>1️⃣ Deskripsi</b> — Teks deskripsi TikTok\n"
            "   Kirim: <code>1</code> lalu kirim teks\n"
            '   Contoh: <code>Cek link di bio!</code>\n\n'
            "<b>2️⃣ Interval</b> — Jarak antar upload (menit)\n"
            "   Kirim: <code>2</code> lalu kirim angka\n"
            "   Contoh: <code>60</code>\n\n"
            "<b>3️⃣ Active User Data</b> — UD mana yang aktif\n"
            "   Kirim: <code>3</code> lalu kirim nomor UD\n"
            "   Contoh: <code>2,5,6</code>\n\n"
            "<b>4️⃣ Tambah Stok</b> — Tambah link YouTube ke UD\n"
            "   Kirim: <code>4 2</code> (untuk UD 2)\n"
            "   Lalu kirim link (1 per baris)\n\n"
            "<b>5️⃣ Lihat Stok</b> — Lihat stok link UD\n"
            "   Kirim: <code>5 2</code>\n\n"
            "<b>6️⃣ Edit Schedule</b> — Ubah jadwal upload UD\n"
            "   Kirim: <code>6 2</code>\n"
            "   Lalu kirim tanggal &amp; jam\n\n"
            "<b>7️⃣ Hapus Stok</b> — Hapus link dari stok UD\n"
            "   Kirim: <code>7 2</code>\n"
            "   Lalu kirim nomor link atau <code>all</code>\n\n"
            "<b>8️⃣ Hashtags</b> — Hashtag untuk TikTok\n"
            "   Kirim: <code>8</code> lalu kirim hashtag\n"
            "   Contoh: <code>fyp, viral, tiktok</code>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🤖 <b>Full Auto:</b>\n"
            "Bot download link dari stok per User Data → split 3 menit → upload TikTok\n"
            "• Hashtag otomatis ditambahkan saat upload\n"
            "• Schedule per User Data (default aktif: UD 2, 5, 6)\n"
            "• add_product=False, add_sound=False, skip_switches=True")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start","📋 Menu utama"),
        BotCommand("download","⬇️ Download & split video"),
        BotCommand("settings","⚙️ Konfigurasi"),
        BotCommand("help","📖 Panduan"),
        BotCommand("cancel","❌ Batalkan setting"),
    ])

def main():
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(FINAL_DIR, exist_ok=True)
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Command handlers (checked first)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("download", cmd_download))

    # Text message handler — routes to settings if in settings mode
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Callback query handler (inline buttons)
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🎬 YouTube Bot + Full Auto is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
