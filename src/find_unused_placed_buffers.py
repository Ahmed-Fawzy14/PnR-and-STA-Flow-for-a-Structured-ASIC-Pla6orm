#!/usr/bin/env python3
"""
Utility script to identify placed-but-unused buffer/inverter instances.

Definition used here:
    Placed-but-unused buffer = instance that appears in the placement map
    (slot already claimed) but does NOT appear in the logical netlist.

Unlike the CTS flow—which needs physically free slots—this script is purely
diagnostic and helps you audit buffers that were placed yet never referenced
by the netlist (e.g., dead buffers left over from synthesis).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, Iterable, List, Set, Tuple


def load_placement_map(map_file: str) -> Dict[str, str]:
    """Return {instance_name: slot_name} mapping from placement map."""
    placement: Dict[str, str] = {}
    if not os.path.exists(map_file):
        raise FileNotFoundError(f"Placement map not found: {map_file}")

    with open(map_file, "r") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            inst_name, slot_name = parts[0], parts[1]
            placement[inst_name] = slot_name

    return placement


def load_netlist_instances(netlist_file: str) -> Set[str]:
    """
    Extract the set of cell instance names that appear in the JSON netlist.

    Supports standard Yosys JSON structure:
        {
            "modules": {
                "top": {
                    "cells": {
                        "inst1": {...},
                        ...
                    }
                }
            }
        }
    """
    if not os.path.exists(netlist_file):
        raise FileNotFoundError(f"Netlist JSON not found: {netlist_file}")

    with open(netlist_file, "r") as f:
        data = json.load(f)

    modules = data.get("modules")
    if not isinstance(modules, dict) or not modules:
        raise ValueError(
            "Netlist JSON missing 'modules' dictionary. "
            "Provide a Yosys-style mapped netlist."
        )

    instances: Set[str] = set()
    for module_name, module_data in modules.items():
        cells = module_data.get("cells", {})
        if not isinstance(cells, dict):
            continue
        instances.update(cells.keys())

    if not instances:
        raise ValueError(
            "No cell instances discovered in the provided netlist. "
            "Ensure you passed the mapped netlist JSON."
        )

    return instances


def filter_buffer_slots(
    placement: Dict[str, str], slot_keywords: Iterable[str]
) -> Dict[str, str]:
    """
    Return {instance: slot} for placement entries whose slot name contains any
    of the provided keywords (case-insensitive).
    """
    keywords = tuple(keyword.lower() for keyword in slot_keywords)
    buffers: Dict[str, str] = {}

    for inst_name, slot_name in placement.items():
        slot_name_lower = slot_name.lower()
        if any(keyword in slot_name_lower for keyword in keywords):
            buffers[inst_name] = slot_name

    return buffers


def find_placed_but_unused_buffers(
    placement_map: Dict[str, str],
    netlist_instances: Set[str],
    slot_keywords: Iterable[str],
) -> List[Tuple[str, str]]:
    """
    Identify buffers that are present in placement_map but absent from netlist.

    Returns a list of tuples: (instance_name, slot_name)
    """
    buffers = filter_buffer_slots(placement_map, slot_keywords)
    unused = [
        (inst_name, buffers[inst_name])
        for inst_name in buffers
        if inst_name not in netlist_instances
    ]
    return unused


def write_results(
    unused_buffers: List[Tuple[str, str]], output_file: str
) -> None:
    """Persist results as JSON for downstream tooling."""
    payload = [
        {"instance": inst_name, "slot": slot_name}
        for inst_name, slot_name in unused_buffers
    ]
    with open(output_file, "w") as f:
        json.dump(payload, f, indent=2)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Identify placed-but-unused buffers by comparing "
        "placement map contents against a mapped netlist JSON."
    )
    parser.add_argument(
        "--map",
        required=True,
        help="Path to placement map file (e.g., build/6502/6502.map)",
    )
    parser.add_argument(
        "--netlist",
        required=True,
        help="Path to mapped netlist JSON (e.g., build/6502/6502_mapped.json)",
    )
    parser.add_argument(
        "--slot-keywords",
        nargs="+",
        default=["buf", "inv"],
        help="Keywords used to classify buffer slots (case-insensitive). "
        "Defaults to ['buf', 'inv'].",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write JSON report of unused buffers.",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    placement = load_placement_map(args.map)
    netlist_instances = load_netlist_instances(args.netlist)

    unused_buffers = find_placed_but_unused_buffers(
        placement, netlist_instances, args.slot_keywords
    )

    total_buffers = len(
        filter_buffer_slots(placement, args.slot_keywords)
    )

    print("\n============================================================")
    print("Placed-but-unused Buffer Report")
    print("============================================================")
    print(f"Placement map: {args.map}")
    print(f"Netlist JSON:  {args.netlist}")
    print(
        f"Slot keywords: {', '.join(args.slot_keywords)} "
        f"(matched {total_buffers} buffer instances)"
    )
    print("------------------------------------------------------------")
    print(f"Total placed buffers: {total_buffers}")
    print(f"Placed buffers missing from netlist: {len(unused_buffers)}")
    print("------------------------------------------------------------")

    if unused_buffers:
        print("Sample (instance → slot):")
        for inst_name, slot_name in unused_buffers[:10]:
            print(f"  {inst_name} -> {slot_name}")
    else:
        print("All placed buffers are referenced by the netlist.")

    if args.output:
        write_results(unused_buffers, args.output)
        print("------------------------------------------------------------")
        print(f"Wrote detailed report to: {args.output}")

    print("============================================================\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))



