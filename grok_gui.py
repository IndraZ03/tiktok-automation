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
from datetime import datetime

# ── Try imports that depend on selenium ──────────────────────────────────────
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

# ── Try pydrive2 (Google Drive upload) ───────────────────────────────────────
try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    GDRIVE_OK = True
except ImportError:
    GDRIVE_OK = False

# ── Paths ────────────────────────────────────────────────────────────────────
APP_DIR              = r"C:\tiktok_automation"
GDRIVE_SETTINGS_YAML = os.path.join(APP_DIR, "gdrive_settings.yaml")
GDRIVE_CREDS_FILE    = os.path.join(APP_DIR, "gdrive_credentials.json")
CLIENT_SECRETS_FILE  = os.path.join(APP_DIR, "client_secrets.json")


def extract_gdrive_folder_id(url_or_id: str) -> str:
    """Parse folder ID from a Google Drive URL or return the string as-is."""
    # e.g. https://drive.google.com/drive/folders/ABC123?usp=sharing
    m = re.search(r'/folders/([a-zA-Z0-9_-]+)', url_or_id)
    if m:
        return m.group(1)
    # Already an ID
    return url_or_id.strip()

# ════════════════════════════════════════════════════════════════════════════
#  DEFAULT PROMPTS
# ════════════════════════════════════════════════════════════════════════════
DEFAULT_PROMPT_1 = '''INSTRUKSI UMUM – GAYA HIJAB HOKAGE "UWAK" 🎬 Format & Teknis - Durasi: 8 detik per video. - Resolusi: Render 8K ultra-realistis. - Produk yang digunakan: Tab Pro S12 (11,6 inci, visual splash warna-warni, ikon 5G, RAM 16GB, ROM 1024GB). - Desain: ramping, mengkilap, bezel tipis. - Aksesoris: keyboard wireless terpisah, stylus metalik, earphone & charger (unboxing opsional). 🎭 Karakter - Wanita Indonesia cantik dengan hijab modern. - Pakaian: Jubah Hokage (putih-oranye), ikat kepala dengan tulisan "uwak". - Gaya: percaya diri, ekspresif, aura ninja yang elegan. 🎤 Sulih Suara (VO) - Bahasa: 100% Bahasa Indonesia. - Singkat (maksimal 6-8 kata, selesai ≤2 detik). - Berenergi tinggi, ekspresif, seperti pembawa acara TikTok Live. 🎥 Kamera & Visual - Sudut pandang: track-in/out, orbit, selfie POV, sudut rendah, sinematik dari atas. - Transisi: jepret, cambuk, zoom, glitch elegan. - Efek tematik: api, debu beterbangan, kilauan emas. - Latar belakang: meja kayu kenari, sorotan emas, efek api sinematik. - Warna dominan: hitam, putih gading, kilauan emas + aksen api merah-oranye. 🔊 Audio & Efek - Musik: beat elegan modern + suasana ninja epik. - Efek: desingan api, percikan api, kilauan emas, glitch lembut. - VO: suara manusia asli, cepat, tegas, kuat.

VIDEO 3 🎥 URUTAN VISUAL (0,0–2,0 detik) Bidikan sudut rendah: karakter Hokage berhijab berdiri dengan percaya diri dengan Tab Pro S12 bersinar di tangan. (2,0–4,0 detik) Partikel api memperlihatkan desain mengkilap yang sangat tipis. (4,0–6,0 detik) Tulisan stylus jarak dekat di layar → guratan kilau keemasan yang halus. (6,0–8,0 detik) Tembakan orbit → tablet melayang di atas meja kenari dengan energi ninja yang luar biasa. 🎤 VO gaya Shopee viral (Bahasa Indonesia) : "Tablet android kenceng tapi cuma sejutaan? Layar OLED, Ram 16 Giga, ROM 1024 Giga! Klik keranjang sekarang sebelum harga balik 3 juta!"

 Jangan ada teks layar. Jangan ada overlay apapun. Jangan ada lip sync'''

DEFAULT_PROMPT_2 = '''Instruksi Umum

Bahasa: 100% Bahasa Indonesia untuk VO 

Detail Produk Konsisten:

Tablet Android

Layar 11,6 inci, resolusi 2560×1600

Layar ON: splash screen besar "ANDROID + ikon 5G WiFi, 16GB RAM, 1024GB ROM

Desain: tipis, sudut membulat, bezel tipis, bodi logam + plastik glossy

Aksesori: keyboard wireless tipis hitam + stylus metalik ramping


Visual Style: nuansa gaming neon glitch (merah–biru), penuh energi, banyak efek cahaya & transisi snap/zoom/shake.

Kamera: handheld shaky, zoom-in ke layar game, orbit cepat.

VO Style: suara natural manusia, cepat, agresif, seperti caster e-sports → bikin penonton terbakar semangat.

Musik: beat trap/EDM gaming, bass kencang, SFX glitch & power-up.

🎮 STYLE 2 – GAMING BEAST

Video 1 (0–8 detik) – Hook

Scene 1 (0–3s):
Angle: POV close-up tangan pegang tablet, game FPS terbuka.
VO (enerjik, cepat, nada hype) "Gue kira boongan! Ternyata beneran dapet layar OLED! Harga sejutaan!"

Scene 2 (3–6s):
Angle: Insert layar, FPS lancar tanpa lag.
VO (tegas, sedikit menantang) "plus keyboard dan mouse gratis! Batere gede, Performa kenceng!" 

Scene 3 (6–8s):
Angle: Camera tilt-up, lampu RGB di belakang.

VO (fun, hype) "Buruan! Sebelum harganya balik 3 juta!"'''

# ════════════════════════════════════════════════════════════════════════════
#  COLOUR PALETTE  (modern, bright, dynamic)
# ════════════════════════════════════════════════════════════════════════════
BG        = "#0F1117"   # very dark navy
CARD      = "#1A1D27"   # dark card
CARD2     = "#22263A"   # lighter card
ACCENT    = "#6C63FF"   # violet
ACCENT2   = "#FF6584"   # coral pink
GREEN     = "#00E5A0"   # neon green
YELLOW    = "#FFD166"   # warm yellow
RED       = "#FF4757"   # red
TEXT      = "#E8EAF6"   # near-white
MUTED     = "#8892B0"   # muted blue-grey
BORDER    = "#2E3250"   # subtle border

STATUS_COLORS = {
    "idle":        MUTED,
    "generating":  YELLOW,
    "waiting":     ACCENT,
    "downloading": GREEN,
    "success":     GREEN,
    "error":       RED,
    "stopped":     RED,
    "login":       YELLOW,
}

