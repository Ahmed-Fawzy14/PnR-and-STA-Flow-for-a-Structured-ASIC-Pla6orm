#!/usr/bin/env python3
# dataStructuresGenerator_SA.py

"""
Data structures generator for greedy + simulated annealing (SA).

Input:
  - logical_db.json (schema: Logical DB v1.0)
  - fabric_db.json  (fabric slots: NAND/INV/DFBBP/... groups)

Output:
  - data_structures.json with three main sections:
      {
        "logical": {
          "instances": [...],
          "cell_type": {...},
          "is_seq": {...},
          "is_buffer": {...},
          "pins": {...}
        },
        "fabric": {
          "slot_info": {...},
          "slots_by_phys_type": {...}
        },
        "nets": {
          "net_graph": {...},   # copied from logical_db["net_graph"] if present
          "neighbors": {...}    # inst -> [neighbor_insts...]
        }
      }

This is design-independent and strictly follows your Logical DB schema:
  - instances are ONLY under logical_db["instances"]
  - no guessing from any other top-level keys
"""

import argparse
import json
import os
from typing import Any, Dict, List, Set


# ---------------- IO helpers ----------------

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir_for(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


# ---------------- Logical section ----------------

def build_logical_section(logical_db: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the logical section strictly according to the Logical DB schema
    AND in the correct form required by Simulated Annealing.

    logical.instances MUST be a dict:
        inst_name -> {type, pins, attrs, params}

    We ALSO produce helper flattened structures:
        - instance_order : list of inst names
        - cell_type      : inst_name -> type
        - is_seq         : inst_name -> bool
        - is_buffer      : inst_name -> bool
        - pins           : inst_name -> {pin: [bits]}

    Returns a dict suitable for data_structures.json:
    {
        "instances": {inst_name: cell_info},   <-- REQUIRED for SA
        "instance_order": [...],
        "cell_type": {...},
        "is_seq": {...},
        "is_buffer": {...},
        "pins": {...}
    }
    """
    if "instances" not in logical_db:
        raise ValueError("logical_db missing required field: 'instances'")

    instances_dict = logical_db["instances"]
    if not isinstance(instances_dict, dict):
        raise ValueError("'instances' must be a dict of inst_name -> cell_info")

    # These will be filled by iterating instances_dict
    instance_order: List[str] = []
    cell_type: Dict[str, str] = {}
    is_seq: Dict[str, bool] = {}
    is_buffer: Dict[str, bool] = {}
    pins_per_inst: Dict[str, Dict[str, List[int]]] = {}

    for inst_name, cell in instances_dict.items():
        if not isinstance(cell, dict):
            raise ValueError(f"Instance '{inst_name}' is not an object (schema violation).")

        if "type" not in cell:
            raise ValueError(f"Instance '{inst_name}' missing required field: 'type'")

        if "pins" not in cell:
            raise ValueError(f"Instance '{inst_name}' missing required field: 'pins'")

        instance_order.append(inst_name)

        # ---- cell type ----
        ctype = cell["type"]
        cell_type[inst_name] = ctype

        # ---- attributes ----
        attrs = cell.get("attrs", {})
        is_seq[inst_name] = bool(attrs.get("is_seq", False))
        is_buffer[inst_name] = bool(attrs.get("is_buffer", False))

        # ---- pins ----
        pins_dict = cell["pins"]
        if not isinstance(pins_dict, dict):
            raise ValueError(f"Instance '{inst_name}'.pins must be a dict")
        pins_per_inst[inst_name] = pins_dict

    # -------- return in SA-compatible shape --------
    return {
        "instances": instances_dict,      # DICT -> REQUIRED by SA
        "instance_order": instance_order, # helpful
        "cell_type": cell_type,
        "is_seq": is_seq,
        "is_buffer": is_buffer,
        "pins": pins_per_inst,
    }


# ---------------- Fabric section ----------------

def build_fabric_section(fabric_db: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the fabric section from fabric_db.

    We scan all top-level keys whose values are lists (e.g., "NAND", "INV",
    "DFBBP", "CONB", ...). Each list entry that has both "name" and
    "physical_cell_type" is treated as a usable slot.

    Returns:
      {
        "slot_info": {
          slot_name: {
            "type": <fabric logical type e.g. "NAND">,
            "physical_cell_type": <string>,
            "x": float,
            "y": float,
            "tile": <string>,
            "width_sites": int,
            "orient": <string>,
          },
          ...
        },
        "slots_by_phys_type": {
          "sky130_fd_sc_hd__nand2_2": [slot0, slot1, ...],
          "sky130_fd_sc_hd__dfbbp_2": [...],
          ...
        }
      }
    """
    slot_info: Dict[str, Dict[str, Any]] = {}
    slots_by_phys_type: Dict[str, List[str]] = {}

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
                continue  # not a placed standard cell slot

            slot_info[name] = {
                "type": slot.get("type"),
                "physical_cell_type": phys,
                "x": slot.get("x"),
                "y": slot.get("y"),
                "tile": slot.get("tile"),
                "width_sites": slot.get("width_sites"),
                "orient": slot.get("orient"),
            }

            slots_by_phys_type.setdefault(phys, []).append(name)

    # Deterministic ordering of slots for each type
    for phys_type in slots_by_phys_type:
        slots_by_phys_type[phys_type].sort()

    return {
        "slot_info": slot_info,
        "slots_by_phys_type": slots_by_phys_type,
    }


# ---------------- Nets / neighbors section ----------------

def build_nets_section(logical_db: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build nets / neighbor section using logical_db["net_graph"] if present.

    Schema from your logical DB:

      "net_graph": {
        <bit_id>: {
          "drivers": [[inst_name, pin_name], ...],
          "sinks":   [[inst_name, pin_name], ...]
        },
        ...
      }

    We keep net_graph as-is and also build a simple neighbor map:
      neighbors[inst] = sorted(list_of_other_instances_sharing_any_net)
    """
    instances_dict = logical_db.get("instances", {})
    inst_names: Set[str] = set(instances_dict.keys())

    net_graph = logical_db.get("net_graph", {})
    if not isinstance(net_graph, dict):
        # If absent or malformed, just return empty neighbors
        return {
            "net_graph": {},
            "neighbors": {},
        }

    neighbors: Dict[str, Set[str]] = {inst: set() for inst in inst_names}

    for bit_id, info in net_graph.items():
        if not isinstance(info, dict):
            continue

        drivers = info.get("drivers", []) or []
        sinks = info.get("sinks", []) or []

        # endpoints is list of instance names on this net
        endpoints: List[str] = []
        for inst, _pin in drivers:
            if inst in inst_names:
                endpoints.append(inst)
        for inst, _pin in sinks:
            if inst in inst_names:
                endpoints.append(inst)

        if len(endpoints) < 2:
            continue

        # Pairwise connect all instances that share this net
        unique_endpoints = list(dict.fromkeys(endpoints))  # remove duplicates, keep order
        n = len(unique_endpoints)
        for i in range(n):
            a = unique_endpoints[i]
            for j in range(i + 1, n):
                b = unique_endpoints[j]
                neighbors[a].add(b)
                neighbors[b].add(a)

    # Convert neighbor sets to sorted lists and drop empty ones
    neighbors_list: Dict[str, List[str]] = {
        inst: sorted(list(nbrs))
        for inst, nbrs in neighbors.items()
        if nbrs
    }

    return {
        "net_graph": net_graph,
        "neighbors": neighbors_list,
    }


# ---------------- CLI / main ----------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate data structures for greedy/SA placer.")
    p.add_argument("--logical-db", required=True, help="Path to logical_db.json")
    p.add_argument("--fabric-db", required=True, help="Path to fabric_db.json")
    # Name chosen to match your existing usage:
    p.add_argument("--out-json", required=True, help="Where to write data_structures.json")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print(f"[INFO] Loading logical_db from '{args.logical_db}'...")
    logical_db = load_json(args.logical_db)

    print(f"[INFO] Loading fabric_db from '{args.fabric_db}'...")
    fabric_db = load_json(args.fabric_db)

    print("[INFO] Building logical section...")
    logical_section = build_logical_section(logical_db)

    print("[INFO] Building fabric section...")
    fabric_section = build_fabric_section(fabric_db)

    print("[INFO] Building nets / neighbor section...")
    nets_section = build_nets_section(logical_db)

    out_obj = {
        "logical": logical_section,
        "fabric": fabric_section,
        "nets": nets_section,
    }

    ensure_dir_for(args.out_json)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out_obj, f, indent=2, sort_keys=True)

    print(f"[INFO] Wrote data structures to '{args.out_json}'.")


if __name__ == "__main__":
    main()