"""
═══════════════════════════════════════════════════════════════
  PART 2: SGV_SELENIUM - Selenium & Video Generation Engine
  SuperGrok One Video Bot - Chrome automation for Grok Imagine
═══════════════════════════════════════════════════════════════
"""

import os
import re
import time
import glob
import shutil
import subprocess
import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from sgv_config import GROK_URL

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  CHROME: OPEN & CONNECT
# ═══════════════════════════════════════════════════════════════
def open_chrome_grok(user_data_dir, port):
    """Open Chrome with remote debugging at Grok Imagine."""
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    proc = subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run", "--no-default-browser-check",
        GROK_URL
    ])
    time.sleep(5)
    return proc


def connect_selenium_grok(port):
    """Connect Selenium to existing Chrome debug instance."""
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    svc = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=svc, options=opts)


def navigate_to_grok(driver, log_fn, max_retries=3):
    """Navigate to grok.com/imagine with retry logic."""
    for attempt in range(1, max_retries + 1):
        try:
            current = driver.current_url
            if "grok.com" in current and "imagine" in current:
                log_fn("✅ Sudah di halaman Grok Imagine")
                return True
        except:
            pass

        try:
            log_fn(f"🌐 Navigasi ke Grok Imagine (attempt {attempt}/{max_retries})...")
            driver.get(GROK_URL)
            time.sleep(5)
            current = driver.current_url
            if "imagine" in current:
                log_fn("✅ Navigasi berhasil!")
                return True
        except Exception as e:
            log_fn(f"⚠️ Navigasi gagal: {e}")

        if attempt < max_retries:
            try:
                log_fn("🔄 Membuka tab baru...")
                driver.switch_to.new_window('tab')
                driver.get(GROK_URL)
                time.sleep(5)
                if "imagine" in driver.current_url:
                    log_fn("✅ Navigasi berhasil via tab baru!")
                    return True
            except Exception as e:
                log_fn(f"⚠️ Tab baru gagal: {e}")

    log_fn("❌ Gagal navigasi ke Grok Imagine")
    return False


