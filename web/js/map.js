// =====================================================================
// Tile sources
// =====================================================================
//
// OFFLINE mode: vector tiles generated locally with 
// Planettileer from OSM data (see tiles-pipeline/), served
// by a small local server (serve tiles.py) exposing a
// TileJSON endoint. No dependency on third-party services.
//
// ONLINE mode: standard OSM raster tiles (light usage,
// compliant with OSM usage policy as long as no bulk
// downloads are performed through this mode).
//
const LOCAL_TILEJSON_URL = 'http://127.0.0.1:8765/tiles.json';
const LOCAL_GLYPHS_URL = 'fonts/{fontstack}/{range}.pbf';
const ONLINE_RASTER_STYLE = {
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
const SATELLITE_STYLE = {
    version: 8,
    sources: {
        satellite: {
            type: 'raster',
            tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
            tileSize: 256,
            attribution: 'Tiles &copy; Esri'
        }
    },
    layers: [{ id: 'satellite-layer', type: 'raster', source: 'satellite' }]
};

let offlineMode = false;
let map;
let isSatellite = false;

/**
 * Builds the "street" style (local vector tiles if available,
 * otherwise online raster tiles).
 */
function buildStreetStyle(tileJson) {
    if (tileJson) {
        // Enhanced vector style: terrain background, water, 
        // road hierarchy, buildings, and city/place labels
        // (requires local glyphs in web/fonts/ for offline use)
        return {
            version: 8,
            glyphs: LOCAL_GLYPHS_URL,
            sources: {
                'offline-osm': {
                    type: 'vector',
                    tiles: tileJson.tiles,
                    minzoom: tileJson.minzoom,
                    maxzoom: tileJson.maxzoom
                }
            },
            layers: [
                // --- Background = EARTH color by default ---
                { id: 'background', type: 'background',
                  paint: { 'background-color': '#eef0e8' } },

                // --- Terrain / land cover ---
                { id: 'landcover', type: 'fill', source: 'offline-osm', 'source-layer': 'landcover',
                  paint: { 'fill-color': [
                      'match', ['get', 'class'],
                      'wood', '#b8d3a0',
                      'forest', '#b8d3a0',
                      'grass', '#cde3ae',
                      'farmland', '#e8e3c4',
                      'sand', '#f0e8c8',
                      'ice', '#eef3f5',
                      '#e3e8d6'
                  ], 'fill-opacity': 0.85 } },
                { id: 'landuse', type: 'fill', source: 'offline-osm', 'source-layer': 'landuse',
                  paint: { 'fill-color': [
                      'match', ['get', 'class'],
                      'residential', '#e8dfd0',
                      'industrial', '#ddd6e2',
                      'commercial', '#e8dad0',
                      'park', '#c2dca3',
                      'cemetery', '#d0dcc4',
                      '#e3e4d8'
                  ], 'fill-opacity': 0.75 } },

                // --- Water ---
                { id: 'water', type: 'fill', source: 'offline-osm', 'source-layer': 'water',
                  paint: { 'fill-color': '#a9d3ef' } },
                { id: 'waterway', type: 'line', source: 'offline-osm', 'source-layer': 'waterway',
                  paint: { 'line-color': '#a9d3ef', 'line-width': 1.2 } },

                // --- Buildings ---
                { id: 'buildings', type: 'fill', source: 'offline-osm', 'source-layer': 'building',
                  minzoom: 13,
                  paint: { 'fill-color': '#cdc3b0', 'fill-opacity': 0.9 } },

                // --- Roads (major roads visible at regional zoom levels) ---
                { id: 'roads-minor', type: 'line', source: 'offline-osm', 'source-layer': 'transportation',
                  filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'path', 'track']]],
                  minzoom: 12,
                  paint: { 'line-color': '#ffffff', 'line-width': 1 } },
                { id: 'roads-secondary', type: 'line', source: 'offline-osm', 'source-layer': 'transportation',
                  filter: ['in', ['get', 'class'], ['literal', ['tertiary', 'secondary']]],
                  minzoom: 8,
                  paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 14, 2.5] } },
                { id: 'roads-primary', type: 'line', source: 'offline-osm', 'source-layer': 'transportation',
                  filter: ['in', ['get', 'class'], ['literal', ['primary', 'trunk']]],
                  minzoom: 5,
                  paint: { 'line-color': '#f2b441', 'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.6, 14, 4] } },
                { id: 'roads-motorway', type: 'line', source: 'offline-osm', 'source-layer': 'transportation',
                  filter: ['==', ['get', 'class'], 'motorway'],
                  minzoom: 4,
                  paint: { 'line-color': '#e8703a', 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.8, 14, 5] } },

                // --- Administrative boundaries ---
                // Countries: visible at all zoom levels
                { id: 'boundaries-country', type: 'line', source: 'offline-osm', 'source-layer': 'boundary',
                  filter: ['<=', ['get', 'admin_level'], 2],
                  paint: { 'line-color': '#a08bb0', 'line-width': 1.2 } },
                // Regions/provinces: more subtle, visible when zooming in
                { id: 'boundaries-region', type: 'line', source: 'offline-osm', 'source-layer': 'boundary',
                  filter: ['all', ['>', ['get', 'admin_level'], 2], ['<=', ['get', 'admin_level'], 4]],
                  minzoom: 7,
                  paint: { 'line-color': '#c0b0cc', 'line-width': 0.8, 'line-dasharray': [2, 2] } },

                // --- Country labels (visible when zoomed out) ---
                { id: 'place-labels-country', type: 'symbol', source: 'offline-osm', 'source-layer': 'place',
                  filter: ['==', ['get', 'class'], 'country'],
                  layout: {
                      'text-field': ['get', 'name'],
                      'text-font': ['Noto Sans Regular'],
                      'text-size': ['interpolate', ['linear'], ['zoom'], 2, 12, 6, 18],
                      'text-letter-spacing': 0.05
                  },
                  paint: {
                      'text-color': '#5b4a66',
                      'text-halo-color': '#eef0e8',
                      'text-halo-width': 1.5
                  } },

                // --- Cities and places labels ---
                { id: 'place-labels-major', type: 'symbol', source: 'offline-osm', 'source-layer': 'place',
                  filter: ['in', ['get', 'class'], ['literal', ['city', 'town']]],
                  minzoom: 4,
                  layout: {
                      'text-field': ['get', 'name'],
                      'text-font': ['Noto Sans Regular'],
                      'text-size': ['interpolate', ['linear'], ['zoom'], 4, 10, 12, 16],
                      'text-variable-anchor': ['top', 'bottom', 'left', 'right'],
                      'text-radial-offset': 0.5
                  },
                  paint: {
                      'text-color': '#1f2937',
                      'text-halo-color': '#ffffff',
                      'text-halo-width': 1.4
                  } },
                { id: 'place-labels-minor', type: 'symbol', source: 'offline-osm', 'source-layer': 'place',
                  filter: ['in', ['get', 'class'], ['literal', ['village', 'hamlet', 'suburb']]],
                  minzoom: 11,
                  layout: {
                      'text-field': ['get', 'name'],
                      'text-font': ['Noto Sans Regular'],
                      'text-size': 11,
                      'text-variable-anchor': ['top', 'bottom', 'left', 'right'],
                      'text-radial-offset': 0.5
                  },
                  paint: {
                      'text-color': '#475569',
                      'text-halo-color': '#ffffff',
                      'text-halo-width': 1.2
                  } }
            ]
        };
    }
    return ONLINE_RASTER_STYLE;
}

