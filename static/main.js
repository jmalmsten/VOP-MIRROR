/* VOP Module:     main.js
Version:        v0.0.37
Description:    Frontend application logic. Handles dynamic HTML generation,
                multi-device state synchronization via timestamps, and UI events.
*/

// Tracks the age of our local data. When we pull from the server, we check if 
// the server's timestamp is newer than ours.
let local_sync_ts = 0; 
// Stores the last known JSON string representation of the UI to detect changes.
let last_known_state_str = "";
// Tracks the highest row ID created to ensure unique DOM IDs.
let keyframeCount = 0;

function formatTime(seconds) {
    /* Converts raw seconds into an HH:MM:SS string for the progress bar ETA. */
    if (!seconds || seconds < 0) return "00:00:00";
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return [hrs, mins, secs].map(v => v < 10 ? "0" + v : v).join(":");
}

function calcFitScale() {
    /* Calculates the base world scale required to make a standard 2x2 object
    fill the vertical bounds of the projection frustum at distance Z=1.
    Formula based on VOP Math: Scale = tan(FOV/2) * 2.0
    */
    const fovVal = parseFloat(document.getElementById('fov').value);
    const scaleInput = document.getElementById('coord_scale');
    if (!fovVal) return;
    
    // Convert degrees to radians for JS Math.tan
    const halfFovRad = (fovVal / 2) * (Math.PI / 180);
    const s = Math.tan(halfFovRad) * 2.0; 
    
    scaleInput.value = s.toFixed(4);
    triggerSync(); // Force a sync push so other connected devices update their scale inputs.
    runTask('preview'); // Automatically refresh the probe image to show the new scale.
}

function createRowHTML(i) {
    /* Generates the raw HTML string for a single table row.
    CRITICAL FIX: Every input element now has an oninput() or onchange() event 
    that calls triggerSync(). This ensures changes are pushed to the server instantly.
    */
    return `
        <tr id="row_${i}">
            <td class="row-index">${i}</td>
            <td><input id="f${i}" type="number" onchange="updateProbeRange()" oninput="triggerSync()"></td>
            <td><button class="snap-btn" onclick="jumpToFrame('f${i}')">GO</button></td>
            <td>
                <select id="m${i}" title="Interpolation Mode" onchange="triggerSync()">
                    <option value="S">Smth</option>
                    <option value="L">Lin</option>
                    <option value="I">In</option>
                    <option value="O">Out</option>
                </select>
            </td>
            <td><input id="crn${i}" type="checkbox" title="Corner" onchange="triggerSync()"></td>
            <td><input id="src${i}" type="number" step="1" title="Source Anchor (-1 Auto)" oninput="triggerSync()"></td>
            <td><input id="stp${i}" type="number" step="1" value="1" title="Source Step" oninput="triggerSync()"></td>
            <td><input id="p${i}" type="text" value="0,0,-10" oninput="triggerSync()"></td>
            <td><input id="r${i}" type="text" value="0,0,0" oninput="triggerSync()"></td>
            <td><input id="c${i}_hex" type="color" value="#ffffff" title="ProjGel" onchange="triggerSync()"></td>
            <td><input id="cg${i}_hex" type="color" value="#ffffff" title="CamGel" onchange="triggerSync()"></td>
            <td><input id="s${i}" type="number" step="0.1" value="1.0" oninput="triggerSync()"></td>
            <td><input id="sd${i}" type="number" step="0.1" value="1.0" oninput="triggerSync()"></td>
            <td><input id="ph${i}" type="number" step="0.1" value="0.5" oninput="triggerSync()"></td>
            <td>${i > 1 ? `<button class="del-btn" onclick="removeKeyframe(${i})">×</button>` : ''}</td>
        </tr>
    `;
}

function addKeyframe() {
    /*
    Appends a new keyframe row to the table.
    Implements Row Cloning: Copies the values of the previously active row to save data entry time.
    */
    const prevId = keyframeCount;
    keyframeCount++;
    
    const container = document.getElementById('sheet_body');
    // Using an HTML template element allows us to parse the string into DOM nodes 
    // before appending, preventing the destruction of existing event listeners in the table.
    const template = document.createElement('template');
    template.innerHTML = createRowHTML(keyframeCount);
    container.appendChild(template.content.firstElementChild);
    
    // --- ROW CLONING LOGIC ---
    if (prevId > 0) {
        // Define the specific parameters we want to copy. We omit 'f' (Frame) and 'src' (Source Anchor)
        // because those typically increment row-by-row.
        const fieldsToClone = ['m', 'crn', 'stp', 'p', 'r', 'c_hex', 'cg_hex', 's', 'sd', 'ph'];
        
        fieldsToClone.forEach(f => {
            // Reconstruct the DOM IDs dynamically (e.g., 'p1' vs 'p2')
            const isHex = f.includes('_hex');
            const baseStr = f.replace('_hex', '');
            const prevStrId = `${baseStr}${prevId}${isHex ? '_hex' : ''}`;
            const newStrId = `${baseStr}${keyframeCount}${isHex ? '_hex' : ''}`;
            
            const prevEl = document.getElementById(prevStrId);
            const newEl = document.getElementById(newStrId);
            
            // If both elements exist, copy the data over.
            if (prevEl && newEl) {
                if (newEl.type === 'checkbox') {
                    newEl.checked = prevEl.checked;
                } else {
                    newEl.value = prevEl.value;
                }
            }
        });
    }
    
    // Force a push to the server so the new row is immediately saved.
    triggerSync();
}

