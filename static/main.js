/* VOP Module:     main.js
Version:        v0.0.42
Description:    Frontend application logic. Handles dynamic HTML generation,
                multi-device state synchronization via timestamps, and UI events.
                Restored SRC and STP inputs to maintain step-printing logic context.
*/

let local_sync_ts = 0; 
let last_known_state_str = "";
let keyframeCount = 0;
let isFirstLoad = true;

function formatTime(seconds) {
    if (!seconds || seconds < 0) return "00:00:00";
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return [hrs, mins, secs].map(v => v < 10 ? "0" + v : v).join(":");
}

async function calcFitScale() {
    const fovVal = parseFloat(document.getElementById('fov').value);
    const scaleInput = document.getElementById('coord_scale');
    if (!fovVal) return;
    
    let zDist = 1.0;
    const p1Input = document.getElementById('p1');
    if (p1Input && p1Input.value) {
        const parts = p1Input.value.split(',');
        if (parts.length >= 3) {
            zDist = Math.abs(parseFloat(parts[2])) || 1.0;
        }
    }

    const camResStr = document.getElementById('cam_res').value || "2028x1520";
    const camRes = camResStr.split('x');
    let camAspect = 1.333; 
    if (camRes.length === 2) {
        camAspect = parseFloat(camRes[0]) / parseFloat(camRes[1]);
    }

    try {
        const resp = await fetch('/get_img_aspect');
        const data = await resp.json();
        const imgAspect = data.aspect || 1.0;

        const halfFovRad = (fovVal / 2) * (Math.PI / 180);
        
        const frustumH = 2.0 * zDist * Math.tan(halfFovRad);
        const frustumW = frustumH * camAspect;

        const scaleH = frustumH / 2.0;
        const scaleW = frustumW / (2.0 * imgAspect);

        const s = Math.min(scaleH, scaleW); 
        
        scaleInput.value = s.toFixed(4);
        triggerSync(); 
        runTask('preview'); 
    } catch (e) {
        console.error("Fit Scale calculation failed", e);
    }
}

function createRowHTML(i) {
    return `
        <div class="sheet-row" id="row_${i}">
            <div class="row-index">${i}</div>
            <div class="k-fr">
                <input id="f${i}" type="number" onchange="updateProbeRange()" oninput="triggerSync()">
                <button class="snap-btn" onclick="jumpToFrame('f${i}')">GO</button>
            </div>
            <div>
                <select id="m${i}" title="Interpolation Mode" onchange="triggerSync()">
                    <option value="S">Smth</option>
                    <option value="L">Lin</option>
                    <option value="I">In</option>
                    <option value="O">Out</option>
                </select>
            </div>
            <div class="row-center">
                <input id="crn${i}" type="checkbox" title="Corner" onchange="triggerSync()">
            </div>
            <div title="Source Anchor (-1 Auto)"><input id="src${i}" type="number" step="1" value="-1" oninput="triggerSync()"></div>
            <div title="Source Step"><input id="stp${i}" type="number" step="1" value="1" oninput="triggerSync()"></div>
            <div><input id="p${i}" type="text" value="0,0,-1.5" oninput="triggerSync()"></div>
            <div><input id="r${i}" type="text" value="0,0,0" oninput="triggerSync()"></div>
            <div><input id="c${i}_hex" type="color" value="#ffffff" title="ProjGel" onchange="triggerSync()"></div>
            <div><input id="cg${i}_hex" type="color" value="#ffffff" title="CamGel" onchange="triggerSync()"></div>
            <div><input id="s${i}" type="number" step="0.1" value="1.0" oninput="triggerSync()"></div>
            <div><input id="sd${i}" type="number" step="0.1" value="1.0" oninput="triggerSync()"></div>
            <div><input id="ph${i}" type="number" step="0.1" value="0.5" oninput="triggerSync()"></div>
            <div>${i > 1 ? `<button class="del-btn" onclick="removeKeyframe(${i})">×</button>` : ''}</div>
        </div>
    `;
}

function addKeyframe(skipSync = false) {
    const prevId = keyframeCount;
    keyframeCount++;
    
    const container = document.getElementById('sheet_body');
    const template = document.createElement('template');
    template.innerHTML = createRowHTML(keyframeCount);
    container.appendChild(template.content.firstElementChild);
    
    if (prevId > 0) {
        const fieldsToClone = ['m', 'crn', 'src', 'stp', 'p', 'r', 'c_hex', 'cg_hex', 's', 'sd', 'ph'];
        fieldsToClone.forEach(f => {
            const isHex = f.includes('_hex');
            const baseStr = f.replace('_hex', '');
            const prevStrId = `${baseStr}${prevId}${isHex ? '_hex' : ''}`;
            const newStrId = `${baseStr}${keyframeCount}${isHex ? '_hex' : ''}`;
            
            const prevEl = document.getElementById(prevStrId);
            const newEl = document.getElementById(newStrId);
            
            if (prevEl && newEl) {
                if (newEl.type === 'checkbox') newEl.checked = prevEl.checked;
                else newEl.value = prevEl.value;
            }
        });
    }
    if (!skipSync) triggerSync();
}

function removeKeyframe(id) {
    const row = document.getElementById(`row_${id}`);
    if (row) row.remove();
    triggerSync();
    runTask('preview'); 
}

function jumpToFrame(id) {
    const el = document.getElementById(id);
    const probe = document.getElementById('probe_frame');
    if (el && probe) {
        probe.value = el.value;
        triggerSync();
        runTask('preview');
    }
}

