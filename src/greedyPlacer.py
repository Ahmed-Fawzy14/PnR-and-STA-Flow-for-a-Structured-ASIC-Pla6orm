#!/usr/bin/env python3
"""
Greedy placer using precomputed data_structures.json.

Pipeline:

1) Load data_structures.json (from dataStructuresGenerator.py).
2) Extract:
   - logical.instances          (list of inst_names in a deterministic order)
   - logical.cell_type          (inst -> physical cell type string)
   - fabric.slots_by_phys_type  (phys_type -> [slot_names...])
3) For each instance in order:
   - ctype = cell_type[inst]
   - bucket = slots_by_phys_type[ctype]
   - pop one slot and assign inst -> slot
4) Write a simple map file for OpenROAD:
     "<inst_name> <slot_name>\\n"
"""

import argparse
import json
import os
from collections import Counter
from typing import Any, Dict, List


# ---------------- IO ----------------

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir_for(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


# ---------------- Coverage summary ----------------

def summarize_type_coverage(
    instances: List[str],
    cell_type: Dict[str, str],
    slots_by_phys_type: Dict[str, List[str]],
) -> None:
    type_counts = Counter(cell_type[inst] for inst in instances)

    print("=== Type coverage summary ===")
    for ctype in sorted(type_counts.keys()):
        count_cells = type_counts[ctype]
        num_slots = len(slots_by_phys_type.get(ctype, []))
        print(f"  {ctype:40s} : {count_cells:5d} cells, {num_slots:5d} slots")
    print("=============================\n")


# ---------------- Greedy placement ----------------

def greedy_place(
    instances: List[str],
    cell_type: Dict[str, str],
    slots_by_phys_type: Dict[str, List[str]],
    strict: bool = True,
) -> Dict[str, str]:
    """
    Greedy placement:

    For each instance in 'instances' order:
      - ctype = cell_type[inst]
      - bucket = slots_by_phys_type[ctype]
      - pop(0) from bucket and assign that slot to inst.

    If no bucket or empty bucket:
      - strict=True  -> raise RuntimeError
      - strict=False -> print error and leave inst unplaced
    """
    placement: Dict[str, str] = {}

    missing_bucket_types = set()
    exhausted_bucket_types = set()

    for inst_name in instances:
        ctype = cell_type.get(inst_name)
        if not ctype:
            msg = f"[ERROR] Instance '{inst_name}' has no recorded cell_type."
            if strict:
                raise RuntimeError(msg)
            print(msg)
            continue

        bucket = slots_by_phys_type.get(ctype)
        if bucket is None:
            missing_bucket_types.add(ctype)
            msg = f"[ERROR] No fabric slots for cell type '{ctype}' (instance {inst_name})."
            if strict:
                raise RuntimeError(msg)
            print(msg)
            continue

        if not bucket:
            exhausted_bucket_types.add(ctype)
            msg = f"[ERROR] Fabric slots for cell type '{ctype}' exhausted (instance {inst_name})."
            if strict:
                raise RuntimeError(msg)
            print(msg)
            continue

        slot_name = bucket.pop(0)
        placement[inst_name] = slot_name

    if missing_bucket_types:
        print("\n[SUMMARY] Some cell types had no matching slots in the fabric:")
        for t in sorted(missing_bucket_types):
            print(f"  - {t}")
        if strict:
            print("[SUMMARY] Strict mode ON; run failed due to missing buckets.")

    if exhausted_bucket_types:
        print("\n[SUMMARY] Some cell types ran out of slots during placement:")
        for t in sorted(exhausted_bucket_types):
            print(f"  - {t}")
        if strict:
            print("[SUMMARY] Strict mode ON; run failed due to exhausted buckets.")

    return placement


# ---------------- Map file writer ----------------

def write_map_file(path: str, placement: Dict[str, str]) -> None:
    ensure_dir_for(path)
    with open(path, "w", encoding="utf-8") as f:
        for inst_name, slot_name in placement.items():
            f.write(f"{inst_name} {slot_name}\n")
    print(f"[INFO] Wrote placement map to '{path}' ({len(placement)} instances).")


# ---------------- CLI / main ----------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Greedy placer using data_structures.json.")
    p.add_argument("--ds-json", required=True, help="Path to data_structures.json.")
    p.add_argument("--out-map", required=True, help="Where to write the instance->slot map.")
    p.add_argument(
        "--no-strict",
        action="store_true",
        help="Do NOT abort on missing/exhausted slots; just warn and skip.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print(f"[INFO] Loading data structures from '{args.ds_json}'...")
    ds = load_json(args.ds_json)

    logical = ds["logical"]
    fabric = ds["fabric"]

    instances: List[str] = logical["instances"]
    cell_type: Dict[str, str] = logical["cell_type"]
    slots_by_phys_type: Dict[str, List[str]] = fabric["slots_by_phys_type"]

    summarize_type_coverage(instances, cell_type, slots_by_phys_type)

    print("[INFO] Running greedy placement...")
    placement = greedy_place(
        instances=instances,
        cell_type=cell_type,
        slots_by_phys_type=slots_by_phys_type,
        strict=not args.no_strict,
    )

    print("[INFO] Writing map file...")
    write_map_file(args.out_map, placement)


if __name__ == "__main__":
    main()
