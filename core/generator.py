# =================
# IMPORTS
# =================
import io
import time
import zipfile
import xml.etree.ElementTree as ET

from .models import (
    CameraAction, HeadingMode, MissionConfig, Waypoint,
    KML_NS, WPML_NS
)

from .geometry import compute_total_distance, estimate_flight_time


# =================
# PUBLIC API
# =================
def generate_kmz(waypoints: list[Waypoint], config: MissionConfig, output_path: str) -> None:
    """
    Generate a DJI-compatible .kmz file and write it to disk.

    Creates two internal files inside the ZIP:
        - wpmz/template.kml : missionConfig metadata only (no Folder/Placemark)
        - wpmz/waylines.wpml : full mission (missionConfig + Folder + Placemarks)

    Args:
        - waypoints : Ordered list of Waypoints objects (minimum 2).
        - config : Global mission configuration.
        - output_path : Destination path for the .kmz file.
    
    Raises:
        - ValueError : fewer than 2 waypoints provided.

    Example:
        >>> wps = [Waypoint(...), Waypoint(...)]
        >>> cfg = MissionConfig()
        >>> generate_kmz(wps, cfg, "mission.kmz")
    """
    kmz_bytes = generate_kmz_bytes(waypoints, config)
    with open(output_path, "wb") as f:
        f.write(kmz_bytes)


def generate_kmz_bytes(waypoints: list[Waypoint], config: MissionConfig) -> bytes:
    """
    Same as generate_kmz() but returns the KMZ content as raw bytes instead of writing to disk.

    Useful for the web server /api/generate endpoint and for round-trip tests that don't need a file on disk.

    Args:
        - waypoints : Ordered list of Waypoint objects (minimum 2).
        - config : Global mission configuration.

    Returns:
        Raw bytes of the .kmz file
    
    Raises:
        ValueError : fewer than 2 waypoints provided
    """
    if len(waypoints) < 2:
        raise ValueError(f"A mission requires at least 2 waypoints, gto {len(waypoints)}.")

    template_bytes = _build_template_kml(config)
    waylines_bytes = _build_waylines_wpml(waypoints, config)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("wpmz/template.kml", template_bytes)
        zf.writestr("wpmz/waylines.wpml", waylines_bytes)

    return buf.getvalue()



# =================
# PRIVATE BUILDERS
# =================

def _build_template_kml(config: MissionConfig) -> bytes:
    """
    Build the wpmz/template.kml file content.

    template.kml contains only the missionConfig section (no Folder, no Placemarks).
    """

    _register_namespaces()

    kml = ET.Element(f"{{{KML_NS}}}kml")
    doc = ET.SubElement(kml, f"{{{KML_NS}}}Document")

    now_ms = str(int(time.time() * 1000))
    _sub(doc, "wpml:author", config.author)
    _sub(doc, "wpml:createTime", now_ms)
    _sub(doc, "wpml:updateTime", now_ms)

    _build_mission_config(doc, config, include_author=False)

    return _to_bytes(kml)


def _build_waylines_wpml(waypoints: list[Waypoint], config: MissionConfig) -> bytes:
    """
    Build the wpmz/waylines.wpml file content.

    waylines.wpml is the file actuallya xecuted by the drone.
    It contains both missionConfig and a Folder with all Placemarks.

    Folder metadata:
        templateId = 0
        executeHeightMode
        waylineId = 0
        distance : computed from waypoints
        duration : computed from waypoints
        autoFlightSpeed : first waypoint speed or transit_speed
    """
    _register_namespaces()

    kml = ET.Element(f"{{{KML_NS}}}kml")
    doc = ET.SubElement(kml, f"{{{KML_NS}}}Document")

    _build_mission_config(doc, config, include_author=False)

    folder = ET.SubElement(doc, f"{{{KML_NS}}}Folder")

    _sub(folder, "wpml:templateId", "0")
    _sub(folder, "wpml:executeHeightMode", config.height_mode.value)
    _sub(folder, "wpml:waylineId", "0")

    distance = compute_total_distance(waypoints)
    duration = estimate_flight_time(waypoints, default_speed=config.transit_speed)
    auto_speed = waypoints[0].speed if waypoints[0].speed is not None else config.transit_speed

    _sub(folder, "wpml:distance", f"{distance:.1f}")
    _sub(folder, "wpml:duration", f"{duration:.1f}")
    _sub(folder, "wpml:autoFlightSpeed", str(auto_speed))

    for i, wp in enumerate(waypoints):
        pm = _build_placemark(wp, i)
        folder.append(pm)
    
    return _to_bytes(kml)


