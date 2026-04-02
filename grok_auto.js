// ═══════════════════════════════════════════════════════════════
//  GROK AUTO JS — Injected by Selenium to automate grok.com
//  Works independently; Selenium only manages Chrome lifecycle
// ═══════════════════════════════════════════════════════════════

(function() {
    'use strict';

    // ── Prevent double-injection ──
    if (window.__GROK_AUTO_INJECTED) return;
    window.__GROK_AUTO_INJECTED = true;

    // ── State shared with Selenium ──
    window.__GROK_AUTO = {
        status: 'idle',        // idle | running | done | error | cancelled
        progress: 0,           // 0-100
        message: '',           // Human-readable status
        videoUrl: null,        // Extracted video URL after generation
        error: null,           // Error message if any
        downloadReady: false,  // True when video is ready to download
        totalGenerated: 0,     // Running total of generated videos
    };

    const STATE = window.__GROK_AUTO;

    // ── Helpers ──
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    function log(msg) {
        STATE.message = msg;
        console.log(`[GrokAuto] ${msg}`);
    }

    function $(selector) {
        return document.querySelector(selector);
    }

    function $$(selector) {
        return document.querySelectorAll(selector);
    }

    function isVisible(el) {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;
        const style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
    }

    async function waitForElement(selector, timeout = 15000, mustBeVisible = true) {
        const start = Date.now();
        while (Date.now() - start < timeout) {
            const el = $(selector);
            if (el && (!mustBeVisible || isVisible(el))) return el;
            await sleep(200);
        }
        return null;
    }

    async function waitForAnyElement(selectors, timeout = 15000) {
        const start = Date.now();
        while (Date.now() - start < timeout) {
            for (const sel of selectors) {
                const el = $(sel);
                if (el && isVisible(el)) return el;
            }
            await sleep(200);
        }
        return null;
    }

    function simulateClick(el) {
        if (!el) return;
        const events = ['pointerover', 'mouseover', 'pointerdown', 'mousedown',
                        'pointerup', 'mouseup', 'click'];
        for (const evName of events) {
            const Ctor = evName.startsWith('pointer') ? PointerEvent : MouseEvent;
            el.dispatchEvent(new Ctor(evName, {
                bubbles: true, cancelable: true, composed: true,
                view: window, detail: 1
            }));
        }
    }

    // ── Navigate to /imagine if needed ──
    async function ensureImaginePage() {
        if (location.pathname.includes('/imagine') && !location.pathname.includes('/imagine/')) {
            log('✅ Already on /imagine');
            return true;
        }
        log('🌐 Navigating to /imagine...');
        // Try clicking the Imagine link on the page first
        const imagineLink = await waitForElement('a[href="/imagine"]', 5000);
        if (imagineLink) {
            simulateClick(imagineLink);
            await sleep(2000);
            if (location.pathname.includes('/imagine')) {
                log('✅ Navigated to /imagine via link');
                return true;
            }
        }
        // Fallback: navigate directly
        location.href = 'https://grok.com/imagine';
        await sleep(3000);
        return location.pathname.includes('/imagine');
    }

    // ── Upload image via file input ──
    async function uploadImage(imageBase64, imageName) {
        log('📷 Uploading image...');

        // Decode base64 to blob
        let b64 = imageBase64;
        if (b64.includes(',')) b64 = b64.split(',')[1];
        const binary = atob(b64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        const blob = new Blob([bytes], { type: 'image/jpeg' });
        const file = new File([blob], imageName || `image-${Date.now()}.jpg`, { type: 'image/jpeg' });

        // Find file input
        const fileInput = await waitForElement('input[type="file"]', 10000, false);
        if (!fileInput) {
            log('⚠️ File input not found');
            return false;
        }

        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
        fileInput.dispatchEvent(new Event('change', { bubbles: true }));

        log('📤 Image sent to file input');
        await sleep(3000);

        // Wait for upload indicator to disappear
        const start = Date.now();
        while (Date.now() - start < 30000) {
            // Check for uploading spinner
            const uploading = $('div[class*="uploading"], .animate-spin');
            if (!uploading || !isVisible(uploading)) break;
            await sleep(500);
        }

        log('✅ Image uploaded');
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  SELECT VIDEO SETTINGS
    //  Selects: Video mode | 720p | 10s | 9:16 ratio
    //  Uses the inline radio groups visible in the query bar UI.
    // ═══════════════════════════════════════════════════════════════

    // Helper: click a radio button inside a named radio group by label text
    async function clickRadioOption(groupAriaLabel, optionText, retries = 3) {
        for (let attempt = 1; attempt <= retries; attempt++) {
            try {
                const group = $(`div[role="radiogroup"][aria-label="${groupAriaLabel}"]`);
                if (!group) {
                    log(`⚠️ Radio group "${groupAriaLabel}" not found (attempt ${attempt})`);
                    await sleep(800);
                    continue;
                }
                const buttons = group.querySelectorAll('button[role="radio"]');
                for (const btn of buttons) {
                    const txt = (btn.textContent || '').trim();
                    if (txt === optionText || txt.includes(optionText)) {
                        const alreadyChecked = btn.getAttribute('aria-checked') === 'true';
                        if (alreadyChecked) {
                            log(`✅ "${optionText}" in "${groupAriaLabel}" already selected`);
                            return true;
                        }
                        simulateClick(btn);
                        await sleep(400);
                        // Verify selection
                        if (btn.getAttribute('aria-checked') === 'true') {
                            log(`✅ "${optionText}" in "${groupAriaLabel}" selected`);
                            return true;
                        }
                        log(`⚠️ Click sent but aria-checked not true yet, retrying...`);
                    }
                }
                log(`⚠️ Option "${optionText}" not found in group "${groupAriaLabel}" (attempt ${attempt})`);
            } catch(e) {
                log(`⚠️ clickRadioOption error: ${e.message}`);
            }
            await sleep(600);
        }
        return false;
    }

    // Helper: select aspect ratio from the dropdown (button + menu)
    async function selectAspectRatio(ratio = '9:16', retries = 3) {
        for (let attempt = 1; attempt <= retries; attempt++) {
            try {
                // Find the Aspect Ratio button
                const ratioBtn = $('button[aria-label="Rasio Aspek"], button[aria-label="Aspect Ratio"]');
                if (!ratioBtn) {
                    log(`⚠️ Aspect ratio button not found (attempt ${attempt})`);
                    await sleep(800);
                    continue;
                }

                // Check if already showing desired ratio in button text
                const currentText = (ratioBtn.textContent || '').trim();
                if (currentText.includes(ratio)) {
                    log(`✅ Aspect ratio ${ratio} already selected`);
                    return true;
                }

                // Open the dropdown
                simulateClick(ratioBtn);
                await sleep(700);

                // Find the ratio option in the menu
                // The menu items appear as: div[role="menu"] > div[role="menuitem"] or button
                const menuItems = [
                    ...$$('div[role="menuitem"]'),
                    ...$$('button[role="menuitem"]'),
                    ...$$('div[data-radix-collection-item]'),
                ];

                let clicked = false;
                for (const item of menuItems) {
                    const txt = (item.textContent || '').trim();
                    if (txt === ratio || txt.includes(ratio)) {
                        simulateClick(item);
                        await sleep(500);
                        clicked = true;
                        log(`✅ Aspect ratio ${ratio} selected`);
                        break;
                    }
                }

                if (!clicked) {
                    // Fallback: look for any element with exact ratio text
                    for (const el of $$('*')) {
                        if (el.children.length === 0) {
                            const t = (el.textContent || '').trim();
                            if (t === ratio) {
                                simulateClick(el.closest('[role="menuitem"]') || el);
                                await sleep(500);
                                clicked = true;
                                log(`✅ Aspect ratio ${ratio} selected (fallback)`);
                                break;
                            }
                        }
                    }
                }

                // Close dropdown if still open (press Escape)
                if (!clicked) {
                    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
                    await sleep(300);
                    log(`⚠️ Ratio ${ratio} option not found in dropdown (attempt ${attempt})`);
                    continue;
                }

                return true;

            } catch(e) {
                log(`⚠️ selectAspectRatio error: ${e.message}`);
            }
            await sleep(600);
        }
        return false;
    }

    // ── Main settings selector: Video | 720p | 10s | 9:16 ──
    async function selectVideoSettings() {
        log('⚙️ Configuring video settings: Video | 720p | 10s | 9:16...');

        // Wait for the query bar controls to be rendered
        const barReady = await waitForElement('div[role="radiogroup"]', 8000);
        if (!barReady) {
            log('⚠️ Radio controls not found in page, skipping settings');
            return false;
        }
        await sleep(500);

        let allOk = true;

        // 1. Mode → Video
        //    aria-label in Indonesian = "Mode generasi", English = "Generation Mode"
        const modeOk = await clickRadioOption('Mode generasi', 'Video')
                    || await clickRadioOption('Generation Mode', 'Video');
        if (!modeOk) {
            log('⚠️ Could not select Video mode, trying fallback...');
            // Fallback: find any radio button with text "Video" inside any radiogroup
            for (const rg of $$('div[role="radiogroup"]')) {
                for (const btn of rg.querySelectorAll('button[role="radio"]')) {
                    if ((btn.textContent || '').trim() === 'Video') {
                        simulateClick(btn);
                        await sleep(400);
                        log('✅ Video mode selected (fallback)');
                        break;
                    }
                }
            }
        }
        await sleep(300);

        // 2. Resolution → 720p
        //    aria-label: "Resolusi Video" (ID) or "Video Resolution" (EN)
        const resOk = await clickRadioOption('Resolusi Video', '720p')
                   || await clickRadioOption('Video Resolution', '720p');
        if (!resOk) allOk = false;
        await sleep(300);

        // 3. Duration → 10s
        //    aria-label: "Durasi Video" (ID) or "Video Duration" (EN)
        const durOk = await clickRadioOption('Durasi Video', '10s')
                   || await clickRadioOption('Video Duration', '10s');
        if (!durOk) allOk = false;
        await sleep(300);

        // 4. Aspect Ratio → 9:16
        const ratioOk = await selectAspectRatio('9:16');
        if (!ratioOk) allOk = false;
        await sleep(300);

        if (allOk) {
            log('✅ All video settings configured: Video | 720p | 10s | 9:16');
        } else {
            log('⚠️ Some settings may not have been set correctly, continuing anyway...');
        }
        return true;
    }

    // Backward-compat alias
    async function selectVideoMode() {
        return selectVideoSettings();
    }

    // ── Fill prompt text ──
    async function fillPrompt(promptText) {
        log('📝 Filling prompt...');

        // Find the content-editable prompt editor (TipTap/ProseMirror)
        let editor = $('div.tiptap.ProseMirror[contenteditable="true"]');
        if (!editor) {
            // Try generic contenteditable
            editor = $('[contenteditable="true"]');
        }
        // Also try textarea (rare)
        const textarea = $('textarea');

        if (editor) {
            editor.scrollIntoView({ block: 'center' });
            editor.focus();
            await sleep(300);

            // Clear existing content
            document.execCommand('selectAll', false);
            document.execCommand('delete', false);
            await sleep(200);

            // Insert text
            document.execCommand('insertText', false, promptText);
            editor.dispatchEvent(new Event('input', { bubbles: true }));
            editor.dispatchEvent(new Event('change', { bubbles: true }));

            await sleep(500);

            // Verify
            const actual = editor.textContent || '';
            if (actual.trim()) {
                log(`✅ Prompt filled: ${promptText.substring(0, 60)}...`);
                return true;
            }

            // Fallback: innerHTML method
            log('🔄 Trying innerHTML method...');
            editor.innerHTML = '<p>' + promptText + '</p>';
            editor.dispatchEvent(new Event('input', { bubbles: true }));
            editor.dispatchEvent(new Event('change', { bubbles: true }));
            editor.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            await sleep(500);

            if (editor.textContent.trim()) {
                log(`✅ Prompt filled (innerHTML): ${promptText.substring(0, 60)}...`);
                return true;
            }
        } else if (textarea) {
            textarea.focus();
            textarea.value = '';
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            document.execCommand('insertText', false, promptText);
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            textarea.dispatchEvent(new Event('change', { bubbles: true }));
            await sleep(500);
            if (textarea.value.trim()) {
                log(`✅ Prompt filled (textarea): ${promptText.substring(0, 60)}...`);
                return true;
            }
        }

        log('❌ Could not fill prompt');
        return false;
    }

    // ── Click Generate button ──
    async function clickGenerate() {
        log('🚀 Clicking Generate...');

        // 1. Try known aria-labels (exact match or partial)
        const labels = ['buat video', 'create video', 'generate', 'submit', 'buat gambar', 'create image', 'send'];
        const allBtns = document.querySelectorAll('button');
        for (const btn of allBtns) {
            if (!isVisible(btn)) continue;
            const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
            if (labels.some(l => aria.includes(l))) {
                simulateClick(btn);
                try { btn.click(); } catch(e){}
                log(`✅ Generate clicked (aria-label: ${aria})`);
                await sleep(2000);
                return true;
            }
        }

        // 2. Try finding button by Send / Arrow Up SVG icon
        // Usually the submit button has an SVG path like M... (an arrow up)
        for (const btn of allBtns) {
            if (!isVisible(btn)) continue;
            const paths = btn.querySelectorAll('svg path');
            if (paths.length > 0) {
                const d = Array.from(paths).map(p => p.getAttribute('d') || '').join(' ');
                // Send/Arrow icon typical paths in Grok
                if (d.includes('M3') && d.includes('21l19-9') || // classic send
                    d.includes('4 12l1.41 1.41L11') ||           // arrow up
                    d.includes('M12 4l-8 8h6v8h4v-8h6z') ||      // another up arrow
                    d.includes('15 21v-8a1 1')) {                // another variant
                    
                    // pastikan tombol ini ada di dekat text area (di "bottom" layar biasanya)
                    const rect = btn.getBoundingClientRect();
                    if (rect.bottom > window.innerHeight / 2) {
                        simulateClick(btn);
                        try { btn.click(); } catch(e){}
                        log(`✅ Generate clicked (SVG icon match)`);
                        await sleep(2000);
                        return true;
                    }
                }
            }
        }

        // 3. Fallback: submit with Ctrl+Enter / Enter on editor
        const editor = $('div.tiptap.ProseMirror[contenteditable="true"]') || $('[contenteditable="true"]');
        if (editor) {
            editor.focus();
            
            // Dispatch Ctrl+Enter
            const eventCtrl = new KeyboardEvent('keydown', {
                key: 'Enter', code: 'Enter', keyCode: 13,
                ctrlKey: true, metaKey: true, bubbles: true, cancelable: true
            });
            editor.dispatchEvent(eventCtrl);
            await sleep(500);
            
            // Dispatch plain Enter
            const eventEnter = new KeyboardEvent('keydown', {
                key: 'Enter', code: 'Enter', keyCode: 13,
                bubbles: true, cancelable: true
            });
            editor.dispatchEvent(eventEnter);
            
            log('✅ Generate triggered via Enter keys on editor');
            await sleep(2000);
            
            // After enter, check if generating overlay appears to confirm it worked
            if (document.querySelector('span.animate-pulse')) {
                return true;
            }
        }

        // 4. Last resort: find any round isolated button near the editor
        const roundBtn = $('button.group[type="button"]') || $('button.rounded-full[type="button"]');
        if (roundBtn && isVisible(roundBtn)) {
            simulateClick(roundBtn);
            try { roundBtn.click(); } catch(e){}
            log('✅ Generate clicked (fallback round button)');
            await sleep(2000);
            return true;
        }

        log('❌ Could not find Generate button');
        return false;
    }

    // ═══════════════════════════════════════════════════════════════
    //  PRECISE PROGRESS DETECTION
    //
    //  "Generating" state: span.animate-pulse with text "Generating" /
    //   "Membuat" / "Membatalkan" visible + span.tabular-nums.animate-pulse
    //   showing "16%" etc.
    //
    //  "Done" state: generating overlay GONE + video#sd-video has a
    //   real assets.grok.com .mp4 src.
    // ═══════════════════════════════════════════════════════════════

    // Returns true if the generating overlay is currently visible.
    function _isGeneratingOverlayVisible() {
        // Check animate-pulse spans: "Generating" / "Membuat" / "Menghasilkan"
        const pulseSpans = $$('span.animate-pulse');
        for (const s of pulseSpans) {
            const t = s.textContent.trim();
            if (t === 'Generating' || t === 'Membuat' || t === 'Menghasilkan') return true;
        }
        // Fallback: check for cancel button text
        for (const btn of $$('button')) {
            const t = btn.textContent.trim();
            if (t === 'Membatalkan' || t === 'Cancel' || t === 'Cancelling') {
                if (isVisible(btn)) return true;
            }
        }
        // Fallback 2: check for any span with animate-pulse containing percentage
        for (const s of pulseSpans) {
            const t = s.textContent.trim();
            if (t.match(/^\d+%$/)) return true;
        }
        return false;
    }

    // Returns percentage from the generating overlay (0 if not visible).
    function _readGeneratingPercent() {
        // span.tabular-nums.animate-pulse contains "16%"
        for (const s of $$('span.tabular-nums')) {
            const t = s.textContent.trim();
            if (t.includes('%') && s.classList.contains('animate-pulse')) {
                const m = t.match(/(\d+)/);
                if (m) return parseInt(m[1]);
            }
        }
        // Fallback: any tabular-nums span with %
        for (const s of $$('span.tabular-nums')) {
            const t = s.textContent.trim();
            if (t.includes('%')) {
                const m = t.match(/(\d+)/);
                if (m) return parseInt(m[1]);
            }
        }
        return 0;
    }

    // Returns the generated video URL from video#sd-video (done state).
    function _getFinishedVideoUrl() {
        // Find ALL videos to ensure we only return the LAST (newest) matching one
        const allVideos = Array.from(document.querySelectorAll('video'));
        if (allVideos.length === 0) return null;
        
        // Loop backwards to find the newest response
        for (let i = allVideos.length - 1; i >= 0; i--) {
            const v = allVideos[i];
            if (v.src && v.src.includes('assets.grok.com') && v.src.includes('.mp4')) {
                // Pastikan video visible (bukan placeholder dari generating state)
                const style = v.getAttribute('style') || '';
                // check visibility
                if (isVisible(v) && (!style.includes('visibility: hidden'))) {
                    return v.src;
                }
            }
        }
        return null;
    }

    // Returns true if Grok rate limit has been reached.
    // Detects the Sonner toast popup with data-type="error" containing
    // "Rate limit reached" or "Upgrade to SuperGrok".
    function _isRateLimitReached() {
        // Method 1: Sonner toast with data-type="error" (primary — paling akurat)
        const toasts = document.querySelectorAll('li[data-sonner-toast][data-type="error"]');
        for (const toast of toasts) {
            const text = (toast.textContent || '').toLowerCase();
            if (text.includes('rate limit') || text.includes('supergrok')) {
                return true;
            }
        }
        // Method 2: Fallback — cari span dengan teks spesifik
        const spans = document.querySelectorAll('span.font-medium, span.font-bold, span.font-semibold');
        for (const s of spans) {
            const t = (s.textContent || '').toLowerCase();
            if ((t.includes('rate limit') && t.includes('reached')) ||
                (t.includes('upgrade') && t.includes('supergrok'))) {
                // Pastikan parent-nya visible (bukan hidden element)
                if (isVisible(s) || (s.closest('li[data-sonner-toast]'))) {
                    return true;
                }
            }
        }
        return false;
    }

    // Returns true if the download button (Unduh/Download) is visible.
    // Detects via: aria-label OR SVG download icon path inside button
    function _isDownloadButtonVisible() {
        return _findDownloadButton() !== null;
    }

    // Helper: find the actual download button element for clicking (NEWEST only)
    function _findDownloadButton() {
        // Karena ada history chat, kita HANYA peduli tombol pada response TERAKHIR
        const articleBtns = Array.from(document.querySelectorAll(
            'main article button, [role="article"] button'
        )).filter(b => isVisible(b));

        // Iterate backwards (dari yang terbaru di bawah)
        for (let i = articleBtns.length - 1; i >= 0; i--) {
            const btn = articleBtns[i];
            
            // Method 1: aria-label
            const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
            if (aria === 'unduh' || aria === 'download') {
                return btn;
            }

            // Method 2: SVG icon
            const svgPaths = btn.querySelectorAll('svg path');
            if (svgPaths.length > 0) {
                const pathData = Array.from(svgPaths).map(p => p.getAttribute('d') || '').join(' ');
                if (pathData.includes('21 15') && pathData.includes('v4') && pathData.includes('M7 10')) {
                    return btn;
                }
                if (pathData.includes('M12') && pathData.includes('l5 5') && pathData.includes('v4')) {
                    return btn;
                }
            }
        }

        // Method 3: jika URL video jadi ada, setidaknya kita anggap state "ada download" = true
        // Ini tidak mereturn button, jadi hanya fallback untuk `_isDownloadButtonVisible` yang mereturn true (boolean check).
        // Fungsi ini mereturn null bila gak ada tombol, sehingga kita biarkan _getFinishedVideoUrl di tempat lain yang mendownloadnya
        return null;
    }

    // ── Track progress (PRECISE — waits for real "done" signal) ──
    async function trackProgress(timeoutMs = 600000) {
        log('⏳ Waiting for generation to start...');
        const start = Date.now();
        let lastPct = -1;
        let generationStarted = false;
        let startWaitMs = Date.now();
        const START_TIMEOUT = 30000; // 30s to detect generation start

        while (Date.now() - start < timeoutMs) {
            if (STATE.status === 'cancelled') return false;

            // ─ Check rate limit ─
            if (_isRateLimitReached()) {
                log('🚫 RATE LIMIT REACHED! Grok meminta upgrade ke SuperGrok.');
                STATE.status = 'rate_limited';
                STATE.error = 'Rate limit reached';
                return false;
            }


            const isGenerating = _isGeneratingOverlayVisible();
            const pctNum = _readGeneratingPercent();

            // ─ Detect generation started ─
            if (!generationStarted) {
                if (isGenerating || pctNum > 0) {
                    generationStarted = true;
                    log('⏳ Generation started! Monitoring progress...');
                } else if (Date.now() - startWaitMs > START_TIMEOUT) {
                    // Check if already done (fast generation)
                    const videoUrl = _getFinishedVideoUrl();
                    if (videoUrl || _isDownloadButtonVisible()) {
                        log('✅ Generation completed instantly or already done!');
                        STATE.progress = 100;
                        STATE.videoUrl = videoUrl;
                        return true;
                    }
                    // Still nothing after 30s — might have missed the start
                    log('⚠️ Generation not detected in 30s, checking if already done...');
                    generationStarted = true; // Assume started, check done
                }
                await sleep(1000);
                continue;
            }

            // ─ While generating: log progress ─
            if (isGenerating) {
                if (pctNum !== lastPct && pctNum > 0) {
                    STATE.progress = pctNum;
                    log(`⏳ Generating: ${pctNum}%`);
                    lastPct = pctNum;
                }
                await sleep(1500);
                continue;
            }

            // ─ Not generating anymore — check for Skip / "I prefer this" ─
            // Grok sometimes shows 2 video options with Skip button
            const skipBtn = Array.from(document.querySelectorAll('button')).find(b =>
                (b.textContent || '').trim() === 'Skip' && isVisible(b));
            if (skipBtn) {
                log('⏭ Menerima 2 opsi video. Klik "Skip"...');
                simulateClick(skipBtn);
                STATE.progress = 99;
                await sleep(3000);
                continue;
            }
            const preferBtn = Array.from(document.querySelectorAll('button')).find(b => {
                const t = (b.textContent || '').trim().toLowerCase();
                return (t.includes('prefer this') || t.includes('suka ini')) && isVisible(b);
            });
            if (preferBtn) {
                log('💡 Menerima 2 opsi video. Klik "I prefer this"...');
                simulateClick(preferBtn);
                STATE.progress = 99;
                await sleep(3000);
                continue;
            }

            // ─ Check for result ─
            // CRITICAL: only declare done when generating overlay is GONE
            const videoUrl = _getFinishedVideoUrl();
            if (videoUrl) {
                STATE.progress = 100;
                STATE.videoUrl = videoUrl;
                log(`✅ Generation complete! Video URL: ${videoUrl.substring(0, 80)}...`);
                await sleep(1500); // Small grace period for page to settle
                return true;
            }

            if (_isDownloadButtonVisible()) {
                STATE.progress = 100;
                log('✅ Generation complete! Download button visible.');
                await sleep(1000);
                return true;
            }

            // Still waiting for video to appear (brief race between overlay gone + video src set)
            if (Date.now() - start > 10000) { // Only after 10s from start
                log('⏳ Generating overlay gone, waiting for video element...');
                await sleep(2000);
                // One more check
                const url2 = _getFinishedVideoUrl();
                if (url2) {
                    STATE.progress = 100;
                    STATE.videoUrl = url2;
                    log(`✅ Video URL found after wait: ${url2.substring(0, 80)}...`);
                    return true;
                }
                if (_isDownloadButtonVisible()) {
                    STATE.progress = 100;
                    log('✅ Download button found after wait.');
                    return true;
                }
            }

            await sleep(1500);
        }

        log('❌ Timeout waiting for generation to complete');
        return false;
    }

    // ── Extract video URL (prefers video#sd-video with real .mp4 src) ──
    async function extractVideoUrl() {
        log('🔍 Extracting video URL...');

        // Priority 1: video#sd-video (the standard def video — always has .mp4 src when done)
        const sdVideo = $('video#sd-video');
        if (sdVideo && sdVideo.src && sdVideo.src.startsWith('https://')) {
            STATE.videoUrl = sdVideo.src;
            log(`✅ Video URL (sd-video): ${sdVideo.src.substring(0, 80)}...`);
            return sdVideo.src;
        }

        // Priority 2: video#hd-video
        const hdVideo = $('video#hd-video');
        if (hdVideo && hdVideo.src && hdVideo.src.startsWith('https://')) {
            STATE.videoUrl = hdVideo.src;
            log(`✅ Video URL (hd-video): ${hdVideo.src.substring(0, 80)}...`);
            return hdVideo.src;
        }

        // Priority 3: use STATE.videoUrl set by trackProgress
        if (STATE.videoUrl && STATE.videoUrl.startsWith('https://')) {
            log(`✅ Video URL (from STATE): ${STATE.videoUrl.substring(0, 80)}...`);
            return STATE.videoUrl;
        }

        // Priority 4: any video with real http .mp4 src
        for (const v of $$('video')) {
            if (v.src && v.src.startsWith('https://') && v.src.includes('.mp4')) {
                STATE.videoUrl = v.src;
                log(`✅ Video URL (fallback): ${v.src.substring(0, 80)}...`);
                return v.src;
            }
        }

        // Priority 5: blob URL (will need download button click)
        for (const v of $$('video')) {
            if (v.src && v.src.startsWith('blob:')) {
                STATE.videoUrl = v.src;
                log('⚠️ Video is blob URL — will use download button method');
                return v.src;
            }
        }

        // Priority 6: download link
        for (const a of $$('a[download], a[href*=".mp4"]')) {
            if (a.href && a.href.startsWith('https://')) {
                STATE.videoUrl = a.href;
                log(`✅ Video URL (download link): ${a.href.substring(0, 80)}...`);
                return a.href;
            }
        }

        log('⚠️ No video URL found');
        return null;
    }

    // ── Extract image URLs ──
    async function extractImageUrls() {
        log('🔍 Extracting image URLs...');
        const urls = [];
        for (const img of $$('article img, .grid img')) {
            const src = img.src || '';
            if (src.startsWith('https://') && src.includes('assets.grok.com') && src.length > 50) {
                urls.push(src);
            }
        }
        if (urls.length > 0) log(`✅ Found ${urls.length} image(s)`);
        return urls;
    }

    // ── Click Download button (waits for it to appear, then clicks) ──
    async function clickDownloadButton() {
        log('📥 Waiting for Download button...');

        // Wait up to 15s for the Unduh/Download button to appear
        const dl = await waitForElement(
            'button[aria-label="Unduh"], button[aria-label="Download"]',
            15000,
            true
        );

        if (!dl) {
            // If STATE.videoUrl already set (from trackProgress), skip button click
            if (STATE.videoUrl && STATE.videoUrl.startsWith('https://')) {
                log('⚠️ Download button not found, but video URL available — skip button click');
                return true;
            }
            log('⚠️ Download button not found');
            return false;
        }

        dl.scrollIntoView({ block: 'center', behavior: 'smooth' });
        await sleep(400);

        // Full pointer event dispatch to trigger React onClick
        simulateClick(dl);
        log('✅ Download (Unduh) button clicked');
        await sleep(2000);
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  MAIN GENERATE FUNCTION — Called from Selenium
    // ═══════════════════════════════════════════════════════════════
    window.__grokGenerate = async function(config) {
        /*
        config = {
            prompt: string,           // Prompt text
            mode: 'video' | 'image',  // Generation mode (default: 'video')
            image: string | null,     // Base64 image data for image-to-video (optional)
            imageName: string,        // Name for uploaded image
            timeout: number,          // Timeout in ms (default: 600000)
        }
        */
        STATE.status = 'running';
        STATE.progress = 0;
        STATE.videoUrl = null;
        STATE.error = null;
        STATE.downloadReady = false;
        STATE.message = 'Starting...';

        try {
            // Step 1: Navigate to /imagine
            if (!await ensureImaginePage()) {
                // Wait for page load after navigation
                await sleep(3000);
                if (!location.pathname.includes('/imagine')) {
                    throw new Error('Failed to navigate to /imagine');
                }
            }
            await sleep(2000);

            if (STATE.status === 'cancelled') return STATE;

            // Step 2: Upload image if provided
            if (config.image) {
                const uploaded = await uploadImage(config.image, config.imageName || 'ref.jpg');
                if (!uploaded) {
                    log('⚠️ Image upload failed, continuing without image');
                }
            }

            if (STATE.status === 'cancelled') return STATE;

            // Step 3: Configure video settings (mode, resolution, duration, ratio)
            if (config.mode !== 'image') {
                await selectVideoSettings();
            }

            if (STATE.status === 'cancelled') return STATE;

            // Step 4: Fill prompt
            const promptFilled = await fillPrompt(config.prompt);
            if (!promptFilled) {
                throw new Error('Failed to fill prompt');
            }

            if (STATE.status === 'cancelled') return STATE;

            // Step 5: Click Generate
            const generated = await clickGenerate();
            if (!generated) {
                throw new Error('Failed to click Generate');
            }

            // Step 6: Track progress
            await sleep(3000); // Wait for generation to start
            const completed = await trackProgress(config.timeout || 600000);
            if (!completed) {
                if (STATE.status === 'cancelled') return STATE;
                throw new Error('Generation timed out or failed');
            }

            // Step 7: Extract result
            await sleep(2000);
            if (config.mode === 'video') {
                const url = await extractVideoUrl();
                if (url) {
                    STATE.downloadReady = true;
                }
            } else {
                const urls = await extractImageUrls();
                if (urls.length > 0) {
                    STATE.videoUrl = urls[0]; // Store first URL
                    STATE.downloadReady = true;
                }
            }

            // Step 8: Click Download
            await clickDownloadButton();

            STATE.status = 'done';
            STATE.totalGenerated++;
            log(`✅ Generation #${STATE.totalGenerated} complete!`);
            return STATE;

        } catch (err) {
            STATE.status = 'error';
            STATE.error = err.message || String(err);
            log(`❌ Error: ${STATE.error}`);
            return STATE;
        }
    };

    // ═══════════════════════════════════════════════════════════════
    //  CANCEL — Called from Selenium
    // ═══════════════════════════════════════════════════════════════
    window.__grokCancel = function() {
        STATE.status = 'cancelled';
        STATE.message = 'Cancelled by user';
        log('🛑 Generation cancelled');
    };

    // ═══════════════════════════════════════════════════════════════
    //  GET STATE — Called from Selenium
    // ═══════════════════════════════════════════════════════════════
    window.__grokGetState = function() {
        return { ...STATE };
    };

    // ═══════════════════════════════════════════════════════════════
    //  MULTI-TAB BATCH — Generate across multiple tabs
    // ═══════════════════════════════════════════════════════════════
    window.__grokBatchState = {
        tabs: [],        // { tabIndex, status, progress, error, videoUrl }
        totalDone: 0,
        totalFailed: 0,
        running: false,
    };

    // Generate on THIS tab (called after Selenium switches to the tab)
    window.__grokTabGenerate = async function(tabIndex, config) {
        const batch = window.__grokBatchState;
        batch.running = true;

        // Init tab state
        if (!batch.tabs[tabIndex]) {
            batch.tabs[tabIndex] = {
                tabIndex, status: 'idle', progress: 0, error: null, videoUrl: null
            };
        }
        const tabState = batch.tabs[tabIndex];
        tabState.status = 'running';
        tabState.progress = 0;
        tabState.error = null;
        tabState.videoUrl = null;

        try {
            // Reset local state
            STATE.status = 'running';
            STATE.progress = 0;
            STATE.videoUrl = null;
            STATE.error = null;

            // We're already on the tab, Selenium navigated us to /imagine
            await sleep(1000);

            // Upload image if provided
            if (config.image) {
                await uploadImage(config.image, config.imageName || 'ref.jpg');
            }

            // Configure all video settings
            if (config.mode !== 'image') {
                await selectVideoSettings();
            }

            // Fill prompt
            const filled = await fillPrompt(config.prompt);
            if (!filled) {
                tabState.status = 'error';
                tabState.error = 'Prompt fill failed';
                return tabState;
            }

            // Snapshot semua video URL yang sudah ada SEBELUM generate diklik
            // Ini untuk membedakan video lama (history) vs video baru (hasil generate)
            tabState.initialVideoUrls = Array.from(document.querySelectorAll('video'))
                .map(v => v.src)
                .filter(s => s && s.includes('assets.grok.com') && s.includes('.mp4'));
            log(`[Tab ${tabIndex}] 📸 Snapshot ${tabState.initialVideoUrls.length} existing video URLs`);

            // Click generate
            const clicked = await clickGenerate();
            if (!clicked) {
                tabState.status = 'error';
                tabState.error = 'Generate click failed';
                return tabState;
            }

            tabState.status = 'generating';
            tabState._config = config;  // Store config for stall retry (re-fill prompt)
            log(`[Tab ${tabIndex}] ✅ Generate started`);
            return tabState;

        } catch (err) {
            tabState.status = 'error';
            tabState.error = err.message || String(err);
            batch.totalFailed++;
            return tabState;
        }
    };

    // ── Check progress — SYNCHRONOUS ──
    // KRITIS: execute_script("return fn()") tidak bisa handle Promise.
    // Hanya membaca DOM state — tidak perlu await apapun.
    window.__grokTabCheckProgress = function(tabIndex) {
        const batch = window.__grokBatchState;
        if (!batch.tabs[tabIndex]) {
            batch.tabs[tabIndex] = {
                tabIndex, status: 'unknown', progress: 0,
                videoUrl: null, generatingOccurred: false, preferClicked: false,
                firstCheckTs: Date.now(), retryCount: 0, retrying: false,
                lastProgressTs: Date.now(), lastProgressPct: -1, stallRetryCount: 0
            };
        }
        const tabState = batch.tabs[tabIndex];

        // Init fields jika belum ada (backward compat)
        if (!tabState.firstCheckTs) tabState.firstCheckTs = Date.now();
        if (tabState.retryCount === undefined) tabState.retryCount = 0;
        if (tabState.retrying === undefined) tabState.retrying = false;
        if (tabState.lastProgressTs === undefined) tabState.lastProgressTs = Date.now();
        if (tabState.lastProgressPct === undefined) tabState.lastProgressPct = -1;
        if (tabState.stallRetryCount === undefined) tabState.stallRetryCount = 0;

        const MAX_RETRIES = 3;           // max retries for no-overlay
        const MAX_STALL_RETRIES = 3;     // max retries for stalled progress (0%)
        const STALL_TIMEOUT_MS = 45000;  // 45s tanpa perubahan progress → stall
        const NO_OVERLAY_TIMEOUT_MS = 30000; // 30s tanpa overlay → retry

        // Pertahankan status terminal
        if (tabState.status === 'done' || tabState.status === 'downloaded' ||
            tabState.status === 'error') {
            return tabState;
        }

        // 0. Cek rate limit DULU sebelum cek apapun
        if (_isRateLimitReached()) {
            log(`[Tab ${tabIndex}] 🚫 RATE LIMIT REACHED! Grok meminta upgrade ke SuperGrok.`);
            tabState.status = 'rate_limited';
            tabState.error = 'Rate limit reached';
            return tabState;
        }

        // ════════════════════════════════════════════════════════════
        // 1. CEK OVERLAY GENERATING DULU — INI PRIORITAS TERTINGGI
        //    Jika overlay masih visible, PASTI masih generating.
        //    JANGAN PERNAH return "done" saat overlay masih ada.
        // ════════════════════════════════════════════════════════════
        const isGenerating = _isGeneratingOverlayVisible();
        const pctNum       = _readGeneratingPercent();

        if (isGenerating || pctNum > 0) {
            // Tandai bahwa overlay pernah terlihat
            tabState.generatingOccurred = true;
            tabState.retrying = false;
            tabState.status   = 'generating';
            tabState.progress = pctNum;

            // ── STALL DETECTION ──
            // Jika overlay muncul tapi progress tetap 0% selama 45s → re-fill prompt & klik ulang
            if (pctNum > 0 && pctNum !== tabState.lastProgressPct) {
                // Progress berubah → reset stall timer
                tabState.lastProgressPct = pctNum;
                tabState.lastProgressTs = Date.now();
            } else if (pctNum === 0 && tabState.generatingOccurred) {
                // Overlay visible tapi pct masih 0%
                const stallElapsed = Date.now() - tabState.lastProgressTs;
                if (stallElapsed > STALL_TIMEOUT_MS && tabState.stallRetryCount < MAX_STALL_RETRIES && !tabState.retrying) {
                    tabState.stallRetryCount++;
                    tabState.retrying = true;
                    log(`[Tab ${tabIndex}] ⚠️ Progress stuck di 0% selama ${Math.round(stallElapsed/1000)}s. Re-fill prompt & generate ulang (stall retry ${tabState.stallRetryCount}/${MAX_STALL_RETRIES})...`);

                    (async () => {
                        try {
                            const config = tabState._config;
                            if (config && config.prompt) {
                                const filled = await fillPrompt(config.prompt);
                                if (filled) {
                                    log(`[Tab ${tabIndex}] 📝 Prompt re-filled`);
                                } else {
                                    log(`[Tab ${tabIndex}] ⚠️ Prompt re-fill gagal, coba generate saja...`);
                                }
                                await sleep(500);
                            }
                            const clicked = await clickGenerate();
                            if (clicked) {
                                log(`[Tab ${tabIndex}] 🔄 Generate re-clicked setelah stall (retry ${tabState.stallRetryCount})`);
                                tabState.generatingOccurred = false;
                                tabState.lastProgressTs = Date.now();
                                tabState.lastProgressPct = -1;
                            } else {
                                log(`[Tab ${tabIndex}] ⚠️ Generate re-click gagal`);
                            }
                        } catch(e) {
                            log(`[Tab ${tabIndex}] ⚠️ Stall retry error: ${e.message}`);
                        }
                        tabState.retrying = false;
                    })();

                    return tabState;
                }
            }

            // OVERLAY MASIH VISIBLE → PASTI masih generating, return langsung
            return tabState;
        }

        // ════════════════════════════════════════════════════════════
        // 2. OVERLAY SUDAH HILANG → Baru cek apakah video selesai
        //    Sampai di sini artinya overlay TIDAK visible.
        //    Sekarang aman untuk cek apakah video/download button ada.
        // ════════════════════════════════════════════════════════════
        {
            // Handle "Skip" / "I prefer this" choice buttons (2 video options)
            if (!tabState.preferClicked) {
                const allBtns = Array.from(document.querySelectorAll('button'));

                const skipBtn = allBtns.find(b => {
                    const text = (b.textContent || '').trim();
                    return text === 'Skip' && isVisible(b);
                });

                if (skipBtn) {
                    log(`[Tab ${tabIndex}] ⏭ Menerima 2 opsi video. Klik "Skip"...`);
                    simulateClick(skipBtn);
                    tabState.preferClicked = true;
                    tabState.status = 'generating';
                    tabState.progress = 99;
                    return tabState;
                }

                const preferBtn = allBtns.find(b => {
                    const text = (b.textContent || '').trim().toLowerCase();
                    return text.includes('prefer this') || text.includes('suka ini');
                });

                if (preferBtn) {
                    log(`[Tab ${tabIndex}] 💡 Menerima 2 opsi video. Klik "I prefer this"...`);
                    simulateClick(preferBtn);
                    tabState.preferClicked = true;
                    tabState.status = 'generating';
                    tabState.progress = 99;
                    return tabState;
                }
            } else {
                // Sudah klik prefer/skip, tunggu sampai button hilang
                const stillHasChoiceBtns = Array.from(document.querySelectorAll('button')).some(b => {
                    const text = (b.textContent || '').trim().toLowerCase();
                    return text === 'skip' || text.includes('prefer this') || text.includes('suka ini');
                });
                if (stillHasChoiceBtns) {
                    tabState.status = 'generating';
                    tabState.progress = 99;
                    return tabState;
                }
            }

            // Cek apakah video sudah jadi (download button visible / video URL ada)
            const finishedUrl = _getFinishedVideoUrl();
            const dlVisible   = _isDownloadButtonVisible();
            if (finishedUrl || dlVisible) {
                // ════ KRITIS: Cek apakah ini VIDEO BARU atau VIDEO LAMA (history) ════
                const initialUrls = tabState.initialVideoUrls || [];
                const isNewVideo = tabState.generatingOccurred ||
                    (finishedUrl && !initialUrls.includes(finishedUrl));
                
                // Safety: jika sudah > 60 detik sejak pertama cek, terima saja
                const elapsedSinceFirstCheck = Date.now() - (tabState.firstCheckTs || Date.now());
                const safetyTimeout = elapsedSinceFirstCheck > 60000;

                if (isNewVideo || safetyTimeout) {
                    tabState.status   = 'done';
                    tabState.progress = 100;
                    tabState.videoUrl = finishedUrl || tabState.videoUrl;
                    if (!tabState.generatingOccurred) {
                        log(`[Tab ${tabIndex}] ✅ DONE (overlay missed — video BARU terdeteksi, URL berbeda dari snapshot)`);
                    } else {
                        log(`[Tab ${tabIndex}] ✅ DONE (overlay hilang + video confirmed)`);
                    }
                    return tabState;
                } else {
                    // Video/button ditemukan tapi SAMA dengan yang lama → masih generating
                    log(`[Tab ${tabIndex}] ⏳ Video/button terlihat tapi merupakan history lama (${initialUrls.length} initial URLs). Menunggu video baru...`);
                    tabState.status = 'generating';
                    tabState.progress = 0;
                }
            }
        }

        // ════════════════════════════════════════════════════════════
        // 3. AUTO-RETRY GENERATE (no overlay detected, no video done)
        //    Sampai di sini artinya: overlay TIDAK visible DAN video BELUM jadi
        //    Jika 30 detik lewat → isi prompt lagi + klik Generate
        // ════════════════════════════════════════════════════════════
        if (!tabState.generatingOccurred && !tabState.retrying) {
            const elapsed = Date.now() - tabState.firstCheckTs;
            if (elapsed > NO_OVERLAY_TIMEOUT_MS && tabState.retryCount < MAX_RETRIES) {
                tabState.retryCount++;
                tabState.retrying = true;
                log(`[Tab ${tabIndex}] ⚠️ Overlay belum muncul setelah ${Math.round(elapsed/1000)}s. Re-fill prompt & generate ulang (retry ${tabState.retryCount}/${MAX_RETRIES})...`);

                (async () => {
                    try {
                        const config = tabState._config;
                        if (config && config.prompt) {
                            const filled = await fillPrompt(config.prompt);
                            if (filled) {
                                log(`[Tab ${tabIndex}] 📝 Prompt re-filled`);
                            }
                            await sleep(500);
                        }
                        const clicked = await clickGenerate();
                        if (clicked) {
                            log(`[Tab ${tabIndex}] 🔄 Generate re-clicked (retry ${tabState.retryCount})`);
                        } else {
                            log(`[Tab ${tabIndex}] ⚠️ Generate re-click gagal`);
                        }
                    } catch(e) {
                        log(`[Tab ${tabIndex}] ⚠️ Generate retry error: ${e.message}`);
                    }
                    tabState.firstCheckTs = Date.now();
                    tabState.retrying = false;
                })();

                return tabState;
            }
        }

        return tabState;
    };

    // ── Download: Tombol Unduh (PRIMARY) + URL requests (FALLBACK) ──
    //
    // PRIMARY: Python panggil execute_script("window.__grokTabDownload(idx);")
    //   → klik tombol Unduh, lalu Python poll sampai .mp4 muncul
    //
    // FALLBACK: Python panggil execute_script("return window.__grokTabGetVideoUrl(idx);")
    //   → return URL untuk Python download via requests (jika button fail)

    // PRIMARY: Klik tombol Unduh
    window.__grokTabDownload = function(tabIndex) {
        const batch = window.__grokBatchState;
        if (!batch.tabs[tabIndex]) {
            batch.tabs[tabIndex] = { tabIndex, status: 'unknown', progress: 0, videoUrl: null };
        }
        const tabState = batch.tabs[tabIndex];
        tabState.status = 'downloading';

        (async () => {
            try {
                // Cari tombol Download (poll max 20 detik)
                let dlBtn = null;
                const dlStart = Date.now();
                while (Date.now() - dlStart < 20000) {
                    dlBtn = _findDownloadButton();
                    if (dlBtn) break;
                    await sleep(500);
                }

                if (!dlBtn) {
                    // Fallback: jika tombol tidak ditemukan, coba download via URL langsung
                    const videoUrl = _getFinishedVideoUrl();
                    if (videoUrl) {
                        log(`[Tab ${tabIndex}] ⚠️ Tombol download tidak ditemukan, tapi URL video ada`);
                        log(`[Tab ${tabIndex}] 🔗 URL: ${videoUrl.substring(0, 80)}...`);
                        tabState.videoUrl = videoUrl;
                        // Trigger download via hidden <a> tag
                        try {
                            const a = document.createElement('a');
                            a.href = videoUrl;
                            a.download = `grok_video_${tabIndex}_${Date.now()}.mp4`;
                            a.style.display = 'none';
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);
                            log(`[Tab ${tabIndex}] ✅ Download via URL link diklik!`);
                        } catch(linkErr) {
                            log(`[Tab ${tabIndex}] ⚠️ Link download gagal: ${linkErr.message}`);
                        }
                        await sleep(2000);
                        tabState.status = 'downloaded';
                        batch.totalDone++;
                        return;
                    }
                    throw new Error('Tombol Unduh tidak muncul & URL video tidak ada');
                }

                dlBtn.scrollIntoView({ block: 'center', behavior: 'smooth' });
                await sleep(500);

                // Klik dengan multiple metode untuk robustness
                try { dlBtn.click(); } catch(e) {}
                simulateClick(dlBtn);
                log(`[Tab ${tabIndex}] ✅ Tombol Unduh diklik!`);

                tabState.videoUrl = _getFinishedVideoUrl() || tabState.videoUrl;
                await sleep(2000);
                tabState.status = 'downloaded';
                batch.totalDone++;
            } catch(e) {
                tabState.status = 'error';
                tabState.error  = e.message;
                batch.totalFailed++;
                log(`[Tab ${tabIndex}] ❌ Download error: ${e.message}`);
            }
        })();

        return tabState; // return langsung, Python polling
    };

    // FALLBACK: Return video URL untuk Python download via requests
    window.__grokTabGetVideoUrl = function(tabIndex) {
        // 1. Cek video#sd-video src (primary)
        const sdVideo = document.querySelector('video#sd-video');
        if (sdVideo && sdVideo.src && sdVideo.src.startsWith('https://') && sdVideo.src.includes('.mp4')) {
            log(`[Tab ${tabIndex}] 📥 URL ditemukan (sd-video): ${sdVideo.src.substring(0, 80)}...`);
            return sdVideo.src;
        }
        // 2. Cek video#hd-video
        const hdVideo = document.querySelector('video#hd-video');
        if (hdVideo && hdVideo.src && hdVideo.src.startsWith('https://') && hdVideo.src.includes('.mp4')) {
            log(`[Tab ${tabIndex}] 📥 URL ditemukan (hd-video): ${hdVideo.src.substring(0, 80)}...`);
            return hdVideo.src;
        }
        // 3. Fallback: any video with https .mp4 src
        for (const v of $$('video')) {
            if (v.src && v.src.startsWith('https://') && v.src.includes('.mp4')) {
                log(`[Tab ${tabIndex}] 📥 URL ditemukan (fallback video): ${v.src.substring(0, 80)}...`);
                return v.src;
            }
        }
        // 4. Cek batch state videoUrl
        const batch = window.__grokBatchState;
        if (batch.tabs[tabIndex] && batch.tabs[tabIndex].videoUrl && 
            batch.tabs[tabIndex].videoUrl.startsWith('https://')) {
            log(`[Tab ${tabIndex}] 📥 URL ditemukan (batch state): ${batch.tabs[tabIndex].videoUrl.substring(0, 80)}...`);
            return batch.tabs[tabIndex].videoUrl;
        }
        // 5. Tidak ada URL
        log(`[Tab ${tabIndex}] ⚠️ Tidak ada video URL`);
        return null;
    };

    log('🚀 Grok Auto JS injected and ready!');
})();
