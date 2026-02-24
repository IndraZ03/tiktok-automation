import subprocess
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

def buka_chrome_debug():
    # Path ke aplikasi Chrome
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    # Path folder profil (Pastikan folder ini ada atau akan dibuat otomatis)
    user_data_dir = r"C:\tiktok_automation\user_data\1"
    
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

def jalankan_selenium():
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        print("Selenium berhasil terhubung ke Chrome!")
        
        base_url = "https://grok.com/imagine"
        
        # Cek apakah tab sudah ada yang membuka URL tersebut
        found_tab = False
        for handle in driver.window_handles:
            try:
                driver.switch_to.window(handle)
                if "grok.com/imagine" in driver.current_url:
                    print(f"Tab ditemukan: {driver.current_url}")
                    found_tab = True
                    break
            except:
                pass
        
        if not found_tab:
            print(f"Membuka URL di tab baru: {base_url}")
            driver.switch_to.new_window('tab')
            driver.get(base_url)

        return driver
    except Exception as e:
        print(f"Gagal menghubungkan Selenium: {e}")
        return None

def process_grok(driver, prompt_text):
    wait = WebDriverWait(driver, 20)
    try:
        print("Memulai otomatisasi Grok...")

        # 1. Isi Prompt
        print("1. Mengisi prompt...")
        # Target: div.tiptap.ProseMirror (contenteditable)
        prompt_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div.tiptap.ProseMirror")))
        prompt_input.click()
        prompt_input.clear()
        prompt_input.send_keys(prompt_text)
        print("   Prompt berhasil diisi.")
        time.sleep(1)

        # 2. Klik Button Setting (Pilih Model)
        print("2. Membuka menu setting (Pilih Model)...")
        # ID: model-select-trigger
        setting_btn = wait.until(EC.element_to_be_clickable((By.ID, "model-select-trigger")))
        setting_btn.click()
        print("   Menu setting terbuka.")
        time.sleep(2) # Tunggu popover/menu muncul

        # 3. Klik 10s
        print("3. Memilih durasi 10s...")
        btn_10s = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@aria-label='10s']")))
        btn_10s.click()
        print("   Durasi 10s dipilih.")
        time.sleep(1)

        # 4. Klik 720p
        print("4. Memilih resolusi 720p...")
        btn_720p = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@aria-label='720p']")))
        btn_720p.click()
        print("   Resolusi 720p dipilih.")
        time.sleep(1)

        # 5. Pilih Aspect Ratio 9:16
        print("5. Memilih aspect ratio 9:16...")
        # Mencari div inner, lalu klik parent button-nya atau element itu sendiri
        # Div inner style: width: 56.25% (9/16)
        # Kita cari element dengan style width sekitar 56.25%
        xpath_ratio = "//div[contains(@style, 'width: 56.25%')]"
        ratio_elem = wait.until(EC.presence_of_element_located((By.XPATH, xpath_ratio)))
        
        # Coba klik parent button-nya jika ada, atau klik element itu sendiri
        try:
            # Cari parent button terdekat
            parent_btn = ratio_elem.find_element(By.XPATH, "./ancestor::button")
            parent_btn.click()
            print("   Ratio 9:16 dipilih (via button parent).")
        except:
            # Fallback klik element langsung
            ratio_elem.click()
            print("   Ratio 9:16 dipilih (via element).")
        time.sleep(1)

        # 6. Pilih Video Format
        print("6. Memilih format Video...")
        # Mencari menu item yang contains "Video"
        # Selector: div[role="menuitem"] // span[text()="Video"]
        xpath_video = "//div[@role='menuitem']//span[contains(text(), 'Video')]"
        video_opt = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_video)))
        video_opt.click()
        print("   Format Video dipilih.")
        time.sleep(1)

        # 7. Klik Placeholder Lagi (Focus Input)
        print("7. Fokus kembali ke input prompt...")
        prompt_input.click()
        print("   Input prompt difokuskan kembali.")
        time.sleep(1)

        # 8. Klik Generate (Kirim)
        print("8. Klik tombol Generate...")
        # Button aria-label="Kirim"
        xpath_kirim = "//button[@aria-label='Kirim']"
        btn_kirim = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_kirim)))
        
        # Cek apakah disabled
        if btn_kirim.get_attribute("disabled"):
            print("   Peringatan: Tombol kirim disabled! Mungkin prompt kosong atau masih loading.")
        
        btn_kirim.click()
        print("   Tombol Generate diklik.")

    except Exception as e:
        print(f"Terjadi kesalahan saat proses Grok: {e}")

if __name__ == "__main__":
    buka_chrome_debug()
    time.sleep(1)
    driver = jalankan_selenium()
    
    if driver:
        # Prompt default, bisa diganti user
        prompt_awal = "A beautiful cinematic video of a futuristic city with flying cars, neon lights, 8k resolution, realistic style"
        process_grok(driver, prompt_awal)
