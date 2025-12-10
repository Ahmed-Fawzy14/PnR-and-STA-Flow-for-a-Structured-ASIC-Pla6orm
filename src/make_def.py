#!/usr/bin/env python3
"""
make_def.py: Generate DEF file for OpenROAD routing

This script generates a DEF (Design Exchange Format) file containing:
- DIEAREA: Die boundary calculated from all fabric cells
- PINS: All I/O pins with + FIXED attribute
- COMPONENTS: All fabric cells (both used and unused) with + FIXED attribute

Usage:
    python make_def.py --design <design_name> [--fabric-db <fabric_db.json>] [--fabric-cells <fabric_cells.yaml>] [--fabric-def <fabric.yaml>] [--data <data_structures.json>]

If --fabric-db is provided, it will be used directly. Otherwise, the script falls back to
using fabric_cells.yaml + fabric.yaml (or data_structures.json for template mapping).
"""

import argparse
import json
import os
import sys
import yaml
from typing import Dict, List, Tuple, Any, Optional


def load_fabric_definition(fabric_def_path: str) -> Dict[str, str]:
    """
    Load fabric.yaml to get template_name -> physical_cell_type mapping
    Returns: dict mapping template names to physical_cell_type strings
    """
    if not os.path.exists(fabric_def_path):
        raise FileNotFoundError(f"Fabric definition file not found: {fabric_def_path}")

    with open(fabric_def_path, 'r') as f:
        fab = yaml.safe_load(f)

    tile_cells = fab.get("tile_definition", {}).get("cells", [])

    template_map = {}
    for cell in tile_cells:
        template = cell.get("template_name")
        cell_type = cell.get("cell_type")
        if template and cell_type:
            template_map[template] = cell_type

    return template_map


def build_template_map_from_data_structures(data_path: str) -> Dict[str, str]:
    """
    Build template -> physical_cell_type mapping from data_structures.json
    This is a fallback when fabric.yaml is not available
    """
    if not os.path.exists(data_path):
        return {}

    try:
        with open(data_path, 'r') as f:
            data = json.load(f)

        fabric = data.get("fabric", {})
        slot_info = fabric.get("slot_info", {})

        template_map = {}
        for slot_name, slot_data in slot_info.items():
            # Extract template name from slot name (after "__")
            try:
                template_name = slot_name.split("__", 1)[1]
            except IndexError:
                continue

            physical_cell_type = slot_data.get("physical_cell_type")
            if physical_cell_type:
                # If template already mapped, verify it's the same
                if template_name in template_map:
                    if template_map[template_name] != physical_cell_type:
                        print(f"[WARNING] Template '{template_name}' has conflicting cell types: "
                              f"{template_map[template_name]} vs {physical_cell_type}")
                else:
                    template_map[template_name] = physical_cell_type

        return template_map
    except Exception as e:
        print(f"[WARNING] Could not build template map from data_structures.json: {e}")
        return {}


