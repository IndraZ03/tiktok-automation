"""
🌐 YT Bot Web Dashboard — Flask API Server
Serves index.html and exposes REST APIs for managing yt_bot_v2.py
"""
import os, sys, json, re, time, threading, shutil, subprocess, traceback
from datetime import datetime, timedelta
from collections import deque
from flask import Flask, jsonify, request, send_from_directory, Response

# ── Reuse configs & helpers from yt_bot_v2 ──
APP_DIR = r"C:\indra\ternak_dracin"
LOGO_PATH = os.path.join(APP_DIR, "logo.png")
TEMP_DIR = os.path.join(APP_DIR, "yt_temp")
FINAL_DIR = os.path.join(APP_DIR, "video_yt")
STOK_PER_UD_FILE = os.path.join(APP_DIR, "yt_stok_per_ud.json")
SCHEDULE_PER_UD_FILE = os.path.join(APP_DIR, "yt_schedule_per_ud.json")
ACTIVE_UD_FILE = os.path.join(APP_DIR, "yt_auto_userdata.json")
USER_SETTINGS_FILE = os.path.join(APP_DIR, "yt_user_settings.json")
SEGMENT_DURATION = 180
UD_PORT_MAP = {i: str(9221 + i) for i in range(1, 21)}

# ── Import TikTok upload functions ──
sys.path.insert(0, APP_DIR)
try:
    from tiktok_gui import open_chrome_debug, connect_selenium, do_upload_file, do_post_video
except:
    pass

TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"

# FFmpeg
def _find_bin(name):
    found = shutil.which(name)
    if found: return found
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
    for c in [os.path.expanduser(rf"~\AppData\Local\Microsoft\WinGet\Links\{name}.exe"),
              rf"C:\ffmpeg\bin\{name}.exe", os.path.join(APP_DIR, f"{name}.exe"),
              os.path.join(scripts_dir, f"{name}.exe")]:
        if os.path.isfile(c): return c
    return name

FFPROBE_PATH = _find_bin("ffprobe")
FFMPEG_PATH = _find_bin("ffmpeg")
YTDLP_PATH = _find_bin("yt-dlp")

TARGET_W, TARGET_H = 1080, 1920
WATERMARK_WIDTH_PCT = 25
WATERMARK_MARGIN_PCT = 2
TEXT_FONT_FILE = "C\\:/Windows/Fonts/arial.ttf"
TEXT_SIZE_PCT = 2.5
TEXT_COLOR = "white"
TEXT_BORDER_COLOR = "black"
TEXT_BORDER_W = 4

# ═══════════════════════════════════════════════════════════
#  JSON helpers
# ═══════════════════════════════════════════════════════════
def _load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return default if default is not None else {}

def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_stok_per_ud(ud_num):
    return _load_json(STOK_PER_UD_FILE, {}).get(str(ud_num), [])

def save_stok_per_ud(ud_num, links):
    all_stok = _load_json(STOK_PER_UD_FILE, {})
    all_stok[str(ud_num)] = links
    _save_json(STOK_PER_UD_FILE, all_stok)

def load_schedule_per_ud(ud_num):
    all_sched = _load_json(SCHEDULE_PER_UD_FILE, {})
    s = all_sched.get(str(ud_num))
    if s and all(k in s for k in ("tanggal","jam","menit")):
        return s
    now = datetime.now()
    return {"tanggal": now.strftime("%Y-%m-%d"), "jam": f"{now.hour:02d}", "menit": f"{now.minute:02d}"}

