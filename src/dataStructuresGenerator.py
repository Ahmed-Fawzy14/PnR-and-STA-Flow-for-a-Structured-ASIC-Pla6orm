# generate_db.py
import json
import argparse
import sys
from collections import defaultdict

def get_macro_type(full_name):
    """Extracts the logical type from a full Sky130 physical name."""
    if not full_name: return "UNKNOWN"
    parts = full_name.split('__')
    if len(parts) < 2: return full_name
    cell_part = parts[-1]
    subparts = cell_part.rsplit('_', 1)
    if len(subparts) == 2 and subparts[1].isdigit():
        base_name = subparts[0]
    else:
        base_name = cell_part
    return base_name.upper()

def build_and_save_structures(netlist_graph_path, logical_db_path, fabric_cells_path, output_json_path):
    print(f"Loading raw files...")
    try:
        with open(netlist_graph_path, 'r') as f: raw_netlist_graph = json.load(f)
        with open(logical_db_path, 'r') as f: raw_logical_json = json.load(f)
        with open(fabric_cells_path, 'r') as f: raw_fabric_json = json.load(f)
    except FileNotFoundError as e:
        print(f"Error loading files: {e}")
        sys.exit(1)

    logical_db = raw_logical_json.get("instances", {})
    netlist_graph = raw_netlist_graph

    fabric_db = []
    slot_coords = {}
    slot_type = {}
    slots_by_type = defaultdict(list)

    # Process Fabric
    for tile in raw_fabric_json.get("tiles", []):
        tile_name = tile.get("name")
        for cell in tile.get("cells", []):
            phys_type = cell.get("physical_cell_type", "")
            logic_type = get_macro_type(phys_type)
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
            fabric_db.append(slot_record)
            slot_coords[cell["name"]] = (cell["x"], cell["y"])
            slot_type[cell["name"]] = logic_type
            slots_by_type[logic_type].append(cell["name"])

    cell_type = {}
    inst_to_nets = {}
    net_to_pins = defaultdict(list)

    # Process Logical Instances
    for inst_name, inst_data in logical_db.items():
        c_type = get_macro_type(inst_data.get("type", ""))
        cell_type[inst_name] = c_type
        
        connected_nets = set()
        pins = inst_data.get("pins", {})
        
        for pin_name, net_list in pins.items():
            for net_id in net_list:
                connected_nets.add(net_id)
                net_to_pins[net_id].append((inst_name, pin_name))
        
        inst_to_nets[inst_name] = connected_nets

    # Process Ports
    ports = raw_logical_json.get("ports", {})
    for port_name, port_data in ports.items():
        for net_id in port_data.get("bits", []):
            net_to_pins[net_id].append((port_name, None))

    pin_coords = {}
    fabric_pins = raw_fabric_json.get("pins", [])
    for pin in fabric_pins:
        pin_coords[pin["name"]] = (pin.get("x_um", 0.0), pin.get("y_um", 0.0))

    # --- PREPARE FOR JSON EXPORT ---
    serializable_inst_to_nets = {k: list(v) for k, v in inst_to_nets.items()}

    final_data = {
        "logical_db": logical_db,
        "netlist_graph": netlist_graph,
        "fabric_db": fabric_db,
        "slot_coords": slot_coords,
        "slot_type": slot_type,
        "slots_by_type": dict(slots_by_type),
        "cell_type": cell_type,
        "inst_to_nets": serializable_inst_to_nets,
        "net_to_pins": dict(net_to_pins),
        "pin_coords": pin_coords
    }

    print(f"Saving processed data to {output_json_path}...")
    with open(output_json_path, 'w') as f:
        json.dump(final_data, f, indent=2)
    print("Done.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compile raw design files into a single processed JSON.")
    
    parser.add_argument("--netlist", required=True, help="Path to mapped_netlist_graph.json")
    parser.add_argument("--logical", required=True, help="Path to logical_db.json")
    parser.add_argument("--fabric", required=True, help="Path to fabric_cells.json")
    parser.add_argument("--output", required=True, help="Path for the output .json file")

    args = parser.parse_args()

    build_and_save_structures(args.netlist, args.logical, args.fabric, args.output)
