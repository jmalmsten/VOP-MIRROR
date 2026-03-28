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

    // Logic to find the last frame number in the sheet
    let nextFrame = 1;
    const existingFrames = Array.from(document.querySelectorAll('input[id^="mds_f"]'))
        .map(input => parseInt(input.value))
        .filter(val => !isNaN(val));
    
    if (existingFrames.length > 0) {
        // Take the highest current frame number and add 1
        nextFrame = Math.max(...existingFrames) + 1;
    }

    const body = document.getElementById('mds_sheet_body');
    const row = document.createElement('div');
    row.className = 'mds-keyframe-group';
    row.innerHTML = `
        <div class="sheet-row mds-master-row">
            <div class="row-num">${idx}</div>
            <input type="number" id="mds_f${idx}" value="${nextFrame}">
            <select id="mds_m${idx}"><option value="S">S</option><option value="L">L</option></select>
            <input type="checkbox" id="mds_crn${idx}">
            <div class="node-tag master">MST</div>
            <input id="mds_p${idx}" value="0,0,-1.0">
            <input id="mds_r${idx}" value="0,0,0">
            <input id="mds_bp_p${idx}" value="0,0,-1.0" class="bp-input">
            <input id="mds_bp_r${idx}" value="0,0,0" class="bp-input">
            <input type="color" id="mds_c${idx}" value="#ffffff" onchange="updateHex(this, 'mds_c${idx}_hex')">
            <input type="hidden" id="mds_c${idx}_hex" value="#ffffff">
            <input type="color" id="mds_cg${idx}" value="#ffffff" onchange="updateHex(this, 'mds_cg${idx}_hex')">
            <input type="hidden" id="mds_cg${idx}_hex" value="#ffffff">
            <input type="number" step="0.1" id="mds_s${idx}" value="1.0">
            <button class="del-btn" onclick="this.parentElement.parentElement.remove()">X</button>
        </div>
        <div class="sheet-row mds-smear-row">
            <div></div><div></div><div></div><div></div>
            <div class="node-tag smear">STRT</div>
            <input id="mds_start_p${idx}" value="0,0,0">
            <input id="mds_start_r${idx}" value="0,0,0">
            <input id="mds_start_bp_p${idx}" value="0,0,0" class="bp-input">
            <input id="mds_start_bp_r${idx}" value="0,0,0" class="bp-input">
            <input type="color" id="mds_start_c${idx}" value="#ffffff" onchange="updateHex(this, 'mds_start_c${idx}_hex')">
            <input type="hidden" id="mds_start_c${idx}_hex" value="#ffffff">
            <input type="color" id="mds_start_cg${idx}" value="#ffffff" onchange="updateHex(this, 'mds_start_cg${idx}_hex')">
            <input type="hidden" id="mds_start_cg${idx}_hex" value="#ffffff">
            <div></div>
        </div>
        <div class="sheet-row mds-smear-row">
            <div></div><div></div><div></div><div></div>
            <div class="node-tag smear">STOP</div>
            <input id="mds_stop_p${idx}" value="0,0,0">
            <input id="mds_stop_r${idx}" value="0,0,0">
            <input id="mds_stop_bp_p${idx}" value="0,0,0" class="bp-input">
            <input id="mds_stop_bp_r${idx}" value="0,0,0" class="bp-input">
            <input type="color" id="mds_stop_c${idx}" value="#ffffff" onchange="updateHex(this, 'mds_stop_c${idx}_hex')">
            <input type="hidden" id="mds_stop_c${idx}_hex" value="#ffffff">
            <input type="color" id="mds_stop_cg${idx}" value="#ffffff" onchange="updateHex(this, 'mds_stop_cg${idx}_hex')">
            <input type="hidden" id="mds_stop_cg${idx}_hex" value="#ffffff">
            <div></div>
        </div>`;
    body.appendChild(row);
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