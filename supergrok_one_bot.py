"""
═══════════════════════════════════════════════════════════════
  PART 4: SUPERGROK_ONE_BOT - Main Entry Point
  SuperGrok One Video Bot - CLI + Bot Initialization
═══════════════════════════════════════════════════════════════

USAGE:
  python supergrok_one_bot.py <nama_user> <BOT_TOKEN> <no_wa> <port> <user_data_chrome>

EXAMPLE:
  python supergrok_one_bot.py Budi 8781330231:AAFZ5enn-P5tIBMwwGe5rOLNgRQ8YWAmfNg 081234567890 9245 C:\\tiktok_automation\\user_data\\1
"""

import sys
import os
import logging
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("SuperGrokOneBot")

# ═══════════════════════════════════════════════════════════════
#  PARSE ARGUMENTS
# ═══════════════════════════════════════════════════════════════
def parse_args():
    """Parse CLI arguments with defaults."""
    APP_DIR = r"C:\tiktok_automation"

    # Defaults
    defaults = {
        "nama_user": "User",
        "bot_token": "",
        "no_wa": "",
        "port": "9245",
        "user_data_chrome": os.path.join(APP_DIR, "user_data", "1"),
    }

    args = sys.argv[1:]

    if len(args) >= 1:
        defaults["nama_user"] = args[0]
    if len(args) >= 2:
        defaults["bot_token"] = args[1]
    if len(args) >= 3:
        defaults["no_wa"] = args[2]
    if len(args) >= 4:
        defaults["port"] = args[3]
    if len(args) >= 5:
        defaults["user_data_chrome"] = args[4]

    # Validate required
    if not defaults["bot_token"]:
        logger.error("❌ BOT_TOKEN wajib diisi!")
        print("\nUsage: python supergrok_one_bot.py <nama_user> <BOT_TOKEN> [no_wa] [port] [user_data_chrome]")
        print("\nContoh:")
        print('  python supergrok_one_bot.py Budi 8781330231:AAxxxxxxxx 081234567890 9245 "C:\\tiktok_automation\\user_data\\1"')
        sys.exit(1)

    return defaults


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    """Main entry point."""
    args = parse_args()

    logger.info("═" * 50)
    logger.info("  🤖 SUPERGROK ONE VIDEO BOT")
    logger.info("═" * 50)
    logger.info(f"  👤 User    : {args['nama_user']}")
    logger.info(f"  🔑 Token   : {args['bot_token'][:20]}...")
    logger.info(f"  📱 WA      : {args['no_wa']}")
    logger.info(f"  🔌 Port    : {args['port']}")
    logger.info(f"  🌐 Chrome  : {args['user_data_chrome']}")
    logger.info("═" * 50)

    # Initialize config (Part 1)
    from sgv_config import init_config
    init_config(
        nama_user=args["nama_user"],
        bot_token=args["bot_token"],
        no_wa=args["no_wa"],
        port=args["port"],
        user_data=args["user_data_chrome"]
    )

    # Import handlers (Part 3) after config is initialized
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    from telegram import BotCommand
    from sgv_bot import (
        cmd_start, cmd_help, cmd_stop,
        callback_gen_again,
        get_generate_conversation_handler,
        get_prompt_conversation_handler,
        get_bahan_conversation_handler,
    )

    # Build application
    app = Application.builder().token(args["bot_token"]).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stop", cmd_stop))

    # Conversation handlers (order matters - more specific first)
    app.add_handler(get_generate_conversation_handler())
    app.add_handler(get_prompt_conversation_handler())
    app.add_handler(get_bahan_conversation_handler())

    # Callback for "Generate Again" button (outside conversation)
    app.add_handler(CallbackQueryHandler(callback_gen_again, pattern=r"^gen_again$"))

    # Set bot commands
    async def set_commands(app):
        await app.bot.set_my_commands([
            BotCommand("start", "📋 Menu utama"),
            BotCommand("generate", "🎬 Generate video"),
            BotCommand("prompt", "📝 Kelola prompt"),
            BotCommand("bahan", "📁 Kelola bahan"),
            BotCommand("help", "❓ Bantuan"),
            BotCommand("stop", "🛑 Stop generate"),
        ])

    app.post_init = set_commands

    logger.info("🚀 Bot dimulai! Tekan Ctrl+C untuk berhenti.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