# ════════════════════════════════════════════════════════════════════════════
#  AUTOMATION ENGINE  (runs in background thread)
# ════════════════════════════════════════════════════════════════════════════
class AutomationEngine:
    def __init__(self, config: dict, log_q: queue.Queue, status_q: queue.Queue):
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

    # ── Helpers ─────────────────────────────────────────────────────────────
    def get_next_filename(self):
        files   = glob.glob(os.path.join(self.cfg["output_dir"], "*.mp4"))
        max_num = 0
        pat     = re.compile(r'(\d+)\.mp4')
        for f in files:
            m = pat.fullmatch(os.path.basename(f))
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{max_num + 1}.mp4"

    # ── Google Drive ─────────────────────────────────────────────────────────
    def _get_gdrive(self):
        """Return an authenticated GoogleDrive instance (cached)."""
        if not GDRIVE_OK:
            self.log("pydrive2 tidak terinstall! pip install pydrive2", "ERROR")
            return None
        if hasattr(self, "_gdrive_obj") and self._gdrive_obj:
            return self._gdrive_obj
        try:
            gauth = GoogleAuth(settings_file=GDRIVE_SETTINGS_YAML)
            # Load saved credentials; if missing/expired refresh or re-auth
            gauth.LoadCredentialsFile(GDRIVE_CREDS_FILE)
            if gauth.credentials is None:
                self.log("GDrive: Credentials belum ada – jalankan Authenticate dari GUI dulu", "ERROR")
                return None
            if gauth.access_token_expired:
                gauth.Refresh()
                gauth.SaveCredentialsFile(GDRIVE_CREDS_FILE)
            drive = GoogleDrive(gauth)
            self._gdrive_obj = drive
            return drive
        except Exception as e:
            self.log(f"GDrive auth error: {e}", "ERROR")
            return None

    def upload_to_gdrive(self, local_path: str, filename: str) -> bool:
        """Upload a local file to the configured GDrive folder."""
        drive = self._get_gdrive()
        if not drive:
            return False
        folder_id = self.cfg.get("gdrive_folder_id", "")
        if not folder_id:
            self.log("GDrive folder ID kosong – skip upload", "WARN")
            return False
        try:
            meta = {'title': filename}
            if folder_id:
                meta['parents'] = [{'id': folder_id}]
            f = drive.CreateFile(meta)
            f.SetContentFile(local_path)
            f.Upload()
            self.log(f"☁ GDrive upload ✅ {filename}")
            return True
        except Exception as e:
            self.log(f"GDrive upload gagal: {e}", "ERROR")
            return False

    def get_random_image(self):
        d = self.cfg.get("tab_bahan_dir", "")
        if not d or not os.path.exists(d):
            return None
        files = [f for f in os.listdir(d) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        return os.path.join(d, random.choice(files)) if files else None

    # ── Chrome ──────────────────────────────────────────────────────────────
    def open_chrome(self):
        self.log("Membuka Chrome dalam mode debug...")
        chrome  = self.cfg.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        port    = self.cfg.get("debug_port", 9222)
        ud      = self.cfg.get("user_data_dir", r"C:\tiktok_automation\user_data\1")
        headless= self.cfg.get("headless", False)

        cmd = [chrome, f"--remote-debugging-port={port}", f"--user-data-dir={ud}"]
        if headless:
            cmd += ["--headless=new", "--disable-gpu", "--no-sandbox"]
        subprocess.Popen(cmd)
        time.sleep(3)

    def kill_chrome(self):
        """Kill Chrome process that is listening on the configured debug port."""
        port = self.cfg.get("debug_port", 9222)
        self.log(f"Mematikan Chrome pada port {port}...")
        try:
            # Find PIDs using the debug port via netstat
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=10
            )
            pids = set()
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pids.add(parts[-1])
            if pids:
                for pid in pids:
                    subprocess.run(["taskkill", "/PID", pid, "/F"],
                                   capture_output=True, timeout=5)
                    self.log(f"Chrome PID {pid} dimatikan ✓")
            else:
                # Fallback: kill by image name (only if no other approach worked)
                result2 = subprocess.run(
                    ["taskkill", "/IM", "chrome.exe", "/F"],
                    capture_output=True, text=True, timeout=5
                )
                self.log("Chrome dimatikan (fallback taskkill) ✓")
        except Exception as e:
            self.log(f"Gagal mematikan Chrome: {e}", "WARN")

    def connect_selenium(self):
        port = self.cfg.get("debug_port", 9222)
        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
        try:
            svc    = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=svc, options=opts)
            driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": self.cfg["output_dir"]
            })
            self.log("Selenium terhubung ke Chrome ✓")
            return driver
        except Exception as e:
            self.log(f"Gagal connect Selenium: {e}", "ERROR")
            return None

    # ── Login if needed ──────────────────────────────────────────────────────
    def do_login(self, driver) -> bool:
        """
        Performs login on the current tab.
        Returns True if login was performed (and presumably succeeded),
        False if page was not a login page.
        """
        if "login" not in driver.current_url:
            return False
        self.log("Halaman login terdeteksi, melakukan login otomatis...")
        wait = WebDriverWait(driver, 15)
        try:
            e = wait.until(EC.element_to_be_clickable((By.ID, "data.email")))
            e.clear(); e.send_keys("oktavandigamer2@gmail.com")
            p = wait.until(EC.element_to_be_clickable((By.ID, "data.password")))
            p.clear(); p.send_keys("oktavandi111111")
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))).click()
            self.log("Login diklik, menunggu redirect...")
            # Wait until URL no longer contains 'login'
            deadline = time.time() + 15
            while time.time() < deadline:
                if "login" not in driver.current_url:
                    self.log("Login berhasil ✓")
                    return True
                time.sleep(0.5)
            self.log("Login selesai (timeout menunggu redirect)", "WARN")
            return True
        except Exception as e:
            self.log(f"Gagal login: {e}", "ERROR")
            return False

    # ── Tab Setup ────────────────────────────────────────────────────────────
    def setup_tabs(self, driver, n_tabs):
        """Open n_tabs tabs to the target URL.
        For each new tab: navigate, check for login, login if needed BEFORE moving on.
        """
        self.log(f"Menyiapkan {n_tabs} tab...")
        url = self.cfg.get("target_url", "https://vidabot.markasai.com/generate-grok")

        while len(driver.window_handles) < n_tabs:
            driver.switch_to.new_window('tab')
            driver.get(url)
            time.sleep(1.5)
            # ── Login check: finish login BEFORE opening next tab ──────────
            if "login" in driver.current_url:
                self.set_tab_status(len(driver.window_handles) - 1, 0, "login")
                logged_in = self.do_login(driver)
                if logged_in:
                    # Navigate to target after login
                    if url not in driver.current_url:
                        driver.get(url)
                        time.sleep(1)
            if self._stop.is_set():
                break

        # Ensure existing tabs are on the right page
        for idx, h in enumerate(driver.window_handles[:n_tabs]):
            driver.switch_to.window(h)
            if url not in driver.current_url:
                driver.get(url)
                time.sleep(1)
                if "login" in driver.current_url:
                    self.set_tab_status(idx, 0, "login")
                    self.do_login(driver)
                    if url not in driver.current_url:
                        driver.get(url)
                        time.sleep(1)

        self.log(f"Total tab: {len(driver.window_handles)}")

    # ── Generate Task ────────────────────────────────────────────────────────
    def do_generate(self, driver, tab_idx, prompt, use_image):
        self.set_tab_status(tab_idx, 0, "generating")
        # Login guard
        if "login" in driver.current_url:
            self.set_tab_status(tab_idx, 0, "login")
            self.do_login(driver)
        wait = WebDriverWait(driver, 10)

        # Fill prompt
        try:
            pa = wait.until(EC.element_to_be_clickable((By.ID, "promptInput")))
            pa.clear()
            driver.execute_script("arguments[0].value = arguments[1];", pa, prompt)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pa)
        except Exception as e:
            self.log(f"Tab {tab_idx+1}: Gagal isi prompt – {e}", "WARN")
            return

        # Upload image
        if use_image:
            img = self.get_random_image()
            if img:
                try:
                    driver.find_element(By.ID, "imageInput").send_keys(img)
                    time.sleep(1)
                except Exception as e:
                    self.log(f"Tab {tab_idx+1}: Gagal upload gambar – {e}", "WARN")

        # Click Generate
        try:
            btn = wait.until(EC.element_to_be_clickable((By.ID, "btnGenerate")))
            btn.click()
            self.log(f"Tab {tab_idx+1}: Generate diklik ✓")
        except Exception as e:
            self.log(f"Tab {tab_idx+1}: Gagal klik Generate – {e}", "ERROR")

    # ── Wait & Download ──────────────────────────────────────────────────────
    def wait_and_download(self, driver, tab_idx) -> bool:
        self.set_tab_status(tab_idx, 0, "waiting")
        start   = time.time()
        timeout = 300  # 5 min

        while time.time() - start < timeout:
            if self._stop.is_set():
                return False

            # Progress %
            try:
                p = driver.find_element(By.ID, "progressPercent").text
                try:
                    pct = int(re.search(r'\d+', p).group())
                except:
                    pct = 0
                self.set_tab_status(tab_idx, pct, "waiting")
            except:
                pass

            # Success?
            try:
                if "Video ready" in driver.find_element(By.ID, "progressLabel").text:
                    break
            except: pass
            try:
                if driver.find_element(By.ID, "btnDownload").is_displayed():
                    break
            except: pass

            # Error?
            try:
                logs = driver.find_element(By.ID, "debugLog").get_attribute("innerText")
                if any(x in logs for x in ["Switching worker", "7 failed", "12 failed"]):
                    self.log(f"Tab {tab_idx+1}: Error terdeteksi di log", "WARN")
                    self.set_tab_status(tab_idx, 0, "error")
                    return False
            except: pass

            time.sleep(1)
        else:
            self.log(f"Tab {tab_idx+1}: Timeout 5 menit", "WARN")
            self.set_tab_status(tab_idx, 0, "error")
            return False

        # --- Download ---
        self.set_tab_status(tab_idx, 100, "downloading")
        wait = WebDriverWait(driver, 30)
        try:
            dl_btn  = wait.until(EC.element_to_be_clickable((By.ID, "btnDownload")))
            dl_url  = dl_btn.get_attribute("href")

            filename  = self.get_next_filename()
            save_path = os.path.join(self.cfg["output_dir"], filename)

            s = requests.Session()
            for c in driver.get_cookies():
                s.cookies.set(c['name'], c['value'])
            ua = driver.execute_script("return navigator.userAgent;")
            s.headers.update({"User-Agent": ua, "Referer": "https://vidabot.markasai.com/"})

            downloaded = False
            try:
                r = s.get(dl_url, stream=True, timeout=10)
                if 'video' in r.headers.get("Content-Type", ""):
                    with open(save_path, 'wb') as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    downloaded = True
                    self.log(f"Tab {tab_idx+1}: ✅ Saved {filename}")
            except Exception as e:
                self.log(f"Tab {tab_idx+1}: Direct download fail – {e}", "WARN")

            # Fallback
            if not downloaded:
                self.log(f"Tab {tab_idx+1}: Fallback extraction...")
                main_tab = driver.current_window_handle
                driver.execute_script(f"window.open('{dl_url}', '_blank');")
                all_h   = driver.window_handles
                new_tab = [h for h in all_h if h != main_tab][-1]
                driver.switch_to.window(new_tab)
                try:
                    vid = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.TAG_NAME, "video")))
                    src = vid.get_attribute("src") or \
                          vid.find_element(By.TAG_NAME, "source").get_attribute("src")
                    if src:
                        r = s.get(src, stream=True)
                        with open(save_path, 'wb') as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                        self.log(f"Tab {tab_idx+1}: ✅ Saved {filename} (fallback)")
                except Exception as e:
                    self.log(f"Tab {tab_idx+1}: Fallback fail – {e}", "ERROR")
                driver.close()
                driver.switch_to.window(main_tab)

            self.set_tab_status(tab_idx, 100, "success")

            # ── Upload to Google Drive if configured ──────────────────────
            if self.cfg.get("save_mode") == "gdrive":
                self.log(f"Tab {tab_idx+1}: Mengunggah ke Google Drive...")
                self.upload_to_gdrive(save_path, filename)

        except Exception as e:
            self.log(f"Tab {tab_idx+1}: Download error – {e}", "ERROR")
            self.set_tab_status(tab_idx, 0, "error")
            return False

        # Regenerate
        try:
            xpath = "//button[contains(text(), 'Generate Again') or contains(@onclick, 'generateVideo')]"
            rb    = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].scrollIntoView(true);", rb)
            time.sleep(0.4)
            try:
                rb.click()
            except:
                driver.execute_script("arguments[0].click();", rb)
            self.log(f"Tab {tab_idx+1}: Regenerate diklik ✓")
        except Exception as e:
            self.log(f"Tab {tab_idx+1}: Tombol regenerate tidak ditemukan – {e}", "WARN")

        return True

    # ── Main Run ─────────────────────────────────────────────────────────────
    def run(self):
        if not SELENIUM_OK:
            self.log("Selenium / requests tidak terinstall!", "ERROR")
            return

        cfg     = self.cfg
        n_tabs  = cfg["n_tabs"]
        n_cycle = cfg["n_cycles"]
        prompts = cfg["prompts"]          # list of str
        url     = cfg.get("target_url", "https://vidabot.markasai.com/generate-grok")
        alternate_img = cfg.get("alternate_image", True)
        use_img_all   = cfg.get("use_image_all", False)

        os.makedirs(cfg["output_dir"], exist_ok=True)

        # Build tab_config
        tab_config = []
        for i in range(n_tabs):
            p = prompts[i % len(prompts)]
            if alternate_img:
                use_img = (i % 2 == 0)   # selang-seling
            else:
                use_img = use_img_all     # semua sama (sesuai checkbox "Semua pakai gambar")
            tab_config.append((p, use_img))

        # Open Chrome
        self.open_chrome()
        if self._stop.is_set():
            return

        driver = self.connect_selenium()
        if not driver:
            return

        self.driver = driver

        # Setup tabs (with login guard)
        self.setup_tabs(driver, n_tabs)
        if self._stop.is_set():
            driver.quit()
            return

        handles      = driver.window_handles
        task_handles = list(handles[:n_tabs])

        # ─ PHASE 1: Initial generation ─
        self.log("=== MEMULAI INITIAL GENERATION ===")
        for i in range(n_tabs):
            if self._stop.is_set():
                break
            if i >= len(driver.window_handles):
                break
            driver.switch_to.window(driver.window_handles[i])
            self.log(f"--- Tab {i+1}: Initial Generate ---")
            self.do_generate(driver, i, tab_config[i][0], tab_config[i][1])
            time.sleep(2)

        # ─ PHASE 2: Cycle loop ─
        for cycle in range(n_cycle):
            if self._stop.is_set():
                break

            t0 = time.time()
            self.log(f"\n=== SIKLUS KE-{cycle+1}/{n_cycle} ===")
            self.stat_q.put({"cycle": cycle + 1})

            # Update task_handles list on first cycle
            if cycle == 0:
                cur = driver.window_handles
                for i in range(n_tabs):
                    task_handles[i] = cur[i] if i < len(cur) else None

            for i in range(n_tabs):
                if self._stop.is_set():
                    break

                handle = task_handles[i]
                if not handle:
                    self.log(f"Tab {i+1}: Closed/Failed – skip")
                    continue

                try:
                    driver.switch_to.window(handle)
                except:
                    self.log(f"Tab {i+1}: Tidak ditemukan", "WARN")
                    task_handles[i] = None
                    self.set_tab_status(i, 0, "error")
                    continue

                ok = self.wait_and_download(driver, i)
                if not ok:
                    driver.close()
                    task_handles[i] = None

            # Respawn failed tabs
            self.log("--- Memeriksa tab yang perlu di-restart ---")
            for i in range(n_tabs):
                if self._stop.is_set():
                    break
                if task_handles[i] is None:
                    self.log(f"Respawning Tab {i+1}...")
                    driver.switch_to.new_window('tab')
                    nh = driver.current_window_handle
                    task_handles[i] = nh
                    driver.get(url)
                    time.sleep(2)
                    # Login guard on respawn
                    if "login" in driver.current_url:
                        self.set_tab_status(i, 0, "login")
                        self.do_login(driver)
                        if url not in driver.current_url:
                            driver.get(url)
                            time.sleep(1)
                    self.do_generate(driver, i, tab_config[i][0], tab_config[i][1])
                    time.sleep(1)

            elapsed = time.time() - t0
            self.log(f"Siklus {cycle+1} selesai – {int(elapsed//60)}m {int(elapsed%60)}s")

        if self._stop.is_set():
            self.log("⛔ Dihentikan oleh user.", "WARN")
            for i in range(n_tabs):
                self.set_tab_status(i, 0, "stopped")
        else:
            self.log("🎉 SEMUA SIKLUS SELESAI!")
            # ── Merge videos if enabled ───────────────────────────────────
            if cfg.get("merge_videos", True):
                self.merge_videos_pairs()
            self.stat_q.put({"done": True})

        # ── Kill Chrome after all cycles done or stopped ─────────────────────
        try:
            driver.quit()
        except Exception:
            pass
        self.kill_chrome()

    # ── Merge Videos ──────────────────────────────────────────────────────────
    def merge_videos_pairs(self):
        """Gabungkan setiap pasangan 2 video menjadi 1 video ~20 detik menggunakan FFmpeg."""
        output_dir  = self.cfg["output_dir"]
        merged_dir  = self.cfg.get("merged_dir",
                                   os.path.join(output_dir, "..", "Output_Merged"))
        merged_dir  = os.path.normpath(merged_dir)
        os.makedirs(merged_dir, exist_ok=True)

        # Kumpulkan semua file .mp4 di output_dir, urutkan berdasarkan nomor
        def _sort_key(f):
            m = re.search(r'(\d+)', os.path.basename(f))
            return int(m.group(1)) if m else 0

        all_files = sorted(
            glob.glob(os.path.join(output_dir, "*.mp4")),
            key=_sort_key
        )

        if len(all_files) < 2:
            self.log("Merge: kurang dari 2 video di output dir, skip.", "WARN")
            return

        self.log(f"🎬 Mulai merge {len(all_files)} video menjadi pasangan (2→1)...")

        pairs = [(all_files[i], all_files[i + 1])
                 for i in range(0, len(all_files) - 1, 2)]

        # Cari nomor output merged selanjutnya
        existing_merged = glob.glob(os.path.join(merged_dir, "merged_*.mp4"))
        next_num = len(existing_merged) + 1

        for idx, (vid1, vid2) in enumerate(pairs):
            if self._stop.is_set():
                break
            out_name = f"merged_{next_num + idx:04d}.mp4"
            out_path = os.path.join(merged_dir, out_name)

            # Buat file daftar (concat demuxer)
            list_file = os.path.join(merged_dir, f"_list_{idx}.txt")
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
                self.log(
                    f"  Merge [{idx+1}/{len(pairs)}]: "
                    f"{os.path.basename(vid1)} + {os.path.basename(vid2)} → {out_name}"
                )
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0:
                    self.log(f"  ✅  {out_name} berhasil dibuat")
                else:
                    self.log(f"  ❌ Gagal merge: {result.stderr[-300:]}", "ERROR")
            except FileNotFoundError:
                self.log("  ❌ FFmpeg tidak ditemukan! Pastikan ffmpeg ada di PATH.", "ERROR")
                break
            except Exception as e:
                self.log(f"  ❌ Error merge pasangan {idx+1}: {e}", "ERROR")
            finally:
                if os.path.exists(list_file):
                    try:
                        os.remove(list_file)
                    except Exception:
                        pass

        self.log(f"🎬 Merge selesai! Hasil tersimpan di: {merged_dir}")
        self.stat_q.put({"merged_dir": merged_dir})


