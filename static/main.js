/* VOP Module:     main.js
Description:    Frontend logic.
*/

/*
#
###########################################################################
#
#                                   VOP
#                       Copyright (C) 2025  jmalmsten
#
#     This program is free software: you can redistribute it and/or modify 
#     it under the terms of the GNU Affero General Public License as 
#     published by the Free Software Foundation, either version 3 of the 
#     License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful, but 
#     WITHOUT ANY WARRANTY; without even the implied warranty of 
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU 
#     Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public 
#     License along with this program.  If not, see 
#     <http://www.gnu.org/licenses/>.
#
#     Source code for this application can be found at 
#     https://codeberg.org/jmalmsten-com/VOP
#
###########################################################################

*/

let local_sync_ts = 0; 
let mdsMasterCount = 0;
let sssMasterCount = 0;
let isFirstLoad = true;
let isEngineRunning = false;
let currentMode = 'SSS'; // <-- tracks the current active mode and sets the initial default.

// Initialize the dropdown listener when the DOM loads
document.addEventListener('DOMContentLoaded', () => {
    const modeSelect = document.getElementById('smear_mode');
    if (modeSelect) {
        currentMode = modeSelect.value;
        toggleSheetVisibility();
        
        modeSelect.addEventListener('change', function(e) {
            if (confirm("Switching modes is destructive. All keyframing will be thrown out. Are you sure you want to continue?")) {
                currentMode = this.value;
                document.getElementById('mds_sheet_body').innerHTML = '';
                document.getElementById('sss_sheet_body').innerHTML = '';
                mdsMasterCount = 0;
                sssMasterCount = 0;
                toggleSheetVisibility();
                triggerSync();
            } else {
                this.value = currentMode; // Revert dropdown if cancelled
            }
        });
    }
});

function toggleSheetVisibility() {
    const mdsWrap = document.getElementById('mds_wrapper');
    const sssWrap = document.getElementById('sss_wrapper');
    if (mdsWrap) mdsWrap.style.display = (currentMode === 'MDS') ? 'block' : 'none';
    if (sssWrap) sssWrap.style.display = (currentMode === 'SSS') ? 'block' : 'none';
}

const VIDEO_EXTS = new Set(['.mp4', '.mov', '.avi', '.mkv', '.webm']);

async function uploadFile(inputId, textId, endpoint) {
    const file = document.getElementById(inputId).files[0];
    if(!file) return;

    const ext = '.' + file.name.split('.').pop().toLowerCase();
    const isVideo = VIDEO_EXTS.has(ext);
    const textEl = document.getElementById(textId);

    if (isVideo) {
        textEl.value = 'EXTRACTING FRAMES - PLEASE WAIT...';
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const resp = await fetch(endpoint, { method: 'POST', body: formData });
        const data = await resp.json();
        // Show the original filename so the user knows what was loaded
        textEl.value = data.filename;
        await triggerSync();
    } catch(e) {
        console.error("Upload failed", e);
        textEl.value = 'UPLOAD FAILED';
    }
}    
    

