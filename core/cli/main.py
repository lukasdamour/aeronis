import typer
from typing import Optional
import csv

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text


from ..editor import MissionEditor
from ..flight_modes import apply_video_mode, apply_photo_mode, DRONE_CAMERAS
from ..generator import generate_kmz
from ..geometry import (
    grid_waypoints, grid_from_polygon,
    compute_total_distance, estimate_flight_time
)
from ..models import (
    CameraAction, DroneType, FinishAction,
    HeightMode, MissionConfig, Waypoint
)
from ..parser import parse_kmz, print_report
from ..validator import validate

console = Console()

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["--help", "-h"]}
)

CLI_HELP = """
Aeronis CLI

A command-line tool to create, inspect, validate, transform and optimiize DJI KMZ missions.

FEATURES
  - Read and inspect existing DJI missions
  - Validate waypoint structure and mission parameters
  - Create missions from CSV waypoint files
  - Simplify waypoint paths using Ramer-Douglas-Peucker (RDP) algorithm
  - Generate rectangular survey grids
  - Generate polygon survey missions
  - Convert missions to video mode
  - Optimize missions for photo capture

COMMANDS
  read          Parse and display a KMZ mission
  validate      Validate a KMZ mission
  create        Create a mission from CSV
  simplify      Simplify waypoint paths
  grid          Generate rectangular survey grid
  polygon       Generate polygon survey mission
  video         Convert mission to video mode
  photo         Optimize mission for photo capture

EXAMPLES
  aeronis read mission.kmz
  aeronis validate mission.kmz
  aeronis create input.csv output.kmz
  aeronis grid --lon 55.45 --lat -20.88 --width 200 --height 150
  aeronis polygon --coords "55.44,-20.88 55.45,-20.87"
  aeronis video mission.kmz video.kmz
  aeronis photo mission.kmz photo.kmz --overlap 0.80 --drone MAVIC_3

For detailed help on a specific command:
    aeronis COMMAND --help
"""

def show_help():
    console.print(
        Panel.fit(
            Text(CLI_HELP.strip(), style="white"),
            title="Aeronis",
            subtitle="CLI Documentation",
            border_style="cyan"
        )
    )

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        show_help()



@app.command(no_args_is_help=True, help="Parse and display a KMZ mission file.")
def read(
    input: str,
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Display full waypoint-by-waypoint details instead of a summary.")
) -> int:
    waypoints, config = parse_kmz(input)

    if verbose:
        print_report(waypoints, config)
        raise typer.Exit(0)
    
    from ..geometry import compute_total_distance, estimate_flight_time

    dist = compute_total_distance(waypoints)
    dur = estimate_flight_time(waypoints, default_speed=config.transit_speed)

    mins, secs = divmod(int(dur), 60)

    alt_min = min(wp.altitude for wp in waypoints)
    alt_max = max(wp.altitude for wp in waypoints)
    alt_str = f"{alt_min:.0f} m" if alt_min == alt_max else f"{alt_min:.0f} - {alt_max:.0f} m"

    table = Table(title="Mission Analysis")

    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("Name", config.name)
    table.add_row("Drone", config.drone_type.name)
    table.add_row("Waypoints", str(len(waypoints)))
    table.add_row("Distance", f"{dist:.1f} m")
    table.add_row("Duration", f"{mins}m {secs:02d}s")
    table.add_row("Altitude", alt_str)

    console.print(table)

    valid, errors, warnings = validate(waypoints, config)
    for e in errors:
        console.print(f"[red][ERROR][/red] {e}")
    for w in warnings:
        console.print(f"[yellow][WARNING][/yellow] {w}")
    
    raise typer.Exit(0 if valid else 1)



@app.command(no_args_is_help=True, name="validate", help="Validate a KMZ mission file.")
def validate_cmd(input: str) -> int:
    waypoints, config = parse_kmz(input)
    valid, errors, warnings = validate(waypoints, config)

    for e in errors:
        console.print(f"[red][ERROR][/red] {e}")
    for w in warnings:
        console.print(f"[yellow][WARNING][/yellow] {w}")
    
    console.print("[green][PASS] Mission is valid[/green]" if valid else "[red][FAIL] Mission has errors[/red]")

    raise typer.Exit(0 if valid else 1)



