"""
Grok Imagine Bot — Multi-Browser Video Generation via grok_autoV2.js
Telegram bot that generates videos using 5 parallel Chrome browsers.
Ports: 9226-9230, User Data: 1grokimagine-5grokimagine.
Default: Video mode, 720p, 10s, 9:16.
"""

import os, sys, re, time, shutil, asyncio, subprocess, logging, json, threading, random, glob, base64
from datetime import datetime, timedelta

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from telegram.constants import ParseMode

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8719519553:AAE7YaB34XuzsURi9L6ynw9FB_fhnsGqre0"
ALLOWED_USER_IDS = []  # Kosong = semua user boleh

APP_DIR        = r"C:\tiktok_automation"
USER_DATA_BASE = os.path.join(APP_DIR, "user_data")
BAHAN_DIR      = os.path.join(APP_DIR, "bahan")
OUTPUT_DIR     = os.path.join(APP_DIR, "grok_output")
MERGED_DIR     = os.path.join(APP_DIR, "grok_output_merged")
PROMPTS_FILE   = os.path.join(APP_DIR, "grok_prompts.json")
SETTINGS_FILE  = os.path.join(APP_DIR, "grok_imagine_settings.json")
GROK_URL       = "https://grok.com/imagine"
JS_FILE        = os.path.join(APP_DIR, "grok_autoV2.js")

# ── Multi-browser config ──
GROK_PORTS = [9226, 9227, 9228, 9229, 9230]
GROK_USER_DATA_DIRS = [
    os.path.join(USER_DATA_BASE, "1grokimagine"),
    os.path.join(USER_DATA_BASE, "2grokimagine"),
    os.path.join(USER_DATA_BASE, "3grokimagine"),
    os.path.join(USER_DATA_BASE, "4grokimagine"),
    os.path.join(USER_DATA_BASE, "5grokimagine"),
]
N_BROWSERS = len(GROK_USER_DATA_DIRS)  # 5

# ═══════════════════════════════════════════════════════════════
#  BOT SETTINGS PERSISTENCE
# ═══════════════════════════════════════════════════════════════
_DEFAULT_SETTINGS = {
    "merge_duration": 20,
    "gen_mode": "Video",
    "resolution": "720p",
    "duration": "10s",
    "aspect_ratio": "9:16",
}

def load_bot_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return {**_DEFAULT_SETTINGS, **json.load(f)}
        except:
            pass
    return dict(_DEFAULT_SETTINGS)

def save_bot_settings(cfg: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

bot_settings = load_bot_settings()

# ═══════════════════════════════════════════════════════════════
#  PROMPTS DATABASE
# ═══════════════════════════════════════════════════════════════
def load_prompts() -> dict:
    if os.path.exists(PROMPTS_FILE):
        try:
            with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_prompts(data: dict):
    with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ═══════════════════════════════════════════════════════════════
#  BAHAN (IMAGE FOLDERS) HELPERS
# ═══════════════════════════════════════════════════════════════
def ensure_bahan_dir():
    os.makedirs(BAHAN_DIR, exist_ok=True)

def list_bahan_folders() -> list:
    ensure_bahan_dir()
    return sorted([d for d in os.listdir(BAHAN_DIR)
                   if os.path.isdir(os.path.join(BAHAN_DIR, d))])

def list_bahan_images(folder_name: str) -> list:
    folder = os.path.join(BAHAN_DIR, folder_name)
    if not os.path.isdir(folder):
        return []
    exts = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')
    return sorted([f for f in os.listdir(folder)
                   if f.lower().endswith(exts)])

def get_random_bahan_image(folder_name: str):
    images = list_bahan_images(folder_name)
    if not images:
        return None
    chosen = random.choice(images)
    return os.path.join(BAHAN_DIR, folder_name, chosen)

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def is_allowed(uid):
    return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS

def escape_html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def image_to_base64(path):
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("utf-8")
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "bmp": "image/bmp"}.get(ext, "image/jpeg")
    return f"data:{mime};base64,{b64}"

# ═══════════════════════════════════════════════════════════════
#  VIDEO MERGE (same method as gtt_core — concat demuxer + re-encode)
# ═══════════════════════════════════════════════════════════════
def merge_video_pair(vid1: str, vid2: str, output_dir: str, log_fn=None):
    """Merge 2 videos using concat demuxer + re-encode (proven reliable)."""
    os.makedirs(output_dir, exist_ok=True)
    out = os.path.join(output_dir, f"merged_{int(time.time())}_{random.randint(100,999)}.mp4")
    txt = os.path.join(output_dir, f"_concat_{int(time.time())}.txt")
    try:
        with open(txt, "w") as f:
            f.write(f"file '{vid1}'\nfile '{vid2}'\n")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", txt,
               "-c:v", "libx264", "-preset", "fast", "-crf", "23",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
               "-t", "20", out]
        if log_fn:
            log_fn(f"🎬 Merge: {os.path.basename(vid1)} + {os.path.basename(vid2)}")
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 10000:
            sz = os.path.getsize(out) / (1024 * 1024)
            if log_fn: log_fn(f"✅ Merged: {os.path.basename(out)} ({sz:.1f} MB)")
            return out
        if log_fn: log_fn(f"❌ Merge gagal: returncode={r.returncode}")
    except FileNotFoundError:
        if log_fn: log_fn("❌ FFmpeg tidak ditemukan!")
    except subprocess.TimeoutExpired:
        if log_fn: log_fn("⚠️ FFmpeg merge timeout (120s)")
    except Exception as e:
        if log_fn: log_fn(f"❌ Merge error: {str(e)[:100]}")
    finally:
        try: os.remove(txt)
        except: pass
    return None