# ═══════════════════════════════════════════════════════════════
#  VIDEO MERGE (FFmpeg concat)
# ═══════════════════════════════════════════════════════════════
def merge_video_pair(vid1: str, vid2: str, output_dir: str, log_fn=None):
    """
    Gabungkan 2 video menjadi 1 menggunakan FFmpeg concat demuxer.
    Returns path to merged video or None on failure.
    """
    os.makedirs(output_dir, exist_ok=True)

    existing = glob.glob(os.path.join(output_dir, "*.mp4"))
    existing_nums = []
    for f in existing:
        m = re.fullmatch(r'(\d+)\.mp4', os.path.basename(f))
        if m:
            existing_nums.append(int(m.group(1)))
    next_num = (max(existing_nums) + 1) if existing_nums else 1

    out_name = f"merged_{next_num}.mp4"
    out_path = os.path.join(output_dir, out_name)

    list_file = os.path.join(output_dir, f"_merge_list_{next_num}.txt")
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
        if log_fn:
            log_fn(f"🎬 Merge: {os.path.basename(vid1)} + {os.path.basename(vid2)} → {out_name}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            if log_fn:
                sz = os.path.getsize(out_path) / (1024 * 1024)
                log_fn(f"✅ Merged: {out_name} ({sz:.1f} MB)")
            return out_path
        else:
            if log_fn:
                log_fn(f"❌ Merge gagal: {result.stderr[-200:] if result.stderr else 'unknown'}")
            return None
    except FileNotFoundError:
        if log_fn:
            log_fn("❌ FFmpeg tidak ditemukan! Pastikan ffmpeg ada di PATH.")
        return None
    except subprocess.TimeoutExpired:
        if log_fn:
            log_fn("⚠️ FFmpeg merge timeout (120s)")
        return None
    except Exception as e:
        if log_fn:
            log_fn(f"❌ Error merge: {str(e)[:100]}")
        return None
    finally:
        if os.path.exists(list_file):
            try:
                os.remove(list_file)
            except:
                pass


# ═══════════════════════════════════════════════════════════════
#  IMAGE UPLOAD HELPERS
# ═══════════════════════════════════════════════════════════════
def _count_uploaded_images(drv):
    try:
        return drv.execute_script("""
            let c = 0;
            c += document.querySelectorAll('img[src*="assets.grok.com"]').length;
            c += document.querySelectorAll('img[src^="blob:"]').length;
            c += document.querySelectorAll('div.group.relative img').length;
            return c;
        """)
    except:
        return 0


def _verify_image_uploaded(drv, before_count, timeout=10):
    for _ in range(timeout * 2):
        try:
            if _count_uploaded_images(drv) > before_count:
                return True
            has_preview = drv.execute_script("""
                const g = document.querySelector('div.group.relative');
                if (g) { const r = g.getBoundingClientRect();
                    if (r.width > 50 && r.height > 50) return true; }
                return false;
            """)
            if has_preview:
                return True
        except:
            pass
        time.sleep(0.5)
    return False


def _try_upload_image(drv, abs_img, before_count, log_fn):
    """Try all upload methods. Returns True if verified uploaded."""
    # Method A: find existing file inputs
    try:
        inputs = drv.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if inputs:
            log_fn(f"🔍 {len(inputs)} file input ditemukan")
            for idx2, fi in enumerate(inputs):
                try:
                    drv.execute_script(
                        "arguments[0].style.cssText='display:block!important;"
                        "visibility:visible!important;opacity:1!important;"
                        "position:absolute;top:0;left:0;width:1px;height:1px;';", fi)
                    fi.send_keys(abs_img)
                    log_fn(f"📤 Sent ke input[{idx2}], verifikasi...")
                    time.sleep(3)
                    if _verify_image_uploaded(drv, before_count):
                        log_fn("✅ Upload berhasil (Method A)!")
                        return True
                    log_fn(f"⚠️ Input[{idx2}] tidak ada preview")
                except Exception as ex:
                    log_fn(f"⚠️ Input[{idx2}] err: {ex}")
    except Exception as ex:
        log_fn(f"⚠️ Method A err: {ex}")

    # Method B: inject new file input
    try:
        log_fn("🔄 Method B: inject file input...")
        iid = f"_gbf_{int(time.time())}"
        drv.execute_script(f"""
            let o = document.getElementById('{iid}'); if(o) o.remove();
            const inp = document.createElement('input');
            inp.type='file'; inp.id='{iid}'; inp.accept='image/*';
            inp.style.cssText='position:absolute;top:0;left:0;z-index:99999;'
                              'display:block;width:1px;height:1px;';
            document.body.appendChild(inp);
        """)
        time.sleep(0.5)
        inj = drv.find_element(By.ID, iid)
        inj.send_keys(abs_img)
        log_fn("📤 Sent ke injected input, verifikasi...")
        time.sleep(3)
        if _verify_image_uploaded(drv, before_count):
            log_fn("✅ Upload berhasil (Method B)!")
            return True
        log_fn("⚠️ Injected input tidak ada preview")
    except Exception as ex:
        log_fn(f"⚠️ Method B err: {ex}")

    return False


# ═══════════════════════════════════════════════════════════════
#  PROMPT FILL HELPERS
# ═══════════════════════════════════════════════════════════════
def _try_fill_prompt(drv, p_text, log_fn):
    """Try filling prompt. Returns True on success."""
    # Method A: click + JS innerHTML
    try:
        ed = drv.execute_script("""
            const e = document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
            if (e) { e.scrollIntoView({behavior:'smooth',block:'center'}); return e; }
            return null;
        """)
        if ed:
            time.sleep(0.4)
            drv.execute_script("arguments[0].focus();", ed)
            time.sleep(0.3)
            ed.click()
            time.sleep(0.3)
            ed.send_keys(Keys.CONTROL + "a")
            time.sleep(0.2)
            ed.send_keys(Keys.DELETE)
            time.sleep(0.2)
            drv.execute_script("""
                const e=arguments[0];
                e.innerHTML='<p>'+arguments[1]+'</p>';
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
                e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));
            """, ed, p_text)
            time.sleep(1)
            actual = drv.execute_script(
                "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent || '';")
            if actual.strip():
                log_fn(f"✅ Prompt diisi (Method A): {p_text[:60]}...")
                return True
    except Exception as ex:
        log_fn(f"⚠️ Prompt Method A: {ex}")

    # Method B: pure JS
    try:
        log_fn("🔄 Prompt Method B: pure JS...")
        r = drv.execute_script("""
            const e=document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
            if (!e) return 'not_found';
            e.scrollIntoView({block:'center'}); e.focus();
            e.innerHTML='<p>'+arguments[0]+'</p>';
            e.dispatchEvent(new Event('input',{bubbles:true}));
            e.dispatchEvent(new Event('change',{bubbles:true}));
            e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));
            return 'ok';
        """, p_text)
        if r == 'ok':
            time.sleep(1)
            actual = drv.execute_script(
                "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent || '';")
            if actual.strip():
                log_fn(f"✅ Prompt diisi (Method B): {p_text[:60]}...")
                return True
        else:
            log_fn("⚠️ Editor tidak ada di DOM")
    except Exception as ex:
        log_fn(f"⚠️ Prompt Method B: {ex}")

    # Method C: WebDriverWait + typing
    try:
        log_fn("🔄 Prompt Method C: typing...")
        ed = WebDriverWait(drv, 20).until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, 'div.tiptap.ProseMirror[contenteditable="true"]')))
        drv.execute_script("arguments[0].scrollIntoView({block:'center'});", ed)
        time.sleep(1)
        ed.click()
        time.sleep(0.5)
        ed.send_keys(Keys.CONTROL + "a")
        ed.send_keys(Keys.DELETE)
        time.sleep(0.3)
        for chunk in [p_text[i:i+50] for i in range(0, len(p_text), 50)]:
            ed.send_keys(chunk)
            time.sleep(0.1)
        time.sleep(1)
        actual = drv.execute_script(
            "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent || '';")
        if actual.strip():
            log_fn(f"✅ Prompt diisi (Method C): {p_text[:60]}...")
            return True
    except Exception as ex:
        log_fn(f"⚠️ Prompt Method C: {ex}")

    return False


