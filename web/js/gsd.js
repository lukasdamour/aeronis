// ===========================================================
// Aeronis - live Ground Sample Distance (GSD) display.
//
// Mirrors the formula in core/flight_modes.py::compute_gsd:
//     gsd_cm_per_px = (sensor_dim_mm / focal_length_mm) * altitude_m * 100 / image_dim_px
//
// Camera specs (sensor size, focal length, resolution) are fetched
// once from /api/camera-specs (backed by the same core.flight_modes.
// DRONE_CAMERAS database used server-side for photo spacing) and
// cached client-side, so GSD updates instantly as altitude/drone
// change -- no network round-trip per keystroke.
// ===========================================================

let droneCameraSpecs = {};

async function loadCameraSpecs() {
    try {
        const res = await fetch('/api/camera-specs');
        const data = await res.json();
        if (data.ok) droneCameraSpecs = data.cameras;
    } catch (err) {
        console.warn('Could not load camera specs for GSD display', err);
    }
}

/**
 * Returns { x, y } GSD in cm/px for the given altitude (m) and drone
 * model, or null if the drone isn't in the camera database or the
 * altitude isn't usable yet.
 */
function computeGsdCm(altitudeM, droneModel) {
    const cam = droneCameraSpecs[(droneModel || '').toUpperCase()];
    if (!cam || !altitudeM || altitudeM <= 0) return null;

    const gsdX = (cam.sensor_width_mm / cam.focal_length_mm) * altitudeM * 100.0 / cam.image_width_px;
    const gsdY = (cam.sensor_height_mm / cam.focal_length_mm) * altitudeM * 100.0 / cam.image_height_px;
    return { x: gsdX, y: gsdY };
}

/**
 * Updates the #st-gsd stat box from the mission's average altitude and
 * the currently selected drone. Called from refreshWpPanel().
 */
function updateGsdDisplay(avgAltitudeM) {
    const el = document.getElementById('st-gsd');
    if (!el) return;

    const drone = document.getElementById('zone-drone')?.value || 'MAVIC_3';
    const gsd = computeGsdCm(avgAltitudeM, drone);
    el.textContent = gsd ? `${gsd.x.toFixed(1)} cm/px` : '-';
}

document.addEventListener('DOMContentLoaded', loadCameraSpecs);
