"""
Grok TikTok Web Dashboard - Flask control panel.

Run:
    python gtt_web_server.py

Open:
    http://localhost:5505
"""
import json
import os
import re
import shutil
import threading
import time
import traceback
import tempfile
import zipfile
from collections import deque
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, render_template_string, request, send_file

from gtt_core import (
    APP_DIR,
    load_db,
    save_db,
    get_ud_config,
    stok_dir,
    count_stok,
    list_stok,
    load_ud_schedule,
    save_ud_schedule,
    load_prompts,
    save_prompts,
    BAHAN_DIR,
    list_bahan_folders,
    list_bahan_images,
    build_tiktok_schedule,
    upload_tiktok_batch,
    resolve_ud_path,
    GrokRateLimitError,
    generate_stok_for_ud,
)
from grok_tiktok_bot import (
    generate_stok_multibrowser,
    merge_leftover_raw,
    custom_merge_video_pair,
    get_raw_dir,
)
from grok_imagine_bot import (
    GrokBrowserWorker as ImagineBrowserWorker,
    GROK_PORTS as IMAGINE_GROK_PORTS,
    GROK_USER_DATA_DIRS as IMAGINE_GROK_USER_DATA_DIRS,
    N_BROWSERS as IMAGINE_N_BROWSERS,
    OUTPUT_DIR as IMAGINE_OUTPUT_DIR,
    MERGED_DIR as IMAGINE_MERGED_DIR,
    load_bot_settings as load_imagine_settings,
    save_bot_settings as save_imagine_settings,
    merge_video_pair as imagine_merge_video_pair,
    get_random_bahan_image as get_random_imagine_bahan_image,
)
from brutal_bot import (
    generate_schedule as brutal_generate_schedule,
    merge_video_pair as brutal_merge_video_pair,
)


HOST = "0.0.0.0"
PORT = 5505
MAX_UD = 20
MAX_LOG_LINES = 400
BRUTAL_MAX_STOK = 50
BRUTAL_UPLOAD_DELAY_MINUTES = 30
IMAGINE_META_FILE = os.path.join(APP_DIR, "grok_imagine_web_meta.json")

app = Flask(__name__)

_log_buffer = deque(maxlen=MAX_LOG_LINES)
_log_subscribers = []
_log_lock = threading.Lock()
_task_lock = threading.Lock()
_tasks = {}  # "generate:1" -> {action, ud, stop_event, thread, started_at}
_imagine_state = {
    "running": False,
    "stop_event": None,
    "thread": None,
    "started_at": "",
    "folder": "",
    "prompt": "",
    "target": 0,
    "generated": 0,
    "failed": 0,
    "merged": 0,
    "browser_states": {},
}



_auto_state = {"running": False, "stop_event": None, "thread": None}

def _full_auto_daemon(stop_event):
    web_log("🤖 Full Auto dimulai!", "success", action="auto")
    while not stop_event.is_set():
        db = load_db()
        active = _parse_ud_list(db.get("active_ud", [1, 2]))
        now = datetime.now()
        ready_uds = []
        future_uds = []

        for ud in active:
            cfg = get_ud_config(db, ud)
            if not cfg.get("prompt_name") or not cfg.get("bahan_folder"):
                continue
            sched = cfg.get("schedule", {})
            try:
                trigger_dt = datetime.strptime(
                    f"{sched.get('tanggal')} {str(sched.get('jam', '02')).zfill(2)}:{str(sched.get('menit', '00')).zfill(2)}", 
                    "%Y-%m-%d %H:%M"
                )
            except Exception as e:
                continue
                
            if trigger_dt <= now:
                ready_uds.append(ud)
            else:
                future_uds.append((trigger_dt, ud))
        
        if not ready_uds and not future_uds:
            if not stop_event.is_set():
                for _ in range(12):
                    if stop_event.is_set(): break
                    time.sleep(5)
            continue
            
        if ready_uds:
            web_log(f"🚀 Menjalankan pipeline untuk UD: {', '.join(map(str, ready_uds))}", "info", action="auto")
            for ud in ready_uds:
                if stop_event.is_set(): break
                web_log(f"UD {ud}: Mulai auto pipeline", "info", ud=ud, action="auto")
                
                # Generate if needed
                db = load_db()
                cfg = get_ud_config(db, ud)
                batch_size = int(cfg.get("batch_size", 30) or 30)
                current = count_stok(ud)
                needed = max(0, batch_size - current)
                if needed > 0:
                    _run_generate(ud, stop_event, needed)
                if stop_event.is_set(): break
                
                # Upload
                if count_stok(ud) > 0:
                    _run_upload(ud, stop_event)               
                if stop_event.is_set(): break
                
                # Update next schedule AFTER upload attempts
                db = load_db()
                cfg = get_ud_config(db, ud)
                interval_hours = int(cfg.get("interval_hours", 5) or 5)
                sched_items = load_ud_schedule(ud)
                next_dt = datetime.now() + timedelta(minutes=1)
                if sched_items and len(sched_items) > 0:
                    try:
                        last_dt = datetime.strptime(sched_items[-1]["schedule"], "%Y-%m-%d %H:%M")
                        next_dt = last_dt + timedelta(minutes=1)
                    except:
                        pass
                
                cfg["schedule"]["tanggal"] = next_dt.strftime("%Y-%m-%d")
                cfg["schedule"]["jam"] = f"{next_dt.hour:02d}"
                cfg["schedule"]["menit"] = f"{next_dt.minute:02d}"
                save_db(db)
                web_log(f"UD {ud}: Next pipeline diset ke {next_dt.strftime('%Y-%m-%d %H:%M')}", "success", ud=ud, action="auto")
                    
            if stop_event.is_set(): break
            time.sleep(10)
            continue
            
        future_uds.sort(key=lambda x: x[0])
        trigger_dt, next_ud = future_uds[0]
        wait_sec = (trigger_dt - datetime.now()).total_seconds()
        web_log(f"⏳ Menunggu jadwal terdekat UD {next_ud} pada {trigger_dt.strftime('%Y-%m-%d %H:%M')} ({(int(wait_sec)//60)} menit)", "info", action="auto")
        
        elapsed = 0
        while elapsed < wait_sec and not stop_event.is_set():
            time.sleep(min(30, wait_sec - elapsed))
            elapsed += 30

    _auto_state["running"] = False
    web_log("⏹ Full Auto dihentikan.", "warn", action="auto")


def _now_time():
    return datetime.now().strftime("%H:%M:%S")


def web_log(msg, tag="info", ud=None, action=None):
    entry = {
        "ts": _now_time(),
        "tag": tag or "info",
        "msg": str(msg),
        "ud": ud,
        "action": action,
    }
    with _log_lock:
        _log_buffer.append(entry)
        dead = []
        for q in _log_subscribers:
            try:
                q.append(entry)
            except Exception:
                dead.append(q)
        for q in dead:
            if q in _log_subscribers:
                _log_subscribers.remove(q)


def _task_key(action, ud):
    return f"{action}:{int(ud)}"


def _is_task_running(action, ud):
    task = _tasks.get(_task_key(action, ud))
    return bool(task and task.get("thread") and task["thread"].is_alive())


def _cleanup_finished_tasks():
    with _task_lock:
        for key, task in list(_tasks.items()):
            th = task.get("thread")
            if th and not th.is_alive():
                _tasks.pop(key, None)


def _parse_ud_list(value):
    if isinstance(value, list):
        items = value
    else:
        items = re.split(r"[\s,]+", str(value or ""))
    nums = []
    for item in items:
        try:
            n = int(item)
        except Exception:
            continue
        if 1 <= n <= MAX_UD and n not in nums:
            nums.append(n)
    return nums


def _parse_hashtags(value):
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,\n]+", str(value or ""))
    tags = []
    for tag in raw:
        clean = str(tag).strip().lstrip("#")
        if clean:
            tags.append(clean)
    return tags


def _brutal_stok_dir(ud):
    d = os.path.join(APP_DIR, "brutal_stok", f"ud_{int(ud)}")
    os.makedirs(d, exist_ok=True)
    return d


def _brutal_raw_dir(ud):
    d = os.path.join(APP_DIR, "brutal_stok_raw", f"ud_{int(ud)}")
    os.makedirs(d, exist_ok=True)
    return d


def _brutal_schedule_file(ud):
    return os.path.join(APP_DIR, f"brutal_schedule_ud_{int(ud)}.json")


def _brutal_count_stok(ud):
    d = _brutal_stok_dir(ud)
    return len([f for f in os.listdir(d) if f.lower().endswith(".mp4")])


def _brutal_list_stok(ud):
    d = _brutal_stok_dir(ud)
    files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".mp4")]
    return sorted(files, key=os.path.getmtime)


def _brutal_raw_count(ud):
    d = _brutal_raw_dir(ud)
    return len([f for f in os.listdir(d) if f.lower().endswith(".mp4")])


def _save_brutal_schedule(ud, schedule):
    with open(_brutal_schedule_file(ud), "w", encoding="utf-8") as f:
        json.dump(schedule, f, indent=2, ensure_ascii=False)


def _load_brutal_schedule(ud):
    f = _brutal_schedule_file(ud)
    if os.path.exists(f):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return []


def _brutal_merge_leftover_raw(ud, log_fn=None):
    raw_dir = _brutal_raw_dir(ud)
    out_dir = _brutal_stok_dir(ud)
    raws = sorted(
        [os.path.join(raw_dir, f) for f in os.listdir(raw_dir) if f.lower().endswith(".mp4")],
        key=os.path.getmtime,
    )
    if len(raws) < 2:
        return []
    if log_fn:
        log_fn(f"UD {ud}: ditemukan {len(raws)} raw brutal sisa, merge dulu...")
    merged = []
    for i in range(0, len(raws) - 1, 2):
        mp = brutal_merge_video_pair(raws[i], raws[i + 1], out_dir, log_fn)
        if mp:
            merged.append(mp)
            for path in (raws[i], raws[i + 1]):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
    return merged


def _load_imagine_meta():
    if os.path.exists(IMAGINE_META_FILE):
        try:
            with open(IMAGINE_META_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _save_imagine_meta(meta):
    with open(IMAGINE_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def _imagine_dirs():
    os.makedirs(IMAGINE_OUTPUT_DIR, exist_ok=True)
    os.makedirs(IMAGINE_MERGED_DIR, exist_ok=True)
    return {"raw": IMAGINE_OUTPUT_DIR, "merged": IMAGINE_MERGED_DIR}


def _safe_imagine_path(file_id):
    file_id = str(file_id or "").replace("\\", "/").strip("/")
    if "/" not in file_id:
        raise ValueError("file id tidak valid")
    kind, name = file_id.split("/", 1)
    if kind not in ("raw", "merged"):
        raise ValueError("jenis file tidak valid")
    name = os.path.basename(name)
    if not name.lower().endswith(".mp4"):
        raise ValueError("hanya mp4")
    path = os.path.join(_imagine_dirs()[kind], name)
    base = os.path.abspath(_imagine_dirs()[kind])
    full = os.path.abspath(path)
    if not full.startswith(base + os.sep):
        raise ValueError("path tidak aman")
    return kind, name, full


def _imagine_file_items():
    dirs = _imagine_dirs()
    meta = _load_imagine_meta()
    items = []
    for kind, folder in dirs.items():
        for path in sorted(glob_mp4(folder), key=os.path.getmtime, reverse=True):
            name = os.path.basename(path)
            fid = f"{kind}/{name}"
            st = os.stat(path)
            info = meta.get(fid, {})
            items.append({
                "id": fid,
                "kind": kind,
                "name": name,
                "size_mb": round(st.st_size / (1024 * 1024), 2),
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "downloaded": bool(info.get("downloaded")),
                "downloaded_at": info.get("downloaded_at", ""),
                "url": f"/api/imagine/media/{kind}/{name}",
                "download_url": f"/api/imagine/download/{kind}/{name}",
            })
    return items


def glob_mp4(folder):
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".mp4")]


