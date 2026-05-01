@echo off
setlocal

:: Nama file yang akan digunakan untuk cloudflared
set CLOUDFLARED_EXE=cloudflared.exe
set DOWNLOAD_URL=https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe

echo ========================================================
echo        CLOUDFLARE TUNNEL - YT BOT DASHBOARD
echo ========================================================
echo.

echo [INFO] Memeriksa apakah cloudflared sudah diunduh...

if not exist "%CLOUDFLARED_EXE%" (
    echo [INFO] cloudflared.exe tidak ditemukan di folder ini.
    echo [INFO] Memulai pengunduhan cloudflared versi terbaru...
    echo.
    curl -L -o "%CLOUDFLARED_EXE%" "%DOWNLOAD_URL%"
    
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Gagal mengunduh cloudflared! Pastikan koneksi internet aktif.
        pause
        exit /b %errorlevel%
    )
    echo.
    echo [INFO] Pengunduhan berhasil diselesaikan!
) else (
    echo [INFO] cloudflared sudah terinstall.
)

echo.
echo ========================================================
echo [INFO] Tautan web publik Anda akan segera muncul...
echo [INFO] CARI TULISAN BERWARNA BIRU BERAKHIRAN "trycloudflare.com"
echo ========================================================
echo.

:: Menjalankan web server
echo [INFO] Menjalankan gtt_web_server.py...
start "" "c:\tiktok_automation\Scripts\python.exe" "c:\tiktok_automation\gtt_web_server.py"

:: Memberikan waktu 3 detik agar server mulai berjalan
timeout /t 3 /nobreak >nul

:: Menjalankan tunnel menuju port 5505
"%CLOUDFLARED_EXE%" tunnel --url http://localhost:5505

pause
