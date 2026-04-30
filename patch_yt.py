import sys
with open(r'c:\tiktok_automation\gtt_web_server.py', 'r', encoding='utf-8') as f:
    text = f.read()

find_text = '''if __name__ == "__main__":
    os.makedirs(os.path.join(APP_DIR, "gtt_stok"), exist_ok=True)
    web_log(f"Grok TikTok Web Dashboard running on http://localhost:{PORT}", "success")
    print(f"Grok TikTok Web Dashboard running on http://localhost:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)'''

replace_text = '''if __name__ == "__main__":
    os.makedirs(os.path.join(APP_DIR, "gtt_stok"), exist_ok=True)
    web_log(f"Grok TikTok Web Dashboard running on http://localhost:{PORT}", "success")
    print(f"Grok TikTok Web Dashboard running on http://localhost:{PORT}")
    try:
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from werkzeug.serving import run_simple
        from yt_web_server import app as yt_app, TEMP_DIR, FINAL_DIR
        os.makedirs(TEMP_DIR, exist_ok=True)
        os.makedirs(FINAL_DIR, exist_ok=True)
        application = DispatcherMiddleware(app, {'/ytbot': yt_app})
        print(f"✅ YT Bot berhasil dipasang di http://localhost:{PORT}/ytbot")
        run_simple(HOST, PORT, application, use_reloader=False, threaded=True)
    except Exception as e:
        print(f"⚠️ Peringatan: Tidak dapat memuat yt_web_server: {e}. Menjalankan GTT secara standalone.")
        app.run(host=HOST, port=PORT, debug=False, threaded=True)'''

if find_text in text:
    print('Found text!')
    text = text.replace(find_text, replace_text)
    with open(r'c:\tiktok_automation\gtt_web_server.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print('Replaced')
else:
    print('Text not found')
