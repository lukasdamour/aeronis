let draw = null
let zoneMode = null;
let rectangleStartPoint = null;
let activeZoneFeatureId = null;
let zoneGenerateTimer = null;
let zonePreviewWaypoints = [];
let zonePreviewMarkers = [];

const ZONE_PARAMS = {
    altitude: 80,
    speed: 5,
    overlap: 0.8,
    angle: 0,
    drone: 'MAVIC_3',
    capture_mode: 'photo',
};

const ZONE_DEBOUNCE_MS = 400;

const SPLIT_PARAMS = {
    maxPerMission: 150,
};

function onSplitValueChange() {
    const value = parseInt(document.getElementById('split-value').value, 10);

    SPLIT_PARAMS.maxPerMission = Math.max(
        1,
        Math.min(value || 150, MAX_WAYPOINTS_PER_MISSION)
    );

    scheduleZoneGeneration();
}


/**
 * Splits an ordered waypoint list (flight-line order from grid-polygon)
 * into contiguous chunks. Always respects MAX_WAYPOINTS_PER_MISSION
 * regardless of the user's settings -- returns { chunks, adjusted }
 * where `adjusted` flags whether the user's requested split had to be
 * overridden to satisfy the hard controller limit.
 */
function splitWaypointsIntoMissions(waypoints) {
    const total = waypoints.length;

    if (!total) {
        return {
            chunks: [],
            adjusted: false
        };
    }

    const maxPerMission = Math.min(
        SPLIT_PARAMS.maxPerMission,
        MAX_WAYPOINTS_PER_MISSION
    );

    const adjusted =
        SPLIT_PARAMS.maxPerMission > MAX_WAYPOINTS_PER_MISSION;

    const missionCount = Math.ceil(total / maxPerMission);

    const baseSize = Math.floor(total / missionCount);
    const remainder = total % missionCount;

    const chunks = [];
    let start = 0;

    for (let i = 0; i < missionCount; i++) {
        const size = baseSize + (i < remainder ? 1 : 0);

        chunks.push(
            waypoints.slice(start, start + size)
        );

        start += size;
    }

    return {
        chunks,
        adjusted
    };
}

function patchDrawForMapLibre() {
    MapboxDraw.constants.classes.CANVAS = 'maplibregl-canvas';
    MapboxDraw.constants.classes.CONTROL_BASE = 'maplibregl-ctrl';
    MapboxDraw.constants.classes.CONTROL_PREFIX = 'maplibregl-ctrl-';
    MapboxDraw.constants.classes.CONTROL_GROUP = 'maplibregl-ctrl-group';
    MapboxDraw.constants.classes.ATTRIBUTION = 'maplibregl-ctrl-attrib';
}

function initZoneDrawing(mapInstance) {
    patchDrawForMapLibre();

    draw = new MapboxDraw({
        displayControlsDefault: false,
        controls: {},
    });

    mapInstance.addControl(draw);

    mapInstance.on('draw.create', (e) => onZoneFinalized(e.features[0]));
    mapInstance.on('draw.selectionchange', (e) => onZoneSelectionChange(e));
    mapInstance.on('draw.update', () => {
        if (activeZoneFeatureId) scheduleZoneGeneration();
    });
}

function startDrawPolygon() {
    if (!draw) return;
    closeZonePanel();
    zoneMode = 'polygon';
    draw.deleteAll();
    draw.changeMode('draw_polygon');
    setZoneToolbarState('polygon');
}

function startDrawRectangle() {
    if (!draw) return;
    closeZonePanel();
    zoneMode = 'rectangle';
    draw.deleteAll();

    draw.changeMode('simple_select');
    setZoneToolbarState('rectangle');
    rectangleStartPoint = null;

    const mapInstance = window.__mapInstance;
    let previewFeatureId = null;

    const updateRectanglePreview = (currentLngLat) => {
        const p1 = rectangleStartPoint;
        const p2 = currentLngLat;
        const minLon = Math.min(p1.lng, p2.lng), maxLon = Math.max(p1.lng, p2.lng);
        const minLat = Math.min(p1.lat, p2.lat), maxLat = Math.max(p1.lat, p2.lat);
        const coords = [
            [minLon, minLat], [maxLon, minLat],
            [maxLon, maxLat], [minLon, maxLat],
            [minLon, minLat]
        ];
        const feature = {
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [coords] },
            properties: {},
        };
        if (previewFeatureId) {
            feature.id = previewFeatureId;
            draw.set({ type: 'FeatureCollection', features: [feature] });
        } else {
            [previewFeatureId] = draw.add(feature);
        }
    };

    const onMouseMove = (e) => {
        if (!rectangleStartPoint) return;
        updateRectanglePreview(e.lngLat);
    };

    const onFirstClick = (e) => {
        rectangleStartPoint = e.lngLat;
        mapInstance.getCanvas().style.cursor = 'crosshair';
        mapInstance.off('click', onFirstClick);
        mapInstance.on('mousemove', onMouseMove);
        mapInstance.once('click', onSecondClick);
    };

    const onSecondClick = (e) => {
        mapInstance.off('mousemove', onMouseMove);
        mapInstance.getCanvas().style.cursor = '';
        const p1 = rectangleStartPoint;
        const p2 = e.lngLat;
        const minLon = Math.min(p1.lng, p2.lng), maxLon = Math.max(p1.lng, p2.lng);
        const minLat = Math.min(p1.lat, p2.lat), maxLat = Math.max(p1.lat, p2.lat);
        const coords = [
            [minLon, minLat], [maxLon, minLat],
            [maxLon, maxLat], [minLon, maxLat],
            [minLon, minLat],
        ];
        const feature = {
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [coords] },
            properties: {},
        };

        draw.deleteAll();
        const [id] = draw.add(feature);
        feature.id = id;
        previewFeatureId = null;
        onZoneFinalized(feature);
    };

    mapInstance.once('click', onFirstClick);
}

