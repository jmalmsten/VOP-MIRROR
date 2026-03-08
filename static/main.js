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

async function calcFitScale(scaleId, fitZId, magType) {
    const fov = parseFloat(document.getElementById('fov').value);
    const zDist = Math.abs(parseFloat(document.getElementById(fitZId).value)) || 1.0;
    
    // Projector HDMI output aspect ratio (1920x1080)
    const projAspect = 1920.0 / 1080.0;

    const r = await fetch(`/get_img_aspect?mag=${magType}`);
    const data = await r.json();
    const imgAspect = data.aspect || 1.777;

    // 1. Mirror vop_math.py logic at Z=1.0
    const fovRad = (fov * Math.PI / 180.0);
    const frustumH_at_1 = 2.0 * Math.tan(fovRad / 2.0);
    const frustumW_at_1 = frustumH_at_1 * projAspect;

    let fitFactor = 1.0;
    if (imgAspect > frustumW_at_1) {
        fitFactor = frustumW_at_1 / imgAspect;
    }

    // 2. Calculate true target bounds at actual Z distance
    const targetH = zDist * frustumH_at_1;
    const targetW = zDist * frustumW_at_1;

    // 3. Find scales, accounting for the 2.0 base quad and backend fitFactor
    const scaleH = targetH / (2.0 * fitFactor);
    const scaleW = targetW / (2.0 * imgAspect * fitFactor);

    const targetScale = Math.min(scaleH, scaleW);
    
    document.getElementById(scaleId).value = targetScale.toFixed(4);
    
    console.log(`--- EXACT VOP_MATH FIT FOV AUDIT (${magType.toUpperCase()}) ---`);
    console.log(`Backend Fit Factor: ${fitFactor.toFixed(4)}`);
    console.log(`Calculated World Scale: ${targetScale.toFixed(4)}`);
    
    await triggerSync();
}

function addMDSKeyframe() {
    mdsMasterCount++;
    const idx = mdsMasterCount;
    const body = document.getElementById('mds_sheet_body');
    const row = document.createElement('div');
    row.className = 'mds-keyframe-group';
    row.innerHTML = `
        <div class="sheet-row mds-master-row">
            <div class="row-num">${idx}</div>
            <input type="number" id="mds_f${idx}" value="${idx === 1 ? 1 : (idx-1)*24+24}">
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
        
        if (st.status === 'rendering' && st.heartbeat) {
            isEngineRunning = true;
            msgEl.innerText = `${st.msg} [${st.heartbeat.current}/${st.heartbeat.total}]`;
            bar.style.width = (st.heartbeat.current/st.heartbeat.total*100) + "%";
        } else {
            if (isEngineRunning) {
                document.getElementById('probe_img').src = '/static/probe_live.jpg?t=' + Date.now();
                isEngineRunning = false;
            }
            msgEl.innerHTML = st.workprint ? `IDLE | <a href="${st.workprint}" target="_blank" style="color:#0cf">VIEW WORKPRINT</a>` : "Ready...";
            bar.style.width = "0%";
        }
    } catch(e) {}
}, 1000);