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
let dreMasterCount = 0;
// BRK keyframe counter. Same role as dreMasterCount / sssMasterCount:
// incremented on add, used as the suffix in input IDs (brk_f1, brk_f2...).
// Not decremented on delete - if a user deletes row 3 of 5, the
// remaining rows keep IDs 1,2,4,5 and the next add becomes 6. That's
// fine because IDs only need uniqueness, not contiguity. Rehydration
// from saved jobs scans for highest-numbered ID and rebuilds enough
// rows to cover it.
let brkMasterCount = 0;
let isFirstLoad = true;
let isEngineRunning = false;
let currentMode = 'SSS'; // <-- tracks the current active mode and sets the initial default.

// Initialize the dropdown listener when the DOM loads
document.addEventListener('DOMContentLoaded', () => {
    const modeSelect = document.getElementById('smear_mode');
    if (modeSelect) {
        currentMode = modeSelect.value;
        toggleSheetVisibility();
        
        // MODE SWITCH HANDLER
        //
        // Non-destructive: switching modes only updates which sheet is
        // visible and which mode the engine will dispatch on. The other
        // modes' keyframe rows stay in the DOM (hidden via wrapper
        // display:none) and their values stay in current_job.json
        // keyed by their mode prefix (mds_*, sss_*, dre_*, brk_*).
        // So switching SSS -> MDS -> SSS is round-trip-safe: your SSS
        // keyframes are still there when you come back.
        //
        // The earlier version of this handler popped a confirm() and
        // wiped sheet bodies on OK. Browsers suppress repeated confirms
        // on the same page after the first one, which made the dropdown
        // un-switchable (the suppressed confirm returns false, the
        // cancel branch fired, and 'this.value = currentMode' snapped
        // the dropdown back). The destructive model was also wrong on
        // its own terms - there's no reason mode switching needs to be
        // a one-way operation. Nuke Job already exists for the
        // "I want a clean slate" use case.
        modeSelect.addEventListener('change', function(e) {
            currentMode = this.value;
            toggleSheetVisibility();
            triggerSync();
        });
    }
});

