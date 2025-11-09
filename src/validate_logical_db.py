#!/usr/bin/env python3
# src/validate_logical_db.py
#
# Validate one or more logical_db.json files.
# - JSON Schema validation (docs/logical_db.schema.json)
# - Semantic checks: type_counts, indexes, net_graph consistency, etc.
#
# Usage examples:
#   python3 src/validate_logical_db.py --db build/6502/6502_logical_db.json
#   python3 src/validate_logical_db.py --design 6502 aes_128 arith z80
#   python3 src/validate_logical_db.py            # auto-discover all under build/**
#   python3 src/validate_logical_db.py --strict   # treat warnings as errors

import argparse
import glob
import json
import os
import sys
from typing import Dict, Any, List, Tuple, Set

try:
    from jsonschema import Draft7Validator
except Exception as e:
    print("ERROR: jsonschema package is required. Install with: pip install jsonschema", file=sys.stderr)
    sys.exit(2)


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_schema(schema_path: str) -> Draft7Validator:
    schema = load_json(schema_path)
    return Draft7Validator(schema)


def infer_db_path_from_design(design: str) -> str:
    return os.path.join("build", design, f"{design}_logical_db.json")


def discover_all_dbs() -> List[str]:
    return sorted(glob.glob(os.path.join("build", "*", "*_logical_db.json")))


def validate_schema(db: Dict[str, Any], schema_validator: Draft7Validator) -> List[str]:
    errors = []
    for err in sorted(schema_validator.iter_errors(db), key=lambda e: e.path):
        loc = "/".join([str(x) for x in err.path])
        errors.append(f"schema: {loc or '<root>'}: {err.message}")
    return errors


def hist_types_from_instances(db: Dict[str, Any]) -> Dict[str, int]:
    h: Dict[str, int] = {}
    for inst in db.get("instances", {}).values():
        t = inst.get("type", "")
        h[t] = h.get(t, 0) + 1
    return h


def collect_referenced_bits(db: Dict[str, Any]) -> Set[int]:
    bits: Set[int] = set()
    for p in db.get("ports", {}).values():
        bits.update(p.get("bits", []))
    for inst in db.get("instances", {}).values():
        for blist in inst.get("pins", {}).values():
            bits.update(blist)
    return bits


