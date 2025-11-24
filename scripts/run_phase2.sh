#!/usr/bin/env bash
set -euo pipefail

# Phase 2 Complete Flow Script
# Runs: Greedy + SA placement, then generates all Phase 2 visualizations

if [ "$#" -lt 1 ]; then
  echo "Usage:"
  echo "  $0 <design> [sa-args...]"
  echo
  echo "Example:"
  echo "  $0 6502"
  echo "  $0 6502 --num-temp-steps 60 --moves-per-temp 1000 --T-initial 200 --alpha 0.95 --P-refine 0.7 --W-initial 0.5 --beta 0.95 --seed 42"
  exit 1
fi

DESIGN="$1"
shift   # remove design so remaining args go to SA

# Try to find logical_db.json (handle both flat and nested structures)
LOGICAL_DB="build/${DESIGN}/${DESIGN}_logical_db.json"
if [ ! -f "$LOGICAL_DB" ]; then
    # Try nested structure (e.g., build/arith/arith/arith_logical_db.json)
    NESTED_LOGICAL_DB="build/${DESIGN}/${DESIGN}/${DESIGN}_logical_db.json"
    if [ -f "$NESTED_LOGICAL_DB" ]; then
        LOGICAL_DB="$NESTED_LOGICAL_DB"
        echo "[INFO] Using nested structure: ${LOGICAL_DB}"
    else
        echo "[ERROR] Could not find logical_db.json for design ${DESIGN}"
        echo "  Tried: build/${DESIGN}/${DESIGN}_logical_db.json"
        echo "  Tried: build/${DESIGN}/${DESIGN}/${DESIGN}_logical_db.json"
        exit 1
    fi
fi

FABRIC_DB="build/fabric/fabric_db.json"
DS_JSON="build/${DESIGN}/data_structures.json"
GREEDY_MAP="build/${DESIGN}/${DESIGN}.map"
SA_MAP="build/${DESIGN}/${DESIGN}_sa.map"
DENSITY_PNG="build/${DESIGN}/${DESIGN}_density.png"
NET_LENGTH_PNG="build/${DESIGN}/${DESIGN}_net_length.png"

echo "=========================================="
echo "Phase 2: Placement & Analysis"
echo "Design: ${DESIGN}"
echo "=========================================="
echo

# Step 1: Generate data structures
echo "[STEP 1/5] Generating data structures..."
python3 src/dataStructuresGenerator.py \
  --logical-db "${LOGICAL_DB}" \
  --fabric-db "${FABRIC_DB}" \
  --out-json "${DS_JSON}"

# Step 2: Run greedy placer
echo
echo "[STEP 2/5] Running greedy placer..."
python3 src/greedyPlacer.py \
  --ds-json "${DS_JSON}" \
  --out-map "${GREEDY_MAP}"

# Step 3: Run simulated annealing
echo
echo "[STEP 3/5] Running simulated annealing with parameters: $@"
python3 src/simulated_annealing.py \
  --data-structures "${DS_JSON}" \
  --initial-map "${GREEDY_MAP}" \
  --out-map "${SA_MAP}" \
  "$@"

# Step 4: Generate placement visualizations
echo
echo "[STEP 4/5] Generating placement visualizations..."
python3 src/visualize_placement.py \
  --data-structures "${DS_JSON}" \
  --placement-map "${SA_MAP}" \
  --design-name "${DESIGN}" \
  --out-density "${DENSITY_PNG}" \
  --out-net-length "${NET_LENGTH_PNG}"

# Step 5: Summary
echo
echo "=========================================="
echo "Phase 2 Complete!"
echo "=========================================="
echo "Generated files:"
echo "  → Greedy map: ${GREEDY_MAP}"
echo "  → SA optimized map: ${SA_MAP}"
echo "  → Density heatmap: ${DENSITY_PNG}"
echo "  → Net length histogram: ${NET_LENGTH_PNG}"
echo
echo "To run SA knob analysis (optional):"
echo "  python3 src/sa_knob_analysis.py --design ${DESIGN}"
echo
