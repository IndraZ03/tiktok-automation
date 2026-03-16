"""
GTT Core — Grok TikTok Bot Engine
Database, Grok generation, video merge, TikTok upload helpers.
"""
import os, sys, re, time, shutil, subprocess, json, threading, random, glob, copy
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
from tiktok_gui import open_chrome_debug, connect_selenium, navigate_upload_page, do_upload_file, do_post_video

APP_DIR = r"C:\tiktok_automation"
USER_DATA_BASE = os.path.join(APP_DIR, "user_data")
BAHAN_DIR = os.path.join(APP_DIR, "bahan")
PROMPTS_FILE = os.path.join(APP_DIR, "grok_prompts.json")
DB_FILE = os.path.join(APP_DIR, "gtt_db.json")
GROK_URL = "https://grok.com/imagine"
RAW_DIR = os.path.join(APP_DIR, "gtt_raw")

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
#  GROK SELENIUM HELPERS
# ═══════════════════════════════════════════════════════════════
def open_chrome_grok(user_data_dir, port):
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
    filename = f"gtt_{int(time.time())}_{tab_idx}.mp4"
    save_path = os.path.join(output_dir, filename)
    downloads_folder = os.path.expanduser("~/Downloads")
    try:
        driver.execute_script("""
            document.querySelectorAll('div[contenteditable="true"]').forEach(e=>{
                e.style.pointerEvents='none'; e.style.zIndex='-1'; });
            document.querySelectorAll('.tiptap,.ProseMirror').forEach(w=>{
                w.style.pointerEvents='none'; w.style.zIndex='-1'; });""")
        time.sleep(0.5)
    except: pass
    video_url = None
    try:
        video_url = driver.execute_script("""
            for(const v of document.querySelectorAll('video')){
                if(v.src&&(v.src.startsWith('http')||v.src.startsWith('blob')))return v.src;
                const s=v.querySelector('source');if(s&&s.src)return s.src;}
            for(const a of document.querySelectorAll('a[download],a[href*=".mp4"]')){
                if(a.href)return a.href;}
            return null;""")
    except: pass
    if video_url and video_url.startswith('http') and not video_url.startswith('blob'):
        log_fn(f"{prefix} URL video, download via requests...")
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
                    log_fn(f"{prefix} Video via requests ({sz:.1f} MB)")
                    return save_path
        except Exception as e:
            log_fn(f"{prefix} requests gagal: {e}")
    dl_clicked = False
    for method_name, method_fn in [
        ("Selenium", lambda: (
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});",
                driver.find_elements(By.CSS_SELECTOR,'button[aria-label="Download"], button[aria-label="Unduh"]')[0]),
            time.sleep(0.5),
            ActionChains(driver).move_to_element(
                driver.find_elements(By.CSS_SELECTOR,'button[aria-label="Download"], button[aria-label="Unduh"]')[0]
            ).click().perform())),
        ("JS", lambda: driver.execute_script("""
            for(const btn of document.querySelectorAll('button')){
                const l=btn.getAttribute('aria-label')||'';
                if(l==='Download'||l==='Unduh'){
                    btn.scrollIntoView({block:'center'});
                    ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev=>
                        btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                    return true;}} return false;""")),
        ("Enter", lambda: driver.find_elements(By.CSS_SELECTOR,
            'button[aria-label="Download"], button[aria-label="Unduh"]')[0].send_keys(Keys.ENTER)),
    ]:
        if dl_clicked: break
        try:
            result = method_fn()
            dl_clicked = True
            log_fn(f"{prefix} Download diklik ({method_name})")
        except: pass
    if not dl_clicked:
        log_fn(f"{prefix} Tidak bisa klik Download"); return None
    log_fn(f"{prefix} Menunggu file (max 60s)...")
    for _ in range(60):
        time.sleep(1)
        for search_dir in [output_dir, downloads_folder]:
            try:
                mp4s = glob.glob(os.path.join(search_dir, "*.mp4"))
                new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
                if new_files:
                    newest = max(new_files, key=os.path.getmtime)
                    if not glob.glob(os.path.join(search_dir, "*.crdownload")):
                        if newest != save_path: shutil.move(newest, save_path)
                        log_fn(f"{prefix} Video diunduh!")
                        return save_path
            except: pass
    log_fn(f"{prefix} Timeout download"); return None

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


