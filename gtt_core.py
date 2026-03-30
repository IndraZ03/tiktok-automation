"""
GTT Core — Grok TikTok Bot Engine
Database, Grok generation, video merge, TikTok upload helpers.
"""
import os, sys, re, time, shutil, subprocess, json, threading, random, glob, copy, logging
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

sys.path.insert(0, r"c:\tiktok_automation")
from tiktok_gui import open_chrome_debug, connect_selenium, navigate_upload_page, do_post_video, inject_video_file

APP_DIR = r"C:\tiktok_automation"
USER_DATA_BASE = os.path.join(APP_DIR, "user_data")
BAHAN_DIR = os.path.join(APP_DIR, "bahan")
PROMPTS_FILE = os.path.join(APP_DIR, "grok_prompts.json")
DB_FILE = os.path.join(APP_DIR, "gtt_db.json")
GROK_URL = "https://grok.com/imagine"
RAW_DIR = os.path.join(APP_DIR, "gtt_raw")
TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"

# JS automation files
GROK_JS_FILE = os.path.join(APP_DIR, "grok_auto.js")
TIKTOK_JS_FILE = os.path.join(APP_DIR, "tiktok_auto.js")

def inject_js(driver, js_file):
    """Read and inject a JS file into the current page."""
    with open(js_file, 'r', encoding='utf-8') as f:
        js_code = f.read()
    driver.execute_script(js_code)

logger = logging.getLogger(__name__)

class GrokRateLimitError(Exception):
    """Raised when Grok rate limit is reached ("Rate limit reached / Upgrade to SuperGrok")."""
    pass


def resolve_ud_path(val):
    val = val.strip()
    if not val: return ""
    if ":" in val or val.startswith("\\") or val.startswith("/"):
        return os.path.normpath(val)
    return os.path.normpath(os.path.join(USER_DATA_BASE, val))

def _find_bin(name):
    found = shutil.which(name)
    if found: return found
    for c in [os.path.expanduser(rf"~\AppData\Local\Microsoft\WinGet\Links\{name}.exe"),
              rf"C:\ffmpeg\bin\{name}.exe", os.path.join(APP_DIR, f"{name}.exe")]:
        if os.path.isfile(c): return c
    return name

FFMPEG_PATH = _find_bin("ffmpeg")
FFPROBE_PATH = _find_bin("ffprobe")

# ═══════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════
_DEFAULT_UD_CONFIG = {
    "prompt_name": "",
    "bahan_folder": "",
    "deskripsi": "",
    "hashtags": [],
    "nama_produk_radio": "",
    "nama_produk_radio_list": [],
    "nama_produk_input": "beli sebelum promonya habis",
    "add_product": True,
    "add_sound": False,
    "interval_hours": 5,
    "batch_size": 30,
    "tiktok_ud": "",
    "tiktok_port": "",
    "schedule": {"tanggal": "", "jam": "02", "menit": "00"},
}

_DEFAULT_DB = {
    "active_ud": [1, 2],
    "grok_ud": os.path.join(USER_DATA_BASE, "gtt_grok"),
    "grok_port": "9270",
    "ud_configs": {},
}

_UD_TIKTOK_DEFAULTS = {
    1: {"tiktok_ud": os.path.join(USER_DATA_BASE, "1"), "tiktok_port": "9222"},
    2: {"tiktok_ud": os.path.join(USER_DATA_BASE, "2"), "tiktok_port": "9223"},
    3: {"tiktok_ud": os.path.join(USER_DATA_BASE, "3"), "tiktok_port": "9224"},
    4: {"tiktok_ud": os.path.join(USER_DATA_BASE, "4"), "tiktok_port": "9225"},
}

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return copy.deepcopy(_DEFAULT_DB)

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

def get_ud_config(db, ud_num):
    key = str(ud_num)
    if key not in db.get("ud_configs", {}):
        cfg = copy.deepcopy(_DEFAULT_UD_CONFIG)
        defaults = _UD_TIKTOK_DEFAULTS.get(ud_num, {})
        cfg["tiktok_ud"] = defaults.get("tiktok_ud", os.path.join(USER_DATA_BASE, str(ud_num)))
        cfg["tiktok_port"] = defaults.get("tiktok_port", str(9221 + ud_num))
        now = datetime.now()
        cfg["schedule"]["tanggal"] = now.strftime("%Y-%m-%d")
        db.setdefault("ud_configs", {})[key] = cfg
    return db["ud_configs"][key]

def stok_dir(ud_num):
    d = os.path.join(APP_DIR, "gtt_stok", f"ud_{ud_num}")
    os.makedirs(d, exist_ok=True)
    return d

def count_stok(ud_num):
    d = stok_dir(ud_num)
    return len([f for f in os.listdir(d) if f.endswith(".mp4")])

def list_stok(ud_num):
    d = stok_dir(ud_num)
    files = sorted(glob.glob(os.path.join(d, "*.mp4")), key=os.path.getmtime)
    return files

def schedule_file(ud_num):
    return os.path.join(APP_DIR, f"gtt_schedule_ud_{ud_num}.json")

def load_ud_schedule(ud_num):
    f = schedule_file(ud_num)
    if os.path.exists(f):
        try:
            with open(f, "r", encoding="utf-8") as fh: return json.load(fh)
        except: pass
    return []

def save_ud_schedule(ud_num, sched):
    with open(schedule_file(ud_num), "w", encoding="utf-8") as f:
        json.dump(sched, f, indent=2, ensure_ascii=False)

# ═══════════════════════════════════════════════════════════════
#  PROMPTS & BAHAN
# ═══════════════════════════════════════════════════════════════
def load_prompts():
    if os.path.exists(PROMPTS_FILE):
        try:
            with open(PROMPTS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def save_prompts(prompts):
    with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(prompts, f, indent=2, ensure_ascii=False)

def list_bahan_folders():
    if not os.path.isdir(BAHAN_DIR): return []
    return sorted([d for d in os.listdir(BAHAN_DIR) if os.path.isdir(os.path.join(BAHAN_DIR, d))])

def list_bahan_images(folder_name):
    d = os.path.join(BAHAN_DIR, folder_name)
    if not os.path.isdir(d): return []
    exts = {".jpg",".jpeg",".png",".gif",".webp",".bmp"}
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if os.path.splitext(f)[1].lower() in exts]

def get_random_bahan_image(folder_name):
    imgs = list_bahan_images(folder_name)
    return random.choice(imgs) if imgs else None

def escape_html(t):
    return str(t).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

