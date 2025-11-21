#!/usr/bin/env python3
"""
Simulated Annealing Placer

Pipeline / assumptions:
- dataStructuresGenerator.py has already run and produced:
    build/<design>/data_structures.json
- greedyPlacer.py has already run and produced:
    build/<design>/<design>.map

This script:
1) Loads data_structures.json:
   - logical.instances           (inst_name -> { "type": ..., "pins": {...}, ... })
   - fabric.slot_info            (slot_name -> { "x", "y", "tile", "physical_cell_type", ... })
   - fabric.slots_by_phys_type   (phys_type -> [slot_name, ...])

2) Loads the initial greedy map:
   - "<inst_name> <slot_name>" per line.

3) Builds a netlist view from logical.instances only:
   - net_to_insts: for each bit ID, which instances touch it?
     (We do NOT depend on logical_db["net_graph"]; pins are enough.)

4) Defines a cost function:
   - Total Half-Perimeter Wirelength (HPWL) over all nets (bits):
       HPWL(net) = (max_x - min_x) + (max_y - min_y)
     using the (x, y) of the slot assigned to each instance.

5) Runs simulated annealing with the schedule/knobs from the slides:

   Annealing Schedule:
     - T_initial: initial temperature
     - Cooling Rate (alpha): T_{k+1} = alpha * T_k
     - Moves per Temp (N): number of move attempts per temperature step

   Hybrid Move Set:
     - P_refine vs P_explore: probability of choosing a "Refine" swap
       vs a windowed "Explore" move. We use:
           P_refine = argument
           P_explore = 1 - P_refine

   Exploration Window:
     - W_initial: starting window size as a fraction of die width/height
       for explore moves (e.g. 0.5 => 50% of die width/height).
     - Window Cooling Rate (beta): window size shrinks each temperature step:
           W_k = W_initial * beta^k

   Move types:
     (a) Refine = swap two instances of the same physical type
     (b) Explore = move one instance of a type to a FREE slot of that
         same type, constrained to a shrinking window around the
         instance’s current (x, y). If no free slot exists in the
         window, we fall back to any free slot of that type.

   - Accept moves with standard SA rule:
       - accept if better (Δ <= 0)
       - accept if worse with probability exp(-Δ / T)

6) Writes the best placement found to out_map, with the same
   "<inst_name> <slot_name>" format as the greedy placer.

Usage example:

    python3 simulated_annealing.py \
        --data-structures build/6502/data_structures.json \
        --initial-map build/6502/6502.map \
        --out-map build/6502/6502_sa.map \
        --num-temp-steps 60 \
        --moves-per-temp 1000 \
        --T-initial 200.0 \
        --alpha 0.95 \
        --P-refine 0.7 \
        --W-initial 0.5 \
        --beta 0.95 \
        --seed 42
"""

import argparse
import json
import math
import os
import random
from typing import Any, Dict, List, Set, Tuple


# ---------------- IO helpers ----------------

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir_for(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def load_map(path: str) -> Dict[str, str]:
    """
    Load a map file of the form:

        <inst_name> <slot_name>

    per line, ignoring blank lines and comment lines.
    """
    mapping: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"Bad map line in {path!r}: {line!r}")
            inst, slot = parts
            mapping[inst] = slot
    return mapping


def write_map(path: str, placement: Dict[str, str]) -> None:
    """
    Write "<inst_name> <slot_name>" one per line.
    """
    ensure_dir_for(path)
    with open(path, "w", encoding="utf-8") as f:
        for inst_name, slot_name in placement.items():
            f.write(f"{inst_name} {slot_name}\n")
    print(f"[INFO] Wrote placement map to '{path}' ({len(placement)} instances).")


# ---------------- Basic geometry ----------------

def compute_die_bbox(slot_info: Dict[str, Dict[str, Any]]) -> Tuple[float, float, float, float]:
    """
    Compute the die bounding box from all slots:

      returns (min_x, max_x, min_y, max_y)

    Raises if slot_info is empty or lacks coordinates.
    """
    xs: List[float] = []
    ys: List[float] = []

    for sinfo in slot_info.values():
        x = sinfo.get("x")
        y = sinfo.get("y")
        if x is None or y is None:
            continue
        xs.append(float(x))
        ys.append(float(y))

    if not xs or not ys:
        raise ValueError("slot_info has no valid x/y coordinates; cannot compute die bbox.")

    return min(xs), max(xs), min(ys), max(ys)


