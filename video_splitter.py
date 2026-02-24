import os
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox

def get_video_duration(video_path):
    # Bersihkan path agar slash/backslash seragam (mencegah error di Windows/ffprobe)
    video_path = os.path.normpath(video_path)
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", video_path
    ]
    try:
        # Menjalankan ffprobe untuk membaca durasi
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        return float(output.decode("utf-8").strip())
    except subprocess.CalledProcessError as e:
        print(f"Error ffprobe pada '{video_path}':\nDetail: {e.output.decode('utf-8', errors='ignore').strip()}")
        return 0.0
    except Exception as e:
        print(f"Error mendapatkan durasi '{video_path}': {e}")
        return 0.0

def split_video():
    # Setup Tkinter untuk dialog file
    root = tk.Tk()
    root.withdraw() # Sembunyikan window utama

    print("--- Video Splitter (30 Detik) ---")
    print("Membuka dialog untuk memilih video...")
    input_video = filedialog.askopenfilename(
        title="Pilih Video yang Akan Dipotong",
        filetypes=[("Video Files", "*.mp4 *.mkv *.avi *.mov")]
    )
    
    if not input_video:
        print("Batal memilih video.")
        return

    print("Membuka dialog untuk memilih folder penyimpanan...")
    output_folder = filedialog.askdirectory(title="Pilih Folder Tujuan Penyimpanan Potongan")
    
    if not output_folder:
        output_folder = os.path.dirname(input_video)
        print(f"Batal memilih folder tujuan, menyimpan otomatis di folder yang sama dengan asalnya: {output_folder}")

    base_name = os.path.splitext(os.path.basename(input_video))[0]
    output_pattern = os.path.normpath(os.path.join(output_folder, f"{base_name}_part%03d.mp4"))
    
    print(f"\nMemproses Pemotongan Video: '{input_video}'")
    print("Metode: Stream Copy 100% (Tanpa Render Ulang, Tanpa Mengurangi Kualitas Asli)\n...")

    # Perintah ffmpeg: memotong video per 30 detik
    # -c copy menjamin tidak ada re-encode, kecepatan instan, dan 100% kualitas terjaga
    # -segment_time 30 mendikte potong tiap 30 detik
    # -reset_timestamps 1 membuat tiap potongan dihitung reset mulai dari 0 detiknya masing-masing
    cmd = [
        "ffmpeg", "-y", "-i", input_video,
        "-c", "copy",
        "-map", "0:v",   # Hanya salin stream video (mengabaikan codec metadata apple yang bikin error)
        "-map", "0:a?",  # Hanya salin stream audio (jika ada)
        "-segment_time", "30",
        "-f", "segment",
        "-reset_timestamps", "1",
        output_pattern
    ]
    
    # Jalankan ffmpeg tanpa window CMD yang menganggu
    # Kita tidak lagi menggunakan DEVNULL untuk stderr agar bisa print error jika ffmpeg gagal berjalan
    process = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode != 0:
        print("\n[PERINGATAN] FFmpeg mengeluarkan error/warning:")
        print(process.stderr.decode('utf-8', errors='ignore'))

    print("Proses potong (split) selesai, memeriksa durasi untuk membuang part potongan sisa...")
    
    # Menghapus potongan terakhir / sisa jika durasinya jauh dari 30 detik
    # Catatan: Kita pasang toleransi < 28 detik akan dihapus (karena FFmpeg motong berdasarkan keyframe, durasi bisa misal 29.5s)
    files_processed = 0
    files_deleted = 0
    
    for file in os.listdir(output_folder):
        if file.startswith(f"{base_name}_part") and file.endswith(".mp4"):
            files_processed += 1
            part_path = os.path.join(output_folder, file)
            duration = get_video_duration(part_path)
            
            # Jika kurang dari 28 detik, asumsikan itu "potongan sisa" yang diceritakan jadi dibuang
            if duration > 0 and duration < 28.0: 
                print(f"-> DIBUANG (Karena durasi nyisa / terlalu pendek): {file} ({duration:.2f} detik)")
                try:
                    os.remove(part_path)
                    files_deleted += 1
                except BaseException as e:
                    print(e)
            else:
                print(f"-> DISIMPAN (Utuh): {file} ({duration:.2f} detik)")
                
    # Laporan
    total_valid = files_processed - files_deleted
    msg = f"Selesai! Berhasil memotong {total_valid} video utuh (±30 detik).\n\nTersimpan di folder:\n{output_folder}"
    print(f"\n==== {msg.replace(chr(10), ' ')} ====")
    messagebox.showinfo("Berhasil", msg)

if __name__ == "__main__":
    split_video()
