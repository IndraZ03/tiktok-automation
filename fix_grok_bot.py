import sys

files = [r'c:\tiktok_automation\grok_imagine_bot.py', r'c:\tiktok_automation\grok_imagine_bot_a.py']

for fp in files:
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()

    # Define MERGED_DIR safely
    content = content.replace("MERGED_DIR = os.path.join(APP_DIR, \"grok_output_merged\")", "")
    content = content.replace("OUTPUT_DIR     = os.path.join(APP_DIR, \"grok_output\")", "OUTPUT_DIR     = os.path.join(APP_DIR, \"grok_output\")\nMERGED_DIR     = os.path.join(APP_DIR, \"grok_output_merged\")")
    
    # Fix merge_video_pair call to use gtt_core
    content = content.replace("merged_path = merge_video_pair(vid_a, vid_b, MERGED_DIR, log_fn)", "merged_path = gtt_core.merge_video_pair(vid_a, vid_b, MERGED_DIR, log_fn)")

    with open(fp, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Fixed {fp}")

