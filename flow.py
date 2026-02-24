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
        print("Setting download...")
        # --- Setting Download Folder ---
        output_folder = r"c:\tiktok_automation\Output"
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
            print(f"Folder Output dibuat: {output_folder}")
        
        try:
            # Menggunakan CDP command agar bisa ubah download path di sesi visual
            driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": output_folder
            })
            print(f"Lokasi download diatur ke: {output_folder}")
        except Exception as e:
            print(f"Gagal mengatur lokasi download: {e}")
        # -------------------------------
        
        base_url = "https://labs.google/fx/id/tools/flow"
        
        # Cek apakah tab sudah ada yang membuka URL tersebut
        found_tab = False
        for handle in driver.window_handles:
            try:
                driver.switch_to.window(handle)
                if "labs.google/fx/id/tools/flow" in driver.current_url:
                    print(f"Tab ditemukan: {driver.current_url}")
                    found_tab = True
                    break
            except:
                pass
        
        if not found_tab:
            print(f"Membuka URL di tab baru: {base_url}")
            driver.switch_to.new_window('tab')
            driver.get(base_url)

        try:
            wait = WebDriverWait(driver, 10)
            print("Mencari tombol 'Project baru'...")
            
            # Coba cari tombol 'Project baru' dengan beberapa selector atau tunggu dia clickable
            # Kadang perlu waktu loading
            xpath_project_baru = "//button[contains(., 'Project baru') or .//span[contains(text(), 'Project baru')]]"
            
            # Tunggu elemen muncul dulu
            wait.until(EC.presence_of_element_located((By.XPATH, xpath_project_baru)))
            
            btn_project_baru = driver.find_element(By.XPATH, xpath_project_baru)
            
            # Coba klik
            try:
                btn_project_baru.click()
                print("Klik standar tombol 'Project baru' berhasil.")
            except:
                driver.execute_script("arguments[0].click();", btn_project_baru)
                print("Klik JS tombol 'Project baru' berhasil.")

            # Tunggu sampai URL berubah ke halaman project (mengandung '/project/')
            print("Menunggu halaman project terbuka...")
            wait.until(EC.url_contains("/project/"))
            print(f"Project berhasil dibuka: {driver.current_url}")
        
        except Exception as e:
            # Jika gagal klik project baru (mungkin sudah di halaman project?), kita log aja tapi jangan return None
            # Biar flow selanjutnya jalan (siapa tau user manual klik)
            print(f"Info: Gagal otomatis membuat project baru (Sisi User mungkin perlu cek): {e}") 
            # Tapi tetap return driver
            
        return driver
    except Exception as e:
        print(f"Gagal menghubungkan Selenium: {e}")
        return None