# ═══════════════════════════════════════════════════════════════
#  GENERATE ONE VIDEO (Main Function)
# ═══════════════════════════════════════════════════════════════
def generate_one_video_grok(image_path, prompt_text, log_fn, stop_event, output_dir,
                             user_data_dir=None, port=None, progress_callback=None):
    """
    Automate one video generation on grok.com/imagine:
    1. Upload image (if provided, skip if text-to-video)
    2. Type prompt text
    3. Click generate button
    4. Track progress percentage
    5. Download the result video
    Returns: path to downloaded video or None

    progress_callback: optional callable(percent_int) for real-time progress
    """
    import requests as req_lib
    os.makedirs(output_dir, exist_ok=True)

    from sgv_config import DEFAULT_PORT, USER_DATA_CHROME
    ud = user_data_dir or USER_DATA_CHROME
    pt = port or DEFAULT_PORT

    chrome_proc = open_chrome_grok(ud, pt)
    driver = None

    try:
        driver = connect_selenium_grok(pt)
        driver.execute_cdp_cmd("Page.setDownloadBehavior",
                               {"behavior": "allow", "downloadPath": output_dir})

        if not navigate_to_grok(driver, log_fn):
            return None

        if stop_event.is_set():
            return None

        time.sleep(3)

        # ─────────────────────────────────────────────────────────
        # UPLOAD + PROMPT: outer retry loop
        # ─────────────────────────────────────────────────────────
        image_uploaded = False
        prompt_filled = False
        abs_image = os.path.abspath(image_path) if (image_path and os.path.exists(str(image_path))) else None

        OUTER_MAX = 4
        for outer_attempt in range(1, OUTER_MAX + 1):
            if stop_event.is_set():
                return None

            if outer_attempt > 1:
                log_fn(f"🔄 RELOAD halaman (attempt {outer_attempt}/{OUTER_MAX})...")
                try:
                    driver.refresh()
                    time.sleep(6)
                    if not navigate_to_grok(driver, log_fn):
                        log_fn("❌ Gagal navigasi ulang")
                        continue
                    time.sleep(3)
                except Exception as e:
                    log_fn(f"⚠️ Reload gagal: {e}")
                    continue

            image_uploaded = False
            prompt_filled = False
            images_before = _count_uploaded_images(driver)

            # ── Upload image (skip if text-to-video / no image) ──
            if abs_image:
                log_fn(f"📷 Mengunggah gambar: {os.path.basename(abs_image)} (attempt {outer_attempt})")
                for inner in range(1, 3):
                    if _try_upload_image(driver, abs_image, images_before, log_fn):
                        image_uploaded = True
                        break
                    if inner < 2:
                        log_fn(f"⚠️ Upload attempt {inner} gagal, tunggu 3s...")
                        time.sleep(3)

                if not image_uploaded:
                    log_fn(f"❌ Upload gagal (attempt {outer_attempt}), akan reload...")
                    continue
            else:
                log_fn("📝 Mode text-to-video (tanpa gambar)")
                image_uploaded = True

            if stop_event.is_set():
                return None

            # ── Fill prompt ──
            log_fn("📝 Mengisi prompt...")
            prompt_filled = _try_fill_prompt(driver, prompt_text, log_fn)

            if not prompt_filled:
                log_fn(f"❌ Prompt gagal diisi (attempt {outer_attempt}), akan reload...")
                continue

            log_fn("✅ Upload & prompt berhasil!")
            break

        if stop_event.is_set():
            return None

        if not prompt_filled:
            log_fn("❌ Prompt gagal diisi setelah semua attempt, abort!")
            return None

        # ── Step 3: Click Settings → Buat Video ──
        log_fn("⚙️ Klik tombol Settings...")
        settings_opened = False

        # Method A: Selenium native click
        try:
            settings_btns = driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Settings"], button[aria-label="Pengaturan"]')
            if settings_btns:
                ActionChains(driver).move_to_element(settings_btns[0]).click().perform()
                time.sleep(1.5)
                if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                    settings_opened = True
                    log_fn("✅ Settings dropdown terbuka (Selenium click)")
        except Exception as e:
            log_fn(f"⚠️ Selenium click gagal: {e}")

        # Method B: JS pointer events
        if not settings_opened:
            try:
                driver.execute_script("""
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        const l = btn.getAttribute('aria-label') || '';
                        if (l === 'Settings' || l === 'Pengaturan') {
                            ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev =>
                                btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev, {bubbles:true,cancelable:true})));
                            return true;
                        }
                    } return false;
                """)
                time.sleep(1.5)
                if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                    settings_opened = True
                    log_fn("✅ Settings dropdown terbuka (pointer events)")
            except Exception as e:
                log_fn(f"⚠️ Pointer events gagal: {e}")

        # Method C: Enter key
        if not settings_opened:
            try:
                sb = driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Settings"], button[aria-label="Pengaturan"]')
                if sb:
                    sb[0].send_keys(Keys.ENTER)
                    time.sleep(1.5)
                    if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                        settings_opened = True
                        log_fn("✅ Settings dropdown terbuka (Enter key)")
            except Exception as e:
                log_fn(f"⚠️ Enter key gagal: {e}")

        if settings_opened:
            log_fn("🎬 Memilih 'Buat Video'...")
            try:
                menu_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
                clicked = False
                for item in menu_items:
                    txt = item.text or ""
                    if "Buat Video" in txt or "Make Video" in txt or "Make video" in txt:
                        ActionChains(driver).move_to_element(item).click().perform()
                        clicked = True
                        break
                if not clicked:
                    driver.execute_script("""
                        const items = document.querySelectorAll('div[role="menuitem"]');
                        for (const item of items) {
                            const t = item.textContent || '';
                            if (t.includes('Buat Video') || t.includes('Make Video') || t.includes('Make video')) {
                                item.click(); return true; }
                        }
                        const spans = document.querySelectorAll('span.font-semibold');
                        for (const s of spans) {
                            const t = s.textContent.trim();
                            if (t === 'Buat Video' || t === 'Make Video') {
                                (s.closest('div[role="menuitem"]') || s.parentElement).click();
                                return true; }
                        } return false;
                    """)
                time.sleep(1)
                log_fn("✅ Mode 'Buat Video' dipilih!")
            except Exception as e:
                log_fn(f"⚠️ Gagal pilih Buat Video: {e}")
        else:
            log_fn("⚠️ Settings dropdown tidak terbuka, lanjut tanpa pilih mode")

        if stop_event.is_set():
            return None

        # ── Step 4: Click Generate button ──
        log_fn("🚀 Klik Generate...")
        try:
            gen_btn = None
            for label in ['Buat video', 'Create video', 'Generate', 'Submit']:
                try:
                    gen_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, f'button[aria-label="{label}"]')))
                    if gen_btn:
                        break
                except:
                    continue

            if not gen_btn:
                try:
                    gen_btn = driver.find_element(
                        By.CSS_SELECTOR, 'button.group[type="button"]')
                except:
                    pass

            if gen_btn:
                gen_btn.click()
                log_fn("✅ Generate diklik!")
            else:
                driver.execute_script("""
                    const btn = document.querySelector('button[aria-label="Buat video"]')
                              || document.querySelector('button[aria-label="Create video"]')
                              || document.querySelector('button.group[type="button"]');
                    if (btn) btn.click();
                """)
                log_fn("✅ Generate diklik via JS!")
            time.sleep(3)
        except Exception as e:
            log_fn(f"❌ Gagal klik Generate: {e}")
            return None

        # ── Step 5: Track progress ──
        log_fn("⏳ Menunggu video selesai (max 10 menit)...")
        start_time = time.time()
        last_pct = ""
        last_pct_num = 0
        generation_started = False

        while time.time() - start_time < 600:
            if stop_event.is_set():
                return None

            try:
                pct_text = driver.execute_script("""
                    const spans = document.querySelectorAll('span.tabular-nums');
                    for (const s of spans) {
                        const t = s.textContent.trim();
                        if (t.includes('%')) return t;
                    }
                    const overlay = document.querySelector('div.flex.justify-center.items-center.gap-2');
                    if (overlay) {
                        const nums = overlay.querySelectorAll('span');
                        for (const n of nums) {
                            if (n.textContent.includes('%')) return n.textContent.trim();
                        }
                    }
                    return '';
                """)
                if pct_text and pct_text != last_pct:
                    last_pct = pct_text
                    generation_started = True
                    m = re.search(r'(\d+)', pct_text)
                    if m:
                        last_pct_num = int(m.group(1))
                        # Call progress callback for real-time updates
                        if progress_callback:
                            try:
                                progress_callback(last_pct_num)
                            except:
                                pass
            except:
                pass

            try:
                is_generating = driver.execute_script("""
                    const spans = document.querySelectorAll('span');
                    for (const s of spans) {
                        const t = s.textContent;
                        if (t.includes('Menghasilkan') || t.includes('Generating')) return true;
                    }
                    return false;
                """)
            except:
                is_generating = False

            if generation_started and not is_generating and last_pct_num > 0:
                log_fn("✅ Generasi selesai! Menunggu video muncul...")
                if progress_callback:
                    try:
                        progress_callback(100)
                    except:
                        pass
                time.sleep(3)
                break

            time.sleep(1)
        else:
            log_fn("❌ Timeout: video tidak selesai dalam 10 menit")
            return None

        if stop_event.is_set():
            return None

        # ── Step 6: Download the video ──
        log_fn("📥 Mengunduh video...")
        filename = f"grok_{int(time.time())}.mp4"
        save_path = os.path.join(output_dir, filename)
        downloaded = False
        downloads_folder = os.path.expanduser("~/Downloads")

        # Dismiss editor overlay
        try:
            driver.execute_script("""
                document.querySelectorAll('div[contenteditable="true"]').forEach(e => {
                    e.style.pointerEvents = 'none'; e.style.zIndex = '-1'; });
                document.querySelectorAll('.tiptap, .ProseMirror').forEach(w => {
                    w.style.pointerEvents = 'none'; w.style.zIndex = '-1'; });
            """)
            time.sleep(0.5)
        except:
            pass

        # ── Method 0: Extract video URL + download via requests ──
        video_url = None
        try:
            video_url = driver.execute_script("""
                const videos = document.querySelectorAll('video');
                for (const v of videos) {
                    if (v.src && (v.src.startsWith('http') || v.src.startsWith('blob'))) return v.src;
                    const src = v.querySelector('source');
                    if (src && src.src) return src.src;
                }
                const links = document.querySelectorAll('a[download], a[href*=".mp4"]');
                for (const a of links) { if (a.href) return a.href; }
                return null;
            """)
        except:
            pass

        if video_url and video_url.startswith('http') and not video_url.startswith('blob'):
            log_fn("🔗 URL video ditemukan, download via requests...")
            try:
                cookies = {c['name']: c['value'] for c in driver.get_cookies()}
                headers = {'User-Agent': driver.execute_script('return navigator.userAgent;'),
                           'Referer': GROK_URL}
                resp = req_lib.get(video_url, cookies=cookies, headers=headers,
                                   stream=True, timeout=120)
                if resp.status_code == 200:
                    with open(save_path, 'wb') as vf:
                        for chunk in resp.iter_content(65536):
                            if chunk:
                                vf.write(chunk)
                    if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                        downloaded = True
                        sz = os.path.getsize(save_path) / (1024 * 1024)
                        log_fn(f"✅ Video didownload via requests ({sz:.1f} MB)")
                else:
                    log_fn(f"⚠️ requests status {resp.status_code}")
            except Exception as e:
                log_fn(f"⚠️ Download via requests gagal: {e}")

        if not downloaded:
            # ── Button click download methods (A/B/C/D) ──
            dl_clicked = False

            # Method A: Selenium scroll + click
            try:
                dl_btns = driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Download"], button[aria-label="Unduh"]')
                if dl_btns:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", dl_btns[0])
                    time.sleep(0.5)
                    ActionChains(driver).move_to_element(dl_btns[0]).click().perform()
                    dl_clicked = True
                    log_fn("✅ Tombol Download diklik (Selenium)")
            except:
                pass

            # Method B: JS pointer events
            if not dl_clicked:
                try:
                    dl_clicked = driver.execute_script("""
                        const btns = document.querySelectorAll('button');
                        for (const btn of btns) {
                            const l = btn.getAttribute('aria-label') || '';
                            if (l === 'Download' || l === 'Unduh') {
                                btn.scrollIntoView({block:'center'});
                                ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev =>
                                    btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                                return true;
                            }
                        } return false;
                    """)
                    if dl_clicked:
                        log_fn("✅ Tombol Download diklik (JS pointer events)")
                except:
                    pass

            # Method C: Enter key
            if not dl_clicked:
                try:
                    dl_btns = driver.find_elements(By.CSS_SELECTOR,
                        'button[aria-label="Download"], button[aria-label="Unduh"]')
                    if dl_btns:
                        dl_btns[0].send_keys(Keys.ENTER)
                        dl_clicked = True
                        log_fn("✅ Tombol Download diklik (Enter key)")
                except:
                    pass

            # Method D: Direct JS click
            if not dl_clicked:
                try:
                    dl_clicked = driver.execute_script("""
                        const sel = ['button[aria-label="Download"]','button[aria-label="Unduh"]',
                                     'a[download]','a[href*=".mp4"]'];
                        for (const s of sel) {
                            const el = document.querySelector(s);
                            if (el) { el.click(); return true; }
                        } return false;
                    """)
                    if dl_clicked:
                        log_fn("✅ Tombol Download diklik (Method D)")
                except:
                    pass

            if not dl_clicked:
                log_fn("❌ Tidak bisa klik tombol Download")
            else:
                log_fn("⏳ Menunggu file terdownload (max 60 detik)...")
                for wait_sec in range(60):
                    time.sleep(1)
                    # Check output_dir
                    try:
                        mp4s = glob.glob(os.path.join(output_dir, "*.mp4"))
                        new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
                        if new_files:
                            newest = max(new_files, key=os.path.getmtime)
                            if not glob.glob(os.path.join(output_dir, "*.crdownload")):
                                if newest != save_path:
                                    shutil.move(newest, save_path)
                                downloaded = True
                                log_fn(f"✅ Video diunduh ke output: {filename}")
                                break
                    except:
                        pass
                    # Check Downloads folder
                    try:
                        mp4s = glob.glob(os.path.join(downloads_folder, "*.mp4"))
                        new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
                        if new_files:
                            newest = max(new_files, key=os.path.getmtime)
                            if not glob.glob(os.path.join(downloads_folder, "*.crdownload")):
                                shutil.move(newest, save_path)
                                downloaded = True
                                log_fn(f"✅ Video diunduh dari Downloads: {filename}")
                                break
                    except:
                        pass
                if not downloaded:
                    log_fn("⚠️ File tidak muncul setelah 60 detik")

        if downloaded and os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
            sz = os.path.getsize(save_path) / (1024 * 1024)
            log_fn(f"📦 Ukuran video: {sz:.1f} MB")
            return save_path

        log_fn("❌ Gagal mengunduh video")
        return None

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


