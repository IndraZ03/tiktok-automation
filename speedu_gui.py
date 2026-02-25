"""
SPEEDU - All-in-One TikTok Content Pipeline GUI
Integrates: Gemini Content Generation → Video Overlay → TikTok Upload Scheduler
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import json
import os
import sys
import time
import subprocess
import re
import textwrap
import winsound
from datetime import datetime, timedelta

# ── Selenium imports ──
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import psutil

# ═══════════════════════════════════════════════════════════════
#  CONSTANTS & THEME (Modern Bright)
# ═══════════════════════════════════════════════════════════════
BG           = "#F0F4FF"       # Light blue-white
BG_CARD      = "#FFFFFF"       # Clean white
BG_INPUT     = "#E8EDF6"       # Soft blue-grey
FG           = "#1A1D2E"       # Dark navy text
FG_DIM       = "#6B7280"       # Grey description
ACCENT       = "#4F46E5"       # Indigo
ACCENT2      = "#7C3AED"       # Purple
SUCCESS      = "#10B981"       # Emerald green
ERROR        = "#EF4444"       # Red
WARN         = "#F59E0B"       # Amber
BORDER       = "#CBD5E1"       # Slate border
BTN_PRIMARY  = "#4F46E5"       # Indigo button
BTN_FG       = "#FFFFFF"
BTN_HOVER    = "#6366F1"
BTN_SUCCESS  = "#10B981"
BTN_ORANGE   = "#F97316"
BTN_DANGER   = "#EF4444"
CARD_SHADOW  = "#D1D5DB"

BASE_DIR     = r"c:\tiktok_automation"
JSON_PATH    = os.path.join(BASE_DIR, "konten_gemini.json")
OVERLAY_DIR  = os.path.join(BASE_DIR, "konten_final_overlay")
WATERMARK    = os.path.join(BASE_DIR, "speedu.png")

STOK_MINIMUM = 12  # Minimal konten yg dibutuhkan
VIDEO_COUNT  = 12  # Jumlah video yg diproses per batch

# ═══════════════════════════════════════════════════════════════
#  GEMINI GENERATOR (from gemini_generator.py)
# ═══════════════════════════════════════════════════════════════
def get_clipboard_text():
    import tkinter as _tk
    root = _tk.Tk(); root.withdraw()
    try: result = root.clipboard_get()
    except _tk.TclError: result = ""
    root.destroy(); return result

def set_clipboard_text(text):
    import tkinter as _tk
    root = _tk.Tk(); root.withdraw()
    root.clipboard_clear(); root.clipboard_append(text)
    root.update(); root.destroy()

PROMPT_TEXT = """kamu adalah expert content creator spesialis video pendek 30 detik (TikTok/Reels/Shorts) tentang persiapan masuk Sekolah Kedinasan. Tugasmu: Buat output **HANYA** berupa array JSON valid yang berisi tepat 2 objek JSON. Jangan tambahkan satu kata pun di luar array JSON. Contoh struktur output: [ {json1}, {json2} ] Struktur setiap JSON persis seperti ini: {   "topik": "Judul topik yang menarik",   "tulisan 1": "Teks overlay 1 (hook kuat)",   "tulisan 2": "Teks overlay 2",   "tulisan 3": "Teks overlay 3",   "tulisan 4": "Teks overlay 4",   "tulisan 5": "Teks overlay 5",   "tulisan 6": "Teks overlay 6 (penutup + CTA)" } Aturan wajib:

