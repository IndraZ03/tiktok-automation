"""
Grok TikTok Bot — Multi-Browser Grok Video Generation + TikTok Schedule Upload
Uses grok_autoV2.js for generation with 5 parallel browsers (ports 9220-9225).
User-data-dirs: 1grok, 2grok, 3grok, 4grok, 5grok.
Default video: Video mode, 720p, 10s, 9:16.
"""
import os, sys, re, time, asyncio, json, threading, random, logging, glob, shutil, base64, queue
from datetime import datetime, timedelta

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

sys.path.insert(0, r"c:\tiktok_automation")
from gtt_core import (
    APP_DIR, BAHAN_DIR, DB_FILE, RAW_DIR, USER_DATA_BASE,
    load_db, save_db, get_ud_config, stok_dir, count_stok, list_stok,
    load_ud_schedule, save_ud_schedule,
    load_prompts, save_prompts, list_bahan_folders, list_bahan_images,
    escape_html, build_tiktok_schedule, upload_tiktok_batch,
    resolve_ud_path, GrokRateLimitError, merge_video_pair,
    get_random_bahan_image,
)

from grok_imagine_bot import GrokBrowserWorker, render_browser_panel, make_progress_bar, format_elapsed, make_mini_bar

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8522516359:AAGrXXryDQVv5kC4twE28mcIOlVlSfSWqv0"
ALLOWED_USER_IDS = []

# ── Multi-browser Grok config ──
GROK_PORTS = [9220, 9221, 9222, 9223, 9224, 9225]  # 6 ports
GROK_USER_DATA_DIRS = [
    os.path.join(USER_DATA_BASE, "1grok"),
    os.path.join(USER_DATA_BASE, "2grok"),
    os.path.join(USER_DATA_BASE, "3grok"),
    os.path.join(USER_DATA_BASE, "4grok"),
    os.path.join(USER_DATA_BASE, "5grok"),
]
N_GROK_BROWSERS = len(GROK_USER_DATA_DIRS)  # 5

GROK_URL = "https://grok.com/imagine"
JS_FILE = os.path.join(APP_DIR, "grok_autoV2.js")

# ── Default video settings ──
DEFAULT_GEN_MODE = "Video"
DEFAULT_RESOLUTION = "720p"
DEFAULT_DURATION = "10s"
DEFAULT_ASPECT_RATIO = "9:16"

# ═══════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════
full_auto_task = {}      # uid -> {stop, thread}
active_gen_task = {}     # uid -> {stop, thread}
active_upload_task = {}  # uid -> {stop, thread}
active_mp3_task = {}     # uid -> {stop, thread}

def is_allowed(uid):
    return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS

def get_raw_dir(ud_num):
    return os.path.join(APP_DIR, f"gtt_raw_{ud_num}")

MP3_DIR = os.path.join(APP_DIR, "brutal_mp3")

def get_random_mp3():
    os.makedirs(MP3_DIR, exist_ok=True)
    mp3s = sorted([f for f in os.listdir(MP3_DIR) if f.lower().endswith('.mp3')])
    if not mp3s: return None
    return os.path.join(MP3_DIR, random.choice(mp3s))

def _mute_and_add_mp3(video_path, log_fn=None):
    import subprocess
    mp3_path = get_random_mp3()
    if not mp3_path:
        if log_fn: log_fn("⚠️ Tidak ada file MP3 di brutal_mp3, video tetap muted")
        tmp_out = video_path + ".muted.mp4"
        cmd = ["ffmpeg", "-y", "-i", video_path, "-an", "-c:v", "copy", tmp_out]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
                os.replace(tmp_out, video_path)
                if log_fn: log_fn("🔇 Video dimute (tanpa MP3)")
                return True
        except Exception as e:
            if log_fn: log_fn(f"❌ Mute error: {e}")
        try:
            if os.path.exists(tmp_out): os.remove(tmp_out)
        except: pass
        return False

    mp3_name = os.path.basename(mp3_path)
    if log_fn: log_fn(f"🎵 Menambahkan audio: {mp3_name[:40]}")
    tmp_out = video_path + ".audio.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", mp3_path,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        tmp_out
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
            os.replace(tmp_out, video_path)
            if log_fn: log_fn(f"✅ Audio diganti: {mp3_name[:40]}")
            return True
        if log_fn: log_fn(f"❌ Audio replace gagal: {r.stderr[-150:]}")
    except Exception as e:
        if log_fn: log_fn(f"❌ Audio replace error: {e}")
    try:
        if os.path.exists(tmp_out): os.remove(tmp_out)
    except: pass
    return False

def custom_merge_video_pair(vid1, vid2, output_dir, log_fn=None):
    out_path = merge_video_pair(vid1, vid2, output_dir, log_fn)
    if out_path:
        _mute_and_add_mp3(out_path, log_fn)
    return out_path

def merge_leftover_raw(ud_num, log_fn=None):
    """Merge leftover raw videos for this UD."""
    raw_dir = get_raw_dir(ud_num)
    if not os.path.isdir(raw_dir):
        return []
    raws = sorted(glob.glob(os.path.join(raw_dir, "*.mp4")), key=os.path.getmtime)
    if len(raws) < 2:
        return []
    if log_fn:
        log_fn(f"🔄 Ditemukan {len(raws)} raw video ganjil/genap sisa, melakukan merge pendahuluan...")
    
    out_dir = stok_dir(ud_num)
    os.makedirs(out_dir, exist_ok=True)
    merged = []
    
    for i in range(0, len(raws) - 1, 2):
        mp = custom_merge_video_pair(raws[i], raws[i+1], out_dir, log_fn)
        if mp:
            merged.append(mp)
            for vp in [raws[i], raws[i+1]]:
                try:
                    if os.path.exists(vp): os.remove(vp)
                except: pass

    if log_fn and merged:
        log_fn(f"✅ Pre-merge sisa selesai: {len(merged)} video baru masuk stok.")
    return merged

# ═══════════════════════════════════════════════════════════════
#  MULTI-BROWSER GROK GENERATION ENGINE
# ═══════════════════════════════════════════════════════════════
def generate_stok_multibrowser(ud_num, needed, prompt_text, bahan_folder, log_fn, stop_event,
                                raw_dir=None, merge_func=None, browser_states=None):
    """
    Multi-browser Grok generation using shared GrokBrowserWorker.
    Launches up to 5 browsers (ports 9220-9224, user-data 1grok-5grok).
    Each browser generates videos in parallel, results go to raw_dir,
    then merge pairs into stok.
    """

    if raw_dir is None:
        raw_dir = get_raw_dir(ud_num)
    out_dir = stok_dir(ud_num)
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    # Need 2 raw per merged video
    raw_needed = needed * 2
    file_lock = threading.Lock()

    # Determine how many browsers to use (up to 5, but at most raw_needed)
    n_browsers = min(N_GROK_BROWSERS, max(1, raw_needed))
    log_fn(f"[UD {ud_num}] 🚀 Multi-browser: {n_browsers} browser, target {needed} merged ({raw_needed} raw)")

    # Build task list
    all_tasks = []
    for vid_idx in range(raw_needed):
        image_path = get_random_bahan_image(bahan_folder) if bahan_folder else None
        all_tasks.append((vid_idx, prompt_text, image_path))

    # Distribute tasks across browsers
    browser_tasks = [[] for _ in range(n_browsers)]
    base_count = raw_needed // n_browsers
    remainder = raw_needed % n_browsers
    idx = 0
    for b in range(n_browsers):
        count = base_count + (1 if b < remainder else 0)
        browser_tasks[b] = all_tasks[idx:idx + count]
        idx += count

    # Launch browsers
    workers = []
    for b in range(n_browsers):
        if stop_event.is_set(): break
        port = GROK_PORTS[b]
        ud_dir = GROK_USER_DATA_DIRS[b]
        os.makedirs(ud_dir, exist_ok=True)

        video_cfg = {
            "gen_mode": DEFAULT_GEN_MODE,
            "resolution": DEFAULT_RESOLUTION,
            "duration": DEFAULT_DURATION,
            "aspect_ratio": DEFAULT_ASPECT_RATIO,
        }
        worker = GrokBrowserWorker(b, port, ud_dir, raw_dir, log_fn, stop_event, file_lock, video_cfg, browser_states)
        if worker.start():
            workers.append(worker)
            log_fn(f"✅ Browser {b+1} terhubung (port {port}, ud: {os.path.basename(ud_dir)})")
        else:
            log_fn(f"❌ Browser {b+1} gagal start")
        time.sleep(3)

    active_workers = [w for w in workers if w.driver is not None]
    if not active_workers:
        log_fn(f"[UD {ud_num}] ❌ Tidak ada browser yang berhasil terhubung!")
        return 0

    n_active = len(active_workers)
    log_fn(f"[UD {ud_num}] ✅ {n_active}/{n_browsers} browser aktif. Memulai generasi...")

    # Redistribute tasks to active workers only
    if n_active < n_browsers:
        active_tasks = [[] for _ in range(n_active)]
        all_flat = [t for bt in browser_tasks for t in bt]
        base_c = len(all_flat) // n_active
        rem_c = len(all_flat) % n_active
        ix = 0
        for b in range(n_active):
            cnt = base_c + (1 if b < rem_c else 0)
            active_tasks[b] = all_flat[ix:ix + cnt]
            ix += cnt
        browser_tasks = active_tasks

    for b in range(n_active):
        log_fn(f"  Browser {active_workers[b].bid+1}: {len(browser_tasks[b])} video")

    # Run all workers in parallel threads
    threads = []
    for b, worker in enumerate(active_workers):
        if not browser_tasks[b]:
            continue
        t = threading.Thread(target=worker.run_tasks,
                             args=(browser_tasks[b],), daemon=True)
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Shutdown browsers
    for w in workers:
        try: w.shutdown()
        except: pass

    total_gen = sum(w.generated for w in workers)
    total_fail = sum(w.failed for w in workers)
    log_fn(f"[UD {ud_num}] 🎬 Raw generate selesai: {total_gen} berhasil, {total_fail} gagal")

    if stop_event.is_set():
        return 0

    # Check rate limit
    if total_gen == 0:
        log_fn(f"[UD {ud_num}] ❌ Tidak ada video yang berhasil di-generate!")
        raise GrokRateLimitError("Tidak ada video yang berhasil. Kemungkinan rate limit.")

    # Merge raw videos into pairs
    raw_files = sorted(glob.glob(os.path.join(raw_dir, "*.mp4")), key=os.path.getmtime)
    log_fn(f"[UD {ud_num}] 🎬 Merge {len(raw_files)} raw videos...")
    merged_count = 0
    _merge_func = merge_func if merge_func else merge_video_pair
    for i in range(0, len(raw_files) - 1, 2):
        if stop_event.is_set(): break
        mp = _merge_func(raw_files[i], raw_files[i+1], out_dir, log_fn)
        if mp:
            merged_count += 1
            log_fn(f"[UD {ud_num}] Merged #{merged_count}")
        for vp in [raw_files[i], raw_files[i+1]]:
            try:
                if os.path.exists(vp): os.remove(vp)
            except: pass

    # Handle leftover odd raw
    remaining_raws = glob.glob(os.path.join(raw_dir, "*.mp4"))
    for leftover in remaining_raws:
        if os.path.exists(leftover):
            dest = os.path.join(out_dir, os.path.basename(leftover))
            try: shutil.move(leftover, dest)
            except: pass

    final_stok = count_stok(ud_num)
    log_fn(f"[UD {ud_num}] ✅ Pipeline selesai! Merged: {merged_count}, Stok total: {final_stok}")
    return merged_count