async function triggerSync() {
    local_sync_ts = Date.now();
    await fetch('/preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(collectParams())});
    document.getElementById('probe_img').src = '/static/probe_live.jpg?t=' + Date.now();
}

function collectParams() {
    const p = { last_sync: local_sync_ts };
    document.querySelectorAll('input, select').forEach(el => {
        // Guard: Do not collect data from file inputs
        if (el.id && el.type !== 'file') {
            let val = el.type === 'checkbox' ? el.checked : el.value;
            
            // Cast string booleans back to native JavaScript booleans for the Python backend
            if (val === 'true') val = true;
            if (val === 'false') val = false;
            
            p[el.id] = val;
        }
    });
    return p;
}

async function runTask(type) {
    await fetch(`/${type}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(collectParams())});
    // comp_preview writes to the same /static/probe_live.jpg as the
    // other two preview types, so it gets the same image-reload treatment.
    if (type === 'preview' || type === 'cam_preview' || type === 'comp_preview') {
        document.getElementById('probe_img').src = '/static/probe_live.jpg?t=' + Date.now();
    }
}

/* Cam Probe: read the existing latent TIFF for the current probe frame
 * from CamMag, convert to JPG, and show it in the preview window.
 *
 * If no latent exists for this frame, the backend writes a clearly-marked
 * placeholder JPG to probe_live.jpg instead - so from the frontend's
 * perspective Cam Probe always succeeds and always produces a fresh JPG.
 * That keeps this handler trivially shaped: post, then cache-bust.
 *
 * Cam Probe runs as a plain Flask request (no engine dispatch) so it's
 * fast and works even while the engine is busy with a long Execute job.
 */
async function runCamProbe() {
    await fetch('/cam_probe', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(collectParams())
    });
    // Cache-bust the preview image so the browser fetches the freshly
    // written JPG instead of serving the stale one.
    document.getElementById('probe_img').src = '/static/probe_live.jpg?t=' + Date.now();
}

function panic() { 
    if (confirm("This stops whatever job is running. Are you sure?")) {
        fetch('/panic', {method: 'POST'}); 
    }
}
function nukeMag() { 
    if (confirm("This deletes all latent frames that has been exposed. All will be trashed. Are you sure? This cannot be undone.")){
        fetch('/nuke_mag', {method: 'POST'}); 
    }
}

function nukeProjMag() {
    if (confirm("This deletes whatever is in the Projector Magazine. Are you sure? This cannot be undone.")) {
        fetch('/nuke_proj_mag', {method: 'POST'});
        document.getElementById('image').value = '';
        triggerSync();
    }
}

function nukeProjBiPack1() {
    if (confirm("This deletes whatever is in Projector BiPack 1. Are you sure? This cannot be undone.")) {
        fetch('/nuke_proj_bipack1', {method: 'POST'});
        document.getElementById('bipack1_image').value = '';
        triggerSync();
    }
}

function nukeProjBiPack2() {
    if (confirm("This deletes whatever is in Projector BiPack 2. Are you sure? This cannot be undone.")) {
        fetch('/nuke_proj_bipack2', {method: 'POST'});
        document.getElementById('bipack2_image').value = '';
        triggerSync();
    }
}

async function nukeJob() {
    if (confirm("Reset current session to default_job.json? This cannot be undone.")) {
        await fetch('/nuke_job', {method: 'POST'});
        window.location.reload(); // Triggers the fresh /status check
    }
}

/* Darkroom Processing: LAB/INVERT
 * Dispatches a background task to invert the mag of the latent image buffer.
 * Highly destructive: Overwrites the original files in CamMag.
 */
async function triggerLabInvert() {
    if (confirm("WARNING: LAB/INVERT\n\nThis will mathematically invert all exposedframes in the CamMag(acting as a negative). This overwrites the original files and is highly destructive. Are you sure you want to proceed?")){
        await fetch('/lab_invert', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(collectParams())
        });
    }
}

async function calcFitScale(scaleId, fitZId, magType, mode = "fit") {
    // mode: "fit"  = entire image visible inside frustum (letterbox/pillarbox)
    //       "fill" = frustum entirely covered by image (image overflows on short axis)
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
            body: JSON.stringify({ fov: fov, ref_z: zDist, aspect_ratio: imgAspect, mode: mode })
        });
        const fitData = await fitReq.json();

        if (fitData.status === 'ok') {
            document.getElementById(scaleId).value = fitData.scale.toFixed(4);
            console.log(`[VOP UI] ${magType.toUpperCase()} Scale ${mode.toUpperCase()} to: ${fitData.scale.toFixed(4)}`);
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
    // Default baseline. One block per layer for clarity. PM keeps its original
    // unsuffixed key names ('p', 'r', 'sp', 'sr', 'ep', 'er', 'pm_gate' etc.)
    // because PM was never asymmetric; only BP got numbered. BP1 inherits the
    // shape of the old single-BP defaults but with 'bp1_' / 'sbp1_' / 'ebp1_'
    // prefixes; BP2 is new and parallel.
    let vals = {
        m: "S", crn: false,
        // Master row spatial defaults
        p: "0,0,-1.0", r: "0,0,0",
        bp1_p: "0,0,-1.0", bp1_r: "0,0,0",
        bp2_p: "0,0,-1.0", bp2_r: "0,0,0",
        // Light + exposure
        c: "#ffffff", cg: "#ffffff", exp: "1.0", f: 1,
        // JK Printer defaults: empty gate (no anchor, just continue), 1:1 playback rate
        pm_gate: "",  pm_cam: "1",  pm_stp: "1",
        bp1_gate: "", bp1_cam: "1", bp1_stp: "1",
        bp2_gate: "", bp2_cam: "1", bp2_stp: "1",
        // Smear START row offsets (one set per layer)
        sp: "0,0,0", sr: "0,0,0",
        sbp1_p: "0,0,0", sbp1_r: "0,0,0",
        sbp2_p: "0,0,0", sbp2_r: "0,0,0",
        sc: "#ffffff", scg: "#ffffff",
        // Smear STOP row offsets (one set per layer)
        ep: "0,0,0", er: "0,0,0",
        ebp1_p: "0,0,0", ebp1_r: "0,0,0",
        ebp2_p: "0,0,0", ebp2_r: "0,0,0",
        ec: "#ffffff", ecg: "#ffffff"
    };

    if (lastRow) {
        // Scraper helpers: look up by selector inside the previous row's DOM
        const getV = (sel) => { const el = lastRow.querySelector(sel); return el ? el.value : ""; };
        const getC = (sel) => { const el = lastRow.querySelector(sel); return el ? el.checked : false; };
        
        // The previous-row scrape now uses explicit per-layer class hooks 
        // (.bp1-input, .bp2-input) rather than the old :not([id*="bp"]) trick.
        // The class-hook approach is clearer and also future-proof - adding a 
        // BP3 wouldn't break PM scrapes the way an [id*="bp"] filter eventually 
        // would once we run out of letters to negate on.
        vals = {
            m: getV('.mds-master-row select'),
            crn: getC('.mds-master-row input[type="checkbox"]'),
            // PM spatial - master row. The :not([id^="mds_pm_"]) excludes 
            // mds_pm_gate / mds_pm_cam / mds_pm_stp from accidentally being 
            // picked up by [id^="mds_p"] (which would otherwise match the 
            // 'pm_' prefix because "mds_p" is a prefix of "mds_pm_").
            p: getV('.mds-master-row input[id^="mds_p"]:not([id^="mds_pm_"]):not([id^="mds_bp1_"]):not([id^="mds_bp2_"])'),
            r: getV('.mds-master-row input[id^="mds_r"]:not([id^="mds_bp1_"]):not([id^="mds_bp2_"])'),
            // BP1/BP2 spatial - master row
            bp1_p: getV('.mds-master-row .bp1-input[id*="_p"]'),
            bp1_r: getV('.mds-master-row .bp1-input[id*="_r"]'),
            bp2_p: getV('.mds-master-row .bp2-input[id*="_p"]'),
            bp2_r: getV('.mds-master-row .bp2-input[id*="_r"]'),
            // Color selectors: Targets hidden hex fields within specific row types
            c: getV('.mds-master-row input[id^="mds_c"]:not([id*="cg"])[id$="_hex"]'),
            cg: getV('.mds-master-row input[id^="mds_cg"][id$="_hex"]'),
            exp: getV('.mds-master-row input[id*="mds_s"]'),
            f: parseInt(getV('.mds-master-row input[id*="_f"]')) + 1,
            
            // Smear START scrapes (one block per layer)
            sp: getV('.mds-smear-row:nth-child(2) input[id^="mds_start_p"]:not(.bp1-input):not(.bp2-input)'),
            sr: getV('.mds-smear-row:nth-child(2) input[id^="mds_start_r"]:not(.bp1-input):not(.bp2-input)'),
            sbp1_p: getV('.mds-smear-row:nth-child(2) .bp1-input[id*="_p"]'),
            sbp1_r: getV('.mds-smear-row:nth-child(2) .bp1-input[id*="_r"]'),
            sbp2_p: getV('.mds-smear-row:nth-child(2) .bp2-input[id*="_p"]'),
            sbp2_r: getV('.mds-smear-row:nth-child(2) .bp2-input[id*="_r"]'),
            sc: getV('.mds-smear-row:nth-child(2) input[id*="_c"][id$="_hex"]:not([id*="cg"])'),
            scg: getV('.mds-smear-row:nth-child(2) input[id*="_cg"][id$="_hex"]'),

            // Smear STOP scrapes (one block per layer)
            ep: getV('.mds-smear-row:nth-child(3) input[id^="mds_stop_p"]:not(.bp1-input):not(.bp2-input)'),
            er: getV('.mds-smear-row:nth-child(3) input[id^="mds_stop_r"]:not(.bp1-input):not(.bp2-input)'),
            ebp1_p: getV('.mds-smear-row:nth-child(3) .bp1-input[id*="_p"]'),
            ebp1_r: getV('.mds-smear-row:nth-child(3) .bp1-input[id*="_r"]'),
            ebp2_p: getV('.mds-smear-row:nth-child(3) .bp2-input[id*="_p"]'),
            ebp2_r: getV('.mds-smear-row:nth-child(3) .bp2-input[id*="_r"]'),
            ec: getV('.mds-smear-row:nth-child(3) input[id*="_c"][id$="_hex"]:not([id*="cg"])'),
            ecg: getV('.mds-smear-row:nth-child(3) input[id*="_cg"][id$="_hex"]'),
            // JK Printer scrape from previous row.
            // GATE: always blank on a NEW keyframe, even if the previous row anchored.
            //       Anchoring on every keyframe would prevent the playhead from
            //       accumulating the user's intended CAM:STP advancement between them.
            // CAM/STP: copy from the previous row so the chosen rate continues by default.
            pm_gate: "",
            pm_cam: getV('.mds-master-row input[id^="mds_pm_cam"]') || "1",
            pm_stp: getV('.mds-master-row input[id^="mds_pm_stp"]') || "1",
            bp1_gate: "",
            bp1_cam: getV('.mds-master-row input[id^="mds_bp1_cam"]') || "1",
            bp1_stp: getV('.mds-master-row input[id^="mds_bp1_stp"]') || "1",
            bp2_gate: "",
            bp2_cam: getV('.mds-master-row input[id^="mds_bp2_cam"]') || "1",
            bp2_stp: getV('.mds-master-row input[id^="mds_bp2_stp"]') || "1"
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
            <!-- JK printer inputs per layer. Each block of three (gate, cam, stp) is gated 
                 by its layer's pm-jk-cell / bp1-jk-cell / bp2-jk-cell class so CSS can 
                 collapse it when the corresponding layer is absent or disabled. -->
            <input type="number" step="1"           id="mds_pm_gate${idx}"  value="${vals.pm_gate}"  class="pm-jk-cell jk-input" placeholder="—">
            <input type="number" step="1" min="1"   id="mds_pm_cam${idx}"   value="${vals.pm_cam}"   class="pm-jk-cell jk-input">
            <input type="number" step="1"           id="mds_pm_stp${idx}"   value="${vals.pm_stp}"   class="pm-jk-cell jk-input">
            <input type="number" step="1"           id="mds_bp1_gate${idx}" value="${vals.bp1_gate}" class="bp1-jk-cell jk-input bp1-input" placeholder="—">
            <input type="number" step="1" min="1"   id="mds_bp1_cam${idx}"  value="${vals.bp1_cam}"  class="bp1-jk-cell jk-input bp1-input">
            <input type="number" step="1"           id="mds_bp1_stp${idx}"  value="${vals.bp1_stp}"  class="bp1-jk-cell jk-input bp1-input">
            <input type="number" step="1"           id="mds_bp2_gate${idx}" value="${vals.bp2_gate}" class="bp2-jk-cell jk-input bp2-input" placeholder="—">
            <input type="number" step="1" min="1"   id="mds_bp2_cam${idx}"  value="${vals.bp2_cam}"  class="bp2-jk-cell jk-input bp2-input">
            <input type="number" step="1"           id="mds_bp2_stp${idx}"  value="${vals.bp2_stp}"  class="bp2-jk-cell jk-input bp2-input">
            <input id="mds_p${idx}"     value="${vals.p}"     class="pm-spatial-cell">
            <input id="mds_r${idx}"     value="${vals.r}"     class="pm-spatial-cell">
            <input id="mds_bp1_p${idx}" value="${vals.bp1_p}" class="bp1-spatial-cell bp1-input">
            <input id="mds_bp1_r${idx}" value="${vals.bp1_r}" class="bp1-spatial-cell bp1-input">
            <input id="mds_bp2_p${idx}" value="${vals.bp2_p}" class="bp2-spatial-cell bp2-input">
            <input id="mds_bp2_r${idx}" value="${vals.bp2_r}" class="bp2-spatial-cell bp2-input">
            <input type="color" id="mds_c${idx}" value="${vals.c}" onchange="updateHex(this, 'mds_c${idx}_hex')">
            <input type="hidden" id="mds_c${idx}_hex" value="${vals.c}">
            <input type="color" id="mds_cg${idx}" value="${vals.cg}" onchange="updateHex(this, 'mds_cg${idx}_hex')">
            <input type="hidden" id="mds_cg${idx}_hex" value="${vals.cg}">
            <input type="number" step="0.1" id="mds_s${idx}" value="${vals.exp}">
            <button class="del-btn" onclick="this.parentElement.parentElement.remove(); reindexMDS();">X</button>
        </div>
        <div class="sheet-row mds-smear-row">
            <div></div><div></div><div></div><div></div>
            <div class="node-tag smear">STRT</div>
            <div class="pm-jk-cell"></div>
            <div class="pm-jk-cell"></div>
            <div class="pm-jk-cell"></div>
            <div class="bp1-jk-cell"></div>
            <div class="bp1-jk-cell"></div>
            <div class="bp1-jk-cell"></div>
            <div class="bp2-jk-cell"></div>
            <div class="bp2-jk-cell"></div>
            <div class="bp2-jk-cell"></div>
            <input id="mds_start_p${idx}"     value="${vals.sp}"     class="pm-spatial-cell">
            <input id="mds_start_r${idx}"     value="${vals.sr}"     class="pm-spatial-cell">
            <input id="mds_start_bp1_p${idx}" value="${vals.sbp1_p}" class="bp1-spatial-cell bp1-input">
            <input id="mds_start_bp1_r${idx}" value="${vals.sbp1_r}" class="bp1-spatial-cell bp1-input">
            <input id="mds_start_bp2_p${idx}" value="${vals.sbp2_p}" class="bp2-spatial-cell bp2-input">
            <input id="mds_start_bp2_r${idx}" value="${vals.sbp2_r}" class="bp2-spatial-cell bp2-input">
            <input type="color" id="mds_start_c${idx}" value="${vals.sc}" onchange="updateHex(this, 'mds_start_c${idx}_hex')">
            <input type="hidden" id="mds_start_c${idx}_hex" value="${vals.sc}">
            <div></div>
            <div></div>
            <div></div>
        </div>
        <div class="sheet-row mds-smear-row">
            <div></div><div></div><div></div><div></div>
            <div class="node-tag smear">STOP</div>
            <div class="pm-jk-cell"></div>
            <div class="pm-jk-cell"></div>
            <div class="pm-jk-cell"></div>
            <div class="bp1-jk-cell"></div>
            <div class="bp1-jk-cell"></div>
            <div class="bp1-jk-cell"></div>
            <div class="bp2-jk-cell"></div>
            <div class="bp2-jk-cell"></div>
            <div class="bp2-jk-cell"></div>
            <input id="mds_stop_p${idx}"     value="${vals.ep}"     class="pm-spatial-cell">
            <input id="mds_stop_r${idx}"     value="${vals.er}"     class="pm-spatial-cell">
            <input id="mds_stop_bp1_p${idx}" value="${vals.ebp1_p}" class="bp1-spatial-cell bp1-input">
            <input id="mds_stop_bp1_r${idx}" value="${vals.ebp1_r}" class="bp1-spatial-cell bp1-input">
            <input id="mds_stop_bp2_p${idx}" value="${vals.ebp2_p}" class="bp2-spatial-cell bp2-input">
            <input id="mds_stop_bp2_r${idx}" value="${vals.ebp2_r}" class="bp2-spatial-cell bp2-input">
            <input type="color" id="mds_stop_c${idx}" value="${vals.ec}" onchange="updateHex(this, 'mds_stop_c${idx}_hex')">
            <input type="hidden" id="mds_stop_c${idx}_hex" value="${vals.ec}">
            <div></div>
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

function addSSSKeyframe() {
    sssMasterCount++; 
    const idx = sssMasterCount;

    const existingRows = document.querySelectorAll('.sss-master-row');
    const lastRow = existingRows.length > 0 ? existingRows[existingRows.length - 1] : null;

    // SSS Base Defaults (Includes SD and PH; the smear-by-shutter knobs SSS
    // adds on top of the shared spatial/light/JK parameters).
    let vals = {
        m: "S", crn: false,
        p: "0,0,-1.0", r: "0,0,0",
        bp1_p: "0,0,-1.0", bp1_r: "0,0,0",
        bp2_p: "0,0,-1.0", bp2_r: "0,0,0",
        c: "#ffffff", cg: "#ffffff", exp: "1.0", sd: "1.0", ph: "0.5", f: 1,
        // JK Printer defaults: empty gate (no anchor, just continue), 1:1 playback rate
        pm_gate: "",  pm_cam: "1",  pm_stp: "1",
        bp1_gate: "", bp1_cam: "1", bp1_stp: "1",
        bp2_gate: "", bp2_cam: "1", bp2_stp: "1"
    };

    if (lastRow) {
        const getV = (sel) => { const el = lastRow.querySelector(sel); return el ? el.value : ""; };
        const getC = (sel) => { const el = lastRow.querySelector(sel); return el ? el.checked : false; };
        
        // Class-hook scrapes (.bp1-input / .bp2-input) for the same reasons as 
        // the MDS scraper above: clearer intent and future-proof against an 
        // eventual BP3 layer.
        // 
        // The :not([id^="sss_pm_"]):not([id^="sss_bp1_"]):not([id^="sss_bp2_"]) 
        // chain on the PM p/r scrapes is necessary because input[id^="sss_p"] 
        // would otherwise match sss_pm_gate / sss_pm_cam / sss_pm_stp - "sss_p" 
        // is also a prefix of "sss_pm". (This was a latent bug in the original 
        // single-BP code that was fixed in passing during the rename.)
        vals = {
            m: getV('select[id^="sss_m"]'),
            crn: getC('input[type="checkbox"]'),
            p: getV('input[id^="sss_p"]:not([id^="sss_pm_"]):not([id^="sss_bp1_"]):not([id^="sss_bp2_"])'),
            r: getV('input[id^="sss_r"]:not([id^="sss_bp1_"]):not([id^="sss_bp2_"])'),
            bp1_p: getV('.bp1-input[id^="sss_bp1_p"]'),
            bp1_r: getV('.bp1-input[id^="sss_bp1_r"]'),
            bp2_p: getV('.bp2-input[id^="sss_bp2_p"]'),
            bp2_r: getV('.bp2-input[id^="sss_bp2_r"]'),
            c: getV('input[id^="sss_c"][id$="_hex"]:not([id*="cg"])'),
            cg: getV('input[id^="sss_cg"][id$="_hex"]'),
            exp: getV('input[id^="sss_exp"]'),
            sd: getV('input[id^="sss_sd"]'),
            ph: getV('input[id^="sss_ph"]'),
            f: parseInt(getV('input[id^="sss_f"]')) + 1,
            // JK Printer scrape from previous row.
            // GATE: always blank on a NEW keyframe, even if the previous row anchored.
            //       Anchoring on every keyframe would prevent the playhead from
            //       accumulating the user's intended CAM:STP advancement between them.
            // CAM/STP: copy from the previous row so the chosen rate continues by default.
            pm_gate: "",
            pm_cam: getV('input[id^="sss_pm_cam"]') || "1",
            pm_stp: getV('input[id^="sss_pm_stp"]') || "1",
            bp1_gate: "",
            bp1_cam: getV('input[id^="sss_bp1_cam"]') || "1",
            bp1_stp: getV('input[id^="sss_bp1_stp"]') || "1",
            bp2_gate: "",
            bp2_cam: getV('input[id^="sss_bp2_cam"]') || "1",
            bp2_stp: getV('input[id^="sss_bp2_stp"]') || "1"
        };
    }

    const body = document.getElementById('sss_sheet_body');
    const row = document.createElement('div');
    row.className = 'sheet-row sss-master-row';
    
   
    row.innerHTML = `
        <div class="row-num">?</div>
        <input type="number" id="sss_f${idx}" value="${vals.f}">
        <select id="sss_m${idx}"><option value="S" ${vals.m==='S'?'selected':''}>S</option><option value="L" ${vals.m==='L'?'selected':''}>L</option></select>
        <input type="checkbox" id="sss_crn${idx}" ${vals.crn?'checked':''}>
        <input type="number" step="1"           id="sss_pm_gate${idx}"  value="${vals.pm_gate}"  class="pm-jk-cell jk-input" placeholder="—">
        <input type="number" step="1" min="1"   id="sss_pm_cam${idx}"   value="${vals.pm_cam}"   class="pm-jk-cell jk-input">
        <input type="number" step="1"           id="sss_pm_stp${idx}"   value="${vals.pm_stp}"   class="pm-jk-cell jk-input">
        <input type="number" step="1"           id="sss_bp1_gate${idx}" value="${vals.bp1_gate}" class="bp1-jk-cell jk-input bp1-input" placeholder="—">
        <input type="number" step="1" min="1"   id="sss_bp1_cam${idx}"  value="${vals.bp1_cam}"  class="bp1-jk-cell jk-input bp1-input">
        <input type="number" step="1"           id="sss_bp1_stp${idx}"  value="${vals.bp1_stp}"  class="bp1-jk-cell jk-input bp1-input">
        <input type="number" step="1"           id="sss_bp2_gate${idx}" value="${vals.bp2_gate}" class="bp2-jk-cell jk-input bp2-input" placeholder="—">
        <input type="number" step="1" min="1"   id="sss_bp2_cam${idx}"  value="${vals.bp2_cam}"  class="bp2-jk-cell jk-input bp2-input">
        <input type="number" step="1"           id="sss_bp2_stp${idx}"  value="${vals.bp2_stp}"  class="bp2-jk-cell jk-input bp2-input">
        <input id="sss_p${idx}"     value="${vals.p}"     class="pm-spatial-cell">
        <input id="sss_r${idx}"     value="${vals.r}"     class="pm-spatial-cell">
        <input id="sss_bp1_p${idx}" value="${vals.bp1_p}" class="bp1-spatial-cell bp1-input">
        <input id="sss_bp1_r${idx}" value="${vals.bp1_r}" class="bp1-spatial-cell bp1-input">
        <input id="sss_bp2_p${idx}" value="${vals.bp2_p}" class="bp2-spatial-cell bp2-input">
        <input id="sss_bp2_r${idx}" value="${vals.bp2_r}" class="bp2-spatial-cell bp2-input">
        <input type="color" id="sss_c${idx}" value="${vals.c}" onchange="updateHex(this, 'sss_c${idx}_hex')">
        <input type="hidden" id="sss_c${idx}_hex" value="${vals.c}">
        <input type="color" id="sss_cg${idx}" value="${vals.cg}" onchange="updateHex(this, 'sss_cg${idx}_hex')">
        <input type="hidden" id="sss_cg${idx}_hex" value="${vals.cg}">
        <input type="number" step="0.1" id="sss_exp${idx}" value="${vals.exp}">
        <input type="number" step="0.1" id="sss_sd${idx}" value="${vals.sd}">
        <input type="number" step="0.1" id="sss_ph${idx}" value="${vals.ph}">
        <button class="del-btn" onclick="this.parentElement.remove(); reindexSSS();">X</button>
    `;
    body.appendChild(row);
    reindexSSS();
}

// Toggle column-visibility classes on the SSS and MDS sheet wrappers.
//
// Each layer (PM, BP1, BP2) has two independent reasons its columns might be
// hidden, so the CSS expands the grid template based on TWO orthogonal classes
// per layer:
//
//   .has-{layer}-video    - The layer holds a video sequence (>1 source frame),
//                           so the JK printer GATE/CAM/STP columns are useful.
//                           A single-frame still doesn't benefit from these knobs.
//
//   .layer-disabled-{layer} - The layer's eye toggle is closed. Both the JK 
//                             columns AND the POS/ROT columns collapse because
//                             a disabled layer can't be animated either.
//
// The two classes interact in CSS via :has() selectors - see style.css.
//
// Called from:
//   1. The 1Hz /status poll loop (so server-side frame-count changes are 
//      reflected within a second of an upload finishing).
//   2. Each eye-toggle's onchange handler (so the columns react immediately, 
//      not on the next poll tick - DOMContentLoaded wires these up below).
function applyLayerVisibility(pmFrames, bp1Frames, bp2Frames,
                              pmVisible, bp1Visible, bp2Visible) {
    const sheets = document.querySelectorAll('.sss-sheet, .mds-sheet');
    sheets.forEach(sheet => {
        // Video presence drives the JK column visibility. >1 because a single 
        // TIFF (still image) doesn't benefit from JK printer controls since 
        // GATE clamps to frame 0 anyway.
        sheet.classList.toggle('has-pm-video',  pmFrames  > 1);
        sheet.classList.toggle('has-bp1-video', bp1Frames > 1);
        sheet.classList.toggle('has-bp2-video', bp2Frames > 1);
        // Eye-toggle state drives the full per-layer column hiding (JK 
        // columns + POS/ROT columns for that layer).
        sheet.classList.toggle('layer-disabled-pm',  !pmVisible);
        sheet.classList.toggle('layer-disabled-bp1', !bp1Visible);
        sheet.classList.toggle('layer-disabled-bp2', !bp2Visible);
    });
}

// Reads current eye-toggle states from the three layer-visibility checkboxes
// and re-applies the visibility classes. Cached frame counts come from the 
// last /status response so we don't need to re-fetch just to update on a 
// toggle change.
//
// _layerVisibilityFrames: last-known frame counts from /status. Updated by 
// the poll loop. Defaults to all-zero so a toggle event that fires before 
// the first poll doesn't crash.
let _layerVisibilityFrames = { pm: 0, bp1: 0, bp2: 0 };
function refreshLayerVisibility() {
    const pmEye  = document.getElementById('pm_visible');
    const bp1Eye = document.getElementById('bp1_visible');
    const bp2Eye = document.getElementById('bp2_visible');
    applyLayerVisibility(
        _layerVisibilityFrames.pm,
        _layerVisibilityFrames.bp1,
        _layerVisibilityFrames.bp2,
        pmEye  ? pmEye.checked  : true,
        bp1Eye ? bp1Eye.checked : true,
        bp2Eye ? bp2Eye.checked : true
    );
}

function reindexSSS() {
    document.querySelectorAll('.sss-master-row').forEach((row, i) => {
        row.querySelector('.row-num').innerText = i + 1;
    });
}

function updateHex(el, targetId) { document.getElementById(targetId).value = el.value; triggerSync(); }

setInterval(async () => {
    try {
        const r = await fetch('/status');
        const st = await r.json();
        
        if (isFirstLoad && st.params && Object.keys(st.params).length > 0) {

            // --- Auto-reconstruct keyframe rows from saved data ---
            let maxMDS = 0;
            let maxSSS = 0;

            // 1. Scan the imported parameters to find the highest keyframe index
            for (const key of Object.keys(st.params)) {
                if (key.startsWith('mds_f')) {
                    const idx = parseInt(key.replace('mds_f', ''));
                    if (idx > maxMDS) maxMDS = idx;
                }
                if (key.startsWith('sss_f')) {
                    const idx = parseInt(key.replace('sss_f', ''));
                    if (idx > maxSSS) maxSSS = idx;
                }
            }

            // 2. Clear out any existing rows to prevent duplicates
            document.getElementById('mds_sheet_body').innerHTML = '';
            document.getElementById('sss_sheet_body').innerHTML = '';
            mdsMasterCount = 0;
            sssMasterCount = 0;

            // 3. Dynamically build the exact number of empty HTML rows needed
            for (let i = 0; i < maxMDS; i++) addMDSKeyframe();
            for (let i = 0; i < maxSSS; i++) addSSSKeyframe();

            // 4. Now that the input fields exist, hydrate them with the saved values
            for (const [k, v] of Object.entries(st.params)) {
                const el = document.getElementById(k);
                // Guard: Do not attempt to write values to file inputs
                if (el && el.type !== 'file') {
                    if (el.type === 'checkbox') el.checked = (v === true || v === 'true');
                    else el.value = v;
                }
            }

            // Read the mode that was just injected from the server parameters
            const loadedMode = document.getElementById('smear_mode');
            if (loadedMode) {
                // Update the global JS state to match the server state
                currentMode = loadedMode.value; 
                // Force the DOM to display the correct sheet corresponding to the state
                toggleSheetVisibility();
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
        // Drive layer column visibility from server-reported source frame counts
        // and the current eye-toggle states. Cache the frame counts so eye-toggle 
        // change events can also call refreshLayerVisibility() without needing to 
        // re-fetch /status.
        _layerVisibilityFrames.pm  = st.pm_frames  || 0;
        _layerVisibilityFrames.bp1 = st.bp1_frames || 0;
        _layerVisibilityFrames.bp2 = st.bp2_frames || 0;
        refreshLayerVisibility();
    } catch(e) { console.error("Poll Error:", e); }
}, 1000);

// --- HTML5 Drag and Drop Fallback ---
document.addEventListener('DOMContentLoaded', () => {
    const setupDropZone = (elementId, inputId, textId, endpoint) => {
        const dropZone = document.getElementById(elementId);
        if (!dropZone) return;

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.style.border = "2px dashed #0cf";
        });

        dropZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropZone.style.border = "";
        });

        dropZone.addEventListener('drop', async (e) => {
            e.preventDefault();
            dropZone.style.border = "";
            
            if (e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                const formData = new FormData();
                formData.append('file', file);
                
                try {
                    const resp = await fetch(endpoint, {method: 'POST', body: formData});
                    const data = await resp.json();
                    document.getElementById(textId).value = data.filename;
                    await triggerSync(); 
                } catch(err) { console.error("Drag-Drop Upload failed", err); }
            }
        });
    };

    // Bind drop zones to the text input fields showing the active image
    setupDropZone('image',          'file_input',     'image',          '/upload_target');
    setupDropZone('bipack1_image',  'bp1_file_input', 'bipack1_image',  '/upload_proj_bipack1');
    setupDropZone('bipack2_image',  'bp2_file_input', 'bipack2_image',  '/upload_proj_bipack2');
    
    // Wire eye-toggle change events so column visibility reacts immediately. 
    // Without this, toggling a layer's eye would only update the columns on 
    // the next /status poll (up to 1s lag), which feels broken.
    // refreshLayerVisibility() reads the current eye states and reuses the 
    // cached frame counts from the last poll.
    ['pm_visible', 'bp1_visible', 'bp2_visible'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', refreshLayerVisibility);
    });
});

/* * Dispatches the dark frame measurement task to the engine and polls the
 * server status. Once the engine stops, it retrieves the generated preview
 * image and the measured noise value.
 */
async function triggerMeasurement() {
    const resTxt = document.getElementById('noise_result_txt');
    resTxt.innerText = "WAIT...";

    // 1. Dispatch the job to the engine using the existing parameter collector
    await fetch('/measure_noise', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(collectParams())

    });

    // 2. Poll the server status endpoint every 1000ms
    let attempts = 0;
    const pollInterval = setInterval(async () => {
        attempts++;
        try {
            const r = await fetch('/status');
            const st = await r.json();

            // Check if engine_running has flipped back to false
            if (st.status !== 'rendering' && attempts > 2) {
                clearInterval(pollInterval);
                
                // Add a 500ms delay to allow the OS file buffer to write to disk
                setTimeout(async () => {
                    // Force the preview image to refresh
                    document.getElementById('probe_img').src = '/static/probe_live.jpg?t=' + Date.now();
                    
                    // Fetch the generated JSON file
                    const nRes = await fetch('/static/noise_data.json?t=' + Date.now());
                    if (nRes.ok) {
                        const data = await nRes.json();
                        const measured = data.measured_noise.toFixed(6);

                        // Render as a clickable element. We use a span with a class
                        // rather than a <a> tag so it stays inline with the rest of 
                        // the result text and doesn't get default link styling that
                        // would clash with the rest of the UI
                        resTxt.innerHTML = `<span class="noise-clickable" title="Click to copy into Noise Crusher">${measured}</span>`;

                        // Wire up the click. We attach the listener AFTER setting innerHTML
                        // because the span doesn't exist until innerHTML has been parsed.
                        resTxt.querySelector('.noise-clickable').addEventListener('click', () => {
                            const target = document.getElementById('black_clip');
                            target.value = measured;
                            // Dispatch a change event so any sync logic listening to the
                            // input (like the auto-save / job-state tracker) picks it up
                            target.dispatchEvent(new Event('chagne', { bubbles: true}));
                        });
                    } else {
                        resTxt.innerText = "ERR";
                    }
                }, 500);
            }           
        } catch (e) {
            console.error("Polling error:", e);
        }
    }, 1000);
}

/* Polls the server for any validation warnings the engine emitted during 
 * the last exposure. If found, displays it in red next to the offending 
 * input and force-updates the input value to match what the engine actually 
 * used. The server consumes the warning on read, so this only fires once 
 * per actual problem.
 */
async function checkValidationWarnings() {
    try {
        const r = await fetch('/check_validation_warning');
        const data = await r.json();
        if (data.warning) {
            const w = data.warning;
            const warnEl = document.getElementById(`${w.field}_warning`);
            const inputEl = document.getElementById(w.field);
            
            if (warnEl) {
                warnEl.innerText = `⚠ ${w.message}`;
                // Auto-clear after 15s so it doesn't linger forever
                setTimeout(() => { warnEl.innerText = ''; }, 15000);
            }
            
            if (inputEl && w.forced_value !== undefined) {
                inputEl.value = w.forced_value;
                inputEl.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
    } catch (e) {
        console.error("Validation check failed:", e);
    }
}

// Poll every 2 seconds — cheap, and only acts when there's actually a warning.
setInterval(checkValidationWarnings, 2000);

async function triggerHotPixelMap() {
    // 1. The reality check prompt!
    if (!confirm("IMPORTANT: Please put the lens cap on the camera!\n\nThis will take a dark frame matching your current Probe Frame's exposuresetting to map defective pixels.\n\nClick OK when the lens cap is fully seated.")){
        return;
    }

    const resTxt = document.getElementById('hp_result_txt');
    resTxt.innerText = "MAPPING...";

    // 2. Dispatch to the engine
    await fetch ('/map_hot_pixels', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(collectParams())
    });

    // 3. Poll for completion
    let attempts = 0;
    const pollInterval = setInterval(async () => {
        attempts++;
        try {
            const r = await fetch('/status');
            const st = await r.json();
            
            if (st.status !== 'rendering' && attempts > 2) {
                clearInterval(pollInterval);
                
                // Allow OS disk buffer flush
                setTimeout(async () => {
                    const nRes = await fetch('/static/hot_pixels.json?t=' + Date.now());
                    if (nRes.ok) {
                        const data = await nRes.json();
                        if (data.error) {
                            resTxt.innerText = "ERR: CAP OFF";
                            resTxt.style.color = "#f44";
                        } else {
                            resTxt.innerText = data.pixels.length + " FIXED";
                            resTxt.style.color = "#0cf";
                        }
                    } else {
                        resTxt.innerText = "FAILED";
                    }
                }, 500);
            }
        } catch (e) {
            console.error("Polling error:", e);
        }
    }, 1000);
}

async function nukeHotPixels() {
    if (confirm("Delete the hot pixel map? Defective pixels will no longer be suppressed in future exposures.")) {
        await fetch('/nuke_hot_pixels', {method: 'POST'});
        document.getElementById('hp_result_txt').innerText = "CLEARED";
        document.getElementById('hp_result_txt').style.color = "#f44"; // Turn red to show it's disabled
    }
}

/* Job Management: Export
Triggers a browser download of the current_job.json file.
*/
async function exportJob() {
    // 1. Push the current DOM state to the server first
    await fetch('/save_job', {
        method: 'post',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(collectParams())
    });

    // 2. Trigger the browser download of the newly updated file
    window.location.href = '/export_job';
}

/**
 * Kicks off a background ffmpeg ProRes 4444 encode from the current CamMag,
 * polls until complete, then triggers a browser download of the .mov file.
 */
async function renderProRes() {
    const btn = document.querySelector('.prores-btn');
    if (btn) { btn.innerText = 'RENDERING...'; btn.disabled = true; }

    try {
        // 1. Start the background render, passing current fps + PAR from the UI.
        // PAR fields are read from the new anamorphic section and forwarded so
        // ffmpeg can write the 'pasp' atom into the MOV. Without these, the
        // editor would have to manually punch the PAR in on import.
        const cp = collectParams();
        const startResp = await fetch('/render_prores', {
            method: 'POST', 
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                fps: cp.fps || 24,
                par_x: cp.par_x || 1.0,
                par_y: cp.par_y || 1.0
            })
        });
        const startData = await startResp.json();

        if (!startResp.ok) {
            alert(`ProRes render failed to start: ${startData.error || startData.status}`);
            if (btn) { btn.innerText = 'RENDER PRORES'; btn.disabled = false; }
            return;
        }

        // 2. Poll /prores_status until ffmpeg finishes
        const pollInterval = setInterval(async () => {
            try {
                const r = await fetch('/prores_status');
                const st = await r.json();

                if (st.status === 'done') {
                    clearInterval(pollInterval);
                    if (btn) { btn.innerText = 'RENDER PRORES'; btn.disabled = false; }
                    // 3. Trigger download
                    window.location.href = `/prores/${st.filename}`; 

                } else if (st.status === 'error') {
                    clearInterval(pollInterval);
                    if(btn) { btn.innerText = 'RENDER PRORES'; btn.disabled = false; }
                    alert(`ProRes render Failed (ffmpeg exit code: ${st.code})`);
                }
                // 'rendering' -> keep polling
            } catch (e) {
                console.error("ProRes poll error:", e);
            }
        }, 2000); // Poll every 2s - no need to hammer it

    } catch (e) {
        console.error("ProRes render error:", e);
        if (btn) { btn.innerText = 'RENDER PRORES'; btn.disabled = false; }
        alert("A network error occurred starting the ProRes render.");
    }
}

/* Job Management: Import
Uploads a JSON file, replaces current_job.json, and handles version warnings.
*/
async function importJob(input) {
    if (!input.files || input.files.length === 0) return;

    const file = input.files[0];
    const formData = new FormData();
    formData.append('file', file);

    try {
        const resp = await fetch('/import_job', { method: 'POST', body: formData});
        const data = await resp.json();

        if (data.status === 'ok') {
            if (data.warning) {
                alert(`COMPATIBILITY WARNING\n\n${data.warning}\n\nSome variables may have changed names or been removed. Verify your keyframes before executing.`);
            }

            // Clear the input so the same file can be selected again if needed
            input.value = "";

            // Force a full page reload to hydrate the DOM with the new JSON data
            window.location.reload();
        } else {
            alert(`Import failed: ${data.error}`);
            input.value = "";
        }
    } catch (err) {
        console.error("Job import error:", err);
        alert("A network error occurred during import.");
        input.value = "";
    }
}