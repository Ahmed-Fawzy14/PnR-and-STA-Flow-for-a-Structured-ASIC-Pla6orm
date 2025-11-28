#!/usr/bin/env python3
"""
Phase 2 Placement Visualizations

Generates:
1. Placement Density Heatmap: 2D histogram showing cell placement density
2. Net Length Histogram: 1D histogram of all net HPWLs
"""

import argparse
import json
import os
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

import numpy as np
from matplotlib import pyplot as plt


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_map(path: str) -> Dict[str, str]:
    """Load placement map: inst_name -> slot_name"""
    mapping: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                continue
            inst, slot = parts
            mapping[inst] = slot
    return mapping


def build_net_to_insts(instances: Dict[str, Any]) -> Dict[int, Set[str]]:
    """Build net_to_insts from logical.instances using pin bit IDs."""
    net_to_insts: Dict[int, Set[str]] = defaultdict(set)
    
    for inst_name, cell in instances.items():
        pins = cell.get("pins", {})
        for _pin_name, bit_list in pins.items():
            if not isinstance(bit_list, list):
                continue
            for bit in bit_list:
                net_to_insts[bit].add(inst_name)
    
    return net_to_insts


def compute_net_hpwls(
    net_to_insts: Dict[int, Set[str]],
    slot_info: Dict[str, Dict[str, Any]],
    placement: Dict[str, str],
) -> List[float]:
    """
    Compute HPWL for each net.
    
    Returns:
        List of HPWL values (one per net)
    """
    net_hpwls: List[float] = []
    
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
            net_hpwls.append(hpwl)
    
    return net_hpwls


def plot_density_heatmap(
    placement: Dict[str, str],
    slot_info: Dict[str, Dict[str, Any]],
    die_bbox: Tuple[float, float, float, float],
    out_path: str,
    design_name: str,
    bins: int = 100,
) -> None:
    """
    Generate a 2D density heatmap of placed cells.
    
    Args:
        placement: inst_name -> slot_name mapping
        slot_info: slot_name -> {x, y, ...} dict
        die_bbox: (min_x, max_x, min_y, max_y)
        out_path: Output PNG path
        design_name: Design name for title
        bins: Number of bins for histogram (default: 100)
    """
    min_x, max_x, min_y, max_y = die_bbox
    
    # Collect placed cell coordinates
    x_coords: List[float] = []
    y_coords: List[float] = []
    
    for inst, slot in placement.items():
        sinfo = slot_info.get(slot)
        if not sinfo:
            continue
        
        x = sinfo.get("x")
        y = sinfo.get("y")
        if x is None or y is None:
            continue
        
        x_coords.append(float(x))
        y_coords.append(float(y))
    
    if not x_coords:
        print("[WARN] No placed cells found for density heatmap")
        return
    
    # Create 2D histogram
    H, xedges, yedges = np.histogram2d(
        x_coords, y_coords,
        bins=bins,
        range=[[min_x, max_x], [min_y, max_y]]
    )
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 10))
    
    # Plot heatmap
    im = ax.imshow(
        H.T,
        origin='lower',
        extent=[min_x, max_x, min_y, max_y],
        aspect='auto',
        cmap='YlOrRd',  # Yellow-Orange-Red colormap
        interpolation='nearest'
    )
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Cell Density', rotation=270, labelpad=20)
    
    # Labels and title
    ax.set_xlabel('X Position (µm)', fontsize=12)
    ax.set_ylabel('Y Position (µm)', fontsize=12)
    ax.set_title(f'{design_name} - Placement Density Heatmap\n'
                 f'Total Placed Cells: {len(x_coords)}', fontsize=14, fontweight='bold')
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"[INFO] Saved density heatmap to '{out_path}'")
    plt.close()