# ═══════════════════════════════════════════════════════════════
#  CHROME CLEANUP — clear cache & history, keep cookies
# ═══════════════════════════════════════════════════════════════
def clear_chrome_data(user_data_dir):
    """Clear Chrome cache & history but keep cookies & login data."""
    profile_dir = os.path.join(user_data_dir, "Default")
    if not os.path.isdir(profile_dir):
        return
    # --- Hapus cache directories ---
    cache_dirs = [
        "Cache", "Code Cache", "GPUCache", "DawnCache",
        "GrShaderCache", "ShaderCache",
        os.path.join("Service Worker", "CacheStorage"),
    ]
    for d in cache_dirs:
        target = os.path.join(profile_dir, d)
        if os.path.isdir(target):
            try: shutil.rmtree(target, ignore_errors=True)
            except Exception: pass
    for d in ["ShaderCache", "GrShaderCache"]:
        target = os.path.join(user_data_dir, d)
        if os.path.isdir(target):
            try: shutil.rmtree(target, ignore_errors=True)
            except Exception: pass
    # --- Hapus history & browsing data files (bukan cookies!) ---
    history_files = [
        "History", "History-journal",
        "Top Sites", "Top Sites-journal",
        "Visited Links", "Visited Links-journal",
        "Web Data", "Web Data-journal",
        "Shortcuts", "Shortcuts-journal",
        "Network Action Predictor", "Network Action Predictor-journal",
        "Favicons", "Favicons-journal",
    ]
    for f in history_files:
        target = os.path.join(profile_dir, f)
        if os.path.isfile(target):
            try: os.remove(target)
            except Exception: pass
    logger.info(f"🧹 Chrome data cleared (cache+history) for {user_data_dir}")

# ═══════════════════════════════════════════════════════════════
#  GROK SELENIUM HELPERS
# ═══════════════════════════════════════════════════════════════
def open_chrome_grok(user_data_dir, port):
    clear_chrome_data(user_data_dir)  # << bersihkan cache & history
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    proc = subprocess.Popen([
        chrome_path, f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run", "--no-default-browser-check", GROK_URL
    ])
    time.sleep(5)
    return proc

def connect_selenium_grok(port):
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    svc = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=svc, options=opts)

# ── Legacy Selenium helpers removed — now using grok_auto.js injection ──
# setup_tab_grok, check_tab_progress are replaced by JS functions:
#   __grokTabGenerate, __grokTabCheckProgress, __grokTabDownload

# ── Legacy download_tab_video removed — now using __grokTabDownload via JS ──

# ═══════════════════════════════════════════════════════════════
#  VIDEO MERGE (2 raw -> 1 ~20 detik)
# ═══════════════════════════════════════════════════════════════
def merge_video_pair(vid1, vid2, output_dir, log_fn=None):
    os.makedirs(output_dir, exist_ok=True)
    out = os.path.join(output_dir, f"merged_{int(time.time())}_{random.randint(100,999)}.mp4")
    txt = os.path.join(output_dir, f"_concat_{int(time.time())}.txt")
    try:
        with open(txt, "w") as f:
            f.write(f"file '{vid1}'\nfile '{vid2}'\n")
        cmd = [FFMPEG_PATH, "-y", "-f", "concat", "-safe", "0", "-i", txt,
               "-c:v", "libx264", "-preset", "fast", "-crf", "23",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
               "-t", "20", out]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 10000:
            if log_fn: log_fn(f"Merged: {os.path.basename(out)}")
            return out
        if log_fn: log_fn(f"Merge gagal: returncode={r.returncode}")
    except Exception as e:
        if log_fn: log_fn(f"Merge error: {e}")
    finally:
        try: os.remove(txt)
        except: pass
    return None

# ═══════════════════════════════════════════════════════════════
#  GENERATE STOK (Grok multi-tab → merge → stok)
#  Simple pipeline: 10 tab → download → merge → restart Chrome tiap 5 merged
# ═══════════════════════════════════════════════════════════════
TABS_PER_BATCH = 10
RESTART_EVERY_MERGED = 5  # Restart Chrome setiap 5 merged video


def _close_all_extra_tabs(driver):
    """Tutup semua tab kecuali tab pertama."""
    try:
        handles = driver.window_handles
        if len(handles) > 1:
            for h in handles[1:]:
                try: driver.switch_to.window(h); driver.close()
                except: pass
            driver.switch_to.window(driver.window_handles[0])
    except: pass


def _start_chrome_session(grok_ud, grok_port, log_fn, ud_num, raw_dir=None):
    """Buka Chrome & connect Selenium. Return (chrome_proc, driver) or (None, None)."""
    if raw_dir is None: raw_dir = RAW_DIR
    log_fn(f"[UD {ud_num}] Membuka Chrome (port {grok_port})...")
    chrome_proc = open_chrome_grok(grok_ud, grok_port)
    try:
        driver = connect_selenium_grok(grok_port)
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": raw_dir})
        log_fn(f"[UD {ud_num}] Chrome terhubung!")
        return chrome_proc, driver
    except Exception as e:
        log_fn(f"[UD {ud_num}] Gagal connect Chrome: {e}")
        try: chrome_proc.terminate()
        except: pass
        return None, None


def _stop_chrome_session(chrome_proc, driver, log_fn, ud_num):
    """Tutup Chrome & driver dengan aman."""
    try:
        if driver: driver.quit()
    except: pass
    try:
        if chrome_proc: chrome_proc.terminate()
    except: pass
    log_fn(f"[UD {ud_num}] Chrome ditutup.")
    time.sleep(3)


def _prewarm_chrome(driver, log_fn, ud_num):
    """Pre-warm Chrome by loading Grok on the initial tab.
    This caches JS/CSS so subsequent tabs load much faster."""
    log_fn(f"[UD {ud_num}] 🔥 Pre-warming Chrome (loading Grok pertama kali)...")
    try:
        driver.get(GROK_URL)
        # Tunggu sampai halaman benar-benar render
        WebDriverWait(driver, 30).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR,
                "div.tiptap, textarea, button[aria-label='Settings'], button[aria-label='Pengaturan']")) > 0
        )
        time.sleep(3)  # extra settle time for JS hydration
        log_fn(f"[UD {ud_num}] ✅ Pre-warm selesai, JS/CSS sudah di-cache")
    except Exception as e:
        log_fn(f"[UD {ud_num}] ⚠️ Pre-warm timeout, lanjut saja: {str(e)[:40]}")
        time.sleep(5)  # fallback wait


