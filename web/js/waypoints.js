// ===========================================================
// Aeronis - waypoint management (add / delete /
// move / edit) onn the MapLibre map.
// ===========================================================

const wpState = {
    waypoints: [],
    selected: null,
    editIdx: null,
    markers: []
};

const MAX_WAYPOINTS_PER_MISSION = 200;
const missionStore = {
    missions: [],   // [{ id, name, waypoints }]
    activeIndex: 0,
    collapsed: false // whether the active mission's waypoint list is hidden
};
const DEFAULT_ALTITUDE = 80;
const DEFAULT_SPEED = 5;
let draggedWpIndex = null;
let currentMissionMode = '';



async function setMissionMode(mode) {
    currentMissionMode = mode;

    ['photo', 'video', 'none'].forEach(m => {
        const btn = document.getElementById(`mode-btn-${m}`);
        if (btn) btn.classList.toggle('active', m === mode);
    });

    if (typeof ZONE_PARAMS !== 'undefined') {
        ZONE_PARAMS.capture_mode = mode;
    }

    if (!wpState.waypoints.length || mode === 'none') {
        if (mode === 'none') {
            wpState.waypoints = wpState.waypoints.map(wp => ({ ...wp, actions: [] }));
            refreshWpMap(window.__mapInstance);
            refreshWpPanel();
            if (typeof snapshotHistory === 'function') snapshotHistory();
        }
        return;
    }

    const drone = document.getElementById('zone-drone') ? document.getElementById('zone-drone').value : 'MAVIC_3';
    const overlap = typeof ZONE_PARAMS !== 'undefined' ? ZONE_PARAMS.overlap : 0.8;

    try {
        const res = await api('/api/set-mode', {
            waypoints: wpState.waypoints,
            mode,
            drone,
            overlap
        });
        if (res.ok) {
            wpState.waypoints = res.waypoints;
            refreshWpMap(window.__mapInstance);
            refreshWpPanel();
            if (typeof snapshotHistory === 'function') snapshotHistory();
            wpToast(`${mode === 'photo' ? 'Photo' : 'Video'} mode applied`, 'ok');
        } else {
            wpToast('Mode error: ' + res.error, 'err');
        }
    } catch (err) {
        wpToast('API server unavailable (run server.py)', 'err');
    }
}

function startMultiMissions(waypointArrays) {
    missionStore.missions = waypointArrays.map((wps, i) => ({
        id: i,
        name: `Mission ${i + 1}`,
        waypoints: wps
    }));
    missionStore.activeIndex = 0;
    loadActiveMission();
    renderMissionTabs();
    updateExportAllVisibility();
}

function clearMissionSplit() {
    missionStore.missions = [];
    missionStore.activeIndex = 0;
    renderMissionTabs();
    updateExportAllVisibility();
}

function loadActiveMission() {
    const mission = missionStore.missions[missionStore.activeIndex];
    if (!mission) return;
    wpState.waypoints = mission.waypoints;
    wpState.selected = null;
    refreshWpMap(window.__mapInstance);
    refreshWpPanel();
}


function syncActiveMissionFromWpState() {
    if (missionStore.missions.length && missionStore.missions[missionStore.activeIndex]) {
        missionStore.missions[missionStore.activeIndex].waypoints = wpState.waypoints;
    }
    renderMissionTabs();
}

function switchMission(idx) {
    if (idx === missionStore.activeIndex) {
        missionStore.collapsed = !missionStore.collapsed;
        renderMissionTabs();
        return;
    }
    // Persist edits made to the mission we're leaving before switching
    if (missionStore.missions[missionStore.activeIndex]) {
        missionStore.missions[missionStore.activeIndex].waypoints = wpState.waypoints;
    }
    missionStore.activeIndex = idx;
    missionStore.collapsed = false;
    loadActiveMission();
    renderMissionTabs();
}

