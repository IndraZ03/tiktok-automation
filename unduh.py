from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import time

import os

def connect_selenium_debug():
    """Hanya mencoba menghubungkan ke Chrome yang SUDAH berjalan di port 9222"""
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    try:
        print("Mencoba menghubungkan ke Chrome (Port 9222)...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        print("Berhasil terhubung ke Chrome!")
        return driver
    except Exception as e:
        print(f"Gagal menghubungkan Selenium. Pastikan Chrome sudah dibuka via flow.py debug port 9222.")
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    # Langsung connect tanpa membuka Chrome baru
    driver = connect_selenium_debug()
    
    if driver:
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
        wait = WebDriverWait(driver, 20)
        action = ActionChains(driver)

        try:
            # 1. Cari Tombol Download Langsung (Tanpa Hover Container spesifik yang class-nya berubah)
            print("Mencari tombol Download...")
            
            # XPath untuk mencari button yang mengandung text 'Download' (baik di span atau i)
            # Kita gunakan '//*' untuk lebih general jika bukan button langsung
            xpath_download_btns = "//button[.//span[contains(text(), 'Download')] or .//i[contains(text(), 'download')]]"
            
            try:
                # Tunggu setidaknya satu tombol download muncul di DOM
                wait.until(EC.presence_of_element_located((By.XPATH, xpath_download_btns)))
            except:
                print("Tidak menemukan elemen tombol Download di DOM.")

            download_btns = driver.find_elements(By.XPATH, xpath_download_btns)
            print(f"Ditemukan {len(download_btns)} kandidat tombol Download.")
            
            download_success = False
            for i, btn in enumerate(download_btns):
                print(f"  Cek tombol {i+1}...")
                try:
                    # Coba scroll ke tombol biar visible
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                    time.sleep(1)
                    
                    if btn.is_displayed():
                        print("    Tombol terlihat (displayed).")
                        # Coba hover dulu siapa tahu perlu hover
                        action.move_to_element(btn).perform()
                        time.sleep(0.5)
                        
                        btn.click()
                        print("    Klik standar berhasil.")
                        download_success = True
                        break
                    else:
                        print("    Tombol tidak terlihat (hidden). Mencoba paksa klik JS...")
                        # Jika hidden, mungkin perlu hover parentnya dulu atau langsung JS click
                        # Coba hover parent
                        parent = btn.find_element(By.XPATH, "./..")
                        action.move_to_element(parent).perform()
                        time.sleep(0.5)
                        
                        driver.execute_script("arguments[0].click();", btn)
                        print("    Klik JS berhasil.")
                        download_success = True
                        break
                except Exception as e:
                    print(f"    Gagal interaksi dengan tombol ini: {e}")
                    # Coba fallback JS click terakhir
                    try:
                        driver.execute_script("arguments[0].click();", btn)
                        print("    Force JS click berhasil (rescue).")
                        download_success = True
                        break
                    except:
                        pass
            
            if not download_success:
                print("Gagal menekan tombol Download manapun.")
                # Debugging: Print page source snippet or structure if needed
                # raise Exception("Gagal Download")
            else:
                print("Tombol Download berhasil ditekan.")

            # 3. Pilih Resolusi dari Dropdown
            print("Mencari opsi 'Ukuran asli (720p)'...")
            
            # Coba cari elemen dengan beberapa variasi XPath
            # Kadang textnya dipecah atau ada di child elements
            xpaths_res = [
                "//*[contains(text(), 'Ukuran asli') and contains(text(), '720p')]", # Gabung
                "//*[contains(text(), '720p')]", # Cuma 720p
                "//div[contains(., 'Ukuran asli') and contains(., '720p')]", # Container text
                "//button[contains(., '720p')]" # Button
            ]
            
            res_clicked = False
            for xpath in xpaths_res:
                if res_clicked: break
                try:
                    candidates = driver.find_elements(By.XPATH, xpath)
                    for cand in candidates:
                        if cand.is_displayed():
                            print(f"Ditemukan kandidat resolusi dengan xpath: {xpath}")
                            # Coba ActionChains dulu (lebih natural)
                            try:
                                action.move_to_element(cand).click().perform()
                                print("Klik ActionChains berhasil.")
                                res_clicked = True
                                break
                            except:
                                # Fallback JS
                                driver.execute_script("arguments[0].click();", cand)
                                print("Klik JS fallback berhasil.")
                                res_clicked = True
                                break
                except:
                    pass
            
            if not res_clicked:
                print("Gagal menemukan opsi 720p dengan selector standard. Mencoba debug dump...")
                # Optional: Print semua text di dropdown jika gagal
                try:
                    dropdowns = driver.find_elements(By.XPATH, "//div[@role='menu'] | //div[contains(@class, 'sc-')]")
                    for d in dropdowns:
                        if d.is_displayed():
                            print(f"Dropdown Content: {d.text}")
                except:
                    pass
                raise Exception("Gagal klik opsi resolusi 720p.")
            
            print("Proses download selesai trigger.")
            time.sleep(5)

        except Exception as e:
            print(f"Terjadi kesalahan: {e}")
            import traceback
            traceback.print_exc()
