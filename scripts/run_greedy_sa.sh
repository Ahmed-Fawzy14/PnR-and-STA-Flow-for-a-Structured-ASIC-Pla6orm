#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage:"
  echo "  $0 <design> <sa-args...>"
  echo
  echo "Example:"
  echo "  $0 6502 --num-temp-steps 60 --moves-per-temp 1000 --T-initial 200 --alpha 0.95 --P-refine 0.7 --W-initial 0.5 --beta 0.95 --seed 42"
  exit 1
fi

DESIGN="$1"
shift   # remove design so remaining args go to SA

LOGICAL_DB="build/${DESIGN}/${DESIGN}_logical_db.json"
FABRIC_DB="build/fabric/fabric_db.json"
DS_JSON="build/${DESIGN}/data_structures.json"
GREEDY_MAP="build/${DESIGN}/${DESIGN}.map"
SA_MAP="build/${DESIGN}/${DESIGN}_sa.map"

echo "[RUN] Generating data structures..."
python src/dataStructuresGenerator.py \
  --logical-db "${LOGICAL_DB}" \
  --fabric-db "${FABRIC_DB}" \
  --out-json "${DS_JSON}"

echo "[RUN] Running greedy placer..."
python src/greedyPlacer.py \
  --ds-json "${DS_JSON}" \
  --out-map "${GREEDY_MAP}"

echo "[RUN] Running simulated annealing with parameters: $@"
python src/simulated_annealing.py \
  --data-structures "${DS_JSON}" \
  --initial-map "${GREEDY_MAP}" \
  --out-map "${SA_MAP}" \
  "$@"

echo "[DONE] Greedy + SA complete!"
echo "  → Greedy map: ${GREEDY_MAP}"
echo "  → SA optimized map: ${SA_MAP}"