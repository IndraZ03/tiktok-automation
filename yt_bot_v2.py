"""
🎬 YouTube Downloader & Splitter + Full Auto TikTok Upload — Telegram Bot
"""
import os, sys, re, math, time, shutil, asyncio, subprocess, logging, json, copy, threading
from datetime import datetime, timedelta

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
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
#  DEFAULTS & STATE
# ═══════════════════════════════════════════════════════════════
_ss = load_schedule_state()
try:
    _def_dt = datetime.strptime(f"{_ss['tanggal']} {_ss['jam']}:{_ss['menit']}", "%Y-%m-%d %H:%M")
except: _def_dt = datetime.now()

DEFAULTS = {
    "save_mode": "local", "gdrive_folder_id": "",
    "deskripsi": "",
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

SETTING_MENU = 0

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
    links = load_stok_links()
    t = f"📦 <b>Stok Link YouTube</b>\n\nTotal: <b>{len(links)}</b> link\n"
    for i, l in enumerate(links[:10]):
        t += f"  {i+1}. <code>{l[:60]}</code>\n"
    if len(links) > 10: t += f"  ... +{len(links)-10} lainnya\n"
    return t

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    cfg = get_cfg(uid)
    ss = load_schedule_state()
    text = (f"🎬 <b>YouTube Bot + Full Auto Upload</b>\n\n"
            f"{stok_text()}\n"
            f"📅 Schedule terakhir: <code>{ss['tanggal']} {ss['jam']}:{ss['menit']}</code>\n"
            f"📝 Deskripsi: <code>{cfg['deskripsi'][:50] or '(kosong)'}</code>\n"
            f"⏱ Interval: <b>{cfg['interval']} menit</b>\n"
            f"🌐 Port: <b>{cfg['debug_port']}</b>")
    await update.message.reply_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)

# ═══════════════════════════════════════════════════════════════
#  SETTINGS CONVERSATION
# ═══════════════════════════════════════════════════════════════
async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return ConversationHandler.END
    cfg = get_cfg(update.effective_user.id)
    links = load_stok_links()
    text = ("⚙️ <b>Settings</b>\n\n"
            f"1️⃣ Tanggal: <code>{cfg['tanggal']}</code>\n"
            f"2️⃣ Jam: <code>{cfg['jam']}:{cfg['menit']}</code>\n"
            f"3️⃣ Deskripsi: <code>{cfg['deskripsi'][:60] or '(kosong)'}</code>\n"
            f"4️⃣ Stok Link: <b>{len(links)} link</b>\n"
            f"5️⃣ User Data Dir: <code>{cfg['user_data_dir']}</code>\n"
            f"6️⃣ Debug Port: <code>{cfg['debug_port']}</code>\n"
            f"7️⃣ Interval: <code>{cfg['interval']} menit</code>\n\n"
            "Kirim nomor (1-7) untuk ubah, atau /cancel")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Tutup", callback_data="close_settings")]])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return SETTING_MENU

async def settings_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cfg = get_cfg(uid)
    txt = update.message.text.strip()
    state = ctx.user_data.get("setting_field")
    if state:
        if state == "date":
            try:
                datetime.strptime(txt, "%Y-%m-%d"); cfg["tanggal"] = txt
            except: await update.message.reply_text("Format salah. YYYY-MM-DD"); return SETTING_MENU
        elif state == "time":
            parts = txt.replace(".",":").split(":")
            if len(parts)==2: cfg["jam"]=parts[0].zfill(2); cfg["menit"]=parts[1].zfill(2)
            else: await update.message.reply_text("Format salah. HH:MM"); return SETTING_MENU
        elif state == "desc": cfg["deskripsi"] = txt
        elif state == "stok":
            urls = [u.strip() for u in txt.split("\n") if u.strip()]
            links = load_stok_links()
            links.extend(urls)
            save_stok_links(links)
        elif state == "userdata": cfg["user_data_dir"] = txt
        elif state == "port": cfg["debug_port"] = txt
        elif state == "interval": cfg["interval"] = txt
        ctx.user_data["setting_field"] = None
        await update.message.reply_text("✅ Setting diperbarui!\nKirim nomor lain atau /cancel")
        return SETTING_MENU
    prompts = {
        "1": ("date","Kirim tanggal (YYYY-MM-DD):"),
        "2": ("time","Kirim jam (HH:MM):"),
        "3": ("desc","Kirim deskripsi TikTok:"),
        "4": ("stok","Kirim link YouTube (satu per baris, bisa banyak sekaligus):"),
        "5": ("userdata","Kirim path user data Chrome:"),
        "6": ("port","Kirim debug port:"),
        "7": ("interval","Kirim interval (menit):"),
    }
    if txt in prompts:
        field, prompt = prompts[txt]
        ctx.user_data["setting_field"] = field
        await update.message.reply_text(prompt)
        return SETTING_MENU
    await update.message.reply_text("Kirim angka 1-7, atau /cancel")
    return SETTING_MENU

