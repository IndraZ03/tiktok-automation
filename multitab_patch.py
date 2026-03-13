import codecs

with open('multitab_helpers.py', 'r', encoding='utf-8') as f:
    helpers = f.read()

new_func = '''
# ═══════════════════════════════════════════════════════════════
#  MULTI-TAB GENERATION (2 VIDEOS AT ONCE)
# ═══════════════════════════════════════════════════════════════
def generate_two_videos_multitab_grok(image_path, prompt_text, log_fn, stop_event, output_dir, 
                                      user_data_dir=None, port=None, progress_callback=None):
    from sgv_config import DEFAULT_PORT, USER_DATA_CHROME, GROK_URL
    import time
    import os

    ud = user_data_dir or USER_DATA_CHROME
    pt = port or DEFAULT_PORT

    chrome_proc = open_chrome_grok(ud, pt)
    driver = None
    vid1_path = None
    vid2_path = None

    try:
        driver = connect_selenium_grok(pt)
        driver.execute_cdp_cmd("Page.setDownloadBehavior",
                               {"behavior": "allow", "downloadPath": output_dir})

        tab_handles = []
        tab_status = {}   # idx -> "generating" | "done" | "failed"
        tab_progress = {} # idx -> pct
        tab_start_time = time.time()
        
        abs_image = os.path.abspath(image_path) if (image_path and os.path.exists(str(image_path))) else None

        for i in range(2):
            if stop_event.is_set():
                break

            if i == 0:
                driver.get(GROK_URL)
                time.sleep(3)
            else:
                driver.switch_to.new_window('tab')
                driver.get(GROK_URL)
                time.sleep(3)

            handle = driver.current_window_handle
            tab_handles.append(handle)

            log_fn(f"[Tab {i+1}] 🌐 Halaman dimuat")
            ok = setup_tab_grok(driver, abs_image, prompt_text, log_fn, i)
            if ok:
                tab_status[i] = "generating"
                tab_progress[i] = 0
            else:
                tab_status[i] = "failed"
                tab_progress[i] = 0

            time.sleep(1)

        if stop_event.is_set():
            return None, None

        timeout_start = time.time()
        MAX_TIMEOUT = 600

        downloaded_videos = {0: None, 1: None}

        while not stop_event.is_set():
            active_tabs = [i for i, s in tab_status.items() if s == "generating"]
            if not active_tabs:
                break

            if time.time() - timeout_start > MAX_TIMEOUT:
                log_fn("⏰ Timeout 10 menit, menyelesaikan batch multitab...")
                for i in active_tabs:
                    tab_status[i] = "failed"
                break

            for i in active_tabs:
                if stop_event.is_set():
                    break
                try:
                    driver.switch_to.window(tab_handles[i])
                    status, pct = check_tab_progress(driver)

                    if pct != tab_progress.get(i, 0):
                        tab_progress[i] = pct
                        if progress_callback:
                            avg_pct = int((tab_progress.get(0,0) + tab_progress.get(1,0)) / 2)
                            try:
                                progress_callback(avg_pct)
                            except:
                                pass

                    if status == "done":
                        log_fn(f"[Tab {i+1}] ✅ Video selesai! Mengunduh...")
                        v_path = download_tab_video(driver, output_dir, log_fn, i, tab_start_time)
                        if v_path and os.path.exists(v_path):
                            tab_status[i] = "done"
                            downloaded_videos[i] = v_path
                        else:
                            tab_status[i] = "failed"
                except Exception as ex:
                    pass

            time.sleep(1)
            
        vid1_path = downloaded_videos.get(0)
        vid2_path = downloaded_videos.get(1)
        if progress_callback:
            try: progress_callback(100)
            except: pass
        return vid1_path, vid2_path

    finally:
        try:
            if driver:
                driver.quit()
        except:
            pass
        try:
            chrome_proc.terminate()
        except:
            pass
'''

with codecs.open('sgv_selenium.py', 'a', encoding='utf-8') as f:
    f.write('\n\n# --- MULTITAB HELPERS INCORPORATED ---\n')
    f.write(helpers)
    f.write('\n\n')
    f.write(new_func)
