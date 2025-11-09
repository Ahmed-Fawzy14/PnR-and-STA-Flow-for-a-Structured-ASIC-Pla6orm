"""
Pin Placement Parser Module

This module provides functionality to parse pin placement YAML files
and convert them into a structured Python format suitable for use
by visualization and validation scripts.
"""

import json
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional


def load_pins(path: str = "pins.yaml") -> dict:
    """
    Parse the pins.yaml file and return a structured dictionary with:
    {
        "version": str,
        "units": {...},
        "layers": {...},
        "die": {...},
        "core": {...},
        "pins": [
            {"name": "in_0", "side": "south", "layer": "met2",
             "x_um": 4.83, "y_um": 0.0, "direction": "INPUT", "status": "FIXED"},
             ...
        ]
    }

    Args:
        path: Path to the pins.yaml file (default: "pins.yaml")

    Returns:
        A dictionary containing all parsed pin placement data with numeric
        fields converted to appropriate types (floats for measurements).

    Raises:
        FileNotFoundError: If the specified file does not exist.
        ValueError: If the file is missing required fields (e.g., "pins",
                    "pin_placement", etc.) or has invalid structure.
    """
    # Check if file exists
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Pin placement file not found: {path}")

    # Load YAML file
    try:
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML file: {e}")

    # Check for top-level pin_placement key
    if not isinstance(data, dict) or "pin_placement" not in data:
        raise ValueError("YAML file must have a top-level 'pin_placement' key")

    pin_placement = data["pin_placement"]

    # Validate required fields
    if "pins" not in pin_placement:
        raise ValueError("Missing required field 'pins' in pin_placement")
    if "version" not in pin_placement:
        raise ValueError("Missing required field 'version' in pin_placement")

    # Build structured output dictionary
    result = {
        "version": str(pin_placement["version"]),
    }

    # Extract units section (coords, dbu_per_micron)
    if "units" in pin_placement:
        result["units"] = pin_placement["units"].copy()
        # Convert dbu_per_micron to int if present
        if "dbu_per_micron" in result["units"]:
            result["units"]["dbu_per_micron"] = int(result["units"]["dbu_per_micron"])
    else:
        result["units"] = {}

    # Extract layers section (maps sides to layer names)
    result["layers"] = pin_placement.get("layers", {})

    # Extract tracks section (track configurations per layer)
    result["tracks"] = pin_placement.get("tracks", {})
    # Convert numeric track fields to floats
    for layer, track_data in result["tracks"].items():
        if isinstance(track_data, dict):
            if "start_um" in track_data:
                track_data["start_um"] = float(track_data["start_um"])
            if "step_um" in track_data:
                track_data["step_um"] = float(track_data["step_um"])

    # Extract die section (die dimensions and margins)
    result["die"] = pin_placement.get("die", {})
    # Convert numeric die fields to floats
    numeric_die_fields = ["width_um", "height_um", "core_margin_um", "corner_keepout_um"]
    for field in numeric_die_fields:
        if field in result["die"]:
            result["die"][field] = float(result["die"][field])

    # Extract core section (core dimensions)
    result["core"] = pin_placement.get("core", {})
    # Convert numeric core fields to floats
    numeric_core_fields = ["width_um", "height_um"]
    for field in numeric_core_fields:
        if field in result["core"]:
            result["core"][field] = float(result["core"][field])

    # Extract additional configuration fields
    if "groups_per_side" in pin_placement:
        result["groups_per_side"] = int(pin_placement["groups_per_side"])
    if "pin_spacing_tracks" in pin_placement:
        result["pin_spacing_tracks"] = int(pin_placement["pin_spacing_tracks"])

    # Extract pin_spacing_um (spacing per layer)
    result["pin_spacing_um"] = pin_placement.get("pin_spacing_um", {})
    # Convert numeric spacing values to floats
    for layer, spacing in result["pin_spacing_um"].items():
        result["pin_spacing_um"][layer] = float(spacing)

    # Extract and process pins list
    pins_raw = pin_placement["pins"]
    if not isinstance(pins_raw, list):
        raise ValueError("Field 'pins' must be a list")

    result["pins"] = []
    for pin in pins_raw:
        if not isinstance(pin, dict):
            raise ValueError("Each pin must be a dictionary")

        # Create a copy of the pin dictionary
        pin_processed = pin.copy()

        # Convert numeric fields to floats
        numeric_pin_fields = ["x_um", "y_um", "width_um", "height_um"]
        for field in numeric_pin_fields:
            if field in pin_processed:
                pin_processed[field] = float(pin_processed[field])

        result["pins"].append(pin_processed)

    return result


def get_pin_list(pins_db: dict) -> List[Dict[str, Any]]:
    """
    Extract a simplified list of pins with {id, x, y} format for visualization.

    Args:
        pins_db: The dictionary returned by load_pins()

    Returns:
        A list of dictionaries, each containing:
        {
            "id": str,  # pin name
            "x": float,  # x coordinate in microns
            "y": float   # y coordinate in microns
        }
    """
    if "pins" not in pins_db:
        raise ValueError("pins_db must contain a 'pins' key")

    pin_list = []
    for pin in pins_db["pins"]:
        pin_list.append({
            "id": pin.get("name", ""),
            "x": float(pin.get("x_um", 0.0)),
            "y": float(pin.get("y_um", 0.0))
        })

    return pin_list


if __name__ == "__main__":
    # Quick verification when run as a script
    try:
        pins_db = load_pins("pins.yaml")

        # Count pins and determine unique layers
        num_pins = len(pins_db["pins"])
        layers = set(pin.get("layer", "unknown") for pin in pins_db["pins"])
        layers_str = "/".join(sorted(layers))

        print(f"Found {num_pins} pins ({layers_str})")

        # Show example pin
        if pins_db["pins"]:
            example_pin = pins_db["pins"][0]
            # Create a simplified representation for display
            example_dict = {
                "name": example_pin.get("name"),
                "side": example_pin.get("side"),
                "x_um": example_pin.get("x_um"),
                "y_um": example_pin.get("y_um")
            }
            print(f"Example pin: {example_dict}")

        # Test get_pin_list helper
        pin_list = get_pin_list(pins_db)
        if pin_list:
            print(f"\nPin list example (first pin): {pin_list[0]}")

        # Save parsed pins_db to file (append to existing JSON)
        output_path = "fabric_cells.json"

        # ✅ Try to read existing JSON, otherwise start empty
        try:
            with open(output_path, "r") as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {}

        # ✅ Append / replace pins field, keep everything else untouched
        # Merge everything, don't remove existing fields
        existing.update({
            "pins": pins_db.get("pins", []),
            "version": pins_db.get("version", existing.get("version")),
            "units": pins_db.get("units", existing.get("units")),
            "layers": pins_db.get("layers", existing.get("layers")),
            "tracks": pins_db.get("tracks", existing.get("tracks")),
            "die": pins_db.get("die", existing.get("die")),
            "core": pins_db.get("core", existing.get("core")),
        })


        # ✅ Write back without overwriting unrelated fields
        with open(output_path, "w") as f:
            json.dump(existing, f, indent=2)

        print(f"\n✅ Pins appended/updated in {output_path}")


        
    except FileNotFoundError as e:
        print(f"Error: {e}")
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

        

