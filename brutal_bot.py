
"""
🔥 BRUTAL BOT — Grok Auto-Generate + TikTok Schedule
Pipeline: Generate 50 video (Grok multi-tab) setiap jam 01:00
→ Schedule 50 video ke TikTok jam 02:00 dst dengan anti-collision
"""
import os, sys, re, time, shutil, asyncio, subprocess, logging, json, threading, random, glob, tempfile
from datetime import datetime, timedelta

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# TikTok upload
sys.path.insert(0, r"c:\tiktok_automation")
from tiktok_gui import open_chrome_debug, connect_selenium, navigate_upload_page, do_upload_file, do_post_video

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN        = "8373740242:AAG3rmqa09DygakkqcUMMib36U7S7-7uwlk"
ALLOWED_USER_IDS = []   # kosong = semua boleh

APP_DIR          = r"C:\tiktok_automation"
BAHAN_DIR        = os.path.join(APP_DIR, "bahan")
BRUTAL_STOK_DIR  = os.path.join(APP_DIR, "brutal_stok")
MP3_DIR          = os.path.join(APP_DIR, "brutal_mp3")
BRUTAL_UD        = os.path.join(APP_DIR, "user_data", "brutal1")
BRUTAL_PORT      = "9260"
GROK_URL         = "https://grok.com/imagine"
SETTINGS_FILE    = os.path.join(APP_DIR, "brutal_settings.json")
SCHEDULE_FILE    = os.path.join(APP_DIR, "tiktok_daily_schedule.json")

TIKTOK_UD        = os.path.join(APP_DIR, "user_data", "brutal2")  # UD TikTok upload
TIKTOK_PORT      = "9261"

MAX_STOK         = 50   # max video di brutal_stok
GENERATE_HOUR    = 0    # jam mulai generate
GENERATE_MINUTE  = 1    # menit mulai generate (00:01)
SCHEDULE_START_HOUR = 2 # jam mulai schedule TikTok (02:00)
BATCH1_COUNT     = 30   # jumlah video batch pertama
BATCH2_COUNT     = 20   # jumlah video batch kedua

# ═══════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════
active_gen_task  = {}   # uid -> {stop, thread}
active_upload_task = {}
full_auto_task   = {}

# ═══════════════════════════════════════════════════════════════
#  SETTINGS
# ═══════════════════════════════════════════════════════════════
_DEFAULT_SETTINGS = {
    "prompt_name": "",
    "folder_name": "",
    "deskripsi": "",
    "hashtags": [],
    "nama_produk_radio_list": [],
    "nama_produk_input": "beli sebelum promonya habis",
    "add_product": True,
    "add_sound": False,
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return {**_DEFAULT_SETTINGS, **json.load(f)}
        except: pass
    return dict(_DEFAULT_SETTINGS)

def save_settings(cfg):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

bot_settings = load_settings()

# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def is_allowed(uid): return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS
def escape_html(t): return str(t).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path,"r",encoding="utf-8") as f: return json.load(f)
        except: pass
    return default if default is not None else {}

def _save_json(path, data):
    with open(path,"w",encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)

# ─── Prompts ───
PROMPTS_FILE = os.path.join(APP_DIR, "grok_prompts.json")
def load_prompts():
    return _load_json(PROMPTS_FILE, {})

# ─── Bahan images ───
def list_bahan_folders():
    os.makedirs(BAHAN_DIR, exist_ok=True)
    return sorted([d for d in os.listdir(BAHAN_DIR) if os.path.isdir(os.path.join(BAHAN_DIR, d))])

def list_bahan_images(folder_name):
    folder = os.path.join(BAHAN_DIR, folder_name)
    if not os.path.isdir(folder): return []
    exts = ('.png','.jpg','.jpeg','.webp','.bmp','.gif')
    return sorted([f for f in os.listdir(folder) if f.lower().endswith(exts)])

def get_random_bahan_image(folder_name):
    imgs = list_bahan_images(folder_name)
    if not imgs: return None
    return os.path.join(BAHAN_DIR, folder_name, random.choice(imgs))

# ─── MP3 Sound ───
def list_mp3():
    os.makedirs(MP3_DIR, exist_ok=True)
    return sorted([f for f in os.listdir(MP3_DIR) if f.lower().endswith('.mp3')])

def get_random_mp3():
    mp3s = list_mp3()
    if not mp3s: return None
    return os.path.join(MP3_DIR, random.choice(mp3s))

def get_random_produk_radio(settings=None):
    """Pick random nama_produk_radio from the list."""
    s = settings or load_settings()
    lst = s.get("nama_produk_radio_list", [])
    # Backward compat: jika masih ada string lama
    if not lst and s.get("nama_produk_radio", ""):
        return s["nama_produk_radio"]
    if not lst: return ""
    return random.choice(lst)

# ─── Stok ───
def count_stok():
    if not os.path.isdir(BRUTAL_STOK_DIR): return 0
    return len([f for f in os.listdir(BRUTAL_STOK_DIR) if f.endswith(".mp4")])

def list_stok():
    if not os.path.isdir(BRUTAL_STOK_DIR): return []
    return sorted([os.path.join(BRUTAL_STOK_DIR, f)
                   for f in os.listdir(BRUTAL_STOK_DIR) if f.endswith(".mp4")],
                  key=os.path.getmtime)

def stok_needed():
    return max(0, MAX_STOK - count_stok())

# ═══════════════════════════════════════════════════════════════
#  SCHEDULE ALGORITHM (Sequential Random Anti-Collision)
# ═══════════════════════════════════════════════════════════════
REST_PERIODS = [
    (9*60, 11*60),      # 09:00 - 11:00
    (13*60, 14*60),     # 13:00 - 14:00
    (22*60+30, 23*60+30),  # 22:30 - 23:30
]

def _minutes_from_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute

def _is_in_rest(minutes_abs: int) -> tuple:
    """Return (True, period_end_minutes) if in rest period, else (False, 0)."""
    m = minutes_abs % (24 * 60)
    for (start, end) in REST_PERIODS:
        if start <= m < end:
            return True, end
    return False, 0

def generate_schedule(video_paths: list, base_date: datetime = None, max_videos: int = None) -> list:
    """
    Generate schedule for videos using sequential random anti-collision.
    base_date: datetime for the first video slot (default: today 02:00 + random 0-15 min)
    max_videos: max number of videos to schedule (default: len(video_paths))
    Returns list of {"path": ..., "schedule": "YYYY-MM-DD HH:MM"} sorted by time.
    """
    if not video_paths: return []

    if base_date is None:
        today = datetime.now().replace(hour=SCHEDULE_START_HOUR, minute=0, second=0, microsecond=0)
        base_date = today + timedelta(minutes=random.randint(0, 15))

    limit = max_videos if max_videos else len(video_paths)
    to_schedule = video_paths[:limit]

    results = []
    current_dt = base_date
    first_dt = base_date

    for i, path in enumerate(to_schedule):
        if i > 0:
            # Random gap 5-25 menit
            gap = random.randint(5, 25)
            candidate_dt = current_dt + timedelta(minutes=gap)
        else:
            candidate_dt = current_dt

        # Skip rest periods
        for _ in range(10):  # max 10 iterations
            mins = _minutes_from_midnight(candidate_dt)
            in_rest, end_mins = _is_in_rest(mins)
            if not in_rest:
                break
            # Jump to end of rest + random 8-36 menit
            candidate_dt = candidate_dt.replace(
                hour=end_mins // 60,
                minute=end_mins % 60,
                second=0, microsecond=0
            ) + timedelta(minutes=random.randint(8, 36))

        # Safety: don't exceed 24h from first video
        if (candidate_dt - first_dt).total_seconds() > 24 * 3600:
            break

        results.append({
            "path": path,
            "schedule": candidate_dt.strftime("%Y-%m-%d %H:%M"),
        })
        current_dt = candidate_dt

    return results

def save_schedule(schedule: list):
    _save_json(SCHEDULE_FILE, schedule)

def load_schedule() -> list:
    return _load_json(SCHEDULE_FILE, [])

