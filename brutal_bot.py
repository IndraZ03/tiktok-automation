
"""
🔥 BRUTAL BOT — Grok Auto-Generate + TikTok Schedule
Pipeline: Generate 50 video (Grok multi-tab) setiap jam 01:00
→ Schedule 50 video ke TikTok jam 02:00 dst dengan anti-collision
"""
import os, sys, re, time, shutil, asyncio, subprocess, logging, json, threading, random, glob
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
BRUTAL_UD        = os.path.join(APP_DIR, "user_data", "brutal")
BRUTAL_PORT      = "9260"
GROK_URL         = "https://grok.com/imagine"
SETTINGS_FILE    = os.path.join(APP_DIR, "brutal_settings.json")
SCHEDULE_FILE    = os.path.join(APP_DIR, "tiktok_daily_schedule.json")

TIKTOK_UD        = os.path.join(APP_DIR, "user_data", "brutal")  # UD TikTok upload
TIKTOK_PORT      = "9261"

MAX_STOK         = 50   # max video di brutal_stok
GENERATE_HOUR    = 1    # jam mulai generate (01:00)
SCHEDULE_START_HOUR = 2 # jam mulai schedule TikTok (02:00)

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

def generate_schedule(video_paths: list, base_date: datetime = None) -> list:
    """
    Generate schedule for up to 50 videos using sequential random anti-collision.
    base_date: datetime for the first video slot (default: today 02:00 + random 0-15 min)
    Returns list of {"path": ..., "schedule": "YYYY-MM-DD HH:MM"} sorted by time.
    """
    if not video_paths: return []

    if base_date is None:
        today = datetime.now().replace(hour=SCHEDULE_START_HOUR, minute=0, second=0, microsecond=0)
        base_date = today + timedelta(minutes=random.randint(0, 15))

    results = []
    current_dt = base_date
    first_dt = base_date

    for i, path in enumerate(video_paths[:MAX_STOK]):
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
            base_mins = candidate_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            rest_day_offset = candidate_dt - base_mins
            hours_so_far = int(rest_day_offset.total_seconds() // 3600)
            # Compute absolute datetime at end of rest period
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
#  GROK SELENIUM HELPERS (copied from grok_imagine_bot.py)
# ═══════════════════════════════════════════════════════════════
def open_chrome_grok(user_data_dir, port):
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
    dl_folder = os.path.expanduser("~/Downloads")

    try:
        driver.execute_script("""
            document.querySelectorAll('div[contenteditable="true"]').forEach(e=>{e.style.pointerEvents='none';e.style.zIndex='-1';});
            document.querySelectorAll('.tiptap,.ProseMirror').forEach(w=>{w.style.pointerEvents='none';w.style.zIndex='-1';});""")
        time.sleep(0.5)
    except: pass

    video_url = None
    try:
        video_url = driver.execute_script("""
            for(const v of document.querySelectorAll('video')){
                if(v.src&&v.src.startsWith('http'))return v.src;
                const s=v.querySelector('source');if(s&&s.src)return s.src;}
            for(const a of document.querySelectorAll('a[download],a[href*=".mp4"]')){if(a.href)return a.href;}
            return null;""")
    except: pass

    if video_url and video_url.startswith('http') and not video_url.startswith('blob'):
        try:
            cookies = {c['name']:c['value'] for c in driver.get_cookies()}
            headers = {'User-Agent': driver.execute_script('return navigator.userAgent;'), 'Referer': GROK_URL}
            resp = req_lib.get(video_url, cookies=cookies, headers=headers, stream=True, timeout=120)
            if resp.status_code == 200:
                with open(save_path,'wb') as vf:
                    for chunk in resp.iter_content(65536):
                        if chunk: vf.write(chunk)
                if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                    log_fn(f"{prefix} Downloaded via requests ({os.path.getsize(save_path)/1024/1024:.1f} MB)")
                    return save_path
        except Exception as e: log_fn(f"{prefix} requests err: {e}")

    dl_clicked = False
    try:
        dl_clicked = driver.execute_script("""
            for(const b of document.querySelectorAll('button')){
                const l=b.getAttribute('aria-label')||'';
                if(l==='Download'||l==='Unduh'){
                    b.scrollIntoView({block:'center'});
                    ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev=>
                        b.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                    return true;}} return false;""")
        if dl_clicked: log_fn(f"{prefix} Download diklik (JS)")
    except: pass

    if not dl_clicked:
        try:
            dl_btns = driver.find_elements(By.CSS_SELECTOR,'button[aria-label="Download"], button[aria-label="Unduh"]')
            if dl_btns:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", dl_btns[0])
                time.sleep(0.5); ActionChains(driver).move_to_element(dl_btns[0]).click().perform()
                dl_clicked = True; log_fn(f"{prefix} Download diklik (Selenium)")
        except: pass

    if not dl_clicked:
        try:
            dl_btns = driver.find_elements(By.CSS_SELECTOR,'button[aria-label="Download"], button[aria-label="Unduh"]')
            if dl_btns: dl_btns[0].send_keys(Keys.ENTER); dl_clicked = True
        except: pass

    if not dl_clicked: log_fn(f"{prefix} Tidak bisa klik Download"); return None

    log_fn(f"{prefix} Menunggu download (60 detik)...")
    for _ in range(60):
        time.sleep(1)
        for folder in [output_dir, dl_folder]:
            try:
                new_files = [f for f in glob.glob(os.path.join(folder,"*.mp4")) if os.path.getmtime(f) > start_time]
                if new_files and not glob.glob(os.path.join(folder,"*.crdownload")):
                    newest = max(new_files, key=os.path.getmtime)
                    if newest != save_path: shutil.move(newest, save_path)
                    log_fn(f"{prefix} Video: {filename}"); return save_path
            except: pass
    log_fn(f"{prefix} Timeout 60 detik"); return None

BRUTAL_RAW_DIR = os.path.join(APP_DIR, "brutal_stok_raw")

def generate_stok(needed, prompt_text, folder_name, log_fn, stop_event):
    os.makedirs(BRUTAL_STOK_DIR, exist_ok=True)
    os.makedirs(BRUTAL_RAW_DIR, exist_ok=True)
    # needed = jumlah video final yang dibutuhkan, raw harus 2x lipat (2 raw = 1 merged)
    target = needed * 2
    log_fn(f"Target generate: {target} raw -> {needed} video 20 detik")
    generated_raw = []; failed = 0

    chrome_proc = open_chrome_grok(BRUTAL_UD, BRUTAL_PORT)
    driver = None
    try:
        driver = connect_selenium_grok(BRUTAL_PORT)
        driver.execute_cdp_cmd("Page.setDownloadBehavior",{"behavior":"allow","downloadPath":BRUTAL_RAW_DIR})
        remaining = target
        while remaining > 0 and not stop_event.is_set():
            batch = min(remaining, 10)
            log_fn(f"=== Batch: {batch} tab (sisa {remaining}) ===")
            tab_handles = []; tab_status = {}; tab_prog = {}
            batch_start = time.time()
            for i in range(batch):
                if stop_event.is_set(): break
                img = get_random_bahan_image(folder_name)
                if not img: log_fn("Tidak ada gambar!"); break
                if i == 0: driver.get(GROK_URL); time.sleep(3)
                else: driver.switch_to.new_window('tab'); driver.get(GROK_URL); time.sleep(3)
                tab_handles.append(driver.current_window_handle)
                ok = setup_tab_grok(driver, img, prompt_text, log_fn, i)
                tab_status[i] = "generating" if ok else "failed"
                tab_prog[i] = 0
                if not ok: failed += 1
                time.sleep(1)
            if stop_event.is_set(): break
            timeout_start = time.time()
            while not stop_event.is_set():
                active = [i for i,s in tab_status.items() if s=="generating"]
                if not active: break
                if time.time()-timeout_start > 600:
                    for i in active: tab_status[i]="failed"; failed+=1
                    break
                for i in active:
                    if stop_event.is_set(): break
                    try:
                        driver.switch_to.window(tab_handles[i])
                        status, pct = check_tab_progress(driver)
                        if pct != tab_prog.get(i,0):
                            tab_prog[i]=pct
                            parts=[f"T{ti+1}:{tab_prog.get(ti,0) if tab_status.get(ti)=='generating' else ('OK' if tab_status.get(ti)=='done' else 'ERR')}" for ti in range(len(tab_handles))]
                            log_fn("Progress: "+' | '.join(parts))
                        if status=="done":
                            vp = download_tab_video(driver, BRUTAL_RAW_DIR, log_fn, i, batch_start)
                            if vp and os.path.exists(vp):
                                generated_raw.append(vp); tab_status[i]="done"
                                log_fn(f"[Tab {i+1}] Raw #{len(generated_raw)}")
                                batch_start = time.time()
                            else: tab_status[i]="failed"; failed+=1
                    except Exception as e: log_fn(f"[Tab {i+1}] {str(e)[:60]}")
                time.sleep(3)
            remaining = target - len(generated_raw)
            for h in driver.window_handles[1:]:
                try: driver.switch_to.window(h); driver.close()
                except: pass
            try: driver.switch_to.window(driver.window_handles[0])
            except: pass
            time.sleep(2)
    finally:
        try:
            if driver: driver.quit()
        except: pass
        try: chrome_proc.terminate()
        except: pass

    log_fn(f"Merge {len(generated_raw)} raw video...")
    merged = []
    for i in range(0, len(generated_raw)-1, 2):
        if stop_event.is_set(): break
        mp = merge_video_pair(generated_raw[i], generated_raw[i+1], BRUTAL_STOK_DIR, log_fn)
        if mp:
            merged.append(mp)
            for vp in [generated_raw[i], generated_raw[i+1]]:
                try:
                    if os.path.exists(vp): os.remove(vp)
                except: pass
    if len(generated_raw) % 2 == 1:
        leftover = generated_raw[-1]
        dest = os.path.join(BRUTAL_STOK_DIR, os.path.basename(leftover))
        try: shutil.move(leftover, dest); merged.append(dest)
        except: pass
    log_fn(f"Stok tersimpan: {len(merged)} video")
    return merged


def upload_schedule_tiktok(schedule, deskripsi, hashtags, log_fn, stop_event):
    if not schedule: return 0
    chrome_proc = open_chrome_debug(TIKTOK_UD, TIKTOK_PORT)
    driver = None; uploaded = 0
    try:
        driver = connect_selenium(TIKTOK_PORT)
        total = len(schedule)
        for idx, item in enumerate(schedule):
            if stop_event.is_set(): break
            path = item["path"]
            schedule_str = item["schedule"]
            if not os.path.exists(path):
                log_fn(f"[{idx+1}/{total}] File tidak ada, skip: {os.path.basename(path)}"); continue
            try:
                sched_dt = datetime.strptime(schedule_str, "%Y-%m-%d %H:%M")
            except:
                log_fn(f"[{idx+1}/{total}] Format jadwal error, skip"); continue
            log_fn(f"[{idx+1}/{total}] Upload: {os.path.basename(path)} | {schedule_str}")
            try:
                navigate_upload_page(driver, force=(idx > 0))
                time.sleep(3)
                do_upload_file(driver, os.path.normpath(path), log_fn)
                time.sleep(5)
                # Tambah nomor urut [1], [2], dst di depan deskripsi
                deskripsi_with_num = f"[{idx+1}] {deskripsi}" if deskripsi else ""
                do_post_video(driver, deskripsi_with_num, "", "", log_fn, sched_dt, stop_event,
                              add_sound=False, add_product=False, skip_switches=True,
                              hashtags=hashtags if hashtags else None)
                try: os.remove(path)
                except: pass
                uploaded += 1
                log_fn(f"  [{idx+1}/{total}] Upload sukses")
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
    log_fn(f"Upload selesai: {uploaded}/{len(schedule)}")
    return uploaded


def run_full_pipeline(uid, chat_id, bot, main_loop, stop_event):
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
    prompt_text = load_prompts().get(prompt_name,"")

    if not prompt_text:
        sendmsg(f"Prompt <code>{escape_html(prompt_name)}</code> tidak ditemukan!")
        log_done.set(); full_auto_task.pop(uid,None); return
    if not folder_name or not list_bahan_images(folder_name):
        sendmsg(f"Folder bahan <code>{escape_html(folder_name)}</code> kosong!")
        log_done.set(); full_auto_task.pop(uid,None); return

    needed = stok_needed()
    if needed <= 0:
        log_fn(f"Stok sudah penuh ({count_stok()}/{MAX_STOK}), skip generate")
        sendmsg(f"Stok penuh ({count_stok()}/{MAX_STOK}), langsung ke schedule.")
    else:
        sendmsg(f"<b>Pipeline dimulai!</b>\nStok: {count_stok()}/{MAX_STOK}\nGenerate: {needed} video")
        log_fn(f"STEP 1: Generate {needed} stok")
        merged = generate_stok(needed, prompt_text, folder_name, log_fn, stop_event)
        log_fn(f"Generate selesai: {len(merged)} video")
        sendmsg(f"Generate selesai! Stok: {count_stok()}/{MAX_STOK}")

    if stop_event.is_set():
        sendmsg("Pipeline dihentikan setelah generate."); log_done.set(); full_auto_task.pop(uid,None); return

    stok_files = list_stok()[:MAX_STOK]
    if not stok_files:
        sendmsg("Tidak ada stok video!"); log_done.set(); full_auto_task.pop(uid,None); return

    log_fn("STEP 2: Buat schedule")
    today_02 = datetime.now().replace(hour=SCHEDULE_START_HOUR,minute=0,second=0,microsecond=0)
    schedule = generate_schedule(stok_files, base_date=today_02)
    save_schedule(schedule)
    log_fn(f"Schedule: {len(schedule)} slot")
    preview = "\n".join([f"  {i+1}. <code>{s['schedule']}</code>" for i,s in enumerate(schedule[:8])])
    if len(schedule)>8: preview+=f"\n  ... +{len(schedule)-8} lagi"
    sendmsg(f"<b>Schedule ({len(schedule)} video):</b>\n{preview}\n\nMulai upload TikTok...")

    if stop_event.is_set():
        sendmsg("Pipeline dihentikan sebelum upload."); log_done.set(); full_auto_task.pop(uid,None); return

    log_fn("STEP 3: Upload TikTok")
    uploaded = upload_schedule_tiktok(schedule, deskripsi, hashtags, log_fn, stop_event)
    log_fn(f"Upload selesai: {uploaded}/{len(schedule)}")
    sendmsg(f"<b>Pipeline selesai!</b>\nTerupload: <b>{uploaded}/{len(schedule)}</b>\nSisa stok: <b>{count_stok()}</b>")
    log_done.set()
    full_auto_task.pop(uid, None)


def run_full_auto_daemon(uid, chat_id, bot, main_loop, stop_event):
    def sendmsg(text):
        asyncio.run_coroutine_threadsafe(bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    sendmsg(f"<b>Full Auto Aktif!</b>\nSetiap hari jam <b>{GENERATE_HOUR:02d}:00</b> WIB:\n"
            f"1. Generate {MAX_STOK} video via Grok\n"
            f"2. Schedule TikTok mulai jam {SCHEDULE_START_HOUR:02d}:00\n\nTekan Stop Auto untuk berhenti.")

    while not stop_event.is_set():
        now = datetime.now()
        target = now.replace(hour=GENERATE_HOUR, minute=0, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        wait_secs = (target - now).total_seconds()
        h = int(wait_secs//3600); m = int((wait_secs%3600)//60)
        sendmsg(f"<b>Full Auto:</b> Menunggu jam {GENERATE_HOUR:02d}:00...\n({h} jam {m} menit lagi)")
        elapsed = 0
        while elapsed < wait_secs and not stop_event.is_set():
            time.sleep(min(60, wait_secs-elapsed)); elapsed += 60
        if stop_event.is_set(): break
        sendmsg(f"<b>Jam {GENERATE_HOUR:02d}:00!</b> Memulai pipeline...")
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
        [InlineKeyboardButton("Upload TikTok Sekarang", callback_data="upload_now")],
        [InlineKeyboardButton("Stop Full Auto" if is_auto else "Full Auto (01:00 Harian)",
                              callback_data="stop_auto" if is_auto else "start_auto")],
        [InlineKeyboardButton("Refresh", callback_data="refresh")],
    ]
    if is_gen:
        rows.insert(3, [InlineKeyboardButton("Stop Generate", callback_data="stop_gen")])
    return InlineKeyboardMarkup(rows)


def status_text():
    s = load_settings(); stok = count_stok(); sched = load_schedule()
    return (f"<b>Brutal Bot</b>\n\n"
            f"Stok: <b>{stok}/{MAX_STOK}</b> video\n"
            f"Prompt: <code>{escape_html(s.get('prompt_name','(kosong)'))}</code>\n"
            f"Folder: <code>{escape_html(s.get('folder_name','(kosong)'))}</code>\n"
            f"Deskripsi: <code>{escape_html(s.get('deskripsi','(kosong)')[:50])}</code>\n"
            f"Hashtags: <code>{escape_html(', '.join('#'+h for h in s.get('hashtags',[])) or '(kosong)')}</code>\n"
            f"Schedule tersimpan: <b>{len(sched)}</b> slot\n"
            f"Generate jam: <b>{GENERATE_HOUR:02d}:00</b> | Schedule mulai: <b>{SCHEDULE_START_HOUR:02d}:00</b>")


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
            "<code>/set hashtags fyp, viral, tiktok</code>",
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
    else:
        await update.message.reply_text("Sub-command tidak dikenal."); return
    save_settings(s)
    await update.message.reply_text(f"<code>{sub}</code> = <code>{escape_html(val[:100])}</code>", parse_mode=ParseMode.HTML)


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
        text = ("<b>Settings</b>\n\nGunakan /set:\n"
                "<code>/set prompt NAMA</code>\n<code>/set folder NAMA</code>\n"
                "<code>/set desc teks...</code>\n<code>/set hashtags fyp, viral</code>\n\n"
                f"Prompt: {escape_html(', '.join(prompts.keys()))}\n"
                f"Folder: {escape_html(', '.join(folders))}")
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    if data == "gen_now":
        if active_gen_task.get(uid): await q.answer("Generate sudah berjalan!", show_alert=True); return
        s = load_settings(); needed = stok_needed()
        if needed <= 0: await q.answer(f"Stok sudah penuh ({MAX_STOK})!", show_alert=True); return
        prompt_text = load_prompts().get(s.get("prompt_name",""),"")
        if not prompt_text: await q.answer("Prompt belum diset!", show_alert=True); return
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
            merged = generate_stok(needed, prompt_text, s.get("folder_name",""), _log2, stop_evt)
            ld2.set()
            asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id,f"Generate selesai! {len(merged)} video.\nStok: {count_stok()}/{MAX_STOK}",parse_mode=ParseMode.HTML),main_loop)
            active_gen_task.pop(uid, None)
        t = threading.Thread(target=_gen, daemon=True)
        active_gen_task[uid] = {"stop": stop_evt, "thread": t}; t.start()
        await q.edit_message_text(f"<b>Generate dimulai!</b>\nTarget: {needed} video raw -> {needed//2} video 20 detik",
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
        preview = "\n".join([f"{i+1}. <code>{s['schedule']}</code>" for i,s in enumerate(schedule[:10])])
        if len(schedule)>10: preview+=f"\n... +{len(schedule)-10} lagi"
        await q.edit_message_text(f"<b>Schedule ({len(schedule)} video):</b>\n{preview}",
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    if data == "upload_now":
        schedule = load_schedule()
        if not schedule: await q.answer("Belum ada schedule! Buat dulu.", show_alert=True); return
        if active_upload_task.get(uid): await q.answer("Upload sudah berjalan!", show_alert=True); return
        s = load_settings(); stop_evt = threading.Event()
        def _upload():
            ll3=threading.Lock(); log3=[]
            def lg3(m):
                with ll3: log3.append(m)
            uploaded = upload_schedule_tiktok(schedule, s.get("deskripsi",""), s.get("hashtags",[]), lg3, stop_evt)
            asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id,f"Upload selesai! {uploaded}/{len(schedule)} video ke TikTok.",parse_mode=ParseMode.HTML),main_loop)
            active_upload_task.pop(uid,None)
        t = threading.Thread(target=_upload, daemon=True)
        active_upload_task[uid] = {"stop": stop_evt, "thread": t}; t.start()
        await q.edit_message_text(f"<b>Upload dimulai!</b>\n{len(schedule)} video ke TikTok.",
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    if data == "start_auto":
        if full_auto_task.get(uid): await q.answer("Full Auto sudah berjalan!", show_alert=True); return
        stop_evt = threading.Event()
        t = threading.Thread(target=run_full_auto_daemon,
                             args=(uid,chat_id,bot,main_loop,stop_evt), daemon=True)
        full_auto_task[uid] = {"stop": stop_evt, "thread": t}; t.start()
        await q.edit_message_text("<b>Full Auto aktif!</b>\nPipeline otomatis setiap hari jam 01:00.",
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    if data == "stop_auto":
        task = full_auto_task.get(uid)
        if task: task["stop"].set(); full_auto_task.pop(uid,None)
        await q.edit_message_text("<b>Full Auto dihentikan.</b>\n\n"+status_text(),
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return


async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start","Menu utama"),
        BotCommand("set","Atur settings"),
    ])


def main():
    os.makedirs(BRUTAL_STOK_DIR, exist_ok=True)
    os.makedirs(BRUTAL_RAW_DIR, exist_ok=True)
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Brutal Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