def _start_chrome_session(grok_ud, grok_port, log_fn, ud_num):
    """Buka Chrome & connect Selenium. Return (chrome_proc, driver) or (None, None)."""
    log_fn(f"[UD {ud_num}] Membuka Chrome (port {grok_port})...")
    chrome_proc = open_chrome_grok(grok_ud, grok_port)
    try:
        driver = connect_selenium_grok(grok_port)
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": RAW_DIR})
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


def _run_mini_batch(driver, num_tabs, bahan_folder, prompt_text, log_fn, stop_event, ud_num):
    """
    Buka num_tabs tab, generate, download raw video.
    Return list of raw file paths yang berhasil didownload.
    """
    tab_handles = []
    tab_status = {}
    tab_prog = {}
    batch_start = time.time()
    generated = []

    # Phase 1: Setup semua tab (upload gambar + isi prompt + klik generate)
    for i in range(num_tabs):
        if stop_event.is_set(): break
        img = get_random_bahan_image(bahan_folder)
        if not img:
            log_fn(f"[UD {ud_num}] Tidak ada gambar bahan!"); break

        # Selalu buka tab baru (fresh)
        try:
            driver.switch_to.new_window('tab')
            # Tutup tab lama cuma di iterasi pertama
            if i == 0:
                old_handles = driver.window_handles
                if len(old_handles) > 1:
                    driver.switch_to.window(old_handles[0])
                    driver.close()
                    driver.switch_to.window(driver.window_handles[-1])
        except: pass
        driver.get(GROK_URL)
        time.sleep(3)

        tab_handles.append(driver.current_window_handle)
        ok = setup_tab_grok(driver, img, prompt_text, log_fn, i)
        tab_status[i] = "generating" if ok else "failed"
        tab_prog[i] = 0
        if not ok:
            log_fn(f"[UD {ud_num}] [Tab {i+1}] Setup gagal")
        time.sleep(1)

    if stop_event.is_set():
        return generated

    # Phase 2: Tunggu semua tab selesai generate & download
    timeout_global = time.time()
    tab_first_seen = {}  # Track kapan tab pertama kali dicek

    while not stop_event.is_set():
        active = [i for i, s in tab_status.items() if s == "generating"]
        if not active:
            break
        # Global timeout: 10 menit untuk seluruh batch
        if time.time() - timeout_global > 600:
            for i in active:
                tab_status[i] = "timeout"
                log_fn(f"[UD {ud_num}] [Tab {i+1}] Global timeout!")
            break

        for i in list(active):
            if stop_event.is_set(): break
            try:
                driver.switch_to.window(tab_handles[i])
                status, pct = check_tab_progress(driver)

                # Track waktu pertama kali tab dicek
                if i not in tab_first_seen:
                    tab_first_seen[i] = time.time()

                if pct != tab_prog.get(i, 0):
                    tab_prog[i] = pct
                    parts = []
                    for ti in range(len(tab_handles)):
                        s = tab_status.get(ti, "?")
                        if s == "generating":
                            parts.append(f"T{ti+1}:{tab_prog.get(ti,0)}%")
                        elif s == "done":
                            parts.append(f"T{ti+1}:OK")
                        else:
                            parts.append(f"T{ti+1}:ERR")
                    log_fn(f"[UD {ud_num}] {' | '.join(parts)}")

                # Deteksi stuck: tab 0% selama 90 detik 
                # sementara tab lain sudah progres (ada yang > 10% atau done)
                if tab_prog.get(i, 0) == 0 and status != "done":
                    elapsed = time.time() - tab_first_seen.get(i, time.time())
                    others_progressing = any(
                        tab_prog.get(ti, 0) > 10 or tab_status.get(ti) == "done"
                        for ti in range(len(tab_handles)) if ti != i
                    )
                    if elapsed > 90 and others_progressing:
                        tab_status[i] = "stuck"
                        log_fn(f"[UD {ud_num}] [Tab {i+1}] Stuck 0% selama {int(elapsed)}s, skip!")
                        continue

                if status == "done":
                    # Download dengan timeout ketat 60 detik
                    vp = download_tab_video(driver, RAW_DIR, log_fn, i, batch_start)
                    if vp and os.path.exists(vp) and os.path.getsize(vp) > 10000:
                        generated.append(vp)
                        tab_status[i] = "done"
                        log_fn(f"[UD {ud_num}] [Tab {i+1}] Raw #{len(generated)} OK")
                        batch_start = time.time()
                    else:
                        tab_status[i] = "dl_fail"
                        log_fn(f"[UD {ud_num}] [Tab {i+1}] Download gagal, skip")
            except Exception as e:
                log_fn(f"[UD {ud_num}] [Tab {i+1}] Error: {str(e)[:50]}")
                tab_status[i] = "error"
        time.sleep(3)

    # Tutup semua extra tab
    _close_all_extra_tabs(driver)

    ok_count = sum(1 for s in tab_status.values() if s == "done")
    fail_count = sum(1 for s in tab_status.values() if s != "done")
    log_fn(f"[UD {ud_num}] Mini-batch: {ok_count} OK, {fail_count} gagal/skip")
    return generated