# ═══════════════════════════════════════════════════════════════
#  FFmpeg MERGE (2 video → 1 ~20 detik)
# ═══════════════════════════════════════════════════════════════
def _mute_and_add_mp3(video_path, log_fn=None):
    """Mute video audio and replace with random MP3 from TikTok_MP3 folder."""
    mp3_path = get_random_mp3()
    if not mp3_path:
        if log_fn: log_fn("⚠️ Tidak ada file MP3 di TikTok_MP3, video tetap muted")
        # Just mute the video
        tmp_out = video_path + ".muted.mp4"
        cmd = ["ffmpeg", "-y", "-i", video_path, "-an", "-c:v", "copy", tmp_out]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
                os.replace(tmp_out, video_path)
                if log_fn: log_fn(f"🔇 Video dimute (tanpa MP3)")
                return True
        except Exception as e:
            if log_fn: log_fn(f"❌ Mute error: {e}")
        try:
            if os.path.exists(tmp_out): os.remove(tmp_out)
        except: pass
        return False

    mp3_name = os.path.basename(mp3_path)
    if log_fn: log_fn(f"🎵 Menambahkan audio: {mp3_name[:40]}")
    tmp_out = video_path + ".audio.mp4"
    # Mute original audio, add MP3 as audio track, loop MP3 if shorter than video
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", mp3_path,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        tmp_out
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
            os.replace(tmp_out, video_path)
            if log_fn: log_fn(f"✅ Audio diganti: {mp3_name[:40]}")
            return True
        if log_fn: log_fn(f"❌ Audio replace gagal: {r.stderr[-150:]}")
    except Exception as e:
        if log_fn: log_fn(f"❌ Audio replace error: {e}")
    try:
        if os.path.exists(tmp_out): os.remove(tmp_out)
    except: pass
    return False

def merge_video_pair(vid1, vid2, output_dir, log_fn=None):
    os.makedirs(output_dir, exist_ok=True)
    existing = glob.glob(os.path.join(output_dir, "*.mp4"))
    nums = []
    for f in existing:
        m = re.fullmatch(r'(\d+)\.mp4', os.path.basename(f))
        if m: nums.append(int(m.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    out_path = os.path.join(output_dir, f"{next_num}.mp4")
    list_file = os.path.join(output_dir, f"_mlist_{next_num}.txt")
    try:
        with open(list_file, "w", encoding="utf-8") as lf:
            lf.write(f"file '{vid1}'\nfile '{vid2}'\n")
        cmd = ["ffmpeg","-y","-f","concat","-safe","0","-i",list_file,"-c","copy",out_path]
        if log_fn: log_fn(f"🎬 Merge: {os.path.basename(vid1)} + {os.path.basename(vid2)} → {next_num}.mp4")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            if log_fn: log_fn(f"✅ Merged: {next_num}.mp4 ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
            # Mute original audio & replace with random MP3
            _mute_and_add_mp3(out_path, log_fn)
            return out_path
        if log_fn: log_fn(f"❌ Merge gagal: {r.stderr[-150:]}")
        return None
    except Exception as e:
        if log_fn: log_fn(f"❌ Merge error: {e}")
        return None
    finally:
        try:
            if os.path.exists(list_file): os.remove(list_file)
        except: pass

# ═══════════════════════════════════════════════════════════════
#  CHROME CLEANUP — clear cache & history, keep cookies
# ═══════════════════════════════════════════════════════════════
def clear_chrome_data(user_data_dir):
    """Clear Chrome cache & history but keep cookies & login data."""
    profile_dir = os.path.join(user_data_dir, "Default")
    if not os.path.isdir(profile_dir):
        # Mungkin belum pernah dibuka, skip
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
            try:
                shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass
    # Cache juga bisa di level user_data_dir langsung
    for d in ["ShaderCache", "GrShaderCache"]:
        target = os.path.join(user_data_dir, d)
        if os.path.isdir(target):
            try:
                shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass

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
            try:
                os.remove(target)
            except Exception:
                pass

    logger.info(f"🧹 Chrome data cleared (cache+history) for {user_data_dir}")

# ═══════════════════════════════════════════════════════════════
#  GROK SELENIUM HELPERS (copied from grok_imagine_bot.py)
# ═══════════════════════════════════════════════════════════════
def open_chrome_grok(user_data_dir, port):
    clear_chrome_data(user_data_dir)  # << bersihkan cache & history
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    proc = subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run", "--no-default-browser-check",
        GROK_URL
    ])
    time.sleep(5)
    return proc

def connect_selenium_grok(port):
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    svc = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=svc, options=opts)

def navigate_to_grok(driver, log_fn, max_retries=3):
    for attempt in range(1, max_retries+1):
        try:
            if GROK_URL not in driver.current_url:
                driver.get(GROK_URL)
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script(
                    "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]') !== null"
                ))
            log_fn(f"✅ Halaman Grok termuat (attempt {attempt})")
            return True
        except Exception as e:
            log_fn(f"⚠️ Navigate attempt {attempt} gagal: {e}")
            if attempt < max_retries: time.sleep(3)
    return False

def _count_imgs(drv):
    try:
        return drv.execute_script("""
            let c=0;
            c+=document.querySelectorAll('img[src*="assets.grok.com"]').length;
            c+=document.querySelectorAll('img[src^="blob:"]').length;
            c+=document.querySelectorAll('div.group.relative img').length;
            return c;""")
    except: return 0

def _verify_uploaded(drv, before, timeout=10):
    for _ in range(timeout*2):
        try:
            if _count_imgs(drv) > before: return True
            has = drv.execute_script("""
                const g=document.querySelector('div.group.relative');
                if(g){const r=g.getBoundingClientRect();if(r.width>50&&r.height>50)return true;}
                return false;""")
            if has: return True
        except: pass
        time.sleep(0.5)
    return False

def _do_upload(drv, abs_img, before):
    try:
        for fi in drv.find_elements(By.CSS_SELECTOR, "input[type='file']"):
            try:
                drv.execute_script("arguments[0].style.cssText='display:block!important;visibility:visible!important;opacity:1!important;position:absolute;top:0;left:0;width:1px;height:1px;';", fi)
                fi.send_keys(abs_img); time.sleep(3)
                if _verify_uploaded(drv, before): return True
            except: pass
    except: pass
    try:
        iid = f"_bf_{int(time.time())}"
        drv.execute_script(f"""
            let o=document.getElementById('{iid}');if(o)o.remove();
            const i=document.createElement('input');i.type='file';i.id='{iid}';i.accept='image/*';
            i.style.cssText='position:absolute;top:0;left:0;z-index:99999;display:block;width:1px;height:1px;';
            document.body.appendChild(i);""")
        time.sleep(0.5)
        drv.find_element(By.ID, iid).send_keys(abs_img)
        time.sleep(3)
        if _verify_uploaded(drv, before): return True
    except: pass
    return False

def _do_fill_prompt(drv, p_text):
    for method in range(3):
        try:
            if method == 0:
                ed = drv.execute_script("""
                    const e=document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                    if(e){e.scrollIntoView({block:'center'});return e;} return null;""")
                if not ed: continue
                drv.execute_script("arguments[0].focus();", ed)
                time.sleep(0.3); ed.click(); time.sleep(0.3)
                ed.send_keys(Keys.CONTROL+"a"); time.sleep(0.2); ed.send_keys(Keys.DELETE); time.sleep(0.2)
                drv.execute_script("""
                    const e=arguments[0];
                    e.innerHTML='<p>'+arguments[1]+'</p>';
                    e.dispatchEvent(new Event('input',{bubbles:true}));
                    e.dispatchEvent(new Event('change',{bubbles:true}));
                    e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));""", ed, p_text)
                time.sleep(1)
            elif method == 1:
                r = drv.execute_script("""
                    const e=document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                    if(!e)return 'nf';
                    e.focus();e.innerHTML='<p>'+arguments[0]+'</p>';
                    e.dispatchEvent(new Event('input',{bubbles:true}));
                    e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));
                    return 'ok';""", p_text)
                if r != 'ok': continue
                time.sleep(1)
            else:
                ed = WebDriverWait(drv, 20).until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'div.tiptap.ProseMirror[contenteditable="true"]')))
                drv.execute_script("arguments[0].scrollIntoView({block:'center'});", ed)
                time.sleep(1); ed.click(); time.sleep(0.5)
                ed.send_keys(Keys.CONTROL+"a"); ed.send_keys(Keys.DELETE); time.sleep(0.3)
                for chunk in [p_text[i:i+50] for i in range(0, len(p_text), 50)]:
                    ed.send_keys(chunk); time.sleep(0.1)
                time.sleep(1)
            actual = drv.execute_script("""return document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]')?.textContent||'';""")
            if actual.strip(): return True
        except: pass
    return False