def _mark_imagine_downloaded(file_ids, downloaded=True):
    meta = _load_imagine_meta()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for fid in file_ids:
        try:
            kind, name, path = _safe_imagine_path(fid)
        except Exception:
            continue
        if not os.path.exists(path):
            continue
        key = f"{kind}/{name}"
        meta.setdefault(key, {})
        meta[key]["downloaded"] = bool(downloaded)
        meta[key]["downloaded_at"] = now if downloaded else ""
    _save_imagine_meta(meta)


def _cfg_for_save(db, ud):
    cfg = get_ud_config(db, ud)
    db.setdefault("ud_configs", {})[str(ud)] = cfg
    return cfg


def _public_cfg(db, ud):
    cfg = get_ud_config(db, ud)
    sched = cfg.get("schedule", {}) or {}
    return {
        "prompt_name": cfg.get("prompt_name", ""),
        "bahan_folder": cfg.get("bahan_folder", ""),
        "deskripsi": cfg.get("deskripsi", ""),
        "hashtags": cfg.get("hashtags", []),
        "nama_produk_radio": cfg.get("nama_produk_radio", ""),
        "nama_produk_radio_list": cfg.get("nama_produk_radio_list", []),
        "nama_produk_input": cfg.get("nama_produk_input", ""),
        "add_product": bool(cfg.get("add_product", True)),
        "add_sound": bool(cfg.get("add_sound", False)),
        "interval_hours": int(cfg.get("interval_hours", 5) or 5),
        "batch_size": int(cfg.get("batch_size", 30) or 30),
        "tiktok_ud": cfg.get("tiktok_ud", ""),
        "tiktok_port": cfg.get("tiktok_port", ""),
        "grok_ud": cfg.get("grok_ud", ""),
        "grok_port": cfg.get("grok_port", ""),
        "schedule": {
            "tanggal": sched.get("tanggal", ""),
            "jam": str(sched.get("jam", "02")).zfill(2),
            "menit": str(sched.get("menit", "00")).zfill(2),
        },
    }


def _status_payload():
    _cleanup_finished_tasks()
    db = load_db()
    active = _parse_ud_list(db.get("active_ud", [1, 2]))
    prompts = load_prompts()
    bahan_folders = list_bahan_folders()
    ud_data = {}
    for ud in range(1, MAX_UD + 1):
        cfg = _public_cfg(db, ud)
        sched_items = load_ud_schedule(ud)
        stok_files = list_stok(ud)
        raw_dir = get_raw_dir(ud)
        raw_count = 0
        if os.path.isdir(raw_dir):
            raw_count = len([f for f in os.listdir(raw_dir) if f.lower().endswith(".mp4")])
        ud_data[str(ud)] = {
            "active": ud in active,
            "stok": len(stok_files),
            "stok_preview": [os.path.basename(p) for p in stok_files[:12]],
            "raw_count": raw_count,
            "schedule_items": len(sched_items),
            "last_schedule": sched_items[-1].get("schedule") if sched_items else "",
            "brutal": {
                "stok": _brutal_count_stok(ud),
                "raw_count": _brutal_raw_count(ud),
                "schedule_items": len(_load_brutal_schedule(ud)),
                "stok_preview": [os.path.basename(p) for p in _brutal_list_stok(ud)[:12]],
            },
            "config": cfg,
            "running": {
                "generate": _is_task_running("generate", ud),
                "upload": _is_task_running("upload", ud),
                "pipeline": _is_task_running("pipeline", ud),
                "brutal_generate": _is_task_running("brutal_generate", ud),
                "brutal_upload": _is_task_running("brutal_upload", ud),
                "brutal_pipeline": _is_task_running("brutal_pipeline", ud),
            },
        }
    return {
        "ok": True,
        "active_uds": active,
        "prompts": sorted(prompts.keys()),
        "bahan_folders": bahan_folders,
        "auto_running": _auto_state.get("running", False),
        "imagine": {
            "settings": load_imagine_settings(),
            "running": bool(_imagine_state.get("running")),
            "started_at": _imagine_state.get("started_at", ""),
            "folder": _imagine_state.get("folder", ""),
            "prompt": _imagine_state.get("prompt", ""),
            "target": _imagine_state.get("target", 0),
            "generated": _imagine_state.get("generated", 0),
            "failed": _imagine_state.get("failed", 0),
            "merged": _imagine_state.get("merged", 0),
            "browser_states": _imagine_state.get("browser_states", {}),
            "files_total": len(_imagine_file_items()),
            "files_downloaded": len([x for x in _imagine_file_items() if x.get("downloaded")]),
        },
        "ud_data": ud_data,
        "tasks": [
            {
                "key": key,
                "action": task.get("action"),
                "ud": task.get("ud"),
                "started_at": task.get("started_at"),
            }
            for key, task in _tasks.items()
            if task.get("thread") and task["thread"].is_alive()
        ],
    }


