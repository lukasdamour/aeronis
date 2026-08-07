// ===========================================================
// Aeronis - undo/redo for waypoint edits.
//
// Snapshots the currently *displayed* mission (wpState.waypoints) as a
// JSON string after every mutating action (add/delete/move/edit a
// waypoint, import a KMZ, generate/edit a mission via the AI assistant,
// change capture mode, clear all). Ctrl+Z / Ctrl+Y (or the toolbar
// buttons) step through that history.
//
// Scope note: this tracks the single mission currently shown in the
// waypoint list. If a mission was split into several battery-limited
// chunks (see zones.js commitZonePreview), undo/redo applies to
// whichever chunk is currently displayed, not across chunks.
// ===========================================================

const undoState = {
    stack: [],
    pointer: -1,
    maxSize: 50,
};

/**
 * Call this right after any action that mutates wpState.waypoints.
 * Truncates any redo branch, so making a new edit after undoing
 * discards the old "future".
 */
function snapshotHistory() {
    undoState.stack = undoState.stack.slice(0, undoState.pointer + 1);
    undoState.stack.push(JSON.stringify(wpState.waypoints));
    if (undoState.stack.length > undoState.maxSize) {
        undoState.stack.shift();
    }
    undoState.pointer = undoState.stack.length - 1;
    updateUndoRedoButtons();
}

function undoEdit() {
    if (undoState.pointer <= 0) return;
    undoState.pointer--;
    restoreHistorySnapshot();
}

function redoEdit() {
    if (undoState.pointer >= undoState.stack.length - 1) return;
    undoState.pointer++;
    restoreHistorySnapshot();
}

function restoreHistorySnapshot() {
    wpState.waypoints = JSON.parse(undoState.stack[undoState.pointer]);
    wpState.selected = null;
    if (window.__mapInstance) refreshWpMap(window.__mapInstance);
    if (typeof refreshWpPanel === 'function') refreshWpPanel();
    if (typeof syncActiveMissionFromWpState === 'function') syncActiveMissionFromWpState();
    updateUndoRedoButtons();
}

function updateUndoRedoButtons() {
    const undoBtn = document.getElementById('undo-btn');
    const redoBtn = document.getElementById('redo-btn');
    if (undoBtn) undoBtn.disabled = undoState.pointer <= 0;
    if (redoBtn) redoBtn.disabled = undoState.pointer >= undoState.stack.length - 1;
}

document.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (!mod) return;
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea') return; // don't hijack text-field undo

    const key = e.key.toLowerCase();
    if (key === 'z' && !e.shiftKey) {
        e.preventDefault();
        undoEdit();
    } else if (key === 'y' || (key === 'z' && e.shiftKey)) {
        e.preventDefault();
        redoEdit();
    }
});

// Seed history with the initial (empty) state once the page has loaded.
document.addEventListener('DOMContentLoaded', () => snapshotHistory());
