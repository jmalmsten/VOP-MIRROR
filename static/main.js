/* VOP Module:     main.js
Version:        v0.0.52 (Defaults Alignment)
Description:    Frontend app logic.
                Synchronized default keyframe Z values to match Fit_Z logic.
*/

let local_sync_ts = 0; 
let last_known_state_str = "";
let sssKeyframeCount = 0;
let mdsMasterCount = 0;
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
    const fitZInput = document.getElementById('fit_z');
    
    if (!fovVal || !fitZInput) return;
    
    const zDist = Math.abs(parseFloat(fitZInput.value)) || 1.0;

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

const modeSelect = document.getElementById('smear_mode');
if(modeSelect) {
    let previousMode = modeSelect.value;
    modeSelect.addEventListener('change', function(e) {
        if(confirm("WARNING: Switching Smear Modes will permanently wipe the current Exposure Sheet. Proceed?")) {
            previousMode = this.value;
            wipeSheetData();
            toggleSheetUI(this.value);
            if(this.value === 'SSS') addSSSKeyframe();
            if(this.value === 'MDS') addMDSKeyframe();
            triggerSync();
        } else {
            this.value = previousMode; 
        }
    });
}

function wipeSheetData() {
    document.getElementById('sss_sheet_body').innerHTML = "";
    document.getElementById('mds_sheet_body').innerHTML = "";
    sssKeyframeCount = 0;
    mdsMasterCount = 0;
}

function toggleSheetUI(mode) {
    document.getElementById('sss_wrapper').style.display = (mode === 'SSS') ? 'flex' : 'none';
    document.getElementById('mds_wrapper').style.display = (mode === 'MDS') ? 'flex' : 'none';
}

function createSSSRowHTML(i) {
    return `
        <div class="sheet-row" id="sss_row_${i}">
            <div class="row-index">${i}</div>
            <div class="k-fr">
                <input id="f${i}" type="number" value="${i === 1 ? 1 : ''}" onchange="updateProbeRange()" oninput="triggerSync()">
                <button class="snap-btn" onclick="jumpToFrame('f${i}')">GO</button>
            </div>
            <div><select id="m${i}" onchange="triggerSync()"><option value="S">Smth</option><option value="L">Lin</option></select></div>
            <div class="row-center"><input id="crn${i}" type="checkbox" onchange="triggerSync()"></div>
            <div><input id="src${i}" type="number" step="1" value="-1" oninput="triggerSync()"></div>
            <div><input id="stp${i}" type="number" step="1" value="1" oninput="triggerSync()"></div>
            <div><input id="p${i}" type="text" value="0,0,-1.0" oninput="triggerSync()"></div>
            <div><input id="r${i}" type="text" value="0,0,0" oninput="triggerSync()"></div>
            <div><input id="c${i}_hex" type="color" value="#ffffff" onchange="triggerSync()"></div>
            <div><input id="cg${i}_hex" type="color" value="#ffffff" onchange="triggerSync()"></div>
            <div><input id="s${i}" type="number" step="0.1" value="1.0" oninput="triggerSync()"></div>
            <div><input id="sd${i}" type="number" step="0.1" value="1.0" oninput="triggerSync()"></div>
            <div><input id="ph${i}" type="number" step="0.1" value="0.5" oninput="triggerSync()"></div>
            <div>${i > 1 ? `<button class="del-btn" onclick="removeRow('sss_row_${i}')">×</button>` : ''}</div>
        </div>
    `;
}

function addSSSKeyframe(skipSync = false) {
    sssKeyframeCount++;
    const container = document.getElementById('sss_sheet_body');
    const template = document.createElement('template');
    template.innerHTML = createSSSRowHTML(sssKeyframeCount);
    container.appendChild(template.content.firstElementChild);
    bindNewInputs(container);
    if (!skipSync) triggerSync();
}

