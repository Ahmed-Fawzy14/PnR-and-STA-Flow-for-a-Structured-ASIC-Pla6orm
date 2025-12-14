#!/usr/bin/env python3
"""
Clock Tree Synthesis (CTS) for Structured ASIC Platform

This script implements a true H-Tree algorithm to build a balanced clock tree
by finding all placed DFFs (sinks) and using unused buffer/inverter cells
from the fabric to distribute the clock signal.

The H-Tree algorithm alternates partitioning direction at each level:
- Even levels: Partition by X-coordinate (left/right split) - horizontal H-bar
- Odd levels: Partition by Y-coordinate (top/bottom split) - vertical H-bar

This creates the characteristic H-shape pattern with geometric symmetry,
minimizing clock skew and wirelength.
"""

import json
import argparse
import os
import sys
import math
from typing import Dict, List, Tuple, Set, Optional, Any
from collections import defaultdict


class ClockTreeSynthesis:
    def __init__(self, design_name: str, build_dir: str = "build"):
        self.design_name = design_name
        self.build_dir = build_dir
        
        # Data structures
        self.placement = {}  # instance -> slot_name
        self.reverse_placement = {}  # slot_name -> instance
        self.logical_db = {}
        self.fabric_db = {}
        self.slot_coords = {}  # slot_name -> (x, y)
        self.slot_type = {}  # slot_name -> type
        self.slots_by_type = {}  # type -> [slot_names]
        
        # CTS-specific
        self.dff_instances = []  # List of DFF instance names
        self.dff_coords = {}  # instance -> (x, y)
        self.unused_buffers = []  # List of (instance_name, slot_name) tuples for placed-but-unused buffers
        self.used_buffers = set()  # Set of buffer instance names we've claimed
        self.netlist_instances = set()  # Set of instance names in the netlist
        self.clock_tree = []  # List of (buffer_instance_name, slot_name, parent, children)
        self.clock_connections = []  # List of (driver, sink) for clock nets
        
        # Clock pin name (standard for sky130 DFFs)
        self.clock_pin = "CLK"
        
        # Netlist modification
        self.mapped_json_data = None
        self.next_net_id = None  # Next available net ID
        self.buffer_net_map = {}  # buffer_instance -> (input_net, output_net)
        self.dff_clock_net_map = {}  # dff_instance -> new_clock_net
        self.netlist_graph = {}  # instance -> [driven_instances] for checking actual usage
        
    def load_placement_map(self, map_file: str) -> None:
        """Load the placement map: instance -> slot_name"""
        print(f"[CTS] Loading placement map from {map_file}...")
        self.placement = {}
        self.reverse_placement = {}
        
        if not os.path.exists(map_file):
            raise FileNotFoundError(f"Placement map not found: {map_file}")
        
        with open(map_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    inst_name = parts[0]
                    slot_name = parts[1]
                    self.placement[inst_name] = slot_name
                    self.reverse_placement[slot_name] = inst_name
        
        print(f"[CTS] Loaded {len(self.placement)} placed instances")
    
    def load_logical_db(self, logical_db_file: str) -> None:
        """Load the logical database to identify DFFs and their clock pins"""
        print(f"[CTS] Loading logical database from {logical_db_file}...")
        
        if not os.path.exists(logical_db_file):
            raise FileNotFoundError(f"Logical DB not found: {logical_db_file}")
        
        with open(logical_db_file, 'r') as f:
            self.logical_db = json.load(f)
        
        # Find all DFF instances
        self.dff_instances = []
        instances = self.logical_db.get("instances", {})
        
        for inst_name, inst_data in instances.items():
            # Check if it's a sequential cell by type name or attrs
            cell_type = inst_data.get("type", "").lower()
            attrs = inst_data.get("attrs", {})
            # Check for DFF variants: dff, dfx, dlat, sdff, dfbbp, etc.
            is_sequential = (attrs.get("is_seq", False) or 
                           any(k in cell_type for k in ("dff", "dfx", "dlat", "sdff", "flop", "ff_", "_ff", "dfbb", "dfrb", "dfrt")))
            
            if is_sequential:
                # Check if it has a clock pin (try both uppercase and lowercase)
                pins = inst_data.get("pins", {})
                pin_names_lower = {k.lower(): k for k in pins.keys()}
                if "clk" in pin_names_lower:
                    self.dff_instances.append(inst_name)
        
        print(f"[CTS] Found {len(self.dff_instances)} DFF instances")
    
    def load_fabric_db(self, fabric_db_file: str) -> None:
        """Load the fabric database to find buffer slots"""
        print(f"[CTS] Loading fabric database from {fabric_db_file}...")
        
        if not os.path.exists(fabric_db_file):
            raise FileNotFoundError(f"Fabric DB not found: {fabric_db_file}")
        
        with open(fabric_db_file, 'r') as f:
            fabric_data = json.load(f)
        
        # Extract slot information
        self.slot_coords = {}
        self.slot_type = {}
        self.slots_by_type = defaultdict(list)
        self.slot_physical_type = {}  # slot_name -> physical_cell_type
        
        # Fabric DB can be in different formats
        if isinstance(fabric_data, dict):
            # Check if it's the processed format with slots_by_type
            if "slots_by_type" in fabric_data:
                self.slots_by_type = fabric_data["slots_by_type"]
                self.slot_coords = fabric_data.get("slot_coords", {})
                self.slot_type = fabric_data.get("slot_type", {})
                # Try to get physical types if available
                if "fabric_db" in fabric_data:
                    for slot in fabric_data["fabric_db"]:
                        slot_name = slot.get("name")
                        if slot_name:
                            self.slot_physical_type[slot_name] = slot.get("physical_cell_type", "")
            # Or if it's the raw fabric_db.json format (organized by type)
            else:
                # Load ALL slot types to get coordinates, but only track BUF/INV for CTS
                for slot_type, slots in fabric_data.items():
                    if isinstance(slots, list):
                        for slot in slots:
                            if isinstance(slot, dict):
                                slot_name = slot.get("name")
                                if slot_name:
                                    # Always store coordinates for all slots
                                    self.slot_coords[slot_name] = (slot.get("x", 0.0), slot.get("y", 0.0))
                                    self.slot_type[slot_name] = slot_type
                                    # Store physical cell type
                                    self.slot_physical_type[slot_name] = slot.get("physical_cell_type", "")
                                    # Only track BUF/INV for buffer selection
                                    if slot_type in ["BUF", "INV"]:
                                        self.slots_by_type[slot_type].append(slot_name)
        
        print(f"[CTS] Found {len(self.slots_by_type.get('BUF', []))} BUF slots")
        print(f"[CTS] Found {len(self.slots_by_type.get('INV', []))} INV slots")
    
    def find_dff_coordinates(self) -> None:
        """Find the physical coordinates of all placed DFFs"""
        print(f"[CTS] Finding DFF coordinates...")
        self.dff_coords = {}
        
        for dff_inst in self.dff_instances:
            if dff_inst in self.placement:
                slot_name = self.placement[dff_inst]
                if slot_name in self.slot_coords:
                    self.dff_coords[dff_inst] = self.slot_coords[slot_name]
        
        print(f"[CTS] Found coordinates for {len(self.dff_coords)} placed DFFs")
    
    def load_netlist_instances(self, mapped_json_file: str) -> None:
        """Load netlist and extract all instance names, and build netlist graph"""
        print(f"[CTS] Loading netlist instances from {mapped_json_file}...")
        
        if not os.path.exists(mapped_json_file):
            raise FileNotFoundError(f"Mapped JSON not found: {mapped_json_file}")
        
        with open(mapped_json_file, 'r') as f:
            data = json.load(f)
        
        modules = data.get("modules", {})
        if not isinstance(modules, dict) or not modules:
            raise ValueError("Netlist JSON missing 'modules' dictionary")
        
        self.netlist_instances = set()
        self.netlist_graph = {}
        
        # Find top module
        top_module = None
        for module_name, module_data in modules.items():
            attrs = module_data.get("attributes", {})
            top_attr = attrs.get("top")
            if (top_attr == "00000000000000000000000000000001" or 
                top_attr == 1 or 
                top_attr is True or 
                str(top_attr) == "1" or
                (isinstance(top_attr, str) and top_attr.endswith("1"))):
                top_module = module_data
                break
        
        if not top_module:
            top_module = list(modules.values())[0]
        
        cells = top_module.get("cells", {})
        if isinstance(cells, dict):
            self.netlist_instances.update(cells.keys())
        
        # Build netlist graph: driver -> [sinks]
        # This helps identify buffers that don't drive anything (unused)
        net_map = {}  # net_id -> {"driver": instance, "sinks": [instances]}
        
        for cell_name, cell in cells.items():
            connections = cell.get("connections", {})
            port_directions = cell.get("port_directions", {})
            
            for port, bits in connections.items():
                direction = port_directions.get(port)
                if not direction:
                    continue
                
                for bit in (bits if isinstance(bits, list) else [bits]):
                    if not isinstance(bit, int):
                        continue
                    
                    if bit not in net_map:
                        net_map[bit] = {"driver": None, "sinks": []}
                    
                    if direction == "output":
                        net_map[bit]["driver"] = cell_name
                    elif direction == "input":
                        net_map[bit]["sinks"].append(cell_name)
        
        # Build adjacency graph: driver -> [sinks]
        for bit, info in net_map.items():
            driver = info["driver"]
            sinks = info["sinks"]
            
            if driver is None:
                continue
            
            if driver not in self.netlist_graph:
                self.netlist_graph[driver] = []
            self.netlist_graph[driver].extend(sinks)
        
        # Initialize empty arrays for instances that don't drive anything
        for inst in self.netlist_instances:
            if inst not in self.netlist_graph:
                self.netlist_graph[inst] = []
        
        print(f"[CTS] Found {len(self.netlist_instances)} instances in netlist")
        print(f"[CTS] Built netlist graph with {len(self.netlist_graph)} entries")
    
    def find_unused_buffers(self) -> None:
        """Find buffers that are in placement map but NOT actually used in netlist.
        A buffer is considered unused if:
        1. It's not in the netlist at all, OR
        2. It's in the netlist but doesn't drive anything (empty output in graph)
        Always also includes unplaced buffer slots from fabric_db.json."""
        print(f"[CTS] Finding placed-but-unused buffer/inverter instances...")
        self.unused_buffers = []
        
        # Find all buffer/inverter instances in placement map
        # Check if slot name contains "buf" or "inv" (case-insensitive)
        buffer_keywords = ["buf", "inv"]
        
        for inst_name, slot_name in self.placement.items():
            slot_name_lower = slot_name.lower()
            # Check if this is a buffer/inverter slot
            is_buffer_slot = any(keyword in slot_name_lower for keyword in buffer_keywords)
            
            if is_buffer_slot:
                # Check if this instance is NOT in the netlist at all
                if inst_name not in self.netlist_instances:
                    self.unused_buffers.append((inst_name, slot_name))
                # OR check if it's in netlist but doesn't drive anything (unused)
                elif inst_name in self.netlist_graph:
                    driven_instances = self.netlist_graph.get(inst_name, [])
                    if len(driven_instances) == 0:
                        # This buffer is in the netlist but doesn't drive anything - it's unused!
                        self.unused_buffers.append((inst_name, slot_name))
        
        placed_count = len(self.unused_buffers)
        print(f"[CTS] Found {placed_count} placed-but-unused buffer/inverter instances")
        
        # Always also add unplaced buffer slots from fabric_db.json
        print(f"[CTS] Adding unplaced buffer/inverter slots from fabric_db.json...")
        # Get all buffer and inverter slots from fabric
        all_buffer_slots = []
        for buf_type in ["BUF", "INV"]:
            all_buffer_slots.extend(self.slots_by_type.get(buf_type, []))
        
        # Filter to only unplaced slots (not in reverse_placement)
        unplaced_count = 0
        for slot_name in all_buffer_slots:
            if slot_name not in self.reverse_placement:
                # Create a temporary instance name for unplaced slots
                # Format: cts_unplaced_<slot_name>
                inst_name = f"cts_unplaced_{slot_name.replace('__', '_').replace('-', '_')}"
                self.unused_buffers.append((inst_name, slot_name))
                unplaced_count += 1
        
        print(f"[CTS] Added {unplaced_count} unplaced buffer/inverter slots")
        print(f"[CTS] Total available buffers: {len(self.unused_buffers)} ({placed_count} placed-but-unused + {unplaced_count} unplaced)")
    
    def euclidean_distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """Calculate Euclidean distance between two points"""
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
    
    def find_nearest_buffer(self, target_x: float, target_y: float) -> Optional[Tuple[str, str]]:
        """Find the nearest unused buffer instance to the target coordinates
        
        Returns:
            Tuple of (instance_name, slot_name) or None if no buffer available
        """
        best_buffer = None
        min_dist = float('inf')
        
        for inst_name, slot_name in self.unused_buffers:
            if inst_name in self.used_buffers:
                continue
            if slot_name not in self.slot_coords:
                continue
            
            slot_x, slot_y = self.slot_coords[slot_name]
            dist = self.euclidean_distance((target_x, target_y), (slot_x, slot_y))
            
            if dist < min_dist:
                min_dist = dist
                best_buffer = (inst_name, slot_name)
        
        return best_buffer
    
    def geometric_center(self, points: List[Tuple[float, float]]) -> Tuple[float, float]:
        """Calculate the geometric center (centroid) of a list of points"""
        if not points:
            return (0.0, 0.0)
        
        sum_x = sum(p[0] for p in points)
        sum_y = sum(p[1] for p in points)
        n = len(points)
        
        return (sum_x / n, sum_y / n)
    
    def get_sink_coordinate(self, sink: str) -> Optional[Tuple[float, float]]:
        """Get the coordinate of a sink (DFF or buffer)"""
        # Check if it's a DFF
        if sink in self.dff_coords:
            return self.dff_coords[sink]
        
        # Check if it's a buffer we've already placed in clock tree
        for buf_inst, slot_name, _, _ in self.clock_tree:
            if buf_inst == sink:
                if slot_name in self.slot_coords:
                    return self.slot_coords[slot_name]
        
        # Check if it's a buffer already in placement map (for existing buffers)
        if sink in self.placement:
            slot_name = self.placement[sink]
            if slot_name in self.slot_coords:
                return self.slot_coords[slot_name]
        
        return None
    
    def build_htree_recursive(self, sinks: List[str], level: int = 0) -> Optional[str]:
        """
        Recursively build a true H-Tree clock distribution network.
        
        A true H-tree alternates partitioning direction at each level:
        - Even levels (0, 2, 4...): Partition by X-coordinate (left/right split)
        - Odd levels (1, 3, 5...): Partition by Y-coordinate (top/bottom split)
        
        This creates the characteristic H-shape pattern where:
        - Horizontal bars connect vertical branches (at even levels)
        - Vertical bars connect horizontal branches (at odd levels)
        
        Args:
            sinks: List of DFF instance names (or buffer instance names for higher levels)
            level: Current tree level (determines partitioning direction)
        
        Returns:
            The instance name of the buffer at this level, or None if no buffer needed
        """
        if not sinks:
            return None
        
        # Base case: if only one sink, return it directly (no buffer needed)
        if len(sinks) == 1:
            return sinks[0]
        
        # Get coordinates of all sinks
        sink_coords = []
        valid_sinks = []
        for sink in sinks:
            coord = self.get_sink_coordinate(sink)
            if coord:
                sink_coords.append(coord)
                valid_sinks.append(sink)
        
        if not sink_coords:
            return None
        
        # Find geometric center
        center_x, center_y = self.geometric_center(sink_coords)
        
        # Find nearest available buffer
        buffer_info = self.find_nearest_buffer(center_x, center_y)
        
        if buffer_info is None:
            # No buffer available, try to connect sinks directly
            # For now, just return first sink as fallback
            print(f"[CTS] WARNING: No buffer available at level {level} for {len(sinks)} sinks")
            return valid_sinks[0] if valid_sinks else None
        
        # Unpack buffer info
        buffer_inst_name, buffer_slot = buffer_info
        
        # Claim this buffer instance
        self.used_buffers.add(buffer_inst_name)
        
        # TRUE H-TREE: Alternate partitioning direction based on level
        # Even levels (0, 2, 4...): Partition by X (left/right) - creates horizontal H-bar
        # Odd levels (1, 3, 5...): Partition by Y (top/bottom) - creates vertical H-bar
        partition_by_x = (level % 2 == 0)
        
        if partition_by_x:
            # Partition by X-coordinate (left/right split)
            # Sort by x-coordinate and split into left/right groups
            sorted_sinks = sorted(valid_sinks, key=lambda s: self.get_sink_coordinate(s)[0] if self.get_sink_coordinate(s) else 0)
            mid = len(sorted_sinks) // 2
            group1_sinks = sorted_sinks[:mid]      # Left group
            group2_sinks = sorted_sinks[mid:]      # Right group
            partition_dir = "X (left/right)"
        else:
            # Partition by Y-coordinate (top/bottom split)
            # Sort by y-coordinate and split into top/bottom groups
            sorted_sinks = sorted(valid_sinks, key=lambda s: self.get_sink_coordinate(s)[1] if self.get_sink_coordinate(s) else 0)
            mid = len(sorted_sinks) // 2
            group1_sinks = sorted_sinks[:mid]      # Top group (lower Y values)
            group2_sinks = sorted_sinks[mid:]      # Bottom group (higher Y values)
            partition_dir = "Y (top/bottom)"
        
        # Recursively build subtrees for both groups
        subtree1 = self.build_htree_recursive(group1_sinks, level + 1) if group1_sinks else None
        subtree2 = self.build_htree_recursive(group2_sinks, level + 1) if group2_sinks else None
        
        # Record this buffer in the clock tree
        children = []
        if subtree1:
            children.append(subtree1)
        if subtree2:
            children.append(subtree2)
        
        self.clock_tree.append((buffer_inst_name, buffer_slot, None, children))
        
        # Record connections
        if subtree1:
            self.clock_connections.append((buffer_inst_name, subtree1))
        if subtree2:
            self.clock_connections.append((buffer_inst_name, subtree2))
        
        return buffer_inst_name
    
    def build_clock_tree(self) -> None:
        """Build the complete clock tree"""
        print(f"[CTS] Building clock tree for {len(self.dff_coords)} DFFs...")
        
        if not self.dff_coords:
            print("[CTS] WARNING: No DFFs found, skipping clock tree synthesis")
            return
        
        # Get list of DFF instance names
        dff_list = list(self.dff_coords.keys())
        
        # Build H-Tree recursively
        root_buffer = self.build_htree_recursive(dff_list, level=0)
        
        # Connect root buffer to clock input pin
        # Find the clock port from the logical DB
        ports = self.logical_db.get("ports", {})
        clock_port = None
        for port_name, port_data in ports.items():
            if port_name.lower() == "clk" and port_data.get("direction") == "input":
                clock_port = port_name
                break
        
        if clock_port and root_buffer:
            self.clock_connections.append((clock_port, root_buffer))
        elif root_buffer:
            # Fallback: try "clk" as default
            self.clock_connections.append(("clk", root_buffer))
        
        print(f"[CTS] Clock tree built with {len(self.clock_tree)} buffers")
        print(f"[CTS] Used {len(self.used_buffers)} buffer slots")
    
    def update_placement_map(self, output_map_file: str) -> None:
        """Update the placement map with new buffer assignments"""
        print(f"[CTS] Updating placement map...")
        
        # Add buffer placements to the placement map
        for buffer_inst_name, slot_name, _, _ in self.clock_tree:
            self.placement[buffer_inst_name] = slot_name
            self.reverse_placement[slot_name] = buffer_inst_name
        
        # Write updated placement map
        os.makedirs(os.path.dirname(output_map_file), exist_ok=True)
        with open(output_map_file, 'w') as f:
            for inst_name, slot_name in sorted(self.placement.items()):
                f.write(f"{inst_name} {slot_name}\n")
        
        print(f"[CTS] Updated placement map written to {output_map_file}")
        print(f"[CTS] Total instances in map: {len(self.placement)}")
    
    def save_clock_tree_info(self, output_file: str) -> None:
        """Save clock tree information for later netlist generation"""
        print(f"[CTS] Saving clock tree information...")
        
        tree_info = {
            "buffers": [
                {
                    "instance": buf[0],
                    "slot": buf[1],
                    "children": buf[3]
                }
                for buf in self.clock_tree
            ],
            "connections": [
                {
                    "driver": conn[0],
                    "sink": conn[1]
                }
                for conn in self.clock_connections
            ],
            "dff_count": len(self.dff_coords),
            "buffer_count": len(self.clock_tree)
        }
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(tree_info, f, indent=2)
        
        print(f"[CTS] Clock tree info saved to {output_file}")
    
    def load_mapped_json(self, mapped_json_file: str) -> None:
        """Load the original mapped JSON netlist"""
        print(f"[CTS] Loading mapped JSON from {mapped_json_file}...")
        
        if not os.path.exists(mapped_json_file):
            raise FileNotFoundError(f"Mapped JSON not found: {mapped_json_file}")
        
        with open(mapped_json_file, 'r') as f:
            self.mapped_json_data = json.load(f)
        
        # Find the maximum net ID to allocate new ones
        max_net_id = 0
        top_module = None
        
        # Try multiple formats for top module detection
        for module_name, module_data in self.mapped_json_data.get("modules", {}).items():
            attrs = module_data.get("attributes", {})
            top_attr = attrs.get("top")
            # Check for various formats: string "0000...1", integer 1, boolean True, string "1"
            if (top_attr == "00000000000000000000000000000001" or 
                top_attr == 1 or 
                top_attr is True or 
                str(top_attr) == "1" or
                (isinstance(top_attr, str) and top_attr.endswith("1"))):
                top_module = module_data
                break
        
        if not top_module:
            # Fallback: use first module
            top_module = list(self.mapped_json_data.get("modules", {}).values())[0]
        
        # Find max net ID from ports and cells
        for port_data in top_module.get("ports", {}).values():
            for bit in port_data.get("bits", []):
                if isinstance(bit, int) and bit > max_net_id:
                    max_net_id = bit
        
        for cell_data in top_module.get("cells", {}).values():
            for pin_bits in cell_data.get("connections", {}).values():
                for bit in (pin_bits if isinstance(pin_bits, list) else [pin_bits]):
                    if isinstance(bit, int) and bit > max_net_id:
                        max_net_id = bit
        
        self.next_net_id = max_net_id + 1
        print(f"[CTS] Next available net ID: {self.next_net_id}")
    
    def get_buffer_cell_type(self, slot_name: str) -> str:
        """Determine the buffer cell type from the slot"""
        # First try to get physical cell type from fabric DB
        physical_type = self.slot_physical_type.get(slot_name, "")
        if physical_type:
            return physical_type
        
        # Fallback: use slot type to infer
        slot_type = self.slot_type.get(slot_name, "")
        if slot_type == "BUF":
            return "sky130_fd_sc_hd__clkbuf_4"  # Default clock buffer
        elif slot_type == "INV":
            return "sky130_fd_sc_hd__clkinv_2"  # Default clock inverter
        else:
            # Last resort: default buffer
            return "sky130_fd_sc_hd__clkbuf_4"
    
    def get_buffer_pin_names(self, cell_type: str) -> tuple:
        """Get input and output pin names for a buffer cell"""
        if "inv" in cell_type.lower():
            return ("A", "Y")  # Input A, Output Y
        else:
            return ("A", "X")  # Input A, Output X (for buffers)
    
    def update_netlist_connections(self, mapped_json_file: str, output_json_file: str) -> None:
        """Update the netlist to add buffer instances and wire the clock tree"""
        print(f"[CTS] Updating netlist connections...")
        
        if not self.mapped_json_data:
            self.load_mapped_json(mapped_json_file)
        
        # Get top module
        top_module = None
        top_module_name = None
        
        # Try multiple formats for top module detection
        for module_name, module_data in self.mapped_json_data.get("modules", {}).items():
            attrs = module_data.get("attributes", {})
            top_attr = attrs.get("top")
            # Check for various formats: string "0000...1", integer 1, boolean True, string "1"
            if (top_attr == "00000000000000000000000000000001" or 
                top_attr == 1 or 
                top_attr is True or 
                str(top_attr) == "1" or
                (isinstance(top_attr, str) and top_attr.endswith("1"))):
                top_module = module_data
                top_module_name = module_name
                break
        
        if not top_module:
            top_module_name = list(self.mapped_json_data.get("modules", {}).keys())[0]
            top_module = self.mapped_json_data["modules"][top_module_name]
        
        cells = top_module.get("cells", {})
        
        # Get original clock net ID
        clock_port = None
        clock_net_id = None
        ports = top_module.get("ports", {})
        for port_name, port_data in ports.items():
            if port_name.lower() == "clk" and port_data.get("direction") == "input":
                clock_port = port_name
                clock_net_id = port_data.get("bits", [None])[0]
                break
        
        if clock_net_id is None:
            print("[CTS] WARNING: Could not find clock port, using net ID 2 as default")
            clock_net_id = 2
        
        # Map buffer instances to their nets
        # Each buffer needs: input_net and output_net
        buffer_net_map = {}  # buffer_instance -> (input_net, output_net)
        
        # Process clock tree connections to assign nets
        # Start from root and work down
        connection_map = {}  # sink -> driver (for finding what drives each sink)
        for driver, sink in self.clock_connections:
            connection_map[sink] = driver
        
        # Assign nets to each buffer
        for buffer_inst, slot_name, _, children in self.clock_tree:
            # Find what drives this buffer
            driver = connection_map.get(buffer_inst)
            
            if driver == clock_port or driver == "clk":
                # Root buffer: input is clock net
                input_net = clock_net_id
            elif driver in buffer_net_map:
                # Driven by another buffer: use that buffer's output net
                input_net = buffer_net_map[driver][1]
            else:
                # Shouldn't happen, but create new net
                input_net = self.next_net_id
                self.next_net_id += 1
            
            # Output net is new
            output_net = self.next_net_id
            self.next_net_id += 1
            
            buffer_net_map[buffer_inst] = (input_net, output_net)
        
        # Map DFFs and buffer children to their new clock nets
        # DFFs and buffer children are connected to their parent buffer's output
        dff_clock_net_map = {}
        buffer_child_net_map = {}  # buffer_instance -> input_net (from parent)
        buffer_instances_set = {buf[0] for buf in self.clock_tree}
        
        for buffer_inst, slot_name, _, children in self.clock_tree:
            output_net = buffer_net_map[buffer_inst][1]
            for child in children:
                # Check if child is a DFF (not a buffer)
                # Primary check: is it in our DFF instances list?
                if child in self.dff_instances:
                    # This is a DFF - connect its clock to this buffer's output
                    dff_clock_net_map[child] = output_net
                elif child in buffer_instances_set:
                    # This is another buffer - connect its input to this buffer's output
                    buffer_child_net_map[child] = output_net
                elif child not in buffer_instances_set:
                    # Not a buffer and not in DFF list, but might be a DFF with different naming
                    # Use naming heuristics as fallback (but less reliable)
                    if child.startswith("$") or "slice" in child:
                        dff_clock_net_map[child] = output_net
        
        # Also handle DFFs that might be returned directly from base case
        # (single sink case - though rare, ensure they get clock nets)
        for dff_inst in self.dff_instances:
            if dff_inst not in dff_clock_net_map:
                # Find which buffer drives this DFF by checking connections
                for driver, sink in self.clock_connections:
                    if sink == dff_inst and driver in buffer_net_map:
                        dff_clock_net_map[dff_inst] = buffer_net_map[driver][1]
                        break
        
        # Update buffer input nets if they're driven by parent buffers
        for buffer_inst, input_net in buffer_child_net_map.items():
            if buffer_inst in buffer_net_map:
                # Update the input net to use parent's output
                old_input, old_output = buffer_net_map[buffer_inst]
                buffer_net_map[buffer_inst] = (input_net, old_output)
        
        # Add buffer cells to the netlist
        # These buffers are placed but not in the netlist, so we add them now
        for buffer_inst, slot_name, _, children in self.clock_tree:
            # Check if buffer already exists (shouldn't happen, but be safe)
            if buffer_inst in cells:
                print(f"[CTS] WARNING: Buffer {buffer_inst} already exists in netlist, updating connections")
                # Update existing cell connections
                cell = cells[buffer_inst]
                cell_type = cell.get("type") or self.get_buffer_cell_type(slot_name)
                input_pin, output_pin = self.get_buffer_pin_names(cell_type)
                input_net, output_net = buffer_net_map[buffer_inst]
                
                # Update connections - clear old connections first
                connections = cell.get("connections", {})
                port_directions = cell.get("port_directions", {})
                
                # Remove any old output pin connections (e.g., 'Y' if we're using 'X')
                for pin in list(connections.keys()):
                    if pin != input_pin and port_directions.get(pin) == "output":
                        # Remove old output pin connections
                        del connections[pin]
                        if pin in port_directions:
                            del port_directions[pin]
                
                # Set new connections
                connections[input_pin] = [input_net]
                connections[output_pin] = [output_net]
                
                # Update port directions to match
                port_directions[input_pin] = "input"
                port_directions[output_pin] = "output"
            else:
                # Create new cell instance (normal case - buffer is placed but not in netlist)
                cell_type = self.get_buffer_cell_type(slot_name)
                input_pin, output_pin = self.get_buffer_pin_names(cell_type)
                input_net, output_net = buffer_net_map[buffer_inst]
                
                # Determine port directions
                port_directions = {input_pin: "input", output_pin: "output"}
                
                # Create cell instance
                cells[buffer_inst] = {
                    "hide_name": 0,
                    "type": cell_type,
                    "parameters": {},
                    "attributes": {},
                    "port_directions": port_directions,
                    "connections": {
                        input_pin: [input_net],
                        output_pin: [output_net]
                    }
                }
        
        # Update DFF clock pin connections
        dffs_updated = 0
        for dff_inst in self.dff_instances:
            if dff_inst in cells and dff_inst in dff_clock_net_map:
                cell = cells[dff_inst]
                connections = cell.get("connections", {})
                
                # Find clock pin (try CLK, clk, etc.)
                clock_pin = None
                for pin_name in connections.keys():
                    if pin_name.upper() == "CLK" or pin_name.lower() == "clk":
                        clock_pin = pin_name
                        break
                
                if clock_pin:
                    # Update clock pin to new net
                    new_clock_net = dff_clock_net_map[dff_inst]
                    connections[clock_pin] = [new_clock_net]
                    dffs_updated += 1
        
        print(f"[CTS] Added {len(self.clock_tree)} buffer instances to netlist")
        print(f"[CTS] Updated {dffs_updated} DFF clock connections")
        
        # Update netnames section to include new clock tree nets
        netnames = top_module.get("netnames", {})
        nets_updated = 0
        
        # Add netnames for all new clock tree nets
        all_new_nets = set()
        for input_net, output_net in buffer_net_map.values():
            all_new_nets.add(input_net)
            all_new_nets.add(output_net)
        
        # Remove original clock net from netnames if it's no longer used
        # (Actually, keep it since clock port still uses it, but mark it differently if needed)
        
        # Add new nets to netnames
        for net_id in all_new_nets:
            net_id_str = str(net_id)
            if net_id_str not in netnames:
                netnames[net_id_str] = {
                    "hide_name": 1,  # Hide auto-generated net names
                    "bits": [net_id],
                    "attributes": {"is_clock_tree": True}
                }
                nets_updated += 1
        
        print(f"[CTS] Updated {nets_updated} netnames for clock tree nets")
        
        # Write updated netlist
        os.makedirs(os.path.dirname(output_json_file), exist_ok=True)
        with open(output_json_file, 'w') as f:
            json.dump(self.mapped_json_data, f, indent=2)
        
        print(f"[CTS] Updated netlist written to {output_json_file}")
    
    def regenerate_netlist_graph(self, cts_json_file: str, output_graph_file: str) -> None:
        """Regenerate netlist graph from CTS netlist"""
        print(f"[CTS] Regenerating netlist graph...")
        
        if not os.path.exists(cts_json_file):
            print(f"[CTS] WARNING: CTS JSON not found, skipping graph regeneration")
            return
        
        with open(cts_json_file, 'r') as f:
            data = json.load(f)
        
        # Find top module
        top_module = None
        for module_name, module_data in data.get("modules", {}).items():
            attrs = module_data.get("attributes", {})
            top_attr = attrs.get("top")
            if (top_attr == "00000000000000000000000000000001" or 
                top_attr == 1 or 
                top_attr is True or 
                str(top_attr) == "1" or
                (isinstance(top_attr, str) and top_attr.endswith("1"))):
                top_module = module_data
                break
        
        if not top_module:
            top_module = list(data.get("modules", {}).values())[0]
        
        cells = top_module.get("cells", {})
        
        # Build: net_bit → { "driver": cell_name, "sinks": [cell1, cell2...] }
        net_map = {}
        
        for cell_name, cell in cells.items():
            connections = cell.get("connections", {})
            port_directions = cell.get("port_directions", {})
            
            for port, bits in connections.items():
                direction = port_directions.get(port)
                if not direction:
                    continue
                
                for bit in (bits if isinstance(bits, list) else [bits]):
                    if not isinstance(bit, int):
                        continue
                    
                    if bit not in net_map:
                        net_map[bit] = {"driver": None, "sinks": []}
                    
                    if direction == "output":
                        net_map[bit]["driver"] = cell_name
                    elif direction == "input":
                        net_map[bit]["sinks"].append(cell_name)
        
        # Build adjacency: driver -> sinks
        netlist_graph = {}
        
        for bit, info in net_map.items():
            driver = info["driver"]
            sinks = info["sinks"]
            
            if driver is None:
                continue
            
            if driver not in netlist_graph:
                netlist_graph[driver] = []
            netlist_graph[driver].extend(sinks)
        
        # Initialize empty arrays for instances that don't drive anything
        for cell_name in cells.keys():
            if cell_name not in netlist_graph:
                netlist_graph[cell_name] = []
        
        # Write JSON output
        os.makedirs(os.path.dirname(output_graph_file), exist_ok=True)
        with open(output_graph_file, 'w') as f:
            json.dump(netlist_graph, f, indent=4)
        
        print(f"[CTS] Netlist graph regenerated: {output_graph_file}")
        print(f"[CTS] Graph contains {len(netlist_graph)} instances")
    
    def run(self, map_file: str, logical_db_file: str, fabric_db_file: str, 
            output_map_file: str, cts_info_file: str, 
            mapped_json_file: str = None, output_json_file: str = None) -> None:
        """Run the complete CTS flow"""
        print(f"\n{'='*60}")
        print(f"Clock Tree Synthesis for {self.design_name}")
        print(f"{'='*60}\n")
        
        # Load data
        self.load_placement_map(map_file)
        self.load_logical_db(logical_db_file)
        self.load_fabric_db(fabric_db_file)
        
        # Load netlist instances to identify unused buffers
        if mapped_json_file:
            self.load_netlist_instances(mapped_json_file)
        else:
            raise ValueError("mapped_json_file is required to identify placed-but-unused buffers")
        
        # Find DFFs and buffers
        self.find_dff_coordinates()
        self.find_unused_buffers()
        
        # Build clock tree
        self.build_clock_tree()
        
        # Update placement map
        self.update_placement_map(output_map_file)
        
        # Update netlist connections if mapped JSON is provided
        if mapped_json_file and output_json_file:
            self.update_netlist_connections(mapped_json_file, output_json_file)
        
        # Save clock tree info
        self.save_clock_tree_info(cts_info_file)
        
        # Regenerate netlist graph from CTS netlist
        if output_json_file:
            graph_output_file = os.path.join(os.path.dirname(output_json_file), 
                                             f"{self.design_name}_cts_mapped_netlist_graph.json")
            self.regenerate_netlist_graph(output_json_file, graph_output_file)
        
        print(f"\n{'='*60}")
        print(f"CTS Complete!")
        print(f"  DFFs: {len(self.dff_coords)}")
        print(f"  Buffers used: {len(self.clock_tree)}")
        print(f"  Connections: {len(self.clock_connections)}")
        print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Clock Tree Synthesis (CTS) for Structured ASIC Platform"
    )
    parser.add_argument(
        "--design",
        required=True,
        help="Design name (e.g., 6502)"
    )
    parser.add_argument(
        "--map",
        help="Input placement map file (default: build/<design>/<design>.map)"
    )
    parser.add_argument(
        "--logical-db",
        help="Logical database file (default: build/<design>/<design>_logical_db.json)"
    )
    parser.add_argument(
        "--fabric-db",
        help="Fabric database file (default: build/fabric/fabric_db.json)"
    )
    parser.add_argument(
        "--output-map",
        help="Output placement map file (default: build/<design>/<design>_cts.map)"
    )
    parser.add_argument(
        "--cts-info",
        help="Output CTS info file (default: build/<design>/<design>_cts.json)"
    )
    parser.add_argument(
        "--mapped-json",
        help="Input mapped JSON file (default: designs/<design>_mapped.json)"
    )
    parser.add_argument(
        "--output-json",
        help="Output updated JSON file (default: build/<design>/<design>_cts_mapped.json)"
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
    
    # Set default paths
    map_file = args.map or os.path.join(build_dir, design_name, f"{design_name}.map")
    logical_db_file = args.logical_db or os.path.join(build_dir, design_name, f"{design_name}_logical_db.json")
    fabric_db_file = args.fabric_db or os.path.join(build_dir, "fabric", "fabric_db.json")
    output_map_file = args.output_map or os.path.join(build_dir, design_name, f"{design_name}_cts.map")
    cts_info_file = args.cts_info or os.path.join(build_dir, design_name, f"{design_name}_cts.json")
    mapped_json_file = args.mapped_json or os.path.join(args.designs_dir, f"{design_name}_mapped.json")
    output_json_file = args.output_json or os.path.join(build_dir, design_name, f"{design_name}_cts_mapped.json")
    
    # Create CTS object and run
    cts = ClockTreeSynthesis(design_name, build_dir)
    cts.run(map_file, logical_db_file, fabric_db_file, output_map_file, cts_info_file,
            mapped_json_file, output_json_file)


if __name__ == "__main__":
    main()

