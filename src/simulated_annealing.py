#!/usr/bin/env python3
# simulated_annealing.py
"""
Simulated Annealing Placer (HPWL + Congestion)

Adds an SA-level routability improvement:
  total_cost = weighted_hpwl + lambda_cong * congestion_cost

Where:
- weighted_hpwl uses net weights that grow with net degree (fanout).
- congestion_cost uses a simple RUDY-style demand on a coarse bin grid:
    For each net bbox in bin space, add (w/area) demand to bins in bbox
    congestion_cost = sum_over_bins(demand^2)
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
                net_to_insts[bit].add(inst_name)

    return net_to_insts


def build_type_index(instances: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Build:
        inst_type: inst_name -> physical cell type string
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
    """
    from collections import defaultdict

    used_slots_by_type: Dict[str, Set[str]] = defaultdict(set)
    for inst_name, slot_name in placement.items():
        ctype = inst_type.get(inst_name)
        if ctype is None:
            continue
        used_slots_by_type[ctype].add(slot_name)

    free_slots_by_type: Dict[str, List[str]] = {}

    for ctype, all_slots in slots_by_phys_type.items():
        used = used_slots_by_type.get(ctype, set())
        free = [s for s in all_slots if s not in used]
        free_slots_by_type[ctype] = free

    return free_slots_by_type


# ---------------- HPWL + congestion cost computation ----------------

def net_weight(deg: int, gamma: float) -> float:
    """
    Simple fanout-based weight:
      w = 1 + gamma * log2(deg)
    """
    if deg <= 1:
        return 1.0
    if gamma <= 0.0:
        return 1.0
    return 1.0 + gamma * math.log2(float(deg))