# --- MULTITAB HELPERS INCORPORATED ---
def setup_tab_grok(driver, image_path, prompt_text, log_fn, tab_idx):
    """
    On the CURRENTLY active tab, do:
      1. Upload image with verification (reload tab if failed)
      2. Click Settings → Buat Video
      3. Fill prompt with verification
      4. Click Generate
    Returns True if generate was clicked successfully.
    """
    prefix = f"[Tab {tab_idx+1}]"

    def _count_imgs(drv):
        try:
            return drv.execute_script("""
                let c=0;
                c+=document.querySelectorAll('img[src*="assets.grok.com"]').length;
                c+=document.querySelectorAll('img[src^="blob:"]').length;
                c+=document.querySelectorAll('div.group.relative img').length;
                return c;
            """)
        except: return 0

    def _verify_uploaded(drv, before, timeout=10):
        for _ in range(timeout*2):
            try:
                if _count_imgs(drv) > before: return True
                has = drv.execute_script("""
                    const g=document.querySelector('div.group.relative');
                    if(g){const r=g.getBoundingClientRect();if(r.width>50&&r.height>50)return true;}
                    return false;
                """)
                if has: return True
            except: pass
            time.sleep(0.5)
        return False

    def _upload(drv, abs_img, before):
        # Method A: existing file inputs
        try:
            inputs = drv.find_elements(By.CSS_SELECTOR, "input[type='file']")
            for fi in inputs:
                try:
                    drv.execute_script(
                        "arguments[0].style.cssText='display:block!important;"
                        "visibility:visible!important;opacity:1!important;"
                        "position:absolute;top:0;left:0;width:1px;height:1px;';", fi)
                    fi.send_keys(abs_img)
                    time.sleep(3)
                    if _verify_uploaded(drv, before):
                        return True
                except: pass
        except: pass
        # Method B: inject
        try:
            iid = f"_tbf_{int(time.time())}"
            drv.execute_script(f"""
                let o=document.getElementById('{iid}');if(o)o.remove();
                const i=document.createElement('input');i.type='file';
                i.id='{iid}';i.accept='image/*';
                i.style.cssText='position:absolute;top:0;left:0;z-index:99999;display:block;width:1px;height:1px;';
                document.body.appendChild(i);
            """)
            time.sleep(0.5)
            drv.find_element(By.ID, iid).send_keys(abs_img)
            time.sleep(3)
            if _verify_uploaded(drv, before): return True
        except: pass
        return False

    def _fill_prompt(drv, p_text):
        # Method A
        try:
            ed = drv.execute_script("""
                const e=document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                if(e){e.scrollIntoView({block:'center'});return e;} return null;
            """)
            if ed:
                drv.execute_script("arguments[0].focus();", ed)
                time.sleep(0.3); ed.click(); time.sleep(0.3)
                ed.send_keys(Keys.CONTROL+"a"); time.sleep(0.2); ed.send_keys(Keys.DELETE); time.sleep(0.2)
                drv.execute_script("""
                    const e=arguments[0];
                    e.innerHTML='<p>'+arguments[1]+'</p>';
                    e.dispatchEvent(new Event('input',{bubbles:true}));
                    e.dispatchEvent(new Event('change',{bubbles:true}));
                    e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));
                """, ed, p_text)
                time.sleep(1)
                actual = drv.execute_script(
                    "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent||'';")
                if actual.strip(): return True
        except: pass
        # Method B: pure JS
        try:
            r = drv.execute_script("""
                const e=document.querySelector('div.tiptap.ProseMirror[contenteditable="true"]');
                if(!e)return 'nf';
                e.focus();e.innerHTML='<p>'+arguments[0]+'</p>';
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true}));
                return 'ok';
            """, p_text)
            time.sleep(1)
            if r == 'ok':
                actual = drv.execute_script(
                    "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent||'';")
                if actual.strip(): return True
        except: pass
        # Method C: typing
        try:
            ed = WebDriverWait(drv, 20).until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'div.tiptap.ProseMirror[contenteditable="true"]')))
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", ed)
            time.sleep(1); ed.click(); time.sleep(0.5)
            ed.send_keys(Keys.CONTROL+"a"); ed.send_keys(Keys.DELETE); time.sleep(0.3)
            for chunk in [p_text[i:i+50] for i in range(0, len(p_text), 50)]:
                ed.send_keys(chunk); time.sleep(0.1)
            time.sleep(1)
            actual = drv.execute_script(
                "return document.querySelector('div.tiptap.ProseMirror[contenteditable=\"true\"]')?.textContent||'';")
            if actual.strip(): return True
        except: pass
        return False

    # ── Upload image with reload-retry (up to 3 outer attempts) ──
    image_uploaded = True
    if image_path and os.path.exists(image_path):
        abs_image = os.path.abspath(image_path)
        image_uploaded = False
        for outer in range(1, 4):
            if outer > 1:
                log_fn(f"{prefix} 🔄 Reload untuk upload ulang (attempt {outer}/3)...")
                try:
                    driver.get(GROK_URL)
                    time.sleep(5)
                except Exception as e:
                    log_fn(f"{prefix} ⚠️ Reload gagal: {e}")
                    continue
            before = _count_imgs(driver)
            log_fn(f"{prefix} 📷 Upload: {os.path.basename(abs_image)} (attempt {outer})")
            if _upload(driver, abs_image, before):
                image_uploaded = True
                log_fn(f"{prefix} ✅ Upload berhasil!")
                break
            log_fn(f"{prefix} ⚠️ Upload attempt {outer} gagal")
        if not image_uploaded:
            log_fn(f"{prefix} ❌ Upload gambar gagal setelah 3 attempt")

    # ── Settings → Buat Video ──
    settings_opened = False
    for method_label, method_fn in [
        ("Selenium", lambda: (
            ActionChains(driver).move_to_element(
                driver.find_elements(By.CSS_SELECTOR,
                    'button[aria-label="Settings"], button[aria-label="Pengaturan"]')[0]
            ).click().perform()
        )),
        ("JS pointer", lambda: driver.execute_script("""
            for(const btn of document.querySelectorAll('button')){
                const l=btn.getAttribute('aria-label')||'';
                if(l==='Settings'||l==='Pengaturan'){
                    ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev=>
                        btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                    return true;}}
            return false;
        """)),
        ("Enter", lambda: driver.find_elements(By.CSS_SELECTOR,
            'button[aria-label="Settings"], button[aria-label="Pengaturan"]')[0].send_keys(Keys.ENTER)),
    ]:
        if settings_opened: break
        try:
            method_fn()
            time.sleep(1.5)
            if driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]'):
                settings_opened = True
        except: pass

    if settings_opened:
        try:
            menu_items = driver.find_elements(By.CSS_SELECTOR, 'div[role="menuitem"]')
            for item in menu_items:
                txt = item.text or ""
                if "Buat Video" in txt or "Make Video" in txt or "Make video" in txt:
                    ActionChains(driver).move_to_element(item).click().perform()
                    break
            time.sleep(1)
        except: pass

    # ── Fill prompt with verification and reload-retry ──
    prompt_filled = False
    for outer in range(1, 4):
        if outer > 1:
            log_fn(f"{prefix} 🔄 Reload untuk isi prompt ulang (attempt {outer}/3)...")
            try:
                driver.get(GROK_URL)
                time.sleep(5)
            except:
                continue
        if _fill_prompt(driver, prompt_text):
            prompt_filled = True
            log_fn(f"{prefix} ✅ Prompt diisi!")
            break
        log_fn(f"{prefix} ⚠️ Prompt attempt {outer} gagal")

    if not prompt_filled:
        log_fn(f"{prefix} ❌ Gagal isi prompt setelah 3 attempt")
        return False

    # ── Click Generate ──
    try:
        gen_btn = None
        for label in ['Buat video', 'Create video', 'Generate', 'Submit']:
            try:
                gen_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, f'button[aria-label="{label}"]')))
                if gen_btn: break
            except: continue
        if not gen_btn:
            try: gen_btn = driver.find_element(By.CSS_SELECTOR, 'button.group[type="button"]')
            except: pass
        if gen_btn:
            gen_btn.click()
        else:
            driver.execute_script("""
                const btn = document.querySelector('button[aria-label="Buat video"]')
                          || document.querySelector('button[aria-label="Create video"]')
                          || document.querySelector('button.group[type="button"]');
                if (btn) btn.click();
            """)
        log_fn(f"{prefix} ✅ Generate diklik!")
        time.sleep(2)
        return True
    except Exception as e:
        log_fn(f"{prefix} ❌ Gagal klik Generate: {e}")
        return False