function removeKeyframe(id) {
    /* Destroys a row by its DOM ID and updates the server. */
    const row = document.getElementById(`row_${id}`);
    if (row) row.remove();
    triggerSync();
    runTask('preview'); 
}

function jumpToFrame(id) {
    /* Reads the master frame number from a row's FR input and pushes it to the Global Probe input. */
    const el = document.getElementById(id);
    const probe = document.getElementById('probe_frame');
    if (el && probe) {
        probe.value = el.value;
        triggerSync();
        runTask('preview');
    }
}

function updateProbeRange() {
    /* Scans all 'FR' inputs to find the absolute minimum and maximum frame numbers,
    then updates the HTML min/max attributes on the global probe input to prevent
    users from requesting frames outside the active timeline bounds.
    */
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
    /* Iterates over every input and select element in the DOM to build a unified JSON object. */
    const data = {};
    document.querySelectorAll('input, select').forEach(i => { 
        if(i.id) data[i.id] = i.value; 
    });
    // Checkboxes must be handled separately because their state is boolean (.checked), not string (.value).
    document.querySelectorAll('input[type="checkbox"]').forEach(i => {
        if(i.id) data[i.id] = i.checked;
    });
    return data;
}

function getComparable(settings) {
    /* Creates a serialized string of the settings object minus the timestamp.
    Used to mathematically verify if the UI state has actually changed.
    */
    const copy = { ...settings };
    delete copy.last_sync;
    return JSON.stringify(copy);
}

function applyServerSettings(params) {
    /* TWO-WAY PULL LOGIC
    Reconstructs the UI based on parameters pulled from the server.
    This handles both the initial load and multi-device updates.
    */
    
    // 1. Ensure enough rows exist to hold the data.
    let maxIdx = 0;
    for (let k in params) {
        if (k.startsWith('f') && !isNaN(parseInt(k.substring(1)))) {
            maxIdx = Math.max(maxIdx, parseInt(k.substring(1)));
        }
    }
    while (keyframeCount < maxIdx) addKeyframe();
    if (keyframeCount === 0) addKeyframe();
    
    // 2. Map the data to the DOM elements.
    for (let k in params) {
        const el = document.getElementById(k);
        
        // THE RACE-CONDITION SHIELD: 
        // document.activeElement identifies the input box the user is currently focused on.
        // If the user is actively typing in a box, we explicitly ignore the server data for that
        // specific box to prevent the server from deleting their half-typed numbers.
        if (el && k !== 'last_sync' && document.activeElement !== el) {
            if(el.type === 'checkbox') {
                if(el.checked !== params[k]) el.checked = params[k];
            } else {
                if(el.value !== params[k]) el.value = params[k];
            }
        }
    }
    
    // Update the local timestamp to match the server data we just pulled.
    local_sync_ts = params.last_sync || 0;
    last_known_state_str = getComparable(getUISettings());
    updateProbeRange();
}

async function triggerSync() {
    /*
    TWO-WAY PUSH LOGIC
    Generates a new timestamp and sends the current UI state to the Flask backend.
    */
    const currentUI = getUISettings();
    const currentUIStr = getComparable(currentUI);
    
    // Only fire the network request if the data actually changed.
    if (currentUIStr !== last_known_state_str) {
        
        // Generate a fresh UNIX timestamp. This asserts that our client data is the newest.
        const new_ts = Date.now();
        const syncPayload = { ...currentUI, last_sync: new_ts };
        
        try {
            const resp = await fetch('/sync_state', { 
                method: 'POST', 
                headers: {'Content-Type': 'application/json'}, 
                body: JSON.stringify(syncPayload) 
            });
            
            // If the server accepted the payload...
            if (resp.status === 200) {
                // ...confirm our local timestamp is now the master.
                local_sync_ts = new_ts; 
                last_known_state_str = currentUIStr;
                
                // Flash the sync indicator green.
                const ind = document.getElementById('sync_indicator');
                if (ind) { 
                    ind.innerText = "● SYNCED"; 
                    ind.style.color = "#0f0"; 
                }
            }
        } catch (e) { 
            console.error("Sync Failed", e); 
        }
    }
}

