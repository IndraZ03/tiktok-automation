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
import base64
from datetime import datetime
import shutil
import requests

try:
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

# Import from the newly created JS controller
try:
    import selenium_js_grok
    JS_GROK_OK = True
except ImportError:
    JS_GROK_OK = False

# ── Paths ────────────────────────────────────────────────────────────────────
APP_DIR              = r"C:\tiktok_automation"
JS_FILE              = os.path.join(APP_DIR, "grok_auto.js")
GROK_URL             = "https://grok.com/imagine"

# ════════════════════════════════════════════════════════════════════════════
#  DEFAULT PROMPTS
# ════════════════════════════════════════════════════════════════════════════
DEFAULT_PROMPT_1 = '''INSTRUKSI UMUM – GAYA HIJAB HOKAGE "UWAK" 🎬 Format & Teknis - Durasi: 8 detik per video. - Resolusi: Render 8K ultra-realistis. - Produk yang digunakan: Tab Pro S12 (11,6 inci, visual splash warna-warni, ikon 5G, RAM 16GB, ROM 1024GB). - Desain: ramping, mengkilap, bezel tipis. - Aksesoris: keyboard wireless terpisah, stylus metalik, earphone & charger (unboxing opsional). 🎭 Karakter - Wanita Indonesia cantik dengan hijab modern. - Pakaian: Jubah Hokage (putih-oranye), ikat kepala dengan tulisan "uwak". - Gaya: percaya diri, ekspresif, aura ninja yang elegan. 🎤 Sulih Suara (VO) - Bahasa: 100% Bahasa Indonesia. - Singkat (maksimal 6-8 kata, selesai ≤2 detik). - Berenergi tinggi, ekspresif, seperti pembawa acara TikTok Live. 🎥 Kamera & Visual - Sudut pandang: track-in/out, orbit, selfie POV, sudut rendah, sinematik dari atas. - Transisi: jepret, cambuk, zoom, glitch elegan. - Efek tematik: api, debu beterbangan, kilauan emas. - Latar belakang: meja kayu kenari, sorotan emas, efek api sinematik. - Warna dominan: hitam, putih gading, kilauan emas + aksen api merah-oranye. 🔊 Audio & Efek - Musik: beat elegan modern + suasana ninja epik. - Efek: desingan api, percikan api, kilauan emas, glitch lembut. - VO: suara manusia asli, cepat, tegas, kuat.'''
DEFAULT_PROMPT_2 = '''Instruksi Umum\n\nBahasa: 100% Bahasa Indonesia untuk VO\n\nDetail Produk Konsisten:\n\nTablet Android\n\nLayar 11,6 inci, resolusi 2560×1600\n\nLayar ON: splash screen besar "ANDROID + ikon 5G WiFi, 16GB RAM, 1024GB ROM\n\nDesain: tipis, sudut membulat, bezel tipis, bodi logam + plastik glossy\n\nAksesori: keyboard wireless tipis hitam + stylus metalik ramping\n\n\nVisual Style: nuansa gaming neon glitch (merah–biru), penuh energi, banyak efek cahaya & transisi snap/zoom/shake.\n\nKamera: handheld shaky, zoom-in ke layar game, orbit cepat.\n\nVO Style: suara natural manusia, cepat, agresif, seperti caster e-sports → bikin penonton terbakar semangat.\n\nMusik: beat trap/EDM gaming, bass kencang, SFX glitch & power-up.'''

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
#  AUTOMATION ENGINE  (Selenium + JS Injected)
# ════════════════════════════════════════════════════════════════════════════
class AutomationEngine:
    def __init__(self, config: dict, log_q: queue.Queue, status_q: queue.Queue):
        self.cfg    = config
        self.log_q  = log_q
        self.stat_q = status_q
        self._stop  = threading.Event()
        self.driver = None
        self.chrome_proc = None

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

    def get_random_image(self):
        d = self.cfg.get("tab_bahan_dir", "")
        if not d or not os.path.exists(d):
            return None
        exts = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
        files = [f for f in os.listdir(d) if f.lower().endswith(exts)]
        if not files:
            # Check subdirectories
            for sub in os.listdir(d):
                sub_path = os.path.join(d, sub)
                if os.path.isdir(sub_path):
                    sub_images = [f for f in os.listdir(sub_path) if f.lower().endswith(exts)]
                    if sub_images:
                        return os.path.join(sub_path, random.choice(sub_images))
            return None
        return os.path.join(d, random.choice(files))
    
    def image_to_base64(self, image_path):
        if not image_path or not os.path.exists(image_path):
            return None
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')

    # ── Chrome lifecycle ─────────────────────────────────────────────────────────
    def _open_chrome(self, user_data_dir, port):
        self.log(f"Membuka Chrome (port={port})...")
        chrome_path = self.cfg.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        cmd = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            GROK_URL
        ]
        proc = subprocess.Popen(cmd)
        time.sleep(5)
        return proc

    def _connect_selenium(self, port):
        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
        svc = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=svc, options=opts)
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": self.cfg["output_dir"]
        })
        self.log("Selenium terhubung ke Chrome ✓")
        return driver

    def setup_tabs(self, driver, n_tabs):
        self.log(f"Menyiapkan {n_tabs} tab...")
        while len(driver.window_handles) < n_tabs:
            try:
                driver.switch_to.new_window('tab')
            except: pass
            if self._stop.is_set():
                break

        for idx, h in enumerate(driver.window_handles[:n_tabs]):
            if self._stop.is_set(): break
            driver.switch_to.window(h)
            
            nav_ok = False
            for nav_try in range(3):
                try:
                    driver.get(GROK_URL)
                    time.sleep(2 + nav_try * 1.5)
                    current_url = driver.current_url or ''
                    if 'grok.com' in current_url or 'imagine' in current_url:
                        nav_ok = True
                        break
                    elif 'about:blank' in current_url or not current_url.startswith('http'):
                        self.log(f"Tab {idx+1} tertahan di about:blank, retry {nav_try+1}/3...")
                        time.sleep(1)
                    else:
                        nav_ok = True
                        break
                except Exception as e:
                    self.log(f"Tab {idx+1} navigasi error: {str(e)[:40]}, retry...")
                    time.sleep(2)
            
            if not nav_ok:
                self.log(f"Tab {idx+1} gagal muat url setelah 3x percobaan.")
        self.log(f"Total tab siap: {len(driver.window_handles)}")

    # ── Main Run (Using JS Injection) ─────────────────────────────────────────────────
    def run(self):
        if not SELENIUM_OK or not JS_GROK_OK:
            self.log("Library Selenium belum diaktifkan / tidak siap!", "ERROR")
            return

        cfg     = self.cfg
        n_tabs  = cfg.get("n_tabs", 5)
        n_cycle = cfg.get("n_cycles", 1)
        prompts = cfg.get("prompts", [])
        alternate_img = cfg.get("alternate_image", True)
        use_img_all   = cfg.get("use_image_all", False)
        output_dir = cfg.get("output_dir", r"C:\tiktok_automation\grok_output")

        os.makedirs(output_dir, exist_ok=True)

        ud = cfg.get("user_data_dir", r"C:\tiktok_automation\user_data\1")
        pt = cfg.get("debug_port", 9250)

        # Build configurations
        prompts_config = []
        for i in range(n_tabs):
            p = prompts[i % len(prompts)] if prompts else "Test prompt"
            use_img = (i % 2 == 0) if alternate_img else use_img_all
            prompts_config.append({
                'prompt': p,
                'mode': 'video',
                'use_image': use_img,
            })

        self.chrome_proc = self._open_chrome(ud, pt)
        if self._stop.is_set():
            return
        
        try:
            self.driver = self._connect_selenium(pt)
        except Exception as e:
            self.log(f"Gagal connect Selenium: {e}", "ERROR")
            return
        
        driver = self.driver
        self.setup_tabs(driver, n_tabs)
        if self._stop.is_set():
            self._cleanup()
            return
        
        tab_handles = driver.window_handles[:n_tabs]
        
        for cycle in range(n_cycle):
            if self._stop.is_set():
                break

            t0 = time.time()
            self.log(f"\n=== SIKLUS KE-{cycle+1}/{n_cycle} ===")
            self.stat_q.put({"cycle": cycle + 1})

            # Phase 1: Start tasks on tabs via JS
            self.log("Phase 1: Inisiasi tugas pada tab...")
            tab_start_times = {}

            for i in range(n_tabs):
                if self._stop.is_set(): break
                cfg_i = prompts_config[i % len(prompts_config)]
                handle = tab_handles[i]

                try:
                    driver.switch_to.window(handle)
                    
                    try:
                        WebDriverWait(driver, 15).until(
                            lambda d: len(d.find_elements(By.CSS_SELECTOR, "div.tiptap, textarea, button[aria-label='Settings'], button[aria-label='Pengaturan']")) > 0
                        )
                        if cycle == 0 and i == 0:
                            self.log(f"Tab {i+1}: Menunggu render awal selesai...")
                            time.sleep(8)
                        else:
                            time.sleep(1)
                    except:
                        self.log(f"Tab {i+1}: ⚠️ Render UI terlambat")

                    selenium_js_grok.inject_js(driver)
                    self.set_tab_status(i, 0, "generating")

                    b64_img = None
                    img_name = 'ref.jpg'
                    if cfg_i.get('use_image'):
                        img_path = self.get_random_image()
                        if img_path:
                            b64_img = self.image_to_base64(img_path)
                            img_name = os.path.basename(img_path)
                            self.log(f"Tab {i+1}: Upload gambar {img_name}")
                    
                    js_config = {
                        'prompt': cfg_i['prompt'],
                        'mode': cfg_i.get('mode', 'video'),
                        'image': b64_img,
                        'imageName': img_name,
                        'timeout': 600000,
                    }

                    driver.execute_script("window.__grokTabGenerate(arguments[0], arguments[1]);", i, js_config)
                    tab_start_times[i] = time.time()
                    self.log(f"Tab {i+1}: Tugas dimulai ✓")
                    time.sleep(1)

                except Exception as e:
                    self.log(f"Tab {i+1} Gagal mulai tugas: {e}", "ERROR")
                    self.set_tab_status(i, 0, "error")

            # Phase 2: Monitor progress 
            self.log("Phase 2: Memantau progress generate...")
            tab_done = set()
            tab_failed = set()
            max_wait = 660  # 11 menit
            monitor_start = time.time()

            # Tunggu minimal 10 detik sebelum mulai cek progress
            # (beri waktu JS untuk memulai generate & overlay muncul)
            time.sleep(10)

            while len(tab_done) + len(tab_failed) < n_tabs:
                if self._stop.is_set(): break
                if time.time() - monitor_start > max_wait:
                    self.log("Timeout maksimum tercapai!", "WARN")
                    break

                for i in range(n_tabs):
                    if i in tab_done or i in tab_failed:
                        continue
                    
                    try:
                        driver.switch_to.window(tab_handles[i])
                        # __grokTabCheckProgress adalah SYNCHRONOUS function
                        # sehingga execute_script("return ...") langsung mengembalikan dict
                        tab_state = driver.execute_script(
                            "return window.__grokTabCheckProgress(arguments[0]);", i
                        )

                        if tab_state and isinstance(tab_state, dict):
                            status   = tab_state.get('status', 'unknown')
                            progress = tab_state.get('progress', 0)

                            if status == 'done':
                                self.set_tab_status(i, 100, "success")
                                tab_done.add(i)
                                self.log(f"Tab {i+1}: Generation selesai ✓")
                            elif status == 'error':
                                err = tab_state.get('error', 'Unknown error')
                                self.set_tab_status(i, 0, "error")
                                tab_failed.add(i)
                                self.log(f"Tab {i+1} Error: {err}", "ERROR")
                            elif status == 'generating':
                                # Update terlepas dari progress = 0 atau tidak
                                self.set_tab_status(i, progress, "generating")
                        else:
                            # tab_state None berarti JS belum siap, skip
                            pass

                    except Exception:
                        pass
                time.sleep(3)

            # Phase 3: Download (via tombol, file watcher tunggu file di disk)
            self.log("Phase 3: Download hasil video...")
            for i in tab_done:
                if self._stop.is_set(): break
                try:
                    driver.switch_to.window(tab_handles[i])
                    self.set_tab_status(i, 100, "downloading")
                    self.log(f"Tab {i+1}: Memulai klik tombol Unduh...")

                    # Catat waktu sekarang sebelum klik
                    dl_time = time.time()

                    # Panggil __grokTabDownload (sync fire-and-forget)
                    # JS akan menunggu tombol Unduh muncul lalu mengkliknya
                    driver.execute_script("window.__grokTabDownload(arguments[0]);", i)

                    # Poll __grokBatchState untuk tahu kapan JS selesai klik tombol
                    js_done = False
                    for _ in range(30):  # max 60 detik
                        time.sleep(2)
                        ts = driver.execute_script(
                            "return window.__grokBatchState.tabs[arguments[0]];", i
                        )
                        if ts:
                            s = ts.get('status', '')
                            if s in ('downloaded', 'error'):
                                if s == 'error':
                                    self.log(f"Tab {i+1}: JS error klik tombol: {ts.get('error')}", "WARN")
                                else:
                                    self.log(f"Tab {i+1}: Tombol sudah diklik, tunggu file...")
                                js_done = True
                                break

                    # Tunggu file .mp4 baru muncul di output_dir (max 90 detik)
                    filename  = self.get_next_filename()
                    save_path = os.path.join(output_dir, filename)
                    dl_ok = False
                    downloads_dir = os.path.expanduser("~/Downloads")

                    for _ in range(90):
                        time.sleep(1)
                        if self._stop.is_set(): break
                        for chk_dir in [output_dir, downloads_dir]:
                            mp4s = glob.glob(os.path.join(chk_dir, "*.mp4"))
                            new  = [f for f in mp4s if os.path.getmtime(f) > dl_time - 1]
                            # Pastikan tidak ada .crdownload (download belum selesai)
                            crdown = glob.glob(os.path.join(chk_dir, "*.crdownload"))
                            if new and not crdown:
                                newest = max(new, key=os.path.getmtime)
                                fsize  = os.path.getsize(newest)
                                if fsize > 50000:  # minimal 50KB
                                    if chk_dir != output_dir or newest != save_path:
                                        os.makedirs(output_dir, exist_ok=True)
                                        shutil.move(newest, save_path)
                                    self.log(f"Tab {i+1}: ✅ Tersimpan: {filename} ({fsize/1024/1024:.1f} MB)")
                                    dl_ok = True
                                    break
                        if dl_ok:
                            break

                    if dl_ok:
                        self.set_tab_status(i, 100, "success")
                    else:
                        self.log(f"Tab {i+1}: ❌ File tidak muncul setelah 90 detik", "ERROR")
                        self.set_tab_status(i, 0, "error")

                except Exception as e:
                    self.log(f"Tab {i+1}: ❌ Exception download: {e}", "ERROR")
                    self.set_tab_status(i, 0, "error")

            # Phase 4: Reload failed tabs for next cycle
            if cycle < n_cycle - 1:
                for i in range(n_tabs):
                    try:
                        driver.switch_to.window(tab_handles[i])
                        driver.get(GROK_URL)
                        time.sleep(1)
                    except:
                        pass
        
            elapsed = time.time() - t0
            self.log(f"Siklus {cycle+1} selesai – {int(elapsed//60)}m {int(elapsed%60)}s")

        if self._stop.is_set():
            self.log("⛔ Dihentikan oleh user.", "WARN")
            for i in range(n_tabs):
                self.set_tab_status(i, 0, "stopped")
        else:
            self.log("🎉 SEMUA SIKLUS SELESAI!")
            self.stat_q.put({"done": True})

        self._cleanup()

    def _cleanup(self):
        try:
            selenium_js_grok.close_chrome(self.driver, self.chrome_proc)
        except:
            pass
        self.driver = None
        self.chrome_proc = None

