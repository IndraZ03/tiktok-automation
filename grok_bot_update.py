import sys, re

new_loop = '''def _generation_loop(uid, chat_id, bot, main_loop, folder_name, count, prompt_name, stop_event):
    import asyncio, os, time, threading
    from telegram.constants import ParseMode
    import gtt_core

    def send(text):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id, text, parse_mode=ParseMode.HTML), main_loop)

    def send_video_tg(path):
        async def _send():
            try:
                with open(path, 'rb') as vf:
                    await bot.send_video(chat_id, video=vf,
                                         caption=f"?? Video dari folder <b>{escape_html(folder_name)}</b>",
                                         parse_mode=ParseMode.HTML,
                                         supports_streaming=True)
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
            except Exception:
                pass
        asyncio.run_coroutine_threadsafe(_send(), main_loop)

    prompts = load_prompts()
    prompt_text = prompts.get(prompt_name)
    if not prompt_text:
        send(f"? Prompt <code>{escape_html(prompt_name)}</code> tidak ditemukan!")
        active_gen_tasks.pop(uid, None)
        return

    images = list_bahan_images(folder_name)
    if not images:
        send(f"? Folder <code>{escape_html(folder_name)}</code> kosong atau tidak ada!")
        active_gen_tasks.pop(uid, None)
        return

    infinite = (count == 0)
    target = "8" if infinite else str(count)
    merge_dur = bot_settings.get("merge_duration", 20)
    merge_enabled = (merge_dur == 20)
    merge_buffer = []

    merge_mode_str = "?? Mode: <b>Gabung 2 video (20 dtk)</b>" if merge_enabled else "?? Mode: <b>Tanpa gabung (10 dtk)</b>"
    send(
        f"?? <b>Generasi dimulai! (grok_auto.js mode)</b>\\n\\n"
        f"?? Folder: <code>{escape_html(folder_name)}</code> ({len(images)} gambar)\\n"
        f"?? Prompt: <code>{escape_html(prompt_name)}</code>\\n"
        f"?? Target: <b>{target}</b> video raw\\n"
        f"{merge_mode_str}\\n\\n"
        f"Gunakan /stop untuk menghentikan."
    )

    generated = 0
    failed = 0
    merged_count = 0

    ud = bot_settings.get("user_data_dir", DEFAULT_USER_DATA)
    pt = bot_settings.get("port", DEFAULT_PORT)

    log_lines = []
    log_lock = threading.Lock()
    log_done = threading.Event()

    def log_fn(msg, tag=None):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        icon = {"success": "?", "error": "?", "warn": "??", "info": "??"}.get(tag, "??")
        with log_lock:
            log_lines.append(f"<code>[{ts}]</code> {icon} {msg}")

    log_msg_future = asyncio.run_coroutine_threadsafe(
        bot.send_message(chat_id,
                         f"?? <b>Live Log</b>\\n\\n<i>Memulai Chrome...</i>",
                         parse_mode=ParseMode.HTML), main_loop)
    try:
        log_msg = log_msg_future.result(timeout=10)
        log_msg_id = log_msg.message_id
    except:
        log_msg_id = None

    async def _live_log_updater():
        last_text = ""
        while not log_done.is_set():
            with log_lock:
                body = "\\n".join(log_lines[-20:]) if log_lines else "<i>Menunggu...</i>"
            text = f"?? <b>Live Log</b>\\n? {generated}/{target} | ? {failed}\\n\\n{body}"
            if text != last_text and log_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=log_msg_id,
                        text=text[:4096], parse_mode=ParseMode.HTML)
                    last_text = text
                except: pass
            await asyncio.sleep(2)
        with log_lock:
            body = "\\n".join(log_lines[-25:]) if log_lines else ""
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=log_msg_id,
                text=f"?? <b>Senyap Log Selesai</b>\\n? {generated}/{target} | ? {failed}\\n\\n{body}"[:4096],
                parse_mode=ParseMode.HTML)
        except: pass

    log_task = asyncio.run_coroutine_threadsafe(_live_log_updater(), main_loop)

    chrome_proc, driver = gtt_core._start_chrome_session(ud, pt, log_fn, "Imagine", raw_dir=OUTPUT_DIR)
    
    if not driver:
        log_done.set()
        send("? Gagal connect Chrome!")
        active_gen_tasks.pop(uid, None)
        return

    try:
        while not stop_event.is_set():
            if not infinite and generated >= count:
                break
            
            remaining = 10 if infinite else min(10, count - generated)
            if remaining <= 0: break
            
            batch_size = remaining
            log_fn(f"--- Batch: {batch_size} tab (sisa {remaining if not infinite else '8'}) ---")
            
            new_raw = gtt_core._run_mini_batch(driver, batch_size, folder_name, prompt_text, log_fn, stop_event, "Imagine", raw_dir=OUTPUT_DIR)
            
            if not new_raw:
                failed += batch_size
                time.sleep(5)
                continue
            
            for video_path in new_raw:
                generated += 1
                sz = os.path.getsize(video_path) / (1024*1024)
                log_fn(f"?? {sz:.1f} MB ({generated}/{target})")

                if merge_enabled:
                    merge_buffer.append(video_path)
                    if len(merge_buffer) >= 2:
                        vid_a = merge_buffer.pop(0)
                        vid_b = merge_buffer.pop(0)
                        merged_path = merge_video_pair(vid_a, vid_b, MERGED_DIR, log_fn)
                        if merged_path:
                            merged_count += 1
                            send_video_tg(merged_path)
                            for _vp in (vid_a, vid_b):
                                try:
                                    if os.path.exists(_vp): os.remove(_vp)
                                except: pass
                            log_fn(f"?? Merged #{merged_count} dikirim", "success")
                        else:
                            log_fn("?? Merge gagal, kirim video terpisah", "warn")
                            send_video_tg(vid_a)
                            send_video_tg(vid_b)
                else:
                    send_video_tg(video_path)
    finally:
        log_done.set()
        time.sleep(2)
        gtt_core._stop_chrome_session(chrome_proc, driver, log_fn, "Imagine")

    if merge_enabled and merge_buffer:
        send(f"?? Sisa {len(merge_buffer)} video di buffer, dikirim tanpa merge")
        for vp in merge_buffer:
            if os.path.exists(vp):
                send_video_tg(vp)
        merge_buffer.clear()

    merge_info = f"\\n?? Merged: <b>{merged_count}</b> video" if merge_enabled else ""
    send(
        f"?? <b>Generasi selesai!</b>\\n\\n"
        f"? Berhasil: <b>{generated}</b>\\n"
        f"? Gagal: <b>{failed}</b>{merge_info}\\n"
        f"?? Folder: <code>{escape_html(folder_name)}</code>"
    )
    active_gen_tasks.pop(uid, None)

'''

files = [r'c:\tiktok_automation\grok_imagine_bot.py', r'c:\tiktok_automation\grok_imagine_bot_a.py']
for fp in files:
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()

    start_idx = content.find('def _generation_loop')
    end_idx = content.find('def main_menu_kb')
    if start_idx == -1 or end_idx == -1:
        print(f"Failed to find markers in {fp}")
        continue
    
    # Prepend the new loop, replace everything up to end_idx
    new_content = content[:start_idx] + new_loop + "\n\n# ---------------------------------------------------------------\n#  TELEGRAM HANDLERS\n# ---------------------------------------------------------------\n" + content[end_idx:]
    
    # Remove generate_one_video_grok, setup_tab_grok, check_tab_progress, download_tab_video
    # safely by regex or finding markers!
    # Or just leave them (they won't hurt, but removing them cleans code).
    # Since the request is just "buat agar automasinya menggunakan grok_auto.js", replacing _generation_loop is enough!
    
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Updated {fp}")

