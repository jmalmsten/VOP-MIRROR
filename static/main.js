/* VOP Module: main.js - v0.0.5 */
let isFirstLoad = true;
let uiLock = false;

// Global detection for user input to prevent status-poll overwrites
document.addEventListener('input', () => { uiLock = true; });
document.addEventListener('change', () => { uiLock = false; });

function updateProbeRange() {
    const f1 = parseInt(document.getElementById('f1').value) || 1;
    const f3 = parseInt(document.getElementById('f3').value) || 100;
    const probe = document.getElementById('probe_frame');
    probe.min = f1; probe.max = f3;
}

async function updateHUD() {
    const resp = await fetch('/status');
    const st = await resp.json();
    
    document.getElementById('st_msg').innerText = st.msg;
    document.getElementById('st_bar').style.width = (st.total > 0 ? (st.current/st.total*100) : 0) + "%";
    
    if (st.eta > 0) {
        const min = Math.floor(st.eta / 60);
        const sec = st.eta % 60;
        document.getElementById('st_eta').innerText = `${min}:${sec.toString().padStart(2, '0')}`;
    }

    // ONLY update inputs if the user isn't currently touching them
    if ((isFirstLoad || !uiLock) && st.params) {
        for (let k in st.params) { 
            const el = document.getElementById(k);
            if(el) el.value = st.params[k]; 
        }
        updateProbeRange(); 
        isFirstLoad = false;
    }
}
setInterval(updateHUD, 1000);

async function runTask(type) {
    const data = {};
    document.querySelectorAll('input, select').forEach(i => { if(i.id) data[i.id] = i.value; });
    const res = await fetch((type === 'preview' ? '/preview' : '/execute_sequence'), {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
    });
    if(type === 'preview') {
        const d = await res.json();
        const img = document.getElementById('probe_img');
        img.src = `/static/probe_live.jpg?t=${d.timestamp}`;
        img.style.display = 'block';
    }
}

function panic() { if(confirm("ABORT CAPTURE?")) fetch('/panic', {method:'POST'}); }
function nukeMag() { if(confirm("PERMANENTLY DELETE ALL TIFFS?")) fetch('/nuke_mag', {method:'POST'}); }