def clamp_int(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def coord_to_bin(x: float, x0: float, x1: float, nbins: int) -> int:
    """
    Map coordinate x in [x0, x1] to a bin index in [0, nbins-1].
    """
    if nbins <= 1 or x1 <= x0:
        return 0
    t = (x - x0) / (x1 - x0)  # can be outside [0,1]
    idx = int(math.floor(t * nbins))
    return clamp_int(idx, 0, nbins - 1)


def compute_cost_components(
    net_to_insts: Dict[int, Set[str]],
    slot_info: Dict[str, Dict[str, Any]],
    placement: Dict[str, str],
    die_bbox: Tuple[float, float, float, float],
    gamma: float,
    bins_x: int,
    bins_y: int,
) -> Tuple[float, float]:
    """
    Compute:
      - weighted_hpwl
      - congestion_cost (sum of squared RUDY demands per bin)
    """
    min_x, max_x, min_y, max_y = die_bbox

    # Demand grid (flattened)
    if bins_x <= 0 or bins_y <= 0:
        bins_x = 1
        bins_y = 1
    demand = [0.0] * (bins_x * bins_y)

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

        if len(xs) < 2:
            continue

        deg = len(xs)
        w = net_weight(deg, gamma)

        x_lo, x_hi = min(xs), max(xs)
        y_lo, y_hi = min(ys), max(ys)

        # Weighted HPWL
        hpwl = (x_hi - x_lo) + (y_hi - y_lo)
        total_hpwl += w * hpwl

        # Congestion (RUDY on bins)
        bx0 = coord_to_bin(x_lo, min_x, max_x, bins_x)
        bx1 = coord_to_bin(x_hi, min_x, max_x, bins_x)
        by0 = coord_to_bin(y_lo, min_y, max_y, bins_y)
        by1 = coord_to_bin(y_hi, min_y, max_y, bins_y)

        if bx0 > bx1:
            bx0, bx1 = bx1, bx0
        if by0 > by1:
            by0, by1 = by1, by0

        area = (bx1 - bx0 + 1) * (by1 - by0 + 1)
        if area <= 0:
            continue

        add = w / float(area)
        for by in range(by0, by1 + 1):
            row = by * bins_x
            for bx in range(bx0, bx1 + 1):
                demand[row + bx] += add

    cong = 0.0
    for d in demand:
        cong += d * d

    return total_hpwl, cong


def compute_total_cost(
    net_to_insts: Dict[int, Set[str]],
    slot_info: Dict[str, Dict[str, Any]],
    placement: Dict[str, str],
    die_bbox: Tuple[float, float, float, float],
    gamma: float,
    bins_x: int,
    bins_y: int,
    lambda_cong: float,
) -> Tuple[float, float, float]:
    """
    Returns (total_cost, weighted_hpwl, congestion_cost)
    """
    hpwl, cong = compute_cost_components(
        net_to_insts=net_to_insts,
        slot_info=slot_info,
        placement=placement,
        die_bbox=die_bbox,
        gamma=gamma,
        bins_x=bins_x,
        bins_y=bins_y,
    )
    total = hpwl + lambda_cong * cong
    return total, hpwl, cong


# ---------------- SA move generation ----------------

def choose_type_with_insts(
    type_to_insts: Dict[str, List[str]],
    slots_by_phys_type: Dict[str, List[str]],
    free_slots_by_type: Dict[str, List[str]],
    require_two_insts: bool = False,
    require_free_slot: bool = False,
) -> str:
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

    placement[inst1], placement[inst2] = slot2, slot1

    move_data = (inst1, slot1, inst2, slot2)
    return "swap", move_data


def revert_swap_move(
    placement: Dict[str, str],
    move_data: Tuple[str, str, str, str],
) -> None:
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
    min_x, max_x, min_y, max_y = die_bbox
    die_width = max_x - min_x
    die_height = max_y - min_y

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

    new_slot = random.choice(candidate_slots)

    placement[inst] = new_slot
    free_slots.remove(new_slot)
    free_slots.append(old_slot)

    move_data = (inst, old_slot, new_slot, ctype)
    return "move_free", move_data


def revert_move_to_free_slot(
    placement: Dict[str, str],
    free_slots_by_type: Dict[str, List[str]],
    move_data: Tuple[str, str, str, str],
) -> None:
    inst, old_slot, new_slot, ctype = move_data

    placement[inst] = old_slot

    free_slots = free_slots_by_type[ctype]
    if old_slot in free_slots:
        free_slots.remove(old_slot)
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
    gamma: float,
    lambda_cong: float,
    lambda_growth: float,
    cong_bins_x: int,
    cong_bins_y: int,
    report_interval: int = 1000,
) -> Tuple[Dict[str, str], float]:
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
    if lambda_cong < 0.0:
        raise ValueError("lambda_cong must be >= 0.")
    if lambda_growth <= 0.0:
        raise ValueError("lambda_growth must be > 0.")
    if cong_bins_x <= 0 or cong_bins_y <= 0:
        raise ValueError("cong_bins_x and cong_bins_y must be positive integers.")

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

    missing_insts = [inst for inst in initial_placement if inst not in instances]
    if missing_insts:
        print(f"[WARN] {len(missing_insts)} instances in initial map are not in logical.instances. "
              f"They will be ignored in cost (but still placed).")

    placement: Dict[str, str] = dict(initial_placement)

    # Initial cost (k=0 lambda)
    lambda_k = lambda_cong * (lambda_growth ** 0)
    current_cost, current_hpwl, current_cong = compute_total_cost(
        net_to_insts, slot_info, placement, die_bbox,
        gamma=gamma, bins_x=cong_bins_x, bins_y=cong_bins_y,
        lambda_cong=lambda_k,
    )
    best_placement: Dict[str, str] = dict(placement)
    best_cost = current_cost
    best_hpwl = current_hpwl
    best_cong = current_cong

    print(f"[INFO] Initial cost: total={current_cost:.3f} hpwl={current_hpwl:.3f} cong={current_cong:.3f} "
          f"(lambda={lambda_k:.6f}, bins={cong_bins_x}x{cong_bins_y}, gamma={gamma})")
    print(f"[INFO] SA schedule: num_temp_steps={num_temp_steps}, moves_per_temp={moves_per_temp}, "
          f"T_initial={T_initial}, alpha={alpha}, W_initial={W_initial}, beta={beta}, "
          f"P_refine={P_refine:.3f}, P_explore={1.0 - P_refine:.3f}, "
          f"lambda_cong={lambda_cong}, lambda_growth={lambda_growth}")

    move_counter = 0

    for k in range(num_temp_steps):
        T_k = T_initial * (alpha ** k)
        W_k = W_initial * (beta ** k)
        lambda_k = lambda_cong * (lambda_growth ** k)

        for _ in range(moves_per_temp):
            move_counter += 1

            use_refine = (random.random() < P_refine)
            if use_refine:
                try:
                    move_kind, move_data = propose_swap_move(
                        placement, inst_type, type_to_insts, slots_by_phys_type, free_slots_by_type
                    )
                except RuntimeError:
                    move_kind, move_data = propose_move_to_free_slot(
                        placement, inst_type, type_to_insts, slots_by_phys_type,
                        free_slots_by_type, slot_info, W_k, die_bbox
                    )
            else:
                try:
                    move_kind, move_data = propose_move_to_free_slot(
                        placement, inst_type, type_to_insts, slots_by_phys_type,
                        free_slots_by_type, slot_info, W_k, die_bbox
                    )
                except RuntimeError:
                    move_kind, move_data = propose_swap_move(
                        placement, inst_type, type_to_insts, slots_by_phys_type, free_slots_by_type
                    )

            new_cost, new_hpwl, new_cong = compute_total_cost(
                net_to_insts, slot_info, placement, die_bbox,
                gamma=gamma, bins_x=cong_bins_x, bins_y=cong_bins_y,
                lambda_cong=lambda_k,
            )
            delta = new_cost - current_cost

            accept = False
            if delta <= 0:
                accept = True
            else:
                # Guard tiny/zero temperature
                if T_k > 1e-12:
                    prob = math.exp(-delta / T_k)
                    if random.random() < prob:
                        accept = True

            if accept:
                current_cost = new_cost
                current_hpwl = new_hpwl
                current_cong = new_cong
                if new_cost < best_cost:
                    best_cost = new_cost
                    best_hpwl = new_hpwl
                    best_cong = new_cong
                    best_placement = dict(placement)
            else:
                if move_kind == "swap":
                    revert_swap_move(placement, move_data)  # type: ignore[arg-type]
                elif move_kind == "move_free":
                    revert_move_to_free_slot(placement, free_slots_by_type, move_data)  # type: ignore[arg-type]
                else:
                    raise RuntimeError(f"Unknown move kind {move_kind!r}")

            if report_interval > 0 and (
                move_counter % report_interval == 0 or move_counter == total_moves
            ):
                print(
                    f"[SA] move={move_counter}/{total_moves} "
                    f"temp_step={k+1}/{num_temp_steps} "
                    f"T={T_k:.4f} W={W_k:.4f} lambda={lambda_k:.6f} "
                    f"cur_total={current_cost:.3f} cur_hpwl={current_hpwl:.3f} cur_cong={current_cong:.3f} "
                    f"best_total={best_cost:.3f}"
                )

    print(f"[INFO] SA finished. Best cost: total={best_cost:.3f} hpwl={best_hpwl:.3f} cong={best_cong:.3f}")
    return best_placement, best_cost