def _setup_single_tab(driver, tab_index, bahan_folder, prompt_text, log_fn, ud_num, skip_nav=False):
    """Setup dan generate pada satu tab. Return (handle, status_str).
    skip_nav=True jika tab sudah di grok.com (misalnya tab pre-warm)."""
    import base64
    img = get_random_bahan_image(bahan_folder)
    if not img:
        log_fn(f"[UD {ud_num}] Tidak ada gambar bahan!")
        return None, 'failed'

    # Navigate ke Grok dengan retry (skip jika sudah di grok.com)
    if skip_nav:
        # Cek apakah memang sudah di grok.com
        current_url = driver.current_url or ''
        if 'grok.com' not in current_url and 'imagine' not in current_url:
            skip_nav = False  # Ternyata belum, tetap navigate

    if not skip_nav:
        nav_ok = False
        for nav_try in range(3):
            try:
                driver.get(GROK_URL)
                time.sleep(4 + nav_try * 2)
                current_url = driver.current_url or ''
                if 'grok.com' in current_url or 'imagine' in current_url:
                    nav_ok = True
                    break
                elif 'about:blank' in current_url or not current_url.startswith('http'):
                    log_fn(f"[UD {ud_num}] [Tab {tab_index+1}] ⚠️ Masih about:blank, retry {nav_try+1}/3...")
                    time.sleep(2)
                else:
                    nav_ok = True
                    break
            except Exception as nav_e:
                log_fn(f"[UD {ud_num}] [Tab {tab_index+1}] ⚠️ Navigasi error: {str(nav_e)[:40]}, retry...")
                time.sleep(3)

        if not nav_ok:
            log_fn(f"[UD {ud_num}] [Tab {tab_index+1}] ❌ Gagal navigasi ke Grok setelah 3x retry")
            return driver.current_window_handle, 'failed'

    handle = driver.current_window_handle

    # Tunggu UI render
    try:
        WebDriverWait(driver, 20).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR,
                "div.tiptap, textarea, button[aria-label='Settings'], button[aria-label='Pengaturan']")) > 0
        )
        time.sleep(2)
    except Exception as e:
        log_fn(f"[UD {ud_num}] [Tab {tab_index+1}] ⚠️ UI render timeout, akan dicoba inject...")

    # Inject grok_auto.js
    try:
        inject_js(driver, GROK_JS_FILE)
    except Exception as e:
        log_fn(f"[UD {ud_num}] [Tab {tab_index+1}] JS inject gagal: {e}")
        return handle, 'failed'

    # Prepare image
    img_b64 = None
    img_name = "ref.jpg"
    if img and os.path.exists(img):
        with open(img, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')
        img_name = os.path.basename(img)

    config = {
        'prompt': prompt_text,
        'image': img_b64,
        'imageName': img_name,
        'mode': 'video',
    }
    try:
        result = driver.execute_script(
            "return await window.__grokTabGenerate(arguments[0], arguments[1]);",
            tab_index, config
        )
        status = result.get('status', '') if result else ''
        if status in ('generating', 'running'):
            log_fn(f"[UD {ud_num}] [Tab {tab_index+1}] Generate dimulai (JS)")
            return handle, 'generating'
        else:
            err = result.get('error', 'unknown') if result else 'no result'
            log_fn(f"[UD {ud_num}] [Tab {tab_index+1}] Setup gagal: {err}")
            return handle, 'failed'
    except Exception as e:
        log_fn(f"[UD {ud_num}] [Tab {tab_index+1}] Generate error: {str(e)[:60]}")
        return handle, 'failed'


def _download_tab_video(driver, tab_index, batch_start, log_fn, ud_num, raw_dir=None):
    """Download video dari tab yang sudah selesai generate.
    Multi-method download seperti brutal_bot.py:
      1. URL extraction + download via requests (paling reliable)
      2. JS __grokTabDownload (klik tombol Unduh)
      3. Selenium scroll+click tombol Download
      4. JS pointer events dispatch
      5. Enter key pada tombol Download
      6. Direct JS click fallback
    Return path file jika berhasil, None jika gagal."""
    if raw_dir is None: raw_dir = RAW_DIR
    downloads_folder = os.path.expanduser("~/Downloads")
    prefix = f"[UD {ud_num}] [Tab {tab_index+1}]"
    dest_filename = f"gtt_{int(time.time())}_{tab_index}.mp4"
    save_path = os.path.join(raw_dir, dest_filename)

    log_fn(f"{prefix} Generate selesai, download...")

    # ── Method 0: Extract video URL + download via requests (PALING RELIABLE) ──
    video_url = None
    try:
        video_url = driver.execute_script(
            "return window.__grokTabGetVideoUrl(arguments[0]);", tab_index)
    except:
        pass

    # Fallback: cari langsung dari DOM
    if not video_url:
        try:
            video_url = driver.execute_script("""
                for(const v of document.querySelectorAll('video')){
                    if(v.src&&v.src.startsWith('https://')&&v.src.includes('.mp4'))return v.src;
                    const src=v.querySelector('source');if(src&&src.src&&src.src.startsWith('https://'))return src.src;
                }
                for(const a of document.querySelectorAll('a[download],a[href*=".mp4"]')){
                    if(a.href&&a.href.startsWith('https://'))return a.href;
                }
                return null;
            """)
        except:
            pass

    if video_url and video_url.startswith('https://') and 'blob:' not in video_url:
        log_fn(f"{prefix} 🔗 URL video ditemukan, download via requests...")
        try:
            import requests as req_lib
            cookies = {c['name']: c['value'] for c in driver.get_cookies()}
            headers = {
                'User-Agent': driver.execute_script('return navigator.userAgent;'),
                'Referer': GROK_URL
            }
            resp = req_lib.get(video_url, cookies=cookies, headers=headers, stream=True, timeout=120)
            if resp.status_code == 200:
                with open(save_path, 'wb') as vf:
                    for chunk in resp.iter_content(65536):
                        if chunk:
                            vf.write(chunk)
                if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                    sz = os.path.getsize(save_path) / (1024 * 1024)
                    log_fn(f"{prefix} ✅ Video via requests ({sz:.1f} MB)")
                    return save_path
                else:
                    log_fn(f"{prefix} ⚠️ File terlalu kecil ({os.path.getsize(save_path)} bytes), coba metode lain...")
                    try: os.remove(save_path)
                    except: pass
            else:
                log_fn(f"{prefix} ⚠️ requests status {resp.status_code}, coba metode lain...")
        except Exception as e:
            log_fn(f"{prefix} ⚠️ requests gagal: {str(e)[:50]}, coba metode lain...")

    # ── Dismiss editor overlay so it doesn't block the Download button ──
    try:
        driver.execute_script("""
            document.querySelectorAll('div[contenteditable="true"]').forEach(e=>{
                e.style.pointerEvents='none'; e.style.zIndex='-1'; });
            document.querySelectorAll('.tiptap,.ProseMirror').forEach(w=>{
                w.style.pointerEvents='none'; w.style.zIndex='-1'; });
        """)
        time.sleep(0.5)
    except:
        pass

    # ── Button click methods ──
    dl_clicked = False

    # Method 1: JS __grokTabDownload (uses _findDownloadButton + URL fallback)
    try:
        driver.execute_script(
            "window.__grokTabDownload(arguments[0]);", tab_index)
        dl_clicked = True
        log_fn(f"{prefix} ✅ Download dimulai (JS __grokTabDownload)")
    except:
        pass

    # Method 2: JS _findDownloadButton() — detects aria-label AND SVG icon buttons
    if not dl_clicked:
        try:
            dl_clicked = driver.execute_script("""
                const btn = window._findDownloadButton ? window._findDownloadButton() : null;
                if (btn) {
                    btn.scrollIntoView({block:'center'});
                    btn.click();
                    return true;
                }
                return false;
            """)
            if dl_clicked:
                log_fn(f"{prefix} ✅ Download diklik (JS _findDownloadButton)")
        except:
            pass

    # Method 3: Selenium scroll + click (aria-label)
    if not dl_clicked:
        try:
            dl_btns = driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Download"], button[aria-label="Unduh"]')
            if dl_btns:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", dl_btns[-1])
                time.sleep(0.5)
                ActionChains(driver).move_to_element(dl_btns[-1]).click().perform()
                dl_clicked = True
                log_fn(f"{prefix} ✅ Download diklik (Selenium)")
        except:
            pass

    # Method 4: JS pointer events dispatch
    if not dl_clicked:
        try:
            dl_clicked = driver.execute_script("""
                const btns = Array.from(document.querySelectorAll('main article button')).filter(b => {
                    const r = b.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                });
                for (const btn of btns) {
                    const paths = btn.querySelectorAll('svg path');
                    if (paths.length === 0) continue;
                    const d = Array.from(paths).map(p => p.getAttribute('d')||'').join(' ');
                    if (d.includes('21 15') && d.includes('v4')) {
                        btn.scrollIntoView({block:'center'});
                        ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev=>
                            btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                        return true;
                    }
                }
                // Fallback: aria-label buttons
                for(const btn of document.querySelectorAll('button')){
                    const l=btn.getAttribute('aria-label')||'';
                    if(l==='Download'||l==='Unduh'){
                        btn.scrollIntoView({block:'center'});
                        ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev=>
                            btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                        return true;}
                }
                return false;
            """)
            if dl_clicked:
                log_fn(f"{prefix} ✅ Download diklik (JS pointer/SVG)")
        except:
            pass

    # Method 5: Last resort — download video URL via requests (jika tombol semua gagal)
    if not dl_clicked:
        log_fn(f"{prefix} ⚠️ Semua metode klik gagal, coba download URL langsung...")
        try:
            fallback_url = driver.execute_script("""
                const v = document.querySelector('video#sd-video') || document.querySelector('video#hd-video');
                if (v && v.src && v.src.includes('assets.grok.com') && v.src.includes('.mp4')) return v.src;
                for (const vid of document.querySelectorAll('video')) {
                    if (vid.src && vid.src.startsWith('https://') && vid.src.includes('.mp4')) return vid.src;
                }
                return null;
            """)
            if fallback_url and fallback_url.startswith('https://'):
                log_fn(f"{prefix} 🔗 URL ditemukan, download via requests...")
                import requests as req_lib
                cookies = {c['name']: c['value'] for c in driver.get_cookies()}
                headers = {'User-Agent': driver.execute_script('return navigator.userAgent;'), 'Referer': GROK_URL}
                resp = req_lib.get(fallback_url, cookies=cookies, headers=headers, stream=True, timeout=120)
                if resp.status_code == 200:
                    with open(save_path, 'wb') as vf:
                        for chunk in resp.iter_content(65536):
                            if chunk: vf.write(chunk)
                    if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                        sz = os.path.getsize(save_path) / (1024 * 1024)
                        log_fn(f"{prefix} ✅ Video via URL fallback ({sz:.1f} MB)")
                        return save_path
        except Exception as e:
            log_fn(f"{prefix} ⚠️ URL fallback gagal: {str(e)[:50]}")

    if not dl_clicked:
        log_fn(f"{prefix} ❌ Download gagal total (semua metode)")
        return None

    time.sleep(3)

    # ── Wait for .mp4 file to appear (max 90s, with crdownload stall detection) ──
    log_fn(f"{prefix} ⏳ Menunggu file terdownload (max 90 detik)...")
    dl_start = time.time()
    last_crdownload_size = -1
    crdownload_stall_start = None

    while time.time() - dl_start < 90:
        time.sleep(2)
        for search_dir in [raw_dir, downloads_folder]:
            try:
                mp4s = glob.glob(os.path.join(search_dir, "*.mp4"))
                new_files = [f for f in mp4s if os.path.getmtime(f) > batch_start]
                crdownloads = glob.glob(os.path.join(search_dir, "*.crdownload"))

                if new_files and not crdownloads:
                    newest = max(new_files, key=os.path.getmtime)
                    if os.path.getsize(newest) > 10000:
                        dest = os.path.join(raw_dir, f"gtt_{int(time.time())}_{tab_index}.mp4")
                        if search_dir != raw_dir:
                            shutil.move(newest, dest)
                        else:
                            if newest != dest:
                                try: shutil.move(newest, dest)
                                except: dest = newest
                        log_fn(f"{prefix} ✅ Video diunduh: {os.path.basename(dest)}")
                        return dest

                # Detect stalled crdownload (tidak bertambah dalam 20 detik)
                if crdownloads:
                    try:
                        cr_size = sum(os.path.getsize(f) for f in crdownloads)
                        if cr_size == last_crdownload_size:
                            if crdownload_stall_start is None:
                                crdownload_stall_start = time.time()
                            elif time.time() - crdownload_stall_start > 20:
                                log_fn(f"{prefix} ⚠️ Download stall 20s, abort")
                                # Hapus crdownload yang macet
                                for cr in crdownloads:
                                    try: os.remove(cr)
                                    except: pass
                                return None
                        else:
                            last_crdownload_size = cr_size
                            crdownload_stall_start = None
                    except:
                        pass

            except:
                pass

        # Check JS state
        try:
            js_state = driver.execute_script(
                "return window.__grokTabCheckProgress(arguments[0]);", tab_index)
            if js_state and js_state.get('status') == 'downloaded':
                # Give a moment for file write to complete
                time.sleep(2)
                for search_dir in [raw_dir, downloads_folder]:
                    mp4s = glob.glob(os.path.join(search_dir, "*.mp4"))
                    new_files = [f for f in mp4s if os.path.getmtime(f) > batch_start]
                    if new_files:
                        newest = max(new_files, key=os.path.getmtime)
                        if os.path.getsize(newest) > 10000:
                            dest = os.path.join(raw_dir, f"gtt_{int(time.time())}_{tab_index}.mp4")
                            if search_dir != raw_dir:
                                shutil.move(newest, dest)
                            else:
                                if newest != dest:
                                    try: shutil.move(newest, dest)
                                    except: dest = newest
                            log_fn(f"{prefix} ✅ Video diunduh (JS confirmed): {os.path.basename(dest)}")
                            return dest
                break  # JS says downloaded but no file found
        except:
            pass

    log_fn(f"{prefix} ❌ Timeout download 90 detik")
    return None


def _open_new_grok_tab(driver, log_fn, ud_num, tab_num):
    """Buka tab baru dan navigasi ke grok.com.
    Menggunakan Selenium native: new_window('tab') + driver.get(URL) + WebDriverWait.
    TIDAK menggunakan window.open(URL) karena gagal saat tab lain sedang generating.
    Return handle tab baru atau None jika gagal."""
    try:
        # Step 1: Buat tab baru (selalu about:blank awalnya — ini normal)
        driver.switch_to.new_window('tab')
        new_handle = driver.current_window_handle
        time.sleep(1)

        # Step 2: Navigasi ke grok.com via driver.get (Selenium native, paling reliable)
        for nav_try in range(3):
            try:
                driver.get(GROK_URL)
                # Step 3: Tunggu sampai URL benar-benar berubah dari about:blank
                WebDriverWait(driver, 15).until(
                    lambda d: 'grok.com' in (d.current_url or '') or 'imagine' in (d.current_url or '')
                )
                log_fn(f"[UD {ud_num}] [Tab {tab_num}] ✅ Tab siap")
                return new_handle
            except Exception as e:
                log_fn(f"[UD {ud_num}] [Tab {tab_num}] ⚠️ Navigasi gagal (retry {nav_try+1}/3): {str(e)[:40]}")
                time.sleep(2 + nav_try * 2)

        # Jika semua retry gagal, cek apakah minimal halaman sudah load
        current_url = driver.current_url or ''
        if 'grok.com' in current_url or 'imagine' in current_url:
            log_fn(f"[UD {ud_num}] [Tab {tab_num}] ✅ Tab siap (setelah retry)")
            return new_handle

        log_fn(f"[UD {ud_num}] [Tab {tab_num}] ⚠️ URL masih: {current_url[:40]}, lanjut tetap...")
        return new_handle

    except Exception as e:
        log_fn(f"[UD {ud_num}] [Tab {tab_num}] ❌ Gagal buat tab: {str(e)[:50]}")
        return None


def _run_mini_batch(driver, num_tabs, bahan_folder, prompt_text, log_fn, stop_event, ud_num, raw_dir=None):
    """
    Buka num_tabs tab, generate via grok_auto.js, download raw video.
    Return list of raw file paths yang berhasil didownload.
    Uses JS injection: __grokTabGenerate + __grokTabCheckProgress + __grokTabDownload
    """
    tab_handles = []
    tab_status = {}  # i -> 'generating' | 'done' | 'failed' | ...
    tab_prog = {}
    batch_start = time.time()
    generated = []
    next_tab_index = 0  # Counter for tab indices (including retries)

    # Phase 0: Pre-warm Chrome pada tab pertama (cache JS/CSS)
    _prewarm_chrome(driver, log_fn, ud_num)

    # Phase 1: Setup semua tab via JS injection
    for i in range(num_tabs):
        if stop_event.is_set(): break

        if i == 0:
            # Tab pertama: REUSE tab pre-warm yang sudah di grok.com
            # Tidak perlu buat tab baru atau navigasi ulang
            handle, status = _setup_single_tab(
                driver, next_tab_index, bahan_folder, prompt_text, log_fn, ud_num,
                skip_nav=True  # Sudah di grok.com dari _prewarm_chrome
            )
        else:
            # Tab selanjutnya: buka tab baru via window.open(GROK_URL)
            new_handle = _open_new_grok_tab(driver, log_fn, ud_num, i + 1)
            if not new_handle:
                tab_handles.append(driver.current_window_handle)
                tab_status[next_tab_index] = 'failed'
                tab_prog[next_tab_index] = 0
                next_tab_index += 1
                continue

            handle, status = _setup_single_tab(
                driver, next_tab_index, bahan_folder, prompt_text, log_fn, ud_num,
                skip_nav=True  # _open_new_grok_tab sudah navigasi ke grok.com
            )

        tab_handles.append(handle or driver.current_window_handle)
        tab_status[next_tab_index] = status
        tab_prog[next_tab_index] = 0
        next_tab_index += 1
        time.sleep(1)

    if stop_event.is_set():
        return generated

    # Phase 2: Poll __grokTabCheckProgress until all done
    timeout_global = time.time()
    retry_tabs = []  # List of tab indices that need retry (download failed)
    MAX_RETRIES_PER_BATCH = 3
    retries_done = 0
    tab_start_time = {}  # i -> time.time() when tab started generating (untuk minimum wait)
    
    # Catat waktu mulai untuk semua tab awal
    for i, s in tab_status.items():
        if s == 'generating':
            tab_start_time[i] = time.time()

    while not stop_event.is_set():
        active = [i for i, s in tab_status.items() if s == 'generating']
        if not active:
            # Check if we need to create retry tabs
            if retry_tabs and retries_done < MAX_RETRIES_PER_BATCH:
                retry_idx = retry_tabs.pop(0)
                retries_done += 1
                log_fn(f"[UD {ud_num}] 🔄 Retry buat tab baru (pengganti Tab {retry_idx+1} yang gagal download)")
                try:
                    new_tab_idx = next_tab_index
                    new_handle = _open_new_grok_tab(driver, log_fn, ud_num, f"R{new_tab_idx+1}")
                    if not new_handle:
                        log_fn(f"[UD {ud_num}] ⚠️ Retry tab gagal dibuat")
                    else:
                        handle, status = _setup_single_tab(
                            driver, new_tab_idx, bahan_folder, prompt_text, log_fn, ud_num,
                            skip_nav=True)
                        tab_handles.append(handle or driver.current_window_handle)
                        tab_status[new_tab_idx] = status
                        tab_prog[new_tab_idx] = 0
                        next_tab_index += 1
                        if status == 'generating':
                            tab_start_time[new_tab_idx] = time.time()
                            batch_start = time.time()  # Reset batch_start agar download tidak match file lama
                            # Tunggu 5 detik agar generation benar-benar mulai sebelum polling
                            log_fn(f"[UD {ud_num}] ⏳ Menunggu 5 detik agar retry tab mulai generate...")
                            time.sleep(5)
                            continue  # Keep polling
                except Exception as e:
                    log_fn(f"[UD {ud_num}] ⚠️ Retry tab gagal: {str(e)[:50]}")
            else:
                break

        if time.time() - timeout_global > 600:
            for i in active:
                tab_status[i] = 'timeout'
                log_fn(f"[UD {ud_num}] [Tab {i+1}] Global timeout!")
            break

        for i in list(active):
            if stop_event.is_set(): break
            try:
                # Find the correct handle for this tab index
                handle_idx = list(tab_status.keys()).index(i)
                if handle_idx < len(tab_handles):
                    driver.switch_to.window(tab_handles[handle_idx])
                else:
                    continue

                state = driver.execute_script(
                    "return window.__grokTabCheckProgress(arguments[0]);", i)
                if not state:
                    continue

                status = state.get('status', '')
                pct = state.get('progress', 0)

                if pct != tab_prog.get(i, 0):
                    tab_prog[i] = pct
                    parts = []
                    for ti in tab_status:
                        s = tab_status.get(ti, '?')
                        if s == 'generating':
                            parts.append(f"T{ti+1}:{tab_prog.get(ti,0)}%")
                        elif s == 'done':
                            parts.append(f"T{ti+1}:OK")
                        elif s == 'dl_fail':
                            parts.append(f"T{ti+1}:DL!")
                        else:
                            parts.append(f"T{ti+1}:ERR")
                    log_fn(f"[UD {ud_num}] {' | '.join(parts)}")

                if status == 'done':
                    # KRITIS: Pastikan tab sudah cukup lama generating sebelum download
                    # Minimal 15 detik sejak tab mulai generate, agar tidak false-positive
                    min_wait = 15  # detik
                    elapsed_since_start = time.time() - tab_start_time.get(i, 0)
                    if elapsed_since_start < min_wait:
                        wait_remaining = min_wait - elapsed_since_start
                        log_fn(f"[UD {ud_num}] [Tab {i+1}] ⏳ Status 'done' tapi baru {elapsed_since_start:.0f}s, tunggu {wait_remaining:.0f}s lagi...")
                        # Belum waktunya, skip dulu — akan dicek lagi di iterasi berikutnya
                        continue

                    found_path = _download_tab_video(driver, i, batch_start, log_fn, ud_num, raw_dir=raw_dir)

                    if found_path and os.path.exists(found_path) and os.path.getsize(found_path) > 10000:
                        generated.append(found_path)
                        tab_status[i] = 'done'
                        log_fn(f"[UD {ud_num}] [Tab {i+1}] Raw #{len(generated)} OK")
                        batch_start = time.time()
                    else:
                        tab_status[i] = 'dl_fail'
                        log_fn(f"[UD {ud_num}] [Tab {i+1}] ❌ Download gagal → akan buat tab pengganti")
                        retry_tabs.append(i)

                elif status == 'rate_limited':
                    tab_status[i] = 'rate_limited'
                    log_fn(f"[UD {ud_num}] [Tab {i+1}] 🚫 RATE LIMIT REACHED! Grok meminta upgrade ke SuperGrok.")
                    # Set semua tab yang masih generating ke rate_limited
                    for ai in active:
                        if tab_status.get(ai) == 'generating':
                            tab_status[ai] = 'rate_limited'
                    # Break inner loop — akan break outer loop juga
                    break

                elif status == 'error':
                    tab_status[i] = 'failed'
                    log_fn(f"[UD {ud_num}] [Tab {i+1}] Error: {state.get('error','?')}")

            except Exception as e:
                log_fn(f"[UD {ud_num}] [Tab {i+1}] Poll error: {str(e)[:50]}")
                tab_status[i] = 'error'
        time.sleep(3)

        # Cek apakah ada rate limit — langsung keluar
        if any(s == 'rate_limited' for s in tab_status.values()):
            break

    # Tutup semua extra tab
    _close_all_extra_tabs(driver)

    # Cek rate limit — propagate ke caller
    if any(s == 'rate_limited' for s in tab_status.values()):
        log_fn(f"[UD {ud_num}] 🚫 Rate limit terdeteksi! Generate dihentikan.")
        return '__RATE_LIMITED__'  # Sentinel value

    ok_count = sum(1 for s in tab_status.values() if s == 'done')
    fail_count = sum(1 for s in tab_status.values() if s != 'done')
    log_fn(f"[UD {ud_num}] Mini-batch: {ok_count} OK, {fail_count} gagal/skip")
    return generated


def _merge_raw_list(raw_list, out_dir, log_fn, stop_event, ud_num, merge_func=None):
    """Merge pairs of raw videos into 20s clips. Returns merged count."""
    merged_count = 0
    for i in range(0, len(raw_list) - 1, 2):
        if stop_event.is_set(): break
        mf = merge_func if merge_func else merge_video_pair
        mp = mf(raw_list[i], raw_list[i + 1], out_dir, log_fn)
        if mp:
            merged_count += 1
            log_fn(f"[UD {ud_num}] Merged #{merged_count}: {os.path.basename(mp)}")
        # Hapus raw setelah merge
        for vp in [raw_list[i], raw_list[i + 1]]:
            try:
                if os.path.exists(vp): os.remove(vp)
            except: pass
    return merged_count


def generate_stok_for_ud(ud_num, needed, prompt_text, bahan_folder, grok_ud, grok_port, log_fn, stop_event, out_dir=None, raw_dir=None, merge_func=None):
    """
    Generate 'needed' merged 20s videos for a UD.
    
    Pipeline sederhana & anti-stuck:
    1. Buka Chrome
    2. Generate 10 tab raw video
    3. Download semua (timeout = skip)
    4. Merge pairs → stok
    5. Restart Chrome tiap 5 merged
    6. Loop sampai stok = target
    """
    if out_dir is None: out_dir = stok_dir(ud_num)
    if raw_dir is None: raw_dir = RAW_DIR
    os.makedirs(raw_dir, exist_ok=True)
    target = needed
    batch_num = 0
    total_merged_this_session = 0
    merged_since_restart = 0
    consecutive_fails = 0
    raw_pool = []  # Sisa raw yang belum di-merge (ganjil)

    log_fn(f"[UD {ud_num}] Target: {target} merged 20s videos")
    log_fn(f"[UD {ud_num}] Mode: {TABS_PER_BATCH} tab/batch, restart Chrome tiap {RESTART_EVERY_MERGED} merged")

    chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num, raw_dir=raw_dir)
    if not driver:
        log_fn(f"[UD {ud_num}] Gagal memulai Chrome!")
        return 0

    try:
        while total_merged_this_session < target and not stop_event.is_set():
            try:
                # Cek stok aktual
                current_stok = count_stok(ud_num)
                still_needed = target - total_merged_this_session
                if still_needed <= 0:
                    log_fn(f"[UD {ud_num}] Target tercapai! Stok: {current_stok}")
                    break

                # Safety: terlalu banyak gagal berturut
                if consecutive_fails >= 5:
                    log_fn(f"[UD {ud_num}] 5x gagal berturut, restart Chrome...")
                    _stop_chrome_session(chrome_proc, driver, log_fn, ud_num)
                    chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num, raw_dir=raw_dir)
                    if not driver:
                        log_fn(f"[UD {ud_num}] Chrome restart gagal, abort!")
                        break
                    consecutive_fails = 0
                    merged_since_restart = 0
                    continue

                # Cek apakah driver masih hidup
                if driver is None:
                    log_fn(f"[UD {ud_num}] Driver mati, restart Chrome...")
                    chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num, raw_dir=raw_dir)
                    if not driver:
                        log_fn(f"[UD {ud_num}] Chrome restart gagal, abort!")
                        break
                    merged_since_restart = 0

                batch_num += 1
                # Hitung berapa raw yang perlu: (still_needed * 2) - sisa raw pool
                raw_needed_total = still_needed * 2 - len(raw_pool)
                tabs_this_batch = min(TABS_PER_BATCH, max(raw_needed_total, 2))
                log_fn(f"[UD {ud_num}] ── Batch {batch_num} ── {tabs_this_batch} tab (butuh {still_needed} merged, raw pool: {len(raw_pool)})")

                # Generate mini-batch
                new_raw = _run_mini_batch(driver, tabs_this_batch, bahan_folder, prompt_text, log_fn, stop_event, ud_num, raw_dir=raw_dir)

                # Cek rate limit sentinel
                if new_raw == '__RATE_LIMITED__':
                    log_fn(f"[UD {ud_num}] 🚫 Rate limit terdeteksi! Menghentikan generate...")
                    raise GrokRateLimitError("Grok rate limit reached. Generate dihentikan.")

                if not new_raw and not raw_pool:
                    consecutive_fails += 1
                    log_fn(f"[UD {ud_num}] Batch {batch_num} gagal total ({consecutive_fails}/5)")
                    time.sleep(5)
                    continue

                consecutive_fails = 0  # Reset jika ada yang berhasil
                raw_pool.extend(new_raw)
                log_fn(f"[UD {ud_num}] Raw pool: {len(raw_pool)} videos")

                if stop_event.is_set(): break

                # Merge pairs dari raw pool
                if len(raw_pool) >= 2:
                    pairs_to_merge = list(raw_pool)
                    raw_pool.clear()

                    # Simpan sisa ganjil kembali ke pool
                    if len(pairs_to_merge) % 2 == 1:
                        raw_pool.append(pairs_to_merge.pop())

                    merged_count = _merge_raw_list(pairs_to_merge, out_dir, log_fn, stop_event, ud_num, merge_func=merge_func)
                    total_merged_this_session += merged_count
                    merged_since_restart += merged_count
                    log_fn(f"[UD {ud_num}] Progress: {total_merged_this_session}/{target} merged (stok: {count_stok(ud_num)})")

                if stop_event.is_set(): break

                # Restart Chrome tiap RESTART_EVERY_MERGED merged
                if merged_since_restart >= RESTART_EVERY_MERGED:
                    log_fn(f"[UD {ud_num}] Restart Chrome ({merged_since_restart} merged)...")
                    _stop_chrome_session(chrome_proc, driver, log_fn, ud_num)
                    chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num, raw_dir=raw_dir)
                    if not driver:
                        log_fn(f"[UD {ud_num}] Chrome restart gagal, abort!")
                        break
                    merged_since_restart = 0

            except GrokRateLimitError:
                raise
            except Exception as e:
                # Chrome crash / koneksi putus → restart otomatis
                log_fn(f"[UD {ud_num}] ⚠️ Chrome error: {type(e).__name__} - {str(e)[:80]}")
                log_fn(f"[UD {ud_num}] Auto-restart Chrome...")
                try: _stop_chrome_session(chrome_proc, driver, log_fn, ud_num)
                except: pass
                driver = None
                time.sleep(5)
                chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num, raw_dir=raw_dir)
                if not driver:
                    consecutive_fails += 1
                    log_fn(f"[UD {ud_num}] Restart gagal ({consecutive_fails}/5)")
                    if consecutive_fails >= 5:
                        log_fn(f"[UD {ud_num}] 5x restart gagal, abort!")
                        break
                else:
                    merged_since_restart = 0
                    log_fn(f"[UD {ud_num}] Chrome restart OK, lanjut generate...")

        # Handle sisa raw pool (ganjil terakhir) - pindah ke stok langsung
        if raw_pool and not stop_event.is_set():
            if len(raw_pool) >= 2:
                mc = _merge_raw_list(raw_pool, out_dir, log_fn, stop_event, ud_num, merge_func=merge_func)
                total_merged_this_session += mc
            # single leftover → pindah langsung ke stok
            for leftover in raw_pool:
                if os.path.exists(leftover):
                    dest = os.path.join(out_dir, os.path.basename(leftover))
                    try: shutil.move(leftover, dest); total_merged_this_session += 1
                    except: pass

    finally:
        _stop_chrome_session(chrome_proc, driver, log_fn, ud_num)

    final_stok = count_stok(ud_num)
    log_fn(f"[UD {ud_num}] Pipeline selesai! Merged: {total_merged_this_session}, Stok total: {final_stok}")
    return total_merged_this_session

