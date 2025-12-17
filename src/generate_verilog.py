#!/usr/bin/env python3
# generate_verilog.py
"""
generate_verilog_from_pd_eco.py

Generate a gate-level Verilog netlist from:
  - build/<design>/data_structures.json
  - build/<design>/<design>_mapped_netlist_graph_after_pd_eco.json
  - build/<design>/<design>_logical_db.json  (for ports)
  - build/<design>/<design>_pd_tielo_source.json (LO/HI tie net info)
  - tech/sky130_fd_sc_hd__tt_025C_1v80.lib    (for min-leakage patterns)
  - build/fabric/fabric_db.json + build/<design>/<design>_cts.map
    (to instantiate unused fabric cells)

Rules:
  - "Design" instances come from data_structures["logical_db"].
  - "Fabric-only" cells (unused slots) come from fabric_db.
  - Spares (graph-level unused) are instances whose AFTER-PD graph entry
    has an empty sink list:  inst -> [].
  - Tie-low / tie-high nets come from <design>_pd_tielo_source.json.
  - Min-leakage input patterns per cell type come from the Liberty .lib.
  - For spares:
      * Input pins are tied according to the min-leak pattern:
          0 -> tie-low net
          1 -> tie-high net (if available, else tie-low)
      * Output pins (X, Y, Z, Q, LO, HI, etc.) and power pins are left as-is.
  - Non-logic cells (tap / decap / fill) are instantiated but NOT ECO-tied
    to conb_1 (no LO/HI connections created by this script).

Top module name:
  - module mod_<design> ( ... );
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# -----------------------------
# Basic I/O helpers
# -----------------------------

def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# -----------------------------
# Liberty (.lib) helpers
# -----------------------------

def _expr_to_pin_pattern(expr: str) -> Dict[str, int]:
    """
    Convert a Liberty 'when' expression like '!A&B&!C' into a pin->0/1 dict:
        '!A&B&!C' -> {'A': 0, 'B': 1, 'C': 0}

    We assume conditions are conjunctions of literals, which is typical
    for leakage_power() entries in standard-cell .lib files.
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
# Data structures helpers
# -----------------------------

def extract_instances_from_data_structures(ds_raw) -> Dict[str, dict]:
    """
    data_structures.json format (from generate_db.py):

      {
        "logical_db": { inst_name: { "type": ..., "pins": ... }, ... },
        ...
      }

    We just return logical_db (already the instances dict).
    """
    if not isinstance(ds_raw, dict):
        raise ValueError("data_structures.json top-level is not a dict")

    logical_db = ds_raw.get("logical_db")
    if not isinstance(logical_db, dict):
        raise ValueError("data_structures.json missing 'logical_db' dict")

    return logical_db