async function runTask(type) {
    /* Dispatches execution commands (Preview, Cam View, Render Sequence) to the Flask backend. 
    */
    const data = getUISettings();
    data.last_sync = local_sync_ts;
    data.type = type; 
    
    // Update the UI labels to reflect the requested probe frame.
    const lblFr = document.getElementById('val_probe_frame');
    const lblSub = document.getElementById('val_probe_sub');
    if (lblFr) lblFr.innerText = data.probe_frame;
    if (lblSub) lblSub.innerText = data.probe_sub;

    try {
        // Determine the correct Flask route based on the task type.
        const targetRoute = type === 'execute' ? '/execute_sequence' : '/preview';
        
        const res = await fetch(targetRoute, {
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify(data)
        });
        
        // If the request was a preview and succeeded, force the image element to reload
        // by appending a cache-busting timestamp query parameter to the image URL.
        if(type !== 'execute' && res.ok) {
            const img = document.getElementById('probe_img');
            const typeLabel = document.getElementById('preview_type');
            if (img) { 
                img.src = `/static/probe_live.jpg?t=${Date.now()}`; 
                img.style.display = 'block'; 
            }
            // Update the UI label so the user knows if they are looking at a synthetic render or physical camera feed.
            if (typeLabel) {
                typeLabel.innerText = (type === 'cam_preview' ? "CAMERA VIEW" : "PROJECTOR PROBE");
            }
        }
    } catch (e) { 
        console.error("Task Error:", e); 
    }
}

// Global Commands
function panic() { fetch('/panic', {method:'POST'}); }
function nukeMag() { if(confirm("NUKE TIFFS?")) fetch('/nuke_mag', {method:'POST'}); }

// Bind event listeners to global UI controls outside the table to ensure they also push updates.
document.querySelectorAll('.c-box input, .c-box select').forEach(el => {
    el.addEventListener('change', triggerSync);
    // Number and Text inputs use 'input' to catch keystrokes immediately, rather than waiting for loss of focus.
    if (el.type === 'number' || el.type === 'text') {
        el.addEventListener('input', triggerSync);
    }
});

// File Upload Logic
const fileInput = document.getElementById('file_input');
if(fileInput) {
    fileInput.addEventListener('change', async function() {
        if(this.files && this.files.length > 0) {
            // Guard against accidental overwrites.
            if(!confirm("WARNING: Uploading a file will ERASE the current contents of the Projector Mag. Continue?")) {
                this.value = ''; 
                return;
            }
            
            // Build a multipart form data payload to transmit the binary file.
            const formData = new FormData();
            formData.append('file', this.files[0]);
            try {
                const resp = await fetch('/upload_target', { method: 'POST', body: formData });
                if(resp.ok) {
                    const data = await resp.json();
                    // Auto-fill the global image input with the newly uploaded filename.
                    document.getElementById('image').value = data.filename;
                    triggerSync();
                    runTask('preview'); 
                } else { 
                    alert("Upload Failed"); 
                }
            } catch(e) { 
                console.error("Upload error", e); 
            }
        }
    });
}

// Master Poller: Runs every 1 second (1000ms).
// Handles both the UI Progress Bar updates and the Multi-Device Data Pulls.
setInterval(async () => {
    try {
        const r = await fetch('/status');
        if (!r.ok) return;
        const st = await r.json();
        
        // MULTI-DEVICE SYNC CHECK
        // If the server's timestamp is newer than our local timestamp, it means 
        // another device (like your laptop) pushed an update. We must pull it.
        if (st.params && st.params.last_sync > local_sync_ts) {
            applyServerSettings(st.params);
        }
        
        // PROGRESS BAR UPDATES
        const msgEl = document.getElementById('st_msg');
        const bar = document.getElementById('st_bar');
        
        if (st.status === 'running' || st.status === 'busy') {
            const timeStr = formatTime(st.eta);
            if (msgEl) msgEl.innerText = `${st.msg} [${st.current}/${st.total}] REMAINING: ${timeStr} | ${st.disk}`;
            // Calculate percentage width. Prevent division by zero if total is 0.
            if (bar) bar.style.width = (st.total > 0 ? (st.current/st.total*100) : 100) + "%";
        } else {
            if (msgEl) msgEl.innerText = `${st.msg} | ${st.disk}`;
            if (bar) bar.style.width = "0%";
        }
    } catch (e) { 
        // Silently catch fetch errors (e.g., if the server is temporarily unreachable).
    }
}, 1000);