function toggleSheetVisibility() {
    const mdsWrap = document.getElementById('mds_wrapper');
    const sssWrap = document.getElementById('sss_wrapper');
    const dreWrap = document.getElementById('dre_wrapper');
    const brkWrap = document.getElementById('brk_wrapper');
    // BRK MODE BODY CLASS
    //
    // Drives the visibility of any element with the
    // .brk-constants class (currently bracket_count and
    // bracket_stops in the Hardware Constants column). See
    // static/style.css for the matching rule. Done via a body
    // class rather than per-element classList toggles so that
    // future BRK-only controls added anywhere in the DOM are
    // covered automatically - just add .brk-constants to them
    // and they're picked up for free.
    // Body classes drive CSS-only visibility for mode-scoped controls
    // that live in the DOM unconditionally (so collectParams() always
    // captures their values) but should only be VISIBLE in their mode.
    // Currently: .brk-constants and .brk-probe-controls key off
    // body.brk-mode; .dre-probe-controls keys off body.dre-mode.
    // See static/style.css for the matching rules.
    document.body.classList.toggle('brk-mode', currentMode === 'BRK');
    document.body.classList.toggle('dre-mode', currentMode === 'DRE');
    if (mdsWrap) mdsWrap.style.display = (currentMode === 'MDS') ? 'block' : 'none';
    if (sssWrap) sssWrap.style.display = (currentMode === 'SSS') ? 'block' : 'none';
    if (dreWrap) dreWrap.style.display = (currentMode === 'DRE') ? 'block' : 'none';
    if (brkWrap) brkWrap.style.display = (currentMode === 'BRK') ? 'block' : 'none';
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
    // Wording updated for v0.12 - the Cam Mag now holds either
    // exposed latents (from Execute) OR an ingested video reel
    // (from the new Cam Mag UPLOAD), so the confirm text shouldn't
    // imply one or the other.
    if (confirm("This deletes everything in the Cam Mag (loaded reels or exposed latents). Are you sure? This cannot be undone.")){
        // Also clear the on-screen reel name immediately so the UI
        // doesn't show a phantom filename until the next /status poll.
        // The /nuke_mag route clears the server-side label too, so the
        // next poll won't repopulate it.
        const el = document.getElementById('cam_mag_filename');
        if (el) el.value = '';
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

    // 2. Read the current PAR values from the GUI. We pull these at click time
    //    rather than relying on a cached job state so the FIT/FILL FOV buttons
    //    always reflect what the user is *currently* about to render with.
    //    If a user types 1.6 into par_x and immediately hits FIT FOV, the math
    //    needs to know about that 1.6 without a triggerSync round-trip first.
    //    Defaults to 1.0 mirror the Python-side defaults so any element-missing
    //    edge case (e.g. a future GUI variant without the PAR fields) still
    //    cleanly reproduces unsqueezed behavior.
    const parX = parseFloat(document.getElementById('par_x')?.value) || 1.0;
    const parY = parseFloat(document.getElementById('par_y')?.value) || 1.0;

    // 3. Ping the Python backend to calculate the exact static scale
    try {
        const fitReq = await fetch('/calculate_fit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                fov: fov,
                ref_z: zDist,
                aspect_ratio: imgAspect,
                mode: mode,
                par_x: parX,
                par_y: parY
            })
        });
        const fitData = await fitReq.json();

        if (fitData.status === 'ok') {
            document.getElementById(scaleId).value = fitData.scale.toFixed(4);
            console.log(`[VOP UI] ${magType.toUpperCase()} Scale ${mode.toUpperCase()} to: ${fitData.scale.toFixed(4)} (PAR ${parX}:${parY})`);
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

// addBRKKeyframe adds one row to the BRK exposure sheet.
//
// Field naming convention mirrors SSS/MDS where the column maps to
// an existing concept (POS, ROT, GATE, CAM, STP, gels) so the
// engine's spatial-transform and JK-printer parsing can reuse the
// existing code paths once the engine-side BRK mode branch is in
// place (slice 12). The fields that DON'T map to existing concepts
// (per-job bracket_count and bracket_stops) are not per-keyframe;
// those land in the Hardware Constants section in slice 9.
//
// Fields per keyframe:
//   brk_f<n>                   frame number
//   brk_pm_gate<n>             PM JK gate frame number
//   brk_pm_cam<n>              PM JK camera index
//   brk_pm_stp<n>              PM JK step
//   brk_bp1_gate<n>            BP1 JK gate frame
//   brk_bp1_cam<n>             BP1 JK camera index
//   brk_bp1_stp<n>             BP1 JK step
//   brk_bp2_gate<n>            BP2 JK gate frame
//   brk_bp2_cam<n>             BP2 JK camera index
//   brk_bp2_stp<n>             BP2 JK step
//   brk_p<n>                   PM position (X,Y,Z as "x,y,z" string)
//                              (Naming matches SSS/MDS/DRE: PM is
//                              the implicit default layer, so its
//                              spatial fields drop the pm_ prefix.
//                              Bipack layers get explicit bp1_ /
//                              bp2_ prefixes below.)
//   brk_r<n>                   PM rotation (Pitch,Roll,Yaw)
//   brk_bp1_pos<n>             BP1 position
//   brk_bp1_rot<n>             BP1 rotation
//   brk_bp2_pos<n>             BP2 position
//   brk_bp2_rot<n>             BP2 rotation
//   brk_c<n>_hex               projector gel color
//   brk_cg<n>_hex              camera gel color
//
// The universal collectParams() walks all <input>/<select> elements
// and uses their IDs as JSON keys, so any new BRK field added here
// is automatically included in the saved job state - no separate
// serializer to maintain.
function addBRKKeyframe() {
    brkMasterCount++;
    const idx = brkMasterCount;

    // Suggest a frame number one ahead of the last keyframe. Matches
    // the SSS/MDS/DRE adders' affordance - users almost always want
    // sequential frames.
    const existingRows = document.querySelectorAll('.brk-keyframe-row');
    let suggestedFrame = 1;
    if (existingRows.length > 0) {
        const lastFrameInput = existingRows[existingRows.length - 1]
            .querySelector('input[id^="brk_f"]');
        if (lastFrameInput) {
            suggestedFrame = (parseInt(lastFrameInput.value) || 0) + 1;
        }
    }

    const row = document.createElement('div');
    row.className = 'sheet-row brk-keyframe-row';
    row.innerHTML = `
        <div>${idx}</div>
        <div><input type="number" id="brk_f${idx}" value="${suggestedFrame}" min="1"></div>

        <div class="pm-jk-cell"><input type="number" class="jk-input" id="brk_pm_gate${idx}" value="1" min="1"></div>
        <div class="pm-jk-cell"><input type="number" class="jk-input" id="brk_pm_cam${idx}" value="1" min="1"></div>
        <div class="pm-jk-cell"><input type="number" class="jk-input" id="brk_pm_stp${idx}" value="1" min="1"></div>

        <div class="bp1-jk-cell"><input type="number" class="jk-input bp1-input" id="brk_bp1_gate${idx}" value="1" min="1"></div>
        <div class="bp1-jk-cell"><input type="number" class="jk-input bp1-input" id="brk_bp1_cam${idx}" value="1" min="1"></div>
        <div class="bp1-jk-cell"><input type="number" class="jk-input bp1-input" id="brk_bp1_stp${idx}" value="1" min="1"></div>

        <div class="bp2-jk-cell"><input type="number" class="jk-input bp2-input" id="brk_bp2_gate${idx}" value="1" min="1"></div>
        <div class="bp2-jk-cell"><input type="number" class="jk-input bp2-input" id="brk_bp2_cam${idx}" value="1" min="1"></div>
        <div class="bp2-jk-cell"><input type="number" class="jk-input bp2-input" id="brk_bp2_stp${idx}" value="1" min="1"></div>

        <div class="pm-spatial-cell"><input type="text" id="brk_p${idx}" value="0,0,-1.0" placeholder="x,y,z"></div>
        <div class="pm-spatial-cell"><input type="text" id="brk_r${idx}" value="0,0,0" placeholder="p,r,y"></div>

        <div class="bp1-spatial-cell"><input type="text" class="bp1-input" id="brk_bp1_pos${idx}" value="0,0,-1.0" placeholder="x,y,z"></div>
        <div class="bp1-spatial-cell"><input type="text" class="bp1-input" id="brk_bp1_rot${idx}" value="0,0,0" placeholder="p,r,y"></div>

        <div class="bp2-spatial-cell"><input type="text" class="bp2-input" id="brk_bp2_pos${idx}" value="0,0,-1.0" placeholder="x,y,z"></div>
        <div class="bp2-spatial-cell"><input type="text" class="bp2-input" id="brk_bp2_rot${idx}" value="0,0,0" placeholder="p,r,y"></div>

        <div><input type="color" id="brk_c${idx}_hex" value="#ffffff" class="sheet-color-input"></div>
        <div><input type="color" id="brk_cg${idx}_hex" value="#ffffff" class="sheet-color-input"></div>

        <div><button onclick="this.closest('.brk-keyframe-row').remove(); triggerSync();">×</button></div>
    `;

    // Wire every input/select in the new row to triggerSync on change,
    // matching the other adders' behavior so editing feels uniform
    // across modes.
    row.querySelectorAll('input, select').forEach(el => {
        el.addEventListener('change', triggerSync);
    });

    document.getElementById('brk_sheet_body').appendChild(row);
    triggerSync();
}

// addDREKeyframe adds one row to the DRE exposure sheet.
// 
// Field naming convention mirrors SSS (so the interpolator parser 
// can reuse the existing 'exp' track without special-casing): 
//     dre_f<n>        frame number
//     dre_m<n>        interpolation mode (S/L, matches SSS values)
//     dre_exp<n>      exposure seconds
//     dre_steps<n>    DRE step count (DRE-only)
//     dre_c<n>_hex    projector gel color
//     dre_cg<n>_hex   camera gel color
//
// The universal collectParams() walks all <input> and <select> 
// elements and uses their IDs as JSON keys, so there's no separate 
// serializer to update - any new DRE field added here is 
// automatically included in the saved job state.
function addDREKeyframe() {
    dreMasterCount++;
    const idx = dreMasterCount;
    
    // Suggest a frame number one ahead of the last keyframe. This 
    // matches the affordance the SSS adder has - users almost always 
    // want sequential frames and shouldn't have to type them.
    const existingRows = document.querySelectorAll('.dre-keyframe-row');
    let suggestedFrame = 1;
    if (existingRows.length > 0) {
        const lastFrameInput = existingRows[existingRows.length - 1]
            .querySelector('input[id^="dre_f"]');
        if (lastFrameInput) {
            suggestedFrame = (parseInt(lastFrameInput.value) || 0) + 1;
        }
    }
    
    const row = document.createElement('div');
    row.className = 'sheet-row dre-keyframe-row';
    row.innerHTML = `
        <div>${idx}</div>
        <div><input type="number" id="dre_f${idx}" value="${suggestedFrame}" min="1"></div>
        <div>
            <select id="dre_m${idx}">
                <option value="S" selected>S</option>
                <option value="L">L</option>
            </select>
        </div>
        <div><input type="number" id="dre_exp${idx}" value="1.0" step="0.1" min="0.1"></div>        <div><input type="number" id="dre_steps${idx}" value="256" step="1" min="2" max="1024"></div>
        <div><input type="color" id="dre_c${idx}_hex" value="#ffffff"></div>
        <div><input type="color" id="dre_cg${idx}_hex" value="#ffffff"></div>
        <div><button onclick="this.closest('.dre-keyframe-row').remove(); triggerSync();">×</button></div>
    `;
    
    // Wire every input in the new row to trigger a save after edit.
    // Matches the SSS adder's behavior so DRE feels identical to use.
    row.querySelectorAll('input, select').forEach(el => {
        el.addEventListener('change', triggerSync);
    });
    
    document.getElementById('dre_sheet_body').appendChild(row);
    triggerSync();
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

            // 1. Scan the imported parameters to find the highest keyframe index.
            //
            // NOTE: DRE is missing from this scan - pre-existing bug,
            // filed for the niggles cleanup pass. Adding BRK in
            // parallel with MDS/SSS here matches the convention but
            // doesn't fix the DRE gap.
            let maxBRK = 0;
            for (const key of Object.keys(st.params)) {
                if (key.startsWith('mds_f')) {
                    const idx = parseInt(key.replace('mds_f', ''));
                    if (idx > maxMDS) maxMDS = idx;
                }
                if (key.startsWith('sss_f')) {
                    const idx = parseInt(key.replace('sss_f', ''));
                    if (idx > maxSSS) maxSSS = idx;
                }
                // Match brk_f<n> but NOT other brk_* fields. The leading
                // 'brk_f' followed by a digit distinguishes the frame-
                // number field from siblings like brk_pm_pos1.
                if (/^brk_f\d/.test(key)) {
                    const idx = parseInt(key.replace('brk_f', ''));
                    if (idx > maxBRK) maxBRK = idx;
                }
            }

            // 2. Clear out any existing rows to prevent duplicates
            document.getElementById('mds_sheet_body').innerHTML = '';
            document.getElementById('sss_sheet_body').innerHTML = '';
            // Defensive existence check: brk_sheet_body only exists after
            // slice 8 lands. Older clients reloading saved jobs without
            // the new template would crash without this guard.
            const brkBody = document.getElementById('brk_sheet_body');
            if (brkBody) brkBody.innerHTML = '';
            mdsMasterCount = 0;
            sssMasterCount = 0;
            brkMasterCount = 0;

            // 3. Dynamically build the exact number of empty HTML rows needed
            for (let i = 0; i < maxMDS; i++) addMDSKeyframe();
            for (let i = 0; i < maxSSS; i++) addSSSKeyframe();
            // BRK rows only if the template loaded - older saved jobs
            // running on pre-slice-8 clients shouldn't error here.
            if (brkBody) {
                for (let i = 0; i < maxBRK; i++) addBRKKeyframe();
            }

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
                // Calibration page may have a task in flight that
                // just completed. Let its controller refresh its
                // readouts and re-enable its buttons. Safe to call
                // every time - it no-ops when no calibration task
                // was in flight. See slice 7's calibration.onEngineComplete().
                if (typeof calibration !== 'undefined' && calibration.onEngineComplete) {
                    calibration.onEngineComplete();
                }
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
    setupDropZone('image',            'file_input',          'image',            '/upload_target');
    setupDropZone('bipack1_image',    'bp1_file_input',      'bipack1_image',    '/upload_proj_bipack1');
    setupDropZone('bipack2_image',    'bp2_file_input',      'bipack2_image',    '/upload_proj_bipack2');
    setupDropZone('cam_mag_filename', 'cam_mag_file_input',  'cam_mag_filename', '/upload_cam_mag');
    
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
// ====================================================================
// CALIBRATION PAGE CONTROLLER (slice 7)
// ====================================================================
//
// Wires up the Peak White calibration controls to the engine endpoints
// added in slice 5. Hooks into the existing /status polling loop rather
// than running its own timer - see the calibration_store.py module
// docstring for the IPC busy-state convention this relies on.
//
// State machine for a calibration task lifecycle:
//
//   1. User clicks a button (Single Measurement / ACB).
//   2. handler POSTs to the appropriate Flask route, sets
//      calibration.taskInFlight, disables buttons, sets status "Measuring".
//   3. /status polling (in the existing setInterval at line ~678) sees
//      isEngineRunning flip from true to false when the engine deletes
//      COMMAND_FILE.
//   4. The existing polling code calls calibration.onEngineComplete() at
//      that moment (see the integration edit below).
//   5. onEngineComplete() refreshes the preview image, fetches
//      /calibration_state, updates the readouts, re-enables buttons,
//      sets status "Ready". If the just-completed task was ACB and the
//      user checked Include Black Level, it kicks off the follow-up
//      black-floor task by recursing through step 2.
//
// All DOM ids match the IDs declared in templates/sections/calibration.html.
// Buttons are wired by id, not by inline onclick, so the HTML stays free
// of JS coupling and slice 6 part 2 can be re-styled or restructured
// without breaking the JS bindings here.

const calibration = {
    // Tracks whether *this* page's UI has initiated a task.
    // Different from the global isEngineRunning (which fires for ANY
    // engine task, including Main page jobs) - we only want to react
    // to completions of tasks we initiated.
    taskInFlight: null,  // null | 'single' | 'acb' | 'acb_black_followup'

    // When the user clicks ACB with "Include black level" checked, we
    // need to remember to fire the follow-up task. Captured at task
    // start so a mid-run uncheck doesn't cancel it.
    pendingBlackFollowup: false,

    // The exposure time ACB just converged on. Captured from the
    // calibration_state response and passed to the black-floor task.
    lastTPeak: null,

    init() {
        // Attach button handlers. Done via addEventListener rather than
        // inline onclick to keep the HTML JS-free and to make it easy
        // to add additional handlers later (e.g. keyboard shortcuts)
        // without conflict.
        const singleBtn = document.getElementById('cal_single_btn');
        const acbBtn = document.getElementById('cal_acb_btn');
        if (singleBtn) singleBtn.addEventListener('click', () => this.runSingle());
        if (acbBtn) acbBtn.addEventListener('click', () => this.runAcb());

        // Auto White Balance button. Same addEventListener pattern as the
        // others so the HTML stays JS-free.
        const wbBtn = document.getElementById('cal_wb_btn')
        if (wbBtn) wbBtn.addEventListener('click', () => this.runWhiteBalance());

        // Initial population of the Current Calibration readout panel.
        // If the engine has been running and writing to calibration.json,
        // this populates the page on load so the user sees real state
        // instead of "--" placeholders.
        this.refreshState();
    },

    // ----------------------------------------------------------------
    // Helpers used by both task handlers
    // ----------------------------------------------------------------

    setStatus(text) {
        const el = document.getElementById('cal_status_text');
        if (el) el.innerText = text;
    },

    // Gate all calibration buttons (including WB) while anytask runs.
    setButtonsEnabled(enabled) {
        ['cal_single_btn', 'cal_acb_btn', 'cal_wb_btn'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.disabled = !enabled;
        })
    },

    // Pull the WB and gain values from Main page's Hardware Constants.
    // Calibration tasks need these for accurate captures - they reflect
    // the user's current camera setup. If the user hasn't filled them
    // in (fresh page load) we fall back to identity defaults that won't
    // produce sensible results but also won't crash.
    getCurrentHardwareParams() {
        const num = (id, fallback) => {
            const el = document.getElementById(id);
            const v = el ? parseFloat(el.value) : NaN;
            return isNaN(v) ? fallback : v;
        };
        const str = (id, fallback) => {
            const el = document.getElementById(id);
            return (el && el.value) ? el.value : fallback;
        };
        return {
            gain:    num('gain', 1.0),
            awb_r:   num('awb_r', 1.0),
            awb_b:   num('awb_b', 1.0),
            cam_res: str('cam_res', '2028x1520'),
        };
    },

    // ----------------------------------------------------------------
    // Task triggers (POST to slice 5 routes)
    // ----------------------------------------------------------------

    async runSingle() {
        // Single Measurement: capture once at the exposure time the
        // user typed in the cal_exposure_s field. Used for sanity-
        // checking specific exposures by hand without invoking the
        // ACB search.
        const exposure = parseFloat(document.getElementById('cal_exposure_s').value);
        if (isNaN(exposure) || exposure <= 0) {
            this.setStatus('Bad exposure value');
            return;
        }

        this.taskInFlight = 'single';
        this.setButtonsEnabled(false);
        this.setStatus('Measuring...');

        const payload = {
            exposure_s: exposure,
            ...this.getCurrentHardwareParams(),
        };

        try {
            await fetch('/single_peak_measurement', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
            // No await on response body needed - the route returns
            // immediately with {"status": "started"}, and the actual
            // completion is detected via the existing /status polling
            // hook. See onEngineComplete() below.
        } catch (e) {
            // Network errors are rare on a local-network Pi setup but
            // shouldn't strand the UI in a "Measuring" state if they
            // happen. Reset to Ready and the user can retry.
            this.setStatus('Network error');
            this.taskInFlight = null;
            this.setButtonsEnabled(true);
        }
    },

    // WB has its own status line on the page, so route its messages there.
    setWbStatus(text) {
        const el = document.getElementById('cal_wb_status_text');
        if (el) el.innerText = text;
    },

    async runWhiteBalance() {
        // Kick off the semi-auto WB routine. Params come from the cal_wb_*
        // fields: gain/awb/res come from Main page hardware constants. The
        // current Main-page awb_r/awb_b are the loop's STARTING gains - leave
        // them near your working values (e.g. 3.3/1.4) so it refines rather
        // than climbing red out of the floor from scratch.
        const grey      = parseFloat(document.getElementById('cal_wb_grey').value);
        const initial   = parseFloat(document.getElementById('cal_wb_initial').value);
        const elow      = parseFloat(document.getElementById('cal_wb_expo_low').value);
        const ehigh     = parseFloat(document.getElementById('cal_wb_expo_high').value);
        if ([grey, initial, elow, ehigh].some(isNaN)) {
            this.setWbStatus('Bad WB parameters');
            return;
        }

        // 'wb' lets onEngineComplete tell this completion apart from ACB's.
        this.taskInFlight = 'wb';
        this.setButtonsEnabled(false);
        this.setWbStatus('Measuring (WB)...');

        const payload = {
            grey_level: grey,
            initial_exposure_s: initial,
            expo_target_low: elow,
            expo_target_high: ehigh,
            ...this.getCurrentHardwareParams(),
        };

        try {
            await fetch('/measure_white_balance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
        } catch (e) {
            this.setWbStatus('Network error');
            this.taskInFlight = null;
            this.setButtonsEnabled(true); 
        }
    },

    async runAcb() {
        // ACB: auto-converge T_peak via bisection-with-doubling-
        // bootstrap. The four ACB parameters come from the
        // cal_acb_* fields on the page. WB and gain come from the
        // Main page's Hardware Constants.
        const initial = parseFloat(document.getElementById('cal_acb_initial').value);
        const tlow = parseFloat(document.getElementById('cal_acb_target_low').value);
        const thigh = parseFloat(document.getElementById('cal_acb_target_high').value);
        const maxIter = parseInt(document.getElementById('cal_acb_max_iter').value);
        if (isNaN(initial) || isNaN(tlow) || isNaN(thigh) || isNaN(maxIter)) {
            this.setStatus('Bad ACB parameters');
            return;
        }

        // Capture whether to follow up with black-floor at task start.
        // If the user toggles the checkbox while ACB is running, we
        // honour the state they had at click-time, not their later
        // state - keeps the operation predictable.
        this.pendingBlackFollowup = document.getElementById('cal_include_black').checked;

        this.taskInFlight = 'acb';
        this.setButtonsEnabled(false);
        this.setStatus('Measuring (ACB)...');

        const payload = {
            initial_exposure_s: initial,
            target_low: tlow,
            target_high: thigh,
            max_iterations: maxIter,
            ...this.getCurrentHardwareParams(),
        };

        try {
            await fetch('/measure_peak_white', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
        } catch (e) {
            this.setStatus('Network error');
            this.taskInFlight = null;
            this.setButtonsEnabled(true);
        }
    },

    async runAcbBlackFollowup() {
        // Called automatically by onEngineComplete() after ACB
        // converges, IF the user enabled the checkbox at ACB click
        // time. Uses the just-measured T_peak as the exposure for the
        // black capture.
        if (this.lastTPeak == null || this.lastTPeak <= 0) {
            // Defensive: if ACB didn't actually produce a valid T_peak
            // (e.g. didn't converge and metadata is missing), skip the
            // follow-up rather than firing a black-floor capture with
            // a bogus exposure.
            this.setStatus('Skipped black floor (no valid T_peak)');
            this.pendingBlackFollowup = false;
            this.setButtonsEnabled(true);
            return;
        }

        this.taskInFlight = 'acb_black_followup';
        this.setStatus('Measuring (black floor)...');

        const payload = {
            exposure_s: this.lastTPeak,
            ...this.getCurrentHardwareParams(),
        };

        try {
            await fetch('/measure_peak_black', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
        } catch (e) {
            this.setStatus('Network error');
            this.taskInFlight = null;
            this.setButtonsEnabled(true);
        }
    },

    // ----------------------------------------------------------------
    // Completion handler (called from /status polling loop)
    // ----------------------------------------------------------------

    async onEngineComplete() {
        // Called when the existing /status polling sees isEngineRunning
        // flip true->false. This is the moment the engine has finished
        // SOMETHING - it might or might not be one of our tasks. If we
        // don't have a task in flight, this is somebody else's
        // completion (e.g. Main page job) and we should not act.
        if (!this.taskInFlight) return;

        const completedTask = this.taskInFlight;
        this.taskInFlight = null;

        // Refresh the preview image. The engine just wrote a new
        // probe_live.jpg as part of the measurement, so swap our img
        // element's src with a cache-busting query string.
        const img = document.getElementById('cal_probe_img');
        if (img) {
            img.src = '/static/probe_live.jpg?t=' + Date.now();
        }

        // Pull fresh state from calibration.json and update readouts.
        await this.refreshState();

        // Decide what happens next based on which task just completed.
        if (completedTask === 'acb' && this.pendingBlackFollowup) {
            // Fire the follow-up. lastTPeak was populated by
            // refreshState() above.
            this.pendingBlackFollowup = false;
            // setStatus and setButtonsEnabled are managed inside
            // runAcbBlackFollowup; no need to set Ready here.
            await this.runAcbBlackFollowup();
            return;
        }

        // WB just finished: pull the derived gains and write them into the
        // Main page's Hardware Constants so the next dispatched job uses them.
        // This is the "semi-auto" hinge - measure once here, every subsequent
        // job reuses these exact values, so WB stays locked frame-to-frame.
        if (completedTask === 'wb') {
            try {
                const r = await fetch('/calibration_state');
                const s = await r.json();
                const rEl = document.getElementById('awb_r');
                const bEl = document.getElementById('awb_b');
                if (rEl && typeof s.awb_r === 'number') rEl.value = s.awb_r.toFixed(4);
                if (bEl && typeof s.awb_b === 'number') bEl.value = s.awb_b.toFixed(4);
            } catch (e) { console.error('WB write-back failed:', e); }
            this.setWbStatus('Ready');
        }

        // Normal completion (no follow-up pending).
        this.setStatus('Ready');
        this.setButtonsEnabled(true);
    },

    // ----------------------------------------------------------------
    // State sync
    // ----------------------------------------------------------------

    async refreshState() {
        // Fetch /calibration_state and populate the Current Calibration
        // readout panel. Also writes the Single Measurement readout if
        // last_single_measurement is present.
        try {
            const r = await fetch('/calibration_state');
            const state = await r.json();

            // Capture T_peak for use by the black-floor follow-up.
            this.lastTPeak = (typeof state.t_peak === 'number') ? state.t_peak : null;

            // Current Calibration readout panel.
            const tpeakEl = document.getElementById('cal_readout_t_peak');
            const floorEl = document.getElementById('cal_readout_black_floor');
            const wbEl = document.getElementById('cal_readout_wb');
            const convergedEl = document.getElementById('cal_readout_converged');

            if (tpeakEl) tpeakEl.innerText = (state.t_peak != null) ?
                state.t_peak.toFixed(4) + ' s' : '--';
            if (floorEl) floorEl.innerText = (state.black_floor_at_t_peak != null) ?
                state.black_floor_at_t_peak.toFixed(6) : '--';

            // WB readout: pull from t_peak_meta which records what WB
            // the calibration was run under. Useful for the user to
            // see at-a-glance whether the current Main page WB matches
            // what T_peak was measured at.
            if (wbEl) {
                if (state.t_peak_meta) {
                    const m = state.t_peak_meta;
                    wbEl.innerText = `R=${m.awb_r}, B=${m.awb_b}`;
                } else {
                    wbEl.innerText = '--';
                }
            }

            // Converged flag: from t_peak_meta.converged. If absent
            // (no ACB has ever run), show "--". If false, show in a
            // way the user notices.
            if (convergedEl) {
                if (state.t_peak_meta && typeof state.t_peak_meta.converged === 'boolean') {
                    convergedEl.innerText = state.t_peak_meta.converged ? 'Yes' : 'No (max iter)';
                } else {
                    convergedEl.innerText = '--';
                }
            }

            // Single Measurement readout. If a single measurement has
            // ever been recorded, show its value colour-coded by
            // brightness range. The colour buckets are the ones we
            // agreed during planning:
            //   < 0.5         info  (blue, "should be brighter")
            //   0.5 .. 0.85   ok    (green, "in range")
            //   0.85 .. 0.95  ok    (green)
            //   0.95 .. 0.99  warn  (yellow, "close to clip")
            //   >= 0.99       danger(red, "clipped")
            const singleEl = document.getElementById('cal_single_result');
            if (singleEl && state.last_single_measurement) {
                const m = state.last_single_measurement;
                const b = m.brightness;
                singleEl.innerText = b.toFixed(4) + ' @ ' + m.exposure_s.toFixed(3) + 's';
                // Clear previous colour classes before applying a new one.
                singleEl.classList.remove('info', 'ok', 'warn', 'danger');
                if (b < 0.5) singleEl.classList.add('info');
                else if (b < 0.95) singleEl.classList.add('ok');
                else if (b < 0.99) singleEl.classList.add('warn');
                else singleEl.classList.add('danger');
            }

            // Auto White Balance readout. These are camera gains (awb_r/awb_b),
            // the same keys jobs consume, written by the WB task.
            const wbREl     = document.getElementById('cal_wb_readout_r');
            const wbBEl     = document.getElementById('cal_wb_readout_b');
            const wbPassEl  = document.getElementById('cal_wb_readout_pass');
            if (wbREl) wbREl.innerText = (typeof state.awb_r === 'number')
                ? state.awb_r.toFixed(4) : '--';
            if (wbBEl) wbBEl.innerText = (typeof state.awb_b === 'number')
                ? state.awb_b.toFixed(4) : '--';
            if (wbPassEl) {
                wbPassEl.classList.remove('cal-wb-readout-pass', 'cal-wb-readout-fail');
                if (state.wb_meta && typeof state.wb_meta.passed === 'boolean') {
                    const p = state.wb_meta.passed;
                    // Show the worst residual so a near-miss is visible.
                    const worst = Math.max(state.wb_meta.confirm_residual_r || 0,
                                           state.wb_meta.confirm_residual_b || 0);
                    wbPassEl.innerText = (p ? 'PASS' : 'FAIL') +
                        ' (' + (worst * 100).toFixed(2) + '%)';
                    wbPassEl.classList.add(p ? 'cal-wb-readout-pass' : 'cal-wb-readout-fail');
                } else {
                    wbPassEl.innerText = '--';
                }
            }
        } catch (e) {
            // Silent fail - the readout staying at "--" is the
            // visible signal that something is wrong with the fetch.
            // A console.error helps future-me diagnose.
            console.error('Calibration state fetch failed:', e);
        }
    },
};

// Initialise after the DOM is parsed. The script tag for main.js is
// near the bottom of the body, so DOMContentLoaded has typically
// already fired by the time main.js executes - we handle both cases.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => calibration.init());
} else {
    calibration.init();
}