def load_fabric_db(fabric_db_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Load fabric_db.json and extract all components with their physical cell types
    Returns: dict mapping slot_name to {physical_cell_type, x, y, orient}
    """
    if not os.path.exists(fabric_db_path):
        raise FileNotFoundError(f"Fabric DB file not found: {fabric_db_path}")

    with open(fabric_db_path, 'r') as f:
        fabric_db = json.load(f)

    slot_info = {}

    # Handle two possible formats:
    # 1. Dictionary with cell type keys (e.g., "NAND": [...], "DFF": [...])
    # 2. Dictionary with "tiles" key containing array of tiles

    if "tiles" in fabric_db:
        # Format 1: tiles array structure
        tiles = fabric_db.get("tiles", [])
        for tile in tiles:
            cells = tile.get("cells", [])
            for cell in cells:
                cell_name = cell.get("name")
                physical_cell_type = cell.get("physical_cell_type")

                if not cell_name or not physical_cell_type:
                    continue

                slot_info[cell_name] = {
                    "physical_cell_type": physical_cell_type,
                    "x": float(cell.get("x", 0.0)),
                    "y": float(cell.get("y", 0.0)),
                    "orient": cell.get("orient", "N")
                }
    else:
        # Format 2: Dictionary with cell type keys
        for group_name, arr in fabric_db.items():
            # Skip non-list entries like site_dimensions_um, core_bbox_um, etc.
            if not isinstance(arr, list):
                continue

            for slot in arr:
                if not isinstance(slot, dict):
                    continue

                name = slot.get("name")
                phys = slot.get("physical_cell_type")
                if not name or not phys:
                    continue

                slot_info[name] = {
                    "physical_cell_type": phys,
                    "x": float(slot.get("x", 0.0)),
                    "y": float(slot.get("y", 0.0)),
                    "orient": slot.get("orient", "N")
                }

    return slot_info


def load_fabric_cells(fabric_cells_path: str, template_map: Dict[str, str], data_path: Optional[str] = None) -> Dict[
    str, Dict[str, Any]]:
    """
    Load fabric_cells.yaml and extract all components with their physical cell types
    Returns: dict mapping slot_name to {physical_cell_type, x, y, orient}
    """
    if not os.path.exists(fabric_cells_path):
        raise FileNotFoundError(f"Fabric cells file not found: {fabric_cells_path}")

    with open(fabric_cells_path, 'r') as f:
        data = yaml.safe_load(f)

    tiles = data.get("fabric_cells_by_tile", {}).get("tiles", {})
    slot_info = {}

    # If template_map is empty, try to build it from data_structures.json
    if not template_map and data_path:
        print("[INFO] Building template map from data_structures.json as fallback")
        template_map = build_template_map_from_data_structures(data_path)

    for tile_name, tile_details in tiles.items():
        cells = tile_details.get("cells", [])
        for cell in cells:
            cell_name = cell.get("name")
            if not cell_name:
                continue

            # Extract template name after "__"
            try:
                template_name = cell_name.split("__", 1)[1]
            except IndexError:
                print(f"[WARNING] Invalid cell name format (no template): {cell_name}")
                continue

            # Get physical cell type from template map
            physical_cell_type = template_map.get(template_name)

            if not physical_cell_type:
                print(
                    f"[WARNING] No physical cell type for template '{template_name}' in cell '{cell_name}'. Skipping.")
                continue

            slot_info[cell_name] = {
                "physical_cell_type": physical_cell_type,
                "x": float(cell.get("x", 0.0)),
                "y": float(cell.get("y", 0.0)),
                "orient": cell.get("orient", "N")
            }

    return slot_info


def load_data_structures(data_path: str) -> Dict[str, Any]:
    """Load data_structures.json file (for pins information)"""
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Data structures file not found: {data_path}")

    with open(data_path, 'r') as f:
        return json.load(f)


def load_placement_map(map_path: str) -> Dict[str, str]:
    """
    Load placement map file (.map format: logical_instance -> physical_slot)
    Returns: dict mapping logical instance names to physical slot names
    """
    if not os.path.exists(map_path):
        print(f"Warning: Map file not found: {map_path}. Assuming no placements.")
        return {}

    placement = {}
    with open(map_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Format: logical_instance physical_slot
            parts = line.split(None, 1)
            if len(parts) == 2:
                logical_inst, physical_slot = parts
                placement[logical_inst] = physical_slot

    return placement


def calculate_die_area(slot_info: Dict[str, Dict[str, Any]], margin_um: float = 5.0) -> Tuple[
    float, float, float, float]:
    """
    Calculate die area from all fabric slots
    Returns: (min_x, min_y, max_x, max_y) in microns
    """
    if not slot_info:
        raise ValueError("No slots found in slot_info")

    xs = []
    ys = []

    for slot_name, slot_data in slot_info.items():
        x = slot_data.get("x")
        y = slot_data.get("y")
        if x is not None and y is not None:
            xs.append(float(x))
            ys.append(float(y))

    if not xs or not ys:
        raise ValueError("No valid coordinates found in slots")

    min_x = min(xs) - margin_um
    min_y = min(ys) - margin_um
    max_x = max(xs) + margin_um
    max_y = max(ys) + margin_um

    return min_x, min_y, max_x, max_y


def microns_to_dbu(value_um: float, dbu_per_micron: int = 1000) -> int:
    """Convert microns to database units (DBU)"""
    return int(round(value_um * dbu_per_micron))


def get_pins_from_fabric_db(fabric_db_path: str) -> List[Dict[str, Any]]:
    """
    Extract pin information from fabric_db.json
    Returns: list of pin dictionaries with name, x, y, direction
    """
    pins = []

    if not os.path.exists(fabric_db_path):
        return pins

    try:
        with open(fabric_db_path, 'r') as f:
            fabric_db = json.load(f)

        # Check if there's a "pins" array at the top level
        if "pins" in fabric_db and isinstance(fabric_db["pins"], list):
            for pin in fabric_db["pins"]:
                if not isinstance(pin, dict):
                    continue

                pin_name = pin.get("name", "")
                if not pin_name:
                    continue

                # Get coordinates (prefer x_um/y_um, fall back to x/y)
                x_um = pin.get("x_um", pin.get("x", 0.0))
                y_um = pin.get("y_um", pin.get("y", 0.0))
                direction = pin.get("direction", "INPUT")

                pins.append({
                    "name": pin_name,
                    "x": float(x_um),
                    "y": float(y_um),
                    "direction": direction.upper()
                })
    except Exception as e:
        print(f"[WARNING] Could not load pins from fabric_db.json: {e}")

    return pins


def get_pins_from_data(data: Dict[str, Any], logical_db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Extract pin information from data_structures.json and optionally logical_db.json
    """
    pins = []
    port_directions = {}  # Map port names to directions

    # Try to get port directions from logical_db if available
    if logical_db_path and os.path.exists(logical_db_path):
        try:
            with open(logical_db_path, 'r') as f:
                logical_db = json.load(f)
            ports = logical_db.get("ports", {})
            for port_name, port_data in ports.items():
                direction = port_data.get("direction", "input")
                port_directions[port_name] = direction
        except Exception as e:
            print(f"[WARNING] Could not load logical_db for port directions: {e}")

    # Try to get pins from fabric section
    fabric = data.get("fabric", {})
    pin_coords = fabric.get("pin_coords", {})

    # Also check if there's a pins list in fabric
    if "pins" in fabric:
        for pin in fabric["pins"]:
            pin_name = pin.get("name", "")
            # Remove "pin_" prefix if present
            if pin_name.startswith("pin_"):
                port_name = pin_name[4:]
            else:
                port_name = pin_name

            x_um = pin.get("x_um", pin.get("x", 0.0))
            y_um = pin.get("y_um", pin.get("y", 0.0))
            direction = pin.get("direction", port_directions.get(port_name, "INPUT"))

            pins.append({
                "name": pin_name,  # Keep original pin name for DEF
                "x": float(x_um),
                "y": float(y_um),
                "direction": direction.upper()
            })
    elif pin_coords:
        # Use pin_coords if available
        for pin_name, coords in pin_coords.items():
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                # Remove "pin_" prefix if present to match with ports
                if pin_name.startswith("pin_"):
                    port_name = pin_name[4:]
                else:
                    port_name = pin_name

                direction = port_directions.get(port_name, "INPUT")

                pins.append({
                    "name": pin_name,  # Keep original pin name for DEF
                    "x": float(coords[0]),
                    "y": float(coords[1]),
                    "direction": direction.upper()
                })

    return pins


def map_logical_pin_to_physical_pin(cell_type: str, logical_pin: str) -> str:
    """
    Map logical pin names (from netlist) to physical LEF pin names.

    Some cells have different pin names in the logical netlist vs the physical LEF:
    - clkbuf cells: logical "Y" -> physical "X"
    - Other cells may have similar mappings

    Args:
        cell_type: Physical cell type (e.g., "sky130_fd_sc_hd__clkbuf_4")
        logical_pin: Logical pin name from netlist (e.g., "Y")

    Returns:
        Physical pin name for LEF/DEF (e.g., "X")
    """
    # Map clkbuf cells: Y -> X
    if "clkbuf" in cell_type.lower():
        if logical_pin == "Y":
            return "X"

    # Default: return logical pin name as-is
    return logical_pin


def write_def_file(
        output_path: str,
        design_name: str,
        die_area: Tuple[float, float, float, float],
        pins: List[Dict[str, Any]],
        slot_info: Dict[str, Dict[str, Any]],
        placement: Dict[str, str],
        net_to_pins: Optional[Dict[int, List[Tuple[str, Optional[str]]]]] = None,
        dbu_per_micron: int = 1000
) -> None:
    """
    Write DEF file with DIEAREA, PINS, COMPONENTS, and NETS sections
    """
    min_x, min_y, max_x, max_y = die_area

    # Expand die area to include all pins if they extend beyond fabric area
    if pins:
        pin_xs = [pin["x"] for pin in pins]
        pin_ys = [pin["y"] for pin in pins]
        if pin_xs and pin_ys:
            pin_min_x = min(pin_xs)
            pin_max_x = max(pin_xs)
            pin_min_y = min(pin_ys)
            pin_max_y = max(pin_ys)

            # Expand die area to include pins with margin
            margin_um = 5.0
            min_x = min(min_x, pin_min_x - margin_um)
            min_y = min(min_y, pin_min_y - margin_um)
            max_x = max(max_x, pin_max_x + margin_um)
            max_y = max(max_y, pin_max_y + margin_um)

    # Convert to DBU
    dbu_min_x = microns_to_dbu(min_x, dbu_per_micron)
    dbu_min_y = microns_to_dbu(min_y, dbu_per_micron)
    dbu_max_x = microns_to_dbu(max_x, dbu_per_micron)
    dbu_max_y = microns_to_dbu(max_y, dbu_per_micron)

    # Create reverse mapping: slot -> logical instance (if any)
    slot_to_instance = {slot: inst for inst, slot in placement.items()}

    # Create mapping from logical instance to physical slot
    instance_to_slot = placement.copy()

    # Create mapping from physical slot to cell type for pin name mapping
    slot_to_cell_type = {}
    for slot_name, slot_data in slot_info.items():
        cell_type = slot_data.get("physical_cell_type")
        if cell_type:
            slot_to_cell_type[slot_name] = cell_type

    # Ensure pins is a list
    if pins is None:
        pins = []
    elif not isinstance(pins, list):
        pins = []

    # Create pin name set for quick lookup (handle both with and without "pin_" prefix)
    pin_names_set = set()
    pin_name_map = {}  # Map from various pin name formats to actual DEF pin name
    for pin in pins:
        pin_name = pin["name"]
        pin_names_set.add(pin_name)
        pin_name_map[pin_name] = pin_name
        # Also add without "pin_" prefix if it has one
        if pin_name.startswith("pin_"):
            pin_name_map[pin_name[4:]] = pin_name
        # And add with "pin_" prefix if it doesn't have one
        if not pin_name.startswith("pin_"):
            pin_name_map[f"pin_{pin_name}"] = pin_name

    # Collect all components (both used and unused)
    components = []
    for slot_name, slot_data in sorted(slot_info.items()):
        physical_cell_type = slot_data.get("physical_cell_type")
        if not physical_cell_type:
            continue  # Skip slots without physical cell type

        x_um = float(slot_data.get("x", 0.0))
        y_um = float(slot_data.get("y", 0.0))
        orient = slot_data.get("orient", "N")

        # Convert to DBU
        x_dbu = microns_to_dbu(x_um, dbu_per_micron)
        y_dbu = microns_to_dbu(y_um, dbu_per_micron)

        # Component name is the physical slot name
        # Cell type is the physical cell type
        components.append({
            "name": slot_name,
            "cell_type": physical_cell_type,
            "x": x_dbu,
            "y": y_dbu,
            "orient": orient
        })

    # Write DEF file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w') as f:
        # Header
        f.write("VERSION 5.8 ;\n")
        f.write("DIVIDERCHAR \"/\" ;\n")
        f.write("BUSBITCHARS \"[]\" ;\n")
        f.write(f"DESIGN {design_name} ;\n")
        f.write(f"UNITS DISTANCE MICRONS {dbu_per_micron} ;\n")
        f.write("\n")

        # DIEAREA
        f.write(f"DIEAREA ( {dbu_min_x} {dbu_min_y} ) ( {dbu_max_x} {dbu_max_y} ) ;\n")
        f.write("\n")

        # PINS section
        f.write(f"PINS {len(pins)} ;\n")
        for pin in pins:
            pin_name = pin["name"]
            x_um = pin["x"]
            y_um = pin["y"]
            direction = pin["direction"]

            # Convert to DBU
            x_dbu = microns_to_dbu(x_um, dbu_per_micron)
            y_dbu = microns_to_dbu(y_um, dbu_per_micron)

            # Determine DEF direction
            def_direction = "INPUT" if direction.upper() in ("INPUT", "IN") else "OUTPUT"

            # Write pin with + LAYER before + FIXED
            f.write(
                f"  - {pin_name} + NET {pin_name} + DIRECTION {def_direction} + USE SIGNAL + LAYER met2 ( -140 0 ) ( 140 280 ) + FIXED ( {x_dbu} {y_dbu} ) N ;\n")
        f.write("END PINS\n")
        f.write("\n")

        # COMPONENTS section
        f.write(f"COMPONENTS {len(components)} ;\n")
        for comp in components:
            comp_name = comp["name"]
            cell_type = comp["cell_type"]
            x_dbu = comp["x"]
            y_dbu = comp["y"]
            orient = comp["orient"]

            # Write component with + FIXED
            f.write(f"  - {comp_name} {cell_type} + FIXED ( {x_dbu} {y_dbu} ) {orient} ;\n")
        f.write("END COMPONENTS\n")
        f.write("\n")

        # NETS section
        if net_to_pins:
            # Include all nets that have at least one valid connection (placed component or pin)
            # OpenROAD may need all nets for validation, even single-connection nets
            valid_nets = {}
            for net_id, connections in net_to_pins.items():
                valid_connections = []
                for conn in connections:
                    inst_or_pin_name, pin_name = conn

                    # Check if it's a pin/port connection
                    if pin_name is None:
                        # This is a top-level pin/port
                        # Try to find matching pin name
                        def_pin_name = pin_name_map.get(inst_or_pin_name)
                        if def_pin_name:
                            valid_connections.append(("PIN", def_pin_name, None))
                    else:
                        # This is an instance pin connection
                        # Check if instance is placed
                        physical_slot = instance_to_slot.get(inst_or_pin_name)
                        if physical_slot:
                            # Map logical pin name to physical LEF pin name
                            cell_type = slot_to_cell_type.get(physical_slot)
                            if cell_type:
                                physical_pin_name = map_logical_pin_to_physical_pin(cell_type, pin_name)
                            else:
                                physical_pin_name = pin_name  # Fallback to logical name
                            valid_connections.append(("COMP", physical_slot, physical_pin_name))

                # Include nets with at least one valid connection
                # (OpenROAD may need all nets for complete netlist validation)
                if len(valid_connections) >= 1:
                    valid_nets[net_id] = valid_connections

            # Write NETS section
            f.write(f"NETS {len(valid_nets)} ;\n")
            for net_id in sorted(valid_nets.keys()):
                connections = valid_nets[net_id]
                # Generate net name
                net_name = f"net_{net_id}"
                f.write(f"  - {net_name}\n")

                # Write all connections
                for conn_type, name, pin_name in connections:
                    if conn_type == "PIN":
                        # Top-level pin connection - use PIN keyword
                        f.write(f"    ( PIN {name} )\n")
                    else:
                        # Component pin connection
                        f.write(f"    ( {name} {pin_name} )\n")

                f.write("  ;\n")

            f.write("END NETS\n")
            f.write("\n")
        else:
            print("[WARNING] No net_to_pins data provided. NETS section will be empty.")

        # Footer
        f.write("END DESIGN\n")

    print(f"[INFO] DEF file written to: {output_path}")
    print(f"[INFO] Die area: ({min_x:.2f}, {min_y:.2f}) to ({max_x:.2f}, {max_y:.2f}) microns")
    print(f"[INFO] Pins: {len(pins)}")
    print(f"[INFO] Components: {len(components)} (all + FIXED)")
    if net_to_pins:
        # Count valid nets (those with at least one valid connection)
        valid_nets_count = 0
        for net_id, connections in net_to_pins.items():
            valid_conn_count = 0
            for conn in connections:
                inst_or_pin_name, pin_name = conn
                if pin_name is None:
                    # Pin connection
                    if pin_name_map.get(inst_or_pin_name):
                        valid_conn_count += 1
                else:
                    # Instance connection
                    if instance_to_slot.get(inst_or_pin_name):
                        valid_conn_count += 1
            if valid_conn_count >= 1:
                valid_nets_count += 1
        print(f"[INFO] Nets: {valid_nets_count} (all nets with >= 1 connection)")


def main():
    parser = argparse.ArgumentParser(
        description="Generate DEF file for OpenROAD routing",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--design",
        required=True,
        help="Design name (e.g., '6502', 'arith')"
    )

    parser.add_argument(
        "--map",
        help="Path to placement map file (default: build/<design>/<design>_cts.map)"
    )

    parser.add_argument(
        "--fabric-cells",
        help="Path to fabric_cells.yaml (default: build/fabric/fabric_cells.yaml)"
    )

    parser.add_argument(
        "--fabric-def",
        help="Path to fabric.yaml (default: build/fabric/fabric.yaml or fabric.yaml in src/)"
    )

    parser.add_argument(
        "--fabric-db",
        help="Path to fabric_db.json (auto-detected from build/fabric/fabric_db.json if not specified). If found, this will be used instead of fabric_cells.yaml"
    )

    parser.add_argument(
        "--data",
        help="Path to data_structures.json (default: build/<design>/data_structures.json)"
    )

    parser.add_argument(
        "--output",
        help="Output DEF file path (default: build/<design>/<design>_fixed.def)"
    )

    parser.add_argument(
        "--build-dir",
        default="build",
        help="Build directory (default: 'build')"
    )

    args = parser.parse_args()

    design_name = args.design
    build_dir = args.build_dir

    # Determine file paths
    # Prioritize fabric_db.json - auto-detect if not explicitly provided
    fabric_db_path = None
    if args.fabric_db:
        fabric_db_path = args.fabric_db
        if not os.path.exists(fabric_db_path):
            raise FileNotFoundError(f"Specified fabric_db.json not found: {fabric_db_path}")
    else:
        # Auto-detect: try multiple possible locations for fabric_db.json
        possible_fabric_db_paths = [
            # os.path.join(build_dir, "fabric", "fabric_db.json"),
            os.path.join("build", "fabric", "fabric_db.json"),
            # os.path.join("fabric_db.json"),
            # os.path.join("build", "fabric", "cells_by_type.json")
        ]
        for path in possible_fabric_db_paths:
            if os.path.exists(path):
                fabric_db_path = path
                print(f"[INFO] Auto-detected fabric_db.json at: {fabric_db_path}")
                break

    # If fabric_db not found, fall back to fabric_cells.yaml
    if not fabric_db_path:
        if args.fabric_cells:
            fabric_cells_path = args.fabric_cells
        else:
            fabric_cells_path = os.path.join(build_dir, "fabric", "fabric_cells.yaml")

        # Determine fabric.yaml path (optional - can fall back to data_structures.json)
        fabric_def_path = None
        if args.fabric_def:
            fabric_def_path = args.fabric_def
        else:
            # Try multiple locations for fabric.yaml
            possible_paths = [
                os.path.join(build_dir, "fabric", "fabric.yaml"),
                os.path.join("fabric.yaml"),
                os.path.join("src", "fabric.yaml"),
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    fabric_def_path = path
                    break
    else:
        # fabric_db_path is set, so we don't need fabric_cells or fabric_def
        fabric_cells_path = None
        fabric_def_path = None

    if args.data:
        data_path = args.data
    else:
        data_path = os.path.join(build_dir, design_name, "data_structures.json")

    if args.map:
        map_path = args.map
    else:
        # Try _cts.map first, then .map
        cts_map_path = os.path.join(build_dir, design_name, f"{design_name}_cts.map")
        regular_map_path = os.path.join(build_dir, design_name, f"{design_name}.map")
        if os.path.exists(cts_map_path):
            map_path = cts_map_path
        elif os.path.exists(regular_map_path):
            map_path = regular_map_path
        else:
            map_path = cts_map_path  # Will show warning if not found

    if args.output:
        output_path = args.output
    else:
        output_path = os.path.join(build_dir, design_name, f"{design_name}_fixed.def")

    # Load fabric information
    if fabric_db_path:
        # Use fabric_db.json directly
        print(f"[INFO] Loading fabric database from: {fabric_db_path}")
        slot_info = load_fabric_db(fabric_db_path)
        print(f"[INFO] Found {len(slot_info)} fabric cells from fabric_db.json")
    else:
        # Fall back to fabric_cells.yaml + fabric.yaml
        # Load fabric definition (template -> cell_type mapping) if available
        template_map = {}
        if fabric_def_path:
            print(f"[INFO] Loading fabric definition from: {fabric_def_path}")
            template_map = load_fabric_definition(fabric_def_path)
            print(f"[INFO] Loaded {len(template_map)} template mappings from fabric.yaml")
        else:
            print("[INFO] fabric.yaml not found, will try to build mapping from data_structures.json")

        # Load fabric cells from fabric_cells.yaml
        print(f"[INFO] Loading fabric cells from: {fabric_cells_path}")
        slot_info = load_fabric_cells(fabric_cells_path, template_map,
                                      data_path=data_path if os.path.exists(data_path) else None)
        print(f"[INFO] Found {len(slot_info)} fabric cells (all components from fabric_cells.yaml)")

    # Load placement map (optional - used to identify used vs unused slots)
    # Note: We still include ALL components from fabric_cells.yaml (both used and unused)
    print(f"[INFO] Loading placement map from: {map_path}")
    placement = load_placement_map(map_path)
    if placement:
        print(f"[INFO] Found {len(placement)} placed instances")

    # Get pins (try to load from fabric_db.json first, then data_structures.json)
    pins = []

    # First, try to get pins from fabric_db.json if we're using it
    if fabric_db_path:
        print(f"[INFO] Loading pins from fabric_db.json")
        pins = get_pins_from_fabric_db(fabric_db_path)
        if pins:
            print(f"[INFO] Found {len(pins)} pins in fabric_db.json")

    # If no pins found in fabric_db.json, try data_structures.json
    if not pins and os.path.exists(data_path):
        try:
            print(f"[INFO] Loading pins from data_structures.json")
            data = load_data_structures(data_path)
            logical_db_path = os.path.join(build_dir, design_name, f"{design_name}_logical_db.json")
            pins = get_pins_from_data(data,
                                      logical_db_path=logical_db_path if os.path.exists(logical_db_path) else None)
            if pins:
                print(f"[INFO] Found {len(pins)} pins in data_structures.json")
        except Exception as e:
            print(f"[WARNING] Could not load pins from data_structures.json: {e}")

    if not pins:
        print("[WARNING] No pins found. PINS section will be empty.")

    # Load net_to_pins from data_structures.json for NETS section
    net_to_pins = None
    if os.path.exists(data_path):
        try:
            print(f"[INFO] Loading net connectivity from data_structures.json")
            data = load_data_structures(data_path)

            # Try to get net_to_pins directly first
            net_to_pins_raw = data.get("net_to_pins", {})

            # If not found, build it from logical.instances and ports
            if not net_to_pins_raw:
                from collections import defaultdict
                net_to_pins = defaultdict(list)

                # Build from logical.instances
                logical = data.get("logical", {})
                instances = logical.get("instances", {})
                for inst_name, inst_data in instances.items():
                    inst_pins = inst_data.get("pins", {})  # Renamed to avoid overwriting main pins variable
                    for pin_name, net_list in inst_pins.items():
                        if isinstance(net_list, list):
                            for net_id in net_list:
                                net_to_pins[net_id].append((inst_name, pin_name))

                # Add ports from logical_db.json if available
                logical_db_path = os.path.join(build_dir, design_name, f"{design_name}_logical_db.json")
                if os.path.exists(logical_db_path):
                    try:
                        with open(logical_db_path, 'r') as f:
                            logical_db = json.load(f)
                        ports = logical_db.get("ports", {})
                        for port_name, port_data in ports.items():
                            bits = port_data.get("bits", [])
                            if isinstance(bits, list):
                                for net_id in bits:
                                    # Use port name directly (may need pin_ prefix handling)
                                    net_to_pins[net_id].append((port_name, None))
                    except Exception as e:
                        print(f"[WARNING] Could not load ports from logical_db.json: {e}")

                # Convert defaultdict to regular dict
                net_to_pins = dict(net_to_pins)
                print(f"[INFO] Built {len(net_to_pins)} nets from logical.instances")
            else:
                # Convert string keys to int if needed, and ensure proper format
                net_to_pins = {}
                for net_key, connections in net_to_pins_raw.items():
                    net_id = int(net_key) if isinstance(net_key, str) else net_key
                    # Ensure connections are in the right format: list of tuples
                    if isinstance(connections, list):
                        formatted_connections = []
                        for conn in connections:
                            if isinstance(conn, (list, tuple)) and len(conn) >= 2:
                                formatted_connections.append((conn[0], conn[1]))
                            elif isinstance(conn, (list, tuple)) and len(conn) == 1:
                                formatted_connections.append((conn[0], None))
                            else:
                                formatted_connections.append((str(conn), None))
                        net_to_pins[net_id] = formatted_connections
                print(f"[INFO] Loaded {len(net_to_pins)} nets from data_structures.json")
        except Exception as e:
            print(f"[WARNING] Could not load net_to_pins from data_structures.json: {e}")
            import traceback
            traceback.print_exc()
            net_to_pins = None

    # Calculate die area
    die_area = calculate_die_area(slot_info, margin_um=5.0)

    # Write DEF file
    write_def_file(
        output_path=output_path,
        design_name=design_name,
        die_area=die_area,
        pins=pins,
        slot_info=slot_info,
        placement=placement,
        net_to_pins=net_to_pins,
        dbu_per_micron=1000
    )

    print(f"[INFO] Successfully generated DEF file: {output_path}")


if __name__ == "__main__":
    main()