#!/usr/bin/env python3
"""
eco_generator.py

Phase 3 ECO driver for the Structured ASIC platform.

By default, this script runs:
  1) Clock Tree Synthesis (CTS) via clock_tree_synthesis.ClockTreeSynthesis
  2) Power-down ECO: tie off unused cells to tie-low / tie-high nets
     sourced from sky130_fd_sc_hd__conb_1 cells, using min-leakage
     input patterns from the Liberty (.lib) file.

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
from typing import Any, Dict, List, Optional, Set, Tuple

# Import CTS implementation (kept in its own script)
from clock_tree_synthesis import ClockTreeSynthesis


# -----------------------------
# Basic JSON helpers
# -----------------------------

def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# -----------------------------
# Liberty (.lib) helpers
# -----------------------------

def _expr_to_pin_pattern(expr: str) -> Dict[str, int]:
    """
    Convert a Liberty 'when' expression like '!A&B&!C' into a pin->0/1 dict:
        '!A&B&!C' -> {'A': 0, 'B': 1, 'C': 0}

    Assumes conditions are conjunctions of literals, which is true for typical
    leakage_power() entries in the sky130 .lib.
    """
    pattern: Dict[str, int] = {}
    if not expr:
        return pattern

    expr = expr.replace(" ", "")
    tokens = expr.split("&")
    for tok in tokens:
        if not tok:
            continue
        if tok in ("1", "0"):
            # Global condition, no pin-specific info.
            continue
        neg = tok.startswith("!")
        pin = tok[1:] if neg else tok
        if not pin:
            continue
        pattern[pin] = 0 if neg else 1
    return pattern


def build_min_leakage_table(lib_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Parse the Liberty .lib file and, for each cell, determine the leakage_power()
    entry with minimum value. Return a table:

      {
        cell_name: {
          "when": <cond_str or None>,
          "value": <float>,
          "pattern": { pin_name: 0 or 1 }
        },
        ...
      }
    """
    if not lib_path.exists():
        raise FileNotFoundError(f"Liberty file not found: {lib_path}")

    leak_entries_by_cell: Dict[str, List[Tuple[Optional[str], float]]] = {}
    current_cell: Optional[str] = None
    pending_value: Optional[float] = None
    pending_when: Optional[str] = None

    with open(lib_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()

            # Start of a cell ("sky130_fd_sc_hd__nand2_1")
            if line.startswith("cell"):
                start = line.find("(")
                end = line.find(")", start + 1)
                if start != -1 and end != -1:
                    name_part = line[start + 1:end].strip()
                    if name_part.startswith('"') and name_part.endswith('"'):
                        name_part = name_part[1:-1]
                    current_cell = name_part
                    leak_entries_by_cell.setdefault(current_cell, [])
                    pending_value = None
                    pending_when = None
                else:
                    current_cell = None
                continue

            if current_cell is None:
                continue

            # leakage_power() block
            if "leakage_power" in line:
                pending_value = None
                pending_when = None
                continue

            if "value" in line and ":" in line:
                try:
                    after = line.split(":", 1)[1]
                    num_str = after.split(";", 1)[0].strip()
                    pending_value = float(num_str)
                except Exception:
                    pending_value = None

                if pending_value is not None and pending_when is not None:
                    leak_entries_by_cell[current_cell].append(
                        (pending_when, pending_value)
                    )
                    pending_value = None
                    pending_when = None
                continue

            if "when" in line and ":" in line:
                try:
                    after = line.split(":", 1)[1]
                    cond_part = after.split(";", 1)[0].strip()
                    if cond_part.startswith('"') and cond_part.endswith('"'):
                        cond_part = cond_part[1:-1]
                    pending_when = cond_part
                except Exception:
                    pending_when = None

                if pending_value is not None and pending_when is not None:
                    leak_entries_by_cell[current_cell].append(
                        (pending_when, pending_value)
                    )
                    pending_value = None
                    pending_when = None
                continue

    table: Dict[str, Dict[str, Any]] = {}
    for cell_name, entries in leak_entries_by_cell.items():
        if not entries:
            continue
        min_when, min_val = min(entries, key=lambda x: x[1])
        pattern = _expr_to_pin_pattern(min_when or "")
        table[cell_name] = {
            "when": min_when,
            "value": min_val,
            "pattern": pattern,
        }

    return table


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


def find_conb1_sources(instances_db: Dict[str, dict]) -> Tuple[
    List[Tuple[str, int]],  # LO sources: (inst_name, lo_bit)
    List[Tuple[str, int]],  # HI sources: (inst_name, hi_bit)
]:
    """
    Find ALL sky130_fd_sc_hd__conb_1 instances that expose LO and/or HI pins.

    Returns:
      (lo_sources, hi_sources)
      where each is a list of (inst_name, net_bit).

    We REQUIRE at least one LO source (tie-low). HI sources are optional.
    """
    lo_sources: List[Tuple[str, int]] = []
    hi_sources: List[Tuple[str, int]] = []

    for inst_name, inst in instances_db.items():
        if inst.get("type") != "sky130_fd_sc_hd__conb_1":
            continue

        pins = inst.get("pins", {})
        lo_bits = pins.get("LO") or []
        hi_bits = pins.get("HI") or []

        if lo_bits:
            try:
                lo_sources.append((inst_name, int(lo_bits[0])))
            except Exception:
                pass
        if hi_bits:
            try:
                hi_sources.append((inst_name, int(hi_bits[0])))
            except Exception:
                pass

    if not lo_sources:
        raise RuntimeError(
            "No sky130_fd_sc_hd__conb_1 with LO pin found in logical_db; "
            "cannot perform power-down ECO."
        )

    if len(lo_sources) > 1 or len(hi_sources) > 1:
        print(
            f"[ECO] INFO: Multiple tie sources available: "
            f"{len(lo_sources)} LO, {len(hi_sources)} HI."
        )

    return lo_sources, hi_sources


# -----------------------------
# Fabric / map helpers
# -----------------------------

def parse_map_file(path: Path) -> Dict[str, str]:
    """
    Parses a .map file of the form:

        <Logical_Name> <Physical_Site_Name>

    Returns: { Logical_Name : Physical_Site_Name }
    """
    mapping: Dict[str, str] = {}
    if not path.exists():
        print(f"[ECO] WARNING: Map file not found: {path}")
        return mapping

    print(f"[ECO] Parsing map file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            inst, slot = parts[0], parts[1]
            mapping[inst] = slot
    return mapping


def load_fabric_cells(path: Path) -> Dict[str, dict]:
    """
    Load the fabric DB JSON and flatten its cells into a dict:

        { cell_name : { "physical_cell_type": ..., ... }, ... }

    From entries like:

        {
          "tiles": [
            {
              "name": "T0Y0",
              "x": 0,
              "y": 0,
              "cells": [
                {
                  "name": "T0Y0__R0_TAP_0",
                  "physical_cell_type": "sky130_fd_sc_hd__tapvpwrvgnd_1",
                  ...
                },
                {
                  "name": "T0Y0__R0_NAND_0",
                  "physical_cell_type": "sky130_fd_sc_hd__nand2_2",
                  ...
                },
                ...
              ]
            },
            ...
          ]
        }
    """
    db = load_json(path)
    cells_by_name: Dict[str, dict] = {}
    for tile in db.get("tiles", []):
        for cell in tile.get("cells", []):
            name = cell.get("name")
            if name:
                cells_by_name[name] = cell
    return cells_by_name


def find_unused_fabric_cells(
    fabric_cells: Dict[str, dict],
    placement_map: Dict[str, str],
) -> Dict[str, dict]:
    """
    Find fabric cells that have NO logical instance mapped to them.

    - fabric_cells: cell_name -> cell_info (from fabric_db)
    - placement_map: logical_inst -> cell_name (from *_cts.map)

    Returns:
      { cell_name : cell_info } for cells that are never used as a mapping target.
    """
    used_slots: Set[str] = set(placement_map.values())
    all_slots: Set[str] = set(fabric_cells.keys())
    unused_slot_names = sorted(all_slots - used_slots)
    return {name: fabric_cells[name] for name in unused_slot_names}


# -----------------------------
# Graph helpers
# -----------------------------

def find_unused_instances_by_empty_fanout(graph: Dict[str, List[str]]) -> Set[str]:
    """
    Unused instances are those that are present as drivers in the netlist
    graph but have an empty fanout list, i.e.:
        "inst_name": []

    NOTE:
      - This captures logical spares that appear in the netlist but drive nothing.
      - Fabric cells with *no mapped instance at all* are tracked separately via
        fabric_db + map (see find_unused_fabric_cells).
    """
    return {drv for drv, sinks in graph.items() if not sinks}


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
      2. All unused instances become sinks of the given conb_1 instance.
      3. Their own fanout stays empty (they drive nothing).

    NOTE:
      - This graph-level representation only captures which driver instance
        feeds which spare instance; it does NOT specify per-pin LO/HI.
      - The actual pin-level tie-off is implemented in generate_verilog.py
        using the same min-leakage patterns derived from the .lib.
    """
    after_graph: Dict[str, List[str]] = {
        drv: list(sinks) for drv, sinks in original_graph.items()
    }

    # 1) Remove unused instances from all drivers' sink lists
    for drv, sinks in after_graph.items():
        after_graph[drv] = [s for s in sinks if s not in unused_insts]

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
    tielo_inst: str,
    tielo_bit: int,
    tiehi_inst: Optional[str],
    tiehi_bit: Optional[int],
    min_leakage_table: Dict[str, Dict[str, Any]],
    fabric_unused_cells: Dict[str, dict],
    slot_to_insts: Dict[str, List[str]],
    out_dir: Path,
):
    """
    Report power-down ECO effects.

    For each ECO-unused logical instance (graph-level spare):
      - Logical DB entry
      - Original + new drivers and fanout
      - Min-leakage tie-off recommendation from .lib
      - Explicit tie-low / tie-high driver instance IDs

    For each fabric-unused cell (slot in fabric_db with no mapped instance):
      - Full cell info (from fabric_db)
      - Min-leakage tie-off recommendation (based on physical_cell_type)
      - Explicit tie-low / tie-high driver instance IDs (conceptual)
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{design}_power_down_eco_report.txt"

    orig_sink_to_drivers = build_sink_to_drivers(original_graph)
    new_sink_to_drivers = build_sink_to_drivers(after_graph)

    with open(report_path, "w", encoding="utf-8") as f:
        # Header
        f.write(f"[ECO REPORT] Design: {design}\n")
        f.write(f"[ECO REPORT] Tie-low (0) driver instance: {tielo_inst}, net bit: {tielo_bit}\n")
        if tiehi_inst is not None and tiehi_bit is not None:
            f.write(f"[ECO REPORT] Tie-high (1) driver instance: {tiehi_inst}, net bit: {tiehi_bit}\n")
        else:
            f.write("[ECO REPORT] No HI source found in logical_db; "
                    "inputs requesting logic '1' will be approximated or tied to LO.\n")
        f.write(f"[ECO REPORT] Number of ECO-unused instances (graph-level): {len(unused_insts)}\n")
        f.write(
            f"[ECO REPORT] Number of unused fabric cells "
            f"(no mapped logical instance): {len(fabric_unused_cells)}\n"
        )
        f.write("\n")

        # Per-instance details (logical ECO spares)
        for inst_name in sorted(unused_insts):
            inst = instances_db.get(inst_name)

            f.write("=" * 80 + "\n")
            f.write(f"Instance: {inst_name}\n")
            if inst is None:
                f.write("  [ERROR] Missing from logical_db\n\n")
                continue

            cell_type = inst.get("type", "<unknown>")

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
                    "now driven only by tie-low/tie-high conb_1 net(s).\n")

            # Explicit tie driver assignment
            f.write("\n  [Tie driver assignment]\n")
            f.write(f"    LO (0) driver: {tielo_inst} (net bit {tielo_bit})\n")
            if tiehi_inst is not None and tiehi_bit is not None:
                f.write(f"    HI (1) driver: {tiehi_inst} (net bit {tiehi_bit})\n")
            else:
                f.write("    HI (1) driver: [no HI source available]\n")

            # Min-leakage recommendation
            leak_info = min_leakage_table.get(cell_type)
            f.write("\n  [Min-leakage tie-off recommendation]\n")
            if leak_info is not None:
                when_expr = leak_info.get("when")
                value = leak_info.get("value")
                pattern = leak_info.get("pattern", {})

                if when_expr is not None:
                    f.write(f"    .lib min-leakage 'when' condition: {when_expr}\n")
                if value is not None:
                    f.write(f"    .lib leakage value: {value}\n")

                if pattern:
                    f.write("    Recommended constant tie-offs (per input pin):\n")
                    for pin_name in sorted(pattern.keys()):
                        bit = pattern[pin_name]
                        tie_str = "TIE-LOW (LO)" if bit == 0 else "TIE-HIGH (HI)"
                        f.write(f"      {pin_name} -> {tie_str}\n")
                else:
                    f.write("    [INFO] No explicit pin pattern parsed; "
                            "defaulting to tie-low for all logic inputs.\n")
            else:
                f.write(f"    [INFO] No leakage_power data for cell type '{cell_type}' "
                        "found in .lib; default to tie-low inputs.\n")

            f.write("\n")

        # Fabric-level unused cells (EVERYTHING, with tie driver info)
        if fabric_unused_cells:
            f.write("=" * 80 + "\n")
            f.write("[Fabric-level unused cells (no mapped logical instance)]\n")
            f.write(
                "These are slots present in fabric_db but never used as a mapping "
                "target in the CTS map. They do not appear as instances in the "
                "logical netlist.\n\n"
            )

            for cell_name in sorted(fabric_unused_cells.keys()):
                cell_info = fabric_unused_cells[cell_name]
                f.write(f"  - Cell: {cell_name}\n")

                # Raw fabric DB entry
                pretty_cell = json.dumps(cell_info, indent=4, sort_keys=True)
                for line in pretty_cell.splitlines():
                    f.write(f"    {line}\n")

                phys_type = cell_info.get("physical_cell_type", "<unknown>")

                # Min-leakage recommendation based on physical cell type
                leak_info = min_leakage_table.get(phys_type)
                f.write("    [Min-leakage tie-off recommendation]\n")
                if leak_info is not None:
                    when_expr = leak_info.get("when")
                    value = leak_info.get("value")
                    pattern = leak_info.get("pattern", {})

                    if when_expr is not None:
                        f.write(f"      .lib min-leakage 'when' condition: {when_expr}\n")
                    if value is not None:
                        f.write(f"      .lib leakage value: {value}\n")

                    if pattern:
                        f.write("      Recommended constant tie-offs (per input pin):\n")
                        for pin_name in sorted(pattern.keys()):
                            bit = pattern[pin_name]
                            tie_str = "TIE-LOW (LO)" if bit == 0 else "TIE-HIGH (HI)"
                            f.write(f"        {pin_name} -> {tie_str}\n")
                    else:
                        f.write("      [INFO] No explicit pin pattern parsed; "
                                "defaulting to tie-low for all logic inputs.\n")
                else:
                    f.write(
                        f"      [INFO] No leakage_power data for physical_cell_type "
                        f"'{phys_type}' found in .lib; default to tie-low inputs.\n"
                    )

                # Conceptual tie drivers to use for this cell
                f.write("    [Tie drivers to use]\n")
                f.write(f"      LO (0) driver: {tielo_inst} (net bit {tielo_bit})\n")
                if tiehi_inst is not None and tiehi_bit is not None:
                    f.write(f"      HI (1) driver: {tiehi_inst} (net bit {tiehi_bit})\n")
                else:
                    f.write("      HI (1) driver: [no HI source available]\n")

                # There are no mapped instances for these cells by definition,
                # but for completeness we still show the mapping (should be []).
                mapped_insts = slot_to_insts.get(cell_name, [])
                f.write(f"    Mapped logical instances: {mapped_insts}\n")
                f.write("\n")

    print(f"[ECO] Wrote power-down ECO report to: {report_path}")


# -----------------------------
# Power-Down ECO core runner
# -----------------------------

def run_power_down_eco(
    design: str,
    build_root: Path = Path("build"),
    lib_path: Optional[Path] = None,
) -> None:
    """
    Run the power-down ECO step for a given design.

    Expects:
      build/<design>/<design>_cts_mapped_netlist_graph.json
      build/<design>/<design>_logical_db.json

    Additionally, for fabric-level unused detection:
      build/fabric/fabric_db.json
      build/<design>/<design>_cts.map

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

    # 0) Min-leakage table from .lib
    min_leakage_table: Dict[str, Dict[str, Any]] = {}
    if lib_path is not None:
        print(f"[ECO] Loading Liberty file for leakage tie-offs: {lib_path}")
        try:
            min_leakage_table = build_min_leakage_table(lib_path)
            print(f"[ECO] Min-leakage table covers {len(min_leakage_table)} cell types.")
        except Exception as e:
            print(f"[ECO] WARNING: failed to parse .lib for leakage info: {e}")
            min_leakage_table = {}
    else:
        print("[ECO] No .lib path provided; leakage-based recommendations disabled.")
        min_leakage_table = {}

    # 1) Find ALL conb_1 LO/HI sources
    tie_lo_sources, tie_hi_sources = find_conb1_sources(instances_db)

    # We will use ONE LO net and ONE HI net as the global tie nets
    tielo_inst, tielo_bit = tie_lo_sources[0]
    if tie_hi_sources:
        tiehi_inst, tiehi_bit = tie_hi_sources[0]
    else:
        tiehi_inst, tiehi_bit = None, None

    print(f"[ECO] Using tie-low driver: {tielo_inst} (LO bit = {tielo_bit})")
    print(f"[ECO] Available tie sources: {len(tie_lo_sources)} LO, {len(tie_hi_sources)} HI.")

    conb_inst_for_graph = tielo_inst

    # 2) Find unused instances by empty fanout in netlist graph
    unused_insts = find_unused_instances_by_empty_fanout(original_graph)
    print(f"[ECO] Unused instances by empty fanout (graph-level spares): {len(unused_insts)}")

    # 2.5) Export unused-instance list + tie info
    unused_list_path = base_dir / f"{design}_pd_unused_instances.json"
    tie_info_path = base_dir / f"{design}_pd_tielo_source.json"

    save_json(unused_list_path, sorted(list(unused_insts)))
    tie_info_payload = {
        "tielo_inst": tielo_inst,
        "tielo_net_bit": tielo_bit,
    }
    if tiehi_inst is not None and tiehi_bit is not None:
        tie_info_payload["tiehi_inst"] = tiehi_inst
        tie_info_payload["tiehi_net_bit"] = tiehi_bit
    save_json(tie_info_path, tie_info_payload)

    print(f"[ECO] Wrote unused-instance list to: {unused_list_path}")
    print(f"[ECO] Wrote tie-low/high source info to:  {tie_info_path}")

    # 2.6) Fabric-level unused cells (no mapped instance)
    fabric_unused_cells: Dict[str, dict] = {}
    slot_to_insts: Dict[str, List[str]] = {}
    fabric_db_path = build_root / "fabric" / "fabric_db.json"
    cts_map_path = base_dir / f"{design}_cts.map"

    if fabric_db_path.exists() and cts_map_path.exists():
        try:
            print(f"[ECO] Loading fabric DB from: {fabric_db_path}")
            fabric_cells = load_fabric_cells(fabric_db_path)
            placement_map = parse_map_file(cts_map_path)

            slot_to_insts = defaultdict(list)
            for inst, slot in placement_map.items():
                slot_to_insts[slot].append(inst)

            fabric_unused_cells = find_unused_fabric_cells(fabric_cells, placement_map)
            print(f"[ECO] Fabric cells with no mapped instance: {len(fabric_unused_cells)}")
        except Exception as e:
            print(f"[ECO] WARNING: failed to analyze fabric-level unused cells: {e}")
            fabric_unused_cells = {}
            slot_to_insts = {}
    else:
        print("[ECO] Fabric DB or CTS map not found; skipping fabric-level unused analysis.")
        fabric_unused_cells = {}
        slot_to_insts = {}

    # 3) Apply ECO to build the "after" graph
    after_graph = apply_pd_eco_to_graph(
        original_graph=original_graph,
        unused_insts=unused_insts,
        conb_inst=conb_inst_for_graph,
    )

    # 4) Save updated graph
    save_json(after_graph_path, after_graph)
    print(f"[ECO] Saved updated netlist graph (after power-down ECO):")
    print(f"      {after_graph_path}")

    # 5) Write verification report (including leakage recommendations + fabric info)
    write_pd_eco_report(
        design=design,
        instances_db=instances_db,
        original_graph=original_graph,
        after_graph=after_graph,
        unused_insts=unused_insts,
        tielo_inst=tielo_inst,
        tielo_bit=tielo_bit,
        tiehi_inst=tiehi_inst,
        tiehi_bit=tiehi_bit,
        min_leakage_table=min_leakage_table,
        fabric_unused_cells=fabric_unused_cells,
        slot_to_insts=slot_to_insts,
        out_dir=base_dir,
    )


# -----------------------------
# CTS runner
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
        "--lib",
        default="tech/sky130_fd_sc_hd__tt_025C_1v80.lib",
        help=(
            "Liberty .lib file used to compute min-leakage tie-offs for "
            "unused cells (default: tech/sky130_fd_sc_hd__tt_025C_1v80.lib)"
        ),
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
    lib_path = Path(args.lib) if args.lib is not None else None

    # Default: run both CTS and power-down ECO.
    if not args.skip_cts:
        run_cts(design, build_dir, designs_dir)

    if not args.skip_pd:
        run_power_down_eco(design, Path(build_dir), lib_path)


if __name__ == "__main__":
    main()