# ═══════════════════════════════════════════════════════════════
#  FULL AUTO DAEMON
# ═══════════════════════════════════════════════════════════════
def _run_ud_pipeline(ud_num, chat_id, bot, main_loop, stop_event):
    """Pipeline untuk satu UD: Generate -> Upload. Multi-browser."""
    import html as _html

    def send(text):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    db = load_db()
    cfg = get_ud_config(db, ud_num)
    prompt_text = load_prompts().get(cfg.get("prompt_name", ""), "")
    if not prompt_text:
        send(f"<b>UD {ud_num}</b>: Prompt tidak ditemukan, skip!")
        return

    batch_size = cfg.get("batch_size", 30)

    send(f"<b>UD {ud_num}</b>: Pipeline dimulai (Multi-Browser)\n"
         f"Browsers: <b>{N_GROK_BROWSERS}</b> (ports {GROK_PORTS[0]}-{GROK_PORTS[N_GROK_BROWSERS-1]})\n"
         f"Video: <code>{DEFAULT_GEN_MODE} {DEFAULT_RESOLUTION} {DEFAULT_DURATION} {DEFAULT_ASPECT_RATIO}</code>")

    # Merge left over sebelum masuk gen
    leftover_merged = merge_leftover_raw(ud_num)
    if leftover_merged:
        send(f"✅ UD {ud_num}: Pre-merge {len(leftover_merged)} video sisa!")

    current_stok = count_stok(ud_num)
    needed = max(0, batch_size - current_stok)

    # STEP 1: Generate jika stok kurang
    if needed > 0 and not stop_event.is_set():
        send(f"<b>UD {ud_num} STEP 1:</b> Generate {needed} video (stok: {current_stok}/{batch_size})")
        gen_log_lines = []; gen_log_lock = threading.Lock()
        gen_done = threading.Event()

        def log_fn(msg):
            s = _html.escape(str(msg))
            with gen_log_lock:
                gen_log_lines.append(f"<code>[{datetime.now().strftime('%H:%M:%S')}]</code> {s}")
                if len(gen_log_lines) > 20: gen_log_lines.pop(0)

        browser_states = {}

        def _gen_updater():
            last_text = ""
            start_time = time.time()
            while not gen_done.is_set() and not stop_event.is_set():
                time.sleep(3)
                elapsed_str = format_elapsed(time.time() - start_time)
                
                with gen_log_lock:
                    log_text = "\n".join(gen_log_lines[-8:]) if gen_log_lines else "<i>Menunggu...</i>"
                
                b_cfg_str = f"({N_GROK_BROWSERS} browsers) ⏱ {elapsed_str}"
                
                text = (
                    f"<b>[UD {ud_num}] 🚀 Generate Progress ({count_stok(ud_num)}/{batch_size})</b>\n"
                    f"{b_cfg_str}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                )
                panel = render_browser_panel(browser_states)
                if panel:
                    text += f"🖥 <b>Browser Status:</b>\n{panel}\n━━━━━━━━━━━━━━━━━━\n"
                text += log_text
                
                if text != last_text:
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)
                        future.result(timeout=10)
                        last_text = text
                    except: pass

        updater_t = threading.Thread(target=_gen_updater, daemon=True)
        updater_t.start()

        try:
            generate_stok_multibrowser(
                ud_num, needed, prompt_text, cfg["bahan_folder"],
                log_fn, stop_event,
                raw_dir=get_raw_dir(ud_num), merge_func=custom_merge_video_pair,
                browser_states=browser_states)
        except GrokRateLimitError:
            gen_done.set()
            updater_t.join(timeout=3)
            send(
                "🚫 <b>RATE LIMIT REACHED!</b>\n\n"
                f"UD {ud_num}: Grok sudah mencapai batas generate.\n"
                "Pesan dari Grok: <i>Rate limit reached — Upgrade to SuperGrok Heavy</i>\n\n"
                "Generate <b>dihentikan otomatis</b>.\n"
                f"Stok saat ini: <b>{count_stok(ud_num)}</b>")
            return
        gen_done.set()
        updater_t.join(timeout=3)
        send(f"<b>UD {ud_num}:</b> Generate selesai! Stok: {count_stok(ud_num)}")

    if stop_event.is_set(): return

    # STEP 2: Build schedule & upload
    stok_files = list_stok(ud_num)[:batch_size]
    if not stok_files:
        send(f"<b>UD {ud_num}:</b> Stok kosong, skip upload!")
        return

    interval_hours = cfg.get("interval_hours", 5)
    start_dt = datetime.now() + timedelta(minutes=30)
    start_dt = start_dt.replace(second=0, microsecond=0)
    rounded = ((start_dt.minute + 4) // 5) * 5
    if rounded >= 60:
        start_dt = start_dt.replace(minute=0) + timedelta(hours=1)
    else:
        start_dt = start_dt.replace(minute=rounded)

    schedule = build_tiktok_schedule(stok_files, start_dt, interval_hours)
    save_ud_schedule(ud_num, schedule)

    preview = "\n".join(f"  {i+1}. <code>{s['schedule']}</code>" for i, s in enumerate(schedule))
    full_text = f"<b>UD {ud_num} STEP 2:</b> Upload {len(schedule)} video\nInterval: {interval_hours}h\n\n{preview}"
    if len(full_text) <= 4096:
        send(full_text)
    else:
        send(full_text[:4096])
        for cs in range(4096, len(full_text), 4096):
            send(full_text[cs:cs+4096])

    upload_stats_fa = {"success": 0, "fail": 0, "current": 0, "total": len(schedule)}
    log_lines2 = []; log_lock2 = threading.Lock()
    upload_done_fa = threading.Event()

    def log_fn2(msg):
        with log_lock2:
            log_lines2.append(msg)
            if len(log_lines2) > 25: log_lines2.pop(0)
            if '✅ Upload sukses' in msg or ('✅' in msg and 'sukses' in msg):
                upload_stats_fa["success"] += 1
            if 'Upload:' in msg or ('Upload' in msg and '/' in msg):
                import re as _re
                match = _re.search(r'\[(\d+)/\d+\]', msg)
                if match:
                    upload_stats_fa["current"] = int(match.group(1))

    def _fa_upload_updater():
        last_text = ""
        while not upload_done_fa.is_set() and not stop_event.is_set():
            time.sleep(5)
            with log_lock2:
                if not log_lines2: continue
                st = upload_stats_fa
                text = (
                    f"<b>[UD {ud_num}] 📤 Upload TikTok</b>\n"
                    f"Video: <b>{st['current']}/{st['total']}</b>\n"
                    f"✅ Berhasil: <b>{st['success']}</b> | ❌ Gagal: <b>{st['fail']}</b>\n\n" +
                    "\n".join(log_lines2[-10:]))
            if text != last_text:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)
                    future.result(timeout=10)
                    last_text = text
                except: pass

    updater_t2 = threading.Thread(target=_fa_upload_updater, daemon=True)
    updater_t2.start()

    cfg["tiktok_ud"] = os.path.join(APP_DIR, "user_data", str(ud_num))
    uploaded = upload_tiktok_batch(ud_num, schedule, cfg, log_fn2, stop_event)
    upload_done_fa.set()
    updater_t2.join(timeout=3)
    upload_stats_fa["success"] = uploaded
    upload_stats_fa["fail"] = upload_stats_fa["total"] - uploaded
    send(f"<b>UD {ud_num}:</b> Upload selesai!\n"
         f"✅ Berhasil: <b>{uploaded}/{len(schedule)}</b>\n"
         f"❌ Gagal: <b>{upload_stats_fa['fail']}</b>")

    # STEP 3: Update schedule untuk pipeline berikutnya
    if uploaded > 0:
        db = load_db()
        cfg = get_ud_config(db, ud_num)
        last_sched_str = schedule[-1]["schedule"]
        try:
            last_dt = datetime.strptime(last_sched_str, "%Y-%m-%d %H:%M")
        except:
            last_dt = datetime.now()
        next_dt = last_dt + timedelta(hours=interval_hours, minutes=random.randint(0, 30))
        cfg["schedule"]["tanggal"] = next_dt.strftime("%Y-%m-%d")
        cfg["schedule"]["jam"] = f"{next_dt.hour:02d}"
        cfg["schedule"]["menit"] = f"{next_dt.minute:02d}"
        save_db(db)
        send(f"<b>UD {ud_num}:</b> Next pipeline: <code>{next_dt.strftime('%Y-%m-%d %H:%M')}</code>")