def _start_task(action, ud, target):
    ud = int(ud)
    key = _task_key(action, ud)
    with _task_lock:
        if _is_task_running(action, ud):
            return False, f"{action} UD {ud} sudah berjalan"
        stop_event = threading.Event()
        thread = threading.Thread(target=target, args=(stop_event,), daemon=True)
        _tasks[key] = {
            "action": action,
            "ud": ud,
            "stop_event": stop_event,
            "thread": thread,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        thread.start()
    return True, "started"


def _run_generate(ud, stop_event, needed_override=None):
    ud = int(ud)
    try:
        db = load_db()
        cfg = get_ud_config(db, ud)
        prompts = load_prompts()
        prompt_name = cfg.get("prompt_name", "")
        prompt_text = prompts.get(prompt_name, "")
        bahan_folder = cfg.get("bahan_folder", "")
        if not prompt_text:
            web_log(f"UD {ud}: prompt belum diset atau kosong.", "error", ud, "generate")
            return
        if not bahan_folder or not list_bahan_images(bahan_folder):
            web_log(f"UD {ud}: bahan folder belum diset atau kosong.", "error", ud, "generate")
            return

        web_log(f"UD {ud}: generate dimulai.", "info", ud, "generate")
        leftover = merge_leftover_raw(ud, lambda m: web_log(m, "info", ud, "generate"))
        if leftover:
            web_log(f"UD {ud}: pre-merge {len(leftover)} video sisa.", "success", ud, "generate")

        batch_size = int(cfg.get("batch_size", 30) or 30)
        current = count_stok(ud)
        needed = int(needed_override) if needed_override else max(0, batch_size - current)
        if needed <= 0:
            web_log(f"UD {ud}: stok sudah penuh ({current}/{batch_size}).", "success", ud, "generate")
            return

        def log_fn(msg):
            tag = "error" if "gagal" in str(msg).lower() or "error" in str(msg).lower() else "info"
            if "selesai" in str(msg).lower() or "berhasil" in str(msg).lower():
                tag = "success"
            web_log(msg, tag, ud, "generate")

        generate_stok_multibrowser(
            ud,
            needed,
            prompt_text,
            bahan_folder,
            log_fn,
            stop_event,
            raw_dir=get_raw_dir(ud),
            merge_func=custom_merge_video_pair,
        )
        web_log(f"UD {ud}: generate selesai. Stok sekarang {count_stok(ud)}.", "success", ud, "generate")
    except GrokRateLimitError as exc:
        web_log(f"UD {ud}: Grok rate limit. {exc}", "warn", ud, "generate")
    except Exception as exc:
        web_log(f"UD {ud}: error generate: {exc}", "error", ud, "generate")
        web_log(traceback.format_exc()[-1200:], "error", ud, "generate")
    finally:
        with _task_lock:
            _tasks.pop(_task_key("generate", ud), None)


def _build_schedule_from_cfg(ud, cfg, stok_files):
    sched = cfg.get("schedule", {}) or {}
    date_str = sched.get("tanggal") or datetime.now().strftime("%Y-%m-%d")
    jam = str(sched.get("jam", "02")).zfill(2)
    menit = str(sched.get("menit", "00")).zfill(2)
    try:
        start_dt = datetime.strptime(f"{date_str} {jam}:{menit}", "%Y-%m-%d %H:%M")
    except Exception:
        start_dt = datetime.now()
    interval = int(cfg.get("interval_hours", 5) or 5)
    schedule = build_tiktok_schedule(stok_files, start_dt, interval)
    save_ud_schedule(ud, schedule)
    return schedule


def _run_upload(ud, stop_event):
    ud = int(ud)
    try:
        db = load_db()
        cfg = get_ud_config(db, ud)
        batch_size = int(cfg.get("batch_size", 30) or 30)
        stok_files = list_stok(ud)[:batch_size]
        if not stok_files:
            web_log(f"UD {ud}: stok kosong, generate dulu.", "error", ud, "upload")
            return
        if not cfg.get("tiktok_ud") or not cfg.get("tiktok_port"):
            web_log(f"UD {ud}: TikTok user-data atau port belum diset.", "error", ud, "upload")
            return

        schedule = _build_schedule_from_cfg(ud, cfg, stok_files)
        web_log(f"UD {ud}: upload dimulai untuk {len(schedule)} video.", "info", ud, "upload")
        web_log(f"UD {ud}: jadwal pertama {schedule[0]['schedule']}.", "info", ud, "upload")

        def log_fn(msg):
            text = str(msg)
            lower = text.lower()
            tag = "info"
            if "berhasil" in lower or "selesai" in lower or "done" in lower:
                tag = "success"
            elif "gagal" in lower or "error" in lower or "tidak" in lower:
                tag = "error"
            elif "skip" in lower or "warning" in lower:
                tag = "warn"
            web_log(text, tag, ud, "upload")

        uploaded = upload_tiktok_batch(ud, schedule, cfg, log_fn, stop_event)
        web_log(f"UD {ud}: upload selesai. Berhasil {uploaded}/{len(schedule)}. Sisa stok {count_stok(ud)}.", "success", ud, "upload")
    except Exception as exc:
        web_log(f"UD {ud}: error upload: {exc}", "error", ud, "upload")
        web_log(traceback.format_exc()[-1200:], "error", ud, "upload")
    finally:
        with _task_lock:
            _tasks.pop(_task_key("upload", ud), None)


def _run_pipeline(ud, stop_event):
    ud = int(ud)
    try:
        web_log(f"UD {ud}: pipeline generate + upload dimulai.", "info", ud, "pipeline")
        _run_generate(ud, stop_event)
        if stop_event.is_set():
            web_log(f"UD {ud}: pipeline dihentikan setelah generate.", "warn", ud, "pipeline")
            return
        _run_upload(ud, stop_event)
        web_log(f"UD {ud}: pipeline selesai.", "success", ud, "pipeline")
    finally:
        with _task_lock:
            _tasks.pop(_task_key("pipeline", ud), None)


def _run_brutal_generate(ud, stop_event, target_stok=None):
    ud = int(ud)
    target_stok = int(target_stok or BRUTAL_MAX_STOK)
    try:
        db = load_db()
        cfg = get_ud_config(db, ud)
        prompts = load_prompts()
        prompt_text = prompts.get(cfg.get("prompt_name", ""), "")
        bahan_folder = cfg.get("bahan_folder", "")
        if not prompt_text:
            web_log(f"UD {ud}: prompt belum diset untuk Brutal Bot.", "error", ud, "brutal")
            return
        if not bahan_folder or not list_bahan_images(bahan_folder):
            web_log(f"UD {ud}: bahan folder belum diset atau kosong untuk Brutal Bot.", "error", ud, "brutal")
            return
        if not cfg.get("grok_ud") or not cfg.get("grok_port"):
            web_log(f"UD {ud}: Grok user-data atau port belum diset.", "error", ud, "brutal")
            return

        def log_fn(msg):
            text = str(msg)
            lower = text.lower()
            tag = "info"
            if "selesai" in lower or "berhasil" in lower or "tersimpan" in lower:
                tag = "success"
            elif "gagal" in lower or "error" in lower or "rate limit" in lower:
                tag = "error"
            elif "skip" in lower or "timeout" in lower:
                tag = "warn"
            web_log(text, tag, ud, "brutal")

        merged_left = _brutal_merge_leftover_raw(ud, log_fn)
        if merged_left:
            web_log(f"UD {ud}: pre-merge brutal {len(merged_left)} video.", "success", ud, "brutal")

        current = _brutal_count_stok(ud)
        needed = max(0, target_stok - current)
        if needed <= 0:
            web_log(f"UD {ud}: stok brutal sudah penuh ({current}/{target_stok}).", "success", ud, "brutal")
            return

        web_log(f"UD {ud}: Brutal Generate dimulai, target {needed} video baru ({current}/{target_stok}).", "info", ud, "brutal")
        generate_stok_for_ud(
            ud_num=f"Brutal-UD{ud}",
            needed=needed,
            prompt_text=prompt_text,
            bahan_folder=bahan_folder,
            grok_ud=cfg.get("grok_ud"),
            grok_port=str(cfg.get("grok_port")),
            log_fn=log_fn,
            stop_event=stop_event,
            out_dir=_brutal_stok_dir(ud),
            raw_dir=_brutal_raw_dir(ud),
            merge_func=brutal_merge_video_pair,
        )
        web_log(f"UD {ud}: Brutal Generate selesai. Stok brutal {_brutal_count_stok(ud)}.", "success", ud, "brutal")
    except GrokRateLimitError as exc:
        web_log(f"UD {ud}: Brutal Grok rate limit. {exc}", "warn", ud, "brutal")
    except Exception as exc:
        web_log(f"UD {ud}: error Brutal Generate: {exc}", "error", ud, "brutal")
        web_log(traceback.format_exc()[-1200:], "error", ud, "brutal")
    finally:
        with _task_lock:
            _tasks.pop(_task_key("brutal_generate", ud), None)


def _build_brutal_schedule_from_cfg(ud, cfg, video_files, delay_minutes=None, max_videos=None):
    delay_minutes = int(delay_minutes if delay_minutes is not None else BRUTAL_UPLOAD_DELAY_MINUTES)
    base_dt = datetime.now() + timedelta(minutes=delay_minutes)
    schedule = brutal_generate_schedule(video_files, base_date=base_dt, max_videos=max_videos)
    for item in schedule:
        item.setdefault("status", "pending")
    _save_brutal_schedule(ud, schedule)
    return schedule


def _run_brutal_upload(ud, stop_event, delay_minutes=None, max_videos=None):
    ud = int(ud)
    try:
        db = load_db()
        cfg = get_ud_config(db, ud)
        stok_files = _brutal_list_stok(ud)
        if max_videos:
            stok_files = stok_files[: int(max_videos)]
        if not stok_files:
            web_log(f"UD {ud}: stok brutal kosong.", "error", ud, "brutal")
            return
        if not cfg.get("tiktok_ud") or not cfg.get("tiktok_port"):
            web_log(f"UD {ud}: TikTok user-data atau port belum diset.", "error", ud, "brutal")
            return

        schedule = _build_brutal_schedule_from_cfg(ud, cfg, stok_files, delay_minutes, max_videos)
        if not schedule:
            web_log(f"UD {ud}: jadwal brutal kosong.", "error", ud, "brutal")
            return
        web_log(f"UD {ud}: Brutal Upload dimulai untuk {len(schedule)} video, mulai {schedule[0]['schedule']}.", "info", ud, "brutal")

        def log_fn(msg):
            text = str(msg)
            lower = text.lower()
            tag = "info"
            if "sukses" in lower or "selesai" in lower or "berhasil" in lower:
                tag = "success"
            elif "gagal" in lower or "error" in lower or "tidak" in lower:
                tag = "error"
            elif "skip" in lower or "warning" in lower:
                tag = "warn"
            web_log(text, tag, ud, "brutal")

        uploaded = upload_tiktok_batch(ud, schedule, cfg, log_fn, stop_event)
        _save_brutal_schedule(ud, schedule)
        web_log(f"UD {ud}: Brutal Upload selesai. Berhasil {uploaded}/{len(schedule)}. Sisa stok brutal {_brutal_count_stok(ud)}.", "success", ud, "brutal")
    except Exception as exc:
        web_log(f"UD {ud}: error Brutal Upload: {exc}", "error", ud, "brutal")
        web_log(traceback.format_exc()[-1200:], "error", ud, "brutal")
    finally:
        with _task_lock:
            _tasks.pop(_task_key("brutal_upload", ud), None)


def _run_brutal_pipeline(ud, stop_event, target_stok=None, delay_minutes=None, max_videos=None):
    ud = int(ud)
    try:
        web_log(f"UD {ud}: Brutal Pipeline dimulai.", "info", ud, "brutal")
        _run_brutal_generate(ud, stop_event, target_stok)
        if stop_event.is_set():
            web_log(f"UD {ud}: Brutal Pipeline dihentikan setelah generate.", "warn", ud, "brutal")
            return
        _run_brutal_upload(ud, stop_event, delay_minutes, max_videos)
        web_log(f"UD {ud}: Brutal Pipeline selesai.", "success", ud, "brutal")
    finally:
        with _task_lock:
            _tasks.pop(_task_key("brutal_pipeline", ud), None)


def _run_imagine_generate(folder_name, prompt_name, count, stop_event):
    try:
        prompts = load_prompts()
        prompt_text = prompts.get(prompt_name, "")
        if not prompt_text:
            web_log(f"Imagine: prompt '{prompt_name}' tidak ditemukan.", "error", action="imagine")
            return
        if not folder_name or not list_bahan_images(folder_name):
            web_log(f"Imagine: folder bahan '{folder_name}' kosong atau tidak ditemukan.", "error", action="imagine")
            return

        cfg = load_imagine_settings()
        video_cfg = {
            "gen_mode": cfg.get("gen_mode", "Video"),
            "resolution": cfg.get("resolution", "720p"),
            "duration": cfg.get("duration", "10s"),
            "aspect_ratio": cfg.get("aspect_ratio", "9:16"),
        }
        merge_enabled = int(cfg.get("merge_duration", 20) or 20) == 20
        count = max(1, int(count or 1))

        _imagine_state.update({
            "running": True,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "folder": folder_name,
            "prompt": prompt_name,
            "target": count,
            "generated": 0,
            "failed": 0,
            "merged": 0,
            "browser_states": {},
        })

        os.makedirs(IMAGINE_OUTPUT_DIR, exist_ok=True)
        os.makedirs(IMAGINE_MERGED_DIR, exist_ok=True)
        file_lock = threading.Lock()
        raw_pool = []
        generated_total = 0
        failed_total = 0
        merged_total = 0

        def log_fn(msg):
            text = str(msg)
            lower = text.lower()
            tag = "info"
            if "berhasil" in lower or "selesai" in lower or "merged" in lower:
                tag = "success"
            elif "gagal" in lower or "error" in lower or "rate limit" in lower:
                tag = "error"
            elif "timeout" in lower or "skip" in lower:
                tag = "warn"
            web_log(text, tag, action="imagine")

        web_log(f"Imagine: generate dimulai. Folder={folder_name}, prompt={prompt_name}, target={count}.", "info", action="imagine")

        while generated_total < count and not stop_event.is_set():
            remaining = count - generated_total
            batch_size = min(remaining, 50)
            n_browsers = min(IMAGINE_N_BROWSERS, max(1, batch_size))
            all_tasks = []
            for idx in range(batch_size):
                all_tasks.append((generated_total + idx, prompt_text, get_random_imagine_bahan_image(folder_name)))

            browser_tasks = [[] for _ in range(n_browsers)]
            base = batch_size // n_browsers
            rem = batch_size % n_browsers
            cursor = 0
            for b in range(n_browsers):
                qty = base + (1 if b < rem else 0)
                browser_tasks[b] = all_tasks[cursor:cursor + qty]
                cursor += qty

            workers = []
            for b in range(n_browsers):
                if stop_event.is_set():
                    break
                os.makedirs(IMAGINE_GROK_USER_DATA_DIRS[b], exist_ok=True)
                worker = ImagineBrowserWorker(
                    b,
                    IMAGINE_GROK_PORTS[b],
                    IMAGINE_GROK_USER_DATA_DIRS[b],
                    IMAGINE_OUTPUT_DIR,
                    log_fn,
                    stop_event,
                    file_lock,
                    video_cfg,
                    _imagine_state["browser_states"],
                )
                if worker.start():
                    workers.append(worker)
                    web_log(f"Imagine: Browser {b+1} aktif port {IMAGINE_GROK_PORTS[b]}.", "success", action="imagine")
                else:
                    web_log(f"Imagine: Browser {b+1} gagal start.", "error", action="imagine")
                time.sleep(3)

            active_workers = [w for w in workers if w.driver is not None]
            if not active_workers:
                web_log("Imagine: tidak ada browser aktif.", "error", action="imagine")
                break

            if len(active_workers) < n_browsers:
                flat = [task for group in browser_tasks for task in group]
                browser_tasks = [[] for _ in active_workers]
                base = len(flat) // len(active_workers)
                rem = len(flat) % len(active_workers)
                cursor = 0
                for b in range(len(active_workers)):
                    qty = base + (1 if b < rem else 0)
                    browser_tasks[b] = flat[cursor:cursor + qty]
                    cursor += qty

            threads = []
            for b, worker in enumerate(active_workers):
                if not browser_tasks[b]:
                    continue
                t = threading.Thread(target=worker.run_tasks, args=(browser_tasks[b],), daemon=True)
                threads.append(t)
                t.start()
            for t in threads:
                t.join()

            round_raw = []
            for worker in workers:
                round_raw.extend(worker.results)
            round_gen = sum(w.generated for w in workers)
            round_fail = sum(w.failed for w in workers)
            generated_total += round_gen
            failed_total += round_fail
            raw_pool.extend(round_raw)
            _imagine_state["generated"] = generated_total
            _imagine_state["failed"] = failed_total
            web_log(f"Imagine: round selesai {round_gen} OK, {round_fail} gagal. Total {generated_total}/{count}.", "success", action="imagine")

            for worker in workers:
                try:
                    worker.shutdown()
                except Exception:
                    pass

            if merge_enabled:
                while len(raw_pool) >= 2 and not stop_event.is_set():
                    vid_a = raw_pool.pop(0)
                    vid_b = raw_pool.pop(0)
                    if not (os.path.exists(vid_a) and os.path.exists(vid_b)):
                        continue
                    merged_path = imagine_merge_video_pair(vid_a, vid_b, IMAGINE_MERGED_DIR, log_fn)
                    if merged_path:
                        merged_total += 1
                        _imagine_state["merged"] = merged_total
            if round_gen == 0:
                break

        web_log(f"Imagine: generate selesai. Berhasil {generated_total}, gagal {failed_total}, merged {merged_total}.", "success", action="imagine")
    except Exception as exc:
        web_log(f"Imagine error: {exc}", "error", action="imagine")
        web_log(traceback.format_exc()[-1200:], "error", action="imagine")
    finally:
        _imagine_state["running"] = False
        _imagine_state["stop_event"] = None
        _imagine_state["thread"] = None


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/status")
def api_status():
    return jsonify(_status_payload())


@app.route("/api/config", methods=["POST"])
def api_config():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    if not 1 <= ud <= MAX_UD:
        return jsonify({"ok": False, "msg": "UD tidak valid"}), 400
    db = load_db()
    cfg = _cfg_for_save(db, ud)

    fields = [
        "prompt_name",
        "bahan_folder",
        "deskripsi",
        "nama_produk_radio",
        "nama_produk_input",
        "tiktok_port",
        "grok_port",
    ]
    for field in fields:
        if field in data:
            cfg[field] = str(data.get(field) or "").strip()

    if "hashtags" in data:
        cfg["hashtags"] = _parse_hashtags(data.get("hashtags"))
    if "nama_produk_radio_list" in data:
        cfg["nama_produk_radio_list"] = [x.strip() for x in str(data.get("nama_produk_radio_list") or "").split("\n") if x.strip()]
    if "add_product" in data:
        cfg["add_product"] = bool(data.get("add_product"))
    if "add_sound" in data:
        cfg["add_sound"] = bool(data.get("add_sound"))
    if "interval_hours" in data:
        cfg["interval_hours"] = max(1, int(data.get("interval_hours") or 1))
    if "batch_size" in data:
        cfg["batch_size"] = max(1, int(data.get("batch_size") or 1))
    if "tiktok_ud" in data:
        cfg["tiktok_ud"] = resolve_ud_path(str(data.get("tiktok_ud") or ""))
    if "grok_ud" in data:
        cfg["grok_ud"] = resolve_ud_path(str(data.get("grok_ud") or ""))
    if "schedule" in data and isinstance(data["schedule"], dict):
        sched = data["schedule"]
        cfg["schedule"] = {
            "tanggal": str(sched.get("tanggal") or "").strip(),
            "jam": str(sched.get("jam") or "00").zfill(2),
            "menit": str(sched.get("menit") or "00").zfill(2),
        }

    save_db(db)
    web_log(f"UD {ud}: konfigurasi disimpan.", "success", ud, "config")
    return jsonify({"ok": True, "config": _public_cfg(db, ud)})


@app.route("/api/active_ud", methods=["POST"])
def api_active_ud():
    data = request.get_json(force=True) or {}
    uds = _parse_ud_list(data.get("uds", []))
    db = load_db()
    db["active_ud"] = uds
    save_db(db)
    web_log(f"Active UD disimpan: {', '.join(map(str, uds)) or '-'}", "success", None, "config")
    return jsonify({"ok": True, "active_uds": uds})


@app.route("/api/action/generate", methods=["POST"])
def api_generate():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    needed = data.get("needed")

    def target(stop_event):
        _run_generate(ud, stop_event, needed)

    ok, msg = _start_task("generate", ud, target)
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/action/upload", methods=["POST"])
def api_upload():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    ok, msg = _start_task("upload", ud, lambda stop_event: _run_upload(ud, stop_event))
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/action/pipeline", methods=["POST"])
def api_pipeline():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    ok, msg = _start_task("pipeline", ud, lambda stop_event: _run_pipeline(ud, stop_event))
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/brutal/generate", methods=["POST"])
def api_brutal_generate():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    target_stok = int(data.get("target_stok") or BRUTAL_MAX_STOK)
    ok, msg = _start_task("brutal_generate", ud, lambda stop_event: _run_brutal_generate(ud, stop_event, target_stok))
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/brutal/upload", methods=["POST"])
def api_brutal_upload():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    delay_minutes = int(data.get("delay_minutes") or BRUTAL_UPLOAD_DELAY_MINUTES)
    max_videos = int(data.get("max_videos") or BRUTAL_MAX_STOK)
    ok, msg = _start_task("brutal_upload", ud, lambda stop_event: _run_brutal_upload(ud, stop_event, delay_minutes, max_videos))
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/brutal/pipeline", methods=["POST"])
def api_brutal_pipeline():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    target_stok = int(data.get("target_stok") or BRUTAL_MAX_STOK)
    delay_minutes = int(data.get("delay_minutes") or BRUTAL_UPLOAD_DELAY_MINUTES)
    max_videos = int(data.get("max_videos") or target_stok)
    ok, msg = _start_task(
        "brutal_pipeline",
        ud,
        lambda stop_event: _run_brutal_pipeline(ud, stop_event, target_stok, delay_minutes, max_videos),
    )
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/brutal/merge", methods=["POST"])
def api_brutal_merge():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    merged = _brutal_merge_leftover_raw(ud, lambda m: web_log(m, "info", ud, "brutal"))
    return jsonify({"ok": True, "merged": len(merged), "stok": _brutal_count_stok(ud)})


@app.route("/api/brutal/clear", methods=["POST"])
def api_brutal_clear():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    removed = 0
    for name in os.listdir(_brutal_stok_dir(ud)):
        path = os.path.join(_brutal_stok_dir(ud), name)
        if os.path.isfile(path) and name.lower().endswith(".mp4"):
            os.remove(path)
            removed += 1
    web_log(f"UD {ud}: stok brutal dikosongkan ({removed} file).", "warn", ud, "brutal")
    return jsonify({"ok": True, "removed": removed})


@app.route("/api/imagine/settings", methods=["GET", "POST"])
def api_imagine_settings():
    if request.method == "GET":
        return jsonify({"ok": True, "settings": load_imagine_settings()})
    data = request.get_json(force=True) or {}
    cfg = load_imagine_settings()
    for key in ("gen_mode", "resolution", "duration", "aspect_ratio"):
        if key in data:
            cfg[key] = str(data.get(key) or "").strip()
    if "merge_duration" in data:
        cfg["merge_duration"] = int(data.get("merge_duration") or 10)
    save_imagine_settings(cfg)
    web_log("Imagine: konfigurasi disimpan.", "success", action="imagine")
    return jsonify({"ok": True, "settings": cfg})


@app.route("/api/imagine/generate", methods=["POST"])
def api_imagine_generate():
    data = request.get_json(force=True) or {}
    if _imagine_state.get("running"):
        return jsonify({"ok": False, "msg": "Imagine generate sudah berjalan"})
    folder = str(data.get("folder") or "").strip()
    prompt = str(data.get("prompt") or "").strip()
    count = int(data.get("count") or 1)
    stop_event = threading.Event()
    thread = threading.Thread(target=_run_imagine_generate, args=(folder, prompt, count, stop_event), daemon=True)
    _imagine_state["running"] = True
    _imagine_state["stop_event"] = stop_event
    _imagine_state["thread"] = thread
    thread.start()
    return jsonify({"ok": True})


@app.route("/api/imagine/stop", methods=["POST"])
def api_imagine_stop():
    if _imagine_state.get("stop_event"):
        _imagine_state["stop_event"].set()
    web_log("Imagine: stop diminta.", "warn", action="imagine")
    return jsonify({"ok": True})


@app.route("/api/imagine/files")
def api_imagine_files():
    kind = request.args.get("kind", "all")
    downloaded = request.args.get("downloaded", "all")
    items = _imagine_file_items()
    if kind in ("raw", "merged"):
        items = [x for x in items if x["kind"] == kind]
    if downloaded == "yes":
        items = [x for x in items if x["downloaded"]]
    elif downloaded == "no":
        items = [x for x in items if not x["downloaded"]]
    return jsonify({"ok": True, "files": items})


@app.route("/api/imagine/media/<kind>/<name>")
def api_imagine_media(kind, name):
    try:
        _, _, path = _safe_imagine_path(f"{kind}/{name}")
    except Exception:
        return jsonify({"ok": False, "msg": "file tidak valid"}), 400
    if not os.path.exists(path):
        return jsonify({"ok": False, "msg": "file tidak ditemukan"}), 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.route("/api/imagine/download/<kind>/<name>")
def api_imagine_download(kind, name):
    try:
        safe_kind, safe_name, path = _safe_imagine_path(f"{kind}/{name}")
    except Exception:
        return jsonify({"ok": False, "msg": "file tidak valid"}), 400
    if not os.path.exists(path):
        return jsonify({"ok": False, "msg": "file tidak ditemukan"}), 404
    _mark_imagine_downloaded([f"{safe_kind}/{safe_name}"], True)
    return send_file(path, as_attachment=True, download_name=safe_name, mimetype="video/mp4")


@app.route("/api/imagine/download_zip", methods=["POST"])
def api_imagine_download_zip():
    data = request.get_json(force=True) or {}
    file_ids = data.get("files") or []
    safe_files = []
    for fid in file_ids:
        try:
            kind, name, path = _safe_imagine_path(fid)
            if os.path.exists(path):
                safe_files.append((f"{kind}/{name}", kind, name, path))
        except Exception:
            continue
    if not safe_files:
        return jsonify({"ok": False, "msg": "Tidak ada file valid"}), 400
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", dir=APP_DIR)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        for fid, kind, name, path in safe_files:
            zf.write(path, arcname=os.path.join(kind, name))
    _mark_imagine_downloaded([x[0] for x in safe_files], True)
    return send_file(tmp.name, as_attachment=True, download_name=f"grok_imagine_{int(time.time())}.zip", mimetype="application/zip")


@app.route("/api/imagine/mark", methods=["POST"])
def api_imagine_mark():
    data = request.get_json(force=True) or {}
    file_ids = data.get("files") or []
    downloaded = bool(data.get("downloaded", True))
    _mark_imagine_downloaded(file_ids, downloaded)
    return jsonify({"ok": True})


@app.route("/api/imagine/delete", methods=["POST"])
def api_imagine_delete():
    data = request.get_json(force=True) or {}
    file_ids = data.get("files") or []
    removed = 0
    for fid in file_ids:
        try:
            _, _, path = _safe_imagine_path(fid)
        except Exception:
            continue
        if os.path.exists(path):
            os.remove(path)
            removed += 1
    web_log(f"Imagine: {removed} file dihapus dari galeri.", "warn", action="imagine")
    return jsonify({"ok": True, "removed": removed})



@app.route("/api/auto/start", methods=["POST"])
def api_auto_start():
    if _auto_state.get("running"):
        return jsonify({"ok": False, "msg": "Already running"})
    stop_evt = threading.Event()
    t = threading.Thread(target=_full_auto_daemon, args=(stop_evt,), daemon=True)
    _auto_state["running"] = True
    _auto_state["stop_event"] = stop_evt
    _auto_state["thread"] = t
    t.start()
    return jsonify({"ok": True})

@app.route("/api/auto/stop", methods=["POST"])
def api_auto_stop():
    if _auto_state.get("stop_event"):
        _auto_state["stop_event"].set()
    _auto_state["running"] = False
    return jsonify({"ok": True})

@app.route("/api/prompts", methods=["GET", "POST", "DELETE"])
def api_prompts():
    if request.method == "GET":
        return jsonify({"ok": True, "prompts": load_prompts()})
    elif request.method == "POST":
        data = request.get_json(force=True) or {}
        name = data.get("name")
        text = data.get("text")
        if not name or not text: return jsonify({"ok": False, "msg": "Nama dan Teks diperlukan"}), 400
        p = load_prompts()
        p[name] = text
        save_prompts(p)
        web_log(f"Prompt '{name}' disimpan.", "success", action="config")
        return jsonify({"ok": True})
    elif request.method == "DELETE":
        data = request.get_json(force=True) or {}
        name = data.get("name")
        p = load_prompts()
        if name in p:
            del p[name]
            save_prompts(p)
            web_log(f"Prompt '{name}' dihapus.", "warn", action="config")
        return jsonify({"ok": True})

import werkzeug
@app.route("/api/bahan", methods=["GET", "POST"])
def api_bahan():
    if request.method == "GET":
        folders = list_bahan_folders()
        data = {}
        for f in folders:
            data[f] = len(list_bahan_images(f))
        return jsonify({"ok": True, "folders": data})
    elif request.method == "POST":
        folder_name = request.form.get("name")
        if not folder_name: return jsonify({"ok": False, "msg": "Nama folder diperlukan"}), 400
        safe_name = werkzeug.utils.secure_filename(folder_name)
        folder_path = os.path.join(BAHAN_DIR, safe_name)
        os.makedirs(folder_path, exist_ok=True)
        files = request.files.getlist("files")
        saved = 0
        for f in files:
            if f.filename:
                fn = werkzeug.utils.secure_filename(f.filename)
                f.save(os.path.join(folder_path, fn))
                saved += 1
        msg = f"Folder '{safe_name}' ditambahkan dengan {saved} file gambar." if saved else f"Folder '{safe_name}' berhasil dibuat."
        web_log(msg, "success", action="config")
        return jsonify({"ok": True, "msg": msg})

@app.route("/api/action/stop", methods=["POST"])
def api_stop():
    data = request.get_json(force=True) or {}
    ud = data.get("ud")
    action = data.get("action")
    stopped = []
    with _task_lock:
        for key, task in list(_tasks.items()):
            if ud not in (None, "", "all") and int(task.get("ud")) != int(ud):
                continue
            if action not in (None, "", "all") and task.get("action") != action:
                continue
            task["stop_event"].set()
            stopped.append(key)
    web_log(f"Stop diminta: {', '.join(stopped) or 'tidak ada task aktif'}", "warn", ud, "stop")
    return jsonify({"ok": True, "stopped": stopped})


@app.route("/api/stok/clear", methods=["POST"])
def api_clear_stok():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    d = stok_dir(ud)
    removed = 0
    for name in os.listdir(d):
        path = os.path.join(d, name)
        if os.path.isfile(path) and name.lower().endswith(".mp4"):
            os.remove(path)
            removed += 1
    web_log(f"UD {ud}: stok dikosongkan ({removed} file).", "warn", ud, "stok")
    return jsonify({"ok": True, "removed": removed})


@app.route("/api/raw/merge", methods=["POST"])
def api_merge_raw():
    data = request.get_json(force=True) or {}
    ud = int(data.get("ud", 1))
    merged = merge_leftover_raw(ud, lambda m: web_log(m, "info", ud, "generate"))
    return jsonify({"ok": True, "merged": len(merged), "stok": count_stok(ud)})


@app.route("/api/logs")
def api_logs():
    def stream():
        q = deque(maxlen=100)
        with _log_lock:
            for entry in _log_buffer:
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
            _log_subscribers.append(q)
        try:
            while True:
                if q:
                    yield f"data: {json.dumps(q.popleft(), ensure_ascii=False)}\n\n"
                else:
                    time.sleep(0.5)
                    yield ": keepalive\n\n"
        except GeneratorExit:
            with _log_lock:
                if q in _log_subscribers:
                    _log_subscribers.remove(q)

    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = os.path.join(APP_DIR, "user_data")
PARENT_PROFILE_DIR = os.path.join(USER_DATA_DIR, "parent")

@app.route("/api/udmgr/folders", methods=["GET"])
def api_udmgr_folders():
    folders = []
    if os.path.isdir(USER_DATA_DIR):
        for name in sorted(os.listdir(USER_DATA_DIR)):
            full = os.path.join(USER_DATA_DIR, name)
            if os.path.isdir(full) and name.lower() != "parent":
                folders.append(name)
    return jsonify({"ok": True, "folders": folders})

@app.route("/api/udmgr/create", methods=["POST"])
def api_udmgr_create():
    data = request.get_json(force=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "msg": "Nama diperlukan"})
    import werkzeug
    safe_name = werkzeug.utils.secure_filename(name)
    path = os.path.join(USER_DATA_DIR, safe_name)
    os.makedirs(path, exist_ok=True)
    web_log(f"UD Manager: Folder '{safe_name}' dibuat.", "success", action="udmgr")
    return jsonify({"ok": True, "msg": f"Folder {safe_name} dibuat"})

