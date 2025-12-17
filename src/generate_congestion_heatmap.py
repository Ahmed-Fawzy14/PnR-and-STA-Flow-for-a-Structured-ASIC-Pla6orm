import re
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import os
import argparse
import sys


def parse_def_diearea(def_path):
    """Parses the DEF file to extract the DIEAREA."""
    try:
        if not os.path.exists(def_path):
            print(f"Error: DEF file not found at {def_path}")
            return None

        with open(def_path, 'r') as f:
            content = f.read()

        # Check units
        units_match = re.search(r'UNITS\s+DISTANCE\s+MICRONS\s+(\d+)', content)
        units = int(units_match.group(1)) if units_match else 1000

        # Parse DIEAREA
        # DIEAREA ( x1 y1 ) ( x2 y2 ) ;
        die_match = re.search(r'DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)', content)
        if die_match:
            x1, y1, x2, y2 = map(int, die_match.groups())
            # Convert to microns
            return (x1 / units, y1 / units, x2 / units, y2 / units)
        else:
            print("Warning: DIEAREA not found in DEF file.")
            return None
    except Exception as e:
        print(f"Error parsing DEF file: {e}")
        return None


def parse_congestion_report(rpt_path):
    """Parses the congestion report to extract bounding boxes and overflow values."""
    data = []
    current_entry = {}

    try:
        if not os.path.exists(rpt_path):
            print(f"Error: Report file not found at {rpt_path}")
            return []

        with open(rpt_path, 'r') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()

            # Parse congestion info line: congestion information: capacity:27 usage:28 overflow:1
            if "congestion information:" in line:
                overflow_match = re.search(r'overflow:(\d+)', line)
                if overflow_match:
                    current_entry['overflow'] = int(overflow_match.group(1))

            # Parse bbox line: bbox = ( 77.8, 112.3 ) - ( 84.7, 119.2) on Layer -
            if line.startswith("bbox ="):
                # Extract coordinates
                # We expect floats or integers
                coords_match = re.search(
                    r'bbox\s*=\s*\(\s*([\d\.-]+)\s*,\s*([\d\.-]+)\s*\)\s*-\s*\(\s*([\d\.-]+)\s*,\s*([\d\.-]+)\s*\)',
                    line)
                if coords_match:
                    x1, y1, x2, y2 = map(float, coords_match.groups())
                    current_entry['bbox'] = (x1, y1, x2, y2)

                    # Only add if we successfully parsed overflow
                    if 'overflow' in current_entry:
                        data.append(current_entry)
                    else:
                        pass

                        # Reset for next entry
                    current_entry = {}

    except Exception as e:
        print(f"Error parsing congestion report: {e}")
        return []

    return data


def plot_heatmap(die_area, congestion_data, output_file, design_name):
    """Plots the congestion heatmap."""
    fig, ax = plt.subplots(figsize=(12, 12))

    # Set plot limits based on DIEAREA
    if die_area:
        die_x1, die_y1, die_x2, die_y2 = die_area
        ax.set_xlim(die_x1, die_x2)
        ax.set_ylim(die_y1, die_y2)
        # Draw die boundary
        rect = patches.Rectangle((die_x1, die_y1), die_x2 - die_x1, die_y2 - die_y1,
                                 linewidth=1.5, edgecolor='black', facecolor='none', label='Die Area')
        ax.add_patch(rect)
    else:
        # Auto-scale if no die area, or set some reasonable defaults if data exists
        if congestion_data:
            # Find min/max from data
            # Not implemented for brevity, but could help if DEF is missing
            pass

    if not congestion_data:
        print("No congestion data found to plot.")
        return

    # Determine max overflow for color scaling
    overflows = [d['overflow'] for d in congestion_data]
    max_overflow = max(overflows) if overflows else 1

    print(f"Plotting {len(congestion_data)} congestion areas. Max overflow: {max_overflow}")

    # Use a colormap
    cmap = plt.get_cmap('Reds')

    for item in congestion_data:
        x1, y1, x2, y2 = item['bbox']
        overflow = item['overflow']

        # Normalize overflow for color map
        val = overflow / max_overflow
        color = cmap(val)

        # Create rectangle
        width = x2 - x1
        height = y2 - y1
        rect = patches.Rectangle((x1, y1), width, height,
                                 linewidth=0, facecolor=color, alpha=0.7)
        ax.add_patch(rect)

    # Setup plot details
    ax.set_title(f'Congestion Heatmap - {design_name}')
    ax.set_xlabel('Microns')
    ax.set_ylabel('Microns')
    ax.set_aspect('equal')

    # Add colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=max_overflow))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax)
    cbar.set_label('Overflow')

    # Ensure output directory exists
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Save
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Heatmap saved to {output_file}")
    plt.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate congestion heatmap.")
    parser.add_argument("--design", required=True, help="Name of the design (e.g., z80)")
    parser.add_argument("--def_file", required=True, help="Path to the .def file")
    parser.add_argument("--rpt_file", required=True, help="Path to the .rpt file")
    parser.add_argument("--output", required=True, help="Path for the output image file")

    args = parser.parse_args()

    print(f"Processing design: {args.design}")
    print(f"DEF file: {args.def_file}")
    print(f"Report file: {args.rpt_file}")

    # 1. Parse DEF for Die Area
    die_area = parse_def_diearea(args.def_file)
    if die_area:
        print(f"Die Area (microns): {die_area}")
    else:
        print("Warning: Could not determine Die Area from DEF.")

    # 2. Parse Congestion Report
    congestion_data = parse_congestion_report(args.rpt_file)

    # 3. Plot Heatmap
    if congestion_data:
        plot_heatmap(die_area, congestion_data, args.output, args.design)
    else:
        print("No congestion data extracted.")