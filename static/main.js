/* VOP Module: main.js - v0.0.30 */
// ... (Previous helper functions: formatTime, calcFitScale, etc. remain the same) ...
let last_sync_ts = 0;
let last_known_state_str = "";
let isFirstLoad = true;
let keyframeCount = 0;

function formatTime(seconds) {
    if (!seconds || seconds < 0) return "00:00:00";
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return [hrs, mins, secs].map(v => v < 10 ? "0" + v : v).join(":");
}

function calcFitScale() {
    const fovVal = parseFloat(document.getElementById('fov').value);
    const scaleInput = document.getElementById('coord_scale');
    if (!fovVal) return;
    const halfFovRad = (fovVal / 2) * (Math.PI / 180);
    scaleInput.value = Math.tan(halfFovRad).toFixed(4);
    runTask('preview');
}

function createRowHTML(i) {
    return `
        <div class="sheet-row" id="row_${i}">
            <div class="row-index">${i}</div>
            <div class="k-fr">
                <input id="f${i}" type="number" onchange="updateProbeRange()">
                <button class="snap-btn" onclick="jumpToFrame('f${i}')">GO</button>
            </div>
            <div>
                <select id="m${i}" title="Interpolation Mode">
                    <option value="S">Smth</option>
                    <option value="L">Lin</option>
                    <option value="I">In</option>
                    <option value="O">Out</option>
                </select>
            </div>
            <div class="row-center">
                <input id="crn${i}" type="checkbox" title="Corner (Sharp Turn)">
            </div>
            <div>
                <input id="stp${i}" type="number" step="1" value="1" title="Source Step (1=Play, 0=Freeze, -1=Rev)">
            </div>
            <div><input id="p${i}" type="text" value="0,0,-10"></div>
            <div><input id="r${i}" type="text" value="0,0,0"></div>
            <div><input id="c${i}_hex" type="color" value="#ffffff" title="ProjGel"></div>
            <div><input id="cg${i}_hex" type="color" value="#ffffff" title="CamGel"></div>
            <div><input id="s${i}" type="number" step="0.1" value="1.0"></div>
            <div><input id="sd${i}" type="number" step="0.1" value="1.0"></div>
            <div><input id="ph${i}" type="number" step="0.1" value="0.5"></div>
            <div>${i > 1 ? `<button class="del-btn" onclick="removeKeyframe(${i})">×</button>` : ''}</div>
        </div>
    `;
}

// ... (addKeyframe, removeKeyframe, jumpToFrame, updateProbeRange, getUISettings, getComparable remain the same) ...

function addKeyframe() {
    keyframeCount++;
    const container = document.getElementById('sheet_container');
    const div = document.createElement('div');
    div.innerHTML = createRowHTML(keyframeCount);
    container.appendChild(div.firstElementChild);
}

function removeKeyframe(id) {
    const row = document.getElementById(`row_${id}`);
    if (row) row.remove();
    runTask('preview'); 
}

function jumpToFrame(id) {
    const el = document.getElementById(id);
    const probe = document.getElementById('probe_frame');
    if (el && probe) {
        probe.value = el.value;
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
    while (keyframeCount < maxIdx) addKeyframe();
    if (keyframeCount === 0) addKeyframe();
    for (let k in params) {
        const el = document.getElementById(k);
        if (el && k !== 'last_sync' && document.activeElement !== el) {
            if(el.type === 'checkbox') el.checked = params[k];
            else el.value = params[k];
        }
    }
    calcFitScale();
    last_sync_ts = params.last_sync || 0;
    last_known_state_str = getComparable(getUISettings());
    updateProbeRange();
}

async function heartbeat() {
    try {
        if (isFirstLoad) {
            const resp = await fetch('/status');
            const data = await resp.json();
            if (data.params) applyServerSettings(data.params);
            isFirstLoad = false;
            return;
        }
        const currentUI = getUISettings();
        const currentUIStr = getComparable(currentUI);
        if (currentUIStr !== last_known_state_str) {
            const syncPayload = { ...currentUI, last_sync: last_sync_ts };
            const resp = await fetch('/sync_state', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(syncPayload) });
            if (resp.status === 200) {
                const data = await resp.json();
                last_sync_ts = data.new_sync;
                last_known_state_str = currentUIStr;
                const ind = document.getElementById('sync_indicator');
                if (ind) { ind.innerText = "● SYNCED"; ind.style.color = "#0f0"; }
            }
        }
    } catch (e) { }
}

async function runTask(type) {
    const data = getUISettings();
    data.last_sync = last_sync_ts;
    data.type = type; 
    const lblFr = document.getElementById('val_probe_frame');
    const lblSub = document.getElementById('val_probe_sub');
    if (lblFr) lblFr.innerText = data.probe_frame;
    if (lblSub) lblSub.innerText = data.probe_sub;

    try {
        const res = await fetch(type === 'execute' ? '/execute_sequence' : '/preview', {
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

const fileInput = document.getElementById('file_input');
if(fileInput) {
    fileInput.addEventListener('change', async function() {
        if(this.files && this.files.length > 0) {
            
            // --- WARN BEFORE NUKE ---
            if(!confirm("WARNING: Uploading a file will ERASE the current contents of the Projector Mag. Continue?")) {
                this.value = ''; // Reset input
                return;
            }

            const formData = new FormData();
            formData.append('file', this.files[0]);
            
            try {
                const resp = await fetch('/upload_target', {
                    method: 'POST',
                    body: formData
                });
                
                if(resp.ok) {
                    const data = await resp.json();
                    document.getElementById('image').value = data.filename;
                    runTask('preview'); 
                } else {
                    alert("Upload Failed");
                }
            } catch(e) { console.error("Upload error", e); }
        }
    });
}

setInterval(heartbeat, 2000);
setInterval(async () => {
    try {
        const r = await fetch('/status');
        if (!r.ok) return;
        const st = await r.json();
        const msgEl = document.getElementById('st_msg');
        const bar = document.getElementById('st_bar');
        if (st.status === 'running' || st.status === 'busy') { // Added 'busy' for ffmpeg state
            const timeStr = formatTime(st.eta);
            if (msgEl) msgEl.innerText = `${st.msg} [${st.current}/${st.total}] REMAINING: ${timeStr} | ${st.disk}`;
            if (bar) bar.style.width = (st.total > 0 ? (st.current/st.total*100) : 100) + "%"; // 100% for busy/ffmpeg
        } else {
            if (msgEl) msgEl.innerText = `${st.msg} | ${st.disk}`;
            if (bar) bar.style.width = "0%";
        }
        const dlLink = document.getElementById('wp_download');
        if (dlLink && st.latest_wp) {
            dlLink.href = `/download/${st.latest_wp}`;
            dlLink.innerText = `DOWNLOAD WORKPRINT: ${st.latest_wp}`;
            dlLink.style.display = 'block';
        } else if (dlLink) { dlLink.style.display = 'none'; }
    } catch (e) { }
}, 1000);