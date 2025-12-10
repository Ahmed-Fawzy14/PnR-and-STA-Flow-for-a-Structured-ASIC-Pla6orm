#!/usr/bin/env python3
# eco_generator.py
"""
eco_generator.py

Phase 3 ECO driver for the Structured ASIC platform.

By default, this script runs:
  1) Clock Tree Synthesis (CTS) via clock_tree_synthesis.ClockTreeSynthesis
  2) Power-down ECO: tie off unused cells to a single sky130_fd_sc_hd__conb_1 LO pin.

Usage:
    # Full Phase 3: CTS then Power-Down ECO
    python eco_generator.py --design 6502

    # CTS only (no power-down ECO)
    python eco_generator.py --design 6502 --skip-pd

    # Power-down ECO only (skip CTS, expects *_cts_mapped_netlist_graph.json already)
    python eco_generator.py --design 6502 --skip-cts
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Import CTS implementation (kept in its own script)
from clock_tree_synthesis import ClockTreeSynthesis


# -----------------------------
# Basic JSON helpers
# -----------------------------

def load_json(path: Path):
    with open(path, "r") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# -----------------------------
# Logical DB helpers
# -----------------------------

def extract_instances_dict(logical_db_raw) -> Dict[str, dict]:
    """
    Try to extract the instances dictionary from whatever format
    the logical_db JSON uses.

    Supported formats:
      1) { "instances": { inst_name: { "type": ..., "pins": ... }, ... }, ... }
      2) { inst_name: { "type": ..., "pins": ... }, ... }
    """
    if not isinstance(logical_db_raw, dict):
        raise ValueError("logical_db JSON is not a dict")

    # Format 1: has a top-level 'instances' dict
    if "instances" in logical_db_raw and isinstance(logical_db_raw["instances"], dict):
        return logical_db_raw["instances"]

    # Format 2: flat dict of instances
    values = list(logical_db_raw.values())
    if values and all(isinstance(v, dict) and "type" in v for v in values):
        return logical_db_raw  # looks like {inst_name: {type:..., pins:...}}

    raise ValueError("Could not recognize instances structure in logical_db.json")


def find_single_conb1_lo(instances_db: Dict[str, dict]) -> Tuple[str, int]:
    """
    Find a SINGLE sky130_fd_sc_hd__conb_1 instance with an LO pin.
    Returns (instance_name, lo_net_bit).
    Raises if 0 found; warns if >1 and picks the first.
    """
    candidates = []
    for inst_name, inst in instances_db.items():
        if inst.get("type") == "sky130_fd_sc_hd__conb_1":
            pins = inst.get("pins", {})
            if "LO" in pins and pins["LO"]:
                # Take the first bit for LO
                lo_bits = pins["LO"]
                lo_bit = int(lo_bits[0])
                candidates.append((inst_name, lo_bit))

    if not candidates:
        raise RuntimeError(
            "No sky130_fd_sc_hd__conb_1 with LO pin found in logical_db; "
            "cannot perform power-down ECO."
        )

    if len(candidates) > 1:
        print("[ECO] WARNING: Multiple conb_1 instances with LO found; using the first one.")

    return candidates[0]


# -----------------------------
# Graph helpers
# -----------------------------

def find_unused_instances_by_empty_fanout(graph: Dict[str, List[str]]) -> Set[str]:
    """
    Unused instances are those that are present as drivers in the netlist
    graph but have an empty fanout list, i.e.:
        "inst_name": []
    """
    unused = {drv for drv, sinks in graph.items() if not sinks}
    return unused


def build_sink_to_drivers(graph: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """
    Reverse adjacency:
        sink_to_drivers[sink] = [driver1, driver2, ...]
    """
    sink_to_drivers: Dict[str, List[str]] = defaultdict(list)
    for drv, sinks in graph.items():
        for s in sinks:
            sink_to_drivers[s].append(drv)
    return sink_to_drivers


def apply_pd_eco_to_graph(
    original_graph: Dict[str, List[str]],
    unused_insts: Set[str],
    conb_inst: str,
) -> Dict[str, List[str]]:
    """
    Build the <design>_mapped_netlist_graph_after_pd_eco.json.

    Rules:
      1. Any appearance of an unused instance as a SINK of some driver
         is removed (we disconnect it from functional logic).
      2. All unused instances become sinks of the single conb_1 instance.
      3. Their own fanout stays empty (they drive nothing).
    """
    # Deep copy the original graph (copy lists)
    after_graph: Dict[str, List[str]] = {
        drv: list(sinks) for drv, sinks in original_graph.items()
    }

    # 1) Remove unused instances from all drivers' sink lists
    for drv, sinks in after_graph.items():
        new_sinks = [s for s in sinks if s not in unused_insts]
        after_graph[drv] = new_sinks

    # 2) Add all unused instances as sinks of the conb_1 instance
    conb_sinks = after_graph.setdefault(conb_inst, [])
    for u in sorted(unused_insts):
        if u not in conb_sinks:
            conb_sinks.append(u)

    return after_graph


# -----------------------------
# Reporting
# -----------------------------

def write_pd_eco_report(
    design: str,
    instances_db: Dict[str, dict],
    original_graph: Dict[str, List[str]],
    after_graph: Dict[str, List[str]],
    unused_insts: Set[str],
    conb_inst: str,
    conb_lo_bit: int,
    out_dir: Path,
):
    """
    Create a text report that, for each unused cell, shows:
      - Logical DB entry (type + pins + attrs)
      - What was done in the netlist graph:
          · Original drivers of this instance
          · New drivers after ECO
          · Fanout of this instance before/after
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{design}_power_down_eco_report.txt"

    orig_sink_to_drivers = build_sink_to_drivers(original_graph)
    new_sink_to_drivers = build_sink_to_drivers(after_graph)

    # Use ASCII arrows (->) and UTF-8 encoding to avoid Windows cp1252 issues
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"[ECO REPORT] Design: {design}\n")
        f.write(f"[ECO REPORT] Tie-low source instance: {conb_inst}\n")
        f.write(f"[ECO REPORT] Tie-low net bit (LO): {conb_lo_bit}\n")
        f.write(f"[ECO REPORT] Number of ECO-unused instances: {len(unused_insts)}\n\n")

        for inst_name in sorted(unused_insts):
            inst = instances_db.get(inst_name)

            f.write("=" * 80 + "\n")
            f.write(f"Instance: {inst_name}\n")
            if inst is None:
                f.write("  [ERROR] Missing from logical_db\n\n")
                continue

            # Logical DB entry
            f.write("  [Logical DB entry]\n")
            pretty = json.dumps(inst, indent=4, sort_keys=True)
            for line in pretty.splitlines():
                f.write(f"    {line}\n")

            # Graph connectivity (before / after)
            orig_fanout = original_graph.get(inst_name, [])
            new_fanout = after_graph.get(inst_name, [])

            orig_drivers = orig_sink_to_drivers.get(inst_name, [])
            new_drivers = new_sink_to_drivers.get(inst_name, [])

            f.write("\n  [Netlist graph connectivity]\n")
            f.write(f"    Original fanout (inst -> sinks): {orig_fanout}\n")
            f.write(f"    New fanout      (inst -> sinks): {new_fanout}\n")
            f.write(f"    Original drivers (-> inst):      {orig_drivers}\n")
            f.write(f"    New drivers      (-> inst):      {new_drivers}\n")
            f.write("    ECO action: disconnected from original drivers; "
                    "now driven only by tie-low conb_1.\n\n")

    print(f"[ECO] Wrote power-down ECO report to: {report_path}")


