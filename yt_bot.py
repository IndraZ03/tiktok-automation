"""
🎬 YouTube Downloader & Splitter — Telegram Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fitur:
  • /download <link_yt> — Download video YT kualitas tertinggi
  • Split video menjadi part 3 menit (tepat, potong di akhir)
  • Watermark logo.png di kiri atas (ukuran persentase, cocok 9:16 TikTok)
  • Text overlay judul + part di tengah bawah
  • Progress realtime di Telegram (edit message)
  • Output ke folder video_yt (default) atau Google Drive
  • Bisa dipakai di grup

Dependensi:
  pip install python-telegram-bot yt-dlp
  pip install pydrive2  (opsional, untuk Google Drive)
  ffmpeg & ffprobe harus ada di PATH
"""

import os
import sys
import re
import math
import time
import shutil
import asyncio
import subprocess
import logging
from datetime import datetime

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)
from telegram.constants import ParseMode

# ── Try pydrive2 (Google Drive upload) ───────────────────────────────────────
try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    GDRIVE_OK = True
except ImportError:
    GDRIVE_OK = False

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8577651733:AAG69uuoImXQpe5qcEtMdlwgu3_6rQAvaBI" 
ALLOWED_USER_IDS = []  # Kosong = semua user boleh

APP_DIR = r"C:\tiktok_automation"
LOGO_PATH = os.path.join(APP_DIR, "logo.png")
TEMP_DIR = os.path.join(APP_DIR, "yt_temp")
FINAL_DIR = os.path.join(APP_DIR, "video_yt")   # folder output final

# GDrive paths (reuse existing credentials from grok_gui)
GDRIVE_SETTINGS_YAML = os.path.join(APP_DIR, "gdrive_settings.yaml")
GDRIVE_CREDS_FILE    = os.path.join(APP_DIR, "gdrive_credentials.json")

SEGMENT_DURATION = 180  # 3 menit dalam detik

# Watermark sizing — persentase dari lebar video (misal 12% = cocok untuk 9:16 TikTok)
WATERMARK_WIDTH_PCT = 12   # persen dari lebar video
WATERMARK_MARGIN_PCT = 2   # persen margin dari tepi

# Text overlay style
TEXT_FONT = "Arial"
TEXT_SIZE_PCT = 3.5   # persen dari tinggi video
TEXT_COLOR = "white"
TEXT_BORDER_COLOR = "black"
TEXT_BORDER_W = 3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  PER-USER SETTINGS
# ═══════════════════════════════════════════════════════════════
# save_mode: "local" (default) atau "gdrive"
user_settings = {}  # uid -> {"save_mode": str, "gdrive_folder_id": str}

def get_user_cfg(uid):
    if uid not in user_settings:
        user_settings[uid] = {
            "save_mode": "local",         # "local" atau "gdrive"
            "gdrive_folder_id": "",       # GDrive folder ID
        }
    return user_settings[uid]


# ═══════════════════════════════════════════════════════════════
#  GDRIVE HELPER
# ═══════════════════════════════════════════════════════════════
_gdrive_instance = None

def get_gdrive():
    """Return an authenticated GoogleDrive instance (cached)."""
    global _gdrive_instance
    if not GDRIVE_OK:
        return None
    if _gdrive_instance:
        return _gdrive_instance
    try:
        gauth = GoogleAuth(settings_file=GDRIVE_SETTINGS_YAML)
        gauth.LoadCredentialsFile(GDRIVE_CREDS_FILE)
        if gauth.credentials is None:
            logger.error("GDrive: Credentials belum ada")
            return None
        if gauth.access_token_expired:
            gauth.Refresh()
            gauth.SaveCredentialsFile(GDRIVE_CREDS_FILE)
        drive = GoogleDrive(gauth)
        _gdrive_instance = drive
        return drive
    except Exception as e:
        logger.error(f"GDrive auth error: {e}")
        return None


