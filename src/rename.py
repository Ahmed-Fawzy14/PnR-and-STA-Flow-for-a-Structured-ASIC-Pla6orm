#!/usr/bin/env python3
# rename.py
"""
rename.py

Rename instances in a gate-level Verilog netlist so that each instance name
matches its assigned physical slot from a placement .map file.

Default naming convention (per design):

  Map file:   build/<design>/<design>_sa.map
  Input .v:   build/<design>/<design>_pd_eco_netlist.v
  Output .v:  build/<design>/<design>_renamed.v

Only instance names are changed. Module names, net names, ports, etc. are left
untouched.

Typical usage:

    python3 rename.py --design 6502

(Optional advanced usage: you can override the inferred paths with
--map / --in-verilog / --out-verilog if needed.)
"""

import argparse
import os
import re
import sys
from typing import Dict, Set, Tuple, List

# A small set of Verilog keywords so we don't treat them as cell types.
VERILOG_KEYWORDS: Set[str] = {
    "module", "endmodule",
    "input", "output", "inout",
    "wire", "tri", "tri0", "tri1", "wand", "wor",
    "reg", "logic",
    "assign",
    "parameter", "localparam",
    "generate", "endgenerate",
    "if", "else", "for", "case", "endcase",
    "always", "initial",
    "function", "endfunction",
    "task", "endtask",
}