/**
 * Checks whether the local tile server is available.
 */
function probeLocalTiles(timeoutMs = 1500) {
    return new Promise(resolve => {
        const controller = new AbortController();
        const timer = setTimeout(() => { controller.abort(); resolve(null); }, timeoutMs);
        fetch(LOCAL_TILEJSON_URL, { signal: controller.signal })
            .then(res => res.json())
            .then(json => { clearTimeout(timer); resolve(json); })
            .catch(() => { clearTimeout(timer); resolve(null); });
    });
}

/**
 * Checks whether we actually have internet access, as opposed to just
 * having a local tile server running. navigator.onLine is not reliable
 * (it only reflects the network interface, not real reachability), so
 * we do a real network probe against a public endpoint instead.
 */
function checkInternetAccess(timeoutMs = 2000) {
    return new Promise(resolve => {
        const controller = new AbortController();
        const timer = setTimeout(() => { controller.abort(); resolve(false); }, timeoutMs);
        fetch('https://tile.openstreetmap.org/0/0/0.png', {
            method: 'HEAD',
            mode: 'no-cors',
            cache: 'no-store',
            signal: controller.signal
        })
            .then(() => { clearTimeout(timer); resolve(true); })
            .catch(() => { clearTimeout(timer); resolve(false); });
    });
}

