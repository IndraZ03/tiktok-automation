
import os, sys, re, time, shutil, asyncio, subprocess, logging, json, threading, random, glob
from datetime import datetime, timedelta

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
    ConversationHandler,
)
from telegram.constants import ParseMode
from selenium import webdriver
# ── Selenium imports ──

from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8781330231:AAFZ5enn-P5tIBMwwGe5rOLNgRQ8YWAmfNg"
ALLOWED_USER_IDS = []  # Kosong = semua user boleh

APP_DIR        = r"C:\tiktok_automation"
BAHAN_DIR      = os.path.join(APP_DIR, "bahan")
OUTPUT_DIR     = os.path.join(APP_DIR, "grok_output")
MERGED_DIR     = os.path.join(APP_DIR, "grok_output_merged")
MERGED_DIR     = os.path.join(APP_DIR, "grok_output_merged")
PROMPTS_FILE   = os.path.join(APP_DIR, "grok_prompts.json")
SETTINGS_FILE  = os.path.join(APP_DIR, "grok_imagine_settings.json")

GROK_URL       = "https://grok.com/imagine"
DEFAULT_USER_DATA = os.path.join(APP_DIR, "user_data", "1")
DEFAULT_PORT   = "9245"

# ═══════════════════════════════════════════════════════════════
#  BOT SETTINGS PERSISTENCE
# ═══════════════════════════════════════════════════════════════
def load_bot_settings() -> dict:
    defaults = {"user_data_dir": DEFAULT_USER_DATA, "port": DEFAULT_PORT, "merge_duration": 20}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return {**defaults, **json.load(f)}
        except:
            pass
    return defaults