def save_schedule_per_ud(ud_num, tanggal, jam, menit):
    all_sched = _load_json(SCHEDULE_PER_UD_FILE, {})
    all_sched[str(ud_num)] = {"tanggal": tanggal, "jam": jam, "menit": menit,
                               "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _save_json(SCHEDULE_PER_UD_FILE, all_sched)

def load_active_ud():
    data = _load_json(ACTIVE_UD_FILE)
    if isinstance(data, list): return data
    if isinstance(data, dict) and "active" in data: return data["active"]
    return [2, 5, 6]

def save_active_ud(ud_list):
    _save_json(ACTIVE_UD_FILE, {"active": ud_list})

def load_user_settings():
    return _load_json(USER_SETTINGS_FILE, {})

def save_user_settings(settings):
    _save_json(USER_SETTINGS_FILE, settings)

# ═══════════════════════════════════════════════════════════
#  Video helpers
# ═══════════════════════════════════════════════════════════
def get_video_duration(fp):
    try:
        r = subprocess.run([FFPROBE_PATH,"-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",fp], capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except: return 0

def get_video_info(fp):
    try:
        r = subprocess.run([FFPROBE_PATH,"-v","error","-select_streams","v:0",
            "-show_entries","stream=width,height","-of","csv=p=0:s=x",fp],
            capture_output=True, text=True, timeout=30)
        w,h = r.stdout.strip().split("x"); return int(w),int(h)
    except: return 1080,1920

def sanitize_filename(title):
    title = re.sub(r'[<>:"/\\|?*!,;\[\]{}()\']', '', title)
    title = re.sub(r'\s+', ' ', title).strip('. ')
    return title[:60].rstrip('. ') if len(title) > 60 else (title or "video")

def truncate_title(title, max_len=20):
    return title[:max_len-3]+"..." if len(title) > max_len else title

def _build_ffmpeg_filter(input_file, logo_path, overlay_title, overlay_part, use_watermark=True):
    vid_w, vid_h = get_video_info(input_file)
    scale_part = f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,setsar=1"
    pad_part = f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:black"
    base_vf = f"{scale_part},{pad_part}"
    dt_title = (f"drawtext=text='{overlay_title}':fontfile='{TEXT_FONT_FILE}':"
                f"fontsize=h*{TEXT_SIZE_PCT}/100:fontcolor={TEXT_COLOR}:borderw={TEXT_BORDER_W}:bordercolor={TEXT_BORDER_COLOR}:"
                f"x=(w-text_w)/2:y=h-text_h*2.5-h*{WATERMARK_MARGIN_PCT*2}/100")
    dt_part = (f"drawtext=text='{overlay_part}':fontfile='{TEXT_FONT_FILE}':"
               f"fontsize=h*{TEXT_SIZE_PCT}/100:fontcolor={TEXT_COLOR}:borderw={TEXT_BORDER_W}:bordercolor={TEXT_BORDER_COLOR}:"
               f"x=(w-text_w)/2:y=h-text_h-h*{WATERMARK_MARGIN_PCT*2}/100")
    if use_watermark and logo_path and os.path.exists(logo_path):
        wm_w = max(32, int(TARGET_W * WATERMARK_WIDTH_PCT / 100))
        mx = max(4, int(TARGET_W * WATERMARK_MARGIN_PCT / 100))
        fc = (f"[0:v]{base_vf}[base];[1:v]scale={wm_w}:-1[wm];[base][wm]overlay={mx}:{mx}[vid];"
              f"[vid]{dt_title}[vid2];[vid2]{dt_part}[out]")
        return fc, True, True
    else:
        vf = f"{base_vf},{dt_title},{dt_part}"
        return vf, False, False

def split_and_process_sync(input_file, output_dir, title, logo_path, log_fn=None, use_watermark=True):
    os.makedirs(output_dir, exist_ok=True)
    duration = get_video_duration(input_file)
    if duration <= 0: raise Exception("Tidak bisa baca durasi video")
    total_parts = max(1, int(duration // SEGMENT_DURATION))
    safe_title = sanitize_filename(title)
    display_title = truncate_title(title)
    output_files = []
    for part in range(1, total_parts + 1):
        start_sec = (part-1)*SEGMENT_DURATION
        output_file = os.path.join(output_dir, f"{safe_title}_Part{part}.mp4")
        if log_fn: log_fn(f"Split Part {part}/{total_parts}...", "info")
        overlay_title = display_title.replace("'","'\\\\\\'").replace(":","\\\\\\:").replace("%","%%")
        overlay_part = f"Part {part}/{total_parts}"
        filter_str, is_complex, needs_logo = _build_ffmpeg_filter(input_file, logo_path, overlay_title, overlay_part, use_watermark)
        if is_complex:
            cmd = [FFMPEG_PATH, "-y", "-ss", str(start_sec), "-t", str(SEGMENT_DURATION),
                   "-i", input_file, "-i", logo_path, "-filter_complex", filter_str,
                   "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                   "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", output_file]
        else:
            cmd = [FFMPEG_PATH, "-y", "-ss", str(start_sec), "-t", str(SEGMENT_DURATION),
                   "-i", input_file, "-vf", filter_str,
                   "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                   "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", output_file]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 10240:
            output_files.append(output_file)
            if log_fn: log_fn(f"  ✓ Part {part} selesai", "success")
        else:
            stderr_msg = r.stderr.decode('utf-8', errors='replace')[-200:] if r.stderr else 'unknown'
            if log_fn: log_fn(f"  ❌ Part {part} gagal: {stderr_msg}", "error")
    return output_files

def download_video_sync(url, temp_dir, log_fn=None):
    os.makedirs(temp_dir, exist_ok=True)
    output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")
    cmd = [YTDLP_PATH,"--no-playlist","-f","bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
           "--merge-output-format","mp4","-o",output_template,"--newline","--no-color",
           "--print","after_move:filepath",url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    filepath = None
    for raw_line in proc.stdout:
        line = raw_line.decode("utf-8", errors="replace").strip()
        pct_match = re.search(r'\[download\]\s+([\d.]+)%', line)
        if pct_match and log_fn:
            log_fn(f"Download: {float(pct_match.group(1)):.0f}%", "info")
        if line and not line.startswith("[") and not line.startswith("Deleting") and os.path.isfile(line):
            filepath = line
    proc.wait()
    if proc.returncode != 0: raise Exception(f"yt-dlp gagal (exit code {proc.returncode})")
    if not filepath:
        mp4s = [os.path.join(temp_dir,f) for f in os.listdir(temp_dir) if f.endswith(".mp4")]
        if mp4s: filepath = max(mp4s, key=os.path.getmtime)
        else: raise Exception("Tidak ada file video yang dihasilkan")
    title = os.path.splitext(os.path.basename(filepath))[0]
    return filepath, title

# ═══════════════════════════════════════════════════════════
#  LOG SYSTEM — Polling based
# ═══════════════════════════════════════════════════════════
MAX_LOG_LINES = 200
_log_buffer = deque(maxlen=MAX_LOG_LINES)
_log_lock = threading.Lock()
_log_counter = 0

def _web_log(msg, tag=None):
    global _log_counter
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"success":"✅","error":"❌","warn":"⚠️","info":"ℹ️"}.get(tag, "▪️")
    with _log_lock:
        _log_counter += 1
        entry = {"id": _log_counter, "ts": ts, "icon": icon, "msg": msg, "tag": tag or ""}
        _log_buffer.append(entry)

# ═══════════════════════════════════════════════════════════
#  FULL AUTO ENGINE (same logic as yt_bot_v2.py _daemon)
# ═══════════════════════════════════════════════════════════
_auto_state = {"running": False, "stop_event": None, "thread": None}
_ud_current_folder = {}
UPLOAD_BATCH_SIZE = 20

def _natural_sort_key(filepath):
    basename = os.path.basename(filepath).lower()
    return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', basename)]

def _get_pending_videos(folder_path):
    if not folder_path or not os.path.isdir(folder_path): return []
    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path)
             if f.lower().endswith(".mp4") and os.path.isfile(os.path.join(folder_path, f))]
    files.sort(key=_natural_sort_key)
    return files

def _download_and_split_to_final(ud_num, log_fn, stop_evt):
    links = load_stok_per_ud(ud_num)
    if not links:
        log_fn(f"❌ [UD {ud_num}] Stok kosong.", "error")
        return None
    url = links[0]
    # cek folder sudah ada
    try:
        result = subprocess.run([YTDLP_PATH,"--no-playlist","--print","title",url],
            capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            pre_title = sanitize_filename(result.stdout.strip())
            existing_folder = os.path.join(FINAL_DIR, pre_title)
            if os.path.isdir(existing_folder):
                existing_mp4s = [f for f in os.listdir(existing_folder) if f.lower().endswith(".mp4")]
                if existing_mp4s:
                    log_fn(f"⏩ [UD {ud_num}] Folder sudah ada: {pre_title} ({len(existing_mp4s)} video), skip download.", "info")
                    return existing_folder
    except Exception as e:
        log_fn(f"⚠️ [UD {ud_num}] Gagal cek judul: {e}", "warn")
    
    log_fn(f"📥 [UD {ud_num}] Downloading: {url[:60]}...", "info")
    job_temp = os.path.join(TEMP_DIR, f"auto_ud{ud_num}_{int(time.time())}")
    try:
        filepath, title = download_video_sync(url, job_temp, log_fn)
        log_fn(f"✓ [UD {ud_num}] Download selesai: {title[:40]}", "success")
        if stop_evt.is_set(): return None
        safe_title = sanitize_filename(title)
        video_folder = os.path.join(FINAL_DIR, safe_title)
        os.makedirs(video_folder, exist_ok=True)
        logo = LOGO_PATH if os.path.exists(LOGO_PATH) else None
        # Load watermark setting
        settings = load_user_settings()
        wm = True
        for uid_str, cfg in settings.items():
            wm = cfg.get("watermark", True)
            break
        output_files = split_and_process_sync(filepath, video_folder, title, logo, log_fn, use_watermark=wm)
        if not output_files:
            log_fn(f"❌ [UD {ud_num}] Split gagal!", "error")
            try: shutil.rmtree(video_folder)
            except: pass
            return None
        log_fn(f"✓ [UD {ud_num}] Split selesai: {len(output_files)} parts", "success")
        return video_folder
    except Exception as e:
        log_fn(f"❌ [UD {ud_num}] Error: {e}", "error")
        return None
    finally:
        try:
            if os.path.exists(job_temp): shutil.rmtree(job_temp)
        except: pass

def _is_403_page(drv):
    try:
        page_src = (drv.page_source or "").lower()
        if "403" in drv.title or "forbidden" in drv.title.lower(): return True
        if "403 forbidden" in page_src or "http error 403" in page_src: return True
    except: pass
    return False

def _force_fresh_tab(drv, log_fn, prefix):
    log_fn(f"{prefix} 🔄 Membuka tab baru...", "info")
    try:
        try:
            drv.switch_to.new_window('tab')
        except:
            drv.execute_script("window.open('about:blank', '_blank');")
            drv.switch_to.window(drv.window_handles[-1])
        time.sleep(1)
        new_window = drv.current_window_handle
        windows = drv.window_handles
        for w in windows:
            if w != new_window:
                try: drv.switch_to.window(w); drv.close()
                except: pass
        drv.switch_to.window(new_window)
        time.sleep(1)
        drv.get(TIKTOK_UPLOAD_URL)
        time.sleep(5)
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            WebDriverWait(drv, 15).until(
                EC.presence_of_element_located((By.XPATH, "//button[@data-e2e='select_video_button' or @aria-label='Select video']")))
            log_fn(f"{prefix} ✅ Tab baru siap", "success")
        except:
            drv.refresh(); time.sleep(5)
            log_fn(f"{prefix} ⚠️ Refresh setelah timeout", "warn")
    except Exception as e:
        log_fn(f"{prefix} ⚠️ Error tab baru: {str(e)[:60]}", "warn")
        err_str = str(e).lower()
        if "invalid session id" in err_str or "disconnected" in err_str:
            raise

def _upload_batch_web(log_fn, stop_evt, ud_num, video_files):
    if not video_files: return 0, 0
    userdata = os.path.join(APP_DIR, "user_data", str(ud_num))
    port = UD_PORT_MAP.get(ud_num, str(9222 + ud_num - 1))
    ss = load_schedule_per_ud(ud_num)
    hour, minute = int(ss["jam"]), int(ss["menit"])
    date_str = ss["tanggal"]
    # load settings
    settings = load_user_settings()
    interval = 60; deskripsi = ""; hashtags = []
    for uid_str, cfg in settings.items():
        interval = int(cfg.get("interval", "60"))
        deskripsi = cfg.get("deskripsi", "")
        hashtags = cfg.get("hashtags", [])
        break
    start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
    MIN_FUTURE_MINUTES = 60
    now = datetime.now()
    min_start = now + timedelta(minutes=MIN_FUTURE_MINUTES)
    if start_dt < min_start:
        start_dt = min_start.replace(second=0, microsecond=0)
        rounded_min = ((start_dt.minute + 4) // 5) * 5
        if rounded_min >= 60:
            start_dt = start_dt.replace(minute=0) + timedelta(hours=1)
        else:
            start_dt = start_dt.replace(minute=rounded_min)
        log_fn(f"⚠️ [UD {ud_num}] Schedule digeser ke {start_dt.strftime('%Y-%m-%d %H:%M')}", "warn")
        save_schedule_per_ud(ud_num, start_dt.strftime("%Y-%m-%d"),
                             f"{start_dt.hour:02d}", f"{start_dt.minute:02d}")
    batch = video_files[:UPLOAD_BATCH_SIZE]
    total = len(batch)
    log_fn(f"📅 [UD {ud_num}] Schedule: {start_dt.strftime('%Y-%m-%d %H:%M')}", "info")
    log_fn(f"🎬 [UD {ud_num}] Upload {total} video...", "info")
    log_fn(f"🌐 [UD {ud_num}] Membuka Chrome (port {port})...", "info")
    chrome_proc = open_chrome_debug(userdata, port)
    driver = connect_selenium(port)
    log_fn(f"✓ [UD {ud_num}] Chrome terhubung!", "success")
    uploaded = 0
    try:
        for idx, out_path in enumerate(batch):
            if stop_evt.is_set(): break
            if not os.path.exists(out_path):
                log_fn(f"  ⚠️ File skip: {os.path.basename(out_path)}", "warn"); continue
            sched_dt = start_dt + timedelta(minutes=interval * idx)
            prefix = f"[UD {ud_num}] [{idx+1}/{total}]"
            log_fn(f"{prefix} Upload: {os.path.basename(out_path)}", "info")
            log_fn(f"{prefix} Schedule: {sched_dt.strftime('%Y-%m-%d %H:%M')}", "info")
            post_ok = False
            for attempt_403 in range(3):
                try:
                    _force_fresh_tab(driver, log_fn, prefix); time.sleep(2)
                    if _is_403_page(driver):
                        log_fn(f"{prefix} ⚠️ 403! Retry...", "warn"); time.sleep(5); continue
                    do_upload_file(driver, os.path.normpath(out_path), log_fn); time.sleep(5)
                    if _is_403_page(driver):
                        log_fn(f"{prefix} ⚠️ 403 setelah upload!", "warn"); time.sleep(5); continue
                    do_post_video(driver, deskripsi, "", "", log_fn, sched_dt, stop_evt,
                                  add_sound=False, add_product=False, skip_switches=True,
                                  hashtags=hashtags if hashtags else None)
                    post_ok = True; break
                except Exception as e:
                    err_str = str(e).lower()
                    if ("403" in err_str or "forbidden" in err_str) and attempt_403 < 2:
                        log_fn(f"{prefix} ⚠️ 403, retry...", "warn"); time.sleep(5); continue
                    if "invalid session id" in err_str or "disconnected" in err_str:
                        log_fn(f"{prefix} ❌ Browser crash, stop batch.", "error")
                        return uploaded, total
                    log_fn(f"{prefix} ❌ Error: {e}", "error"); break
            if post_ok:
                try: os.remove(out_path)
                except: pass
                uploaded += 1
                log_fn(f"{prefix} ✅ Upload sukses!", "success")
            if idx < total - 1 and not stop_evt.is_set():
                log_fn(f"{prefix} ⏳ Menunggu 10 detik...", "info"); time.sleep(10)
    finally:
        try: driver.quit()
        except: pass
        try: chrome_proc.terminate()
        except: pass
    if uploaded > 0:
        last_sched = start_dt + timedelta(minutes=interval * (uploaded - 1))
        next_dt = last_sched + timedelta(minutes=interval)
        save_schedule_per_ud(ud_num, next_dt.strftime("%Y-%m-%d"), f"{next_dt.hour:02d}", f"{next_dt.minute:02d}")
        log_fn(f"💾 [UD {ud_num}] Next schedule: {next_dt.strftime('%Y-%m-%d %H:%M')}", "success")
    log_fn(f"🎉 [UD {ud_num}] Batch selesai! {uploaded}/{total}", "success")
    return uploaded, total

def _full_auto_daemon_logic(stop_evt):
    log = _web_log
    active = load_active_ud()
    log(f"🤖 Full Auto dimulai! Active UD: {', '.join(str(x) for x in active)}", "success")
    while not stop_evt.is_set():
        active = load_active_ud()
        # Housekeeping
        for ud_num in active:
            current_folder = _ud_current_folder.get(ud_num)
            if current_folder and not _get_pending_videos(current_folder):
                log(f"🗑 UD {ud_num}: Semua video terupload, hapus folder.", "info")
                try:
                    if os.path.isdir(current_folder): shutil.rmtree(current_folder)
                except: pass
                links = load_stok_per_ud(ud_num)
                if links:
                    links_copy = list(links)
                    new_links = [l for l in links_copy if l != links_copy[0]]
                    save_stok_per_ud(ud_num, new_links)
                    log(f"✅ [UD {ud_num}] Link stok dihapus.", "info")
                _ud_current_folder.pop(ud_num, None)
        # Kumpulkan candidates
        candidates = []
        for ud_num in active:
            has_pending = bool(_get_pending_videos(_ud_current_folder.get(ud_num)))
            has_stok = bool(load_stok_per_ud(ud_num))
            if not has_pending and not has_stok: continue
            state = load_schedule_per_ud(ud_num)
            try:
                trigger_dt = datetime.strptime(f"{state['tanggal']} {state['jam']}:{state['menit']}", "%Y-%m-%d %H:%M")
            except:
                log(f"❌ Format schedule UD {ud_num} error!", "error"); continue
            candidates.append((trigger_dt, ud_num, has_pending))
        if not candidates:
            if not stop_evt.is_set():
                log("📦 Semua stok kosong. Menunggu 60 detik...", "info")
                for _ in range(12):
                    if stop_evt.is_set(): break
                    time.sleep(5)
            continue
        candidates.sort(key=lambda x: x[0])
        trigger_dt, ud_num, has_pending = candidates[0]
        
        sched_info = "\n".join(
            f"  {'➡️' if c[1]==ud_num else '  '} UD {c[1]}: "
            f"{c[0].strftime('%Y-%m-%d %H:%M')}"
            f"{' (sisa video)' if c[2] else ''}"
            for c in candidates
        )
        log(f"📅 Jadwal UD:\n{sched_info}\n\n🎯 Terdekat: UD {ud_num} — {trigger_dt.strftime('%Y-%m-%d %H:%M')}", "info")

        # Tunggu jadwal
        now = datetime.now()
        wait_sec = (trigger_dt - now).total_seconds()
        if wait_sec > 0:
            log(f"⏳ UD {ud_num}: Menunggu jadwal ({int(wait_sec//60)} menit lagi)", "info")
            elapsed = 0
            while elapsed < wait_sec and not stop_evt.is_set():
                time.sleep(min(30, wait_sec - elapsed)); elapsed += 30
            if stop_evt.is_set(): break
        pending = _get_pending_videos(_ud_current_folder.get(ud_num))
        if not pending:
            links = load_stok_per_ud(ud_num)
            if not links:
                log(f"⚠️ UD {ud_num}: Stok habis.", "warn"); continue
            log(f"📥 UD {ud_num}: Downloading {links[0][:60]}...", "info")
            new_folder = _download_and_split_to_final(ud_num, log, stop_evt)
            if not new_folder or stop_evt.is_set():
                log(f"❌ UD {ud_num}: Download gagal.", "error"); time.sleep(10); continue
            _ud_current_folder[ud_num] = new_folder
            pending = _get_pending_videos(new_folder)
            log(f"✅ UD {ud_num}: Download selesai! {len(pending)} video siap.", "success")
        if not pending or stop_evt.is_set(): continue
        folder_name = os.path.basename(_ud_current_folder.get(ud_num, ""))
        log(f"🚀 UD {ud_num}: Upload batch {UPLOAD_BATCH_SIZE} video dari {folder_name}", "info")
        try:
            uploaded, _ = _upload_batch_web(log, stop_evt, ud_num, pending)
        except Exception as e:
            log(f"❌ [UD {ud_num}] Error upload: {e}", "error")
            uploaded = 0
        sisa = len(_get_pending_videos(_ud_current_folder.get(ud_num, "")))
        log(f"✅ UD {ud_num}: Batch selesai! {uploaded} terupload, sisa {sisa}", "success")
        if not stop_evt.is_set():
            time.sleep(10)
    log("⏹ Full Auto dihentikan.", "warn")
    _auto_state["running"] = False

def _full_auto_daemon(stop_evt):
    try:
        _full_auto_daemon_logic(stop_evt)
    except Exception as e:
        import traceback
        _web_log(f"🔥 FATAL ERROR di daemon: {e}", "error")
        _web_log(f"Details: {traceback.format_exc()}", "error")
        print(f"FATAL ERROR di daemon:\n{traceback.format_exc()}")
    finally:
        _auto_state["running"] = False

# ═══════════════════════════════════════════════════════════
#  FLASK APP
# ═══════════════════════════════════════════════════════════
app = Flask(__name__, static_folder=os.path.dirname(os.path.abspath(__file__)))

@app.route("/")
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")

@app.route("/api/status")
def api_status():
    active = load_active_ud()
    ud_data = {}
    for ud in range(1, 21):
        links = load_stok_per_ud(ud)
        sched = load_schedule_per_ud(ud)
        folder = _ud_current_folder.get(ud)
        pending = len(_get_pending_videos(folder)) if folder else 0
        ud_data[str(ud)] = {
            "stok": len(links),
            "links": links[:20],
            "schedule": sched,
            "active": ud in active,
            "pending_videos": pending,
            "current_folder": os.path.basename(folder) if folder else None,
        }
    # Load settings
    settings = load_user_settings()
    interval = "60"; deskripsi = ""; hashtags = []; watermark = True
    for uid_str, cfg in settings.items():
        interval = cfg.get("interval", "60")
        deskripsi = cfg.get("deskripsi", "")
        hashtags = cfg.get("hashtags", [])
        watermark = cfg.get("watermark", True)
        break
    # List video_yt folders
    folders = []
    if os.path.isdir(FINAL_DIR):
        for name in sorted(os.listdir(FINAL_DIR)):
            path = os.path.join(FINAL_DIR, name)
            if os.path.isdir(path):
                files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
                total_size = sum(os.path.getsize(os.path.join(path, f)) for f in files)
                folders.append({"name": name, "files": len(files), "size_mb": round(total_size/(1024*1024), 1)})
    return jsonify({
        "auto_running": _auto_state["running"],
        "active_uds": active,
        "ud_data": ud_data,
        "settings": {"interval": interval, "deskripsi": deskripsi, "hashtags": hashtags, "watermark": watermark},
        "folders": folders,
    })

@app.route("/api/active_ud", methods=["POST"])
def api_set_active_ud():
    data = request.json
    uds = data.get("uds", [])
    uds = [int(x) for x in uds if 1 <= int(x) <= 20]
    save_active_ud(uds)
    return jsonify({"ok": True, "active": uds})

@app.route("/api/stok", methods=["POST"])
def api_add_stok():
    data = request.json
    ud = int(data.get("ud", 1))
    urls = data.get("urls", [])
    urls = [u.strip() for u in urls if u.strip()]
    links = load_stok_per_ud(ud)
    links.extend(urls)
    save_stok_per_ud(ud, links)
    return jsonify({"ok": True, "total": len(links)})

@app.route("/api/stok/delete", methods=["POST"])
def api_del_stok():
    data = request.json
    ud = int(data.get("ud", 1))
    idx = data.get("index")  # None = delete all
    if idx is None or idx == "all":
        save_stok_per_ud(ud, [])
        return jsonify({"ok": True, "remaining": 0})
    idx = int(idx)
    links = load_stok_per_ud(ud)
    if 0 <= idx < len(links):
        links.pop(idx)
        save_stok_per_ud(ud, links)
    return jsonify({"ok": True, "remaining": len(links)})

@app.route("/api/schedule", methods=["POST"])
def api_set_schedule():
    data = request.json
    ud = int(data.get("ud", 1))
    tanggal = data.get("tanggal")
    jam = data.get("jam", "00").zfill(2)
    menit = data.get("menit", "00").zfill(2)
    save_schedule_per_ud(ud, tanggal, jam, menit)
    return jsonify({"ok": True})

@app.route("/api/settings", methods=["POST"])
def api_set_settings():
    data = request.json
    settings = load_user_settings()
    # use first UID key or create "web"
    uid_key = "web"
    for k in settings:
        uid_key = k; break
    if uid_key not in settings:
        settings[uid_key] = {}
    cfg = settings[uid_key]
    if "deskripsi" in data: cfg["deskripsi"] = data["deskripsi"]
    if "interval" in data: cfg["interval"] = str(data["interval"])
    if "hashtags" in data: cfg["hashtags"] = data["hashtags"]
    if "watermark" in data: cfg["watermark"] = bool(data["watermark"])
    save_user_settings(settings)
    return jsonify({"ok": True})

@app.route("/api/auto/start", methods=["POST"])
def api_auto_start():
    if _auto_state["running"]:
        return jsonify({"ok": False, "msg": "Already running"})
    stop_evt = threading.Event()
    t = threading.Thread(target=_full_auto_daemon, args=(stop_evt,), daemon=True)
    _auto_state["running"] = True
    _auto_state["stop_event"] = stop_evt
    _auto_state["thread"] = t
    t.start()
    return jsonify({"ok": True})

@app.route("/api/auto/stop", methods=["POST"])
def api_auto_stop():
    if _auto_state["stop_event"]:
        _auto_state["stop_event"].set()
    _auto_state["running"] = False
    return jsonify({"ok": True})

@app.route("/api/logs_poll")
def api_logs_poll():
    last_id = int(request.args.get("last_id", 0))
    with _log_lock:
        new_logs = [e for e in _log_buffer if e.get("id", 0) > last_id]
        return jsonify(new_logs)

@app.route("/api/folder/delete", methods=["POST"])
def api_delete_folder():
    data = request.json
    name = data.get("name")
    if not name: return jsonify({"ok": False})
    path = os.path.join(FINAL_DIR, name)
    if os.path.isdir(path):
        shutil.rmtree(path)
    return jsonify({"ok": True})

if __name__ == "__main__":
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(FINAL_DIR, exist_ok=True)
    print("🌐 YT Bot Web Dashboard running on http://localhost:5555")
    app.run(host="0.0.0.0", port=5555, debug=False, threaded=True)