# ═══════════════════════════════════════════════════════════════
#  MULTI-BROWSER GROK WORKER (uses grok_autoV2.js)
# ═══════════════════════════════════════════════════════════════
class GrokBrowserWorker:
    """One Chrome instance generating videos via grok_autoV2.js injection."""

    def __init__(self, browser_id, port, user_data_dir, output_dir, log_fn, stop_event, file_lock, video_cfg, browser_states=None):
        self.bid = browser_id
        self.port = port
        self.user_data_dir = user_data_dir
        self.output_dir = output_dir
        self.log_fn = log_fn
        self._stop = stop_event
        self._file_lock = file_lock
        self.video_cfg = video_cfg  # {gen_mode, resolution, duration, aspect_ratio}
        self.driver = None
        self.generated = 0
        self.failed = 0
        self.results = []  # List of successfully generated file paths
        self._browser_states = browser_states  # Shared dict for live dashboard
        self._update_state("idle", 0, "Menunggu...")

    def _update_state(self, status, progress=0, message="", task_num=0, total_tasks=0):
        """Update shared browser state for live dashboard."""
        if self._browser_states is not None:
            self._browser_states[self.bid] = {
                "status": status,
                "progress": progress,
                "message": message,
                "generated": self.generated,
                "failed": self.failed,
                "task_num": task_num,
                "total_tasks": total_tasks,
            }

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_fn(f"[{ts}] [B{self.bid+1}] {msg}")

    def get_next_filename(self, folder):
        with self._file_lock:
            files = glob.glob(os.path.join(folder, "*.mp4"))
            pat = re.compile(r'(\d+)\.mp4')
            max_n = 0
            for f in files:
                m = pat.fullmatch(os.path.basename(f))
                if m: max_n = max(max_n, int(m.group(1)))
            return f"{max_n + 1}.mp4"

    def open_chrome(self):
        self.log(f"Membuka Chrome port={self.port}...")
        chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        cmd = [chrome,
               f"--remote-debugging-port={self.port}",
               f"--user-data-dir={self.user_data_dir}",
               "--headless=new",
               "--no-first-run", "--no-default-browser-check",
               GROK_URL]
        subprocess.Popen(cmd)
        time.sleep(6)

    def kill_chrome(self):
        try:
            res = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10)
            pids = set()
            for line in res.stdout.splitlines():
                if f":{self.port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts: pids.add(parts[-1])
            for pid in pids:
                subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=5)
                self.log(f"Chrome PID {pid} dimatikan ✓")
        except Exception as e:
            self.log(f"Gagal matikan Chrome: {e}")

    def connect_selenium(self):
        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{self.port}")
        try:
            svc = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=svc, options=opts)
            os.makedirs(self.output_dir, exist_ok=True)
            driver.execute_cdp_cmd("Page.setDownloadBehavior",
                                   {"behavior": "allow", "downloadPath": self.output_dir})
            self.log(f"Selenium terhubung ✓ (port {self.port})")
            return driver
        except Exception as e:
            self.log(f"Gagal connect Selenium: {e}")
            return None

    def inject_js(self, driver):
        if not os.path.exists(JS_FILE):
            self.log(f"❌ File JS tidak ditemukan: {JS_FILE}")
            return False
        try:
            with open(JS_FILE, "r", encoding="utf-8") as f:
                js_code = f.read()
            driver.execute_script(js_code)
            time.sleep(1)
            ready = driver.execute_script("return typeof window.__grokGenerate === 'function';")
            if ready:
                self.log("✅ grok_autoV2.js di-inject")
                return True
            else:
                self.log("⚠️ JS inject tapi __grokGenerate tidak tersedia")
                return False
        except Exception as e:
            self.log(f"❌ Gagal inject JS: {e}")
            return False

    def do_single_generate(self, driver, gen_idx, prompt_text, image_path, output_dir):
        """Generate a single video. Returns file path, 'RATE_LIMITED', or None."""
        prefix = f"[#{gen_idx+1}]"

        # Navigate to /imagine
        self._update_state("navigating", 0, "Membuka /imagine...")
        self.log(f"{prefix} 🌐 Membuka grok.com/imagine...")
        driver.get(GROK_URL)
        time.sleep(5)
        if self._stop.is_set(): return None

        # Inject JS
        self._update_state("injecting", 5, "Inject JS...")
        if not self.inject_js(driver):
            self.log(f"{prefix} ❌ Gagal inject JS")
            return None
        if self._stop.is_set(): return None

        # Prepare image
        image_b64 = None
        image_name = "ref.jpg"
        if image_path and os.path.exists(image_path):
            self._update_state("uploading", 8, f"Encoding {os.path.basename(image_path)[:20]}...")
            self.log(f"{prefix} 📷 Encoding: {os.path.basename(image_path)}")
            try:
                image_b64 = image_to_base64(image_path)
                image_name = os.path.basename(image_path)
            except Exception as e:
                self.log(f"{prefix} ⚠️ Gagal encode gambar: {e}")
                image_b64 = None
        if self._stop.is_set(): return None

        # Call __grokGenerate with configurable video settings
        self._update_state("generating", 10, "Memulai generate...")
        self.log(f"{prefix} 🚀 Generate: {prompt_text[:60]}...")
        try:
            config_json = json.dumps({
                "prompt": prompt_text,
                "mode": "video",
                "image": image_b64,
                "imageName": image_name,
                "timeout": 600000,
                "upscale": False,
                "useImageRef": True if image_b64 else False,
                "genMode": self.video_cfg.get("gen_mode", "Video"),
                "resolution": self.video_cfg.get("resolution", "720p"),
                "duration": self.video_cfg.get("duration", "10s"),
                "aspectRatio": self.video_cfg.get("aspect_ratio", "9:16"),
            })
            driver.execute_script(f"""
                (async function() {{
                    try {{
                        await window.__grokGenerate({config_json});
                    }} catch(e) {{
                        window.__GROK_AUTO.status = 'error';
                        window.__GROK_AUTO.error = e.message;
                    }}
                }})();
            """)
        except Exception as e:
            self.log(f"{prefix} ❌ Gagal __grokGenerate: {e}")
            return None

        # Poll progress
        poll_start = time.time()
        poll_timeout = 660
        last_pct = -1
        last_msg = ""

        while time.time() - poll_start < poll_timeout:
            if self._stop.is_set():
                try: driver.execute_script("window.__grokCancel();")
                except: pass
                return None

            try:
                state = driver.execute_script("return window.__grokGetState();")
            except Exception:
                time.sleep(2)
                continue

            if not state:
                time.sleep(1)
                continue

            status = state.get("status", "idle")
            pct = state.get("progress", 0)
            msg = state.get("message", "")
            error = state.get("error")

            if pct != last_pct:
                last_pct = pct
                self._update_state("generating", max(10, min(95, pct)), msg[:40])
                self.log(f"{prefix} ⏳ {pct}% — {msg[:60]}")

            if status == "done":
                self._update_state("downloading", 98, "Selesai! Downloading...")
                self.log(f"{prefix} ✅ Generasi selesai!")
                break
            elif status == "error":
                self._update_state("error", 0, error or "Unknown error")
                self.log(f"{prefix} ❌ Error: {error or 'Unknown'}")
                return None
            elif status == "rate_limited":
                self._update_state("rate_limited", 0, "Rate limited!")
                self.log(f"{prefix} 🚫 RATE LIMIT!")
                return "RATE_LIMITED"
            elif status == "cancelled":
                return None

            time.sleep(2)
        else:
            self._update_state("error", 0, "Timeout")
            self.log(f"{prefix} ❌ Timeout")
            return None

        if self._stop.is_set(): return None

        # Download video
        try:
            state = driver.execute_script("return window.__grokGetState();")
            vid_url = state.get("videoUrl") if state else None
        except:
            vid_url = None

        if not vid_url or not vid_url.startswith("https://"):
            try:
                vid_url = driver.execute_script("""
                    const sd = document.querySelector('video#sd-video');
                    if (sd && sd.src && sd.src.startsWith('https://')) return sd.src;
                    const hd = document.querySelector('video#hd-video');
                    if (hd && hd.src && hd.src.startsWith('https://')) return hd.src;
                    for (const v of document.querySelectorAll('video')) {
                        if (v.src && v.src.startsWith('https://') && v.src.includes('.mp4'))
                            return v.src;
                    }
                    return null;
                """)
            except:
                vid_url = None

        if not vid_url or not vid_url.startswith("https://"):
            self.log(f"{prefix} ❌ Video URL tidak ditemukan")
            return None

        filename = self.get_next_filename(output_dir)
        save_path = os.path.join(output_dir, filename)
        self._update_state("downloading", 98, "Downloading video...")
        self.log(f"{prefix} ⬇️ Downloading...")

        try:
            cookies = {c['name']: c['value'] for c in driver.get_cookies()}
            headers = {
                'User-Agent': driver.execute_script("return navigator.userAgent;"),
                'Referer': 'https://grok.com/',
            }
            resp = requests.get(vid_url, headers=headers, cookies=cookies,
                                stream=True, timeout=120)
            if resp.status_code == 200:
                size = 0
                with open(save_path, 'wb') as f:
                    for chunk in resp.iter_content(65536):
                        if chunk:
                            f.write(chunk)
                            size += len(chunk)
                if size > 50000:
                    self.log(f"{prefix} ✅ {filename} ({size/1024/1024:.1f} MB)")
                    return save_path
                else:
                    try: os.remove(save_path)
                    except: pass
        except Exception as e:
            self.log(f"{prefix} ⚠️ Download error: {e}")

        # Fallback file watcher
        dl_time = time.time()
        downloads_dir = os.path.expanduser("~/Downloads")
        for _ in range(60):
            time.sleep(1)
            if self._stop.is_set(): return None
            for chk in [output_dir, downloads_dir]:
                try:
                    mp4s = glob.glob(os.path.join(chk, "*.mp4"))
                    new = [f for f in mp4s if os.path.getmtime(f) > dl_time - 2]
                    if new and not glob.glob(os.path.join(chk, "*.crdownload")):
                        newest = max(new, key=os.path.getmtime)
                        if os.path.getsize(newest) > 50000:
                            if newest != save_path:
                                shutil.move(newest, save_path)
                            self.log(f"{prefix} ✅ {filename} ({os.path.getsize(save_path)/1024/1024:.1f} MB)")
                            return save_path
                except: pass

        self.log(f"{prefix} ❌ Download gagal")
        return None

    def start(self):
        """Launch Chrome and connect Selenium."""
        self.open_chrome()
        if self._stop.is_set(): return False
        driver = self.connect_selenium()
        if not driver:
            return False
        self.driver = driver
        return True

    def run_tasks(self, tasks):
        """
        tasks = list of (gen_num, prompt_text, image_path)
        Runs on self.driver.
        """
        driver = self.driver
        delay = 5

        for task_idx, (gen_num, prompt_text, image_path) in enumerate(tasks):
            if self._stop.is_set(): break

            self._update_state("generating", 0, "Memulai...", task_idx + 1, len(tasks))
            result = self.do_single_generate(driver, gen_num, prompt_text, image_path, self.output_dir)

            if result == "RATE_LIMITED":
                self._update_state("rate_limited", 0, "Menunggu 2 menit...", task_idx + 1, len(tasks))
                self.log("🚫 Rate limit! Menunggu 2 menit...")
                for _ in range(120):
                    if self._stop.is_set(): break
                    time.sleep(1)
                if self._stop.is_set(): break
                result = self.do_single_generate(driver, gen_num, prompt_text, image_path, self.output_dir)
                if result == "RATE_LIMITED":
                    self._update_state("error", 0, "Rate limit masih aktif")
                    self.log("🚫 Rate limit masih aktif. Stop browser ini.")
                    break

            if result and result != "RATE_LIMITED":
                self.generated += 1
                self.results.append(result)
                self._update_state("success", 100, f"✅ Video #{self.generated}", task_idx + 1, len(tasks))
            else:
                self.failed += 1
                self._update_state("error", 0, "Gagal", task_idx + 1, len(tasks))

            # Delay between videos
            if task_idx < len(tasks) - 1 and not self._stop.is_set():
                self.log(f"⏳ Jeda {delay} detik...")
                for _ in range(delay):
                    if self._stop.is_set(): break
                    time.sleep(1)

    def shutdown(self):
        self._update_state("done", 100, f"Selesai: {self.generated} OK, {self.failed} gagal")
        self.log(f"🏁 B{self.bid+1} total: {self.generated} OK, {self.failed} gagal")
        try: self.driver.quit()
        except: pass
        self.kill_chrome()


