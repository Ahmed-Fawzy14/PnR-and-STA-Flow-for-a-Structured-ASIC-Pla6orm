#!/usr/bin/env bash
set -euo pipefail

# Phase 3 driver:
# 1) eco_generator.py      (CTS + power-down ECO)
# 2) generate_verilog.py
# 3) generate_pd_eco.py
# 4) animated_eco_pd.py
# 5) cts_vis.py            (CTS visualization)
#
# Usage (from repo root):
#   ./scripts/run_phase_3.sh          # default design = 6502
#   ./scripts/run_phase_3.sh 6502



# Figure out where this script lives and what the project root is
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &>/dev/null && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Default design is 6502 unless overridden as $1
DESIGN="${1:-6502}"

echo "========================================"
echo " Phase 3 flow"
echo " Project root : ${PROJECT_ROOT}"
echo " Design       : ${DESIGN}"
echo "========================================"
echo

# Always run from project root so relative paths ("build", "designs", "src") work
cd "$PROJECT_ROOT"

# 1) CTS + Power-down ECO
echo "[1/5] Running eco_generator.py (CTS + power-down ECO)..."
python src/eco_generator.py \
  --design "${DESIGN}"

# 2) Generate Verilog netlist after PD ECO
echo
echo "[2/5] Running generate_verilog.py..."
python src/generate_verilog.py \
  --design "${DESIGN}"

# 3) Generate PD ECO visualization / extra artifacts
echo
echo "[3/5] Running generate_pd_eco.py..."
python src/generate_pd_eco.py \
  --design "${DESIGN}"

# 4) Animated ECO PD plot
echo
echo "[4/5] Running animated_eco_pd.py..."
python src/animated_eco_pd.py \
  --design "${DESIGN}" \
  --animate

# 5) CTS visualization (pre-CTS vs post-CTS netlist) #CHANGE fabric_db_o
#    Uses:
#      fabric:      build/fabric/fabric_db.json
#      map:         build/<design>/<design>_cts.map
#      old_netlist: designs/<design>_mapped.json        (pre-CTS)
#      new_netlist: build/<design>/<design>_cts_mapped.json (post-CTS)
#      out:         build/<design>/<design>_cts_vis.png
echo
echo "[5/5] Running visualize_cts.py (CTS visualization)..."
python src/visualize_cts.py \
  --fabric "build/fabric/fabric_db_o.json" \
  --map "build/${DESIGN}/${DESIGN}_sa.map" \
  --old_netlist "build/${DESIGN}/${DESIGN}_mapped_netlist_graph.json" \
  --new_netlist "build/${DESIGN}/${DESIGN}_cts_mapped_netlist_graph.json" \
  --out "build/${DESIGN}/${DESIGN}_cts_vis.png"

echo
echo "========================================"
echo " Phase 3 completed for design: ${DESIGN}"
echo "========================================"