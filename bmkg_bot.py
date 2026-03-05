"""
🌦️ BMKG Weather Alert → Grok Video → TikTok Auto-Upload — Telegram Bot
Fetches BMKG weather alerts, generates video via Grok (vidabot), adds text overlay, uploads to TikTok.

Features:
  - Manual: /generate or button "🚀 Manual Generate"
  - Full Auto: Daemon that runs the full pipeline every 2 hours automatically
"""
import os, sys, re, time, shutil, asyncio, subprocess, logging, json, threading, textwrap
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

# ── Selenium imports ──
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
BOT_TOKEN = "7821951521:AAEUSgUhjYK4V8mptCCuqPyaCptST_pxMyU"
ALLOWED_USER_IDS = []   # kosong = semua user diperbolehkan

APP_DIR         = r"C:\tiktok_automation"
PROMPT_FILE     = os.path.join(APP_DIR, "prompt.md")
PROMPT_IMAGE_DIR= os.path.join(APP_DIR, "bahan_forecast")
OUTPUT_DIR      = os.path.join(APP_DIR, "bmkg_output")
OVERLAY_DIR     = os.path.join(APP_DIR, "bmkg_overlay")
WATERMARK_PATH  = os.path.join(APP_DIR, "speedu.png")
SETTINGS_FILE   = os.path.join(APP_DIR, "bmkg_settings.json")

BMKG_RSS_URL    = "https://www.bmkg.go.id/alerts/nowcast/id/rss.xml"
GROK_URL        = "https://vidabot.markasai.com/generate-grok"

# Overlay settings
FONT_NAME        = "Arial"
FONT_SIZE        = 60
FADE_DURATION_MS = 500
MAX_CHARS_PER_LINE = 22

# Full Auto
FULL_AUTO_INTERVAL_HOURS = 2        # Berjalan per 2 jam
FULL_AUTO_WAIT_POLL_SEC  = 30       # Polling stop event setiap 30 detik saat menunggu interval

# TikTok defaults
DEFAULT_USER_DATA = os.path.join(APP_DIR, "user_data", "1")
DEFAULT_PORT      = "9222"

# ═══════════════════════════════════════════════════════════════
#  SETTINGS PERSISTENCE
# ═══════════════════════════════════════════════════════════════
DEFAULT_SETTINGS = {
    "user_data_dir": DEFAULT_USER_DATA,
    "debug_port": DEFAULT_PORT,
    "deskripsi": "Peringatan Dini Cuaca BMKG 🌦️⚠️ #bmkg #cuaca #peringatandini #hujanlebat #fyp",
    "hashtags": ["bmkg", "cuaca", "peringatandini", "hujanlebat", "fyp", "viral"],
    "interval": "60",
    "schedule_tanggal": datetime.now().strftime("%Y-%m-%d"),
    "schedule_jam": f"{datetime.now().hour:02d}",
    "schedule_menit": f"{datetime.now().minute:02d}",
    "auto_interval_hours": FULL_AUTO_INTERVAL_HOURS,
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
        except:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings(cfg):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

bot_settings = load_settings()

# ═══════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════
active_tasks   = {}         # uid -> True   (manual pipeline running)
stop_events    = {}         # uid -> threading.Event (manual stop)
full_auto_tasks = {}        # uid -> {"stop": Event, "thread": Thread, "chat_id": int}

def is_allowed(uid):
    return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS

def escape_html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ═══════════════════════════════════════════════════════════════
#  BMKG RSS PARSER
# ═══════════════════════════════════════════════════════════════
def fetch_bmkg_alert():
    """Fetch the first BMKG weather alert from RSS feed."""
    try:
        resp = requests.get(BMKG_RSS_URL, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        item = root.find(".//channel/item")
        if item is None:
            return None
        title       = item.findtext("title", "").strip()
        description = item.findtext("description", "").strip()
        loc_match   = re.search(r'\bdi\s+(.+)$', title, re.IGNORECASE)
        location    = loc_match.group(1).strip() if loc_match else ""
        return {"title": title, "description": description, "location": location}
    except Exception as e:
        logger.error(f"BMKG fetch error: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
#  GROK VIDEO GENERATION
# ═══════════════════════════════════════════════════════════════
def load_prompt():
    if os.path.exists(PROMPT_FILE):
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "Generate a weather alert video"

def get_random_image():
    """Pick a random image from bahan_forecast directory."""
    if not os.path.isdir(PROMPT_IMAGE_DIR):
        return None
    exts = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
    files = [os.path.join(PROMPT_IMAGE_DIR, f)
             for f in os.listdir(PROMPT_IMAGE_DIR)
             if f.lower().endswith(exts) and os.path.isfile(os.path.join(PROMPT_IMAGE_DIR, f))]
    if not files:
        return None
    import random
    chosen = random.choice(files)
    logger.info(f"Random image dipilih: {os.path.basename(chosen)}")
    return chosen

def open_chrome_grok(user_data_dir, port):
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    proc = subprocess.Popen([chrome_path, f"--remote-debugging-port={port}",
                             f"--user-data-dir={user_data_dir}"])
    time.sleep(5)
    return proc

def connect_selenium_grok(port):
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    svc = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=svc, options=opts)

def do_login_grok(driver, log_fn):
    if "login" not in driver.current_url:
        return False
    log_fn("🔐 Login otomatis...")
    wait = WebDriverWait(driver, 15)
    try:
        # e = wait.until(EC.element_to_be_clickable((By.ID, "data.email")))
        # e.clear(); e.send_keys("oktavandigamer2@gmail.com")
        p = wait.until(EC.element_to_be_clickable((By.ID, "data.password")))
        p.clear(); p.send_keys("oktavandi111111")
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))).click()
        log_fn("🔐 Login diklik...")
        deadline = time.time() + 15
        while time.time() < deadline:
            if "login" not in driver.current_url:
                log_fn("✅ Login berhasil!")
                return True
            time.sleep(0.5)
    except Exception as e:
        log_fn(f"❌ Gagal login: {e}")
    return True

