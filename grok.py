import subprocess
import time
import os
import random
import glob
import re
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION ---
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = r"C:\tiktok_automation\user_data\1"
TAB_BAHAN_DIR = r"C:\tiktok_automation\tab_bahan"
OUTPUT_DIR = r"C:\tiktok_automation\Output"
TARGET_URL = "https://vidabot.markasai.com/generate-grok"

PROMPT_1 = '''INSTRUKSI UMUM – GAYA HIJAB HOKAGE “UWAK” 🎬 Format & Teknis - Durasi: 8 detik per video. - Resolusi: Render 8K ultra-realistis. - Produk yang digunakan: Tab Pro S12 (11,6 inci, visual splash warna-warni, ikon 5G, RAM 16GB, ROM 1024GB). - Desain: ramping, mengkilap, bezel tipis. - Aksesoris: keyboard wireless terpisah, stylus metalik, earphone & charger (unboxing opsional). 🎭 Karakter - Wanita Indonesia cantik dengan hijab modern. - Pakaian: Jubah Hokage (putih-oranye), ikat kepala dengan tulisan “uwak”. - Gaya: percaya diri, ekspresif, aura ninja yang elegan. 🎤 Sulih Suara (VO) - Bahasa: 100% Bahasa Indonesia. - Singkat (maksimal 6-8 kata, selesai ≤2 detik). - Berenergi tinggi, ekspresif, seperti pembawa acara TikTok Live. 🎥 Kamera & Visual - Sudut pandang: track-in/out, orbit, selfie POV, sudut rendah, sinematik dari atas. - Transisi: jepret, cambuk, zoom, glitch elegan. - Efek tematik: api, debu beterbangan, kilauan emas. - Latar belakang: meja kayu kenari, sorotan emas, efek api sinematik. - Warna dominan: hitam, putih gading, kilauan emas + aksen api merah-oranye. 🔊 Audio & Efek - Musik: beat elegan modern + suasana ninja epik. - Efek: desingan api, percikan api, kilauan emas, glitch lembut. - VO: suara manusia asli, cepat, tegas, kuat. 

VIDEO 3 🎥 URUTAN VISUAL (0,0–2,0 detik) Bidikan sudut rendah: karakter Hokage berhijab berdiri dengan percaya diri dengan Tab Pro S12 bersinar di tangan. (2,0–4,0 detik) Partikel api memperlihatkan desain mengkilap yang sangat tipis. (4,0–6,0 detik) Tulisan stylus jarak dekat di layar → guratan kilau keemasan yang halus. (6,0–8,0 detik) Tembakan orbit → tablet melayang di atas meja kenari dengan energi ninja yang luar biasa. 🎤 VO gaya Shopee viral (Bahasa Indonesia) : "Tablet android kenceng tapi cuma sejutaan? Layar OLED, Ram 16 Giga, ROM 1024 Giga! Klik keranjang sekarang sebelum harga balik 3 juta!"


 Jangan ada teks layar. Jangan ada overlay apapun. Jangan ada lip sync'''
