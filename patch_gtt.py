import os, json, re

with open(r'c:\tiktok_automation\gtt_web_server.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Add save_prompts and BAHAN_DIR to imports
text = text.replace('load_prompts,', 'load_prompts,\n    save_prompts,\n    BAHAN_DIR,')
if 'timedelta' not in text:
    text = text.replace('from datetime import datetime', 'from datetime import datetime, timedelta')

# 2. Add _auto_state
auto_state_code = """
_auto_state = {"running": False, "stop_event": None, "thread": None}

def _full_auto_daemon(stop_event):
    web_log("🤖 Full Auto dimulai!", "success", tag="auto")
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
            web_log(f"🚀 Menjalankan pipeline untuk UD: {', '.join(map(str, ready_uds))}", "info", tag="auto")
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
                next_dt = datetime.now() + timedelta(hours=interval_hours)
                if sched_items and len(sched_items) > 0:
                    try:
                        last_dt = datetime.strptime(sched_items[-1]["schedule"], "%Y-%m-%d %H:%M")
                        next_dt = last_dt + timedelta(hours=interval_hours)
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
        web_log(f"⏳ Menunggu jadwal terdekat UD {next_ud} pada {trigger_dt.strftime('%Y-%m-%d %H:%M')} ({(int(wait_sec)//60)} menit)", "info", tag="auto")
        
        elapsed = 0
        while elapsed < wait_sec and not stop_event.is_set():
            time.sleep(min(30, wait_sec - elapsed))
            elapsed += 30

    _auto_state["running"] = False
    web_log("⏹ Full Auto dihentikan.", "warn", tag="auto")
"""
text = text.replace('def _now_time():', auto_state_code + '\n\ndef _now_time():')

# 3. Add auto_running to _status_payload
text = text.replace('"bahan_folders": bahan_folders,', '"bahan_folders": bahan_folders,\n        "auto_running": _auto_state.get("running", False),')


# 4. Add new routes
new_routes = """
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
        web_log(f"Prompt '{name}' disimpan.", "success", tag="config")
        return jsonify({"ok": True})
    elif request.method == "DELETE":
        data = request.get_json(force=True) or {}
        name = data.get("name")
        p = load_prompts()
        if name in p:
            del p[name]
            save_prompts(p)
            web_log(f"Prompt '{name}' dihapus.", "warn", tag="config")
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
        web_log(msg, "success", tag="config")
        return jsonify({"ok": True, "msg": msg})
"""

text = text.replace('@app.route("/api/action/stop", methods=["POST"])', new_routes + '\n@app.route("/api/action/stop", methods=["POST"])')

# 5. Update INDEX_HTML to inject the UI.
html_find = '''    <section class="center">
      <div class="section-head">
        <h2 id="configTitle">Konfigurasi UD 1</h2>'''

html_replace = '''    <section class="center">
      <div class="section-head" style="display:flex; justify-content:space-between; align-items:center; gap: 10px; border-bottom: 0;">
        <div style="display:flex; gap: 10px;">
          <button id="tabSettingsBtn" onclick="switchTab('settings')" style="background:var(--brand);">Settings UD</button>
          <button id="tabResourcesBtn" onclick="switchTab('resources')" class="secondary">Prompt & Bahan</button>
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

      <!-- SETTINGS TAB -->
      <div id="tabSettings" style="display:block; border-top: 1px solid var(--line);">
        <div class="section-head" style="border-top: none;">
          <h2 id="configTitle">Konfigurasi UD 1</h2>'''

text = text.replace(html_find, html_replace)

html_find_end_center = '''        <label>Preview stok</label>
        <div class="file-list" id="stokPreview"></div>
      </div>
    </section>'''

html_replace_end_center = '''        <label>Preview stok</label>
        <div class="file-list" id="stokPreview"></div>
      </div>
      </div>
    </section>'''

text = text.replace(html_find_end_center, html_replace_end_center)

js_find = '''function renderUdGrid() {'''

js_replace = '''function switchTab(tab) {
  $('tabSettings').style.display = tab === 'settings' ? 'block' : 'none';
  $('tabResources').style.display = tab === 'resources' ? 'block' : 'none';
  $('tabSettingsBtn').className = tab === 'settings' ? '' : 'secondary';
  $('tabResourcesBtn').className = tab === 'resources' ? '' : 'secondary';
  if(tab === 'resources') refreshResources();
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

function renderUdGrid() {'''

text = text.replace(js_find, js_replace)

js_update_find = '''  $('runPill').textContent = running ? 'running' : 'idle';
  $('activeInput').value = state.active_uds.join(',');'''

js_update_replace = '''  $('runPill').textContent = running ? 'running' : 'idle';
  $('activeInput').value = state.active_uds.join(',');
  if ($('autoSwitch').checked !== state.auto_running) {
    $('autoSwitch').checked = state.auto_running;
  }'''

text = text.replace(js_update_find, js_update_replace)

# Final write check: did replacements work?
tests = [
  ("1. save_prompts added", 'save_prompts' in text),
  ("2. _auto_state added", '_auto_state =' in text),
  ("3. auto_running injected", 'auto_running' in text),
  ("4. routes injected", '/api/auto/start' in text),
  ("5. html section injected", 'tabSettingsBtn' in text),
  ("6. html end injected", 'tabSettings' in text),
  ("7. js setup injected", 'switchTab' in text),
  ("8. autoSwitch injected", 'autoSwitch' in text),
]

for t, passed in tests:
    print(t, passed)

with open(r'c:\tiktok_automation\gtt_web_server.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated gtt_web_server.py successfully")