import subprocess
@app.route("/api/udmgr/chrome_parent", methods=["POST"])
def api_udmgr_chrome_parent():
    if not os.path.exists(CHROME_EXE):
        return jsonify({"ok": False, "msg": f"Chrome tidak ditemukan: {CHROME_EXE}"})
    cmd = [CHROME_EXE, "--remote-debugging-port=9222", f"--user-data-dir={PARENT_PROFILE_DIR}"]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        web_log("UD Manager: Chrome Parent diluncurkan (port 9222).", "success", action="udmgr")
        return jsonify({"ok": True})
    except Exception as e:
        web_log(f"UD Manager: Gagal meluncurkan Chrome Parent: {e}", "error", action="udmgr")
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/udmgr/chrome", methods=["POST"])
def api_udmgr_chrome():
    data = request.get_json(force=True) or {}
    folder = str(data.get("folder") or "").strip()
    if not folder:
        return jsonify({"ok": False, "msg": "Folder tidak ditentukan"})
    if not os.path.exists(CHROME_EXE):
        return jsonify({"ok": False, "msg": f"Chrome tidak ditemukan: {CHROME_EXE}"})
    ud_path = os.path.join(USER_DATA_DIR, folder)
    cmd = [CHROME_EXE, f"--user-data-dir={ud_path}"]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        web_log(f"UD Manager: Chrome diluncurkan untuk '{folder}'.", "success", action="udmgr")
        return jsonify({"ok": True})
    except Exception as e:
        web_log(f"UD Manager: Gagal meluncurkan Chrome untuk '{folder}': {e}", "error", action="udmgr")
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/udmgr/duplicate", methods=["POST"])
def api_udmgr_duplicate():
    data = request.get_json(force=True) or {}
    folders = data.get("folders", [])
    if not folders:
        return jsonify({"ok": False, "msg": "Tidak ada folder yang dipilih"})
    
    src_default = os.path.join(PARENT_PROFILE_DIR, "Default")
    src_local_state = os.path.join(PARENT_PROFILE_DIR, "Local State")
    if not os.path.isdir(src_default) or not os.path.isfile(src_local_state):
        return jsonify({"ok": False, "msg": "Default / Local State tidak ditemukan di parent profile!"})
        
    def do_copy():
        import shutil
        success = 0
        for folder in folders:
            dest_dir = os.path.join(USER_DATA_DIR, folder)
            dest_default = os.path.join(dest_dir, "Default")
            dest_local_state = os.path.join(dest_dir, "Local State")
            try:
                if os.path.exists(dest_default):
                    shutil.rmtree(dest_default)
                shutil.copytree(src_default, dest_default)
                shutil.copy2(src_local_state, dest_local_state)
                success += 1
                web_log(f"UD Manager: Duplikasi berhasil ke '{folder}'", "success", action="udmgr")
            except Exception as e:
                web_log(f"UD Manager: Gagal duplikasi ke '{folder}': {e}", "error", action="udmgr")
        web_log(f"UD Manager: Selesai duplikasi {success}/{len(folders)}", "success", action="udmgr")

    threading.Thread(target=do_copy, daemon=True).start()
    return jsonify({"ok": True, "msg": "Proses duplikasi dimulai..."})