def generate_video_grok(log_fn, stop_event, output_dir):
    """Automate Grok video generation and download. Returns path or None."""
    os.makedirs(output_dir, exist_ok=True)
    prompt     = load_prompt()
    image_path = get_random_image()
    grok_user_data = os.path.join(APP_DIR, "user_data", "grok")
    grok_port      = "9230"

    log_fn("🌐 Membuka Chrome untuk Grok...")
    chrome_proc = open_chrome_grok(grok_user_data, grok_port)
    driver = None
    try:
        driver = connect_selenium_grok(grok_port)
        driver.execute_cdp_cmd("Page.setDownloadBehavior",
                               {"behavior": "allow", "downloadPath": output_dir})

        log_fn("🌐 Navigasi ke Grok...")
        driver.get(GROK_URL)
        time.sleep(3)

        if "login" in driver.current_url:
            do_login_grok(driver, log_fn)
            if GROK_URL not in driver.current_url:
                driver.get(GROK_URL); time.sleep(3)

        if stop_event.is_set():
            return None

        wait = WebDriverWait(driver, 15)
        log_fn("📝 Mengisi prompt...")
        try:
            pa = wait.until(EC.element_to_be_clickable((By.ID, "promptInput")))
            pa.clear()
            driver.execute_script("arguments[0].value = arguments[1];", pa, prompt)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pa)
        except Exception as e:
            log_fn(f"❌ Gagal isi prompt: {e}"); return None

        if image_path:
            try:
                log_fn(f"📷 Upload gambar: {os.path.basename(image_path)}")
                driver.find_element(By.ID, "imageInput").send_keys(image_path)
                time.sleep(1)
            except Exception as e:
                log_fn(f"⚠️ Gagal upload gambar: {e}")

        try:
            btn = wait.until(EC.element_to_be_clickable((By.ID, "btnGenerate")))
            btn.click(); log_fn("🚀 Generate diklik!")
        except Exception as e:
            log_fn(f"❌ Gagal klik Generate: {e}"); return None

        log_fn("⏳ Menunggu video selesai (max 5 menit)...")
        start_time = time.time()
        while time.time() - start_time < 300:
            if stop_event.is_set():
                return None
            try:
                p = driver.find_element(By.ID, "progressPercent").text
                pct_match = re.search(r'\d+', p)
                if pct_match and int(pct_match.group()) > 0:
                    log_fn(f"⏳ Progress: {pct_match.group()}%")
            except: pass
            try:
                if "Video ready" in driver.find_element(By.ID, "progressLabel").text:
                    break
            except: pass
            try:
                if driver.find_element(By.ID, "btnDownload").is_displayed():
                    break
            except: pass
            try:
                fails = driver.find_elements(By.XPATH,
                    "//div[contains(@class,'video-placeholder') and "
                    ".//*[contains(text(),'Generation Failed')]]")
                if fails:
                    log_fn("❌ Generation Failed!"); return None
            except: pass
            time.sleep(3)
        else:
            log_fn("❌ Timeout: video tidak selesai di-generate"); return None

        log_fn("📥 Mengunduh video...")
        try:
            dl_btn  = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.ID, "btnDownload")))
            dl_url  = dl_btn.get_attribute("href")
            filename  = f"bmkg_{int(time.time())}.mp4"
            save_path = os.path.join(output_dir, filename)

            s  = requests.Session()
            for c in driver.get_cookies():
                s.cookies.set(c['name'], c['value'])
            ua = driver.execute_script("return navigator.userAgent;")
            s.headers.update({"User-Agent": ua, "Referer": "https://vidabot.markasai.com/"})

            downloaded = False
            try:
                r = s.get(dl_url, stream=True, timeout=30)
                if 'video' in r.headers.get("Content-Type", ""):
                    with open(save_path, 'wb') as f:
                        for chunk in r.iter_content(8192): f.write(chunk)
                    downloaded = True
                    log_fn(f"✅ Video diunduh: {filename}")
            except Exception as e:
                log_fn(f"⚠️ Direct download gagal: {e}")

            if not downloaded:
                log_fn("📥 Fallback download...")
                main_tab = driver.current_window_handle
                driver.execute_script(f"window.open('{dl_url}', '_blank');")
                new_tab = [h for h in driver.window_handles if h != main_tab][-1]
                driver.switch_to.window(new_tab)
                try:
                    vid = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.TAG_NAME, "video")))
                    src = (vid.get_attribute("src") or
                           vid.find_element(By.TAG_NAME, "source").get_attribute("src"))
                    if src:
                        r = s.get(src, stream=True)
                        with open(save_path, 'wb') as f:
                            for chunk in r.iter_content(8192): f.write(chunk)
                        downloaded = True
                        log_fn(f"✅ Video diunduh (fallback): {filename}")
                except Exception as e:
                    log_fn(f"❌ Fallback gagal: {e}")
                driver.close()
                driver.switch_to.window(main_tab)

            if downloaded and os.path.exists(save_path):
                if os.path.getsize(save_path) < 10240:
                    log_fn("⚠️ File terlalu kecil, dihapus.")
                    os.remove(save_path); return None
                return save_path
        except Exception as e:
            log_fn(f"❌ Download error: {e}")

        return None
    finally:
        try:
            if driver: driver.quit()
        except: pass
        try: chrome_proc.terminate()
        except: pass