def setup_tab_grok(driver, image_path, prompt_text, log_fn, tab_idx):
    prefix = f"[Tab {tab_idx+1}]"
    image_uploaded = True
    if image_path and os.path.exists(image_path):
        abs_image = os.path.abspath(image_path); image_uploaded = False
        for outer in range(1, 4):
            if outer > 1:
                log_fn(f"{prefix} Reload upload attempt {outer}/3...")
                try: driver.get(GROK_URL); time.sleep(5)
                except: continue
            before = _count_imgs(driver)
            if _do_upload(driver, abs_image, before):
                image_uploaded = True; log_fn(f"{prefix} Upload OK!"); break
            log_fn(f"{prefix} Upload {outer} gagal")
        if not image_uploaded: log_fn(f"{prefix} Upload gagal 3x")

    for fn in [
        lambda: ActionChains(driver).move_to_element(
            driver.find_elements(By.CSS_SELECTOR,'button[aria-label="Settings"], button[aria-label="Pengaturan"]')[0]
        ).click().perform(),
        lambda: driver.execute_script("""
            for(const b of document.querySelectorAll('button')){
                const l=b.getAttribute('aria-label')||'';
                if(l==='Settings'||l==='Pengaturan'){b.click();return true;}}return false;""")
    ]:
        try:
            fn(); time.sleep(1.5)
            if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                for item in driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                    if "Buat Video" in (item.text or "") or "Make Video" in (item.text or ""):
                        ActionChains(driver).move_to_element(item).click().perform(); break
                time.sleep(1); break
        except: pass

    prompt_ok = False
    for outer in range(1, 4):
        if outer > 1:
            log_fn(f"{prefix} Reload prompt attempt {outer}/3...")
            try: driver.get(GROK_URL); time.sleep(5)
            except: continue
        if _do_fill_prompt(driver, prompt_text):
            prompt_ok = True; log_fn(f"{prefix} Prompt OK!"); break
        log_fn(f"{prefix} Prompt {outer} gagal")
    if not prompt_ok: log_fn(f"{prefix} Prompt gagal 3x"); return False

    try:
        gen_btn = None
        for label in ['Buat video','Create video','Generate','Submit']:
            try:
                gen_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, f'button[aria-label="{label}"]')))
                if gen_btn: break
            except: continue
        if not gen_btn:
            try: gen_btn = driver.find_element(By.CSS_SELECTOR, 'button.group[type="button"]')
            except: pass
        if gen_btn: gen_btn.click()
        else:
            driver.execute_script("""
                const b=document.querySelector('button[aria-label="Buat video"]')||document.querySelector('button.group[type="button"]');
                if(b)b.click();""")
        log_fn(f"{prefix} Generate diklik!"); time.sleep(2); return True
    except Exception as e:
        log_fn(f"{prefix} Generate gagal: {e}"); return False

def check_tab_progress(driver):
    pct_num = 0; is_gen = False
    try:
        pt = driver.execute_script("""
            const spans=document.querySelectorAll('span.tabular-nums');
            for(const s of spans){const t=s.textContent.trim();if(t.includes('%'))return t;}
            return '';""")
        if pt:
            m = re.search(r'(\d+)', pt)
            if m: pct_num = int(m.group(1))
    except: pass
    try:
        is_gen = driver.execute_script("""
            for(const s of document.querySelectorAll('span')){
                if(s.textContent.includes('Menghasilkan')||s.textContent.includes('Generating'))return true;}
            return false;""")
    except: pass
    try:
        dl = driver.find_elements(By.CSS_SELECTOR,'button[aria-label="Download"], button[aria-label="Unduh"]')
        if dl and not is_gen: return "done", 100
    except: pass
    if is_gen or pct_num > 0: return "generating", pct_num
    return "idle", 0

def download_tab_video(driver, output_dir, log_fn, tab_idx, start_time):
    import requests as req_lib
    prefix = f"[Tab {tab_idx+1}]"
    filename = f"brutal_{int(time.time())}_{tab_idx}.mp4"
    save_path = os.path.join(output_dir, filename)
    downloads_folder = os.path.expanduser("~/Downloads")

    # ── Dismiss editor overlay so it doesn't block the Download button ──
    try:
        driver.execute_script("""
            document.querySelectorAll('div[contenteditable="true"]').forEach(e=>{
                e.style.pointerEvents='none'; e.style.zIndex='-1'; });
            document.querySelectorAll('.tiptap,.ProseMirror').forEach(w=>{
                w.style.pointerEvents='none'; w.style.zIndex='-1'; });
        """)
        time.sleep(0.5)
    except: pass

    # ── Method 0: Extract video URL + download via requests ──
    video_url = None
    try:
        video_url = driver.execute_script("""
            for(const v of document.querySelectorAll('video')){
                if(v.src&&(v.src.startsWith('http')||v.src.startsWith('blob')))return v.src;
                const s=v.querySelector('source');if(s&&s.src)return s.src;
            }
            for(const a of document.querySelectorAll('a[download],a[href*=".mp4"]')){
                if(a.href)return a.href;
            }
            return null;
        """)
    except: pass

    if video_url and video_url.startswith('http') and not video_url.startswith('blob'):
        log_fn(f"{prefix} 🔗 URL video, download via requests...")
        try:
            cookies = {c['name']:c['value'] for c in driver.get_cookies()}
            headers = {'User-Agent': driver.execute_script('return navigator.userAgent;'), 'Referer': GROK_URL}
            resp = req_lib.get(video_url, cookies=cookies, headers=headers, stream=True, timeout=120)
            if resp.status_code == 200:
                with open(save_path, 'wb') as vf:
                    for chunk in resp.iter_content(65536):
                        if chunk: vf.write(chunk)
                if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                    sz = os.path.getsize(save_path)/(1024*1024)
                    log_fn(f"{prefix} ✅ Video via requests ({sz:.1f} MB)")
                    return save_path
        except Exception as e:
            log_fn(f"{prefix} ⚠️ requests gagal: {e}")

    # ── Button click methods ──
    dl_clicked = False
    # Method A: Selenium scroll + click
    try:
        dl_btns = driver.find_elements(By.CSS_SELECTOR,
            'button[aria-label="Download"], button[aria-label="Unduh"]')
        if dl_btns:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", dl_btns[0])
            time.sleep(0.5)
            ActionChains(driver).move_to_element(dl_btns[0]).click().perform()
            dl_clicked = True
            log_fn(f"{prefix} ✅ Download diklik (Selenium)")
    except: pass

    # Method B: JS pointer events
    if not dl_clicked:
        try:
            dl_clicked = driver.execute_script("""
                for(const btn of document.querySelectorAll('button')){
                    const l=btn.getAttribute('aria-label')||'';
                    if(l==='Download'||l==='Unduh'){
                        btn.scrollIntoView({block:'center'});
                        ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev=>
                            btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                        return true;}
                } return false;
            """)
            if dl_clicked: log_fn(f"{prefix} ✅ Download diklik (JS pointer)")
        except: pass

    # Method C: Enter key
    if not dl_clicked:
        try:
            dl_btns = driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Download"], button[aria-label="Unduh"]')
            if dl_btns:
                dl_btns[0].send_keys(Keys.ENTER)
                dl_clicked = True
                log_fn(f"{prefix} ✅ Download diklik (Enter)")
        except: pass

    # Method D: direct JS click any matching element
    if not dl_clicked:
        try:
            dl_clicked = driver.execute_script("""
                const sel=['button[aria-label="Download"]','button[aria-label="Unduh"]',
                           'a[download]','a[href*=".mp4"]'];
                for(const s of sel){const el=document.querySelector(s);if(el){el.click();return true;}}
                return false;
            """)
            if dl_clicked: log_fn(f"{prefix} ✅ Download diklik (Method D)")
        except: pass

    if not dl_clicked:
        log_fn(f"{prefix} ❌ Tidak bisa klik tombol Download")
        return None

    log_fn(f"{prefix} ⏳ Menunggu file terdownload (max 60 detik)...")
    for _ in range(60):
        time.sleep(1)
        # Check output_dir
        try:
            mp4s = glob.glob(os.path.join(output_dir, "*.mp4"))
            new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
            if new_files:
                newest = max(new_files, key=os.path.getmtime)
                if not glob.glob(os.path.join(output_dir, "*.crdownload")):
                    if newest != save_path: shutil.move(newest, save_path)
                    log_fn(f"{prefix} ✅ Video diunduh: {filename}")
                    return save_path
        except: pass
        # Check Downloads folder
        try:
            mp4s = glob.glob(os.path.join(downloads_folder, "*.mp4"))
            new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
            if new_files:
                newest = max(new_files, key=os.path.getmtime)
                if not glob.glob(os.path.join(downloads_folder, "*.crdownload")):
                    shutil.move(newest, save_path)
                    log_fn(f"{prefix} ✅ Video diunduh dari Downloads: {filename}")
                    return save_path
        except: pass

    log_fn(f"{prefix} ❌ Timeout download 60 detik")
    return None

BRUTAL_RAW_DIR = os.path.join(APP_DIR, "brutal_stok_raw")

