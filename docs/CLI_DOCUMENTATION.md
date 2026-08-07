# Aeronis CLI - Complete Documentation

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Help and Usage](#help-and-usage)
5. [Features](#features)
6. [Command Reference](#command-reference)
7. [Input Formats](#input-formats)
8. [Examples](#examples)
9. [Advanced Usage](#advanced-usage)

---

## Overview

**Aeronis CLI** is a command-line tool designed to create, inspect, validate, transform, and optimize DJI KMZ (Keyhole Markup Language Zipped) mission files. It enables users to programmatically manage drone missions with precise control over waypoints, camera actions, flight parameters, and survey patterns.

### Target Users

- Drone operators managing complex multi-waypoint missions
- Survey professionals generating systematic coverage patterns
- Researchers automating mission workflows
- Integration systems requiring mission file manipulation

### Supported Formats

- **Input:** KMZ mission files, CSV waypoint lists
- **Output:** KMZ mission files
- **Drones:** Multiple DJI models (MAVIC_3, MAVIC_2, PHANTOM_4, etc.)

---

## Installation

### Prerequisites

- Python 3.8 or later
- `typer` CLI framework
- `rich` for formatted console output

### Setup

```bash
# Install from source
pip install -e .

# Verify installation
aeronis --help
```

---

## Quick Start

### Basic Mission Reading

```bash
aeronis read mission.kmz
```

### Create a Mission from CSV

```bash
aeronis create waypoints.csv output.kmz --name "My Mission" --altitude 80 --speed 5
```

### Generate a Survey Grid

```bash
aeronis grid --lon 55.45 --lat -20.88 --width 200 --height 150 -o grid_mission.kmz
```

---

## Help and Usage

### Displaying the Main Help

#### Command: `aeronis`

**Behavior:** Running the command without arguments or subcommand displays the main help panel.

```bash
$ aeronis
```

**Output:**
```
╭─────────────────────────────────────── Aeronis ────────────────────────────────────────╮
│ Aeronis CLI                                                                            │
│                                                                                        │
│ A command-line tool to create, inspect, validate, transform and optimiize DJI KMZ      │
│ missions.                                                                              │
│                                                                                        │
│ FEATURES                                                                               │
│   - Read and inspect existing DJI missions                                             │
│   - Validate waypoint structure and mission parameters                                 │
│   - Create missions from CSV waypoint files                                            │
│   - Simplify waypoint paths using Ramer-Douglas-Peucker (RDP) algorithm                │
│   - Generate rectangular survey grids                                                  │
│   - Generate polygon survey missions                                                   │
│   - Convert missions to video mode                                                     │
│   - Optimize missions for photo capture                                                │
│                                                                                        │
│ COMMANDS                                                                               │
│   read          Parse and display a KMZ mission                                        │
│   validate      Validate a KMZ mission                                                 │
│   create        Create a mission from CSV                                              │
│   simplify      Simplify waypoint paths                                                │
│   grid          Generate rectangular survey grid                                       │
│   polygon       Generate polygon survey mission                                        │
│   video         Convert mission to video mode                                          │
│   photo         Optimize mission for photo capture                                     │
│                                                                                        │
│ EXAMPLES                                                                               │
│   aeronis read mission.kmz                                                             │
│   aeronis validate mission.kmz                                                         │
│   aeronis create input.csv output.kmz                                                  │
│   aeronis grid --lon 55.45 --lat -20.88 --width 200 --height 150                       │
│   aeronis polygon --coords "55.44,-20.88 55.45,-20.87"                                 │
│   aeronis video mission.kmz video.kmz                                                  │
│   aeronis photo mission.kmz photo.kmz --overlap 0.80 --drone MAVIC_3                   │
│                                                                                        │
│ For detailed help on a specific command:                                               │
│     aeronis COMMAND --help                                                             │
╰────────────────────────────────── CLI Documentation ───────────────────────────────────╯
```

**Use Case:** Quick reference of all available commands and basic usage examples.

---

#### Command: `aeronis --help` or `aeronis -h`

**Behavior:** Displays the same main help panel as running without arguments.

```bash
$ aeronis --help
$ aeronis -h
```

**Output:** Same as above (main help panel with all available commands)

**Use Case:** When you need a reminder of available commands or basic usage syntax.

---

### Displaying Command-Specific Help

#### Command: `aeronis <command>` (without arguments)

**Behavior:** Running a specific command without required arguments automatically displays that command's help information.

**Example with `read` command:**

```bash
$ aeronis read
```

**Output:**
```
Usage: aeronis read [OPTIONS] INPUT

Parse and display a KMZ mission file.

Options:
  -v, --verbose  Display full waypoint-by-waypoint details instead of a
                 summary.
  -h, --help     Show this message and exit.
```

**Example with `grid` command:**

```bash
$ aeronis grid
```

**Output:**
```
Usage: aeronis grid [OPTIONS] -o TEXT

Generate rectangular survey grid.

Options:
  --lon FLOAT           Center longitude (degrees)  [required]
  --lat FLOAT           Center latitude (degrees)  [required]
  -w, --width FLOAT     Grid width (meters)  [default: 200]
  --height FLOAT        Grid height (meters)
  --spacing FLOAT       Waypoint spacing (meters)  [default: 50]
  -a, --altitude FLOAT  Altitude (meters)  [default: 80]
  -s, --speed FLOAT     Speed (m/s)  [default: 5]
  --angle FLOAT         Grid rotation angle (degrees)  [default: 0]
  -n, --name TEXT       Mission name  [default: Grid Mission]
  -o TEXT               Output file  [required]
  --no-photo            Disable photo triggers
  -h, --help            Show this message and exit.
```

**Use Case:** Learn about a specific command's options and required parameters.

---

#### Command: `aeronis <command> --help` or `aeronis <command> -h`

**Behavior:** Explicitly requests help for a specific command (same as running without arguments).

```bash
$ aeronis validate --help
$ aeronis create -h
$ aeronis polygon --help
```

**Output:** Command-specific help with all available options and parameters.

**Use Case:** Detailed exploration of a command's capabilities and options.

---

## Features

### Core Capabilities

| Feature | Description |
|---------|-------------|
| **Read** | Parse and display existing DJI mission files with summary or verbose output |
| **Validate** | Check mission structure, waypoint parameters, and constraints |
| **Create** | Build missions from CSV waypoint lists with custom parameters |
| **Simplify** | Reduce waypoint count using Ramer-Douglas-Peucker (RDP) algorithm |
| **Grid** | Generate rectangular survey patterns with configurable spacing |
| **Polygon** | Create survey missions following a polygon boundary with camera overlap |
| **Video** | Convert missions to video recording mode |
| **Photo** | Optimize missions for photo capture with calculated spacing |

### Mission Manipulation

- **Waypoint Management:** Add, remove, or modify waypoints
- **Camera Actions:** Automatic photo trigger placement and video mode configuration
- **Flight Parameters:** Control speed, altitude, pitch angle, and flight modes
- **Path Optimization:** Simplify complex paths while maintaining coverage
- **Survey Generation:** Create systematic patterns for mapping and inspection

---

## Command Reference

### `read` - Parse and Display KMZ Missions

Display mission information and waypoint details from a KMZ file.

```bash
aeronis read <input> [OPTIONS]
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `input` | string | ✓ | Path to KMZ mission file |
| `-v, --verbose` | flag | | Show detailed waypoint-by-waypoint information instead of summary |

#### Output

- Mission name and drone type
- Waypoint count
- Total distance and estimated flight duration
- Altitude range
- Validation errors and warnings

#### Example

```bash
# Summary view
aeronis read mission.kmz

# Detailed view
aeronis read mission.kmz -v
```

---

### `validate` - Check Mission Validity

Validate mission structure, waypoint parameters, and compliance with constraints.

```bash
aeronis validate <input>
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `input` | string | ✓ | Path to KMZ mission file |

#### Validation Checks

- Waypoint coordinate validity (latitude range: -90°–90°, longitude: -180°–180°)
- Altitude constraints (minimum and maximum bounds)
- Speed feasibility for drone model
- Consecutive waypoint distance requirements
- Mission structure integrity

#### Exit Codes

- `0` - Mission is valid
- `1` - Mission has errors

#### Example

```bash
aeronis validate mission.kmz
```

---

### `create` - Build Mission from CSV

Create a KMZ mission file from a CSV waypoint list.

```bash
aeronis create <input> <output> [OPTIONS]
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `input` | string | ✓ | Path to CSV waypoint file |
| `output` | string | ✓ | Output KMZ file path |
| `-n, --name` | string | "Mission" | Mission name |
| `-s, --speed` | float | 5.0 | Default transit speed (m/s) |
| `-a, --altitude` | float | 80.0 | Default altitude (meters) |
| `--no-photo` | flag | | Disable automatic photo triggers |

#### Constraints

- Minimum 2 waypoints required
- Missing altitude/speed values use command defaults

#### Example

```bash
aeronis create waypoints.csv mission.kmz \
  --name "Survey Mission" \
  --altitude 100 \
  --speed 6.5 \
  --no-photo
```

---

### `simplify` - Reduce Waypoint Complexity

Simplify mission waypoint paths using the Ramer-Douglas-Peucker algorithm to reduce waypoint count while maintaining path accuracy.

```bash
aeronis simplify <input> <output> [OPTIONS]
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `input` | string | ✓ | Input KMZ mission file |
| `output` | string | ✓ | Output KMZ file path |
| `-e, --epsilon` | float | 0.00001 | Simplification tolerance (degrees) |

#### Algorithm Details

- **RDP Algorithm:** Reduces points by removing vertices that fall within epsilon distance from the simplified line
- **Epsilon:** Lower values preserve more detail; higher values create smoother, shorter paths
- **Typical Range:** 0.00001–0.0001 degrees (~1–10 meters depending on latitude)

#### Example

```bash
# Conservative simplification
aeronis simplify complex.kmz simplified.kmz --epsilon 0.00001

# Aggressive simplification
aeronis simplify complex.kmz simplified.kmz --epsilon 0.0001
```

---

### `grid` - Generate Rectangular Survey Grid

Generate a systematic rectangular survey pattern with configurable grid spacing.

```bash
aeronis grid --lon <lon> --lat <lat> [OPTIONS] -o <output>
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--lon` | float | ✓ | Center longitude (degrees) |
| `--lat` | float | ✓ | Center latitude (degrees) |
| `-w, --width` | float | 200 | Grid width (meters) |
| `--height` | float | width | Grid height (meters) |
| `--spacing` | float | 50 | Waypoint spacing (meters) |
| `-a, --altitude` | float | 80 | Altitude (meters) |
| `-s, --speed` | float | 5 | Speed (m/s) |
| `--angle` | float | 0 | Grid rotation angle (degrees) |
| `-n, --name` | string | "Grid Mission" | Mission name |
| `-o` | string | ✓ | Output file |
| `--no-photo` | flag | | Disable photo triggers |

#### Use Cases

- Photogrammetry surveys (regular grid coverage)
- Multi-spectral imaging
- Thermal inspection of large areas
- Precision agriculture

#### Example

```bash
# Basic 200m × 200m grid at 50m spacing
aeronis grid --lon 55.45 --lat -20.88 -o grid_mission.kmz

# Custom dimensions and spacing
aeronis grid \
  --lon 55.45 --lat -20.88 \
  --width 500 --height 300 \
  --spacing 25 \
  --altitude 100 \
  --speed 7 \
  --angle 45 \
  -n "Advanced Survey" \
  -o output.kmz
```

---

### `polygon` - Generate Polygon Survey Mission

Create a survey mission that follows a polygon boundary with calculated camera overlap for coverage mapping.

```bash
aeronis polygon --coords "<lon1>,<lat1> <lon2>,<lat2> ..." [OPTIONS] -o <output>
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--coords` | string | ✓ | Space-separated coordinate pairs (format: "lon,lat lon,lat ...") |
| `-a, --altitude` | float | 80 | Altitude (meters) |
| `-o, --overlap` | float | 0.8 | Photo overlap ratio (0.0–1.0) |
| `--drone` | string | "MAVIC_3" | Drone model for camera specs |
| `--angle` | float | 0 | Grid rotation (degrees) |
| `-s, --speed` | float | 5 | Speed (m/s) |
| `-n, --name` | string | "Polygon Survey" | Mission name |
| `-o` | string | ✓ | Output file |
| `--no-photo` | flag | | Disable photo triggers |

#### Coordinate Format

```
"55.450,-20.880 55.451,-20.881 55.452,-20.880 55.451,-20.879"
```

- Space-separated pairs
- Each pair: `longitude,latitude`
- Minimum 3 points required
- Polygon automatically closes

#### Example

```bash
# Simple triangular survey
aeronis polygon \
  --coords "55.450,-20.880 55.451,-20.881 55.452,-20.880" \
  --altitude 100 \
  --overlap 0.85 \
  --drone MAVIC_3 \
  -n "Triangle Survey" \
  -o triangle.kmz

# Complex polygon with custom overlap
aeronis polygon \
  --coords "55.448,-20.880 55.452,-20.882 55.455,-20.878 55.450,-20.875" \
  --altitude 150 \
  --overlap 0.90 \
  --angle 30 \
  --drone PHANTOM_4 \
  -o complex_survey.kmz
```

---

### `video` - Convert Mission to Video Mode

Transform a mission for continuous video recording by adjusting camera parameters and removing discrete photo triggers.

```bash
aeronis video <input> <output>
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `input` | string | ✓ | Input KMZ mission file |
| `output` | string | ✓ | Output KMZ file path |

#### Behavior

- Removes discrete photo trigger actions
- Adjusts camera gimbal for continuous video capture
- Maintains waypoint path and flight parameters
- Optimizes speed for smooth video motion

#### Example

```bash
aeronis video survey_with_photos.kmz video_mission.kmz
```

---

### `photo` - Optimize for Photo Capture

Adjust mission waypoints and timing to ensure optimal photo coverage with calculated spacing based on camera overlap.

```bash
aeronis photo <input> <output> [OPTIONS]
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `input` | string | ✓ | Input KMZ mission file |
| `output` | string | ✓ | Output KMZ file path |
| `-o, --overlap` | float | 0.8 | Desired photo overlap (0.0–1.0) |
| `--drone` | string | "MAVIC_3" | Drone model for camera specifications |

#### Overlap Explanation

- **0.8 (80%):** Standard photogrammetry; balances coverage and file size
- **0.85–0.90:** High-precision surveys; recommended for 3D reconstruction
- **0.70–0.75:** Standard inspection; cost-efficient

#### Supported Drones

- `MAVIC_3`
- `MAVIC_2`
- `PHANTOM_4`
- `AIR_2`
- `AIR_3`

#### Example

```bash
# Standard 80% overlap
aeronis photo original.kmz optimized.kmz --overlap 0.80

# High-precision 90% overlap
aeronis photo original.kmz optimized.kmz \
  --overlap 0.90 \
  --drone MAVIC_3
```

---

## Input Formats

### CSV Waypoint Format

CSV files must contain waypoint data with the following structure:

#### Column Specification

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `lon` | float | ✓ | Longitude (-180 to 180) |
| `lat` | float | ✓ | Latitude (-90 to 90) |
| `altitude` | float | | Altitude in meters (uses command default if omitted) |
| `speed` | float | | Transit speed in m/s (uses command default if omitted) |
| `pitch` | float | | Camera pitch angle in degrees (optional) |

#### Notes

- **Header:** Automatically detected; optional
- **Empty lines and comments:** Lines starting with `#` are ignored
- **Column order matters** if no header is present
- **Missing values:** Non-required columns can be left blank

#### Example CSV with Header

```csv
lon,lat,altitude,speed,pitch
55.450,-20.880,80,5,-90
55.451,-20.881,80,5,-90
55.452,-20.882,85,6,-85
55.453,-20.883,90,5,-90
```

#### Example CSV without Header

```
55.450,-20.880,80,5,-90
55.451,-20.881,80,5,-90
55.452,-20.882,85,6,-85
```

#### Example CSV with Defaults

```csv
lon,lat
55.450,-20.880
55.451,-20.881
55.452,-20.882
# Altitude and speed will use command-line defaults
```

### KMZ File Structure

KMZ files are ZIP archives containing:
- `doc.kml` - Main mission definition in KML format
- Associated resources (images, icons)

The tool automatically handles KMZ parsing and generation.

---

## Examples

### Workflow 1: Create and Validate a Survey Mission

```bash
# 1. Create mission from waypoints
aeronis create waypoints.csv survey.kmz \
  --name "Island Survey" \
  --altitude 120 \
  --speed 6

# 2. Inspect the mission
aeronis read survey.kmz

# 3. Validate compliance
aeronis validate survey.kmz

# 4. Optimize for photos
aeronis photo survey.kmz survey_optimized.kmz --overlap 0.85
```

### Workflow 2: Generate and Simplify Grid Survey

```bash
# 1. Generate high-resolution grid
aeronis grid \
  --lon 55.45 --lat -20.88 \
  --width 1000 --height 800 \
  --spacing 20 \
  --altitude 100 \
  --name "High-Res Survey" \
  -o grid_detailed.kmz

# 2. Simplify if file is too large
aeronis simplify grid_detailed.kmz grid_simple.kmz \
  --epsilon 0.00002

# 3. Convert to video mode for reconnaissance
aeronis video grid_simple.kmz grid_video.kmz
```

### Workflow 3: Polygon Survey with High Overlap

```bash
# Define survey area as polygon
aeronis polygon \
  --coords "55.448,-20.880 55.452,-20.882 55.455,-20.878 55.451,-20.876" \
  --altitude 150 \
  --overlap 0.90 \
  --drone MAVIC_3 \
  --angle 45 \
  --name "Precision Survey" \
  -o precision_survey.kmz

# Validate
aeronis validate precision_survey.kmz

# Read detailed report
aeronis read precision_survey.kmz -v
```

---

## Advanced Usage

### Performance Tips

1. **Large Surveys:** Use `simplify` to reduce waypoint count for faster processing
   ```bash
   aeronis simplify large_grid.kmz reduced.kmz --epsilon 0.00005
   ```

2. **Grid Optimization:** Increase spacing to reduce waypoint count
   ```bash
   aeronis grid --spacing 75 ...  # Instead of 50
   ```

3. **Batch Processing:** Use shell scripts to process multiple missions
   ```bash
   for file in missions/*.kmz; do
     aeronis validate "$file"
   done
   ```

### Drone-Specific Configurations

#### MAVIC_3 (Default)

```bash
aeronis grid --lon 55.45 --lat -20.88 --altitude 120
```

#### PHANTOM_4

```bash
aeronis polygon --coords "..." --drone PHANTOM_4 --altitude 100
```

#### AIR_3

```bash
aeronis photo original.kmz optimized.kmz --drone AIR_3
```

### Combining Operations

```bash
# Create, validate, optimize, and convert to video in sequence
aeronis create waypoints.csv temp.kmz && \
aeronis validate temp.kmz && \
aeronis photo temp.kmz optimized.kmz --overlap 0.85 && \
aeronis video optimized.kmz final_video.kmz && \
rm temp.kmz
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Validation failed or mission error |
| `2` | Invalid command arguments |

---

## Troubleshooting

### "CSV must contain at least 2 waypoints"

**Cause:** Input CSV has fewer than 2 waypoints.

**Solution:** Verify CSV file contains at least 2 valid waypoint rows.

```bash
cat waypoints.csv  # Inspect file
```

### "Non-numeric values in coordinate pair"

**Cause:** Longitude or latitude is not a valid number.

**Solution:** Check polygon coordinates use proper decimal format.

```bash
# Correct format
aeronis polygon --coords "55.450,-20.880 55.451,-20.881"

# Incorrect format
aeronis polygon --coords "55.450° -20.880°"  # Invalid
```

### "Mission invalid - aborting export"

**Cause:** Generated mission fails validation checks.

**Solution:** Review validation errors and adjust parameters.

```bash
aeronis validate mission.kmz  # See detailed errors
```

### Mission file not found

**Cause:** Incorrect file path or permission issue.

**Solution:** Use absolute paths or verify file exists.

```bash
ls -la /path/to/mission.kmz
```
