import math
import sys
import os
import heapq
from collections import defaultdict

# Import the loader provided by the user
try:
    from dataStructuresGenerator import build_data_structures
except ImportError:
    print("Error: data_loader.py not found. Please ensure it is in the same directory.")
    sys.exit(1)

class GreedyPlacer:
    def __init__(self, design_name, netlist_graph_path, logical_db_path, fabric_cells_path):
        self.design_name = design_name
        
        # 1. Load Data using the provided loader
        print(f"[{design_name}] Loading Data...")
        self.data = build_data_structures(netlist_graph_path, logical_db_path, fabric_cells_path)
        
        # Unpack commonly used structures for easier access
        self.logical_db = self.data["logical_db"]
        self.fabric_db = self.data["fabric_db"]
        self.slot_coords = self.data["slot_coords"]
        self.slot_type = self.data["slot_type"]
        self.slots_by_type = self.data["slots_by_type"]
        self.cell_type = self.data["cell_type"]
        self.inst_to_nets = self.data["inst_to_nets"]
        self.net_to_pins = self.data["net_to_pins"]
        self.pin_coords = self.data["pin_coords"]
        
        # Initialize State
        self.placement = {} # instance_name -> slot_name
        self.occupied_slots = set()
        self.unplaced_instances = set(self.logical_db.keys())

        # Pre-sort slots by coordinate to potentially speed up search (optional optimization)
        # We keep them as is, but we will filter them dynamically.

    def get_distance(self, x1, y1, x2, y2):
        """Euclidean distance for finding nearest slot."""
        return math.sqrt((x1 - x2)**2 + (y1 - y2)**2)

    def find_nearest_slot(self, target_x, target_y, required_type):
        """
        Finds the nearest AVAILABLE slot of the required type to the target coordinates.
        Returns slot_name or None if exhausted.
        """
        best_slot = None
        min_dist = float('inf')
        
        # Get all slots of this type
        candidate_slots = self.slots_by_type.get(required_type, [])
        
        # Optimization: This is a linear scan. For 10k+ cells this can be slow.
        # In a production placer, we would use a K-D Tree or spatial binning.
        # For this academic scope, linear scan is usually acceptable given the constraints.
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
        """Helper to finalize placement of an instance."""
        c_type = self.cell_type[inst_name]
        
        slot = self.find_nearest_slot(target_x, target_y, c_type)
        
        if slot:
            self.placement[inst_name] = slot
            self.occupied_slots.add(slot)
            self.unplaced_instances.remove(inst_name)
            return True
        else:
            print(f"CRITICAL WARNING: No available '{c_type}' slots left for {inst_name}!")
            return False

    def run_seed_placement(self):
        """
        Phase 1: SEED
        Place cells connected directly to fixed I/O pins at the nearest valid fabric slot.
        """
        print("Running Seed Placement (I/O Driven)...")
        count = 0
        
        # Identify cells connected to I/Os
        # We iterate over all unplaced instances
        # If they have a net that connects to a PORT (pin_coords), we calculate the IO center.
        
        # To do this efficiently:
        # 1. Identify nets connected to IOs
        io_nets = {} # net_id -> list of (x, y) of connected pins
        
        for net_id, pins_on_net in self.net_to_pins.items():
            io_locs = []
            for (name, pin_type) in pins_on_net:
                # If pin_type is None, it's a port (based on loader logic)
                # OR check if name is in pin_coords
                if name in self.pin_coords:
                    io_locs.append(self.pin_coords[name])
            
            if io_locs:
                io_nets[net_id] = io_locs

        # 2. Find instances connected to these nets
        seed_candidates = []
        
        for inst_name in list(self.unplaced_instances):
            connected_nets = self.inst_to_nets.get(inst_name, set())
            
            connected_io_locs = []
            for net_id in connected_nets:
                if net_id in io_nets:
                    connected_io_locs.extend(io_nets[net_id])
            
            if connected_io_locs:
                # Calculate Center of Gravity of I/Os
                avg_x = sum(x for x, y in connected_io_locs) / len(connected_io_locs)
                avg_y = sum(y for x, y in connected_io_locs) / len(connected_io_locs)
                seed_candidates.append((inst_name, avg_x, avg_y))

        # 3. Place them
        for inst_name, x, y in seed_candidates:
            if inst_name in self.unplaced_instances: # Double check
                if self.place_instance(inst_name, x, y):
                    count += 1
                    
        print(f"  -> Placed {count} seed instances.")

    def run_grow_placement(self):
        """
        Phase 2: GROW
        Iteratively place the most-connected unplaced cell at the barycenter 
        of its already-placed neighbors.
        """
        print("Running Grow Placement (Connectivity Driven)...")
        
        # To optimize "finding the most connected unplaced cell", we use a Priority Queue.
        # Score = Number of connections to PLACED cells.
        # Python's heapq is a min-heap, so we store (-score, inst_name).
        
        connectivity_scores = defaultdict(int)
        pq = []
        
        # 1. Initialize scores based on Seed placement
        # For every placed cell, find its unplaced neighbors and increment their score
        for placed_inst in self.placement.keys():
            self._update_neighbors(placed_inst, connectivity_scores, pq)
            
        count = 0
        while self.unplaced_instances:
            best_inst = None
            
            # Get best candidate from heap
            while pq:
                score, inst = heapq.heappop(pq)
                score = -score # convert back to positive
                
                if inst not in self.unplaced_instances:
                    continue # Already placed
                
                # Lazy update check: 
                # The score in heap might be stale (lower than current reality).
                # However, for "Grow", we usually just want a good candidate.
                # To be strictly correct, we checks if score == connectivity_scores[inst].
                if score < connectivity_scores[inst]:
                    continue # Skip stale entries
                
                best_inst = inst
                break
            
            # If priority queue is empty or exhausted but we still have unplaced cells
            # (This happens if we have disjoint islands of logic not connected to I/Os)
            if best_inst is None:
                # Fallback: Pick an arbitrary unplaced cell (e.g., the first one)
                # Ideally, pick one with high degree in general
                best_inst = list(self.unplaced_instances)[0]
            
            # Calculate Barycenter of PLACED neighbors
            target_x, target_y = self._calculate_barycenter(best_inst)
            
            # Place it
            success = self.place_instance(best_inst, target_x, target_y)
            if success:
                count += 1
                # Update neighbors of this newly placed cell
                self._update_neighbors(best_inst, connectivity_scores, pq)
            else:
                # Failed to place (no slots). We must remove it to avoid infinite loop
                self.unplaced_instances.remove(best_inst)
            
            if count % 100 == 0:
                sys.stdout.write(f"\r  -> Placed {count} instances...")
                sys.stdout.flush()

        print(f"\n  -> Grow phase complete. Total placed: {len(self.placement)}")

    def _update_neighbors(self, placed_inst, scores, pq):
        """Helper: When a cell is placed, boost score of its unplaced neighbors."""
        nets = self.inst_to_nets.get(placed_inst, set())
        
        for net_id in nets:
            pins = self.net_to_pins.get(net_id, [])
            for (neighbor_name, _) in pins:
                if neighbor_name in self.unplaced_instances:
                    # Increment score
                    scores[neighbor_name] += 1
                    # Push to heap (negate for max-heap behavior)
                    heapq.heappush(pq, (-scores[neighbor_name], neighbor_name))

    def _calculate_barycenter(self, inst_name):
        """Calculates average X,Y of all PLACED neighbors."""
        nets = self.inst_to_nets.get(inst_name, set())
        
        neighbor_coords = []
        
        for net_id in nets:
            pins = self.net_to_pins.get(net_id, [])
            for (neighbor, _) in pins:
                # Check if neighbor is placed
                if neighbor in self.placement:
                    slot = self.placement[neighbor]
                    neighbor_coords.append(self.slot_coords[slot])
                # Check if neighbor is a PIN (I/O)
                elif neighbor in self.pin_coords:
                    neighbor_coords.append(self.pin_coords[neighbor])
        
        if not neighbor_coords:
            # Disconnected or start of island? Place in center of die as fallback
            # Find center of all slots roughly
            all_x = [c[0] for c in self.slot_coords.values()]
            all_y = [c[1] for c in self.slot_coords.values()]
            return (min(all_x) + max(all_x))/2, (min(all_y) + max(all_y))/2
            
        avg_x = sum(x for x, y in neighbor_coords) / len(neighbor_coords)
        avg_y = sum(y for x, y in neighbor_coords) / len(neighbor_coords)
        
        return avg_x, avg_y

    def write_map_file(self, output_dir="build"):
        """Writes the .map file as required."""
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # Create directory for design if needed
        design_dir = os.path.join(output_dir, self.design_name)
        if not os.path.exists(design_dir):
            os.makedirs(design_dir)
            
        filename = os.path.join(design_dir, f"{self.design_name}.map")
        
        print(f"Writing output to {filename}...")
        with open(filename, "w") as f:
            for inst, slot in self.placement.items():
                f.write(f"{inst} {slot}\n")
        print("Done.")

# ==========================================
# Main Execution
# ==========================================
if __name__ == "__main__":
    # You can change these to match your specific file locations
    DESIGN_NAME = "6502" 
    
    # Assuming standard file naming based on your description
    NETLIST_GRAPH = f"{DESIGN_NAME}_mapped_netlist_graph.json" # or design_name_netlist_graph.json
    LOGICAL_DB    = f"{DESIGN_NAME}_logical_db.json"
    FABRIC_CELLS  = "fabric_cells.json" # or fabric_cells.db
    
    # Check if files exist before running
    if not os.path.exists(LOGICAL_DB):
        print(f"Please ensure input files exist. Could not find: {LOGICAL_DB}")
        # Fallback for the example provided in chat context
        NETLIST_GRAPH = "design_name_netlist_graph.json"
        LOGICAL_DB = "design_name_logical_db.json"
        FABRIC_CELLS = "fabric_cells.db"
        print(f"Trying fallback names: {LOGICAL_DB}")

    placer = GreedyPlacer(DESIGN_NAME, NETLIST_GRAPH, LOGICAL_DB, FABRIC_CELLS)
    
    # Run Task 1A
    placer.run_seed_placement()
    placer.run_grow_placement()
    
    # Save Result
    placer.write_map_file()