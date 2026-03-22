"""
═══════════════════════════════════════════════════════════════
  SELENIUM + JS GROK AUTOMATION
  
  Selenium handles Chrome lifecycle (open, tabs, close)
  JavaScript handles all Grok DOM automation (generate, download)
  
  Usage:
    python selenium_js_grok.py
    
  Features:
    - Single-tab or multi-tab generation
    - Image upload (image-to-video mode)
    - Auto-download via requests or button click
    - Progress tracking
    - Retry on failure
    - Configurable prompts and settings
═══════════════════════════════════════════════════════════════
"""

import os
import sys
import re
import time
import glob
import json
import shutil
import base64
import random
import logging
import subprocess
import threading
import requests
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("GrokAuto")

# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════
APP_DIR         = r"C:\tiktok_automation"
OUTPUT_DIR      = os.path.join(APP_DIR, "grok_output")
BAHAN_DIR       = os.path.join(APP_DIR, "bahan")
JS_FILE         = os.path.join(APP_DIR, "grok_auto.js")
CHROME_PATH     = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEFAULT_USER_DATA = os.path.join(APP_DIR, "user_data", "brutal1")
DEFAULT_PORT    = 9250
GROK_URL        = "https://grok.com/imagine"

# ═══════════════════════════════════════════════════════════════
#  CHROME MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def clear_chrome_data(user_data_dir):
    """Clear Chrome cache/history for faster startup (preserve cookies)."""
    if not os.path.exists(user_data_dir):
        return
    default_dir = os.path.join(user_data_dir, "Default")
    if not os.path.isdir(default_dir):
        return
    
    targets = [
        "Cache", "Code Cache", "GPUCache", "Service Worker",
        "History", "History-journal",
        "Visited Links", "Top Sites", "Top Sites-journal",
        "Web Data-journal", "Shortcuts", "Shortcuts-journal"
    ]
    for t in targets:
        p = os.path.join(default_dir, t)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.isfile(p):
                os.remove(p)
        except:
            pass
    log.info("🧹 Chrome cache cleared")


def kill_chrome():
    """Kill all Chrome processes."""
    try:
#         subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], 
                       capture_output=True, timeout=10)
        time.sleep(2)
    except:
        pass


def open_chrome(user_data_dir=None, port=None):
    """Open Chrome with remote debugging enabled."""
    ud = user_data_dir or DEFAULT_USER_DATA
    pt = port or DEFAULT_PORT
    
    os.makedirs(ud, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    clear_chrome_data(ud)
    
    log.info(f"🌐 Opening Chrome (port={pt})...")
    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={pt}",
        f"--user-data-dir={ud}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        GROK_URL
    ]
    proc = subprocess.Popen(cmd)
    time.sleep(5)
    return proc


def connect_selenium(port=None):
    """Connect Selenium to running Chrome instance."""
    pt = port or DEFAULT_PORT
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{pt}")
    
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)
    
    # Set download directory
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": OUTPUT_DIR
    })
    
    log.info("✅ Selenium connected to Chrome")
    return driver


def close_chrome(driver=None, chrome_proc=None):
    """Close Chrome gracefully."""
    log.info("🔒 Closing Chrome...")
    try:
        if driver:
            driver.quit()
    except:
        pass
    try:
        if chrome_proc:
            chrome_proc.terminate()
            chrome_proc.wait(timeout=5)
    except:
        pass
    kill_chrome()
    log.info("✅ Chrome closed")


# ═══════════════════════════════════════════════════════════════
#  JAVASCRIPT INJECTION
# ═══════════════════════════════════════════════════════════════

def load_js():
    """Load the grok_auto.js file content."""
    if not os.path.exists(JS_FILE):
        log.error(f"❌ JS file not found: {JS_FILE}")
        sys.exit(1)
    with open(JS_FILE, 'r', encoding='utf-8') as f:
        return f.read()


def inject_js(driver):
    """Inject grok_auto.js into the current page."""
    js_code = load_js()
    driver.execute_script(js_code)
    time.sleep(1)
    
    # Verify injection
    injected = driver.execute_script("return !!window.__GROK_AUTO_INJECTED;")
    if injected:
        log.info("✅ JS injected successfully")
        return True
    else:
        log.error("❌ JS injection failed")
        return False