def upload_to_gdrive(local_path, filename, folder_id):
    """Upload a local file to GDrive folder. Returns True/False."""
    drive = get_gdrive()
    if not drive:
        return False
    try:
        meta = {'title': filename}
        if folder_id:
            meta['parents'] = [{'id': folder_id}]
        f = drive.CreateFile(meta)
        f.SetContentFile(local_path)
        f.Upload()
        return True
    except Exception as e:
        logger.error(f"GDrive upload gagal: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def is_allowed(uid):
    return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS


def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_duration(seconds):
    """Format seconds ke MM:SS atau HH:MM:SS."""
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def format_size(bytes_size):
    """Format bytes ke human readable."""
    if bytes_size >= 1024 * 1024 * 1024:
        return f"{bytes_size / (1024**3):.1f}GB"
    if bytes_size >= 1024 * 1024:
        return f"{bytes_size / (1024**2):.1f}MB"
    if bytes_size >= 1024:
        return f"{bytes_size / 1024:.1f}KB"
    return f"{bytes_size}B"


def get_video_duration(filepath):
    """Dapatkan durasi video dalam detik menggunakan ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath
            ],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception:
        return 0


def get_video_info(filepath):
    """Dapatkan info resolusi video."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x",
                filepath
            ],
            capture_output=True, text=True, timeout=30
        )
        w, h = result.stdout.strip().split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1920  # default TikTok


def sanitize_filename(title):
    """Bersihkan judul untuk nama file."""
    title = re.sub(r'[<>:"/\\|?*]', '', title)
    title = title.strip()
    if len(title) > 80:
        title = title[:80]
    return title


def truncate_title(title, max_len=40):
    """Potong judul untuk overlay text."""
    if len(title) > max_len:
        return title[:max_len - 3] + "..."
    return title


# ═══════════════════════════════════════════════════════════════
#  PROGRESS BAR
# ═══════════════════════════════════════════════════════════════
def progress_bar(pct, width=20):
    """Unicode progress bar."""
    pct = max(0, min(100, pct))
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def build_progress_message(title, stages):
    """
    Build a structured progress message.
    stages = list of {"name": str, "status": str, "pct": int, "detail": str}
    status: "pending", "running", "done", "error"
    """
    STATUS_ICONS = {
        "pending": "⏳",
        "running": "🔄",
        "done": "✅",
        "error": "❌",
        "sending": "📤",
    }
    
    lines = [f"🎬 <b>{escape_html(title)}</b>\n"]
    
    for s in stages:
        icon = STATUS_ICONS.get(s["status"], "⏳")
        name = s["name"]
        pct = s.get("pct", 0)
        detail = s.get("detail", "")
        
        if s["status"] == "running":
            bar = progress_bar(pct)
            lines.append(f"{icon} <b>{name}</b>  {bar} {pct}%")
            if detail:
                lines.append(f"    <i>{escape_html(detail)}</i>")
        elif s["status"] == "done":
            lines.append(f"{icon} <b>{name}</b> — Selesai")
            if detail:
                lines.append(f"    <i>{escape_html(detail)}</i>")
        elif s["status"] == "error":
            lines.append(f"{icon} <b>{name}</b> — Error")
            if detail:
                lines.append(f"    <i>{escape_html(detail)}</i>")
        else:
            lines.append(f"{icon} {name}")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  CORE: DOWNLOAD
# ═══════════════════════════════════════════════════════════════
async def download_video(url, temp_dir, progress_callback=None):
    """
    Download video YT menggunakan yt-dlp dengan kualitas tertinggi.
    Returns (filepath, title) atau raises Exception.
    """
    os.makedirs(temp_dir, exist_ok=True)
    
    output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")
    
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--newline",          # progress per line
        "--no-color",
        "--print", "after_move:filepath",  # print final path
        url
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    
    filepath = None
    last_progress = 0
    
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        line = line.decode("utf-8", errors="replace").strip()
        
        # Parse progress: [download]  45.2% of ~150.00MiB ...
        pct_match = re.search(r'\[download\]\s+([\d.]+)%', line)
        if pct_match:
            pct = float(pct_match.group(1))
            if progress_callback and pct - last_progress >= 2:
                # Extract speed and ETA
                speed_match = re.search(r'at\s+([\d.]+\w+/s)', line)
                eta_match = re.search(r'ETA\s+(\S+)', line)
                detail = f"{pct:.0f}%"
                if speed_match:
                    detail += f" • {speed_match.group(1)}"
                if eta_match:
                    detail += f" • ETA {eta_match.group(1)}"
                await progress_callback(int(pct), detail)
                last_progress = pct
        
        # The --print after_move:filepath prints the final path as the LAST output line
        if line and not line.startswith("[") and not line.startswith("Deleting") and os.path.isfile(line):
            filepath = line
    
    await proc.wait()
    
    if proc.returncode != 0:
        raise Exception(f"yt-dlp gagal (exit code {proc.returncode})")
    
    # If filepath not captured via --print, find it
    if not filepath:
        mp4_files = [
            os.path.join(temp_dir, f)
            for f in os.listdir(temp_dir) if f.endswith(".mp4")
        ]
        if mp4_files:
            filepath = max(mp4_files, key=os.path.getmtime)
        else:
            raise Exception("Tidak ada file video yang dihasilkan")
    
    # Extract title from filename
    title = os.path.splitext(os.path.basename(filepath))[0]
    
    return filepath, title