function renderMissionTabs() {
    const container = document.getElementById('mission-tabs');
    const wpList = document.getElementById('wp-list');
    if (!container || !wpList) return;

    if (wpList.parentElement) wpList.parentElement.removeChild(wpList);

    if (missionStore.missions.length <= 1) {
        container.style.display = 'none';
        container.innerHTML = '';
        container.insertAdjacentElement('afterend', wpList);
        wpList.style.display = '';
        return;
    }

    container.style.display = 'flex';
    container.innerHTML = missionStore.missions.map((m, i) => `
        <div class="mission-tab-group">
            <button class="mission-tab ${i === missionStore.activeIndex ? 'active' : ''} ${i === missionStore.activeIndex && missionStore.collapsed ? 'collapsed' : ''}" data-idx="${i}">
                <span class="mission-tab-name">${m.name}</span>
                <span class="mission-tab-count">${m.waypoints.length}</span>
            </button>
            <div class="mission-tab-body ${i === missionStore.activeIndex && missionStore.collapsed ? 'is-collapsed' : ''}" data-body-idx="${i}"></div>
        </div>
    `).join('');

    container.querySelectorAll('.mission-tab').forEach(btn => {
        btn.addEventListener('click', () => switchMission(parseInt(btn.dataset.idx, 10)));
    });

    const activeBody = container.querySelector(`.mission-tab-body[data-body-idx="${missionStore.activeIndex}"]`);
    if (activeBody) {
        activeBody.appendChild(wpList);
        wpList.style.display = missionStore.collapsed ? 'none' : '';
    }
}

function updateExportAllVisibility() {
    const btn = document.getElementById('export-all-btn');
    if (!btn) return;
    btn.style.display = missionStore.missions.length > 1 ? '' : 'none';
}

async function exportAllMissions(missionConfigBase) {
    if (!missionStore.missions.length) return;

    // Persist any edits made to the currently active mission first
    if (missionStore.missions[missionStore.activeIndex]) {
        missionStore.missions[missionStore.activeIndex].waypoints = wpState.waypoints;
    }

    const files = [];
    let failed = 0;
    for (let i = 0; i < missionStore.missions.length; i++) {
        const mission = missionStore.missions[i];
        if (mission.waypoints.length < 2) continue;

        const body = Object.assign(
            { waypoints: mission.waypoints },
            missionConfigBase,
            { name: `${missionConfigBase.name} ${i + 1}` }
        );

        let res;
        try {
            res = await api('/api/generate', body);
        } catch (e) {
            wpToast(`Mission ${i + 1}: API server unavailable`, 'err');
            failed++;
            continue;
        }
        if (!res.ok) {
            wpToast(`Mission ${i + 1}: ${res.error}`, 'err');
            failed++;
            continue;
        }

        files.push({ name: res.filename, data: base64ToBytes(res.kmz_b64) });
    }

    if (!files.length) {
        wpToast('No missions could be exported', 'err');
        return;
    }

    const zipBytes = buildZip(files);
    const zipName = `${(missionConfigBase.name || 'DJI Mission').replace(/[^a-z0-9_\- ]/gi, '_')}.zip`;
    const saved = await saveZipFile(zipBytes, zipName);

    if (saved) {
        const note = failed ? ` (${failed} failed)` : '';
        wpToast(`Downloaded ${files.length}/${missionStore.missions.length} missions in ${zipName}${note}`, failed ? 'err' : 'ok');
    }
}


/**
 * Attaches the "click to add waypoint" interaction to the map.
 * Call once `map` (declared in map.js) has been initialized.
 */
function initWaypoints(mapInstance) {
    mapInstance.on('click', (e) => {
        // Ignore click if a marker drag has just finished
        if (e.originalEvent && e.originalEvent._wpDragHandled) return;

        if (typeof draw !== 'undefined' && draw) {
            const features = draw.getAll().features;
            if (features.length > 0) {
                const rendered = mapInstance.queryRenderedFeatures(e.point, {
                    layers: [
                        'gl-draw-polygon-fill-inactive.cold',
                        'gl-draw-polygon-fill-active.cold',
                        'gl-draw-polygon-fill-inactive.hot',
                        'gl-draw-polygon-fill-active.hot',
                    ]
                });
                if (rendered.length > 0) return;
            }
        }
        wpState.waypoints.push({
            lon: e.lngLat.lng,
            lat: e.lngLat.lat,
            altitude: DEFAULT_ALTITUDE,
            speed: DEFAULT_SPEED,
            actions: []
        });
        refreshWpMap(mapInstance);
        refreshWpPanel();
        if (typeof snapshotHistory === 'function') snapshotHistory();
    });
}


