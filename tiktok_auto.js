// ═══════════════════════════════════════════════════════════════
//  TIKTOK AUTO JS — Injected by Selenium to automate TikTok Studio upload
//  Works independently; Selenium only manages Chrome lifecycle + file input
//  Pattern follows grok_auto.js architecture
// ═══════════════════════════════════════════════════════════════

(function () {
    'use strict';

    // ── Prevent double-injection ──
    if (window.__TIKTOK_AUTO_INJECTED) return;
    window.__TIKTOK_AUTO_INJECTED = true;

    // ── State shared with Selenium ──
    window.__TIKTOK_AUTO = {
        status: 'idle',       // idle | running | done | error
        step: '',             // current step name
        progress: 0,          // 0-100
        message: '',          // human-readable status
        error: null,
    };

    const STATE = window.__TIKTOK_AUTO;

    // ═══════════════════════════════════════════════════════════════
    //  HELPERS
    // ═══════════════════════════════════════════════════════════════
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    function log(msg) {
        STATE.message = msg;
        console.log(`[TikTokAuto] ${msg}`);
    }

    function $(sel)  { return document.querySelector(sel); }
    function $$(sel) { return document.querySelectorAll(sel); }

    function isVisible(el) {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        const s = getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
    }

    async function waitFor(sel, timeout = 20000, visible = true) {
        const t0 = Date.now();
        while (Date.now() - t0 < timeout) {
            const el = $(sel);
            if (el && (!visible || isVisible(el))) return el;
            await sleep(300);
        }
        return null;
    }

    async function waitForAny(selectors, timeout = 20000) {
        const t0 = Date.now();
        while (Date.now() - t0 < timeout) {
            for (const s of selectors) {
                const el = $(s);
                if (el && isVisible(el)) return el;
            }
            await sleep(300);
        }
        return null;
    }

    function simulateClick(el) {
        if (!el) return;
        for (const ev of ['pointerover','mouseover','pointerdown','mousedown',
                          'pointerup','mouseup','click']) {
            const Ctor = ev.startsWith('pointer') ? PointerEvent : MouseEvent;
            el.dispatchEvent(new Ctor(ev, {
                bubbles: true, cancelable: true, composed: true,
                view: window, detail: 1
            }));
        }
    }

    function simulateType(el, text) {
        if (!el) return;
        el.focus();
        el.value = '';
        el.dispatchEvent(new Event('focus', { bubbles: true }));
        for (const ch of text) {
            el.value += ch;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keydown',  { key: ch, bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keypress', { key: ch, bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keyup',    { key: ch, bubbles: true }));
        }
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function findButtonByText(text, parent = document) {
        const btns = parent.querySelectorAll('button');
        for (const b of btns) {
            const t = (b.textContent || '').trim();
            if (t === text || t.includes(text)) {
                if (isVisible(b)) return b;
            }
        }
        // Also search divs inside buttons
        for (const b of btns) {
            const inner = b.querySelector('div');
            if (inner) {
                const t = (inner.textContent || '').trim();
                if (t === text || t.includes(text)) {
                    if (isVisible(b)) return b;
                }
            }
        }
        return null;
    }

    function findElementByText(text, tag = 'div', parent = document) {
        for (const el of parent.querySelectorAll(tag)) {
            const t = (el.textContent || '').trim();
            if (t === text || t.includes(text)) {
                if (isVisible(el)) return el;
            }
        }
        return null;
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 1: WAIT FOR UPLOAD READY
    //  (File is uploaded by Selenium via input[type=file], JS waits for processing)
    // ═══════════════════════════════════════════════════════════════
    async function waitForVideoProcessed(timeout = 120000) {
        log('⏳ Menunggu video diproses oleh TikTok...');
        STATE.step = 'processing_video';

        const t0 = Date.now();
        while (Date.now() - t0 < timeout) {
            // Check if the editor / caption area is ready
            const caption = $("div[role='textbox']") ||
                           $("div.notranslate.public-DraftEditor-content") ||
                           $("div[contenteditable='true'][data-placeholder]");
            if (caption && isVisible(caption)) {
                log('✅ Video diproses, editor siap!');
                return true;
            }

            // Check for error messages
            const errEl = findElementByText('Upload failed', 'span') ||
                          findElementByText('Upload gagal', 'span');
            if (errEl) {
                throw new Error('Upload gagal menurut TikTok');
            }

            await sleep(2000);
        }
        throw new Error('Timeout menunggu video diproses');
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 2: FILL DESCRIPTION
    // ═══════════════════════════════════════════════════════════════
    async function fillDescription(description) {
        log(`📝 Mengisi deskripsi: "${description.substring(0, 50)}..."`);
        STATE.step = 'fill_description';

        const caption = await waitFor("div[role='textbox']", 10000) ||
                        await waitFor("div.notranslate.public-DraftEditor-content", 5000);
        if (!caption) throw new Error('Editor deskripsi tidak ditemukan');

        // Clear existing content
        caption.focus();
        await sleep(300);
        document.execCommand('selectAll', false, null);
        await sleep(100);
        document.execCommand('delete', false, null);
        await sleep(300);

        // Insert text via execCommand for rich editor compatibility
        document.execCommand('insertText', false, description);
        await sleep(500);

        log('✅ Deskripsi diisi');
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 3: ADD HASHTAGS
    // ═══════════════════════════════════════════════════════════════
    async function addHashtags(hashtags) {
        if (!hashtags || hashtags.length === 0) {
            log('⏭ Tidak ada hashtag');
            return true;
        }

        log(`#️⃣ Menambahkan ${hashtags.length} hashtag...`);
        STATE.step = 'add_hashtags';

        const caption = $("div[role='textbox']") ||
                       $("div.notranslate.public-DraftEditor-content");
        if (!caption) {
            log('⚠️ Caption tidak ditemukan, skip hashtags');
            return false;
        }

        caption.focus();
        await sleep(300);

        // Move cursor to end
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(caption);
        range.collapse(false);
        sel.removeAllRanges();
        sel.addRange(range);

        for (const tag of hashtags) {
            const clean = tag.replace(/^#/, '').trim();
            if (!clean) continue;

            document.execCommand('insertText', false, ' #' + clean);
            await sleep(500);

            // Wait for autocomplete dropdown
            await sleep(1500);

            // Press Tab to select autocomplete if available
            caption.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Tab', code: 'Tab', keyCode: 9, bubbles: true
            }));
            await sleep(800);

            log(`  ✅ #${clean}`);
        }

        log('✅ Semua hashtag ditambahkan');
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 4: ADD LOCATION
    // ═══════════════════════════════════════════════════════════════
    async function addLocation(location) {
        if (!location) {
            log('⏭ Lokasi tidak diaktifkan');
            return true;
        }

        log(`📍 Mengisi lokasi: ${location}`);
        STATE.step = 'add_location';

        const locInput = await waitFor("input[placeholder='Search locations']", 10000);
        if (!locInput) {
            log('⚠️ Input lokasi tidak ditemukan');
            return false;
        }

        locInput.scrollIntoView({ block: 'center' });
        await sleep(500);
        simulateClick(locInput);
        await sleep(300);

        // Clear & type
        locInput.value = '';
        locInput.dispatchEvent(new Event('input', { bubbles: true }));
        await sleep(200);

        simulateType(locInput, location);
        await sleep(3000);

        // Click first option
        const option = $("div[role='option']") || $("div[class*='Select__item']");
        if (option && isVisible(option)) {
            simulateClick(option);
            log(`✅ Lokasi dipilih: ${location}`);
        } else {
            log('⚠️ Dropdown lokasi tidak muncul');
        }

        await sleep(1000);
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 5: ADD PRODUCT
    // ═══════════════════════════════════════════════════════════════
    async function addProduct(productRadioName, productTitle) {
        if (!productRadioName) {
            log('⏭ Produk tidak diaktifkan');
            return true;
        }

        log(`🏷️ Menambahkan produk: ${productRadioName}`);
        STATE.step = 'add_product';

        // A - Click "+ Add" button
        const addBtn = findButtonByText('Add');
        if (!addBtn) throw new Error('Tombol "Add" produk tidak ditemukan');
        simulateClick(addBtn);
        await sleep(2000);

        // B - Click "Next" button (first)
        const nextBtn1 = findButtonByText('Next');
        if (!nextBtn1) throw new Error('Tombol "Next" pertama tidak ditemukan');
        simulateClick(nextBtn1);
        await sleep(2000);

        // B2 - Check for "My shop" tab, click "Showcase products" if present
        const myShopTab = findElementByText('My shop', 'button');
        if (myShopTab) {
            log('  💡 Tab "My shop" terdeteksi, klik "Showcase products"...');
            const showcaseTab = findElementByText('Showcase products', 'button') ||
                               findElementByText('Showcase products', 'div');
            if (showcaseTab) {
                simulateClick(showcaseTab);
                await sleep(2000);
            }
        }

        // C - Search product
        log(`  🔍 Mencari produk: ${productRadioName.substring(0, 60)}...`);
        const searchInput = $("input[placeholder='Search products']");
        if (searchInput) {
            simulateType(searchInput, productRadioName);
            await sleep(1000);
            // Click search or press Enter
            searchInput.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true
            }));
            await sleep(3000);
        }

        // C3 - Select radio button
        const radio = $(`input[type='radio'][name='${productRadioName}']`);
        if (radio) {
            const wrapper = radio.parentElement;
            wrapper.scrollIntoView({ block: 'center' });
            await sleep(500);
            simulateClick(wrapper);
            log('  ✅ Radio produk dipilih');
        } else {
            // Fallback: click first radio
            const anyRadio = $("input[type='radio']");
            if (anyRadio) {
                simulateClick(anyRadio.parentElement);
                log('  ✅ Radio produk dipilih (fallback: first radio)');
            } else {
                log('  ⚠️ Radio produk tidak ditemukan');
            }
        }
        await sleep(1000);

        // D - Click Next (second time - look for primary button)
        const allNextBtns = Array.from($$('button')).filter(b => {
            const div = b.querySelector('div');
            return div && div.textContent.trim() === 'Next' && isVisible(b);
        });
        const primaryNext = allNextBtns.find(b =>
            (b.className || '').includes('primary')
        ) || allNextBtns[allNextBtns.length - 1];

        if (primaryNext) {
            primaryNext.scrollIntoView({ block: 'center' });
            await sleep(500);
            simulateClick(primaryNext);
            await sleep(2000);
        }

        // E - Product title
        if (productTitle) {
            log(`  📝 Mengisi judul produk: ${productTitle}`);
            const titleInput = $("input[class*='TUXTextInputCore-input']");
            if (titleInput) {
                titleInput.focus();
                titleInput.value = '';
                titleInput.dispatchEvent(new Event('input', { bubbles: true }));
                await sleep(200);
                simulateType(titleInput, productTitle);
                await sleep(1000);
            }
        }

        // F - Click Add (last - the confirmation button)
        await sleep(1000);
        const allAddBtns = Array.from($$('button')).filter(b => {
            const div = b.querySelector('div');
            return div && div.textContent.trim() === 'Add' && isVisible(b);
        });
        // Prefer button inside modal
        let targetAdd = null;
        for (const b of allAddBtns) {
            const inModal = b.closest('[class*="modal"],[class*="Modal"],[class*="dialog"],[role="dialog"]');
            if (inModal) { targetAdd = b; break; }
        }
        if (!targetAdd && allAddBtns.length > 0) targetAdd = allAddBtns[allAddBtns.length - 1];

        if (targetAdd) {
            targetAdd.scrollIntoView({ block: 'center' });
            await sleep(500);
            simulateClick(targetAdd);
            log('  ✅ Produk ditambahkan');
        } else {
            log('  ⚠️ Tombol Add terakhir tidak ditemukan');
        }

        await sleep(2000);
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 6: SWITCHES (Show More, Disclose, Branded, AI-generated)
    // ═══════════════════════════════════════════════════════════════
    async function configureSwitches() {
        log('⚙️ Mengatur switches...');
        STATE.step = 'switches';

        // Show More / Advanced settings
        try {
            const advContainer = $("div[data-e2e='advanced_settings_container']");
            if (advContainer) {
                advContainer.scrollIntoView({ block: 'center' });
                await sleep(500);
                simulateClick(advContainer);
                await sleep(2000);
            }
        } catch(e) { log(`  ⚠️ Show more: ${e.message}`); }

        // Disclose content
        try {
            const discl = $("div[data-e2e='disclose_content_container'] div[class*='Switch__content']");
            if (discl) { simulateClick(discl); await sleep(1500); }
        } catch(e) { log(`  ⚠️ Disclose: ${e.message}`); }

        // Branded content
        try {
            const branded = document.querySelector(
                "span:has(+ label), label"
            );
            // More reliable: directly find by text
            const allSpans = $$('span');
            for (const s of allSpans) {
                if (s.textContent.includes('Branded content')) {
                    const label = s.parentElement.querySelector('label') ||
                                  s.previousElementSibling;
                    if (label) { simulateClick(label); await sleep(1000); }
                    break;
                }
            }
        } catch(e) { log(`  ⚠️ Branded: ${e.message}`); }

        // AI-generated
        try {
            const aiSwitch = $("div[data-e2e='aigc_container'] div[class*='Switch__content']");
            if (aiSwitch) { simulateClick(aiSwitch); await sleep(1000); }
        } catch(e) { log(`  ⚠️ AI-generated: ${e.message}`); }

        log('✅ Switches diatur');
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 7: CONTENT CHECK LITE — Turn OFF if ON
    // ═══════════════════════════════════════════════════════════════
    async function disableContentCheckLite() {
        log('🛡️ Memeriksa Content Check Lite...');
        STATE.step = 'content_check';

        // Search all text nodes for "content check"
        const allEls = $$('span, div, label, p');
        for (const el of allEls) {
            const txt = (el.textContent || '').toLowerCase().trim();
            if (txt.includes('content check')) {
                // Find the nearest Switch toggle
                const parent = el.closest('div[class*="jsx-"], div[class*="container"], div[class*="row"]')
                              || el.parentElement;
                if (!parent) continue;

                const switchEl = parent.querySelector('div[class*="Switch__content"], div[role="switch"]');
                if (!switchEl) continue;

                const cls = switchEl.className || '';
                const aria = switchEl.getAttribute('aria-checked') || '';
                const rootEl = switchEl.closest('div[class*="Switch__root"]');
                const rootCls = rootEl ? rootEl.className : '';

                const isOn = cls.includes('checked-true') ||
                             rootCls.includes('checked-true') ||
                             aria === 'true';

                if (isOn) {
                    switchEl.scrollIntoView({ block: 'center' });
                    await sleep(300);
                    simulateClick(switchEl);
                    await sleep(1000);
                    log('✅ Content Check Lite dimatikan');
                    return true;
                } else {
                    log('✅ Content Check Lite sudah OFF');
                    return true;
                }
            }
        }

        log('ℹ️ Content Check Lite tidak ditemukan');
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 8: ADD SOUND FROM FAVORITES
    // ═══════════════════════════════════════════════════════════════
    async function addSound() {
        log('🔊 Menambahkan sound dari Favorites...');
        STATE.step = 'add_sound';

        // Click sounds button
        const soundBtn = $("button[data-button-name='sounds']");
        if (!soundBtn) {
            log('⚠️ Tombol Sounds tidak ditemukan');
            return false;
        }
        soundBtn.scrollIntoView({ block: 'center' });
        await sleep(500);
        simulateClick(soundBtn);
        await sleep(3000);

        // Click Favorites tab
        const favTab = $("button[role='tab'][aria-controls='panel-favorites']");
        if (favTab) {
            simulateClick(favTab);
            await sleep(3000);
        }

        // Click + button
        const plusBtn = $("button[data-icon-only='true'][data-type='stroke'] span[data-icon='PlusBold']");
        if (plusBtn) {
            const btn = plusBtn.closest('button');
            if (btn) {
                simulateClick(btn);
                log('✅ Sound ditambahkan');

                // Wait for + button to become disabled (sound attached)
                const t0 = Date.now();
                while (Date.now() - t0 < 30000) {
                    if (btn.getAttribute('aria-disabled') === 'true' || !btn.isConnected) break;
                    await sleep(500);
                }
            }
        } else {
            log('⚠️ Tombol + sound tidak ditemukan');
        }

        // Mute original
        try {
            const volBtn = $("button[data-icon-only='true'][data-type='text'] span[data-icon='VolumeUp']");
            if (volBtn) {
                simulateClick(volBtn.closest('button'));
                await sleep(1000);
                log('✅ Audio original di-mute');
            }
        } catch(e) {}

        // Save sounds
        await sleep(1000);
        const saveBtn = findButtonByText('Save');
        if (saveBtn) {
            simulateClick(saveBtn);
            await sleep(3000);
            log('✅ Sound disimpan');
        }

        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 9: SET SCHEDULE (Date + Time)
    // ═══════════════════════════════════════════════════════════════
    async function setSchedule(year, month, day, hour, minute) {
        log(`📅 Mengatur jadwal: ${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')} ${String(hour).padStart(2,'0')}:${String(minute).padStart(2,'0')}`);
        STATE.step = 'set_schedule';

        // Find "When to post" section
        await waitFor("*", 5000); // wait for page settle
        const whenToPost = findElementByText('When to post', '*');
        if (whenToPost) {
            whenToPost.scrollIntoView({ block: 'center' });
            await sleep(500);
        }

        // Click "Schedule" radio
        const scheduleRadio = $("input[name='postSchedule'][value='schedule']");
        if (scheduleRadio) {
            const label = scheduleRadio.closest('label') ||
                         scheduleRadio.parentElement.closest('label');
            if (label) {
                label.scrollIntoView({ block: 'center' });
                await sleep(500);
                simulateClick(label);
                await sleep(2000);
            }
        }

        // ── TIME PICKER ──
        const targetHour = String(hour).padStart(2, '0');
        const targetMinVal = Math.floor(minute / 5) * 5;
        const targetMin = String(targetMinVal).padStart(2, '0');

        log(`  ⏰ Setting time: ${targetHour}:${targetMin}`);

        // Click time input to open picker
        const timeInput = $("div[class*='TUXTextInputCore'] input[readonly]");
        if (timeInput && (timeInput.value || '').includes(':')) {
            simulateClick(timeInput);
            await sleep(2000);

            // Click hour
            const hourSpan = findElementByText(targetHour, 'span');
            // More precise: look inside timepicker
            const hourEls = $$("span[class*='tiktok-timepicker-left']");
            for (const h of hourEls) {
                if (h.textContent.trim() === targetHour) {
                    simulateClick(h);
                    log(`  ✅ Jam ${targetHour}`);
                    break;
                }
            }
            await sleep(1000);

            // Click minute
            const minEls = $$("span[class*='tiktok-timepicker-right']");
            for (const m of minEls) {
                if (m.textContent.trim() === targetMin) {
                    simulateClick(m);
                    log(`  ✅ Menit ${targetMin}`);
                    break;
                }
            }
            await sleep(1000);

            // Close timepicker
            document.body.click();
            await sleep(1000);
        }

        // ── DATE PICKER ──
        const targetDateStr = `${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
        log(`  📆 Setting date: ${targetDateStr}`);

        // Find the date input (readonly, value like "2026-03-20")
        const dateInputs = $$("div[class*='TUXTextInputCore'] input[readonly]");
        for (const di of dateInputs) {
            const v = di.value || '';
            if (v.includes('-') && v.length === 10 && isVisible(di) && !v.includes(':')) {
                simulateClick(di);
                await sleep(2000);
                break;
            }
        }

        // Navigate to correct month if needed
        const targetMonthName = new Date(year, month - 1).toLocaleString('en', { month: 'long' });

        for (let nav = 0; nav < 12; nav++) {
            const monthTitle = $("div[class*='calendar-wrapper'] span[class*='month-title']");
            if (!monthTitle) break;
            const currentMonth = monthTitle.textContent.trim();
            if (currentMonth === targetMonthName) break;
            // Click forward arrow
            const arrows = $$("div[class*='calendar-wrapper'] span[class*='arrow']");
            if (arrows.length >= 2) {
                simulateClick(arrows[1]);
                await sleep(500);
            }
        }

        // Click the day
        const targetDay = String(day);
        const daySpans = $$("div[class*='calendar-wrapper'] span[class*='day']");
        for (const ds of daySpans) {
            const cls = ds.className || '';
            if (ds.textContent.trim() === targetDay &&
                isVisible(ds) &&
                !cls.includes('header') &&
                (cls.includes('valid') || !cls.includes('invalid'))) {
                simulateClick(ds);
                log(`  ✅ Tanggal ${targetDateStr}`);
                break;
            }
        }
        await sleep(2000);

        log('✅ Schedule diatur');
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  STEP 10: CLICK SCHEDULE/POST BUTTON
    // ═══════════════════════════════════════════════════════════════
    async function clickScheduleButton() {
        log('📤 Klik tombol Schedule...');
        STATE.step = 'click_schedule';

        await sleep(2000);

        // Primary target: button[data-e2e='post_video_button'] with text 'Schedule'
        let schedBtn = $("button[data-e2e='post_video_button']");
        if (schedBtn && !schedBtn.textContent.includes('Schedule')) schedBtn = null;

        if (!schedBtn) {
            // Fallback: find button with text 'Schedule' and primary style
            const allBtns = Array.from($$('button')).filter(b => {
                const t = (b.textContent || '').trim();
                return t.includes('Schedule') && isVisible(b) &&
                       (b.className || '').includes('primary');
            });
            schedBtn = allBtns[0] || null;
        }

        if (!schedBtn) {
            // Last resort
            schedBtn = findButtonByText('Schedule');
        }

        if (schedBtn) {
            schedBtn.scrollIntoView({ block: 'center' });
            await sleep(500);
            simulateClick(schedBtn);
            log('✅ Tombol Schedule diklik');
        } else {
            throw new Error('Tombol Schedule tidak ditemukan');
        }

        await sleep(3000);

        // Handle confirm popup (inside modal/dialog)
        const modalConfirm = document.querySelector(
            "div[class*='modal'] button, div[class*='Modal'] button, " +
            "div[class*='dialog'] button, div[role='dialog'] button"
        );
        if (modalConfirm) {
            const text = (modalConfirm.textContent || '').trim();
            if (text.includes('Schedule') || text.includes('Confirm')) {
                simulateClick(modalConfirm);
                log('✅ Konfirmasi popup diklik');
            }
        }

        await sleep(3000);
        log('✅ Video berhasil di-schedule!');
        return true;
    }

    // ═══════════════════════════════════════════════════════════════
    //  MAIN ORCHESTRATION — Called from Python
    //  window.__tiktokUpload(config)
    //  config = {
    //    description: "...",
    //    hashtags: ["fyp", "viral"],
    //    location: "Jakarta" | null,
    //    productRadio: "ProductName" | null,
    //    productTitle: "buy before promo ends" | null,
    //    addSound: false,
    //    skipSwitches: false,
    //    schedule: { year, month, day, hour, minute }
    //  }
    // ═══════════════════════════════════════════════════════════════
    window.__tiktokUpload = function(config) {
        STATE.status  = 'running';
        STATE.step    = 'init';
        STATE.progress = 0;
        STATE.error    = null;

        (async () => {
            try {
                const totalSteps = 8;
                let step = 0;

                // Step 1: Wait for video to be processed
                await waitForVideoProcessed(120000);
                step++; STATE.progress = Math.round(step / totalSteps * 100);

                // Step 2: Fill description
                await fillDescription(config.description || '');
                step++; STATE.progress = Math.round(step / totalSteps * 100);

                // Step 3: Add hashtags
                await addHashtags(config.hashtags || []);
                step++; STATE.progress = Math.round(step / totalSteps * 100);

                // Step 4: Add location
                await addLocation(config.location || null);
                step++; STATE.progress = Math.round(step / totalSteps * 100);

                // Step 5: Add product
                if (config.productRadio) {
                    await addProduct(config.productRadio, config.productTitle || '');
                }
                step++; STATE.progress = Math.round(step / totalSteps * 100);

                // Step 6: Configure switches
                if (!config.skipSwitches) {
                    await configureSwitches();
                }
                await disableContentCheckLite();
                step++; STATE.progress = Math.round(step / totalSteps * 100);

                // Step 7: Sound
                if (config.addSound) {
                    await addSound();
                }
                step++; STATE.progress = Math.round(step / totalSteps * 100);

                // Step 8: Schedule
                if (config.schedule) {
                    const s = config.schedule;
                    await setSchedule(s.year, s.month, s.day, s.hour, s.minute);
                    await clickScheduleButton();
                }
                step++; STATE.progress = 100;

                STATE.status = 'done';
                log('🎉 Upload selesai!');

            } catch (e) {
                STATE.status = 'error';
                STATE.error  = e.message || String(e);
                log(`❌ Error: ${STATE.error}`);
            }
        })();

        return STATE;
    };

    // ── Get state (polled by Python) ──
    window.__tiktokGetState = function() {
        return { ...STATE };
    };

    log('🚀 TikTok Auto JS injected and ready!');
})();
