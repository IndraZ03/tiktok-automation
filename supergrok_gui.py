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
from datetime import datetime

# ── Try selenium imports ──
try:
    import requests
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
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
    except Exception as e:
        pass

# ── Default prompts ──
DEFAULT_PROMPT_1 = """Buat video singkat 8 detik dengan visual sinematik berkualitas tinggi.\nKarakter: wanita Indonesia cantik, percaya diri, modern.\nProduk: Tablet Android layar 11.6 inci, OLED, 5G, RAM 16GB, ROM 1024GB.\nGaya: Cinematic, Lighting dramatis, efek api/emas.\nVO: Bahasa Indonesia, singkat, enerjik.\nJangan ada teks overlay di layar."""

DEFAULT_PROMPT_2 = """Gaming Beast Video 8 detik.\nKarakter: gamer muda, antusias, pakai tablet gaming.\nProduk: Tablet Android, layar 11.6 inci, 5G, 16GB RAM, 1024GB ROM.\nGaya: neon glitch merah-biru, energik, banyak efek cahaya.\nVO: Bahasa Indonesia, cepat, agresif, caster e-sports.\nMusik: trap/EDM gaming, bass kencang."""

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

STATUS_COLORS = {
    "idle":        MUTED,
    "generating":  YELLOW,
    "waiting":     ACCENT,
    "downloading": GREEN,
    "success":     GREEN,
    "error":       RED,
    "stopped":     RED,
    "setting":     ACCENT,
    "uploading":   ACCENT,
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
#  AUTOMATION ENGINE  (runs in background thread)
# ════════════════════════════════════════════════════════════════════════════
class AutomationEngine:
    def __init__(self, config, log_q, status_q):
        self.cfg    = config
        self.log_q  = log_q
        self.stat_q = status_q
        self._stop  = threading.Event()
        self.driver = None

    def stop(self):
        self._stop.set()

    def log(self, msg, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_q.put(f"[{ts}] [{level}] {msg}")

    def set_tab_status(self, tab_idx, pct, status):
        self.stat_q.put({"tab": tab_idx, "pct": pct, "status": status})

    # ── File naming ──
    def get_next_filename(self, folder):
        files = glob.glob(os.path.join(folder, "*.mp4"))
        pat   = re.compile(r'(\d+)\.mp4')
        max_n = 0
        for f in files:
            m = pat.fullmatch(os.path.basename(f))
            if m: max_n = max(max_n, int(m.group(1)))
        return f"{max_n + 1}.mp4"

    # ── Chrome ──
    def open_chrome(self):
        self.log("Membuka Chrome dalam mode debug...")
        chrome = self.cfg.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        port   = self.cfg.get("debug_port", DEFAULT_PORT)
        ud     = self.cfg.get("user_data_dir", DEFAULT_USER_DATA)
        cmd    = [chrome, f"--remote-debugging-port={port}", f"--user-data-dir={ud}",
                  "--no-first-run", "--no-default-browser-check", GROK_URL]
        subprocess.Popen(cmd)
        time.sleep(5)

    def kill_chrome(self):
        port = self.cfg.get("debug_port", DEFAULT_PORT)
        try:
            res = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10)
            pids = set()
            for line in res.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts: pids.add(parts[-1])
            for pid in pids:
                subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=5)
                self.log(f"Chrome PID {pid} dimatikan ✓")
            if not pids:
                subprocess.run(["taskkill", "/IM", "chrome.exe", "/F"], capture_output=True, timeout=5)
        except Exception as e:
            self.log(f"Gagal matikan Chrome: {e}", "WARN")

    def connect_selenium(self):
        port = self.cfg.get("debug_port", DEFAULT_PORT)
        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
        try:
            svc    = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=svc, options=opts)
            output_dir = self.cfg["output_dir"]
            os.makedirs(output_dir, exist_ok=True)
            driver.execute_cdp_cmd("Page.setDownloadBehavior",
                                   {"behavior": "allow", "downloadPath": output_dir})
            self.log("Selenium terhubung ke Chrome ✓")
            return driver
        except Exception as e:
            self.log(f"Gagal connect Selenium: {e}", "ERROR")
            return None

    # ── Setup tab ──
    def setup_tab(self, driver, image_path, prompt_text, tab_idx):
        """Navigate, upload image, set Buat Video, fill prompt, click generate."""
        prefix = f"Tab {tab_idx+1}"
        self.set_tab_status(tab_idx, 0, "generating")

        # Navigate to grok
        try:
            cur = driver.current_url
            if "grok.com" not in cur or "imagine" not in cur:
                driver.get(GROK_URL)
                time.sleep(5)
        except:
            driver.get(GROK_URL)
            time.sleep(5)

        if self._stop.is_set(): return False

        # Upload image
        if image_path and os.path.exists(image_path):
            self.log(f"{prefix}: Upload gambar {os.path.basename(image_path)}")
            abs_img = os.path.abspath(image_path)
            uploaded = False

            # Count before
            def count_imgs():
                try:
                    return driver.execute_script("""
                        let c = 0;
                        c += document.querySelectorAll('img[src*="assets.grok.com"]').length;
                        c += document.querySelectorAll('img[src^="blob:"]').length;
                        c += document.querySelectorAll('div.group.relative img').length;
                        return c;
                    """)
                except: return 0

            before = count_imgs()

            # Method A: direct file input
            try:
                file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if file_inputs:
                    fi = file_inputs[-1]
                    driver.execute_script(
                        "arguments[0].style.display='block';arguments[0].style.visibility='visible';"
                        "arguments[0].style.opacity='1';arguments[0].style.height='1px';"
                        "arguments[0].style.width='1px';arguments[0].style.position='absolute';", fi)
                    fi.send_keys(abs_img)
                    time.sleep(3)
                    if count_imgs() > before:
                        uploaded = True
                        self.log(f"{prefix}: ✅ Gambar terupload (method A)")
            except: pass

            # Method B: inject input
            if not uploaded:
                try:
                    inj_id = f"sgrok_input_{tab_idx}"
                    driver.execute_script(f"""
                        const old = document.getElementById('{inj_id}');
                        if (old) old.remove();
                        const i = document.createElement('input');
                        i.type='file'; i.id='{inj_id}'; i.accept='image/*';
                        i.style.cssText='position:absolute;top:0;left:0;z-index:99999;display:block;width:1px;height:1px;';
                        document.body.appendChild(i);
                    """)
                    time.sleep(0.5)
                    inj = driver.find_element(By.ID, inj_id)
                    inj.send_keys(abs_img)
                    time.sleep(3)
                    if count_imgs() > before:
                        uploaded = True
                        self.log(f"{prefix}: ✅ Gambar terupload (method B)")
                except: pass

            if not uploaded:
                self.log(f"{prefix}: ⚠️ Upload gambar gagal, lanjut tanpa gambar", "WARN")
        else:
            self.log(f"{prefix}: ⚠️ Tidak ada gambar")

        if self._stop.is_set(): return False

        # Settings → Buat Video
        self.set_tab_status(tab_idx, 5, "setting")
        settings_opened = False
        for attempt_label, attempt_fn in [
            ("Selenium", lambda: ActionChains(driver).move_to_element(
                driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Settings"], button[aria-label="Pengaturan"]')[0]
            ).click().perform()),
            ("JS pointer", lambda: driver.execute_script("""
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const l = b.getAttribute('aria-label') || '';
                    if (l === 'Settings' || l === 'Pengaturan') {
                        b.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
                        b.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
                        b.dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));
                        b.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
                        b.dispatchEvent(new MouseEvent('click',{bubbles:true}));
                        return true;
                    }
                } return false;""")),
            ("Enter key", lambda: driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Settings"], button[aria-label="Pengaturan"]')[0].send_keys(Keys.ENTER)),
        ]:
            if settings_opened: break
            try:
                attempt_fn()
                time.sleep(1.5)
                if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                    settings_opened = True
            except: pass

        if settings_opened:
            try:
                items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
                for it in items:
                    t = it.text or ""
                    if "Buat Video" in t or "Make Video" in t or "Make video" in t:
                        ActionChains(driver).move_to_element(it).click().perform()
                        self.log(f"{prefix}: ✅ Buat Video dipilih")
                        break
                time.sleep(1)
            except: pass
        else:
            self.log(f"{prefix}: ⚠️ Settings tidak terbuka, lanjut", "WARN")

        if self._stop.is_set(): return False

        # Fill prompt
        self.set_tab_status(tab_idx, 10, "generating")
        prompt_filled = False
        try:
            editor = driver.execute_script("""
                const ed = document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                if (ed) { ed.scrollIntoView({behavior:'smooth',block:'center'}); return ed; }
                return null;
            """)
            if editor:
                time.sleep(0.5)
                driver.execute_script("arguments[0].focus();", editor)
                editor.click()
                time.sleep(0.3)
                editor.send_keys(Keys.CONTROL + "a")
                time.sleep(0.2)
                editor.send_keys(Keys.DELETE)
                time.sleep(0.2)
                driver.execute_script("""
                    const ed = arguments[0];
                    ed.innerHTML = '<p>' + arguments[1] + '</p>';
                    ed.dispatchEvent(new Event('input', {bubbles:true}));
                    ed.dispatchEvent(new Event('change', {bubbles:true}));
                """, editor, prompt_text)
                time.sleep(1)
                prompt_filled = True
                self.log(f"{prefix}: ✅ Prompt diisi")
        except: pass

        if not prompt_filled:
            try:
                result = driver.execute_script("""
                    const ed = document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                    if (!ed) return 'not_found';
                    ed.focus();
                    ed.innerHTML = '<p>' + arguments[0] + '</p>';
                    ed.dispatchEvent(new Event('input', {bubbles:true}));
                    ed.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true}));
                    return 'ok';
                """, prompt_text)
                if result == 'ok':
                    prompt_filled = True
                    time.sleep(1)
            except: pass

        if not prompt_filled:
            try:
                ed = WebDriverWait(driver, 20).until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'div.tiptap.ProseMirror[contenteditable="true"]')))
                ed.click(); time.sleep(0.5)
                ed.send_keys(Keys.CONTROL + "a"); ed.send_keys(Keys.DELETE); time.sleep(0.3)
                for chunk in [prompt_text[i:i+50] for i in range(0, len(prompt_text), 50)]:
                    ed.send_keys(chunk); time.sleep(0.1)
                prompt_filled = True
            except Exception as e:
                self.log(f"{prefix}: ❌ Semua metode prompt gagal: {e}", "ERROR")
                return False

        if self._stop.is_set(): return False

        # Click Generate
        try:
            gen_btn = None
            for lbl in ['Buat video', 'Create video', 'Generate', 'Submit']:
                try:
                    gen_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, f'button[aria-label="{lbl}"]')))
                    if gen_btn: break
                except: continue
            if not gen_btn:
                try: gen_btn = driver.find_element(By.CSS_SELECTOR, 'button.group[type="button"]')
                except: pass
            if gen_btn:
                gen_btn.click()
            else:
                driver.execute_script("""
                    const b = document.querySelector('button[aria-label="Buat video"]')
                           || document.querySelector('button[aria-label="Create video"]')
                           || document.querySelector('button.group[type="button"]');
                    if (b) b.click();
                """)
            self.log(f"{prefix}: ✅ Generate diklik!")
            time.sleep(3)
            return True
        except Exception as e:
            self.log(f"{prefix}: ❌ Gagal klik Generate: {e}", "ERROR")
            return False

    # ── Wait & Download ──
    def wait_and_download(self, driver, tab_idx, output_dir):
        prefix     = f"Tab {tab_idx+1}"
        start_time = time.time()
        timeout    = 600  # 10 menit
        last_pct   = ""
        last_pct_n = 0
        gen_started = False
        self.set_tab_status(tab_idx, 0, "waiting")

        while time.time() - start_time < timeout:
            if self._stop.is_set(): return None

            # Read progress %
            try:
                pct_text = driver.execute_script("""
                    const spans = document.querySelectorAll('span.tabular-nums');
                    for (const s of spans) {
                        const t = s.textContent.trim();
                        if (t.includes('%')) return t;
                    }
                    const ov = document.querySelector('div.flex.justify-center.items-center.gap-2');
                    if (ov) {
                        for (const n of ov.querySelectorAll('span'))
                            if (n.textContent.includes('%')) return n.textContent.trim();
                    }
                    return '';
                """)
                if pct_text and pct_text != last_pct:
                    self.log(f"{prefix}: ⏳ Progress {pct_text}")
                    last_pct = pct_text
                    gen_started = True
                    m = re.search(r'(\d+)', pct_text)
                    if m:
                        last_pct_n = int(m.group(1))
                        self.set_tab_status(tab_idx, last_pct_n, "waiting")
            except: pass

            # Check generating overlay
            try:
                is_gen = driver.execute_script("""
                    const spans = document.querySelectorAll('span');
                    for (const s of spans) {
                        const t = s.textContent;
                        if (t.includes('Menghasilkan') || t.includes('Generating')) return true;
                    }
                    return false;
                """)
            except: is_gen = False

            # Check Download button
            try:
                dl_btns = driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Download"], button[aria-label="Unduh"]')
                if dl_btns and not is_gen:
                    self.log(f"{prefix}: ✅ Video selesai! Memulai download...")
                    break
            except: pass

            if gen_started and not is_gen and last_pct_n > 0:
                self.log(f"{prefix}: ✅ Generasi selesai! Menunggu elemen muncul...")
                time.sleep(3)
                break

            time.sleep(1)
        else:
            self.log(f"{prefix}: ❌ Timeout 10 menit", "ERROR")
            self.set_tab_status(tab_idx, 0, "error")
            return None

        if self._stop.is_set(): return None

        # Download
        self.set_tab_status(tab_idx, 100, "downloading")
        filename  = self.get_next_filename(output_dir)
        save_path = os.path.join(output_dir, filename)
        dl_clicked = False

        # Click download button
        try:
            dl_btns = driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Download"], button[aria-label="Unduh"]')
            if dl_btns:
                ActionChains(driver).move_to_element(dl_btns[0]).click().perform()
                dl_clicked = True
                self.log(f"{prefix}: ✅ Tombol Download diklik (Selenium)")
        except: pass

        if not dl_clicked:
            try:
                dl_clicked = driver.execute_script("""
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        const l = b.getAttribute('aria-label') || '';
                        if (l === 'Download' || l === 'Unduh') {
                            b.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
                            b.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
                            b.dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));
                            b.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));
                            b.dispatchEvent(new MouseEvent('click',{bubbles:true}));
                            return true;
                        }
                    } return false;
                """)
                if dl_clicked: self.log(f"{prefix}: ✅ Download diklik (pointer events)")
            except: pass

        if not dl_clicked:
            try:
                dl_btns = driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Download"], button[aria-label="Unduh"]')
                if dl_btns:
                    dl_btns[0].send_keys(Keys.ENTER)
                    dl_clicked = True
                    self.log(f"{prefix}: ✅ Download diklik (Enter)")
            except: pass

        if not dl_clicked:
            self.log(f"{prefix}: ❌ Tidak bisa klik Download", "ERROR")
            self.set_tab_status(tab_idx, 0, "error")
            return None

        # Wait for file
        self.log(f"{prefix}: ⏳ Menunggu file (max 60 detik)...")
        gen_time      = start_time
        dl_time       = time.time()
        downloads_dir = os.path.expanduser("~/Downloads")

        for _ in range(60):
            time.sleep(1)
            if self._stop.is_set(): return None

            for check_dir in [output_dir, downloads_dir]:
                try:
                    mp4s = glob.glob(os.path.join(check_dir, "*.mp4"))
                    new  = [f for f in mp4s if os.path.getmtime(f) > dl_time - 2]
                    if new:
                        crdowns = glob.glob(os.path.join(check_dir, "*.crdownload"))
                        if not crdowns:
                            newest = max(new, key=os.path.getmtime)
                            if check_dir != output_dir:
                                os.makedirs(output_dir, exist_ok=True)
                                shutil.move(newest, save_path)
                                newest = save_path
                            elif newest != save_path:
                                shutil.move(newest, save_path)
                                newest = save_path
                            if os.path.getsize(newest) > 10240:
                                self.log(f"{prefix}: ✅ {filename} ({os.path.getsize(newest)/1024/1024:.1f} MB)")
                                self.set_tab_status(tab_idx, 100, "success")
                                return newest
                except: pass

        self.log(f"{prefix}: ❌ File tidak muncul setelah 60 detik", "ERROR")
        self.set_tab_status(tab_idx, 0, "error")
        return None

    # ── Merge pairs ──
    def merge_videos_pairs(self, output_dir, merged_dir):
        def _sort_key(f):
            m = re.search(r'(\d+)', os.path.basename(f))
            return int(m.group(1)) if m else 0

        os.makedirs(merged_dir, exist_ok=True)
        all_files = sorted(
            [f for f in glob.glob(os.path.join(output_dir, "*.mp4"))
             if os.path.getsize(f) > 10240],
            key=_sort_key
        )
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

    # ── Main Run ──
    def run(self):
        if not SELENIUM_OK:
            self.log("Selenium tidak terinstall!", "ERROR")
            return

        cfg          = self.cfg
        n_tabs       = cfg["n_tabs"]
        n_cycles     = cfg["n_cycles"]
        prompts      = cfg["prompts"]
        output_dir   = cfg["output_dir"]
        merged_dir   = cfg.get("merged_dir", MERGED_DIR)
        bahan_folder = cfg.get("bahan_folder", "")
        alt_img      = cfg.get("alternate_image", True)
        use_all      = cfg.get("use_image_all", True)

        os.makedirs(output_dir, exist_ok=True)

        self.open_chrome()
        if self._stop.is_set(): return

        driver = self.connect_selenium()
        if not driver: return
        self.driver = driver

        for cycle in range(n_cycles):
            if self._stop.is_set(): break
            self.log(f"\n=== SIKLUS {cycle+1}/{n_cycles} ===")
            self.stat_q.put({"cycle": cycle + 1})

            downloaded_in_cycle = []

            # ── Phase 1: Buka tab satu per satu, klik Generate, lanjut ──
            self.log(f"[Phase 1] Membuka {n_tabs} tab & klik Generate...")
            tab_handles   = []   # window handle per tab
            tab_status    = {}   # idx -> "generating" | "done" | "failed"
            tab_progress  = {}   # idx -> int pct
            tab_start_time = time.time()

            for i in range(n_tabs):
                if self._stop.is_set(): break

                # Tentukan prompt & gambar
                prompt_text = prompts[i % len(prompts)]
                if alt_img:
                    use_img = (i % 2 == 0)
                else:
                    use_img = use_all
                image_path = None
                if use_img and bahan_folder:
                    image_path = get_random_bahan_image(bahan_folder)

                # Buka tab baru (tab pertama gunakan tab yang ada)
                if i == 0:
                    # Pakai tab yang sudah ada atau tab pertama
                    if driver.window_handles:
                        driver.switch_to.window(driver.window_handles[0])
                    driver.get(GROK_URL)
                    time.sleep(3)
                else:
                    try:
                        driver.switch_to.new_window('tab')
                        driver.get(GROK_URL)
                        time.sleep(3)
                    except Exception as e:
                        self.log(f"Tab {i+1}: Gagal buka tab baru – {e}", "WARN")
                        tab_status[i] = "failed"
                        tab_progress[i] = 0
                        continue

                handle = driver.current_window_handle
                tab_handles.append(handle)

                self.log(f"[Tab {i+1}] 🌐 Halaman dimuat, setup & generate...")

                ok = self.setup_tab(driver, image_path, prompt_text, i)
                if ok:
                    tab_status[i]   = "generating"
                    tab_progress[i] = 0
                    self.log(f"[Tab {i+1}] ✅ Generate diklik, lanjut ke tab berikutnya")
                else:
                    tab_status[i]   = "failed"
                    tab_progress[i] = 0
                    self.log(f"[Tab {i+1}] ❌ Setup gagal, skip", "WARN")

                time.sleep(1)  # jeda kecil sebelum tab berikutnya

            if self._stop.is_set(): break

            actual_tabs = len(tab_handles)
            self.log(f"[Phase 1 selesai] {actual_tabs} tab generate berjalan.")

            # ── Phase 2: Round-Robin monitoring semua tab ──
            self.log("[Phase 2] Monitoring progress semua tab (round-robin)...")
            timeout_start = time.time()
            MAX_TIMEOUT   = 600  # 10 menit per siklus

            while not self._stop.is_set():
                # Cek apakah masih ada tab yang generate
                active = [i for i, s in tab_status.items() if s == "generating"]
                if not active:
                    self.log("✅ Semua tab selesai di siklus ini!")
                    break

                if time.time() - timeout_start > MAX_TIMEOUT:
                    self.log("⏰ Timeout 10 menit, tandai sisa tab sebagai gagal", "WARN")
                    for i in active:
                        tab_status[i] = "failed"
                        self.set_tab_status(i, 0, "error")
                    break

                for i in active:
                    if self._stop.is_set(): break

                    # Jika handle sudah tidak valid (tab ketutup), skip
                    if i >= len(tab_handles):
                        tab_status[i] = "failed"
                        continue

                    try:
                        driver.switch_to.window(tab_handles[i])
                    except Exception as e:
                        self.log(f"[Tab {i+1}] Handle tidak valid: {e}", "WARN")
                        tab_status[i] = "failed"
                        self.set_tab_status(i, 0, "error")
                        continue

                    # Baca progress
                    try:
                        pct_text = driver.execute_script("""
                            const spans = document.querySelectorAll('span.tabular-nums');
                            for (const s of spans) {
                                const t = s.textContent.trim();
                                if (t.includes('%')) return t;
                            }
                            const ov = document.querySelector('div.flex.justify-center.items-center.gap-2');
                            if (ov) {
                                for (const n of ov.querySelectorAll('span'))
                                    if (n.textContent.includes('%')) return n.textContent.trim();
                            }
                            return '';
                        """)
                        if pct_text:
                            m = re.search(r'(\d+)', pct_text)
                            if m:
                                new_pct = int(m.group(1))
                                if new_pct != tab_progress.get(i, 0):
                                    tab_progress[i] = new_pct
                                    self.set_tab_status(i, new_pct, "waiting")
                                    # Tampilkan summary progress
                                    parts = []
                                    for ti in range(actual_tabs):
                                        s = tab_status.get(ti, "?")
                                        p = tab_progress.get(ti, 0)
                                        if s == "done":    parts.append(f"T{ti+1}:✅")
                                        elif s == "failed": parts.append(f"T{ti+1}:❌")
                                        else:              parts.append(f"T{ti+1}:{p}%")
                                    self.log(f"📊 {' | '.join(parts)}")
                    except: pass

                    # Cek status (done/generating/idle)
                    try:
                        is_generating = driver.execute_script("""
                            const spans = document.querySelectorAll('span');
                            for (const s of spans) {
                                const t = s.textContent;
                                if (t.includes('Menghasilkan') || t.includes('Generating')) return true;
                            }
                            return false;
                        """)
                    except: is_generating = False

                    try:
                        dl_btns = driver.find_elements(By.CSS_SELECTOR,
                            'button[aria-label="Download"], button[aria-label="Unduh"]')
                        has_download = bool(dl_btns)
                    except: has_download = False

                    generation_started = tab_progress.get(i, 0) > 0

                    if (has_download and not is_generating) or \
                       (generation_started and not is_generating and tab_progress.get(i, 0) > 0):
                        # Video selesai, langsung download
                        self.log(f"[Tab {i+1}] ✅ Video selesai! Mengunduh...")
                        self.set_tab_status(i, 100, "downloading")
                        video_path = self.wait_and_download(driver, i, output_dir)
                        if video_path:
                            downloaded_in_cycle.append(video_path)
                            tab_status[i] = "done"
                            self.set_tab_status(i, 100, "success")
                        else:
                            tab_status[i] = "failed"
                            self.set_tab_status(i, 0, "error")
                        # Update timestamp agar tab berikutnya tidak konflik file
                        tab_start_time = time.time()

                time.sleep(3)  # tunggu sebelum ronde berikutnya

            # ── Phase 3: Tutup tab ekstra untuk siklus berikutnya ──
            if cycle < n_cycles - 1 and not self._stop.is_set():
                self.log("[Phase 3] Menutup tab ekstra, siap siklus berikutnya...")
                all_handles = driver.window_handles
                for h in all_handles[1:]:
                    try:
                        driver.switch_to.window(h)
                        driver.close()
                    except: pass
                if driver.window_handles:
                    driver.switch_to.window(driver.window_handles[0])
                time.sleep(2)

            self.log(f"Siklus {cycle+1} selesai. Download: {len(downloaded_in_cycle)} video.")

        if self._stop.is_set():
            self.log("⛔ Dihentikan oleh user.", "WARN")
            for i in range(n_tabs):
                self.set_tab_status(i, 0, "stopped")
        else:
            self.log("🎉 SEMUA SIKLUS SELESAI!")
            if cfg.get("merge_videos", True):
                self.merge_videos_pairs(output_dir, merged_dir)
            self.stat_q.put({"done": True})

        try: driver.quit()
        except: pass
        self.kill_chrome()