// ===================
// Markers & polyline
// ===================

function buildWpMarkerEl(idx, selected) {
    const el = document.createElement('div');
    el.className = 'wp-marker' + (selected ? ' selected' : '');
    el.textContent = String(idx + 1);
    return el;
}

function refreshWpMap(mapInstance) {
    // Remove existing markers
    wpState.markers.forEach(m => m.remove());
    wpState.markers = [];

    wpState.waypoints.forEach((wp, i) => {
        const el = buildWpMarkerEl(i, i == wpState.selected);

        const marker = new maplibregl.Marker({ element: el, draggable: true}).setLngLat([wp.lon, wp.lat]).addTo(mapInstance);
        el.addEventListener('click', (ev) => {
            ev.stopPropagation();
            wpState.selected = i;
            refreshWpMap(mapInstance);
            refreshWpPanel();
        });

        marker.on('drag', () => {
            const pos = marker.getLngLat();
            wpState.waypoints[i].lon = pos.lng;
            wpState.waypoints[i].lat = pos.lat;
            refreshWpPolyline(mapInstance);
        });

        marker.on('dragend', () => {
            refreshWpPanel();
        });

        wpState.markers.push(marker);
    });

    refreshWpPolyline(mapInstance);
}

function refreshWpPolyline(mapInstance) {
    const data = {
        type: 'FeatureCollection',
        features: wpState.waypoints.length >= 2 ? [{
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: wpState.waypoints.map(w => [w.lon, w.lat])
            },
            properties: {}
        }] : []
    };

    const source = mapInstance.getSource('wp-path');
    if (source) {
        source.setData(data);
    } else {
        mapInstance.addSource('wp-path', { type: 'geojson', data });
        mapInstance.addLayer({
            id: 'wp-path-layer',
            type: 'line',
            source: 'wp-path',
            paint: {
                'line-color': '#185FA5',
                'line-width': 2.5,
                'line-opacity': 0.75,
                'line-dasharray': [2, 1.5]
            }
        });
    }
}


// =============================================
// Python backend (core/) exposed through Flask
// =============================================

const API_BASE = '';