def save_bot_settings(cfg: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

bot_settings = load_bot_settings()

# ═══════════════════════════════════════════════════════════════
#  PROMPTS DATABASE
# ═══════════════════════════════════════════════════════════════
def load_prompts() -> dict:
    """Load prompts from JSON. Returns {name: text}."""
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

def get_random_bahan_image(folder_name: str) -> str | None:
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


# ═══════════════════════════════════════════════════════════════
#  VIDEO MERGE (FFmpeg concat)
# ═══════════════════════════════════════════════════════════════
def merge_video_pair(vid1: str, vid2: str, output_dir: str, log_fn=None) -> str | None:
    """
    Gabungkan 2 video menjadi 1 menggunakan FFmpeg concat demuxer.
    Returns path to merged video or None on failure.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Tentukan nomor output berikutnya
    existing = glob.glob(os.path.join(output_dir, "*.mp4"))
    existing_nums = []
    for f in existing:
        m = re.fullmatch(r'(\d+)\.mp4', os.path.basename(f))
        if m:
            existing_nums.append(int(m.group(1)))
    next_num = (max(existing_nums) + 1) if existing_nums else 1

    out_name = f"{next_num}.mp4"
    out_path = os.path.join(output_dir, out_name)

    # Buat file daftar (concat demuxer)
    list_file = os.path.join(output_dir, f"_merge_list_{next_num}.txt")
    try:
        with open(list_file, "w", encoding="utf-8") as lf:
            lf.write(f"file '{vid1}'\n")
            lf.write(f"file '{vid2}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            out_path
        ]
        if log_fn:
            log_fn(
                f"🎬 Merge: {os.path.basename(vid1)} + {os.path.basename(vid2)} → {out_name}"
            )
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            if log_fn:
                sz = os.path.getsize(out_path) / (1024 * 1024)
                log_fn(f"✅ Merged: {out_name} ({sz:.1f} MB)")
            return out_path
        else:
            if log_fn:
                log_fn(f"❌ Merge gagal: {result.stderr[-200:] if result.stderr else 'unknown'}")
            return None
    except FileNotFoundError:
        if log_fn:
            log_fn("❌ FFmpeg tidak ditemukan! Pastikan ffmpeg ada di PATH.")
        return None
    except subprocess.TimeoutExpired:
        if log_fn:
            log_fn("⚠️ FFmpeg merge timeout (120s)")
        return None
    except Exception as e:
        if log_fn:
            log_fn(f"❌ Error merge: {str(e)[:100]}")
        return None
    finally:
        if os.path.exists(list_file):
            try:
                os.remove(list_file)
            except:
                pass

# ═══════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════
active_gen_tasks = {}   # uid -> {"stop": Event, "thread": Thread}

# Conversation states
WAITING_PROMPT_NAME, WAITING_PROMPT_TEXT = range(2)
WAITING_FOLDER_NAME = 10
WAITING_BAHAN_PHOTO = 11

# ═══════════════════════════════════════════════════════════════
#  SELENIUM: CHROME + GROK
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
    """Navigate to grok.com/imagine with retry logic."""
    for attempt in range(1, max_retries + 1):
        try:
            current = driver.current_url
            if "grok.com" in current and "imagine" in current:
                log_fn("✅ Sudah di halaman Grok Imagine")
                return True
        except:
            pass

        try:
            log_fn(f"🌐 Navigasi ke Grok Imagine (attempt {attempt}/{max_retries})...")
            driver.get(GROK_URL)
            time.sleep(5)
            current = driver.current_url
            if "imagine" in current:
                log_fn("✅ Navigasi berhasil!")
                return True
        except Exception as e:
            log_fn(f"⚠️ Navigasi gagal: {e}")

        if attempt < max_retries:
            try:
                log_fn("🔄 Membuka tab baru...")
                driver.switch_to.new_window('tab')
                driver.get(GROK_URL)
                time.sleep(5)
                if "imagine" in driver.current_url:
                    log_fn("✅ Navigasi berhasil via tab baru!")
                    return True
            except Exception as e:
                log_fn(f"⚠️ Tab baru gagal: {e}")

    log_fn("❌ Gagal navigasi ke Grok Imagine")
    return False


def generate_one_video_grok(image_path, prompt_text, log_fn, stop_event, output_dir,
                             user_data_dir=None, port=None):
    """
    Automate one video generation on grok.com/imagine:
    1. Upload image via file input (with reload-retry on failure)
    2. Type prompt text
    3. Click generate button
    4. Track progress percentage
    5. Download the result video (multiple methods)
    Returns: path to downloaded video or None
    """
    import requests as req_lib
    os.makedirs(output_dir, exist_ok=True)

    ud = user_data_dir or bot_settings.get("user_data_dir", DEFAULT_USER_DATA)
    pt = port or bot_settings.get("port", DEFAULT_PORT)

    log_fn("🌐 Membuka Chrome untuk Grok Imagine...")
    chrome_proc = open_chrome_grok(ud, pt)
    driver = None

    try:
        driver = connect_selenium_grok(pt)
        driver.execute_cdp_cmd("Page.setDownloadBehavior",
                               {"behavior": "allow", "downloadPath": output_dir})

        if not navigate_to_grok(driver, log_fn):
            return None

        if stop_event.is_set():
            return None

        time.sleep(3)

        # ─────────────────────────────────────────────────────────
        # UPLOAD + PROMPT: outer retry loop (reload on full failure)
        # Each iteration: try upload → fill prompt → if both ok, break
        # ─────────────────────────────────────────────────────────
        image_uploaded = False
        prompt_filled  = False
        abs_image = os.path.abspath(image_path) if (image_path and os.path.exists(image_path)) else None

        def _count_uploaded_images(drv):
            try:
                return drv.execute_script("""
                    let c = 0;
                    c += document.querySelectorAll('img[src*="assets.grok.com"]').length;
                    c += document.querySelectorAll('img[src^="blob:"]').length;
                    c += document.querySelectorAll('div.group.relative img').length;
                    return c;
                """)
            except:
                return 0

        def _verify_image_uploaded(drv, before_count, timeout=10):
            for _ in range(timeout * 2):
                try:
                    if _count_uploaded_images(drv) > before_count:
                        return True
                    has_preview = drv.execute_script("""
                        const g = document.querySelector('div.group.relative');
                        if (g) { const r = g.getBoundingClientRect();
                            if (r.width > 50 && r.height > 50) return true; }
                        return false;
                    """)
                    if has_preview:
                        return True
                except:
                    pass
                time.sleep(0.5)
            return False

        def _try_upload_image(drv, a_img, before_count):
            """Try all upload methods. Returns True if verified uploaded."""
            # Method A: find existing file inputs
            try:
                inputs = drv.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if inputs:
                    log_fn(f"🔍 {len(inputs)} file input ditemukan")
                    for idx2, fi in enumerate(inputs):
                        try:
                            drv.execute_script(
                                "arguments[0].style.cssText='display:block!important;"
                                "visibility:visible!important;opacity:1!important;"
                                "position:absolute;top:0;left:0;width:1px;height:1px;';", fi)
                            fi.send_keys(a_img)
                            log_fn(f"📤 Sent ke input[{idx2}], verifikasi...")
                            time.sleep(3)
                            if _verify_image_uploaded(drv, before_count):
                                log_fn("✅ Upload + verifikasi berhasil (Method A)!")
                                return True
                            log_fn(f"⚠️ Input[{idx2}] tidak ada preview")
                        except Exception as ex:
                            log_fn(f"⚠️ Input[{idx2}] err: {ex}")
            except Exception as ex:
                log_fn(f"⚠️ Method A err: {ex}")

            # Method B: inject new file input
            try:
                log_fn("🔄 Method B: inject file input...")
                iid = f"_gbf_{int(time.time())}"
                drv.execute_script(f"""
                    let o = document.getElementById('{iid}'); if(o) o.remove();
                    const inp = document.createElement('input');
                    inp.type='file'; inp.id='{iid}'; inp.accept='image/*';
                    inp.style.cssText='position:absolute;top:0;left:0;z-index:99999;"
                                      "display:block;width:1px;height:1px;';
                    document.body.appendChild(inp);
                """)
                time.sleep(0.5)
                inj = drv.find_element(By.ID, iid)
                inj.send_keys(a_img)
                log_fn("📤 Sent ke injected input, verifikasi...")
                time.sleep(3)
                if _verify_image_uploaded(drv, before_count):
                    log_fn("✅ Upload + verifikasi berhasil (Method B)!")
                    return True
                log_fn("⚠️ Injected input tidak ada preview")
            except Exception as ex:
                log_fn(f"⚠️ Method B err: {ex}")

            return False

        def _try_fill_prompt(drv, p_text):
            """Try filling prompt. Returns True on success."""
            # Method A: click + JS innerHTML
            try:
                ed = drv.execute_script("""
                    const e = document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                    if (e) { e.scrollIntoView({behavior:'smooth',block:'center'}); return e; }
                    return null;
                """)
                if ed:
                    time.sleep(0.4)
                    drv.execute_script("arguments[0].focus();", ed)
                    time.sleep(0.3)
                    ed.click()
                    time.sleep(0.3)
                    ed.send_keys(Keys.CONTROL + "a")
                    time.sleep(0.2)
                    ed.send_keys(Keys.DELETE)
                    time.sleep(0.2)
                    drv.execute_script("""
                        const e=arguments[0];
                        e.innerHTML='<p>'+arguments[1]+'</p>';
                        e.dispatchEvent(new Event('input',{bubbles:true}));
                        e.dispatchEvent(new Event('change',{bubbles:true}));
                        e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));
                    """, ed, p_text)
                    time.sleep(1)
                    # Verify prompt actually has text
                    actual = drv.execute_script(
                        "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent || '';")
                    if actual.strip():
                        log_fn(f"✅ Prompt diisi (Method A): {p_text[:60]}...")
                        return True
            except Exception as ex:
                log_fn(f"⚠️ Prompt Method A: {ex}")

            # Method B: pure JS
            try:
                log_fn("🔄 Prompt Method B: pure JS...")
                r = drv.execute_script("""
                    const e=document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                    if (!e) return 'not_found';
                    e.scrollIntoView({block:'center'}); e.focus();
                    e.innerHTML='<p>'+arguments[0]+'</p>';
                    e.dispatchEvent(new Event('input',{bubbles:true}));
                    e.dispatchEvent(new Event('change',{bubbles:true}));
                    e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));
                    return 'ok';
                """, p_text)
                if r == 'ok':
                    time.sleep(1)
                    actual = drv.execute_script(
                        "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent || '';")
                    if actual.strip():
                        log_fn(f"✅ Prompt diisi (Method B): {p_text[:60]}...")
                        return True
                else:
                    log_fn("⚠️ Editor tidak ada di DOM")
            except Exception as ex:
                log_fn(f"⚠️ Prompt Method B: {ex}")

            # Method C: WebDriverWait + typing
            try:
                log_fn("🔄 Prompt Method C: typing...")
                ed = WebDriverWait(drv, 20).until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'div.tiptap.ProseMirror[contenteditable="true"]')))
                drv.execute_script("arguments[0].scrollIntoView({block:'center'});", ed)
                time.sleep(1)
                ed.click()
                time.sleep(0.5)
                ed.send_keys(Keys.CONTROL + "a")
                ed.send_keys(Keys.DELETE)
                time.sleep(0.3)
                for chunk in [p_text[i:i+50] for i in range(0, len(p_text), 50)]:
                    ed.send_keys(chunk)
                    time.sleep(0.1)
                time.sleep(1)
                actual = drv.execute_script(
                    "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent || '';")
                if actual.strip():
                    log_fn(f"✅ Prompt diisi (Method C): {p_text[:60]}...")
                    return True
            except Exception as ex:
                log_fn(f"⚠️ Prompt Method C: {ex}")

            return False

        # ── OUTER RETRY LOOP: upload + prompt (max 4 full attempts) ──
        OUTER_MAX = 4
        for outer_attempt in range(1, OUTER_MAX + 1):
            if stop_event.is_set():
                return None

            if outer_attempt > 1:
                log_fn(f"🔄 RELOAD halaman (outer attempt {outer_attempt}/{OUTER_MAX})...")
                try:
                    driver.refresh()
                    time.sleep(6)
                    if not navigate_to_grok(driver, log_fn):
                        log_fn("❌ Gagal navigasi ulang")
                        continue
                    time.sleep(3)
                except Exception as e:
                    log_fn(f"⚠️ Reload gagal: {e}")
                    continue

            image_uploaded = False
            prompt_filled  = False
            images_before = _count_uploaded_images(driver)

            # ── Upload image ──
            if abs_image:
                log_fn(f"📷 Mengunggah gambar: {os.path.basename(abs_image)} (outer {outer_attempt})")
                # Inner upload retry (2 sub-attempts before outer reload)
                for inner in range(1, 3):
                    if _try_upload_image(driver, abs_image, images_before):
                        image_uploaded = True
                        break
                    if inner < 2:
                        log_fn(f"⚠️ Inner upload attempt {inner} gagal, tunggu 3s...")
                        time.sleep(3)

                if not image_uploaded:
                    log_fn(f"❌ Upload gagal (outer {outer_attempt}), akan reload...")
                    continue  # trigger outer reload
            else:
                log_fn("⚠️ Tidak ada gambar, generate tanpa gambar")
                image_uploaded = True  # skip upload check

            if stop_event.is_set():
                return None

            # ── Fill prompt (inside outer loop) ──
            log_fn("📝 Mengisi prompt...")
            prompt_filled = _try_fill_prompt(driver, prompt_text)

            if not prompt_filled:
                log_fn(f"❌ Prompt gagal diisi (outer {outer_attempt}), akan reload...")
                continue  # trigger outer reload

            # Both upload + prompt OK — break outer loop
            log_fn("✅ Upload & prompt berhasil, lanjut ke settings...")
            break  # exit outer retry loop

        if stop_event.is_set():
            return None

        # If prompt still not filled after all retries, abort
        if not prompt_filled:
            log_fn("❌ Prompt gagal diisi setelah semua attempt, abort!")
            return None

        # ── Step 3: Click Settings/Pengaturan → Buat Video ──
        log_fn("⚙️ Klik tombol Settings...")
        settings_opened = False

        # Method A: Selenium native click
        try:
            settings_btns = driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Settings"], button[aria-label="Pengaturan"]')
            if settings_btns:
                ActionChains(driver).move_to_element(settings_btns[0]).click().perform()
                time.sleep(1.5)
                if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                    settings_opened = True
                    log_fn("✅ Settings dropdown terbuka (Selenium click)")
        except Exception as e:
            log_fn(f"⚠️ Selenium click gagal: {e}")

        # Method B: JS pointer events
        if not settings_opened:
            try:
                driver.execute_script("""
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        const l = btn.getAttribute('aria-label') || '';
                        if (l === 'Settings' || l === 'Pengaturan') {
                            ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev =>
                                btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev, {bubbles:true,cancelable:true})));
                            return true;
                        }
                    } return false;
                """)
                time.sleep(1.5)
                if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                    settings_opened = True
                    log_fn("✅ Settings dropdown terbuka (pointer events)")
            except Exception as e:
                log_fn(f"⚠️ Pointer events gagal: {e}")

        # Method C: Enter key
        if not settings_opened:
            try:
                sb = driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Settings"], button[aria-label="Pengaturan"]')
                if sb:
                    sb[0].send_keys(Keys.ENTER)
                    time.sleep(1.5)
                    if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                        settings_opened = True
                        log_fn("✅ Settings dropdown terbuka (Enter key)")
            except Exception as e:
                log_fn(f"⚠️ Enter key gagal: {e}")

        if settings_opened:
            log_fn("🎬 Memilih 'Buat Video'...")
            try:
                menu_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
                clicked = False
                for item in menu_items:
                    txt = item.text or ""
                    if "Buat Video" in txt or "Make Video" in txt or "Make video" in txt:
                        ActionChains(driver).move_to_element(item).click().perform()
                        clicked = True
                        break
                if not clicked:
                    driver.execute_script("""
                        const items = document.querySelectorAll('div[role="menuitem"]');
                        for (const item of items) {
                            const t = item.textContent || '';
                            if (t.includes('Buat Video') || t.includes('Make Video') || t.includes('Make video')) {
                                item.click(); return true; }
                        }
                        const spans = document.querySelectorAll('span.font-semibold');
                        for (const s of spans) {
                            const t = s.textContent.trim();
                            if (t === 'Buat Video' || t === 'Make Video') {
                                (s.closest('div[role="menuitem"]') || s.parentElement).click();
                                return true; }
                        } return false;
                    """)
                time.sleep(1)
                log_fn("✅ Mode 'Buat Video' dipilih!")
            except Exception as e:
                log_fn(f"⚠️ Gagal pilih Buat Video: {e}")
        else:
            log_fn("⚠️ Settings dropdown tidak terbuka, lanjut tanpa pilih mode")

        if stop_event.is_set():
            return None


        # ── Step 4: Click Generate button ──
        log_fn("🚀 Klik Generate...")
        try:
            # Try multiple aria-labels (ID/EN)
            gen_btn = None
            for label in ['Buat video', 'Create video', 'Generate', 'Submit']:
                try:
                    gen_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, f'button[aria-label="{label}"]')))
                    if gen_btn:
                        break
                except:
                    continue

            if not gen_btn:
                # Fallback: find the round submit button with arrow icon
                try:
                    gen_btn = driver.find_element(
                        By.CSS_SELECTOR, 'button.group[type="button"]')
                except:
                    pass

            if gen_btn:
                gen_btn.click()
                log_fn("✅ Generate diklik!")
            else:
                # Last resort: JS click
                driver.execute_script("""
                    const btn = document.querySelector('button[aria-label="Buat video"]')
                              || document.querySelector('button[aria-label="Create video"]')
                              || document.querySelector('button.group[type="button"]');
                    if (btn) btn.click();
                """)
                log_fn("✅ Generate diklik via JS!")
            time.sleep(3)
        except Exception as e:
            log_fn(f"❌ Gagal klik Generate: {e}")
            return None

        # ── Step 4: Track progress ──
        log_fn("⏳ Menunggu video selesai (max 10 menit)...")
        start_time = time.time()
        last_pct = ""
        last_pct_num = 0
        generation_started = False
        while time.time() - start_time < 600:
            if stop_event.is_set():
                return None

            # Read progress percentage via JS
            try:
                pct_text = driver.execute_script("""
                    const spans = document.querySelectorAll('span.tabular-nums');
                    for (const s of spans) {
                        const t = s.textContent.trim();
                        if (t.includes('%')) return t;
                    }
                    const overlay = document.querySelector('div.flex.justify-center.items-center.gap-2');
                    if (overlay) {
                        const nums = overlay.querySelectorAll('span');
                        for (const n of nums) {
                            if (n.textContent.includes('%')) return n.textContent.trim();
                        }
                    }
                    return '';
                """)
                if pct_text and pct_text != last_pct:
                    log_fn(f"⏳ Progress: {pct_text}")
                    last_pct = pct_text
                    generation_started = True
                    # Extract numeric value
                    m = re.search(r'(\d+)', pct_text)
                    if m:
                        last_pct_num = int(m.group(1))
            except:
                pass

            # Check if 'Menghasilkan'/'Generating' overlay is still present
            try:
                is_generating = driver.execute_script("""
                    const spans = document.querySelectorAll('span');
                    for (const s of spans) {
                        const t = s.textContent;
                        if (t.includes('Menghasilkan') || t.includes('Generating')) return true;
                    }
                    return false;
                """)
            except:
                is_generating = False

            # Only consider done if generation was started and overlay is gone
            if generation_started and not is_generating and last_pct_num > 0:
                log_fn("✅ Generasi selesai! Menunggu video muncul...")
                time.sleep(3)  # Beri waktu video element muncul
                break

            time.sleep(1)
        else:
            log_fn("❌ Timeout: video tidak selesai dalam 10 menit")
            return None

        if stop_event.is_set():
            return None

        # ── Step 5: Download the video ──
        log_fn("📥 Mengunduh video...")
        filename = f"grok_{int(time.time())}.mp4"
        save_path = os.path.join(output_dir, filename)
        downloaded = False
        downloads_folder = os.path.expanduser("~/Downloads")

        # ── Sub-step: dismiss/hide textarea that blocks Download button ──
        try:
            driver.execute_script("""
                // Hide the tiptap ProseMirror editor div so it doesn't block Download button
                const editors = document.querySelectorAll('div[contenteditable="true"]');
                editors.forEach(e => { e.style.pointerEvents = 'none'; e.style.zIndex = '-1'; });
                // Also hide its parent wrappers if they cover the button
                const wrappers = document.querySelectorAll('.tiptap, .ProseMirror');
                wrappers.forEach(w => { w.style.pointerEvents = 'none'; w.style.zIndex = '-1'; });
            """)
            time.sleep(0.5)
            log_fn("🧹 Editor div disembunyikan (agar tidak tutup Download button)")
        except Exception as e:
            log_fn(f"⚠️ Gagal sembunyikan editor: {e}")

        # ── Method 0: Extract video URL from DOM and download with requests ──
        video_url = None
        try:
            video_url = driver.execute_script("""
                // Try video element src
                const videos = document.querySelectorAll('video');
                for (const v of videos) {
                    if (v.src && (v.src.startsWith('http') || v.src.startsWith('blob'))) return v.src;
                    const src = v.querySelector('source');
                    if (src && src.src) return src.src;
                }
                // Try anchor download links
                const links = document.querySelectorAll('a[download], a[href*=".mp4"]');
                for (const a of links) { if (a.href) return a.href; }
                return null;
            """)
        except Exception as e:
            log_fn(f"⚠️ Extract video URL gagal: {e}")

        if video_url and video_url.startswith('http') and not video_url.startswith('blob'):
            log_fn(f"🔗 URL video ditemukan, download via requests...")
            try:
                cookies = {c['name']: c['value'] for c in driver.get_cookies()}
                headers = {'User-Agent': driver.execute_script('return navigator.userAgent;'),
                           'Referer': GROK_URL}
                resp = req_lib.get(video_url, cookies=cookies, headers=headers,
                                   stream=True, timeout=120)
                if resp.status_code == 200:
                    with open(save_path, 'wb') as vf:
                        for chunk in resp.iter_content(65536):
                            if chunk:
                                vf.write(chunk)
                    if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                        downloaded = True
                        sz = os.path.getsize(save_path)/(1024*1024)
                        log_fn(f"✅ Video didownload via requests ({sz:.1f} MB)")
                    else:
                        log_fn("⚠️ File dari requests terlalu kecil/kosong")
                else:
                    log_fn(f"⚠️ requests status {resp.status_code}")
            except Exception as e:
                log_fn(f"⚠️ Download via requests gagal: {e}")

        if not downloaded:
            # ── Method A: Selenium scroll + click Download button ──
            dl_clicked = False
            try:
                dl_btns = driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Download"], button[aria-label="Unduh"]')
                if dl_btns:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", dl_btns[0])
                    time.sleep(0.5)
                    ActionChains(driver).move_to_element(dl_btns[0]).click().perform()
                    dl_clicked = True
                    log_fn("✅ Tombol Download diklik (Selenium + scroll)")
            except Exception as e:
                log_fn(f"⚠️ Selenium click Download gagal: {e}")

            # ── Method B: JS pointer events on Download button ──
            if not dl_clicked:
                try:
                    dl_clicked = driver.execute_script("""
                        const btns = document.querySelectorAll('button');
                        for (const btn of btns) {
                            const l = btn.getAttribute('aria-label') || '';
                            if (l === 'Download' || l === 'Unduh') {
                                btn.scrollIntoView({block:'center'});
                                ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev =>
                                    btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                                return true;
                            }
                        } return false;
                    """)
                    if dl_clicked:
                        log_fn("✅ Tombol Download diklik (JS pointer events)")
                except Exception as e:
                    log_fn(f"⚠️ JS pointer events Download gagal: {e}")

            # ── Method C: Enter key on Download button ──
            if not dl_clicked:
                try:
                    dl_btns = driver.find_elements(By.CSS_SELECTOR,
                        'button[aria-label="Download"], button[aria-label="Unduh"]')
                    if dl_btns:
                        dl_btns[0].send_keys(Keys.ENTER)
                        dl_clicked = True
                        log_fn("✅ Tombol Download diklik (Enter key)")
                except Exception as e:
                    log_fn(f"⚠️ Enter key Download gagal: {e}")

            # ── Method D: Direct JS click (bypass overlay) ──
            if not dl_clicked:
                try:
                    dl_clicked = driver.execute_script("""
                        const sel = ['button[aria-label="Download"]','button[aria-label="Unduh"]',
                                     'a[download]','a[href*=".mp4"]'];
                        for (const s of sel) {
                            const el = document.querySelector(s);
                            if (el) { el.click(); return true; }
                        } return false;
                    """)
                    if dl_clicked:
                        log_fn("✅ Tombol Download diklik (Method D JS direct click)")
                except Exception as e:
                    log_fn(f"⚠️ Method D gagal: {e}")

            if not dl_clicked:
                log_fn("❌ Tidak bisa klik tombol Download")
            else:
                # Wait for file to appear
                log_fn("⏳ Menunggu file terdownload (max 60 detik)...")
                for wait_sec in range(60):
                    time.sleep(1)
                    # Check output_dir
                    try:
                        mp4s = glob.glob(os.path.join(output_dir, "*.mp4"))
                        new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
                        if new_files:
                            newest = max(new_files, key=os.path.getmtime)
                            if not glob.glob(os.path.join(output_dir, "*.crdownload")):
                                if newest != save_path:
                                    shutil.move(newest, save_path)
                                downloaded = True
                                log_fn(f"✅ Video diunduh ke output: {filename}")
                                break
                    except:
                        pass
                    # Check Downloads folder
                    try:
                        mp4s = glob.glob(os.path.join(downloads_folder, "*.mp4"))
                        new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
                        if new_files:
                            newest = max(new_files, key=os.path.getmtime)
                            if not glob.glob(os.path.join(downloads_folder, "*.crdownload")):
                                shutil.move(newest, save_path)
                                downloaded = True
                                log_fn(f"✅ Video diunduh dari Downloads: {filename}")
                                break
                    except:
                        pass
                if not downloaded:
                    log_fn("⚠️ File tidak muncul setelah 60 detik via button click")

        if downloaded and os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
            sz = os.path.getsize(save_path) / (1024 * 1024)
            log_fn(f"📦 Ukuran video: {sz:.1f} MB")
            return save_path

        log_fn("❌ Gagal mengunduh video")
        return None

    finally:
        try:
            if driver:
                driver.quit()
        except:
            pass
        try:
            chrome_proc.terminate()
        except:
            pass


# ═══════════════════════════════════════════════════════════════
#  MULTI-TAB HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def setup_tab_grok(driver, image_path, prompt_text, log_fn, tab_idx):
    """
    On the CURRENTLY active tab, do:
      1. Upload image with verification (reload tab if failed)
      2. Click Settings → Buat Video
      3. Fill prompt with verification
      4. Click Generate
    Returns True if generate was clicked successfully.
    """
    prefix = f"[Tab {tab_idx+1}]"

    def _count_imgs(drv):
        try:
            return drv.execute_script("""
                let c=0;
                c+=document.querySelectorAll('img[src*="assets.grok.com"]').length;
                c+=document.querySelectorAll('img[src^="blob:"]').length;
                c+=document.querySelectorAll('div.group.relative img').length;
                return c;
            """)
        except: return 0

    def _verify_uploaded(drv, before, timeout=10):
        for _ in range(timeout*2):
            try:
                if _count_imgs(drv) > before: return True
                has = drv.execute_script("""
                    const g=document.querySelector('div.group.relative');
                    if(g){const r=g.getBoundingClientRect();if(r.width>50&&r.height>50)return true;}
                    return false;
                """)
                if has: return True
            except: pass
            time.sleep(0.5)
        return False

    def _upload(drv, abs_img, before):
        # Method A: existing file inputs
        try:
            inputs = drv.find_elements(By.CSS_SELECTOR, "input[type='file']")
            for fi in inputs:
                try:
                    drv.execute_script(
                        "arguments[0].style.cssText='display:block!important;"
                        "visibility:visible!important;opacity:1!important;"
                        "position:absolute;top:0;left:0;width:1px;height:1px;';", fi)
                    fi.send_keys(abs_img)
                    time.sleep(3)
                    if _verify_uploaded(drv, before):
                        return True
                except: pass
        except: pass
        # Method B: inject
        try:
            iid = f"_tbf_{int(time.time())}"
            drv.execute_script(f"""
                let o=document.getElementById('{iid}');if(o)o.remove();
                const i=document.createElement('input');i.type='file';
                i.id='{iid}';i.accept='image/*';
                i.style.cssText='position:absolute;top:0;left:0;z-index:99999;display:block;width:1px;height:1px;';
                document.body.appendChild(i);
            """)
            time.sleep(0.5)
            drv.find_element(By.ID, iid).send_keys(abs_img)
            time.sleep(3)
            if _verify_uploaded(drv, before): return True
        except: pass
        return False

    def _fill_prompt(drv, p_text):
        # Method A
        try:
            ed = drv.execute_script("""
                const e=document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                if(e){e.scrollIntoView({block:'center'});return e;} return null;
            """)
            if ed:
                drv.execute_script("arguments[0].focus();", ed)
                time.sleep(0.3); ed.click(); time.sleep(0.3)
                ed.send_keys(Keys.CONTROL+"a"); time.sleep(0.2); ed.send_keys(Keys.DELETE); time.sleep(0.2)
                drv.execute_script("""
                    const e=arguments[0];
                    e.innerHTML='<p>'+arguments[1]+'</p>';
                    e.dispatchEvent(new Event('input',{bubbles:true}));
                    e.dispatchEvent(new Event('change',{bubbles:true}));
                    e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));
                """, ed, p_text)
                time.sleep(1)
                actual = drv.execute_script(
                    "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent||'';")
                if actual.strip(): return True
        except: pass
        # Method B: pure JS
        try:
            r = drv.execute_script("""
                const e=document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                if(!e)return 'nf';
                e.focus();e.innerHTML='<p>'+arguments[0]+'</p>';
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));
                return 'ok';
            """, p_text)
            time.sleep(1)
            if r == 'ok':
                actual = drv.execute_script(
                    "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent||'';")
                if actual.strip(): return True
        except: pass
        # Method C: typing
        try:
            ed = WebDriverWait(drv, 20).until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'div.tiptap.ProseMirror[contenteditable="true"]')))
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", ed)
            time.sleep(1); ed.click(); time.sleep(0.5)
            ed.send_keys(Keys.CONTROL+"a"); ed.send_keys(Keys.DELETE); time.sleep(0.3)
            for chunk in [p_text[i:i+50] for i in range(0, len(p_text), 50)]:
                ed.send_keys(chunk); time.sleep(0.1)
            time.sleep(1)
            actual = drv.execute_script(
                "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent||'';")
            if actual.strip(): return True
        except: pass
        return False

    # ── Upload image with reload-retry (up to 3 outer attempts) ──
    image_uploaded = True
    if image_path and os.path.exists(image_path):
        abs_image = os.path.abspath(image_path)
        image_uploaded = False
        for outer in range(1, 4):
            if outer > 1:
                log_fn(f"{prefix} 🔄 Reload untuk upload ulang (attempt {outer}/3)...")
                try:
                    driver.get(GROK_URL)
                    time.sleep(5)
                except Exception as e:
                    log_fn(f"{prefix} ⚠️ Reload gagal: {e}")
                    continue
            before = _count_imgs(driver)
            log_fn(f"{prefix} 📷 Upload: {os.path.basename(abs_image)} (attempt {outer})")
            if _upload(driver, abs_image, before):
                image_uploaded = True
                log_fn(f"{prefix} ✅ Upload berhasil!")
                break
            log_fn(f"{prefix} ⚠️ Upload attempt {outer} gagal")
        if not image_uploaded:
            log_fn(f"{prefix} ❌ Upload gambar gagal setelah 3 attempt")

    # ── Settings → Buat Video ──
    settings_opened = False
    for method_label, method_fn in [
        ("Selenium", lambda: (
            ActionChains(driver).move_to_element(
                driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Settings"], button[aria-label="Pengaturan"]')[0]
            ).click().perform()
        )),
        ("JS pointer", lambda: driver.execute_script("""
            for(const btn of document.querySelectorAll('button')){
                const l=btn.getAttribute('aria-label')||'';
                if(l==='Settings'||l==='Pengaturan'){
                    ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev=>
                        btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                    return true;}}
            return false;
        """)),
        ("Enter", lambda: driver.find_elements(By.CSS_SELECTOR,
            'button[aria-label="Settings"], button[aria-label="Pengaturan"]')[0].send_keys(Keys.ENTER)),
    ]:
        if settings_opened: break
        try:
            method_fn()
            time.sleep(1.5)
            if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                settings_opened = True
        except: pass

    if settings_opened:
        try:
            menu_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
            for item in menu_items:
                txt = item.text or ""
                if "Buat Video" in txt or "Make Video" in txt or "Make video" in txt:
                    ActionChains(driver).move_to_element(item).click().perform()
                    break
            time.sleep(1)
        except: pass

    # ── Fill prompt with verification and reload-retry ──
    prompt_filled = False
    for outer in range(1, 4):
        if outer > 1:
            log_fn(f"{prefix} 🔄 Reload untuk isi prompt ulang (attempt {outer}/3)...")
            try:
                driver.get(GROK_URL)
                time.sleep(5)
            except:
                continue
        if _fill_prompt(driver, prompt_text):
            prompt_filled = True
            log_fn(f"{prefix} ✅ Prompt diisi!")
            break
        log_fn(f"{prefix} ⚠️ Prompt attempt {outer} gagal")

    if not prompt_filled:
        log_fn(f"{prefix} ❌ Gagal isi prompt setelah 3 attempt")
        return False

    # ── Click Generate ──
    try:
        gen_btn = None
        for label in ['Buat video', 'Create video', 'Generate', 'Submit']:
            try:
                gen_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, f'button[aria-label="{label}"]')))
                if gen_btn: break
            except: continue
        if not gen_btn:
            try: gen_btn = driver.find_element(By.CSS_SELECTOR, 'button.group[type="button"]')
            except: pass
        if gen_btn:
            gen_btn.click()
        else:
            driver.execute_script("""
                const btn = document.querySelector('button[aria-label="Buat video"]')
                          || document.querySelector('button[aria-label="Create video"]')
                          || document.querySelector('button.group[type="button"]');
                if (btn) btn.click();
            """)
        log_fn(f"{prefix} ✅ Generate diklik!")
        time.sleep(2)
        return True
    except Exception as e:
        log_fn(f"{prefix} ❌ Gagal klik Generate: {e}")
        return False


def check_tab_progress(driver):
    """
    Check progress of video generation on the currently active tab.
    Returns (status, pct_num):
      status = "generating" | "done" | "idle"
      pct_num = integer percentage (0-100)
    """
    pct_num = 0
    is_generating = False

    # Check rate limit FIRST
    try:
        is_rate_limited = driver.execute_script("""
            const allText = document.querySelectorAll('span, div, p');
            for (const el of allText) {
                const t = (el.textContent || '').trim();
                if (t.includes('Rate limit reached') || t.includes('Batas laju tercapai')) return true;
            }
            for (const el of document.querySelectorAll('button, span, div')) {
                const t = (el.textContent || '').trim();
                if (t.includes('Upgrade to SuperGrok') || t.includes('SuperGrok Heavy')) return true;
            }
            return false;
        """)
        if is_rate_limited:
            return "rate_limited", 0
    except:
        pass

    # Read percentage
    try:
        pct_text = driver.execute_script("""
            const spans = document.querySelectorAll('span.tabular-nums');
            for (const s of spans) {
                const t = s.textContent.trim();
                if (t.includes('%')) return t;
            }
            const overlay = document.querySelector('div.flex.justify-center.items-center.gap-2');
            if (overlay) {
                const nums = overlay.querySelectorAll('span');
                for (const n of nums) {
                    if (n.textContent.includes('%')) return n.textContent.trim();
                }
            }
            return '';
        """)
        if pct_text:
            m = re.search(r'(\d+)', pct_text)
            if m:
                pct_num = int(m.group(1))
    except:
        pass

    # Check if generating overlay is shown
    try:
        is_generating = driver.execute_script("""
            const spans = document.querySelectorAll('span');
            for (const s of spans) {
                const t = s.textContent;
                if (t.includes('Menghasilkan') || t.includes('Generating')) return true;
            }
            return false;
        """)
    except:
        pass

    # Check if Download button is visible (= done)
    has_download = False
    try:
        dl_btns = driver.find_elements(By.CSS_SELECTOR,
            'button[aria-label="Download"], button[aria-label="Unduh"]')
        if dl_btns:
            has_download = True
    except:
        pass

    if has_download and not is_generating:
        return "done", 100
    elif is_generating or pct_num > 0:
        return "generating", pct_num
    else:
        return "idle", 0


def download_tab_video(driver, output_dir, log_fn, tab_idx, start_time):
    """
    Download video from the currently active tab.
    Returns path to downloaded video or None.
    """
    import requests as req_lib
    prefix = f"[Tab {tab_idx+1}]"
    filename = f"grok_{int(time.time())}_{tab_idx}.mp4"
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


# ═══════════════════════════════════════════════════════════════
#  GENERATION LOOP (runs in thread)
# ═══════════════════════════════════════════════════════════════
def _generation_loop(uid, chat_id, bot, main_loop, folder_name, count, prompt_name, stop_event):
    import asyncio, os, time, threading
    from telegram.constants import ParseMode
    import gtt_core

    def send(text):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    def send_video_tg(path):
        async def _send():
            try:
                with open(path, 'rb') as vf:
                    await bot.send_video(chat_id, video=vf,
                                         caption=f"?? Video dari folder <b>{escape_html(folder_name)}</b>",
                                         parse_mode=ParseMode.HTML,
                                         supports_streaming=True)
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
            except Exception:
                pass
        asyncio.run_coroutine_threadsafe(_send(), main_loop)

    prompts = load_prompts()
    prompt_text = prompts.get(prompt_name)
    if not prompt_text:
        send(f"? Prompt <code>{escape_html(prompt_name)}</code> tidak ditemukan!")
        active_gen_tasks.pop(uid, None)
        return

    images = list_bahan_images(folder_name)
    if not images:
        send(f"? Folder <code>{escape_html(folder_name)}</code> kosong atau tidak ada!")
        active_gen_tasks.pop(uid, None)
        return

    infinite = (count == 0)
    target = "8" if infinite else str(count)
    merge_dur = bot_settings.get("merge_duration", 20)
    merge_enabled = (merge_dur == 20)
    merge_buffer = []

    merge_mode_str = "?? Mode: <b>Gabung 2 video (20 dtk)</b>" if merge_enabled else "?? Mode: <b>Tanpa gabung (10 dtk)</b>"
    send(
        f"?? <b>Generasi dimulai! (grok_auto.js mode)</b>\n\n"
        f"?? Folder: <code>{escape_html(folder_name)}</code> ({len(images)} gambar)\n"
        f"?? Prompt: <code>{escape_html(prompt_name)}</code>\n"
        f"?? Target: <b>{target}</b> video raw\n"
        f"{merge_mode_str}\n\n"
        f"Gunakan /stop untuk menghentikan."
    )

    generated = 0
    failed = 0
    merged_count = 0

    ud = bot_settings.get("user_data_dir", DEFAULT_USER_DATA)
    pt = bot_settings.get("port", DEFAULT_PORT)

    log_lines = []
    log_lock = threading.Lock()
    log_done = threading.Event()

    def log_fn(msg, tag=None):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        icon = {"success": "?", "error": "?", "warn": "??", "info": "??"}.get(tag, "??")
        with log_lock:
            log_lines.append(f"<code>[{ts}]</code> {icon} {msg}")

    log_msg_future = asyncio.run_coroutine_threadsafe(
        bot.send_message(chat_id,
                         f"?? <b>Live Log</b>\n\n<i>Memulai Chrome...</i>",
                         parse_mode=ParseMode.HTML), main_loop)
    try:
        log_msg = log_msg_future.result(timeout=10)
        log_msg_id = log_msg.message_id
    except:
        log_msg_id = None

    async def _live_log_updater():
        last_text = ""
        while not log_done.is_set():
            with log_lock:
                body = "\n".join(log_lines[-20:]) if log_lines else "<i>Menunggu...</i>"
            text = f"?? <b>Live Log</b>\n? {generated}/{target} | ? {failed}\n\n{body}"
            if text != last_text and log_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=log_msg_id,
                        text=text[:4096], parse_mode=ParseMode.HTML)
                    last_text = text
                except: pass
            await asyncio.sleep(2)
        with log_lock:
            body = "\n".join(log_lines[-25:]) if log_lines else ""
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=log_msg_id,
                text=f"?? <b>Senyap Log Selesai</b>\n? {generated}/{target} | ? {failed}\n\n{body}"[:4096],
                parse_mode=ParseMode.HTML)
        except: pass

    log_task = asyncio.run_coroutine_threadsafe(_live_log_updater(), main_loop)

    chrome_proc, driver = gtt_core._start_chrome_session(ud, pt, log_fn, "Imagine", raw_dir=OUTPUT_DIR)
    
    if not driver:
        log_done.set()
        send("? Gagal connect Chrome!")
        active_gen_tasks.pop(uid, None)
        return

    try:
        while not stop_event.is_set():
            if not infinite and generated >= count:
                break
            
            remaining = 10 if infinite else min(10, count - generated)
            if remaining <= 0: break
            
            batch_size = remaining
            log_fn(f"--- Batch: {batch_size} tab (sisa {remaining if not infinite else '8'}) ---")
            
            new_raw = gtt_core._run_mini_batch(driver, batch_size, folder_name, prompt_text, log_fn, stop_event, "Imagine", raw_dir=OUTPUT_DIR)
            
            # Check rate limit sentinel
            if new_raw == '__RATE_LIMITED__':
                log_fn("🚫 RATE LIMIT REACHED! Grok meminta upgrade ke SuperGrok.", "error")
                send(
                    "🚫 <b>RATE LIMIT REACHED!</b>\n\n"
                    "Grok sudah mencapai batas generate.\n"
                    "Pesan dari Grok: <i>Rate limit reached — Upgrade to SuperGrok Heavy</i>\n\n"
                    "Generate <b>dihentikan otomatis</b>."
                )
                stop_event.set()
                break

            if not new_raw:
                failed += batch_size
                time.sleep(5)
                continue
            
            for video_path in new_raw:
                generated += 1
                sz = os.path.getsize(video_path) / (1024*1024)
                log_fn(f"?? {sz:.1f} MB ({generated}/{target})")

                if merge_enabled:
                    merge_buffer.append(video_path)
                    if len(merge_buffer) >= 2:
                        vid_a = merge_buffer.pop(0)
                        vid_b = merge_buffer.pop(0)
                        merged_path = gtt_core.merge_video_pair(vid_a, vid_b, MERGED_DIR, log_fn)
                        if merged_path:
                            merged_count += 1
                            send_video_tg(merged_path)
                            for _vp in (vid_a, vid_b):
                                try:
                                    if os.path.exists(_vp): os.remove(_vp)
                                except: pass
                            log_fn(f"?? Merged #{merged_count} dikirim", "success")
                        else:
                            log_fn("?? Merge gagal, kirim video terpisah", "warn")
                            send_video_tg(vid_a)
                            send_video_tg(vid_b)
                else:
                    send_video_tg(video_path)
    finally:
        log_done.set()
        time.sleep(2)
        gtt_core._stop_chrome_session(chrome_proc, driver, log_fn, "Imagine")

    if merge_enabled and merge_buffer:
        send(f"?? Sisa {len(merge_buffer)} video di buffer, dikirim tanpa merge")
        for vp in merge_buffer:
            if os.path.exists(vp):
                send_video_tg(vp)
        merge_buffer.clear()

    merge_info = f"\n?? Merged: <b>{merged_count}</b> video" if merge_enabled else ""
    send(
        f"?? <b>Generasi selesai!</b>\n\n"
        f"? Berhasil: <b>{generated}</b>\n"
        f"? Gagal: <b>{failed}</b>{merge_info}\n"
        f"?? Folder: <code>{escape_html(folder_name)}</code>"
    )
    active_gen_tasks.pop(uid, None)



# ---------------------------------------------------------------
#  TELEGRAM HANDLERS
# ---------------------------------------------------------------
def main_menu_kb(uid=None):
    is_running = bool(uid and active_gen_tasks.get(uid))
    rows = [
        [InlineKeyboardButton("📁 Kelola Bahan", callback_data="bahan_menu"),
         InlineKeyboardButton("📝 Kelola Prompt", callback_data="prompt_menu")],
    ]
    if is_running:
        rows.append([InlineKeyboardButton("⏹ Stop Generate", callback_data="stop_gen")])
    rows.append([InlineKeyboardButton("↻ Refresh", callback_data="refresh")])
    return InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    folders = list_bahan_folders()
    prompts = load_prompts()
    is_running = bool(active_gen_tasks.get(uid))

    status = "🟢 <b>Sedang generate</b>" if is_running else "⚫ <b>Idle</b>"

    cfg = bot_settings
    merge_dur = cfg.get("merge_duration", 20)
    merge_label = f"🎬 20 dtk (gabung 2 video)" if merge_dur == 20 else "🎬 10 dtk (tanpa gabung)"
    text = (
        "🎬 <b>Grok Imagine Video Generator</b>\n\n"
        f"{status}\n\n"
        f"📁 Folder bahan: <b>{len(folders)}</b> ({', '.join(folders) if folders else 'kosong'})\n"
        f"📝 Prompt tersimpan: <b>{len(prompts)}</b>\n"
        f"🔌 Port: <code>{cfg.get('port', DEFAULT_PORT)}</code>\n"
        f"📂 User Data: <code>{cfg.get('user_data_dir', DEFAULT_USER_DATA)}</code>\n"
        f"📂 Output: <code>{OUTPUT_DIR}</code>\n"
        f"📂 Merged: <code>{MERGED_DIR}</code>\n"
        f"{merge_label}\n\n"
        "<b>Command:</b>\n"
        "<code>/generate [folder] [jumlah] [prompt]</code>\n"
        "<code>/stop</code> — hentikan generasi\n"
        "<code>/set port 9245</code> — ubah port Chrome\n"
        "<code>/set userdata 1</code> — ubah user data dir\n"
        "<code>/set merge 10|20</code> — durasi output video\n\n"
        "Gunakan tombol di bawah untuk kelola bahan & prompt."
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb(uid), parse_mode=ParseMode.HTML)


async def cmd_generate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    if active_gen_tasks.get(uid):
        await update.message.reply_text("⚠️ Proses generate sedang berjalan! Gunakan /stop dulu.")
        return

    args = update.message.text.strip().split()
    # /generate [folder] [count] [prompt_name]
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
    count = 0  # default infinite
    prompt_name = None

    if len(args) >= 3:
        try:
            count = int(args[2])
        except ValueError:
            # args[2] might be the prompt name if no count given
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

    # Validate
    if folder_name not in list_bahan_folders():
        await update.message.reply_text(
            f"❌ Folder <code>{escape_html(folder_name)}</code> tidak ditemukan!\n\n"
            f"Folder tersedia: {', '.join(f'<code>{f}</code>' for f in list_bahan_folders())}",
            parse_mode=ParseMode.HTML)
        return

    prompts = load_prompts()
    if prompt_name not in prompts:
        await update.message.reply_text(
            f"❌ Prompt <code>{escape_html(prompt_name)}</code> tidak ditemukan!\n\n"
            f"Prompt tersedia: {', '.join(f'<code>{p}</code>' for p in prompts.keys())}",
            parse_mode=ParseMode.HTML)
        return

    # Validate even count when merge is enabled
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

    target_str = str(count) if count > 0 else "∞ (infinite)"
    await update.message.reply_text(
        f"🚀 <b>Generate dimulai!</b>\n\n"
        f"📁 Folder: <code>{escape_html(folder_name)}</code>\n"
        f"🎯 Target: <b>{target_str}</b>\n"
        f"📝 Prompt: <code>{escape_html(prompt_name)}</code>\n\n"
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
    text = (
        "📖 <b>Grok Imagine Bot — Panduan</b>\n\n"
        "<b>Perintah:</b>\n"
        "/start — Menu utama\n"
        "/generate [folder] [jumlah] [prompt] — Mulai generate video\n"
        "/stop — Hentikan generasi\n"
        "/set port [port] — Ubah port Chrome\n"
        "/set userdata [nomor] — Ubah user data dir\n"
        "/set merge 10|20 — Durasi output (10=tanpa gabung, 20=gabung 2)\n"
        "/help — Panduan ini\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>Folder Bahan</b>: Kelola subfolder gambar di\n"
        f"<code>{BAHAN_DIR}</code>\n\n"
        "📝 <b>Prompt</b>: Kelola database prompt yang digunakan\n"
        "untuk sebagai teks input di Grok Imagine.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎬 <b>Contoh:</b>\n"
        "<code>/generate hijab 5 promptKeren</code>\n"
        "→ Generate 5 video dari folder hijab\n\n"
        "<code>/generate hijab promptKeren</code>\n"
        "→ Generate infinite video sampai /stop"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return
    args = update.message.text.strip().split(None, 2)
    if len(args) < 3:
        cfg = bot_settings
        merge_dur = cfg.get("merge_duration", 20)
        merge_label = "🎬 20 dtk (gabung 2 video)" if merge_dur == 20 else "🎬 10 dtk (tanpa gabung)"
        await update.message.reply_text(
            "⚙️ <b>Settings</b>\n\n"
            f"🔌 Port: <code>{cfg.get('port', DEFAULT_PORT)}</code>\n"
            f"📂 User Data: <code>{cfg.get('user_data_dir', DEFAULT_USER_DATA)}</code>\n"
            f"{merge_label}\n\n"
            "<b>Format:</b>\n"
            "<code>/set port 9245</code>\n"
            "<code>/set userdata 1</code>\n"
            "<code>/set merge 20</code> — gabung 2 video (default)\n"
            "<code>/set merge 10</code> — tanpa gabung",
            parse_mode=ParseMode.HTML)
        return

    sub = args[1].lower()
    val = args[2].strip()
    cfg = bot_settings

    if sub == "port":
        cfg["port"] = val
        save_bot_settings(cfg)
        await update.message.reply_text(
            f"✅ Port diubah: <code>{val}</code>", parse_mode=ParseMode.HTML)
    elif sub == "userdata":
        cfg["user_data_dir"] = os.path.join(APP_DIR, "user_data", val)
        save_bot_settings(cfg)
        await update.message.reply_text(
            f"✅ User Data: <code>user_data/{val}</code>", parse_mode=ParseMode.HTML)
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
        await update.message.reply_text("❌ Sub-command tidak dikenal. Gunakan: port, userdata, merge")


# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not is_allowed(uid):
        return
    data = q.data

    # ── Refresh ──
    if data == "refresh":
        folders = list_bahan_folders()
        prompts = load_prompts()
        is_running = bool(active_gen_tasks.get(uid))
        status = "🟢 <b>Sedang generate</b>" if is_running else "⚫ <b>Idle</b>"
        text = (
            "🎬 <b>Grok Imagine Video Generator</b>\n\n"
            f"{status}\n\n"
            f"📁 Folder bahan: <b>{len(folders)}</b>\n"
            f"📝 Prompt tersimpan: <b>{len(prompts)}</b>"
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

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Tambah Gambar", callback_data=f"bahan_add_image_{folder_name}")],
            [InlineKeyboardButton("🗑 Hapus Gambar", callback_data=f"bahan_del_image_{folder_name}")] if imgs else [],
            [InlineKeyboardButton("🗑 Hapus Folder", callback_data=f"bahan_del_{folder_name}")],
            [InlineKeyboardButton("📁 Kembali", callback_data="bahan_menu")],
        ])
        # Filter out empty rows
        kb = InlineKeyboardMarkup([row for row in kb.inline_keyboard if row])
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if data.startswith("bahan_del_"):
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
#  TEXT MESSAGE HANDLER (for conversations)
# ═══════════════════════════════════════════════════════════════
async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    waiting = ctx.user_data.get("waiting_for")
    if not waiting:
        return  # Not waiting for anything

    text = update.message.text.strip()

    if text.startswith("/"):
        ctx.user_data.pop("waiting_for", None)
        ctx.user_data.pop("new_prompt_name", None)
        return  # Let command handlers process it

    # ── Create folder ──
    if waiting == "folder_name":
        ctx.user_data.pop("waiting_for", None)
        # Sanitize folder name
        safe_name = re.sub(r'[^\w\-]', '_', text)
        folder_path = os.path.join(BAHAN_DIR, safe_name)
        os.makedirs(folder_path, exist_ok=True)
        await update.message.reply_text(
            f"✅ Folder <b>{escape_html(safe_name)}</b> dibuat!\n\n"
            f"📂 Path: <code>{escape_html(folder_path)}</code>\n\n"
            "Sekarang tambahkan gambar ke folder tersebut secara manual,\n"
            "atau kirim foto ke bot ini (coming soon).",
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


# ═══════════════════════════════════════════════════════════════
#  PHOTO HANDLER (for adding images to folders)
# ═══════════════════════════════════════════════════════════════
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    waiting = ctx.user_data.get("waiting_for")
    if waiting != "bahan_photo":
        return  # Not waiting for a photo

    folder_name = ctx.user_data.get("target_folder")
    if not folder_name:
        ctx.user_data.pop("waiting_for", None)
        await update.message.reply_text("⚠️ Folder target tidak ditemukan. Coba lagi dari menu.")
        return

    folder_path = os.path.join(BAHAN_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    try:
        # Handle photo (compressed) or document (original quality)
        if update.message.photo:
            # Get highest resolution photo
            photo = update.message.photo[-1]
            file = await photo.get_file()
            ext = "jpg"
        elif update.message.document:
            doc = update.message.document
            mime = doc.mime_type or ""
            if not mime.startswith("image/"):
                await update.message.reply_text("⚠️ File bukan gambar. Kirim foto/gambar saja.")
                return
            file = await doc.get_file()
            orig_name = doc.file_name or "image"
            ext = orig_name.rsplit(".", 1)[-1] if "." in orig_name else "jpg"
        else:
            return

        # Generate unique filename
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
        BotCommand("generate", "🎬 Generate video"),
        BotCommand("stop",     "⏹ Stop generasi"),
        BotCommand("set",      "⚙️ Ubah settings"),
        BotCommand("help",     "📖 Panduan"),
        BotCommand("cancel",   "❌ Batalkan input"),
    ])

def main():
    os.makedirs(BAHAN_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("stop",     cmd_stop))
    app.add_handler(CommandHandler("set",      cmd_set))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("cancel",   cancel_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    # Text handler for conversations (folder name, prompt name/text)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    print("🎬 Grok Imagine Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
