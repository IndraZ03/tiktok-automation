import subprocess
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import os
import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
# Pastikan alias EC digunakan dengan benar
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# Global variables removed to prevent stale driver issues
# Driver and wait will be passed to functions instead

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
    process = subprocess.Popen(cmd)
    
    # Beri jeda 3-5 detik agar Chrome terbuka sempurna sebelum Selenium masuk
    time.sleep(5)
    return process

def jalankan_selenium():
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        print("Selenium berhasil terhubung ke Chrome!")
        
        # Buka TikTok Studio jika belum terbuka
        if "tiktok.com/tiktokstudio/upload" not in driver.current_url:
            driver.get("https://www.tiktok.com/tiktokstudio/upload")
            
        return driver
    except Exception as e:
        print(f"Gagal menghubungkan Selenium: {e}")
        return None

def simulasi_upload(driver, file_path):
    try:
        wait = WebDriverWait(driver, 20)
        
        print("Mencari elemen upload...")
        
        # PERBAIKAN: Nama fungsi yang benar adalah presence_of_element_located
        # Kita gunakan selector XPath yang lebih umum untuk input file di TikTok Studio
        upload_input = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//input[@type='file']")
        ))

        if os.path.exists(file_path):
            # Mengirim path file langsung ke elemen input
            upload_input.send_keys(file_path)
            print(f"Berhasil menyuntikkan file: {file_path}")
            
            # Berikan waktu jeda agar browser mulai memproses file
            print("Sedang mengunggah... Harap tunggu sampai halaman editor muncul.")
            time.sleep(5) 
        else:
            print(f"File tidak ditemukan: {file_path}")

    except Exception as e:
        print(f"Gagal melakukan simulasi upload: {e}")



