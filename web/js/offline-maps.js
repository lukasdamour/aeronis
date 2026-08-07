// ===========================================================
// Aeronis - Offline Maps page
// Lets users download real map data (region or hand-drawn zone) so the
// planner's map keeps working with no internet connection in the field.
// ===========================================================

const API_BASE = '';

async function apiGet(endpoint) {
    const res = await fetch(API_BASE + endpoint);
    return res.json();
}

async function apiPost(endpoint, body) {
    const res = await fetch(API_BASE + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
    });
    return res.json();
}

async function apiDelete(endpoint) {
    const res = await fetch(API_BASE + endpoint, { method: 'DELETE' });
    return res.json();
}

let omMap;
let regionsCache = [];
let offlineMapsAvailable = true;
let isDrawing = false;
let drawStart = null;
let drawnBounds = null; // [west, south, east, north]
const jobsState = {};   // job_id -> latest status payload

const OM_BASE_STYLE = {
    version: 8,
    sources: {
        osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '&copy; OpenStreetMap contributors'
        }
    },
    layers: [{ id: 'osm-layer', type: 'raster', source: 'osm' }]
};

// ---------------------------------------------------------------
// Map + rectangle drawing (kept intentionally simple: this page only
// ever needs a single axis-aligned bounding box, not full polygons).
// ---------------------------------------------------------------

function emptyRectFeature() {
    return { type: 'FeatureCollection', features: [] };
}

function rectFeatureFromBounds(bounds) {
    const [w, s, e, n] = bounds;
    return {
        type: 'FeatureCollection',
        features: [{
            type: 'Feature',
            properties: {},
            geometry: { type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] }
        }]
    };
}

function initMap() {
    omMap = new maplibregl.Map({
        container: 'om-map',
        style: OM_BASE_STYLE,
        center: [2.2, 46.6],
        zoom: 4.5,
        minZoom: 2,
        maxZoom: 18
    });

    omMap.on('load', () => {
        omMap.addSource('om-draw-rect', { type: 'geojson', data: emptyRectFeature() });
        omMap.addLayer({
            id: 'om-draw-rect-fill', type: 'fill', source: 'om-draw-rect',
            paint: { 'fill-color': '#185fA5', 'fill-opacity': 0.15 }
        });
        omMap.addLayer({
            id: 'om-draw-rect-line', type: 'line', source: 'om-draw-rect',
            paint: { 'line-color': '#185fA5', 'line-width': 2 }
        });
    });

    omMap.getCanvas().addEventListener('mousedown', onMapMouseDown);
}

function toggleDrawRectangle() {
    isDrawing = !isDrawing;
    setDrawButtonState();
    omMap.dragPan[isDrawing ? 'disable' : 'enable']();
}

function setDrawButtonState() {
    const btn = document.getElementById('om-draw-btn');
    btn.classList.toggle('active', isDrawing);
    btn.textContent = isDrawing ? 'Click & drag on the map…' : '▭ Draw zone on map';
}

function onMapMouseDown(e) {
    if (!isDrawing) return;
    e.preventDefault();
    drawStart = omMap.unproject([e.offsetX, e.offsetY]);

    const onMove = (moveEvent) => {
        updateDrawnRect(drawStart, omMap.unproject([moveEvent.offsetX, moveEvent.offsetY]));
    };
    const onUp = (upEvent) => {
        updateDrawnRect(drawStart, omMap.unproject([upEvent.offsetX, upEvent.offsetY]));
        omMap.getCanvas().removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
        isDrawing = false;
        setDrawButtonState();
        omMap.dragPan.enable();
    };

    omMap.getCanvas().addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
}

function updateDrawnRect(p1, p2) {
    const west = Math.min(p1.lng, p2.lng);
    const east = Math.max(p1.lng, p2.lng);
    const south = Math.min(p1.lat, p2.lat);
    const north = Math.max(p1.lat, p2.lat);
    drawnBounds = [west, south, east, north];

    if (omMap.getSource('om-draw-rect')) {
        omMap.getSource('om-draw-rect').setData(rectFeatureFromBounds(drawnBounds));
    }

    document.getElementById('om-clear-btn').disabled = false;
    document.getElementById('om-download-custom-btn').disabled = !offlineMapsAvailable;
    document.getElementById('om-bounds-hint').textContent =
        `Zone: ${west.toFixed(4)}, ${south.toFixed(4)} → ${east.toFixed(4)}, ${north.toFixed(4)}`;
}

function clearDrawnRectangle() {
    drawnBounds = null;
    if (omMap.getSource('om-draw-rect')) {
        omMap.getSource('om-draw-rect').setData(emptyRectFeature());
    }
    document.getElementById('om-clear-btn').disabled = true;
    document.getElementById('om-download-custom-btn').disabled = true;
    document.getElementById('om-bounds-hint').textContent = '';
}

// ---------------------------------------------------------------
// Regions catalog
// ---------------------------------------------------------------