def check_tab_progress(driver):
    """
    Check progress of video generation on the currently active tab.
    Returns (status, pct_num):
      status = "generating" | "done" | "idle"
      pct_num = integer percentage (0-100)
    """
    pct_num = 0
    is_generating = False

    # Read percentage
    try:
        pct_text = driver.execute_script("""
            const spans = document.querySelectorAll('span.tabular-nums');
            for (const s of spans) {
                const t = s.textContent.trim();
                if (t.includes('%')) return t;
            }
            const overlay = document.querySelector('div.flex.justify-center.items-center.gap-2');
            if (overlay) {
                const nums = overlay.querySelectorAll('span');
                for (const n of nums) {
                    if (n.textContent.includes('%')) return n.textContent.trim();
                }
            }
            return '';
        """)
        if pct_text:
            m = re.search(r'(\d+)', pct_text)
            if m:
                pct_num = int(m.group(1))
    except:
        pass

    # Check if generating overlay is shown
    try:
        is_generating = driver.execute_script("""
            const spans = document.querySelectorAll('span');
            for (const s of spans) {
                const t = s.textContent;
                if (t.includes('Menghasilkan') || t.includes('Generating')) return true;
            }
            return false;
        """)
    except:
        pass

    # Check if Download button is visible (= done)
    has_download = False
    try:
        dl_btns = driver.find_elements(By.CSS_SELECTOR,
            'button[aria-label="Download"], button[aria-label="Unduh"]')
        if dl_btns:
            has_download = True
    except:
        pass

    if has_download and not is_generating:
        return "done", 100
    elif is_generating or pct_num > 0:
        return "generating", pct_num
    else:
        return "idle", 0