def check_semantics(db: Dict[str, Any], strict: bool = False) -> Tuple[List[str], List[str]]:
    """
    Returns (errors, warnings).
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1) type_counts matches histogram
    hist = hist_types_from_instances(db)
    tcounts = db.get("type_counts", {})
    if hist != tcounts:
        errors.append(f"type_counts mismatch: actual={hist} schema={tcounts}")

    # 2) ports[*].width == len(bits), and indexes.inputs/outputs are correct
    ports = db.get("ports", {})
    inputs_expected, outputs_expected = [], []
    for pname, p in ports.items():
        bits = p.get("bits", [])
        width = p.get("width", None)
        if width is not None and width != len(bits):
            errors.append(f"port '{pname}': width={width} != len(bits)={len(bits)}")
        d = p.get("direction", "")
        if d == "input":
            inputs_expected.append(pname)
        elif d == "output":
            outputs_expected.append(pname)
    inputs_idx = db.get("indexes", {}).get("inputs", [])
    outputs_idx = db.get("indexes", {}).get("outputs", [])
    if sorted(inputs_expected) != sorted(inputs_idx):
        errors.append(f"indexes.inputs mismatch: expected={sorted(inputs_expected)} got={sorted(inputs_idx)}")
    if sorted(outputs_expected) != sorted(outputs_idx):
        errors.append(f"indexes.outputs mismatch: expected={sorted(outputs_expected)} got={sorted(outputs_idx)}")

    # 3) indexes.by_type covers instances accurately
    by_type = db.get("indexes", {}).get("by_type", {})
    # flatten by_type -> set(insts)
    insts_by_type_flat: Set[str] = set()
    for t, lst in by_type.items():
        for inst in lst:
            insts_by_type_flat.add(inst)
    # actual instances
    all_inst_names = set(db.get("instances", {}).keys())
    # Check per-type contents
    recomputed_by_type: Dict[str, List[str]] = {}
    for inst_name, inst in db.get("instances", {}).items():
        recomputed_by_type.setdefault(inst.get("type", ""), []).append(inst_name)
    # sort values for deterministic compare
    recomputed_by_type = {t: sorted(v) for t, v in recomputed_by_type.items()}
    by_type_sorted = {t: sorted(v) for t, v in by_type.items()}
    if recomputed_by_type != by_type_sorted:
        errors.append(f"indexes.by_type mismatch.")

    # 4) buses members must exist in ports
    buses = db.get("buses", {})
    for bname, binfo in buses.items():
        for member in binfo.get("members", []):
            if member not in ports:
                errors.append(f"bus '{bname}' member '{member}' not present in ports")

    # 5) All referenced bits appear in net_graph
    net_graph = db.get("net_graph", {})
    referenced_bits = collect_referenced_bits(db)
    missing_nodes = [b for b in sorted(referenced_bits) if str(b) not in net_graph]
    if missing_nodes:
        errors.append(f"net_graph missing nodes for bits: {missing_nodes[:20]}{'...' if len(missing_nodes)>20 else ''}")

    # 6) Drivers/sinks in net_graph must reference valid instances/pins (or '$const')
    for bkey, node in net_graph.items():
        for role, entries in (("driver", node.get("drivers", [])), ("sink", node.get("sinks", []))):
            for inst, pin in entries:
                if inst == "$const":
                    continue
                if inst not in db.get("instances", {}):
                    errors.append(f"net_graph bit {bkey}: {role} references unknown instance '{inst}'")
                    continue
                inst_pins = db["instances"][inst].get("pins", {})
                if pin not in inst_pins:
                    errors.append(f"net_graph bit {bkey}: {role} '{inst}.{pin}' not found in instance pins")

    # 7) Multi-driver bits: warning by default, error in --strict
    multi = [b for (b, node) in net_graph.items() if len(node.get("drivers", [])) > 1]
    recorded_multi = db.get("stats", {}).get("num_multidriver_bits", 0)
    if len(multi) != recorded_multi:
        warnings.append(f"stats.num_multidriver_bits={recorded_multi} but computed={len(multi)}")
    if multi:
        msg = f"multi-driver nets detected on bits: {multi[:20]}{'...' if len(multi)>20 else ''}"
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    return errors, warnings


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate logical_db.json files against schema and semantic rules.")
    ap.add_argument("--db", nargs="*", help="Path(s) to logical_db.json file(s).")
    ap.add_argument("--design", nargs="*", help="Design name(s) to resolve as build/<design>/<design>_logical_db.json")
    ap.add_argument("--schema", default=os.path.join("docs", "logical_db.schema.json"),
                    help="Path to JSON Schema (default: docs/logical_db.schema.json)")
    ap.add_argument("--strict", action="store_true", help="Treat warnings (e.g., multi-driver) as errors.")
    args = ap.parse_args()

    db_paths: List[str] = []
    if args.db:
        db_paths.extend(args.db)
    if args.design:
        db_paths.extend([infer_db_path_from_design(d) for d in args.design])
    if not db_paths:
        db_paths = discover_all_dbs()

    if not db_paths:
        print("No logical_db.json files found. Provide --db paths or --design names, or build/*/*_logical_db.json.", file=sys.stderr)
        sys.exit(2)

    schema_validator = load_schema(args.schema)

    any_errors = 0
    any_warnings = 0

    for path in db_paths:
        print(f"\n→ Validating {path}")
        try:
            db = load_json(path)
        except Exception as e:
            print(f"ERROR: cannot open {path}: {e}", file=sys.stderr)
            any_errors += 1
            continue

        schema_errs = validate_schema(db, schema_validator)
        sem_errs, sem_warns = ([], [])

        if schema_errs:
            print("✖ Schema validation failed:")
            for m in schema_errs:
                print(f"   - {m}")
            any_errors += 1
            # If schema fails, semantic checks may cascade; still try:
        else:
            print("✓ Schema: OK")

        try:
            sem_errs, sem_warns = check_semantics(db, strict=args.strict)
        except Exception as e:
            print(f"✖ Semantic checks crashed: {e}", file=sys.stderr)
            any_errors += 1
            continue

        if sem_errs:
            print("✖ Semantic errors:")
            for m in sem_errs:
                print(f"   - {m}")
            any_errors += 1
        else:
            print("✓ Semantics: OK")

        if sem_warns:
            print("⚠ Warnings:")
            for m in sem_warns:
                print(f"   - {m}")
            any_warnings += len(sem_warns)

    if any_errors:
        print(f"\nRESULT: ✖ FAILED  (errors: {any_errors}, warnings: {any_warnings})")
        sys.exit(1)
    else:
        status = "OK"
        if args.strict and any_warnings:
            status = "OK (warnings treated as errors would fail)"
        print(f"\nRESULT: ✓ PASSED  (warnings: {any_warnings})")
        sys.exit(0)


if __name__ == "__main__":
    main()
