import os
import telebot
from yt_dlp import YoutubeDL
from moviepy.editor import VideoFileClip, ImageClip, TextClip, CompositeVideoClip
import math
from tqdm import tqdm
import time
import threading

# Ganti dengan token bot Telegram kamu (dapat dari BotFather)
BOT_TOKEN = '8577651733:AAG69uuoImXQpe5qcEtMdlwgu3_6rQAvaBI'

# Inisialisasi bot
bot = telebot.TeleBot(BOT_TOKEN)

# Folder penyimpanan
OUTPUT_FOLDER = 'video-yt'
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Path logo watermark (ganti kalau beda)
LOGO_PATH = 'logo.png'  # Pastikan file ini ada!

# Fungsi untuk update progress di Telegram (edit pesan)
def update_progress(message, progress_message_id, text):
    try:
        bot.edit_message_text(chat_id=message.chat.id, message_id=progress_message_id, text=text)
    except Exception as e:
        if "message is not modified" in str(e):  # Hindari error kalau text sama
            pass

# Handler untuk command /download <link>
@bot.message_handler(commands=['download'])
def handle_download_command(message):
    # Ambil link dari pesan setelah command
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Cara pakai: /download <link_youtube>\nContoh: /download https://www.youtube.com/watch?v=...")
        return

    url = args[1].strip()
    if 'youtube.com' not in url and 'youtu.be' not in url:
        bot.reply_to(message, "Link harus dari YouTube!")
        return

    # Kirim pesan awal progress
    progress_msg = bot.reply_to(message, "Mengunduh video: 0%...")
    progress_msg_id = progress_msg.message_id

    try:
        # Variable shared untuk percent download
        current_percent = "0"
        download_complete = False

        # Progress hook untuk yt-dlp (update variable)
        def download_progress(d):
            nonlocal current_percent
            if d['status'] == 'downloading':
                current_percent = d.get('_percent_str', '0%').strip('%')

        # Thread untuk update realtime setiap 1 detik
        def realtime_update_thread():
            nonlocal download_complete
            last_text = ""
            while not download_complete:
                new_text = f"Mengunduh video: {current_percent}%..."
                if new_text != last_text:
                    update_progress(message, progress_msg_id, new_text)
                    last_text = new_text
                time.sleep(1)

        # Jalankan thread update
        update_thread = threading.Thread(target=realtime_update_thread)
        update_thread.start()

        # Opsi yt-dlp untuk download video terbaik
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',  # Kualitas tertinggi
            'outtmpl': os.path.join(OUTPUT_FOLDER, '%(title)s.%(ext)s'),  # Simpan di folder dengan nama judul
            'noplaylist': True,
            'quiet': True,  # Matikan output console, pakai hook aja
            'progress_hooks': [download_progress],
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_title = info['title']
            video_ext = info['ext']
            video_path = os.path.join(OUTPUT_FOLDER, f"{video_title}.{video_ext}")

        # Stop thread setelah download selesai
        download_complete = True
        update_thread.join()

        # Update progress ke splitting
        update_progress(message, progress_msg_id, "Download selesai. Mulai splitting: 0%...")

        # Split video menjadi chunk 3 menit (180 detik)
        clip = VideoFileClip(video_path)
        duration = clip.duration
        width, height = clip.size
        chunk_duration = 180  # 3 menit dalam detik
        num_chunks = math.ceil(duration / chunk_duration)

        # Ukuran watermark: 10% dari lebar video
        watermark_size = int(width * 0.1)
        # Ukuran font text: 5% dari tinggi video
        font_size = int(height * 0.05)

        # Load logo jika ada
        if os.path.exists(LOGO_PATH):
            logo = ImageClip(LOGO_PATH).resize(width=watermark_size).set_position(("left", "top"))
        else:
            logo = None
            bot.reply_to(message, "Warning: logo.png tidak ditemukan, skip watermark.")

        total_steps = num_chunks * 100  # Estimasi total progress untuk semua chunk
        current_step = 0

        for i in range(num_chunks):
            start_time = i * chunk_duration
            end_time = min((i + 1) * chunk_duration, duration)
            chunk_clip = clip.subclip(start_time, end_time)
            chunk_duration_actual = end_time - start_time  # Durasi aktual chunk

            # Text overlay: "Judul Video - Part X" di bawah tengah
            text = TextClip(f"{video_title} - Part {i+1}", fontsize=font_size, color='white', stroke_color='black', stroke_width=1)
            text = text.set_position(('center', 'bottom')).set_duration(chunk_duration_actual)

            # Komposisi: Video + Watermark (jika ada) + Text
            elements = [chunk_clip, text]
            if logo:
                logo_chunk = logo.set_duration(chunk_duration_actual)  # Sesuaikan durasi logo
                elements.append(logo_chunk)

            final_chunk = CompositeVideoClip(elements)

            # Simpan chunk dengan progress bar (tqdm untuk track write_videofile)
            chunk_filename = os.path.join(OUTPUT_FOLDER, f"{video_title}_part_{i+1}.{video_ext}")

            # Custom progress untuk moviepy write (pakai tqdm)
            with tqdm(total=100, desc=f"Chunk {i+1}", leave=False) as pbar:
                def progress_callback(progress):
                    nonlocal current_step
                    pbar.n = int(progress * 100)
                    pbar.refresh()
                    overall_percent = int((current_step + pbar.n) / total_steps * 100)
                    update_progress(message, progress_msg_id, f"Splitting chunk {i+1}/{num_chunks}: {pbar.n}% (Total: {overall_percent}%)...")
                
                # Moviepy nggak punya built-in callback, jadi kita simulasi dengan time-based update
                # Tapi untuk akurat, kita pakai wrapper sederhana
                start_render = time.time()
                final_chunk.write_videofile(chunk_filename, codec='libx264', audio_codec='aac', logger=None)  # Matikan logger default
                # Simulasi progress (karena moviepy lambat di callback, kita update setiap detik)
                while time.time() - start_render < chunk_duration_actual / 2:  # Estimasi waktu render
                    elapsed = time.time() - start_render
                    estimated_progress = min(1, elapsed / (chunk_duration_actual / 2))  # Asumsi render ~setengah durasi
                    progress_callback(estimated_progress)
                    time.sleep(1)
                progress_callback(1.0)  # Selesai

            current_step += 100
            bot.reply_to(message, f"Chunk {i+1} selesai (dengan watermark & overlay): {chunk_filename}")

        # Hapus file original jika tidak dibutuhkan (opsional, uncomment jika mau)
        # os.remove(video_path)

        update_progress(message, progress_msg_id, "Proses selesai! Semua chunk disimpan di folder video-yt.")

    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)}")

# Jalankan bot
bot.polling()