# -----------------------------
# Power-Down ECO core runner
# -----------------------------

def run_power_down_eco(design: str, build_root: Path = Path("build")) -> None:
    """
    Run the power-down ECO step for a given design.

    Expects:
      build/<design>/<design>_cts_mapped_netlist_graph.json
      build/<design>/<design>_logical_db.json

    Produces:
      build/<design>/<design>_mapped_netlist_graph_after_pd_eco.json
      build/<design>/<design>_power_down_eco_report.txt
      build/<design>/<design>_pd_unused_instances.json
      build/<design>/<design>_pd_tielo_source.json
    """
    base_dir = build_root / design
    netlist_graph_path = base_dir / f"{design}_cts_mapped_netlist_graph.json"
    logical_db_path = base_dir / f"{design}_logical_db.json"
    after_graph_path = base_dir / f"{design}_mapped_netlist_graph_after_pd_eco.json"

    if not netlist_graph_path.exists():
        raise FileNotFoundError(f"Netlist graph not found: {netlist_graph_path}")
    if not logical_db_path.exists():
        raise FileNotFoundError(f"Logical DB not found: {logical_db_path}")

    print(f"[ECO] Design: {design}")
    print(f"[ECO] Loading logical DB from: {logical_db_path}")
    print(f"[ECO] Loading netlist graph from: {netlist_graph_path}")

    logical_db_raw = load_json(logical_db_path)
    instances_db = extract_instances_dict(logical_db_raw)
    original_graph = load_json(netlist_graph_path)

    print(f"[ECO] Total instances in logical_db: {len(instances_db)}")

    # 1) Find the conb_1 LO source
    conb_inst, conb_lo_bit = find_single_conb1_lo(instances_db)
    print(f"[ECO] Using tie-low driver: {conb_inst} (LO bit = {conb_lo_bit})")

    # 2) Find unused instances by empty fanout in netlist graph
    unused_insts = find_unused_instances_by_empty_fanout(original_graph)
    print(f"[ECO] Unused instances by empty fanout: {len(unused_insts)}")

    # 2.5) Export unused-instance list + tie-low info for visualization
    unused_list_path = base_dir / f"{design}_pd_unused_instances.json"
    tie_info_path = base_dir / f"{design}_pd_tielo_source.json"

    save_json(unused_list_path, sorted(list(unused_insts)))
    save_json(
        tie_info_path,
        {
            "tielo_inst": conb_inst,
            "tielo_net_bit": conb_lo_bit,
        },
    )

    print(f"[ECO] Wrote unused-instance list to: {unused_list_path}")
    print(f"[ECO] Wrote tie-low source info to:  {tie_info_path}")

    # 3) Apply ECO to build the "after" graph
    after_graph = apply_pd_eco_to_graph(
        original_graph=original_graph,
        unused_insts=unused_insts,
        conb_inst=conb_inst,
    )

    # 4) Save updated graph
    save_json(after_graph_path, after_graph)
    print(f"[ECO] Saved updated netlist graph (after power-down ECO):")
    print(f"      {after_graph_path}")

    # 5) Write verification report
    write_pd_eco_report(
        design=design,
        instances_db=instances_db,
        original_graph=original_graph,
        after_graph=after_graph,
        unused_insts=unused_insts,
        conb_inst=conb_inst,
        conb_lo_bit=conb_lo_bit,
        out_dir=base_dir,
    )


