#!/usr/bin/env python3
"""
Visualize Clock Tree Synthesis (CTS) results

Shows DFFs (sinks), CTS buffers, and clock tree connections on a layout view.
"""

import json
import argparse
import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from typing import Dict, List, Tuple, Optional


def load_json(path: str) -> dict:
    """Load JSON file"""
    with open(path, 'r') as f:
        return json.load(f)


def load_placement_map(map_file: str) -> Dict[str, str]:
    """Load placement map: instance -> slot_name"""
    placement = {}
    with open(map_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                inst_name = parts[0]
                slot_name = ' '.join(parts[1:])
                placement[inst_name] = slot_name
    return placement


def load_fabric_db(fabric_db_file: str) -> Dict[str, Tuple[float, float]]:
    """Load fabric DB and extract slot coordinates"""
    fabric_data = load_json(fabric_db_file)
    slot_coords = {}
    
    if isinstance(fabric_data, dict):
        # Check if it's the processed format
        if "slot_coords" in fabric_data:
            coords_dict = fabric_data["slot_coords"]
            for slot_name, coord in coords_dict.items():
                if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                    slot_coords[slot_name] = (float(coord[0]), float(coord[1]))
        else:
            # Raw fabric_db.json format (organized by type)
            for slot_type, slots in fabric_data.items():
                if isinstance(slots, list):
                    for slot in slots:
                        if isinstance(slot, dict):
                            slot_name = slot.get("name")
                            if slot_name:
                                x = slot.get("x", 0.0)
                                y = slot.get("y", 0.0)
                                slot_coords[slot_name] = (float(x), float(y))
    
    return slot_coords


def get_coordinate(instance_name: str, placement: Dict[str, str], 
                   slot_coords: Dict[str, Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """Get coordinate for an instance"""
    if instance_name in placement:
        slot_name = placement[instance_name]
        if slot_name in slot_coords:
            return slot_coords[slot_name]
    return None


def visualize_cts(cts_info_file: str, placement_map_file: str, 
                   fabric_db_file: str, output_png: str, design_name: str = "arith"):
    """Visualize CTS results"""
    
    print(f"[VIS] Loading CTS info from {cts_info_file}...")
    cts_info = load_json(cts_info_file)
    
    print(f"[VIS] Loading placement map from {placement_map_file}...")
    placement = load_placement_map(placement_map_file)
    
    print(f"[VIS] Loading fabric DB from {fabric_db_file}...")
    slot_coords = load_fabric_db(fabric_db_file)
    
    # Extract data
    buffers = cts_info.get("buffers", [])
    connections = cts_info.get("connections", [])
    
    # Get coordinates for all buffers and DFFs
    buffer_coords = {}
    dff_coords = {}
    
    # Get buffer coordinates
    for buf in buffers:
        buf_inst = buf["instance"]
        buf_slot = buf["slot"]
        coord = get_coordinate(buf_inst, placement, slot_coords)
        if coord:
            buffer_coords[buf_inst] = coord
        
        # Check children - if they're DFFs, get their coordinates
        for child in buf.get("children", []):
            if not child.startswith("cts_"):  # It's a DFF
                coord = get_coordinate(child, placement, slot_coords)
                if coord:
                    dff_coords[child] = coord
    
    # Also get DFF coordinates from connections
    for conn in connections:
        sink = conn["sink"]
        if not sink.startswith("cts_") and sink != "clk":
            coord = get_coordinate(sink, placement, slot_coords)
            if coord:
                dff_coords[sink] = coord
    
    print(f"[VIS] Found {len(buffer_coords)} buffer coordinates")
    print(f"[VIS] Found {len(dff_coords)} DFF coordinates")
    
    # Create figure
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    
    # Draw connections
    for conn in connections:
        driver = conn["driver"]
        sink = conn["sink"]
        
        # Skip clock port connection (we'll draw it separately)
        if driver == "clk":
            continue
        
        driver_coord = None
        sink_coord = None
        
        if driver in buffer_coords:
            driver_coord = buffer_coords[driver]
        elif driver in placement:
            driver_coord = get_coordinate(driver, placement, slot_coords)
        
        if sink in buffer_coords:
            sink_coord = buffer_coords[sink]
        elif sink in dff_coords:
            sink_coord = dff_coords[sink]
        elif sink in placement:
            sink_coord = get_coordinate(sink, placement, slot_coords)
        
        if driver_coord and sink_coord:
            ax.plot([driver_coord[0], sink_coord[0]], 
                   [driver_coord[1], sink_coord[1]], 
                   'b-', linewidth=1.5, alpha=0.6, zorder=1)
    
    # Draw DFFs (sinks)
    for dff_name, coord in dff_coords.items():
        ax.scatter(coord[0], coord[1], c='red', s=150, marker='s', 
                  edgecolors='darkred', linewidths=2, zorder=3, label='DFF' if dff_name == list(dff_coords.keys())[0] else '')
    
    # Draw buffers
    for buf_inst, coord in buffer_coords.items():
        ax.scatter(coord[0], coord[1], c='green', s=200, marker='^', 
                  edgecolors='darkgreen', linewidths=2, zorder=3, 
                  label='CTS Buffer' if buf_inst == list(buffer_coords.keys())[0] else '')
    
    # Draw root connection (from clock port)
    root_conn = None
    for conn in connections:
        if conn["driver"] == "clk":
            root_conn = conn
            break
    
    if root_conn:
        root_buffer = root_conn["sink"]
        if root_buffer in buffer_coords:
            root_coord = buffer_coords[root_buffer]
            # Draw a special marker for root buffer
            ax.scatter(root_coord[0], root_coord[1], c='blue', s=250, marker='*', 
                      edgecolors='darkblue', linewidths=2, zorder=4, label='Root Buffer')
    
    # Set labels and title
    ax.set_xlabel('X (µm)', fontsize=12)
    ax.set_ylabel('Y (µm)', fontsize=12)
    ax.set_title(f'Clock Tree Synthesis - {design_name}\n'
                f'DFFs: {len(dff_coords)}, Buffers: {len(buffer_coords)}, Connections: {len(connections)}',
                fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', fontsize=10)
    ax.set_aspect('equal', adjustable='box')
    
    # Save figure
    os.makedirs(os.path.dirname(output_png), exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_png, dpi=150, bbox_inches='tight')
    print(f"[VIS] Visualization saved to {output_png}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Visualize Clock Tree Synthesis results")
    parser.add_argument("--design", required=True, help="Design name (e.g., arith)")
    parser.add_argument("--cts-info", help="CTS info JSON file (default: build/<design>/<design>_cts.json)")
    parser.add_argument("--map", help="Placement map file (default: build/<design>/<design>_cts.map)")
    parser.add_argument("--fabric-db", help="Fabric DB file (default: build/fabric/fabric_db.json)")
    parser.add_argument("--output", help="Output PNG file (default: build/<design>/<design>_cts_visualization.png)")
    parser.add_argument("--build-dir", default="build", help="Build directory (default: build)")
    
    args = parser.parse_args()
    
    design_name = args.design
    build_dir = args.build_dir
    
    # Set default paths
    cts_info_file = args.cts_info or os.path.join(build_dir, design_name, f"{design_name}_cts.json")
    map_file = args.map or os.path.join(build_dir, design_name, f"{design_name}_cts.map")
    fabric_db_file = args.fabric_db or os.path.join(build_dir, "fabric", "fabric_db.json")
    output_png = args.output or os.path.join(build_dir, design_name, f"{design_name}_cts_visualization.png")
    
    visualize_cts(cts_info_file, map_file, fabric_db_file, output_png, design_name)


if __name__ == "__main__":
    main()

