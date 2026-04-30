@echo off
chcp 65001 >nul
title 🚀 Install FFmpeg N-122760-g33b215d155-20260217 (FIXED)
color 0b
echo.
echo ================================================
echo     Install FFmpeg Versi Spesifik + FIX MSSTORE
echo     Hash: g33b215d155 - 17 Feb 2026
echo ================================================
echo.

:: ====================== RUN AS ADMIN ======================
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [✓] Running as Administrator...
) else (
    echo [❌] Harus dijalankan sebagai Administrator!
    pause
    exit
)

:: ====================== FIX WINGET MSSTORE AGREEMENT ======================
echo [→] Memperbaiki Winget msstore agreement...
winget source update --accept-source-agreements >nul 2>&1
winget source reset --force >nul 2>&1
winget source update --accept-source-agreements >nul 2>&1

:: ====================== INSTALL 7-ZIP (jika belum ada) ======================
where 7z.exe >nul 2>&1
if %errorLevel% == 0 (
    echo [✓] 7-Zip sudah terinstall.
    set "SEVENZIP_CMD=7z.exe"
) else (
    echo [→] 7-Zip belum ada, mendownload 7za.exe standalone dari GitHub...
    set "SEVENZIP_CMD=%~dp07za.exe"
    if not exist "%~dp07za.exe" (
        powershell -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://github.com/develar/7zip-bin/raw/master/win/x64/7za.exe' -OutFile '%~dp07za.exe'"
    )
    if exist "%~dp07za.exe" (
        echo [✓] 7za.exe siap digunakan.
    ) else (
        echo [⚠] Gagal download 7za.exe. Pastikan koneksi internet lancar.
        pause
        exit
    )
)

:: ====================== DOWNLOAD FFmpeg ======================
set "FFMPEG_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-git-full.7z"
set "DOWNLOAD_FILE=%~dp0ffmpeg-full.7z"
set "EXTRACT_DIR=C:\ffmpeg"

echo [→] Downloading FFmpeg (Terbaru)...
powershell -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%FFMPEG_URL%' -OutFile '%DOWNLOAD_FILE%'"

if not exist "%DOWNLOAD_FILE%" (
    echo [❌] Download gagal!
    pause
    exit
) else (
    echo [✓] Download berhasil.
)

:: ====================== EXTRACT ======================
echo [→] Extracting ke C:\ffmpeg ...
if not exist "%EXTRACT_DIR%" mkdir "%EXTRACT_DIR%"

"%SEVENZIP_CMD%" x "%DOWNLOAD_FILE%" -o"%EXTRACT_DIR%" -y >nul

:: Pindah isi folder
for /d %%i in ("%EXTRACT_DIR%\ffmpeg-*") do (
    xcopy "%%i\*" "%EXTRACT_DIR%\" /E /Y >nul
    rmdir "%%i" /s /q
)

echo [✓] Extract selesai.

:: ====================== TAMBAHKAN KE PATH ======================
echo [→] Menambahkan ke PATH...
setx /M PATH "%PATH%;C:\ffmpeg\bin" >nul

:: ====================== VERIFY ======================
echo.
echo [→] Memeriksa instalasi FFmpeg...
ffmpeg -version >nul 2>&1
if %errorLevel% == 0 (
    color 0a
    echo.
    echo ================================================
    echo     ✅ BERHASIL! FFmpeg sudah terinstall
    echo     Versi : Latest Git Build (Gyan.dev)
    echo     Path  : C:\ffmpeg\bin
    echo ================================================
) else (
    echo [⚠] Gagal mendeteksi FFmpeg. Tutup semua CMD/PowerShell lalu buka ulang agar PATH ter-refresh.
)

echo.
echo Tekan tombol apa saja untuk keluar...
pause >nul