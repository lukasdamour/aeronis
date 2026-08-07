const missionConfigState = {
    finishAction: 'goHome',
};

let llmPanelOpen = false;

function toggleLlmPanel() {
    llmPanelOpen = !llmPanelOpen;
    const panel = document.getElementById('llm-panel');
    const bubble = document.getElementById('llm-bubble');
    if (panel) panel.style.display = llmPanelOpen ? 'block' : 'none';
    if (bubble) bubble.textContent = llmPanelOpen ? '✕' : '✨';
    if (llmPanelOpen) loadLlmConfig();
}

function setLlmTab(tab) {
    const isGenerate = tab === 'generate';
    document.getElementById('llm-tab-generate')?.classList.toggle('active', isGenerate);
    document.getElementById('llm-tab-edit')?.classList.toggle('active', !isGenerate);
    document.getElementById('llm-tab-panel-generate').style.display = isGenerate ? 'block' : 'none';
    document.getElementById('llm-tab-panel-edit').style.display = isGenerate ? 'none' : 'block';
}

async function loadLlmConfig() {
    const status = document.getElementById('llm-status');
    try {
        const res = await fetch('/api/llm/config');
        const data = await res.json();
        if (!data.ok) return;

        llmInstalledModels = data.local.installed_models || [];
        populateModelSelect(data.local.default_model);

        if (status) {
            status.textContent = (llmInstalledModels.length === 0)
                ? 'No local model detected -- run "ollama pull llama3.1" or pick another installed model.'
                : '';
        }
    } catch (err) {
        if (status) status.textContent = 'Backend unreachable (is Ollama / server.py running?).';
    }
}

let llmInstalledModels = [];

function populateModelSelect(defaultModel) {
    const modelSelect = document.getElementById('llm-model');
    if (!modelSelect) return;

    if (llmInstalledModels.length === 0) {
        modelSelect.innerHTML = `<option value="${defaultModel || ''}">${defaultModel || 'model...'}</option>`;
        return;
    }

    modelSelect.innerHTML = llmInstalledModels
        .map(name => `<option value="${name}">${name}</option>`)
        .join('');
}

async function submitLlmPrompt() {
    const textarea = document.getElementById('llm-prompt');
    const button = document.getElementById('llm-submit');
    const box = document.getElementById('llm-reasoning');
    const loading = document.getElementById('llm-loading');

    const prompt = (textarea?.value || '').trim();
    if (!prompt) return;

    const model = (document.getElementById('llm-model')?.value || '').trim() || null;

    button.disabled = true;
    if (loading) loading.style.display = 'block';
    if (box) { box.style.display = 'none'; box.classList.remove('err'); }

    try {
        const res = await api('/api/llm/plan', {
            prompt,
            model,
            current_params: (typeof ZONE_PARAMS !== 'undefined') ? ZONE_PARAMS : null,
        });

        if (!res.ok) {
            showLlmMessage(res.error || 'Unknown error', true);
            return;
        }

        if (res.mode === 'place') {
            await applyLlmPlaceResult(res);
        } else {
            await applyLlmPlan(res.plan);
        }

        const summary = `Altitude ${res.plan.altitude}m · Speed ${res.plan.speed}m/s · `
            + `Overlap ${Math.round(res.plan.overlap * 100)}% · Angle ${res.plan.angle}° · `
            + `${res.plan.drone} · ${res.plan.capture_mode} · finish: ${res.plan.finish_action}`;
        const locationLine = res.mode === 'place' ? `📍 ${res.place_name}\n` : '';
        showLlmMessage(`${locationLine}${res.plan.reasoning || ''}\n${summary}`.trim(), false);
    } catch (err) {
        showLlmMessage('Server unavailable (run server.py).', true);
    } finally {
        button.disabled = false;
        if (loading) loading.style.display = 'none';
    }
}

function showLlmMessage(text, isError) {
    const box = document.getElementById('llm-reasoning');
    if (!box) return;
    box.textContent = text;
    box.style.display = 'block';
    box.classList.toggle('err', !!isError);
}