Pilih DUA topik SECARA ACAK dan BERBEDA setiap kali dari 7 ini:   1. tips skd → jadikan topik: "Tips SKD Kedinasan"   2. tips persiapan fisik masuk sekolah kedinasan → jadikan topik: "Tips Persiapan Fisik Masuk Sekolah Kedinasan"   3. tips masuk sekolah kedinasan → jadikan topik: "Tips Masuk Sekolah Kedinasan"   4. tips belajar sekolah kedinasan → jadikan topik: "Tips Belajar Sekolah Kedinasan"   5. tips skb stmkg → jadikan topik: "Tips SKB STMKG"   6. benefit menjadi lulusan stmkg dan asn bmkg → jadikan topik: "Benefit Menjadi Lulusan Sekolah Kedinasan STMKG dan ASN BMKG"   7. tips tes wawancara sekolah kedinasan → jadikan topik: "Tips Tes Wawancara Sekolah Kedinasan"
Buat tepat 6 tulisan per JSON (cocok untuk 30 detik dengan fade in/out, masing-masing tampil ±5 detik untuk konten lebih panjang).
Semua teks dalam Bahasa Indonesia yang santai, memotivasi, mudah dibaca besar di video. Tulisan JANGAN DIBERIKAN EMOTICON. CUKUP TULISAN
Tulisan 1 = Hook yang bikin orang berhenti scroll, dengan detail awal.
Tulisan 2-5 = Isi tips paling penting & actionable, dengan penjelasan lebih panjang dan contoh spesifik.
Tulisan 6 = Ringkasan lengkap + strong CTA (contoh: \u201cSimpan video ini! Comment 'MAU' kalau mau part 2, Follow untuk tips harian, dan share ke temanmu!\u201d).
Setiap tulisan lebih detail (maksimal 250-300 karakter) supaya konten agak panjang tapi tetap readable di layar. Generate array JSON sekarang!"""


def run_gemini_generate(num_loops, log_fn, stop_event, headless=False, prompt_text=None, user_data_dir=None, port="9222"):
    if prompt_text is None:
        prompt_text = PROMPT_TEXT
    """Generate konten tulisan via Gemini browser automation."""
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if user_data_dir is None:
        user_data_dir = os.path.join(BASE_DIR, "user_data", "1")
    
    log_fn(f"Membuka Chrome untuk Gemini (port {port})...", "info")
    cmd = [chrome_path, f"--remote-debugging-port={port}", f"--user-data-dir={user_data_dir}"]
    if headless: 
        cmd.extend([
            "--headless=new", 
            "--window-size=1920,1080",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ])
    proc = subprocess.Popen(cmd)
    time.sleep(4)
    
    # Connect Selenium
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)
    log_fn("Chrome terhubung!", "success")
    
    driver.get("https://gemini.google.com/")
    wait = WebDriverWait(driver, 30)
    wait_long = WebDriverWait(driver, 180)
    action = ActionChains(driver)
    
    db_data = []
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                db_data = json.load(f)
        except: pass
    
    MAX_RETRIES = 3  # Maks retry per loop jika parse gagal
    success_count = 0
    retry_count = 0
    
    while success_count < num_loops:
        if stop_event.is_set():
            log_fn("Generate dihentikan.", "warn"); break
        
        is_retry = retry_count > 0
        if is_retry:
            log_fn(f"  Retry {retry_count}/{MAX_RETRIES} untuk loop {success_count+1}...", "warn")
        else:
            log_fn(f"Loop generate {success_count+1}/{num_loops}...", "info")
        
        try:
            textarea = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//div[contains(@class, 'ql-editor')]")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", textarea)
            time.sleep(1)
            
            try:
                textarea.click(); time.sleep(0.5)
                textarea.send_keys(Keys.CONTROL, "a"); time.sleep(0.2)
                textarea.send_keys(Keys.BACK_SPACE); time.sleep(0.2)
                set_clipboard_text(prompt_text)
                textarea.send_keys(Keys.CONTROL, "v"); time.sleep(1)
            except Exception as e:
                # Fallback to JS if element not interactable (e.g., in headless)
                driver.execute_script("arguments[0].focus(); arguments[0].textContent = '';", textarea)

            if len(textarea.text.strip()) < 10 or prompt_text[:20] not in textarea.text:
                driver.execute_script("arguments[0].focus(); document.execCommand('insertText', false, arguments[1]);", textarea, prompt_text)
                driver.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", textarea)
            
            try:
                time.sleep(1); textarea.send_keys(" ")
            except:
                driver.execute_script("arguments[0].dispatchEvent(new KeyboardEvent('keydown', {'key':' '}));", textarea)
            
            send_xpath = "//button[contains(@class, 'send-button')]"
            send_btn = wait.until(EC.presence_of_element_located((By.XPATH, send_xpath)))
            
            try:
                send_btn.click()
            except:
                driver.execute_script("arguments[0].click();", send_btn)
                
            log_fn("Prompt dikirim, menunggu generate...", "info")
            time.sleep(5)
            try:
                WebDriverWait(driver, 120).until_not(
                    EC.presence_of_element_located((By.XPATH, "//div[@aria-busy='true']"))
                )
            except Exception as e:
                log_fn("Menunggu batas waktu habis, lanjut proses.", "warn")
            log_fn("Generate selesai!", "success"); time.sleep(3)
            
            # Copy result
            clipboard_result = ""
            try:
                responses = driver.find_elements(By.XPATH, "//div[contains(@class,'message-content')] | //model-response")
                if responses:
                    action.move_to_element(responses[-1]).perform(); time.sleep(1)
                copy_btns = driver.find_elements(By.XPATH,
                    "//button[descendant::mat-icon[@data-mat-icon-name='content_copy'] or @mattooltip='Copy' or contains(@aria-label,'Copy') or contains(@aria-label,'Salin')]")
                if copy_btns:
                    set_clipboard_text("")
                    try: action.move_to_element(copy_btns[-1]).click().perform()
                    except: driver.execute_script("arguments[0].click();", copy_btns[-1])
                    time.sleep(1.5)
                    clipboard_result = get_clipboard_text()
            except: pass
            
            if not clipboard_result or "{" not in clipboard_result:
                # Fallback to direct DOM extraction since clipboard API might fail in Headless
                panels = driver.find_elements(By.XPATH, "//div[contains(@class,'markdown-main-panel')]")
                if panels: 
                    clipboard_result = driver.execute_script("return arguments[0].innerText;", panels[-1])
                else:
                    responses = driver.find_elements(By.XPATH, "//div[contains(@class,'message-content')] | //model-response")
                    if responses: 
                        clipboard_result = driver.execute_script("return arguments[0].innerText;", responses[-1])
                        
                if not clipboard_result:
                    clipboard_result = driver.execute_script("return document.body.innerText;")
            
            # Parse JSON
            hasil_json = None
            match = re.search(r'\[.*\]', clipboard_result, re.DOTALL)
            if not match: match = re.search(r'\{.*\}', clipboard_result, re.DOTALL)
            if match:
                json_str = match.group(0).replace('```json', '').replace('```', '').strip()
                # Fix trailing commas inside JSON objects/arrays
                json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
                # Fix incomplete JSON that got cut off by adding '}]' if needed
                if json_str.count('[') > json_str.count(']'):
                    if not json_str.endswith('}'):
                        json_str += '"\n}'
                    json_str += '\n]'
                
                try: hasil_json = json.loads(json_str)
                except: pass
            
            if isinstance(hasil_json, list):
                # Validasi: pastikan setiap item punya tulisan 1
                valid_items = [item for item in hasil_json if "tulisan 1" in item and "topik" in item]
                if valid_items:
                    for item in valid_items:
                        item['nomor'] = len(db_data) + 1; db_data.append(item)
                    log_fn(f"  +{len(valid_items)} konten ditambahkan", "success")
                    success_count += 1; retry_count = 0
                else:
                    log_fn("  JSON ada tapi isinya tidak valid (tidak ada tulisan/topik)", "warn")
                    retry_count += 1
            elif isinstance(hasil_json, dict):
                if "tulisan 1" in hasil_json and "topik" in hasil_json:
                    hasil_json['nomor'] = len(db_data) + 1; db_data.append(hasil_json)
                    log_fn("  +1 konten ditambahkan", "success")
                    success_count += 1; retry_count = 0
                else:
                    log_fn("  JSON ada tapi isinya tidak valid (tidak ada tulisan/topik)", "warn")
                    retry_count += 1
            else:
                log_fn("  Parse JSON gagal, akan retry generate ulang...", "warn")
                retry_count += 1
            
            # Simpan hanya jika ada data valid baru
            with open(JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(db_data, f, indent=4, ensure_ascii=False)
            
            # Jika sudah retry maksimal, skip loop ini
            if retry_count >= MAX_RETRIES:
                log_fn(f"  Sudah {MAX_RETRIES}x retry gagal, skip loop ini.", "error")
                success_count += 1; retry_count = 0
            
        except Exception as e:
            log_fn(f"  Error loop {success_count+1}: {e}", "error")
            retry_count += 1
            if retry_count >= MAX_RETRIES:
                log_fn(f"  Sudah {MAX_RETRIES}x error, skip loop ini.", "error")
                success_count += 1; retry_count = 0
    
    # Close Chrome
    for conn in psutil.net_connections(kind='tcp'):
        if conn.laddr.port == int(port) and conn.status == 'LISTEN':
            try: psutil.Process(conn.pid).terminate()
            except: pass; break
    
    return len(db_data)


# ═══════════════════════════════════════════════════════════════
#  VIDEO OVERLAY (from video_overlay.py)
# ═══════════════════════════════════════════════════════════════
FONT_NAME = "Arial"
FONT_SIZE = 75
FADE_DURATION_MS = 500
TULISAN_DURATION = 5
WATERMARK_SCALE = 250
WATERMARK_MARGIN_TOP = 25
MAX_CHARS_PER_LINE = 20

def strip_emoji(text):
    emoji_pattern = re.compile(
        u"(\ud83d[\ude00-\ude4f])|"
        u"(\ud83c[\udf00-\uffff])|"
        u"(\ud83d[\u0000-\uddff])|"
        u"(\ud83d[\ude80-\udeff])|"
        u"(\ud83c[\udde0-\uddff])|"
        u"[\U00010000-\U0010ffff]|"
        u"[\u2600-\u2B55]|"
        u"[\u2300-\u23FF]"
    )
    return ' '.join(emoji_pattern.sub(r'', text).split()).strip()

def seconds_to_ass(s):
    h = int(s // 3600); m = int((s % 3600)//60); sec = int(s%60); cs = int((s%1)*100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

# Resolusi referensi tetap untuk ASS subtitle
# libass otomatis menyesuaikan skala ke resolusi video asli
REF_W, REF_H = 1080, 1920

def generate_ass(tulisan_list):
    y = int(REF_H * 0.55); x = REF_W // 2
    ass = f"""[Script Info]
