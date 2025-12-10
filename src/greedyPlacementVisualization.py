#greedyPlacementVisualization.py
import argparse
import os
import sys
from PIL import Image

# Import from sibling files
# Assuming this script is run from the project root or the same directory
try:
    from greedyPlacer import GreedyPlacer
    import visualize_placement as viz
except ImportError:
    # Fallback if run from parent directory or different context
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from greedyPlacer import GreedyPlacer
    import visualize_placement as viz


def main():
    parser = argparse.ArgumentParser(description="Visualize Greedy Placement Animation")
    parser.add_argument("--design", required=True, help="Design Name")
    parser.add_argument("--data", required=True, help="Path to processed_data.json")
    parser.add_argument("--fabric", required=True, help="Path to fabric_cells.json")
    parser.add_argument("--output", required=True, help="Output GIF path")
    parser.add_argument("--interval", type=int, default=50, help="Placements per frame")
    parser.add_argument("--width", type=int, default=1000, help="Image width")

    # Visualization defaults
    parser.add_argument("--slot-w", type=float, default=0.46)
    parser.add_argument("--slot-h", type=float, default=2.72)

    args = parser.parse_args()

    # 1. Load Fabric Data (for visualization context)
    print(f"Loading fabric from {args.fabric}...")
    fab = viz.load_json(args.fabric)
    if not fab:
        sys.exit(1)

    # 2. Initialize Placer
    placer = GreedyPlacer(args.design, args.data)

    # 3. Pre-calculate Visualization Geometry
    # We need to know the die/core dimensions beforehand.
    # We can infer them from the fabric and *all* potential slots (even empty ones)
    # or just use the fabric definition.

    # Get all potential slots from fabric to establish the grid
    all_slots = viz.collect_slots(fab, None, args.slot_w, args.slot_h)
    die_um, core_um = viz.infer_die_core(fab, all_slots)
    pins = viz.parse_pins(fab, die_um)

    # Scale calculations
    scale = args.width / max(1.0, die_um["width_um"])

    die_px = {
        "width": die_um["width_um"] * scale,
        "height": die_um["height_um"] * scale
    }
    core_px = {
        "x": core_um["x_um"] * scale,
        "y": core_um["y_um"] * scale,
        "width": core_um["width_um"] * scale,
        "height": core_um["height_um"] * scale
    }

    pins_px = []
    for p in pins:
        pins_px.append({
            "name": p["name"],
            "side": p["side"],
            "direction": p["direction"],
            "x": p["x"] * scale,
            "y": p["y"] * scale,
            "w": p["w"] * scale,
            "h": p["h"] * scale
        })

    # 4. Callback Setup
    frames = []
    placement_counter = 0

    def capture_frame(current_placer):
        nonlocal placement_counter
        placement_counter += 1

        if placement_counter % args.interval == 0:
            # Convert placer.placement (inst -> slot) to slots_px format
            # We need to map slot_name -> inst_name
            # But visualize_placement expects a map of {phys_loc: logical_name}

            # Create a temporary map for visualization
            current_map = {slot: inst for inst, slot in current_placer.placement.items()}

            # Collect only placed slots
            # Note: collect_slots iterates over FABRIC tiles and checks against the map
            # This might be slow if fabric is huge.
            # Optimization: We already have 'all_slots' (which has phys_loc).
            # We can just filter/update 'all_slots' instead of re-parsing fabric.

            current_slots_px = []
            for s in all_slots:
                phys_loc = s["phys_loc"]
                if phys_loc in current_map:
                    # This slot is occupied
                    logical_name = current_map[phys_loc]

                    # Create a copy to modify type if needed, or just use as is
                    # The type in 's' is the physical type.
                    # If we want to color by cell type, we should use the placed instance's type.
                    # The placer has 'cell_type' map.

                    inst_type = current_placer.cell_type.get(logical_name, "UNK")
                    clean_type = viz.clean_type_name(inst_type)

                    current_slots_px.append({
                        "type": clean_type,
                        "x": s["x"] * scale,
                        "y": s["y"] * scale,
                        "w": s["w"] * scale,
                        "h": s["h"] * scale
                    })

            # Generate Color Map
            unique_types = [s["type"] for s in current_slots_px]
            cmap = viz.slot_color_map(unique_types)

            # Create Image
            title = f"Placement: {len(current_placer.placement)} cells"
            img = viz.create_placement_image(die_px, core_px, current_slots_px, pins_px, scale, cmap, title)

            # Convert to RGB to ensure compatibility with GIF saving (sometimes RGBA causes issues)
            # But we want transparency? GIF supports transparency but it's tricky.
            # Let's composite over white for safety.
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])

            frames.append(bg)
            print(f"Captured frame {len(frames)} ({len(current_placer.placement)} cells)")

    # 5. Run Placement
    print("Starting placement with animation capture...")

    # Initial empty frame
    capture_frame(placer)

    placer.run_seed_placement(callback=capture_frame)
    placer.run_grow_placement(callback=capture_frame)

    # Final frame
    capture_frame(placer)

    # 6. Save Animation
    if frames:
        print(f"Saving animation to {args.output} with {len(frames)} frames...")
        # Duration is in milliseconds per frame
        frames[0].save(
            args.output,
            save_all=True,
            append_images=frames[1:],
            optimize=False,
            duration=100,
            loop=0
        )
        print("Done!")
    else:
        print("No frames captured.")


if __name__ == "__main__":
    main()