# ═══════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════
active_gen_tasks = {}   # uid -> {"stop": Event, "thread": Thread}


# ═══════════════════════════════════════════════════════════════
#  MULTI-BROWSER GENERATION LOOP (runs in thread)
# ═══════════════════════════════════════════════════════════════
def _generation_loop(uid, chat_id, bot, main_loop, folder_name, count, prompt_name, stop_event):
    """Multi-browser generation loop using grok_autoV2.js."""

    def send(text):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    def send_video_tg(path):
        """Send video to Telegram, then delete the file."""
        async def _send():
            try:
                # Validate before sending
                if not os.path.exists(path):
                    return
                fsize = os.path.getsize(path)
                if fsize < 50000:
                    log_fn(f"⚠️ File terlalu kecil, skip: {os.path.basename(path)}")
                    try: os.remove(path)
                    except: pass
                    return
                if fsize > 50 * 1024 * 1024:  # > 50MB
                    log_fn(f"⚠️ File terlalu besar ({fsize/1024/1024:.0f}MB), kirim sebagai document")
                    with open(path, 'rb') as vf:
                        await bot.send_document(chat_id, document=vf,
                                                caption=f"🎬 Video dari <b>{escape_html(folder_name)}</b> ({fsize/1024/1024:.1f}MB)",
                                                parse_mode=ParseMode.HTML)
                else:
                    with open(path, 'rb') as vf:
                        await bot.send_video(chat_id, video=vf,
                                             caption=f"🎬 Video dari <b>{escape_html(folder_name)}</b>",
                                             parse_mode=ParseMode.HTML,
                                             supports_streaming=True,
                                             read_timeout=120,
                                             write_timeout=120)
                # Delete after successful send
                try:
                    if os.path.exists(path): os.remove(path)
                except: pass
            except Exception as e:
                log_fn(f"⚠️ Gagal kirim {os.path.basename(path)}: {str(e)[:60]}")
        asyncio.run_coroutine_threadsafe(_send(), main_loop)

    prompts = load_prompts()
    prompt_text = prompts.get(prompt_name)
    if not prompt_text:
        send(f"❌ Prompt <code>{escape_html(prompt_name)}</code> tidak ditemukan!")
        active_gen_tasks.pop(uid, None)
        return

    images = list_bahan_images(folder_name)
    if not images:
        send(f"❌ Folder <code>{escape_html(folder_name)}</code> kosong atau tidak ada!")
        active_gen_tasks.pop(uid, None)
        return

    infinite = (count == 0)
    target_str = "∞" if infinite else str(count)
    actual_count = count if not infinite else 10  # Batch 10 for infinite mode

    cfg = bot_settings
    merge_dur = cfg.get("merge_duration", 20)
    merge_enabled = (merge_dur == 20)
    gen_mode = cfg.get("gen_mode", "Video")
    resolution = cfg.get("resolution", "720p")
    duration = cfg.get("duration", "10s")
    aspect_ratio = cfg.get("aspect_ratio", "9:16")

    video_cfg = {
        "gen_mode": gen_mode,
        "resolution": resolution,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
    }

    merge_mode_str = "🎬 Mode: <b>Gabung 2 video (20 dtk)</b>" if merge_enabled else "🎬 Mode: <b>Tanpa gabung (10 dtk)</b>"
    send(
        f"🚀 <b>Multi-Browser Generate dimulai!</b>\n\n"
        f"📁 Folder: <code>{escape_html(folder_name)}</code> ({len(images)} gambar)\n"
        f"📝 Prompt: <code>{escape_html(prompt_name)}</code>\n"
        f"🎯 Target: <b>{target_str}</b> video raw\n"
        f"🖥 Browser: <b>{N_BROWSERS}</b> (ports {GROK_PORTS[0]}-{GROK_PORTS[-1]})\n"
        f"🎬 Video: <code>{gen_mode} {resolution} {duration} {aspect_ratio}</code>\n"
        f"{merge_mode_str}\n\n"
        f"Gunakan /stop untuk menghentikan."
    )

    # ── Live log message ──
    log_lines = []
    log_lock = threading.Lock()
    log_done = threading.Event()
    generated_total = [0]
    failed_total = [0]
    merged_count = [0]
    start_time = time.time()
    browser_states = {}  # Shared dict: bid -> {status, progress, message, ...}
    active_worker_list = []  # Reference to current workers for dashboard

    def make_progress_bar(current, total, bar_length=15):
        """Create a colorful gradient progress bar for Telegram."""
        if total <= 0 or current <= 0:
            pct = 0
        else:
            pct = min(100, int(current / total * 100))

        filled = int(bar_length * pct / 100)
        empty = bar_length - filled

        # Gradient colors based on percentage
        if pct < 25:
            fill_char = "🟥"
        elif pct < 50:
            fill_char = "🟧"
        elif pct < 75:
            fill_char = "🟨"
        else:
            fill_char = "🟩"

        bar = fill_char * filled + "⬜" * empty
        return bar, pct

    def make_mini_bar(current, total=100, length=8):
        """Create a compact per-browser progress bar."""
        if total <= 0 or current <= 0:
            pct = 0
        else:
            pct = min(100, int(current / total * 100))
        filled = int(length * pct / 100)
        empty = length - filled
        if pct < 25:
            c = "🟥"
        elif pct < 50:
            c = "🟧"
        elif pct < 75:
            c = "🟨"
        else:
            c = "🟩"
        return c * filled + "⬜" * empty, pct

    def render_browser_panel():
        """Render per-browser status panel."""
        if not browser_states:
            return ""
        lines = []
        status_icons = {
            "idle": "⚪", "navigating": "🌐", "injecting": "💉",
            "uploading": "📤", "generating": "🔄", "downloading": "⬇️",
            "success": "✅", "error": "❌", "rate_limited": "🚫",
            "done": "🏁",
        }
        for bid in sorted(browser_states.keys()):
            st = browser_states[bid]
            status = st.get("status", "idle")
            pct = st.get("progress", 0)
            msg = st.get("message", "")[:25]
            gen = st.get("generated", 0)
            fail = st.get("failed", 0)
            task_n = st.get("task_num", 0)
            task_t = st.get("total_tasks", 0)
            icon = status_icons.get(status, "⚪")

            bar, bar_pct = make_mini_bar(pct, 100, 8)

            task_info = f"({task_n}/{task_t})" if task_t > 0 else ""
            stat_str = f"✓{gen}" if gen > 0 else ""
            if fail > 0:
                stat_str += f" ✗{fail}"

            lines.append(
                f"{icon} <b>B{bid+1}</b> {bar} {bar_pct}% {stat_str} {task_info}"
                f"\n     <i>{escape_html(msg)}</i>"
            )
        return "\n".join(lines)

    def format_elapsed(seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}j {m}m {s}d"
        elif m > 0:
            return f"{m}m {s}d"
        return f"{s}d"

    def log_fn(msg, tag=None):
        ts = datetime.now().strftime("%H:%M:%S")
        with log_lock:
            log_lines.append(f"<code>[{ts}]</code> {escape_html(msg)}")
            if len(log_lines) > 25: log_lines.pop(0)

    log_msg_future = asyncio.run_coroutine_threadsafe(
        bot.send_message(chat_id,
                         f"📋 <b>Live Log</b>\n\n<i>Memulai {N_BROWSERS} browser...</i>",
                         parse_mode=ParseMode.HTML), main_loop)
    try:
        log_msg = log_msg_future.result(timeout=10)
        log_msg_id = log_msg.message_id
    except:
        log_msg_id = None

    async def _live_log_updater():
        last_text = ""
        while not log_done.is_set():
            elapsed = time.time() - start_time
            elapsed_str = format_elapsed(elapsed)
            gen = generated_total[0]
            fail = failed_total[0]

            # Overall progress bar
            if not infinite and count > 0:
                bar, pct = make_progress_bar(gen, count)
                progress_line = f"{bar} <b>{pct}%</b>"
                counter_line = f"📊 <b>{gen}</b>/{count} video"
            else:
                spinner = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
                spin_idx = int(elapsed) % len(spinner)
                progress_line = f"🟩🟩🟩 <b>♾️ INFINITE</b> 🟩🟩🟩"
                counter_line = f"📊 <b>{gen}</b> video <code>{spinner[spin_idx]}</code>"

            # Speed
            if elapsed > 10 and gen > 0:
                speed = gen / (elapsed / 60)
                speed_str = f"⚡ {speed:.1f} vid/min"
            else:
                speed_str = "⚡ --"

            # Per-browser panel
            browser_panel = render_browser_panel()

            with log_lock:
                body = "\n".join(log_lines[-8:]) if log_lines else "<i>Menunggu...</i>"

            text = (
                f"📋 <b>Grok Imagine — Live Dashboard</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{progress_line}\n"
                f"{counter_line}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Berhasil: <b>{gen}</b>  ❌ Gagal: <b>{fail}</b>\n"
                f"🎬 Merged: <b>{merged_count[0]}</b>  ⏱ {elapsed_str}\n"
                f"{speed_str}\n"
            )
            if browser_panel:
                text += f"━━━━━━━━━━━━━━━━━━━━\n🖥 <b>Browser Status:</b>\n{browser_panel}\n"
            text += f"━━━━━━━━━━━━━━━━━━━━\n{body}"

            if text != last_text and log_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=log_msg_id,
                        text=text[:4096], parse_mode=ParseMode.HTML)
                    last_text = text
                except: pass
            await asyncio.sleep(3)

        # ── Final update ──
        elapsed = time.time() - start_time
        elapsed_str = format_elapsed(elapsed)
        gen = generated_total[0]
        fail = failed_total[0]

        if not infinite and count > 0:
            bar, pct = make_progress_bar(gen, count)
            progress_line = f"{bar} <b>{pct}%</b>"
        else:
            progress_line = f"🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 <b>DONE</b>"

        browser_panel = render_browser_panel()
        with log_lock:
            body = "\n".join(log_lines[-10:]) if log_lines else ""

        try:
            final = (
                f"🏁 <b>Grok Imagine — Selesai!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{progress_line}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Berhasil: <b>{gen}</b>  ❌ Gagal: <b>{fail}</b>\n"
                f"🎬 Merged: <b>{merged_count[0]}</b>  ⏱ Total: {elapsed_str}\n"
            )
            if browser_panel:
                final += f"━━━━━━━━━━━━━━━━━━━━\n🖥 <b>Browser Final:</b>\n{browser_panel}\n"
            final += f"━━━━━━━━━━━━━━━━━━━━\n{body}"
            await bot.edit_message_text(
                chat_id=chat_id, message_id=log_msg_id,
                text=final[:4096], parse_mode=ParseMode.HTML)
        except: pass

    log_task = asyncio.run_coroutine_threadsafe(_live_log_updater(), main_loop)

    # ── Main multi-browser loop ──
    raw_pool = []  # Only freshly generated files from this session
    file_lock = threading.Lock()

    try:
        while not stop_event.is_set():
            if not infinite and generated_total[0] >= count:
                break

            remaining = actual_count if infinite else (count - generated_total[0])
            if remaining <= 0: break

            batch_size = min(remaining, 50)  # Max 50 per round
            log_fn(f"--- Round: {batch_size} video, {N_BROWSERS} browser ---")

            # Build tasks
            all_tasks = []
            for vid_idx in range(batch_size):
                img_path = get_random_bahan_image(folder_name)
                all_tasks.append((vid_idx, prompt_text, img_path))

            # Determine how many browsers to use
            n_browsers = min(N_BROWSERS, max(1, batch_size))

            # Distribute tasks
            browser_tasks = [[] for _ in range(n_browsers)]
            base_c = batch_size // n_browsers
            rem_c = batch_size % n_browsers
            idx = 0
            for b in range(n_browsers):
                cnt = base_c + (1 if b < rem_c else 0)
                browser_tasks[b] = all_tasks[idx:idx + cnt]
                idx += cnt

            # Launch browsers
            workers = []
            for b in range(n_browsers):
                if stop_event.is_set(): break
                port = GROK_PORTS[b]
                ud_dir = GROK_USER_DATA_DIRS[b]
                os.makedirs(ud_dir, exist_ok=True)

                worker = GrokBrowserWorker(
                    b, port, ud_dir, OUTPUT_DIR, log_fn,
                    stop_event, file_lock, video_cfg, browser_states)
                if worker.start():
                    workers.append(worker)
                    log_fn(f"✅ Browser {b+1} terhubung (port {port})")
                else:
                    log_fn(f"❌ Browser {b+1} gagal start")
                time.sleep(3)

            active_workers = [w for w in workers if w.driver is not None]
            if not active_workers:
                log_fn("❌ Tidak ada browser yang berhasil terhubung!")
                break

            n_active = len(active_workers)
            log_fn(f"✅ {n_active}/{n_browsers} browser aktif. Memulai generasi...")

            # Redistribute tasks to active workers only
            if n_active < n_browsers:
                active_tasks = [[] for _ in range(n_active)]
                all_flat = [t for bt in browser_tasks for t in bt]
                base_cc = len(all_flat) // n_active
                rem_cc = len(all_flat) % n_active
                ix = 0
                for b in range(n_active):
                    cc = base_cc + (1 if b < rem_cc else 0)
                    active_tasks[b] = all_flat[ix:ix + cc]
                    ix += cc
                browser_tasks = active_tasks

            # Run all workers in parallel
            threads = []
            for b, worker in enumerate(active_workers):
                if not browser_tasks[b]: continue
                t = threading.Thread(target=worker.run_tasks,
                                     args=(browser_tasks[b],), daemon=True)
                threads.append(t)

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Collect generated files from workers (raw pool)
            round_raw = []
            for w in workers:
                round_raw.extend(w.results)

            # Shutdown browsers
            for w in workers:
                try: w.shutdown()
                except: pass

            round_gen = sum(w.generated for w in workers)
            round_fail = sum(w.failed for w in workers)
            generated_total[0] += round_gen
            failed_total[0] += round_fail

            log_fn(f"🎬 Round selesai: {round_gen} OK, {round_fail} gagal (total: {generated_total[0]})")

            if round_gen == 0 and not infinite:
                log_fn("⚠️ Tidak ada video berhasil round ini.")
                break

            # Add this round's files to raw pool
            raw_pool.extend(round_raw)

            # Process merge + send from raw pool only
            if merge_enabled:
                while len(raw_pool) >= 2 and not stop_event.is_set():
                    vid_a = raw_pool.pop(0)
                    vid_b = raw_pool.pop(0)

                    # Validate both files exist and are not corrupt
                    a_ok = os.path.exists(vid_a) and os.path.getsize(vid_a) > 50000
                    b_ok = os.path.exists(vid_b) and os.path.getsize(vid_b) > 50000

                    if not a_ok and not b_ok:
                        log_fn("⚠️ Kedua video rusak, skip")
                        for _vp in (vid_a, vid_b):
                            try:
                                if os.path.exists(_vp): os.remove(_vp)
                            except: pass
                        continue
                    if not a_ok:
                        log_fn(f"⚠️ {os.path.basename(vid_a)} rusak, kirim {os.path.basename(vid_b)} saja")
                        try:
                            if os.path.exists(vid_a): os.remove(vid_a)
                        except: pass
                        send_video_tg(vid_b)
                        continue
                    if not b_ok:
                        log_fn(f"⚠️ {os.path.basename(vid_b)} rusak, kirim {os.path.basename(vid_a)} saja")
                        try:
                            if os.path.exists(vid_b): os.remove(vid_b)
                        except: pass
                        send_video_tg(vid_a)
                        continue

                    merged_path = merge_video_pair(vid_a, vid_b, MERGED_DIR, log_fn)
                    if merged_path:
                        merged_count[0] += 1
                        send_video_tg(merged_path)
                        # Delete raw source files after merge
                        for _vp in (vid_a, vid_b):
                            try:
                                if os.path.exists(_vp): os.remove(_vp)
                            except: pass
                        log_fn(f"📬 Merged #{merged_count[0]} dikirim")
                    else:
                        log_fn("⚠️ Merge gagal, kirim terpisah")
                        send_video_tg(vid_a)
                        send_video_tg(vid_b)
                    time.sleep(0.5)  # Small delay between sends
            else:
                for vf in list(raw_pool):
                    if os.path.exists(vf) and os.path.getsize(vf) > 50000:
                        send_video_tg(vf)
                    else:
                        # Remove corrupt/small files silently
                        try:
                            if os.path.exists(vf): os.remove(vf)
                        except: pass
                    time.sleep(0.5)  # Small delay between sends
                raw_pool.clear()

            if stop_event.is_set(): break
            if infinite:
                log_fn("♾️ Mode infinite, lanjut round berikutnya...")
                time.sleep(5)

    except Exception as e:
        log_fn(f"❌ Error: {type(e).__name__}: {str(e)[:80]}")
    finally:
        log_done.set()
        time.sleep(2)

    # Send remaining raw pool buffer
    if merge_enabled and raw_pool:
        send(f"📬 Sisa {len(raw_pool)} video di buffer, dikirim tanpa merge")
        for vp in raw_pool:
            if os.path.exists(vp):
                send_video_tg(vp)
        raw_pool.clear()

    merge_info = f"\n🎬 Merged: <b>{merged_count[0]}</b> video" if merge_enabled else ""
    send(
        f"✅ <b>Generasi selesai!</b>\n\n"
        f"✅ Berhasil: <b>{generated_total[0]}</b>\n"
        f"❌ Gagal: <b>{failed_total[0]}</b>{merge_info}\n"
        f"📁 Folder: <code>{escape_html(folder_name)}</code>"
    )
    active_gen_tasks.pop(uid, None)