async function applyLlmPlaceResult(res) {
    if (typeof draw !== 'undefined' && draw && res.polygon && res.polygon.length >= 3) {
        const ring = res.polygon.concat([res.polygon[0]]); // close the ring
        const feature = {
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [ring] },
            properties: {},
        };
        draw.deleteAll();
        const [id] = draw.add(feature);
        feature.id = id;
        if (typeof onZoneFinalized === 'function') onZoneFinalized(feature);

        if (window.__mapInstance) {
            const lons = res.polygon.map(p => p[0]);
            const lats = res.polygon.map(p => p[1]);
            window.__mapInstance.fitBounds(
                [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
                { padding: 80, animate: true }
            );
        }
    }

    missionConfigState.finishAction = res.plan.finish_action;

    const setVal = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    };
    setVal('zone-altitude', res.plan.altitude);
    setVal('zone-speed', res.plan.speed);
    setVal('zone-overlap', Math.round(res.plan.overlap * 100));
    setVal('zone-angle', res.plan.angle);
    setVal('zone-drone', res.plan.drone);
    setVal('split-value', res.plan.max_waypoints_per_mission);

    ZONE_PARAMS.altitude = res.plan.altitude;
    ZONE_PARAMS.speed = res.plan.speed;
    ZONE_PARAMS.overlap = res.plan.overlap;
    ZONE_PARAMS.angle = res.plan.angle;
    ZONE_PARAMS.drone = res.plan.drone;
    ZONE_PARAMS.capture_mode = res.plan.capture_mode;
    ['photo', 'video', 'none'].forEach(m => {
        const btn = document.getElementById(`mode-btn-${m}`);
        if (btn) btn.classList.toggle('active', m === res.plan.capture_mode);
    });
    if (typeof currentMissionMode !== 'undefined') currentMissionMode = res.plan.capture_mode;

    if (typeof onSplitValueChange === 'function') onSplitValueChange();

    if (typeof finalizeMissionFromWaypoints === 'function') {
        await finalizeMissionFromWaypoints(res.waypoints);
    } else {
        wpState.waypoints = res.waypoints;
        wpState.selected = null;
        if (window.__mapInstance) refreshWpMap(window.__mapInstance);
        if (typeof refreshWpPanel === 'function') refreshWpPanel();
        if (typeof snapshotHistory === 'function') snapshotHistory();
    }
}


async function applyLlmPlan(plan) {
    const setVal = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    };

    setVal('zone-altitude', plan.altitude);
    setVal('zone-speed', plan.speed);
    setVal('zone-overlap', Math.round(plan.overlap * 100));
    setVal('zone-angle', plan.angle);
    setVal('zone-drone', plan.drone);
    setVal('split-value', plan.max_waypoints_per_mission);

    missionConfigState.finishAction = plan.finish_action;

    if (typeof onZoneParamChange === 'function') onZoneParamChange();
    if (typeof onSplitValueChange === 'function') onSplitValueChange();
    if (typeof setMissionMode === 'function') setMissionMode(plan.capture_mode);

    clearTimeout(zoneGenerateTimer);
    if (typeof activeZoneFeatureId !== 'undefined' && activeZoneFeatureId) {
        if (typeof commitZonePreview === 'function') await commitZonePreview();
    } else if (typeof wpToast === 'function') {
        wpToast('Parameters updated -- draw or select a zone on the map to generate the mission', '');
    }
}


function buildMissionConfig() {
    return {
        name: 'DJI Mission',
        drone: document.getElementById('zone-drone')?.value || 'MAVIC_3',
        finishAction: missionConfigState.finishAction,
        transitSpeed: parseFloat(document.getElementById('zone-speed')?.value) || 10,
        heightMode: 'relativeToStartPoint',
    };
}


async function submitLlmEditPrompt() {
    const textarea = document.getElementById('llm-edit-prompt');
    const button = document.getElementById('llm-edit-submit');
    const box = document.getElementById('llm-edit-reasoning');
    const loading = document.getElementById('llm-edit-loading');
    const status = document.getElementById('llm-edit-status');

    const prompt = (textarea?.value || '').trim();
    if (!prompt) return;

    if (!wpState.waypoints || wpState.waypoints.length < 2) {
        if (status) status.textContent = 'Need at least 2 waypoints on the map to edit.';
        return;
    }

    const model = (document.getElementById('llm-model')?.value || '').trim() || null;

    button.disabled = true;
    if (loading) loading.style.display = 'block';
    if (box) { box.style.display = 'none'; box.classList.remove('err'); }
    if (status) status.textContent = '';

    try {
        const res = await api('/api/llm/edit', {
            prompt,
            model,
            waypoints: wpState.waypoints,
            config: (typeof buildMissionConfig === 'function') ? buildMissionConfig() : null,
        });

        if (!res.ok) {
            showLlmEditMessage(res.error || 'Unknown error', true);
            return;
        }

        wpState.waypoints = res.waypoints;
        if (typeof refreshWpMap === 'function' && window.__mapInstance) refreshWpMap(window.__mapInstance);
        if (typeof refreshWpPanel === 'function') refreshWpPanel();
        if (typeof snapshotHistory === 'function') snapshotHistory();
        if (typeof syncActiveMissionFromWpState === 'function') syncActiveMissionFromWpState();

        const summary = (res.applied && res.applied.length)
            ? res.applied.join(' · ')
            : 'Nothing to change for this request.';
        showLlmEditMessage(`${res.reasoning || ''}\n${summary}`.trim(), false);
        if (typeof wpToast === 'function') wpToast('Mission edited', 'ok');
    } catch (err) {
        showLlmEditMessage('Server unavailable (run server.py).', true);
    } finally {
        button.disabled = false;
        if (loading) loading.style.display = 'none';
    }
}

function showLlmEditMessage(text, isError) {
    const box = document.getElementById('llm-edit-reasoning');
    if (!box) return;
    box.textContent = text;
    box.style.display = 'block';
    box.classList.toggle('err', !!isError);
}