function createMDSRowHTML(i) {
    return `
        <div id="mds_group_${i}">
            <div class="sheet-row mds-master-row">
                <div class="row-index">${i}</div>
                <div class="k-fr">
                    <input id="mds_f${i}" type="number" value="${i === 1 ? 1 : ''}" onchange="updateProbeRange()" oninput="triggerSync()">
                    <button class="snap-btn" onclick="jumpToFrame('mds_f${i}')">GO</button>
                </div>
                <div><select id="mds_m${i}" onchange="triggerSync()"><option value="S">Smth</option><option value="L">Lin</option></select></div>
                <div class="row-center"><input id="mds_crn${i}" type="checkbox" onchange="triggerSync()"></div>
                <div class="node-label" style="background: #345; color: #fff;">MASTER</div>
                <div><input id="mds_p${i}" type="text" value="0,0,-1.0" oninput="triggerSync()"></div>
                <div><input id="mds_r${i}" type="text" value="0,0,0" oninput="triggerSync()"></div>
                <div></div>
                <div></div>
                <div><input id="mds_s${i}" type="number" step="0.1" value="1.0" oninput="triggerSync()"></div>
                <div>${i > 1 ? `<button class="del-btn" onclick="removeRow('mds_group_${i}')">×</button>` : ''}</div>
            </div>
            <div class="sheet-row mds-sub-row">
                <div class="row-index">↳</div>
                <div></div><div></div><div></div>
                <div class="node-label">SMR: STRT</div>
                <div><input id="mds_start_p${i}" type="text" value="0,0,0" oninput="triggerSync()" style="color: #faa;"></div>
                <div><input id="mds_start_r${i}" type="text" value="0,0,0" oninput="triggerSync()" style="color: #faa;"></div>
                <div><input id="mds_start_c${i}_hex" type="color" value="#ffffff" onchange="triggerSync()"></div>
                <div><input id="mds_start_cg${i}_hex" type="color" value="#ffffff" onchange="triggerSync()"></div>
                <div></div><div></div>
            </div>
            <div class="sheet-row mds-sub-row">
                <div class="row-index">↳</div>
                <div></div><div></div><div></div>
                <div class="node-label">SMR: STOP</div>
                <div><input id="mds_stop_p${i}" type="text" value="0,0,0" oninput="triggerSync()" style="color: #faa;"></div>
                <div><input id="mds_stop_r${i}" type="text" value="0,0,0" oninput="triggerSync()" style="color: #faa;"></div>
                <div><input id="mds_stop_c${i}_hex" type="color" value="#ffffff" onchange="triggerSync()"></div>
                <div><input id="mds_stop_cg${i}_hex" type="color" value="#ffffff" onchange="triggerSync()"></div>
                <div></div><div></div>
            </div>
        </div>
    `;
}

function addMDSKeyframe(skipSync = false) {
    mdsMasterCount++;
    const container = document.getElementById('mds_sheet_body');
    const template = document.createElement('template');
    template.innerHTML = createMDSRowHTML(mdsMasterCount);
    container.appendChild(template.content.firstElementChild);
    
    if (mdsMasterCount > 1) {
        const prevId = mdsMasterCount - 1;
        const fields = ['p', 'r', 's'];
        const subFields = ['p', 'r', 'c_hex', 'cg_hex'];
        
        fields.forEach(f => {
            const prevEl = document.getElementById(`mds_${f}${prevId}`);
            const newEl = document.getElementById(`mds_${f}${mdsMasterCount}`);
            if (prevEl && newEl) newEl.value = prevEl.value;
        });
        
        ['start', 'stop'].forEach(type => {
            subFields.forEach(f => {
                const prevEl = document.getElementById(`mds_${type}_${f}${prevId}`);
                const newEl = document.getElementById(`mds_${type}_${f}${mdsMasterCount}`);
                if (prevEl && newEl) newEl.value = prevEl.value;
            });
        });
    }
    
    bindNewInputs(container);
    if (!skipSync) triggerSync();
}

function removeRow(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
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
    const inputs = Array.from(document.querySelectorAll('input[id*="f"]'))
                        .map(i => parseInt(i.value))
                        .filter(v => !isNaN(v));
    if (inputs.length > 0) {
        const probe = document.getElementById('probe_frame');
        if (probe) { probe.min = Math.min(...inputs) || 1; probe.max = Math.max(...inputs) || 100; }
    }
}