/**
 * Decides which street style to use: local vector tiles are only used
 * as a fallback when there is genuinely no internet access, even if
 * the local tile server happens to be running (e.g. always-on in Docker).
 */
function resolveStreetTileJson() {
    return Promise.all([checkInternetAccess(), probeLocalTiles()])
        .then(([hasInternet, tileJson]) => (hasInternet ? null : tileJson));
}

// ---------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------
resolveStreetTileJson().then(tileJson => {
    offlineMode = !!tileJson;

    map = new maplibregl.Map({
        container: 'map',
        style: buildStreetStyle(tileJson),
        center: tileJson && tileJson.bounds
            ? [(tileJson.bounds[0] + tileJson.bounds[2]) / 2, (tileJson.bounds[1] + tileJson.bounds[3]) / 2]
            : [-3.7, 40.0],
        zoom: 5,
        minZoom: 3,
        maxZoom: 20  // Beyond the tile maxzoom (14), MapLibre
                     // automatically overzooms vector tiles.
                     // This remains sharp because vectors are used
                     // instead of pixels (similar to OpenFreeMap)
    });

    // Automatically adjusts the initial zoom so the entire
    // downloaded area fits in the viewport
    if (tileJson && tileJson.bounds) {
        map.fitBounds(
            [[tileJson.bounds[0], tileJson.bounds[1]], [tileJson.bounds[2], tileJson.bounds[3]]],
            { padding: 20, animate: false }
        );
    }

    if (offlineMode) {
        document.getElementById('offlineIndicator').style.display = 'flex';
    }

    map.on('load', () => {
        loadCountryBorders();
        window.__mapInstance = map;
        initWaypoints(map);
        initZoneDrawing(map);
        if (window.markMapReady) window.markMapReady();
    });
});

// ---------------------------------------------------------------
// Country borders (local GeoJSON) - shown in satellite mode
// ---------------------------------------------------------------
function loadCountryBorders() {
    fetch('data/countries.geojson')
        .then(res => res.json())
        .then(data => {
            map.addSource('country-borders', { type: 'geojson', data });
            map.addLayer({
                id: 'country-borders-layer',
                type: 'line',
                source: 'country-borders',
                paint: { 'line-color': '#ffffff', 'line-width': 1.5, 'line-opacity': 0.8 },
                layout: { visibility: 'none' }
            });
        })
        .catch(() => console.warn('countries.geojson unavailable'));
}

// ---------------------------------------------------------------
// Street / Satellite toggle
// ---------------------------------------------------------------
const toggleBtn = document.getElementById('toggleMap');

function updateButton() {
    toggleBtn.innerText = isSatellite ? 'Map' : 'Satellite';
}

toggleBtn.onclick = function () {
    if (!map) return;

    if (isSatellite) {
        resolveStreetTileJson().then(tileJson => map.setStyle(buildStreetStyle(tileJson)));
    } else {
        map.setStyle(SATELLITE_STYLE);
    }

    // Reattach border layer after style changes
    // (setStyle resets all custom sources/layers).
    map.once('styledata', () => {
        if (!map.getSource('country-borders')) {
            loadCountryBorders();
        }
        if (map.getLayer('country-borders-layer')) {
            map.setLayoutProperty('country-borders-layer', 'visibility', isSatellite ? 'visible' : 'none');
        }
    });

    isSatellite = !isSatellite;
    updateButton();
};