def _build_mission_config(parent: ET.Element, config: MissionConfig, include_author: bool = False) -> ET.Element:
    """
    Build the <missionConfig> element and append it to parent.

    Used by both template.kml and waylines.wpml builders to avoid duplicating the config construction logic.

    Args:
        - parent : Parent XML element to append to
        - config : MissionConfig to serialize.
        - include_author : if True, prepend author/timestamp tags (only used in template.kml)

    Returns:
        The created <MissionConfig> element.
    """

    mc = ET.SubElement(parent, f"{{{WPML_NS}}}missionConfig")

    _sub(mc, "wpml:flyToWaylineMode", "safely")
    _sub(mc, "wpml:finishAction", config.finish_action.value)
    _sub(mc, "wpml:exitOnRCLost", "executeLostAction")
    _sub(mc, "wpml:executeRCLostAction", config.rc_lost_action)
    _sub(mc, "wpml:globalTransitionalSpeed", str(config.transit_speed))

    drone_info = config.drone_info
    di = ET.SubElement(mc, f"{{{WPML_NS}}}droneInfo")
    _sub(di, "wpml:droneEnumValue", drone_info.enum_value)
    _sub(di, "wpml:droneSubEnumValue", str(drone_info.sub_enum_value))

    return mc


def _build_placemark(wp: Waypoint, index: int) -> ET.Element:
    """
    Build a single <Placemark> element for the given waypoint.

    ActionGroup structure :
        actionGroup[0] - trigger=reachPoint
            - action : takePhoto (or other camera actions)
            - action : gimbalRotate (if wp.pitch is not None)

        actionGroup[1] - trigger=betweenAdjacentPoints
            - action: gimbalEvenlyRotate (if wp.pitch is not None)
    

    Args:
        - wp : Waypoint to serialize.
        - index : Zero-based position in the mission

    Returns:
        A <kml:Placemark> ET.Element ready to append to the Folder
    """

    pm = ET.Element(f"{{{KML_NS}}}Placemark")

    point = ET.SubElement(pm, f"{{{KML_NS}}}Point")
    _sub(point, "kml:coordinates", f"{wp.lon},{wp.lat}")

    _sub(pm, "wpml:index", str(index))
    _sub(pm, "wpml:executeHeight", str(wp.altitude))

    if wp.speed is not None:
        _sub(pm, "wpml:waypointSpeed", str(wp.speed))
 
    hp = ET.SubElement(pm, f"{{{WPML_NS}}}waypointHeadingParam")
    _sub(hp, "wpml:waypointHeadingMode", wp.heading_mode.value)

    heading_angle = wp.heading_angle if wp.heading_angle is not None else 0
    _sub(hp, "wpml:waypointHeadingAngle", str(heading_angle))
    _sub(hp, "wpml:waypointPoiPoint", "0.0,0.0,0.0")
    _sub(hp, "wpml:waypointHeadingAngleEnable", "1")
    _sub(hp, "wpml:waypointHeadingPathMode", "followBadArc")
    _sub(hp, "wpml:waypointHeadingPoiIndex", "0")

    tp = ET.SubElement(pm, f"{{{WPML_NS}}}waypointTurnParam")
    _sub(tp, "wpml:waypointTurnMode", wp.turn_mode.value)
    _sub(tp, "wpml:waypointTurnDampingDist", "0")

    _sub(pm, "wpml:useStraightLine", "0")

    ag_reach = _build_action_group_reach(wp, index)
    pm.append(ag_reach)

    ag_between = _build_action_group_between(wp, index)
    if ag_between is not None:
        pm.append(ag_between)

    return pm