def get_state(driver):
    """Get the current automation state from JS."""
    try:
        return driver.execute_script("return window.__grokGetState();")
    except:
        return {"status": "error", "message": "Failed to get state"}


# ═══════════════════════════════════════════════════════════════
#  IMAGE HELPERS
# ═══════════════════════════════════════════════════════════════

def image_to_base64(image_path):
    """Convert image file to base64 string."""
    if not image_path or not os.path.exists(image_path):
        return None
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def get_random_bahan_image(folder_name=None):
    """Get a random image from bahan directory."""
    search_dir = BAHAN_DIR
    if folder_name:
        search_dir = os.path.join(BAHAN_DIR, folder_name)
    
    if not os.path.isdir(search_dir):
        return None
    
    exts = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
    images = [f for f in os.listdir(search_dir) if f.lower().endswith(exts)]
    if not images:
        # Try subdirectories
        for sub in os.listdir(search_dir):
            sub_path = os.path.join(search_dir, sub)
            if os.path.isdir(sub_path):
                sub_images = [f for f in os.listdir(sub_path) if f.lower().endswith(exts)]
                if sub_images:
                    chosen = random.choice(sub_images)
                    return os.path.join(sub_path, chosen)
        return None
    
    chosen = random.choice(images)
    return os.path.join(search_dir, chosen)


# ═══════════════════════════════════════════════════════════════
#  VIDEO DOWNLOAD
# ═══════════════════════════════════════════════════════════════

def download_video_requests(driver, video_url, save_path):
    """Download video using requests library (faster, more reliable)."""
    if not video_url or video_url.startswith('blob:'):
        return False
    
    try:
        cookies = {c['name']: c['value'] for c in driver.get_cookies()}
        headers = {
            'User-Agent': driver.execute_script('return navigator.userAgent;'),
            'Referer': 'https://grok.com/'
        }
        resp = requests.get(video_url, cookies=cookies, headers=headers,
                           stream=True, timeout=120)
        if resp.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in resp.iter_content(65536):
                    if chunk:
                        f.write(chunk)
            if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                sz = os.path.getsize(save_path) / (1024 * 1024)
                log.info(f"✅ Video downloaded via requests ({sz:.1f} MB)")
                return True
    except Exception as e:
        log.warning(f"⚠️ requests download failed: {e}")
    return False


def wait_for_download_file(output_dir, start_time, timeout=60):
    """Wait for a new .mp4 file to appear in the output directory."""
    downloads_folder = os.path.expanduser("~/Downloads")
    
    for _ in range(timeout):
        time.sleep(1)
        # Check output_dir
        for check_dir in [output_dir, downloads_folder]:
            try:
                mp4s = glob.glob(os.path.join(check_dir, "*.mp4"))
                new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
                if new_files:
                    newest = max(new_files, key=os.path.getmtime)
                    # Make sure download is complete
                    if not glob.glob(os.path.join(check_dir, "*.crdownload")):
                        return newest
            except:
                pass
    return None


# ═══════════════════════════════════════════════════════════════
#  SINGLE-TAB GENERATION
# ═══════════════════════════════════════════════════════════════