@app.command(no_args_is_help=True, help="Create a KMZ mission from a CSV file.")
def create(
    input: str, output: str, name: str = typer.Option("Mission", "--name", "-n"),
    speed: float = typer.Option(5.0, "--speed", "-s"), altitude: float = typer.Option(80.0, "--altitude", "-a"),
    no_photo: bool = typer.Option(False, "--no-photo")
) -> int:
    waypoints = _load_csv(
        input, default_speed=speed,
        default_altitude=altitude,
        with_photo=not no_photo
    )
    if len(waypoints) < 2:
        raise typer.BadParameter("CSV must contain at least 2 waypoints.")
    
    config = MissionConfig(name=name, transit_speed=speed)
    valid, errors, warnings = validate(waypoints, config)
    for e in errors:
        console.print(f"[red][ERROR][/red] {e}")
    for w in warnings:
        console.print(f"[yellow][WARNING][/yellow] {w}")
    
    if not valid:
        console.print(f"[red][ERROR]Mission invalid - aborting export[/red]")
        raise typer.Exit(1)
    
    generate_kmz(waypoints, config, output)
    console.print(f"[green][SUCCESS] Wrote {len(waypoints)} waypoints to {output}")
    


@app.command(no_args_is_help=True, help="Simplify mission using Ramer-Douglas-Peucker (RDP) algorithm.")
def simplify(
    input: str, output: str,
    epsilon : float = typer.Option(0.00001, "--epsilon", "-e")
) -> int:
    editor = MissionEditor.from_kmz(input)

    before = editor.count
    removed = editor.simplify(eps=epsilon)

    editor.to_kmz(output)

    table = Table(title="Simplification")
    
    table.add_column("Metric")
    table.add_column("Value")

    table.add_row("Before", str(before))
    table.add_row("After", str(editor.count))
    table.add_row("Removed", str(removed))

    console.print(table)
    console.print(f"[green][SUCCESS] Wrote to {output}[/green]")



@app.command(no_args_is_help=True, help="Generate rectangular survey grid.")
def grid(
    output: str, lon: float = typer.Option(..., "--lon"), lat: float = typer.Option(..., "--lat"), width: float = typer.Option(200, "--width", "-w"),
    height: Optional[float] = typer.Option(None), spacing: float = typer.Option(50),
    altitude: float = typer.Option(80, "--altitude", "-a"), speed: float = typer.Option(5),
    angle: float = typer.Option(0), no_photo: bool = typer.Option(False, "--no-photo"),
    name: str = typer.Option("Grid Mission", "--name", "-n")
) -> int:
    height = height or width

    waypoints = grid_waypoints(
        center_lon=lon, center_lat=lat,
        width_m=width, height_m=height,
        spacing_m=spacing, altitude=altitude,
        speed=speed, angle_deg=angle, with_photo=not no_photo
    )

    config = MissionConfig(name=name, transit_speed=speed)
    valid, errors, warnings = validate(waypoints, config)
    for e in errors:
        console.print(f"[red][ERROR][/red] {e}")
    for w in warnings:
        console.print(f"[yellow][WARNING][/yellow] {w}")
    
    if not valid:
        console.print(f"[red][ERROR]Mission invalid - aborting export[/red]")
        raise typer.Exit(1)
    
    generate_kmz(waypoints, config, output)
    console.print(f"[green][SUCCESS] Generated {len(waypoints)}-waypoint grid in {output}[/green]")



@app.command(no_args_is_help=True, help="Generate a polygon survey mission.")
def polygon(
    output: str, coords: str = typer.Option(..., "--coords"),
    altitude: float = typer.Option(80, "--altitude", "-a"),
    overlap: float = typer.Option(0.8, "--overlap", "-o"),
    drone: str = typer.Option("MAVIC_3"), angle: float = typer.Option(0),
    speed: float = typer.Option(5), no_photo: bool = typer.Option(False, "--no-photo"),
    name: str = typer.Option("Polygon Survey", "--name", "-n")
) -> int:
    polygon = _parse_coords(coords)

    if len(polygon) < 3:
        raise typer.BadParameter("At least 3 points required.")
    
    if not (0.0 <= overlap < 1.0):
        raise typer.BadParameter("Overlap must be in [0.0, 1.0)")
    
    waypoints = grid_from_polygon(
        polygon=polygon, altitude=altitude,
        overlap=overlap, drone_model=drone.upper(),
        angle_deg=angle, speed=speed, with_photo=not no_photo
    )
    config = MissionConfig(name=name, transit_speed=speed)

    config = MissionConfig(name=name, transit_speed=speed)
    valid, errors, warnings = validate(waypoints, config)
    for e in errors:
        console.print(f"[red][ERROR][/red] {e}")
    for w in warnings:
        console.print(f"[yellow][WARNING][/yellow] {w}")

    if not valid:
        console.print(f"[red][ERROR]Mission invalid - aborting export[/red]")
        raise typer.Exit(1)

    generate_kmz(waypoints, config, output)
    console.print(f"[green][SUCCESS] Wrote to {output}[/green]")



