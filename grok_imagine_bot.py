
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
PROMPTS_FILE   = os.path.join(APP_DIR, "grok_prompts.json")
SETTINGS_FILE  = os.path.join(APP_DIR, "grok_imagine_settings.json")

GROK_URL       = "https://grok.com/imagine"
DEFAULT_USER_DATA = os.path.join(APP_DIR, "user_data", "1")
DEFAULT_PORT   = "9245"

# ═══════════════════════════════════════════════════════════════
#  BOT SETTINGS PERSISTENCE
# ═══════════════════════════════════════════════════════════════
def load_bot_settings() -> dict:
    defaults = {"user_data_dir": DEFAULT_USER_DATA, "port": DEFAULT_PORT}
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
    1. Click Attach button → Animate Image → select file
    2. Type prompt text
    3. Click generate button
    4. Track progress percentage
    5. Download the result video
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

        wait = WebDriverWait(driver, 20)
        time.sleep(3)

        # ── Step 1: Upload image for Animate Image ──
        if image_path and os.path.exists(image_path):
            log_fn(f"📷 Mengunggah gambar: {os.path.basename(image_path)}")
            image_uploaded = False
            abs_image = os.path.abspath(image_path)

            # --- Attempt B: Directly find any file input on page ---
            if not image_uploaded:
                try:
                    log_fn("🔄 Fallback: cari hidden file input langsung...")
                    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                    if file_inputs:
                        fi = file_inputs[-1]
                        driver.execute_script(
                            "arguments[0].style.display='block';"
                            "arguments[0].style.visibility='visible';"
                            "arguments[0].style.opacity='1';"
                            "arguments[0].style.height='1px';"
                            "arguments[0].style.width='1px';"
                            "arguments[0].style.position='absolute';", fi)
                        fi.send_keys(abs_image)
                        image_uploaded = True
                        log_fn("✅ Gambar dipilih via hidden file input!")
                        time.sleep(3)
                except Exception as e:
                    log_fn(f"⚠️ Hidden file input gagal: {e}")

            # --- Attempt C: Inject file input via JS ---
            if not image_uploaded:
                try:
                    log_fn("🔄 Fallback: inject file input via JS...")
                    driver.execute_script("""
                        const input = document.createElement('input');
                        input.type = 'file';
                        input.id = 'grok_bot_file_input';
                        input.accept = 'image/*';
                        input.style.cssText = 'position:absolute;top:0;left:0;z-index:99999;display:block;width:1px;height:1px;';
                        document.body.appendChild(input);
                    """)
                    time.sleep(0.5)
                    injected_input = driver.find_element(By.ID, "grok_bot_file_input")
                    injected_input.send_keys(abs_image)
                    log_fn("✅ Gambar dipilih via injected input!")
                    image_uploaded = True
                    time.sleep(3)
                except Exception as e:
                    log_fn(f"⚠️ Inject file input gagal: {e}")

            if not image_uploaded:
                log_fn("❌ Semua metode upload gambar gagal!")
        else:
            log_fn("⚠️ Tidak ada gambar, generate tanpa gambar")

        if stop_event.is_set():
            return None

        # ── Step 3: Click Settings/Pengaturan → Buat Video ──
        log_fn("⚙️ Klik tombol Settings...")
        settings_opened = False

        # Method A: Selenium native click (triggers React events properly)
        try:
            settings_btns = driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Settings"], button[aria-label="Pengaturan"]')
            if settings_btns:
                ActionChains(driver).move_to_element(settings_btns[0]).click().perform()
                time.sleep(1.5)
                # Verify dropdown opened
                menu_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
                if menu_items:
                    settings_opened = True
                    log_fn("✅ Settings dropdown terbuka (Selenium click)")
        except Exception as e:
            log_fn(f"⚠️ Selenium click gagal: {e}")

        # Method B: JS dispatch full pointer events (for Radix UI)
        if not settings_opened:
            try:
                log_fn("🔄 Mencoba klik Settings via pointer events...")
                driver.execute_script("""
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        const label = btn.getAttribute('aria-label') || '';
                        if (label === 'Settings' || label === 'Pengaturan') {
                            btn.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, cancelable: true}));
                            btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
                            btn.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, cancelable: true}));
                            btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true}));
                            btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                            return true;
                        }
                    }
                    return false;
                """)
                time.sleep(1.5)
                menu_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
                if menu_items:
                    settings_opened = True
                    log_fn("✅ Settings dropdown terbuka (pointer events)")
            except Exception as e:
                log_fn(f"⚠️ Pointer events gagal: {e}")

        # Method C: Focus + Enter key
        if not settings_opened:
            try:
                log_fn("🔄 Mencoba klik Settings via focus+enter...")
                settings_btns = driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Settings"], button[aria-label="Pengaturan"]')
                if settings_btns:
                    settings_btns[0].send_keys(Keys.ENTER)
                    time.sleep(1.5)
                    menu_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
                    if menu_items:
                        settings_opened = True
                        log_fn("✅ Settings dropdown terbuka (Enter key)")
            except Exception as e:
                log_fn(f"⚠️ Enter key gagal: {e}")

        # Now select "Buat Video" / "Make Video"
        if settings_opened:
            log_fn("🎬 Memilih 'Buat Video'...")
            try:
                # Method 1: Selenium click on menu item
                menu_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
                clicked = False
                for item in menu_items:
                    txt = item.text or ""
                    if "Buat Video" in txt or "Make Video" in txt or "Make video" in txt:
                        ActionChains(driver).move_to_element(item).click().perform()
                        clicked = True
                        break

                if not clicked:
                    # Method 2: JS click on menu item
                    driver.execute_script("""
                        const items = document.querySelectorAll('div[role="menuitem"]');
                        for (const item of items) {
                            const txt = item.textContent || '';
                            if (txt.includes('Buat Video') || txt.includes('Make Video') || txt.includes('Make video')) {
                                item.click(); return true;
                            }
                        }
                        const spans = document.querySelectorAll('span.font-semibold');
                        for (const span of spans) {
                            const t = span.textContent.trim();
                            if (t === 'Buat Video' || t === 'Make Video') {
                                span.closest('div[role="menuitem"]')?.click() || span.parentElement.click();
                                return true;
                            }
                        }
                        return false;
                    """)

                time.sleep(1)
                log_fn("✅ Mode 'Buat Video' dipilih!")
            except Exception as e:
                log_fn(f"⚠️ Gagal pilih Buat Video: {e}")
        else:
            log_fn("⚠️ Settings dropdown tidak terbuka, lanjut tanpa pilih mode")

        if stop_event.is_set():
            return None

         # ── Step 2: Type the prompt ──
        log_fn("📝 Mengisi prompt...")
        try:
            # Find the ProseMirror contenteditable div
            editor = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'div.tiptap.ProseMirror[contenteditable="true"]')))
            editor.click()
            time.sleep(0.5)

            # Clear existing content and type new prompt
            editor.send_keys(Keys.CONTROL + "a")
            time.sleep(0.2)
            editor.send_keys(Keys.DELETE)
            time.sleep(0.2)

            # Use JavaScript to set the content for reliability
            driver.execute_script("""
                const editor = document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                if (editor) {
                    editor.innerHTML = '<p>' + arguments[0] + '</p>';
                    editor.dispatchEvent(new Event('input', {bubbles: true}));
                }
            """, prompt_text)
            time.sleep(1)
            log_fn(f"✅ Prompt diisi: {prompt_text[:60]}...")
        except Exception as e:
            log_fn(f"❌ Gagal isi prompt: {e}")
            return None

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

        # Click the Download button
        dl_clicked = False

        # Method A: Selenium click
        try:
            dl_btns = driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Download"], button[aria-label="Unduh"]')
            if dl_btns:
                ActionChains(driver).move_to_element(dl_btns[0]).click().perform()
                dl_clicked = True
                log_fn("✅ Tombol Download diklik (Selenium)")
        except Exception as e:
            log_fn(f"⚠️ Selenium click Download gagal: {e}")

        # Method B: JS pointer events
        if not dl_clicked:
            try:
                dl_clicked = driver.execute_script("""
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        const label = btn.getAttribute('aria-label') || '';
                        if (label === 'Download' || label === 'Unduh') {
                            btn.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true}));
                            btn.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                            btn.dispatchEvent(new PointerEvent('pointerup', {bubbles:true}));
                            btn.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                            btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                            return true;
                        }
                    }
                    return false;
                """)
                if dl_clicked:
                    log_fn("✅ Tombol Download diklik (pointer events)")
            except Exception as e:
                log_fn(f"⚠️ JS click Download gagal: {e}")

        # Method C: Enter key
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

        if not dl_clicked:
            log_fn("❌ Tidak bisa klik tombol Download")

        # Wait for file to appear in output_dir or Downloads folder
        if dl_clicked:
            log_fn("⏳ Menunggu file terdownload (max 30 detik)...")
            downloads_folder = os.path.expanduser("~/Downloads")
            for wait_sec in range(30):
                time.sleep(1)

                # Check output_dir for new mp4
                try:
                    mp4s = glob.glob(os.path.join(output_dir, "*.mp4"))
                    new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
                    if new_files:
                        newest = max(new_files, key=os.path.getmtime)
                        crdowns = glob.glob(os.path.join(output_dir, "*.crdownload"))
                        if not crdowns:
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
                        crdowns = glob.glob(os.path.join(downloads_folder, "*.crdownload"))
                        if not crdowns:
                            shutil.move(newest, save_path)
                            downloaded = True
                            log_fn(f"✅ Video diunduh dari Downloads: {filename}")
                            break
                except:
                    pass

            if not downloaded:
                log_fn("⚠️ File tidak muncul setelah 30 detik")

        if downloaded and os.path.exists(save_path):
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
      1. Upload image (Attach → Animate Image OR fallback file input)
      2. Click Settings → Buat Video
      3. Fill prompt
      4. Click Generate
    Returns True if generate was clicked successfully.
    """
    wait = WebDriverWait(driver, 20)
    prefix = f"[Tab {tab_idx+1}]"

    # ── Upload image ──
    if image_path and os.path.exists(image_path):
        log_fn(f"{prefix} 📷 Upload: {os.path.basename(image_path)}")
        abs_image = os.path.abspath(image_path)
        image_uploaded = False

        # Attempt B: Direct hidden file input
        if not image_uploaded:
            try:
                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if file_inputs:
                    fi = file_inputs[-1]
                    driver.execute_script(
                        "arguments[0].style.display='block';"
                        "arguments[0].style.visibility='visible';"
                        "arguments[0].style.opacity='1';"
                        "arguments[0].style.height='1px';"
                        "arguments[0].style.width='1px';"
                        "arguments[0].style.position='absolute';", fi)
                    fi.send_keys(abs_image)
                    image_uploaded = True
                    time.sleep(2)
            except:
                pass

        # Attempt C: Inject file input
        if not image_uploaded:
            try:
                driver.execute_script("""
                    const input = document.createElement('input');
                    input.type = 'file'; input.id = 'grok_bot_file_input';
                    input.accept = 'image/*';
                    input.style.cssText = 'position:absolute;top:0;left:0;z-index:99999;display:block;width:1px;height:1px;';
                    document.body.appendChild(input);
                """)
                time.sleep(0.5)
                injected = driver.find_element(By.ID, "grok_bot_file_input")
                injected.send_keys(abs_image)
                image_uploaded = True
                time.sleep(2)
            except:
                pass

        if not image_uploaded:
            log_fn(f"{prefix} ⚠️ Upload gambar gagal")

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
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                const label = btn.getAttribute('aria-label') || '';
                if (label === 'Settings' || label === 'Pengaturan') {
                    btn.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true}));
                    btn.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                    btn.dispatchEvent(new PointerEvent('pointerup', {bubbles:true}));
                    btn.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                    btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                    return true;
                }
            }
            return false;
        """)),
        ("Enter key", lambda: driver.find_elements(By.CSS_SELECTOR,
            'button[aria-label="Settings"], button[aria-label="Pengaturan"]')[0].send_keys(Keys.ENTER)),
    ]:
        if settings_opened:
            break
        try:
            method_fn()
            time.sleep(1.5)
            if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                settings_opened = True
        except:
            pass

    if settings_opened:
        try:
            menu_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
            for item in menu_items:
                txt = item.text or ""
                if "Buat Video" in txt or "Make Video" in txt or "Make video" in txt:
                    ActionChains(driver).move_to_element(item).click().perform()
                    break
            time.sleep(1)
        except:
            pass

    # ── Fill prompt ──
    try:
        editor = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, 'div.tiptap.ProseMirror[contenteditable="true"]')))
        editor.click()
        time.sleep(0.3)
        editor.send_keys(Keys.CONTROL + "a")
        time.sleep(0.2)
        editor.send_keys(Keys.DELETE)
        time.sleep(0.2)
        driver.execute_script("""
            const editor = document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
            if (editor) {
                editor.innerHTML = '<p>' + arguments[0] + '</p>';
                editor.dispatchEvent(new Event('input', {bubbles: true}));
            }
        """, prompt_text)
        time.sleep(0.5)
    except Exception as e:
        log_fn(f"{prefix} ❌ Gagal isi prompt: {e}")
        return False

    # ── Click Generate ──
    try:
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
            try:
                gen_btn = driver.find_element(By.CSS_SELECTOR, 'button.group[type="button"]')
            except:
                pass
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
    Click the Download button on the currently active tab and wait for file.
    Returns path to downloaded video or None.
    """
    prefix = f"[Tab {tab_idx+1}]"
    filename = f"grok_{int(time.time())}_{tab_idx}.mp4"
    save_path = os.path.join(output_dir, filename)
    dl_clicked = False

    # Method A: Selenium click
    try:
        dl_btns = driver.find_elements(By.CSS_SELECTOR,
            'button[aria-label="Download"], button[aria-label="Unduh"]')
        if dl_btns:
            ActionChains(driver).move_to_element(dl_btns[0]).click().perform()
            dl_clicked = True
    except:
        pass

    # Method B: JS pointer events
    if not dl_clicked:
        try:
            dl_clicked = driver.execute_script("""
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    const label = btn.getAttribute('aria-label') || '';
                    if (label === 'Download' || label === 'Unduh') {
                        btn.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true}));
                        btn.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                        btn.dispatchEvent(new PointerEvent('pointerup', {bubbles:true}));
                        btn.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                        btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                        return true;
                    }
                }
                return false;
            """)
        except:
            pass

    # Method C: Enter key
    if not dl_clicked:
        try:
            dl_btns = driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Download"], button[aria-label="Unduh"]')
            if dl_btns:
                dl_btns[0].send_keys(Keys.ENTER)
                dl_clicked = True
        except:
            pass

    if not dl_clicked:
        log_fn(f"{prefix} ❌ Tidak bisa klik tombol Download")
        return None

    log_fn(f"{prefix} ⏳ Menunggu file terdownload...")
    downloads_folder = os.path.expanduser("~/Downloads")
    for _ in range(30):
        time.sleep(1)
        # Check output_dir
        try:
            mp4s = glob.glob(os.path.join(output_dir, "*.mp4"))
            new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
            if new_files:
                newest = max(new_files, key=os.path.getmtime)
                crdowns = glob.glob(os.path.join(output_dir, "*.crdownload"))
                if not crdowns:
                    if newest != save_path:
                        shutil.move(newest, save_path)
                    log_fn(f"{prefix} ✅ Video diunduh: {filename}")
                    return save_path
        except:
            pass
        # Check Downloads folder
        try:
            mp4s = glob.glob(os.path.join(downloads_folder, "*.mp4"))
            new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
            if new_files:
                newest = max(new_files, key=os.path.getmtime)
                crdowns = glob.glob(os.path.join(downloads_folder, "*.crdownload"))
                if not crdowns:
                    shutil.move(newest, save_path)
                    log_fn(f"{prefix} ✅ Video diunduh: {filename}")
                    return save_path
        except:
            pass

    log_fn(f"{prefix} ❌ Timeout download 30 detik")
    return None


# ═══════════════════════════════════════════════════════════════
#  GENERATION LOOP (runs in thread)
# ═══════════════════════════════════════════════════════════════
def _generation_loop(uid, chat_id, bot, main_loop, folder_name, count, prompt_name, stop_event):
    """
    Loop that generates `count` videos (or infinite if count=0).
    If count >= 10: uses MULTI-TAB mode (up to 10 tabs simultaneously).
    Otherwise: single-tab sequential mode.
    """
    def send(text):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    def send_video_tg(path):
        async def _send():
            try:
                with open(path, 'rb') as vf:
                    await bot.send_video(chat_id, video=vf,
                                         caption=f"🎬 Video dari folder <b>{escape_html(folder_name)}</b>",
                                         parse_mode=ParseMode.HTML,
                                         supports_streaming=True)
            except Exception as e:
                pass
        asyncio.run_coroutine_threadsafe(_send(), main_loop)

    # Load prompt
    prompts = load_prompts()
    prompt_text = prompts.get(prompt_name)
    if not prompt_text:
        send(f"❌ Prompt <code>{escape_html(prompt_name)}</code> tidak ditemukan!")
        active_gen_tasks.pop(uid, None)
        return

    # Check bahan folder
    images = list_bahan_images(folder_name)
    if not images:
        send(f"❌ Folder <code>{escape_html(folder_name)}</code> kosong atau tidak ada!")
        active_gen_tasks.pop(uid, None)
        return

    infinite = (count == 0)
    target = "∞" if infinite else str(count)
    use_multi = (not infinite and count >= 10)
    mode_label = "Multi-Tab" if use_multi else "Single-Tab"

    send(
        f"🚀 <b>Generasi dimulai! ({mode_label})</b>\n\n"
        f"📁 Folder: <code>{escape_html(folder_name)}</code> ({len(images)} gambar)\n"
        f"📝 Prompt: <code>{escape_html(prompt_name)}</code>\n"
        f"🎯 Target: <b>{target}</b> video\n\n"
        f"Gunakan /stop untuk menghentikan."
    )

    generated = 0
    failed = 0

    # ═════════════════════════════════════════════════
    #  MULTI-TAB MODE (count >= 10)
    # ═════════════════════════════════════════════════
    if use_multi:
        ud = bot_settings.get("user_data_dir", DEFAULT_USER_DATA)
        pt = bot_settings.get("port", DEFAULT_PORT)

        log_lines = []
        log_lock = threading.Lock()
        log_done = threading.Event()

        def log_fn(msg, tag=None):
            ts = datetime.now().strftime("%H:%M:%S")
            icon = {"success": "✅", "error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(tag, "▪️")
            with log_lock:
                log_lines.append(f"<code>[{ts}]</code> {icon} {msg}")

        # Send live log message
        log_msg_future = asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id,
                f"🎬 <b>Multi-Tab Live Log</b>\n\n<i>Memulai...</i>",
                parse_mode=ParseMode.HTML), main_loop)
        try:
            log_msg = log_msg_future.result(timeout=10)
            log_msg_id = log_msg.message_id
        except:
            log_msg_id = None

        # Live log updater
        async def _live_log_updater():
            last_text = ""
            while not log_done.is_set():
                with log_lock:
                    body = "\n".join(log_lines[-20:]) if log_lines else "<i>Menunggu...</i>"
                text = f"🎬 <b>Multi-Tab Live Log</b>\n✅ {generated}/{target} | ❌ {failed}\n\n{body}"
                if text != last_text and log_msg_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id, message_id=log_msg_id,
                            text=text[:4096], parse_mode=ParseMode.HTML)
                        last_text = text
                    except:
                        pass
                await asyncio.sleep(2)
            # Final update
            with log_lock:
                body = "\n".join(log_lines[-25:]) if log_lines else ""
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=log_msg_id,
                    text=f"🎬 <b>Multi-Tab Log Selesai</b>\n✅ {generated}/{target} | ❌ {failed}\n\n{body}"[:4096],
                    parse_mode=ParseMode.HTML)
            except:
                pass

        log_task = asyncio.run_coroutine_threadsafe(_live_log_updater(), main_loop)

        driver = None
        chrome_proc = None
        try:
            # Open Chrome once
            log_fn("🌐 Membuka Chrome...")
            chrome_proc = open_chrome_grok(ud, pt)
            driver = connect_selenium_grok(pt)
            driver.execute_cdp_cmd("Page.setDownloadBehavior",
                                   {"behavior": "allow", "downloadPath": OUTPUT_DIR})
            os.makedirs(OUTPUT_DIR, exist_ok=True)

            remaining = count - generated

            while remaining > 0 and not stop_event.is_set():
                batch_size = min(remaining, 10)
                log_fn(f"═══ Batch baru: {batch_size} tab (sisa {remaining}) ═══")

                # ── Phase 1: Setup each tab & click Generate ──
                tab_handles = []
                tab_status = {}   # idx -> "generating" | "done" | "failed"
                tab_progress = {} # idx -> pct
                tab_start_time = time.time()

                for i in range(batch_size):
                    if stop_event.is_set():
                        break

                    image_path = get_random_bahan_image(folder_name)
                    if not image_path:
                        log_fn("❌ Tidak ada gambar lagi!")
                        break

                    # Open new tab (or use first tab for i=0)
                    if i == 0:
                        # Use current tab
                        driver.get(GROK_URL)
                        time.sleep(3)
                    else:
                        driver.switch_to.new_window('tab')
                        driver.get(GROK_URL)
                        time.sleep(3)

                    handle = driver.current_window_handle
                    tab_handles.append(handle)

                    log_fn(f"[Tab {i+1}] 🌐 Halaman dimuat")

                    ok = setup_tab_grok(driver, image_path, prompt_text, log_fn, i)
                    if ok:
                        tab_status[i] = "generating"
                        tab_progress[i] = 0
                    else:
                        tab_status[i] = "failed"
                        tab_progress[i] = 0
                        failed += 1

                    # Small delay before next tab
                    time.sleep(1)

                if stop_event.is_set():
                    break

                # ── Phase 2: Round-Robin monitoring ──
                log_fn("═══ Monitoring Progress (Round-Robin) ═══")
                timeout_start = time.time()
                MAX_TIMEOUT = 600  # 10 minutes per batch

                while not stop_event.is_set():
                    # Check if all tabs are done/failed
                    active_tabs = [i for i, s in tab_status.items()
                                   if s == "generating"]
                    if not active_tabs:
                        log_fn("✅ Semua tab selesai!")
                        break

                    if time.time() - timeout_start > MAX_TIMEOUT:
                        log_fn("⏰ Timeout 10 menit, menyelesaikan batch...")
                        for i in active_tabs:
                            tab_status[i] = "failed"
                            failed += 1
                        break

                    for i in active_tabs:
                        if stop_event.is_set():
                            break
                        try:
                            driver.switch_to.window(tab_handles[i])
                            status, pct = check_tab_progress(driver)

                            if pct != tab_progress.get(i, 0):
                                tab_progress[i] = pct
                                # Build progress summary
                                progress_parts = []
                                for ti in range(len(tab_handles)):
                                    s = tab_status.get(ti, "?")
                                    p = tab_progress.get(ti, 0)
                                    if s == "done":
                                        progress_parts.append(f"T{ti+1}:✅")
                                    elif s == "failed":
                                        progress_parts.append(f"T{ti+1}:❌")
                                    else:
                                        progress_parts.append(f"T{ti+1}:{p}%")
                                log_fn(f"📊 {' | '.join(progress_parts)}")

                            if status == "done":
                                log_fn(f"[Tab {i+1}] ✅ Video selesai! Mengunduh...")
                                video_path = download_tab_video(
                                    driver, OUTPUT_DIR, log_fn, i, tab_start_time)
                                if video_path and os.path.exists(video_path):
                                    generated += 1
                                    tab_status[i] = "done"
                                    sz = os.path.getsize(video_path) / (1024*1024)
                                    log_fn(f"[Tab {i+1}] 📦 {sz:.1f} MB ({generated}/{target})")
                                    send_video_tg(video_path)
                                    # Update download timestamp so next tabs don't conflict
                                    tab_start_time = time.time()
                                else:
                                    tab_status[i] = "failed"
                                    failed += 1
                                    log_fn(f"[Tab {i+1}] ❌ Download gagal")
                        except Exception as e:
                            log_fn(f"[Tab {i+1}] ⚠️ Error: {str(e)[:80]}")

                    time.sleep(3)  # Wait before next round

                # ── Phase 3: Cleanup tabs for next batch ──
                remaining = count - generated
                if remaining > 0 and not stop_event.is_set():
                    log_fn(f"🔄 Menutup tab lama, sisa target: {remaining}")
                    # Close all tabs except first
                    all_handles = driver.window_handles
                    for h in all_handles[1:]:
                        try:
                            driver.switch_to.window(h)
                            driver.close()
                        except:
                            pass
                    driver.switch_to.window(driver.window_handles[0])
                    time.sleep(2)

        except Exception as e:
            log_fn(f"❌ Error fatal: {str(e)[:150]}")
        finally:
            log_done.set()
            time.sleep(3)
            try:
                if driver:
                    driver.quit()
            except:
                pass
            try:
                if chrome_proc:
                    chrome_proc.terminate()
            except:
                pass

    # ═════════════════════════════════════════════════
    #  SINGLE-TAB MODE (count < 10 or infinite)
    # ═════════════════════════════════════════════════
    else:
        idx = 0
        while not stop_event.is_set():
            if not infinite and generated >= count:
                break

            idx += 1
            image_path = get_random_bahan_image(folder_name)
            if not image_path:
                send("❌ Tidak ada gambar lagi di folder bahan!")
                break

            send(
                f"🎬 <b>[Video {idx}]</b> Generating...\n"
                f"📷 Gambar: <code>{escape_html(os.path.basename(image_path))}</code>"
            )

            log_lines = []
            log_lock = threading.Lock()
            log_done = threading.Event()

            def log_fn(msg, tag=None):
                ts = datetime.now().strftime("%H:%M:%S")
                icon = {"success": "✅", "error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(tag, "▪️")
                with log_lock:
                    log_lines.append(f"<code>[{ts}]</code> {icon} {msg}")

            # Send initial log message and start live updater
            log_msg_future = asyncio.run_coroutine_threadsafe(
                bot.send_message(
                    chat_id,
                    f"🎬 <b>[Video {idx}] Live Log</b>\n\n<i>Memulai...</i>",
                    parse_mode=ParseMode.HTML),
                main_loop)
            try:
                log_msg = log_msg_future.result(timeout=10)
                log_msg_id = log_msg.message_id
            except:
                log_msg_id = None

            # Live log updater in async
            async def _live_log_updater():
                last_text = ""
                while not log_done.is_set():
                    with log_lock:
                        body = "\n".join(log_lines[-15:]) if log_lines else "<i>Menunggu...</i>"
                    text = f"🎬 <b>[Video {idx}] Live Log</b>\n\n{body}"
                    if text != last_text and log_msg_id:
                        try:
                            await bot.edit_message_text(
                                chat_id=chat_id, message_id=log_msg_id,
                                text=text[:4096], parse_mode=ParseMode.HTML)
                            last_text = text
                        except:
                            pass
                    await asyncio.sleep(2)
                # Final update
                with log_lock:
                    body = "\n".join(log_lines[-20:]) if log_lines else ""
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=log_msg_id,
                        text=f"🎬 <b>[Video {idx}] Log Selesai</b>\n\n{body}"[:4096],
                        parse_mode=ParseMode.HTML)
                except:
                    pass

            log_task = asyncio.run_coroutine_threadsafe(_live_log_updater(), main_loop)

            video_path = generate_one_video_grok(
                image_path, prompt_text, log_fn, stop_event, OUTPUT_DIR,
                user_data_dir=bot_settings.get("user_data_dir"),
                port=bot_settings.get("port"))

            # Stop live log updater
            log_done.set()
            time.sleep(3)  # Let final update happen

            if stop_event.is_set():
                break

            if video_path and os.path.exists(video_path):
                generated += 1
                send(
                    f"✅ <b>[Video {idx}] Berhasil!</b> ({generated}/{target})"
                )
                # Send video to Telegram
                send_video_tg(video_path)
                time.sleep(3)
            else:
                failed += 1
                send(
                    f"❌ <b>[Video {idx}] Gagal!</b>"
                )

            if not infinite and generated >= count:
                break

            if not stop_event.is_set():
                send("⏳ Menunggu 10 detik sebelum video berikutnya...")
                for _ in range(10):
                    if stop_event.is_set():
                        break
                    time.sleep(1)

    # Final summary
    send(
        f"🏁 <b>Generasi selesai!</b>\n\n"
        f"✅ Berhasil: <b>{generated}</b>\n"
        f"❌ Gagal: <b>{failed}</b>\n"
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
    text = (
        "🎬 <b>Grok Imagine Video Generator</b>\n\n"
        f"{status}\n\n"
        f"📁 Folder bahan: <b>{len(folders)}</b> ({', '.join(folders) if folders else 'kosong'})\n"
        f"📝 Prompt tersimpan: <b>{len(prompts)}</b>\n"
        f"🔌 Port: <code>{cfg.get('port', DEFAULT_PORT)}</code>\n"
        f"📂 User Data: <code>{cfg.get('user_data_dir', DEFAULT_USER_DATA)}</code>\n"
        f"📂 Output: <code>{OUTPUT_DIR}</code>\n\n"
        "<b>Command:</b>\n"
        "<code>/generate [folder] [jumlah] [prompt]</code>\n"
        "<code>/stop</code> — hentikan generasi\n"
        "<code>/set port 9245</code> — ubah port Chrome\n"
        "<code>/set userdata 1</code> — ubah user data dir\n\n"
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
        await update.message.reply_text(
            "⚙️ <b>Settings</b>\n\n"
            f"🔌 Port: <code>{cfg.get('port', DEFAULT_PORT)}</code>\n"
            f"📂 User Data: <code>{cfg.get('user_data_dir', DEFAULT_USER_DATA)}</code>\n\n"
            "<b>Format:</b>\n"
            "<code>/set port 9245</code>\n"
            "<code>/set userdata 1</code>",
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
    else:
        await update.message.reply_text("❌ Sub-command tidak dikenal. Gunakan: port, userdata")


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

    # ══════════════════════════════════════
    #  BAHAN MENU
    # ══════════════════════════════════════
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
            [InlineKeyboardButton("🗑 Hapus Folder", callback_data=f"bahan_del_{folder_name}")],
            [InlineKeyboardButton("📁 Kembali", callback_data="bahan_menu")],
        ])
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
    await update.message.reply_text("❌ Dibatalkan.", reply_markup=main_menu_kb(update.effective_user.id))


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

    print("🎬 Grok Imagine Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