def merge_leftover_raw(log_fn=None):
    """Merge leftover raw videos from previous interrupted sessions."""
    if not os.path.isdir(BRUTAL_RAW_DIR):
        return []
    raws = sorted(glob.glob(os.path.join(BRUTAL_RAW_DIR, "*.mp4")), key=os.path.getmtime)
    if len(raws) < 2:
        return []
    if log_fn:
        log_fn(f"🔄 Ditemukan {len(raws)} raw video sisa, melakukan merge...")
    os.makedirs(BRUTAL_STOK_DIR, exist_ok=True)
    merged = []
    for i in range(0, len(raws) - 1, 2):
        mp = merge_video_pair(raws[i], raws[i+1], BRUTAL_STOK_DIR, log_fn)
        if mp:
            merged.append(mp)
            for vp in [raws[i], raws[i+1]]:
                try:
                    if os.path.exists(vp): os.remove(vp)
                except: pass
    # Handle odd leftover
    if len(raws) % 2 == 1:
        leftover = raws[-1]
        dest = os.path.join(BRUTAL_STOK_DIR, os.path.basename(leftover))
        try: shutil.move(leftover, dest); merged.append(dest)
        except: pass
    if log_fn and merged:
        log_fn(f"✅ Merge sisa selesai: {len(merged)} video baru ditambahkan ke stok")
    return merged

def generate_stok(needed, prompt_text, folder_name, log_fn, stop_event):
    os.makedirs(BRUTAL_STOK_DIR, exist_ok=True)
    os.makedirs(BRUTAL_RAW_DIR, exist_ok=True)
    # Merge leftover raw videos dari sesi sebelumnya
    leftover_merged = merge_leftover_raw(log_fn)
    if leftover_merged:
        # Re-check kebutuhan setelah merge sisa
        needed = stok_needed()
        if needed <= 0:
            log_fn(f"Stok sudah penuh setelah merge sisa ({count_stok()}/{MAX_STOK})")
            return glob.glob(os.path.join(BRUTAL_STOK_DIR, "*.mp4"))

    # Gunakan pipeline robust dari gtt_core yang menjalankan grok_auto.js
    import gtt_core
    from gtt_core import GrokRateLimitError
    # GrokRateLimitError dibiarkan propagate ke caller (run_full_pipeline / _gen)
    merged_count = gtt_core.generate_stok_for_ud(
        ud_num="Brutal",
        needed=needed,
        prompt_text=prompt_text,
        bahan_folder=folder_name,
        grok_ud=BRUTAL_UD,
        grok_port=BRUTAL_PORT,
        log_fn=log_fn,
        stop_event=stop_event,
        out_dir=BRUTAL_STOK_DIR,
        raw_dir=BRUTAL_RAW_DIR,
        merge_func=merge_video_pair
    )
    
    merged = glob.glob(os.path.join(BRUTAL_STOK_DIR, "*.mp4"))
    log_fn(f"Stok generate selesai. Stok total tersimpan: {len(merged)} video")
    return merged


def upload_schedule_tiktok(schedule, deskripsi="", hashtags=None, log_fn=None, stop_event=None,
                          nama_produk_radio="", nama_produk_input="",
                          add_product=True, add_sound=False,
                          nama_produk_radio_list=None):
    if not schedule: return 0
    # Filter: hanya upload yang belum selesai (tanpa status "done")
    remaining = [s for s in schedule if s.get("status") != "done"]
    if not remaining:
        log_fn("Semua schedule sudah selesai diupload.")
        return 0
    log_fn(f"Schedule: {len(remaining)} sisa dari {len(schedule)} total")
    clear_chrome_data(TIKTOK_UD)  # << bersihkan cache & history
    chrome_proc = open_chrome_debug(TIKTOK_UD, TIKTOK_PORT)
    driver = None; uploaded = 0
    try:
        driver = connect_selenium(TIKTOK_PORT)
        total = len(remaining)
        for idx, item in enumerate(remaining):
            if stop_event.is_set(): break
            path = item["path"]
            schedule_str = item["schedule"]
            if not os.path.exists(path):
                log_fn(f"[{idx+1}/{total}] File tidak ada, skip: {os.path.basename(path)}")
                item["status"] = "skipped"
                save_schedule(schedule)  # Simpan progress
                continue
            try:
                sched_dt = datetime.strptime(schedule_str, "%Y-%m-%d %H:%M")
            except:
                log_fn(f"[{idx+1}/{total}] Format jadwal error, skip")
                item["status"] = "skipped"
                save_schedule(schedule)
                continue
            # Pick random produk_radio for this upload
            radio_candidates = list(nama_produk_radio_list) if nama_produk_radio_list else ([nama_produk_radio] if nama_produk_radio else [])
            if radio_candidates:
                random.shuffle(radio_candidates)
                chosen_radio = radio_candidates[0]
                log_fn(f"  🎲 Produk radio dipilih: {chosen_radio[:50]}")
            else:
                chosen_radio = ""
            log_fn(f"[{idx+1}/{total}] Upload: {os.path.basename(path)} | {schedule_str}")
            try:
                navigate_upload_page(driver, force=(idx > 0))
                time.sleep(3)
                do_upload_file(driver, os.path.normpath(path), log_fn)
                time.sleep(5)
                # Tambah nomor urut [1], [2], dst di depan deskripsi
                deskripsi_with_num = f"[{idx+1}] {deskripsi}" if deskripsi else ""
                
                # Coba post dengan retry produk radio
                post_ok = False
                tried_radios = []
                for radio_try in radio_candidates if radio_candidates else [""]:
                    try:
                        do_post_video(driver, deskripsi_with_num,
                                      radio_try, nama_produk_input,
                                      log_fn, sched_dt, stop_event,
                                      add_sound=add_sound, add_product=add_product,
                                      skip_switches=True,
                                      hashtags=hashtags if hashtags else None)
                        post_ok = True
                        break
                    except Exception as e_post:
                        tried_radios.append(radio_try)
                        err_msg = str(e_post).lower()
                        # Jika error karena produk tidak ditemukan, coba nama lain
                        if any(kw in err_msg for kw in ["radio", "produk", "timeout", "presence", "not found", "xpath"]):
                            log_fn(f"  ⚠️ Produk '{radio_try[:30]}' tidak ditemukan, coba lain...")
                            continue
                        else:
                            # Error lain (bukan soal produk), langsung raise
                            raise
                
                if not post_ok:
                    log_fn(f"  ❌ Semua produk radio gagal ({len(tried_radios)} dicoba)")
                    raise Exception(f"Semua produk radio gagal: {', '.join(t[:20] for t in tried_radios)}")
                
                try: os.remove(path)
                except: pass
                uploaded += 1
                item["status"] = "done"
                save_schedule(schedule)  # Simpan progress setiap upload sukses
                log_fn(f"  [{idx+1}/{total}] Upload sukses ✓ (progress disimpan)")
            except Exception as e:
                log_fn(f"  [{idx+1}/{total}] Error: {e}")
            if idx < total-1 and not stop_event.is_set():
                log_fn("  Menunggu 10 detik..."); time.sleep(10)
    finally:
        try:
            if driver: driver.quit()
        except: pass
        try: chrome_proc.terminate()
        except: pass
    log_fn(f"Upload selesai: {uploaded}/{total}")
    return uploaded