@app.command(no_args_is_help=True, help="Convert mission to video mode.")
def video(input: str, output: str) -> int:
    editor = MissionEditor.from_kmz(input)
    apply_video_mode(editor)

    valid, errors, warnings = validate(editor.waypoints, editor.config)
    for e in errors:
        console.print(f"[red][ERROR][/red] {e}")
    for w in warnings:
        console.print(f"[yellow][WARNING][/yellow] {w}")
    
    if not valid:
        console.print(f"[red][ERROR]Mission invalid - aborting export[/red]")
        raise typer.Exit(1)

    editor.to_kmz(output)
    console.print(f"[green][SUCCESS] Wrote to {output}[/green]")


@app.command(no_args_is_help=True, help="Optimize mission for photo capture.")
def photo(
    input: str, output: str,
    overlap: float = typer.Option(0.8, "--overlap", "-o"),
    drone: str = typer.Option("MAVIC_3")
) -> int:
    editor = MissionEditor.from_kmz(input)
    apply_photo_mode(editor, overlap=overlap, drone_model=drone.upper())

    valid, errors, warnings = validate(editor.waypoints, editor.config)
    for e in errors:
        console.print(f"[red][ERROR][/red] {e}")
    for w in warnings:
        console.print(f"[yellow][WARNING][/yellow] {w}")
    
    if not valid:
        console.print(f"[red][ERROR]Mission invalid - aborting export[/red]")
        raise typer.Exit(1)

    editor.to_kmz(output)
    console.print(f"[green][SUCCESS] Wrote to {output}[/green]")



def _parse_coords(coords_str: str) -> list[tuple[float, float]]:
    """
    Parse a space-separated string of "lon,lat" pairs.

    Example input: "55.448,-20.880 55.452,-20.882 55.452,-20.878"
    Returns: [(55.448,-20.880), (55.452,-20.882), (55.452,-20.878)]

    Raises:
        ValueError : malformed pair or non-numeric values
    """
    polygon = []
    for pair in coords_str.strip().split():
        parts = pair.split(",")
        if len(parts) != 2:
            raise ValueError(f"Invalid coordinate pair {pair!r} - expected 'lon,lat'.")
        
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            raise ValueError(f"Non-numeric values in coordinate pair {pair!r}.")
        
        polygon.append((lon, lat))
    return polygon


def _load_csv(path: str, default_speed: float, default_altitude: float, with_photo: bool) -> list[Waypoint]:
    """
    Load waypoints from a CSV file.

    Expected columns (order matters, header optional):
        lon, lat, altitude, speed, pitch

    Only lon and lat are required. Missing altitude, speed or pitch use the provided defaults or None.

    Example CSV:
        lon,lat,altitude,speed,pitch
        55.450,-20.880,80,5,-90
        55.451,-20.881,80,5,-90
    """
    waypoints = []
    with open(path, newline="", encoding="utf-8") as f:
        # Collect a sample for the sniffer, but skip lines that are completely empty or comments
        sample_lines = []
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            sample_lines.append(line)
            if len(sample_lines) >= 5:  # Grab enough clean lines to make an accurate guess
                break
        
        # Reset file pointer to the beginning for actual reading
        f.seek(0)
        
        # Determine if there is a header based only on valid data lines
        has_header = False
        if sample_lines:
            try:
                sample = "".join(sample_lines)
                has_header = csv.Sniffer().has_header(sample)
            except csv.Error:
                has_header = False

        reader = csv.reader(f)
        
        # If a header exists, we need to skip the *first non-comment line*
        skipped_header = False

        for row_num, row in enumerate(reader, start=1):
            row = [c.strip() for c in row]
            
            # Skip empty lines or comments during full parsing
            if not row or not row[0] or row[0].startswith("#"): 
                continue
            
            # If the sniffer found a header, skip this first valid data row
            if has_header and not skipped_header:
                skipped_header = True
                continue

            if len(row) < 2:
                raise ValueError(f"CSV row {row_num}: expected at least 2 columns (lon, lat), got {len(row)}.")

            try:
                lon = float(row[0])
                lat = float(row[1])
                altitude = float(row[2]) if len(row) > 2 and row[2] else default_altitude
                speed = float(row[3]) if len(row) > 3 and row[3] else default_speed
                pitch = float(row[4]) if len(row) > 4 and row[4] else None
            except ValueError as exc:
                raise ValueError(f"CSV row {row_num}: {exc}") from exc
            
            actions = [CameraAction.TAKE_PHOTO.value] if with_photo else []
            waypoints.append(
                Waypoint(
                    lon=lon, lat=lat, altitude=altitude,
                    speed=speed, pitch=pitch, actions=actions
                )
            )

    return waypoints