# ═══════════════════════════════════════════════════════════════
#  TELEGRAM HANDLERS
# ═══════════════════════════════════════════════════════════════
def main_menu_kb(uid=None):
    is_running = bool(uid and active_gen_tasks.get(uid))
    rows = [
        [InlineKeyboardButton("📁 Kelola Bahan", callback_data="bahan_menu"),
         InlineKeyboardButton("📝 Kelola Prompt", callback_data="prompt_menu")],
    ]
    if is_running:
        rows.append([InlineKeyboardButton("⏹ Stop Generate", callback_data="stop_gen")])
    rows.append([InlineKeyboardButton("⚙️ Settings", callback_data="settings_view")])
    rows.append([InlineKeyboardButton("↻ Refresh", callback_data="refresh")])
    return InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    folders = list_bahan_folders()
    prompts = load_prompts()
    is_running = bool(active_gen_tasks.get(uid))

    status = "🟢 <b>Sedang generate</b>" if is_running else "⚫ <b>Idle</b>"
    cfg = bot_settings
    merge_dur = cfg.get("merge_duration", 20)
    merge_label = "🎬 20 dtk (gabung 2 video)" if merge_dur == 20 else "🎬 10 dtk (tanpa gabung)"

    text = (
        "🎬 <b>Grok Imagine Bot (Multi-Browser)</b>\n\n"
        f"{status}\n\n"
        f"📁 Folder bahan: <b>{len(folders)}</b> ({', '.join(folders) if folders else 'kosong'})\n"
        f"📝 Prompt tersimpan: <b>{len(prompts)}</b>\n\n"
        f"<b>🔌 Multi-Browser Config:</b>\n"
        f"  Browsers: <b>{N_BROWSERS}</b> (ports {GROK_PORTS[0]}-{GROK_PORTS[-1]})\n"
        f"  User Data: 1grokimagine - 5grokimagine\n"
        f"  Mode: <code>{cfg.get('gen_mode', 'Video')}</code>\n"
        f"  Resolution: <code>{cfg.get('resolution', '720p')}</code>\n"
        f"  Duration: <code>{cfg.get('duration', '10s')}</code>\n"
        f"  Ratio: <code>{cfg.get('aspect_ratio', '9:16')}</code>\n"
        f"  {merge_label}\n\n"
        "<b>Command:</b>\n"
        "<code>/generate [folder] [jumlah] [prompt]</code>\n"
        "<code>/stop</code> — hentikan generasi\n"
        "<code>/set mode Video|Image</code>\n"
        "<code>/set resolution 480p|720p</code>\n"
        "<code>/set duration 6s|10s</code>\n"
        "<code>/set ratio 9:16|16:9|1:1</code>\n"
        "<code>/set merge 10|20</code>\n"
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)