def _build_action_group_reach(wp: Waypoint, index: int) -> ET.Element:
    """
    Build the reachPoint actionGroup for a waypoint.

    Contains:
        - one action per entry in wp.actions (camera actions)
        - one gimbalRotate action if wp.pitch is not None
    """
    ag = ET.Element(f"{{{WPML_NS}}}actionGroup")
    _sub(ag, "wpml:actionGroupId", "0")
    _sub(ag, "wpml:actionGroupStartIndex", str(index))
    _sub(ag, "wpml:actionGroupEndIndex", str(index))
    _sub(ag, "wpml:actionGroupMode", "parallel")

    trig = ET.SubElement(ag, f"{{{WPML_NS}}}actionTrigger")
    _sub(trig, "wpml:actionTriggerType", "reachPoint")

    action_id = 2 * index

    # Camera actions
    for func in wp.actions:
        action = ET.SubElement(ag, f"{{{WPML_NS}}}action")
        _sub(action, "wpml:actionId", str(action_id))
        _sub(action, "wpml:actionActuatorFunc", func)
        param = ET.SubElement(action, f"{{{WPML_NS}}}actionActuatorFuncParam")
        if func == CameraAction.TAKE_PHOTO.value:
            _sub(param, "wpml:payloadPositionIndex", "0")
        elif func == CameraAction.START_RECORD.value:
            _sub(param, "wpml:payloadPositionIndex", "0")
        elif func == CameraAction.STOP_RECORD.value:
            _sub(param, "wpml:payloadPositionIndex", "0")
        action_id += 1

    # gimbalRotate
    if wp.pitch is not None:
        action = ET.SubElement(ag, f"{{{WPML_NS}}}action")
        _sub(action, "wpml:actionId", str(2 * index + 1))
        _sub(action, "wpml:actionActuatorFunc", "gimbalRotate")
        param = ET.SubElement(action, f"{{{WPML_NS}}}actionActuatorFuncParam")
        _sub(param, "wpml:gimbalHeadingYawBase", "aircraft")
        _sub(param, "wpml:gimbalRotateMode", "absoluteAngle")
        _sub(param, "wpml:gimbalPitchRotateEnable", "1")
        _sub(param, "wpml:gimbalPitchRotateAngle", str(wp.pitch))
        _sub(param, "wpml:gimbalRollRotateEnable", "0")
        _sub(param, "wpml:gimbalRollRotateAngle", "0")
        _sub(param, "wpml:gimbalYawRotateEnable", "0")
        _sub(param, "wpml:gimbalYawRotateAngle", "0")
        _sub(param, "wpml:gimbalRotateTimeEnable", "0")
        _sub(param, "wpml:gimbalRotateTime", "0")
        _sub(param, "wpml:payloadPositionIndex", "0")

    return ag


def _build_action_group_between(wp: Waypoint, index: int) -> ET.Element | None:
    """
    Build the betweenAdjacentPoints actionGroup for a waypoint.

    Contains a gimbalEvenlyRotate action that smoothly rotates the gimbal during trabel to the next waypoint.

    Returns None if wp.pitch is None (no gimbal action needed), so the caller can simply skip appending it.
    """
    if wp.pitch is None:
        return None
    
    ag = ET.Element(f"{{{WPML_NS}}}actionGroup")
    _sub(ag, "wpml:actionGroupId", "1")
    _sub(ag, "wpml:actionGroupStartIndex", str(index))
    _sub(ag, "wpml:actionGroupEndIndex", str(index + 1))
    _sub(ag, "wpml:actionGroupMode", "parallel")

    trig = ET.SubElement(ag, f"{{{WPML_NS}}}actionTrigger")
    _sub(trig, "wpml:actionTriggerType", "betweenAdjacentPoints")

    action = ET.SubElement(ag, f"{{{WPML_NS}}}action")
    _sub(action, "wpml:actionId", str(2 * index + 3))
    _sub(action, "wpml:actionActuatorFunc", "gimbalEvenlyRotate")
    param = ET.SubElement(action, f"{{{WPML_NS}}}actionActuatorFuncParam")
    _sub(param, "wpml:gimbalPitchRotateAngle", str(wp.pitch))
    _sub(param, "wpml:payloadPositionIndex", "0")

    return ag



# =================
# UTILITIES
# =================

def _sub(parent: ET.Element, tag: str, text: str = "") -> ET.Element:
    """
    Create a sub-element with the correct namespace and optional text.

    Args:
        - parent : Parent element.
        - tag : Tag in "prefix:localname" format 'e.g. "wpml:index").
        - text : Text content of the element
    
    Returns:
        The created sub-element.

    
    Example:
        _sub(folder, "wpml:distance", "4482.1")
        # -> <wpml:distance>4482.1</wpml:distance>
    """
    ns_map = {"kml": KML_NS, "wpml": WPML_NS}
    prefix, local = tag.split(":")
    el = ET.SubElement(parent, f"{{{ns_map[prefix]}}}{local}")
    if text:
        el.text = str(text)
    return el


def _register_namespaces() -> None:
    """
    Register KML and WPML namespace prefixes with the ElementTree so that the serialized XML uses readable prefixes instead of ns0/ns1.

    Must be called before ET.tostring() or ET.ElementTree.write().
    """
    ET.register_namespace("", KML_NS) # default namespace (no prefix)
    ET.register_namespace("wpml", WPML_NS)


def _indent(elem: ET.Element, level: int = 0) -> None:
    """
    In-place pretty-print an XML element tree by adding indentation and newlines.
    """
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            _indent(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def _to_bytes(root: ET.Element) -> bytes:
    """
    Serialize an XML element tree to UTF-8 bytes with XML declaration.

    Args:
        - root : Root element to serialize.

    Returns:
        - UTF-8 encoded XML bytes including the <?xml ...?> declaration.
    """
    _indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)