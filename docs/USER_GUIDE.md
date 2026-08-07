# User Guide -- Web App

This guide covers the web/desktop interface: drawing coverage zones, editing waypoints, choosing a capture mode, importing and exporting missions, and using the local AI assistant. For the command-line tool, see [CLI_DOCUMENTATION.md](CLI_DOCUMENTATION.md).

## Table of Contents

- [User Guide -- Web App](#user-guide----web-app)
  - [Table of Contents](#table-of-contents)
  - [Opening the app](#opening-the-app)
  - [The map and the waypoint panel](#the-map-and-the-waypoint-panel)
  - [Drawing a coverage zone](#drawing-a-coverage-zone)
  - [Editing waypoints manually](#editing-waypoints-manually)
  - [Multiple missions and automatic splitting](#multiple-missions-and-automatic-splitting)
  - [Capture modes: photo, video, GSD](#capture-modes-photo-video-gsd)
  - [Importing and exporting missions](#importing-and-exporting-missions)
  - [Undo / redo](#undo--redo)
  - [The AI assistant](#the-ai-assistant)
  - [Offline maps](#offline-maps)
  - [Troubleshooting](#troubleshooting)

---

## Opening the app

Once the server is running (see the main [README](../README.md) or the [Deployment Guide](DEPLOYMENT.md)), open it in a browser at `http://localhost:8000` (Docker) or `http://127.0.0.1:5000` (running `server.py` directly). The desktop build opens the same interface in its own window -- no browser needed.

A short splash screen with the app logo appears while the map finishes loading, then fades into the main view.

## The map and the waypoint panel

The main view has two parts:

- **The map**, showing your current position (or a default view) with vector tiles from either the public OpenStreetMap servers or your own offline tile server.
- **The waypoint panel**, listing every waypoint of the currently active mission in order, with its coordinates, altitude, speed and camera actions. Waypoints can be reordered here by dragging.

Each waypoint also appears as a numbered marker on the map. Clicking a marker selects it (highlighted in both the map and the panel); dragging a marker moves the waypoint.

## Drawing a coverage zone

Rather than placing waypoints one by one, you can draw the area you want covered and let the tool generate a full lawnmower-pattern mission for you:

1. Choose **rectangle** or **polygon** zone mode from the toolbar.
2. Draw the zone on the map: click-drag for a rectangle, or click each vertex in turn for a polygon (double-click or click the first point again to close it).
3. A live preview of the generated waypoints appears as you adjust the zone or its parameters -- altitude, speed, drone model, overlap percentage, and rotation angle. Adjusting the angle changes the flight-line direction, useful for aligning passes with the long side of a field or a prevailing wind.
4. Confirm to commit the preview into the active mission's waypoint list.

The zone generator uses the classic photogrammetry pattern: parallel flight lines spaced according to the requested photo overlap for the chosen drone's camera, with a point-in-polygon check so waypoints stay inside the drawn area, followed by a path-simplification pass to remove redundant points.

> **⚠️ Warning -- avoid drawing very large zones.** There's no upper limit on the size of a zone or the resulting number of flight lines/waypoints. A very large zone (especially combined with a low altitude and/or high overlap, which both increase flight-line density) can generate an extremely large number of waypoints and freeze or crash the app; in that case, a computer restart may be needed to recover. Start with a smaller zone or a higher altitude/lower overlap, and increase from there.

## Editing waypoints manually

After generating a zone (or starting from scratch), you can fine-tune individual waypoints:

- **Add**: click on the map in "add waypoint" mode to append a new point.
- **Move**: drag an existing marker.
- **Delete**: select a waypoint and remove it from the panel.
- **Edit fields**: altitude, speed, gimbal pitch, and camera actions (take photo, start/stop record, hover, rotate yaw, rotate gimbal) can all be edited per waypoint in the panel.

## Multiple missions and automatic splitting

DJI's RC2 controller becomes unreliable above roughly 200 waypoints in a single mission. If a drawn zone would generate more than that, it's automatically split into several missions, shown as tabs above the waypoint panel. Each mission can be edited, previewed, and exported independently, or all together as a single `.zip` of `.kmz` files.

You can adjust the split threshold (waypoints per mission) in the zone parameters before committing a zone.

## Capture modes: photo, video, GSD

Two capture modes cover most survey use cases:

- **Photo mode** places a `takePhoto` action at every waypoint, with spacing computed for a target overlap percentage given the selected drone's real camera specs.
- **Video mode** replaces discrete photo triggers with a single record-start action at the beginning of the mission and record-stop at the end, for continuous video capture.

While editing altitude or the drone model, a live **Ground Sample Distance (GSD)** readout shows the resulting image resolution on the ground (cm/pixel), computed client-side from the same camera database the server uses for photo spacing -- so it updates instantly, with no round-trip to the server.

## Importing and exporting missions

- **Import**: drag and drop a `.kmz` (or `.kml`/`.wpml`) file onto the app, or use the import button. This replaces the current mission's waypoints after confirmation -- export or duplicate anything you want to keep first.
- **Export**: download the active mission as a `.kmz`, ready to load into DJI Pilot 2 / DJI Fly. If several missions exist (see splitting above), you can export all of them at once as a single `.zip`.

Sample mission files are available under `samples/` in the repository if you want to try importing something before flying your own.

## Undo / redo

Every mutating action (adding, moving, deleting a waypoint; importing a mission; running the AI assistant; switching capture mode) is snapshotted. Use `Ctrl+Z` / `Ctrl+Y` (or the toolbar buttons) to step backward and forward. Undo/redo applies to whichever mission tab is currently displayed, not across tabs if a zone was split into several missions.

## The AI assistant

The assistant panel (opened from the bubble in the corner of the map) lets you describe what you want in plain language instead of clicking through zone parameters:

- **Generate tab**: describe a place and a mission -- *"survey the stadium at 100m altitude with 85% overlap"* -- and the assistant geocodes the place name, draws a matching zone, and generates the waypoints. You can also describe changes to the current parameters without naming a place.
- **Edit tab**: describe a change to the mission you already have -- *"lower altitude to 60m and switch to video mode"* -- and the assistant applies it to the existing waypoints. It only ever calls the same editing operations available in the UI (set altitude, set speed, add/remove a camera action, reverse direction, simplify path); it never touches waypoint coordinates directly, so your drawn flight path is never silently rewritten.

The assistant runs entirely on a local [Ollama](https://ollama.com) model -- nothing is sent to a cloud API. If Ollama isn't running or isn't reachable, the panel reports that the assistant is unavailable rather than failing silently; see [Deployment Guide § Ollama](DEPLOYMENT.md#giving-the-app-access-to-ollama) if you're setting this up yourself.

## Offline maps

If no internet connection is available in the field, the app can serve its own map tiles from a `.mbtiles` file instead of fetching them from the public OpenStreetMap servers. This requires the offline tile server to be running and a tile file to be present -- see the [Deployment Guide](DEPLOYMENT.md) for how to generate and serve one. When it isn't configured, the app falls back to the public tile servers and simply needs an internet connection.

## Troubleshooting

**The map doesn't load / stays blank.** Check that the app container (or `server.py`) is actually running and reachable at the port you're using -- see [Deployment Guide § Diagnosing a Docker deployment](DEPLOYMENT.md#diagnosing-a-docker-deployment) for the common causes.

**"Assistant unavailable" in the AI panel.** Ollama isn't reachable from the app. See [Deployment Guide § Ollama](DEPLOYMENT.md#giving-the-app-access-to-ollama).

**Import fails with an error.** Only `.kmz` (and the `.kml`/`.wpml` files inside one) produced by a compatible WPML version are supported; very old or heavily customized mission files may use fields this tool doesn't parse yet.

**A generated zone has far more waypoints than expected.** Check the overlap percentage and altitude -- lower altitude and higher overlap both increase flight-line density, and therefore waypoint count, for the same area.

**The app freezes or crashes after drawing a zone.** This usually happens with very large zones -- see the warning in [Drawing a coverage zone](#drawing-a-coverage-zone). Draw a smaller zone, or raise the altitude / lower the overlap to reduce the number of flight lines, then retry.