Title: Konten Overlay
ScriptType: v4.00+
PlayResX: {REF_W}
PlayResY: {REF_H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Overlay,{FONT_NAME},{FONT_SIZE},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,1,0,0,0,100,100,0,0,3,25,0,5,30,30,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    for idx, t in enumerate(tulisan_list):
        s_t = idx*TULISAN_DURATION; e_t = s_t + TULISAN_DURATION
        clean = strip_emoji(t)
        lines = textwrap.wrap(clean, width=MAX_CHARS_PER_LINE)
        text = "\\N".join(lines)
        ass += f"Dialogue: 0,{seconds_to_ass(s_t)},{seconds_to_ass(e_t)},Overlay,,0,0,0,,{{\\fad({FADE_DURATION_MS},{FADE_DURATION_MS})\\pos({x},{y})}}{text}\n"
    return ass

def overlay_video(video_path, konten_nomor, output_path, log_fn):
    """Overlay teks + watermark ke video. Returns True on success."""
    # Load konten
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    konten = None
    for item in data:
        if item.get("nomor") == konten_nomor:
            konten = item; break
    if not konten:
        log_fn(f"Konten nomor {konten_nomor} tidak ditemukan!", "error"); return False
    
    tulisan_list = [konten[f"tulisan {i}"] for i in range(1,7) if f"tulisan {i}" in konten]
    if not tulisan_list:
        log_fn("Tidak ada tulisan di konten!", "error"); return False
    
    topik = konten.get("topik", "?")
    log_fn(f"  Topik: {topik}", "info")
    
    # Generate ASS subtitle (resolusi referensi tetap 1080x1920, libass auto-scale)
    ass_content = generate_ass(tulisan_list)
    os.makedirs(OVERLAY_DIR, exist_ok=True)
    ass_file = os.path.join(OVERLAY_DIR, f"temp_{konten_nomor}.ass")
    with open(ass_file, "w", encoding="utf-8") as f:
        f.write(ass_content)
    
    ass_esc = ass_file.replace("\\", "/").replace(":", "\\:")
    fc = (f"[0:v]ass='{ass_esc}'[texted];"
          f"[1:v]scale={WATERMARK_SCALE}:-1[wm];"
          f"[texted][wm]overlay=(W-w)/2:{WATERMARK_MARGIN_TOP}")
    
    cmd = ["ffmpeg", "-y", "-i", video_path, "-i", WATERMARK,
           "-filter_complex", fc, "-c:v", "libx264", "-crf", "18",
           "-preset", "slow", "-c:a", "copy", "-map", "0:a?", output_path]
    
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    try: os.remove(ass_file)
    except: pass
    
    if proc.returncode != 0:
        err = proc.stderr.decode('utf-8', errors='ignore').split('\n')
        for line in err[-5:]: log_fn(f"  FFmpeg: {line.strip()}", "error")
        return False
    return True


# ═══════════════════════════════════════════════════════════════
#  TIKTOK UPLOAD (from tiktok_gui.py - simplified, no product/switches/sound)
# ═══════════════════════════════════════════════════════════════
def open_chrome_debug(user_data_dir, port, headless=False):
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    cmd = [chrome_path, f"--remote-debugging-port={port}", f"--user-data-dir={user_data_dir}"]
    if headless: cmd.extend(["--headless=new", "--window-size=1920,1080"])
    proc = subprocess.Popen(cmd)
    time.sleep(5); return proc

def connect_selenium(port):
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    svc = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=svc, options=opts)

def navigate_upload_page(driver, force=False):
    if force or "tiktok.com/tiktokstudio/upload" not in driver.current_url:
        driver.get("https://www.tiktok.com/tiktokstudio/content"); time.sleep(3)
        driver.get("https://www.tiktok.com/tiktokstudio/upload"); time.sleep(5)
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
    except:
        driver.refresh(); time.sleep(5)

def do_upload_file(driver, file_path, log_fn):
    wait = WebDriverWait(driver, 30)
    log_fn("  Mencari elemen upload...", "info")
    inp = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
    inp.send_keys(file_path)
    log_fn(f"  File diupload: {os.path.basename(file_path)}", "success")
    time.sleep(3)
    
    # Tunggu sampai upload selesai (progress 100%)
    log_fn("  Menunggu upload selesai...", "info")
    max_wait = 600  # Maksimal 10 menit
    start = time.time()
    last_pct = ""
    while time.time() - start < max_wait:
        try:
            # Cek apakah ada progress indicator upload
            progress_els = driver.find_elements(By.XPATH,
                "//div[contains(@class, 'info-progress-num')]")
            if progress_els and progress_els[0].is_displayed():
                pct_text = progress_els[0].text.strip()
                if pct_text != last_pct:
                    log_fn(f"  Upload: {pct_text}", "info")
                    last_pct = pct_text
                time.sleep(2)
                continue
            
            # Cek apakah masih ada indikator uploading (icon CloudUpload + MB text)
            uploading = driver.find_elements(By.XPATH,
                "//div[@data-e2e='upload_status_container']//span[@data-icon='CloudUpload']")
            if uploading:
                time.sleep(2)
                continue
            
            # Tidak ada progress indicator = upload selesai
            break
        except:
            time.sleep(2)
    
    log_fn("  Upload selesai!", "success")
    time.sleep(3)

