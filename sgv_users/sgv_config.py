"""
═══════════════════════════════════════════════════════════════
  PART 1: SGV_CONFIG - Configuration & Utilities
  SuperGrok One Video Bot - Config, Folders, Prompts, Bahan
═══════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import logging
import random
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  DEFAULTS (overridden by CLI args or supergrok_one_bot.py)
# ═══════════════════════════════════════════════════════════════
APP_DIR = r"C:\tiktok_automation"
GROK_URL = "https://grok.com/imagine"

# These will be set by main entry point
NAMA_USER = "User"
BOT_TOKEN = ""
NO_WA = ""
DEFAULT_PORT = "9245"
USER_DATA_CHROME = os.path.join(APP_DIR, "user_data", "1")

# Subscription
SUBSCRIPTION_DAYS = 30
START_DATE = None  # Will be set from config file

# WhatsApp group link
WA_GROUP_LINK = "https://chat.whatsapp.com/FUOOnA6PJMZKehq6dQwhge"

# ═══════════════════════════════════════════════════════════════
#  DYNAMIC FOLDER PATHS (set after NAMA_USER is initialized)
# ═══════════════════════════════════════════════════════════════
BAHAN_DIR = ""
VIDEO_DIR = ""
PROMPT_DIR = ""
PROMPTS_FILE = ""
CONFIG_FILE = ""


def init_config(nama_user, bot_token, no_wa, port, user_data):
    """Initialize all configuration from CLI args."""
    global NAMA_USER, BOT_TOKEN, NO_WA, DEFAULT_PORT, USER_DATA_CHROME
    global BAHAN_DIR, VIDEO_DIR, PROMPT_DIR, PROMPTS_FILE, CONFIG_FILE
    global START_DATE

    NAMA_USER = nama_user
    BOT_TOKEN = bot_token
    NO_WA = no_wa
    DEFAULT_PORT = port
    USER_DATA_CHROME = user_data

    # Set folder paths
    BAHAN_DIR = os.path.join(APP_DIR, f"bahan-{nama_user}")
    VIDEO_DIR = os.path.join(APP_DIR, f"video-{nama_user}")
    PROMPT_DIR = os.path.join(APP_DIR, f"prompt-{nama_user}")
    PROMPTS_FILE = os.path.join(PROMPT_DIR, "prompt.json")
    CONFIG_FILE = os.path.join(APP_DIR, f"sgv_config_{nama_user}.json")

    # Create directories
    os.makedirs(BAHAN_DIR, exist_ok=True)
    os.makedirs(VIDEO_DIR, exist_ok=True)
    os.makedirs(PROMPT_DIR, exist_ok=True)

    # Load or initialize start date
    _load_or_init_start_date()

    logger.info(f"✅ Config initialized for user: {NAMA_USER}")
    logger.info(f"   📁 Bahan: {BAHAN_DIR}")
    logger.info(f"   📁 Video: {VIDEO_DIR}")
    logger.info(f"   📁 Prompt: {PROMPT_DIR}")
    logger.info(f"   🔑 Port: {DEFAULT_PORT}")
    logger.info(f"   🌐 Chrome: {USER_DATA_CHROME}")


def _load_or_init_start_date():
    """Load start date from config file or create new one."""
    global START_DATE
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                START_DATE = datetime.fromisoformat(data.get("start_date", ""))
                return
        except:
            pass

    # First run - set start date to now
    START_DATE = datetime.now()
    _save_config()


def _save_config():
    """Save config to file."""
    data = {
        "start_date": START_DATE.isoformat() if START_DATE else datetime.now().isoformat(),
        "nama_user": NAMA_USER,
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Gagal simpan config: {e}")


# ═══════════════════════════════════════════════════════════════
#  SUBSCRIPTION CHECK
# ═══════════════════════════════════════════════════════════════
def is_subscription_active() -> bool:
    """Check if subscription is still active (within 30 days)."""
    if not START_DATE:
        return False
    end_date = START_DATE + timedelta(days=SUBSCRIPTION_DAYS)
    return datetime.now() <= end_date


def get_subscription_end_date() -> str:
    """Get formatted subscription end date."""
    if not START_DATE:
        return "Tidak diketahui"
    end_date = START_DATE + timedelta(days=SUBSCRIPTION_DAYS)
    return end_date.strftime("%d %B %Y, %H:%M WIB")


def get_days_remaining() -> int:
    """Get remaining subscription days."""
    if not START_DATE:
        return 0
    end_date = START_DATE + timedelta(days=SUBSCRIPTION_DAYS)
    remaining = (end_date - datetime.now()).days
    return max(0, remaining)


SUBSCRIPTION_EXPIRED_MSG = (
    "🚫 <b>MASA LANGGANAN BOT SUDAH BERAKHIR.</b>\n\n"
    "SILAHKAN LANJUTKAN BERLANGGANAN DI\n"
    f"👉 https://chat.whatsapp.com/FUOOnA6PJMZKehq6dQwhge"
)


# ═══════════════════════════════════════════════════════════════
#  PROMPTS DATABASE
# ═══════════════════════════════════════════════════════════════
def load_prompts() -> dict:
    """Load prompts from JSON. Returns {name: text}."""
    if os.path.exists(PROMPTS_FILE):
        try:
            with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}


def save_prompts(data: dict):
    """Save prompts to JSON."""
    os.makedirs(os.path.dirname(PROMPTS_FILE), exist_ok=True)
    with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
#  BAHAN (IMAGE FOLDERS) HELPERS
# ═══════════════════════════════════════════════════════════════
def ensure_bahan_dir():
    os.makedirs(BAHAN_DIR, exist_ok=True)


def list_bahan_folders() -> list:
    """List subfolders in bahan directory."""
    ensure_bahan_dir()
    return sorted([d for d in os.listdir(BAHAN_DIR)
                   if os.path.isdir(os.path.join(BAHAN_DIR, d))])


def list_bahan_images(folder_name: str) -> list:
    """List image files in a bahan subfolder."""
    folder = os.path.join(BAHAN_DIR, folder_name)
    if not os.path.isdir(folder):
        return []
    exts = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')
    return sorted([f for f in os.listdir(folder)
                   if f.lower().endswith(exts)])


def get_random_bahan_image(folder_name: str):
    """Get a random image path from a bahan folder."""
    images = list_bahan_images(folder_name)
    if not images:
        return None
    chosen = random.choice(images)
    return os.path.join(BAHAN_DIR, folder_name, chosen)


def get_bahan_folder_path(folder_name: str) -> str:
    """Get full path to a bahan subfolder."""
    return os.path.join(BAHAN_DIR, folder_name)


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════
def escape_html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