def proses_post_video(driver, deskripsi_baru, nama_produk):
    wait = WebDriverWait(driver, 20)
    try:
        # 1. Cek tombol "Turn on"
        try:
            print("Mengecek tombol Turn on...")
            turn_on = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                (By.XPATH, "//div[contains(@class, 'Button__content') and text()='Turn on']")
            ))
            turn_on.click()
            print("Tombol Turn on diklik.")
            time.sleep(2) # Beri jeda setelah modal tertutup
        except:
            print("Tombol Turn on tidak muncul, lanjut...")

        # 2. Isi Deskripsi
        print("Mengisi deskripsi...")
        caption_box = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//div[@role='textbox'] | //div[contains(@class, 'notranslate public-DraftEditor-content')]")
        ))
        caption_box.click()
        caption_box.send_keys(Keys.CONTROL + "a")
        caption_box.send_keys(Keys.BACKSPACE)
        caption_box.send_keys(deskripsi_baru)
        time.sleep(1)

        # 3. REPLACED: Flow Tambah Produk (Gantikan Lokasi)
        print("Memulai proses tambah produk...")
        
        # A. Klik tombol "+ Add" awal
        try:
            add_init_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[.//div[text()='Add']]")
            ))
            add_init_btn.click()
            print("Tombol awal '+ Add' diklik.")
            time.sleep(2)
        except Exception as e:
            print(f"Gagal klik tombol Add awal: {e}")
            raise e # Hentikan program jika error

        # B. Klik "Next" di pop-up pertama
        try:
            next_btn_1 = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[.//div[text()='Next']]")
            ))
            next_btn_1.click()
            print("Tombol Next pertama diklik.")
            time.sleep(2)
        except Exception as e:
            print(f"Gagal klik Next pertama: {e}")
            raise e

        # C. Pilih Radio Button berdasarkan NAMA PRODUK
        try:
            print(f"Mencari produk dengan nama: {nama_produk}")
            # Cari input radio button berdasarkan atribut NAME
            xpath_produk = f"//input[@type='radio' and @name='{nama_produk}']"
            
            target_radio_input = wait.until(EC.presence_of_element_located(
                (By.XPATH, xpath_produk)
            ))
            
            # Cari parent element (wrapper)
            target_radio_wrapper = target_radio_input.find_element(By.XPATH, "./..")
            
            # Scroll ke wrapper
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_radio_wrapper)
            time.sleep(1)
            
            try:
                # Coba klik standar pada wrapper
                target_radio_wrapper.click()
                print(f"Klik wrapper produk '{nama_produk}' (standar).")
            except:
                # Jika gagal, gunakan JS Click pada wrapper
                driver.execute_script("arguments[0].click();", target_radio_wrapper)
                print(f"Klik wrapper produk '{nama_produk}' (JS).")
            
            time.sleep(1)
            print("Radio button produk berhasil dipilih.")

        except Exception as e:
            print(f"Gagal memilih radio button: {e}")
            raise e

        # # D. Klik "Next" kedua (Updated: Focus fix & Direct JS)
        print("-" * 40)
        print("STEP D: Mencoba klik Next tombol kedua...")
        
        try:
            # Tunggu sebentar untuk memastikan DOM stabil
            time.sleep(2)
            
            # Cari semua tombol Next yang visible
            next_buttons = driver.find_elements(By.XPATH, "//button[.//div[text()='Next']]")
            
            print(f"Ditemukan {len(next_buttons)} tombol Next")
            
            target_button = None
            for i, btn in enumerate(next_buttons):
                print(f"Tombol {i+1}:")
                print(f"  - Visible: {btn.is_displayed()}")
                print(f"  - Enabled: {btn.is_enabled()}")
                print(f"  - Class: {btn.get_attribute('class')}")
                print(f"  - aria-disabled: {btn.get_attribute('aria-disabled')}")
                
                # Filter tombol yang visible dan mengandung class primary
                if btn.is_displayed() and "primary" in btn.get_attribute("class"):
                    target_button = btn
                    print(f"  -> TERPILIH sebagai target")
            
            if target_button:
                print(f"\nTombol target ditemukan, mencoba klik...")
                
                # Scroll ke tombol
                driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", target_button)
                time.sleep(1)
                
                # Simpan posisi sebelum klik
                before_html = driver.find_element(By.TAG_NAME, "body").get_attribute("outerHTML")[:500]
                
                # Metode 1: Klik dengan ActionChains (paling reliable untuk visual click)
                try:
                    from selenium.webdriver.common.action_chains import ActionChains
                    actions = ActionChains(driver)
                    actions.move_to_element(target_button).click().perform()
                    print("Klik dengan ActionChains berhasil dieksekusi")
                except Exception as e:
                    print(f"ActionChains gagal: {e}")
                    
                    # Metode 2: Klik biasa
                    try:
                        target_button.click()
                        print("Klik biasa berhasil dieksekusi")
                    except:
                        # Metode 3: JavaScript sebagai fallback
                        driver.execute_script("arguments[0].click();", target_button)
                        print("Klik JavaScript berhasil dieksekusi")
                
                # Tunggu 2 detik untuk melihat perubahan
                time.sleep(2)
                
                # VERIFIKASI: Cek apakah ada perubahan setelah klik
                try:
                    # Cek apakah elemen input produk muncul (indikator sukses)
                    input_produk = driver.find_elements(By.XPATH, "//input[contains(@class, 'TUXTextInputCore-input')]")
                    
                    if len(input_produk) > 0 and input_produk[0].is_displayed():
                        print("✓ VERIFIKASI BERHASIL: Input nama produk muncul, Next kedua berhasil diklik")
                    else:
                        # Cek apakah tombol Next masih ada dan sama
                        after_buttons = driver.find_elements(By.XPATH, "//button[.//div[text()='Next']]")
                        
                        if len(after_buttons) == len(next_buttons):
                            print("✗ VERIFIKASI GAGAL: Tombol Next masih sama, belum terklik")
                            print("  Mencoba metode alternatif...")
                            
                            # Metode alternatif: Klik koordinat atau tekan Enter
                            try:
                                # Coba tekan Enter pada radio button yang dipilih
                                target_radio_wrapper.send_keys(Keys.ENTER)
                                print("  Mengirim ENTER ke radio button")
                                time.sleep(2)
                            except:
                                pass
                            
                            # Cek lagi setelah metode alternatif
                            input_produk_after = driver.find_elements(By.XPATH, "//input[contains(@class, 'TUXTextInputCore-input')]")
                            if len(input_produk_after) > 0:
                                print("✓ Metode alternatif berhasil!")
                            else:
                                raise Exception("Tidak bisa klik Next kedua setelah semua percobaan")
                        else:
                            print("✓ Next kedua berhasil diklik (input produk muncul)")
                        
                except Exception as verify_error:
                    print(f"Error saat verifikasi: {verify_error}")
                    
            else:
                print("Tidak menemukan tombol Next yang sesuai")
                raise Exception("Tombol Next kedua tidak ditemukan")
                
        except Exception as e:
            print(f"Error di step D: {e}")
            
            # Tampilkan screenshot untuk debugging (jika memungkinkan)
            try:
                screenshot_path = "debug_next_button.png"
                driver.save_screenshot(screenshot_path)
                print(f"Screenshot disimpan ke {screenshot_path}")
            except:
                pass
                
            raise e

        # E. Isi Nama Produk (Input)
        try:
            nama_produk_input = "beli sebelum promonya habis"
            product_name_input = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//input[contains(@class, 'TUXTextInputCore-input')]")
            ))
            product_name_input.click()
            
            # Bersihkan input lama jika ada
            product_name_input.send_keys(Keys.CONTROL + "a")
            product_name_input.send_keys(Keys.BACKSPACE)
            
            # Isi dengan nama produk
            product_name_input.send_keys(nama_produk_input)
            print(f"Input nama produk diisi dengan: {nama_produk_input}")
            time.sleep(1)
        except Exception as e:
            print(f"Gagal mengisi input nama produk: {e}")
            raise e

        # F. Klik "Add" Terakhir
        # F. KLIK "ADD" TERAKHIR (PERBAIKAN)
        print("-" * 40)
        print("STEP F: Mencoba klik tombol Add terakhir...")
        
        try:
            time.sleep(2)
            
            # Strategi 1: Cari tombol Add yang visible dan berada di modal/dialog
            add_buttons = driver.find_elements(By.XPATH, "//button[.//div[text()='Add']]")
            print(f"Ditemukan {len(add_buttons)} tombol Add")
            
            target_add_button = None
            
            for i, btn in enumerate(add_buttons):
                print(f"Tombol Add {i+1}:")
                print(f"  - Visible: {btn.is_displayed()}")
                print(f"  - Enabled: {btn.is_enabled()}")
                print(f"  - Class: {btn.get_attribute('class')}")
                print(f"  - Text: {btn.text}")
                
                # Filter tombol yang visible
                if btn.is_displayed():
                    # Cek apakah tombol ini berada dalam konteks modal (kemungkinan besar yang terakhir)
                    parent_modal = btn.find_elements(By.XPATH, "./ancestor::div[contains(@class, 'modal') or contains(@class, 'Modal') or contains(@class, 'dialog')]")
                    if parent_modal:
                        print(f"  -> Tombol ini berada dalam modal, prioritas tinggi")
                        target_add_button = btn
                    elif target_add_button is None:
                        # Jika belum ada target, ambil yang visible saja
                        target_add_button = btn
                        print(f"  -> Tombol visible, dijadikan target sementara")
            
            if target_add_button:
                print(f"\nTombol Add target ditemukan, mencoba klik...")
                
                # Scroll ke tombol
                driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", target_add_button)
                time.sleep(1)
                
                # Metode 1: Klik dengan ActionChains (paling reliable)
                try:
                    actions = ActionChains(driver)
                    actions.move_to_element(target_add_button).click().perform()
                    print("✓ Klik Add dengan ActionChains berhasil")
                except Exception as e:
                    print(f"ActionChains gagal: {e}")
                    
                    # Metode 2: Klik dengan JavaScript
                    try:
                        driver.execute_script("arguments[0].click();", target_add_button)
                        print("✓ Klik Add dengan JavaScript berhasil")
                    except Exception as e2:
                        print(f"JavaScript click gagal: {e2}")
                        
                        # Metode 3: Klik koordinat
                        try:
                            location = target_add_button.location
                            size = target_add_button.size
                            x = location['x'] + size['width'] // 2
                            y = location['y'] + size['height'] // 2
                            
                            from selenium.webdriver.common.action_chains import ActionChains
                            actions = ActionChains(driver)
                            actions.move_by_offset(x, y).click().perform()
                            actions.move_by_offset(-x, -y).perform()  # Kembalikan ke posisi awal
                            print("✓ Klik Add dengan koordinat berhasil")
                        except Exception as e3:
                            print(f"Klik koordinat gagal: {e3}")
                            raise Exception("Semua metode klik Add gagal")
                
                time.sleep(2)
                
                # VERIFIKASI: Cek apakah tombol Add sudah tidak ada (berhasil)
                try:
                    after_click_buttons = driver.find_elements(By.XPATH, "//button[.//div[text()='Add']]")
                    visible_after = [btn for btn in after_click_buttons if btn.is_displayed()]
                    
                    if len(visible_after) < len([btn for btn in add_buttons if btn.is_displayed()]):
                        print("✓ VERIFIKASI BERHASIL: Tombol Add berkurang/ hilang")
                    else:
                        # Cek apakah ada indikator produk ditambahkan
                        success_indicator = driver.find_elements(By.XPATH, "//*[contains(text(), 'added') or contains(text(), 'Added') or contains(text(), 'success')]")
                        if success_indicator:
                            print("✓ VERIFIKASI BERHASIL: Ada indikator produk ditambahkan")
                        else:
                            print("⚠ VERIFIKASI: Tombol Add masih ada, mungkin perlu menunggu")
                            time.sleep(2)
                except:
                    pass
                    
            else:
                print("Tidak menemukan tombol Add yang visible")
                
                # Strategi 2: Cari berdasarkan teks dan class
                try:
                    print("Mencoba strategi alternatif...")
                    alt_add_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'primary') and .//div[text()='Add']]")
                    driver.execute_script("arguments[0].click();", alt_add_btn)
                    print("✓ Berhasil klik Add dengan selector alternatif")
                except:
                    # Strategi 3: Cari di footer modal
                    try:
                        footer_add_btn = driver.find_element(By.XPATH, "//div[contains(@class, 'footer')]//button[.//div[text()='Add']]")
                        driver.execute_script("arguments[0].click();", footer_add_btn)
                        print("✓ Berhasil klik Add di footer")
                    except Exception as e:
                        print(f"Semua strategi gagal: {e}")
                        raise Exception("Tidak bisa klik tombol Add terakhir")
        
        except Exception as e:
            print(f"Error di step F: {e}")
            
            # Screenshot untuk debugging
            try:
                driver.save_screenshot("debug_add_button.png")
                print("Screenshot disimpan ke debug_add_button.png")
            except:
                pass
            
            raise e

        print("\n✓ Selesai menambahkan produk!")

        # G. Pengaturan Lanjutan (Show More & Switches)
        try:
            print("-" * 40)
            print("STEP G: Mengatur Show More & Switches...")
            time.sleep(1)

            # 1. Klik Show More
            try:
                show_more = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@data-e2e='advanced_settings_container']")
                ))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", show_more)
                show_more.click()
                print("✓ Tombol 'Show more' diklik")
                time.sleep(2) # Tunggu animasi expand selesai
            except Exception as e:
                print(f"Gagal klik Show more: {e}")

            # 2. Klik Switch 1: Disclose post content
            try:
                # Strategi: Cari teks 'Disclose post content', lalu cari switch di dalam container yang sama atau sibling
                # XPath: Cari div dengan teks tersebut, lalu cari elemen switch di dalamnya
                xpath_switch_1 = "//div[@data-e2e='disclose_content_container']//div[contains(@class, 'Switch__content')]"
                
                switch_1 = wait.until(EC.presence_of_element_located((By.XPATH, xpath_switch_1)))
                
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", switch_1)
                time.sleep(1)
                
                # Cek status switch (opsional, tapi bagus untuk memastikan)
                # is_checked = switch_1.get_attribute("aria-checked") == "true"
                
                driver.execute_script("arguments[0].click();", switch_1)
                print("✓ Switch 'Disclose post content' diklik")
                time.sleep(2) # Tunggu efek switch (checkbox muncul)
            except Exception as e:
                print(f"Gagal klik Switch 'Disclose post content': {e}")

            # 3. Klik Checkbox (Branded Content)
            try:
                # XPath checkbox: Label preceding 'Branded content'
                xpath_checkbox = "//span[contains(., 'Branded content')]/preceding-sibling::label"
                
                target_checkbox = wait.until(EC.presence_of_element_located(
                    (By.XPATH, xpath_checkbox)
                ))
                
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_checkbox)
                time.sleep(1)
                
                driver.execute_script("arguments[0].click();", target_checkbox)
                print("✓ Checkbox 'Branded content' diklik")
                time.sleep(1)
            except Exception as e:
                print(f"Gagal klik Checkbox Branded Content: {e}")
                # Fallback
                try:
                    fallback_cb = driver.find_element(By.XPATH, "//span[contains(., 'Your brand')]/preceding-sibling::label")
                    driver.execute_script("arguments[0].click();", fallback_cb)
                    print("✓ Checkbox 'Your brand' (fallback) diklik")
                except:
                    pass

            # 4. Klik Switch 2: AI-generated content
            try:
                # Strategi: Cari container dengan data-e2e='aigc_container' lalu switch di dalamnya
                xpath_switch_2 = "//div[@data-e2e='aigc_container']//div[contains(@class, 'Switch__content')]"
                
                switch_2 = wait.until(EC.presence_of_element_located((By.XPATH, xpath_switch_2)))
                
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", switch_2)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", switch_2)
                print("✓ Switch 'AI-generated content' diklik")
            except Exception as e:
                # Fallback cari text manual jika container id berubah
                try:
                    xpath_fallback = "//span[contains(text(), 'AI-generated content')]/ancestor::div[contains(@class, 'container')]//div[contains(@class, 'Switch__content')]"
                    switch_2_alt = driver.find_element(By.XPATH, xpath_fallback)
                    driver.execute_script("arguments[0].click();", switch_2_alt)
                    print("✓ Switch 'AI-generated content' (fallback) diklik")
                except Exception as ex_fallback:
                    print(f"Gagal klik Switch 'AI-generated content': {e}")

        except Exception as e:
            print(f"Error di Step G: {e}")

        # H. Klik tombol Sounds
        try:
            print("-" * 40)
            print("STEP H: Klik tombol Sounds...")
            time.sleep(2)

            sounds_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[@data-button-name='sounds']")
            ))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", sounds_btn)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", sounds_btn)
            print("✓ Tombol 'Sounds' diklik")
            time.sleep(3)  # Tunggu halaman sound muncul
        except Exception as e:
            print(f"Gagal klik Sounds: {e}")
            raise e

        # I. Klik tab Favorites
        try:
            print("-" * 40)
            print("STEP I: Klik tab Favorites...")

            # Tunggu sampai tab Favorites muncul dan bisa diklik
            favorites_tab = WebDriverWait(driver, 15).until(EC.element_to_be_clickable(
                (By.XPATH, "//button[@role='tab' and @aria-controls='panel-favorites']")
            ))
            time.sleep(1)
            driver.execute_script("arguments[0].click();", favorites_tab)
            print("✓ Tab 'Favorites' diklik")
            time.sleep(3)  # Tunggu daftar favorites muncul
        except Exception as e:
            print(f"Gagal klik tab Favorites: {e}")
            raise e

        # J. Klik tombol + untuk menambahkan sound
        try:
            print("-" * 40)
            print("STEP J: Klik tombol + untuk menambahkan sound...")
            time.sleep(2)

            # Cari tombol + (PlusBold icon, data-icon-only="true", stroke type)
            add_sound_btn = WebDriverWait(driver, 15).until(EC.element_to_be_clickable(
                (By.XPATH, "//button[@data-icon-only='true' and @data-type='stroke' and .//span[@data-icon='PlusBold']]")
            ))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_sound_btn)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", add_sound_btn)
            print("✓ Tombol '+' sound diklik")

            # Tunggu sampai tombol + menjadi disabled (sound berhasil ditambahkan)
            print("Menunggu sound ditambahkan (tombol + menjadi disabled)...")
            WebDriverWait(driver, 30).until(
                lambda d: d.find_element(
                    By.XPATH, "//button[@data-icon-only='true' and @data-type='stroke' and .//span[@data-icon='PlusBold']]"
                ).get_attribute("aria-disabled") == "true"
                or d.find_element(
                    By.XPATH, "//button[@data-icon-only='true' and @data-type='stroke' and .//span[@data-icon='PlusBold']]"
                ).get_attribute("data-disabled") == "true"
                or not d.find_element(
                    By.XPATH, "//button[@data-icon-only='true' and @data-type='stroke' and .//span[@data-icon='PlusBold']]"
                ).is_enabled()
            )
            print("✓ Sound berhasil ditambahkan (tombol + sudah disabled)")
            time.sleep(1)
        except Exception as e:
            print(f"Gagal menambahkan sound: {e}")
            raise e

        # J2. Matikan sound ori video (klik tombol VolumeUp)
        try:
            print("-" * 40)
            print("STEP J2: Matikan sound original video...")
            time.sleep(1)

            # Cari tombol volume (icon VolumeUp) - data-icon-only="true" dan data-type="text"
            volume_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
                (By.XPATH, "//button[@data-icon-only='true' and @data-type='text' and .//span[@data-icon='VolumeUp']]")
            ))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", volume_btn)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", volume_btn)
            print("✓ Sound original video di-mute (VolumeUp diklik)")
            time.sleep(1)
        except Exception as e:
            print(f"⚠ Gagal mute sound original: {e}")
            # Tidak raise karena ini opsional, lanjut ke Save

        # K. Klik tombol Save
        try:
            print("-" * 40)
            print("STEP K: Klik tombol Save...")
            time.sleep(1)

            save_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
                (By.XPATH, "//div[contains(@class, 'Button__content') and contains(@class, 'type-primary')]//*[text()='Save']/ancestor::button | //button[.//div[contains(@class, 'Button__content') and contains(@class, 'type-primary') and .//text()='Save']]")
            ))
            driver.execute_script("arguments[0].click();", save_btn)
            print("✓ Tombol 'Save' diklik")
            time.sleep(3)  # Tunggu kembali ke halaman utama
        except Exception as e:
            # Fallback: cari tombol Save dengan cara lain
            try:
                print(f"Mencoba fallback Save: {e}")
                save_btn_alt = driver.find_element(
                    By.XPATH, "//div[contains(@class, 'Button__content') and contains(., 'Save')]/ancestor::button"
                )
                driver.execute_script("arguments[0].click();", save_btn_alt)
                print("✓ Tombol 'Save' diklik (fallback)")
                time.sleep(3)
            except Exception as e2:
                print(f"Gagal klik Save: {e2}")
                raise e2

        # L. Atur Schedule Posting
        try:
            print("-" * 40)
            print("STEP L: Mengatur Schedule Posting...")

            # Tunggu sampai "When to post" muncul
            print("Menunggu 'When to post' muncul...")
            WebDriverWait(driver, 15).until(EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(), 'When to post')]")
            ))
            print("✓ 'When to post' ditemukan")
            time.sleep(1)

            # Pilih radio button 'Schedule'
            print("Memilih radio button 'Schedule'...")
            schedule_radio = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//input[@name='postSchedule' and @value='schedule']/ancestor::label")
            ))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", schedule_radio)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", schedule_radio)
            print("✓ Radio button 'Schedule' dipilih")
            time.sleep(2)  # Tunggu pengaturan jam dan tanggal muncul

            # Atur Jam: 01:00 (1 AM)
            # DOM: div.tiktok-timepicker-time-picker-container
            #   div.tiktok-timepicker-time-scroll-container (jam - left)
            #     span.tiktok-timepicker-option-text.tiktok-timepicker-left "01"
            #   div.tiktok-timepicker-time-scroll-container (menit - right)  
            #     span.tiktok-timepicker-option-text.tiktok-timepicker-right "00"
            print("Mengatur jam ke 01:00...")
            time_input = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//div[contains(@class, 'TUXTextInputCore')]//input[@readonly and (contains(@value, ':'))]")
            ))
            # Klik input waktu untuk membuka scroll picker
            driver.execute_script("arguments[0].click();", time_input)
            time.sleep(2)

            # Klik jam "01" di kolom kiri
            try:
                hour_span = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, "//div[contains(@class, 'tiktok-timepicker-time-picker-container')]//span[contains(@class, 'tiktok-timepicker-left') and text()='23']")
                ))
                hour_span.click()
                print("✓ Jam '01' diklik")
            except Exception as e_h:
                print(f"⚠ Gagal klik jam 01: {e_h}")
                # Fallback: scroll ke atas dulu
                try:
                    hour_container = driver.find_element(
                        By.XPATH, "//div[contains(@class, 'tiktok-timepicker-time-picker-container')]//div[contains(@class, 'tiktok-timepicker-time-scroll-container')][1]"
                    )
                    driver.execute_script("arguments[0].scrollTop = 0;", hour_container)
                    time.sleep(1)
                    hour_span = driver.find_element(
                        By.XPATH, "//span[contains(@class, 'tiktok-timepicker-left') and text()='01']"
                    )
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", hour_span)
                    time.sleep(0.5)
                    hour_span.click()
                    print("✓ Jam '01' diklik (setelah scroll)")
                except Exception as e_h2:
                    print(f"⚠ Gagal klik jam (fallback): {e_h2}")
            
            time.sleep(1)

            # Klik menit "00" di kolom kanan
            try:
                minute_span = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, "//div[contains(@class, 'tiktok-timepicker-time-picker-container')]//span[contains(@class, 'tiktok-timepicker-right') and text()='00']")
                ))
                minute_span.click()
                print("✓ Menit '00' diklik")
            except Exception as e_m:
                print(f"⚠ Gagal klik menit 00: {e_m}")
                # Fallback: scroll ke atas dulu
                try:
                    minute_container = driver.find_elements(
                        By.XPATH, "//div[contains(@class, 'tiktok-timepicker-time-picker-container')]//div[contains(@class, 'tiktok-timepicker-time-scroll-container')]"
                    )
                    if len(minute_container) >= 2:
                        driver.execute_script("arguments[0].scrollTop = 0;", minute_container[1])
                        time.sleep(1)
                    minute_span = driver.find_element(
                        By.XPATH, "//span[contains(@class, 'tiktok-timepicker-right') and text()='00']"
                    )
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", minute_span)
                    time.sleep(0.5)
                    minute_span.click()
                    print("✓ Menit '00' diklik (setelah scroll)")
                except Exception as e_m2:
                    print(f"⚠ Gagal klik menit (fallback): {e_m2}")

            print("✓ Waktu diatur ke 01:00")
            time.sleep(1)

            # Klik di luar untuk menutup time picker
            driver.execute_script("document.body.click();")
            time.sleep(1)

            # Atur Tanggal: Besok
            # DOM: div.calendar-wrapper
            #   div.days-wrapper > div.day-span-container > span.day.valid "20"
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            tomorrow_day = str((datetime.now() + timedelta(days=1)).day)
            print(f"Mengatur tanggal ke {tomorrow} (hari ke-{tomorrow_day})...")

            # Klik input tanggal untuk membuka calendar picker
            date_inputs = driver.find_elements(
                By.XPATH, "//div[contains(@class, 'TUXTextInputCore')]//input[@readonly]"
            )
            date_input = None
            for di in date_inputs:
                val = di.get_attribute("value") or ""
                if "-" in val and len(val) == 10 and di.is_displayed():
                    date_input = di
                    break
            
            if date_input:
                driver.execute_script("arguments[0].click();", date_input)
                time.sleep(2)
            else:
                print("⚠ Input tanggal tidak ditemukan")

            # Klik tanggal besok di kalender (span.day.valid)
            try:
                # Cari span.day.valid yang teksnya = tanggal besok
                date_span = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
                    (By.XPATH, f"//div[contains(@class, 'calendar-wrapper')]//span[contains(@class, 'day') and contains(@class, 'valid') and text()='{tomorrow_day}']")
                ))
                date_span.click()
                print(f"✓ Tanggal {tomorrow} dipilih")
            except Exception as e_date:
                print(f"⚠ Gagal klik tanggal via class valid: {e_date}")
                # Fallback: cari semua span.day di calendar-wrapper
                try:
                    day_spans = driver.find_elements(
                        By.XPATH, "//div[contains(@class, 'calendar-wrapper')]//span[contains(@class, 'day')]"
                    )
                    date_clicked = False
                    for ds in day_spans:
                        if ds.text.strip() == tomorrow_day and ds.is_displayed():
                            ds_class = ds.get_attribute("class") or ""
                            # Pastikan bukan header (day-header)
                            if "header" not in ds_class:
                                ds.click()
                                print(f"✓ Tanggal {tomorrow} dipilih (fallback)")
                                date_clicked = True
                                break
                    if not date_clicked:
                        print(f"⚠ Tidak menemukan tanggal {tomorrow_day} di kalender")
                except Exception as e_date2:
                    print(f"⚠ Gagal atur tanggal (fallback): {e_date2}")
            time.sleep(2)

            print("✓ Schedule posting berhasil diatur!")

        except Exception as e:
            print(f"Error di Step L (Schedule): {e}")
            raise e

    except Exception as e:
        print(f"\n❌ Terjadi kesalahan: {e}")
        try:
            print(f"Current URL: {driver.current_url}")
        except:
            pass
        