# ═══════════════════════════════════════════════════════════════
#  CORE: SPLIT + WATERMARK + TEXT OVERLAY (single FFmpeg pass)
# ═══════════════════════════════════════════════════════════════
def build_ffmpeg_split_cmd(input_file, output_file, start_sec, duration,
                           title_text, part_num, total_parts, logo_path,
                           video_width):
    """
    Build FFmpeg command untuk satu segment:
    - Potong dari start_sec selama duration detik
    - Overlay logo.png di kiri atas (ukuran proporsional)
    - Text overlay "{title} - Part X/Y" di tengah bawah
    """
    # Overlay text content
    overlay_text = f"{title_text} - Part {part_num}/{total_parts}"
    # Escape FFmpeg special characters in text
    overlay_text = overlay_text.replace("'", "'\\''")
    overlay_text = overlay_text.replace(":", "\\:")
    overlay_text = overlay_text.replace("%", "%%")
    
    # Calculate watermark pixel width from video width percentage
    wm_width = max(32, int(video_width * WATERMARK_WIDTH_PCT / 100))
    margin_x = max(4, int(video_width * WATERMARK_MARGIN_PCT / 100))
    
    # Build complex filter:
    # 1. Scale logo to fixed pixel width (derived from percentage), preserve AR
    # 2. Overlay logo at top-left with margin
    # 3. Draw text at bottom center
    filter_complex = (
        # Scale logo to calculated width, keep aspect ratio
        f"[1:v]scale={wm_width}:-1[wm];"
        # Overlay logo at top-left with margin
        f"[0:v][wm]overlay={margin_x}:{margin_x}[vid];"
        # Draw text at bottom center
        f"[vid]drawtext="
        f"text='{overlay_text}':"
        f"font='{TEXT_FONT}':"
        f"fontsize=h*{TEXT_SIZE_PCT}/100:"
        f"fontcolor={TEXT_COLOR}:"
        f"borderw={TEXT_BORDER_W}:"
        f"bordercolor={TEXT_BORDER_COLOR}:"
        f"x=(w-text_w)/2:"
        f"y=h-text_h-h*{WATERMARK_MARGIN_PCT*2}/100"
        f"[out]"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-t", str(duration),
        "-i", input_file,
        "-i", logo_path,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        output_file
    ]
    
    return cmd


