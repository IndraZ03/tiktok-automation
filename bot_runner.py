"""
🤖 Bot Runner — Multi-Bot Process Manager
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs multiple Telegram bot scripts simultaneously.
Features:
  • Auto-restart on crash
  • Uptime / downtime tracking in JSON DB
  • Flexible: just add .py files to BOTS list
  • Color-coded console output
  • Graceful shutdown (Ctrl+C)
"""

import subprocess
import sys
import os
import json
import time
import signal
import threading
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION — Tambahkan bot baru di sini!
# ═══════════════════════════════════════════════════════════════
# Format: {"name": "Nama Bot", "script": "nama_file.py"}
# Tambahkan entry baru jika membuat bot Telegram lagi.

BOTS = [
    {"name": "SPEEDU Bot",   "script": "speedu_bot.py"},
    {"name": "Grok Bot",     "script": "grok_bot.py"},
    {"name": "TikTok Bot",   "script": "tiktok_bot.py"},
    # ── Tambahkan bot baru di bawah ini ──
    # {"name": "Nama Bot Baru", "script": "nama_bot_baru.py"},
]

# Paths
APP_DIR = r"C:\tiktok_automation"
PYTHON  = sys.executable  # Use the same Python interpreter
DB_FILE = os.path.join(APP_DIR, "bot_runner_db.json")

# Auto-restart settings
AUTO_RESTART       = True
RESTART_DELAY_SEC  = 5      # Delay sebelum restart
MAX_RAPID_RESTARTS = 5      # Max restart dalam window
RAPID_WINDOW_SEC   = 60     # Window untuk menghitung rapid restart

# ═══════════════════════════════════════════════════════════════
#  DATABASE (JSON)
# ═══════════════════════════════════════════════════════════════
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"bots": {}}


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def record_event(bot_name, event_type, reason=""):
    """
    Record an event to the DB.
    event_type: "start", "stop", "crash", "restart"
    """
    db = load_db()
    if bot_name not in db["bots"]:
        db["bots"][bot_name] = {
            "total_starts": 0,
            "total_crashes": 0,
            "current_status": "stopped",
            "uptime_start": None,
            "events": [],
        }

    bot = db["bots"][bot_name]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    event = {
        "type": event_type,
        "timestamp": now,
    }
    if reason:
        event["reason"] = reason

    # Update status
    if event_type == "start":
        bot["current_status"] = "running"
        bot["uptime_start"] = now
        bot["total_starts"] += 1

    elif event_type in ("stop", "crash"):
        bot["current_status"] = "stopped"
        # Calculate uptime duration
        if bot["uptime_start"]:
            try:
                start = datetime.strptime(bot["uptime_start"], "%Y-%m-%d %H:%M:%S")
                end = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
                duration = str(end - start)
                event["uptime_duration"] = duration
            except ValueError:
                pass
        bot["uptime_start"] = None
        if event_type == "crash":
            bot["total_crashes"] += 1

    elif event_type == "restart":
        bot["current_status"] = "restarting"

    # Keep last 100 events
    bot["events"].append(event)
    if len(bot["events"]) > 100:
        bot["events"] = bot["events"][-100:]

    save_db(db)


# ═══════════════════════════════════════════════════════════════
#  CONSOLE COLORS
# ═══════════════════════════════════════════════════════════════
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    DIM     = "\033[2m"

# Assign a color to each bot for easy identification
BOT_COLORS = [C.CYAN, C.MAGENTA, C.GREEN, C.YELLOW, C.BLUE, C.RED]


def ts():
    return datetime.now().strftime("%H:%M:%S")


def log(msg, color=C.RESET):
    print(f"{C.DIM}[{ts()}]{C.RESET} {color}{msg}{C.RESET}")