PROMPT_2 = '''Instruksi Umum

Bahasa: 100% Bahasa Indonesia untuk VO 

Detail Produk Konsisten:

Tablet Android

Layar 11,6 inci, resolusi 2560×1600

Layar ON: splash screen besar “ANDROID + ikon 5G WiFi, 16GB RAM, 1024GB ROM

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

# Tab Logic: (Prompt Text, Upload Image?)
# Tab 1: P1 + Image
# Tab 2: P1 + No Image
# Tab 3: P2 + Image
# Tab 4: P2 + No Image
# ... Alternating Pattern
TAB_CONFIG = [
    (PROMPT_1, True),   # Tab 1
    (PROMPT_1, False),  # Tab 2
    (PROMPT_2, True),   # Tab 3
    (PROMPT_2, False),  # Tab 4
    (PROMPT_1, True),   # Tab 5
    (PROMPT_1, False),  # Tab 6
    (PROMPT_2, True),   # Tab 7
    (PROMPT_2, False),  # Tab 8
    (PROMPT_1, True),   # Tab 9
    (PROMPT_1, False),  # Tab 10
]

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def get_next_filename():
    """Returns the next sequential filename: 1.mp4, 2.mp4, etc."""
    # Cari semua file yang hanya berupa angka.mp4
    files = glob.glob(os.path.join(OUTPUT_DIR, "*.mp4"))
    max_num = 0
    pattern = re.compile(r'(\d+)\.mp4')
    
    for f in files:
        basename = os.path.basename(f)
        match = pattern.fullmatch(basename) # Pakai fullmatch agar tidak match 'video_1.mp4'
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num
    
    return f"{max_num + 1}.mp4"

def get_random_image():
    if not os.path.exists(TAB_BAHAN_DIR):
        return None
    files = [f for f in os.listdir(TAB_BAHAN_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    if not files:
        return None
    choice = random.choice(files)
    return os.path.join(TAB_BAHAN_DIR, choice)

def buka_chrome_debug():
    print("Mencoba membuka Chrome dalam mode debug...")
    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port=9222",
        f"--user-data-dir={USER_DATA_DIR}"
    ]
    subprocess.Popen(cmd)
    time.sleep(3)

def jalankan_selenium():
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        print("Selenium berhasil terhubung ke Chrome!")
        
        # Set download directory using CDP
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": OUTPUT_DIR
        })
        
        return driver
    except Exception as e:
        print(f"Gagal menghubungkan Selenium: {e}")
        return None

def setup_10_tabs(driver):
    print("Menyiapkan 10 Tab...")
    while len(driver.window_handles) < 10:
        driver.switch_to.new_window('tab')
        driver.get(TARGET_URL)
        time.sleep(0.5)
        
    # Ensure all tabs are on correct URL
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        if TARGET_URL not in driver.current_url:
             driver.get(TARGET_URL)
    
    print(f"Total Tab: {len(driver.window_handles)}")

def do_generate_task(driver, prompt_text, use_image):
    """Fills prompt, uploads image (if needed), logs in (if needed), clicks Generate."""
    wait = WebDriverWait(driver, 10)
    
    # Cek login dulu
    if "login" in driver.current_url:
        print("Terdeteksi halaman login, mencoba login otomatis...")
        try:
             # Simple login handler
             email = wait.until(EC.element_to_be_clickable((By.ID, "data.email")))
             email.clear()
             email.send_keys("oktavandigamer2@gmail.com")
             
             pw = wait.until(EC.element_to_be_clickable((By.ID, "data.password")))
             pw.clear()
             pw.send_keys("oktavandi111111")
             
             btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']")))
             btn.click()
             time.sleep(3)
        except:
             pass

    # 1. Fill Prompt
    try:
        print(f"Mengisi prompt: {prompt_text}")
        prompt_area = wait.until(EC.element_to_be_clickable((By.ID, "promptInput")))
        prompt_area.clear()
        driver.execute_script("arguments[0].value = arguments[1];", prompt_area, prompt_text)
        driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", prompt_area)
    except Exception as e:
        print(f"Gagal isi prompt: {e}")
        return

    # 2. Upload Image
    if use_image:
        img = get_random_image()
        if img:
            try:
                print(f"Upload gambar: {os.path.basename(img)}")
                image_input = driver.find_element(By.ID, "imageInput")
                image_input.send_keys(img)
                time.sleep(1)
            except Exception as e:
                print(f"Gagal upload gambar: {e}")
    
    # 3. Click Generate
    try:
        print("Klik Generate...")
        generate_btn = wait.until(EC.element_to_be_clickable((By.ID, "btnGenerate")))
        generate_btn.click()
    except Exception as e:
        print(f"Gagal klik generate: {e}")

def wait_and_download(driver):
    """Waits for video, downloads it, saves with sequential ID."""
    wait = WebDriverWait(driver, 180) # timeout 3 menit per tab jika perlu
    
    print("Menunggu video ready...")
    try:
        while True:
            try:
                # Cek label progress
                progress = driver.find_element(By.ID, "progressLabel").text
                if "Video ready" in progress:
                    break
            except:
                pass
            
            try:
                # Cek tombol download visible
                dl_btn = driver.find_element(By.ID, "btnDownload")
                if dl_btn.is_displayed():
                    break
            except:
                pass
                
            time.sleep(3)
            
        # Download Steps
        print("Video ready, memulai download...")
        download_btn = wait.until(EC.element_to_be_clickable((By.ID, "btnDownload")))
        download_url = download_btn.get_attribute("href")
        
        if download_url:
            filename = get_next_filename()
            save_path = os.path.join(OUTPUT_DIR, filename)
            
            # Requests Download Logic
            s = requests.Session()
            for cookie in driver.get_cookies():
                s.cookies.set(cookie['name'], cookie['value'])
            
            user_agent = driver.execute_script("return navigator.userAgent;")
            s.headers.update({"User-Agent": user_agent, "Referer": "https://vidabot.markasai.com/"})
            
            # Try direct
            success = False
            try:
                r = s.get(download_url, stream=True, timeout=10)
                ct = r.headers.get("Content-Type", "")
                if 'video' in ct:
                    with open(save_path, 'wb') as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    success = True
                    print(f"Download OK: {filename}")
            except:
                pass
                
            # Fallback Selenium Extraction
            if not success:
               print("Fallback Selenium Extraction...")
               driver.execute_script(f"window.open('{download_url}', '_blank');")
               driver.switch_to.window(driver.window_handles[-1])
               try:
                   vid = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "video")))
                   src = vid.get_attribute("src")
                   if not src:
                       src = vid.find_element(By.TAG_NAME, "source").get_attribute("src")
                   
                   if src:
                       r = s.get(src, stream=True)
                       with open(save_path, 'wb') as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                       print(f"Download OK (Fallback): {filename}")
               except Exception as e:
                   print(f"Gagal download fallback: {e}")
               
               driver.close()
               driver.switch_to.window(driver.window_handles[0]) # WARNING: context depends on caller loop logic
               # We need to handle window switching carefully in the loop
               
    except Exception as e:
        print(f"Error wait/download: {e}")

    # Regenerate
    try:
        print("Klik Generate Again...")
        # Mencari tombol dengan onclick="generateVideo()"
        regen_btn = driver.find_element(By.CSS_SELECTOR, "button[onclick='generateVideo()']")
        regen_btn.click()
    except Exception as e:
        print(f"Gagal klik generate again: {e}")

if __name__ == "__main__":
    n_siklus = int(input("Mau berapa siklus? "))
    
    buka_chrome_debug()
    driver = jalankan_selenium()
    
    if driver:
        setup_10_tabs(driver)
        handles = driver.window_handles
        
        # --- PHASE 1: INITIAL GENERATION ---
        print("\n=== MEMULAI INITIAL GENERATION ===")
        for i in range(10):
            # Safety check handle count
            if i >= len(driver.window_handles): break
            
            driver.switch_to.window(driver.window_handles[i])
            print(f"--- Processing Tab {i+1} ---")
            
            cfg = TAB_CONFIG[i] # (Prompt, ImageBool)
            
            # Check if we need to Generate Again or Fresh Start?
            # First run is always Fresh Start logic (fill prompt)
            do_generate_task(driver, cfg[0], cfg[1])
            time.sleep(2) # Jeda antar tab
            
        # --- PHASE 2: CYCLE LOOP (Wait, Download, Regen) ---
        for cycle in range(n_siklus):
            start_cycle_time = time.time()
            print(f"\n=== SIKLUS KE-{cycle+1} (MENUNGGU & DOWNLOAD) ===")
            
            # Helper to manage closed tabs
            # We track indices that need to be restarted in a fresh tab
            tabs_to_restart = [] # List of config indices (0-9) that failed and need restart

            # Iterate all tabs to harvest results
            # Note: We iterate by index 0..9. We must map this to actual window handles.
            # Since some might be closed, this mapping gets tricky.
            # BETTER STRATEGY: 
            # We maintain a list of 'active_handles' corresponding to tasks 0..9
            # If a task failed, its handle is set to None.
            # At end of cycle, we respawn handles for None entries.
            
            if cycle == 0:
                 # Initialize tracking list on first cycle
                 # task_handles[i] = handle_string or None
                 task_handles = [None] * 10
                 current_all = driver.window_handles
                 for i in range(10):
                     if i < len(current_all):
                         task_handles[i] = current_all[i]
            
            for i in range(10):
                handle = task_handles[i]
                if not handle:
                    print(f"--- Tab {i+1} (Closed/Failed) --- Skipping wait.")
                    continue
                
                # Switch to tab
                try:
                    driver.switch_to.window(handle)
                except:
                    print(f"--- Tab {i+1} tidak ditemukan (mungkin sudah tertutup) ---")
                    task_handles[i] = None
                    continue

                print(f"--- Tab {i+1}: Menunggu Selesai ---")
                
                wait = WebDriverWait(driver, 180)
                download_success = False
                tab_failed = False
                
                try:
                    # Wait Loop with Error Checking
                    start_wait = time.time()
                    last_percent = ""
                    
                    while time.time() - start_wait < 300: # 5 min limit
                        # 0. Cek & Tampilkan Progress
                        try:
                            p_elem = driver.find_element(By.ID, "progressPercent")
                            p_text = p_elem.text
                            if p_text != last_percent:
                                print(f"Tab {i+1} Progress: {p_text}   ", end='\r')
                                last_percent = p_text
                        except:
                            pass

                        # 1. Cek Sukses
                        try:
                            if "Video ready" in driver.find_element(By.ID, "progressLabel").text: 
                                print(f"\nTab {i+1} Video Ready!")
                                break
                        except: pass
                        try:
                            if driver.find_element(By.ID, "btnDownload").is_displayed(): 
                                print(f"\nTab {i+1} Download Button Visible!")
                                break
                        except: pass
                        
                        # 2. Cek Error Log
                        try:
                            debug_div = driver.find_element(By.ID, "debugLog")
                            logs = debug_div.get_attribute("innerText") # atau text
                            # Cek indikator failure
                            if "Switching worker" in logs or "7 failed" in logs or "12 failed" in logs:
                                print(f"\nDETEKSI ERROR pada Tab {i+1}: Worker Failed / Switching Worker.")
                                tab_failed = True
                                break
                        except:
                            pass
                            
                        time.sleep(1) # Cek lebih cepat (1 detik) untuk responsivitas progress
                    
                    if tab_failed:
                        print(f"Tab {i+1} dianggap GAGAL. Menutup tab...")
                        driver.close()
                        task_handles[i] = None # Mark as closed
                        continue # Lanjut ke tab berikutnya
                    
                    # Jika timeout 5 menit belum selesai juga?
                    if time.time() - start_wait >= 300:
                         print(f"Tab {i+1} Timeout menunggu video. Skip dulu.")
                         continue

                    # Download Logic
                    dl_btn = wait.until(EC.element_to_be_clickable((By.ID, "btnDownload")))
                    dl_url = dl_btn.get_attribute("href")
                    
                    filename = get_next_filename()
                    save_path = os.path.join(OUTPUT_DIR, filename)
                    print(f"Download URL: {dl_url}")
                    
                    # Attempt Download
                    s = requests.Session()
                    for c in driver.get_cookies(): s.cookies.set(c['name'], c['value'])
                    user_agent = driver.execute_script("return navigator.userAgent;")
                    s.headers.update({"User-Agent": user_agent, "Referer": "https://vidabot.markasai.com/"})
                    
                    downloaded = False
                    
                    # Try direct
                    try:
                        r = s.get(dl_url, stream=True, timeout=10)
                        if 'video' in r.headers.get("Content-Type", ""):
                            with open(save_path, 'wb') as f:
                                for chunk in r.iter_content(8192): f.write(chunk)
                            downloaded = True
                            print(f"Saved: {filename}")
                    except Exception as e:
                        print(f"Direct fail: {e}")
                        
                    if not downloaded:
                        # Fallback
                        print("Fallback extraction...")
                        main_tab = driver.current_window_handle
                        driver.execute_script(f"window.open('{dl_url}', '_blank');")
                        # Switch to new tab
                        # Helper to find new tab: it is the one NOT in task_handles (mostly)
                        # or just compare len
                        all_handles_now = driver.window_handles
                        new_tab = [h for h in all_handles_now if h != main_tab][-1]
                        
                        driver.switch_to.window(new_tab)
                        
                        try:
                            vid = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "video")))
                            src = vid.get_attribute("src")
                            if not src: src = vid.find_element(By.TAG_NAME, "source").get_attribute("src")
                            
                            if src:
                                r = s.get(src, stream=True)
                                with open(save_path, 'wb') as f:
                                    for chunk in r.iter_content(8192): f.write(chunk)
                                print(f"Saved (Fallback): {filename}")
                        except Exception as e:
                            print(f"Fallback fail: {e}")
                        
                        driver.close()
                        driver.switch_to.window(main_tab)
                    
                    # REGENERATE logic
                    print("Mencoba klik Generate Again...")
                    try:
                        regen_xpath = "//button[contains(text(), 'Generate Again') or contains(@onclick, 'generateVideo')]"
                        regen_btn = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, regen_xpath))
                        )
                        driver.execute_script("arguments[0].scrollIntoView(true);", regen_btn)
                        time.sleep(0.5)
                        try:
                            regen_btn.click()
                        except:
                            driver.execute_script("arguments[0].click();", regen_btn)
                        print("Regenerate clicked.")
                    except Exception as e:
                        print(f"Buttons regenerate not found/clickable ({e})")
                        # Jika tidak bisa klik regenerate, mungkin perlu ditandai? 
                        # Atau biarkan saja, nanti dia stuck atau manual fix.
                    
                except Exception as e:
                    print(f"Error proccessing tab {i+1}: {e}")
            
            # --- END OF CYCLE REVIEW ---
            # Check for failed/closed tabs and respawn them
            print("\n--- Memeriksa tab yang perlu di-restart (Failed/Closed) ---")
            for i in range(10):
                if task_handles[i] is None:
                    print(f"Respawning Tab {i+1}...")
                    driver.switch_to.new_window('tab')
                    new_handle = driver.current_window_handle
                    task_handles[i] = new_handle
                    
                    driver.get(TARGET_URL)
                    time.sleep(2)
                    
                    # Run Task Again
                    cfg = TAB_CONFIG[i]
                    print(f"Generating ulang task untuk Tab {i+1}...")
                    do_generate_task(driver, cfg[0], cfg[1])
                    time.sleep(1)

            elapsed_cycle = time.time() - start_cycle_time
            print(f"Siklus {cycle+1} selesai dalam {int(elapsed_cycle // 60)} menit {int(elapsed_cycle % 60)} detik.")
            
        print("SEMUA SIKLUS SELESAI.")
