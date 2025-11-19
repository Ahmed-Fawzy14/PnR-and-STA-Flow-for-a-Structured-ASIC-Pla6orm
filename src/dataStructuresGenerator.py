import json
from collections import defaultdict

def get_macro_type(full_name):
    """
    Extracts the logical type from a full Sky130 physical name.
    Example: 'sky130_fd_sc_hd__nand2_2' -> 'NAND2'
             'sky130_fd_sc_hd__tapvpwrvgnd_1' -> 'TAP'
    """
    if not full_name:
        return "UNKNOWN"
    
    # Standard sky130 naming convention usually separates lib and cell by double underscore
    parts = full_name.split('__')
    if len(parts) < 2:
        return full_name # Fallback
    
    cell_part = parts[-1] # e.g. 'nand2_2'
    
    # Remove size suffix (e.g., '_1', '_2', '_4')
    # Find the last underscore and see if the suffix is a number
    subparts = cell_part.rsplit('_', 1)
    if len(subparts) == 2 and subparts[1].isdigit():
        base_name = subparts[0]
    else:
        base_name = cell_part
        
    return base_name.upper()

def build_data_structures(netlist_graph_path, logical_db_path, fabric_cells_path):
    print(f"Loading {netlist_graph_path}...")
    with open(netlist_graph_path, 'r') as f:
        raw_netlist_graph = json.load(f)

    print(f"Loading {logical_db_path}...")
    with open(logical_db_path, 'r') as f:
        raw_logical_json = json.load(f)

    print(f"Loading {fabric_cells_path}...")
    with open(fabric_cells_path, 'r') as f:
        raw_fabric_json = json.load(f)

    # ==========================================
    # 1. Logical Netlist Structures
    # ==========================================
    
    # 1.1 logical_db
    # Spec implies logical_db is the dictionary of instances
    logical_db = raw_logical_json.get("instances", {})
    
    # 1.2 netlist_graph
    # Directly loaded from file
    netlist_graph = raw_netlist_graph

    # ==========================================
    # 2. Fabric Structures
    # ==========================================
    
    fabric_db = []
    slot_coords = {}
    slot_type = {}
    slots_by_type = defaultdict(list)
    
    # Iterate over tiles to flatten cells into fabric_db
    for tile in raw_fabric_json.get("tiles", []):
        tile_name = tile.get("name")
        
        for cell in tile.get("cells", []):
            # Derive logical type (e.g. "BUF" from "sky130...buf_1")
            phys_type = cell.get("physical_cell_type", "")
            logic_type = get_macro_type(phys_type)
            
            # Create slot record
            slot_record = {
                "name": cell["name"],
                "type": logic_type,
                "x": cell["x"],
                "y": cell["y"],
                "orient": cell.get("orient", "N"),
                "tile": tile_name,
                "width_sites": cell.get("width_sites", 1),
                "physical_cell_type": phys_type
            }
            
            # 2.1 fabric_db
            fabric_db.append(slot_record)
            
            # 2.2 slot_coords
            slot_coords[cell["name"]] = (cell["x"], cell["y"])
            
            # 2.3 slot_type
            slot_type[cell["name"]] = logic_type
            
            # 2.4 slots_by_type
            slots_by_type[logic_type].append(cell["name"])

    # ==========================================
    # 3. Derived Netlist Structures
    # ==========================================

    cell_type = {}
    inst_to_nets = {}
    net_to_pins = defaultdict(list)

    # Process Instances
    for inst_name, inst_data in logical_db.items():
        # 3.1 cell_type
        # Normalize the instance type (e.g. sky130...nand2 -> NAND2)
        c_type = get_macro_type(inst_data.get("type", ""))
        cell_type[inst_name] = c_type
        
        # 3.2 inst_to_nets
        # Collect all unique net IDs connected to this instance
        # Pins dict structure: "A": [124], "B": [125]
        connected_nets = set()
        pins = inst_data.get("pins", {})
        
        for pin_name, net_list in pins.items():
            for net_id in net_list:
                connected_nets.add(net_id)
                
                # 3.3 net_to_pins (Instance side)
                # Add (instance_name, pin_name) to the net's list
                net_to_pins[net_id].append((inst_name, pin_name))
        
        inst_to_nets[inst_name] = connected_nets

    # Process Ports (Top-level I/O) for net_to_pins
    # The spec example shows ("pin_GPIO0", None) for ports
    ports = raw_logical_json.get("ports", {})
    for port_name, port_data in ports.items():
        # port_data["bits"] contains the net IDs connected to this port
        for net_id in port_data.get("bits", []):
            # Using port name directly. If 'pin_' prefix is strictly required 
            # by your downstream tools, change `port_name` to `f"pin_{port_name}"`
            net_to_pins[net_id].append((port_name, None))

    # ==========================================
    # 4. Pin Structures
    # ==========================================
    
    pin_coords = {}
    
    # Loaded from fabric_cells.db "pins" list
    fabric_pins = raw_fabric_json.get("pins", [])
    for pin in fabric_pins:
        p_name = pin["name"]
        # 4.1 pin_coords
        pin_coords[p_name] = (pin.get("x_um", 0.0), pin.get("y_um", 0.0))

    return {
        "logical_db": logical_db,
        "netlist_graph": netlist_graph,
        "fabric_db": fabric_db,
        "slot_coords": slot_coords,
        "slot_type": slot_type,
        "slots_by_type": dict(slots_by_type),
        "cell_type": cell_type,
        "inst_to_nets": inst_to_nets,
        "net_to_pins": dict(net_to_pins),
        "pin_coords": pin_coords
    }