def generate_single(driver, prompt_text, mode='video', image_path=None, 
                    timeout_ms=600000):
    """
    Generate a single video/image on the current tab.
    JS handles all DOM interactions.
    Python handles download + file management.
    
    Returns: path to downloaded file, or None on failure.
    """
    # Inject JS if not already
    try:
        is_injected = driver.execute_script("return !!window.__GROK_AUTO_INJECTED;")
    except:
        is_injected = False
    
    if not is_injected:
        if not inject_js(driver):
            return None

    # Prepare config
    config = {
        'prompt': prompt_text,
        'mode': mode,
        'image': None,
        'imageName': 'ref.jpg',
        'timeout': timeout_ms,
    }
    
    # Handle image
    if image_path:
        b64 = image_to_base64(image_path)
        if b64:
            config['image'] = b64
            config['imageName'] = os.path.basename(image_path)
            log.info(f"📷 Image prepared: {os.path.basename(image_path)}")
    
    # Start generation via JS
    log.info(f"🚀 Starting generation: {prompt_text[:80]}...")
    start_time = time.time()
    
    # Call the async JS function
    driver.execute_script("""
        window.__grokGenerate(arguments[0]).then(result => {
            window.__grokLastResult = result;
        }).catch(err => {
            window.__grokLastResult = {status: 'error', error: err.message};
        });
    """, config)
    
    # Poll for completion
    last_progress = -1
    while True:
        time.sleep(2)
        elapsed = time.time() - start_time
        
        state = get_state(driver)
        status = state.get('status', 'unknown')
        progress = state.get('progress', 0)
        message = state.get('message', '')
        
        if progress != last_progress:
            log.info(f"⏳ [{int(elapsed)}s] {message} ({progress}%)")
            last_progress = progress
        
        if status == 'done':
            log.info(f"✅ Generation complete in {int(elapsed)}s")
            break
        elif status == 'error':
            error = state.get('error', 'Unknown error')
            log.error(f"❌ Generation failed: {error}")
            return None
        elif status == 'cancelled':
            log.info("🛑 Generation cancelled")
            return None
        
        if elapsed > (timeout_ms / 1000) + 30:
            log.error("❌ Timeout exceeded")
            return None
    
    # Download the video
    video_url = state.get('videoUrl')
    if not video_url:
        # Try to extract again
        try:
            video_url = driver.execute_script("""
                for(const v of document.querySelectorAll('video')){
                    if(v.src && v.src.startsWith('http')) return v.src;
                    const s = v.querySelector('source');
                    if(s && s.src) return s.src;
                }
                return null;
            """)
        except:
            pass
    
    filename = f"grok_{int(time.time())}.mp4"
    save_path = os.path.join(OUTPUT_DIR, filename)
    
    # Method 1: Download via requests
    if video_url and download_video_requests(driver, video_url, save_path):
        return save_path
    
    # Method 2: Wait for file from browser download
    log.info("📥 Waiting for browser download...")
    dl_start = time.time()
    downloaded_file = wait_for_download_file(OUTPUT_DIR, start_time)
    if downloaded_file:
        if downloaded_file != save_path:
            shutil.move(downloaded_file, save_path)
        log.info(f"✅ Video saved: {filename}")
        return save_path
    
    # Method 3: Check Downloads folder
    downloads_folder = os.path.expanduser("~/Downloads")
    downloaded_file = wait_for_download_file(downloads_folder, start_time, timeout=30)
    if downloaded_file:
        shutil.move(downloaded_file, save_path)
        log.info(f"✅ Video saved from Downloads: {filename}")
        return save_path
    
    log.warning("⚠️ Could not download video file")
    return None


# ═══════════════════════════════════════════════════════════════
#  MULTI-TAB GENERATION
# ═══════════════════════════════════════════════════════════════

def setup_tabs(driver, num_tabs, url=GROK_URL):
    """Open multiple tabs, each navigating to grok.com/imagine."""
    log.info(f"📑 Setting up {num_tabs} tabs...")
    handles = driver.window_handles
    
    # Open additional tabs
    while len(driver.window_handles) < num_tabs:
        driver.switch_to.new_window('tab')
        driver.get(url)
        time.sleep(1)
    
    # Ensure all tabs are on the correct URL
    for i, handle in enumerate(driver.window_handles[:num_tabs]):
        driver.switch_to.window(handle)
        current = driver.current_url
        if 'grok.com' not in current or 'imagine' not in current:
            driver.get(url)
            time.sleep(1)
    
    log.info(f"✅ {len(driver.window_handles)} tabs ready")
    return driver.window_handles[:num_tabs]