async def cmd_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return

    if active_gen_tasks.get(uid):
        await update.message.reply_text("⚠️ Proses generate sedang berjalan! Gunakan /stop dulu.")
        return

    args = update.message.text.strip().split()
    if len(args) < 2:
        folders = list_bahan_folders()
        prompts = load_prompts()
        text = (
            "❓ <b>Format:</b>\n"
            "<code>/generate [folder] [jumlah] [prompt]</code>\n\n"
            "• <b>folder</b>: nama subfolder di bahan\n"
            "• <b>jumlah</b>: angka (opsional, kosong = infinite)\n"
            "• <b>prompt</b>: nama prompt dari database\n\n"
            f"📁 Folder tersedia: {', '.join(f'<code>{f}</code>' for f in folders) if folders else '<i>kosong</i>'}\n"
            f"📝 Prompt tersedia: {', '.join(f'<code>{p}</code>' for p in prompts.keys()) if prompts else '<i>kosong</i>'}"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    folder_name = args[1]
    count = 0
    prompt_name = None

    if len(args) >= 3:
        try:
            count = int(args[2])
        except ValueError:
            prompt_name = args[2]
            count = 0

    if len(args) >= 4:
        prompt_name = args[3]

    if not prompt_name:
        prompts = load_prompts()
        if len(prompts) == 1:
            prompt_name = list(prompts.keys())[0]
        else:
            text = (
                "❌ Nama prompt harus diisi!\n\n"
                f"Prompt tersedia: {', '.join(f'<code>{p}</code>' for p in prompts.keys()) if prompts else '<i>kosong</i>'}"
            )
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            return

    # Validate folder
    if folder_name not in list_bahan_folders():
        await update.message.reply_text(
            f"❌ Folder <code>{escape_html(folder_name)}</code> tidak ditemukan!\n\n"
            f"Folder tersedia: {', '.join(f'<code>{f}</code>' for f in list_bahan_folders())}",
            parse_mode=ParseMode.HTML)
        return

    # Validate prompt
    prompts = load_prompts()
    if prompt_name not in prompts:
        await update.message.reply_text(
            f"❌ Prompt <code>{escape_html(prompt_name)}</code> tidak ditemukan!\n\n"
            f"Prompt tersedia: {', '.join(f'<code>{p}</code>' for p in prompts.keys())}",
            parse_mode=ParseMode.HTML)
        return

    # Validate even count for merge mode
    merge_dur = bot_settings.get("merge_duration", 20)
    if merge_dur == 20 and count > 0 and count % 2 != 0:
        await update.message.reply_text(
            "⚠️ <b>Jumlah harus genap!</b>\n\n"
            f"Mode merge aktif (20 dtk = gabung 2 video).\n"
            f"Jumlah <code>{count}</code> tidak genap.\n\n"
            f"Gunakan jumlah genap (misal: 2, 4, 6, 10, 20)\n"
            f"atau nonaktifkan merge: <code>/set merge 10</code>",
            parse_mode=ParseMode.HTML)
        return

    # Start generation
    stop_evt = threading.Event()
    main_loop = asyncio.get_event_loop()

    t = threading.Thread(
        target=_generation_loop,
        args=(uid, update.effective_chat.id, ctx.bot, main_loop,
              folder_name, count, prompt_name, stop_evt),
        daemon=True, name=f"grok_gen_{uid}")

    active_gen_tasks[uid] = {"stop": stop_evt, "thread": t}
    t.start()

    cfg = bot_settings
    target_str = str(count) if count > 0 else "∞ (infinite)"
    await update.message.reply_text(
        f"🚀 <b>Multi-Browser Generate dimulai!</b>\n\n"
        f"📁 Folder: <code>{escape_html(folder_name)}</code>\n"
        f"🎯 Target: <b>{target_str}</b>\n"
        f"📝 Prompt: <code>{escape_html(prompt_name)}</code>\n"
        f"🖥 Browser: <b>{N_BROWSERS}</b> (ports {GROK_PORTS[0]}-{GROK_PORTS[-1]})\n"
        f"🎬 Video: <code>{cfg.get('gen_mode','Video')} {cfg.get('resolution','720p')} "
        f"{cfg.get('duration','10s')} {cfg.get('aspect_ratio','9:16')}</code>\n\n"
        f"Gunakan /stop untuk menghentikan.",
        reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    task = active_gen_tasks.get(uid)
    if task:
        task["stop"].set()
        await update.message.reply_text("⏹ Menghentikan generasi...",
                                         reply_markup=main_menu_kb(uid))
    else:
        await update.message.reply_text("ℹ️ Tidak ada generasi yang berjalan.")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg = bot_settings
    text = (
        "📖 <b>Grok Imagine Bot (Multi-Browser) — Panduan</b>\n\n"
        "<b>Perintah:</b>\n"
        "/start — Menu utama\n"
        "/generate [folder] [jumlah] [prompt] — Mulai generate video\n"
        "/stop — Hentikan generasi\n"
        "/set — Ubah settings\n"
        "/help — Panduan ini\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>⚙️ Settings:</b>\n"
        "<code>/set mode Video|Image</code> — Mode generasi\n"
        "<code>/set resolution 480p|720p</code> — Resolusi\n"
        "<code>/set duration 6s|10s</code> — Durasi\n"
        "<code>/set ratio 9:16|16:9|1:1</code> — Aspect ratio\n"
        "<code>/set merge 10|20</code> — Durasi output\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>🔌 Multi-Browser:</b>\n"
        f"  Browsers: {N_BROWSERS} (ports {GROK_PORTS[0]}-{GROK_PORTS[-1]})\n"
        f"  User Data: 1grokimagine - 5grokimagine\n"
        f"  Mode: <code>{cfg.get('gen_mode','Video')}</code>\n"
        f"  Resolution: <code>{cfg.get('resolution','720p')}</code>\n"
        f"  Duration: <code>{cfg.get('duration','10s')}</code>\n"
        f"  Ratio: <code>{cfg.get('aspect_ratio','9:16')}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎬 <b>Contoh:</b>\n"
        "<code>/generate hijab 10 promptKeren</code>\n"
        "→ Generate 10 video dengan 5 browser paralel\n\n"
        "<code>/generate hijab promptKeren</code>\n"
        "→ Generate infinite video sampai /stop"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    args = update.message.text.strip().split(None, 2)

    if len(args) < 3:
        cfg = bot_settings
        merge_dur = cfg.get("merge_duration", 20)
        merge_label = "🎬 20 dtk (gabung 2 video)" if merge_dur == 20 else "🎬 10 dtk (tanpa gabung)"
        await update.message.reply_text(
            "⚙️ <b>Settings</b>\n\n"
            f"🎬 Mode: <code>{cfg.get('gen_mode', 'Video')}</code>\n"
            f"📐 Resolution: <code>{cfg.get('resolution', '720p')}</code>\n"
            f"⏱ Duration: <code>{cfg.get('duration', '10s')}</code>\n"
            f"📏 Ratio: <code>{cfg.get('aspect_ratio', '9:16')}</code>\n"
            f"{merge_label}\n\n"
            "<b>Format:</b>\n"
            "<code>/set mode Video|Image</code>\n"
            "<code>/set resolution 480p|720p</code>\n"
            "<code>/set duration 6s|10s</code>\n"
            "<code>/set ratio 9:16|16:9|1:1</code>\n"
            "<code>/set merge 20</code> — gabung 2 video (default)\n"
            "<code>/set merge 10</code> — tanpa gabung",
            parse_mode=ParseMode.HTML)
        return

    sub = args[1].lower()
    val = args[2].strip()
    cfg = bot_settings

    if sub == "mode":
        if val in ("Video", "video", "Image", "image"):
            cfg["gen_mode"] = val.capitalize()
            save_bot_settings(cfg)
            await update.message.reply_text(
                f"✅ Mode: <code>{cfg['gen_mode']}</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Pilihan: <code>Video</code> atau <code>Image</code>", parse_mode=ParseMode.HTML)

    elif sub == "resolution":
        if val in ("480p", "720p"):
            cfg["resolution"] = val
            save_bot_settings(cfg)
            await update.message.reply_text(
                f"✅ Resolution: <code>{val}</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Pilihan: <code>480p</code> atau <code>720p</code>", parse_mode=ParseMode.HTML)

    elif sub == "duration":
        if val in ("6s", "10s"):
            cfg["duration"] = val
            save_bot_settings(cfg)
            await update.message.reply_text(
                f"✅ Duration: <code>{val}</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Pilihan: <code>6s</code> atau <code>10s</code>", parse_mode=ParseMode.HTML)

    elif sub == "ratio":
        valid_ratios = ["9:16", "16:9", "1:1", "4:5", "3:4"]
        if val in valid_ratios:
            cfg["aspect_ratio"] = val
            save_bot_settings(cfg)
            await update.message.reply_text(
                f"✅ Aspect Ratio: <code>{val}</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(
                f"❌ Pilihan: {', '.join(f'<code>{r}</code>' for r in valid_ratios)}", parse_mode=ParseMode.HTML)

    elif sub == "merge":
        if val in ("10", "20"):
            cfg["merge_duration"] = int(val)
            save_bot_settings(cfg)
            if int(val) == 20:
                await update.message.reply_text(
                    "✅ Merge: <b>🎬 20 detik</b>\n"
                    "Setiap 2 video akan digabung menjadi 1 video ~20 detik.\n"
                    "Jumlah generate harus genap.",
                    parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(
                    "✅ Merge: <b>🎬 10 detik</b>\n"
                    "Video dikirim langsung tanpa digabung.",
                    parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(
                "❌ Format salah! Gunakan:\n"
                "<code>/set merge 20</code> — gabung 2 video\n"
                "<code>/set merge 10</code> — tanpa gabung",
                parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(
            "❌ Sub-command tidak dikenal.\n"
            "Gunakan: <code>mode</code>, <code>resolution</code>, <code>duration</code>, <code>ratio</code>, <code>merge</code>",
            parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not is_allowed(uid): return
    data = q.data

    # ── Refresh ──
    if data == "refresh":
        folders = list_bahan_folders()
        prompts = load_prompts()
        is_running = bool(active_gen_tasks.get(uid))
        status = "🟢 <b>Sedang generate</b>" if is_running else "⚫ <b>Idle</b>"
        cfg = bot_settings
        text = (
            "🎬 <b>Grok Imagine Bot (Multi-Browser)</b>\n\n"
            f"{status}\n\n"
            f"📁 Folder bahan: <b>{len(folders)}</b>\n"
            f"📝 Prompt tersimpan: <b>{len(prompts)}</b>\n\n"
            f"<b>🔌 Config:</b>\n"
            f"  Browser: <b>{N_BROWSERS}</b> (ports {GROK_PORTS[0]}-{GROK_PORTS[-1]})\n"
            f"  Video: <code>{cfg.get('gen_mode','Video')} {cfg.get('resolution','720p')} "
            f"{cfg.get('duration','10s')} {cfg.get('aspect_ratio','9:16')}</code>"
        )
        await q.edit_message_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)
        return

    # ── Stop ──
    if data == "stop_gen":
        task = active_gen_tasks.get(uid)
        if task:
            task["stop"].set()
        await q.edit_message_text("⏹ Menghentikan generasi...",
                                   reply_markup=main_menu_kb(uid))
        return

    # ── Settings View ──
    if data == "settings_view":
        cfg = bot_settings
        merge_dur = cfg.get("merge_duration", 20)
        merge_label = "🎬 20 dtk (gabung 2 video)" if merge_dur == 20 else "🎬 10 dtk (tanpa gabung)"
        text = (
            "⚙️ <b>Settings (Multi-Browser)</b>\n\n"
            f"<b>🔌 Browser:</b>\n"
            f"  Total: <b>{N_BROWSERS}</b> (ports {GROK_PORTS[0]}-{GROK_PORTS[-1]})\n"
            f"  User Data: 1grokimagine - 5grokimagine\n\n"
            f"<b>🎬 Video Settings:</b>\n"
            f"  Mode: <code>{cfg.get('gen_mode', 'Video')}</code>\n"
            f"  Resolution: <code>{cfg.get('resolution', '720p')}</code>\n"
            f"  Duration: <code>{cfg.get('duration', '10s')}</code>\n"
            f"  Ratio: <code>{cfg.get('aspect_ratio', '9:16')}</code>\n"
            f"  {merge_label}\n\n"
            "<b>Ubah via /set:</b>\n"
            "<code>/set mode Video|Image</code>\n"
            "<code>/set resolution 480p|720p</code>\n"
            "<code>/set duration 6s|10s</code>\n"
            "<code>/set ratio 9:16|16:9|1:1</code>\n"
            "<code>/set merge 10|20</code>"
        )
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Menu", callback_data="refresh")]]),
            parse_mode=ParseMode.HTML)
        return

    # ═══════════════════════════════════════════════════════════════
    #  BAHAN MENU
    # ═══════════════════════════════════════════════════════════════
    if data == "bahan_menu":
        folders = list_bahan_folders()
        text = f"📁 <b>Kelola Bahan</b>\n\n📂 Path: <code>{BAHAN_DIR}</code>\n\n"
        if folders:
            for f in folders:
                imgs = list_bahan_images(f)
                text += f"📁 <b>{escape_html(f)}</b> — {len(imgs)} gambar\n"
        else:
            text += "<i>Belum ada folder bahan.</i>\n"
        text += "\nTambahkan folder baru atau pilih folder untuk melihat isinya."

        rows = []
        for f in folders:
            rows.append([InlineKeyboardButton(f"📁 {f}", callback_data=f"bahan_view_{f}")])
        rows.append([InlineKeyboardButton("➕ Tambah Folder", callback_data="bahan_add_folder")])
        rows.append([InlineKeyboardButton("🏠 Menu", callback_data="refresh")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                   parse_mode=ParseMode.HTML)
        return

    if data.startswith("bahan_view_"):
        folder_name = data[len("bahan_view_"):]
        imgs = list_bahan_images(folder_name)
        text = f"📁 <b>Folder: {escape_html(folder_name)}</b>\n\n"
        if imgs:
            for img in imgs[:20]:
                text += f"  📷 <code>{escape_html(img)}</code>\n"
            if len(imgs) > 20:
                text += f"  ... dan {len(imgs) - 20} lainnya\n"
        else:
            text += "<i>Folder kosong.</i>\n"
        text += f"\n📊 Total: {len(imgs)} gambar"

        kb_rows = [
            [InlineKeyboardButton("➕ Tambah Gambar", callback_data=f"bahan_add_image_{folder_name}")],
        ]
        if imgs:
            kb_rows.append([InlineKeyboardButton("🗑 Hapus Gambar", callback_data=f"bahan_del_image_{folder_name}")])
        kb_rows.append([InlineKeyboardButton("🗑 Hapus Folder", callback_data=f"bahan_del_{folder_name}")])
        kb_rows.append([InlineKeyboardButton("📁 Kembali", callback_data="bahan_menu")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows),
                                   parse_mode=ParseMode.HTML)
        return

    if data.startswith("bahan_del_") and not data.startswith("bahan_del_image_"):
        folder_name = data[len("bahan_del_"):]
        folder_path = os.path.join(BAHAN_DIR, folder_name)
        try:
            if os.path.isdir(folder_path):
                shutil.rmtree(folder_path)
            await q.edit_message_text(
                f"🗑 Folder <b>{escape_html(folder_name)}</b> dihapus!",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📁 Kembali", callback_data="bahan_menu")]]),
                parse_mode=ParseMode.HTML)
        except Exception as e:
            await q.edit_message_text(f"❌ Gagal hapus: {e}",
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton("📁 Kembali", callback_data="bahan_menu")]]))
        return

    if data.startswith("bahan_add_image_"):
        folder_name = data[len("bahan_add_image_"):]
        folder_path = os.path.join(BAHAN_DIR, folder_name)
        if not os.path.isdir(folder_path):
            await q.edit_message_text(f"❌ Folder <b>{escape_html(folder_name)}</b> tidak ditemukan.",
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton("📁 Kembali", callback_data="bahan_menu")]]),
                                       parse_mode=ParseMode.HTML)
            return
        ctx.user_data["waiting_for"] = "bahan_photo"
        ctx.user_data["target_folder"] = folder_name
        await q.edit_message_text(
            f"📷 <b>Tambah Gambar ke: {escape_html(folder_name)}</b>\n\n"
            "Kirim foto/gambar yang ingin ditambahkan.\n"
            "Bisa kirim beberapa foto sekaligus.\n\n"
            "Atau kirim /cancel untuk batal.",
            parse_mode=ParseMode.HTML)
        return

    if data.startswith("bahan_del_image_"):
        folder_name = data[len("bahan_del_image_"):]
        imgs = list_bahan_images(folder_name)
        if not imgs:
            await q.edit_message_text(
                f"📁 Folder <b>{escape_html(folder_name)}</b> kosong.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📁 Kembali", callback_data=f"bahan_view_{folder_name}")]]),
                parse_mode=ParseMode.HTML)
            return
        text = f"🗑 <b>Hapus Gambar dari: {escape_html(folder_name)}</b>\n\nPilih gambar yang ingin dihapus:\n"
        rows = []
        for img in imgs[:30]:
            short = img if len(img) <= 30 else img[:27] + "..."
            cb_data = f"bahan_do_del_{folder_name}|{img}"
            if len(cb_data) > 64:
                cb_data = cb_data[:64]
            rows.append([InlineKeyboardButton(f"🗑 {short}", callback_data=cb_data)])
        if len(imgs) > 30:
            text += f"\n<i>Menampilkan 30 dari {len(imgs)} gambar.</i>\n"
        rows.append([InlineKeyboardButton("📁 Kembali", callback_data=f"bahan_view_{folder_name}")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                   parse_mode=ParseMode.HTML)
        return

    if data.startswith("bahan_do_del_"):
        payload = data[len("bahan_do_del_"):]
        if "|" in payload:
            folder_name, img_name = payload.split("|", 1)
        else:
            await q.edit_message_text("❌ Data tidak valid.",
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton("📁 Kembali", callback_data="bahan_menu")]]),
                                       parse_mode=ParseMode.HTML)
            return
        img_path = os.path.join(BAHAN_DIR, folder_name, img_name)
        try:
            if os.path.isfile(img_path):
                os.remove(img_path)
                await q.edit_message_text(
                    f"🗑 Gambar <code>{escape_html(img_name)}</code> dihapus dari <b>{escape_html(folder_name)}</b>!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🗑 Hapus Lagi", callback_data=f"bahan_del_image_{folder_name}")],
                        [InlineKeyboardButton("📁 Kembali ke Folder", callback_data=f"bahan_view_{folder_name}")]]),
                    parse_mode=ParseMode.HTML)
            else:
                await q.edit_message_text(
                    f"⚠️ File tidak ditemukan: <code>{escape_html(img_name)}</code>",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("📁 Kembali", callback_data=f"bahan_view_{folder_name}")]]),
                    parse_mode=ParseMode.HTML)
        except Exception as e:
            await q.edit_message_text(f"❌ Gagal hapus: {e}",
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton("📁 Kembali", callback_data=f"bahan_view_{folder_name}")]]),
                                       parse_mode=ParseMode.HTML)
        return

    if data == "bahan_add_folder":
        ctx.user_data["waiting_for"] = "folder_name"
        await q.edit_message_text(
            "📁 <b>Tambah Folder Bahan</b>\n\n"
            "Kirim nama folder baru (contoh: <code>hijab</code>).\n"
            "Atau kirim /cancel untuk batal.",
            parse_mode=ParseMode.HTML)
        return

    # ══════════════════════════════════════
    #  PROMPT MENU
    # ══════════════════════════════════════
    if data == "prompt_menu":
        prompts = load_prompts()
        text = "📝 <b>Kelola Prompt</b>\n\n"
        if prompts:
            for name, content in prompts.items():
                text += f"📝 <b>{escape_html(name)}</b>: <code>{escape_html(content[:60])}...</code>\n"
        else:
            text += "<i>Belum ada prompt tersimpan.</i>\n"
        text += "\nTambahkan prompt baru atau pilih untuk menghapus."

        rows = []
        for name in prompts:
            rows.append([
                InlineKeyboardButton(f"📝 {name}", callback_data=f"prompt_view_{name}"),
                InlineKeyboardButton("🗑", callback_data=f"prompt_del_{name}")
            ])
        rows.append([InlineKeyboardButton("➕ Tambah Prompt", callback_data="prompt_add")])
        rows.append([InlineKeyboardButton("🏠 Menu", callback_data="refresh")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                   parse_mode=ParseMode.HTML)
        return

    if data.startswith("prompt_view_"):
        name = data[len("prompt_view_"):]
        prompts = load_prompts()
        content = prompts.get(name, "(tidak ditemukan)")
        text = (
            f"📝 <b>Prompt: {escape_html(name)}</b>\n\n"
            f"<code>{escape_html(content)}</code>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Hapus", callback_data=f"prompt_del_{name}")],
            [InlineKeyboardButton("📝 Kembali", callback_data="prompt_menu")],
        ])
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if data.startswith("prompt_del_"):
        name = data[len("prompt_del_"):]
        prompts = load_prompts()
        if name in prompts:
            del prompts[name]
            save_prompts(prompts)
        await q.edit_message_text(
            f"🗑 Prompt <b>{escape_html(name)}</b> dihapus!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📝 Kembali", callback_data="prompt_menu")]]),
            parse_mode=ParseMode.HTML)
        return

    if data == "prompt_add":
        ctx.user_data["waiting_for"] = "prompt_name"
        await q.edit_message_text(
            "📝 <b>Tambah Prompt Baru</b>\n\n"
            "Kirim <b>nama</b> prompt (contoh: <code>promptKeren</code>).\n"
            "Atau kirim /cancel untuk batal.",
            parse_mode=ParseMode.HTML)
        return