async function api(endpoint, body) {
    const res = await fetch(API_BASE + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    return res.json();
}


// ================================
// Sidebar : stats + waypoint list
// ================================

async function refreshWpPanel() {
    const wps = wpState.waypoints;
    const n = wps.length;

    const stWps = document.getElementById('st-wps');
    const stDist = document.getElementById('st-dist');
    const stDur = document.getElementById('st-dur');
    const stAlt = document.getElementById('st-alt');
    if (!stWps) return; // sidebar not yet present in the DOM

    stWps.textContent = n;

    if (n >= 2) {
        try {
            const res = await api('/api/validate', { waypoints: wps });
            if (res.ok && res.stats) {
                const dist = res.stats.distance_m;
                const dur = res.stats.duration_s;
                stDist.textContent = dist >= 1000 ? (dist / 1000).toFixed(1) + ' km' : dist + ' m';
                stDur.textContent = Math.floor(dur / 60) + 'm ' + (dur % 60) + 's';
            }
        } catch (e) {
            stDist.textContent = '?';
            stDur.textContent = '?';
            console.warn('API server unavailable (is server.py running?', e);
        }
    } else {
        stDist.textContent = '-';
        stDur.textContent = '-';
    }

    if (n > 0) {
        const avg = wps.reduce((s, w) => s + w.altitude, 0) / n;
        stAlt.textContent = Math.round(avg) + 'm';
        if (typeof updateGsdDisplay === 'function') updateGsdDisplay(avg);
    } else {
        stAlt.textContent = '-';
        if (typeof updateGsdDisplay === 'function') updateGsdDisplay(0);
    }

    const list = document.getElementById('wp-list');
    if (n == 0) {
        list.innerHTML = '<div class="wp-empty">Click on the map to add waypoints</div>';
        return;
    }

    list.innerHTML = wps.map((wp, i) => `
        <div class="wp-item ${i === wpState.selected ? 'selected' : ''}" data-idx="${i}" draggable="true">
            <div class="wp-head">
                <div class="wp-idx">${i + 1}</div>
                <div class="wp-name">WP ${i + 1}</div>
                <span class="wp-meta">${wp.altitude}m · ${wp.speed}m/s</span>
                <button class="wp-del" data-idx="${i}" title="Delete">x</button>
            </div>
            <div class="wp-coords">${wp.lon.toFixed(5)}, ${wp.lat.toFixed(5)}</div>
            ${wp.actions.length ? `<div class="wp-tags">${wp.actions.map(a => `<span class="wp-tag">${a}</span>`).join('')}</div>` : ''}
        </div>
    `).join('') + '<div id="wp-drop-end"></div>';
    
    const dropEnd = document.getElementById('wp-drop-end');

    dropEnd.addEventListener('dragover', (e) => {
        e.preventDefault();
    });

    dropEnd.addEventListener('drop', (e) => {
        e.preventDefault();
        if (draggedWpIndex === null) return;
        reorderWaypoint(
            draggedWpIndex,
            wpState.waypoints.length
        );
    });

    list.querySelectorAll('.wp-item').forEach(item => {
        item.addEventListener('click', () =>
            selectWp(parseInt(item.dataset.idx, 10))
        );

        item.addEventListener('dragstart', (e) => {
            draggedWpIndex = parseInt(item.dataset.idx, 10);
            item.classList.add('dragging');

            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', draggedWpIndex);
        });

        item.addEventListener('dragend', () => {
            item.classList.remove('dragging');
            draggedWpIndex = null;
        });

        item.addEventListener('dragover', (e) => {
            e.preventDefault();
            item.classList.add('drag-over');
        });

        item.addEventListener('dragleave', () => {
            item.classList.remove('drag-over');
        });

        item.addEventListener('drop', (e) => {
            e.preventDefault();
            item.classList.remove('drag-over');
            const targetIndex = parseInt(item.dataset.idx, 10);
            if (
                draggedWpIndex === null ||
                draggedWpIndex === targetIndex
            ) {
                return;
            }
            reorderWaypoint(draggedWpIndex, targetIndex);
        });

    });
    list.querySelectorAll('.wp-del').forEach(btn => {
        btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            deleteWp(parseInt(btn.dataset.idx, 10));
        });
    });
}


async function selectWp(i) {
    wpState.selected = i;
    refreshWpMap(window.__mapInstance);
    await refreshWpPanel();
    openWpEdit(i);
}

function deleteWp(i) {
    wpState.waypoints.splice(i, 1);
    if (wpState.selected !== null && wpState.selected >= wpState.waypoints.length) {
        wpState.selected = null;
    }
    refreshWpMap(window.__mapInstance);
    refreshWpPanel();
    if (typeof snapshotHistory === 'function') snapshotHistory();
}

function reorderWaypoint(from, to) {
    const moved = wpState.waypoints.splice(from, 1)[0];
    if (to >= wpState.waypoints.length) {
        wpState.waypoints.push(moved);
    } else {
        wpState.waypoints.splice(to, 0, moved);
    }

    refreshWpMap(window.__mapInstance);
    refreshWpPanel();
    if (typeof snapshotHistory === 'function') snapshotHistory();

}

/**
 * Lightweight HTML replacement for window.confirm(). Native confirm()
 * dialogs are unreliable inside Tauri's embedded webview (WRY/WKWebView) --
 * this works identically in a normal browser and inside the desktop app.
 */