def run_full_auto(uid, chat_id, bot, main_loop, stop_event):
    def send(text):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    db = load_db()
    active = db.get("active_ud", [1, 2])
    send(f"<b>Full Auto dimulai! (Multi-Browser Mode)</b>\n"
         f"Active UD: <b>{', '.join(str(x) for x in active)}</b>\n"
         f"Grok Browsers: <b>{N_GROK_BROWSERS}</b> (ports {GROK_PORTS[0]}-{GROK_PORTS[N_GROK_BROWSERS-1]})\n"
         f"Video: <code>{DEFAULT_GEN_MODE} {DEFAULT_RESOLUTION} {DEFAULT_DURATION} {DEFAULT_ASPECT_RATIO}</code>")

    while not stop_event.is_set():
        db = load_db()
        active = db.get("active_ud", [1, 2])

        now = datetime.now()
        ready_uds = []
        future_uds = []
        for ud_num in active:
            cfg = get_ud_config(db, ud_num)
            if not cfg.get("prompt_name") or not cfg.get("bahan_folder"):
                continue
            sched = cfg.get("schedule", {})
            try:
                trigger_dt = datetime.strptime(
                    f"{sched['tanggal']} {sched['jam']}:{sched['menit']}", "%Y-%m-%d %H:%M")
            except:
                continue
            if trigger_dt <= now:
                ready_uds.append(ud_num)
            else:
                future_uds.append((trigger_dt, ud_num))

        if not ready_uds and not future_uds:
            if not stop_event.is_set():
                send("Semua UD belum dikonfigurasi (prompt/bahan kosong). Menunggu 60 detik...")
                for _ in range(12):
                    if stop_event.is_set(): break
                    time.sleep(5)
            continue

        # Jika ada UD yang siap → jalankan satu per satu (karena browser shared)
        if ready_uds:
            send(f"<b>🚀 Menjalankan {len(ready_uds)} UD:</b> {', '.join(f'UD {u}' for u in ready_uds)}")
            for ud_num in ready_uds:
                if stop_event.is_set(): break
                _run_ud_pipeline(ud_num, chat_id, bot, main_loop, stop_event)

            if stop_event.is_set(): break
            send(f"<b>✅ Semua UD selesai!</b> ({', '.join(f'UD {u}' for u in ready_uds)})")
            time.sleep(10)
            continue

        # Tidak ada yang siap → tunggu jadwal terdekat
        future_uds.sort(key=lambda x: x[0])
        trigger_dt, next_ud = future_uds[0]
        sched_info = "\n".join(
            f"  {'>' if c[1]==next_ud else ' '} UD {c[1]}: <code>{c[0].strftime('%Y-%m-%d %H:%M')}</code>"
            for c in future_uds)
        wait_sec = (trigger_dt - now).total_seconds()
        h = int(wait_sec // 3600); m = int((wait_sec % 3600) // 60)
        send(f"<b>Jadwal UD:</b>\n{sched_info}\n\nMenunggu: <b>UD {next_ud}</b> ({h}j {m}m lagi)")

        elapsed = 0
        while elapsed < wait_sec and not stop_event.is_set():
            time.sleep(min(30, wait_sec - elapsed)); elapsed += 30

    full_auto_task.pop(uid, None)
    send("<b>Full Auto dihentikan.</b>")

# ═══════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════
def main_menu_kb(uid=None):
    is_auto = bool(uid and full_auto_task.get(uid))
    is_gen = bool(uid and active_gen_task.get(uid))
    is_upload = bool(uid and active_upload_task.get(uid))
    db = load_db()
    active = db.get("active_ud", [1, 2])
    rows = [
        [InlineKeyboardButton("Kelola Bahan", callback_data="bahan_menu"),
         InlineKeyboardButton("Kelola Prompt", callback_data="prompt_menu")],
    ]
    # UD status buttons
    ud_row = []
    for ud in active:
        ud_row.append(InlineKeyboardButton(f"UD {ud}", callback_data=f"ud_status_{ud}"))
        if len(ud_row) == 3:
            rows.append(ud_row); ud_row = []
    if ud_row: rows.append(ud_row)

    # Stok Sekarang & Upload Sekarang
    rows.append([InlineKeyboardButton("🎬 Stok Sekarang", callback_data="stok_now_choose"),
                 InlineKeyboardButton("📤 Upload Sekarang", callback_data="upload_now_choose")])
    rows.append([InlineKeyboardButton("🎵 Mute+MP3 (brutal_mp3)", callback_data="mp3_choose")])

    # Stop buttons when tasks are running
    is_mp3 = bool(uid and active_mp3_task.get(uid))
    if is_gen:
        rows.append([InlineKeyboardButton("⏹ Stop Generate", callback_data="stop_gen")])
    if is_upload:
        rows.append([InlineKeyboardButton("⏹ Stop Upload", callback_data="stop_upload")])
    if is_mp3:
        rows.append([InlineKeyboardButton("⏹ Stop Mute+MP3", callback_data="stop_mp3")])

    rows.append([InlineKeyboardButton("Settings", callback_data="settings_menu")])
    rows.append([InlineKeyboardButton(
        "Stop Auto" if is_auto else "Full Auto",
        callback_data="stop_auto" if is_auto else "start_auto")])
    rows.append([InlineKeyboardButton("Refresh", callback_data="refresh")])
    return InlineKeyboardMarkup(rows)

def status_text():
    db = load_db()
    active = db.get("active_ud", [1, 2])
    lines = ["<b>Grok TikTok Bot (Multi-Browser)</b>\n"]
    lines.append(f"Active UD: <b>{', '.join(str(x) for x in active)}</b>")
    lines.append(f"Grok Browsers: <b>{N_GROK_BROWSERS}</b> (ports {GROK_PORTS[0]}-{GROK_PORTS[N_GROK_BROWSERS-1]})")
    lines.append(f"Video: <code>{DEFAULT_GEN_MODE} {DEFAULT_RESOLUTION} {DEFAULT_DURATION} {DEFAULT_ASPECT_RATIO}</code>\n")
    for ud in active:
        cfg = get_ud_config(db, ud)
        stok = count_stok(ud)
        sched = cfg.get("schedule", {})
        sched_str = f"{sched.get('tanggal','-')} {sched.get('jam','00')}:{sched.get('menit','00')}"
        prod = "ON" if cfg.get("add_product") else "OFF"
        sound = "ON" if cfg.get("add_sound") else "OFF"
        lines.append(
            f"<b>UD {ud}:</b>\n"
            f"  Stok: <b>{stok}/{cfg.get('batch_size',30)}</b>\n"
            f"  Prompt: <code>{escape_html(cfg.get('prompt_name','(kosong)'))}</code>\n"
            f"  Bahan: <code>{escape_html(cfg.get('bahan_folder','(kosong)'))}</code>\n"
            f"  Desc: <code>{escape_html(cfg.get('deskripsi','(kosong)')[:40])}</code>\n"
            f"  Interval: <b>{cfg.get('interval_hours',5)}h</b> | Produk: {prod} | Sound: {sound}\n"
            f"  Schedule: <code>{sched_str}</code>\n")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
#  TELEGRAM HANDLERS
# ═══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    await update.message.reply_text(status_text(), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))

async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid): return
    raw = update.message.text.strip()
    args = raw.split(None, 1)
    if len(args) < 2:
        await update.message.reply_text(
            "<b>Format /set:</b>\n\n"
            "<code>/set ud 1,2</code> - Active UD\n"
            "<code>/set prompt 1 hijab</code> - Prompt UD 1\n"
            "<code>/set bahan 1 hijab</code> - Bahan folder UD 1\n"
            "<code>/set desc 1 teks...</code> - Deskripsi UD 1\n"
            "<code>/set hashtags 1 fyp, viral</code> - Hashtags UD 1\n"
            "<code>/set produk 1 on/off</code> - Toggle produk\n"
            "<code>/set produk_input 1 JUDUL</code> - Judul produk\n"
            "<code>/produk_radio 1</code> - Kelola daftar produk radio UD 1\n"
            "<code>/set sound 1 on/off</code> - Toggle sound favorites\n"
            "<code>/set interval 1 5</code> - Interval (jam)\n"
            "<code>/set batch 1 30</code> - Batch size\n"
            "<code>/set sched 1 2026-03-16 02:00</code> - Schedule\n"
            "<code>/set tiktok_ud 1 2</code> - TikTok user_data\n"
            "<code>/set tiktok_port 1 9223</code> - TikTok port",
            parse_mode=ParseMode.HTML)
        return
    parts = args[1].split(None, 1)
    sub = parts[0].lower()
    val = parts[1].strip() if len(parts) > 1 else ""
    db = load_db()

    # Global settings
    if sub == "ud":
        nums = [int(x) for x in re.split(r'[,\s]+', val) if x.strip().isdigit()]
        nums = [n for n in nums if 1 <= n <= 7]
        if not nums:
            await update.message.reply_text("Format: <code>/set ud 1,2</code>", parse_mode=ParseMode.HTML); return
        db["active_ud"] = nums; save_db(db)
        await update.message.reply_text(f"Active UD: <b>{', '.join(str(x) for x in nums)}</b>", parse_mode=ParseMode.HTML)
        return

    # Per-UD settings: /set SUB UD_NUM VALUE
    sub_parts = val.split(None, 1)
    if not sub_parts or not sub_parts[0].isdigit():
        await update.message.reply_text("Format: <code>/set [cmd] [UD_NUM] [value]</code>", parse_mode=ParseMode.HTML); return
    ud_num = int(sub_parts[0])
    ud_val = sub_parts[1].strip() if len(sub_parts) > 1 else ""
    cfg = get_ud_config(db, ud_num)

    if sub == "prompt":
        prompts = load_prompts()
        if ud_val not in prompts:
            await update.message.reply_text(f"Prompt <code>{escape_html(ud_val)}</code> tidak ada!\nTersedia: {', '.join(prompts.keys())}", parse_mode=ParseMode.HTML); return
        cfg["prompt_name"] = ud_val
    elif sub == "bahan":
        imgs = list_bahan_images(ud_val)
        if not imgs:
            await update.message.reply_text(f"Folder <code>{escape_html(ud_val)}</code> kosong!", parse_mode=ParseMode.HTML); return
        cfg["bahan_folder"] = ud_val
    elif sub == "desc":
        cfg["deskripsi"] = ud_val
    elif sub in ("hashtags", "tags"):
        tags = [t.strip().lstrip('#') for t in re.split(r'[,\n]+', ud_val) if t.strip()]
        cfg["hashtags"] = tags; ud_val = ', '.join('#'+t for t in tags)
    elif sub == "produk":
        cfg["add_product"] = ud_val.lower() in ("on","true","1","ya")
        ud_val = "ON" if cfg["add_product"] else "OFF"
    elif sub == "produk_radio":
        radio_list = cfg.get("nama_produk_radio_list", [])
        if ud_val and ud_val not in radio_list:
            radio_list.append(ud_val)
        cfg["nama_produk_radio_list"] = radio_list
        cfg["nama_produk_radio"] = ud_val
        ud_val = ', '.join(radio_list) if radio_list else '(kosong)'
    elif sub == "produk_input":
        cfg["nama_produk_input"] = ud_val
    elif sub == "sound":
        cfg["add_sound"] = ud_val.lower() in ("on","true","1","ya")
        ud_val = "ON" if cfg["add_sound"] else "OFF"
    elif sub == "interval":
        try: cfg["interval_hours"] = int(ud_val)
        except: cfg["interval_hours"] = 5
        ud_val = f"{cfg['interval_hours']} jam"
    elif sub == "batch":
        try: cfg["batch_size"] = int(ud_val)
        except: cfg["batch_size"] = 30
        ud_val = str(cfg["batch_size"])
    elif sub == "sched":
        sched_parts = ud_val.split()
        if len(sched_parts) < 2:
            await update.message.reply_text("Format: <code>/set sched 1 2026-03-16 02:00</code>", parse_mode=ParseMode.HTML); return
        date_str = sched_parts[0]
        time_str = sched_parts[1].replace(".", ":")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            tp = time_str.split(":")
            cfg["schedule"] = {"tanggal": date_str, "jam": tp[0].zfill(2), "menit": tp[1].zfill(2)}
            ud_val = f"{date_str} {tp[0].zfill(2)}:{tp[1].zfill(2)}"
        except:
            await update.message.reply_text("Format tanggal salah!", parse_mode=ParseMode.HTML); return
    elif sub == "tiktok_ud":
        cfg["tiktok_ud"] = resolve_ud_path(ud_val)
        ud_val = cfg["tiktok_ud"]
    elif sub == "tiktok_port":
        cfg["tiktok_port"] = ud_val
    else:
        await update.message.reply_text("Sub-command tidak dikenal. Ketik <code>/set</code>", parse_mode=ParseMode.HTML); return

    save_db(db)
    await update.message.reply_text(f"UD {ud_num} <code>{sub}</code> = <code>{escape_html(str(ud_val)[:100])}</code>", parse_mode=ParseMode.HTML)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Grok TikTok Bot (Multi-Browser)</b>\n\n"
        "/start - Menu utama\n"
        "/set - Konfigurasi (lihat daftar)\n"
        "/help - Panduan\n"
        "/stop - Stop auto/generate\n\n"
        "<b>Grok Config:</b>\n"
        f"  Browsers: {N_GROK_BROWSERS} (ports {GROK_PORTS[0]}-{GROK_PORTS[N_GROK_BROWSERS-1]})\n"
        f"  User Data: 1grok, 2grok, 3grok, 4grok, 5grok\n"
        f"  Video: {DEFAULT_GEN_MODE} {DEFAULT_RESOLUTION} {DEFAULT_DURATION} {DEFAULT_ASPECT_RATIO}\n\n"
        "<b>Flow:</b>\n"
        "1. Set prompt dan bahan per UD\n"
        "2. Set schedule per UD\n"
        "3. Full Auto: generate + upload otomatis\n"
        "4. Interval = jam antar video TikTok (default 5h)",
        parse_mode=ParseMode.HTML)

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    stopped = []
    t = full_auto_task.get(uid)
    if t: t["stop"].set(); full_auto_task.pop(uid, None); stopped.append("Full Auto")
    t = active_gen_task.get(uid)
    if t: t["stop"].set(); active_gen_task.pop(uid, None); stopped.append("Generate")
    if stopped:
        await update.message.reply_text(f"Dihentikan: {', '.join(stopped)}")
    else:
        await update.message.reply_text("Tidak ada proses berjalan.")

