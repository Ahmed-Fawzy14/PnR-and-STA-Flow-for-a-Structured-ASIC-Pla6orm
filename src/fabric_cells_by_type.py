#!/usr/bin/env python3
"""
Read a fabric DB (with tiles/cells) and emit a JSON mapping
logical type -> list of cells:

{
  "TAP": [
    { "name": "...", "type": "TAP", "x": ..., "y": ..., ... },
    ...
  ],
  "NAND": [
    { "name": "...", "type": "NAND", "x": ..., "y": ..., ... },
    ...
  ],
  ...
}

Assumes instance names follow the pattern:
    <tile_name>__R<row>_<TYPE>_<index>
e.g. "T0Y0__R0_TAP_0", "T0Y0__R0_NAND_0"
"""

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List


def infer_logical_type(inst_name: str) -> str:
    """
    Extract the logical type from an instance name like:
      T0Y0__R0_TAP_0  -> TAP
      T0Y0__R0_NAND_0 -> NAND
    """
    try:
        # Split off tile prefix: "T0Y0__R0_TAP_0" -> "R0_TAP_0"
        after_tile = inst_name.split("__", 1)[1]
        parts = after_tile.split("_")
        # parts = ["R0", "TAP", "0"] -> type is index 1
        if len(parts) >= 2:
            return parts[1]
    except Exception:
        pass
    return "UNKNOWN"


def build_cells_by_type(fabric_db: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Given the fabric DB (with tiles + cells), build a dict:
      type -> list of cell entries
    """
    cells_by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for tile in fabric_db.get("tiles", []):
        tile_name = tile.get("name")
        for cell in tile.get("cells", []):
            inst_name = cell.get("name", "")

            logical_type = infer_logical_type(inst_name)

            entry = {
                "name": inst_name,
                "type": logical_type,
                "x": cell.get("x"),
                "y": cell.get("y"),
                "orient": cell.get("orient"),
                "tile": tile_name,
                "width_sites": cell.get("width_sites"),
                "physical_cell_type": cell.get("physical_cell_type"),
            }

            cells_by_type[logical_type].append(entry)

    return cells_by_type


def main(
    input_path: str = "build/fabric/fabric_db.json",
    output_path: str = "build/fabric/cells_by_type.json",
):
    in_path = Path(input_path)
    out_path = Path(output_path)

    if not in_path.exists():
        raise FileNotFoundError(f"Input fabric DB not found: {in_path}")

    print(f"[INFO] Loading fabric DB from: {in_path}")
    with open(in_path, "r") as f:
        fabric_db = json.load(f)

    print("[INFO] Grouping cells by logical type...")
    cells_by_type = build_cells_by_type(fabric_db)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(cells_by_type, f, indent=2)

    print(f"[INFO] Wrote cells-by-type JSON to: {out_path}")


if __name__ == "__main__":
    main()