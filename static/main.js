/* VOP Module:     main.js
Version:        v0.0.70
Description:    Frontend logic.
                Synchronized FIT FOV math with vop_math.py's internal fit_factor auto-scale.
*/
let local_sync_ts = 0; 
let mdsMasterCount = 0;
let isFirstLoad = true;
let isEngineRunning = false;

async function uploadFile(inputId, textId, endpoint) {
    const file = document.getElementById(inputId).files[0];
    if(!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
        const resp = await fetch(endpoint, {method: 'POST', body: formData});
        const data = await resp.json();
        document.getElementById(textId).value = data.filename;
        await triggerSync(); 
    } catch(e) { console.error("Upload failed", e); }
}

async function triggerSync() {
    local_sync_ts = Date.now();
    await fetch('/preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(collectParams())});
    document.getElementById('probe_img').src = '/static/probe_live.jpg?t=' + Date.now();
}

function collectParams() {
    const p = { last_sync: local_sync_ts };
    document.querySelectorAll('input, select').forEach(el => {
        if (el.id) p[el.id] = el.type === 'checkbox' ? el.checked : el.value;
    });
    return p;
}

async function runTask(type) {
    await fetch(`/${type}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(collectParams())});
    if (type === 'preview' || type === 'cam_preview') {
        document.getElementById('probe_img').src = '/static/probe_live.jpg?t=' + Date.now();
    }
}

function panic() { fetch('/panic', {method: 'POST'}); }
function nukeMag() { fetch('/nuke_mag', {method: 'POST'}); }

function nukeProjMag() {
    fetch('/nuke_proj_mag', {method: 'POST'});
    document.getElementById('image').value = '';
    triggerSync();
}

function nukeProjBiPack() {
    fetch('/nuke_proj_bipack', {method: 'POST'});
    document.getElementById('bipack_image').value = '';
    triggerSync();
}

async function nukeJob() {
    if (confirm("Reset current session to default_job.json? This cannot be undone.")) {
        await fetch('/nuke_job', {method: 'POST'});
        window.location.reload(); // Triggers the fresh /status check
    }
}

async function calcFitScale(scaleId, fitZId, magType) {
    const fov = parseFloat(document.getElementById('fov').value);
    const zDist = Math.abs(parseFloat(document.getElementById(fitZId).value)) || 1.0;

    // 1. Get the aspect ratio of the loaded image
    const aspectReq = await fetch(`/get_img_aspect?mag=${magType}`);
    const aspectData = await aspectReq.json();
    const imgAspect = aspectData.aspect || 1.777;

    // 2. Ping the Python backend to calculate the exact static scale
    try {
        const fitReq = await fetch('/calculate_fit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fov: fov, ref_z: zDist, aspect_ratio: imgAspect })
        });
        const fitData = await fitReq.json();

        if (fitData.status === 'ok') {
            document.getElementById(scaleId).value = fitData.scale.toFixed(4);
            console.log(`[VOP UI] ${magType.toUpperCase()} Scale Fit to: ${fitData.scale.toFixed(4)}`);
            await triggerSync();
        } else {
            console.error("Fit Calc Error:", fitData.message);
        }
    } catch (e) {
        console.error("Failed to calculate fit", e);
    }
}

function addMDSKeyframe() {
    mdsMasterCount++; 
    const idx = mdsMasterCount; 
    
    const existingRows = document.querySelectorAll('.mds-keyframe-group');
    const lastRow = existingRows.length > 0 ? existingRows[existingRows.length - 1] : null;

    // Default baseline
    let vals = {
        m: "S", crn: false, p: "0,0,-1.0", r: "0,0,0", bp_p: "0,0,-1.0", bp_r: "0,0,0",
        c: "#ffffff", cg: "#ffffff", s: "1.0", f: 1,
        sp: "0,0,0", sr: "0,0,0", sbp_p: "0,0,0", sbp_r: "0,0,0", sc: "#ffffff", scg: "#ffffff",
        ep: "0,0,0", er: "0,0,0", ebp_p: "0,0,0", ebp_r: "0,0,0", ec: "#ffffff", ecg: "#ffffff"
    };

    if (lastRow) {
        // Scraper helper: looks for an input that starts with the prefix and ends with the suffix
        const getV = (sel) => { const el = lastRow.querySelector(sel); return el ? el.value : ""; };
        const getC = (sel) => { const el = lastRow.querySelector(sel); return el ? el.checked : false; };
        
        vals = {
            m: getV('.mds-master-row select'),
            crn: getC('.mds-master-row input[type="checkbox"]'),
            p: getV('.mds-master-row input[id*="_p"]:not([id*="bp"])'),
            r: getV('.mds-master-row input[id*="_r"]:not([id*="bp"])'),
            bp_p: getV('.mds-master-row .bp-input[id*="_p"]'),
            bp_r: getV('.mds-master-row .bp-input[id*="_r"]'),
            // Fixed Color Selectors: Targets hidden hex fields within specific row types
            c: getV('.mds-master-row input[id^="mds_c"]:not([id*="cg"])[id$="_hex"]'),
            cg: getV('.mds-master-row input[id^="mds_cg"][id$="_hex"]'),
            s: getV('.mds-master-row input[id*="_s"]'),
            f: parseInt(getV('.mds-master-row input[id*="_f"]')) + 1,
            
            // Smear Start Scrapes
            sp: getV('.mds-smear-row:nth-child(2) input[id*="_p"]:not([id*="bp"])'),
            sr: getV('.mds-smear-row:nth-child(2) input[id*="_r"]:not([id*="bp"])'),
            sbp_p: getV('.mds-smear-row:nth-child(2) .bp-input[id*="_p"]'),
            sbp_r: getV('.mds-smear-row:nth-child(2) .bp-input[id*="_r"]'),
            sc: getV('.mds-smear-row:nth-child(2) input[id*="_c"][id$="_hex"]:not([id*="cg"])'),
            scg: getV('.mds-smear-row:nth-child(2) input[id*="_cg"][id$="_hex"]'),

            // Smear Stop Scrapes
            ep: getV('.mds-smear-row:nth-child(3) input[id*="_p"]:not([id*="bp"])'),
            er: getV('.mds-smear-row:nth-child(3) input[id*="_r"]:not([id*="bp"])'),
            ebp_p: getV('.mds-smear-row:nth-child(3) .bp-input[id*="_p"]'),
            ebp_r: getV('.mds-smear-row:nth-child(3) .bp-input[id*="_r"]'),
            ec: getV('.mds-smear-row:nth-child(3) input[id*="_c"][id$="_hex"]:not([id*="cg"])'),
            ecg: getV('.mds-smear-row:nth-child(3) input[id*="_cg"][id$="_hex"]')
        };
    }

    const body = document.getElementById('mds_sheet_body');
    const row = document.createElement('div');
    row.className = 'mds-keyframe-group';
    row.innerHTML = `
        <div class="sheet-row mds-master-row">
            <div class="row-num">?</div>
            <input type="number" id="mds_f${idx}" value="${vals.f}">
            <select id="mds_m${idx}"><option value="S" ${vals.m==='S'?'selected':''}>S</option><option value="L" ${vals.m==='L'?'selected':''}>L</option></select>
            <input type="checkbox" id="mds_crn${idx}" ${vals.crn?'checked':''}>
            <div class="node-tag master">MST</div>
            <input id="mds_p${idx}" value="${vals.p}">
            <input id="mds_r${idx}" value="${vals.r}">
            <input id="mds_bp_p${idx}" value="${vals.bp_p}" class="bp-input">
            <input id="mds_bp_r${idx}" value="${vals.bp_r}" class="bp-input">
            <input type="color" id="mds_c${idx}" value="${vals.c}" onchange="updateHex(this, 'mds_c${idx}_hex')">
            <input type="hidden" id="mds_c${idx}_hex" value="${vals.c}">
            <input type="color" id="mds_cg${idx}" value="${vals.cg}" onchange="updateHex(this, 'mds_cg${idx}_hex')">
            <input type="hidden" id="mds_cg${idx}_hex" value="${vals.cg}">
            <input type="number" step="0.1" id="mds_s${idx}" value="${vals.s}">
            <button class="del-btn" onclick="this.parentElement.parentElement.remove(); reindexMDS();">X</button>
        </div>
        <div class="sheet-row mds-smear-row">
            <div></div><div></div><div></div><div></div>
            <div class="node-tag smear">STRT</div>
            <input id="mds_start_p${idx}" value="${vals.sp}">
            <input id="mds_start_r${idx}" value="${vals.sr}">
            <input id="mds_start_bp_p${idx}" value="${vals.sbp_p}" class="bp-input">
            <input id="mds_start_bp_r${idx}" value="${vals.sbp_r}" class="bp-input">
            <input type="color" id="mds_start_c${idx}" value="${vals.sc}" onchange="updateHex(this, 'mds_start_c${idx}_hex')">
            <input type="hidden" id="mds_start_c${idx}_hex" value="${vals.sc}">>
            <div></div>
            <div></div>
        </div>
        <div class="sheet-row mds-smear-row">
            <div></div><div></div><div></div><div></div>
            <div class="node-tag smear">STOP</div>
            <input id="mds_stop_p${idx}" value="${vals.ep}">
            <input id="mds_stop_r${idx}" value="${vals.er}">
            <input id="mds_stop_bp_p${idx}" value="${vals.ebp_p}" class="bp-input">
            <input id="mds_stop_bp_r${idx}" value="${vals.ebp_r}" class="bp-input">
            <input type="color" id="mds_stop_c${idx}" value="${vals.ec}" onchange="updateHex(this, 'mds_stop_c${idx}_hex')">
            <input type="hidden" id="mds_stop_c${idx}_hex" value="${vals.ec}">
            <div></div>
            <div></div>
        </div>`;
    body.appendChild(row);
    reindexMDS();
}

function reindexMDS() {
    document.querySelectorAll('.mds-keyframe-group').forEach((group, i) => {
        group.querySelector('.row-num').innerText = i + 1;
    });
}

function updateHex(el, targetId) { document.getElementById(targetId).value = el.value; triggerSync(); }

setInterval(async () => {
    try {
        const r = await fetch('/status');
        const st = await r.json();
        
        if (isFirstLoad && st.params && Object.keys(st.params).length > 0) {
            for (const [k, v] of Object.entries(st.params)) {
                const el = document.getElementById(k);
                if (el) {
                    if (el.type === 'checkbox') el.checked = (v === true || v === 'true');
                    else el.value = v;
                }
            }
            document.getElementById('probe_img').src = '/static/probe_live.jpg?t=' + Date.now();
            isFirstLoad = false;
        }

        document.getElementById('sync_indicator').innerHTML = st.params ? '<span style="color:#0f0">● ONLINE</span>' : '○ OFFLINE';
        const msgEl = document.getElementById('st_msg');
        const bar = document.getElementById('st_bar');
        const etaEl = document.getElementById('st_eta');
        
        if (st.status === 'rendering' && st.heartbeat) {
            isEngineRunning = true;
            // FIXED: Use st.heartbeat.msg instead of st.msg
            msgEl.innerText = `${st.heartbeat.msg} [${st.heartbeat.current}/${st.heartbeat.total}]`;
            bar.style.width = (st.heartbeat.current/st.heartbeat.total*100) + "%";
            
            // Format ETA (HH:MM:SS) - Only if eta exists
            if (st.heartbeat.eta !== undefined) {
                const h = Math.floor(st.heartbeat.eta / 3600).toString().padStart(2, '0');
                const m = Math.floor((st.heartbeat.eta % 3600) / 60).toString().padStart(2, '0');
                const s = (st.heartbeat.eta % 60).toString().padStart(2, '0');
                const mb = st.heartbeat.est_mb;
                const sizeStr = mb > 1024 ? (mb / 1024).toFixed(2) + " GB" : mb + " MB";
                if (etaEl) etaEl.innerText = `ETA: ${h}:${m}:${s} | TOTAL PROJ: ${sizeStr}`;
            }
        } else {
            if (isEngineRunning) {
                document.getElementById('probe_img').src = '/static/probe_live.jpg?t=' + Date.now();
                isEngineRunning = false;
            }
            msgEl.innerHTML = st.workprint ? `IDLE | <a href="${st.workprint}" target="_blank" style="color:#0cf">VIEW WORKPRINT</a>` : "Ready...";
            bar.style.width = "0%";
            if (etaEl) etaEl.innerText = ""; 
        }
    } catch(e) { console.error("Poll Error:", e); }
}, 1000);