def generate_multitab(driver, prompts_config, num_tabs=5, cycles=1, 
                      bahan_folder=None):
    """
    Multi-tab batch generation.
    
    prompts_config: list of dicts:
        [
            {"prompt": "text...", "mode": "video", "use_image": True},
            {"prompt": "text...", "mode": "video", "use_image": False},
            ...
        ]
    
    Runs prompts across multiple tabs in parallel.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Setup tabs
    tab_handles = setup_tabs(driver, num_tabs)
    num_tabs = len(tab_handles)
    
    total_results = []
    
    for cycle in range(1, cycles + 1):
        log.info(f"\n{'='*60}")
        log.info(f"  CYCLE {cycle}/{cycles}")
        log.info(f"{'='*60}\n")
        
        cycle_start = time.time()
        
        # ── Phase 1: Start generation on all tabs ──
        log.info("── Phase 1: Starting generation on all tabs ──")
        tab_start_times = {}
        
        for i in range(min(num_tabs, len(prompts_config))):
            cfg = prompts_config[i % len(prompts_config)]
            handle = tab_handles[i]
            
            try:
                driver.switch_to.window(handle)
                log.info(f"[Tab {i+1}] Starting...")
                
                # Inject JS
                inject_js(driver)
                
                # Prepare image
                image_b64 = None
                image_name = 'ref.jpg'
                if cfg.get('use_image'):
                    img_path = get_random_bahan_image(bahan_folder)
                    if img_path:
                        image_b64 = image_to_base64(img_path)
                        image_name = os.path.basename(img_path)
                        log.info(f"[Tab {i+1}] 📷 Image: {image_name}")
                
                # Start generate via JS (async, non-blocking)
                tab_config = {
                    'prompt': cfg['prompt'],
                    'mode': cfg.get('mode', 'video'),
                    'image': image_b64,
                    'imageName': image_name,
                    'timeout': 600000,
                }
                
                driver.execute_script("""
                    window.__grokTabGenerate(arguments[0], arguments[1]);
                """, i, tab_config)
                
                tab_start_times[i] = time.time()
                log.info(f"[Tab {i+1}] ✅ Generation started")
                time.sleep(1)  # Brief pause between tabs
                
            except Exception as e:
                log.error(f"[Tab {i+1}] ❌ Failed to start: {e}")
        
        # ── Phase 2: Monitor progress on all tabs ──
        log.info("\n── Phase 2: Monitoring progress ──")
        tab_done = set()
        tab_failed = set()
        max_wait = 660  # 11 minutes max
        monitor_start = time.time()
        
        while len(tab_done) + len(tab_failed) < min(num_tabs, len(prompts_config)):
            if time.time() - monitor_start > max_wait:
                log.warning("⚠️ Max wait time reached, moving on")
                break
            
            for i in range(min(num_tabs, len(prompts_config))):
                if i in tab_done or i in tab_failed:
                    continue
                
                try:
                    driver.switch_to.window(tab_handles[i])
                    
                    # Check progress
                    tab_state = driver.execute_script(
                        "return window.__grokTabCheckProgress(arguments[0]);", i
                    )
                    
                    if tab_state:
                        status = tab_state.get('status', 'unknown')
                        progress = tab_state.get('progress', 0)
                        
                        if status == 'done':
                            log.info(f"[Tab {i+1}] ✅ Done!")
                            tab_done.add(i)
                        elif status == 'error':
                            log.error(f"[Tab {i+1}] ❌ Error: {tab_state.get('error')}")
                            tab_failed.add(i)
                        elif progress > 0:
                            elapsed = int(time.time() - tab_start_times.get(i, monitor_start))
                            log.info(f"[Tab {i+1}] ⏳ {progress}% ({elapsed}s)")
                    
                except Exception as e:
                    log.warning(f"[Tab {i+1}] ⚠️ Check failed: {e}")
            
            time.sleep(5)  # Check every 5 seconds
        
        # ── Phase 3: Download from completed tabs ──
        log.info("\n── Phase 3: Downloading results ──")
        
        for i in tab_done:
            try:
                driver.switch_to.window(tab_handles[i])
                log.info(f"[Tab {i+1}] 📥 Downloading...")
                
                # Get video URL and click download
                result = driver.execute_script(
                    "return await window.__grokTabDownload(arguments[0]);", i
                )
                
                video_url = result.get('videoUrl') if result else None
                
                filename = f"grok_{int(time.time())}_{i}.mp4"
                save_path = os.path.join(OUTPUT_DIR, filename)
                
                # Download via requests
                if video_url and download_video_requests(driver, video_url, save_path):
                    total_results.append(save_path)
                    log.info(f"[Tab {i+1}] ✅ Saved: {filename}")
                else:
                    # Wait for browser download
                    dl_file = wait_for_download_file(
                        OUTPUT_DIR, tab_start_times.get(i, cycle_start), timeout=30
                    )
                    if dl_file:
                        if dl_file != save_path:
                            shutil.move(dl_file, save_path)
                        total_results.append(save_path)
                        log.info(f"[Tab {i+1}] ✅ Saved: {filename}")
                    else:
                        log.warning(f"[Tab {i+1}] ⚠️ Download failed")
                
                time.sleep(1)
                
            except Exception as e:
                log.error(f"[Tab {i+1}] ❌ Download error: {e}")
        
        # ── Phase 4: Reload failed tabs for next cycle ──
        if cycle < cycles:
            log.info("\n── Reloading tabs for next cycle ──")
            for i in range(min(num_tabs, len(prompts_config))):
                try:
                    driver.switch_to.window(tab_handles[i])
                    driver.get(GROK_URL)
                    time.sleep(1)
                except:
                    pass
        
        elapsed_cycle = time.time() - cycle_start
        log.info(f"\n✅ Cycle {cycle} done in {int(elapsed_cycle//60)}m {int(elapsed_cycle%60)}s")
        log.info(f"   Results: {len(tab_done)} success, {len(tab_failed)} failed")
    
    return total_results


# ═══════════════════════════════════════════════════════════════
#  MAIN — Interactive CLI
# ═══════════════════════════════════════════════════════════════

def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║         SELENIUM + JS GROK AUTOMATION                    ║
║   Selenium = Chrome controller | JS = Grok automator    ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    print("Mode:")
    print("  1. Single Tab — Generate satu per satu")
    print("  2. Multi Tab  — Generate paralel banyak tab")
    print("  3. Quick Test — Test satu video dengan prompt default")
    print()
    
    mode = input("Pilih mode (1/2/3): ").strip()
    
    chrome_proc = None
    driver = None
    
    try:
        # Open Chrome
        user_data = input(f"User data dir [{DEFAULT_USER_DATA}]: ").strip() or DEFAULT_USER_DATA
        port = input(f"Port [{DEFAULT_PORT}]: ").strip()
        port = int(port) if port else DEFAULT_PORT
        
        chrome_proc = open_chrome(user_data, port)
        driver = connect_selenium(port)
        
        if mode == '1':
            # ── Single Tab Mode ──
            print("\n── Single Tab Mode ──")
            print("Masukkan prompt (ketik 'q' untuk selesai):")
            
            count = 0
            while True:
                prompt = input(f"\n[{count+1}] Prompt: ").strip()
                if prompt.lower() == 'q':
                    break
                if not prompt:
                    continue
                
                use_img = input("Pakai gambar? (y/n) [n]: ").strip().lower() == 'y'
                img_path = None
                if use_img:
                    folder = input("Folder bahan (kosong = random): ").strip() or None
                    img_path = get_random_bahan_image(folder)
                    if img_path:
                        print(f"   📷 Image: {os.path.basename(img_path)}")
                    else:
                        print("   ⚠️ Tidak ada gambar, lanjut tanpa gambar")
                
                gen_mode = input("Mode (video/image) [video]: ").strip() or 'video'
                
                result = generate_single(driver, prompt, mode=gen_mode, image_path=img_path)
                if result:
                    print(f"   ✅ Output: {result}")
                    count += 1
                else:
                    print("   ❌ Generation gagal")
                
                # Reload page for next generation
                try:
                    driver.get(GROK_URL)
                    time.sleep(3)
                except:
                    pass
            
            print(f"\n✅ Total generated: {count}")
        
        elif mode == '2':
            # ── Multi Tab Mode ──
            print("\n── Multi Tab Mode ──")
            
            num_tabs = int(input("Jumlah tab [5]: ").strip() or '5')
            cycles = int(input("Jumlah siklus [1]: ").strip() or '1')
            bahan = input("Folder bahan (kosong = none): ").strip() or None
            
            print(f"\nMasukkan {num_tabs} prompt (satu per baris):")
            prompts_config = []
            for i in range(num_tabs):
                prompt = input(f"  Tab {i+1} prompt: ").strip()
                if not prompt:
                    prompt = f"Generate a stunning cinematic video of a futuristic cityscape at sunset, style #{i+1}"
                use_img = input(f"  Tab {i+1} pakai gambar? (y/n) [n]: ").strip().lower() == 'y'
                prompts_config.append({
                    'prompt': prompt,
                    'mode': 'video',
                    'use_image': use_img,
                })
            
            results = generate_multitab(driver, prompts_config, num_tabs=num_tabs,
                                       cycles=cycles, bahan_folder=bahan)
            print(f"\n✅ Total videos generated: {len(results)}")
            for r in results:
                print(f"   📹 {r}")
        
        elif mode == '3':
            # ── Quick Test ──
            print("\n── Quick Test ──")
            test_prompt = (
                "Create an 8-second cinematic video of a powerful dragon "
                "soaring over snow-capped mountains at golden hour. "
                "Ultra detailed, 8K quality, dramatic lighting."
            )
            print(f"Prompt: {test_prompt[:80]}...")
            
            result = generate_single(driver, test_prompt, mode='video')
            if result:
                print(f"\n✅ Video saved: {result}")
            else:
                print("\n❌ Generation failed")
        
        else:
            print("Mode tidak valid")
    
    except KeyboardInterrupt:
        print("\n\n⛔ Interrupted by user")
    except Exception as e:
        log.error(f"❌ Fatal error: {e}", exc_info=True)
    finally:
        # Prompt before closing
        input("\nTekan Enter untuk menutup Chrome...")
        close_chrome(driver, chrome_proc)


# ═══════════════════════════════════════════════════════════════
#  PROGRAMMATIC API — For use from other scripts
# ═══════════════════════════════════════════════════════════════

class GrokAutomation:
    """
    Wrapper class for programmatic use from other scripts.
    
    Usage:
        grok = GrokAutomation()
        grok.start()
        result = grok.generate("prompt text", mode='video')
        grok.stop()
    """
    
    def __init__(self, user_data_dir=None, port=None):
        self.user_data_dir = user_data_dir or DEFAULT_USER_DATA
        self.port = port or DEFAULT_PORT
        self.driver = None
        self.chrome_proc = None
        self._js_injected = False
    
    def start(self):
        """Start Chrome and connect Selenium."""
        self.chrome_proc = open_chrome(self.user_data_dir, self.port)
        self.driver = connect_selenium(self.port)
        return self
    
    def _ensure_js(self):
        """Ensure JS is injected on the current page."""
        if not self._js_injected:
            try:
                is_inj = self.driver.execute_script("return !!window.__GROK_AUTO_INJECTED;")
                if is_inj:
                    self._js_injected = True
                    return
            except:
                pass
            inject_js(self.driver)
            self._js_injected = True
    
    def generate(self, prompt_text, mode='video', image_path=None, timeout_ms=600000):
        """Generate a single video/image. Returns file path or None."""
        self._ensure_js()
        result = generate_single(self.driver, prompt_text, mode=mode,
                                image_path=image_path, timeout_ms=timeout_ms)
        self._js_injected = False  # Need re-inject after page change
        return result
    
    def generate_batch(self, prompts_config, num_tabs=5, cycles=1, bahan_folder=None):
        """Generate multiple videos in parallel. Returns list of file paths."""
        return generate_multitab(self.driver, prompts_config, num_tabs=num_tabs,
                                cycles=cycles, bahan_folder=bahan_folder)
    
    def navigate(self, url=GROK_URL):
        """Navigate to a URL."""
        self.driver.get(url)
        time.sleep(3)
        self._js_injected = False
    
    def stop(self):
        """Close Chrome and cleanup."""
        close_chrome(self.driver, self.chrome_proc)
        self.driver = None
        self.chrome_proc = None
        self._js_injected = False
    
    def __enter__(self):
        return self.start()
    
    def __exit__(self, *args):
        self.stop()


if __name__ == "__main__":
    main()