# ════════════════════════════════════════════════════════════════════════════
#  MAIN GUI
# ════════════════════════════════════════════════════════════════════════════
class GrokJSApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⚡ Selenium+JS Grok Automation")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.geometry("1100x750")

        self.style = ttk.Style(self)
        self._apply_style()

        # State/Vars
        self.log_q = queue.Queue()
        self.stat_q = queue.Queue()
        self.engine = None
        self.thread = None

        self.var_n_tabs       = tk.IntVar(value=5)
        self.var_n_cycles     = tk.IntVar(value=1)
        self.var_bahan_dir    = tk.StringVar(value=os.path.join(APP_DIR, "bahan"))
        self.var_output_dir   = tk.StringVar(value=os.path.join(APP_DIR, "Output", "grok_js"))
        self.var_chkbx_alt    = tk.BooleanVar(value=True)  
        self.var_chkbx_all    = tk.BooleanVar(value=False) 

        self.prompts_text_widgets = []
        self.tab_monitor_frames   = [] # widgets for tab visual progress

        # Auto create output dir
        os.makedirs(self.var_output_dir.get(), exist_ok=True)

        self._build_ui()
        self._poll_queues()

    def _apply_style(self):
        s = self.style
        s.theme_use('clam')
        
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("Card2.TFrame", background=CARD2)
        
        s.configure("Header.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 18, "bold"))
        s.configure("TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("Light.TLabel", background=CARD2, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("BG.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        
        s.configure("TButton",
                    font=("Segoe UI", 10, "bold"),
                    background=ACCENT,
                    foreground=TEXT,
                    borderwidth=0,
                    focuscolor=ACCENT,
                    padding=6)
        s.map("TButton",
              background=[("active", ACCENT2), ("disabled", MUTED)],
              foreground=[("disabled", "#CCCCCC")])

        s.configure("Start.TButton", font=("Segoe UI", 11, "bold"), background=GREEN, foreground="#000000")
        s.map("Start.TButton", background=[("active", "#00C88C"), ("disabled", MUTED)])

        s.configure("Stop.TButton", font=("Segoe UI", 11, "bold"), background=RED, foreground=TEXT)
        s.map("Stop.TButton", background=[("active", "#D63031"), ("disabled", MUTED)])

        s.configure("TabLabel.TLabel", background=CARD2, foreground=TEXT, font=("Segoe UI", 11, "bold"))
        s.configure("TabPct.TLabel", background=CARD2, foreground=TEXT, font=("Segoe UI", 18, "bold"))

        # Checkbox & Radio
        s.configure("TCheckbutton", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
        s.map("TCheckbutton", background=[("active", CARD)])
        
        # Horizontal progress
        s.configure("Horizontal.TProgressbar", thickness=12)

    def _build_ui(self):
        main_container = ttk.Frame(self, padding=20)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Header
        hdr = ttk.Label(main_container, text="⚡ Selenium+JS Grok Automation (UI)", style="Header.TLabel")
        hdr.pack(anchor="nw", pady=(0,20))

        # PanedWindow
        paned = tk.PanedWindow(main_container, orient=tk.HORIZONTAL, bg=BORDER, bd=0, sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True)

        left_col  = ttk.Frame(paned, style="TFrame")
        right_col = ttk.Frame(paned, style="TFrame")
        paned.add(left_col, width=450)
        paned.add(right_col)

        # Left Column Layout
        self._build_config_panel(left_col)
        self._build_prompt_panel(left_col)
        self._build_log_panel(left_col)

        # Right Column Layout
        self._build_tab_monitor(right_col)
        self._build_output_panel(right_col)

    def _build_config_panel(self, parent):
        f = ttk.Frame(parent, style="Card.TFrame", padding=15)
        f.pack(fill=tk.X, pady=(0,15))

        ttk.Label(f, text="Pengaturan Utama", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="nw", pady=(0,10))

        # Row 1: n_tabs & n_cycles
        row1 = ttk.Frame(f, style="Card.TFrame")
        row1.grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Label(row1, text="Jumlah Tab:").pack(side=tk.LEFT)
        ttk.Spinbox(row1, from_=1, to=20, textvariable=self.var_n_tabs, width=5).pack(side=tk.LEFT, padx=(5,20))
        ttk.Label(row1, text="Siklus:").pack(side=tk.LEFT)
        ttk.Spinbox(row1, from_=1, to=100, textvariable=self.var_n_cycles, width=5).pack(side=tk.LEFT, padx=5)

        # Row 2: Bahan Folder
        ttk.Label(f, text="Folder Bahan:").grid(row=2, column=0, sticky="w", pady=5)
        b_frame = ttk.Frame(f, style="Card.TFrame")
        b_frame.grid(row=2, column=1, sticky="ew", pady=5)
        e1 = tk.Entry(b_frame, textvariable=self.var_bahan_dir, bg=CARD2, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT)
        e1.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3, padx=(0,5))
        ttk.Button(b_frame, text="Browse", width=8, command=lambda: self._browse_dir(self.var_bahan_dir)).pack(side=tk.LEFT)

        # Row 3: Output Folder
        ttk.Label(f, text="Folder Hasil:").grid(row=3, column=0, sticky="w", pady=5)
        o_frame = ttk.Frame(f, style="Card.TFrame")
        o_frame.grid(row=3, column=1, sticky="ew", pady=5)
        e2 = tk.Entry(o_frame, textvariable=self.var_output_dir, bg=CARD2, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT)
        e2.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3, padx=(0,5))
        ttk.Button(o_frame, text="Browse", width=8, command=lambda: self._browse_dir(self.var_output_dir)).pack(side=tk.LEFT)

        # Image checkbox logic
        row4 = ttk.Frame(f, style="Card.TFrame")
        row4.grid(row=4, column=0, columnspan=2, sticky="nw", pady=10)
        
        self.chk_alt = ttk.Checkbutton(row4, text="Tab Gambar Selang-seling (Tab 1 Ya, Tab 2 Tidak)", 
                                       variable=self.var_chkbx_alt, command=self._on_alternate_changed)
        self.chk_alt.pack(anchor="w", pady=2)
        
        self.chk_all = ttk.Checkbutton(row4, text="Semua Tab Pakai Gambar", variable=self.var_chkbx_all)
        self.chk_all.pack(anchor="w", pady=2)
        self._on_alternate_changed() # set initial visibility

        # Action Buttons
        btn_frame = ttk.Frame(f, style="Card.TFrame")
        btn_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10,0))
        self.btn_start = ttk.Button(btn_frame, text="▶ START GENERATE", style="Start.TButton", command=self._on_generate)
        self.btn_start.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5), ipady=5)
        self.btn_stop = ttk.Button(btn_frame, text="⏹ STOP", style="Stop.TButton", command=self._on_stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5,0), ipady=5)

    def _on_alternate_changed(self):
        if self.var_chkbx_alt.get():
            self.chk_all.pack_forget()
        else:
            self.chk_all.pack(anchor="w", pady=2)

    def _build_prompt_panel(self, parent):
        f = ttk.Frame(parent, style="Card.TFrame", padding=15)
        f.pack(fill=tk.BOTH, expand=True, pady=(0,15))

        top = ttk.Frame(f, style="Card.TFrame")
        top.pack(fill=tk.X, pady=(0,10))
        ttk.Label(top, text="Daftar Prompt", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(top, text="＋", width=3, command=self._add_prompt).pack(side=tk.RIGHT)
        ttk.Button(top, text="－", width=3, command=self._remove_prompt).pack(side=tk.RIGHT, padx=5)

        self.prompts_notebook = ttk.Notebook(f)
        self.prompts_notebook.pack(fill=tk.BOTH, expand=True)

        self._add_prompt_tab("Prompt 1", DEFAULT_PROMPT_1)
        self._add_prompt_tab("Prompt 2", DEFAULT_PROMPT_2)

    def _add_prompt_tab(self, title, content=""):
        frame = ttk.Frame(self.prompts_notebook, style="Card2.TFrame")
        txt = scrolledtext.ScrolledText(frame, bg=CARD2, fg=TEXT, insertbackground=TEXT, 
                                        font=("Consolas", 9), relief=tk.FLAT, wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        txt.insert("1.0", content)
        self.prompts_text_widgets.append(txt)
        self.prompts_notebook.add(frame, text=title)

    def _add_prompt(self):
        n = len(self.prompts_text_widgets) + 1
        self._add_prompt_tab(f"Prompt {n}", f"Masukkan prompt {n} disini...")

    def _remove_prompt(self):
        if len(self.prompts_text_widgets) > 1:
            idx = len(self.prompts_text_widgets) - 1
            self.prompts_notebook.forget(idx)
            self.prompts_text_widgets.pop()

    def _build_log_panel(self, parent):
        f = ttk.Frame(parent, style="Card.TFrame", padding=15)
        f.pack(fill=tk.X)
        ttk.Label(f, text="System Log", font=("Segoe UI", 12, "bold")).pack(anchor="nw", pady=(0,5))
        self.log_txt = scrolledtext.ScrolledText(f, height=8, bg="#000000", fg="#00FF00", 
                                                 font=("Consolas", 9), relief=tk.FLAT)
        self.log_txt.pack(fill=tk.X)
        self.log_txt.tag_config("ERROR", foreground="#FF4757")
        self.log_txt.tag_config("WARN", foreground="#FFD166")
        self.log_txt.tag_config("INFO", foreground="#E8EAF6")

    def _build_tab_monitor(self, parent):
        self.cycle_lbl = ttk.Label(parent, text="Siklus: 0 / 0", style="BG.TLabel", font=("Segoe UI", 12, "bold"))
        self.cycle_lbl.pack(anchor="ne", padx=5)

        self.monitor_canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        self.monitor_scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.monitor_canvas.yview)
        self.monitor_inner = ttk.Frame(self.monitor_canvas, style="TFrame")

        self.monitor_inner.bind("<Configure>", lambda e: self.monitor_canvas.configure(scrollregion=self.monitor_canvas.bbox("all")))
        self.monitor_canvas.create_window((0, 0), window=self.monitor_inner, anchor="nw", tags="inner_frame")
        self.monitor_canvas.configure(yscrollcommand=self.monitor_scrollbar.set)
        
        self.monitor_canvas.bind('<Configure>', self._on_canvas_resize)

        self.monitor_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5,0))
        self.monitor_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._rebuild_tab_rows(self.var_n_tabs.get())
        
    def _on_canvas_resize(self, event):
        self.monitor_canvas.itemconfig("inner_frame", width=event.width)

    def _rebuild_tab_rows(self, n_tabs):
        for w in self.monitor_inner.winfo_children():
            w.destroy()
        self.tab_monitor_frames.clear()

        for i in range(n_tabs):
            row = ttk.Frame(self.monitor_inner, style="Card2.TFrame")
            row.pack(fill=tk.X, pady=5, padx=5)

            # Left side: Icon, Name
            left = ttk.Frame(row, style="Card2.TFrame")
            left.pack(side=tk.LEFT, fill=tk.Y, padx=15, pady=10)
            ttk.Label(left, text=f"Tab {i+1}", style="TabLabel.TLabel").pack(anchor="w")
            lbl_status = ttk.Label(left, text="IDLE", foreground=STATUS_COLORS["idle"], font=("Segoe UI", 9, "bold"), background=CARD2)
            lbl_status.pack(anchor="w", pady=(2,0))

            # Center: Progress bar
            center = ttk.Frame(row, style="Card2.TFrame")
            center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=10)
            pb = ttk.Progressbar(center, style="Horizontal.TProgressbar", length=100, mode="determinate")
            pb.pack(fill=tk.X, expand=True)

            # Right: Pct
            right = ttk.Frame(row, style="Card2.TFrame")
            right.pack(side=tk.RIGHT, fill=tk.Y, padx=15, pady=10)
            lbl_pct = ttk.Label(right, text="0%", style="TabPct.TLabel", foreground=STATUS_COLORS["idle"])
            lbl_pct.pack(anchor="e")

            self.tab_monitor_frames.append({
                "lbl_status": lbl_status,
                "pb": pb,
                "lbl_pct": lbl_pct
            })

    def _build_output_panel(self, parent):
        f = ttk.Frame(parent, style="Card.TFrame", padding=10)
        f.pack(fill=tk.X, pady=(15,0), padx=5)

        top = ttk.Frame(f, style="Card.TFrame")
        top.pack(fill=tk.X)
        ttk.Label(top, text="Output Directory", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(top, text="Buka Folder", command=self._open_output_dir).pack(side=tk.RIGHT)

        txt_frame = ttk.Frame(f, style="Card.TFrame")
        txt_frame.pack(fill=tk.X, pady=(10,0))
        self.output_list = scrolledtext.ScrolledText(txt_frame, height=4, bg=CARD2, fg=TEXT, 
                                                     font=("Consolas", 9), relief=tk.FLAT)
        self.output_list.pack(fill=tk.X)
        self._refresh_output_folder()

    def _browse_dir(self, string_var):
        d = filedialog.askdirectory()
        if d:
            string_var.set(d)

    def _append_log(self, msg, tag="INFO"):
        self.log_txt.config(state=tk.NORMAL)
        self.log_txt.insert(tk.END, msg + "\n", tag)
        self.log_txt.see(tk.END)
        self.log_txt.config(state=tk.DISABLED)

    def _refresh_output_folder(self):
        self.output_list.config(state=tk.NORMAL)
        self.output_list.delete("1.0", tk.END)
        d = self.var_output_dir.get()
        if os.path.exists(d):
            files = sorted(glob.glob(os.path.join(d, "*.mp4")), key=os.path.getctime, reverse=True)
            if files:
                for f in files[:10]:
                    self.output_list.insert(tk.END, f"📹 {os.path.basename(f)}\n")
            else:
                self.output_list.insert(tk.END, "Belum ada file mp4\n")
        self.output_list.config(state=tk.DISABLED)

    def _open_output_dir(self):
        d = self.var_output_dir.get()
        if os.path.exists(d):
            os.startfile(d)
        else:
            self._append_log("Folder tidak ditemukan", "WARN")

    def _collect_prompts(self):
        res = []
        for txt in self.prompts_text_widgets:
            p = txt.get("1.0", tk.END).strip()
            if p: res.append(p)
        return res

    def _on_generate(self):
        prompts = self._collect_prompts()
        if not prompts:
            messagebox.showwarning("Warning", "Minimal 1 prompt harus diisi!")
            return

        ntabs = self.var_n_tabs.get()
        self._rebuild_tab_rows(ntabs)
        self.cycle_lbl.config(text=f"Siklus: 1 / {self.var_n_cycles.get()}")

        cfg = {
            "n_tabs": ntabs,
            "n_cycles": self.var_n_cycles.get(),
            "tab_bahan_dir": self.var_bahan_dir.get(),
            "output_dir": self.var_output_dir.get(),
            "alternate_image": self.var_chkbx_alt.get(),
            "use_image_all": self.var_chkbx_all.get(),
            "prompts": prompts,
            "debug_port": 9250,
        }

        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self._append_log("=== MEMULAI GENERASI (SELENIUM+JS) ===", "INFO")

        self.engine = AutomationEngine(cfg, self.log_q, self.stat_q)
        self.thread = threading.Thread(target=self.engine.run, daemon=True)
        self.thread.start()

    def _on_stop(self):
        if self.engine:
            self.engine.stop()
            self._append_log("Mengirim sinyal stop...", "WARN")
            self.btn_stop.config(state=tk.DISABLED)

    def _set_idle(self):
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self._refresh_output_folder()

    def _poll_queues(self):
        while not self.log_q.empty():
            msg = self.log_q.get_nowait()
            tag = "INFO"
            if "[ERROR]" in msg: tag = "ERROR"
            elif "[WARN]" in msg: tag = "WARN"
            self._append_log(msg, tag)

        while not self.stat_q.empty():
            msg = self.stat_q.get_nowait()
            if "done" in msg:
                self._append_log("Proses Selesai", "INFO")
                self._set_idle()
            elif "cycle" in msg:
                c = msg["cycle"]
                tc = self.var_n_cycles.get()
                self.cycle_lbl.config(text=f"Siklus: {c} / {tc}")
                # Reset UI tabs for new cycle
                for row in self.tab_monitor_frames:
                    row["pb"]["value"] = 0
                    row["lbl_pct"].config(text="0%", foreground=STATUS_COLORS["idle"])
                    row["lbl_status"].config(text="STARTING", foreground=STATUS_COLORS["idle"])
            elif "tab" in msg:
                idx = msg["tab"]
                pct = msg["pct"]
                sts = msg.get("status", "idle")
                
                if idx < len(self.tab_monitor_frames):
                    ui = self.tab_monitor_frames[idx]
                    ui["pb"]["value"] = pct
                    c = STATUS_COLORS.get(sts, MUTED)
                    ui["lbl_pct"].config(text=f"{pct}%", foreground=c)
                    ui["lbl_status"].config(text=sts.upper(), foreground=c)

        self.after(200, self._poll_queues)

# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = GrokJSApp()
    app.mainloop()