function updateProbeRange() {
    const inputs = Array.from(document.querySelectorAll('input[id^="f"]'))
                        .map(i => parseInt(i.value))
                        .filter(v => !isNaN(v));
    
    if (inputs.length > 0) {
        const minF = Math.min(...inputs);
        const maxF = Math.max(...inputs);
        const probe = document.getElementById('probe_frame');
        if (probe) {
            probe.min = minF || 1;
            probe.max = maxF || 100;
        }
    }
}

function getUISettings() {
    const data = {};
    document.querySelectorAll('input, select').forEach(i => { 
        if(i.id) data[i.id] = i.value; 
    });
    document.querySelectorAll('input[type="checkbox"]').forEach(i => {
        if(i.id) data[i.id] = i.checked;
    });
    return data;
}

function getComparable(settings) {
    const copy = { ...settings };
    delete copy.last_sync;
    return JSON.stringify(copy);
}

function applyServerSettings(params) {
    let maxIdx = 0;
    for (let k in params) {
        if (k.startsWith('f') && !isNaN(parseInt(k.substring(1)))) {
            maxIdx = Math.max(maxIdx, parseInt(k.substring(1)));
        }
    }
    
    while (keyframeCount < maxIdx) addKeyframe(true);
    if (keyframeCount === 0) addKeyframe(true);
    
    for (let k in params) {
        const el = document.getElementById(k);
        if (el && k !== 'last_sync' && document.activeElement !== el) {
            if(el.type === 'checkbox') {
                if(el.checked !== params[k]) el.checked = params[k];
            } else {
                if(el.value !== params[k]) el.value = params[k];
            }
        }
    }
    
    local_sync_ts = params.last_sync || 0;
    last_known_state_str = getComparable(getUISettings());
    updateProbeRange();
}

async function triggerSync() {
    const currentUI = getUISettings();
    const currentUIStr = getComparable(currentUI);
    
    if (currentUIStr !== last_known_state_str) {
        const new_ts = Date.now();
        const syncPayload = { ...currentUI, last_sync: new_ts };
        
        try {
            const resp = await fetch('/sync_state', { 
                method: 'POST', 
                headers: {'Content-Type': 'application/json'}, 
                body: JSON.stringify(syncPayload) 
            });
            
            if (resp.status === 200) {
                local_sync_ts = new_ts; 
                last_known_state_str = currentUIStr;
                const ind = document.getElementById('sync_indicator');
                if (ind) { ind.innerText = "● SYNCED"; ind.style.color = "#0f0"; }
            }
        } catch (e) { console.error("Sync Failed", e); }
    }
}

async function runTask(type) {
    const data = getUISettings();
    data.last_sync = local_sync_ts;
    data.type = type; 
    
    const lblFr = document.getElementById('val_probe_frame');
    const lblSub = document.getElementById('val_probe_sub');
    if (lblFr) lblFr.innerText = data.probe_frame;
    if (lblSub) lblSub.innerText = data.probe_sub;

    try {
        const targetRoute = type === 'execute' ? '/execute_sequence' : '/preview';
        const res = await fetch(targetRoute, {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
        });
        
        if(type !== 'execute' && res.ok) {
            const img = document.getElementById('probe_img');
            const typeLabel = document.getElementById('preview_type');
            if (img) { img.src = `/static/probe_live.jpg?t=${Date.now()}`; img.style.display = 'block'; }
            if (typeLabel) typeLabel.innerText = (type === 'cam_preview' ? "CAMERA VIEW" : "PROJECTOR PROBE");
        }
    } catch (e) { console.error("Task Error:", e); }
}

function panic() { fetch('/panic', {method:'POST'}); }
function nukeMag() { if(confirm("NUKE TIFFS?")) fetch('/nuke_mag', {method:'POST'}); }

document.querySelectorAll('.c-box input, .c-box select').forEach(el => {
    el.addEventListener('change', triggerSync);
    if (el.type === 'number' || el.type === 'text') el.addEventListener('input', triggerSync);
});

const fileInput = document.getElementById('file_input');
if(fileInput) {
    fileInput.addEventListener('change', async function() {
        if(this.files && this.files.length > 0) {
            if(!confirm("WARNING: Uploading a file will ERASE the current contents of the Projector Mag. Continue?")) {
                this.value = ''; return;
            }
            const formData = new FormData();
            formData.append('file', this.files[0]);
            try {
                const resp = await fetch('/upload_target', { method: 'POST', body: formData });
                if(resp.ok) {
                    const data = await resp.json();
                    document.getElementById('image').value = data.filename;
                    triggerSync();
                    runTask('preview'); 
                } else { alert("Upload Failed"); }
            } catch(e) { console.error("Upload error", e); }
        }
    });
}

setInterval(async () => {
    try {
        const r = await fetch('/status');
        if (!r.ok) return;
        const st = await r.json();
        
        if (st.params && (isFirstLoad || st.params.last_sync > local_sync_ts)) {
            applyServerSettings(st.params);
            isFirstLoad = false;
        }
        
        const msgEl = document.getElementById('st_msg');
        const bar = document.getElementById('st_bar');
        
        if (st.status === 'running' || st.status === 'busy') {
            const timeStr = formatTime(st.eta);
            if (msgEl) msgEl.innerHTML = `${st.msg} [${st.current}/${st.total}] REMAINING: ${timeStr} | ${st.disk}`;
            if (bar) bar.style.width = (st.total > 0 ? (st.current/st.total*100) : 100) + "%";
        } else {
            let wpLink = st.latest_wp ? ` | <a href="/workprints/${st.latest_wp}" target="_blank" style="color:#0cf; text-decoration:none; font-weight:bold;">▶ VIEW LATEST WORKPRINT</a>` : "";
            if (msgEl) msgEl.innerHTML = `${st.msg} | ${st.disk}${wpLink}`;
            if (bar) bar.style.width = "0%";
        }
    } catch (e) { }
}, 1000);