"""
Grok TikTok Bot — Per-UD Grok 20s Video Generation + TikTok Schedule Upload
Setiap UD punya: prompt, bahan, stok, hashtag, produk, sound, deskripsi, interval, schedule
"""
import os, sys, re, time, asyncio, json, threading, random, logging
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
    escape_html, generate_stok_for_ud, build_tiktok_schedule, upload_tiktok_batch,
    resolve_ud_path,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = "8522516359:AAGrXXryDQVv5kC4twE28mcIOlVlSfSWqv0"
ALLOWED_USER_IDS = []

# ═══════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════
full_auto_task = {}   # uid -> {stop, thread}
active_gen_task = {}  # uid -> {stop, thread}

def is_allowed(uid):
    return not ALLOWED_USER_IDS or uid in ALLOWED_USER_IDS

# ═══════════════════════════════════════════════════════════════
#  FULL AUTO DAEMON
# ═══════════════════════════════════════════════════════════════
def run_full_auto(uid, chat_id, bot, main_loop, stop_event):
    def send(text):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    db = load_db()
    active = db.get("active_ud", [1, 2])
    send(f"<b>Full Auto dimulai!</b>\nActive UD: <b>{', '.join(str(x) for x in active)}</b>\n"
         f"Logika: Tunggu jadwal UD terdekat -> generate -> upload batch")

    while not stop_event.is_set():
        db = load_db()
        active = db.get("active_ud", [1, 2])
        grok_ud = db.get("grok_ud", os.path.join(USER_DATA_BASE, "gtt_grok"))
        grok_port = db.get("grok_port", "9270")

        # Kumpulkan kandidat UD
        candidates = []
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
            candidates.append((trigger_dt, ud_num))

        if not candidates:
            if not stop_event.is_set():
                send("Semua UD belum dikonfigurasi (prompt/bahan kosong). Menunggu 60 detik...")
                for _ in range(12):
                    if stop_event.is_set(): break
                    time.sleep(5)
            continue

        candidates.sort(key=lambda x: x[0])
        trigger_dt, ud_num = candidates[0]

        # Tampilkan jadwal
        sched_info = "\n".join(
            f"  {'>' if c[1]==ud_num else ' '} UD {c[1]}: <code>{c[0].strftime('%Y-%m-%d %H:%M')}</code>"
            for c in candidates)
        send(f"<b>Jadwal UD:</b>\n{sched_info}\n\nTerdekat: <b>UD {ud_num}</b>")

        # Tunggu jadwal
        now = datetime.now()
        wait_sec = (trigger_dt - now).total_seconds()
        if wait_sec > 0:
            h = int(wait_sec // 3600); m = int((wait_sec % 3600) // 60)
            send(f"<b>UD {ud_num}</b>: Menunggu jadwal...\n"
                 f"<code>{trigger_dt.strftime('%Y-%m-%d %H:%M')}</code> ({h}j {m}m lagi)")
            elapsed = 0
            while elapsed < wait_sec and not stop_event.is_set():
                time.sleep(min(30, wait_sec - elapsed)); elapsed += 30
            if stop_event.is_set(): break

        # Pipeline: Generate -> Upload
        db = load_db()
        cfg = get_ud_config(db, ud_num)
        prompt_text = load_prompts().get(cfg.get("prompt_name", ""), "")
        if not prompt_text:
            send(f"<b>UD {ud_num}</b>: Prompt tidak ditemukan, skip!")
            continue

        batch_size = cfg.get("batch_size", 30)
        current_stok = count_stok(ud_num)
        needed = max(0, batch_size - current_stok)

        # STEP 1: Generate jika stok kurang
        if needed > 0 and not stop_event.is_set():
            send(f"<b>UD {ud_num} STEP 1:</b> Generate {needed} video (stok: {current_stok}/{batch_size})")
            log_lines = []; log_lock = threading.Lock()
            def log_fn(msg):
                with log_lock:
                    log_lines.append(f"<code>[{datetime.now().strftime('%H:%M:%S')}]</code> {msg}")
                    if len(log_lines) > 30: log_lines.pop(0)

            generate_stok_for_ud(ud_num, needed, prompt_text, cfg["bahan_folder"],
                                 grok_ud, grok_port, log_fn, stop_event)
            send(f"<b>UD {ud_num}:</b> Generate selesai! Stok: {count_stok(ud_num)}")

        if stop_event.is_set(): break

        # STEP 2: Build schedule & upload
        stok_files = list_stok(ud_num)[:batch_size]
        if not stok_files:
            send(f"<b>UD {ud_num}:</b> Stok kosong, skip upload!")
            continue

        interval_hours = cfg.get("interval_hours", 5)
        # Schedule mulai dari sekarang + 60 menit (agar TikTok bisa schedule)
        start_dt = datetime.now() + timedelta(minutes=60)
        start_dt = start_dt.replace(second=0, microsecond=0)
        # Bulatkan ke 5 menit
        rounded = ((start_dt.minute + 4) // 5) * 5
        if rounded >= 60:
            start_dt = start_dt.replace(minute=0) + timedelta(hours=1)
        else:
            start_dt = start_dt.replace(minute=rounded)

        schedule = build_tiktok_schedule(stok_files, start_dt, interval_hours)
        save_ud_schedule(ud_num, schedule)

        preview = "\n".join(f"  {i+1}. <code>{s['schedule']}</code>" for i, s in enumerate(schedule))
        full_text = f"<b>UD {ud_num} STEP 2:</b> Upload {len(schedule)} video\nInterval: {interval_hours}h\n\n{preview}"
        # Split jika terlalu panjang
        if len(full_text) <= 4096:
            send(full_text)
        else:
            send(full_text[:4096])
            for cs in range(4096, len(full_text), 4096):
                send(full_text[cs:cs+4096])

        log_lines2 = []; log_lock2 = threading.Lock()
        def log_fn2(msg):
            with log_lock2:
                log_lines2.append(msg)

        uploaded = upload_tiktok_batch(ud_num, schedule, cfg, log_fn2, stop_event)
        send(f"<b>UD {ud_num}:</b> Upload selesai! {uploaded}/{len(schedule)}")

        # STEP 3: Update schedule untuk pipeline berikutnya
        if uploaded > 0:
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

        if not stop_event.is_set():
            time.sleep(10)

    full_auto_task.pop(uid, None)
    send("<b>Full Auto dihentikan.</b>")

# ═══════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════
def main_menu_kb(uid=None):
    is_auto = bool(uid and full_auto_task.get(uid))
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

    rows.append([InlineKeyboardButton("Settings", callback_data="settings_menu")])
    rows.append([InlineKeyboardButton(
        "Stop Auto" if is_auto else "Full Auto",
        callback_data="stop_auto" if is_auto else "start_auto")])
    rows.append([InlineKeyboardButton("Refresh", callback_data="refresh")])
    return InlineKeyboardMarkup(rows)

def status_text():
    db = load_db()
    active = db.get("active_ud", [1, 2])
    lines = ["<b>Grok TikTok Bot</b>\n"]
    lines.append(f"Active UD: <b>{', '.join(str(x) for x in active)}</b>\n")
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
            "<code>/set produk_radio 1 NAMA</code> - Nama produk radio\n"
            "<code>/set produk_input 1 JUDUL</code> - Judul produk\n"
            "<code>/set sound 1 on/off</code> - Toggle sound favorites\n"
            "<code>/set interval 1 5</code> - Interval (jam)\n"
            "<code>/set batch 1 30</code> - Batch size\n"
            "<code>/set sched 1 2026-03-16 02:00</code> - Schedule\n"
            "<code>/set tiktok_ud 1 2</code> - TikTok user_data UD 1 = user_data/2\n"
            "<code>/set tiktok_port 1 9223</code> - TikTok port\n"
            "<code>/set grok_ud gtt_grok</code> - Grok user_data\n"
            "<code>/set grok_port 9270</code> - Grok port",
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
    if sub == "grok_ud":
        full_path = resolve_ud_path(val)
        db["grok_ud"] = full_path; save_db(db)
        await update.message.reply_text(f"Grok UD: <code>{escape_html(full_path)}</code>", parse_mode=ParseMode.HTML); return
    if sub == "grok_port":
        db["grok_port"] = val; save_db(db)
        await update.message.reply_text(f"Grok Port: <code>{val}</code>", parse_mode=ParseMode.HTML); return

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
        cfg["nama_produk_radio"] = ud_val
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
        "<b>Grok TikTok Bot</b>\n\n"
        "/start - Menu utama\n"
        "/set - Konfigurasi (lihat daftar)\n"
        "/help - Panduan\n"
        "/stop - Stop auto/generate\n\n"
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
        import shutil
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
            f"  Radio: <code>{escape_html(cfg.get('nama_produk_radio','(kosong)')[:40])}</code>\n"
            f"  Input: <code>{escape_html(cfg.get('nama_produk_input','(kosong)')[:40])}</code>\n"
            f"<b>Sound:</b> {'ON' if cfg.get('add_sound') else 'OFF'}\n"
            f"\nTikTok UD: <code>{escape_html(cfg.get('tiktok_ud',''))}</code>\n"
            f"TikTok Port: <code>{cfg.get('tiktok_port','')}</code>")
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
        needed = max(0, cfg.get("batch_size", 30) - count_stok(ud_num))
        if needed <= 0:
            await q.edit_message_text(f"Stok UD {ud_num} sudah penuh!", reply_markup=main_menu_kb(uid)); return

        stop_evt = threading.Event()
        grok_ud = db.get("grok_ud", os.path.join(USER_DATA_BASE, "gtt_grok"))
        grok_port = db.get("grok_port", "9270")
        
        initial_msg = await q.edit_message_text(f"Generate UD {ud_num} dimulai! Target: {needed} video\nMembuka browser...", reply_markup=main_menu_kb(uid))
        msg_id = initial_msg.message_id
        
        log_lines = []
        log_lock = threading.Lock()
        
        async def _log_updater():
            last_text = ""
            while not stop_evt.is_set():
                await asyncio.sleep(4.0)
                with log_lock:
                    if not log_lines: continue
                    text = f"<b>[UD {ud_num}] Prog Generate {needed} Stok</b>\n" + "\n".join(log_lines)
                if text != last_text:
                    try:
                        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, 
                                                    parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
                        last_text = text
                    except Exception as e:
                        pass # Ignore flood control or unchanged messages

        asyncio.create_task(_log_updater())
        
        def _gen():
            import html
            def lg(msg):
                s = html.escape(str(msg))
                with log_lock:
                    log_lines.append(f"<code>[{datetime.now().strftime('%H:%M:%S')}]</code> {s}")
                    if len(log_lines) > 20:
                        log_lines.pop(0)
                        
            try:
                generate_stok_for_ud(ud_num, needed, prompt_text, cfg["bahan_folder"],
                                     grok_ud, grok_port, lg, stop_evt)
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
        db = load_db()
        cfg = get_ud_config(db, ud_num)
        stok_files = list_stok(ud_num)[:cfg.get("batch_size", 30)]
        if not stok_files:
            await q.edit_message_text(f"Stok UD {ud_num} kosong!", reply_markup=main_menu_kb(uid)); return
        stop_evt = threading.Event()
        interval_hours = cfg.get("interval_hours", 5)
        start_dt = datetime.now() + timedelta(minutes=60)
        start_dt = start_dt.replace(second=0, microsecond=0)
        schedule = build_tiktok_schedule(stok_files, start_dt, interval_hours)
        save_ud_schedule(ud_num, schedule)
        def _upload():
            def lg(m): pass
            uploaded = upload_tiktok_batch(ud_num, schedule, cfg, lg, stop_evt)
            asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id, f"Upload UD {ud_num} selesai! {uploaded}/{len(schedule)}"), main_loop)
        t = threading.Thread(target=_upload, daemon=True); t.start()
        preview = "\n".join(f"  {i+1}. <code>{s['schedule']}</code>" for i, s in enumerate(schedule))
        full_text = f"<b>Upload UD {ud_num}</b>\n{len(schedule)} video, interval {interval_hours}h\n\n{preview}"
        if len(full_text) <= 4096:
            await q.edit_message_text(full_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid))
        else:
            await q.edit_message_text(full_text[:4096], parse_mode=ParseMode.HTML)
            for cs in range(4096, len(full_text), 4096):
                await bot.send_message(chat_id, full_text[cs:cs+4096], parse_mode=ParseMode.HTML)
        return

    # ── CLEAR STOK ──
    if data.startswith("clear_stok_"):
        import shutil
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
            f"Active UD: <b>{', '.join(str(x) for x in active)}</b>\n"
            f"Grok UD: <code>{escape_html(db.get('grok_ud',''))}</code>\n"
            f"Grok Port: <code>{db.get('grok_port','9270')}</code>\n\n"
            f"Prompt: {escape_html(', '.join(prompts.keys()) or '(kosong)')}\n"
            f"Bahan: {escape_html(', '.join(folders) or '(kosong)')}\n\n"
            "Gunakan <code>/set</code> untuk mengubah konfigurasi.")
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(uid)); return

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
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Grok TikTok Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