# ═══════════════════════════════════════════════════════════════
#  TEXT & PHOTO HANDLERS
# ═══════════════════════════════════════════════════════════════
async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return

    waiting = ctx.user_data.get("waiting_for")
    if not waiting: return

    text = update.message.text.strip()
    if text.startswith("/"):
        ctx.user_data.pop("waiting_for", None)
        ctx.user_data.pop("new_prompt_name", None)
        return

    # ── Create folder ──
    if waiting == "folder_name":
        ctx.user_data.pop("waiting_for", None)
        safe_name = re.sub(r'[^\w\-]', '_', text)
        folder_path = os.path.join(BAHAN_DIR, safe_name)
        os.makedirs(folder_path, exist_ok=True)
        await update.message.reply_text(
            f"✅ Folder <b>{escape_html(safe_name)}</b> dibuat!\n\n"
            f"📂 Path: <code>{escape_html(folder_path)}</code>\n\n"
            "Sekarang tambahkan gambar ke folder tersebut.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📁 Kelola Bahan", callback_data="bahan_menu")],
                 [InlineKeyboardButton("🏠 Menu", callback_data="refresh")]]),
            parse_mode=ParseMode.HTML)
        return

    # ── Add prompt: step 1 (name) ──
    if waiting == "prompt_name":
        ctx.user_data["waiting_for"] = "prompt_text"
        ctx.user_data["new_prompt_name"] = text
        await update.message.reply_text(
            f"📝 Nama prompt: <b>{escape_html(text)}</b>\n\n"
            "Sekarang kirim <b>isi teks prompt</b>-nya.\n"
            "Atau /cancel untuk batal.",
            parse_mode=ParseMode.HTML)
        return

    # ── Add prompt: step 2 (text) ──
    if waiting == "prompt_text":
        ctx.user_data.pop("waiting_for", None)
        name = ctx.user_data.pop("new_prompt_name", "untitled")
        prompts = load_prompts()
        prompts[name] = text
        save_prompts(prompts)
        await update.message.reply_text(
            f"✅ Prompt <b>{escape_html(name)}</b> tersimpan!\n\n"
            f"<code>{escape_html(text[:200])}</code>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📝 Kelola Prompt", callback_data="prompt_menu")],
                 [InlineKeyboardButton("🏠 Menu", callback_data="refresh")]]),
            parse_mode=ParseMode.HTML)
        return