# ═══════════════════════════════════════════════════════════════
#  PRODUK RADIO (per UD list management)
# ═══════════════════════════════════════════════════════════════
async def cmd_produk_radio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/produk_radio UD_NUM — list; /produk_radio UD_NUM add NAMA; /produk_radio UD_NUM del NOMOR"""
    uid = update.effective_user.id
    if not is_allowed(uid): return
    raw = update.message.text.strip(); args = raw.split(None, 3)

    if len(args) < 2 or not args[1].isdigit():
        await update.message.reply_text(
            "<b>📻 Produk Radio</b>\n\n"
            "<code>/produk_radio 1</code> — lihat daftar UD 1\n"
            "<code>/produk_radio 1 add NAMA</code> — tambah\n"
            "<code>/produk_radio 1 del NOMOR</code> — hapus",
            parse_mode=ParseMode.HTML); return

    ud_num = int(args[1])
    db = load_db()
    cfg = get_ud_config(db, ud_num)
    radio_list = cfg.get("nama_produk_radio_list", [])
    if not radio_list and cfg.get("nama_produk_radio", ""):
        radio_list = [cfg["nama_produk_radio"]]
        cfg["nama_produk_radio_list"] = radio_list

    if len(args) < 3:
        if not radio_list:
            await update.message.reply_text(
                f"<b>📻 Produk Radio UD {ud_num}:</b>\n(kosong)\n\n"
                f"<code>/produk_radio {ud_num} add NAMA</code> untuk menambah",
                parse_mode=ParseMode.HTML)
        else:
            lines = [f"  {i+1}. <code>{escape_html(r)}</code>" for i, r in enumerate(radio_list)]
            await update.message.reply_text(
                f"<b>📻 Produk Radio UD {ud_num} ({len(radio_list)}):</b>\n" + "\n".join(lines) +
                f"\n\nUpload akan memilih <b>random 1</b> dari daftar.\n"
                f"<code>/produk_radio {ud_num} add NAMA</code> — tambah\n"
                f"<code>/produk_radio {ud_num} del NOMOR</code> — hapus",
                parse_mode=ParseMode.HTML)
        return

    sub_cmd = args[2].lower()
    if sub_cmd == "add" and len(args) >= 4:
        new_name = args[3].strip()
        if new_name in radio_list:
            await update.message.reply_text(f"<code>{escape_html(new_name)}</code> sudah ada!", parse_mode=ParseMode.HTML); return
        radio_list.append(new_name)
        cfg["nama_produk_radio_list"] = radio_list
        cfg["nama_produk_radio"] = new_name
        save_db(db)
        await update.message.reply_text(
            f"✅ UD {ud_num}: Ditambahkan <code>{escape_html(new_name)}</code>\nTotal: {len(radio_list)} produk radio",
            parse_mode=ParseMode.HTML)
    elif sub_cmd == "del" and len(args) >= 4:
        try:
            idx = int(args[3].strip()) - 1
            if 0 <= idx < len(radio_list):
                removed = radio_list.pop(idx)
                cfg["nama_produk_radio_list"] = radio_list
                save_db(db)
                await update.message.reply_text(
                    f"🗑 UD {ud_num}: Dihapus <code>{escape_html(removed)}</code>\nSisa: {len(radio_list)}",
                    parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(f"Nomor tidak valid (1-{len(radio_list)})"); return
        except ValueError:
            await update.message.reply_text(f"Gunakan nomor, contoh: <code>/produk_radio {ud_num} del 1</code>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(
            f"<b>📻 Produk Radio UD {ud_num}:</b>\n"
            f"<code>/produk_radio {ud_num}</code> — lihat\n"
            f"<code>/produk_radio {ud_num} add NAMA</code> — tambah\n"
            f"<code>/produk_radio {ud_num} del NOMOR</code> — hapus",
            parse_mode=ParseMode.HTML)

# ═══════════════════════════════════════════════════════════════
#  BUTTON HANDLER
# ═══════════════════════════════════════════════════════════════
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not is_allowed(uid): return
    data = q.data; chat_id = q.message.chat_id
    bot = ctx.bot; main_loop = asyncio.get_event_loop()
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Kembali", callback_data="refresh")]])

    if data == "refresh":
        await q.edit_message_text(status_text(), parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    # ── BAHAN MENU ──
    if data == "bahan_menu":
        folders = list_bahan_folders()
        rows = []
        for f in folders:
            imgs = list_bahan_images(f)
            rows.append([InlineKeyboardButton(f"{f} ({len(imgs)})", callback_data=f"bahan_view|{f}")])
        rows.append([InlineKeyboardButton("+ Tambah Folder", callback_data="bahan_add_folder")])
        rows.append([InlineKeyboardButton("Kembali", callback_data="refresh")])
        text = f"<b>Kelola Bahan</b>\n{len(folders)} folder tersedia"
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)); return

    if data.startswith("bahan_view|"):
        folder = data.split("|", 1)[1]
        imgs = list_bahan_images(folder)
        text = f"<b>Bahan: {escape_html(folder)}</b>\n{len(imgs)} gambar\n\n"
        for i, img in enumerate(imgs[:20]):
            text += f"  {i+1}. <code>{os.path.basename(img)}</code>\n"
        if len(imgs) > 20: text += f"  ... +{len(imgs)-20} lagi\n"
        text += "\nKirim foto untuk menambah gambar ke folder ini."
        ctx.user_data["waiting_for"] = f"bahan_photo|{folder}"
        rows = [
            [InlineKeyboardButton("Hapus Folder", callback_data=f"bahan_del|{folder}")],
            [InlineKeyboardButton("Kembali", callback_data="bahan_menu")]
        ]
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)); return

    if data == "bahan_add_folder":
        ctx.user_data["waiting_for"] = "bahan_new_folder"
        await bot.send_message(chat_id, "Kirim nama folder baru:"); return

    if data.startswith("bahan_del|"):
        folder = data.split("|", 1)[1]
        path = os.path.join(BAHAN_DIR, folder)
        try:
            if os.path.isdir(path): shutil.rmtree(path)
            await q.edit_message_text(f"Folder <code>{escape_html(folder)}</code> dihapus!", parse_mode=ParseMode.HTML, reply_markup=back_kb)
        except Exception as e:
            await q.edit_message_text(f"Gagal hapus: {e}", reply_markup=back_kb)
        return

    # ── PROMPT MENU ──
    if data == "prompt_menu":
        prompts = load_prompts()
        rows = []
        for name in prompts:
            rows.append([InlineKeyboardButton(name, callback_data=f"prompt_view|{name}")])
        rows.append([InlineKeyboardButton("+ Tambah Prompt", callback_data="prompt_add")])
        rows.append([InlineKeyboardButton("Kembali", callback_data="refresh")])
        text = f"<b>Kelola Prompt</b>\n{len(prompts)} prompt tersedia"
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)); return

    if data.startswith("prompt_view|"):
        name = data.split("|", 1)[1]
        prompts = load_prompts()
        text_val = prompts.get(name, "(tidak ditemukan)")
        rows = [
            [InlineKeyboardButton("Hapus Prompt", callback_data=f"prompt_del|{name}")],
            [InlineKeyboardButton("Kembali", callback_data="prompt_menu")]
        ]
        await q.edit_message_text(
            f"<b>Prompt: {escape_html(name)}</b>\n\n<code>{escape_html(text_val[:500])}</code>",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)); return

    if data == "prompt_add":
        ctx.user_data["waiting_for"] = "prompt_name"
        await bot.send_message(chat_id, "Kirim <b>nama</b> prompt baru:", parse_mode=ParseMode.HTML); return

    if data.startswith("prompt_del|"):
        name = data.split("|", 1)[1]
        prompts = load_prompts()
        prompts.pop(name, None); save_prompts(prompts)
        await q.edit_message_text(f"Prompt <code>{escape_html(name)}</code> dihapus!", parse_mode=ParseMode.HTML, reply_markup=back_kb); return

    # ── UD STATUS ──
    if data.startswith("ud_status_"):
        ud_num = int(data.split("_")[-1])
        db = load_db()
        cfg = get_ud_config(db, ud_num)
        stok = count_stok(ud_num)
        sched = cfg.get("schedule", {})
        sched_str = f"{sched.get('tanggal','-')} {sched.get('jam','00')}:{sched.get('menit','00')}"
        hashtags_disp = ', '.join('#'+h for h in cfg.get('hashtags',[])) or '(kosong)'
        text = (
            f"<b>UD {ud_num} Status</b>\n\n"
            f"Stok: <b>{stok}/{cfg.get('batch_size',30)}</b> video\n"
            f"Prompt: <code>{escape_html(cfg.get('prompt_name','(kosong)'))}</code>\n"
            f"Bahan: <code>{escape_html(cfg.get('bahan_folder','(kosong)'))}</code>\n"
            f"Deskripsi: <code>{escape_html(cfg.get('deskripsi','(kosong)')[:50])}</code>\n"
            f"Hashtags: <code>{escape_html(hashtags_disp)}</code>\n"
            f"Interval: <b>{cfg.get('interval_hours',5)}h</b>\n"
            f"Schedule: <code>{sched_str}</code>\n\n"
            f"<b>Produk:</b> {'ON' if cfg.get('add_product') else 'OFF'}\n"
            f"  Radio ({len(cfg.get('nama_produk_radio_list',[]))}): <code>{escape_html(', '.join(cfg.get('nama_produk_radio_list',[])) or cfg.get('nama_produk_radio','(kosong)'))[:60]}</code>\n"
            f"  Input: <code>{escape_html(cfg.get('nama_produk_input','(kosong)')[:40])}</code>\n"
            f"<b>Sound:</b> {'ON' if cfg.get('add_sound') else 'OFF'}\n\n"
            f"<b>🔌 Grok (Shared Multi-Browser):</b>\n"
            f"  Browsers: {N_GROK_BROWSERS} (ports {GROK_PORTS[0]}-{GROK_PORTS[N_GROK_BROWSERS-1]})\n"
            f"  User Data: 1grok-5grok\n"
            f"  Video: {DEFAULT_GEN_MODE} {DEFAULT_RESOLUTION} {DEFAULT_DURATION} {DEFAULT_ASPECT_RATIO}\n"
            f"<b>🔌 TikTok Chrome:</b>\n"
            f"  UD: <code>{escape_html(cfg.get('tiktok_ud',''))}</code>\n"
            f"  Port: <code>{cfg.get('tiktok_port','')}</code>")
        rows = [
            [InlineKeyboardButton(f"Generate UD {ud_num}", callback_data=f"gen_ud_{ud_num}"),
             InlineKeyboardButton(f"Upload UD {ud_num}", callback_data=f"upload_ud_{ud_num}")],
            [InlineKeyboardButton(f"Clear Stok UD {ud_num}", callback_data=f"clear_stok_{ud_num}")],
            [InlineKeyboardButton("Kembali", callback_data="refresh")]
        ]
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)); return

    # ── GENERATE NOW (per UD) ──
    if data.startswith("gen_ud_"):
        ud_num = int(data.split("_")[-1])
        if active_gen_task.get(uid):
            await q.edit_message_text("Generate sudah berjalan!", reply_markup=main_menu_kb(uid)); return
        db = load_db()
        cfg = get_ud_config(db, ud_num)
        prompt_text = load_prompts().get(cfg.get("prompt_name",""), "")
        if not prompt_text:
            await q.edit_message_text("Prompt belum diset!", reply_markup=main_menu_kb(uid)); return
        if not cfg.get("bahan_folder"):
            await q.edit_message_text("Bahan belum diset!", reply_markup=main_menu_kb(uid)); return
            
        merge_leftover_raw(ud_num)
        needed = max(0, cfg.get("batch_size", 30) - count_stok(ud_num))
        
        if needed <= 0:
            await q.edit_message_text(f"Stok UD {ud_num} sudah penuh!", reply_markup=main_menu_kb(uid)); return

        stop_evt = threading.Event()
        
        initial_msg = await q.edit_message_text(
            f"Generate UD {ud_num} dimulai! Target: {needed} video\n"
            f"Multi-Browser: {N_GROK_BROWSERS} browser (ports {GROK_PORTS[0]}-{GROK_PORTS[N_GROK_BROWSERS-1]})\n"
            f"Membuka browser...", reply_markup=main_menu_kb(uid))
        msg_id = initial_msg.message_id
        
        log_lines = []
        log_lock = threading.Lock()
        
        def _log_updater():
            last_text = ""
            while not stop_evt.is_set():
                time.sleep(4.0)
                with log_lock:
                    if not log_lines: continue
                    text = f"<b>[UD {ud_num}] Multi-Browser Generate {needed} Stok</b>\n" + "\n".join(log_lines)
                if text != last_text:
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, 
                                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                            main_loop
                        )
                        future.result(timeout=5)
                        last_text = text
                    except Exception:
                        pass

        threading.Thread(target=_log_updater, daemon=True).start()
        
        def _gen():
            import html
            def lg(msg):
                s = html.escape(str(msg))
                with log_lock:
                    log_lines.append(f"<code>[{datetime.now().strftime('%H:%M:%S')}]</code> {s}")
                    if len(log_lines) > 20:
                        log_lines.pop(0)
                        
            try:
                generate_stok_multibrowser(
                    ud_num, needed, prompt_text, cfg["bahan_folder"],
                    lg, stop_evt,
                    raw_dir=get_raw_dir(ud_num), merge_func=custom_merge_video_pair)
            except GrokRateLimitError:
                lg("🚫 RATE LIMIT! Grok tidak bisa generate lagi.")
                stop_evt.set()
                try:
                    with log_lock:
                        final_text = (
                            f"🚫 <b>RATE LIMIT REACHED!</b>\n\n"
                            f"UD {ud_num}: Grok sudah mencapai batas generate.\n"
                            f"Pesan: <i>Rate limit reached — Upgrade to SuperGrok Heavy</i>\n\n"
                            f"Generate <b>dihentikan otomatis</b>.\n"
                            f"Stok saat ini: <b>{count_stok(ud_num)}</b>")
                    asyncio.run_coroutine_threadsafe(
                        bot.edit_message_text(final_text, chat_id=chat_id, message_id=msg_id,
                                              parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                        main_loop)
                except: pass
                active_gen_task.pop(uid, None)
                return
            except Exception as e:
                lg(f"Error {type(e).__name__}: {str(e)[:40]}")
            finally:
                stop_evt.set()
                try:
                    with log_lock:
                        final_text = f"<b>Generate UD {ud_num} Selesai!</b> Stok: {count_stok(ud_num)}\n" + "\n".join(log_lines[-7:])
                    asyncio.run_coroutine_threadsafe(
                        bot.edit_message_text(final_text, chat_id=chat_id, message_id=msg_id, 
                                              parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                        main_loop
                    )
                except: pass
                active_gen_task.pop(uid, None)
            
        t = threading.Thread(target=_gen, daemon=True); t.start()
        active_gen_task[uid] = {"stop": stop_evt, "thread": t}
        return

    # ── UPLOAD NOW (per UD) ──
    if data.startswith("upload_ud_"):
        ud_num = int(data.split("_")[-1])
        if active_upload_task.get(uid):
            await q.edit_message_text("Upload sudah berjalan!", reply_markup=main_menu_kb(uid)); return
        db = load_db()
        cfg = get_ud_config(db, ud_num)
        stok_files = list_stok(ud_num)[:cfg.get("batch_size", 30)]
        if not stok_files:
            await q.edit_message_text(f"Stok UD {ud_num} kosong!", reply_markup=main_menu_kb(uid)); return

        tiktok_ud = cfg.get("tiktok_ud", "")
        tiktok_port = cfg.get("tiktok_port", "")
        if not tiktok_ud or not tiktok_port:
            await q.edit_message_text(
                f"UD {ud_num}: TikTok UD/Port belum diset!\n"
                f"Gunakan:\n<code>/set tiktok_ud {ud_num} PATH</code>\n<code>/set tiktok_port {ud_num} PORT</code>",
                parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

        stop_evt = threading.Event()
        interval_hours = cfg.get("interval_hours", 5)
        start_dt = datetime.now() + timedelta(minutes=60)
        start_dt = start_dt.replace(second=0, microsecond=0)
        schedule = build_tiktok_schedule(stok_files, start_dt, interval_hours)
        save_ud_schedule(ud_num, schedule)

        sched_preview = "\n".join(f"  {i+1}. <code>{s['schedule']}</code>" for i, s in enumerate(schedule[:15]))
        if len(schedule) > 15:
            sched_preview += f"\n  ... +{len(schedule)-15} lagi"

        initial_msg = await q.edit_message_text(
            f"<b>📤 Upload UD {ud_num}</b>\n"
            f"Total: {len(schedule)} video, interval {interval_hours}h\n\n"
            f"<b>Jadwal:</b>\n{sched_preview}\n\n"
            f"⏳ Memulai upload...",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        upload_msg_id = initial_msg.message_id

        log_lines_uud = []; log_lock_uud = threading.Lock()
        upload_stats_uud = {"success": 0, "fail": 0, "current": 0, "total": len(schedule)}

        def _uud_log_updater():
            last_text = ""
            while not stop_evt.is_set():
                time.sleep(4.0)
                with log_lock_uud:
                    if not log_lines_uud: continue
                    st = upload_stats_uud
                    header = (
                        f"<b>📤 [UD {ud_num}] Upload TikTok</b>\n"
                        f"Video: <b>{st['current']}/{st['total']}</b>\n"
                        f"✅ Berhasil: <b>{st['success']}</b> | ❌ Gagal: <b>{st['fail']}</b>\n\n"
                        f"<b>Jadwal:</b>\n{sched_preview}\n\n"
                        f"<b>Progress:</b>\n")
                    text = header + "\n".join(log_lines_uud[-10:])
                if len(text) > 4096:
                    text = text[:4090] + "\n..."
                if text != last_text:
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            bot.edit_message_text(text, chat_id=chat_id, message_id=upload_msg_id,
                                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                            main_loop)
                        future.result(timeout=5)
                        last_text = text
                    except: pass
        threading.Thread(target=_uud_log_updater, daemon=True).start()

        def _upload_ud():
            import html as _html
            def lg(m):
                s = _html.escape(str(m))
                with log_lock_uud:
                    log_lines_uud.append(f"<code>[{datetime.now().strftime('%H:%M:%S')}]</code> {s}")
                    if len(log_lines_uud) > 20: log_lines_uud.pop(0)
                    if '✅ Upload sukses' in m or '✅' in m and 'sukses' in m:
                        upload_stats_uud["success"] += 1
                    if 'Upload:' in m or ('Upload' in m and '/' in m):
                        import re as _re
                        match = _re.search(r'\[(\d+)/\d+\]', m)
                        if match:
                            upload_stats_uud["current"] = int(match.group(1))
            try:
                cfg["tiktok_ud"] = os.path.join(APP_DIR, "user_data", str(ud_num))
                uploaded = upload_tiktok_batch(ud_num, schedule, cfg, lg, stop_evt)
                upload_stats_uud["success"] = uploaded
                upload_stats_uud["fail"] = upload_stats_uud["total"] - uploaded
            except Exception as e:
                lg(f"Error: {type(e).__name__}: {str(e)[:40]}")
                uploaded = upload_stats_uud["success"]
            finally:
                stop_evt.set()
                try:
                    with log_lock_uud:
                        st = upload_stats_uud
                        final_text = (
                            f"<b>📤 Upload UD {ud_num} Selesai!</b>\n\n"
                            f"Video: <b>{st['total']}</b>\n"
                            f"✅ Berhasil: <b>{st['success']}</b>\n"
                            f"❌ Gagal: <b>{st['fail']}</b>\n"
                            f"Sisa stok: <b>{count_stok(ud_num)}</b>\n\n" +
                            "\n".join(log_lines_uud[-7:])
                        )
                    asyncio.run_coroutine_threadsafe(
                        bot.edit_message_text(final_text, chat_id=chat_id, message_id=upload_msg_id,
                                              parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                        main_loop)
                except: pass
                active_upload_task.pop(uid, None)

        t = threading.Thread(target=_upload_ud, daemon=True); t.start()
        active_upload_task[uid] = {"stop": stop_evt, "thread": t}
        return

    # ── CLEAR STOK ──
    if data.startswith("clear_stok_"):
        ud_num = int(data.split("_")[-1])
        d = stok_dir(ud_num)
        for f in os.listdir(d):
            fp = os.path.join(d, f)
            if f.endswith(".mp4"):
                try: os.remove(fp)
                except: pass
        await q.edit_message_text(f"Stok UD {ud_num} dikosongkan!", reply_markup=main_menu_kb(uid)); return

    # ── SETTINGS MENU ──
    if data == "settings_menu":
        db = load_db()
        prompts = load_prompts()
        folders = list_bahan_folders()
        active = db.get("active_ud", [1, 2])
        text = (
            "<b>Settings</b>\n\n"
            f"Active UD: <b>{', '.join(str(x) for x in active)}</b>\n\n"
            f"<b>🔌 Grok (Multi-Browser):</b>\n"
            f"  Browsers: {N_GROK_BROWSERS} (ports {GROK_PORTS[0]}-{GROK_PORTS[N_GROK_BROWSERS-1]})\n"
            f"  User Data: 1grok, 2grok, 3grok, 4grok, 5grok\n"
            f"  Video: {DEFAULT_GEN_MODE} {DEFAULT_RESOLUTION} {DEFAULT_DURATION} {DEFAULT_ASPECT_RATIO}\n\n"
            f"Prompt: {escape_html(', '.join(prompts.keys()) or '(kosong)')}\n"
            f"Bahan: {escape_html(', '.join(folders) or '(kosong)')}\n\n"
            "Gunakan <code>/set</code> untuk mengubah konfigurasi.")
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    # ── STOK SEKARANG (choose UD) ──
    if data == "stok_now_choose":
        if active_gen_task.get(uid):
            await q.edit_message_text("Generate sudah berjalan!", reply_markup=main_menu_kb(uid)); return
        db = load_db()
        active = db.get("active_ud", [1, 2])
        rows = []
        for ud in active:
            cfg = get_ud_config(db, ud)
            stok = count_stok(ud)
            batch = cfg.get('batch_size', 30)
            rows.append([InlineKeyboardButton(
                f"UD {ud} (Stok: {stok}/{batch})",
                callback_data=f"stok_now_{ud}")])
        rows.append([InlineKeyboardButton("Kembali", callback_data="refresh")])
        await q.edit_message_text(
            "<b>🎬 Stok Sekarang</b>\nPilih UD untuk generate stok (Multi-Browser):",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)); return

    if data.startswith("stok_now_"):
        ud_num = int(data.split("_")[-1])
        if active_gen_task.get(uid):
            await q.edit_message_text("Generate sudah berjalan!", reply_markup=main_menu_kb(uid)); return
        db = load_db()
        cfg = get_ud_config(db, ud_num)
        prompt_text = load_prompts().get(cfg.get("prompt_name", ""), "")
        if not prompt_text:
            await q.edit_message_text(f"UD {ud_num}: Prompt belum diset!", reply_markup=main_menu_kb(uid)); return
        if not cfg.get("bahan_folder"):
            await q.edit_message_text(f"UD {ud_num}: Bahan belum diset!", reply_markup=main_menu_kb(uid)); return
            
        merge_leftover_raw(ud_num)
        needed = max(0, cfg.get("batch_size", 30) - count_stok(ud_num))
        
        if needed <= 0:
            await q.edit_message_text(f"Stok UD {ud_num} sudah penuh!", reply_markup=main_menu_kb(uid)); return

        stop_evt = threading.Event()

        initial_msg = await q.edit_message_text(
            f"<b>🎬 Stok Sekarang UD {ud_num}</b>\nTarget: {needed} video\n"
            f"Multi-Browser: {N_GROK_BROWSERS} browser\nMembuka browser...",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        msg_id = initial_msg.message_id

        log_lines = []; log_lock = threading.Lock()

        def _stok_log_updater():
            last_text = ""
            while not stop_evt.is_set():
                time.sleep(4.0)
                with log_lock:
                    if not log_lines: continue
                    text = f"<b>🎬 [UD {ud_num}] Multi-Browser Stok Generate ({needed} video)</b>\n" + "\n".join(log_lines)
                if text != last_text:
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id,
                                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                            main_loop)
                        future.result(timeout=5)
                        last_text = text
                    except: pass
        threading.Thread(target=_stok_log_updater, daemon=True).start()

        def _stok_gen():
            import html as _html
            def lg(msg):
                s = _html.escape(str(msg))
                with log_lock:
                    log_lines.append(f"<code>[{datetime.now().strftime('%H:%M:%S')}]</code> {s}")
                    if len(log_lines) > 20: log_lines.pop(0)
            try:
                generate_stok_multibrowser(
                    ud_num, needed, prompt_text, cfg["bahan_folder"],
                    lg, stop_evt,
                    raw_dir=get_raw_dir(ud_num), merge_func=custom_merge_video_pair)
            except GrokRateLimitError:
                lg("🚫 RATE LIMIT! Grok tidak bisa generate lagi.")
                stop_evt.set()
                try:
                    with log_lock:
                        final_text = (
                            f"🚫 <b>RATE LIMIT REACHED!</b>\n\n"
                            f"UD {ud_num}: Grok sudah mencapai batas generate.\n"
                            f"Pesan: <i>Rate limit reached — Upgrade to SuperGrok Heavy</i>\n\n"
                            f"Generate <b>dihentikan otomatis</b>.\n"
                            f"Stok saat ini: <b>{count_stok(ud_num)}</b>")
                    asyncio.run_coroutine_threadsafe(
                        bot.edit_message_text(final_text, chat_id=chat_id, message_id=msg_id,
                                              parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                        main_loop)
                except: pass
                active_gen_task.pop(uid, None)
                return
            except Exception as e:
                lg(f"Error {type(e).__name__}: {str(e)[:40]}")
            finally:
                stop_evt.set()
                try:
                    with log_lock:
                        final_text = f"<b>🎬 Stok UD {ud_num} Selesai!</b> Stok: {count_stok(ud_num)}\n" + "\n".join(log_lines[-7:])
                    asyncio.run_coroutine_threadsafe(
                        bot.edit_message_text(final_text, chat_id=chat_id, message_id=msg_id,
                                              parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                        main_loop)
                except: pass
                active_gen_task.pop(uid, None)

        t = threading.Thread(target=_stok_gen, daemon=True); t.start()
        active_gen_task[uid] = {"stop": stop_evt, "thread": t}
        return

    if data == "stop_gen":
        task = active_gen_task.get(uid)
        if task: task["stop"].set(); active_gen_task.pop(uid, None)
        await q.edit_message_text("<b>Generate dihentikan.</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    # ── UPLOAD TIKTOK SEKARANG (choose UD) ──
    if data == "upload_now_choose":
        if active_upload_task.get(uid):
            await q.edit_message_text("Upload sudah berjalan!", reply_markup=main_menu_kb(uid)); return
        db = load_db()
        active = db.get("active_ud", [1, 2])
        rows = []
        for ud in active:
            stok = count_stok(ud)
            rows.append([InlineKeyboardButton(
                f"UD {ud} (Stok: {stok} video)",
                callback_data=f"upload_now_{ud}")])
        rows.append([InlineKeyboardButton("Kembali", callback_data="refresh")])
        await q.edit_message_text(
            "<b>📤 Upload TikTok Sekarang</b>\nPilih UD untuk upload stok:",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)); return

    if data.startswith("upload_now_"):
        ud_num = int(data.split("_")[-1])
        if active_upload_task.get(uid):
            await q.edit_message_text("Upload sudah berjalan!", reply_markup=main_menu_kb(uid)); return
        db = load_db()
        cfg = get_ud_config(db, ud_num)
        stok_files = list_stok(ud_num)[:cfg.get("batch_size", 30)]
        if not stok_files:
            await q.edit_message_text(f"Stok UD {ud_num} kosong! Generate dulu.", reply_markup=main_menu_kb(uid)); return

        tiktok_ud = cfg.get("tiktok_ud", "")
        tiktok_port = cfg.get("tiktok_port", "")
        if not tiktok_ud or not tiktok_port:
            await q.edit_message_text(
                f"UD {ud_num}: TikTok UD/Port belum diset!\n"
                f"Gunakan:\n<code>/set {ud_num} tiktok_ud PATH</code>\n<code>/set {ud_num} tiktok_port PORT</code>",
                parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

        stop_evt = threading.Event()
        interval_hours = cfg.get("interval_hours", 5)

        start_dt = datetime.now() + timedelta(minutes=30)
        start_dt = start_dt.replace(second=0, microsecond=0)
        schedule = build_tiktok_schedule(stok_files, start_dt, interval_hours)
        save_ud_schedule(ud_num, schedule)

        sched_preview = "\n".join(f"  {i+1}. <code>{s['schedule']}</code>" for i, s in enumerate(schedule[:15]))
        if len(schedule) > 15:
            sched_preview += f"\n  ... +{len(schedule)-15} lagi"

        initial_msg = await q.edit_message_text(
            f"<b>📤 Upload UD {ud_num} Sekarang!</b>\n"
            f"Total: {len(schedule)} video, interval {interval_hours}h\n"
            f"Mulai: <code>{start_dt.strftime('%H:%M')}</code>\n\n"
            f"<b>Jadwal:</b>\n{sched_preview}\n\n"
            f"⏳ Memulai upload...",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        upload_msg_id = initial_msg.message_id

        log_lines_ul = []; log_lock_ul = threading.Lock()
        upload_stats_ul = {"success": 0, "fail": 0, "current": 0, "total": len(schedule)}

        def _upload_log_updater():
            last_text = ""
            while not stop_evt.is_set():
                time.sleep(4.0)
                with log_lock_ul:
                    if not log_lines_ul: continue
                    st = upload_stats_ul
                    header = (
                        f"<b>📤 [UD {ud_num}] Upload TikTok</b>\n"
                        f"Video: <b>{st['current']}/{st['total']}</b>\n"
                        f"✅ Berhasil: <b>{st['success']}</b> | ❌ Gagal: <b>{st['fail']}</b>\n\n"
                        f"<b>Jadwal:</b>\n{sched_preview}\n\n"
                        f"<b>Progress:</b>\n")
                    text = header + "\n".join(log_lines_ul[-10:])
                if len(text) > 4096:
                    text = text[:4090] + "\n..."
                if text != last_text:
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            bot.edit_message_text(text, chat_id=chat_id, message_id=upload_msg_id,
                                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                            main_loop)
                        future.result(timeout=5)
                        last_text = text
                    except: pass
        threading.Thread(target=_upload_log_updater, daemon=True).start()

        def _upload_now():
            import html as _html
            def lg(m):
                s = _html.escape(str(m))
                with log_lock_ul:
                    log_lines_ul.append(f"<code>[{datetime.now().strftime('%H:%M:%S')}]</code> {s}")
                    if len(log_lines_ul) > 20: log_lines_ul.pop(0)
                    if '✅ Upload sukses' in m or ('✅' in m and 'sukses' in m):
                        upload_stats_ul["success"] += 1
                    if 'Upload:' in m or ('Upload' in m and '/' in m):
                        import re as _re
                        match = _re.search(r'\[(\d+)/\d+\]', m)
                        if match:
                            upload_stats_ul["current"] = int(match.group(1))
            try:
                cfg["tiktok_ud"] = os.path.join(APP_DIR, "user_data", str(ud_num))
                uploaded = upload_tiktok_batch(ud_num, schedule, cfg, lg, stop_evt)
                upload_stats_ul["success"] = uploaded
                upload_stats_ul["fail"] = upload_stats_ul["total"] - uploaded
            except Exception as e:
                lg(f"Error: {type(e).__name__}: {str(e)[:40]}")
            finally:
                stop_evt.set()
                try:
                    with log_lock_ul:
                        st = upload_stats_ul
                        final_text = (
                            f"<b>📤 Upload UD {ud_num} Selesai!</b>\n\n"
                            f"Video: <b>{st['total']}</b>\n"
                            f"✅ Berhasil: <b>{st['success']}</b>\n"
                            f"❌ Gagal: <b>{st['fail']}</b>\n"
                            f"Sisa stok: <b>{count_stok(ud_num)}</b>\n\n" +
                            "\n".join(log_lines_ul[-7:])
                        )
                    asyncio.run_coroutine_threadsafe(
                        bot.edit_message_text(final_text, chat_id=chat_id, message_id=upload_msg_id,
                                              parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                        main_loop)
                except: pass
                active_upload_task.pop(uid, None)

        t = threading.Thread(target=_upload_now, daemon=True); t.start()
        active_upload_task[uid] = {"stop": stop_evt, "thread": t}
        return

    if data == "stop_upload":
        task = active_upload_task.get(uid)
        if task: task["stop"].set(); active_upload_task.pop(uid, None)
        await q.edit_message_text("<b>Upload dihentikan.</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    # ── MUTE + MP3 (choose UD) ──
    if data == "mp3_choose":
        if active_mp3_task.get(uid):
            await q.edit_message_text("Proses Mute+MP3 sudah berjalan!", reply_markup=main_menu_kb(uid)); return
        db = load_db()
        active = db.get("active_ud", [1, 2])
        mp3_count = len([f for f in os.listdir(MP3_DIR) if f.lower().endswith('.mp3')]) if os.path.isdir(MP3_DIR) else 0
        rows = []
        for ud in active:
            stok = count_stok(ud)
            rows.append([InlineKeyboardButton(
                f"UD {ud} (Stok: {stok} video)",
                callback_data=f"mp3_ud_{ud}")])
        rows.append([InlineKeyboardButton("Kembali", callback_data="refresh")])
        await q.edit_message_text(
            f"<b>🎵 Mute + Add MP3</b>\n"
            f"Sumber MP3: <code>brutal_mp3/</code> ({mp3_count} file)\n\n"
            f"Pilih UD untuk mute & replace audio seluruh stok:",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)); return

    if data.startswith("mp3_ud_"):
        ud_num = int(data.split("_")[-1])
        if active_mp3_task.get(uid):
            await q.edit_message_text("Proses Mute+MP3 sudah berjalan!", reply_markup=main_menu_kb(uid)); return
        stok_files = list_stok(ud_num)
        if not stok_files:
            await q.edit_message_text(f"Stok UD {ud_num} kosong!", reply_markup=main_menu_kb(uid)); return

        mp3_test = get_random_mp3()
        mp3_count = len([f for f in os.listdir(MP3_DIR) if f.lower().endswith('.mp3')]) if os.path.isdir(MP3_DIR) else 0
        if mp3_test:
            mp3_info = f"Sumber: <code>brutal_mp3/</code> ({mp3_count} file)"
        else:
            mp3_info = "⚠️ Tidak ada MP3 di <code>brutal_mp3/</code>, video hanya dimute"

        stop_evt = threading.Event()
        initial_msg = await q.edit_message_text(
            f"<b>🎵 Mute+MP3 UD {ud_num}</b>\n"
            f"Total: {len(stok_files)} video\n"
            f"{mp3_info}\n\n⏳ Memulai proses...",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        msg_id = initial_msg.message_id

        log_lines_mp3 = []; log_lock_mp3 = threading.Lock()

        def _mp3_log_updater():
            last_text = ""
            while not stop_evt.is_set():
                time.sleep(3.0)
                with log_lock_mp3:
                    if not log_lines_mp3: continue
                    text = f"<b>🎵 [UD {ud_num}] Mute+MP3</b>\n" + "\n".join(log_lines_mp3[-15:])
                if text != last_text:
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id,
                                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                            main_loop)
                        future.result(timeout=5)
                        last_text = text
                    except: pass
        threading.Thread(target=_mp3_log_updater, daemon=True).start()

        def _mp3_process():
            import html as _html
            success = 0; fail = 0; total = len(stok_files)
            def lg(m):
                s = _html.escape(str(m))
                with log_lock_mp3:
                    log_lines_mp3.append(f"<code>[{datetime.now().strftime('%H:%M:%S')}]</code> {s}")
                    if len(log_lines_mp3) > 25: log_lines_mp3.pop(0)
            try:
                for idx, vpath in enumerate(stok_files):
                    if stop_evt.is_set():
                        lg("⏹ Dihentikan oleh user.")
                        break
                    fname = os.path.basename(vpath)
                    lg(f"[{idx+1}/{total}] 🎬 {fname[:45]}")
                    ok = _mute_and_add_mp3(vpath, log_fn=lg)
                    if ok:
                        success += 1
                    else:
                        fail += 1
            except Exception as e:
                lg(f"❌ Error: {type(e).__name__}: {str(e)[:60]}")
            finally:
                stop_evt.set()
                try:
                    with log_lock_mp3:
                        final_text = (
                            f"<b>🎵 Mute+MP3 UD {ud_num} Selesai!</b>\n"
                            f"✅ Sukses: {success}/{total}\n"
                            f"❌ Gagal: {fail}/{total}\n\n" +
                            "\n".join(log_lines_mp3[-7:])
                        )
                    asyncio.run_coroutine_threadsafe(
                        bot.edit_message_text(final_text, chat_id=chat_id, message_id=msg_id,
                                              parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)),
                        main_loop)
                except: pass
                active_mp3_task.pop(uid, None)

        t = threading.Thread(target=_mp3_process, daemon=True); t.start()
        active_mp3_task[uid] = {"stop": stop_evt, "thread": t}
        return

    if data == "stop_mp3":
        task = active_mp3_task.get(uid)
        if task: task["stop"].set(); active_mp3_task.pop(uid, None)
        await q.edit_message_text("<b>Mute+MP3 dihentikan.</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    # ── FULL AUTO ──
    if data == "start_auto":
        if full_auto_task.get(uid):
            await q.edit_message_text("Full Auto sudah berjalan!", reply_markup=main_menu_kb(uid)); return
        stop_evt = threading.Event()
        t = threading.Thread(target=run_full_auto, args=(uid, chat_id, bot, main_loop, stop_evt), daemon=True)
        full_auto_task[uid] = {"stop": stop_evt, "thread": t}; t.start()
        await q.edit_message_text("<b>Full Auto aktif!</b>\nTekan Stop Auto untuk menghentikan.",
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

    if data == "stop_auto":
        t = full_auto_task.get(uid)
        if t: t["stop"].set(); full_auto_task.pop(uid, None)
        t2 = active_gen_task.get(uid)
        if t2: t2["stop"].set(); active_gen_task.pop(uid, None)
        t3 = active_upload_task.get(uid)
        if t3: t3["stop"].set(); active_upload_task.pop(uid, None)
        await q.edit_message_text("<b>Full Auto dihentikan.</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

# ═══════════════════════════════════════════════════════════════
#  TEXT & PHOTO HANDLERS
# ═══════════════════════════════════════════════════════════════
async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    uid = update.effective_user.id
    if not is_allowed(uid): return
    waiting = ctx.user_data.get("waiting_for", "")
    text = update.message.text.strip()

    if waiting == "bahan_new_folder":
        safe = re.sub(r'[^\w\-]', '_', text)
        os.makedirs(os.path.join(BAHAN_DIR, safe), exist_ok=True)
        ctx.user_data["waiting_for"] = ""
        await update.message.reply_text(f"Folder <code>{escape_html(safe)}</code> dibuat!\nKirim foto untuk menambah gambar.",
                                         parse_mode=ParseMode.HTML)
        ctx.user_data["waiting_for"] = f"bahan_photo|{safe}"
        return

    if waiting == "prompt_name":
        ctx.user_data["new_prompt_name"] = text
        ctx.user_data["waiting_for"] = "prompt_text"
        await update.message.reply_text(f"Nama: <code>{escape_html(text)}</code>\nSekarang kirim <b>teks prompt</b>:",
                                         parse_mode=ParseMode.HTML)
        return

    if waiting == "prompt_text":
        name = ctx.user_data.get("new_prompt_name", "unnamed")
        prompts = load_prompts()
        prompts[name] = text
        save_prompts(prompts)
        ctx.user_data["waiting_for"] = ""
        await update.message.reply_text(f"Prompt <code>{escape_html(name)}</code> disimpan!", parse_mode=ParseMode.HTML)
        return

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo: return
    uid = update.effective_user.id
    if not is_allowed(uid): return
    waiting = ctx.user_data.get("waiting_for", "")
    if not waiting.startswith("bahan_photo|"): return
    folder = waiting.split("|", 1)[1]
    folder_path = os.path.join(BAHAN_DIR, folder)
    os.makedirs(folder_path, exist_ok=True)
    photo = update.message.photo[-1]
    file = await photo.get_file()
    filename = f"img_{int(datetime.now().timestamp())}_{random.randint(100,999)}.jpg"
    filepath = os.path.join(folder_path, filename)
    await file.download_to_drive(filepath)
    count = len(list_bahan_images(folder))
    await update.message.reply_text(f"Gambar disimpan ke <code>{escape_html(folder)}</code> ({count} gambar)",
                                     parse_mode=ParseMode.HTML)

# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Menu utama"),
        BotCommand("set", "Konfigurasi"),
        BotCommand("produk_radio", "Kelola produk radio"),
        BotCommand("help", "Panduan"),
        BotCommand("stop", "Stop proses"),
    ])

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Set BOT_TOKEN dulu di grok_tiktok_bot.py!")
        return
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(CommandHandler("produk_radio", cmd_produk_radio))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Grok TikTok Bot (Multi-Browser) is running...")
    print(f"  Browsers: {N_GROK_BROWSERS} (ports {GROK_PORTS[0]}-{GROK_PORTS[N_GROK_BROWSERS-1]})")
    print(f"  User Data: 1grok, 2grok, 3grok, 4grok, 5grok")
    print(f"  Video: {DEFAULT_GEN_MODE} {DEFAULT_RESOLUTION} {DEFAULT_DURATION} {DEFAULT_ASPECT_RATIO}")
    app.run_polling()

if __name__ == "__main__":
    main()