INDEX_HTML = r"""
<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Grok TikTok Control</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #637083;
      --line: #d9e0ea;
      --brand: #1769aa;
      --ok: #16824a;
      --warn: #a86600;
      --err: #b42318;
      --shadow: 0 8px 26px rgba(27, 39, 55, .08);
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Segoe UI, Arial, sans-serif; background: var(--bg); color: var(--text); }
    header { height: 58px; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; border-bottom: 1px solid var(--line); background: #fff; position: sticky; top: 0; z-index: 10; }
    h1 { margin: 0; font-size: 18px; font-weight: 700; letter-spacing: 0; }
    .top { display: flex; gap: 10px; align-items: center; color: var(--muted); font-size: 13px; }
    main { display: grid; grid-template-columns: 280px minmax(0, 1fr) 430px; gap: 14px; padding: 14px; min-height: calc(100vh - 58px); }
    section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); min-width: 0; }
    .left, .center, .right { overflow: hidden; }
    .section-head { padding: 14px 14px 10px; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; align-items: center; gap: 10px; }
    h2 { margin: 0; font-size: 15px; }
    .body { padding: 14px; }
    .ud-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .ud-btn { border: 1px solid var(--line); background: #fff; color: var(--text); height: 42px; border-radius: 6px; cursor: pointer; font-weight: 700; }
    .ud-btn.active { border-color: var(--brand); background: #e8f2fb; color: #0f548c; }
    .ud-btn.enabled { box-shadow: inset 0 -3px 0 var(--ok); }
    .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; }
    .stat { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; }
    .stat small { display: block; color: var(--muted); font-size: 12px; }
    .stat strong { font-size: 20px; }
    label { display: block; font-size: 12px; color: var(--muted); margin: 10px 0 5px; }
    input, select, textarea { width: 100%; border: 1px solid var(--line); border-radius: 6px; padding: 9px 10px; font: inherit; background: #fff; color: var(--text); }
    textarea { min-height: 82px; resize: vertical; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .row3 { display: grid; grid-template-columns: 1.2fr .7fr .7fr; gap: 10px; }
    .checks { display: flex; gap: 12px; margin-top: 10px; align-items: center; flex-wrap: wrap; }
    .check { display: flex; gap: 6px; align-items: center; color: var(--text); font-size: 13px; }
    .check input { width: auto; }
    .actions { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 14px; }
    button { border: 1px solid transparent; background: var(--brand); color: #fff; min-height: 38px; border-radius: 6px; padding: 8px 10px; cursor: pointer; font-weight: 700; }
    button.secondary { background: #fff; color: var(--brand); border-color: #b9d2e7; }
    button.warn { background: var(--warn); }
    button.danger { background: var(--err); }
    button:disabled { opacity: .45; cursor: not-allowed; }
    .active-line { display: flex; gap: 8px; margin-top: 12px; }
    .active-line input { flex: 1; }
    .log { height: calc(100vh - 135px); overflow: auto; background: #101820; color: #d8e2ee; padding: 10px; font: 12px Consolas, monospace; }
    .log-line { padding: 4px 2px; border-bottom: 1px solid rgba(255,255,255,.05); white-space: pre-wrap; overflow-wrap: anywhere; }
    .log-line.success { color: #87e0a8; }
    .log-line.error { color: #ffaaa3; }
    .log-line.warn { color: #ffd083; }
    .muted { color: var(--muted); font-size: 12px; }
    .pill { display: inline-flex; align-items: center; height: 24px; padding: 0 9px; border-radius: 999px; background: #edf2f7; color: #42526b; font-size: 12px; font-weight: 700; }
    .pill.run { background: #fff4d6; color: #815500; }
    .file-list { margin-top: 8px; border: 1px solid var(--line); border-radius: 6px; max-height: 130px; overflow: auto; padding: 7px 9px; background: #fbfcfe; font-size: 12px; color: var(--muted); }
    .file-list div { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 2px 0; }
    .gallery-tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 12px 0; }
    .gallery-tools select, .gallery-tools input { width: auto; min-width: 130px; }
    .gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; max-height: 520px; overflow: auto; padding-right: 4px; }
    .media-card { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; overflow: hidden; }
    .media-card.downloaded { border-color: #8bd0aa; background: #f4fbf7; }
    .media-card video { width: 100%; aspect-ratio: 9 / 16; object-fit: cover; display: block; background: #0b1118; }
    .media-meta { padding: 8px; font-size: 12px; color: var(--muted); }
    .media-meta strong { color: var(--text); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .media-actions { display: flex; gap: 6px; padding: 0 8px 8px; }
    .media-actions a, .media-actions button { min-height: 30px; padding: 5px 7px; font-size: 12px; text-decoration: none; display: inline-flex; align-items: center; border-radius: 6px; }
    .media-check { position: absolute; margin: 7px; width: 18px; height: 18px; }
    .browser-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; margin: 10px 0; }
    .browser-box { border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: #fbfcfe; font-size: 12px; }
    .progress-track { height: 7px; background: #e5ebf2; border-radius: 99px; overflow: hidden; margin-top: 6px; }
    .progress-fill { height: 100%; background: var(--brand); width: 0%; }
    @media (max-width: 1180px) { main { grid-template-columns: 230px minmax(0, 1fr); } .right { grid-column: 1 / -1; } .log { height: 320px; } }
    @media (max-width: 760px) { main { grid-template-columns: 1fr; } .stats, .actions, .row, .row3 { grid-template-columns: 1fr; } header { align-items: flex-start; height: auto; padding: 12px; flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <h1>Grok TikTok Control</h1>
    <div class="top">
      <span id="serverState">Memuat...</span>
      <button class="secondary" onclick="refresh()">Refresh</button>
    </div>
  </header>
  <main>
    <section class="left">
      <div class="section-head"><h2>UD</h2><span class="pill" id="selectedPill">UD 1</span></div>
      <div class="body">
        <div class="ud-grid" id="udGrid"></div>
        <label>Active UD</label>
        <div class="active-line">
          <input id="activeInput" placeholder="1,2,3">
          <button onclick="saveActive()">Simpan</button>
        </div>
        <p class="muted">Tombol bergaris hijau berarti UD aktif di database.</p>
      </div>
    </section>

    <section class="center">
      <div class="section-head" style="display:flex; justify-content:space-between; align-items:center; gap: 10px; border-bottom: 0;">
        <div style="display:flex; gap: 10px;">
          <button id="tabSettingsBtn" onclick="switchTab('settings')" style="background:var(--brand);">Settings UD</button>
          <button id="tabResourcesBtn" onclick="switchTab('resources')" class="secondary">Prompt & Bahan</button>
          <button id="tabBrutalBtn" onclick="switchTab('brutal')" class="secondary">Brutal Bot</button>
          <button id="tabImagineBtn" onclick="switchTab('imagine')" class="secondary">Grok Imagine</button>
          <button id="tabUdMgrBtn" onclick="switchTab('udmgr')" class="secondary">Manajemen UD</button>
        </div>
        <div style="display:flex; gap: 10px; align-items:center;">
          <label style="margin:0; font-weight:bold; color:var(--brand); white-space:nowrap;"><input type="checkbox" id="autoSwitch" onchange="toggleAuto()" style="width:auto; vertical-align:middle; margin-right:5px;"> Full Auto (All Active UDs)</label>
        </div>
      </div>
      
      <!-- RESOURCES TAB -->
      <div id="tabResources" class="body" style="display:none; border-top: 1px solid var(--line);">
         <h3 style="margin-top:0;">Daftar Prompt</h3>
         <div class="row">
           <div>
             <input id="newPromptName" placeholder="Nama Prompt">
           </div>
           <div>
             <button onclick="saveNewPrompt()">Simpan</button>
             <button class="danger" onclick="deletePrompt()">Hapus</button>
           </div>
         </div>
         <textarea id="newPromptText" placeholder="Isi prompt..." style="margin-top:10px;"></textarea>
         <div class="file-list" id="promptList" style="max-height: 150px; margin-bottom: 20px;"></div>
         
         <h3>Daftar Bahan</h3>
         <div class="row">
           <div>
             <input id="newBahanName" placeholder="Nama Folder Bahan Baru">
             <input type="file" id="newBahanFiles" multiple accept="image/*" style="margin-top:5px;">
           </div>
           <div>
             <button onclick="saveBahan()">Buat / Upload Bahan</button>
           </div>
         </div>
         <div class="file-list" id="bahanList" style="max-height: 150px;"></div>
      </div>

      <!-- BRUTAL TAB -->
      <div id="tabBrutal" class="body" style="display:none; border-top: 1px solid var(--line);">
        <div class="section-head" style="border:0; padding:0 0 12px 0;">
          <h2 id="brutalTitle">Brutal Bot UD 1</h2>
          <span class="pill" id="brutalRunPill">idle</span>
        </div>
        <div class="stats">
          <div class="stat"><small>Brutal Stok</small><strong id="brutalStokCount">0</strong></div>
          <div class="stat"><small>Brutal Raw</small><strong id="brutalRawCount">0</strong></div>
          <div class="stat"><small>Brutal Schedule</small><strong id="brutalSchedCount">0</strong></div>
          <div class="stat"><small>UD Target</small><strong id="brutalUdLabel">1</strong></div>
        </div>
        <div class="row3">
          <div>
            <label>Target Stok Brutal</label>
            <input id="brutalTargetStok" type="number" min="1" value="50">
          </div>
          <div>
            <label>Upload Delay (menit)</label>
            <input id="brutalDelayMinutes" type="number" min="0" value="30">
          </div>
          <div>
            <label>Max Upload</label>
            <input id="brutalMaxVideos" type="number" min="1" value="50">
          </div>
        </div>
        <p class="muted">
          Brutal Bot memakai prompt, bahan, description, hashtag, produk, TikTok UD/port, dan Grok UD/port dari konfigurasi UD yang sedang dipilih. Stoknya disimpan terpisah di folder brutal per UD.
        </p>
        <div class="actions">
          <button onclick="saveConfig()">Simpan Config UD</button>
          <button onclick="runBrutal('generate')">Brutal Generate</button>
          <button onclick="runBrutal('upload')">Brutal Upload</button>
          <button onclick="runBrutal('pipeline')">Brutal Pipeline</button>
          <button class="secondary" onclick="mergeBrutalRaw()">Merge Raw</button>
          <button class="warn" onclick="stopUd()">Stop UD</button>
          <button class="danger" onclick="clearBrutalStok()">Clear Brutal</button>
          <button class="secondary" onclick="refresh()">Reload</button>
        </div>
        <label>Preview stok brutal</label>
        <div class="file-list" id="brutalStokPreview"></div>
      </div>

      <!-- IMAGINE TAB -->
      <div id="tabImagine" class="body" style="display:none; border-top: 1px solid var(--line);">
        <div class="section-head" style="border:0; padding:0 0 12px 0;">
          <h2>Grok Imagine Web</h2>
          <span class="pill" id="imagineRunPill">idle</span>
        </div>
        <div class="stats">
          <div class="stat"><small>Generated</small><strong id="imagineGenerated">0</strong></div>
          <div class="stat"><small>Failed</small><strong id="imagineFailed">0</strong></div>
          <div class="stat"><small>Merged</small><strong id="imagineMerged">0</strong></div>
          <div class="stat"><small>Downloaded</small><strong id="imagineDownloaded">0</strong></div>
        </div>
        <div class="row3">
          <div>
            <label>Folder Bahan</label>
            <select id="imagineFolder"></select>
          </div>
          <div>
            <label>Prompt</label>
            <select id="imaginePrompt"></select>
          </div>
          <div>
            <label>Jumlah Generate</label>
            <input id="imagineCount" type="number" min="1" value="10">
          </div>
        </div>
        <div class="row">
          <div>
            <label>Mode / Resolusi / Durasi</label>
            <div class="row3">
              <select id="imagineMode"><option>Video</option><option>Image</option></select>
              <select id="imagineResolution"><option>720p</option><option>1080p</option></select>
              <select id="imagineDuration"><option>10s</option><option>5s</option></select>
            </div>
          </div>
          <div>
            <label>Aspect / Merge</label>
            <div class="row">
              <select id="imagineAspect"><option>9:16</option><option>16:9</option><option>1:1</option></select>
              <select id="imagineMerge"><option value="20">Gabung 2 video</option><option value="10">Tanpa gabung</option></select>
            </div>
          </div>
        </div>
        <div class="actions">
          <button onclick="saveImagineSettings()">Simpan Config</button>
          <button onclick="startImagine()">Generate Imagine</button>
          <button class="warn" onclick="stopImagine()">Stop Imagine</button>
          <button class="secondary" onclick="loadImagineFiles()">Reload Galeri</button>
          <button onclick="downloadSelectedImagine()">Download Selected</button>
          <button class="secondary" onclick="markSelectedImagine(true)">Mark Downloaded</button>
          <button class="secondary" onclick="markSelectedImagine(false)">Unmark</button>
          <button class="danger" onclick="deleteSelectedImagine()">Delete Selected</button>
        </div>
        <div class="browser-grid" id="imagineBrowsers"></div>
        <div class="gallery-tools">
          <select id="imagineKindFilter" onchange="loadImagineFiles()">
            <option value="all">Semua file</option>
            <option value="merged">Merged</option>
            <option value="raw">Raw</option>
          </select>
          <select id="imagineDownloadedFilter" onchange="loadImagineFiles()">
            <option value="all">Semua status</option>
            <option value="no">Belum downloaded</option>
            <option value="yes">Sudah downloaded</option>
          </select>
          <button class="secondary" onclick="selectAllImagine(true)">Select All</button>
          <button class="secondary" onclick="selectAllImagine(false)">Clear Select</button>
          <span class="muted" id="imagineGalleryInfo">0 file</span>
        </div>
        <div class="gallery" id="imagineGallery"></div>
      </div>

      <!-- UDMGR TAB -->
      <div id="tabUdmgr" class="body" style="display:none; border-top: 1px solid var(--line);">
        <div class="section-head" style="border:0; padding:0 0 12px 0;">
          <h2>Manajemen Chrome UD</h2>
        </div>
        <div class="actions" style="margin-bottom:20px;">
          <button onclick="launchUdmgrChromeParent()" style="background:#ffa502; color:#17202a;">🔑 Login Chrome (Parent)</button>
          <button onclick="duplicateUdmgrProfile()" style="background:#6c5ce7;">📋 Duplicate Default+LocalState</button>
        </div>
        
        <h3 style="margin-top:0;">Buat UD Baru</h3>
        <div class="row">
          <div><input id="newUdName" placeholder="Contoh: 1, grok1, dll" /></div>
          <div><button onclick="createUdmgrFolder()">Buat UD</button></div>
        </div>

        <h3 style="margin-top:20px;">Daftar Profil UD</h3>
        <div class="gallery-tools">
          <button class="secondary" onclick="selectAllUdmgr(true)">Select All</button>
          <button class="secondary" onclick="selectAllUdmgr(false)">Clear Select</button>
        </div>
        <div class="browser-grid" id="udmgrFolders" style="margin-top:10px;"></div>
      </div>

      <!-- SETTINGS TAB -->
      <div id="tabSettings" style="display:block; border-top: 1px solid var(--line);">
        <div class="section-head" style="border-top: none;">
          <h2 id="configTitle">Konfigurasi UD 1</h2>
        <span class="pill" id="runPill">idle</span>
      </div>
      <div class="body">
        <div class="stats">
          <div class="stat"><small>Stok</small><strong id="stokCount">0</strong></div>
          <div class="stat"><small>Raw</small><strong id="rawCount">0</strong></div>
          <div class="stat"><small>Schedule</small><strong id="schedCount">0</strong></div>
          <div class="stat"><small>Batch</small><strong id="batchCount">0</strong></div>
        </div>
        <div class="row">
          <div>
            <label>Prompt</label>
            <select id="promptName"></select>
          </div>
          <div>
            <label>Bahan Folder</label>
            <select id="bahanFolder"></select>
          </div>
        </div>
        <label>Description per UD</label>
        <textarea id="deskripsi" placeholder="Caption/deskripsi TikTok"></textarea>
        <label>Hashtag per UD</label>
        <textarea id="hashtags" placeholder="#fyp, #viral"></textarea>
        <div class="row">
          <div>
            <label>Nama Produk Input</label>
            <input id="namaProdukInput">
          </div>
          <div>
            <label>Produk Radio Default</label>
            <input id="namaProdukRadio">
          </div>
        </div>
        <label>Produk Radio List (satu per baris)</label>
        <textarea id="produkRadioList"></textarea>
        <div class="row">
          <div>
            <label>TikTok User Data</label>
            <input id="tiktokUd">
          </div>
          <div>
            <label>TikTok Port</label>
            <input id="tiktokPort">
          </div>
        </div>
        <div class="row">
          <div>
            <label>Grok User Data</label>
            <input id="grokUd">
          </div>
          <div>
            <label>Grok Port</label>
            <input id="grokPort">
          </div>
        </div>
        <div class="row3">
          <div>
            <label>Tanggal Schedule</label>
            <input id="schedDate" type="date">
          </div>
          <div>
            <label>Jam</label>
            <input id="schedHour" type="number" min="0" max="23">
          </div>
          <div>
            <label>Menit</label>
            <input id="schedMinute" type="number" min="0" max="59">
          </div>
        </div>
        <div class="row">
          <div>
            <label>Interval Upload (jam)</label>
            <input id="intervalHours" type="number" min="1">
          </div>
          <div>
            <label>Batch Size</label>
            <input id="batchSize" type="number" min="1">
          </div>
        </div>
        <div class="checks">
          <label class="check"><input id="addProduct" type="checkbox"> Add product</label>
          <label class="check"><input id="addSound" type="checkbox"> Add sound</label>
        </div>
        <div class="actions">
          <button onclick="saveConfig()">Simpan</button>
          <button onclick="runAction('generate')">Generate</button>
          <button onclick="runAction('upload')">Upload</button>
          <button onclick="runAction('pipeline')">Gen+Upload</button>
          <button class="secondary" onclick="mergeRaw()">Merge Raw</button>
          <button class="warn" onclick="stopUd()">Stop UD</button>
          <button class="danger" onclick="clearStok()">Clear Stok</button>
          <button class="secondary" onclick="refresh()">Reload</button>
        </div>
        <label>Preview stok</label>
        <div class="file-list" id="stokPreview"></div>
      </div>
      </div>
    </section>

    <section class="right">
      <div class="section-head"><h2>Live Log</h2><button class="secondary" onclick="clearLog()">Clear View</button></div>
      <div class="log" id="log"></div>
    </section>
  </main>

<script>
let state = null;
let selectedUd = 1;
let imagineFiles = [];
const $ = (id) => document.getElementById(id);
let _activeLoaded = false;

function tagText(tag) {
  return tag === 'success' ? 'OK' : tag === 'error' ? 'ERR' : tag === 'warn' ? 'WARN' : 'INFO';
}

function appendLog(entry) {
  const line = document.createElement('div');
  line.className = 'log-line ' + (entry.tag || 'info');
  const ud = entry.ud ? ` UD${entry.ud}` : '';
  const action = entry.action ? ` ${entry.action}` : '';
  line.textContent = `[${entry.ts}] [${tagText(entry.tag)}${ud}${action}] ${entry.msg}`;
  $('log').appendChild(line);
  $('log').scrollTop = $('log').scrollHeight;
}

function clearLog() { $('log').innerHTML = ''; }

function optionList(select, values, current, emptyLabel) {
  select.innerHTML = '';
  const empty = document.createElement('option');
  empty.value = '';
  empty.textContent = emptyLabel || '-';
  select.appendChild(empty);
  values.forEach(v => {
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = v;
    if (v === current) opt.selected = true;
    select.appendChild(opt);
  });
}

function switchTab(tab) {
  $('tabSettings').style.display = tab === 'settings' ? 'block' : 'none';
  $('tabResources').style.display = tab === 'resources' ? 'block' : 'none';
  $('tabBrutal').style.display = tab === 'brutal' ? 'block' : 'none';
  $('tabImagine').style.display = tab === 'imagine' ? 'block' : 'none';
  $('tabUdmgr').style.display = tab === 'udmgr' ? 'block' : 'none';

  $('tabSettingsBtn').className = tab === 'settings' ? '' : 'secondary';
  $('tabResourcesBtn').className = tab === 'resources' ? '' : 'secondary';
  $('tabBrutalBtn').className = tab === 'brutal' ? '' : 'secondary';
  $('tabImagineBtn').className = tab === 'imagine' ? '' : 'secondary';
  $('tabUdMgrBtn').className = tab === 'udmgr' ? '' : 'secondary';

  if(tab === 'resources') refreshResources();
  if(tab === 'imagine') loadImagineFiles();
  if(tab === 'udmgr') loadUdmgrFolders();
}

async function loadUdmgrFolders() {
  const res = await fetch('/api/udmgr/folders').then(r=>r.json());
  if(!res.ok) return;
  const grid = $('udmgrFolders');
  grid.innerHTML = res.folders.map(f => `
    <div class="browser-box" style="display:flex; flex-direction:column; gap:5px;">
      <div><input type="checkbox" class="udmgr-check" value="${escapeHtml(f)}"> <strong>${escapeHtml(f)}</strong></div>
      <button class="secondary" style="width:100%; font-size:11px; padding:4px;" onclick="launchUdmgrChrome('${escapeHtml(f)}')">Buka Chrome</button>
    </div>
  `).join('');
}
function selectAllUdmgr(on) { document.querySelectorAll('.udmgr-check').forEach(x => x.checked = !!on); }
async function launchUdmgrChromeParent() {
  await api('/api/udmgr/chrome_parent');
}
async function launchUdmgrChrome(folder) {
  await api('/api/udmgr/chrome', {folder});
}
async function createUdmgrFolder() {
  const name = $('newUdName').value;
  if (!name.trim()) return alert('Isi nama UD');
  await api('/api/udmgr/create', {name});
  $('newUdName').value = '';
  await loadUdmgrFolders();
}
async function duplicateUdmgrProfile() {
  const folders = Array.from(document.querySelectorAll('.udmgr-check:checked')).map(x => x.value);
  if(!folders.length) return alert('Pilih minimal satu folder UD');
  if(!confirm('Duplicate Local State & Default ke '+folders.length+' folder? Data lama akan tertimpa!')) return;
  await api('/api/udmgr/duplicate', {folders});
}

let promptsMap = {};
async function refreshResources() {
  const p = await fetch('/api/prompts').then(r=>r.json());
  if(p.ok) {
    promptsMap = p.prompts;
    const pl = $('promptList');
    pl.innerHTML = '';
    for(const k of Object.keys(promptsMap).sort()) {
      const d = document.createElement('div');
      d.innerHTML = `<b>${k}</b>: <span style="color:var(--muted)">${String(promptsMap[k]).substring(0,60)}...</span>`;
      d.style.cursor = 'pointer';
      d.onclick = () => { $('newPromptName').value = k; $('newPromptText').value = promptsMap[k]; };
      pl.appendChild(d);
    }
  }
  const b = await fetch('/api/bahan').then(r=>r.json());
  if(b.ok) {
    const bl = $('bahanList');
    bl.innerHTML = '';
    for(const k of Object.keys(b.folders).sort()) {
      const d = document.createElement('div');
      d.innerHTML = `<b>${k}</b> <span style="float:right;color:var(--brand);">${b.folders[k]} files</span>`;
      bl.appendChild(d);
    }
  }
}

async function saveNewPrompt() {
  const name = $('newPromptName').value.trim();
  const text = $('newPromptText').value.trim();
  if(!name || !text) return alert('Isi nama dan text prompt');
  await fetch('/api/prompts', {method:'POST', body:JSON.stringify({name,text})});
  refreshResources();
  refresh();
}

async function deletePrompt() {
  const name = $('newPromptName').value.trim();
  if(!name) return;
  if(confirm('Hapus prompt ' + name + '?')) {
    await fetch('/api/prompts', {method:'DELETE', body:JSON.stringify({name})});
    $('newPromptName').value = ''; $('newPromptText').value = '';
    refreshResources();
    refresh();
  }
}

async function saveBahan() {
  const name = $('newBahanName').value.trim();
  const files = $('newBahanFiles').files;
  if(!name) return alert('Nama folder diperlukan');
  const fd = new FormData();
  fd.append('name', name);
  for(let i=0; i<files.length; i++) fd.append('files', files[i]);
  const btn = event.target; btn.disabled = true; btn.textContent = 'Uploading...';
  try {
    const res = await fetch('/api/bahan', {method:'POST', body:fd}).then(r=>r.json());
    alert(res.msg);
  } catch(e) { alert('Error: ' + e); }
  btn.disabled = false; btn.textContent = 'Buat / Upload Bahan';
  $('newBahanName').value = '';
  $('newBahanFiles').value = '';
  refreshResources();
  refresh();
}

async function toggleAuto() {
  const on = $('autoSwitch').checked;
  const url = on ? '/api/auto/start' : '/api/auto/stop';
  const res = await fetch(url, {method:'POST'}).then(r=>r.json());
  if(!res.ok) alert(res.msg);
  setTimeout(refresh, 500);
}

function renderUdGrid() {
  const grid = $('udGrid');
  grid.innerHTML = '';
  for (let i = 1; i <= 20; i++) {
    const d = state.ud_data[String(i)];
    const btn = document.createElement('button');
    btn.className = 'ud-btn' + (i === selectedUd ? ' active' : '') + (d.active ? ' enabled' : '');
    btn.textContent = `UD ${i}`;
    btn.onclick = () => { selectedUd = i; render(); };
    grid.appendChild(btn);
  }
}

function render() {
  if (!state) return;
  const d = state.ud_data[String(selectedUd)];
  const cfg = d.config;
  const brutal = d.brutal || {};
  renderUdGrid();
  $('selectedPill').textContent = `UD ${selectedUd}`;
  $('configTitle').textContent = `Konfigurasi UD ${selectedUd}`;
  $('stokCount').textContent = d.stok;
  $('rawCount').textContent = d.raw_count;
  $('schedCount').textContent = d.schedule_items;
  $('batchCount').textContent = cfg.batch_size;
  const running = d.running.generate || d.running.upload || d.running.pipeline;
  $('runPill').className = running ? 'pill run' : 'pill';
  $('runPill').textContent = running ? 'running' : 'idle';
  if (!_activeLoaded) {
    $('activeInput').value = state.active_uds.join(',');
    _activeLoaded = true;
  }
  if (!document.activeElement || document.activeElement.id !== 'autoSwitch') {
    $('autoSwitch').checked = state.auto_running;
  }
  if (window.lastRenderedUd !== selectedUd) {
    optionList($('promptName'), state.prompts, cfg.prompt_name, 'Pilih prompt');
    optionList($('bahanFolder'), state.bahan_folders, cfg.bahan_folder, 'Pilih bahan');
    $('deskripsi').value = cfg.deskripsi || '';
    $('hashtags').value = (cfg.hashtags || []).map(x => '#' + x).join(', ');
    $('namaProdukRadio').value = cfg.nama_produk_radio || '';
    $('produkRadioList').value = (cfg.nama_produk_radio_list || []).join('\n');
    $('namaProdukInput').value = cfg.nama_produk_input || '';
    $('tiktokUd').value = cfg.tiktok_ud || '';
    $('tiktokPort').value = cfg.tiktok_port || '';
    $('grokUd').value = cfg.grok_ud || '';
    $('grokPort').value = cfg.grok_port || '';
    $('schedDate').value = cfg.schedule.tanggal || '';
    $('schedHour').value = Number(cfg.schedule.jam || 0);
    $('schedMinute').value = Number(cfg.schedule.menit || 0);
    $('intervalHours').value = cfg.interval_hours || 5;
    $('batchSize').value = cfg.batch_size || 30;
    $('addProduct').checked = !!cfg.add_product;
    $('addSound').checked = !!cfg.add_sound;
    window.lastRenderedUd = selectedUd;
  }
  $('stokPreview').innerHTML = d.stok_preview.length ? d.stok_preview.map(x => `<div>${escapeHtml(x)}</div>`).join('') : '<div>Belum ada stok.</div>';
  $('brutalTitle').textContent = `Brutal Bot UD ${selectedUd}`;
  $('brutalStokCount').textContent = brutal.stok || 0;
  $('brutalRawCount').textContent = brutal.raw_count || 0;
  $('brutalSchedCount').textContent = brutal.schedule_items || 0;
  $('brutalUdLabel').textContent = selectedUd;
  const brutalRunning = d.running.brutal_generate || d.running.brutal_upload || d.running.brutal_pipeline;
  $('brutalRunPill').className = brutalRunning ? 'pill run' : 'pill';
  $('brutalRunPill').textContent = brutalRunning ? 'running' : 'idle';
  $('brutalStokPreview').innerHTML = brutal.stok_preview && brutal.stok_preview.length ? brutal.stok_preview.map(x => `<div>${escapeHtml(x)}</div>`).join('') : '<div>Belum ada stok brutal.</div>';
  renderImagineState();
  $('serverState').textContent = `${state.tasks.length} task aktif`;
}

function renderImagineState() {
  const im = state.imagine || {};
  const settings = im.settings || {};
  $('imagineGenerated').textContent = im.generated || 0;
  $('imagineFailed').textContent = im.failed || 0;
  $('imagineMerged').textContent = im.merged || 0;
  $('imagineDownloaded').textContent = `${im.files_downloaded || 0}/${im.files_total || 0}`;
  $('imagineRunPill').className = im.running ? 'pill run' : 'pill';
  $('imagineRunPill').textContent = im.running ? 'running' : 'idle';
  if (!window.imagineRendered) {
    optionList($('imagineFolder'), state.bahan_folders || [], im.folder || '', 'Pilih bahan');
    optionList($('imaginePrompt'), state.prompts || [], im.prompt || '', 'Pilih prompt');
    $('imagineMode').value = settings.gen_mode || 'Video';
    $('imagineResolution').value = settings.resolution || '720p';
    $('imagineDuration').value = settings.duration || '10s';
    $('imagineAspect').value = settings.aspect_ratio || '9:16';
    $('imagineMerge').value = String(settings.merge_duration || 20);
    window.imagineRendered = true;
  }
  const bs = im.browser_states || {};
  const keys = Object.keys(bs).sort((a,b)=>Number(a)-Number(b));
  $('imagineBrowsers').innerHTML = keys.length ? keys.map(k => {
    const b = bs[k] || {};
    const pct = Math.max(0, Math.min(100, Number(b.progress || 0)));
    return `<div class="browser-box"><strong>B${Number(k)+1}</strong> ${escapeHtml(b.status || 'idle')}<div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div><div class="muted">${pct}% ${escapeHtml(b.message || '')}</div><div class="muted">OK ${b.generated || 0} / Fail ${b.failed || 0}</div></div>`;
  }).join('') : '<div class="muted">Browser idle.</div>';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function api(url, data) {
  const r = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data || {})
  });
  const out = await r.json();
  if (!out.ok) appendLog({ts: new Date().toLocaleTimeString(), tag: 'error', msg: out.msg || 'Request gagal'});
  return out;
}

async function refresh() {
  const r = await fetch('/api/status');
  state = await r.json();
  render();
}

async function saveConfig() {
  await api('/api/config', {
    ud: selectedUd,
    prompt_name: $('promptName').value,
    bahan_folder: $('bahanFolder').value,
    deskripsi: $('deskripsi').value,
    hashtags: $('hashtags').value,
    nama_produk_radio: $('namaProdukRadio').value,
    nama_produk_radio_list: $('produkRadioList').value,
    nama_produk_input: $('namaProdukInput').value,
    tiktok_ud: $('tiktokUd').value,
    tiktok_port: $('tiktokPort').value,
    grok_ud: $('grokUd').value,
    grok_port: $('grokPort').value,
    schedule: {tanggal: $('schedDate').value, jam: $('schedHour').value, menit: $('schedMinute').value},
    interval_hours: $('intervalHours').value,
    batch_size: $('batchSize').value,
    add_product: $('addProduct').checked,
    add_sound: $('addSound').checked
  });
  await refresh();
}

async function saveActive() {
  await api('/api/active_ud', {uds: $('activeInput').value});
  _activeLoaded = false;
  await refresh();
}

async function runAction(action) {
  await saveConfig();
  await api(`/api/action/${action}`, {ud: selectedUd});
  setTimeout(refresh, 500);
}

async function stopUd() {
  await api('/api/action/stop', {ud: selectedUd, action: 'all'});
  setTimeout(refresh, 500);
}

async function mergeRaw() {
  await api('/api/raw/merge', {ud: selectedUd});
  await refresh();
}

async function clearStok() {
  if (!confirm(`Kosongkan stok UD ${selectedUd}?`)) return;
  await api('/api/stok/clear', {ud: selectedUd});
  await refresh();
}

async function runBrutal(action) {
  await saveConfig();
  const payload = {
    ud: selectedUd,
    target_stok: Number($('brutalTargetStok').value || 50),
    delay_minutes: Number($('brutalDelayMinutes').value || 30),
    max_videos: Number($('brutalMaxVideos').value || 50)
  };
  await api(`/api/brutal/${action}`, payload);
  setTimeout(refresh, 500);
}

async function mergeBrutalRaw() {
  await api('/api/brutal/merge', {ud: selectedUd});
  await refresh();
}

async function clearBrutalStok() {
  if (!confirm(`Kosongkan stok BRUTAL UD ${selectedUd}?`)) return;
  await api('/api/brutal/clear', {ud: selectedUd});
  await refresh();
}

async function saveImagineSettings() {
  await api('/api/imagine/settings', {
    gen_mode: $('imagineMode').value,
    resolution: $('imagineResolution').value,
    duration: $('imagineDuration').value,
    aspect_ratio: $('imagineAspect').value,
    merge_duration: Number($('imagineMerge').value || 20)
  });
  await refresh();
}

async function startImagine() {
  await saveImagineSettings();
  await api('/api/imagine/generate', {
    folder: $('imagineFolder').value,
    prompt: $('imaginePrompt').value,
    count: Number($('imagineCount').value || 1)
  });
  setTimeout(refresh, 500);
}

async function stopImagine() {
  await api('/api/imagine/stop', {});
  setTimeout(refresh, 500);
}

async function loadImagineFiles() {
  const kind = $('imagineKindFilter') ? $('imagineKindFilter').value : 'all';
  const downloaded = $('imagineDownloadedFilter') ? $('imagineDownloadedFilter').value : 'all';
  const res = await fetch(`/api/imagine/files?kind=${encodeURIComponent(kind)}&downloaded=${encodeURIComponent(downloaded)}`).then(r=>r.json());
  if (!res.ok) return;
  imagineFiles = res.files || [];
  renderImagineGallery();
}

function selectedImagineIds() {
  return Array.from(document.querySelectorAll('.imagine-select:checked')).map(x => x.value);
}

function renderImagineGallery() {
  const g = $('imagineGallery');
  $('imagineGalleryInfo').textContent = `${imagineFiles.length} file`;
  if (!imagineFiles.length) {
    g.innerHTML = '<div class="muted">Belum ada hasil generate.</div>';
    return;
  }
  g.innerHTML = imagineFiles.map(f => `
    <div class="media-card ${f.downloaded ? 'downloaded' : ''}">
      <input class="media-check imagine-select" type="checkbox" value="${escapeHtml(f.id)}">
      <video src="${escapeHtml(f.url)}" controls preload="metadata"></video>
      <div class="media-meta">
        <strong>${escapeHtml(f.name)}</strong>
        <div>${escapeHtml(f.kind)} · ${f.size_mb} MB</div>
        <div>${escapeHtml(f.mtime)}</div>
        <div>${f.downloaded ? 'downloaded ' + escapeHtml(f.downloaded_at || '') : 'belum downloaded'}</div>
      </div>
      <div class="media-actions">
        <a class="secondary" href="${escapeHtml(f.download_url)}">Download</a>
        <button class="secondary" onclick="markSelectedImagineFromCard('${escapeHtml(f.id)}', true)">Mark</button>
      </div>
    </div>
  `).join('');
}

function selectAllImagine(on) {
  document.querySelectorAll('.imagine-select').forEach(x => x.checked = !!on);
}

async function markSelectedImagineFromCard(id, downloaded) {
  await api('/api/imagine/mark', {files:[id], downloaded});
  await loadImagineFiles();
  await refresh();
}

async function markSelectedImagine(downloaded) {
  const files = selectedImagineIds();
  if (!files.length) return alert('Pilih file dulu');
  await api('/api/imagine/mark', {files, downloaded});
  await loadImagineFiles();
  await refresh();
}

async function deleteSelectedImagine() {
  const files = selectedImagineIds();
  if (!files.length) return alert('Pilih file dulu');
  if (!confirm(`Hapus ${files.length} file dari galeri?`)) return;
  await api('/api/imagine/delete', {files});
  await loadImagineFiles();
  await refresh();
}

async function downloadSelectedImagine() {
  const files = selectedImagineIds();
  if (!files.length) return alert('Pilih file dulu');
  const r = await fetch('/api/imagine/download_zip', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({files})
  });
  if (!r.ok) {
    const out = await r.json().catch(()=>({msg:'Download gagal'}));
    return alert(out.msg || 'Download gagal');
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `grok_imagine_${Date.now()}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  setTimeout(async () => { await loadImagineFiles(); await refresh(); }, 800);
}

const es = new EventSource('/api/logs');
es.onmessage = (event) => appendLog(JSON.parse(event.data));
setInterval(refresh, 5000);
refresh();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    os.makedirs(os.path.join(APP_DIR, "gtt_stok"), exist_ok=True)
    web_log(f"Grok TikTok Web Dashboard running on http://localhost:{PORT}", "success")
    print(f"Grok TikTok Web Dashboard running on http://localhost:{PORT}")
    try:
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from werkzeug.middleware.proxy_fix import ProxyFix
        from werkzeug.serving import run_simple
        from yt_web_server import app as yt_app, TEMP_DIR, FINAL_DIR
        os.makedirs(TEMP_DIR, exist_ok=True)
        os.makedirs(FINAL_DIR, exist_ok=True)
        application = DispatcherMiddleware(app, {'/ytbot': yt_app})
        application = ProxyFix(application, x_for=1, x_proto=1, x_host=1, x_prefix=1)
        print(f"[OK] YT Bot berhasil dipasang di http://localhost:{PORT}/ytbot")
        run_simple(HOST, PORT, application, use_reloader=False, threaded=True)
    except Exception as e:
        print(f"[WARN] Peringatan: Tidak dapat memuat yt_web_server: {e}. Menjalankan GTT secara standalone.")
        app.run(host=HOST, port=PORT, debug=False, threaded=True)