# ═══════════════════════════════════════════════════════════════
#  VIDEO OVERLAY
# ═══════════════════════════════════════════════════════════════
def strip_emoji(text):
    emoji_pat = re.compile(
        u"(\ud83d[\ude00-\ude4f])|(\ud83c[\udf00-\uffff])|(\ud83d[\u0000-\uddff])|"
        u"(\ud83d[\ude80-\udeff])|(\ud83c[\udde0-\uddff])|[\U00010000-\U0010ffff]|"
        u"[\u2600-\u2B55]|[\u2300-\u23FF]")
    return ' '.join(emoji_pat.sub('', text).split()).strip()

def split_description_to_segments(description, max_duration_sec=10):
    desc = strip_emoji(description.strip())
    sentences = [s.strip() for s in re.split(r'[.\n]+', desc) if s.strip()]
    if not sentences:
        return [desc]
    segments = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) > 80 and current:
            segments.append(current.strip()); current = sent
        else:
            current = (current + ". " + sent).strip(". ")
    if current:
        segments.append(current.strip())
    max_seg = max(2, max_duration_sec // 3)
    if len(segments) > max_seg:
        merged = []
        chunk = len(segments) // max_seg + 1
        for i in range(0, len(segments), chunk):
            merged.append(". ".join(segments[i:i+chunk]))
        segments = merged[:max_seg]
    return segments

def seconds_to_ass_time(seconds):
    h = int(seconds // 3600); m = int((seconds % 3600) // 60)
    s = int(seconds % 60);    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def generate_ass_subtitle(segments, video_duration=10):
    ref_w, ref_h  = 1080, 1920
    y_pos, x_pos  = int(ref_h * 0.55), ref_w // 2
    dur_per_seg   = video_duration / len(segments) if segments else video_duration

    ass = (
        f"[Script Info]\nTitle: BMKG Alert Overlay\nScriptType: v4.00+\n"
        f"PlayResX: {ref_w}\nPlayResY: {ref_h}\nWrapStyle: 0\n\n"
        f"[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        f"OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        f"Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: BMKGAlert,{FONT_NAME},{FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H80000000,1,0,0,0,100,100,0,0,3,3,10,5,30,30,30,1\n\n"
        f"[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    for idx, seg in enumerate(segments):
        start = seconds_to_ass_time(idx * dur_per_seg)
        end   = seconds_to_ass_time((idx + 1) * dur_per_seg)
        lines = textwrap.wrap(strip_emoji(seg), width=MAX_CHARS_PER_LINE)
        body  = "\\N".join(lines)
        styled = f"{{\\fad({FADE_DURATION_MS},{FADE_DURATION_MS})\\pos({x_pos},{y_pos})}}{body}"
        ass += f"Dialogue: 0,{start},{end},BMKGAlert,,0,0,0,,{styled}\n"

    return ass

def get_video_duration(video_path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except:
        return 10

def process_overlay(video_path, segments, output_path, log_fn):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    video_dur = get_video_duration(video_path)
    log_fn(f"📐 Durasi: {video_dur:.1f}s | {len(segments)} segment")

    ass_content = generate_ass_subtitle(segments, video_dur)
    ass_file    = output_path.replace(".mp4", ".ass")
    with open(ass_file, "w", encoding="utf-8") as f:
        f.write(ass_content)

    ass_esc = ass_file.replace("\\", "/").replace(":", "\\:")
    use_wm  = os.path.exists(WATERMARK_PATH)

    if use_wm:
        flt = (f"[0:v]ass='{ass_esc}'[texted];"
               f"[1:v]scale=250:-1[wm];"
               f"[texted][wm]overlay=(W-w)/2:25")
        cmd = ["ffmpeg", "-y", "-i", video_path, "-i", WATERMARK_PATH,
               "-filter_complex", flt,
               "-c:v", "libx264", "-crf", "18", "-preset", "fast",
               "-c:a", "copy", "-map", "0:a?", output_path]
    else:
        cmd = ["ffmpeg", "-y", "-i", video_path,
               "-vf", f"ass='{ass_esc}'",
               "-c:v", "libx264", "-crf", "18", "-preset", "fast",
               "-c:a", "copy", "-map", "0:a?", output_path]

    log_fn("🎬 Memproses overlay...")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    try: os.remove(ass_file)
    except: pass

    if proc.returncode != 0:
        log_fn(f"❌ FFmpeg: {proc.stderr.decode('utf-8', errors='ignore')[-200:]}")
        return False

    log_fn(f"✅ Overlay selesai ({os.path.getsize(output_path)/1024/1024:.1f} MB)")
    return True

# ═══════════════════════════════════════════════════════════════
#  TIKTOK UPLOAD
# ═══════════════════════════════════════════════════════════════
def upload_to_tiktok(video_path, deskripsi, location, log_fn, stop_event, cfg):
    userdata = cfg.get("user_data_dir", DEFAULT_USER_DATA)
    port     = cfg.get("debug_port", DEFAULT_PORT)
    hashtags = cfg.get("hashtags", [])

    ss_tanggal = cfg.get("schedule_tanggal", datetime.now().strftime("%Y-%m-%d"))
    ss_jam     = int(cfg.get("schedule_jam", datetime.now().hour))
    ss_menit   = int(cfg.get("schedule_menit", datetime.now().minute))
    interval   = int(cfg.get("interval", "60"))

    schedule_dt = datetime.strptime(ss_tanggal, "%Y-%m-%d").replace(
        hour=ss_jam, minute=ss_menit)

    MIN_FUTURE = 60
    now        = datetime.now()
    min_start  = now + timedelta(minutes=MIN_FUTURE)
    if schedule_dt < min_start:
        schedule_dt  = min_start.replace(second=0, microsecond=0)
        rounded_min  = ((schedule_dt.minute + 4) // 5) * 5
        if rounded_min >= 60:
            schedule_dt = schedule_dt.replace(minute=0) + timedelta(hours=1)
        else:
            schedule_dt = schedule_dt.replace(minute=rounded_min)
        log_fn(f"⚠️ Schedule digeser → {schedule_dt.strftime('%Y-%m-%d %H:%M')}")

    log_fn(f"📅 Schedule: {schedule_dt.strftime('%Y-%m-%d %H:%M')}")
    log_fn(f"📍 Lokasi: {location}")
    log_fn(f"🌐 Membuka Chrome TikTok (port {port})...")

    chrome_proc = open_chrome_debug(userdata, port)
    driver      = connect_selenium(port)
    log_fn("✅ Chrome terhubung!")

    try:
        navigate_upload_page(driver, force=True)
        time.sleep(3)
        do_upload_file(driver, os.path.normpath(video_path), log_fn)
        time.sleep(5)
        do_post_video(driver, deskripsi, "", "", log_fn,
                      schedule_dt, stop_event,
                      add_sound=False, add_product=False,
                      skip_switches=True,
                      hashtags=hashtags if hashtags else None,
                      location=location if location else None)
        log_fn("✅ Video berhasil di-schedule di TikTok!")

        # Advance TikTok schedule for next upload
        next_dt = schedule_dt + timedelta(minutes=interval)
        cfg["schedule_tanggal"] = next_dt.strftime("%Y-%m-%d")
        cfg["schedule_jam"]     = f"{next_dt.hour:02d}"
        cfg["schedule_menit"]   = f"{next_dt.minute:02d}"
        save_settings(cfg)
        log_fn(f"💾 Next schedule: {next_dt.strftime('%Y-%m-%d %H:%M')}")
        return True

    except Exception as e:
        log_fn(f"❌ Upload error: {e}")
        return False
    finally:
        try: driver.quit()
        except: pass
        try: chrome_proc.terminate()
        except: pass

# ═══════════════════════════════════════════════════════════════
#  FULL PIPELINE
# ═══════════════════════════════════════════════════════════════
def run_full_pipeline(log_fn, stop_event, cfg):
    """Steps: 1-Fetch BMKG 2-Grok 3-Overlay 4-TikTok"""

    log_fn("🌦️ [1/4] Mengambil data BMKG...", "info")
    alert = fetch_bmkg_alert()
    if not alert:
        log_fn("❌ Gagal ambil data BMKG!", "error"); return False

    log_fn(f"📋 {alert['title']}", "info")
    log_fn(f"📍 Lokasi: {alert['location']}", "info")
    if stop_event.is_set(): return False

    log_fn("🎬 [2/4] Generate video via Grok...", "info")
    video_path = generate_video_grok(log_fn, stop_event, OUTPUT_DIR)
    if not video_path:
        log_fn("❌ Gagal generate video!", "error"); return False
    log_fn(f"✅ Video: {os.path.basename(video_path)}", "success")
    if stop_event.is_set(): return False

    log_fn("🎨 [3/4] Menambahkan text overlay...", "info")
    segments = split_description_to_segments(alert['description'])
    log_fn(f"📝 {len(segments)} segment teks", "info")

    overlay_out = os.path.join(OVERLAY_DIR, f"bmkg_overlay_{int(time.time())}.mp4")
    os.makedirs(OVERLAY_DIR, exist_ok=True)
    if not process_overlay(video_path, segments, overlay_out, log_fn):
        log_fn("❌ Gagal proses overlay!", "error"); return False
    if stop_event.is_set(): return False

    log_fn("📤 [4/4] Upload ke TikTok...", "info")
    deskripsi = cfg.get("deskripsi", DEFAULT_SETTINGS["deskripsi"])
    ok = upload_to_tiktok(overlay_out, deskripsi, alert['location'],
                          log_fn, stop_event, cfg)
    if ok:
        log_fn("🎉 Pipeline selesai! Video berhasil diupload!", "success")
    else:
        log_fn("❌ Pipeline gagal pada upload TikTok.", "error")
    return ok

# ═══════════════════════════════════════════════════════════════
#  FULL AUTO DAEMON
# ═══════════════════════════════════════════════════════════════
def _full_auto_daemon(uid, chat_id, bot, stop_event, main_loop):
    """
    Background daemon: Jalankan pipeline sekali, lalu tunggu 2 jam, ulangi.
    Kirim notifikasi ke chat setiap siklus.
    """
    def send(text):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    cfg = bot_settings
    auto_interval_hours = cfg.get("auto_interval_hours", FULL_AUTO_INTERVAL_HOURS)
    run_count = 0

    send(
        f"🤖 <b>Full Auto BMKG dimulai!</b>\n\n"
        f"Pipeline akan berjalan otomatis setiap <b>{auto_interval_hours} jam</b>.\n"
        f"Tekan <b>Stop Full Auto</b> untuk menghentikan."
    )

    while not stop_event.is_set():
        run_count += 1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        send(f"🌦️ <b>[Auto Run #{run_count}]</b>\n⏱ {now_str}\nMemulai pipeline...")

        log_lines = []

        def log_fn(msg, tag=None):
            ts   = datetime.now().strftime("%H:%M:%S")
            icon = {"success": "✅", "error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(tag, "▪️")
            log_lines.append(f"[{ts}] {icon} {msg}")

        try:
            success = run_full_pipeline(log_fn, stop_event, cfg)
        except Exception as e:
            log_fn(f"Error: {e}", "error")
            success = False

        # Send result summary (last 15 lines)
        summary = "\n".join(log_lines[-15:])
        status  = "✅ <b>Berhasil!</b>" if success else "❌ <b>Gagal.</b>"
        send(
            f"🌦️ <b>[Auto Run #{run_count}] Selesai</b>\n\n"
            f"{status}\n\n"
            f"<pre>{escape_html(summary)}</pre>"
        )

        if stop_event.is_set():
            break

        # Wait for next cycle, checking stop_event every FULL_AUTO_WAIT_POLL_SEC seconds
        next_run = datetime.now() + timedelta(hours=auto_interval_hours)
        send(
            f"⏳ <b>Full Auto</b>: Selesai run #{run_count}.\n"
            f"Run #{run_count+1} akan dimulai: <code>{next_run.strftime('%Y-%m-%d %H:%M')}</code>"
        )

        elapsed = 0
        total_wait = auto_interval_hours * 3600
        while elapsed < total_wait and not stop_event.is_set():
            time.sleep(FULL_AUTO_WAIT_POLL_SEC)
            elapsed += FULL_AUTO_WAIT_POLL_SEC

    full_auto_tasks.pop(uid, None)
    send("⏹ <b>Full Auto BMKG dihentikan.</b>")

# ═══════════════════════════════════════════════════════════════
#  TELEGRAM BOT HANDLERS
# ═══════════════════════════════════════════════════════════════
def main_menu_kb(uid=None):
    is_running_manual = bool(uid and active_tasks.get(uid))
    is_auto_running   = bool(uid and full_auto_tasks.get(uid))

    rows = []

    if is_running_manual:
        rows.append([InlineKeyboardButton("⏹ Stop Manual", callback_data="stop_pipeline")])
    else:
        rows.append([InlineKeyboardButton("🚀 Manual Generate", callback_data="start_pipeline")])

    if is_auto_running:
        rows.append([InlineKeyboardButton("⏹ Stop Full Auto", callback_data="stop_full_auto")])
    else:
        rows.append([InlineKeyboardButton("🤖 Mulai Full Auto", callback_data="start_full_auto")])

    rows.append([InlineKeyboardButton("🌦️ Cek BMKG", callback_data="check_bmkg")])
    rows.append([InlineKeyboardButton("⚙️ Settings", callback_data="show_settings")])
    rows.append([InlineKeyboardButton("↻ Refresh", callback_data="refresh")])
    return InlineKeyboardMarkup(rows)

def _status_text(uid):
    cfg = bot_settings
    is_auto = bool(full_auto_tasks.get(uid))
    is_manual = bool(active_tasks.get(uid))
    status_line = ""
    if is_auto:
        status_line = "🟢 <b>Full Auto AKTIF</b>"
    elif is_manual:
        status_line = "🟡 <b>Manual pipeline berjalan</b>"
    else:
        status_line = "⚫ <b>Idle</b> (tidak ada proses berjalan)"

    return (
        "🌦️ <b>BMKG Video Generator Bot</b>\n\n"
        f"{status_line}\n\n"
        f"📅 Schedule: <code>{cfg.get('schedule_tanggal','')} "
        f"{cfg.get('schedule_jam','')}:{cfg.get('schedule_menit','')}</code>\n"
        f"⏱ Interval TikTok sched: <code>{cfg.get('interval','60')} menit</code>\n"
        f"🔄 Full Auto interval: <code>{cfg.get('auto_interval_hours', FULL_AUTO_INTERVAL_HOURS)} jam</code>\n"
        f"📝 Deskripsi: <code>{escape_html(cfg.get('deskripsi','')[:50])}</code>\n"
        f"📍 Port: <code>{cfg.get('debug_port', DEFAULT_PORT)}</code>"
    )

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    await update.message.reply_text(
        _status_text(uid), reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)

async def cmd_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start full auto via /auto command."""
    uid = update.effective_user.id
    if not is_allowed(uid): return
    if full_auto_tasks.get(uid):
        await update.message.reply_text("ℹ️ Full Auto sudah berjalan.")
        return
    await _do_start_full_auto(update.effective_chat.id, uid, ctx.bot)
    await update.message.reply_text("🤖 Full Auto dimulai!", reply_markup=main_menu_kb(uid))

async def cmd_stopauto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    task = full_auto_tasks.get(uid)
    if task:
        task["stop"].set()
        await update.message.reply_text("⏹ Full Auto dihentikan.", reply_markup=main_menu_kb(uid))
    else:
        await update.message.reply_text("ℹ️ Full Auto tidak sedang berjalan.")

async def cmd_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    if active_tasks.get(uid):
        await update.message.reply_text("⚠️ Proses sedang berjalan!")
        return
    await _start_pipeline(update.effective_chat.id, uid, ctx.bot)

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    evt = stop_events.get(uid)
    if evt:
        evt.set()
        await update.message.reply_text("⏹ Menghentikan manual pipeline...")
    else:
        await update.message.reply_text("ℹ️ Tidak ada manual pipeline berjalan.")

async def cmd_bmkg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    alert = fetch_bmkg_alert()
    if not alert:
        await update.message.reply_text("ℹ️ Tidak ada peringatan BMKG aktif saat ini.")
        return
    text = (
        f"🌦️ <b>Peringatan BMKG Terbaru</b>\n\n"
        f"📋 <b>{escape_html(alert['title'])}</b>\n\n"
        f"📝 {escape_html(alert['description'][:500])}\n\n"
        f"📍 Lokasi: <b>{escape_html(alert['location'])}</b>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    raw  = update.message.text.strip()
    args = raw.split(None, 2)
    if len(args) < 3:
        await update.message.reply_text(
            "⚙️ <b>Format /set:</b>\n\n"
            "<code>/set desc Peringatan BMKG 🌦️</code>\n"
            "<code>/set port 9222</code>\n"
            "<code>/set userdata 1</code>\n"
            "<code>/set hashtags bmkg, cuaca, fyp</code>\n"
            "<code>/set sched 2026-03-05 14:30</code>\n"
            "<code>/set interval 60</code>\n"
            "<code>/set auto_interval 2</code>",
            parse_mode=ParseMode.HTML)
        return

    sub = args[1].lower()
    val = args[2].strip()
    cfg = bot_settings

    if sub == "desc":
        cfg["deskripsi"] = val; save_settings(cfg)
        await update.message.reply_text(
            f"✅ Deskripsi: <code>{escape_html(val[:60])}</code>", parse_mode=ParseMode.HTML)

    elif sub == "port":
        cfg["debug_port"] = val; save_settings(cfg)
        await update.message.reply_text(f"✅ Port: <code>{val}</code>", parse_mode=ParseMode.HTML)

    elif sub == "userdata":
        cfg["user_data_dir"] = os.path.join(APP_DIR, "user_data", val); save_settings(cfg)
        await update.message.reply_text(
            f"✅ User Data: <code>user_data/{val}</code>", parse_mode=ParseMode.HTML)

    elif sub == "hashtags":
        tags = [t.strip().lstrip('#') for t in re.split(r'[,\n]+', val)
                if t.strip().lstrip('#')]
        cfg["hashtags"] = tags; save_settings(cfg)
        await update.message.reply_text(
            f"✅ Hashtags: <code>{escape_html(', '.join('#'+t for t in tags))}</code>",
            parse_mode=ParseMode.HTML)

    elif sub == "sched":
        parts = val.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Contoh: <code>/set sched 2026-03-05 14:30</code>", parse_mode=ParseMode.HTML)
            return
        try:
            datetime.strptime(parts[0], "%Y-%m-%d")
            tp = parts[1].replace(".", ":").split(":")
            if len(tp) != 2: raise ValueError
            cfg["schedule_tanggal"] = parts[0]
            cfg["schedule_jam"]     = tp[0].zfill(2)
            cfg["schedule_menit"]   = tp[1].zfill(2)
            save_settings(cfg)
            await update.message.reply_text(
                f"✅ Schedule: <code>{parts[0]} {tp[0].zfill(2)}:{tp[1].zfill(2)}</code>",
                parse_mode=ParseMode.HTML)
        except:
            await update.message.reply_text(
                "❌ Format salah. Contoh: <code>/set sched 2026-03-05 14:30</code>",
                parse_mode=ParseMode.HTML)

    elif sub == "interval":
        cfg["interval"] = val; save_settings(cfg)
        await update.message.reply_text(
            f"✅ Interval: <code>{val} menit</code>", parse_mode=ParseMode.HTML)

    elif sub == "auto_interval":
        try:
            h = float(val)
            cfg["auto_interval_hours"] = h; save_settings(cfg)
            await update.message.reply_text(
                f"✅ Full Auto interval: <code>{h} jam</code>", parse_mode=ParseMode.HTML)
        except:
            await update.message.reply_text(
                "❌ Contoh: <code>/set auto_interval 2</code>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("❌ Sub-command tidak dikenal.",
                                         parse_mode=ParseMode.HTML)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>BMKG Video Generator Bot</b>\n\n"
        "<b>Perintah:</b>\n"
        "/start — Menu utama\n"
        "/generate — Manual: ambil BMKG → Grok → Overlay → TikTok\n"
        "/stop — Stop manual pipeline\n"
        "/auto — Aktifkan Full Auto (setiap 2 jam)\n"
        "/stopauto — Hentikan Full Auto\n"
        "/bmkg — Cek peringatan BMKG terbaru\n"
        "/set — Ubah settings\n"
        "/help — Panduan ini\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ <b>Panduan /set:</b>\n\n"
        "<code>/set desc Peringatan BMKG 🌦️</code>\n"
        "<code>/set port 9222</code>\n"
        "<code>/set userdata 1</code>\n"
        "<code>/set hashtags bmkg, cuaca, fyp</code>\n"
        "<code>/set sched 2026-03-05 14:30</code>\n"
        "<code>/set interval 60</code>\n"
        "<code>/set auto_interval 2</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>Full Auto:</b>\n"
        "Otomatis jalankan pipeline setiap <b>2 jam</b>.\n"
        "🚀 <b>Manual:</b>\n"
        "Jalankan pipeline sekali saat tombol ditekan."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ═══════════════════════════════════════════════════════════════
#  PIPELINE RUNNER HELPERS
# ═══════════════════════════════════════════════════════════════
async def _start_pipeline(chat_id, uid, bot):
    """Start manual pipeline in background thread with live Telegram log."""
    if active_tasks.get(uid):
        await bot.send_message(chat_id, "⚠️ Proses sedang berjalan!")
        return

    stop_evt = threading.Event()
    stop_events[uid] = stop_evt

    log_msg = await bot.send_message(
        chat_id,
        "🚀 <b>BMKG Manual Pipeline Dimulai!</b>\n\n⏳ Memulai...",
        parse_mode=ParseMode.HTML)

    log_lines = []

    async def _update_log():
        last = ""
        while not stop_evt.is_set() and uid in active_tasks:
            body = "\n".join(log_lines[-20:]) if log_lines else "<i>Menunggu...</i>"
            text = f"🌦️ <b>BMKG Log</b>\n\n{body}"
            if text != last:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=log_msg.message_id,
                        text=text[:4096], parse_mode=ParseMode.HTML)
                    last = text
                except: pass
            await asyncio.sleep(3)
        # Final update
        body = "\n".join(log_lines[-25:]) if log_lines else ""
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=log_msg.message_id,
                text=f"🌦️ <b>BMKG Log — Selesai</b>\n\n{body}"[:4096],
                parse_mode=ParseMode.HTML)
        except: pass

    def log_fn(msg, tag=None):
        ts   = datetime.now().strftime("%H:%M:%S")
        icon = {"success": "✅", "error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(tag, "▪️")
        log_lines.append(f"<code>[{ts}]</code> {icon} {msg}")

    def thread_fn():
        try:
            run_full_pipeline(log_fn, stop_evt, bot_settings)
        except Exception as e:
            log_fn(f"Pipeline error: {e}", "error")
        finally:
            active_tasks.pop(uid, None)
            stop_events.pop(uid, None)

    active_tasks[uid] = True
    threading.Thread(target=thread_fn, daemon=True).start()
    asyncio.create_task(_update_log())

async def _do_start_full_auto(chat_id, uid, bot):
    """Start the Full Auto daemon thread."""
    if full_auto_tasks.get(uid):
        return  # already running

    stop_evt  = threading.Event()
    main_loop = asyncio.get_event_loop()

    t = threading.Thread(
        target=_full_auto_daemon,
        args=(uid, chat_id, bot, stop_evt, main_loop),
        daemon=True,
        name=f"bmkg_full_auto_{uid}"
    )
    full_auto_tasks[uid] = {"stop": stop_evt, "thread": t, "chat_id": chat_id}
    t.start()

# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid     = q.from_user.id
    if not is_allowed(uid): return
    data    = q.data
    chat_id = q.message.chat_id

    if data == "refresh":
        await q.edit_message_text(
            _status_text(uid), reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    if data == "check_bmkg":
        alert = fetch_bmkg_alert()
        if not alert:
            await q.edit_message_text(
                "ℹ️ Tidak ada peringatan BMKG aktif.",
                reply_markup=main_menu_kb(uid))
            return
        text = (
            f"🌦️ <b>Peringatan BMKG Terbaru</b>\n\n"
            f"📋 <b>{escape_html(alert['title'])}</b>\n\n"
            f"📝 {escape_html(alert['description'][:400])}\n\n"
            f"📍 Lokasi: <b>{escape_html(alert['location'])}</b>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Manual Generate", callback_data="start_pipeline")],
            [InlineKeyboardButton("🤖 Mulai Full Auto", callback_data="start_full_auto")],
            [InlineKeyboardButton("🏠 Menu", callback_data="refresh")]
        ])
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if data == "start_pipeline":
        await q.edit_message_text("🚀 Memulai manual pipeline...", parse_mode=ParseMode.HTML)
        await _start_pipeline(chat_id, uid, ctx.bot)
        return

    if data == "stop_pipeline":
        evt = stop_events.get(uid)
        if evt: evt.set()
        await q.edit_message_text(
            "⏹ Menghentikan manual pipeline...",
            reply_markup=main_menu_kb(uid))
        return

    if data == "start_full_auto":
        if full_auto_tasks.get(uid):
            await q.edit_message_text(
                "⚠️ Full Auto sudah berjalan!",
                reply_markup=main_menu_kb(uid))
            return
        await _do_start_full_auto(chat_id, uid, ctx.bot)
        cfg = bot_settings
        await q.edit_message_text(
            f"🤖 <b>Full Auto dimulai!</b>\n\n"
            f"Pipeline akan berjalan otomatis setiap "
            f"<b>{cfg.get('auto_interval_hours', FULL_AUTO_INTERVAL_HOURS)} jam</b>.\n"
            f"Log dikirimkan ke chat ini setiap siklus.\n\n"
            f"Tekan <b>Stop Full Auto</b> untuk menghentikan.",
            reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    if data == "stop_full_auto":
        task = full_auto_tasks.get(uid)
        if task:
            task["stop"].set()
        await q.edit_message_text(
            "⏹ <b>Full Auto dihentikan.</b>",
            reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    if data == "show_settings":
        cfg = bot_settings
        ht  = ', '.join(f"#{t}" for t in cfg.get('hashtags', [])) or '(kosong)'
        text = (
            "⚙️ <b>Settings</b>\n\n"
            f"📝 Deskripsi: <code>{escape_html(cfg.get('deskripsi','')[:60])}</code>\n"
            f"📍 Port: <code>{cfg.get('debug_port', DEFAULT_PORT)}</code>\n"
            f"📁 User Data: <code>{cfg.get('user_data_dir','')}</code>\n"
            f"🏷 Hashtags: <code>{escape_html(ht)}</code>\n"
            f"📅 Schedule: <code>{cfg.get('schedule_tanggal','')} "
            f"{cfg.get('schedule_jam','')}:{cfg.get('schedule_menit','')}</code>\n"
            f"⏱ Interval sched TikTok: <code>{cfg.get('interval','60')} menit</code>\n"
            f"🔄 Full Auto interval: <code>{cfg.get('auto_interval_hours', FULL_AUTO_INTERVAL_HOURS)} jam</code>\n\n"
            "Gunakan <code>/set</code> untuk mengubah settings."
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="refresh")]])
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start",    "📋 Menu utama"),
        BotCommand("auto",     "🤖 Aktifkan Full Auto (setiap 2 jam)"),
        BotCommand("stopauto", "⏹ Hentikan Full Auto"),
        BotCommand("generate", "🚀 Manual: BMKG → Grok → TikTok"),
        BotCommand("stop",     "⏹ Stop manual pipeline"),
        BotCommand("bmkg",     "🌦️ Cek peringatan BMKG"),
        BotCommand("set",      "⚙️ Ubah settings"),
        BotCommand("help",     "📖 Panduan"),
    ])

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(OVERLAY_DIR, exist_ok=True)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("auto",     cmd_auto))
    app.add_handler(CommandHandler("stopauto", cmd_stopauto))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("stop",     cmd_stop))
    app.add_handler(CommandHandler("bmkg",     cmd_bmkg))
    app.add_handler(CommandHandler("set",      cmd_set))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🌦️ BMKG Video Generator Bot (Full Auto + Manual) is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