def extract_ports_from_logical_db(logical_raw) -> Dict[str, dict]:
    """
    Extract ports from <design>_logical_db.json.

    Expected shape (Yosys-style):

      {
        "ports": {
          "A": { "direction": "input",  "bits": [ ... ] },
          "Y": { "direction": "output", "bits": [ ... ] },
          ...
        },
        ...
      }
    """
    if not isinstance(logical_raw, dict):
        raise ValueError("logical_db JSON top-level is not a dict")

    ports = logical_raw.get("ports", {})
    if not isinstance(ports, dict):
        raise ValueError("logical_db JSON missing 'ports' dict")

    for pname, pinfo in ports.items():
        if not isinstance(pinfo, dict):
            raise ValueError(f"Port {pname} entry is not a dict")
        if "bits" not in pinfo:
            raise ValueError(f"Port {pname} missing 'bits' field")
        if "direction" not in pinfo:
            pinfo["direction"] = "input"

    return ports


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
        print(f"[VERILOG] WARNING: Map file not found: {path}")
        return mapping

    print(f"[VERILOG] Parsing map file: {path}")
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
    Fabric cells that have NO logical instance mapped to them:

      - fabric_cells: cell_name -> cell_info
      - placement_map: logical_inst -> cell_name

    Returns: { cell_name : cell_info }
    """
    used_slots: Set[str] = set(placement_map.values())
    all_slots: Set[str] = set(fabric_cells.keys())
    unused_slot_names = sorted(all_slots - used_slots)
    return {name: fabric_cells[name] for name in unused_slot_names}


# -----------------------------
# Pin / cell classification
# -----------------------------

COMMON_OUTPUT_NAMES = {
    "X", "Y", "Z", "ZN",
    "Q", "QN", "Q_N",
    "LO", "HI",
}

POWER_PINS = {
    "VPWR", "VGND", "VPB", "VNB",
    "VDD", "VSS", "VCC", "GND",
}


def is_output_pin(pin_name: str) -> bool:
    return pin_name in COMMON_OUTPUT_NAMES


def remap_pin_name_for_cell(cell_type: str, pin_name: str) -> str:
    """
    Remap logical pin names to Verilog pin names for specific cell types.

    For Sky130 buffers, we sometimes prefer the output pin 'X' instead of 'Y'.
    Currently we leave names as-is except this special case.
    """
    ct_upper = cell_type.upper()
    if "BUF" in ct_upper and pin_name == "Y":
        return "X"
    return pin_name


NON_LOGIC_PREFIXES = (
    "sky130_fd_sc_hd__tap",
    "sky130_fd_sc_hd__decap",
    "sky130_fd_sc_hd__fill",
)

def is_non_logic_cell_type(cell_type: str) -> bool:
    """
    Returns True for non-logic physical cells like taps, decaps, fillers.
    These should be instantiated in the Verilog but NOT have ECO LO/HI
    tie-offs applied to them.
    """
    ct = (cell_type or "").lower()
    return any(ct.startswith(pref) for pref in NON_LOGIC_PREFIXES)


def infer_input_pins_from_design(
    design_instances: Dict[str, dict]
) -> Dict[str, List[str]]:
    """
    From the design's logical_db instances, infer which pin names are
    "logic inputs" per cell type (exclude outputs and power pins).

    Returns:
      { cell_type : [input_pin_names...] }
    """
    per_type: Dict[str, Set[str]] = {}

    for inst in design_instances.values():
        ctype = inst.get("type", "")
        pins = inst.get("pins", {})
        for pname in pins.keys():
            up = pname.upper()
            if pname in COMMON_OUTPUT_NAMES:
                continue
            if up in POWER_PINS:
                continue
            per_type.setdefault(ctype, set()).add(pname)

    return {ctype: sorted(pins) for ctype, pins in per_type.items()}


# -----------------------------
# Graph / spare detection
# -----------------------------

def find_spares_from_after_graph(
    instances: Dict[str, dict],
    graph_after: Dict[str, List[str]],
    exclude_insts: Set[str],
) -> Set[str]:
    """
    Spares are instances whose entry in the after-PD graph has an empty
    sink list:  inst -> [].

    We:
      - Look at graph_after keys (drivers).
      - If sinks list is empty and drv in instances and not in exclude_insts,
        we mark it as a spare.
    """
    spares: Set[str] = set()

    for drv, sinks in graph_after.items():
        if drv in exclude_insts:
            continue
        if drv in instances and (not sinks):
            spares.add(drv)

    return spares


# -----------------------------
# Net collection / naming
# -----------------------------

def collect_all_net_bits(
    instances: Dict[str, dict],
    ports: Dict[str, dict],
) -> Set[int]:
    """
    Gather all bit IDs used in:
      - instance pins
      - port bits

    Assumes bits are integers or strings convertible to int.
    """
    net_bits: Set[int] = set()

    # From instances
    for inst in instances.values():
        pins = inst.get("pins", {})
        for bits in pins.values():
            for b in bits:
                try:
                    net_bits.add(int(b))
                except Exception:
                    pass

    # From ports
    for pinfo in ports.values():
        for b in pinfo.get("bits", []):
            try:
                net_bits.add(int(b))
            except Exception:
                pass

    return net_bits


def net_name(bit) -> str:
    """Map a net bit ID to a Verilog wire name."""
    return f"n{bit}"


# -----------------------------
# ECO pin override logic
# -----------------------------

def pins_with_pd_overrides(
    inst_name: str,
    inst: dict,
    is_spare: bool,
    tie_low_bit: int,
    tie_high_bit: Optional[int],
    pattern: Dict[str, int],
) -> Dict[str, List[int]]:
    """
    Build the effective pins for an instance, applying power-down ECO:

      - if not a spare, keep original pins as-is.
      - if a spare, tie all NON-OUTPUT / NON-POWER pins according to
        the min-leak "pattern" mapping:
          pattern[pin] = 0 -> LO (tie_low_bit)
          pattern[pin] = 1 -> HI (tie_high_bit), but if HI not available
                              fall back to LO.

        Any input pin not present in pattern is default-tied to LO.
    """
    pins = inst.get("pins", {})
    effective_pins: Dict[str, List[int]] = {}

    for pin_name, bits in pins.items():
        # Normalize bits to int list
        norm_bits: List[int] = []
        for b in bits:
            try:
                norm_bits.append(int(b))
            except Exception:
                continue

        if not is_spare:
            # No ECO override for used logic: keep as-is
            effective_pins[pin_name] = norm_bits
            continue

        # For spares:
        up = pin_name.upper()
        if is_output_pin(pin_name) or up in POWER_PINS:
            # Outputs / power pins are not tied
            effective_pins[pin_name] = norm_bits
            continue

        # Logic inputs: apply min-leak pattern if available
        desired = pattern.get(pin_name)
        if desired is None:
            # No explicit pattern -> default to LO
            target_bit = tie_low_bit
        elif desired == 0 or tie_high_bit is None:
            target_bit = tie_low_bit
        else:
            target_bit = tie_high_bit

        if norm_bits:
            effective_pins[pin_name] = [target_bit] * len(norm_bits)
        else:
            # No bits listed; synthesize a single bit
            effective_pins[pin_name] = [target_bit]

    return effective_pins


# -----------------------------
# Verilog generation
# -----------------------------

def generate_verilog(
    design: str,
    all_instances: Dict[str, dict],
    graph_after: Dict[str, List[str]],
    ports: Dict[str, dict],
    min_leakage_table: Dict[str, Dict[str, Any]],
    tielo_inst: str,
    tie_low_bit: int,
    tiehi_inst: Optional[str],
    tie_high_bit: Optional[int],
) -> str:
    """
    Build the full Verilog source as a string.

    Module name: mod_<design>
    """

    # 1) Determine spares from AFTER-PD graph
    exclude = {tielo_inst}
    if tiehi_inst is not None:
        exclude.add(tiehi_inst)
    spares = find_spares_from_after_graph(all_instances, graph_after, exclude)

    # 2) Collect all nets
    net_bits = collect_all_net_bits(all_instances, ports)
    net_bits.add(int(tie_low_bit))
    if tie_high_bit is not None:
        net_bits.add(int(tie_high_bit))

    # 3) Start building Verilog
    lines: List[str] = []

    lines.append("// Auto-generated PD-ECO gate-level netlist")
    lines.append(f"// Design: {design}")
    lines.append("// Sources:")
    lines.append("//   data_structures.json (logical_db)")
    lines.append("//   <design>_mapped_netlist_graph_after_pd_eco.json")
    lines.append("//   <design>_logical_db.json (ports)")
    lines.append("//   <design>_pd_tielo_source.json (LO/HI nets)")
    lines.append("")
    lines.append(f"module mod_{design} (")

    # Top-level ports
    port_names = list(ports.keys())
    if port_names:
        for i, pname in enumerate(port_names):
            comma = "," if i != len(port_names) - 1 else ""
            lines.append(f"  {pname}{comma}")
    lines.append(");")
    lines.append("")

    # Port declarations
    lines.append("  // Port declarations")
    for pname in port_names:
        pinfo = ports[pname]
        direction = pinfo.get("direction", "input")
        bits = []
        for b in pinfo.get("bits", []):
            try:
                bits.append(int(b))
            except Exception:
                pass
        width = len(bits)

        if width <= 1:
            range_str = ""
        else:
            range_str = f"[{width - 1}:0] "

        dir_kw = direction.lower()
        if dir_kw not in ("input", "output", "inout"):
            dir_kw = "input"

        lines.append(f"  {dir_kw} {range_str}{pname};")
    lines.append("")

    # Internal nets
    if net_bits:
        lines.append("  // Internal nets")
        for b in sorted(net_bits):
            lines.append(f"  wire {net_name(b)};")
        lines.append("")

    # Port <-> net connections
    lines.append("  // Connect top-level ports to internal nets")
    for pname in port_names:
        pinfo = ports[pname]
        direction = pinfo.get("direction", "input").lower()

        bits = []
        for b in pinfo.get("bits", []):
            try:
                bits.append(int(b))
            except Exception:
                pass

        width = len(bits)
        if width == 1:
            b0 = bits[0]
            if direction == "input":
                lines.append(f"  assign {net_name(b0)} = {pname};")
            elif direction in ("output", "inout"):
                lines.append(f"  assign {pname} = {net_name(b0)};")
        else:
            for idx, b in enumerate(bits):
                if direction == "input":
                    lines.append(f"  assign {net_name(b)} = {pname}[{idx}];")
                elif direction in ("output", "inout"):
                    lines.append(f"  assign {pname}[{idx}] = {net_name(b)};")
    lines.append("")

    # Cell instantiations
    lines.append("  // Cell instances")
    for inst_name, inst in all_instances.items():
        ctype = inst.get("type", "UNKNOWN")

        # Non-logic cells (tap / decap / fill):
        #   - MUST be instantiated in the .v
        #   - MUST NOT be driven by conb_1 (no ECO LO/HI ties)
        if is_non_logic_cell_type(ctype):
            lines.append(f"  {ctype} {inst_name} ();")
            continue

        # Logic cells: apply spare detection + min-leakage ECO ties
        is_spare = inst_name in spares

        leak_info = min_leakage_table.get(ctype)
        pattern = leak_info.get("pattern", {}) if leak_info is not None else {}

        eff_pins = pins_with_pd_overrides(
            inst_name=inst_name,
            inst=inst,
            is_spare=is_spare,
            tie_low_bit=tie_low_bit,
            tie_high_bit=tie_high_bit,
            pattern=pattern,
        )

        inst_label = inst_name  # NO leading backslash; matches DEF / map

        conn_strs: List[str] = []
        for pin_name, bits in eff_pins.items():
            verilog_pin = remap_pin_name_for_cell(ctype, pin_name)

            if not bits:
                conn_strs.append(f".{verilog_pin}()")
                continue

            if len(bits) == 1:
                conn_strs.append(f".{verilog_pin}({net_name(bits[0])})")
            else:
                net_list = ", ".join(net_name(b) for b in bits)
                conn_strs.append(f".{verilog_pin}({{ {net_list} }})")

        conn_body = ", ".join(conn_strs)
        lines.append(f"  {ctype} {inst_label} ( {conn_body} );")

    lines.append("")
    lines.append("endmodule")
    lines.append("")

    return "\n".join(lines)


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate a PD-ECO gate-level Verilog netlist from "
            "data_structures.json, mapped_netlist_graph_after_pd_eco, "
            "logical_db (ports), PD tie info, Liberty .lib, and fabric DB."
        )
    )
    parser.add_argument(
        "--design",
        required=True,
        help="Design name (expects build/<design>/...)",
    )
    parser.add_argument(
        "--build-dir",
        default="build",
        help="Build directory root (default: build)",
    )
    parser.add_argument(
        "--lib",
        default="tech/sky130_fd_sc_hd__tt_025C_1v80.lib",
        help=(
            "Liberty .lib file used to compute min-leakage tie-offs "
            "for unused cells (default: tech/sky130_fd_sc_hd__tt_025C_1v80.lib)"
        ),
    )

    args = parser.parse_args()
    design = args.design
    build_dir = Path(args.build_dir)
    lib_path = Path(args.lib)

    base_dir = build_dir / design
    ds_path = base_dir / "data_structures.json"
    graph_after_path = base_dir / f"{design}_mapped_netlist_graph_after_pd_eco.json"
    logical_db_path = base_dir / f"{design}_logical_db.json"
    tie_info_path = base_dir / f"{design}_pd_tielo_source.json"
    out_verilog_path = base_dir / f"{design}_pd_eco_netlist.v"

    fabric_db_path = build_dir / "fabric" / "fabric_db.json"
    cts_map_path = base_dir / f"{design}_cts.map"

    # Sanity checks
    if not ds_path.exists():
        raise FileNotFoundError(f"data_structures.json not found: {ds_path}")
    if not graph_after_path.exists():
        raise FileNotFoundError(f"After-PD graph not found: {graph_after_path}")
    if not logical_db_path.exists():
        raise FileNotFoundError(f"logical_db.json not found: {logical_db_path}")
    if not tie_info_path.exists():
        print(f"[VERILOG] WARNING: PD tie info JSON not found: {tie_info_path}")
        print("           Will try to proceed, but LO/HI nets may be incomplete.")

    print(f"[VERILOG] Design: {design}")
    print(f"[VERILOG] data_structures: {ds_path}")
    print(f"[VERILOG] logical_db (for ports): {logical_db_path}")
    print(f"[VERILOG] after-PD graph: {graph_after_path}")
    print(f"[VERILOG] tie info JSON: {tie_info_path}")
    print(f"[VERILOG] Liberty .lib: {lib_path}")
    print(f"[VERILOG] output Verilog: {out_verilog_path}")

    # Load core JSONs
    ds_raw = load_json(ds_path)
    design_instances = extract_instances_from_data_structures(ds_raw)
    graph_after = load_json(graph_after_path)
    logical_raw = load_json(logical_db_path)
    ports = extract_ports_from_logical_db(logical_raw)

    print(f"[VERILOG] Design instances in logical_db: {len(design_instances)}")
    print(f"[VERILOG] Drivers in after-PD graph:       {len(graph_after)}")
    print(f"[VERILOG] #ports:                          {len(ports)}")

    # Load tie info
    tielo_inst: str = ""
    tie_low_bit: Optional[int] = None
    tiehi_inst: Optional[str] = None
    tie_high_bit: Optional[int] = None

    if tie_info_path.exists():
        tie_info = load_json(tie_info_path)
        tielo_inst = tie_info.get("tielo_inst", "")
        tie_low_bit = int(tie_info.get("tielo_net_bit"))
        tiehi_inst = tie_info.get("tiehi_inst")
        if "tiehi_net_bit" in tie_info:
            tie_high_bit = int(tie_info["tiehi_net_bit"])
        print(f"[VERILOG] Using tie-low net from inst '{tielo_inst}', bit {tie_low_bit}")
        if tiehi_inst is not None and tie_high_bit is not None:
            print(f"[VERILOG] Using tie-high net from inst '{tiehi_inst}', bit {tie_high_bit}")
        else:
            print("[VERILOG] No explicit HI (1) tie source in PD info; "
                  "min-leak '1' bits will be tied to LO.")
    else:
        raise FileNotFoundError(
            f"PD tie info file not found: {tie_info_path} "
            "(run eco_generator.py Phase 3 first)."
        )

    if tie_low_bit is None:
        raise RuntimeError("tie_low_bit is None; cannot proceed with PD ECO netlist.")

    # Min-leakage table from .lib
    min_leakage_table: Dict[str, Dict[str, Any]] = {}
    if lib_path.exists():
        print(f"[VERILOG] Loading Liberty file for min-leakage patterns...")
        try:
            min_leakage_table = build_min_leakage_table(lib_path)
            print(f"[VERILOG] Min-leak table covers {len(min_leakage_table)} cell types.")
        except Exception as e:
            print(f"[VERILOG] WARNING: failed to parse .lib for leakage info: {e}")
            min_leakage_table = {}
    else:
        print(f"[VERILOG] WARNING: Liberty file not found: {lib_path}; "
              "spares will be tied to LO only.")
        min_leakage_table = {}

    # Fabric-level unused cells -> create synthetic instances
    fabric_instances: Dict[str, dict] = {}
    if fabric_db_path.exists() and cts_map_path.exists():
        print(f"[VERILOG] Loading fabric DB from: {fabric_db_path}")
        fabric_cells = load_fabric_cells(fabric_db_path)
        placement_map = parse_map_file(cts_map_path)

        fabric_unused_cells = find_unused_fabric_cells(fabric_cells, placement_map)
        print(f"[VERILOG] Fabric cells with no mapped instance: {len(fabric_unused_cells)}")

        # infer input pins per cell type from design instances
        input_pin_template = infer_input_pins_from_design(design_instances)

        for cell_name, cell_info in fabric_unused_cells.items():
            ctype = cell_info.get("physical_cell_type", "UNKNOWN")

            # If the slot is already used by a design instance, skip
            if cell_name in design_instances:
                continue

            # Non-logic: instantiate later with empty pin list
            if is_non_logic_cell_type(ctype):
                fabric_instances[cell_name] = {
                    "type": ctype,
                    "pins": {},
                }
                continue

            # Logic cell in unused fabric: build a minimal pin map tied to LO/HI
            pin_names = input_pin_template.get(ctype)
            if not pin_names:
                # We don't know its pins; instantiate with empty pins
                fabric_instances[cell_name] = {
                    "type": ctype,
                    "pins": {},
                }
                continue

            leak_info = min_leakage_table.get(ctype)
            pattern = leak_info.get("pattern", {}) if leak_info is not None else {}

            pins: Dict[str, List[int]] = {}
            for pname in pin_names:
                desired = pattern.get(pname)
                if desired is None:
                    target = tie_low_bit
                elif desired == 0 or tie_high_bit is None:
                    target = tie_low_bit
                else:
                    target = tie_high_bit
                pins[pname] = [int(target)]

            fabric_instances[cell_name] = {
                "type": ctype,
                "pins": pins,
            }

    else:
        print("[VERILOG] Fabric DB or CTS map not found; "
              "skipping instantiation of fabric-only unused cells.")
        fabric_instances = {}

    # Merge design + fabric instances
    all_instances: Dict[str, dict] = dict(design_instances)
    for name, inst in fabric_instances.items():
        if name not in all_instances:
            all_instances[name] = inst

    # Generate Verilog
    verilog_src = generate_verilog(
        design=design,
        all_instances=all_instances,
        graph_after=graph_after,
        ports=ports,
        min_leakage_table=min_leakage_table,
        tielo_inst=tielo_inst,
        tie_low_bit=tie_low_bit,
        tiehi_inst=tiehi_inst,
        tie_high_bit=tie_high_bit,
    )

    write_text(out_verilog_path, verilog_src)
    print("[VERILOG] Done. Wrote gate-level netlist.")


if __name__ == "__main__":
    main()

# how to run:
#   python src/generate_verilog.py --design <design>