def klik_post_final(driver):
    # --- KONFIRMASI MANUAL (Comment block ini jika ingin auto-post) ---
    print("\n" + "="*40)
    try:
        konfirmasi = input(">>> SELESAI EDIT. Lanjutkan posting? (y/n): ")
        if konfirmasi.lower() != 'y':
            print("❌ Posting dibatalkan oleh pengguna.")
            return
    except Exception:
        pass # Handle case jika input error
    print("="*40 + "\n")
    # ------------------------------------------------------------------

    wait = WebDriverWait(driver, 20)
    try:
        # Klik Schedule (tombol post untuk scheduled posting)
        print("Mencoba klik tombol Schedule...")
        
        # Cari tombol Schedule/Post
        schedule_button = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//button[@data-e2e='post_video_button' or @data-e2e='schedule_video_button'] | //button[.//div[text()='Schedule']]")
        ))

        # Pastikan tombol terlihat (scroll)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", schedule_button)
        time.sleep(2)

        # Gunakan JS Click untuk menembus overlay modal jika masih ada
        driver.execute_script("arguments[0].click();", schedule_button)
        print("✓ Perintah klik Schedule/Post dikirim via JavaScript.")

        # Tangani pop-up konfirmasi jika muncul
        try:
            print("Mengecek konfirmasi akhir...")
            confirm_btn = WebDriverWait(driver, 7).until(EC.element_to_be_clickable(
                (By.XPATH, "//button[.//div[text()='Schedule' or text()='Post now' or text()='Confirm']]")
            ))
            driver.execute_script("arguments[0].click();", confirm_btn)
            print("✓ Konfirmasi akhir diklik.")
        except:
            print("Modal konfirmasi tidak muncul atau tidak diperlukan.")

        print("\n✓ Video berhasil di-schedule!")

    except Exception as e:
        print(f"Gagal saat proses posting akhir: {e}")