function getUISettings() {
    const data = {};
    document.querySelectorAll('.c-box input, .c-box select, .vop-sheet input, .vop-sheet select').forEach(i => { 
        if(i.id) {
            data[i.id] = (i.type === 'checkbox') ? i.checked : i.value;
        }
    });
    return data;
}

function getComparable(settings) {
    const copy = { ...settings };
    delete copy.last_sync;
    return JSON.stringify(copy);
}

function bindNewInputs(container) {
    container.querySelectorAll('input:not([type="file"]), select').forEach(el => {
        el.removeEventListener('change', triggerSync);
        el.addEventListener('change', triggerSync);
    });
}

async function triggerSync() {
    const currentUI = getUISettings();
    const currentUIStr = getComparable(currentUI);
    
    if (currentUIStr !== last_known_state_str) {
        const new_ts = Date.now();
        const syncPayload = { ...currentUI, last_sync: new_ts };
        
        try {
            const resp = await fetch('/sync_state', { 
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(syncPayload) 
            });
            if (resp.status === 200) {
                local_sync_ts = new_ts; 
                last_known_state_str = currentUIStr;
                const ind = document.getElementById('sync_indicator');
                if (ind) { ind.innerText = "● SYNCED"; ind.style.color = "#0f0"; }
            }
        } catch (e) { }
    }
}

async function runTask(type) {
    const data = getUISettings();
    data.last_sync = local_sync_ts;
    data.type = type; 
    try {
        const targetRoute = '/' + type; 
        
        const res = await fetch(targetRoute, {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
        });
        
        if(type !== 'execute' && res.ok) {
            const img = document.getElementById('probe_img');
            const typeLabel = document.getElementById('preview_type');
            if (img) { 
                img.src = `/static/probe_live.jpg?t=${Date.now()}`; 
                img.style.display = 'block'; 
            }
            if (typeLabel) {
                typeLabel.innerText = (type === 'cam_preview' ? "CAMERA VIEW" : "PROJECTOR PROBE");
            }
        }
    } catch (e) { 
        console.error("Task execution failed:", e);
    }
}

function panic() { fetch('/panic', {method:'POST'}); }
function nukeMag() { if(confirm("NUKE TIFFS?")) fetch('/nuke_mag', {method:'POST'}); }

document.querySelectorAll('.c-box input:not([type="file"]), .c-box select').forEach(el => {
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

async function pollHeartbeat() {
    try {
        const response = await fetch('/status');
        if (response.ok) {
            const data = await response.json();
            
            const msgEl = document.getElementById('st_msg');
            const barEl = document.getElementById('st_bar');
            
            if (!msgEl || !barEl) return; 
            
            if (data.status === 'idle') {
                if (msgEl.innerText !== "Ready..." && !msgEl.innerHTML.includes('<a')) {
                    msgEl.innerText = "Ready...";
                    barEl.style.width = "0%";
                }
            } else if (data.status === 'rendering' && data.heartbeat) {
                const hb = data.heartbeat;
                const pct = (hb.current / hb.total) * 100;
                
                const mins = Math.floor(hb.eta / 60);
                const secs = hb.eta % 60;
                const etaStr = `${mins}:${secs < 10 ? '0' : ''}${secs}`;
                
                msgEl.innerText = `RENDERING: Frame ${hb.current} of ${hb.total} | ETA: ${etaStr} | Est. Size: ${hb.est_mb} MB`;
                barEl.style.width = `${pct}%`;
            } else if (data.status === 'complete') {
                if (data.workprint) {
                    msgEl.innerHTML = `COMPLETE: <a href="${data.workprint}" target="_blank" style="color: #0f0; text-decoration: underline; font-weight: bold;">Download FFmpeg Workprint</a>`;
                } else {
                    msgEl.innerText = "COMPLETE: Workprint finished.";
                }
                barEl.style.width = "100%";
            }
        }
    } catch (e) {
    }
}

setInterval(pollHeartbeat, 1000);

toggleSheetUI(document.getElementById('smear_mode').value);