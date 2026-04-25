import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import subprocess
import time
import os
import random
import glob
import re
import queue
import json
import shutil
import base64
from datetime import datetime

# ── Try selenium imports ──
try:
    import requests
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_OK = True
except ImportError:
    SELENIUM_OK = False

# ── Paths ──
APP_DIR    = r"C:\tiktok_automation"
BAHAN_DIR  = os.path.join(APP_DIR, "bahan")
OUTPUT_DIR = os.path.join(APP_DIR, "download-grok")
MERGED_DIR = os.path.join(APP_DIR, "download-grok-merged")
GROK_URL   = "https://grok.com/imagine"
DEFAULT_USER_DATA = os.path.join(APP_DIR, "user_data", "1")
DEFAULT_PORT      = 9245
PROMPTS_FILE      = os.path.join(APP_DIR, "supergrok_prompts.json")
JS_FILE           = os.path.join(APP_DIR, "grok_autoV2.js")

# ── Prompts persistence ──
def load_prompts_db():
    """Load prompts list from JSON. Returns list of str."""
    if os.path.exists(PROMPTS_FILE):
        try:
            with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except:
            pass
    return [DEFAULT_PROMPT_1, DEFAULT_PROMPT_2]

def save_prompts_db(prompts_list):
    """Save list of prompt strings to JSON."""
    try:
        with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
            json.dump(prompts_list, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# ── Default prompts ──
DEFAULT_PROMPT_1 = """Buat video singkat 8 detik dengan visual sinematik berkualitas tinggi.
Karakter: wanita Indonesia cantik, percaya diri, modern.
Produk: Tablet Android layar 11.6 inci, OLED, 5G, RAM 16GB, ROM 1024GB.
Gaya: Cinematic, Lighting dramatis, efek api/emas.
VO: Bahasa Indonesia, singkat, enerjik.
Jangan ada teks overlay di layar."""

DEFAULT_PROMPT_2 = """Gaming Beast Video 8 detik.
Karakter: gamer muda, antusias, pakai tablet gaming.
Produk: Tablet Android, layar 11.6 inci, 5G, 16GB RAM, 1024GB ROM.
Gaya: neon glitch merah-biru, energik, banyak efek cahaya.
VO: Bahasa Indonesia, cepat, agresif, caster e-sports.
Musik: trap/EDM gaming, bass kencang."""

# ── Color Palette ──
BG        = "#0F1117"
CARD      = "#1A1D27"
CARD2     = "#22263A"
ACCENT    = "#6C63FF"
ACCENT2   = "#FF6584"
GREEN     = "#00E5A0"
YELLOW    = "#FFD166"
RED       = "#FF4757"
TEXT      = "#E8EAF6"
MUTED     = "#8892B0"
BORDER    = "#2E3250"

# Browser row colors (unique per browser)
BROWSER_COLORS = ["#6C63FF", "#FF6584", "#00E5A0", "#FFD166", "#00B4D8",
                  "#E040FB", "#FF9800", "#76FF03", "#F44336", "#26C6DA"]

STATUS_COLORS = {
    "idle":         MUTED,
    "injecting":    ACCENT,
    "uploading":    ACCENT,
    "setting":      ACCENT,
    "generating":   YELLOW,
    "waiting":      YELLOW,
    "downloading":  GREEN,
    "success":      GREEN,
    "error":        RED,
    "stopped":      RED,
    "rate_limited": RED,
}

# ════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════════════
def list_bahan_folders():
    if not os.path.isdir(BAHAN_DIR):
        return []
    return sorted([d for d in os.listdir(BAHAN_DIR) if os.path.isdir(os.path.join(BAHAN_DIR, d))])

def get_random_bahan_image(folder_name):
    folder = os.path.join(BAHAN_DIR, folder_name)
    if not os.path.isdir(folder):
        return None
    exts = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
    imgs = [f for f in os.listdir(folder) if f.lower().endswith(exts)]
    return os.path.join(folder, random.choice(imgs)) if imgs else None

def image_to_base64(path):
    """Convert image file to base64 data URL."""
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("utf-8")
    ext = os.path.splitext(path)[1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "bmp": "image/bmp"}.get(ext.lstrip("."), "image/jpeg")
    return f"data:{mime};base64,{b64}"

def merge_video_pair(vid1, vid2, output_dir, log_fn=None):
    os.makedirs(output_dir, exist_ok=True)
    existing = glob.glob(os.path.join(output_dir, "*.mp4"))
    nums = []
    for f in existing:
        m = re.fullmatch(r'(\d+)\.mp4', os.path.basename(f))
        if m: nums.append(int(m.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    out_path  = os.path.join(output_dir, f"{next_num}.mp4")
    list_file = os.path.join(output_dir, f"_merge_{next_num}.txt")
    try:
        with open(list_file, "w", encoding="utf-8") as lf:
            lf.write(f"file '{vid1}'\nfile '{vid2}'\n")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out_path]
        if log_fn: log_fn(f"🎬 Merge: {os.path.basename(vid1)} + {os.path.basename(vid2)} → {next_num}.mp4")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            if log_fn: log_fn(f"✅ Merged: {next_num}.mp4 ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
            return out_path
        else:
            if log_fn: log_fn(f"❌ Merge gagal: {r.stderr[-200:]}")
            return None
    except FileNotFoundError:
        if log_fn: log_fn("❌ FFmpeg tidak ditemukan!")
        return None
    except Exception as e:
        if log_fn: log_fn(f"❌ Error merge: {e}")
        return None
    finally:
        try: os.remove(list_file)
        except: pass


# ════════════════════════════════════════════════════════════════════════════
#  SINGLE BROWSER WORKER — runs in its own thread
# ════════════════════════════════════════════════════════════════════════════
class BrowserWorker:
    """One Chrome instance + Selenium driver generating videos sequentially."""

    def __init__(self, browser_id, cfg, log_q, stat_q, stop_event, file_lock):
        self.bid       = browser_id      # 0-based browser index
        self.cfg       = cfg
        self.log_q     = log_q
        self.stat_q    = stat_q
        self._stop     = stop_event      # shared across all workers
        self._file_lock = file_lock      # shared lock for file numbering
        self.driver    = None
        self.port      = cfg["debug_port"] + browser_id
        self.user_data = cfg["user_data_dir"]  # same for all browsers
        self.generated = 0
        self.failed    = 0

    def log(self, msg, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_q.put(f"[{ts}] [B{self.bid+1}] [{level}] {msg}")

    def set_status(self, pct, status):
        self.stat_q.put({"browser": self.bid, "pct": pct, "status": status})

    def set_info(self, key, value):
        self.stat_q.put({"browser": self.bid, key: value})

    # ── File naming (thread-safe) ──
    def get_next_filename(self, folder):
        with self._file_lock:
            files = glob.glob(os.path.join(folder, "*.mp4"))
            pat   = re.compile(r'(\d+)\.mp4')
            max_n = 0
            for f in files:
                m = pat.fullmatch(os.path.basename(f))
                if m: max_n = max(max_n, int(m.group(1)))
            return f"{max_n + 1}.mp4"

    # ── Chrome ──
    def open_chrome(self):
        headless = self.cfg.get("headless", False)
        self.log(f"Membuka Chrome port={self.port} {'(headless)' if headless else ''}...")
        chrome = self.cfg.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        cmd    = [chrome,
                  f"--remote-debugging-port={self.port}",
                  f"--user-data-dir={self.user_data}",
                  "--no-first-run", "--no-default-browser-check"]
        if headless:
            cmd.append("--headless=new")
        cmd.append(GROK_URL)
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
            self.log(f"Gagal matikan Chrome: {e}", "WARN")

    def connect_selenium(self):
        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{self.port}")
        try:
            svc    = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=svc, options=opts)
            output_dir = self.cfg["output_dir"]
            os.makedirs(output_dir, exist_ok=True)
            driver.execute_cdp_cmd("Page.setDownloadBehavior",
                                   {"behavior": "allow", "downloadPath": output_dir})
            self.log(f"Selenium terhubung ✓ (port {self.port})")
            return driver
        except Exception as e:
            self.log(f"Gagal connect Selenium: {e}", "ERROR")
            return None

    # ── Inject grok_autoV2.js ──
    def inject_js(self, driver):
        if not os.path.exists(JS_FILE):
            self.log(f"❌ File JS tidak ditemukan: {JS_FILE}", "ERROR")
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
                self.log("⚠️ JS inject tapi __grokGenerate tidak tersedia", "WARN")
                return False
        except Exception as e:
            self.log(f"❌ Gagal inject JS: {e}", "ERROR")
            return False

    # ══════════════════════════════════════════════════════════════
    #  SINGLE GENERATION
    # ══════════════════════════════════════════════════════════════
    def do_single_generate(self, driver, gen_idx, prompt_text, image_path, output_dir):
        prefix = f"[#{gen_idx+1}]"
        self.set_status(0, "injecting")

        # Navigate to fresh /imagine page
        self.log(f"{prefix} 🌐 Membuka grok.com/imagine...")
        driver.get(GROK_URL)
        time.sleep(5)
        if self._stop.is_set(): return None

        # Inject JS
        self.set_status(5, "injecting")
        if not self.inject_js(driver):
            self.log(f"{prefix} ❌ Gagal inject JS", "ERROR")
            self.set_status(0, "error")
            return None
        if self._stop.is_set(): return None

        # Prepare image
        image_b64 = None
        image_name = "ref.jpg"
        if image_path and os.path.exists(image_path):
            self.log(f"{prefix} 📷 Encoding: {os.path.basename(image_path)}")
            self.set_status(8, "uploading")
            try:
                image_b64 = image_to_base64(image_path)
                image_name = os.path.basename(image_path)
            except Exception as e:
                self.log(f"{prefix} ⚠️ Gagal encode gambar: {e}", "WARN")
                image_b64 = None
        if self._stop.is_set(): return None

        # Call __grokGenerate
        self.set_status(10, "generating")
        self.log(f"{prefix} 🚀 Generate: {prompt_text[:60]}...")

        try:
            config_json = json.dumps({
                "prompt": prompt_text,
                "mode": "video",
                "image": image_b64,
                "imageName": image_name,
                "timeout": 600000,
                "upscale": self.cfg.get("upscale", False),
                "useImageRef": True if image_b64 else False,
                "genMode":     self.cfg.get("gen_mode", "Video"),
                "resolution":  self.cfg.get("resolution", "720p"),
                "duration":    self.cfg.get("duration", "10s"),
                "aspectRatio": self.cfg.get("aspect_ratio", "9:16"),
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
            self.log(f"{prefix} ❌ Gagal __grokGenerate: {e}", "ERROR")
            self.set_status(0, "error")
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
            except Exception as e:
                time.sleep(2)
                continue

            if not state:
                time.sleep(1)
                continue

            status  = state.get("status", "idle")
            pct     = state.get("progress", 0)
            msg     = state.get("message", "")
            error   = state.get("error")

            if pct != last_pct:
                self.set_status(pct, "generating" if status == "running" else status)
                last_pct = pct

            if msg and msg != last_msg:
                self.log(f"{prefix} 💬 {msg}")
                last_msg = msg

            if status == "done":
                self.log(f"{prefix} ✅ Generasi selesai!")
                self.set_status(100, "downloading")
                break
            elif status == "error":
                self.log(f"{prefix} ❌ Error: {error or 'Unknown'}", "ERROR")
                self.set_status(0, "error")
                return None
            elif status == "rate_limited":
                self.log(f"{prefix} 🚫 RATE LIMIT!", "ERROR")
                self.set_status(0, "rate_limited")
                return "RATE_LIMITED"
            elif status == "cancelled":
                return None

            time.sleep(2)
        else:
            self.log(f"{prefix} ❌ Timeout", "ERROR")
            self.set_status(0, "error")
            return None

        if self._stop.is_set(): return None

        # Download video
        self.set_status(100, "downloading")
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
            self.log(f"{prefix} ❌ Video URL tidak ditemukan", "ERROR")
            self.set_status(0, "error")
            return None

        filename  = self.get_next_filename(output_dir)
        save_path = os.path.join(output_dir, filename)
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
                    self.set_status(100, "success")
                    # Navigate back to /imagine for next generation
                    try:
                        driver.get(GROK_URL)
                        self.log(f"{prefix} 🔄 Kembali ke /imagine")
                    except: pass
                    return save_path
                else:
                    try: os.remove(save_path)
                    except: pass
        except Exception as e:
            self.log(f"{prefix} ⚠️ Download error: {e}", "WARN")

        # Fallback file watcher
        dl_time = time.time()
        downloads_dir = os.path.expanduser("~/Downloads")
        for _ in range(60):
            time.sleep(1)
            if self._stop.is_set(): return None
            for chk in [output_dir, downloads_dir]:
                try:
                    mp4s = glob.glob(os.path.join(chk, "*.mp4"))
                    new  = [f for f in mp4s if os.path.getmtime(f) > dl_time - 2]
                    if new and not glob.glob(os.path.join(chk, "*.crdownload")):
                        newest = max(new, key=os.path.getmtime)
                        if os.path.getsize(newest) > 50000:
                            if newest != save_path:
                                shutil.move(newest, save_path)
                            self.log(f"{prefix} ✅ {filename} ({os.path.getsize(save_path)/1024/1024:.1f} MB)")
                            self.set_status(100, "success")
                            try:
                                driver.get(GROK_URL)
                                self.log(f"{prefix} 🔄 Kembali ke /imagine")
                            except: pass
                            return save_path
                except: pass

        self.log(f"{prefix} ❌ Download gagal", "ERROR")
        self.set_status(0, "error")
        return None

    # ── Start browser (called once) ──
    def start(self):
        """Launch Chrome and connect Selenium. Returns True if connected."""
        self.open_chrome()
        if self._stop.is_set(): return False

        driver = self.connect_selenium()
        if not driver:
            self.set_status(0, "error")
            return False
        self.driver = driver
        return True

    # ── Run a batch of tasks on this already-open browser ──
    def run_tasks(self, tasks):
        """
        tasks = list of (gen_num, prompt_text, image_path)
        Runs on self.driver (must be connected already)
        """
        driver     = self.driver
        output_dir = self.cfg["output_dir"]
        delay      = self.cfg.get("delay_between", 5)

        for task_idx, (gen_num, prompt_text, image_path) in enumerate(tasks):
            if self._stop.is_set(): break

            self.set_info("current_task", task_idx + 1)
            self.set_info("total_tasks",  len(tasks))

            result = self.do_single_generate(driver, gen_num, prompt_text, image_path, output_dir)

            if result == "RATE_LIMITED":
                self.log("🚫 Rate limit! Menunggu 2 menit...", "WARN")
                self.set_status(0, "rate_limited")
                for _ in range(120):
                    if self._stop.is_set(): break
                    time.sleep(1)
                if self._stop.is_set(): break
                result = self.do_single_generate(driver, gen_num, prompt_text, image_path, output_dir)
                if result == "RATE_LIMITED":
                    self.log("🚫 Rate limit masih aktif. Stop browser ini.", "ERROR")
                    break

            if result and result != "RATE_LIMITED":
                self.generated += 1
            else:
                self.failed += 1

            # Report totals
            self.stat_q.put({"browser_done": self.bid,
                             "generated": self.generated,
                             "failed": self.failed})

            # Delay between videos
            if task_idx < len(tasks) - 1 and not self._stop.is_set():
                self.log(f"⏳ Jeda {delay} detik...")
                for _ in range(delay):
                    if self._stop.is_set(): break
                    time.sleep(1)

    # ── Shutdown browser ──
    def shutdown(self):
        self.log(f"🏁 B{self.bid+1} total: {self.generated} OK, {self.failed} gagal")
        self.set_status(100 if self.generated > 0 else 0,
                        "success" if self.failed == 0 else "idle")
        try: self.driver.quit()
        except: pass
        self.kill_chrome()


# ════════════════════════════════════════════════════════════════════════════
#  MULTI-BROWSER AUTOMATION ENGINE
# ════════════════════════════════════════════════════════════════════════════
class AutomationEngine:
    def __init__(self, config, log_q, status_q):
        self.cfg    = config
        self.log_q  = log_q
        self.stat_q = status_q
        self._stop  = threading.Event()
        self._file_lock = threading.Lock()

    def stop(self):
        self._stop.set()

    def log(self, msg, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_q.put(f"[{ts}] [{level}] {msg}")

    def merge_videos_pairs(self, output_dir, merged_dir):
        def _sort_key(f):
            m = re.search(r'(\d+)', os.path.basename(f))
            return int(m.group(1)) if m else 0
        os.makedirs(merged_dir, exist_ok=True)
        all_files = sorted(
            [f for f in glob.glob(os.path.join(output_dir, "*.mp4"))
             if os.path.getsize(f) > 10240], key=_sort_key)
        if len(all_files) < 2:
            self.log("Merge: kurang dari 2 video, skip", "WARN")
            return
        pairs = [(all_files[i], all_files[i+1]) for i in range(0, len(all_files) - 1, 2)]
        self.log(f"🎬 Mulai merge {len(pairs)} pasang video...")
        for v1, v2 in pairs:
            if self._stop.is_set(): break
            merge_video_pair(v1, v2, merged_dir, log_fn=self.log)
        self.log(f"🎬 Merge selesai! Hasil di: {merged_dir}")
        self.stat_q.put({"merged_dir": merged_dir})

    def _prepare_user_data_dirs(self, base_ud, n_browsers):
        """
        Chrome requires exclusive lock on user-data-dir.
        Browser 0: uses base_ud directly.
        Browser 1+: copies base_ud to base_ud_b2, base_ud_b3, etc.
        Returns list of user-data-dir paths.
        """
        dirs = [base_ud]  # browser 0 uses original
        for i in range(1, n_browsers):
            # e.g. C:\tiktok_automation\user_data\1  →  C:\tiktok_automation\user_data\1_b2
            dest = f"{base_ud}_b{i+1}"
            if not os.path.exists(dest):
                self.log(f"📁 Menyalin profil Chrome untuk Browser {i+1}: {dest}")
                try:
                    shutil.copytree(base_ud, dest,
                                    ignore=shutil.ignore_patterns(
                                        'SingletonLock', 'SingletonCookie',
                                        'SingletonSocket', 'lockfile', 'Lock*'
                                    ))
                    self.log(f"✅ Profil B{i+1} siap")
                except Exception as e:
                    self.log(f"⚠️ Gagal copy profil: {e}", "WARN")
                    os.makedirs(dest, exist_ok=True)
            else:
                self.log(f"📁 Profil B{i+1} sudah ada: {dest}")
            dirs.append(dest)
        return dirs

    def run(self):
        if not SELENIUM_OK:
            self.log("Selenium tidak terinstall!", "ERROR")
            return

        cfg          = self.cfg
        n_browsers   = cfg["n_browsers"]
        n_videos     = cfg["n_videos"]
        n_cycles     = cfg["n_cycles"]
        prompts      = cfg["prompts"]
        output_dir   = cfg["output_dir"]
        merged_dir   = cfg.get("merged_dir", MERGED_DIR)
        bahan_folder = cfg.get("bahan_folder", "")
        use_image    = cfg.get("use_image", True)
        base_ud      = cfg.get("user_data_dir", DEFAULT_USER_DATA)

        os.makedirs(output_dir, exist_ok=True)

        # ── Step 1: Prepare separate user-data-dirs (Chrome locks each one) ──
        user_data_dirs = self._prepare_user_data_dirs(base_ud, n_browsers)
        if self._stop.is_set(): return

        # ── Step 2: Launch all browsers ONCE (persist across cycles) ──
        self.log(f"\n🚀 Meluncurkan {n_browsers} browser...")
        workers = []
        for b in range(n_browsers):
            if self._stop.is_set(): break
            worker_cfg = dict(cfg)
            worker_cfg["debug_port"]    = cfg["debug_port"] + b
            worker_cfg["user_data_dir"] = user_data_dirs[b]

            worker = BrowserWorker(b, worker_cfg, self.log_q, self.stat_q,
                                   self._stop, self._file_lock)
            if worker.start():
                workers.append(worker)
                self.log(f"✅ Browser {b+1} terhubung (port {worker.port})")
            else:
                self.log(f"❌ Browser {b+1} gagal start", "ERROR")
                workers.append(worker)  # keep for tracking

            time.sleep(3)  # stagger Chrome launches

        active_workers = [w for w in workers if w.driver is not None]
        if not active_workers:
            self.log("❌ Tidak ada browser yang berhasil terhubung!", "ERROR")
            return

        n_active = len(active_workers)
        self.log(f"\n✅ {n_active}/{n_browsers} browser aktif. Memulai generasi...")

        # ── Step 3: Run cycles ──
        total_target = n_videos * n_cycles

        for cycle in range(n_cycles):
            if self._stop.is_set(): break
            self.log(f"\n{'='*60}")
            self.log(f"=== SIKLUS {cycle+1}/{n_cycles} — {n_videos} video ÷ {n_active} browser ===")
            self.log(f"{'='*60}")
            self.stat_q.put({"cycle": cycle + 1})

            # Build task list for this cycle
            all_tasks = []
            for vid_idx in range(n_videos):
                gen_num     = cycle * n_videos + vid_idx
                prompt_text = prompts[vid_idx % len(prompts)]
                image_path  = None
                if use_image and bahan_folder:
                    image_path = get_random_bahan_image(bahan_folder)
                all_tasks.append((gen_num, prompt_text, image_path))

            # ── Fair contiguous distribution ──
            # 20 videos ÷ 4 browsers = [5, 5, 5, 5]
            # 22 videos ÷ 4 browsers = [6, 6, 5, 5]  (extras go to first browsers)
            browser_tasks = [[] for _ in range(n_active)]
            base_count = n_videos // n_active
            remainder  = n_videos % n_active
            idx = 0
            for b in range(n_active):
                count = base_count + (1 if b < remainder else 0)
                browser_tasks[b] = all_tasks[idx : idx + count]
                idx += count

            for b in range(n_active):
                self.log(f"  Browser {active_workers[b].bid+1}: {len(browser_tasks[b])} video")

            # ── Run all workers in parallel threads ──
            threads = []
            for b, worker in enumerate(active_workers):
                if not browser_tasks[b]:
                    continue
                t = threading.Thread(target=worker.run_tasks,
                                     args=(browser_tasks[b],), daemon=True)
                threads.append(t)

            for t in threads:
                t.start()

            # Wait for all threads to finish this cycle
            for t in threads:
                t.join()

            if self._stop.is_set(): break

            # Summarize cycle
            cycle_gen  = sum(w.generated for w in active_workers)
            cycle_fail = sum(w.failed for w in active_workers)
            self.log(f"\nSiklus {cycle+1} selesai: {cycle_gen} total OK, {cycle_fail} total gagal")

            # Delay between cycles
            if cycle < n_cycles - 1 and not self._stop.is_set():
                self.log("⏳ Jeda antar siklus (10 detik)...")
                for _ in range(10):
                    if self._stop.is_set(): break
                    time.sleep(1)

        # ── Step 4: Shutdown all browsers ──
        for w in workers:
            try: w.shutdown()
            except: pass

        total_gen  = sum(w.generated for w in workers)
        total_fail = sum(w.failed for w in workers)

        if self._stop.is_set():
            self.log("⛔ Dihentikan oleh user.", "WARN")
        else:
            self.log(f"\n🎉 SEMUA SELESAI! Total: {total_gen} berhasil, {total_fail} gagal")
            if cfg.get("merge_videos", True):
                self.merge_videos_pairs(output_dir, merged_dir)
            self.stat_q.put({"done": True, "total_generated": total_gen, "total_failed": total_fail})


# ════════════════════════════════════════════════════════════════════════════
#  MAIN GUI
# ════════════════════════════════════════════════════════════════════════════
class SuperGrokApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🚀 SuperGrok V2 — Multi-Browser Generator")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.state("zoomed")

        self.prompts       = load_prompts_db()
        self.engine        = None
        self.engine_thread = None
        self.log_q         = queue.Queue()
        self.stat_q        = queue.Queue()
        self._running      = False
        self.browser_rows  = []  # list of dicts for each browser row

        self._apply_style()
        self._build_ui()
        self._refresh_output_folder()
        self.after(300, self._poll_queues)

    # ── Style ──
    def _apply_style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("TFrame",       background=BG)
        st.configure("Card.TFrame",  background=CARD)
        st.configure("Card2.TFrame", background=CARD2)
        st.configure("TLabel",       background=BG,    foreground=TEXT,   font=("Segoe UI", 10))
        st.configure("Card.TLabel",  background=CARD,  foreground=TEXT,   font=("Segoe UI", 10))
        st.configure("Card2.TLabel", background=CARD2, foreground=TEXT,   font=("Segoe UI", 10))
        st.configure("Title.TLabel", background=BG,    foreground=TEXT,   font=("Segoe UI", 20, "bold"))
        st.configure("Head.TLabel",  background=CARD,  foreground=ACCENT, font=("Segoe UI", 11, "bold"))
        st.configure("Accent.TButton", background=ACCENT, foreground="#FFFFFF",
                     font=("Segoe UI", 11, "bold"), borderwidth=0, relief="flat", padding=(16, 8))
        st.map("Accent.TButton",
               background=[("active", "#8B83FF"), ("disabled", CARD2)],
               foreground=[("disabled", MUTED)])
        st.configure("Stop.TButton", background=RED, foreground="#FFFFFF",
                     font=("Segoe UI", 11, "bold"), borderwidth=0, relief="flat", padding=(16, 8))
        st.map("Stop.TButton", background=[("active", "#FF6B6B")])
        st.configure("Flat.TButton", background=CARD2, foreground=TEXT,
                     font=("Segoe UI", 10), borderwidth=0, relief="flat", padding=(10, 6))
        st.map("Flat.TButton", background=[("active", BORDER)])
        st.configure("TNotebook",      background=BG,    borderwidth=0)
        st.configure("TNotebook.Tab",  background=CARD2, foreground=MUTED, padding=(14, 6), font=("Segoe UI", 10))
        st.map("TNotebook.Tab",
               background=[("selected", CARD), ("active", BORDER)],
               foreground=[("selected", ACCENT)])
        st.configure("TEntry",   fieldbackground=CARD2, background=CARD2, foreground=TEXT,
                     insertcolor=TEXT, borderwidth=0, font=("Segoe UI", 10))
        st.configure("TSpinbox", fieldbackground=CARD2, background=CARD2, foreground=TEXT,
                     insertcolor=TEXT, borderwidth=0, font=("Segoe UI", 10))
        st.configure("TCheckbutton", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
        st.map("TCheckbutton", background=[("active", CARD)], foreground=[("active", ACCENT)])
        st.configure("Gen.Horizontal.TProgressbar",     troughcolor=CARD2, background=ACCENT,  thickness=14, borderwidth=0)
        st.configure("Success.Horizontal.TProgressbar", troughcolor=CARD2, background=GREEN,   thickness=14, borderwidth=0)
        st.configure("Error.Horizontal.TProgressbar",   troughcolor=CARD2, background=RED,     thickness=14, borderwidth=0)
        st.configure("Treeview",         background=CARD2, fieldbackground=CARD2, foreground=TEXT, rowheight=22, font=("Segoe UI", 9))
        st.configure("Treeview.Heading", background=CARD,  foreground=ACCENT, font=("Segoe UI", 9, "bold"), relief="flat")
        st.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#FFF")])

    # ── Build UI ──
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=12)
        hdr.pack(fill="x", padx=20)
        tk.Label(hdr, text="🚀 SuperGrok V2", bg=BG, fg=TEXT,
                 font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(hdr, text="  Multi-browser parallel • grok_autoV2.js",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left", pady=4)

        badge_frame = tk.Frame(hdr, bg=BG)
        badge_frame.pack(side="right")
        self.cycle_badge = tk.Label(badge_frame, text="Siklus: –", bg=ACCENT, fg="#FFF",
                                    font=("Segoe UI", 10, "bold"), padx=10, pady=4)
        self.cycle_badge.pack(side="right", padx=(4, 0))
        self.gen_badge = tk.Label(badge_frame, text="✅ 0 video", bg=GREEN, fg="#000",
                                   font=("Segoe UI", 10, "bold"), padx=10, pady=4)
        self.gen_badge.pack(side="right", padx=(4, 0))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20)

        # Action bar (bottom)
        bar = tk.Frame(self, bg=CARD, pady=10)
        bar.pack(side="bottom", fill="x", padx=12, pady=(0, 8))
        self.btn_generate = ttk.Button(bar, text="▶  Mulai Generate",
                                       style="Accent.TButton", command=self._on_generate)
        self.btn_generate.pack(side="left", padx=(16, 8))
        self.btn_stop = ttk.Button(bar, text="⏹  Stop",
                                   style="Stop.TButton", command=self._on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        self.status_lbl = tk.Label(bar, text="⬤  Idle", bg=CARD, fg=MUTED,
                                   font=("Segoe UI", 11, "bold"))
        self.status_lbl.pack(side="left", padx=16)
        tk.Frame(self, bg=BORDER, height=1).pack(side="bottom", fill="x", padx=12)

        # Main container
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)
        left  = tk.Frame(main, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_config_panel(left)
        self._build_browser_monitor(left)
        self._build_prompt_panel(right)
        self._build_output_panel(right)
        self._build_log_panel(right)

    # ── Config Panel ──
    def _build_config_panel(self, parent):
        card = tk.Frame(parent, bg=CARD, bd=0, pady=10, padx=14)
        card.pack(fill="x", pady=(0, 8))

        tk.Label(card, text="⚙  Konfigurasi", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))

        lkw = dict(bg=CARD, fg=MUTED, font=("Segoe UI", 9))

        # Row 1: Browsers, Videos per cycle, Cycles
        tk.Label(card, text="Jumlah Browser:", **lkw).grid(row=1, column=0, sticky="w")
        self.var_browsers = tk.IntVar(value=1)
        ttk.Spinbox(card, from_=1, to=10, textvariable=self.var_browsers, width=4
                     ).grid(row=1, column=1, padx=(4, 16), sticky="w")

        tk.Label(card, text="Video per Siklus:", **lkw).grid(row=1, column=2, sticky="w")
        self.var_videos = tk.IntVar(value=5)
        ttk.Spinbox(card, from_=1, to=100, textvariable=self.var_videos, width=6
                     ).grid(row=1, column=3, padx=(4, 16), sticky="w")

        tk.Label(card, text="Jumlah Siklus:", **lkw).grid(row=1, column=4, sticky="w")
        self.var_cycles = tk.IntVar(value=3)
        ttk.Spinbox(card, from_=1, to=9999, textvariable=self.var_cycles, width=6
                     ).grid(row=1, column=5, padx=4, sticky="w")

        # Row 2: Port, Delay
        tk.Label(card, text="Base Debug Port:", **lkw).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.var_port = tk.IntVar(value=DEFAULT_PORT)
        ttk.Spinbox(card, from_=1024, to=65535, textvariable=self.var_port, width=7
                     ).grid(row=2, column=1, padx=(4, 16), sticky="w", pady=(8, 0))

        tk.Label(card, text="Jeda (detik):", **lkw).grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.var_delay = tk.IntVar(value=5)
        ttk.Spinbox(card, from_=0, to=300, textvariable=self.var_delay, width=6
                     ).grid(row=2, column=3, padx=(4, 16), sticky="w", pady=(8, 0))

        # Row 3: Chrome Path
        tk.Label(card, text="Chrome Path:", **lkw).grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.var_chrome = tk.StringVar(value=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        ttk.Entry(card, textvariable=self.var_chrome, width=35
                  ).grid(row=3, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(8, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_file(self.var_chrome)
                   ).grid(row=3, column=5, padx=(0, 4), pady=(8, 0))

        # Row 4: User Data Dir (SHARED across all browsers)
        tk.Label(card, text="User Data Dir:", **lkw).grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.var_ud = tk.StringVar(value=DEFAULT_USER_DATA)
        ttk.Entry(card, textvariable=self.var_ud, width=35
                  ).grid(row=4, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_dir(self.var_ud)
                   ).grid(row=4, column=5, padx=(0, 4), pady=(4, 0))

        # Row 5+6: Output, Merged Dir
        tk.Label(card, text="Output Dir:", **lkw).grid(row=5, column=0, sticky="w", pady=(4, 0))
        self.var_outdir = tk.StringVar(value=OUTPUT_DIR)
        ttk.Entry(card, textvariable=self.var_outdir, width=35
                  ).grid(row=5, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_dir(self.var_outdir)
                   ).grid(row=5, column=5, padx=(0, 4), pady=(4, 0))

        tk.Label(card, text="Merged Dir:", **lkw).grid(row=6, column=0, sticky="w", pady=(4, 0))
        self.var_mergeddir = tk.StringVar(value=MERGED_DIR)
        ttk.Entry(card, textvariable=self.var_mergeddir, width=35
                  ).grid(row=6, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_dir(self.var_mergeddir)
                   ).grid(row=6, column=5, padx=(0, 4), pady=(4, 0))

        # Row 7: Bahan Folder
        tk.Label(card, text="Folder Bahan:", **lkw).grid(row=7, column=0, sticky="w", pady=(4, 0))
        self.var_bahan_folder = tk.StringVar(value="")
        self._bahan_cb = ttk.Combobox(card, textvariable=self.var_bahan_folder, width=20, state="readonly")
        self._bahan_cb.grid(row=7, column=1, columnspan=2, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="🔄", style="Flat.TButton", width=3,
                   command=self._refresh_bahan_list).grid(row=7, column=3, padx=(0, 4), pady=(4, 0))
        self._refresh_bahan_list()

        # Row 8-10: Video Settings
        tk.Frame(card, bg=BORDER, height=1).grid(row=8, column=0, columnspan=6, sticky="ew", pady=(10, 6))
        tk.Label(card, text="🎬  Video Settings", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).grid(row=9, column=0, columnspan=6, sticky="w", pady=(0, 4))

        vs_f = tk.Frame(card, bg=CARD)
        vs_f.grid(row=10, column=0, columnspan=6, sticky="w", pady=(2, 0))

        tk.Label(vs_f, text="Mode:", **lkw).pack(side="left")
        self.var_gen_mode = tk.StringVar(value="Video")
        ttk.Combobox(vs_f, textvariable=self.var_gen_mode, values=["Video", "Image"],
                     width=8, state="readonly").pack(side="left", padx=(4, 16))

        tk.Label(vs_f, text="Resolusi:", **lkw).pack(side="left")
        self.var_resolution = tk.StringVar(value="720p")
        ttk.Combobox(vs_f, textvariable=self.var_resolution, values=["480p", "720p"],
                     width=6, state="readonly").pack(side="left", padx=(4, 16))

        tk.Label(vs_f, text="Durasi:", **lkw).pack(side="left")
        self.var_duration = tk.StringVar(value="10s")
        ttk.Combobox(vs_f, textvariable=self.var_duration, values=["6s", "10s"],
                     width=5, state="readonly").pack(side="left", padx=(4, 16))

        tk.Label(vs_f, text="Rasio:", **lkw).pack(side="left")
        self.var_aspect_ratio = tk.StringVar(value="9:16")
        ttk.Combobox(vs_f, textvariable=self.var_aspect_ratio,
                     values=["9:16", "16:9", "1:1", "4:5", "3:4"],
                     width=6, state="readonly").pack(side="left", padx=(4, 0))

        # Row 11: Checkboxes
        chk_f = tk.Frame(card, bg=CARD)
        chk_f.grid(row=11, column=0, columnspan=6, sticky="w", pady=(8, 0))

        self.var_use_image = tk.BooleanVar(value=True)
        ttk.Checkbutton(chk_f, text="📷 Gunakan Gambar",
                        variable=self.var_use_image, style="TCheckbutton"
                        ).pack(side="left", padx=(0, 16))

        self.var_upscale = tk.BooleanVar(value=False)
        ttk.Checkbutton(chk_f, text="🔍 Upscale HD",
                        variable=self.var_upscale, style="TCheckbutton"
                        ).pack(side="left", padx=(0, 16))

        self.var_headless = tk.BooleanVar(value=False)
        ttk.Checkbutton(chk_f, text="🖥️ Headless (--headless=new)",
                        variable=self.var_headless, style="TCheckbutton"
                        ).pack(side="left", padx=(0, 16))

        # Row 12: Merge
        mrg_f = tk.Frame(card, bg=CARD)
        mrg_f.grid(row=12, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self.var_merge_videos = tk.BooleanVar(value=True)
        ttk.Checkbutton(mrg_f, style="TCheckbutton",
                        text="🎬 Gabungkan 2 Video → 1 setelah semua siklus",
                        variable=self.var_merge_videos).pack(side="left")

        card.columnconfigure(1, weight=1)
        card.columnconfigure(3, weight=1)

    def _refresh_bahan_list(self):
        folders = list_bahan_folders()
        self._bahan_cb["values"] = folders
        if folders and not self.var_bahan_folder.get():
            self.var_bahan_folder.set(folders[0])

    # ── Browser Monitor Panel ──
    def _build_browser_monitor(self, parent):
        outer = tk.Frame(parent, bg=CARD, pady=14, padx=14)
        outer.pack(fill="both", expand=True, pady=(0, 8))

        tk.Label(outer, text="📊  Browser Monitor", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 10))

        canvas = tk.Canvas(outer, bg=CARD, highlightthickness=0)
        vsb    = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.monitor_frame = tk.Frame(canvas, bg=CARD)
        win_id = canvas.create_window((0, 0), window=self.monitor_frame, anchor="nw")

        def _on_resize(e): canvas.itemconfig(win_id, width=e.width)
        canvas.bind("<Configure>", _on_resize)
        def _on_frame_cfg(e): canvas.configure(scrollregion=canvas.bbox("all"))
        self.monitor_frame.bind("<Configure>", _on_frame_cfg)

        self._rebuild_browser_rows(1)

    def _rebuild_browser_rows(self, n):
        for w in self.monitor_frame.winfo_children():
            w.destroy()
        self.browser_rows = []

        for i in range(n):
            color = BROWSER_COLORS[i % len(BROWSER_COLORS)]

            row = tk.Frame(self.monitor_frame, bg=CARD, pady=6)
            row.pack(fill="x", padx=2, pady=(0, 4))

            # Color indicator + Browser label
            indicator = tk.Label(row, text="●", bg=CARD, fg=color,
                                 font=("Segoe UI", 14, "bold"))
            indicator.pack(side="left", padx=(0, 4))

            name_lbl = tk.Label(row, text=f"Browser {i+1}", bg=CARD, fg=TEXT,
                                font=("Segoe UI", 10, "bold"), width=10, anchor="w")
            name_lbl.pack(side="left")

            # Progress bar
            bar = ttk.Progressbar(row, style="Gen.Horizontal.TProgressbar",
                                  orient="horizontal", length=200, maximum=100)
            bar.pack(side="left", padx=(4, 8), fill="x", expand=True)

            # Percent
            pct_lbl = tk.Label(row, text="0%", bg=CARD, fg=MUTED,
                               font=("Segoe UI", 10, "bold"), width=5)
            pct_lbl.pack(side="left")

            # Status
            stat_lbl = tk.Label(row, text="idle", bg=CARD, fg=MUTED,
                                font=("Segoe UI", 9, "bold"), width=12, anchor="w")
            stat_lbl.pack(side="left", padx=(4, 4))

            # Task counter
            task_lbl = tk.Label(row, text="–/–", bg=CARD, fg=MUTED,
                                font=("Segoe UI", 9), width=6)
            task_lbl.pack(side="left")

            # OK count
            ok_lbl = tk.Label(row, text="✅0", bg=CARD, fg=GREEN,
                              font=("Segoe UI", 9, "bold"), width=5)
            ok_lbl.pack(side="left", padx=(4, 0))

            self.browser_rows.append({
                "bar": bar, "pct": pct_lbl, "status": stat_lbl,
                "task": task_lbl, "ok": ok_lbl, "indicator": indicator,
                "color": color
            })

    # ── Prompt Panel ──
    def _build_prompt_panel(self, parent):
        card = tk.Frame(parent, bg=CARD, pady=10, padx=14)
        card.pack(fill="both", expand=True, pady=(0, 8))

        hdr = tk.Frame(card, bg=CARD)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📝  Prompts", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(hdr, text="💾 Save",   style="Flat.TButton", command=self._save_prompts).pack(side="right", padx=2)
        ttk.Button(hdr, text="＋ Tambah", style="Flat.TButton", command=self._add_prompt).pack(side="right", padx=2)
        ttk.Button(hdr, text="－ Hapus",  style="Flat.TButton", command=self._remove_prompt).pack(side="right", padx=2)

        self.prompt_nb    = ttk.Notebook(card)
        self.prompt_texts = []
        self.prompt_nb.pack(fill="both", expand=True, pady=(8, 0))
        for idx, p in enumerate(self.prompts):
            self._add_prompt_tab(f"Prompt {idx+1}", p)

    def _add_prompt_tab(self, title, content=""):
        frm = tk.Frame(self.prompt_nb, bg=CARD)
        txt = scrolledtext.ScrolledText(frm, wrap="word", height=9,
                                        bg=CARD2, fg=TEXT, insertbackground=TEXT,
                                        font=("Consolas", 9), relief="flat", selectbackground=ACCENT)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", content)
        self.prompt_nb.add(frm, text=title)
        self.prompt_texts.append(txt)

    def _save_prompts(self):
        ps = [t.get("1.0", "end").strip() for t in self.prompt_texts]
        save_prompts_db(ps)
        self._append_log(f"💾 Prompts tersimpan ({len(ps)} prompt)")

    def _add_prompt(self):
        idx = len(self.prompt_texts) + 1
        self._add_prompt_tab(f"Prompt {idx}")
        self.prompts.append("")
        self._save_prompts()

    def _remove_prompt(self):
        if len(self.prompt_texts) <= 1:
            messagebox.showwarning("Warning", "Minimal 1 prompt harus ada.")
            return
        last = len(self.prompt_texts) - 1
        self.prompt_nb.forget(last)
        self.prompt_texts.pop()
        self.prompts.pop()
        self._save_prompts()

    # ── Output Panel ──
    def _build_output_panel(self, parent):
        card = tk.Frame(parent, bg=CARD2, pady=10, padx=14)
        card.pack(fill="x", pady=(0, 8))

        hdr = tk.Frame(card, bg=CARD2)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📁  Output Terbaru", bg=CARD2, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(hdr, text="🔄 Refresh", style="Flat.TButton",
                   command=self._refresh_output_folder).pack(side="right")
        ttk.Button(hdr, text="📂 Buka", style="Flat.TButton",
                   command=self._open_output_dir).pack(side="right", padx=4)

        frm = tk.Frame(card, bg=CARD2)
        frm.pack(fill="both", pady=(6, 0))
        cols = ("File", "Ukuran", "Waktu")
        self.out_tree = ttk.Treeview(frm, columns=cols, show="headings", height=5)
        for c in cols: self.out_tree.heading(c, text=c)
        self.out_tree.column("File",   width=160)
        self.out_tree.column("Ukuran", width=80, anchor="e")
        self.out_tree.column("Waktu",  width=130, anchor="center")
        vsb2 = ttk.Scrollbar(frm, orient="vertical", command=self.out_tree.yview)
        self.out_tree.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side="right", fill="y")
        self.out_tree.pack(fill="both", expand=True)

    # ── Log Panel ──
    def _build_log_panel(self, parent):
        card = tk.Frame(parent, bg=CARD, pady=10, padx=14)
        card.pack(fill="both", expand=True)
        hdr = tk.Frame(card, bg=CARD)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📋  Log", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(hdr, text="🗑 Clear", style="Flat.TButton",
                   command=lambda: (self.log_box.configure(state="normal"),
                                   self.log_box.delete("1.0", "end"),
                                   self.log_box.configure(state="disabled"))
                   ).pack(side="right")
        self.log_box = scrolledtext.ScrolledText(card, state="disabled",
                                                  bg=BG, fg=TEXT, font=("Consolas", 9),
                                                  relief="flat", height=10, insertbackground=TEXT,
                                                  selectbackground=ACCENT)
        self.log_box.pack(fill="both", expand=True, pady=(6, 0))
        self.log_box.tag_config("INFO",  foreground=TEXT)
        self.log_box.tag_config("WARN",  foreground=YELLOW)
        self.log_box.tag_config("ERROR", foreground=RED)
        self.log_box.tag_config("OK",    foreground=GREEN)

    # ── Helpers ──
    def _browse_dir(self, var):
        d = filedialog.askdirectory()
        if d: var.set(d.replace("/", "\\"))

    def _browse_file(self, var):
        f = filedialog.askopenfilename(filetypes=[("Executables", "*.exe"), ("All", "*.*")])
        if f: var.set(f)

    def _append_log(self, msg):
        tag = "INFO"
        if "✅" in msg or "selesai" in msg.lower() or "🎉" in msg: tag = "OK"
        elif "[WARN]" in msg or "⚠" in msg: tag = "WARN"
        elif "[ERROR]" in msg or "❌" in msg or "🚫" in msg: tag = "ERROR"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _refresh_output_folder(self):
        d = self.var_outdir.get() if hasattr(self, "var_outdir") else OUTPUT_DIR
        if not os.path.exists(d): return
        files = sorted(glob.glob(os.path.join(d, "*.mp4")), key=os.path.getmtime, reverse=True)
        self.out_tree.delete(*self.out_tree.get_children())
        for f in files[:30]:
            sz  = os.path.getsize(f)
            szs = f"{sz/1024/1024:.2f} MB" if sz > 1048576 else f"{sz//1024} KB"
            mt  = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M")
            self.out_tree.insert("", "end", values=(os.path.basename(f), szs, mt))

    def _open_output_dir(self):
        d = self.var_outdir.get()
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    def _collect_prompts(self):
        ps = [t.get("1.0", "end").strip() for t in self.prompt_texts]
        return [p for p in ps if p] or [DEFAULT_PROMPT_1]

    # ── Generate / Stop ──
    def _on_generate(self):
        if self._running: return

        if not os.path.exists(JS_FILE):
            messagebox.showerror("File Tidak Ditemukan",
                                 f"grok_autoV2.js tidak ditemukan di:\n{JS_FILE}")
            return

        prompts    = self._collect_prompts()
        n_browsers = self.var_browsers.get()
        n_videos   = self.var_videos.get()
        n_cycles   = self.var_cycles.get()

        cfg = {
            "prompts":         prompts,
            "n_browsers":      n_browsers,
            "n_videos":        n_videos,
            "n_cycles":        n_cycles,
            "delay_between":   self.var_delay.get(),
            "debug_port":      self.var_port.get(),
            "chrome_path":     self.var_chrome.get(),
            "user_data_dir":   self.var_ud.get(),
            "output_dir":      self.var_outdir.get(),
            "merged_dir":      self.var_mergeddir.get(),
            "merge_videos":    self.var_merge_videos.get(),
            "bahan_folder":    self.var_bahan_folder.get(),
            "use_image":       self.var_use_image.get(),
            "upscale":         self.var_upscale.get(),
            "headless":        self.var_headless.get(),
            "gen_mode":        self.var_gen_mode.get(),
            "resolution":      self.var_resolution.get(),
            "duration":        self.var_duration.get(),
            "aspect_ratio":    self.var_aspect_ratio.get(),
        }

        # Rebuild browser monitor rows
        self._rebuild_browser_rows(n_browsers)

        self._total_generated = 0

        self.engine        = AutomationEngine(cfg, self.log_q, self.stat_q)
        self.engine_thread = threading.Thread(target=self.engine.run, daemon=True)
        self.engine_thread.start()
        self._running = True
        self.btn_generate.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.status_lbl.configure(text="⬤  Running", fg=GREEN)
        self._append_log(f"▶ SuperGrok V2 dimulai: {n_browsers} browser × {n_videos} video × {n_cycles} siklus")

    def _on_stop(self):
        if self.engine: self.engine.stop()
        self._set_idle()
        self._append_log("⛔ Stop diminta.")

    def _set_idle(self):
        self._running = False
        self.btn_generate.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status_lbl.configure(text="⬤  Idle", fg=MUTED)

    # ── Queue Polling ──
    def _poll_queues(self):
        # Log queue
        try:
            while True:
                msg = self.log_q.get_nowait()
                self._append_log(msg)
        except queue.Empty: pass

        # Status queue
        try:
            while True:
                ev = self.stat_q.get_nowait()

                # Per-browser progress
                if "browser" in ev:
                    b = ev["browser"]
                    if b < len(self.browser_rows):
                        row = self.browser_rows[b]

                        if "pct" in ev and "status" in ev:
                            pct    = ev["pct"]
                            status = ev["status"]
                            color  = STATUS_COLORS.get(status, MUTED)

                            row["bar"]["value"] = pct
                            row["pct"].configure(text=f"{pct}%", fg=color)
                            row["status"].configure(text=status, fg=color)

                            if status == "success":
                                row["bar"].configure(style="Success.Horizontal.TProgressbar")
                            elif status in ("error", "rate_limited", "stopped"):
                                row["bar"].configure(style="Error.Horizontal.TProgressbar")
                            else:
                                row["bar"].configure(style="Gen.Horizontal.TProgressbar")

                        if "current_task" in ev:
                            ct = ev["current_task"]
                            tt = ev.get("total_tasks", "?")
                            row["task"].configure(text=f"{ct}/{tt}")

                # Browser done event (with OK count)
                if "browser_done" in ev:
                    b = ev["browser_done"]
                    gen = ev.get("generated", 0)
                    if b < len(self.browser_rows):
                        self.browser_rows[b]["ok"].configure(text=f"✅{gen}")
                    # Update global badge
                    self._total_generated = sum(
                        int(self.browser_rows[i]["ok"].cget("text").replace("✅", "") or "0")
                        for i in range(len(self.browser_rows))
                    )
                    self.gen_badge.configure(text=f"✅ {self._total_generated} video")

                if "cycle" in ev:
                    self.cycle_badge.configure(text=f"Siklus: {ev['cycle']}")

                if ev.get("done"):
                    self._set_idle()
                    self._refresh_output_folder()
                    tg = ev.get("total_generated", 0)
                    tf = ev.get("total_failed", 0)
                    self.gen_badge.configure(text=f"✅ {tg} video")
                    info = (f"Semua siklus selesai!\n"
                            f"Berhasil: {tg}, Gagal: {tf}\n"
                            f"Output: {self.var_outdir.get()}")
                    messagebox.showinfo("🎉 Selesai!", info)

                if "merged_dir" in ev and not ev.get("done"):
                    self._append_log(f"🎬 Merge tersimpan di: {ev['merged_dir']}")

        except queue.Empty: pass

        # Auto-refresh output
        if self._running:
            if not hasattr(self, "_last_ref"): self._last_ref = time.time()
            if time.time() - self._last_ref > 15:
                self._refresh_output_folder()
                self._last_ref = time.time()

        # Thread died check
        if self._running and self.engine_thread and not self.engine_thread.is_alive():
            self._set_idle()
            self._append_log("Thread selesai.")

        self.after(300, self._poll_queues)


# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = SuperGrokApp()
    app.mainloop()