async def split_and_process(input_file, output_dir, title, logo_path,
                            progress_callback=None):
    """
    Split video menjadi segment 3 menit, masing-masing dengan watermark + text.
    Returns list of output file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    duration = get_video_duration(input_file)
    if duration <= 0:
        raise Exception("Tidak bisa baca durasi video")
    
    # Hitung jumlah segment (tepat 3 menit, potong yang terakhir)
    total_parts = int(duration // SEGMENT_DURATION)
    if total_parts == 0:
        total_parts = 1  # Video kurang dari 3 menit, tetap proses 1 part
    
    safe_title = sanitize_filename(title)
    display_title = truncate_title(title)
    output_files = []
    
    # Get video width for watermark sizing
    vid_w, vid_h = get_video_info(input_file)
    
    for part in range(1, total_parts + 1):
        start_sec = (part - 1) * SEGMENT_DURATION
        
        # Untuk part terakhir, tetap paksa durasi 3 menit (potong tepat)
        seg_duration = SEGMENT_DURATION
        
        output_file = os.path.join(output_dir, f"{safe_title}_Part{part}.mp4")
        
        if progress_callback:
            await progress_callback(
                part, total_parts,
                int((part - 1) / total_parts * 100),
                f"Processing Part {part}/{total_parts}..."
            )
        
        cmd = build_ffmpeg_split_cmd(
            input_file, output_file,
            start_sec, seg_duration,
            display_title, part, total_parts,
            logo_path, vid_w
        )
        
        # Run FFmpeg
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")[-500:]
            logger.error(f"FFmpeg error part {part}: {error_msg}")
            # Skip this part but continue
            if progress_callback:
                await progress_callback(
                    part, total_parts,
                    int(part / total_parts * 100),
                    f"⚠️ Part {part} gagal, skip..."
                )
            continue
        
        if os.path.exists(output_file) and os.path.getsize(output_file) > 10240:
            output_files.append(output_file)
        
        if progress_callback:
            await progress_callback(
                part, total_parts,
                int(part / total_parts * 100),
                f"Part {part}/{total_parts} ✅ selesai"
            )
    
    return output_files


# ═══════════════════════════════════════════════════════════════
#  TELEGRAM: /download HANDLER
# ═══════════════════════════════════════════════════════════════

# Track active tasks to prevent overlap
active_tasks = {}  # chat_id -> True


async def cmd_download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /download <youtube_url>"""
    uid = update.effective_user.id
    chat_id = update.message.chat_id
    
    if not is_allowed(uid):
        await update.message.reply_text("❌ Kamu tidak diizinkan menggunakan bot ini.")
        return
    
    # Parse URL from command
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "❌ <b>Format salah!</b>\n\n"
            "Gunakan: <code>/download &lt;link_youtube&gt;</code>\n"
            "Contoh: <code>/download https://youtu.be/abc123</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    url = args[0]
    
    # Validate YouTube URL
    yt_pattern = re.compile(
        r'(https?://)?(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/|m\.youtube\.com/watch\?v=)'
    )
    if not yt_pattern.search(url):
        await update.message.reply_text(
            "❌ <b>URL tidak valid!</b>\n"
            "Pastikan URL adalah link YouTube yang benar.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Prevent concurrent downloads per chat
    if active_tasks.get(chat_id):
        await update.message.reply_text(
            "⏳ <b>Ada proses yang masih berjalan.</b>\n"
            "Tunggu sampai selesai sebelum download baru.",
            parse_mode=ParseMode.HTML
        )
        return
    
    active_tasks[chat_id] = True
    
    # Create temp directory for this job
    job_id = f"{chat_id}_{int(time.time())}"
    job_temp = os.path.join(TEMP_DIR, job_id)
    job_temp_output = os.path.join(TEMP_DIR, f"{job_id}_out")
    
    # User save mode
    ucfg = get_user_cfg(uid)
    save_mode = ucfg["save_mode"]  # "local" or "gdrive"
    
    if save_mode == "gdrive":
        save_label = "☁ Upload ke Google Drive"
    else:
        save_label = "💾 Simpan ke folder"
    
    # Initialize progress message
    stages = [
        {"name": "📥 Download Video", "status": "running", "pct": 0, "detail": "Memulai download..."},
        {"name": "✂️ Split & Process", "status": "pending", "pct": 0, "detail": ""},
        {"name": save_label, "status": "pending", "pct": 0, "detail": ""},
    ]
    
    progress_msg = await update.message.reply_text(
        build_progress_message("Memproses...", stages),
        parse_mode=ParseMode.HTML
    )
    
    last_edit_time = [time.time()]  # mutable for closure
    MIN_EDIT_INTERVAL = 2.0  # minimum detik antar edit agar tidak rate-limited
    
    async def safe_edit(text):
        """Edit message dengan rate limiting."""
        now = time.time()
        if now - last_edit_time[0] < MIN_EDIT_INTERVAL:
            return
        try:
            await progress_msg.edit_text(text, parse_mode=ParseMode.HTML)
            last_edit_time[0] = now
        except Exception:
            pass
    
    try:
        # ═══════════ STAGE 1: DOWNLOAD ═══════════
        async def dl_progress(pct, detail):
            stages[0]["pct"] = pct
            stages[0]["detail"] = detail
            await safe_edit(build_progress_message("Memproses...", stages))
        
        filepath, title = await download_video(url, job_temp, dl_progress)
        
        file_size = os.path.getsize(filepath)
        duration = get_video_duration(filepath)
        
        stages[0]["status"] = "done"
        stages[0]["detail"] = (
            f"{format_size(file_size)} • {format_duration(duration)}"
        )
        
        # Check if logo exists
        if not os.path.exists(LOGO_PATH):
            stages[0]["detail"] += " ⚠️ logo.png tidak ditemukan, skip watermark"
            use_logo = False
        else:
            use_logo = True
        
        await safe_edit(build_progress_message(title, stages))
        
        # ═══════════ STAGE 2: SPLIT & PROCESS ═══════════
        total_parts = max(1, int(duration // SEGMENT_DURATION))
        
        stages[1]["status"] = "running"
        stages[1]["pct"] = 0
        stages[1]["detail"] = f"0/{total_parts} parts • Durasi: {format_duration(duration)}"
        await safe_edit(build_progress_message(title, stages))
        
        async def split_progress(current_part, total, pct, detail):
            stages[1]["pct"] = pct
            stages[1]["detail"] = f"{current_part}/{total} parts • {detail}"
            await safe_edit(build_progress_message(title, stages))
        
        logo_to_use = LOGO_PATH if use_logo else None
        
        # Jika logo tidak ada, buat proses tanpa watermark
        if not use_logo:
            output_files = await split_no_watermark(
                filepath, job_temp_output, title, split_progress
            )
        else:
            output_files = await split_and_process(
                filepath, job_temp_output, title, logo_to_use, split_progress
            )
        
        if not output_files:
            stages[1]["status"] = "error"
            stages[1]["detail"] = "Tidak ada part yang berhasil diproses"
            await safe_edit(build_progress_message(title, stages))
            raise Exception("Tidak ada video yang berhasil diproses")
        
        stages[1]["status"] = "done"
        stages[1]["detail"] = f"{len(output_files)} parts selesai"
        await safe_edit(build_progress_message(title, stages))
        
        # ═══════════ STAGE 3: SAVE / UPLOAD ═══════════
        stages[2]["status"] = "running"
        stages[2]["pct"] = 0
        stages[2]["detail"] = f"0/{len(output_files)} file"
        await safe_edit(build_progress_message(title, stages))
        
        saved_count = 0
        safe_title = sanitize_filename(title)
        
        if save_mode == "gdrive":
            # ── Upload ke Google Drive ──
            folder_id = ucfg.get("gdrive_folder_id", "")
            if not GDRIVE_OK:
                stages[2]["status"] = "error"
                stages[2]["detail"] = "pydrive2 tidak terinstall! pip install pydrive2"
                await safe_edit(build_progress_message(title, stages))
                raise Exception("pydrive2 tidak terinstall")
            
            for i, out_file in enumerate(output_files):
                part_num = i + 1
                fname = os.path.basename(out_file)
                ok = upload_to_gdrive(out_file, fname, folder_id)
                if ok:
                    saved_count += 1
                    logger.info(f"GDrive upload OK: {fname}")
                else:
                    logger.error(f"GDrive upload FAIL: {fname}")
                
                stages[2]["pct"] = int(part_num / len(output_files) * 100)
                stages[2]["detail"] = f"{saved_count}/{len(output_files)} uploaded"
                last_edit_time[0] = 0
                await safe_edit(build_progress_message(title, stages))
            
            save_location = f"Google Drive (folder: {folder_id[:20]}...)" if folder_id else "Google Drive (root)"
        
        else:
            # ── Simpan ke folder lokal video_yt/<judul> ──
            video_folder = os.path.join(FINAL_DIR, safe_title)
            os.makedirs(video_folder, exist_ok=True)
            
            for i, out_file in enumerate(output_files):
                part_num = i + 1
                fname = os.path.basename(out_file)
                dest = os.path.join(video_folder, fname)
                try:
                    shutil.move(out_file, dest)
                    saved_count += 1
                except Exception as e:
                    logger.error(f"Move error {fname}: {e}")
                
                stages[2]["pct"] = int(part_num / len(output_files) * 100)
                stages[2]["detail"] = f"{saved_count}/{len(output_files)} tersimpan"
                last_edit_time[0] = 0
                await safe_edit(build_progress_message(title, stages))
            
            save_location = video_folder
        
        stages[2]["status"] = "done"
        stages[2]["detail"] = f"{saved_count}/{len(output_files)} ✅"
        
        # Final summary
        summary = (
            f"\n\n{'━' * 28}\n"
            f"✅ <b>SELESAI!</b>\n"
            f"📹 {escape_html(truncate_title(title, 50))}\n"
            f"📌 {saved_count} part tersimpan\n"
            f"⏱ Durasi asli: {format_duration(duration)}\n"
            f"📂 <code>{escape_html(str(save_location))}</code>"
        )
        
        final_text = build_progress_message(title, stages) + summary
        try:
            await progress_msg.edit_text(final_text[:4096], parse_mode=ParseMode.HTML)
        except Exception:
            pass
    
    except Exception as e:
        logger.error(f"Download error: {e}")
        try:
            error_text = (
                f"❌ <b>Error!</b>\n\n"
                f"<code>{escape_html(str(e)[:500])}</code>\n\n"
                f"URL: <code>{escape_html(url)}</code>"
            )
            await progress_msg.edit_text(error_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    
    finally:
        # Cleanup temp files only (NOT the final output folder)
        for d in [job_temp, job_temp_output]:
            try:
                if os.path.exists(d):
                    shutil.rmtree(d)
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
        
        active_tasks.pop(chat_id, None)


async def split_no_watermark(input_file, output_dir, title, progress_callback=None):
    """Split tanpa watermark (fallback jika logo.png tidak ada)."""
    os.makedirs(output_dir, exist_ok=True)
    
    duration = get_video_duration(input_file)
    if duration <= 0:
        raise Exception("Tidak bisa baca durasi video")
    
    total_parts = max(1, int(duration // SEGMENT_DURATION))
    safe_title = sanitize_filename(title)
    display_title = truncate_title(title)
    output_files = []
    
    for part in range(1, total_parts + 1):
        start_sec = (part - 1) * SEGMENT_DURATION
        seg_duration = SEGMENT_DURATION
        
        output_file = os.path.join(output_dir, f"{safe_title}_Part{part}.mp4")
        
        if progress_callback:
            await progress_callback(
                part, total_parts,
                int((part - 1) / total_parts * 100),
                f"Processing Part {part}/{total_parts}..."
            )
        
        # Text overlay tanpa logo
        overlay_text = f"{display_title} - Part {part}/{total_parts}"
        overlay_text = overlay_text.replace("'", "'\\''")
        overlay_text = overlay_text.replace(":", "\\:")
        overlay_text = overlay_text.replace("%", "%%")
        
        filter_str = (
            f"drawtext="
            f"text='{overlay_text}':"
            f"font='{TEXT_FONT}':"
            f"fontsize=h*{TEXT_SIZE_PCT}/100:"
            f"fontcolor={TEXT_COLOR}:"
            f"borderw={TEXT_BORDER_W}:"
            f"bordercolor={TEXT_BORDER_COLOR}:"
            f"x=(w-text_w)/2:"
            f"y=h-text_h-h*{WATERMARK_MARGIN_PCT*2}/100"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-t", str(seg_duration),
            "-i", input_file,
            "-vf", filter_str,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_file
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")[-500:]
            logger.error(f"FFmpeg error part {part}: {error_msg}")
            continue
        
        if os.path.exists(output_file) and os.path.getsize(output_file) > 10240:
            output_files.append(output_file)
        
        if progress_callback:
            await progress_callback(
                part, total_parts,
                int(part / total_parts * 100),
                f"Part {part}/{total_parts} ✅ selesai"
            )
    
    return output_files


# ═══════════════════════════════════════════════════════════════
#  TELEGRAM: /mode, /setfolder, /start, /help
# ═══════════════════════════════════════════════════════════════
async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Toggle save mode: local <-> gdrive."""
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    ucfg = get_user_cfg(uid)
    
    args = ctx.args
    if args and args[0].lower() in ("local", "gdrive"):
        ucfg["save_mode"] = args[0].lower()
    else:
        # Toggle
        ucfg["save_mode"] = "gdrive" if ucfg["save_mode"] == "local" else "local"
    
    mode = ucfg["save_mode"]
    if mode == "local":
        text = (
            f"💾 <b>Mode: Simpan Lokal</b>\n\n"
            f"Video akan disimpan ke:\n"
            f"<code>{FINAL_DIR}/&lt;judul video&gt;/</code>\n\n"
            f"Ketik <code>/mode gdrive</code> untuk switch ke Google Drive."
        )
    else:
        folder_id = ucfg.get('gdrive_folder_id', '')
        text = (
            f"☁ <b>Mode: Google Drive</b>\n\n"
            f"Video akan diupload ke Google Drive.\n"
            f"Folder ID: <code>{folder_id if folder_id else '(root / belum diset)'}</code>\n\n"
            f"Gunakan <code>/setfolder &lt;folder_id&gt;</code> untuk set folder tujuan.\n"
            f"Ketik <code>/mode local</code> untuk switch ke lokal."
        )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_setfolder(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Set Google Drive folder ID."""
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    ucfg = get_user_cfg(uid)
    
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "❌ <b>Format:</b> <code>/setfolder &lt;folder_id_atau_url&gt;</code>\n\n"
            "Contoh:\n"
            "<code>/setfolder 1A2B3C4D5E6F</code>\n"
            "<code>/setfolder https://drive.google.com/drive/folders/1A2B3C4D5E6F</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    raw = args[0]
    # Extract folder ID from URL if needed
    m = re.search(r'folders/([a-zA-Z0-9_-]+)', raw)
    folder_id = m.group(1) if m else raw
    
    ucfg["gdrive_folder_id"] = folder_id
    ucfg["save_mode"] = "gdrive"  # auto switch to gdrive mode
    
    await update.message.reply_text(
        f"✅ <b>GDrive folder ID diset!</b>\n\n"
        f"Folder ID: <code>{folder_id}</code>\n"
        f"Mode: ☁ Google Drive",
        parse_mode=ParseMode.HTML
    )


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ucfg = get_user_cfg(uid)
    mode_str = "💾 Lokal" if ucfg["save_mode"] == "local" else "☁ Google Drive"
    
    text = (
        "🎬 <b>YouTube Downloader & Splitter Bot</b>\n\n"
        "Bot ini mengunduh video YouTube kualitas tertinggi, "
        "memotongnya menjadi part 3 menit, menambahkan watermark logo "
        "dan text overlay judul + part number.\n\n"
        "<b>📌 Cara Pakai:</b>\n"
        "<code>/download &lt;link_youtube&gt;</code>\n\n"
        "<b>Contoh:</b>\n"
        "<code>/download https://youtu.be/dQw4w9WgXcQ</code>\n\n"
        "<b>Fitur:</b>\n"
        "• ⬇️ Download kualitas tertinggi\n"
        "• ✂️ Auto split 3 menit per part\n"
        "• 🖼 Watermark logo di kiri atas\n"
        "• 📝 Text overlay judul + part di bawah tengah\n"
        "• 📊 Progress realtime\n"
        f"• � Output: {mode_str}\n\n"
        "<b>Mode Output:</b>\n"
        "/mode — Toggle local/gdrive\n"
        "/setfolder — Set GDrive folder ID\n\n"
        f"📂 Output lokal: <code>{FINAL_DIR}</code>\n"
        f"⏱ Durasi per part: <b>{SEGMENT_DURATION // 60} menit</b>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>Panduan YouTube Bot</b>\n\n"
        "<b>Perintah:</b>\n"
        "/start — Info bot\n"
        "/download &lt;url&gt; — Download & proses video\n"
        "/mode — Toggle mode output (local/gdrive)\n"
        "/mode local — Set mode ke lokal\n"
        "/mode gdrive — Set mode ke Google Drive\n"
        "/setfolder &lt;id&gt; — Set GDrive folder tujuan\n"
        "/help — Panduan ini\n\n"
        "<b>Output:</b>\n"
        f"• 💾 Lokal: <code>{FINAL_DIR}/&lt;judul&gt;/</code>\n"
        "• ☁ GDrive: upload ke folder yang diset\n\n"
        "<b>Catatan:</b>\n"
        "• Video dipotong tepat 3 menit per part\n"
        "• Sisa durasi < 3 menit di akhir tidak diikutkan\n"
        "• Watermark logo.png otomatis di kiri atas\n"
        "• Ukuran watermark proporsional (cocok semua resolusi)\n"
        "• Text overlay judul + part number di bawah tengah\n"
        "• Bisa dipakai di grup dan private chat\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
async def post_init(application):
    """Register menu commands visible in Telegram UI."""
    await application.bot.set_my_commands([
        BotCommand("start", "🎬 Info bot"),
        BotCommand("download", "⬇️ Download & split video YouTube"),
        BotCommand("mode", "💾 Toggle mode output (local/gdrive)"),
        BotCommand("setfolder", "☁ Set GDrive folder ID"),
        BotCommand("help", "📖 Panduan"),
    ])


def main():
    # Ensure dirs exist
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(FINAL_DIR, exist_ok=True)
    
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("download", cmd_download))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("setfolder", cmd_setfolder))
    
    print("🎬 YouTube Downloader Bot is running...")
    print(f"📂 Logo: {LOGO_PATH}")
    print(f"📂 Temp: {TEMP_DIR}")
    print(f"📂 Output: {FINAL_DIR}")
    app.run_polling()


if __name__ == "__main__":
    main()
