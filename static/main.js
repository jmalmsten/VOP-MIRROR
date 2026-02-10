/* VOP Module: main.js - v0.0.20 */
let last_sync_ts = 0;
let last_known_state_str = "";
let isFirstLoad = true;

function jumpToFrame(id) {
    const el = document.getElementById(id);
    const probe = document.getElementById('probe_frame');
    if (el && probe) {
        probe.value = el.value;
        runTask('preview');
    }
}

function updateProbeRange() {
    const f1_el = document.getElementById('f1');
    const f3_el = document.getElementById('f3');
    const probe = document.getElementById('probe_frame');
    if (f1_el && f3_el && probe) {
        probe.min = parseInt(f1_el.value) || 1;
        probe.max = parseInt(f3_el.value) || 100;
    }
}

function getUISettings() {
    const data = {};
    document.querySelectorAll('input, select').forEach(i => { 
        if(i.id) data[i.id] = i.value; 
    });
    return data;
}

function getComparable(settings) {
    const copy = { ...settings };
    delete copy.last_sync;
    return JSON.stringify(copy);
}

function applyServerSettings(params) {
    for (let k in params) {
        const el = document.getElementById(k);
        if (el && k !== 'last_sync' && document.activeElement !== el) {
            el.value = params[k];
        }
    }
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
            const resp = await fetch('/sync_state', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(syncPayload)
            });

            if (resp.status === 200) {
                const data = await resp.json();
                last_sync_ts = data.new_sync;
                last_known_state_str = currentUIStr;
                const ind = document.getElementById('sync_indicator');
                if (ind) { ind.innerText = "● SYNCED"; ind.style.color = "#0f0"; }
            }
        }
    } catch (e) { console.error("Heartbeat error:", e); }
}

async function runTask(type) {
    const data = getUISettings();
    data.last_sync = last_sync_ts;
    data.type = type; 
    
    const lblFr = document.getElementById('val_probe_frame');
    const lblSub = document.getElementById('val_probe_sub');
    if (lblFr) lblFr.innerText = data.probe_frame;
    if (lblSub) lblSub.innerText = data.probe_sub;

    const endpoint = (type === 'execute' ? '/execute_sequence' : '/preview');
    try {
        const res = await fetch(endpoint, {
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify(data)
        });

        if(type !== 'execute' && res.ok) {
            const img = document.getElementById('probe_img');
            const typeLabel = document.getElementById('preview_type');
            if (img) {
                img.src = `/static/probe_live.jpg?t=${Date.now()}`;
                img.style.display = 'block';
            }
            if (typeLabel) typeLabel.innerText = (type === 'cam_preview' ? "CAMERA VIEW" : "PROJECTOR PROBE");
        }
    } catch (e) { console.error("Task Error:", e); }
}

function panic() { fetch('/panic', {method:'POST'}); }
function nukeMag() { if(confirm("NUKE TIFFS?")) fetch('/nuke_mag', {method:'POST'}); }

setInterval(heartbeat, 2000);

setInterval(async () => {
    try {
        const r = await fetch('/status');
        if (!r.ok) return;
        const st = await r.json();
        
        const msgEl = document.getElementById('st_msg');
        const bar = document.getElementById('st_bar');
        
        if (st.status === 'running') {
            if (msgEl) msgEl.innerText = `${st.msg} [${st.current}/${st.total}] ETA: ${st.eta}s | ${st.disk}`;
            if (bar) bar.style.width = (st.total > 0 ? (st.current/st.total*100) : 0) + "%";
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