function cancelZoneDrawing() {
    if (!draw) return;
    if (zoneMode) {
        if (zoneMode === 'polygon') {
            draw.changeMode('simple_select');
        }

        const mapInstance = window.__mapInstance;
        if (mapInstance) {
            mapInstance.getCanvas().style.cursor = '';
        }

        if (activeZoneFeatureId) {
            setTimeout(() => {
                draw.changeMode('simple_select', { featureIds: [activeZoneFeatureId] });
            }, 0);
        }
    }
    zoneMode = null;
    rectangleStartPoint = null;
    setZoneToolbarState(null);
}

function clearZone() {
    if (!draw) return;
    closeZonePanel();
    draw.deleteAll();
    zoneMode = null;
    rectangleStartPoint = null;
    activeZoneFeatureId = null;
    setZoneToolbarState(null);
    clearZonePreview()
    if (typeof clearMissionSplit === 'function') clearMissionSplit();
}

function setZoneToolbarState(mode) {
    document.querySelectorAll('.zone-tool-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
}

function onZoneFinalized(feature) {
    zoneMode = null;
    setZoneToolbarState(null);
    setTimeout(() => {
        draw.changeMode('simple_select', { featureIds: [feature.id] });
        openZonePanelFor(feature.id);
    }, 0);
}

function onZoneSelectionChange(e) {
    const selected = e.features && e.features[0];
    if (selected && selected.geometry.type === 'Polygon') {
        openZonePanelFor(selected.id);
    } else {
        closeZonePanel();
    }
}

function openZonePanelFor(featureId) {
    activeZoneFeatureId = featureId;
    document.getElementById('zone-panel').style.display = 'block';
    scheduleZoneGeneration(0);
}


function toggleZonePanelCollapse() {
    const panel = document.getElementById('zone-panel');
    if (panel) panel.classList.toggle('collapsed');
}

function closeZonePanel() {
    activeZoneFeatureId = null;
    clearTimeout(zoneGenerateTimer);
    const panel = document.getElementById('zone-panel');
    if (panel) panel.style.display = 'none';
    clearZonePreview();
    if (window.__mapInstance) refreshWpMap(window.__mapInstance);
}

function setZoneCaptureMode(mode) {
    if (typeof setMissionMode === 'function') setMissionMode(mode);
    ZONE_PARAMS.capture_mode = mode;
}

function onZoneParamChange() {
    ZONE_PARAMS.altitude = parseFloat(document.getElementById('zone-altitude').value) || 80;
    ZONE_PARAMS.speed = parseFloat(document.getElementById('zone-speed').value) || 5;
    ZONE_PARAMS.overlap = parseFloat(document.getElementById('zone-overlap').value) / 100 || 0.8;
    ZONE_PARAMS.angle = parseFloat(document.getElementById('zone-angle').value) || 0;
    ZONE_PARAMS.drone = document.getElementById('zone-drone').value;
    if (typeof updateGsdDisplay === 'function') updateGsdDisplay(ZONE_PARAMS.altitude);
    scheduleZoneGeneration();
}


function scheduleZoneGeneration(delayMS = ZONE_DEBOUNCE_MS) {
    clearTimeout(zoneGenerateTimer);
    zoneGenerateTimer = setTimeout(previewMissionFromActiveZone, delayMS);
}


async function previewMissionFromActiveZone() {
    if (!activeZoneFeatureId) return;

    const feature = draw.get(activeZoneFeatureId);
    if (!feature) return;
    
    const coords = feature.geometry.coordinates[0];
    const polygon = coords.slice(0, -1).map(([lon, lat]) => [lon, lat]);
    if (polygon.length < 3) return;

    let res;
    try {
        res = await api('/api/grid-polygon', {
            polygon,
            altitude: ZONE_PARAMS.altitude,
            speed: ZONE_PARAMS.speed,
            overlap: ZONE_PARAMS.overlap,
            angle: ZONE_PARAMS.angle,
            drone: ZONE_PARAMS.drone,
        });
    } catch (err) {
        wpToast('API server unavailable (run server.py)', 'err');
        return;
    }

    if (!res.ok) {
        wpToast('Grid generation failed: ' + res.error, 'err');
        return;
    }

    if (!res.waypoints.length) {
        wpToast('Zone too small for the computed flight line spacing', 'err');
        clearZonePreview();
        refreshWpMap(window.__mapInstance);
        return;
    }

    hideWpMission();
    zonePreviewWaypoints = res.waypoints;
    const maxPerMission = Math.min(SPLIT_PARAMS.maxPerMission, MAX_WAYPOINTS_PER_MISSION);

    const missionCount = Math.ceil(res.waypoints.length / maxPerMission);
    const label = document.getElementById("split-mission-count");

    if (label) {
        label.textContent = missionCount;
    }
    drawZonePreview(res.waypoints);
    wpToast(`Preview: ${res.waypoints.length} waypoints (click Generate to confirm)`, '');
}


async function finalizeMissionFromWaypoints(waypoints) {
    const { chunks, adjusted } = splitWaypointsIntoMissions(waypoints);

    const finalMissions = [];
    for (const chunk of chunks) {
        let wps = [...chunk];

        if (ZONE_PARAMS.capture_mode === 'none') {
            wps = wps.map(wp => ({ ...wp, actions: [] }));
        } else {
            try {
                const res = await api('/api/set-mode', {
                    waypoints: wps,
                    mode: ZONE_PARAMS.capture_mode,
                    drone: ZONE_PARAMS.drone,
                    overlap: ZONE_PARAMS.overlap,
                });
                if (res.ok) {
                    wps = res.waypoints;
                } else {
                    wpToast('Mode application failed: ' + res.error, 'err');
                    return false;
                }
            } catch (err) {
                wpToast('API server unavailable (run server.py)', 'err');
                return false;
            }
        }
        finalMissions.push(wps);
    }

    if (finalMissions.length === 1) {
        if (typeof clearMissionSplit === 'function') clearMissionSplit();
        wpState.waypoints = [...finalMissions[0]];
        wpState.selected = null;
        refreshWpMap(window.__mapInstance);
        refreshWpPanel();
        if (typeof snapshotHistory === 'function') snapshotHistory();
        wpToast(`Mission confirmed - ${wpState.waypoints.length} waypoints`, 'ok');
    } else {
        startMultiMissions(finalMissions);
        if (typeof snapshotHistory === 'function') snapshotHistory();
        const total = finalMissions.reduce((s, m) => s + m.length, 0);
        const capNote = adjusted ? ' (adjusted to respect the 200 WP/mission controller limit)' : '';
        wpToast(`Zone split into ${finalMissions.length} missions (${total} waypoints total)${capNote}`, 'ok');
    }
    return true;
}

async function commitZonePreview() {
    clearTimeout(zoneGenerateTimer); 
    await previewMissionFromActiveZone(); 

    if (!zonePreviewWaypoints.length) {
        wpToast('No valid preview to confirm', 'err');
        return;
    }

    const waypoints = [...zonePreviewWaypoints];
    clearZonePreview();
    await finalizeMissionFromWaypoints(waypoints);
}


function drawZonePreview(waypoints) {
    const mapInstance = window.__mapInstance;
    if (!mapInstance) return;

    const geojson = {
        type: 'Feature',
        geometry: {
            type: 'LineString',
            coordinates: waypoints.map(w => [w.lon, w.lat])
        },
        properties: {}
    };

    const src = mapInstance.getSource('zone-preview');
    if (src) {
        src.setData(geojson);
    } else {
        mapInstance.addSource('zone-preview', { type: 'geojson', data: geojson});
        mapInstance.addLayer({
            id: 'zone-preview-line',
            type: 'line',
            source: 'zone-preview',
            paint: {
                'line-color': '#f59e0b',
                'line-width': 1.5,
                'line-opacity': 0.7,
                'line-dasharray': [3, 2]
            }
        });
    }
    drawZonePreviewMarkers(waypoints);
}

function drawZonePreviewMarkers(waypoints) {
    zonePreviewMarkers.forEach(m => m.remove());
    zonePreviewMarkers = [];

    const mapInstance = window.__mapInstance;
    if (!mapInstance) return;

    waypoints.forEach((wp, i) => {
        const el = document.createElement('div');
        el.className = 'wp-marker';
        el.textContent = String(i + 1);
        const marker = new maplibregl.Marker({ element: el}).setLngLat([wp.lon, wp.lat]).addTo(mapInstance);
        zonePreviewMarkers.push(marker);
    });
}

function clearZonePreview() {
    zonePreviewWaypoints = [];
    zonePreviewMarkers.forEach(m => m.remove());
    zonePreviewMarkers = [];
    const mapInstance = window.__mapInstance;
    if (!mapInstance) return;
    if (mapInstance.getLayer('zone-preview-line')) mapInstance.removeLayer('zone-preview-line');
    if (mapInstance.getSource('zone-preview')) mapInstance.removeSource('zone-preview');
}

function hideWpMission() {
    wpState.markers.forEach(m => m.remove());
    wpState.markers = [];
    const mapInstance = window.__mapInstance;
    if (!mapInstance) return;
    const source = mapInstance.getSource('wp-path');
    if (source) source.setData({ type: 'FeatureCollection', features: [] });
}
