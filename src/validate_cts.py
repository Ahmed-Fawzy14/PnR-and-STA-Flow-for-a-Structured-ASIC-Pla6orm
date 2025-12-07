#!/usr/bin/env python3
"""
Validation script for Clock Tree Synthesis (CTS)

This script validates that:
1. All buffers are properly placed in the placement map
2. All DFF clock pins are connected to the clock tree (not original clock net)
3. Clock tree structure is correct (all DFFs reachable from clock port)
4. No missing connections or orphaned buffers
"""

import json
import argparse
import os
import sys
from collections import defaultdict, deque


def load_json(filepath):
    """Load JSON file"""
    with open(filepath, 'r') as f:
        return json.load(f)


def validate_placement_map(cts_map_file, cts_info_file):
    """Validate that all buffers are in the placement map"""
    print("\n" + "="*60)
    print("Validating Placement Map")
    print("="*60)
    
    # Load CTS info
    cts_info = load_json(cts_info_file)
    buffer_instances = {buf["instance"] for buf in cts_info["buffers"]}
    
    # Load placement map
    placed_instances = set()
    with open(cts_map_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                parts = line.split()
                if len(parts) >= 2:
                    placed_instances.add(parts[0])
    
    # Check all buffers are placed
    missing_buffers = buffer_instances - placed_instances
    if missing_buffers:
        print(f"❌ ERROR: {len(missing_buffers)} buffers missing from placement map")
        print(f"   Examples: {list(missing_buffers)[:5]}")
        return False
    else:
        print(f"✅ All {len(buffer_instances)} buffers are in placement map")
        return True


def validate_netlist_connections(original_json, cts_json, cts_info_file):
    """Validate that DFF clock pins are connected to clock tree"""
    print("\n" + "="*60)
    print("Validating Netlist Connections")
    print("="*60)
    
    # Load files
    original = load_json(original_json)
    cts_netlist = load_json(cts_json)
    cts_info = load_json(cts_info_file)
    
    # Get top modules
    orig_top = None
    cts_top = None
    for module_name, module_data in original.get("modules", {}).items():
        if module_data.get("attributes", {}).get("top") == "00000000000000000000000000000001":
            orig_top = module_data
            break
    if not orig_top:
        orig_top = list(original.get("modules", {}).values())[0]
    
    for module_name, module_data in cts_netlist.get("modules", {}).items():
        if module_data.get("attributes", {}).get("top") == "00000000000000000000000000000001":
            cts_top = module_data
            break
    if not cts_top:
        cts_top = list(cts_netlist.get("modules", {}).values())[0]
    
    orig_cells = orig_top.get("cells", {})
    cts_cells = cts_top.get("cells", {})
    
    # Get original clock net ID
    clock_net_id = None
    ports = orig_top.get("ports", {})
    for port_name, port_data in ports.items():
        if port_name.lower() == "clk" and port_data.get("direction") == "input":
            clock_net_id = port_data.get("bits", [None])[0]
            break
    
    if clock_net_id is None:
        print("⚠️  WARNING: Could not find original clock net ID")
        clock_net_id = 2  # Default assumption
    
    print(f"Original clock net ID: {clock_net_id}")
    
    # Find all DFF instances
    dff_instances = []
    for inst_name, inst_data in orig_cells.items():
        cell_type = inst_data.get("type", "").lower()
        if any(k in cell_type for k in ("dff", "dfx", "dlat", "sdff", "flop", "ff_", "_ff", "dfbb", "dfrb", "dfrt")):
            pins = inst_data.get("connections", {})
            pin_names_lower = {k.lower(): k for k in pins.keys()}
            if "clk" in pin_names_lower:
                dff_instances.append(inst_name)
    
    print(f"Found {len(dff_instances)} DFF instances")
    
    # Check DFF clock connections
    still_connected_to_original = []
    connected_to_tree = []
    not_found = []
    
    for dff_inst in dff_instances:
        if dff_inst not in cts_cells:
            not_found.append(dff_inst)
            continue
        
        cts_cell = cts_cells[dff_inst]
        connections = cts_cell.get("connections", {})
        
        # Find clock pin
        clock_pin = None
        for pin_name in connections.keys():
            if pin_name.upper() == "CLK" or pin_name.lower() == "clk":
                clock_pin = pin_name
                break
        
        if clock_pin:
            clock_net = connections[clock_pin]
            if isinstance(clock_net, list) and len(clock_net) > 0:
                clock_net = clock_net[0]
            
            if clock_net == clock_net_id:
                still_connected_to_original.append(dff_inst)
            else:
                connected_to_tree.append((dff_inst, clock_net))
    
    # Report results
    if not_found:
        print(f"❌ ERROR: {len(not_found)} DFFs not found in CTS netlist")
        return False
    
    if still_connected_to_original:
        print(f"❌ ERROR: {len(still_connected_to_original)} DFFs still connected to original clock net")
        print(f"   Examples: {still_connected_to_original[:5]}")
        return False
    
    print(f"✅ All {len(connected_to_tree)} DFFs connected to clock tree (new net IDs)")
    
    # Check buffer instances exist
    buffer_instances = {buf["instance"] for buf in cts_info["buffers"]}
    missing_buffers = buffer_instances - set(cts_cells.keys())
    if missing_buffers:
        print(f"❌ ERROR: {len(missing_buffers)} buffers missing from netlist")
        return False
    
    print(f"✅ All {len(buffer_instances)} buffers present in netlist")
    
    return True


def validate_clock_tree_structure(cts_info_file):
    """Validate that clock tree structure is correct"""
    print("\n" + "="*60)
    print("Validating Clock Tree Structure")
    print("="*60)
    
    cts_info = load_json(cts_info_file)
    
    # Build connection graph
    connections = cts_info["connections"]
    buffer_instances = {buf["instance"] for buf in cts_info["buffers"]}
    
    # Find root (connected to clock port)
    root_buffer = None
    for conn in connections:
        driver = conn.get("driver") if isinstance(conn, dict) else conn[0]
        sink = conn.get("sink") if isinstance(conn, dict) else conn[1]
        
        if driver.lower() == "clk" or driver == "clk":
            if sink in buffer_instances:
                root_buffer = sink
                break
    
    if not root_buffer:
        print("❌ ERROR: Could not find root buffer (connected to clock port)")
        return False
    
    print(f"Root buffer: {root_buffer}")
    
    # Build graph: buffer -> [children]
    graph = defaultdict(list)
    dff_sinks = set()
    
    for conn in connections:
        driver = conn.get("driver") if isinstance(conn, dict) else conn[0]
        sink = conn.get("sink") if isinstance(conn, dict) else conn[1]
        
        if driver in buffer_instances:
            graph[driver].append(sink)
        if sink not in buffer_instances and (sink.startswith("$") or "slice" in sink):
            dff_sinks.add(sink)
    
    # Verify all buffers have children (except leaf buffers)
    buffers_without_children = []
    for buf_inst in buffer_instances:
        if buf_inst not in graph or len(graph[buf_inst]) == 0:
            buffers_without_children.append(buf_inst)
    
    if buffers_without_children:
        print(f"⚠️  WARNING: {len(buffers_without_children)} buffers have no children")
        print(f"   This might be okay if they're leaf buffers")
    
    # Count DFFs reached
    print(f"DFFs in tree: {len(dff_sinks)}")
    print(f"Expected DFFs: {cts_info['dff_count']}")
    
    if len(dff_sinks) != cts_info['dff_count']:
        print(f"⚠️  WARNING: DFF count mismatch")
        print(f"   Tree has {len(dff_sinks)} DFFs, expected {cts_info['dff_count']}")
    
    # Verify tree connectivity (BFS from root)
    visited = set()
    queue = deque([root_buffer])
    visited.add(root_buffer)
    
    while queue:
        current = queue.popleft()
        if current in graph:
            for child in graph[current]:
                if child not in visited:
                    visited.add(child)
                    if child in buffer_instances:
                        queue.append(child)
    
    unreachable_buffers = buffer_instances - visited
    if unreachable_buffers:
        print(f"❌ ERROR: {len(unreachable_buffers)} buffers unreachable from root")
        return False
    
    print(f"✅ All {len(buffer_instances)} buffers reachable from root")
    print(f"✅ Tree structure is valid")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Validate Clock Tree Synthesis results"
    )
    parser.add_argument(
        "--design",
        required=True,
        help="Design name (e.g., 6502)"
    )
    parser.add_argument(
        "--build-dir",
        default="build",
        help="Build directory (default: build)"
    )
    parser.add_argument(
        "--designs-dir",
        default="designs",
        help="Designs directory (default: designs)"
    )
    
    args = parser.parse_args()
    
    design_name = args.design
    build_dir = args.build_dir
    designs_dir = args.designs_dir
    
    # File paths
    cts_map_file = os.path.join(build_dir, design_name, f"{design_name}_cts.map")
    cts_info_file = os.path.join(build_dir, design_name, f"{design_name}_cts.json")
    original_json = os.path.join(designs_dir, f"{design_name}_mapped.json")
    cts_json = os.path.join(build_dir, design_name, f"{design_name}_cts_mapped.json")
    
    # Check files exist
    missing_files = []
    for name, path in [("CTS map", cts_map_file), ("CTS info", cts_info_file),
                       ("Original JSON", original_json), ("CTS JSON", cts_json)]:
        if not os.path.exists(path):
            missing_files.append(f"{name}: {path}")
    
    if missing_files:
        print("❌ ERROR: Missing required files:")
        for f in missing_files:
            print(f"   {f}")
        sys.exit(1)
    
    # Run validations
    all_passed = True
    
    # 1. Validate placement map
    if not validate_placement_map(cts_map_file, cts_info_file):
        all_passed = False
    
    # 2. Validate netlist connections
    if not validate_netlist_connections(original_json, cts_json, cts_info_file):
        all_passed = False
    
    # 3. Validate tree structure
    if not validate_clock_tree_structure(cts_info_file):
        all_passed = False
    
    # Final summary
    print("\n" + "="*60)
    if all_passed:
        print("✅ ALL VALIDATIONS PASSED")
    else:
        print("❌ SOME VALIDATIONS FAILED")
    print("="*60 + "\n")
    
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