# ---------------- CLI ----------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Simulated Annealing placer using data_structures.json and greedy map "
                    "with HPWL + congestion (RUDY bins)."
    )
    p.add_argument("--data-structures", required=True, help="Path to data_structures.json.")
    p.add_argument("--initial-map", required=True, help="Path to initial greedy map file.")
    p.add_argument("--out-map", required=True, help="Path to write the SA-optimized map file.")

    # Annealing schedule
    p.add_argument("--num-temp-steps", type=int, default=1000,
                   help="Number of temperature steps.")
    p.add_argument("--moves-per-temp", type=int, default=150,
                   help="Moves per temperature step N.")
    p.add_argument("--T-initial", dest="T_initial", type=float, default=4000000.0,
                   help="Initial temperature T_initial.")
    p.add_argument("--alpha", type=float, default=0.80,
                   help="Cooling rate alpha (T_{k+1} = alpha * T_k).")

    # Hybrid move set
    p.add_argument("--P-refine", dest="P_refine", type=float, default=0.9,
                   help="Probability of refine (swap) move; explore = 1 - P_refine.")

    # Exploration window
    p.add_argument("--W-initial", dest="W_initial", type=float, default=0.3,
                   help="Initial exploration window fraction.")
    p.add_argument("--beta", type=float, default=0.90,
                   help="Window cooling rate beta.")

    # ---- NEW: HPWL weighting + congestion knobs ----
    p.add_argument("--gamma", type=float, default=0.75,
                   help="Net weight strength for weighted HPWL: w=1+gamma*log2(deg). (default: 0.75)")
    p.add_argument("--lambda-cong", dest="lambda_cong", type=float, default=0.10,
                   help="Congestion weight λ in total = hpwl + λ*cong. (default: 0.10)")
    p.add_argument("--lambda-growth", dest="lambda_growth", type=float, default=1.00,
                   help="Multiply λ each temp step: λ_k = λ0*(growth^k). (default: 1.00)")
    p.add_argument("--cong-bins-x", type=int, default=30,
                   help="Congestion grid bins in X. (default: 30)")
    p.add_argument("--cong-bins-y", type=int, default=30,
                   help="Congestion grid bins in Y. (default: 30)")

    # Misc
    p.add_argument("--report-interval", type=int, default=1000,
                   help="Print SA progress every N moves.")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed for reproducibility (0 means system randomness).")

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

    instances = logical.get("instances")
    if not isinstance(instances, dict):
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

    print(f"[INFO] logical.instances: {len(instances)} entries.")
    print(f"[INFO] initial_placement: {len(initial_placement)} entries.")

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
        gamma=args.gamma,
        lambda_cong=args.lambda_cong,
        lambda_growth=args.lambda_growth,
        cong_bins_x=args.cong_bins_x,
        cong_bins_y=args.cong_bins_y,
        report_interval=args.report_interval,
    )

    print("[INFO] Writing best placement map...")
    write_map(args.out_map, best_placement)
    print("[INFO] Done.")


if __name__ == "__main__":
    main()