# ---------------- Data structure builders ----------------

def build_net_to_insts(instances: Dict[str, Any]) -> Dict[int, Set[str]]:
    """
    Build net_to_insts from logical.instances only, using pin bit IDs.

    Each pin is an array of integers (bit IDs). Any pins that share the
    same bit ID are considered connected on the same net (that bit).

    Returns:
        net_to_insts: bit_id (int) -> set of instance names that touch that bit.
    """
    from collections import defaultdict

    net_to_insts: Dict[int, Set[str]] = defaultdict(set)

    for inst_name, cell in instances.items():
        pins = cell.get("pins", {})
        for _pin_name, bit_list in pins.items():
            if not isinstance(bit_list, list):
                continue
            for bit in bit_list:
                # bit is an integer per schema
                net_to_insts[bit].add(inst_name)

    return net_to_insts


def build_type_index(instances: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Build:
        inst_type: inst_name -> physical cell type string (e.g. "sky130_fd_sc_hd__nand2_2")
        type_to_insts: ctype -> [inst_name, inst_name, ...]
    """
    from collections import defaultdict

    inst_type: Dict[str, str] = {}
    type_to_insts: Dict[str, List[str]] = defaultdict(list)

    for inst_name, cell in instances.items():
        ctype = cell.get("type")
        if not ctype:
            raise ValueError(f"Instance {inst_name!r} has no 'type' field.")
        inst_type[inst_name] = ctype
        type_to_insts[ctype].append(inst_name)

    return inst_type, type_to_insts


def build_free_slots(
    slots_by_phys_type: Dict[str, List[str]],
    placement: Dict[str, str],
    inst_type: Dict[str, str],
) -> Dict[str, List[str]]:
    """
    Build free slot lists per physical type by starting from all slots and
    removing those used in the current placement.

    Returns:
        free_slots_by_type: phys_type -> [slot_name, ...]
    """
    from collections import defaultdict

    used_slots_by_type: Dict[str, Set[str]] = defaultdict(set)
    for inst_name, slot_name in placement.items():
        ctype = inst_type.get(inst_name)
        if ctype is None:
            # If an instance in the map isn't in logical.instances, we simply skip it.
            continue
        used_slots_by_type[ctype].add(slot_name)

    free_slots_by_type: Dict[str, List[str]] = {}

    for ctype, all_slots in slots_by_phys_type.items():
        used = used_slots_by_type.get(ctype, set())
        free = [s for s in all_slots if s not in used]
        free_slots_by_type[ctype] = free

    return free_slots_by_type


# ---------------- HPWL cost computation ----------------

def compute_total_hpwl(
    net_to_insts: Dict[int, Set[str]],
    slot_info: Dict[str, Dict[str, Any]],
    placement: Dict[str, str],
) -> float:
    """
    Compute total half-perimeter wirelength (HPWL), summing over all nets.

    For each net (bit): consider all instances that touch that net and have
    a defined placement. Take their (x, y) from slot_info and compute:

        HPWL_net = (max_x - min_x) + (max_y - min_y)

    Nets with 0 or 1 placed instances contribute 0.

    Returns:
        total HPWL (float)
    """
    total_hpwl = 0.0

    for _bit_id, insts in net_to_insts.items():
        xs: List[float] = []
        ys: List[float] = []

        for inst in insts:
            slot = placement.get(inst)
            if slot is None:
                continue
            sinfo = slot_info.get(slot)
            if not sinfo:
                continue

            x = sinfo.get("x")
            y = sinfo.get("y")
            if x is None or y is None:
                continue

            xs.append(float(x))
            ys.append(float(y))

        if len(xs) >= 2:
            hpwl = (max(xs) - min(xs)) + (max(ys) - min(ys))
            total_hpwl += hpwl

    return total_hpwl


# ---------------- SA move generation ----------------

def choose_type_with_insts(
    type_to_insts: Dict[str, List[str]],
    slots_by_phys_type: Dict[str, List[str]],
    free_slots_by_type: Dict[str, List[str]],
    require_two_insts: bool = False,
    require_free_slot: bool = False,
) -> str:
    """
    Choose a physical type that satisfies constraints:
      - exists in type_to_insts (has logical instances)
      - has slots in slots_by_phys_type
      - if require_two_insts: len(type_to_insts[ctype]) >= 2
      - if require_free_slot: free_slots_by_type[ctype] is non-empty

    Returns:
      chosen type string, or raises RuntimeError if none exist.
    """
    candidates: List[str] = []

    for ctype, insts in type_to_insts.items():
        if ctype not in slots_by_phys_type:
            continue
        if require_two_insts and len(insts) < 2:
            continue
        if require_free_slot and not free_slots_by_type.get(ctype):
            continue
        candidates.append(ctype)

    if not candidates:
        raise RuntimeError("No cell type satisfies the requested constraints for SA moves.")

    return random.choice(candidates)


def propose_swap_move(
    placement: Dict[str, str],
    inst_type: Dict[str, str],
    type_to_insts: Dict[str, List[str]],
    slots_by_phys_type: Dict[str, List[str]],
    free_slots_by_type: Dict[str, List[str]],
) -> Tuple[str, Tuple[str, str, str, str]]:
    """
    Refine move: swap between two instances of the same type.

    Returns:
        ("swap", (inst1, slot1, inst2, slot2))
    """
    # Pick a type with at least two instances and at least one slot.
    ctype = choose_type_with_insts(
        type_to_insts,
        slots_by_phys_type,
        free_slots_by_type,
        require_two_insts=True,
        require_free_slot=False,
    )

    insts = type_to_insts[ctype]
    inst1, inst2 = random.sample(insts, 2)
    slot1 = placement[inst1]
    slot2 = placement[inst2]

    # Apply swap
    placement[inst1], placement[inst2] = slot2, slot1

    move_data = (inst1, slot1, inst2, slot2)
    return "swap", move_data


def revert_swap_move(
    placement: Dict[str, str],
    move_data: Tuple[str, str, str, str],
) -> None:
    """
    Undo a swap move.
    move_data = (inst1, old_slot1, inst2, old_slot2)
    """
    inst1, old_slot1, inst2, old_slot2 = move_data
    placement[inst1] = old_slot1
    placement[inst2] = old_slot2


def propose_move_to_free_slot(
    placement: Dict[str, str],
    inst_type: Dict[str, str],
    type_to_insts: Dict[str, List[str]],
    slots_by_phys_type: Dict[str, List[str]],
    free_slots_by_type: Dict[str, List[str]],
    slot_info: Dict[str, Dict[str, Any]],
    W: float,
    die_bbox: Tuple[float, float, float, float],
) -> Tuple[str, Tuple[str, str, str, str]]:
    """
    Explore move: move a single instance of some type to a free slot
    of that same type, limited by a window of size W relative to the
    die dimensions.

    W is interpreted as a fraction of die width/height:
      - die_width  = max_x - min_x
      - die_height = max_y - min_y
      - allowed box around current (x,y):
            |x_new - x_cur| <= 0.5 * W * die_width
            |y_new - y_cur| <= 0.5 * W * die_height

    If no free slot exists in that window, we fall back to any free slot
    of that type.

    Returns:
        ("move_free", (inst, old_slot, new_slot, ctype))
    """
    min_x, max_x, min_y, max_y = die_bbox
    die_width = max_x - min_x
    die_height = max_y - min_y

    # Pick a type that has at least one instance AND at least one free slot.
    ctype = choose_type_with_insts(
        type_to_insts,
        slots_by_phys_type,
        free_slots_by_type,
        require_two_insts=False,
        require_free_slot=True,
    )

    insts = type_to_insts[ctype]
    inst = random.choice(insts)

    old_slot = placement[inst]
    free_slots = free_slots_by_type[ctype]

    # Default candidate set
    candidate_slots = free_slots

    if W > 0.0 and die_width > 0.0 and die_height > 0.0:
        sinfo_cur = slot_info.get(old_slot)
        if sinfo_cur is not None and sinfo_cur.get("x") is not None and sinfo_cur.get("y") is not None:
            cx = float(sinfo_cur["x"])
            cy = float(sinfo_cur["y"])
            half_dx = 0.5 * W * die_width
            half_dy = 0.5 * W * die_height

            window_candidates: List[str] = []
            for s in free_slots:
                sinfo_new = slot_info.get(s)
                if sinfo_new is None:
                    continue
                x_new = sinfo_new.get("x")
                y_new = sinfo_new.get("y")
                if x_new is None or y_new is None:
                    continue
                x_new = float(x_new)
                y_new = float(y_new)
                if abs(x_new - cx) <= half_dx and abs(y_new - cy) <= half_dy:
                    window_candidates.append(s)

            if window_candidates:
                candidate_slots = window_candidates

    # Pick a free slot randomly from candidate set
    new_slot = random.choice(candidate_slots)

    # Apply move: update placement and free slots
    placement[inst] = new_slot
    # new_slot no longer free; old_slot becomes free
    free_slots.remove(new_slot)
    free_slots.append(old_slot)

    move_data = (inst, old_slot, new_slot, ctype)
    return "move_free", move_data


def revert_move_to_free_slot(
    placement: Dict[str, str],
    free_slots_by_type: Dict[str, List[str]],
    move_data: Tuple[str, str, str, str],
) -> None:
    """
    Undo a move-to-free-slot move.
    move_data = (inst, old_slot, new_slot, ctype)
    """
    inst, old_slot, new_slot, ctype = move_data

    # Restore placement
    placement[inst] = old_slot

    # Update free slots
    free_slots = free_slots_by_type[ctype]
    # Remove old_slot (it was added as free in propose; now it's used again)
    if old_slot in free_slots:
        free_slots.remove(old_slot)
    # new_slot becomes free again
    if new_slot not in free_slots:
        free_slots.append(new_slot)


# ---------------- SA main loop ----------------

def simulated_annealing(
    instances: Dict[str, Any],
    slot_info: Dict[str, Dict[str, Any]],
    slots_by_phys_type: Dict[str, List[str]],
    initial_placement: Dict[str, str],
    num_temp_steps: int,
    T_initial: float,
    alpha: float,
    moves_per_temp: int,
    P_refine: float,
    W_initial: float,
    beta: float,
    report_interval: int = 1000,
) -> Tuple[Dict[str, str], float]:
    """
    Run simulated annealing to optimize HPWL with the lecture knobs:

      - T_initial
      - Cooling Rate alpha (T_{k+1} = alpha * T_k)
      - Moves per Temp N (moves_per_temp)
      - P_refine vs P_explore = 1 - P_refine
      - W_initial (fraction of die size)
      - Window Cooling Rate beta (W_k = W_initial * beta^k)

    Arguments:
        instances          : logical.instances
        slot_info          : fabric.slot_info
        slots_by_phys_type : fabric.slots_by_phys_type
        initial_placement  : inst_name -> slot_name from greedy
        num_temp_steps     : number of temperature steps
        T_initial          : initial temperature
        alpha              : temperature cooling rate
        moves_per_temp     : N moves per temperature step
        P_refine           : probability of refine (swap) move
                             P_explore = 1 - P_refine
        W_initial          : initial window size fraction
        beta               : window cooling rate
        report_interval    : print progress every ~report_interval moves

    Returns:
        (best_placement, best_cost)
    """
    if num_temp_steps <= 0 or moves_per_temp <= 0:
        raise ValueError("num_temp_steps and moves_per_temp must be positive integers.")
    if T_initial <= 0.0:
        raise ValueError("T_initial must be positive.")
    if not (0.0 < alpha <= 1.0):
        raise ValueError("alpha must be in (0, 1].")
    if not (0.0 <= P_refine <= 1.0):
        raise ValueError("P_refine must be in [0, 1].")
    if not (0.0 <= W_initial <= 1.0):
        raise ValueError("W_initial must be in [0, 1] (fraction of die size).")
    if not (0.0 < beta <= 1.0):
        raise ValueError("beta must be in (0, 1].")

    total_moves = num_temp_steps * moves_per_temp

    print("[INFO] Building net_to_insts...")
    net_to_insts = build_net_to_insts(instances)

    print("[INFO] Building type index...")
    inst_type, type_to_insts = build_type_index(instances)

    print("[INFO] Building free slot lists...")
    free_slots_by_type = build_free_slots(slots_by_phys_type, initial_placement, inst_type)

    print("[INFO] Computing die bounding box for exploration window...")
    die_bbox = compute_die_bbox(slot_info)
    min_x, max_x, min_y, max_y = die_bbox
    print(f"[INFO] Die bbox: x=[{min_x:.3f}, {max_x:.3f}], y=[{min_y:.3f}, {max_y:.3f}]")

    # Check that all placed instances are known in instances
    missing_insts = [inst for inst in initial_placement if inst not in instances]
    if missing_insts:
        print(f"[WARN] {len(missing_insts)} instances in initial map are not in logical.instances. "
              f"They will be ignored in cost (but still placed).")

    # Current solution
    placement: Dict[str, str] = dict(initial_placement)
    current_cost = compute_total_hpwl(net_to_insts, slot_info, placement)
    best_placement: Dict[str, str] = dict(placement)
    best_cost = current_cost

    print(f"[INFO] Initial HPWL cost: {current_cost:.3f}")
    print(f"[INFO] SA schedule: num_temp_steps={num_temp_steps}, "
          f"moves_per_temp={moves_per_temp}, T_initial={T_initial}, alpha={alpha}, "
          f"W_initial={W_initial}, beta={beta}, P_refine={P_refine:.3f}, "
          f"P_explore={1.0 - P_refine:.3f}")

    move_counter = 0

    for k in range(num_temp_steps):
        # Temperature and window size for this step
        T_k = T_initial * (alpha ** k)
        W_k = W_initial * (beta ** k)

        for _ in range(moves_per_temp):
            move_counter += 1

            # Decide move type based on P_refine vs P_explore
            use_refine = (random.random() < P_refine)
            if use_refine:
                # Try swap; if impossible, fall back to explore
                try:
                    move_kind, move_data = propose_swap_move(
                        placement,
                        inst_type,
                        type_to_insts,
                        slots_by_phys_type,
                        free_slots_by_type,
                    )
                except RuntimeError:
                    move_kind, move_data = propose_move_to_free_slot(
                        placement,
                        inst_type,
                        type_to_insts,
                        slots_by_phys_type,
                        free_slots_by_type,
                        slot_info,
                        W_k,
                        die_bbox,
                    )
            else:
                # Try explore (move-to-windowed-free-slot); if impossible, fall back to swap
                try:
                    move_kind, move_data = propose_move_to_free_slot(
                        placement,
                        inst_type,
                        type_to_insts,
                        slots_by_phys_type,
                        free_slots_by_type,
                        slot_info,
                        W_k,
                        die_bbox,
                    )
                except RuntimeError:
                    move_kind, move_data = propose_swap_move(
                        placement,
                        inst_type,
                        type_to_insts,
                        slots_by_phys_type,
                        free_slots_by_type,
                    )

            # Compute new cost
            new_cost = compute_total_hpwl(net_to_insts, slot_info, placement)
            delta = new_cost - current_cost

            # Decide acceptance
            accept = False
            if delta <= 0:
                accept = True
            else:
                prob = math.exp(-delta / T_k)
                if random.random() < prob:
                    accept = True

            if accept:
                current_cost = new_cost
                if new_cost < best_cost:
                    best_cost = new_cost
                    best_placement = dict(placement)
            else:
                # Revert move
                if move_kind == "swap":
                    revert_swap_move(placement, move_data)  # type: ignore[arg-type]
                elif move_kind == "move_free":
                    revert_move_to_free_slot(placement, free_slots_by_type, move_data)  # type: ignore[arg-type]
                else:
                    raise RuntimeError(f"Unknown move kind {move_kind!r}")

            # Optional progress report
            if report_interval > 0 and (
                move_counter % report_interval == 0 or move_counter == total_moves
            ):
                print(
                    f"[SA] move={move_counter}/{total_moves} "
                    f"temp_step={k+1}/{num_temp_steps} "
                    f"T={T_k:.4f} W={W_k:.4f} "
                    f"current_cost={current_cost:.3f} best_cost={best_cost:.3f}"
                )

    print(f"[INFO] SA finished. Best HPWL cost: {best_cost:.3f}")
    return best_placement, best_cost


# ---------------- CLI ----------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Simulated Annealing placer using data_structures.json and greedy map "
                    "with T_initial, alpha, N, P_refine/P_explore, W_initial, and beta."
    )
    p.add_argument(
        "--data-structures",
        required=True,
        help="Path to data_structures.json (from dataStructuresGenerator.py).",
    )
    p.add_argument(
        "--initial-map",
        required=True,
        help="Path to initial greedy map file (inst -> slot).",
    )
    p.add_argument(
        "--out-map",
        required=True,
        help="Path to write the SA-optimized map file.",
    )

    # Annealing schedule
    p.add_argument(
        "--num-temp-steps",
        type=int,
        default=60,
        help="Number of temperature steps (default: 60).",
    )
    p.add_argument(
        "--moves-per-temp",
        type=int,
        default=1000,
        help="Moves per temperature step N (default: 1000).",
    )
    p.add_argument(
        "--T-initial",
        dest="T_initial",
        type=float,
        default=200.0,
        help="Initial temperature T_initial (default: 200.0).",
    )
    p.add_argument(
        "--alpha",
        type=float,
        default=0.95,
        help="Cooling rate alpha (T_{k+1} = alpha * T_k), default: 0.95.",
    )

    # Hybrid move set
    p.add_argument(
        "--P-refine",
        dest="P_refine",
        type=float,
        default=0.7,
        help="Probability P_refine of choosing a refine (swap) move; "
             "P_explore = 1 - P_refine (default: 0.7).",
    )

    # Exploration window
    p.add_argument(
        "--W-initial",
        dest="W_initial",
        type=float,
        default=0.5,
        help="Initial exploration window size W_initial as fraction of die width/height "
             "(default: 0.5).",
    )
    p.add_argument(
        "--beta",
        type=float,
        default=0.95,
        help="Window cooling rate beta (W_k = W_initial * beta^k), default: 0.95.",
    )

    # Misc
    p.add_argument(
        "--report-interval",
        type=int,
        default=1000,
        help="Print SA progress every N moves (default: 1000).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed for reproducibility (default: 0; 0 means use system randomness).",
    )

    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.seed != 0:
        random.seed(args.seed)
        print(f"[INFO] Using random seed {args.seed}.")
    else:
        print("[INFO] Using system randomness (no fixed seed).")

    print(f"[INFO] Loading data structures from '{args.data_structures}'...")
    ds = load_json(args.data_structures)

    logical = ds.get("logical")
    fabric = ds.get("fabric")

    if logical is None or fabric is None:
        raise ValueError("data_structures.json must contain top-level keys 'logical' and 'fabric'.")

    # logical.instances is the dict built by dataStructuresGenerator
    instances = logical.get("instances")
    if not isinstance(instances, dict):
        # Fallback in case you ever change the schema name
        instances = logical.get("cells")

    if not isinstance(instances, dict):
        raise ValueError("'logical.instances' or 'logical.cells' must be a dict in data_structures.json.")

    slots_by_phys_type = fabric.get("slots_by_phys_type")
    slot_info = fabric.get("slot_info")

    if not isinstance(slots_by_phys_type, dict):
        raise ValueError("'fabric.slots_by_phys_type' must be a dict in data_structures.json.")
    if not isinstance(slot_info, dict):
        raise ValueError("'fabric.slot_info' must be a dict in data_structures.json.")

    print(f"[INFO] Loading initial placement map from '{args.initial_map}'...")
    initial_placement = load_map(args.initial_map)

    # Basic sanity check: number of placed instances vs logical.instances
    print(f"[INFO] logical.instances: {len(instances)} entries.")
    print(f"[INFO] initial_placement: {len(initial_placement)} entries.")

    # Run SA with the lecture-style knobs
    best_placement, best_cost = simulated_annealing(
        instances=instances,
        slot_info=slot_info,
        slots_by_phys_type=slots_by_phys_type,
        initial_placement=initial_placement,
        num_temp_steps=args.num_temp_steps,
        T_initial=args.T_initial,
        alpha=args.alpha,
        moves_per_temp=args.moves_per_temp,
        P_refine=args.P_refine,
        W_initial=args.W_initial,
        beta=args.beta,
        report_interval=args.report_interval,
    )

    # Write best map
    print("[INFO] Writing best placement map...")
    write_map(args.out_map, best_placement)
    print("[INFO] Done.")


if __name__ == "__main__":
    main()