def run_full_pipeline(uid, chat_id, bot, main_loop, stop_event):
    """Full Auto pipeline: generate 50 stok → schedule 30 → wait → schedule 20."""
    def sendmsg(text):
        asyncio.run_coroutine_threadsafe(bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    log_lines = []; log_lock = threading.Lock(); log_done = threading.Event()
    def log_fn(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        with log_lock:
            log_lines.append(f"<code>[{ts}]</code> {msg}")
            if len(log_lines) > 30: log_lines.pop(0)

    lmf = asyncio.run_coroutine_threadsafe(
        bot.send_message(chat_id,"<b>Pipeline Log</b>\n\n<i>Memulai...</i>",parse_mode=ParseMode.HTML),main_loop)
    try: lm=lmf.result(timeout=10); lmid=lm.message_id
    except: lmid=None

    async def _live():
        last=""
        while not log_done.is_set():
            with log_lock: body="\n".join(log_lines[-20:]) if log_lines else "<i>Menunggu...</i>"
            text=f"<b>Pipeline Log</b>\n\n{body}"
            if text!=last and lmid:
                try: await bot.edit_message_text(chat_id=chat_id,message_id=lmid,text=text[:4096],parse_mode=ParseMode.HTML); last=text
                except: pass
            await asyncio.sleep(3)
        with log_lock: body="\n".join(log_lines[-25:])
        try: await bot.edit_message_text(chat_id=chat_id,message_id=lmid,
            text=f"<b>Pipeline Selesai</b>\n\n{body}"[:4096],parse_mode=ParseMode.HTML)
        except: pass

    asyncio.run_coroutine_threadsafe(_live(), main_loop)

    settings = load_settings()
    prompt_name = settings.get("prompt_name",""); folder_name = settings.get("folder_name","")
    deskripsi = settings.get("deskripsi",""); hashtags = settings.get("hashtags",[])
    nama_produk_radio_list = settings.get("nama_produk_radio_list", [])
    # Backward compat
    if not nama_produk_radio_list and settings.get("nama_produk_radio", ""):
        nama_produk_radio_list = [settings["nama_produk_radio"]]
    nama_produk_radio = get_random_produk_radio(settings)
    nama_produk_input = settings.get("nama_produk_input","")
    add_product = settings.get("add_product", True)
    add_sound = settings.get("add_sound", False)
    prompt_text = load_prompts().get(prompt_name,"")

    try:
        if not prompt_text:
            sendmsg(f"Prompt <code>{escape_html(prompt_name)}</code> tidak ditemukan!")
            return
        if not folder_name or not list_bahan_images(folder_name):
            sendmsg(f"Folder bahan <code>{escape_html(folder_name)}</code> kosong!")
            return

        # ── STEP 1: Generate stok ──
        needed = stok_needed()
        if needed <= 0:
            log_fn(f"Stok sudah penuh ({count_stok()}/{MAX_STOK}), skip generate")
            sendmsg(f"Stok penuh ({count_stok()}/{MAX_STOK}), langsung ke schedule.")
        else:
            sendmsg(f"<b>Pipeline dimulai!</b>\nStok: {count_stok()}/{MAX_STOK}\nGenerate: {needed} video")
            log_fn(f"STEP 1: Generate {needed} stok")
            try:
                merged = generate_stok(needed, prompt_text, folder_name, log_fn, stop_event)
                log_fn(f"Generate selesai: {len(merged)} video")
                sendmsg(f"Generate selesai! Stok: {count_stok()}/{MAX_STOK}")
            except Exception as gen_err:
                from gtt_core import GrokRateLimitError
                if isinstance(gen_err, GrokRateLimitError):
                    log_fn("🚫 RATE LIMIT! Generate dihentikan.")
                    sendmsg(
                        "🚫 <b>RATE LIMIT REACHED!</b>\n\n"
                        "Grok sudah mencapai batas generate.\n"
                        "Pesan dari Grok: <i>Rate limit reached — Upgrade to SuperGrok Heavy</i>\n\n"
                        "Pipeline <b>dihentikan otomatis</b>.\n"
                        f"Stok saat ini: <b>{count_stok()}/{MAX_STOK}</b>")
                else:
                    log_fn(f"❌ Error Generate: {type(gen_err).__name__}: {str(gen_err)[:80]}")
                    sendmsg(f"❌ Pipeline dihentikan karena error: {type(gen_err).__name__}\n{str(gen_err)[:200]}")
                return

        if stop_event.is_set():
            sendmsg("Pipeline dihentikan setelah generate.")
            return

        stok_files = list_stok()[:MAX_STOK]
        if not stok_files:
            sendmsg("Tidak ada stok video!")
            return

        upload_kwargs = dict(
            deskripsi=deskripsi, hashtags=hashtags,
            nama_produk_radio=nama_produk_radio,
            nama_produk_input=nama_produk_input,
            add_product=add_product, add_sound=add_sound,
            nama_produk_radio_list=nama_produk_radio_list
        )
        total_uploaded = 0

        # ── STEP 2: BATCH 1 — Schedule & upload 30 video mulai jam 02:00 ──
        batch1_files = stok_files[:BATCH1_COUNT]
        batch2_files = stok_files[BATCH1_COUNT:BATCH1_COUNT + BATCH2_COUNT]

        log_fn(f"STEP 2: Batch 1 — {len(batch1_files)} video mulai jam {SCHEDULE_START_HOUR:02d}:00")
        today_02 = datetime.now().replace(hour=SCHEDULE_START_HOUR, minute=0, second=0, microsecond=0)
        
        # Jika jadwal hari ini sudah terlewat > 10 jam, base_date = besok (safety).
        if datetime.now() > today_02 + timedelta(hours=10):
            today_02 += timedelta(days=1)
            
        schedule_batch1 = generate_schedule(batch1_files, base_date=today_02)
        save_schedule(schedule_batch1)
        preview1 = "\n".join([f"  {i+1}. <code>{s['schedule']}</code>" for i,s in enumerate(schedule_batch1)])
        sendmsg(f"<b>Batch 1 ({len(schedule_batch1)} video):</b>\n{preview1}\n\nMulai upload Batch 1...")

        if stop_event.is_set():
            sendmsg("Pipeline dihentikan sebelum upload.")
            return

        log_fn("STEP 3: Upload Batch 1")
        uploaded1 = upload_schedule_tiktok(schedule_batch1, log_fn=log_fn, stop_event=stop_event, **upload_kwargs)
        total_uploaded += uploaded1
        log_fn(f"Batch 1 selesai: {uploaded1}/{len(schedule_batch1)}")
        sendmsg(f"<b>Batch 1 selesai!</b> {uploaded1}/{len(schedule_batch1)} uploaded")

        if stop_event.is_set() or not batch2_files:
            if not batch2_files:
                sendmsg(f"<b>Pipeline selesai!</b>\nTotal: <b>{total_uploaded}/{len(stok_files)}</b>")
            else:
                sendmsg("Pipeline dihentikan setelah Batch 1.")
            return

        # ── STEP 4: Tunggu sampai waktu schedule video ke-30 ──
        last_batch1_time_str = schedule_batch1[-1]["schedule"]
        last_batch1_dt = datetime.strptime(last_batch1_time_str, "%Y-%m-%d %H:%M")
        now = datetime.now()
        if now < last_batch1_dt:
            wait_secs = (last_batch1_dt - now).total_seconds()
            h = int(wait_secs // 3600); m = int((wait_secs % 3600) // 60)
            log_fn(f"STEP 4: Menunggu sampai {last_batch1_time_str} ({h}j {m}m lagi)...")
            sendmsg(f"<b>Menunggu Batch 2...</b>\nWaktu video ke-{len(schedule_batch1)}: <code>{last_batch1_time_str}</code>\n({h} jam {m} menit lagi)")
            elapsed = 0
            while elapsed < wait_secs and not stop_event.is_set():
                time.sleep(min(60, wait_secs - elapsed))
                elapsed += 60
        else:
            log_fn(f"Waktu video ke-{len(schedule_batch1)} sudah lewat, langsung Batch 2")

        if stop_event.is_set():
            sendmsg("Pipeline dihentikan sebelum Batch 2.")
            return

        # ── STEP 5: BATCH 2 — Schedule & upload 20 video dari datetime.now() ──
        log_fn(f"STEP 5: Batch 2 — {len(batch2_files)} video mulai dari sekarang")
        base2 = datetime.now() + timedelta(minutes=random.randint(5, 15))
        schedule_batch2 = generate_schedule(batch2_files, base_date=base2)
        # Gabungkan schedule untuk save
        full_schedule = schedule_batch1 + schedule_batch2
        save_schedule(full_schedule)

        preview2 = "\n".join([f"  {i+1}. <code>{s['schedule']}</code>" for i,s in enumerate(schedule_batch2)])
        sendmsg(f"<b>Batch 2 ({len(schedule_batch2)} video):</b>\n{preview2}\n\nMulai upload Batch 2...")

        log_fn("STEP 6: Upload Batch 2")
        uploaded2 = upload_schedule_tiktok(schedule_batch2, log_fn=log_fn, stop_event=stop_event, **upload_kwargs)
        total_uploaded += uploaded2
        log_fn(f"Batch 2 selesai: {uploaded2}/{len(schedule_batch2)}")

        log_fn(f"Pipeline Complete: {total_uploaded}/{len(stok_files)}")
        sendmsg(f"<b>Pipeline selesai!</b>\nBatch 1: <b>{uploaded1}/{len(schedule_batch1)}</b>\n"
                f"Batch 2: <b>{uploaded2}/{len(schedule_batch2)}</b>\n"
                f"Total: <b>{total_uploaded}/{len(stok_files)}</b>\nSisa stok: <b>{count_stok()}</b>")
    except Exception as e:
        log_fn(f"❌ Pipeline terhenti karena error: {type(e).__name__} - {str(e)[:50]}")
        sendmsg(f"❌ <b>Pipeline terhenti karena error!</b>\n<code>{type(e).__name__}: {str(e)[:100]}</code>")
    finally:
        log_done.set()
        full_auto_task.pop(uid, None)


def run_full_auto_daemon(uid, chat_id, bot, main_loop, stop_event):
    def sendmsg(text):
        asyncio.run_coroutine_threadsafe(bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    sendmsg(f"<b>Full Auto Aktif!</b>\nSetiap hari jam <b>{GENERATE_HOUR:02d}:{GENERATE_MINUTE:02d}</b> WIB:\n"
            f"1. Generate {MAX_STOK} video via Grok\n"
            f"2. Schedule Batch 1: {BATCH1_COUNT} video mulai jam {SCHEDULE_START_HOUR:02d}:00\n"
            f"3. Tunggu → Schedule Batch 2: {BATCH2_COUNT} video\n\nTekan Stop Auto untuk berhenti.")

    while not stop_event.is_set():
        now = datetime.now()
        target = now.replace(hour=GENERATE_HOUR, minute=GENERATE_MINUTE, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        wait_secs = (target - now).total_seconds()
        h = int(wait_secs//3600); m = int((wait_secs%3600)//60)
        sendmsg(f"<b>Full Auto:</b> Menunggu jam {GENERATE_HOUR:02d}:{GENERATE_MINUTE:02d}...\n({h} jam {m} menit lagi)")
        elapsed = 0
        while elapsed < wait_secs and not stop_event.is_set():
            time.sleep(min(60, wait_secs-elapsed)); elapsed += 60
        if stop_event.is_set(): break
        sendmsg(f"<b>Jam {GENERATE_HOUR:02d}:{GENERATE_MINUTE:02d}!</b> Memulai pipeline...")
        run_full_pipeline(uid, chat_id, bot, main_loop, stop_event)
        if stop_event.is_set(): break

    sendmsg("<b>Full Auto dihentikan.</b>")
    full_auto_task.pop(uid, None)


def main_menu_kb(uid=None):
    is_auto = bool(uid and full_auto_task.get(uid))
    is_gen  = bool(uid and active_gen_task.get(uid))
    rows = [
        [InlineKeyboardButton("Status Stok", callback_data="status_stok"),
         InlineKeyboardButton("Settings", callback_data="settings_menu")],
        [InlineKeyboardButton("Generate Sekarang", callback_data="gen_now"),
         InlineKeyboardButton("Buat Schedule", callback_data="make_schedule")],
        [InlineKeyboardButton("📤 Upload TikTok Sekarang", callback_data="upload_now")],
        [InlineKeyboardButton("Stop Full Auto" if is_auto else f"Full Auto ({GENERATE_HOUR:02d}:{GENERATE_MINUTE:02d} Harian)",
                              callback_data="stop_auto" if is_auto else "start_auto")],
        [InlineKeyboardButton("Refresh", callback_data="refresh")],
    ]
    if is_gen:
        rows.insert(3, [InlineKeyboardButton("Stop Generate", callback_data="stop_gen")])
    return InlineKeyboardMarkup(rows)


def status_text():
    s = load_settings(); stok = count_stok(); sched = load_schedule()
    prod_status = "ON" if s.get('add_product', True) else "OFF"
    sound_status = "ON" if s.get('add_sound', False) else "OFF"
    # Produk radio list
    radio_list = s.get('nama_produk_radio_list', [])
    if not radio_list and s.get('nama_produk_radio', ''):
        radio_list = [s['nama_produk_radio']]
    radio_display = ', '.join(radio_list) if radio_list else '(kosong)'
    # MP3 list
    mp3_files = list_mp3()
    mp3_display = f"{len(mp3_files)} file" if mp3_files else '(kosong)'
    # Schedule progress
    sched_done = len([x for x in sched if x.get("status") == "done"])
    sched_remaining = len([x for x in sched if x.get("status") not in ("done", "skipped")])
    sched_info = f"{len(sched)} slot"
    if sched_done > 0:
        sched_info += f" ({sched_done} selesai, {sched_remaining} sisa)"
    # Raw leftover
    raw_count = len(glob.glob(os.path.join(BRUTAL_RAW_DIR, "*.mp4"))) if os.path.isdir(BRUTAL_RAW_DIR) else 0
    raw_info = f"\nRaw sisa: <b>{raw_count}</b> (akan auto-merge saat generate)" if raw_count > 0 else ""
    return (f"<b>Brutal Bot</b>\n\n"
            f"Stok: <b>{stok}/{MAX_STOK}</b> video\n"
            f"Prompt: <code>{escape_html(s.get('prompt_name','(kosong)'))}</code>\n"
            f"Folder: <code>{escape_html(s.get('folder_name','(kosong)'))}</code>\n"
            f"Deskripsi: <code>{escape_html(s.get('deskripsi','(kosong)')[:50])}</code>\n"
            f"Hashtags: <code>{escape_html(', '.join('#'+h for h in s.get('hashtags',[])) or '(kosong)')}</code>\n"
            f"\n<b>Produk:</b> {prod_status}\n"
            f"  Nama ({len(radio_list)}): <code>{escape_html(radio_display[:80])}</code>\n"
            f"  Judul: <code>{escape_html(s.get('nama_produk_input','(kosong)')[:50])}</code>\n"
            f"<b>Sound TikTok:</b> {sound_status}\n"
            f"<b>🎵 MP3 Audio:</b> {mp3_display}\n"
            f"\nSchedule: <b>{sched_info}</b>{raw_info}\n"
            f"Generate jam: <b>{GENERATE_HOUR:02d}:{GENERATE_MINUTE:02d}</b> | Schedule mulai: <b>{SCHEDULE_START_HOUR:02d}:00</b>\n"
            f"Batch: <b>{BATCH1_COUNT}+{BATCH2_COUNT}</b> (2x schedule per hari)")


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    await update.message.reply_text(status_text(), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))


async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    raw = update.message.text.strip(); args = raw.split(None, 2)
    if len(args) < 3:
        await update.message.reply_text(
            "<b>Format /set:</b>\n"
            "<code>/set prompt NAMA</code>\n"
            "<code>/set folder NAMA</code>\n"
            "<code>/set desc teks deskripsi</code>\n"
            "<code>/set hashtags fyp, viral, tiktok</code>\n"
            "\n<b>🛒 Produk:</b>\n"
            "<code>/set produk on</code> atau <code>/set produk off</code>\n"
            "<code>/set produk_input JUDUL_PRODUK</code>\n"
            "\n<b>🎵 Sound TikTok:</b>\n"
            "<code>/set sound on</code> atau <code>/set sound off</code>\n"
            "\n<b>📻 Produk Radio (multi):</b>\n"
            "<code>/produk_radio</code> — lihat daftar\n"
            "<code>/produk_radio add NAMA</code> — tambah\n"
            "<code>/produk_radio del NOMOR</code> — hapus\n"
            "\n<b>🎵 MP3 Audio:</b>\n"
            "<code>/mp3</code> — lihat daftar\n"
            "<code>/mp3 del NOMOR</code> — hapus\n"
            "Kirim file .mp3 langsung ke chat untuk menambahkan",
            parse_mode=ParseMode.HTML); return
    sub = args[1].lower(); val = args[2].strip()
    s = load_settings()
    if sub == "prompt":
        prompts = load_prompts()
        if val not in prompts:
            await update.message.reply_text(f"Prompt <code>{escape_html(val)}</code> tidak ada!\nTersedia: {', '.join(prompts.keys())}", parse_mode=ParseMode.HTML); return
        s["prompt_name"] = val
    elif sub == "folder":
        if not list_bahan_images(val):
            await update.message.reply_text(f"Folder <code>{escape_html(val)}</code> kosong!", parse_mode=ParseMode.HTML); return
        s["folder_name"] = val
    elif sub == "desc":
        s["deskripsi"] = val
    elif sub in ("hashtags","tags"):
        tags = [t.strip().lstrip('#') for t in re.split(r'[,\n]+',val) if t.strip()]
        s["hashtags"] = tags; val = ', '.join('#'+t for t in tags)
    elif sub == "produk":
        if val.lower() in ("on","true","1","ya"):
            s["add_product"] = True; val = "ON ✅"
        elif val.lower() in ("off","false","0","tidak"):
            s["add_product"] = False; val = "OFF ❌"
        else:
            await update.message.reply_text("Gunakan: <code>/set produk on</code> atau <code>/set produk off</code>", parse_mode=ParseMode.HTML); return
    elif sub == "produk_input":
        s["nama_produk_input"] = val
    elif sub == "sound":
        if val.lower() in ("on","true","1","ya"):
            s["add_sound"] = True; val = "ON ✅"
        elif val.lower() in ("off","false","0","tidak"):
            s["add_sound"] = False; val = "OFF ❌"
        else:
            await update.message.reply_text("Gunakan: <code>/set sound on</code> atau <code>/set sound off</code>", parse_mode=ParseMode.HTML); return
    else:
        await update.message.reply_text("Sub-command tidak dikenal."); return
    save_settings(s)
    await update.message.reply_text(f"<code>{sub}</code> = <code>{escape_html(val[:100])}</code>", parse_mode=ParseMode.HTML)


async def cmd_produk_radio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Manage produk radio list: /produk_radio, /produk_radio add NAMA, /produk_radio del NOMOR"""
    uid = update.effective_user.id
    if not is_allowed(uid): return
    raw = update.message.text.strip(); args = raw.split(None, 2)
    s = load_settings()
    radio_list = s.get("nama_produk_radio_list", [])
    # Backward compat
    if not radio_list and s.get("nama_produk_radio", ""):
        radio_list = [s["nama_produk_radio"]]
        s["nama_produk_radio_list"] = radio_list
        save_settings(s)

    if len(args) < 2:
        # Show list
        if not radio_list:
            await update.message.reply_text("<b>📻 Produk Radio:</b>\n(kosong)\n\n<code>/produk_radio add NAMA</code> untuk menambah", parse_mode=ParseMode.HTML)
        else:
            lines = [f"  {i+1}. <code>{escape_html(r)}</code>" for i, r in enumerate(radio_list)]
            await update.message.reply_text(
                f"<b>📻 Produk Radio ({len(radio_list)}):</b>\n" + "\n".join(lines) +
                f"\n\nUpload akan memilih <b>random 1</b> dari daftar.\n"
                f"<code>/produk_radio add NAMA</code> — tambah\n"
                f"<code>/produk_radio del NOMOR</code> — hapus",
                parse_mode=ParseMode.HTML)
        return

    sub_cmd = args[1].lower()
    if sub_cmd == "add" and len(args) >= 3:
        new_name = args[2].strip()
        if new_name in radio_list:
            await update.message.reply_text(f"<code>{escape_html(new_name)}</code> sudah ada di daftar!", parse_mode=ParseMode.HTML); return
        radio_list.append(new_name)
        s["nama_produk_radio_list"] = radio_list
        save_settings(s)
        await update.message.reply_text(f"✅ Ditambahkan: <code>{escape_html(new_name)}</code>\nTotal: {len(radio_list)} produk radio", parse_mode=ParseMode.HTML)
    elif sub_cmd == "del" and len(args) >= 3:
        try:
            idx = int(args[2].strip()) - 1
            if 0 <= idx < len(radio_list):
                removed = radio_list.pop(idx)
                s["nama_produk_radio_list"] = radio_list
                save_settings(s)
                await update.message.reply_text(f"🗑 Dihapus: <code>{escape_html(removed)}</code>\nSisa: {len(radio_list)} produk radio", parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(f"Nomor tidak valid (1-{len(radio_list)})"); return
        except ValueError:
            await update.message.reply_text("Gunakan nomor urut, contoh: <code>/produk_radio del 1</code>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(
            "<b>📻 Produk Radio:</b>\n"
            "<code>/produk_radio</code> — lihat daftar\n"
            "<code>/produk_radio add NAMA</code> — tambah\n"
            "<code>/produk_radio del NOMOR</code> — hapus",
            parse_mode=ParseMode.HTML)


async def cmd_mp3(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/mp3 — list MP3 files; /mp3 del NOMOR — delete by index"""
    uid = update.effective_user.id
    if not is_allowed(uid): return
    raw = update.message.text.strip(); args = raw.split(None, 2)
    mp3_files = list_mp3()

    if len(args) < 2:
        if not mp3_files:
            await update.message.reply_text(
                "<b>🎵 MP3 Audio:</b>\n(kosong)\n\nKirim file .mp3 ke chat untuk menambahkan.",
                parse_mode=ParseMode.HTML)
        else:
            lines = [f"  {i+1}. <code>{escape_html(f[:60])}</code>" for i, f in enumerate(mp3_files)]
            await update.message.reply_text(
                f"<b>🎵 MP3 Audio ({len(mp3_files)}):</b>\n" + "\n".join(lines) +
                f"\n\nSetiap video akan mendapat <b>random 1</b> MP3.\n"
                f"Kirim file .mp3 ke chat untuk menambahkan.\n"
                f"<code>/mp3 del NOMOR</code> — hapus",
                parse_mode=ParseMode.HTML)
        return

    sub_cmd = args[1].lower()
    if sub_cmd == "del" and len(args) >= 3:
        try:
            idx = int(args[2].strip()) - 1
            if 0 <= idx < len(mp3_files):
                removed = mp3_files[idx]
                fpath = os.path.join(MP3_DIR, removed)
                try: os.remove(fpath)
                except: pass
                await update.message.reply_text(f"🗑 Dihapus: <code>{escape_html(removed[:60])}</code>\nSisa: {len(mp3_files)-1} file MP3", parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(f"Nomor tidak valid (1-{len(mp3_files)})")
        except ValueError:
            await update.message.reply_text("Gunakan nomor urut, contoh: <code>/mp3 del 1</code>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(
            "<b>🎵 MP3 Audio:</b>\n"
            "<code>/mp3</code> — lihat daftar\n"
            "<code>/mp3 del NOMOR</code> — hapus\n"
            "Kirim file .mp3 langsung ke chat untuk menambahkan",
            parse_mode=ParseMode.HTML)


async def handle_audio_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle MP3 file sent to chat — save to TikTok_MP3 folder."""
    uid = update.effective_user.id
    if not is_allowed(uid): return
    doc = update.message.document or update.message.audio
    if not doc: return
    fname = doc.file_name or f"audio_{int(time.time())}.mp3"
    if not fname.lower().endswith('.mp3'):
        await update.message.reply_text("⚠️ Hanya file .mp3 yang diterima."); return
    os.makedirs(MP3_DIR, exist_ok=True)
    save_path = os.path.join(MP3_DIR, fname)
    tg_file = await doc.get_file()
    await tg_file.download_to_drive(save_path)
    count = len(list_mp3())
    await update.message.reply_text(
        f"✅ MP3 disimpan: <code>{escape_html(fname[:60])}</code>\n"
        f"Total MP3: <b>{count}</b>\n"
        f"Setiap video akan mendapat random 1 MP3 saat generate.",
        parse_mode=ParseMode.HTML)


async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not is_allowed(uid): return
    data = q.data; chat_id = q.message.chat_id
    bot = ctx.bot; main_loop = asyncio.get_event_loop()

    if data in ("refresh","status_stok"):
        await q.edit_message_text(status_text(), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    if data == "settings_menu":
        prompts = load_prompts(); folders = list_bahan_folders()
        s = load_settings()
        prod_status = "✅ ON" if s.get('add_product', True) else "❌ OFF"
        sound_status = "✅ ON" if s.get('add_sound', False) else "❌ OFF"
        radio_list = s.get('nama_produk_radio_list', [])
        if not radio_list and s.get('nama_produk_radio', ''):
            radio_list = [s['nama_produk_radio']]
        radio_display = ', '.join(radio_list) if radio_list else '(kosong)'
        mp3_files = list_mp3()
        mp3_display = f"{len(mp3_files)} file" if mp3_files else '(kosong)'
        text = ("<b>Settings</b>\n\nGunakan /set:\n"
                "<code>/set prompt NAMA</code>\n<code>/set folder NAMA</code>\n"
                "<code>/set desc teks...</code>\n<code>/set hashtags fyp, viral</code>\n\n"
                "<b>🛒 Produk:</b>\n"
                "<code>/set produk on/off</code>\n"
                "<code>/set produk_input JUDUL_PRODUK</code>\n\n"
                "<b>📻 Produk Radio (multi):</b>\n"
                "<code>/produk_radio</code> — lihat/tambah/hapus\n\n"
                "<b>🎵 Sound TikTok:</b>\n"
                "<code>/set sound on/off</code>\n\n"
                "<b>🎵 MP3 Audio:</b>\n"
                "<code>/mp3</code> — lihat/hapus\n"
                "Kirim file .mp3 ke chat\n\n"
                f"Prompt: {escape_html(', '.join(prompts.keys()))}\n"
                f"Folder: {escape_html(', '.join(folders))}\n\n"
                f"<b>Current:</b>\n"
                f"  Produk: {prod_status}\n"
                f"  Produk Radio ({len(radio_list)}): <code>{escape_html(radio_display[:80])}</code>\n"
                f"  Produk Input: <code>{escape_html(s.get('nama_produk_input','(kosong)'))}</code>\n"
                f"  Sound TikTok: {sound_status}\n"
                f"  MP3 Audio: {mp3_display}")
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    if data == "gen_now":
        if active_gen_task.get(uid):
            await q.answer("Generate sudah berjalan!", show_alert=True)
            return
        s = load_settings(); needed = stok_needed()
        if needed <= 0:
            await q.answer(f"Stok sudah penuh ({MAX_STOK})!", show_alert=True)
            await q.edit_message_text(f"⚠️ <b>Generate dibatalkan!</b>\n\nStok sudah penuh ({MAX_STOK}/{MAX_STOK}).\nBot tidak butuh generate raw video lagi.",
                                      parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
            return
        prompt_text = load_prompts().get(s.get("prompt_name",""),"")
        if not prompt_text:
            await q.answer("Prompt belum diset!", show_alert=True)
            await q.edit_message_text("⚠️ <b>Generate dibatalkan!</b>\n\nPrompt untuk generate belum diatur. Silakan set prompt di menu Settings.",
                                      parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
            return
        stop_evt = threading.Event()
        log_lines2 = []; ll2 = threading.Lock(); ld2 = threading.Event()
        def _log2(m):
            with ll2: log_lines2.append(f"<code>[{datetime.now().strftime('%H:%M:%S')}]</code> {m}")
            if len(log_lines2)>30: log_lines2.pop(0)
        def _gen():
            lmf2 = asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id,"<b>Generate Log</b>\n\n<i>Mulai...</i>",parse_mode=ParseMode.HTML),main_loop)
            try: lm2=lmf2.result(timeout=10); lmid2=lm2.message_id
            except: lmid2=None
            async def _upd2():
                last2=""
                while not ld2.is_set():
                    with ll2: body2="\n".join(log_lines2[-20:]) if log_lines2 else "<i>Menunggu...</i>"
                    text2=f"<b>Generate Log</b>\n\n{body2}"
                    if text2!=last2 and lmid2:
                        try: await bot.edit_message_text(chat_id=chat_id,message_id=lmid2,text=text2[:4096],parse_mode=ParseMode.HTML); last2=text2
                        except: pass
                    await asyncio.sleep(3)
            asyncio.run_coroutine_threadsafe(_upd2(), main_loop)
            try:
                merged = generate_stok(needed, prompt_text, s.get("folder_name",""), _log2, stop_evt)
                ld2.set()
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(chat_id,f"Generate selesai! {len(merged)} video.\nStok: {count_stok()}/{MAX_STOK}",parse_mode=ParseMode.HTML),main_loop)
            except Exception as gen_err:
                ld2.set()
                from gtt_core import GrokRateLimitError
                if isinstance(gen_err, GrokRateLimitError):
                    _log2("🚫 RATE LIMIT! Grok tidak bisa generate lagi.")
                    asyncio.run_coroutine_threadsafe(
                        bot.send_message(chat_id,
                            "🚫 <b>RATE LIMIT REACHED!</b>\n\n"
                            "Grok sudah mencapai batas generate.\n"
                            "Pesan dari Grok: <i>Rate limit reached — Upgrade to SuperGrok Heavy</i>\n\n"
                            "Generate <b>dihentikan otomatis</b>.\n"
                            f"Stok saat ini: <b>{count_stok()}/{MAX_STOK}</b>",
                            parse_mode=ParseMode.HTML), main_loop)
                else:
                    _log2(f"❌ Error: {type(gen_err).__name__}: {str(gen_err)[:80]}")
                    asyncio.run_coroutine_threadsafe(
                        bot.send_message(chat_id,f"❌ Generate error: {type(gen_err).__name__}\n{str(gen_err)[:200]}",parse_mode=ParseMode.HTML),main_loop)
            finally:
                ld2.set()  # safety: pastikan live log updater berhenti
                active_gen_task.pop(uid, None)
        t = threading.Thread(target=_gen, daemon=True)
        active_gen_task[uid] = {"stop": stop_evt, "thread": t}; t.start()
        await q.edit_message_text(f"<b>Generate dimulai!</b>\nTarget: {needed*2} video raw -> {needed} video 20 detik",
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    if data == "stop_gen":
        task = active_gen_task.get(uid)
        if task: task["stop"].set(); active_gen_task.pop(uid,None)
        await q.edit_message_text("Generate dihentikan.", reply_markup=main_menu_kb(uid)); return

    if data == "make_schedule":
        stok_files = list_stok()[:MAX_STOK]
        if not stok_files: await q.answer("Stok kosong!", show_alert=True); return
        today_02 = datetime.now().replace(hour=SCHEDULE_START_HOUR,minute=0,second=0,microsecond=0)
        schedule = generate_schedule(stok_files, base_date=today_02)
        save_schedule(schedule)
        preview = "\n".join([f"{i+1}. <code>{s['schedule']}</code>" for i,s in enumerate(schedule)])
        full_text = f"<b>Schedule ({len(schedule)} video):</b>\n{preview}"
        # Split pesan jika terlalu panjang (Telegram limit 4096 chars)
        if len(full_text) <= 4096:
            await q.edit_message_text(full_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        else:
            await q.edit_message_text(full_text[:4096], parse_mode=ParseMode.HTML)
            for chunk_start in range(4096, len(full_text), 4096):
                await bot.send_message(chat_id, full_text[chunk_start:chunk_start+4096], parse_mode=ParseMode.HTML)
            await bot.send_message(chat_id, "Schedule di atas.", reply_markup=main_menu_kb(uid))
        return

    if data == "upload_now":
        # Upload TikTok Sekarang: schedule dari datetime.now(), semaksimalnya
        stok_files = list_stok()
        if not stok_files: await q.answer("Stok kosong! Generate dulu.", show_alert=True); return
        if active_upload_task.get(uid): await q.answer("Upload sudah berjalan!", show_alert=True); return
        s = load_settings(); stop_evt = threading.Event()

        # Generate schedule mulai dari sekarang + 30 menit
        base_now = datetime.now() + timedelta(minutes=30)
        schedule = generate_schedule(stok_files, base_date=base_now)
        save_schedule(schedule)

        preview = "\n".join([f"{i+1}. <code>{x['schedule']}</code>" for i,x in enumerate(schedule)])

        # Produk radio list
        radio_list = s.get('nama_produk_radio_list', [])
        if not radio_list and s.get('nama_produk_radio', ''):
            radio_list = [s['nama_produk_radio']]

        def _upload():
            ll3=threading.Lock(); log3=[]
            def lg3(m):
                with ll3: log3.append(m)
            uploaded = upload_schedule_tiktok(schedule, s.get("deskripsi",""), s.get("hashtags",[]), lg3, stop_evt,
                                              nama_produk_radio=get_random_produk_radio(s),
                                              nama_produk_input=s.get("nama_produk_input",""),
                                              add_product=s.get("add_product", True),
                                              add_sound=s.get("add_sound", False),
                                              nama_produk_radio_list=radio_list)
            asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id,f"Upload selesai! {uploaded}/{len(schedule)} video ke TikTok.",parse_mode=ParseMode.HTML),main_loop)
            active_upload_task.pop(uid,None)
        t = threading.Thread(target=_upload, daemon=True)
        active_upload_task[uid] = {"stop": stop_evt, "thread": t}; t.start()
        full_text = f"<b>Upload Sekarang!</b>\n{len(schedule)} video dari stok\nMulai: <code>{base_now.strftime('%H:%M')}</code>\n\n{preview}"
        if len(full_text) <= 4096:
            await q.edit_message_text(full_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        else:
            await q.edit_message_text(full_text[:4096], parse_mode=ParseMode.HTML)
            for chunk_start in range(4096, len(full_text), 4096):
                await bot.send_message(chat_id, full_text[chunk_start:chunk_start+4096], parse_mode=ParseMode.HTML)
            await bot.send_message(chat_id, "Upload dimulai!", reply_markup=main_menu_kb(uid))
        return

    if data == "start_auto":
        if full_auto_task.get(uid): await q.answer("Full Auto sudah berjalan!", show_alert=True); return
        stop_evt = threading.Event()
        t = threading.Thread(target=run_full_auto_daemon,
                             args=(uid,chat_id,bot,main_loop,stop_evt), daemon=True)
        full_auto_task[uid] = {"stop": stop_evt, "thread": t}; t.start()
        await q.edit_message_text(f"<b>Full Auto aktif!</b>\nPipeline otomatis setiap hari jam {GENERATE_HOUR:02d}:{GENERATE_MINUTE:02d}.\n"
                                  f"Batch 1: {BATCH1_COUNT} video | Batch 2: {BATCH2_COUNT} video",
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    if data == "stop_auto":
        task = full_auto_task.get(uid)
        if task: task["stop"].set(); full_auto_task.pop(uid,None)
        await q.edit_message_text("<b>Full Auto dihentikan.</b>\n\n"+status_text(),
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return


async def post_init(application):
    try:
        await application.bot.set_my_commands([
            BotCommand("start","Menu utama"),
            BotCommand("set","Atur settings"),
            BotCommand("mp3","Kelola MP3 audio"),
            BotCommand("produk_radio","Kelola produk radio"),
        ], read_timeout=20, connect_timeout=20)
        logger.info("Bot commands registered successfully.")
    except Exception as e:
        logger.warning(f"Gagal set_my_commands saat startup (timeout/error): {e}")


def main():
    os.makedirs(BRUTAL_STOK_DIR, exist_ok=True)
    os.makedirs(BRUTAL_RAW_DIR, exist_ok=True)
    os.makedirs(MP3_DIR, exist_ok=True)
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(CommandHandler("mp3", cmd_mp3))
    app.add_handler(CommandHandler("produk_radio", cmd_produk_radio))
    app.add_handler(CallbackQueryHandler(button_handler))
    # Handle MP3 file uploads via document or audio
    app.add_handler(MessageHandler(filters.Document.MimeType("audio/mpeg") | filters.AUDIO, handle_audio_file))
    print("Brutal Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