if __name__ == "__main__":
    buka_chrome_debug()
    time.sleep(1)
    driver = jalankan_selenium()
    
    if driver:
        print("Browser siap dan URL telah dimuat.")
        
        wait = WebDriverWait(driver, 20)
        try:
            # 1. Klik Dropdown Teks ke Video
            print("Mencoba klik tombol dropdown 'Teks ke Video'...")
            # Menggunakan XPath yang mencari text di dalam button/span
            teks_ke_video_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[.//span[contains(text(), 'Teks ke Video')]] | //span[contains(text(), 'Teks ke Video')]")
            ))
            teks_ke_video_btn.click()
            print("Tombol dropdown diklik.")
            time.sleep(1)

            # 2. Pilih Frame menjadi Video
            print("Mencari opsi 'Frame menjadi Video'...")
            time.sleep(2) # Tunggu animasi dropdown selesai
            
            # Cari elemen secara manual untuk debug visual
            options_candidates = driver.find_elements(By.XPATH, "//*[contains(text(), 'Frame menjadi Video')]")
            print(f"Ditemukan {len(options_candidates)} elemen teks 'Frame menjadi Video'.")
            
            clicked = False
            for i, opt in enumerate(options_candidates):
                print(f"  Elemen {i+1}: Tag={opt.tag_name}, Visible={opt.is_displayed()}")
                if opt.is_displayed():
                    # Coba klik parentnya jika elemennya span/text nempel
                    try:
                        # Klik JS pada elemen text langsung
                        driver.execute_script("arguments[0].click();", opt)
                        print("  -> Klik JS pada elemen text berhasil.")
                        clicked = True
                        break
                    except:
                        pass
            
            if not clicked:
                print("Mencoba selector alternatif (parent div)...")
                # Coba cari elemen yang mungkin parent dari text tersebut yang clickable
                xpath_alt = "//*[contains(text(), 'Frame menjadi Video')]/ancestor::div[@role='menuitem' or contains(@class, 'item') or position()=1]"
                alt_elem = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_alt)))
                driver.execute_script("arguments[0].click();", alt_elem)
                print("Klik selector alternatif berhasil.")

            print("Opsi 'Frame menjadi Video' telah dipilih.")
            time.sleep(2)

            # Fungsi Reusable untuk Upload Frame
            def upload_and_process_frame(urutan):
                print(f"\n[FRAME {urutan}] Memulai proses upload...")
                
                # 3. Klik tombol Add (+)
                print(f"[FRAME {urutan}] Mencari tombol Add (+)...")
                xpath_add = "//button[.//i[contains(text(), 'add')] or .//i[contains(@class, 'google-symbols') and contains(text(), 'add')]]"
                
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        # Tunggu tombol add muncul
                        wait.until(EC.presence_of_all_elements_located((By.XPATH, xpath_add)))
                        
                        # Ambil semua tombol add
                        add_buttons = driver.find_elements(By.XPATH, xpath_add)
                        print(f"  (Percobaan {attempt+1}) Ditemukan {len(add_buttons)} tombol Add.")
                        
                        if add_buttons:
                            # LOGIKA PILIH TOMBOL:
                            # Frame 1: Ambil tombol pertama (index 0) - Asumsi slot pertama
                            # Frame > 1: Ambil tombol terakhir (index -1) - Asumsi append
                            if urutan == 1:
                                target_index = 0
                                print(f"  Frame 1: Memilih tombol Add PERTAMA.")
                            else:
                                target_index = -1
                                print(f"  Frame {urutan}: Memilih tombol Add TERAKHIR.")
                            
                            target_add = add_buttons[target_index]
                            
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_add)
                            time.sleep(1)
                            target_add.click()
                            print(f"  Tombol Add berhasil diklik.")
                            break # Berhasil, keluar loop
                        else:
                            raise Exception("Tidak ada tombol Add ditemukan.")
                            
                    except Exception as e:
                        print(f"  Gagal klik tombol Add (Percobaan {attempt+1}): {e}")
                        if attempt < max_retries - 1:
                            time.sleep(2)
                        else:
                            raise Exception("Gagal klik tombol Add setelah semua percobaan.")
                
                time.sleep(1)

                # 4. Klik Upload & Pilih Foto Random
                import random
                import glob

                print(f"[FRAME {urutan}] Mencari tombol Upload...")
                
                # Cek apakah ada input file yang bisa langsung ditembak
                file_input = driver.find_elements(By.XPATH, "//input[@type='file']")
                
                if not file_input:
                    # Klik tombol Upload di menu
                    upload_menu_btn = wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "//div[contains(text(), 'Upload') or .//i[contains(text(), 'upload')]]")
                    ))
                    upload_menu_btn.click()
                    print("  Tombol Upload menu diklik.")
                    time.sleep(1)
                    
                    # Cari input file lagi setelah klik
                    file_input = driver.find_elements(By.XPATH, "//input[@type='file']")
                
                if file_input:
                    # Ambil satu file random dari folder tab_bahan
                    folder_bahan = r"c:\tiktok_automation\tab_bahan"
                    list_foto = glob.glob(os.path.join(folder_bahan, "*.*"))
                    list_foto = [f for f in list_foto if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.heic', '.avif'))]
                    
                    if list_foto:
                        foto_random = random.choice(list_foto)
                        print(f"  Mengupload foto: {foto_random}")
                        
                        # Send keys ke input file pertama
                        file_input[0].send_keys(foto_random)
                        print("  Foto berhasil diupload via send_keys.")
                        time.sleep(5) # Tunggu upload selesai

                        # 5. Ubah Orientasi ke Potret (Jika belum)
                        print(f"[FRAME {urutan}] Mencoba mengatur orientasi ke Potret...")
                        try:
                            # Klik Dropdown Orientasi
                            xpath_orient_btn = "//button[@role='combobox' and (.//i[contains(text(), 'crop')] or contains(., 'Lanskap') or contains(., 'Potret'))]"
                            
                            orientation_btn = wait.until(EC.element_to_be_clickable(
                                (By.XPATH, xpath_orient_btn)
                            ))
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", orientation_btn)
                            time.sleep(1)
                            driver.execute_script("arguments[0].click();", orientation_btn)
                            print("  Dropdown orientasi diklik (JS).")
                            time.sleep(2)

                            # Pilih 'Potret'
                            xpath_potret = "//*[contains(text(), 'Potret')]"
                            potret_candidates = driver.find_elements(By.XPATH, xpath_potret)
                            
                            potret_clicked = False
                            for cand in potret_candidates:
                                if cand.is_displayed():
                                    try:
                                        driver.execute_script("arguments[0].click();", cand)
                                        print("  Opsi 'Potret' dipilih (JS).")
                                        potret_clicked = True
                                        break
                                    except:
                                        pass
                            
                            if not potret_clicked:
                                potret_opt = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_potret)))
                                driver.execute_script("arguments[0].click();", potret_opt)
                                print("  Opsi 'Potret' dipilih (Wait+JS).")
                                
                            time.sleep(2)

                            # 6. Klik Pangkas dan Simpan
                            print(f"[FRAME {urutan}] Mencoba klik 'Pangkas dan Simpan'...")
                            crop_save_btn = wait.until(EC.element_to_be_clickable(
                                (By.XPATH, "//button[contains(., 'Pangkas dan Simpan')]")
                            ))
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", crop_save_btn)
                            driver.execute_script("arguments[0].click();", crop_save_btn)
                            print("  Tombol 'Pangkas dan Simpan' diklik.")
                            
                            # Tunggu proses simpan selesai sebelum lanjut ke frame berikutnya
                            time.sleep(3) 

                        except Exception as e_orient:
                            print(f"  Gagal mengatur orientasi: {e_orient}")
                    
                    else:
                        print("  Tidak ada foto di folder tab_bahan!")
                else:
                    print("  Input type='file' tidak ditemukan!")

            # 7. Fungsi Input Prompt & Generate
            def input_prompt_and_generate(text):
                print("\n[PROMPT] Memulai proses input prompt...")
                try:
                    # A. Isi Text Area
                    print(f"  Mengisi text area dengan: '{text}'")
                    # Cari text area berdasarkan ID
                    text_area = wait.until(EC.presence_of_element_located((By.ID, "PINHOLE_TEXT_AREA_ELEMENT_ID")))
                    
                    # Pastikan elemen visible dan clickable
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", text_area)
                    time.sleep(1)
                    
                    text_area.click()
                    text_area.clear() 
                    text_area.send_keys(text)
                    print("  Text area berhasil diisi.")
                    time.sleep(1)

                    # B. Klik Tombol "Buat"
                    print("  Mencari tombol 'Buat'...")
                    # Cari button yang punya icon arrow_forward atau text Buat
                    xpath_create = "//button[.//i[contains(text(), 'arrow_forward')] or .//span[contains(text(), 'Buat')]]"
                    create_btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_create)))
                    
                    create_btn.click()
                    print("  Tombol 'Buat' diklik.")

                    # --- LOGIKA MENUNGGU GENERATE SELESAI ---
                    import re
                    print("  Menunggu proses generate berjalan...")
                    
                    timeout = 60*7 # 10 menit
                    start_time = time.time()
                    seen_progress = False
                    
                    time.sleep(5) # Tunggu UI update awal

                    while time.time() - start_time < timeout:
                        try:
                            # 1. Cek Progress Persen
                            progress_elems = driver.find_elements(By.XPATH, "//*[contains(text(), '%')]")
                            found_now = False
                            for elem in progress_elems:
                                try:
                                    if elem.is_displayed():
                                        txt = elem.text.strip()
                                        match = re.search(r'(\d+)\s*%', txt)
                                        if match:
                                            p = int(match.group(1))
                                            if 0 <= p <= 100:
                                                print(f"    Status Generate: {p}%", end='\r')
                                                found_now = True
                                                seen_progress = True
                                                if p >= 100:
                                                    print("\n    Generate mencapai 100%. Selesai.")
                                                    raise StopIteration # Paksa keluar loop
                                                break
                                except:
                                    continue
                            
                            # 2. Cek Tombol Download (Indikator selesai alternatif)
                            # Jika tombol download muncul, berarti sudah jadi meskipun persen belum 100
                            xpath_download_check = "//button[.//span[contains(text(), 'Download')] or .//i[contains(text(), 'download')]]"
                            download_btns_check = driver.find_elements(By.XPATH, xpath_download_check)
                            for btn in download_btns_check:
                                if btn.is_displayed():
                                    print("\n    Tombol Download muncul! Generate selesai (Early Finish).")
                                    raise StopIteration

                            # Logika keluar loop jika indikator hilang
                            if not found_now and seen_progress:
                                print("\n    Indikator persen menghilang. Generate dianggap selesai.")
                                break
                            
                            # Timeout awal jika gak ada apa2
                            if not found_now and not seen_progress and (time.time() - start_time > 60):
                                print("\n    Tidak ada indikator persen setelah 60 detik.")
                                break

                        except StopIteration:
                            break
                        except:
                            pass
                        time.sleep(2)
                    
                    # --- PROSES DOWNLOAD ---
                    print("\n[DOWNLOAD] Memulai proses download...")
                    from selenium.webdriver.common.action_chains import ActionChains
                    action = ActionChains(driver)
                    
                    try:
                        # 1. Cari Tombol Download
                        print("  Mencari tombol Download...")
                        xpath_download_btns = "//button[.//span[contains(text(), 'Download')] or .//i[contains(text(), 'download')]]"
                        
                        # Tunggu sebentar siapa tahu baru render
                        time.sleep(2)
                        
                        download_btns = driver.find_elements(By.XPATH, xpath_download_btns)
                        print(f"  Ditemukan {len(download_btns)} kandidat tombol Download.")
                        
                        download_success = False
                        for i, btn in enumerate(download_btns):
                            try:
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                                time.sleep(1)
                                
                                if btn.is_displayed():
                                    action.move_to_element(btn).perform()
                                    time.sleep(0.5)
                                    btn.click()
                                    print("    Klik tombol Download berhasil.")
                                    download_success = True
                                    break
                                else:
                                    # Coba paksa JS
                                    driver.execute_script("arguments[0].click();", btn)
                                    print("    Klik JS tombol Download berhasil.")
                                    download_success = True
                                    break
                            except:
                                pass
                        
                        if not download_success:
                            print("  Gagal menekan tombol Download.")
                        else:
                            # 2. Pilih Resolusi 720p
                            print("  Mencari opsi 'Ukuran asli (720p)'...")
                            time.sleep(2) # Tunggu dropdown muncul
                            
                            xpaths_res = [
                                "//*[contains(text(), 'Ukuran asli') and contains(text(), '720p')]", 
                                "//*[contains(text(), '720p')]", 
                                "//button[contains(., '720p')]"
                            ]
                            
                            res_clicked = False
                            for xpath in xpaths_res:
                                if res_clicked: break
                                candidates = driver.find_elements(By.XPATH, xpath)
                                for cand in candidates:
                                    if cand.is_displayed():
                                        try:
                                            action.move_to_element(cand).click().perform()
                                            print("    Klik opsi 720p berhasil.")
                                            res_clicked = True
                                            break
                                        except:
                                            driver.execute_script("arguments[0].click();", cand)
                                            print("    Klik JS opsi 720p berhasil.")
                                            res_clicked = True
                                            break
                            
                            if not res_clicked:
                                print("  Gagal memilih resolusi 720p.")
                            else:
                                print("  Proses download selesai trigger.")
                                time.sleep(5)

                    except Exception as e:
                        print(f"  Gagal saat download: {e}")
                    # -----------------------
                    
                except Exception as e:
                    print(f"  Gagal proses prompt: {e}")

            # --- EKSEKUSI ---
            # Frame 1
            upload_and_process_frame(1)
            time.sleep(10)
            # Frame 2
            upload_and_process_frame(2)
            time.sleep(10)
            # Input Prompt & Generate
            # Masukkan prompt yang diinginkan di sini
            prompt_awal = 'INSTRUKSI UMUM – GAYA HIJAB HOKAGE “UWAK” Format & Teknis - Durasi: 8 detik per video - Resolusi: Render 8K ultra-realistis - Produk yang digunakan: Tab Pro S12 (11,6 inci, visual splash warna-warni, ikon 5G, RAM 16GB, ROM 1024GB) - Desain: ramping, mengkilap, bezel tipis - Aksesoris: keyboard wireless terpisah, stylus metalik, earphone & charger (unboxing opsional) Karakter - Wanita Indonesia cantik dengan hijab modern - Pakaian: Jubah Hokage (putih-oranye), ikat kepala dengan tulisan “uwak” - Gaya: percaya diri, ekspresif, aura ninja yang elegan Sulih Suara (VO) - Bahasa: 100% Bahasa Indonesia - Singkat (maksimal 6-8 kata, selesai ≤2 detik) - Berenergi tinggi, ekspresif, seperti pembawa acara TikTok Live Kamera & Visual - Sudut pandang: track-in/out, orbit, selfie POV, sudut rendah, sinematik dari atas - Transisi: jepret, cambuk, zoom, glitch elegan - Efek tematik: api, debu beterbangan, kilauan emas - Latar belakang: meja kayu kenari, sorotan emas, efek api sinematik - Warna dominan: hitam, putih gading, kilauan emas + aksen api merah-oranye Audio & Efek - Musik: beat elegan modern + suasana ninja epik - Efek: desingan api, percikan api, kilauan emas, glitch lembut - VO: suara manusia asli, cepat, tegas, kuat VIDEO 1 URUTAN VISUAL (0.0–2.0s) Track-in gerak lambat → gadis berhijab modern, jubah Hokage putih-oranye, ikat kepala “uwak” (2.0–4.0s) Dia mengangkat Tab Pro S12 di atas meja kayu kenari, layar menampilkan percikan warna-warni (4.0–6.0 detik) Tampilan dekat layar: ikon 5G, RAM 16GB, ROM 1024GB (6.0–8.0 detik) Bidikan orbit yang elegan, stylus diputar seperti kunai dengan efek api VO gaya Shopee viral (Bahasa Indonesia) : "Tablet android kenceng tapi cuma sejuta? Keyboard dan mouse gratis! Layar OLED, Ram 16 Giga ROM 1000 Giga! Klik sekarang sebelum habis!" Jangan ada teks layar Jangan ada overlay apapun Jangan ada lip sync' 
            input_prompt_and_generate(prompt_awal)

        except Exception as e:
            print(f"Terjadi kesalahan saat memilih mode: {e}")