# ==========================================
# Example Execution
# ==========================================
if __name__ == "__main__":
    # Update these paths to point to your actual files
    NETLIST_GRAPH_FILE = "6502_mapped_netlist_graph.json"
    LOGICAL_DB_FILE = "6502_logical_db.json"
    FABRIC_CELLS_FILE = "fabric_cells.json"

    def print_sample(name, obj, limit=50):
        """Helper to print the first 'limit' items of a structure."""
        print(f"\n{'='*25} {name} (First {limit}) {'='*25}")
        
        if isinstance(obj, list):
            # Print first 'limit' items
            for i, item in enumerate(obj[:limit]):
                print(f"[{i}] {item}")
            if len(obj) > limit:
                print(f"... and {len(obj) - limit} more items.")
        
        elif isinstance(obj, dict):
            # Print first 'limit' keys
            keys = list(obj.keys())[:limit]
            for k in keys:
                val = obj[k]
                # Convert sets to lists for display so they print clearly
                if isinstance(val, set):
                    val = list(val)
                print(f"{k}: {val}")
            if len(obj) > limit:
                print(f"... and {len(obj) - limit} more items.")
        else:
            print(f"Type {type(obj)} not supported for sampling.")

    try:
        data = build_data_structures(NETLIST_GRAPH_FILE, LOGICAL_DB_FILE, FABRIC_CELLS_FILE)
        
        print("\n--- Data Loaded Successfully ---")
        
        # List of keys corresponding to headers 1-4 in the spec
        keys_to_validate = [
            "logical_db",
            "netlist_graph",
            "fabric_db",
            "slot_coords",
            "slot_type",
            "slots_by_type",
            "cell_type",
            "inst_to_nets",
            "net_to_pins",
            "pin_coords"
        ]
        
        for key in keys_to_validate:
            if key in data and key != "slots_by_type":
                print_sample(key, data[key], limit=10)
            else:
                print(f"\nWARNING: Key '{key}' not found in returned data.")

    except FileNotFoundError as e:
        print(f"Error: {e}. Please ensure your JSON files are in the correct path.")
    except Exception as e:
        print(f"An error occurred: {e}")