def do_post_tiktok(driver, deskripsi, schedule_dt, log_fn):
    """Post to TikTok - simplified: no product, no switches, no sound."""
    wait = WebDriverWait(driver, 20)
    
    # Turn on
    try:
        turn_on = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
            (By.XPATH, "//div[contains(@class, 'Button__content') and text()='Turn on']")))
        turn_on.click(); time.sleep(2)
    except: pass
    
    # Description
    log_fn("  Mengisi deskripsi...", "info")
    caption = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//div[@role='textbox'] | //div[contains(@class, 'notranslate public-DraftEditor-content')]")))
    caption.click()
    caption.send_keys(Keys.CONTROL + "a"); caption.send_keys(Keys.BACKSPACE)
    caption.send_keys(deskripsi); time.sleep(1)
    
    # ── Content Check Lite ── Jika toggle ON, klik agar menjadi OFF
    try:
        log_fn("  Memeriksa Content Check Lite...", "info")
        # Cari switch Content Check Lite yang sedang checked (ON)
        # Indikator: div dengan class Switch__root--checked-true di dekat headline 'Content check lite'
        checked_switches = driver.find_elements(
            By.XPATH,
            "//span[contains(text(),'Content check lite')]"
            "/ancestor::div[contains(@class,'jsx-')]"
            "//div[contains(@class,'Switch__root--checked-true')]"
            "//input[@role='switch']"
        )
        if not checked_switches:
            # Fallback: cari semua switch input yang checked (aria-checked="true")
            checked_switches = driver.find_elements(
                By.XPATH,
                "//div[@aria-checked='true' and contains(@class,'Switch__content')]"
                "/ancestor::div[contains(@class,'Switch__root')]"
                "//input[@role='switch']"
            )
        if checked_switches:
            switch_input = checked_switches[0]
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", switch_input)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", switch_input)
            time.sleep(1)
            log_fn("  Content Check Lite dimatikan.", "success")
        else:
            log_fn("  Content Check Lite sudah OFF atau tidak ditemukan.", "info")
    except Exception as e:
        log_fn(f"  Warning Content Check Lite: {e}", "warn")
    
    # ── Schedule ──
    log_fn("  Mengatur schedule...", "info")
    WebDriverWait(driver, 15).until(EC.presence_of_element_located(
        (By.XPATH, "//*[contains(text(),'When to post')]")))
    time.sleep(1)
    
    sr = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//input[@name='postSchedule' and @value='schedule']/ancestor::label")))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sr)
    time.sleep(1); driver.execute_script("arguments[0].click();", sr); time.sleep(2)
    
    # Time picker
    target_hour = f"{schedule_dt.hour:02d}"
    target_min = f"{(schedule_dt.minute // 5) * 5:02d}"
    log_fn(f"  Waktu: {target_hour}:{target_min}", "info")
    
    ti = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//div[contains(@class,'TUXTextInputCore')]//input[@readonly and contains(@value,':')]")))
    driver.execute_script("arguments[0].click();", ti); time.sleep(2)
    
    # Hour
    try:
        hs = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
            (By.XPATH, f"//div[contains(@class,'tiktok-timepicker-time-picker-container')]//span[contains(@class,'tiktok-timepicker-left') and text()='{target_hour}']")))
        hs.click()
    except:
        try:
            hc = driver.find_element(By.XPATH, "//div[contains(@class,'tiktok-timepicker-time-picker-container')]//div[contains(@class,'tiktok-timepicker-time-scroll-container')][1]")
            driver.execute_script("arguments[0].scrollTop=0;", hc); time.sleep(1)
            hs2 = driver.find_element(By.XPATH, f"//span[contains(@class,'tiktok-timepicker-left') and text()='{target_hour}']")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", hs2); time.sleep(.5)
            hs2.click()
        except: pass
    time.sleep(1)
    
    # Minute
    try:
        ms = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
            (By.XPATH, f"//div[contains(@class,'tiktok-timepicker-time-picker-container')]//span[contains(@class,'tiktok-timepicker-right') and text()='{target_min}']")))
        ms.click()
    except:
        try:
            mcs = driver.find_elements(By.XPATH, "//div[contains(@class,'tiktok-timepicker-time-picker-container')]//div[contains(@class,'tiktok-timepicker-time-scroll-container')]")
            if len(mcs) >= 2: driver.execute_script("arguments[0].scrollTop=0;", mcs[1]); time.sleep(1)
            ms2 = driver.find_element(By.XPATH, f"//span[contains(@class,'tiktok-timepicker-right') and text()='{target_min}']")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", ms2); time.sleep(.5)
            ms2.click()
        except: pass
    time.sleep(1)
    driver.execute_script("document.body.click();"); time.sleep(1)
    
    # Date picker
    target_day = str(schedule_dt.day)
    target_date = schedule_dt.strftime("%Y-%m-%d")
    log_fn(f"  Tanggal: {target_date}", "info")
    
    di_list = driver.find_elements(By.XPATH, "//div[contains(@class,'TUXTextInputCore')]//input[@readonly]")
    for di in di_list:
        v = di.get_attribute("value") or ""
        if "-" in v and len(v) == 10 and di.is_displayed():
            driver.execute_script("arguments[0].click();", di); time.sleep(2); break
    
    try:
        month_title = driver.find_element(By.XPATH, "//div[contains(@class,'calendar-wrapper')]//span[contains(@class,'month-title')]")
        cal_month = month_title.text.strip()
        target_month = schedule_dt.strftime("%B")
        while cal_month != target_month:
            arrows = driver.find_elements(By.XPATH, "//div[contains(@class,'calendar-wrapper')]//span[contains(@class,'arrow')]")
            if len(arrows) >= 2: arrows[1].click(); time.sleep(1)
            cal_month = driver.find_element(By.XPATH, "//div[contains(@class,'calendar-wrapper')]//span[contains(@class,'month-title')]").text.strip()
    except: pass
    
    try:
        ds = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
            (By.XPATH, f"//div[contains(@class,'calendar-wrapper')]//span[contains(@class,'day') and contains(@class,'valid') and text()='{target_day}']")))
        ds.click()
    except:
        try:
            spans = driver.find_elements(By.XPATH, "//div[contains(@class,'calendar-wrapper')]//span[contains(@class,'day')]")
            for s in spans:
                if s.text.strip() == target_day and s.is_displayed():
                    if "header" not in (s.get_attribute("class") or ""): s.click(); break
        except: pass
    time.sleep(2)
    log_fn("  Schedule diatur!", "success")
    
    # Schedule button
    log_fn("  Klik Schedule...", "info"); time.sleep(2)
    try:
        sch = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
            (By.XPATH, "//button[@data-e2e='post_video_button' and .//div[contains(text(),'Schedule')]]")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sch)
        time.sleep(1); driver.execute_script("arguments[0].click();", sch)
    except:
        try:
            sch2 = driver.find_element(By.XPATH, "//button[contains(@class,'type-primary') and .//div[contains(text(),'Schedule')]]")
            driver.execute_script("arguments[0].click();", sch2)
        except:
            all_btns = driver.find_elements(By.XPATH, "//button")
            for b in all_btns:
                try:
                    if b.text.strip() == "Schedule" and b.is_displayed():
                        driver.execute_script("arguments[0].click();", b); break
                except: continue
    
    # Confirm
    try:
        cb = WebDriverWait(driver, 7).until(EC.element_to_be_clickable(
            (By.XPATH, "//button[.//div[text()='Schedule' or text()='Confirm']]")))
        driver.execute_script("arguments[0].click();", cb)
    except: pass
    
    log_fn("  Video berhasil di-schedule!", "success"); time.sleep(3)


