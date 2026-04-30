@echo off
chcp 65001 >nul
title 🚀 Install ImageMagick 7.1.2-18 (Q16-HDRI)
color 0b
echo.
echo ================================================
echo     Install ImageMagick 7.1.2-18 Q16-HDRI-x64
echo     Official Latest Version - March 2026
echo ================================================
echo.

:: ====================== RUN AS ADMIN ======================
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [✓] Running as Administrator...
) else (
    echo [❌] Harus dijalankan sebagai Administrator!
    echo    Klik kanan file .bat → Run as administrator
    pause
    exit
)

:: ====================== DOWNLOAD ImageMagick ======================
set "IM_URL=https://imagemagick.org/archive/binaries/ImageMagick-7.1.2-18-Q16-HDRI-x64-dll.exe"
set "DOWNLOAD_FILE=%~dp0ImageMagick-Installer.exe"
set "INSTALL_DIR=C:\ImageMagick"

echo [→] Downloading ImageMagick 7.1.2-18...
powershell -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%IM_URL%' -OutFile '%DOWNLOAD_FILE%'"

if not exist "%DOWNLOAD_FILE%" (
    echo [❌] Download gagal! Cek koneksi internet.
    pause
    exit
) else (
    echo [✓] Download berhasil.
)

:: ====================== INSTALL SILENT ======================
echo [→] Menginstall ImageMagick secara silent ke %INSTALL_DIR% ...
"%DOWNLOAD_FILE%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="%INSTALL_DIR%" /TASKS="" /SP- 

if %errorLevel% == 0 (
    echo [✓] Instalasi selesai.
) else (
    echo [⚠] Instalasi selesai dengan kode %errorLevel%.
)

:: ====================== TAMBAHKAN KE PATH (jika perlu) ======================
echo [→] Menambahkan ke PATH sistem...
setx /M PATH "%PATH%;%INSTALL_DIR%" >nul

:: ====================== VERIFY ======================
echo.
echo [→] Memverifikasi instalasi...
timeout /t 2 >nul

magick --version | findstr /C:"7.1.2-18" >nul
if %errorLevel% == 0 (
    color 0a
    echo.
    echo ================================================
    echo     ✅ BERHASIL! ImageMagick berhasil diinstall
    echo     Versi   : 7.1.2-18 Q16-HDRI
    echo     Path    : C:\ImageMagick
    echo     Command : magick --version
    echo ================================================
) else (
    color 0c
    echo [⚠] Versi tidak terdeteksi.
    echo     Coba tutup semua Command Prompt lalu buka yang baru.
    echo     Ketik: magick --version
)

echo.
echo Tekan tombol apa saja untuk keluar...
pause >nul

:: Bersihkan installer
del "%DOWNLOAD_FILE%" >nul 2>&1