if __name__ == "__main__":
    nama_produk = "beli sebelum promonya habis"
    # Gunakan absolute path
    my_desc = "Segera Try out di speedu.online"
    # Ganti string ini dengan nama produk yang sesuai di akun Anda (persis dengan di HTML)
    my_product = "X-Prime Tablet Matepad Pro XPRIME S25 5G Snapdragon 888 10.1 Inch HD 120Hz 16GB RAM 1TB ROM 8800mAh 11-core Wifi Bluetooth 2 Ultra-high-performance Desain Elegan dan Modern 10.1 inch HD 120Hz 16GB+1TB Android 15 8800mAh 11-core  2 Get 8" 
    video_path = r"C:\tiktok_automation\1.mp4"
    chrome_process = buka_chrome_debug()
    time.sleep(1)
    
    driver = jalankan_selenium()
    if driver:
        print("Siap melakukan otomasi!")
        try:
            simulasi_upload(driver, video_path)
            time.sleep(5) 
            proses_post_video(driver, my_desc, my_product)
            klik_post_final(driver)
        except Exception as e:
            print(f"Terjadi error: {e}")
        finally:
            print("Cleaning up...")
            try:
                driver.quit()
            except:
                pass
            
            if chrome_process:
                print(f"Menutup Chrome (PID: {chrome_process.pid})...")
                chrome_process.terminate()
                print("Chrome process terminated.")
  