async function loadRegions() {
    const res = await apiGet('/api/offline-maps/regions');
    if (!res.ok) return;
    regionsCache = res.regions;
    renderRegionList();
    renderCustomRegionSelect();
}

function renderRegionList() {
    document.getElementById('om-region-list').innerHTML = regionsCache.map(r => `
        <div class="om-region-card">
            <div>
                <div class="om-region-name">${r.label}</div>
                <div class="om-region-size">~${(r.approx_pbf_mb / 1000).toFixed(1)} GB source data</div>
            </div>
            <button class="hbtn primary" ${offlineMapsAvailable ? '' : 'disabled'} onclick="downloadRegion('${r.id}')">Download</button>
        </div>
    `).join('');
}

function renderCustomRegionSelect() {
    document.getElementById('om-custom-region').innerHTML =
        regionsCache.map(r => `<option value="${r.id}">${r.label}</option>`).join('');
}

async function downloadRegion(regionId) {
    handleDownloadResponse(await apiPost('/api/offline-maps/download', { region: regionId }));
}

async function downloadCustomZone() {
    if (!drawnBounds) return;
    const regionId = document.getElementById('om-custom-region').value;
    const name = document.getElementById('om-custom-name').value.trim() || 'Custom zone';
    handleDownloadResponse(await apiPost('/api/offline-maps/download', {
        region: regionId, bounds: drawnBounds, name
    }));
}

function handleDownloadResponse(res) {
    if (!res.ok) {
        alert('Could not start download: ' + res.error);
        return;
    }
    jobsState[res.job_id] = { status: 'running', log_tail: '' };
    renderJobs();
    pollJob(res.job_id);
}

// ---------------------------------------------------------------
// Background job polling
// ---------------------------------------------------------------

async function pollJob(jobId) {
    const res = await apiGet(`/api/offline-maps/jobs/${jobId}`);
    if (!res.ok) return;
    jobsState[jobId] = res;
    renderJobs();

    if (res.status === 'running') {
        setTimeout(() => pollJob(jobId), 2000);
    } else {
        loadMaps(); // done or error: refresh the downloaded-maps list either way
    }
}

function renderJobs() {
    const ids = Object.keys(jobsState);
    document.getElementById('om-jobs-empty').style.display = ids.length ? 'none' : '';
    document.getElementById('om-jobs-list').innerHTML = ids.map(id => {
        const job = jobsState[id];
        const statusLabel = job.status === 'running' ? 'Building…'
            : job.status === 'done' ? '✅ Done' : '❌ Failed';
        return `
            <div class="om-card">
                <div class="om-card-row">
                    <div class="om-card-title">${job.output_name || id}</div>
                    <div>${statusLabel}</div>
                </div>
                ${job.status === 'running' ? '<div class="om-progress"><div class="om-progress-bar"></div></div>' : ''}
                <div class="om-log">${(job.log_tail || 'Starting…').replace(/</g, '&lt;')}</div>
            </div>
        `;
    }).join('');
}

// ---------------------------------------------------------------
// Downloaded maps management
// ---------------------------------------------------------------

async function loadMaps() {
    const res = await apiGet('/api/offline-maps');
    if (res.ok) renderMaps(res.maps);
}

function renderMaps(maps) {
    document.getElementById('om-maps-empty').style.display = maps.length ? 'none' : '';
    document.getElementById('om-maps-list').innerHTML = maps.map(m => `
        <div class="om-card">
            <div class="om-card-row">
                <div class="om-card-title">${m.label} ${m.active ? '<span class="om-badge">Active</span>' : ''}</div>
            </div>
            <div class="om-card-meta">${m.size_mb} MB · built ${new Date(m.built_at * 1000).toLocaleDateString()}</div>
            <div class="om-card-actions">
                ${m.active ? '' : `<button class="hbtn primary" onclick="activateMap('${m.id}')">Use offline</button>`}
                <button class="hbtn danger" ${m.active ? 'disabled title="Switch to another map first"' : ''} onclick="deleteMap('${m.id}')">Delete</button>
            </div>
        </div>
    `).join('');
}

async function activateMap(mapId) {
    const res = await apiPost('/api/offline-maps/activate', { id: mapId });
    if (!res.ok) { alert('Could not activate map: ' + res.error); return; }
    loadMaps();
}

async function deleteMap(mapId) {
    if (!confirm('Delete this offline map? This cannot be undone.')) return;
    const res = await apiDelete(`/api/offline-maps/${mapId}`);
    if (!res.ok) { alert('Could not delete map: ' + res.error); return; }
    loadMaps();
}

// ---------------------------------------------------------------
// Init
// ---------------------------------------------------------------

async function checkAvailability() {
    const res = await apiGet('/api/offline-maps/availability');
    if (res.ok && !res.available) {
        offlineMapsAvailable = false;
        const el = document.getElementById('om-unavailable');
        el.style.display = '';
        el.textContent = '⚠ ' + res.error;
        renderRegionList();
        document.getElementById('om-download-custom-btn').disabled = true;
    }
}

initMap();
checkAvailability().then(loadRegions);
loadMaps();