# ════════════════════════════════════════════════════════════════════════════
#  MAIN GUI
# ════════════════════════════════════════════════════════════════════════════
class GrokApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⚡ Grok Video Automation")
        self.configure(bg=BG)
        self.resizable(True, True)

        # ── FULLSCREEN di awal ───────────────────────────────────────────────
        self.state("zoomed")          # Windows maximize (full screen tanpa taskbar)
        # Jika ingin benar-benar fullscreen (tanpa taskbar), ganti dengan:
        # self.attributes("-fullscreen", True)

        # State
        self.prompts      = [DEFAULT_PROMPT_1, DEFAULT_PROMPT_2]
        self.engine       = None
        self.engine_thread= None
        self.log_q        = queue.Queue()
        self.stat_q       = queue.Queue()
        self.tab_rows     = []   # list of dicts {label, bar, status_lbl, pct_lbl}
        self._running     = False

        self._apply_style()
        self._build_ui()
        self._refresh_output_folder()
        self.after(200, self._poll_queues)

    # ── ttk Style ────────────────────────────────────────────────────────────
    def _apply_style(self):
        st = ttk.Style(self)
        st.theme_use("clam")

        st.configure("TFrame",       background=BG)
        st.configure("Card.TFrame",  background=CARD)
        st.configure("Card2.TFrame", background=CARD2)

        st.configure("TLabel",       background=BG,   foreground=TEXT,   font=("Segoe UI", 10))
        st.configure("Card.TLabel",  background=CARD, foreground=TEXT,   font=("Segoe UI", 10))
        st.configure("Card2.TLabel", background=CARD2,foreground=TEXT,   font=("Segoe UI", 10))
        st.configure("Title.TLabel", background=BG,   foreground=TEXT,   font=("Segoe UI", 20, "bold"))
        st.configure("Sub.TLabel",   background=BG,   foreground=MUTED,  font=("Segoe UI", 10))
        st.configure("Head.TLabel",  background=CARD, foreground=ACCENT, font=("Segoe UI", 11, "bold"))
        st.configure("Head2.TLabel", background=CARD2,foreground=ACCENT, font=("Segoe UI", 11, "bold"))

        st.configure("Accent.TButton",
                     background=ACCENT, foreground="#FFFFFF",
                     font=("Segoe UI", 11, "bold"),
                     borderwidth=0, relief="flat", padding=(16, 8))
        st.map("Accent.TButton",
               background=[("active", "#8B83FF"), ("disabled", CARD2)],
               foreground=[("disabled", MUTED)])

        st.configure("Stop.TButton",
                     background=RED, foreground="#FFFFFF",
                     font=("Segoe UI", 11, "bold"),
                     borderwidth=0, relief="flat", padding=(16, 8))
        st.map("Stop.TButton", background=[("active", "#FF6B6B")])

        st.configure("Flat.TButton",
                     background=CARD2, foreground=TEXT,
                     font=("Segoe UI", 10),
                     borderwidth=0, relief="flat", padding=(10, 6))
        st.map("Flat.TButton", background=[("active", BORDER)])

        st.configure("TNotebook",       background=BG,    borderwidth=0)
        st.configure("TNotebook.Tab",   background=CARD2, foreground=MUTED,
                     padding=(14, 6), font=("Segoe UI", 10))
        st.map("TNotebook.Tab",
               background=[("selected", CARD), ("active", BORDER)],
               foreground=[("selected", ACCENT)])

        st.configure("TEntry",  fieldbackground=CARD2, background=CARD2,
                     foreground=TEXT, insertcolor=TEXT, borderwidth=0,
                     font=("Segoe UI", 10))

        st.configure("TSpinbox", fieldbackground=CARD2, background=CARD2,
                     foreground=TEXT, insertcolor=TEXT, borderwidth=0,
                     font=("Segoe UI", 10))

        st.configure("TCheckbutton", background=CARD, foreground=TEXT,
                     font=("Segoe UI", 10))
        st.map("TCheckbutton",
               background=[("active", CARD)],
               foreground=[("active", ACCENT)])

        # Progress bar
        st.configure("Gen.Horizontal.TProgressbar",
                     troughcolor=CARD2, background=ACCENT,
                     thickness=12, borderwidth=0)
        st.configure("Success.Horizontal.TProgressbar",
                     troughcolor=CARD2, background=GREEN,
                     thickness=12, borderwidth=0)
        st.configure("Error.Horizontal.TProgressbar",
                     troughcolor=CARD2, background=RED,
                     thickness=12, borderwidth=0)

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──
        hdr = tk.Frame(self, bg=BG, pady=12)
        hdr.pack(fill="x", padx=20)

        tk.Label(hdr, text="⚡ Grok Video Automation",
                 bg=BG, fg=TEXT, font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(hdr, text="  Automated multi-tab video generation",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left", pady=4)

        self.cycle_badge = tk.Label(hdr, text="Siklus: –",
                                    bg=ACCENT, fg="#FFF",
                                    font=("Segoe UI", 10, "bold"),
                                    padx=10, pady=4, relief="flat")
        self.cycle_badge.pack(side="right")

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x", padx=20)

        # ── Action bar – packed FIRST so expand=True cannot push it off-screen ──
        bar = tk.Frame(self, bg=CARD, pady=10)
        bar.pack(side="bottom", fill="x", padx=12, pady=(0, 8))

        self.btn_generate = ttk.Button(bar, text="▶  Mulai Generate",
                                       style="Accent.TButton",
                                       command=self._on_generate)
        self.btn_generate.pack(side="left", padx=(16, 8))

        self.btn_stop = ttk.Button(bar, text="⏹  Stop",
                                   style="Stop.TButton",
                                   command=self._on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)

        self.status_lbl = tk.Label(bar, text="⬤  Idle", bg=CARD,
                                   fg=MUTED, font=("Segoe UI", 11, "bold"))
        self.status_lbl.pack(side="left", padx=16)

        # separator above bar
        tk.Frame(self, bg=BORDER, height=1).pack(side="bottom", fill="x", padx=12)

        # ── Main container (left | right) – packed AFTER bar so it fills the rest ──
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)

        left  = tk.Frame(main, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        # ══ LEFT ══
        self._build_config_panel(left)
        self._build_tab_monitor(left)

        # ══ RIGHT ══
        self._build_prompt_panel(right)
        self._build_output_panel(right)
        self._build_log_panel(right)

    # ── Config Panel ──────────────────────────────────────────────────────────
    def _build_config_panel(self, parent):
        card = tk.Frame(parent, bg=CARD, bd=0, pady=10, padx=14)
        card.pack(fill="x", pady=(0, 8))

        tk.Label(card, text="⚙  Konfigurasi", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=6,
                                                      sticky="w", pady=(0, 8))

        lbl_kw = dict(bg=CARD, fg=MUTED, font=("Segoe UI", 9))
        ent_kw = dict(width=12)

        # Row 1
        tk.Label(card, text="Tabs per Siklus:", **lbl_kw).grid(row=1, column=0, sticky="w")
        self.var_tabs = tk.IntVar(value=10)
        sb_tabs = ttk.Spinbox(card, from_=1, to=50, textvariable=self.var_tabs, width=6)
        sb_tabs.grid(row=1, column=1, padx=(4, 16), sticky="w")

        tk.Label(card, text="Jumlah Siklus:", **lbl_kw).grid(row=1, column=2, sticky="w")
        self.var_cycles = tk.IntVar(value=3)
        sb_cyc = ttk.Spinbox(card, from_=1, to=9999, textvariable=self.var_cycles, width=8)
        sb_cyc.grid(row=1, column=3, padx=(4, 16), sticky="w")

        tk.Label(card, text="Debug Port:", **lbl_kw).grid(row=1, column=4, sticky="w")
        self.var_port = tk.IntVar(value=9222)
        sb_port = ttk.Spinbox(card, from_=1024, to=65535, textvariable=self.var_port, width=7)
        sb_port.grid(row=1, column=5, padx=4, sticky="w")

        # Row 2 – Checkboxes
        chk_frame = tk.Frame(card, bg=CARD)
        chk_frame.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))

        self.var_headless = tk.BooleanVar(value=False)
        chk_headless = ttk.Checkbutton(chk_frame, text="Jalankan Headless Chrome",
                               variable=self.var_headless, style="TCheckbutton")
        chk_headless.pack(side="left", padx=(0, 20))

        # ── Checkbox: Selang-seling use image ──────────────────────────────
        self.var_alternate_img = tk.BooleanVar(value=True)
        chk_alt = ttk.Checkbutton(chk_frame,
                                   text="Selang-seling Use Image (tab genap=gambar, ganjil=tidak)",
                                   variable=self.var_alternate_img,
                                   style="TCheckbutton",
                                   command=self._on_alternate_changed)
        chk_alt.pack(side="left", padx=(0, 20))

        # ── Checkbox: Semua pakai gambar (muncul saat selang-seling OFF) ───
        self.var_use_img_all = tk.BooleanVar(value=True)
        self._chk_use_img_all = ttk.Checkbutton(chk_frame,
                                                  text="Semua Tab Pakai Gambar",
                                                  variable=self.var_use_img_all,
                                                  style="TCheckbutton")
        # Tampilkan hanya jika var_alternate_img = False
        self._chk_use_img_all.pack(side="left")
        self._on_alternate_changed()  # Set initial visibility

        # ── Row 2b - Checkbox: Gabungkan 2 video menjadi 1 (20 detik) ─────
        chk_frame2 = tk.Frame(card, bg=CARD)
        chk_frame2.grid(row=2, column=0, columnspan=6, sticky="w", pady=(2, 0))
        # (actually put in separate row; we need to shift rows below by using a new frame)
        # Reset: use a dedicated sub-frame below chk_frame
        chk_frame2.grid_forget()
        merge_frame = tk.Frame(card, bg=CARD)
        merge_frame.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))

        self.var_merge_videos = tk.BooleanVar(value=True)
        chk_merge = ttk.Checkbutton(
            merge_frame,
            text="🎬 Gabungkan 2 Video Menjadi 1 (output 10 dtk → digabung jadi 20 dtk) setelah semua siklus",
            variable=self.var_merge_videos,
            style="TCheckbutton")
        chk_merge.pack(side="left")

        # Paths
        tk.Label(card, text="Output Dir:", **lbl_kw).grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.var_outdir = tk.StringVar(value=r"C:\tiktok_automation\Output")
        ent_out = ttk.Entry(card, textvariable=self.var_outdir, width=30)
        ent_out.grid(row=4, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(8, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_dir(self.var_outdir)
                   ).grid(row=4, column=5, padx=(0, 4), pady=(8, 0))

        tk.Label(card, text="Bahan Dir:", **lbl_kw).grid(row=5, column=0, sticky="w", pady=(4, 0))
        self.var_bahandir = tk.StringVar(value=r"C:\tiktok_automation\tab_bahan")
        ent_bhn = ttk.Entry(card, textvariable=self.var_bahandir, width=30)
        ent_bhn.grid(row=5, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_dir(self.var_bahandir)
                   ).grid(row=5, column=5, padx=(0, 4), pady=(4, 0))

        tk.Label(card, text="Merged Dir:", **lbl_kw).grid(row=6, column=0, sticky="w", pady=(4, 0))
        self.var_mergeddir = tk.StringVar(value=r"C:\tiktok_automation\Output_Merged")
        ent_mrg = ttk.Entry(card, textvariable=self.var_mergeddir, width=30)
        ent_mrg.grid(row=6, column=1, columnspan=4, sticky="ew", padx=(4, 4), pady=(4, 0))
        ttk.Button(card, text="…", style="Flat.TButton", width=3,
                   command=lambda: self._browse_dir(self.var_mergeddir)
                   ).grid(row=6, column=5, padx=(0, 4), pady=(4, 0))

        # ──── Row 8: Output Destination (Local / Google Drive) ────────────────────────
        sep2 = tk.Frame(card, bg=BORDER, height=1)
        sep2.grid(row=8, column=0, columnspan=6, sticky="ew", pady=(10, 6))

        tk.Label(card, text="💾  Simpan Output:", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 10, "bold")).grid(row=9, column=0, columnspan=2,
                                                     sticky="w", pady=(0, 4))

        self.var_save_mode = tk.StringVar(value="local")

        dest_frame = tk.Frame(card, bg=CARD)
        dest_frame.grid(row=10, column=0, columnspan=6, sticky="w")

        rb_local = tk.Radiobutton(
            dest_frame, text="📂  Lokal (default)",
            variable=self.var_save_mode, value="local",
            bg=CARD, fg=GREEN, selectcolor=CARD2,
            activebackground=CARD, activeforeground=GREEN,
            font=("Segoe UI", 10, "bold"),
            command=self._on_save_mode_changed)
        rb_local.pack(side="left", padx=(0, 20))

        rb_gdrive = tk.Radiobutton(
            dest_frame, text="☁  Google Drive",
            variable=self.var_save_mode, value="gdrive",
            bg=CARD, fg=ACCENT, selectcolor=CARD2,
            activebackground=CARD, activeforeground=ACCENT,
            font=("Segoe UI", 10, "bold"),
            command=self._on_save_mode_changed)
        rb_gdrive.pack(side="left")

        # GDrive row (hidden by default)
        self._gdrive_row = tk.Frame(card, bg=CARD)
        self._gdrive_row.grid(row=11, column=0, columnspan=6, sticky="ew", pady=(6, 0))

        tk.Label(self._gdrive_row, text="Link Folder GDrive:",
                 bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")

        self.var_gdrive_url = tk.StringVar(value="")
        self._ent_gdrive = ttk.Entry(self._gdrive_row, textvariable=self.var_gdrive_url, width=36)
        self._ent_gdrive.pack(side="left", padx=(6, 6), fill="x", expand=True)

        ttk.Button(self._gdrive_row, text="🔐 Authenticate",
                   style="Flat.TButton",
                   command=self._gdrive_authenticate).pack(side="left", padx=(0, 4))
        ttk.Button(self._gdrive_row, text="✅ Test Koneksi",
                   style="Flat.TButton",
                   command=self._gdrive_test).pack(side="left")

        self._gdrive_status_lbl = tk.Label(self._gdrive_row, text="",
                                            bg=CARD, fg=MUTED,
                                            font=("Segoe UI", 9, "italic"))
        self._gdrive_status_lbl.pack(side="left", padx=(8, 0))

        self._on_save_mode_changed()  # set initial visibility

        card.columnconfigure(1, weight=1)
        card.columnconfigure(3, weight=1)

    def _on_alternate_changed(self):
        """Show/hide 'Semua Tab Pakai Gambar' checkbox based on alternate_img state."""
        if not hasattr(self, "_chk_use_img_all"):
            return
        if self.var_alternate_img.get():
            self._chk_use_img_all.pack_forget()
        else:
            self._chk_use_img_all.pack(side="left")

    def _on_save_mode_changed(self):
        """Show/hide GDrive row based on save mode radio selection."""
        if not hasattr(self, "_gdrive_row"):
            return
        mode = self.var_save_mode.get()
        if mode == "gdrive":
            self._gdrive_row.grid()
        else:
            self._gdrive_row.grid_remove()

    def _gdrive_authenticate(self):
        """Run OAuth flow in a background thread so GUI stays responsive."""
        if not GDRIVE_OK:
            messagebox.showerror("pydrive2 tidak ada",
                                 "Jalankan:\n  pip install pydrive2\n\nlalu restart aplikasi.")
            return
        if not os.path.isfile(CLIENT_SECRETS_FILE):
            messagebox.showerror(
                "client_secrets.json tidak ada",
                "Buat project di Google Cloud Console, aktifkan Drive API,\n"
                "download OAuth credentials (Desktop App) dan simpan sebagai:\n\n"
                f"  {CLIENT_SECRETS_FILE}\n\nLalu klik Authenticate lagi."
            )
            return
        self._gdrive_status_lbl.configure(text="⏳ Membuka browser untuk auth...", fg=YELLOW)
        self.update_idletasks()

        def _do_auth():
            try:
                gauth = GoogleAuth(settings_file=GDRIVE_SETTINGS_YAML)
                gauth.LocalWebserverAuth()          # opens browser first time
                gauth.SaveCredentialsFile(GDRIVE_CREDS_FILE)
                self.after(0, lambda: self._gdrive_status_lbl.configure(
                    text="✅ Authenticated & tersimpan!", fg=GREEN))
            except Exception as e:
                self.after(0, lambda: self._gdrive_status_lbl.configure(
                    text=f"❌ Error: {e}", fg=RED))

        threading.Thread(target=_do_auth, daemon=True).start()

    def _gdrive_test(self):
        """Quick test: list root and verify folder ID is accessible."""
        if not GDRIVE_OK:
            messagebox.showerror("pydrive2 tidak ada", "pip install pydrive2")
            return
        if not os.path.isfile(GDRIVE_CREDS_FILE):
            messagebox.showwarning("Belum auth", "Klik Authenticate dulu.")
            return
        url = self.var_gdrive_url.get().strip()
        if not url:
            messagebox.showwarning("Link kosong", "Masukkan link folder Google Drive.")
            return
        folder_id = extract_gdrive_folder_id(url)
        self._gdrive_status_lbl.configure(text="⏳ Testing...", fg=YELLOW)
        self.update_idletasks()

        def _do_test():
            try:
                gauth = GoogleAuth(settings_file=GDRIVE_SETTINGS_YAML)
                gauth.LoadCredentialsFile(GDRIVE_CREDS_FILE)
                if gauth.access_token_expired:
                    gauth.Refresh()
                    gauth.SaveCredentialsFile(GDRIVE_CREDS_FILE)
                drive = GoogleDrive(gauth)
                folder_list = drive.ListFile(
                    {'q': f"'{folder_id}' in parents and trashed=false",
                     'maxResults': 1}).GetList()
                self.after(0, lambda: self._gdrive_status_lbl.configure(
                    text=f"✅ Folder OK (ID: {folder_id[:16]}…)", fg=GREEN))
            except Exception as e:
                self.after(0, lambda: self._gdrive_status_lbl.configure(
                    text=f"❌ {e}", fg=RED))

        threading.Thread(target=_do_test, daemon=True).start()

    # ── Prompt Panel ─────────────────────────────────────────────────────────
    def _build_prompt_panel(self, parent):
        card = tk.Frame(parent, bg=CARD, pady=10, padx=14)
        card.pack(fill="both", expand=True, pady=(0, 8))

        header = tk.Frame(card, bg=CARD)
        header.pack(fill="x")
        tk.Label(header, text="📝  Prompts", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(header, text="＋ Tambah", style="Flat.TButton",
                   command=self._add_prompt).pack(side="right", padx=2)
        ttk.Button(header, text="－ Hapus", style="Flat.TButton",
                   command=self._remove_prompt).pack(side="right", padx=2)

        self.prompt_nb = ttk.Notebook(card)
        self.prompt_nb.pack(fill="both", expand=True, pady=(8, 0))

        self.prompt_texts = []
        for idx, p in enumerate(self.prompts):
            self._add_prompt_tab(f"Prompt {idx+1}", p)

    def _add_prompt_tab(self, title, content=""):
        frm  = tk.Frame(self.prompt_nb, bg=CARD)
        txt  = scrolledtext.ScrolledText(frm, wrap="word", height=9,
                                         bg=CARD2, fg=TEXT, insertbackground=TEXT,
                                         font=("Consolas", 9), relief="flat",
                                         selectbackground=ACCENT)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", content)
        self.prompt_nb.add(frm, text=title)
        self.prompt_texts.append(txt)

    def _add_prompt(self):
        idx = len(self.prompt_texts) + 1
        self._add_prompt_tab(f"Prompt {idx}")
        self.prompts.append("")

    def _remove_prompt(self):
        if len(self.prompt_texts) <= 1:
            messagebox.showwarning("Warning", "Minimal 1 prompt harus ada.")
            return
        last = len(self.prompt_texts) - 1
        self.prompt_nb.forget(last)
        self.prompt_texts.pop()
        self.prompts.pop()

    # ── Tab Monitor ───────────────────────────────────────────────────────────
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

        def _on_resize(e):
            canvas.itemconfig(win_id, width=e.width)
        canvas.bind("<Configure>", _on_resize)

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self.monitor_frame.bind("<Configure>", _on_frame_configure)

        self._canvas = canvas
        self._rebuild_tab_rows(10)

    def _rebuild_tab_rows(self, n_tabs):
        for w in self.monitor_frame.winfo_children():
            w.destroy()
        self.tab_rows = []

        for i in range(n_tabs):
            row = tk.Frame(self.monitor_frame, bg=CARD, pady=3)
            row.pack(fill="x", padx=2)

            # Tab number
            num_lbl = tk.Label(row, text=f"Tab {i+1:02d}", bg=CARD, fg=MUTED,
                               font=("Segoe UI", 9, "bold"), width=7)
            num_lbl.pack(side="left")

            # Progress bar
            bar = ttk.Progressbar(row, style="Gen.Horizontal.TProgressbar",
                                   orient="horizontal", length=200, maximum=100)
            bar.pack(side="left", padx=(4, 8), fill="x", expand=True)

            # Percent label
            pct_lbl = tk.Label(row, text="0%", bg=CARD, fg=MUTED,
                               font=("Segoe UI", 9), width=5)
            pct_lbl.pack(side="left")

            # Status label
            stat_lbl = tk.Label(row, text="idle", bg=CARD, fg=MUTED,
                                font=("Segoe UI", 9, "bold"), width=12, anchor="w")
            stat_lbl.pack(side="left", padx=(4, 0))

            self.tab_rows.append({
                "bar": bar, "pct": pct_lbl, "status": stat_lbl
            })

    # ── Output Folder ─────────────────────────────────────────────────────────
    def _build_output_panel(self, parent):
        card = tk.Frame(parent, bg=CARD2, pady=10, padx=14)
        card.pack(fill="x", pady=(0, 8))

        header = tk.Frame(card, bg=CARD2)
        header.pack(fill="x")
        tk.Label(header, text="📁  Output Terbaru", bg=CARD2, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(header, text="🔄 Refresh", style="Flat.TButton",
                   command=self._refresh_output_folder).pack(side="right")
        ttk.Button(header, text="📂 Buka", style="Flat.TButton",
                   command=self._open_output_dir).pack(side="right", padx=4)

        frm = tk.Frame(card, bg=CARD2)
        frm.pack(fill="both", pady=(6, 0))

        cols = ("File", "Ukuran", "Waktu")
        self.out_tree = ttk.Treeview(frm, columns=cols, show="headings", height=6)
        for c in cols:
            self.out_tree.heading(c, text=c)
        self.out_tree.column("File",    width=160)
        self.out_tree.column("Ukuran",  width=80,  anchor="e")
        self.out_tree.column("Waktu",   width=130, anchor="center")

        # Style treeview
        st = ttk.Style()
        st.configure("Treeview",
                      background=CARD2, fieldbackground=CARD2,
                      foreground=TEXT, rowheight=22,
                      font=("Segoe UI", 9))
        st.configure("Treeview.Heading",
                      background=CARD, foreground=ACCENT,
                      font=("Segoe UI", 9, "bold"), relief="flat")
        st.map("Treeview", background=[("selected", ACCENT)],
               foreground=[("selected", "#FFF")])

        vsb2 = ttk.Scrollbar(frm, orient="vertical", command=self.out_tree.yview)
        self.out_tree.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side="right", fill="y")
        self.out_tree.pack(fill="both", expand=True)

    # ── Log Panel ─────────────────────────────────────────────────────────────
    def _build_log_panel(self, parent):
        card = tk.Frame(parent, bg=CARD, pady=10, padx=14)
        card.pack(fill="both", expand=True)

        header = tk.Frame(card, bg=CARD)
        header.pack(fill="x")
        tk.Label(header, text="📋  Log", bg=CARD, fg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(header, text="🗑 Clear", style="Flat.TButton",
                   command=lambda: self.log_box.configure(state="normal") or
                                   self.log_box.delete("1.0", "end") or
                                   self.log_box.configure(state="disabled")
                   ).pack(side="right")

        self.log_box = scrolledtext.ScrolledText(card, state="disabled",
                                                  bg=BG, fg=TEXT,
                                                  font=("Consolas", 9),
                                                  relief="flat", height=10,
                                                  insertbackground=TEXT,
                                                  selectbackground=ACCENT)
        self.log_box.pack(fill="both", expand=True, pady=(6, 0))

        self.log_box.tag_config("INFO",  foreground=TEXT)
        self.log_box.tag_config("WARN",  foreground=YELLOW)
        self.log_box.tag_config("ERROR", foreground=RED)
        self.log_box.tag_config("OK",    foreground=GREEN)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _browse_dir(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    def _append_log(self, msg, tag="INFO"):
        self.log_box.configure(state="normal")
        if "✅" in msg or "selesai" in msg.lower() or "🎉" in msg:
            tag = "OK"
        elif "[WARN]" in msg:
            tag = "WARN"
        elif "[ERROR]" in msg:
            tag = "ERROR"
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _refresh_output_folder(self):
        d = self.var_outdir.get() if hasattr(self, "var_outdir") else r"C:\tiktok_automation\Output"
        if not os.path.exists(d):
            return
        files = glob.glob(os.path.join(d, "*.mp4"))
        files.sort(key=os.path.getmtime, reverse=True)

        self.out_tree.delete(*self.out_tree.get_children())
        for f in files[:30]:
            sz  = os.path.getsize(f)
            sz_s= f"{sz/1024/1024:.2f} MB" if sz > 1024 * 1024 else f"{sz//1024} KB"
            mt  = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M")
            self.out_tree.insert("", "end", values=(os.path.basename(f), sz_s, mt))

    def _open_output_dir(self):
        d = self.var_outdir.get()
        if os.path.exists(d):
            os.startfile(d)

    # ── Generate / Stop ──────────────────────────────────────────────────────
    def _collect_prompts(self):
        ps = []
        for txt in self.prompt_texts:
            content = txt.get("1.0", "end").strip()
            if content:
                ps.append(content)
        return ps if ps else [DEFAULT_PROMPT_1]

    def _on_generate(self):
        if self._running:
            return

        prompts = self._collect_prompts()
        n_tabs  = self.var_tabs.get()
        n_cycles= self.var_cycles.get()

        cfg = {
            "prompts":          prompts,
            "n_tabs":           n_tabs,
            "n_cycles":         n_cycles,
            "headless":         self.var_headless.get(),
            "debug_port":       self.var_port.get(),
            "output_dir":       self.var_outdir.get(),
            "tab_bahan_dir":    self.var_bahandir.get(),
            "merged_dir":       self.var_mergeddir.get(),
            "merge_videos":     self.var_merge_videos.get(),
            "chrome_path":      r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "user_data_dir":    r"C:\tiktok_automation\user_data\1",
            "target_url":       "https://vidabot.markasai.com/generate-grok",
            "alternate_image":  self.var_alternate_img.get(),
            "use_image_all":    self.var_use_img_all.get(),
            # ── Save destination ──────────────────────────────────────────
            "save_mode":        self.var_save_mode.get(),
            "gdrive_folder_id": extract_gdrive_folder_id(self.var_gdrive_url.get().strip())
                                if self.var_save_mode.get() == "gdrive" else "",
        }

        # Rebuild tab rows
        self._rebuild_tab_rows(n_tabs)

        self.engine = AutomationEngine(cfg, self.log_q, self.stat_q)
        self.engine_thread = threading.Thread(target=self.engine.run, daemon=True)
        self.engine_thread.start()

        self._running = True
        self.btn_generate.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.status_lbl.configure(text="⬤  Running", fg=GREEN)
        self._append_log("▶ Automation dimulai...")

    def _on_stop(self):
        if self.engine:
            self.engine.stop()
        self._set_idle()
        self._append_log("⛔ Stop diminta. Menunggu thread selesai...")

    def _set_idle(self):
        self._running = False
        self.btn_generate.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status_lbl.configure(text="⬤  Idle", fg=MUTED)

    # ── Queue Polling ─────────────────────────────────────────────────────────
    def _poll_queues(self):
        # Log queue
        try:
            while True:
                msg = self.log_q.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass

        # Status queue
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
                    merged_dir = ev.get("merged_dir", "")
                    if merged_dir:
                        info_msg = (
                            f"Semua siklus telah selesai!\n"
                            f"Video asli: {self.var_outdir.get()}\n"
                            f"Video gabungan: {merged_dir}"
                        )
                    else:
                        info_msg = f"Semua siklus telah selesai!\nCek folder output: {self.var_outdir.get()}"
                    messagebox.showinfo("🎉 Selesai!", info_msg)

                if "merged_dir" in ev and not ev.get("done"):
                    # partial merge notification
                    self._append_log(f"🎬 Video gabungan tersimpan di: {ev['merged_dir']}")
        except queue.Empty:
            pass

        # Auto-refresh output every 15 seconds when running
        if self._running:
            if not hasattr(self, "_last_refresh"):
                self._last_refresh = time.time()
            if time.time() - self._last_refresh > 15:
                self._refresh_output_folder()
                self._last_refresh = time.time()

        # Check if thread died unexpectedly
        if self._running and self.engine_thread and not self.engine_thread.is_alive():
            self._set_idle()
            self._append_log("Thread selesai.", "INFO")

        self.after(300, self._poll_queues)


# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = GrokApp()
    app.mainloop()