# ════════════════════════════════════════════════════════════════════════════
#  MAIN GUI
# ════════════════════════════════════════════════════════════════════════════
class SuperGrokApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🚀 SuperGrok Video Generator")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.state("zoomed")

        self.prompts       = load_prompts_db()
        self.engine        = None
        self.engine_thread = None
        self.log_q         = queue.Queue()
        self.stat_q        = queue.Queue()
        self.tab_rows      = []
        self._running      = False

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
        st.configure("Gen.Horizontal.TProgressbar",     troughcolor=CARD2, background=ACCENT,  thickness=12, borderwidth=0)
        st.configure("Success.Horizontal.TProgressbar", troughcolor=CARD2, background=GREEN,   thickness=12, borderwidth=0)
        st.configure("Error.Horizontal.TProgressbar",   troughcolor=CARD2, background=RED,     thickness=12, borderwidth=0)
        st.configure("Treeview",         background=CARD2, fieldbackground=CARD2, foreground=TEXT, rowheight=22, font=("Segoe UI", 9))
        st.configure("Treeview.Heading", background=CARD,  foreground=ACCENT, font=("Segoe UI", 9, "bold"), relief="flat")
        st.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#FFF")])

    # ── Build UI ──
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=12)
        hdr.pack(fill="x", padx=20)
        tk.Label(hdr, text="🚀 SuperGrok Video Generator", bg=BG, fg=TEXT,
                 font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(hdr, text="  Auto generate video dari grok.com/imagine",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left", pady=4)
        self.cycle_badge = tk.Label(hdr, text="Siklus: –", bg=ACCENT, fg="#FFF",
                                    font=("Segoe UI", 10, "bold"), padx=10, pady=4)
        self.cycle_badge.pack(side="right")
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
        self._build_tab_monitor(left)
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

        # Row 1: Tabs, Cycles, Port
        tk.Label(card, text="Tabs per Siklus:", **lkw).grid(row=1, column=0, sticky="w")
        self.var_tabs = tk.IntVar(value=10)
        ttk.Spinbox(card, from_=1, to=50, textvariable=self.var_tabs, width=6).grid(row=1, column=1, padx=(4, 16), sticky="w")

        tk.Label(card, text="Jumlah Siklus:", **lkw).grid(row=1, column=2, sticky="w")
        self.var_cycles = tk.IntVar(value=3)
        ttk.Spinbox(card, from_=1, to=9999, textvariable=self.var_cycles, width=8).grid(row=1, column=3, padx=(4, 16), sticky="w")

        tk.Label(card, text="Debug Port:", **lkw).grid(row=1, column=4, sticky="w")
        self.var_port = tk.IntVar(value=DEFAULT_PORT)
        ttk.Spinbox(card, from_=1024, to=65535, textvariable=self.var_port, width=7).grid(row=1, column=5, padx=4, sticky="w")

        # Row 2: Chrome Path & User Data
        tk.Label(card, text="Chrome Path:", **lkw).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.var_chrome = tk.StringVar(value=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        ent_chrome = ttk.Entry(card, textvariable=self.var_chrome, width=35)
        ent_chrome.grid(row=2, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(8, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_file(self.var_chrome)).grid(row=2, column=5, padx=(0, 4), pady=(8, 0))

        tk.Label(card, text="User Data Dir:", **lkw).grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.var_ud = tk.StringVar(value=DEFAULT_USER_DATA)
        ttk.Entry(card, textvariable=self.var_ud, width=35).grid(row=3, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_dir(self.var_ud)).grid(row=3, column=5, padx=(0, 4), pady=(4, 0))

        # Row 4: Output, Merged Dir
        tk.Label(card, text="Output Dir:", **lkw).grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.var_outdir = tk.StringVar(value=OUTPUT_DIR)
        ttk.Entry(card, textvariable=self.var_outdir, width=35).grid(row=4, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_dir(self.var_outdir)).grid(row=4, column=5, padx=(0, 4), pady=(4, 0))

        tk.Label(card, text="Merged Dir:", **lkw).grid(row=5, column=0, sticky="w", pady=(4, 0))
        self.var_mergeddir = tk.StringVar(value=MERGED_DIR)
        ttk.Entry(card, textvariable=self.var_mergeddir, width=35).grid(row=5, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_dir(self.var_mergeddir)).grid(row=5, column=5, padx=(0, 4), pady=(4, 0))

        # Row 6: Bahan Folder selector
        tk.Label(card, text="Folder Bahan:", **lkw).grid(row=6, column=0, sticky="w", pady=(4, 0))
        self.var_bahan_folder = tk.StringVar(value="")
        self._bahan_cb = ttk.Combobox(card, textvariable=self.var_bahan_folder, width=20, state="readonly")
        self._bahan_cb.grid(row=6, column=1, columnspan=2, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="🔄", style="Flat.TButton", width=3,
                   command=self._refresh_bahan_list).grid(row=6, column=3, padx=(0, 4), pady=(4, 0))
        self._refresh_bahan_list()

        # Row 7: Checkboxes
        chk_f = tk.Frame(card, bg=CARD)
        chk_f.grid(row=7, column=0, columnspan=6, sticky="w", pady=(8, 0))

        self.var_alternate_img = tk.BooleanVar(value=True)
        chk_alt = ttk.Checkbutton(chk_f, text="Selang-seling Use Image",
                                   variable=self.var_alternate_img, style="TCheckbutton",
                                   command=self._on_alternate_changed)
        chk_alt.pack(side="left", padx=(0, 20))

        self.var_use_img_all = tk.BooleanVar(value=True)
        self._chk_use_all = ttk.Checkbutton(chk_f, text="Semua Tab Pakai Gambar",
                                              variable=self.var_use_img_all, style="TCheckbutton")
        self._chk_use_all.pack(side="left", padx=(0, 20))
        self._on_alternate_changed()

        # Row 8: Merge checkbox
        mrg_f = tk.Frame(card, bg=CARD)
        mrg_f.grid(row=8, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self.var_merge_videos = tk.BooleanVar(value=True)
        ttk.Checkbutton(mrg_f, style="TCheckbutton",
                        text="🎬 Gabungkan 2 Video Menjadi 1 (~20 dtk) setelah semua siklus",
                        variable=self.var_merge_videos).pack(side="left")

        card.columnconfigure(1, weight=1)
        card.columnconfigure(3, weight=1)

    def _refresh_bahan_list(self):
        folders = list_bahan_folders()
        self._bahan_cb["values"] = folders
        if folders and not self.var_bahan_folder.get():
            self.var_bahan_folder.set(folders[0])

    def _on_alternate_changed(self):
        if not hasattr(self, "_chk_use_all"): return
        if self.var_alternate_img.get():
            self._chk_use_all.pack_forget()
        else:
            self._chk_use_all.pack(side="left")

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
        """Collect all prompt texts and save to JSON."""
        ps = [t.get("1.0", "end").strip() for t in self.prompt_texts]
        save_prompts_db(ps)
        self._append_log(f"💾 Prompts tersimpan ({len(ps)} prompt) → supergrok_prompts.json")

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

    # ── Tab Monitor ──
    def _build_tab_monitor(self, parent):
        outer = tk.Frame(parent, bg=CARD, pady=10, padx=14)
        outer.pack(fill="both", expand=True, pady=(0, 8))
        tk.Label(outer, text="🖥  Tab Monitor", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))

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
        self._rebuild_tab_rows(10)

    def _rebuild_tab_rows(self, n):
        for w in self.monitor_frame.winfo_children(): w.destroy()
        self.tab_rows = []
        for i in range(n):
            row = tk.Frame(self.monitor_frame, bg=CARD, pady=3)
            row.pack(fill="x", padx=2)
            tk.Label(row, text=f"Tab {i+1:02d}", bg=CARD, fg=MUTED,
                     font=("Segoe UI", 9, "bold"), width=7).pack(side="left")
            bar = ttk.Progressbar(row, style="Gen.Horizontal.TProgressbar",
                                  orient="horizontal", length=200, maximum=100)
            bar.pack(side="left", padx=(4, 8), fill="x", expand=True)
            pct_lbl  = tk.Label(row, text="0%", bg=CARD, fg=MUTED, font=("Segoe UI", 9), width=5)
            pct_lbl.pack(side="left")
            stat_lbl = tk.Label(row, text="idle", bg=CARD, fg=MUTED,
                                font=("Segoe UI", 9, "bold"), width=12, anchor="w")
            stat_lbl.pack(side="left", padx=(4, 0))
            self.tab_rows.append({"bar": bar, "pct": pct_lbl, "status": stat_lbl})

    # ── Output Panel ──
    def _build_output_panel(self, parent):
        card = tk.Frame(parent, bg=CARD2, pady=10, padx=14)
        card.pack(fill="x", pady=(0, 8))

        hdr = tk.Frame(card, bg=CARD2)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📁  Output Terbaru (download-grok)", bg=CARD2, fg=ACCENT,
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
        elif "[ERROR]" in msg or "❌" in msg: tag = "ERROR"
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
        prompts  = self._collect_prompts()
        n_tabs   = self.var_tabs.get()
        n_cycles = self.var_cycles.get()

        cfg = {
            "prompts":         prompts,
            "n_tabs":          n_tabs,
            "n_cycles":        n_cycles,
            "debug_port":      self.var_port.get(),
            "chrome_path":     self.var_chrome.get(),
            "user_data_dir":   self.var_ud.get(),
            "output_dir":      self.var_outdir.get(),
            "merged_dir":      self.var_mergeddir.get(),
            "merge_videos":    self.var_merge_videos.get(),
            "bahan_folder":    self.var_bahan_folder.get(),
            "alternate_image": self.var_alternate_img.get(),
            "use_image_all":   self.var_use_img_all.get(),
        }

        self._rebuild_tab_rows(n_tabs)
        self.engine        = AutomationEngine(cfg, self.log_q, self.stat_q)
        self.engine_thread = threading.Thread(target=self.engine.run, daemon=True)
        self.engine_thread.start()
        self._running = True
        self.btn_generate.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.status_lbl.configure(text="⬤  Running", fg=GREEN)
        self._append_log("▶ SuperGrok Automation dimulai...")

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
        try:
            while True:
                msg = self.log_q.get_nowait()
                self._append_log(msg)
        except queue.Empty: pass

        try:
            while True:
                ev = self.stat_q.get_nowait()
                if "tab" in ev:
                    i      = ev["tab"]
                    pct    = ev.get("pct", 0)
                    status = ev.get("status", "idle")
                    if i < len(self.tab_rows):
                        row   = self.tab_rows[i]
                        color = STATUS_COLORS.get(status, MUTED)
                        row["bar"]["value"] = pct
                        if status == "success":
                            row["bar"].configure(style="Success.Horizontal.TProgressbar")
                        elif status == "error":
                            row["bar"].configure(style="Error.Horizontal.TProgressbar")
                        else:
                            row["bar"].configure(style="Gen.Horizontal.TProgressbar")
                        row["pct"].configure(text=f"{pct}%", fg=color)
                        row["status"].configure(text=status, fg=color)
                if "cycle" in ev:
                    self.cycle_badge.configure(text=f"Siklus: {ev['cycle']}")
                if ev.get("done"):
                    self._set_idle()
                    self._refresh_output_folder()
                    merged = ev.get("merged_dir", "")
                    info   = (f"Semua siklus selesai!\nVideo asli: {self.var_outdir.get()}\n"
                              f"Video gabungan: {merged}") if merged else \
                             f"Semua siklus selesai!\nCek: {self.var_outdir.get()}"
                    messagebox.showinfo("🎉 Selesai!", info)
                if "merged_dir" in ev and not ev.get("done"):
                    self._append_log(f"🎬 Merge tersimpan di: {ev['merged_dir']}")
        except queue.Empty: pass

        if self._running:
            if not hasattr(self, "_last_ref"): self._last_ref = time.time()
            if time.time() - self._last_ref > 15:
                self._refresh_output_folder()
                self._last_ref = time.time()

        if self._running and self.engine_thread and not self.engine_thread.is_alive():
            self._set_idle()
            self._append_log("Thread selesai.")

        self.after(300, self._poll_queues)


# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = SuperGrokApp()
    app.mainloop()