def load_map(map_path: str) -> Dict[str, str]:
    """
    Load a <inst> <slot> map file into a dictionary: inst_name -> slot_name.
    Ignores blank lines and lines starting with '#'.
    """
    mapping: Dict[str, str] = {}
    with open(map_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(
                    f"Bad line in map file {map_path!r} at line {lineno}: {line!r}"
                )
            inst, slot = parts
            if inst in mapping and mapping[inst] != slot:
                raise ValueError(
                    f"Instance {inst!r} appears multiple times in map with "
                    f"different slots: {mapping[inst]!r} vs {slot!r}"
                )
            mapping[inst] = slot
    if not mapping:
        raise ValueError(f"Map file {map_path!r} is empty or contains no mappings.")
    return mapping


def ensure_dir_for(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def rename_instances_in_verilog(
    verilog_lines: List[str],
    renames: Dict[str, str],
) -> Tuple[List[str], int, Set[str], Set[str]]:
    """
    Process Verilog lines and rename instance names according to 'renames'.

    Returns:
        (new_lines, num_renamed, insts_seen, insts_unmapped)

    - new_lines: modified Verilog lines
    - num_renamed: how many instances were actually renamed
    - insts_seen: set of instance names we recognized in instantiation positions
    - insts_unmapped: subset of insts_seen that did not appear in 'renames'
    """
    new_lines: List[str] = []

    # Regex to match a simple gate-level instantiation:
    #
    #   <cell_type> <inst_name> (
    #   <cell_type> <inst_name> #(...params...) (
    #
    # Captures:
    #   1: leading whitespace
    #   2: cell type
    #   3: instance name
    #   4: the part up to and including '(' or '#(' (kept as-is)
    #
    inst_pattern = re.compile(
        r'^(\s*)'                         # 1: leading spaces
        r'([A-Za-z_][A-Za-z0-9_$]*)'      # 2: cell type
        r'\s+'                            #    space(s)
        r'([A-Za-z_][A-Za-z0-9_$]*)'      # 3: instance name
        r'(\s*(?:#\s*\(|\())'             # 4: " (" or " # ("
    )

    num_renamed = 0
    insts_seen: Set[str] = set()
    insts_unmapped: Set[str] = set()

    for line in verilog_lines:
        stripped = line.lstrip()
        # Skip comments and preprocessor lines
        if stripped.startswith("//") or stripped.startswith("`"):
            new_lines.append(line)
            continue

        m = inst_pattern.match(line)
        if not m:
            new_lines.append(line)
            continue

        indent, cell_type, inst_name, after = m.groups()

        # Don't treat Verilog keywords as cell types (e.g., "module top (... )").
        if cell_type in VERILOG_KEYWORDS:
            new_lines.append(line)
            continue

        # We recognized this as an instantiation
        insts_seen.add(inst_name)

        new_name = renames.get(inst_name)
        if not new_name or new_name == inst_name:
            # No mapping -> keep original name but record it's unmapped
            insts_unmapped.add(inst_name)
            new_lines.append(line)
            continue

        # Rebuild the line with the new instance name
        rest = line[m.end(4):]  # everything after the '(' or "#("
        new_line = f"{indent}{cell_type} {new_name}{after}{rest}"
        new_lines.append(new_line)
        num_renamed += 1

    return new_lines, num_renamed, insts_seen, insts_unmapped


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Rename Verilog instance names according to a placement .map file.\n"
            "By default, paths are derived from --design:\n"
            "  build/<design>/<design>sa.map\n"
            "  build/<design>/<design>_pd_eco_netlist.v\n"
            "  build/<design>/<design>_renamed.v"
        )
    )
    p.add_argument(
        "--design",
        required=True,
        help="Design name (used to derive default paths under build/<design>/).",
    )
    # Optional overrides (in case you want custom filenames)
    p.add_argument(
        "--map",
        help="Override: explicit path to <inst> <slot> placement map file.",
    )
    p.add_argument(
        "--in-verilog",
        help="Override: explicit path to input gate-level Verilog netlist (.v).",
    )
    p.add_argument(
        "--out-verilog",
        help="Override: explicit path to output renamed Verilog netlist (.v).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    design = args.design

    # Derive defaults if not overridden
    map_path = args.map or os.path.join("build", design, f"{design}_sa.map")
    in_v_path = args.in_verilog or os.path.join("build", design, f"{design}_pd_eco_netlist.v")
    out_v_path = args.out_verilog or os.path.join("build", design, f"{design}_renamed.v")

    print(f"[INFO] Design          : {design}")
    print(f"[INFO] Using map       : {map_path}")
    print(f"[INFO] Using input .v  : {in_v_path}")
    print(f"[INFO] Using output .v : {out_v_path}")

    if not os.path.exists(map_path):
        print(f"[ERROR] Map file not found: {map_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(in_v_path):
        print(f"[ERROR] Input Verilog not found: {in_v_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Loading map...")
    renames = load_map(map_path)
    print(f"[INFO] Map entries loaded: {len(renames)}")

    print(f"[INFO] Reading Verilog...")
    with open(in_v_path, "r", encoding="utf-8") as f:
        verilog_lines = f.readlines()

    new_lines, num_renamed, insts_seen, insts_unmapped = rename_instances_in_verilog(
        verilog_lines,
        renames,
    )

    # Stats
    print(f"[INFO] Instances recognized in Verilog (instantiation sites): {len(insts_seen)}")
    print(f"[INFO] Instances renamed: {num_renamed}")

    # Map entries that never appeared in the Verilog
    unused_map_keys = set(renames.keys()) - insts_seen
    if unused_map_keys:
        print(f"[WARN] {len(unused_map_keys)} instances appear in the map, "
              f"but were not found in the Verilog.")
        for name in sorted(list(unused_map_keys))[:10]:
            print(f"       - {name}")
        if len(unused_map_keys) > 10:
            print("       ... (truncated)")

    # Instances we saw in the Verilog but that had no mapping
    if insts_unmapped:
        print(f"[WARN] {len(insts_unmapped)} instances were seen in the Verilog "
              f"but have no entry in the map (kept original names).")
        for name in sorted(list(insts_unmapped))[:10]:
            print(f"       - {name}")
        if len(insts_unmapped) > 10:
            print("       ... (truncated)")

    print(f"[INFO] Writing renamed Verilog to '{out_v_path}'...")
    ensure_dir_for(out_v_path)
    with open(out_v_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print("[INFO] Done.")


if __name__ == "__main__":
    main()