async def cancel_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("setting_field", None)
    await update.message.reply_text("Settings ditutup.", reply_markup=main_menu_kb(update.effective_user.id))
    return ConversationHandler.END

async def close_settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer("Settings ditutup")
    await q.edit_message_text("⚙️ Settings ditutup.")
    ctx.user_data.pop("setting_field", None)
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════════
#  FULL AUTO UPLOAD (download from stok → split → upload TikTok)
# ═══════════════════════════════════════════════════════════════
def _full_auto_single_upload(cfg, log_fn, stop_evt):
    """Download 1 link from stok, split, upload all parts to TikTok."""
    links = load_stok_links()
    if not links:
        log_fn("❌ Stok link kosong!", "error"); return False

    url = links[0]
    log_fn(f"📥 Downloading: {url[:60]}...", "info")

    job_temp = os.path.join(TEMP_DIR, f"auto_{int(time.time())}")
    job_out = os.path.join(TEMP_DIR, f"auto_{int(time.time())}_out")

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

        # Read schedule from state file
        ss = load_schedule_state()
        hour = int(ss["jam"]); minute = int(ss["menit"])
        date_str = ss["tanggal"]
        interval = int(cfg.get("interval", "60"))
        deskripsi = cfg.get("deskripsi", "")
        userdata = cfg.get("user_data_dir", "")
        port = cfg.get("debug_port", "9222")

        start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
        log_fn(f"📅 Schedule mulai: {start_dt.strftime('%Y-%m-%d %H:%M')}", "info")
        log_fn(f"🌐 Membuka Chrome (port {port})...", "info")

        chrome_proc = open_chrome_debug(userdata, port)
        driver = connect_selenium(port)
        log_fn("✓ Chrome terhubung!", "success")
        uploaded = 0

        try:
            for idx, out_path in enumerate(output_files):
                if stop_evt.is_set(): break
                if not os.path.exists(out_path): continue
                sched_dt = start_dt + timedelta(minutes=interval * idx)
                log_fn(f"[{idx+1}/{len(output_files)}] Upload: {os.path.basename(out_path)}", "info")
                log_fn(f"  Schedule: {sched_dt.strftime('%Y-%m-%d %H:%M')}", "info")
                try:
                    navigate_upload_page(driver, force=(idx > 0))
                    time.sleep(3)
                    do_upload_file(driver, os.path.normpath(out_path), log_fn)
                    time.sleep(5)
                    do_post_video(driver, deskripsi, "", "", log_fn, sched_dt, stop_evt,
                                 add_sound=False, add_product=False, skip_switches=True)
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
            save_schedule_state(next_dt.strftime("%Y-%m-%d"), f"{next_dt.hour:02d}", f"{next_dt.minute:02d}")
            log_fn(f"💾 Next schedule: {next_dt.strftime('%Y-%m-%d %H:%M')}", "success")
            # Remove used link from stok
            remove_stok_link(url)
            log_fn(f"🗑 Link dihapus dari stok", "success")

        log_fn(f"🎉 Selesai! {uploaded}/{len(output_files)} parts uploaded", "success")
        return True

    except Exception as e:
        log_fn(f"❌ Error: {e}", "error")
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

    if data == "refresh":
        ss = load_schedule_state(); cfg = get_cfg(uid)
        text = (f"🎬 <b>YouTube Bot + Full Auto Upload</b>\n\n{stok_text()}\n"
                f"📅 Schedule: <code>{ss['tanggal']} {ss['jam']}:{ss['menit']}</code>\n"
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
            _send("🤖 <b>Full Auto dimulai!</b>\nBot akan download dari stok → split → upload TikTok.")
            while not stop_auto.is_set():
                links = load_stok_links()
                if not links:
                    _send("📦 Stok link kosong. Menunggu 60 detik...")
                    for _ in range(12):
                        if stop_auto.is_set(): break
                        time.sleep(5)
                    continue

                state = load_schedule_state()
                try:
                    trigger_dt = datetime.strptime(
                        f"{state['tanggal']} {state['jam']}:{state['menit']}", "%Y-%m-%d %H:%M"
                    ) + timedelta(minutes=1)
                except:
                    _send("❌ Format schedule_state error!"); break

                now = datetime.now()
                wait_sec = (trigger_dt - now).total_seconds()
                if wait_sec > 0:
                    _send(f"⏳ <b>Full Auto</b>: menunggu <code>{trigger_dt.strftime('%Y-%m-%d %H:%M')}</code> "
                          f"({int(wait_sec//60)} menit lagi)...")
                    elapsed = 0
                    while elapsed < wait_sec and not stop_auto.is_set():
                        time.sleep(min(30, wait_sec - elapsed)); elapsed += 30
                    if stop_auto.is_set(): break

                _send("🚀 <b>Full Auto</b>: memulai download & upload...")
                lock = get_lock(uid)
                if not lock.acquire(blocking=True, timeout=60):
                    _send("⚠️ Gagal acquire lock, coba lagi..."); time.sleep(60); continue

                log_buffers[uid] = []
                log_fn = make_log_fn(uid)
                cfg = get_cfg(uid)
                inner_stop = threading.Event()
                try:
                    _full_auto_single_upload(cfg, log_fn, inner_stop)
                except Exception as e:
                    _send(f"❌ Error: {e}")
                finally:
                    lock.release()

                lines = log_buffers.get(uid, [])
                summary = "\n".join(lines[-8:])
                _send(f"🎉 <b>Full Auto: selesai!</b>\n\n{summary}\n\n{stok_text()}")
                if stop_auto.is_set(): break
                time.sleep(10)

            full_auto_tasks.pop(uid, None)
            _send("⏹ <b>Full Auto dihentikan.</b>")

        t = threading.Thread(target=_daemon, daemon=True, name=f"yt_full_auto_{uid}")
        full_auto_tasks[uid] = {"stop": stop_auto, "thread": t}
        t.start()
        await q.edit_message_text(
            "🤖 <b>Full Auto aktif!</b>\nBot akan otomatis download stok link → split → upload ke TikTok.\n\nTekan <b>Stop Full Auto</b> untuk menghentikan.",
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
            "/download &lt;url&gt; — Download & split video\n"
            "/settings — Konfigurasi (waktu, deskripsi, stok link, port)\n"
            "/help — Panduan\n\n"
            "<b>Full Auto:</b>\n"
            "Bot download link dari stok → split 3 menit → upload TikTok\n"
            "Schedule berdasarkan tanggal terakhir (schedule_state)\n"
            "add_product=False, add_sound=False, skip_switches=True")
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
    settings_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", cmd_settings)],
        states={SETTING_MENU: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, settings_input),
            CallbackQueryHandler(close_settings_cb, pattern="^close_settings$"),
        ]},
        fallbacks=[CommandHandler("cancel", cancel_settings),
                   CommandHandler("settings", cmd_settings),
                   CallbackQueryHandler(close_settings_cb, pattern="^close_settings$")],
        allow_reentry=True,
    )
    app.add_handler(settings_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("download", cmd_download))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("🎬 YouTube Bot + Full Auto is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