# ═══════════════════════════════════════════════════════════════
#  BOT PROCESS WRAPPER
# ═══════════════════════════════════════════════════════════════
class BotProcess:
    def __init__(self, name, script, color):
        self.name = name
        self.script = script
        self.color = color
        self.process = None
        self.thread = None
        self.restart_times = []  # timestamps of recent restarts
        self._stop_requested = False

    @property
    def full_path(self):
        return os.path.join(APP_DIR, self.script)

    @property
    def is_alive(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        """Start the bot subprocess."""
        if not os.path.exists(self.full_path):
            log(f"❌ {self.name}: File tidak ditemukan: {self.script}", C.RED)
            record_event(self.name, "stop", f"File tidak ditemukan: {self.script}")
            return False

        self._stop_requested = False
        try:
            # Force UTF-8 encoding for child process stdout
            # (without this, piped stdout falls back to cp1252 on Windows → emoji crash)
            child_env = os.environ.copy()
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUNBUFFERED"] = "1"

            self.process = subprocess.Popen(
                [PYTHON, self.full_path],
                cwd=APP_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                env=child_env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            log(f"✅ {self.name} dimulai (PID: {self.process.pid})", self.color)
            record_event(self.name, "start")

            # Start output reader thread
            self.thread = threading.Thread(
                target=self._read_output, daemon=True, name=f"reader-{self.name}"
            )
            self.thread.start()
            return True

        except Exception as e:
            log(f"❌ {self.name}: Gagal start — {e}", C.RED)
            record_event(self.name, "crash", str(e))
            return False

    def stop(self):
        """Gracefully stop the bot subprocess."""
        self._stop_requested = True
        if self.process and self.is_alive:
            log(f"⏹ Menghentikan {self.name} (PID: {self.process.pid})...", self.color)
            try:
                if os.name == "nt":
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.process.terminate()

                # Wait up to 10 seconds
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    log(f"⚠ {self.name}: Force kill", C.YELLOW)
                    self.process.kill()
                    self.process.wait(timeout=5)

            except Exception as e:
                log(f"⚠ {self.name}: Error stopping — {e}", C.YELLOW)
                try:
                    self.process.kill()
                except Exception:
                    pass

            record_event(self.name, "stop", "Dihentikan oleh user (Ctrl+C)")
            log(f"🛑 {self.name} dihentikan", self.color)

    def _read_output(self):
        """Read and print subprocess output with bot name prefix."""
        prefix = f"{self.color}[{self.name}]{C.RESET}"
        try:
            for line in iter(self.process.stdout.readline, ""):
                if not line:
                    break
                print(f"{C.DIM}[{ts()}]{C.RESET} {prefix} {line.rstrip()}")
        except Exception:
            pass

        # Process ended
        if self.process:
            retcode = self.process.poll()
            if retcode is not None and retcode != 0 and not self._stop_requested:
                reason = f"Exit code: {retcode}"
                log(f"💥 {self.name} crashed! ({reason})", C.RED)
                record_event(self.name, "crash", reason)

    def should_restart(self):
        """Check if auto-restart should happen (not too many rapid restarts)."""
        if self._stop_requested:
            return False

        now = time.time()
        # Clean old timestamps
        self.restart_times = [t for t in self.restart_times if now - t < RAPID_WINDOW_SEC]

        if len(self.restart_times) >= MAX_RAPID_RESTARTS:
            log(f"⚠ {self.name}: Terlalu banyak restart ({MAX_RAPID_RESTARTS}x dalam {RAPID_WINDOW_SEC}s). "
                f"Tidak auto-restart.", C.YELLOW)
            record_event(self.name, "stop", f"Rapid restart limit ({MAX_RAPID_RESTARTS}x/{RAPID_WINDOW_SEC}s)")
            return False

        self.restart_times.append(now)
        return True

    def restart(self):
        """Restart the bot."""
        log(f"🔄 Restarting {self.name} dalam {RESTART_DELAY_SEC}s...", self.color)
        record_event(self.name, "restart")
        time.sleep(RESTART_DELAY_SEC)
        self.start()


# ═══════════════════════════════════════════════════════════════
#  MAIN RUNNER
# ═══════════════════════════════════════════════════════════════
def print_banner():
    print(f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════╗
║         🤖 Bot Runner — Multi-Bot Manager        ║
╚══════════════════════════════════════════════════╝{C.RESET}
""")

    for i, bot in enumerate(BOTS):
        color = BOT_COLORS[i % len(BOT_COLORS)]
        exists = "✅" if os.path.exists(os.path.join(APP_DIR, bot["script"])) else "❌"
        print(f"  {color}● {bot['name']}{C.RESET}  →  {bot['script']}  {exists}")

    print(f"""
{C.DIM}  Auto-restart: {'ON' if AUTO_RESTART else 'OFF'}
  DB: {DB_FILE}
  Python: {PYTHON}
  Tekan Ctrl+C untuk menghentikan semua bot{C.RESET}
""")


def main():
    print_banner()

    # Create bot processes
    bots = []
    for i, cfg in enumerate(BOTS):
        color = BOT_COLORS[i % len(BOT_COLORS)]
        bp = BotProcess(cfg["name"], cfg["script"], color)
        bots.append(bp)

    # Start all
    log(f"🚀 Memulai {len(bots)} bot...", C.BOLD)
    for bp in bots:
        bp.start()
        time.sleep(1)  # Stagger starts

    log(f"✅ Semua bot telah dimulai!", C.GREEN + C.BOLD)

    # Shutdown handler
    shutdown = threading.Event()

    def on_signal(sig, frame):
        log(f"\n⚠ Sinyal {sig} diterima, menghentikan semua bot...", C.YELLOW + C.BOLD)
        shutdown.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    if os.name == "nt":
        signal.signal(signal.SIGBREAK, on_signal)

    # Monitor loop
    try:
        while not shutdown.is_set():
            for bp in bots:
                if not bp.is_alive and not bp._stop_requested:
                    if AUTO_RESTART and bp.should_restart():
                        bp.restart()

            # Check every 3 seconds
            shutdown.wait(timeout=3)

    except KeyboardInterrupt:
        log("\n⚠ Ctrl+C diterima!", C.YELLOW + C.BOLD)

    # Graceful shutdown
    log("🛑 Menghentikan semua bot...", C.RED + C.BOLD)
    for bp in bots:
        bp.stop()

    # Final status
    print(f"\n{C.CYAN}{C.BOLD}═══ Status Akhir ═══{C.RESET}")
    db = load_db()
    for bp in bots:
        bot_data = db["bots"].get(bp.name, {})
        total_starts = bot_data.get("total_starts", 0)
        total_crashes = bot_data.get("total_crashes", 0)
        events = bot_data.get("events", [])
        last_event = events[-1] if events else {}

        print(f"  {bp.color}● {bp.name}{C.RESET}")
        print(f"    Total starts: {total_starts}  |  Crashes: {total_crashes}")
        if last_event:
            print(f"    Last event: {last_event.get('type', '-')} @ {last_event.get('timestamp', '-')}")
            if last_event.get("uptime_duration"):
                print(f"    Uptime: {last_event['uptime_duration']}")
            if last_event.get("reason"):
                print(f"    Reason: {last_event['reason']}")

    print(f"\n{C.DIM}Database tersimpan di: {DB_FILE}{C.RESET}")
    log("👋 Bot Runner selesai.", C.BOLD)


if __name__ == "__main__":
    main()