def _merge_raw_list(raw_list, out_dir, log_fn, stop_event, ud_num):
    """Merge pairs of raw videos into 20s clips. Returns merged count."""
    merged_count = 0
    for i in range(0, len(raw_list) - 1, 2):
        if stop_event.is_set(): break
        mp = merge_video_pair(raw_list[i], raw_list[i + 1], out_dir, log_fn)
        if mp:
            merged_count += 1
            log_fn(f"[UD {ud_num}] Merged #{merged_count}: {os.path.basename(mp)}")
        # Hapus raw setelah merge
        for vp in [raw_list[i], raw_list[i + 1]]:
            try:
                if os.path.exists(vp): os.remove(vp)
            except: pass
    return merged_count


def generate_stok_for_ud(ud_num, needed, prompt_text, bahan_folder, grok_ud, grok_port, log_fn, stop_event):
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
    out_dir = stok_dir(ud_num)
    os.makedirs(RAW_DIR, exist_ok=True)
    target = needed
    batch_num = 0
    total_merged_this_session = 0
    merged_since_restart = 0
    consecutive_fails = 0
    raw_pool = []  # Sisa raw yang belum di-merge (ganjil)

    log_fn(f"[UD {ud_num}] Target: {target} merged 20s videos")
    log_fn(f"[UD {ud_num}] Mode: {TABS_PER_BATCH} tab/batch, restart Chrome tiap {RESTART_EVERY_MERGED} merged")

    chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num)
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
                    chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num)
                    if not driver:
                        log_fn(f"[UD {ud_num}] Chrome restart gagal, abort!")
                        break
                    consecutive_fails = 0
                    merged_since_restart = 0
                    continue

                # Cek apakah driver masih hidup
                if driver is None:
                    log_fn(f"[UD {ud_num}] Driver mati, restart Chrome...")
                    chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num)
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
                new_raw = _run_mini_batch(driver, tabs_this_batch, bahan_folder, prompt_text, log_fn, stop_event, ud_num)

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

                    merged_count = _merge_raw_list(pairs_to_merge, out_dir, log_fn, stop_event, ud_num)
                    total_merged_this_session += merged_count
                    merged_since_restart += merged_count
                    log_fn(f"[UD {ud_num}] Progress: {total_merged_this_session}/{target} merged (stok: {count_stok(ud_num)})")

                if stop_event.is_set(): break

                # Restart Chrome tiap RESTART_EVERY_MERGED merged
                if merged_since_restart >= RESTART_EVERY_MERGED:
                    log_fn(f"[UD {ud_num}] Restart Chrome ({merged_since_restart} merged)...")
                    _stop_chrome_session(chrome_proc, driver, log_fn, ud_num)
                    chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num)
                    if not driver:
                        log_fn(f"[UD {ud_num}] Chrome restart gagal, abort!")
                        break
                    merged_since_restart = 0

            except Exception as e:
                # Chrome crash / koneksi putus → restart otomatis
                log_fn(f"[UD {ud_num}] ⚠️ Chrome error: {str(e)[:80]}")
                log_fn(f"[UD {ud_num}] Auto-restart Chrome...")
                try: _stop_chrome_session(chrome_proc, driver, log_fn, ud_num)
                except: pass
                driver = None
                time.sleep(5)
                chrome_proc, driver = _start_chrome_session(grok_ud, grok_port, log_fn, ud_num)
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
                mc = _merge_raw_list(raw_pool, out_dir, log_fn, stop_event, ud_num)
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
    """Upload videos to TikTok with scheduling. Returns uploaded count."""
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
    # Backward compat
    if not nama_produk_radio_list and nama_produk_radio:
        nama_produk_radio_list = [nama_produk_radio]
    nama_produk_input = ud_cfg.get("nama_produk_input", "")
    add_product = ud_cfg.get("add_product", True)
    add_sound = ud_cfg.get("add_sound", False)

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
                log_fn(f"[UD {ud_num}] [{idx+1}/{total}] Format jadwal error"); 
                item["status"] = "skipped"; save_ud_schedule(ud_num, schedule); continue

            # Pick random produk_radio with retry
            radio_candidates = list(nama_produk_radio_list) if nama_produk_radio_list else ([nama_produk_radio] if nama_produk_radio else [])
            if radio_candidates:
                random.shuffle(radio_candidates)
                log_fn(f"[UD {ud_num}] [{idx+1}/{total}] 🎲 Produk: {radio_candidates[0][:40]}")

            log_fn(f"[UD {ud_num}] [{idx+1}/{total}] Upload: {os.path.basename(path)} | {item['schedule']}")
            try:
                navigate_upload_page(driver, force=(idx > 0))
                time.sleep(3)
                do_upload_file(driver, os.path.normpath(path), log_fn)
                time.sleep(5)
                desc_with_num = f"[{idx+1}] {deskripsi}" if deskripsi else ""

                # Retry produk radio
                post_ok = False
                tried = []
                for radio_try in radio_candidates if radio_candidates else [""]:
                    try:
                        do_post_video(driver, desc_with_num, radio_try, nama_produk_input,
                                      log_fn, sched_dt, stop_event,
                                      add_sound=add_sound, add_product=add_product,
                                      skip_switches=True, hashtags=hashtags if hashtags else None)
                        post_ok = True; break
                    except Exception as e_post:
                        tried.append(radio_try)
                        err_msg = str(e_post).lower()
                        if any(kw in err_msg for kw in ["radio", "produk", "timeout", "presence", "not found", "xpath"]):
                            log_fn(f"[UD {ud_num}]   ⚠️ '{radio_try[:30]}' tidak ada, coba lain...")
                            continue
                        else:
                            raise
                if not post_ok:
                    raise Exception(f"Semua produk radio gagal: {', '.join(t[:20] for t in tried)}")

                try: os.remove(path)
                except: pass
                uploaded += 1
                item["status"] = "done"
                save_ud_schedule(ud_num, schedule)
                log_fn(f"[UD {ud_num}] [{idx+1}/{total}] Upload sukses (saved)")
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
