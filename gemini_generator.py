import time
import json
import os
import re
import subprocess
import tkinter as tk
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import psutil

# Fungsi untuk mengambil text dari clipboard menggunaka tkinter bawaan python
def get_clipboard_text():
    root = tk.Tk()
    root.withdraw()
    try:
        result = root.clipboard_get()
    except tk.TclError:
        result = ""
    root.destroy()
    return result

# Fungsi untuk menulis teks ke clipboard
def set_clipboard_text(text):
    root = tk.Tk()
    root.withdraw()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()
    root.destroy()

def buka_chrome_debug():
    # Path ke aplikasi Chrome
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    # Path folder profil (Pastikan folder ini ada atau akan dibuat otomatis)
    user_data_dir = r"C:\tiktok_automation\user_data\6"
    
    print("Mencoba membuka Chrome dalam mode debug...")
    
    # Perintah CMD
    cmd = [
        chrome_path,
        f"--remote-debugging-port=9222",
        f"--user-data-dir={user_data_dir}"
    ]
    
    # Menjalankan Chrome tanpa menunggu prosesnya selesai (Popen)
    subprocess.Popen(cmd)
    
    # Beri jeda 3-5 detik agar Chrome terbuka sempurna sebelum Selenium masuk
    time.sleep(3)

def connect_selenium_debug():
    """Menghubungkan ke Chrome yang berjalan di port 9222"""
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    try:
        print("Mencoba menghubungkan ke Chrome (Port 9222)...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        print("Berhasil terhubung ke Chrome!")
        return driver
    except Exception as e:
        print("Gagal menghubungkan Selenium. Pastikan Chrome sudah dibuka dengan remote debugging di port 9222.")
        print(f"Error: {e}")
        return None

def find_chrome_pid(port=9222):
    """Mencari Process ID dari Chrome yang LISTEN di port tertentu"""
    for conn in psutil.net_connections(kind='tcp'):
        if conn.laddr.port == port and conn.status == 'LISTEN':
            return conn.pid
    return None

def kill_process(pid):
    """Mematikan process by PID"""
    try:
        process = psutil.Process(pid)
        process.terminate()
        print(f"Berhasil menutup process ID {pid}")
    except Exception as e:
        print(f"Gagal mematikan Process {pid}: {e}")

def main():
    try:
        num_loops_input = input("Masukkan jumlah loop generate konten: ")
        num_loops = int(num_loops_input)
    except ValueError:
        print("Input tidak valid. Program berhenti.")
        return

    # Munculkan Chrome sebelum connect
    buka_chrome_debug()

    driver = connect_selenium_debug()
    if not driver:
        return

    # Buka Gemini
    print("Membuka https://gemini.google.com/ ...")
    driver.get("https://gemini.google.com/")
    
    wait = WebDriverWait(driver, 30)
    wait_long = WebDriverWait(driver, 180) # Toleransi waktu generate lebih lama (3 menit)
    action = ActionChains(driver)

    db_filename = r"c:\tiktok_automation\konten_gemini.json"
    db_data = []

    # Jika db lama ada, kita load dan append supaya penomorannya bisa berlanjut (optional)
    if os.path.exists(db_filename):
        try:
            with open(db_filename, "r", encoding="utf-8") as f:
                db_data = json.load(f)
        except:
            pass
            
    prompt_text = """Kamu adalah expert content creator spesialis video pendek 30 detik (TikTok/Reels/Shorts) tentang persiapan masuk Sekolah Kedinasan. Tugasmu: Buat output **HANYA** berupa array JSON valid yang berisi tepat 2 objek JSON. Jangan tambahkan satu kata pun di luar array JSON. Contoh struktur output: [ {json1}, {json2} ] Struktur setiap JSON persis seperti ini: {   "topik": "Judul topik yang menarik",   "tulisan 1": "Teks overlay 1 (hook kuat)",   "tulisan 2": "Teks overlay 2",   "tulisan 3": "Teks overlay 3",   "tulisan 4": "Teks overlay 4",   "tulisan 5": "Teks overlay 5",   "tulisan 6": "Teks overlay 6 (penutup + CTA)" } Aturan wajib:

Pilih DUA topik SECARA ACAK dan BERBEDA setiap kali dari 5 ini:   1. tips skd → jadikan topik: "Tips SKD Kedinasan"   2. tips persiapan fisik masuk sekolah kedinasan → jadikan topik: "Tips Persiapan Fisik Masuk Sekolah Kedinasan"   3. tips masuk sekolah kedinasan → jadikan topik: "Tips Masuk Sekolah Kedinasan"   4. tips belajar sekolah kedinasan → jadikan topik: "Tips Belajar Sekolah Kedinasan"   5. tips skb stmkg → jadikan topik: "Tips SKB STMKG"
Buat tepat 6 tulisan per JSON (cocok untuk 30 detik dengan fade in/out, masing-masing tampil ±5 detik untuk konten lebih panjang).
Semua teks dalam Bahasa Indonesia yang santai, memotivasi, mudah dibaca besar di video.
Gunakan bullet point (*) seperti contoh agar rapi saat di-overlay.
Tulisan 1 = Hook yang bikin orang berhenti scroll, dengan detail awal.
Tulisan 2-5 = Isi tips paling penting & actionable, dengan penjelasan lebih panjang dan contoh spesifik.
Tulisan 6 = Ringkasan lengkap + strong CTA (contoh: “Simpan video ini! Comment ‘MAU’ kalau mau part 2, Follow untuk tips harian, dan share ke temanmu!”).
Setiap tulisan lebih detail (maksimal 250-300 karakter) supaya konten agak panjang tapi tetap readable di layar. Generate array JSON sekarang!"""

    for i in range(num_loops):
        print(f"\n--- Memulai Loop {i+1} dari {num_loops} ---")
        try:
            # 1. Temukan textarea (placeholder) dan isi Prompt
            textarea_xpath = "//div[contains(@class, 'ql-editor')]"
            textarea = wait.until(EC.presence_of_element_located((By.XPATH, textarea_xpath)))
            
            # Scroll ke textarea dan klik untuk fokus
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", textarea)
            time.sleep(1)
            textarea.click()
            time.sleep(1)
            
            # Kita bersihkan textarea secara aman (menghindari TrustedHTML error)
            textarea.send_keys(Keys.CONTROL, "a")
            time.sleep(0.2)
            textarea.send_keys(Keys.BACK_SPACE)
            
            # Simpan prompt ke clipboard dan paste masuk (Cara aman menghindari enter submit)
            set_clipboard_text(prompt_text)
            textarea.send_keys(Keys.CONTROL, "v")
            time.sleep(1)
            
            # Cara alternatif inject text murni jaga-jaga paste gagal
            if "expert content creator" not in textarea.text:
                 print("Paste gagal, mencoba inject javascript text content...")
                 # Menggunakan textContent yang bebas dari kendala TrustedHTML 
                 driver.execute_script("arguments[0].textContent = arguments[1];", textarea, prompt_text)
                 # Trigger event input agar UI-nya sadar ada text baru
                 driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", textarea)
                 time.sleep(1)
                 # Tekan spasi satu kali untuk trigger re-render / check validation field
                 textarea.send_keys(" ")

            # 2. Temukan tombol Send dan Klik
            send_btn_xpath = "//button[contains(@class, 'send-button')]"
            send_btn = wait.until(EC.element_to_be_clickable((By.XPATH, send_btn_xpath)))
            send_btn.click()
            print("Pesan prompt dikirim...")

            # 3. Tunggu sampai generate selesai
            print("Menunggu proses generate selesai (tombol send aktif kembali)...")
            time.sleep(5) # Delay sedikit agar element state send button berubah ke "Generating" state
            
            # Tunggu tombol send bisa diklik lagi (indikator generate telah beres)
            wait_long.until(EC.element_to_be_clickable((By.XPATH, send_btn_xpath)))
            print("Generate selesai! Tunggu antarmuka merender tombol copy...")
            time.sleep(3) 
            
            # 4. Klik Tombol Copy (dari hasil generate terakhir)
            clipboard_result = ""
            try:
                responses = driver.find_elements(By.XPATH, "//div[contains(@class, 'message-content')] | //model-response")
                if responses:
                    last_response = responses[-1]
                    # Hover the response to make the copy button visible
                    action.move_to_element(last_response).perform()
                    time.sleep(1)
                
                # Cari tombol action di respon terbaru
                copy_btns = driver.find_elements(By.XPATH, "//button[descendant::mat-icon[@data-mat-icon-name='content_copy'] or @mattooltip='Copy' or contains(@aria-label, 'Copy') or contains(@aria-label, 'Salin')]")
                
                if copy_btns:
                    target_btn = copy_btns[-1]
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_btn)
                    time.sleep(1)

                    # Reset clipboard sebelumnya agar tidak membaca isi lama
                    set_clipboard_text("") 

                    # Coba klik native menggunakan ActionChains agar clipboard permission tercapai
                    try:
                        action.move_to_element(target_btn).click().perform()
                        print("Tombol Copy berhasil diklik (ActionChains).")
                    except:
                        # Fallback jika intercepted
                        driver.execute_script("arguments[0].click();", target_btn)
                        print("Tombol Copy berhasil diklik (JS).")
                    
                    time.sleep(1.5) # Tunggu clipboard terisi
                    clipboard_result = get_clipboard_text()
                else:
                    print("Tombol copy tidak ditemukan! Membaca teks secara langsung...")
            except Exception as e:
                print(f"Gagal klik tombol copy secara normal, mencoba membaca secara langsung... Error: {e}")

            # Fallback membaca text DOM jika clipboard tidak menyalin secara benar atau kosong
            if not clipboard_result or "{" not in clipboard_result:
                print("Fallback mengambil teks secara langsung dari web DOM.")
                responses = driver.find_elements(By.XPATH, "//div[contains(@class, 'message-content')] | //model-response")
                if responses:
                     clipboard_result = responses[-1].text

            # 5. Parsing dan simpan hasil (mencari format JSON dengan Regular Expression)
            hasil_json = None
            
            # Cari Array JSON dlu, jika tak ada cari Object JSON
            match = re.search(r'\[.*\]', clipboard_result, re.DOTALL)
            if not match:
                match = re.search(r'\{.*\}', clipboard_result, re.DOTALL)
                
            if match:
                 json_str = match.group(0)
                 # Membersihkan sedikit sisa format markdown jika ada di dalam clipboard/text DOM
                 json_str = json_str.replace('```json', '').replace('```', '').strip()
                 try:
                     hasil_json = json.loads(json_str)
                 except Exception as e:
                     print(f"Gagal parse JSON (1): {e}")

            if isinstance(hasil_json, list):
                 print(f"Berhasil mengekstrak {len(hasil_json)} JSON object dari Array:")
                 for item in hasil_json:
                     nomor_urut = len(db_data) + 1
                     item['nomor'] = nomor_urut # Memberikan nomor urut
                     db_data.append(item)
            elif isinstance(hasil_json, dict):
                 print("Berhasil mengekstrak spesifik JSON Object:")
                 nomor_urut = len(db_data) + 1
                 hasil_json['nomor'] = nomor_urut
                 db_data.append(hasil_json)
            else:
                 print("Gagal mengekstrak format JSON. Menyimpan Teks Raw.")
                 nomor_urut = len(db_data) + 1
                 db_data.append({
                     "nomor": nomor_urut,
                     "raw_text": clipboard_result,
                     "status": "JSON parse error"
                 })

            # Tulis Data ke File JSON
            with open(db_filename, "w", encoding="utf-8") as f:
                json.dump(db_data, f, indent=4, ensure_ascii=False)
            
            print(f"-> Hasil loop {i+1} tersimpan dalam {db_filename}.")

        except Exception as e:
            print(f"Terjadi error pada pengerjaan Loop {i+1}: {e}")
            import traceback
            traceback.print_exc()

    print("\n--- Semua Proses Looping Selsai ---")
    
    # Menutup Browser Sesuai PID
    chrome_pid = find_chrome_pid(9222)
    if chrome_pid:
        print(f"Ditemukan PID Chrome (9222): {chrome_pid}. Mematikan proses sekarang.")
        kill_process(chrome_pid)
    else:
        print("Tidak dapat menemukan PID spesifik Chrome (port 9222). Melakukan driver.quit().")
        driver.quit()

if __name__ == "__main__":
    main()