# ═══════════════════════════════════════════════════════════════
#  GUI APPLICATION
# ═══════════════════════════════════════════════════════════════
class SpeeduApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SPEEDU - Content Pipeline")
        self.root.configure(bg=BG)
        self.root.state("zoomed")
        
        self.stop_event = threading.Event()
        self.running = False
        self.start_time = None
        self._progress_current = 0
        self._progress_total = 0
        self._last_step_time = None  # Waktu saat step terakhir selesai
        
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Card.TFrame", background=BG_CARD)
        style.configure("TLabel", background=BG_CARD, foreground=FG, font=("Segoe UI", 10))
        style.configure("Green.Horizontal.TProgressbar", troughcolor=BG_INPUT, background=SUCCESS)
        
        self._build_ui()
    
    def _build_ui(self):
        # ═══ HEADER ═══
        hdr = tk.Frame(self.root, bg=ACCENT, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚡ SPEEDU", bg=ACCENT, fg="white",
                 font=("Segoe UI", 24, "bold")).pack(side="left", padx=20)
        tk.Label(hdr, text="Content Pipeline  |  Generate → Overlay → Upload",
                 bg=ACCENT, fg="#C7D2FE", font=("Segoe UI", 12)).pack(side="left", padx=10)
        self.timer_label = tk.Label(hdr, text="00:00:00", bg=ACCENT, fg="#FCD34D",
                                    font=("Consolas", 18, "bold"))
        self.timer_label.pack(side="right", padx=20)
        
        # ═══ STOK INFO BAR ═══
        stok_bar = tk.Frame(self.root, bg=BG_CARD, pady=8,
                            highlightbackground=BORDER, highlightthickness=1)
        stok_bar.pack(fill="x", padx=15, pady=(10, 0))
        
        tk.Label(stok_bar, text="📦 Stok:", bg=BG_CARD, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=(15, 10))
        
        self.stok_tulisan_label = tk.Label(stok_bar, text="Tulisan: -", bg=BG_CARD, fg=ACCENT,
                                           font=("Segoe UI", 12, "bold"))
        self.stok_tulisan_label.pack(side="left", padx=(0, 5))
        
        tk.Button(stok_bar, text="🗑", bg=BG_CARD, fg=ERROR, relief="flat",
                  font=("Segoe UI", 10), cursor="hand2", bd=0,
                  command=self._delete_stok_tulisan).pack(side="left", padx=(0, 15))
        
        tk.Label(stok_bar, text="│", bg=BG_CARD, fg=BORDER,
                 font=("Segoe UI", 14)).pack(side="left", padx=5)
        
        self.stok_overlay_label = tk.Label(stok_bar, text="Overlay: -", bg=BG_CARD, fg=BTN_ORANGE,
                                            font=("Segoe UI", 12, "bold"))
        self.stok_overlay_label.pack(side="left", padx=(20, 5))
        
        tk.Button(stok_bar, text="🗑", bg=BG_CARD, fg=ERROR, relief="flat",
                  font=("Segoe UI", 10), cursor="hand2", bd=0,
                  command=self._delete_stok_overlay).pack(side="left", padx=(0, 10))
        
        tk.Button(stok_bar, text="↻ Refresh", bg=BG_INPUT, fg=ACCENT, relief="flat",
                  padx=12, pady=2, font=("Segoe UI", 10, "bold"), cursor="hand2",
                  activebackground=BORDER, command=self._refresh_stok).pack(side="right", padx=15)
        
        # ═══ MAIN CONTAINER ═══
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=15, pady=10)
        main.columnconfigure(0, weight=2)
        main.columnconfigure(1, weight=3)
        main.rowconfigure(0, weight=1)
        
        # ═══ LEFT COLUMN ═══
        left = tk.Frame(main, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        
        self._card(left, "📂 Sumber Video", self._build_source)
        self._card(left, "📝 Deskripsi TikTok", self._build_desc)
        self._card(left, "📅 Schedule", self._build_schedule)
        self._card(left, "🌐 Chrome", self._build_chrome)
        
        # ═══ RIGHT COLUMN ═══
        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        
        self._card(right, "🎮 Aksi", self._build_actions)
        self._card(right, "📊 Progress", self._build_progress, expand=True)
        
        # ═══ BOTTOM BAR ═══
        bot = tk.Frame(self.root, bg=BG, pady=8)
        bot.pack(fill="x")
        self.status_label = tk.Label(bot, text="Status: Idle", bg=BG, fg=FG_DIM,
                                     font=("Segoe UI", 11))
        self.status_label.pack(side="left", padx=20)
        
        self._refresh_stok()
    
    # ── UI Helpers ──
    def _card(self, parent, title, builder_fn, expand=False):
        frame = tk.LabelFrame(parent, text=f"  {title}  ", bg=BG_CARD, fg=ACCENT,
                               font=("Segoe UI", 11, "bold"), bd=0, relief="flat",
                               highlightbackground=BORDER, highlightthickness=1,
                               padx=14, pady=10)
        frame.pack(fill="both", expand=expand, pady=4)
        builder_fn(frame)
        return frame
    
    def _labeled_entry(self, parent, label, default="", row=0, width=40):
        tk.Label(parent, text=label, bg=BG_CARD, fg=FG, font=("Segoe UI", 10)).grid(
            row=row, column=0, sticky="w", pady=4)
        e = tk.Entry(parent, width=width, bg=BG_INPUT, fg=FG, insertbackground=FG,
                     font=("Segoe UI", 10), relief="flat", bd=0,
                     highlightthickness=2, highlightcolor=ACCENT, highlightbackground=BORDER)
        e.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)
        e.insert(0, default)
        parent.columnconfigure(1, weight=1)
        return e
    
    def _make_btn(self, parent, text, color, command, **kw):
        btn = tk.Button(parent, text=text, bg=color, fg=BTN_FG, relief="flat",
                        font=("Segoe UI", 11, "bold"), pady=8, padx=16,
                        activebackground=color, activeforeground="white",
                        cursor="hand2", command=command, **kw)
        return btn
    
    # ── Build Sections ──
    def _build_source(self, f):
        tk.Label(f, text="Folder:", bg=BG_CARD, fg=FG, font=("Segoe UI", 10)).grid(
            row=0, column=0, sticky="w", pady=4)
        ff = tk.Frame(f, bg=BG_CARD)
        ff.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)
        self.folder_entry = tk.Entry(ff, width=35, bg=BG_INPUT, fg=FG, insertbackground=FG,
                                     font=("Segoe UI", 10), relief="flat", bd=0,
                                     highlightthickness=2, highlightcolor=ACCENT, highlightbackground=BORDER)
        self.folder_entry.pack(side="left", fill="x", expand=True)
        self.folder_entry.insert(0, os.path.join(BASE_DIR, "konten_speedu_final"))
        tk.Button(ff, text="Browse", bg=ACCENT2, fg="white", relief="flat", padx=10,
                  font=("Segoe UI", 9, "bold"), cursor="hand2",
                  command=self._browse_folder).pack(side="right", padx=(5, 0))
        f.columnconfigure(1, weight=1)
    
    def _build_desc(self, f):
        self.desc_text = tk.Text(f, height=4, bg=BG_INPUT, fg=FG, insertbackground=FG,
                                 font=("Segoe UI", 10), relief="flat", bd=0, wrap="word",
                                 highlightthickness=2, highlightcolor=ACCENT, highlightbackground=BORDER)
        self.desc_text.pack(fill="both", expand=True)
        self.desc_text.insert("1.0", "Siapkan diri kamu di sekolah kedinasan dengan baik demi masa depan cerah #kedinasan2026 #sekdin #stmkg")
    
    def _build_schedule(self, f):
        r = 0
        tk.Label(f, text="Mulai:", bg=BG_CARD, fg=FG, font=("Segoe UI", 10)).grid(
            row=r, column=0, sticky="w", pady=4)
        sf = tk.Frame(f, bg=BG_CARD)
        sf.grid(row=r, column=1, sticky="ew", padx=(8, 0), pady=4)
        
        tomorrow = datetime.now() + timedelta(days=1)
        self.date_entry = tk.Entry(sf, width=12, bg=BG_INPUT, fg=FG, insertbackground=FG,
                                   font=("Segoe UI", 10), relief="flat", justify="center",
                                   highlightthickness=2, highlightcolor=ACCENT, highlightbackground=BORDER)
        self.date_entry.pack(side="left", padx=(0, 5))
        self.date_entry.insert(0, tomorrow.strftime("%Y-%m-%d"))
        
        self.hour_entry = tk.Entry(sf, width=4, bg=BG_INPUT, fg=FG, insertbackground=FG,
                                   font=("Segoe UI", 10), relief="flat", justify="center",
                                   highlightthickness=2, highlightcolor=ACCENT, highlightbackground=BORDER)
        self.hour_entry.pack(side="left"); self.hour_entry.insert(0, "06")
        tk.Label(sf, text=":", bg=BG_CARD, fg=FG, font=("Segoe UI", 12, "bold")).pack(side="left")
        self.minute_entry = tk.Entry(sf, width=4, bg=BG_INPUT, fg=FG, insertbackground=FG,
                                     font=("Segoe UI", 10), relief="flat", justify="center",
                                     highlightthickness=2, highlightcolor=ACCENT, highlightbackground=BORDER)
        self.minute_entry.pack(side="left"); self.minute_entry.insert(0, "00")
        f.columnconfigure(1, weight=1)
        
        r += 1
        self.interval_entry = self._labeled_entry(f, "Interval (menit):", "120", r)
    
    def _build_chrome(self, f):
        self.userdata_entry = self._labeled_entry(f, "User Data:", os.path.join(BASE_DIR, "user_data", "7"), 0)
        self.port_entry = self._labeled_entry(f, "Port:", "9223", 1)
        self.headless_var = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text="Headless Chrome", variable=self.headless_var, bg=BG_CARD, fg=FG, font=("Segoe UI", 10), activebackground=BG_CARD).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
    
    def _build_actions(self, f):
        bf = tk.Frame(f, bg=BG_CARD)
        bf.pack(fill="x")
        
        self.btn_stok = self._make_btn(bf, "📋 Stok Tulisan", BTN_PRIMARY, self._on_stok)
        self.btn_stok.pack(side="left", padx=(0, 8), pady=4)
        
        self.btn_overlay = self._make_btn(bf, "🎨 Buat Overlay", BTN_ORANGE, self._on_overlay)
        self.btn_overlay.pack(side="left", padx=(0, 8), pady=4)
        
        self.btn_full = self._make_btn(bf, "🚀 Full Loop", BTN_SUCCESS, self._on_full_loop)
        self.btn_full.pack(side="left", padx=(0, 8), pady=4)
        
        self.btn_stop = self._make_btn(bf, "⏹ Stop", BTN_DANGER, self._on_stop)
        self.btn_stop.pack(side="right", pady=4)
        self.btn_stop.config(state="disabled")
    
    def _build_progress(self, f):
        pf = tk.Frame(f, bg=BG_CARD)
        pf.pack(fill="x", pady=(0, 5))
        self.progress_label = tk.Label(pf, text="0 / 0  (0%)", bg=BG_CARD, fg=ACCENT,
                                       font=("Segoe UI", 12, "bold"))
        self.progress_label.pack(side="left")
        self.eta_label = tk.Label(pf, text="", bg=BG_CARD, fg=FG_DIM, font=("Segoe UI", 10))
        self.eta_label.pack(side="right")
        
        self.progress_bar = ttk.Progressbar(f, mode="determinate", length=400,
                                            style="Green.Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", pady=(0, 8))
        
        self.log_box = scrolledtext.ScrolledText(f, bg="#1E1B2E", fg="#A5F3C0",
                                                  font=("Consolas", 9), relief="flat",
                                                  insertbackground=SUCCESS, wrap="word")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_config("error", foreground=ERROR)
        self.log_box.tag_config("success", foreground=SUCCESS)
        self.log_box.tag_config("warn", foreground=WARN)
        self.log_box.tag_config("info", foreground="#818CF8")
    
    # ═══════════════════════════════════════════════════════════════
    #  LOGIC / ACTIONS
    # ═══════════════════════════════════════════════════════════════
    def _log(self, msg, tag=None):
        ts = datetime.now().strftime("%H:%M:%S")
        auto_tag = tag
        if not auto_tag:
            if any(k in msg for k in ["✓", "berhasil", "BERHASIL"]): auto_tag = "success"
            elif any(k in msg for k in ["⚠", "gagal"]): auto_tag = "warn"
            elif any(k in msg for k in ["❌", "ERROR", "Error"]): auto_tag = "error"
        def _do():
            self.log_box.insert(tk.END, f"[{ts}] {msg}\n", auto_tag or "")
            self.log_box.see(tk.END)
        self.root.after(0, _do)
    
    def _set_status(self, text, color=FG_DIM):
        self.root.after(0, lambda: self.status_label.config(text=f"Status: {text}", fg=color))
    
    def _update_progress(self, current, total):
        self._progress_current = current
        self._progress_total = total
        self._last_step_time = time.time()
        pct = int(current/total*100) if total else 0
        def _do():
            self.progress_bar["maximum"] = total
            self.progress_bar["value"] = current
            self.progress_label.config(text=f"{current} / {total}  ({pct}%)")
        self.root.after(0, _do)
    
    def _update_timer(self):
        if not self.running: return
        elapsed = time.time() - self.start_time
        h = int(elapsed//3600); m = int((elapsed%3600)//60); s = int(elapsed%60)
        self.timer_label.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        
        # ETA dinamis - hitung ulang setiap detik
        cur = self._progress_current
        tot = self._progress_total
        if cur > 0 and tot > 0 and cur < tot:
            avg_per_item = elapsed / cur
            remaining = avg_per_item * (tot - cur)
            # Kurangi waktu sejak step terakhir agar countdown terasa real-time
            if self._last_step_time:
                since_last = time.time() - self._last_step_time
                remaining = max(0, remaining - since_last)
            r_h = int(remaining // 3600)
            r_m = int((remaining % 3600) // 60)
            r_s = int(remaining % 60)
            if r_h > 0:
                eta_str = f"ETA: ~{r_h}j {r_m}m {r_s}s"
            else:
                eta_str = f"ETA: ~{r_m}m {r_s}s"
            self.eta_label.config(text=eta_str)
        elif cur >= tot and tot > 0:
            self.eta_label.config(text="Selesai!")
        
        self.root.after(1000, self._update_timer)
    
    def _refresh_stok(self):
        # Hitung stok tulisan dari JSON
        tulisan_count = 0
        if os.path.exists(JSON_PATH):
            try:
                with open(JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tulisan_count = len([d for d in data if "tulisan 1" in d])
            except: pass
        
        # Hitung stok overlay dari folder
        overlay_count = 0
        if os.path.isdir(OVERLAY_DIR):
            overlay_count = len([f for f in os.listdir(OVERLAY_DIR)
                                 if f.lower().endswith("_overlay.mp4")])
        
        # Update labels
        color_t = SUCCESS if tulisan_count >= STOK_MINIMUM else ERROR
        color_o = SUCCESS if overlay_count >= VIDEO_COUNT else WARN
        
        self.root.after(0, lambda: (
            self.stok_tulisan_label.config(text=f"Tulisan: {tulisan_count}", fg=color_t),
            self.stok_overlay_label.config(text=f"Overlay: {overlay_count}", fg=color_o)
        ))
        return tulisan_count
    
    def _browse_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.folder_entry.delete(0, tk.END)
            self.folder_entry.insert(0, d)
    
    def _delete_stok_tulisan(self):
        if not messagebox.askyesno("Hapus Stok Tulisan",
                "Hapus semua konten di konten_gemini.json?\nAksi ini tidak dapat dibatalkan."):
            return
        try:
            with open(JSON_PATH, "w", encoding="utf-8") as f:
                json.dump([], f)
            self._refresh_stok()
            self._log("Stok tulisan dihapus.", "warn")
        except Exception as e:
            messagebox.showerror("Error", str(e))
    
    def _delete_stok_overlay(self):
        if not os.path.isdir(OVERLAY_DIR):
            return
        files = [f for f in os.listdir(OVERLAY_DIR) if f.lower().endswith("_overlay.mp4")]
        if not files:
            return
        if not messagebox.askyesno("Hapus Stok Overlay",
                f"Hapus {len(files)} file overlay di konten_final_overlay?\nAksi ini tidak dapat dibatalkan."):
            return
        deleted = 0
        for f in files:
            try:
                os.remove(os.path.join(OVERLAY_DIR, f))
                deleted += 1
            except: pass
        self._refresh_stok()
        self._log(f"Stok overlay dihapus ({deleted} file).", "warn")
    
    def _set_running(self, running):
        self.running = running
        state_btns = "disabled" if running else "normal"
        state_stop = "normal" if running else "disabled"
        self.root.after(0, lambda: (
            self.btn_stok.config(state=state_btns),
            self.btn_overlay.config(state=state_btns),
            self.btn_full.config(state=state_btns),
            self.btn_stop.config(state=state_stop)
        ))
    
    # ── Button: Stok Tulisan ──
    def _on_stok(self):
        self._set_running(True)
        self.start_time = time.time()
        self._update_timer()
        self.stop_event.clear()
        self.log_box.delete("1.0", tk.END)
        threading.Thread(target=self._task_stok, daemon=True).start()
    
    def _task_stok(self):
        try:
            stok = self._refresh_stok()
            self._log(f"Stok konten saat ini: {stok}", "info")
            if stok >= STOK_MINIMUM:
                self._log(f"Stok mencukupi ({stok} >= {STOK_MINIMUM}). Tidak perlu generate.", "success")
            else:
                needed = STOK_MINIMUM - stok
                loops = (needed + 1) // 2  # Gemini generates 2 per loop
                self._log(f"Kurang {needed} konten, menjalankan {loops} loop Gemini...", "warn")
                self._set_status("Generating konten...", ACCENT)
                is_headless = getattr(self, 'headless_var', tk.BooleanVar(value=False)).get()
                total = run_gemini_generate(loops, self._log, self.stop_event, is_headless)
                self._log(f"Total konten sekarang: {total}", "success")
                self._refresh_stok()
            self._set_status("Stok selesai!", SUCCESS)
        except Exception as e:
            self._log(f"Error: {e}", "error")
            self._set_status(f"Error: {e}", ERROR)
        finally:
            self._set_running(False)
    
    # ── Button: Buat Overlay ──
    def _on_overlay(self):
        self._set_running(True)
        self.start_time = time.time()
        self._update_timer()
        self.stop_event.clear()
        self.log_box.delete("1.0", tk.END)
        threading.Thread(target=self._task_overlay, daemon=True).start()
    
    def _task_overlay(self):
        try:
            folder = self.folder_entry.get().strip()
            if not folder or not os.path.isdir(folder):
                self._log("Folder video tidak valid!", "error"); return
            
            videos = sorted([f for f in os.listdir(folder) if f.lower().endswith(".mp4")])[:VIDEO_COUNT]
            if not videos:
                self._log("Tidak ada video .mp4 di folder!", "error"); return
            
            stok = self._refresh_stok()
            if stok < len(videos):
                self._log(f"Stok konten ({stok}) kurang dari jumlah video ({len(videos)})!", "error"); return
            
            os.makedirs(OVERLAY_DIR, exist_ok=True)
            total = len(videos)
            self._update_progress(0, total)
            self._set_status("Membuat overlay...", ACCENT)
            
            for idx, vid in enumerate(videos):
                if self.stop_event.is_set(): self._log("Overlay dihentikan.", "warn"); break
                
                vid_path = os.path.join(folder, vid)
                out_name = os.path.splitext(vid)[0] + "_overlay.mp4"
                out_path = os.path.join(OVERLAY_DIR, out_name)
                
                # Skip jika sudah ada
                if os.path.exists(out_path):
                    self._log(f"[{idx+1}/{total}] {out_name} sudah ada, skip.", "info")
                else:
                    self._log(f"[{idx+1}/{total}] Overlay: {vid} → konten #{idx+1}...", "info")
                    ok = overlay_video(vid_path, idx+1, out_path, self._log)
                    if ok:
                        sz = os.path.getsize(out_path) / (1024*1024)
                        self._log(f"  ✓ Berhasil! ({sz:.1f} MB)", "success")
                    else:
                        self._log(f"  ❌ Gagal overlay {vid}!", "error")
                
                self._update_progress(idx+1, total)
            
            self._log(f"Overlay selesai! {total} video.", "success")
            self._set_status("Overlay selesai!", SUCCESS)
        except Exception as e:
            self._log(f"Error: {e}", "error")
            self._set_status(f"Error", ERROR)
        finally:
            self._set_running(False)
    
    # ── Button: Full Loop ──
    def _on_full_loop(self):
        self._set_running(True)
        self.start_time = time.time()
        self._update_timer()
        self.stop_event.clear()
        self.log_box.delete("1.0", tk.END)
        threading.Thread(target=self._task_full_loop, daemon=True).start()
    
    def _task_full_loop(self):
        try:
            folder = self.folder_entry.get().strip()
            if not folder or not os.path.isdir(folder):
                self._log("Folder video tidak valid!", "error"); self._set_running(False); return
            
            videos = sorted([f for f in os.listdir(folder) if f.lower().endswith(".mp4")])[:VIDEO_COUNT]
            if not videos:
                self._log("Tidak ada video .mp4 di folder!", "error"); self._set_running(False); return
            
            total_steps = len(videos) * 3  # 3 phases
            current_step = 0
            
            # ═══ PHASE 1: Konten Gemini ═══
            self._log("═══ PHASE 1: Memeriksa Stok Konten Gemini ═══", "info")
            self._set_status("Phase 1: Konten...", ACCENT)
            stok = self._refresh_stok()
            if stok < len(videos):
                needed = len(videos) - stok
                loops = (needed + 1) // 2
                self._log(f"Stok kurang ({stok}/{len(videos)}), generate {loops} loop...", "warn")
                is_headless = getattr(self, 'headless_var', tk.BooleanVar(value=False)).get()
                run_gemini_generate(loops, self._log, self.stop_event, is_headless)
                stok = self._refresh_stok()
                if stok < len(videos):
                    self._log(f"Stok masih kurang ({stok})! Coba lagi nanti.", "error")
                    self._set_running(False); return
            else:
                self._log(f"Stok konten cukup: {stok}", "success")
            current_step += len(videos)
            self._update_progress(current_step, total_steps)
            if self.stop_event.is_set(): self._set_running(False); return
            
            # ═══ PHASE 2: Video Overlay ═══
            self._log("\n═══ PHASE 2: Video Overlay ═══", "info")
            self._set_status("Phase 2: Overlay...", ACCENT)
            os.makedirs(OVERLAY_DIR, exist_ok=True)
            
            overlay_files = []
            for idx, vid in enumerate(videos):
                if self.stop_event.is_set(): break
                vid_path = os.path.join(folder, vid)
                out_name = os.path.splitext(vid)[0] + "_overlay.mp4"
                out_path = os.path.join(OVERLAY_DIR, out_name)
                
                if os.path.exists(out_path):
                    self._log(f"[{idx+1}/{len(videos)}] {out_name} sudah ada, skip.", "info")
                else:
                    self._log(f"[{idx+1}/{len(videos)}] Overlay: {vid}...", "info")
                    ok = overlay_video(vid_path, idx+1, out_path, self._log)
                    if ok:
                        self._log(f"  ✓ Overlay berhasil!", "success")
                    else:
                        self._log(f"  ❌ Gagal overlay!", "error")
                
                overlay_files.append(out_path)
                current_step += 1
                self._update_progress(current_step, total_steps)
            
            if self.stop_event.is_set():
                self._log("Dihentikan oleh user.", "warn"); self._set_running(False); return
            
            # ═══ PHASE 3: Upload TikTok ═══
            self._log("\n═══ PHASE 3: Upload ke TikTok ═══", "info")
            self._set_status("Phase 3: Upload...", ACCENT)
            
            deskripsi = self.desc_text.get("1.0", tk.END).strip() or "Segera Try out di speedu.online"
            hour = int(self.hour_entry.get().strip() or "6")
            minute = int(self.minute_entry.get().strip() or "0")
            date_str = self.date_entry.get().strip()
            interval = int(self.interval_entry.get().strip() or "120")
            userdata = self.userdata_entry.get().strip()
            port = self.port_entry.get().strip() or "9223"
            
            start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
            
            is_headless = getattr(self, 'headless_var', tk.BooleanVar(value=False)).get()
            self._log(f"Membuka Chrome (port {port}, headless={is_headless})...", "info")
            chrome_proc = open_chrome_debug(userdata, port, is_headless)
            driver = connect_selenium(port)
            self._log("Chrome terhubung!", "success")
            
            try:
                for idx, out_path in enumerate(overlay_files):
                    if self.stop_event.is_set(): break
                    if not os.path.exists(out_path):
                        self._log(f"[{idx+1}] File tidak ada: {out_path}, skip!", "warn")
                        current_step += 1; self._update_progress(current_step, total_steps); continue
                    
                    sched_dt = start_dt + timedelta(minutes=interval * idx)
                    self._log(f"\n[{idx+1}/{len(overlay_files)}] Upload: {os.path.basename(out_path)}", "info")
                    self._log(f"  Schedule: {sched_dt.strftime('%Y-%m-%d %H:%M')}", "info")
                    
                    try:
                        navigate_upload_page(driver, force=(idx > 0))
                        time.sleep(3)
                        do_upload_file(driver, os.path.normpath(out_path), self._log)
                        time.sleep(5)
                        do_post_tiktok(driver, deskripsi, sched_dt, self._log)
                    except Exception as e:
                        self._log(f"  ❌ Error: {e}", "error")
                    
                    current_step += 1
                    self._update_progress(current_step, total_steps)
                    
                    if idx < len(overlay_files) - 1 and not self.stop_event.is_set():
                        self._log("  Menunggu 10 detik...", "info"); time.sleep(10)
            finally:
                try: driver.quit()
                except: pass
                try: chrome_proc.terminate()
                except: pass
            
            # ═══ DONE ═══
            self._log(f"\n{'═'*50}", "success")
            self._log(f"🎉 SELESAI! Pipeline {len(videos)} video telah diproses.", "success")
            self._log(f"{'═'*50}", "success")
            self._set_status("SELESAI!", SUCCESS)
            
            try:
                for _ in range(3): winsound.Beep(1000, 300); time.sleep(0.2)
                winsound.Beep(1500, 500)
            except: pass
        
        except Exception as e:
            self._log(f"Fatal error: {e}", "error")
            self._set_status(f"Error: {e}", ERROR)
            import traceback; self._log(traceback.format_exc(), "error")
        finally:
            self._set_running(False)
    
    def _on_stop(self):
        self.stop_event.set()
        self._set_status("Stopping...", WARN)
        self._log("⏹ Stop requested.", "warn")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    app = SpeeduApp(root)
    root.mainloop()