# ═══════════════════════════════════════════════════════════════
#  TIKTOK UPLOAD (schedule + upload batch)
# ═══════════════════════════════════════════════════════════════
def build_tiktok_schedule(video_files, start_dt, interval_hours):
    """Build schedule list with interval_hours + random minutes between each."""
    schedule = []
    current_dt = start_dt
    for path in video_files:
        schedule.append({"path": path, "schedule": current_dt.strftime("%Y-%m-%d %H:%M"), "status": "pending"})
        jitter = random.randint(0, 30)
        current_dt += timedelta(hours=interval_hours, minutes=jitter)
    return schedule

def upload_tiktok_batch(ud_num, schedule, ud_cfg, log_fn, stop_event):
    """
    Upload videos to TikTok with scheduling via tiktok_auto.js injection.
    Selenium handles: Chrome lifecycle, file upload via input[type=file].
    JS handles: description, hashtags, product, switches, schedule, post button.
    Returns uploaded count.
    """
    remaining = [s for s in schedule if s.get("status") not in ("done", "skipped")]
    if not remaining:
        log_fn(f"[UD {ud_num}] Semua sudah diupload."); return 0
    log_fn(f"[UD {ud_num}] Upload {len(remaining)} video...")
    tiktok_ud = ud_cfg.get("tiktok_ud", "")
    tiktok_port = ud_cfg.get("tiktok_port", "")
    deskripsi = ud_cfg.get("deskripsi", "")
    hashtags = ud_cfg.get("hashtags", [])
    nama_produk_radio = ud_cfg.get("nama_produk_radio", "")
    nama_produk_radio_list = ud_cfg.get("nama_produk_radio_list", [])
    if not nama_produk_radio_list and nama_produk_radio:
        nama_produk_radio_list = [nama_produk_radio]
    nama_produk_input = ud_cfg.get("nama_produk_input", "")
    add_product = ud_cfg.get("add_product", True)
    add_sound = ud_cfg.get("add_sound", False)

    clear_chrome_data(tiktok_ud)
    chrome_proc = open_chrome_debug(tiktok_ud, tiktok_port)
    driver = None; uploaded = 0
    try:
        driver = connect_selenium(tiktok_port)
        total = len(remaining)
        for idx, item in enumerate(remaining):
            if stop_event.is_set(): break
            path = item["path"]
            if not os.path.exists(path):
                log_fn(f"[UD {ud_num}] [{idx+1}/{total}] File tidak ada, skip")
                item["status"] = "skipped"; save_ud_schedule(ud_num, schedule); continue
            try:
                sched_dt = datetime.strptime(item["schedule"], "%Y-%m-%d %H:%M")
            except:
                log_fn(f"[UD {ud_num}] [{idx+1}/{total}] Format jadwal error")
                item["status"] = "skipped"; save_ud_schedule(ud_num, schedule); continue

            # Pick random produk_radio
            radio_candidates = list(nama_produk_radio_list) if nama_produk_radio_list else []
            chosen_radio = None
            if radio_candidates and add_product:
                random.shuffle(radio_candidates)
                chosen_radio = radio_candidates[0]
                log_fn(f"[UD {ud_num}] [{idx+1}/{total}] 🎲 Produk: {chosen_radio[:40]}")

            log_fn(f"[UD {ud_num}] [{idx+1}/{total}] Upload: {os.path.basename(path)} | {item['schedule']}")
            try:
                # 1. Navigate to upload page
                navigate_upload_page(driver, force=(idx > 0))
                time.sleep(3)

                # 2. Upload file via input[type=file]
                inject_video_file(driver, path)
                log_fn(f"[UD {ud_num}] [{idx+1}/{total}] File disuntikkan")
                time.sleep(5)

                desc_with_num = f"[{idx+1}] {deskripsi}" if deskripsi else ""

                # 3. Post video with produk radio retry (like brutal_bot)
                post_ok = False
                tried_radios = []
                candidates_to_try = list(radio_candidates) if (radio_candidates and add_product) else [""]

                for radio_try in candidates_to_try:
                    if stop_event.is_set(): break
                    try:
                        do_post_video(
                            driver=driver,
                            deskripsi=desc_with_num,
                            nama_produk_radio=radio_try if add_product else "",
                            nama_produk_input=nama_produk_input if add_product else "",
                            log=lambda m, *args: log_fn(f"[UD {ud_num}]   {m}"),
                            schedule_dt=sched_dt,
                            stop_event=stop_event,
                            add_sound=add_sound,
                            add_product=add_product,
                            skip_switches=True,
                            hashtags=hashtags if hashtags else [],
                            location=None
                        )
                        post_ok = True
                        break
                    except Exception as e_post:
                        tried_radios.append(radio_try)
                        err_msg = str(e_post).lower()
                        # Jika error karena produk tidak ditemukan, coba nama lain
                        if any(kw in err_msg for kw in ["radio", "produk", "timeout", "presence", "not found", "xpath"]):
                            log_fn(f"[UD {ud_num}]   ⚠️ Produk '{radio_try[:30]}' tidak ditemukan, coba lain...")
                            continue
                        else:
                            # Error lain (bukan soal produk), langsung raise
                            raise

                if post_ok and not stop_event.is_set():
                    try: os.remove(path)
                    except: pass
                    uploaded += 1
                    item["status"] = "done"
                    save_ud_schedule(ud_num, schedule)
                    log_fn(f"[UD {ud_num}] [{idx+1}/{total}] ✅ Upload sukses")
                elif tried_radios and not post_ok:
                    log_fn(f"[UD {ud_num}] [{idx+1}/{total}] ❌ Semua produk radio gagal ({len(tried_radios)} dicoba)")

            except Exception as e:
                log_fn(f"[UD {ud_num}] [{idx+1}/{total}] Error: {e}")
            if idx < total-1 and not stop_event.is_set():
                log_fn(f"[UD {ud_num}] Menunggu 10 detik..."); time.sleep(10)
    finally:
        try:
            if driver: driver.quit()
        except: pass
        try: chrome_proc.terminate()
        except: pass
    log_fn(f"[UD {ud_num}] Upload selesai: {uploaded}/{len(remaining)}")
    return uploaded
