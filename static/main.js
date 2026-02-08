/* VOP Module: main.js - v0.0.18 */
let last_sync_ts = 0;
let last_known_state_str = "";
let isFirstLoad = true;

function jumpToFrame(id) {
    const val = document.getElementById(id).value;
    const probe = document.getElementById('probe_frame');
    if (probe && val) {
        probe.value = val;
        runTask('preview');
    }
}

function updateProbeRange() {
    const f1 = parseInt(document.getElementById('f1').value) || 1;
    const f3 = parseInt(document.getElementById('f3').value) || 100;
    const probe = document.getElementById('probe_frame');
    if (probe) { probe.min = f1; probe.max = f3; }
}

function getUISettings() {
    const data = {};
    document.querySelectorAll('input, select').forEach(i => { if(i.id) data[i.id] = i.value; });
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
    if (isFirstLoad) {
        const resp = await fetch('/status');
        const data = await resp.json();
        applyServerSettings(data.params);
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
            document.getElementById('sync_indicator').innerText = "● SYNCED";
            document.getElementById('sync_indicator').style.color = "#0f0";
        } else if (resp.status === 409) {
            const data = await resp.json();
            handleConflict(data.server_params);
        }
    }
}

function handleConflict(serverParams) {
    if (confirm("CONFLICT: Server has newer settings. Load them?")) {
        applyServerSettings(serverParams);
    } else {
        const currentUI = getUISettings();
        fetch('/sync_state', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ ...currentUI, force_overwrite: true })
        }).then(r => r.json()).then(data => {
            last_sync_ts = data.new_sync;
            last_known_state_str = getComparable(currentUI);
        });
    }
}

async function runTask(type) {
    const data = getUISettings();
    data.last_sync = last_sync_ts;
    
    if(document.getElementById('val_probe_frame')) document.getElementById('val_probe_frame').innerText = data.probe_frame;
    if(document.getElementById('val_probe_sub')) document.getElementById('val_probe_sub').innerText = data.probe_sub;

    try {
        const res = await fetch((type === 'preview' ? '/preview' : '/execute_sequence'), {
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify(data)
        });

        if(type === 'preview' && res.ok) {
            const img = document.getElementById('probe_img');
            img.src = `/static/probe_live.jpg?t=${Date.now()}`;
            img.style.display = 'block';
        }
    } catch (e) { console.error("Sync Error", e); }
}

function panic() { fetch('/panic', {method:'POST'}); }
function nukeMag() { if(confirm("NUKE TIFFS?")) fetch('/nuke_mag', {method:'POST'}); }

setInterval(heartbeat, 2000);
setInterval(async () => {
    const r = await fetch('/status');
    const st = await r.json();
    document.getElementById('st_msg').innerText = st.msg;
    const bar = document.getElementById('st_bar');
    if (bar) bar.style.width = (st.total > 0 ? (st.current/st.total*100) : 0) + "%";
    
    const dlLink = document.getElementById('wp_download');
    if (dlLink && st.latest_wp) {
        dlLink.href = `/download/${st.latest_wp}`;
        dlLink.innerText = `DOWNLOAD WORKPRINT: ${st.latest_wp}`;
        dlLink.style.display = 'block';
    } else if (dlLink) { dlLink.style.display = 'none'; }
}, 1000);