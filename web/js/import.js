let dragOverlayDepth = 0;

async function importMissionFile(file) {
    if (!file) return;

    const isSupported = /\.(kmz|kml|wpml)$/i.test(file.name);
    if (!isSupported) {
        wpToast('Unsupported file type (.kmz expected)', 'err');
        return;
    }

    if (wpState.waypoints.length > 0) {
        const proceed = await showConfirm(`This will replace the ${wpState.waypoints.length} existing waypoint(s). Continue?`);
        if (!proceed) return;
    }

    const reader = new FileReader();
    reader.onload = async (e) => {
        const bytes = new Uint8Array(e.target.result);
        let binary = '';
        const chunkSize = 8192;
        for (let i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
        }
        const b64 = btoa(binary);

        let res;
        try {
            res = await api('/api/import', { kmz_b64: b64});
        } catch (err) {
            wpToast('API server unavailable (run server.py)', 'err');
            return;
        }

        if (!res.ok) {
            wpToast('Import failed: ' + res.error, 'err');
            return;
        }

        // If several missions had previously been generated (e.g. via a zone
        // split into multiple sub-missions), importing a new file replaces
        // the whole plan, so all of them must be discarded first.
        if (typeof clearMissionSplit === 'function') clearMissionSplit();

        wpState.waypoints = res.waypoints;
        wpState.selected = null;
        refreshWpMap(window.__mapInstance);
        refreshWpPanel();
        if (typeof snapshotHistory === 'function') snapshotHistory();

        if (wpState.waypoints.length && window.__mapInstance) {
            const lons = wpState.waypoints.map(w => w.lon);
            const lats = wpState.waypoints.map(w => w.lat);
            window.__mapInstance.fitBounds(
                [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
                { padding: 60, animate: true }
            );
        }
        wpToast(`${res.stats.waypoints} waypoint(s) imported from ${file.name}`, 'ok');
    };
    reader.readAsArrayBuffer(file);
}


function initImportDropZone() {
    const zone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    if (!zone || !fileInput) return;

    fileInput.addEventListener('change', (e) => {
        importMissionFile(e.target.files[0]);
        fileInput.value = '';
    });

    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('drag');
    });

    zone.addEventListener('dragleave', () => {
        zone.classList.remove('drag');
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('drag');
        importMissionFile(e.dataTransfer.files[0]);
    });
}


function initGlobalDropOverlay() {
    const overlay = document.getElementById('drag-overlay');
    if (!overlay) return;

    window.addEventListener('dragenter', (e) => {
        e.preventDefault();
        dragOverlayDepth++;
        overlay.classList.add('visible');
    });

    window.addEventListener('dragover', (e) => {
        e.preventDefault();
    });

    window.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dragOverlayDepth = Math.max(0, dragOverlayDepth - 1);
        if (dragOverlayDepth === 0) overlay.classList.remove('visible');
    });

    window.addEventListener('drop', (e) => {
        e.preventDefault();
        dragOverlayDepth = 0;
        overlay.classList.remove('visible');
        const file = e.dataTransfer.files && e.dataTransfer.files[0];
        importMissionFile(file);
    });
}

initImportDropZone();
initGlobalDropOverlay();