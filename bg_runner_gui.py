"""
🚀 BG-Script Runner GUI
━━━━━━━━━━━━━━━━━━━━━━━
Tkinter GUI to launch, monitor, and kill Python scripts from bg-script folder.
Features:
  • Checkbox selection for individual scripts
  • Run selected or all scripts
  • PID tracking persisted to JSON (survives app restart)
  • Live status checking — knows if a process is still alive
  • Kill individual or all running processes
  • Modern dark-themed UI
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import os
import sys
import json
import shutil
import psutil
from datetime import datetime
import threading
import time

# ═══════════════════════════════════════════════════════════════
#  PATHS & CONFIG
# ═══════════════════════════════════════════════════════════════
APP_DIR = r"C:\tiktok_automation"
BG_SCRIPT_DIR = os.path.join(APP_DIR, "bg-script")
PID_DB_FILE = os.path.join(APP_DIR, "bg_runner_pids.json")
PYTHON_EXE = os.path.join(APP_DIR, "Scripts", "python.exe")
REFRESH_INTERVAL_MS = 3000  # Auto-refresh every 3 seconds

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = os.path.join(APP_DIR, "user_data")
PARENT_PROFILE_DIR = os.path.join(USER_DATA_DIR, "parent")


# ═══════════════════════════════════════════════════════════════
#  PID DATABASE (JSON persistence)
# ═══════════════════════════════════════════════════════════════
def load_pid_db():
    """Load PID database from JSON file."""
    if os.path.exists(PID_DB_FILE):
        try:
            with open(PID_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_pid_db(db):
    """Save PID database to JSON file."""
    with open(PID_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def is_process_alive(pid):
    """Check if a process with the given PID is still running."""
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def get_process_info(pid):
    """Get process info (name, cpu, memory) if alive."""
    try:
        proc = psutil.Process(pid)
        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
            return {
                "name": proc.name(),
                "status": proc.status(),
                "cpu": proc.cpu_percent(interval=0),
                "memory_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
                "create_time": datetime.fromtimestamp(proc.create_time()).strftime("%Y-%m-%d %H:%M:%S"),
            }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    return None


def scan_bat_scripts():
    """Scan bg-script folder for .bat files and parse the Python script they run."""
    scripts = []
    if not os.path.isdir(BG_SCRIPT_DIR):
        return scripts

    for filename in sorted(os.listdir(BG_SCRIPT_DIR)):
        if not filename.lower().endswith(".bat"):
            continue
        filepath = os.path.join(BG_SCRIPT_DIR, filename)
        py_script = None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.lower().startswith("python "):
                        py_script = line.split(None, 1)[1].strip()
                        break
        except IOError:
            pass

        scripts.append({
            "bat_name": filename,
            "bat_path": filepath,
            "py_script": py_script or "(unknown)",
            "display_name": os.path.splitext(filename)[0].replace("_", " ").title(),
        })
    return scripts


# ═══════════════════════════════════════════════════════════════
#  COLORS & THEME
# ═══════════════════════════════════════════════════════════════
COLORS = {
    "bg_dark": "#0f0f1a",
    "bg_card": "#1a1a2e",
    "bg_card_hover": "#22223a",
    "bg_input": "#16213e",
    "accent": "#00d4aa",
    "accent_hover": "#00f5c4",
    "danger": "#ff4757",
    "danger_hover": "#ff6b81",
    "warning": "#ffa502",
    "text": "#e8e8e8",
    "text_dim": "#8888aa",
    "text_bright": "#ffffff",
    "success": "#2ed573",
    "border": "#2a2a4a",
    "running": "#2ed573",
    "stopped": "#ff4757",
    "unknown": "#ffa502",
}


# ═══════════════════════════════════════════════════════════════
#  MAIN GUI CLASS
# ═══════════════════════════════════════════════════════════════
class BgRunnerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🚀 BG-Script Runner")
        self.root.geometry("1050x850")
        self.root.minsize(900, 700)
        self.root.configure(bg=COLORS["bg_dark"])

        # Set icon if available
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        # Data
        self.scripts = scan_bat_scripts()
        self.checkboxes = {}  # script_name -> BooleanVar
        self.pid_db = load_pid_db()
        self.status_labels = {}  # script_name -> label widget
        self.pid_labels = {}    # script_name -> label widget
        self.kill_buttons = {}  # script_name -> button widget

        # Data for profile duplication
        self.profile_checkboxes = {}  # folder_name -> BooleanVar

        # Build UI
        self._build_header()
        self._build_toolbar()
        self._build_script_list()
        self._build_chrome_login_section()
        self._build_log_panel()
        self._build_footer()

        # Initial status refresh
        self.root.after(500, self._refresh_status)

        # Auto-refresh timer
        self._schedule_refresh()

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── HEADER ─────────────────────────────────────────────
    def _build_header(self):
        header = tk.Frame(self.root, bg=COLORS["bg_card"], pady=15, padx=20)
        header.pack(fill=tk.X, padx=0, pady=0)

        title = tk.Label(
            header,
            text="🚀  BG-Script Runner",
            font=("Segoe UI", 20, "bold"),
            fg=COLORS["accent"],
            bg=COLORS["bg_card"],
        )
        title.pack(side=tk.LEFT)

        subtitle = tk.Label(
            header,
            text="Process Manager untuk bg-script",
            font=("Segoe UI", 10),
            fg=COLORS["text_dim"],
            bg=COLORS["bg_card"],
        )
        subtitle.pack(side=tk.LEFT, padx=(15, 0), pady=(5, 0))

        # Running count badge
        self.running_count_label = tk.Label(
            header,
            text="0 running",
            font=("Segoe UI", 10, "bold"),
            fg=COLORS["bg_dark"],
            bg=COLORS["success"],
            padx=10,
            pady=2,
        )
        self.running_count_label.pack(side=tk.RIGHT)

    # ─── TOOLBAR ────────────────────────────────────────────
    def _build_toolbar(self):
        toolbar = tk.Frame(self.root, bg=COLORS["bg_dark"], pady=8, padx=15)
        toolbar.pack(fill=tk.X)

        # Select All / Deselect All
        btn_style = {
            "font": ("Segoe UI", 9, "bold"),
            "bd": 0,
            "padx": 12,
            "pady": 6,
            "cursor": "hand2",
            "relief": tk.FLAT,
            "activebackground": COLORS["accent_hover"],
        }

        select_all_btn = tk.Button(
            toolbar, text="☑ Pilih Semua", bg=COLORS["bg_card"], fg=COLORS["text"],
            activeforeground=COLORS["text_bright"],
            command=self._select_all, **btn_style
        )
        select_all_btn.pack(side=tk.LEFT, padx=(0, 5))

        deselect_all_btn = tk.Button(
            toolbar, text="☐ Batal Semua", bg=COLORS["bg_card"], fg=COLORS["text"],
            activeforeground=COLORS["text_bright"],
            command=self._deselect_all, **btn_style
        )
        deselect_all_btn.pack(side=tk.LEFT, padx=(0, 15))

        # Run Selected
        run_btn = tk.Button(
            toolbar, text="▶  Jalankan Terpilih", bg=COLORS["accent"], fg=COLORS["bg_dark"],
            activeforeground=COLORS["bg_dark"],
            command=self._run_selected, **btn_style
        )
        run_btn.pack(side=tk.LEFT, padx=(0, 5))

        # Run All
        run_all_btn = tk.Button(
            toolbar, text="▶▶  Jalankan Semua", bg="#0078d4", fg=COLORS["text_bright"],
            activeforeground=COLORS["text_bright"],
            command=self._run_all, **btn_style
        )
        run_all_btn.pack(side=tk.LEFT, padx=(0, 15))

        # Kill All
        kill_all_btn = tk.Button(
            toolbar, text="⛔  Kill Semua", bg=COLORS["danger"], fg=COLORS["text_bright"],
            activeforeground=COLORS["text_bright"],
            command=self._kill_all, **btn_style
        )
        kill_all_btn.pack(side=tk.RIGHT, padx=(0, 0))

        # Refresh
        refresh_btn = tk.Button(
            toolbar, text="🔄 Refresh", bg=COLORS["bg_card"], fg=COLORS["text"],
            activeforeground=COLORS["text_bright"],
            command=self._refresh_status, **btn_style
        )
        refresh_btn.pack(side=tk.RIGHT, padx=(0, 5))

    # ─── SCRIPT LIST ────────────────────────────────────────
    def _build_script_list(self):
        container = tk.Frame(self.root, bg=COLORS["bg_dark"], padx=15, pady=5)
        container.pack(fill=tk.BOTH, expand=True)

        # Canvas + Scrollbar for scrollable list
        canvas_frame = tk.Frame(container, bg=COLORS["bg_dark"])
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, bg=COLORS["bg_dark"], highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        self.script_frame = tk.Frame(canvas, bg=COLORS["bg_dark"])

        self.script_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.script_frame, anchor="nw", tags="frame")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Make canvas frame expand with window
        def on_canvas_configure(event):
            canvas.itemconfig("frame", width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Column headers
        header_frame = tk.Frame(self.script_frame, bg=COLORS["border"], pady=6, padx=10)
        header_frame.pack(fill=tk.X, padx=0, pady=(0, 2))

        headers = [
            ("", 30), ("Script", 180), ("Python File", 200),
            ("Status", 80), ("PID", 70), ("Action", 90),
        ]
        for text, width in headers:
            tk.Label(
                header_frame, text=text, font=("Segoe UI", 9, "bold"),
                fg=COLORS["text_dim"], bg=COLORS["border"], anchor="w", width=width // 8
            ).pack(side=tk.LEFT, padx=(5, 0))

        # Script rows
        for i, script in enumerate(self.scripts):
            self._build_script_row(script, i)

    def _build_script_row(self, script, index):
        key = script["bat_name"]
        bg = COLORS["bg_card"] if index % 2 == 0 else COLORS["bg_input"]

        row = tk.Frame(self.script_frame, bg=bg, pady=8, padx=10)
        row.pack(fill=tk.X, padx=0, pady=1)

        # Hover effect
        def on_enter(e, frame=row):
            frame.configure(bg=COLORS["bg_card_hover"])
            for w in frame.winfo_children():
                try:
                    w.configure(bg=COLORS["bg_card_hover"])
                except tk.TclError:
                    pass

        def on_leave(e, frame=row, orig_bg=bg):
            frame.configure(bg=orig_bg)
            for w in frame.winfo_children():
                try:
                    w.configure(bg=orig_bg)
                except tk.TclError:
                    pass

        row.bind("<Enter>", on_enter)
        row.bind("<Leave>", on_leave)

        # Checkbox
        var = tk.BooleanVar(value=False)
        self.checkboxes[key] = var
        cb = tk.Checkbutton(
            row, variable=var, bg=bg, activebackground=bg,
            selectcolor=COLORS["bg_input"], bd=0, highlightthickness=0,
        )
        cb.pack(side=tk.LEFT, padx=(0, 5))

        # Script name
        name_label = tk.Label(
            row, text=script["display_name"],
            font=("Segoe UI", 11, "bold"), fg=COLORS["text_bright"],
            bg=bg, anchor="w", width=20,
        )
        name_label.pack(side=tk.LEFT, padx=(0, 5))

        # Python file
        py_label = tk.Label(
            row, text=script["py_script"],
            font=("Consolas", 9), fg=COLORS["text_dim"],
            bg=bg, anchor="w", width=25,
        )
        py_label.pack(side=tk.LEFT, padx=(0, 5))

        # Status indicator
        status_label = tk.Label(
            row, text="● IDLE",
            font=("Segoe UI", 9, "bold"), fg=COLORS["text_dim"],
            bg=bg, anchor="w", width=12,
        )
        status_label.pack(side=tk.LEFT, padx=(0, 5))
        self.status_labels[key] = status_label

        # PID label
        pid_label = tk.Label(
            row, text="—",
            font=("Consolas", 9), fg=COLORS["text_dim"],
            bg=bg, anchor="w", width=8,
        )
        pid_label.pack(side=tk.LEFT, padx=(0, 5))
        self.pid_labels[key] = pid_label

        # Kill button (individual)
        kill_btn = tk.Button(
            row, text="⛔ Kill",
            font=("Segoe UI", 8, "bold"), fg=COLORS["text_bright"],
            bg=COLORS["danger"], activebackground=COLORS["danger_hover"],
            bd=0, padx=8, pady=2, cursor="hand2",
            command=lambda k=key: self._kill_script(k),
            state=tk.DISABLED,
        )
        kill_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self.kill_buttons[key] = kill_btn

    # ─── CHROME LOGIN & PROFILE DUPLICATION ─────────────────
    def _build_chrome_login_section(self):
        """Build the Chrome Login + Profile Duplicate section."""
        section = tk.Frame(self.root, bg=COLORS["bg_dark"], padx=15, pady=5)
        section.pack(fill=tk.BOTH, expand=False)

        # Section header
        sec_header = tk.Frame(section, bg=COLORS["bg_card"], pady=8, padx=12)
        sec_header.pack(fill=tk.X, pady=(0, 5))

        tk.Label(
            sec_header, text="🌐  Chrome Login & Profile Duplicator",
            font=("Segoe UI", 13, "bold"), fg=COLORS["accent"],
            bg=COLORS["bg_card"],
        ).pack(side=tk.LEFT)

        # ── Login button ──
        login_btn = tk.Button(
            sec_header, text="🔑  Login Chrome (Parent)",
            font=("Segoe UI", 10, "bold"), fg=COLORS["bg_dark"],
            bg="#ffa502", activebackground="#ffbe76",
            bd=0, padx=14, pady=5, cursor="hand2",
            command=self._launch_chrome_login,
        )
        login_btn.pack(side=tk.RIGHT)

        # ── Profile list area ──
        profile_area = tk.Frame(section, bg=COLORS["bg_card"], padx=10, pady=8)
        profile_area.pack(fill=tk.BOTH, expand=False)

        # Toolbar for profiles
        prof_toolbar = tk.Frame(profile_area, bg=COLORS["bg_card"], pady=4)
        prof_toolbar.pack(fill=tk.X)

        tk.Label(
            prof_toolbar, text="📂 Pilih folder profil tujuan duplikasi:",
            font=("Segoe UI", 9), fg=COLORS["text_dim"],
            bg=COLORS["bg_card"], anchor="w",
        ).pack(side=tk.LEFT)

        # Select All / Deselect All for profiles
        prof_btn_style = {
            "font": ("Segoe UI", 8, "bold"),
            "bd": 0,
            "padx": 10,
            "pady": 4,
            "cursor": "hand2",
            "relief": tk.FLAT,
        }

        self.prof_select_all_var = tk.BooleanVar(value=False)

        deselect_prof_btn = tk.Button(
            prof_toolbar, text="☐ Batal Semua",
            bg=COLORS["bg_input"], fg=COLORS["text"],
            activebackground=COLORS["bg_card_hover"],
            activeforeground=COLORS["text_bright"],
            command=self._deselect_all_profiles, **prof_btn_style,
        )
        deselect_prof_btn.pack(side=tk.RIGHT, padx=(5, 0))

        select_all_prof_btn = tk.Button(
            prof_toolbar, text="☑ Pilih Semua",
            bg=COLORS["bg_input"], fg=COLORS["text"],
            activebackground=COLORS["bg_card_hover"],
            activeforeground=COLORS["text_bright"],
            command=self._select_all_profiles, **prof_btn_style,
        )
        select_all_prof_btn.pack(side=tk.RIGHT, padx=(5, 0))

        refresh_prof_btn = tk.Button(
            prof_toolbar, text="🔄 Refresh",
            bg=COLORS["bg_input"], fg=COLORS["text"],
            activebackground=COLORS["bg_card_hover"],
            activeforeground=COLORS["text_bright"],
            command=self._refresh_profile_list, **prof_btn_style,
        )
        refresh_prof_btn.pack(side=tk.RIGHT, padx=(5, 0))

        # Scrollable checkbox grid for profiles
        self.profile_canvas_frame = tk.Frame(profile_area, bg=COLORS["bg_input"])
        self.profile_canvas_frame.pack(fill=tk.BOTH, expand=False, pady=(4, 0))

        prof_canvas = tk.Canvas(
            self.profile_canvas_frame, bg=COLORS["bg_input"],
            highlightthickness=0, height=110,
        )
        prof_scrollbar = tk.Scrollbar(
            self.profile_canvas_frame, orient=tk.VERTICAL, command=prof_canvas.yview,
        )
        self.profile_inner_frame = tk.Frame(prof_canvas, bg=COLORS["bg_input"])

        self.profile_inner_frame.bind(
            "<Configure>",
            lambda e: prof_canvas.configure(scrollregion=prof_canvas.bbox("all")),
        )

        prof_canvas.create_window((0, 0), window=self.profile_inner_frame, anchor="nw", tags="prof_frame")
        prof_canvas.configure(yscrollcommand=prof_scrollbar.set)

        def on_prof_canvas_configure(event):
            prof_canvas.itemconfig("prof_frame", width=event.width)
        prof_canvas.bind("<Configure>", on_prof_canvas_configure)

        prof_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        prof_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Duplicate button
        dup_toolbar = tk.Frame(profile_area, bg=COLORS["bg_card"], pady=6)
        dup_toolbar.pack(fill=tk.X)

        self.duplicate_btn = tk.Button(
            dup_toolbar, text="📋  Duplicate (Copy Default + Local State → Terpilih)",
            font=("Segoe UI", 10, "bold"), fg=COLORS["text_bright"],
            bg="#6c5ce7", activebackground="#a29bfe",
            bd=0, padx=16, pady=6, cursor="hand2",
            command=self._duplicate_profiles,
        )
        self.duplicate_btn.pack(side=tk.LEFT)

        self.dup_status_label = tk.Label(
            dup_toolbar, text="",
            font=("Segoe UI", 9), fg=COLORS["text_dim"],
            bg=COLORS["bg_card"], anchor="w",
        )
        self.dup_status_label.pack(side=tk.LEFT, padx=(12, 0))

        # Populate profiles
        self._refresh_profile_list()

    def _get_profile_folders(self):
        """Get all subfolders in user_data except 'parent'."""
        folders = []
        if not os.path.isdir(USER_DATA_DIR):
            return folders
        for name in sorted(os.listdir(USER_DATA_DIR)):
            full = os.path.join(USER_DATA_DIR, name)
            if os.path.isdir(full) and name.lower() != "parent":
                folders.append(name)
        return folders

    def _refresh_profile_list(self):
        """Rebuild the profile checkbox list."""
        # Clear existing
        for widget in self.profile_inner_frame.winfo_children():
            widget.destroy()
        self.profile_checkboxes.clear()

        folders = self._get_profile_folders()
        if not folders:
            tk.Label(
                self.profile_inner_frame,
                text="  (tidak ada folder profil di user_data)",
                font=("Segoe UI", 9), fg=COLORS["text_dim"],
                bg=COLORS["bg_input"],
            ).pack(anchor="w", pady=4)
            return

        # Grid layout — 4 columns
        cols = 4
        for i, folder in enumerate(folders):
            row_idx = i // cols
            col_idx = i % cols

            var = tk.BooleanVar(value=False)
            self.profile_checkboxes[folder] = var

            cb = tk.Checkbutton(
                self.profile_inner_frame,
                text=folder,
                variable=var,
                font=("Consolas", 9),
                fg=COLORS["text"],
                bg=COLORS["bg_input"],
                selectcolor=COLORS["bg_card"],
                activebackground=COLORS["bg_input"],
                activeforeground=COLORS["text_bright"],
                bd=0,
                highlightthickness=0,
                anchor="w",
            )
            cb.grid(row=row_idx, column=col_idx, sticky="w", padx=(8, 20), pady=2)

    def _select_all_profiles(self):
        for var in self.profile_checkboxes.values():
            var.set(True)

    def _deselect_all_profiles(self):
        for var in self.profile_checkboxes.values():
            var.set(False)

    def _launch_chrome_login(self):
        """Launch Chrome with remote debugging pointing to parent profile."""
        if not os.path.exists(CHROME_EXE):
            self._log(f"❌ Chrome tidak ditemukan: {CHROME_EXE}", "error")
            messagebox.showerror("Error", f"Chrome tidak ditemukan:\n{CHROME_EXE}")
            return

        cmd = [
            CHROME_EXE,
            "--remote-debugging-port=9222",
            f'--user-data-dir={PARENT_PROFILE_DIR}',
        ]
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._log("🌐 Chrome diluncurkan dengan profil parent (port 9222)", "success")
        except Exception as e:
            self._log(f"❌ Gagal meluncurkan Chrome: {e}", "error")

    def _duplicate_profiles(self):
        """Copy Default folder and Local State from parent to selected profiles."""
        selected = [name for name, var in self.profile_checkboxes.items() if var.get()]
        if not selected:
            self._log("⚠ Tidak ada folder profil yang dipilih!", "warning")
            messagebox.showwarning("Peringatan", "Pilih minimal satu folder profil tujuan.")
            return

        src_default = os.path.join(PARENT_PROFILE_DIR, "Default")
        src_local_state = os.path.join(PARENT_PROFILE_DIR, "Local State")

        if not os.path.isdir(src_default):
            self._log("❌ Folder 'Default' tidak ditemukan di parent!", "error")
            return
        if not os.path.isfile(src_local_state):
            self._log("❌ File 'Local State' tidak ditemukan di parent!", "error")
            return

        if not messagebox.askyesno(
            "Konfirmasi Duplikasi",
            f"Duplikasi Default + Local State dari parent ke {len(selected)} folder?\n\n"
            f"Folder tujuan:\n" + "\n".join(f"  • {s}" for s in selected) +
            "\n\n⚠ Data yang ada akan di-overwrite!",
        ):
            return

        self.duplicate_btn.configure(state=tk.DISABLED, text="⏳ Menyalin...")
        self.dup_status_label.configure(text="Memulai duplikasi...", fg=COLORS["warning"])
        self.root.update_idletasks()

        # Run in thread to avoid freezing GUI
        def do_copy():
            success = 0
            errors = []
            for folder in selected:
                dest_dir = os.path.join(USER_DATA_DIR, folder)
                dest_default = os.path.join(dest_dir, "Default")
                dest_local_state = os.path.join(dest_dir, "Local State")

                try:
                    # Copy Default folder (overwrite)
                    if os.path.exists(dest_default):
                        shutil.rmtree(dest_default)
                    shutil.copytree(src_default, dest_default)

                    # Copy Local State file (overwrite)
                    shutil.copy2(src_local_state, dest_local_state)

                    success += 1
                    self.root.after(0, lambda f=folder: self._log(
                        f"✅ Berhasil duplikasi ke: {f}", "success"
                    ))
                except Exception as e:
                    errors.append((folder, str(e)))
                    self.root.after(0, lambda f=folder, err=str(e): self._log(
                        f"❌ Gagal duplikasi ke {f}: {err}", "error"
                    ))

                # Update progress on GUI thread
                self.root.after(0, lambda s=success, t=len(selected): self.dup_status_label.configure(
                    text=f"Progress: {s}/{t}",
                    fg=COLORS["accent"],
                ))

            # Done
            def on_done():
                self.duplicate_btn.configure(
                    state=tk.NORMAL,
                    text="📋  Duplicate (Copy Default + Local State → Terpilih)",
                )
                if errors:
                    self.dup_status_label.configure(
                        text=f"Selesai: {success} berhasil, {len(errors)} gagal",
                        fg=COLORS["danger"],
                    )
                else:
                    self.dup_status_label.configure(
                        text=f"✅ Selesai! {success} folder berhasil diduplikasi",
                        fg=COLORS["success"],
                    )
                self._log(f"📋 Duplikasi selesai: {success}/{len(selected)} berhasil", "info")

            self.root.after(0, on_done)

        threading.Thread(target=do_copy, daemon=True).start()

    # ─── LOG PANEL ──────────────────────────────────────────
    def _build_log_panel(self):
        log_container = tk.Frame(self.root, bg=COLORS["bg_dark"], padx=15, pady=5)
        log_container.pack(fill=tk.X)

        log_header = tk.Label(
            log_container, text="📋 Log Aktivitas",
            font=("Segoe UI", 10, "bold"), fg=COLORS["text_dim"],
            bg=COLORS["bg_dark"], anchor="w",
        )
        log_header.pack(fill=tk.X, pady=(0, 3))

        self.log_text = tk.Text(
            log_container, height=8,
            font=("Consolas", 9), fg=COLORS["text"],
            bg=COLORS["bg_input"], insertbackground=COLORS["accent"],
            selectbackground=COLORS["accent"], selectforeground=COLORS["bg_dark"],
            bd=0, padx=10, pady=8, wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.log_text.pack(fill=tk.X)

        # Configure log tags
        self.log_text.tag_configure("time", foreground=COLORS["text_dim"])
        self.log_text.tag_configure("info", foreground=COLORS["accent"])
        self.log_text.tag_configure("success", foreground=COLORS["success"])
        self.log_text.tag_configure("error", foreground=COLORS["danger"])
        self.log_text.tag_configure("warning", foreground=COLORS["warning"])

    # ─── FOOTER ─────────────────────────────────────────────
    def _build_footer(self):
        footer = tk.Frame(self.root, bg=COLORS["border"], pady=6, padx=15)
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        self.footer_label = tk.Label(
            footer, text=f"📂 {BG_SCRIPT_DIR}  |  {len(self.scripts)} scripts ditemukan",
            font=("Segoe UI", 8), fg=COLORS["text_dim"], bg=COLORS["border"],
        )
        self.footer_label.pack(side=tk.LEFT)

        self.time_label = tk.Label(
            footer, text="",
            font=("Segoe UI", 8), fg=COLORS["text_dim"], bg=COLORS["border"],
        )
        self.time_label.pack(side=tk.RIGHT)
        self._update_clock()

    # ═══════════════════════════════════════════════════════════
    #  ACTIONS
    # ═══════════════════════════════════════════════════════════
    def _log(self, message, tag="info"):
        """Add a message to the log panel."""
        self.log_text.configure(state=tk.NORMAL)
        now = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{now}] ", "time")
        self.log_text.insert(tk.END, f"{message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _select_all(self):
        for var in self.checkboxes.values():
            var.set(True)

    def _deselect_all(self):
        for var in self.checkboxes.values():
            var.set(False)

    def _get_selected_scripts(self):
        """Get list of selected script dicts."""
        selected = []
        for script in self.scripts:
            key = script["bat_name"]
            if self.checkboxes.get(key) and self.checkboxes[key].get():
                selected.append(script)
        return selected

    def _run_script(self, script):
        """Run a single script by launching its .bat file hidden (windowless)."""
        key = script["bat_name"]

        # Check if already running
        if key in self.pid_db:
            pid = self.pid_db[key].get("pid")
            if pid and is_process_alive(pid):
                self._log(f"⚠ {script['display_name']} sudah berjalan (PID: {pid})", "warning")
                return

        try:
            # Use the venv python to run the script directly (more reliable for PID tracking)
            py_script_path = os.path.join(APP_DIR, script["py_script"])
            if not os.path.exists(py_script_path):
                self._log(f"❌ File tidak ditemukan: {script['py_script']}", "error")
                return

            # Determine python executable
            python_exe = PYTHON_EXE if os.path.exists(PYTHON_EXE) else sys.executable

            # Set up environment
            child_env = os.environ.copy()
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUNBUFFERED"] = "1"
            # Add venv's Scripts to PATH
            venv_scripts = os.path.join(APP_DIR, "Scripts")
            if os.path.isdir(venv_scripts):
                child_env["PATH"] = venv_scripts + ";" + child_env.get("PATH", "")
                child_env["VIRTUAL_ENV"] = APP_DIR

            proc = subprocess.Popen(
                [python_exe, py_script_path],
                cwd=APP_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                env=child_env,
            )

            # Record PID
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.pid_db[key] = {
                "pid": proc.pid,
                "script": script["py_script"],
                "display_name": script["display_name"],
                "started_at": now,
            }
            save_pid_db(self.pid_db)

            self._log(f"✅ {script['display_name']} dimulai — PID: {proc.pid}", "success")

        except Exception as e:
            self._log(f"❌ Gagal menjalankan {script['display_name']}: {e}", "error")

    def _run_selected(self):
        """Run all selected scripts."""
        selected = self._get_selected_scripts()
        if not selected:
            self._log("⚠ Tidak ada script yang dipilih!", "warning")
            return

        self._log(f"🚀 Menjalankan {len(selected)} script...", "info")
        for script in selected:
            self._run_script(script)
            time.sleep(0.5)  # Small stagger

        self.root.after(1000, self._refresh_status)

    def _run_all(self):
        """Run all scripts."""
        if not self.scripts:
            self._log("⚠ Tidak ada script ditemukan!", "warning")
            return

        self._log(f"🚀 Menjalankan SEMUA {len(self.scripts)} script...", "info")
        for script in self.scripts:
            self._run_script(script)
            time.sleep(0.5)

        self.root.after(1000, self._refresh_status)

    def _kill_script(self, key):
        """Kill a specific script by its key."""
        if key not in self.pid_db:
            self._log(f"⚠ Tidak ada PID tersimpan untuk {key}", "warning")
            return

        pid = self.pid_db[key].get("pid")
        display_name = self.pid_db[key].get("display_name", key)

        if not pid:
            self._log(f"⚠ PID tidak valid untuk {display_name}", "warning")
            return

        try:
            proc = psutil.Process(pid)
            # Kill process tree (including child processes)
            children = proc.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            proc.kill()
            proc.wait(timeout=5)

            self._log(f"🛑 {display_name} dihentikan (PID: {pid})", "error")
        except psutil.NoSuchProcess:
            self._log(f"ℹ {display_name} sudah tidak berjalan (PID: {pid})", "info")
        except psutil.AccessDenied:
            self._log(f"❌ Akses ditolak untuk menghentikan {display_name} (PID: {pid})", "error")
            return
        except Exception as e:
            self._log(f"❌ Error menghentikan {display_name}: {e}", "error")

        # Remove from DB
        del self.pid_db[key]
        save_pid_db(self.pid_db)

        self.root.after(500, self._refresh_status)

    def _kill_all(self):
        """Kill all running scripts."""
        running = []
        for key, data in list(self.pid_db.items()):
            pid = data.get("pid")
            if pid and is_process_alive(pid):
                running.append(key)

        if not running:
            self._log("ℹ Tidak ada script yang sedang berjalan", "info")
            return

        if not messagebox.askyesno(
            "Konfirmasi Kill Semua",
            f"Yakin ingin menghentikan {len(running)} script yang berjalan?",
        ):
            return

        self._log(f"🛑 Menghentikan {len(running)} script...", "error")
        for key in running:
            self._kill_script(key)

    # ═══════════════════════════════════════════════════════════
    #  STATUS REFRESH
    # ═══════════════════════════════════════════════════════════
    def _refresh_status(self):
        """Refresh status of all scripts based on PID database."""
        self.pid_db = load_pid_db()  # Re-read from file (could be modified externally)
        running_count = 0

        for script in self.scripts:
            key = script["bat_name"]
            status_label = self.status_labels.get(key)
            pid_label = self.pid_labels.get(key)
            kill_btn = self.kill_buttons.get(key)

            if not status_label:
                continue

            if key in self.pid_db:
                pid = self.pid_db[key].get("pid")
                if pid and is_process_alive(pid):
                    # RUNNING
                    status_label.configure(text="● RUNNING", fg=COLORS["running"])
                    pid_label.configure(text=str(pid), fg=COLORS["accent"])
                    kill_btn.configure(state=tk.NORMAL)
                    running_count += 1
                else:
                    # Was running but now dead
                    status_label.configure(text="● STOPPED", fg=COLORS["stopped"])
                    pid_label.configure(text=f"({pid})" if pid else "—", fg=COLORS["text_dim"])
                    kill_btn.configure(state=tk.DISABLED)
                    # Clean up dead entry
                    del self.pid_db[key]
                    save_pid_db(self.pid_db)
            else:
                # Never started / not tracked
                status_label.configure(text="● IDLE", fg=COLORS["text_dim"])
                pid_label.configure(text="—", fg=COLORS["text_dim"])
                kill_btn.configure(state=tk.DISABLED)

        # Update running count badge
        if running_count > 0:
            self.running_count_label.configure(
                text=f"{running_count} running",
                bg=COLORS["success"], fg=COLORS["bg_dark"],
            )
        else:
            self.running_count_label.configure(
                text="0 running",
                bg=COLORS["text_dim"], fg=COLORS["bg_dark"],
            )

    def _schedule_refresh(self):
        """Schedule periodic status refresh."""
        self._refresh_status()
        self.root.after(REFRESH_INTERVAL_MS, self._schedule_refresh)

    def _update_clock(self):
        """Update the clock in footer."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.configure(text=f"🕐 {now}")
        self.root.after(1000, self._update_clock)

    def _on_close(self):
        """Handle window close — save state and exit."""
        save_pid_db(self.pid_db)
        self.root.destroy()


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════
def main():
    root = tk.Tk()

    # Center window on screen
    w, h = 1050, 850
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    app = BgRunnerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
