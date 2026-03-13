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