async def cancel_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("waiting_for", None)
    ctx.user_data.pop("new_prompt_name", None)
    ctx.user_data.pop("target_folder", None)
    await update.message.reply_text("❌ Dibatalkan.", reply_markup=main_menu_kb(update.effective_user.id))


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return

    waiting = ctx.user_data.get("waiting_for")
    if waiting != "bahan_photo":
        return

    folder_name = ctx.user_data.get("target_folder")
    if not folder_name:
        ctx.user_data.pop("waiting_for", None)
        await update.message.reply_text("⚠️ Folder target tidak ditemukan. Coba lagi dari menu.")
        return

    folder_path = os.path.join(BAHAN_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    try:
        if update.message.photo:
            photo = update.message.photo[-1]
            file = await photo.get_file()
            ext = "jpg"
        elif update.message.document:
            doc = update.message.document
            mime = doc.mime_type or ""
            if not mime.startswith("image/"):
                await update.message.reply_text("⚠️ File bukan gambar.")
                return
            file = await doc.get_file()
            orig_name = doc.file_name or "image"
            ext = orig_name.rsplit(".", 1)[-1] if "." in orig_name else "jpg"
        else:
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rand = random.randint(1000, 9999)
        filename = f"img_{ts}_{rand}.{ext}"
        save_path = os.path.join(folder_path, filename)

        await file.download_to_drive(save_path)
        imgs_count = len(list_bahan_images(folder_name))
        await update.message.reply_text(
            f"✅ Gambar disimpan ke <b>{escape_html(folder_name)}</b>!\n\n"
            f"📄 File: <code>{escape_html(filename)}</code>\n"
            f"📊 Total gambar di folder: <b>{imgs_count}</b>\n\n"
            "Kirim foto lagi atau /cancel untuk selesai.",
            parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal simpan gambar: {e}")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start",    "📋 Menu utama"),
        BotCommand("generate", "🎬 Generate video (multi-browser)"),
        BotCommand("stop",     "⏹ Stop generasi"),
        BotCommand("set",      "⚙️ Ubah settings"),
        BotCommand("help",     "📖 Panduan"),
        BotCommand("cancel",   "❌ Batalkan input"),
    ])

def main():
    os.makedirs(BAHAN_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(MERGED_DIR, exist_ok=True)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("stop",     cmd_stop))
    app.add_handler(CommandHandler("set",      cmd_set))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("cancel",   cancel_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    cfg = bot_settings
    try:
        print("🎬 Grok Imagine Bot (Multi-Browser) is running...")
    except UnicodeEncodeError:
        print("Grok Imagine Bot (Multi-Browser) is running...")
    print(f"  Browsers: {N_BROWSERS} (ports {GROK_PORTS[0]}-{GROK_PORTS[-1]})")
    print(f"  User Data: 1grokimagine, 2grokimagine, 3grokimagine, 4grokimagine, 5grokimagine")
    print(f"  Video: {cfg.get('gen_mode','Video')} {cfg.get('resolution','720p')} "
          f"{cfg.get('duration','10s')} {cfg.get('aspect_ratio','9:16')}")
    app.run_polling()


if __name__ == "__main__":
    main()
