# greedyPlacer.py
import math
import sys
import os
import heapq
import json
import argparse
from collections import defaultdict


class GreedyPlacer:
    def __init__(self, design_name, processed_json_path):
        self.design_name = design_name

        print(f"[{design_name}] Loading pre-compiled structures from {processed_json_path}...")

        try:
            with open(processed_json_path, 'r') as f:
                self.data = json.load(f)
        except FileNotFoundError:
            print(f"Error: Could not find data file: {processed_json_path}")
            sys.exit(1)

        # Unpack structures
        if "logical_db" in self.data:
            self.logical_db = self.data["logical_db"]
            self.fabric_db = self.data["fabric_db"]
            self.slot_coords = self.data["slot_coords"]
            self.slot_type = self.data["slot_type"]
            self.slots_by_type = self.data["slots_by_type"]
            self.cell_type = self.data["cell_type"]
            self.net_to_pins = self.data["net_to_pins"]
            self.pin_coords = self.data["pin_coords"]

            # RECONSTRUCT SETS from Lists
            self.inst_to_nets = {k: set(v) for k, v in self.data["inst_to_nets"].items()}
        else:
            self._normalize_data()

        # Initialize State
        self.placement = {}  # instance_name -> slot_name
        self.occupied_slots = set()
        self.unplaced_instances = set(self.logical_db.keys())

    def _normalize_data(self):
        print("Adapting data structure from new format...")
        self.logical_db = self.data["logical"]["instances"]

        # Fabric
        self.slot_coords = {}
        self.slot_type = {}
        for name, info in self.data["fabric"]["slot_info"].items():
            self.slot_coords[name] = (info["x"], info["y"])
            self.slot_type[name] = info["physical_cell_type"]

        self.slots_by_type = self.data["fabric"]["slots_by_phys_type"]
        self.cell_type = self.data["logical"]["cell_type"]

        # Nets
        self.net_to_pins = {}
        self.inst_to_nets = defaultdict(set)

        net_graph = self.data["nets"].get("net_graph", {})
        for net_id, info in net_graph.items():
            pins = []
            # Drivers
            for inst, pin in info.get("drivers", []):
                pins.append((inst, pin))
                self.inst_to_nets[inst].add(net_id)
            # Sinks
            for inst, pin in info.get("sinks", []):
                pins.append((inst, pin))
                self.inst_to_nets[inst].add(net_id)

            self.net_to_pins[net_id] = pins

        # Pin Coords - Missing in new format, defaulting to empty
        self.pin_coords = {}

    def get_distance(self, x1, y1, x2, y2):
        return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    def find_nearest_slot(self, target_x, target_y, required_type):
        best_slot = None
        min_dist = float('inf')

        candidate_slots = self.slots_by_type.get(required_type, [])

        for slot_name in candidate_slots:
            if slot_name in self.occupied_slots:
                continue

            sx, sy = self.slot_coords[slot_name]
            dist = self.get_distance(target_x, target_y, sx, sy)

            if dist < min_dist:
                min_dist = dist
                best_slot = slot_name

        return best_slot

    def place_instance(self, inst_name, target_x, target_y):
        c_type = self.cell_type[inst_name]
        slot = self.find_nearest_slot(target_x, target_y, c_type)

        if slot:
            self.placement[inst_name] = slot
            self.occupied_slots.add(slot)
            self.unplaced_instances.remove(inst_name)
            return True
        else:
            print(f"WARNING: No '{c_type}' slots for {inst_name}")
            return False

    def run_seed_placement(self, callback=None):
        """Phase 1: Place cells connected to I/Os."""
        print("Running Seed Placement (I/O Driven)...")
        count = 0

        io_nets = {}

        # Identify nets connected to pins
        for net_id, pins_on_net in self.net_to_pins.items():
            io_locs = []
            for (name, pin_type) in pins_on_net:
                if name in self.pin_coords:
                    io_locs.append(self.pin_coords[name])

            if io_locs:
                io_nets[net_id] = io_locs

        seed_candidates = []

        for inst_name in list(self.unplaced_instances):
            connected_nets = self.inst_to_nets.get(inst_name, set())
            connected_io_locs = []
            for net_id in connected_nets:
                # Handle potential int/string mismatch from JSON
                if str(net_id) in io_nets:
                    connected_io_locs.extend(io_nets[str(net_id)])
                elif net_id in io_nets:
                    connected_io_locs.extend(io_nets[net_id])

            if connected_io_locs:
                avg_x = sum(x for x, y in connected_io_locs) / len(connected_io_locs)
                avg_y = sum(y for x, y in connected_io_locs) / len(connected_io_locs)
                seed_candidates.append((inst_name, avg_x, avg_y))

        for inst_name, x, y in seed_candidates:
            if inst_name in self.unplaced_instances:
                if self.place_instance(inst_name, x, y):
                    count += 1
                    if callback:
                        callback(self)

        print(f"  -> Placed {count} seed instances.")

    def run_grow_placement(self, callback=None):
        """Phase 2: Place remaining cells based on connectivity."""
        print("Running Grow Placement (Connectivity Driven)...")

        connectivity_scores = defaultdict(int)
        pq = []

        # Init scores based on seeds
        for placed_inst in self.placement.keys():
            self._update_neighbors(placed_inst, connectivity_scores, pq)

        count = 0
        while self.unplaced_instances:
            best_inst = None

            while pq:
                score, inst = heapq.heappop(pq)
                score = -score

                if inst not in self.unplaced_instances: continue
                if score < connectivity_scores[inst]: continue

                best_inst = inst
                break

            if best_inst is None:
                best_inst = list(self.unplaced_instances)[0]

            target_x, target_y = self._calculate_barycenter(best_inst)

            if self.place_instance(best_inst, target_x, target_y):
                count += 1
                self._update_neighbors(best_inst, connectivity_scores, pq)
                if callback:
                    callback(self)
            else:
                self.unplaced_instances.remove(best_inst)

            if count % 500 == 0:
                sys.stdout.write(f"\r  -> Placed {count} instances...")
                sys.stdout.flush()

        print(f"\n  -> Grow phase complete. Total placed: {len(self.placement)}")

    def _update_neighbors(self, placed_inst, scores, pq):
        nets = self.inst_to_nets.get(placed_inst, set())
        for net_id in nets:
            pins = self.net_to_pins.get(str(net_id)) or self.net_to_pins.get(net_id) or []

            for (neighbor_name, _) in pins:
                if neighbor_name in self.unplaced_instances:
                    scores[neighbor_name] += 1
                    heapq.heappush(pq, (-scores[neighbor_name], neighbor_name))

    def _calculate_barycenter(self, inst_name):
        nets = self.inst_to_nets.get(inst_name, set())
        neighbor_coords = []

        for net_id in nets:
            pins = self.net_to_pins.get(str(net_id)) or self.net_to_pins.get(net_id) or []

            for (neighbor, _) in pins:
                if neighbor in self.placement:
                    slot = self.placement[neighbor]
                    neighbor_coords.append(self.slot_coords[slot])
                elif neighbor in self.pin_coords:
                    neighbor_coords.append(self.pin_coords[neighbor])

        if not neighbor_coords:
            all_x = [c[0] for c in self.slot_coords.values()]
            all_y = [c[1] for c in self.slot_coords.values()]
            return (min(all_x) + max(all_x)) / 2, (min(all_y) + max(all_y)) / 2

        avg_x = sum(x for x, y in neighbor_coords) / len(neighbor_coords)
        avg_y = sum(y for x, y in neighbor_coords) / len(neighbor_coords)
        return avg_x, avg_y

    def write_map_file(self, output_file_path):
        """Writes the placement map to the specific file path provided."""

        # Ensure the directory exists (extract dir from file path)
        output_dir = os.path.dirname(output_file_path)

        # If output_dir is empty string, it means current directory, so we skip makedirs
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except OSError as e:
                print(f"Error creating directory {output_dir}: {e}")
                return

        print(f"Writing output to {output_file_path}...")
        try:
            with open(output_file_path, "w") as f:
                for inst, slot in self.placement.items():
                    f.write(f"{inst} {slot}\n")
            print("Done.")
        except IOError as e:
            print(f"Error writing to file {output_file_path}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Placement on Processed Data.")

    parser.add_argument("--design", required=True, help="Design Name (e.g. 6502)")
    parser.add_argument("--data", required=True, help="Path to processed_data.json")
    parser.add_argument("--output", required=True, help="Full path for the output .map file")

    args = parser.parse_args()

    placer = GreedyPlacer(args.design, args.data)
    placer.run_seed_placement()
    placer.run_grow_placement()
    # Pass the exact file path from arguments
    placer.write_map_file(args.output)