# -----------------------------
# CTS runner (called from here, but CTS script stays separate)
# -----------------------------

def run_cts(
    design: str,
    build_dir: str = "build",
    designs_dir: str = "designs",
) -> None:
    """
    Run Clock Tree Synthesis (CTS) for the given design.

    This simply wraps ClockTreeSynthesis.run(...) with the same default
    paths that clock_tree_synthesis.py uses in its own CLI.
    """
    print("\n" + "=" * 60)
    print(f"[ECO] Running Clock Tree Synthesis (CTS) for {design}")
    print("=" * 60 + "\n")

    build_root = Path(build_dir)
    design_build = build_root / design
    designs_root = Path(designs_dir)

    map_file = design_build / f"{design}_sa.map"
    logical_db_file = design_build / f"{design}_logical_db.json"
    fabric_db_file = build_root / "fabric" / "cells_by_type.json"
    output_map_file = design_build / f"{design}_cts.map"
    cts_info_file = design_build / f"{design}_cts.json"
    mapped_json_file = designs_root / f"{design}_mapped.json"
    output_json_file = design_build / f"{design}_cts_mapped.json"

    cts = ClockTreeSynthesis(design, build_dir)
    cts.run(
        str(map_file),
        str(logical_db_file),
        str(fabric_db_file),
        str(output_map_file),
        str(cts_info_file),
        str(mapped_json_file),
        str(output_json_file),
    )


# -----------------------------
# CLI entry point
# -----------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Phase 3 ECO driver: runs CTS and/or power-down ECO.\n"
            "Default: run CTS first, then power-down ECO."
        )
    )
    parser.add_argument(
        "--design",
        required=True,
        help="Design name (expects build/<design>/ etc.).",
    )
    parser.add_argument(
        "--build-dir",
        default="build",
        help="Build directory root (default: build)",
    )
    parser.add_argument(
        "--designs-dir",
        default="designs",
        help="Directory containing <design>_mapped.json (default: designs)",
    )
    parser.add_argument(
        "--skip-cts",
        action="store_true",
        help="Skip CTS step and only run power-down ECO.",
    )
    parser.add_argument(
        "--skip-pd",
        action="store_true",
        help="Skip power-down ECO (run CTS only).",
    )

    args = parser.parse_args()

    if args.skip_cts and args.skip_pd:
        raise SystemExit("Error: cannot skip both CTS and power-down ECO.")

    design = args.design
    build_dir = args.build_dir
    designs_dir = args.designs_dir

    # Default: run both CTS and power-down ECO.
    if not args.skip_cts:
        run_cts(design, build_dir, designs_dir)

    if not args.skip_pd:
        run_power_down_eco(design, Path(build_dir))


if __name__ == "__main__":
    main()