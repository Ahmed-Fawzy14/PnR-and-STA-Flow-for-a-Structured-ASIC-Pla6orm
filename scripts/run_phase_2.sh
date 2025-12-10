#!/usr/bin/env bash
set -euo pipefail

# Placement driver:
# 1) placer.py                        (greedy + SA placement)
# 2) greedyPlacementVisualization.py  (existing visualization)
# 3) placement_visualizations.py      (density + net HPWL hist)
#
# Usage (from repo root):
#   ./scripts/run_placer.sh          # default design = 6502
#   ./scripts/run_placer.sh arith    # or any other design name


# Figure out where this script lives and what the project root is
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &>/dev/null && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Default design is 6502 unless overridden as $1
DESIGN="${1:-6502}"

echo "========================================"
echo " Placement flow"
echo " Project root : ${PROJECT_ROOT}"
echo " Design       : ${DESIGN}"
echo "========================================"
echo

# Always run from project root so relative paths ("build", "designs", "src") work
cd "$PROJECT_ROOT"

# 1) Combined placer (greedy + SA)
echo "[1/3] Running placer.py (greedy + SA)..."
python src/placer.py \
  --design "${DESIGN}"

# 2) Greedy placement visualization
#    (assumes greedyPlacementVisualization.py accepts --design)
echo
echo "[2/3] Running greedyPlacementVisualization.py..."
python src/greedyPlacementVisualization.py \
  --design "${DESIGN}" \
  --data "build/${DESIGN}/data_structures.json" \
  --fabric "build/fabric/fabric_db.json"




# 3) Phase 2 placement visualizations (density + net HPWL histogram)
#    Uses:
#      data_structures: build/<design>/data_structures_sa.json
#      placement map :  build/<design>/<design>.map   (SA final map)
#      outputs:
#        build/<design>/<design>_density.png
#        build/<design>/<design>_net_length_hist.png
echo
echo "[3/3] Running visualize_graphs.py (density + net HPWL hist)..."
python src/visualize_graphs.py \
  --data-structures "build/${DESIGN}/data_structures_sa.json" \
  --placement-map   "build/${DESIGN}/${DESIGN}.map" \
  --design-name     "${DESIGN}" \
  --out-density     "build/${DESIGN}/${DESIGN}_density.png" \
  --out-net-length  "build/${DESIGN}/${DESIGN}_net_length_hist.png"

echo
echo "========================================"
echo " Placement flow completed for design (phase 2): ${DESIGN}"
echo "========================================"