def plot_net_length_histogram(
    net_hpwls: List[float],
    out_path: str,
    design_name: str,
    bins: int = 50,
) -> None:
    """
    Generate a 1D histogram of net HPWLs.
    
    Args:
        net_hpwls: List of HPWL values (one per net)
        out_path: Output PNG path
        design_name: Design name for title
        bins: Number of bins for histogram (default: 50)
    """
    if not net_hpwls:
        print("[WARN] No net HPWLs found for histogram")
        return
    
    # Create figure
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Plot histogram
    n, bins_edges, patches = ax.hist(
        net_hpwls,
        bins=bins,
        edgecolor='black',
        alpha=0.7,
        color='steelblue'
    )
    
    # Statistics
    mean_hpwl = np.mean(net_hpwls)
    median_hpwl = np.median(net_hpwls)
    max_hpwl = np.max(net_hpwls)
    total_hpwl = np.sum(net_hpwls)
    
    # Add statistics text
    stats_text = (
        f'Total Nets: {len(net_hpwls)}\n'
        f'Total HPWL: {total_hpwl:.2f} µm\n'
        f'Mean HPWL: {mean_hpwl:.2f} µm\n'
        f'Median HPWL: {median_hpwl:.2f} µm\n'
        f'Max HPWL: {max_hpwl:.2f} µm'
    )
    
    ax.text(0.98, 0.98, stats_text,
            transform=ax.transAxes,
            verticalalignment='top',
            horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            fontsize=10,
            family='monospace')
    
    # Labels and title
    ax.set_xlabel('Net HPWL (µm)', fontsize=12)
    ax.set_ylabel('Number of Nets', fontsize=12)
    ax.set_title(f'{design_name} - Net Length Histogram', fontsize=14, fontweight='bold')
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle='--', axis='y')
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"[INFO] Saved net length histogram to '{out_path}'")
    plt.close()


def compute_die_bbox(slot_info: Dict[str, Dict[str, Any]]) -> Tuple[float, float, float, float]:
    """Compute die bounding box from all slots."""
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
        raise ValueError("slot_info has no valid x/y coordinates")
    
    return min(xs), max(xs), min(ys), max(ys)


def main():
    parser = argparse.ArgumentParser(
        description="Generate Phase 2 placement visualizations: density heatmap and net length histogram"
    )
    parser.add_argument(
        "--data-structures",
        required=True,
        help="Path to data_structures.json"
    )
    parser.add_argument(
        "--placement-map",
        required=True,
        help="Path to placement map file (inst -> slot)"
    )
    parser.add_argument(
        "--design-name",
        required=True,
        help="Design name (e.g., '6502')"
    )
    parser.add_argument(
        "--out-density",
        required=True,
        help="Output path for density heatmap PNG"
    )
    parser.add_argument(
        "--out-net-length",
        required=True,
        help="Output path for net length histogram PNG"
    )
    parser.add_argument(
        "--density-bins",
        type=int,
        default=100,
        help="Number of bins for density heatmap (default: 100)"
    )
    parser.add_argument(
        "--hist-bins",
        type=int,
        default=50,
        help="Number of bins for net length histogram (default: 50)"
    )
    
    args = parser.parse_args()
    
    # Load data
    print(f"[INFO] Loading data structures from '{args.data_structures}'...")
    ds = load_json(args.data_structures)
    
    logical = ds.get("logical")
    fabric = ds.get("fabric")
    
    if logical is None or fabric is None:
        raise ValueError("data_structures.json must contain 'logical' and 'fabric' keys")
    
    instances = logical.get("instances")
    if not isinstance(instances, dict):
        instances = logical.get("cells")
    if not isinstance(instances, dict):
        raise ValueError("'logical.instances' or 'logical.cells' must be a dict")
    
    slot_info = fabric.get("slot_info")
    if not isinstance(slot_info, dict):
        raise ValueError("'fabric.slot_info' must be a dict")
    
    print(f"[INFO] Loading placement map from '{args.placement_map}'...")
    placement = load_map(args.placement_map)
    
    # Build net structure
    print("[INFO] Building net structure...")
    net_to_insts = build_net_to_insts(instances)
    
    # Compute die bbox
    print("[INFO] Computing die bounding box...")
    die_bbox = compute_die_bbox(slot_info)
    
    # Generate density heatmap
    print("[INFO] Generating placement density heatmap...")
    plot_density_heatmap(
        placement,
        slot_info,
        die_bbox,
        args.out_density,
        args.design_name,
        bins=args.density_bins
    )
    
    # Compute net HPWLs
    print("[INFO] Computing net HPWLs...")
    net_hpwls = compute_net_hpwls(net_to_insts, slot_info, placement)
    
    # Generate net length histogram
    print("[INFO] Generating net length histogram...")
    plot_net_length_histogram(
        net_hpwls,
        args.out_net_length,
        args.design_name,
        bins=args.hist_bins
    )
    
    print("[INFO] Done.")


if __name__ == "__main__":
    main()