def download_tab_video(driver, output_dir, log_fn, tab_idx, start_time):
    """
    Download video from the currently active tab.
    Returns path to downloaded video or None.
    """
    import requests as req_lib
    prefix = f"[Tab {tab_idx+1}]"
    filename = f"grok_{int(time.time())}_{tab_idx}.mp4"
    save_path = os.path.join(output_dir, filename)
    downloads_folder = os.path.expanduser("~/Downloads")

    # ── Dismiss editor overlay so it doesn't block the Download button ──
    try:
        driver.execute_script("""
            document.querySelectorAll('div[contenteditable="true"]').forEach(e=>{
                e.style.pointerEvents='none'; e.style.zIndex='-1'; });
            document.querySelectorAll('.tiptap,.ProseMirror').forEach(w=>{
                w.style.pointerEvents='none'; w.style.zIndex='-1'; });
        """)
        time.sleep(0.5)
    except: pass

    # ── Method 0: Extract video URL + download via requests ──
    video_url = None
    try:
        video_url = driver.execute_script("""
            for(const v of document.querySelectorAll('video')){
                if(v.src&&(v.src.startsWith('http')||v.src.startsWith('blob')))return v.src;
                const s=v.querySelector('source');if(s&&s.src)return s.src;
            }
            for(const a of document.querySelectorAll('a[download],a[href*=".mp4"]')){
                if(a.href)return a.href;
            }
            return null;
        """)
    except: pass

    if video_url and video_url.startswith('http') and not video_url.startswith('blob'):
        log_fn(f"{prefix} 🔗 URL video, download via requests...")
        try:
            cookies = {c['name']:c['value'] for c in driver.get_cookies()}
            headers = {'User-Agent': driver.execute_script('return navigator.userAgent;'), 'Referer': GROK_URL}
            resp = req_lib.get(video_url, cookies=cookies, headers=headers, stream=True, timeout=120)
            if resp.status_code == 200:
                with open(save_path, 'wb') as vf:
                    for chunk in resp.iter_content(65536):
                        if chunk: vf.write(chunk)
                if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                    sz = os.path.getsize(save_path)/(1024*1024)
                    log_fn(f"{prefix} ✅ Video via requests ({sz:.1f} MB)")
                    return save_path
        except Exception as e:
            log_fn(f"{prefix} ⚠️ requests gagal: {e}")

    # ── Button click methods ──
    dl_clicked = False
    # Method A: Selenium scroll + click
    try:
        dl_btns = driver.find_elements(By.CSS_SELECTOR,
            'button[aria-label="Download"], button[aria-label="Unduh"]')
        if dl_btns:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", dl_btns[0])
            time.sleep(0.5)
            ActionChains(driver).move_to_element(dl_btns[0]).click().perform()
            dl_clicked = True
            log_fn(f"{prefix} ✅ Download diklik (Selenium)")
    except: pass

    # Method B: JS pointer events
    if not dl_clicked:
        try:
            dl_clicked = driver.execute_script("""
                for(const btn of document.querySelectorAll('button')){
                    const l=btn.getAttribute('aria-label')||'';
                    if(l==='Download'||l==='Unduh'){
                        btn.scrollIntoView({block:'center'});
                        ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(ev=>
                            btn.dispatchEvent(new (ev.startsWith('pointer')?PointerEvent:MouseEvent)(ev,{bubbles:true})));
                        return true;}
                } return false;
            """)
            if dl_clicked: log_fn(f"{prefix} ✅ Download diklik (JS pointer)")
        except: pass

    # Method C: Enter key
    if not dl_clicked:
        try:
            dl_btns = driver.find_elements(By.CSS_SELECTOR,
                'button[aria-label="Download"], button[aria-label="Unduh"]')
            if dl_btns:
                dl_btns[0].send_keys(Keys.ENTER)
                dl_clicked = True
                log_fn(f"{prefix} ✅ Download diklik (Enter)")
        except: pass

    # Method D: direct JS click any matching element
    if not dl_clicked:
        try:
            dl_clicked = driver.execute_script("""
                const sel=['button[aria-label="Download"]','button[aria-label="Unduh"]',
                           'a[download]','a[href*=".mp4"]'];
                for(const s of sel){const el=document.querySelector(s);if(el){el.click();return true;}}
                return false;
            """)
            if dl_clicked: log_fn(f"{prefix} ✅ Download diklik (Method D)")
        except: pass

    if not dl_clicked:
        log_fn(f"{prefix} ❌ Tidak bisa klik tombol Download")
        return None

    log_fn(f"{prefix} ⏳ Menunggu file terdownload (max 60 detik)...")
    for _ in range(60):
        time.sleep(1)
        # Check output_dir
        try:
            mp4s = glob.glob(os.path.join(output_dir, "*.mp4"))
            new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
            if new_files:
                newest = max(new_files, key=os.path.getmtime)
                if not glob.glob(os.path.join(output_dir, "*.crdownload")):
                    if newest != save_path: shutil.move(newest, save_path)
                    log_fn(f"{prefix} ✅ Video diunduh: {filename}")
                    return save_path
        except: pass
        # Check Downloads folder
        try:
            mp4s = glob.glob(os.path.join(downloads_folder, "*.mp4"))
            new_files = [f for f in mp4s if os.path.getmtime(f) > start_time]
            if new_files:
                newest = max(new_files, key=os.path.getmtime)
                if not glob.glob(os.path.join(downloads_folder, "*.crdownload")):
                    shutil.move(newest, save_path)
                    log_fn(f"{prefix} ✅ Video diunduh dari Downloads: {filename}")
                    return save_path
        except: pass

    log_fn(f"{prefix} ❌ Timeout download 60 detik")
    return None


# ═══════════════════════════════════════════════════════════════
#  GENERATION LOOP (runs in thread)
# ═══════════════════════════════════════════════════════════════



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