function showConfirm(message) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'edit-popup';
        overlay.innerHTML = `
            <div class="edit-box">
                <h3>Confirm</h3>
                <p style="font-size:13px; color:var(--text); margin:0 0 14px;">${message}</p>
                <div class="edit-actions">
                    <button class="btn-sm" id="confirm-cancel">Cancel</button>
                    <button class="btn-sm ok" id="confirm-ok">Confirm</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        const cleanup = (result) => {
            overlay.remove();
            resolve(result);
        };

        overlay.querySelector('#confirm-ok').addEventListener('click', () => cleanup(true));
        overlay.querySelector('#confirm-cancel').addEventListener('click', () => cleanup(false));
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) cleanup(false);
        });
    });
}

async function clearWaypoints() {
    if (!wpState.waypoints.length || await showConfirm('Delete all waypoints?')) {
        wpState.waypoints = [];
        wpState.selected = null;
        refreshWpMap(window.__mapInstance);
        refreshWpPanel();
        if (typeof snapshotHistory === 'function') snapshotHistory();
        if (typeof clearMissionSplit === 'function') clearMissionSplit();

        const feedback = document.getElementById('val-feedback');
        if (feedback) feedback.innerHTML = '';

        if (typeof clearZone === 'function') clearZone();
    }
}



// =======================
// Waypoit editing popup
// =======================

function openWpEdit(i) {
    const wp = wpState.waypoints[i];
    if (!wp) return;

    wpState.editIdx = i;
    document.getElementById('wp-edit-title').textContent = `Waypoint ${i + 1}`;
    document.getElementById('wp-edit-lon').value = wp.lon;
    document.getElementById('wp-edit-lat').value = wp.lat;
    document.getElementById('wp-edit-alt').value = wp.altitude;
    document.getElementById('wp-edit-spd').value = wp.speed;
    document.getElementById('wp-edit-action').value = wp.actions[0] || '';
    document.getElementById('wp-edit-popup').style.display = 'flex';
}

function closeWpEdit() {
    document.getElementById('wp-edit-popup').style.display = 'none';
}

function saveWpEdit() {
    const i = wpState.editIdx;
    const wp = wpState.waypoints[i]
    wp.lon = parseFloat(document.getElementById('wp-edit-lon').value)
    wp.lat = parseFloat(document.getElementById('wp-edit-lat').value)
    wp.altitude = parseFloat(document.getElementById('wp-edit-alt').value);
    wp.speed = parseFloat(document.getElementById('wp-edit-spd').value);
    const act = document.getElementById('wp-edit-action').value;
    wp.actions = act ? [act] : [];

    wpState.markers[i].setLngLat([wp.lon, wp.lat]);
    refreshWpMap(window.__mapInstance);
    refreshWpPanel();
    if (typeof snapshotHistory === 'function') snapshotHistory();
    closeWpEdit();
}



// ========================
// Validation & KMZ export
// ========================

async function validateMission() {
    if (!wpState.waypoints.length) {
        wpToast('No waypoints', 'err');
        return;
    }

    let res;
    try {
        res = await api('/api/validate', { waypoints: wpState.waypoints });
    } catch (e) {
        wpToast('API server unavailable (start server.py)', 'err');
        return;
    }
    if (!res.ok) {
        wpToast('Server error : ' + res.error, 'err');
        return;
    }


    let html = '';
    if (res.valid) {
        html += `<div class="val-box ok">Valid mission — ${res.stats.distance_m}m, ${Math.floor(res.stats.duration_s / 60)}m${res.stats.duration_s % 60}s</div>`;
    }
    res.errors.forEach(e => html += `<div class="val-box err">x ${e}</div>`);
    res.warnings.forEach(w => html += `<div class="val-box warn"> ${w}</div>`);

    const feedback = document.getElementById('val-feedback');
    if (feedback) feedback.innerHTML = html;

    wpToast(res.valid ? "Mission valid" : "Errors detected", res.valid ? 'ok' : 'err');
}

async function generateKMZ(missionConfig) {
    if (wpState.waypoints.length < 2) {
        wpToast("Add at least 2 waypoints", "err");
        return;
    }
    if (wpState.waypoints.length > MAX_WAYPOINTS_PER_MISSION) {
        wpToast(
            `Too many waypoints (${wpState.waypoints.length}) — the controller crashes beyond ${MAX_WAYPOINTS_PER_MISSION}. Split this mission first.`,
            'err'
        );
        return;
    }

    const body = Object.assign({ waypoints: wpState.waypoints }, missionConfig);

    let res;
    try {
        res = await api('/api/generate', body);
    } catch (e) {
        wpToast('API server unavailable (start server.py)', 'err');
        return;
    }

    if (!res.ok) {
        wpToast('Error: ' + res.error, 'err');
        return;
    }

    const saved = await saveKMZFile(res.kmz_b64, res.filename);
    if (!saved) return;

    const s = res.stats;
    wpToast(
        `KMZ generated — ${s.waypoints} WP, ${s.distance_m}m, ${Math.floor(s.duration_s / 60)}m${s.duration_s % 60}s`,
        'ok'
    );

    if (s.warnings.length) {
        const feedback = document.getElementById('val-feedback');
        if (feedback) {
            feedback.innerHTML = s.warnings.map(w => `<div class="val-box warn">${w}</div>`).join('');
        }
    }
}


/**
 * Decodes a base64 string into a Uint8Array of raw bytes.
 */
function base64ToBytes(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes
}

/**
 * Saves a base64-encoded KMZ file. Uses the File System Access API
 * (showDaveFilePicker) when available so the user gets the native
 * "Save As" dialog with control over location/name. Falls back to a 
 * plan <a download> click on browsers that don't support it
 * (Firefox, Safari) or if the user dismisses the picker with an error.
 */
async function saveKMZFile(base64Data, suggestedName) {
    const bytes = base64ToBytes(base64Data);

    if ('showSaveFilePicker' in window) {
        let handle = null;
        try {
            handle = await window.showSaveFilePicker({
                suggestedName,
                types: [{
                    description: 'KMZ Mission File',
                    accept: { 'application/vnd.google-earth.kmz': ['.kmz']}
                }]
            });
        } catch (err) {
            if (err.name === 'AbortError') {
                wpToast('Save cancelled', '');
                return false;
            }
            console.warn('showSaveFilePicker failed, falling back to direct download', err);
            handle = null;
        }
        if (handle) {
            const writable = await handle.createWritable();
            await writable.write(bytes);
            await writable.close();
            return true;
        }
    }
    const blob = new Blob([bytes], {type: 'application/vnd.google-earth.kmz'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = suggestedName;
    link.click();
    URL.revokeObjectURL(url);
    return true;
}


async function saveZipFile(bytes, suggestedName) {
    if ('showSaveFilePicker' in window) {
        let handle = null;
        try {
            handle = await window.showSaveFilePicker({
                suggestedName,
                types: [{
                    description: 'ZIP Archive',
                    accept: { 'application/zip': ['.zip'] }
                }]
            });
        } catch (err) {
            if (err.name === 'AbortError') {
                wpToast('Save cancelled', '');
                return false;
            }
            console.warn('showSaveFilePicker failed, falling back to direct download', err);
            handle = null;
        }
        if (handle) {
            const writable = await handle.createWritable();
            await writable.write(bytes);
            await writable.close();
            return true;
        }
    }
    const blob = new Blob([bytes], {type: 'application/zip'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = suggestedName;
    link.click();
    URL.revokeObjectURL(url);
    return true;
}



// ==========================
// Simple notification toast
// ==========================

let wpToastTimer;
function wpToast(msg, type = '') {
    let el = document.getElementById('wp-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'wp-toast';
        el.className = 'toast';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.className = 'toast show' + (type === 'ok' ? ' ok-toast' : type === 'err' ? ' err-toast' : '');
    clearTimeout(wpToastTimer);
    wpToastTimer = setTimeout(() => el.classList.remove('show'), 3000);
}