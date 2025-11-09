# Structured ASIC Design Validator - Phase 1

A validation tool for verifying if digital designs can be successfully mapped to a structured ASIC fabric.

## Overview

This project validates whether hardware designs can be implemented on a structured ASIC fabric by comparing required cell types against available fabric slots. The validator ensures that each design's cell requirements do not exceed the fabric's capacity.


## Usage

### Basic Command
```bash
python3 validator.py <design_name>
```

### Examples
```bash
python3 validator.py 6502
python3 validator.py aes_128
python3 validator.py arith
python3 validator.py z80
```

### Alternative (Environment Variable)
```bash
DESIGN=6502 python3 validator.py
```

## Validation Results

| Design | Total Cells | Status | Peak Utilization | Notes |
|--------|-------------|--------|------------------|-------|
| **6502** | 2,899 |  PASSED | 3.3% (BUF, OR) | Low utilization |
| **aes_128** | 85,819 |  PASSED | **95.2% (NAND)** | Near capacity |
| **arith** | 463 |  PASSED | 0.7% (BUF) | Minimal usage |
| **z80** | 9,144 |  PASSED | 17.5% (OR) | Moderate usage |

### Fabric Capacity
- **Total cells:** 158,760
- **Cell types:** 8 (NAND, OR, INV, BUF, DFBBP, CONB, TAP, FILL)
- **Breakdown:**
  - NAND: 48,600 slots
  - OR: 25,920 slots
  - INV: 12,960 slots
  - BUF: 9,720 slots
  - DFBBP: 6,480 slots
  - CONB: 9,720 slots

## How It Works

1. **Load Fabric Database:** Reads `fabric_db.json` to get available cell slots
2. **Load Design Database:** Reads `build/<design>/<design>_logical_db.json` for cell requirements
3. **Normalize Cell Types:** Converts SKY130 cell names (e.g., `sky130_fd_sc_hd__nand2_1`) to fabric types (e.g., `NAND`)
4. **Validate:** Compares required counts vs. available slots
5. **Report:** Generates utilization report and saves to `build/<design>/<design>_validation.rpt`

## Output

The validator produces:
- **Console output:** Real-time validation status and utilization percentages
- **Report file:** Detailed validation report saved to `build/<design>/<design>_validation.rpt`

### Sample Output
```
============================================================
Validating Design: 6502
============================================================

Fabric Utilization Report:
------------------------------------------------------------
 BUF: 322/9720 used (3.3%)
 CONB: 3/9720 used (0.0%)
 DFBBP: 143/6480 used (2.2%)
 INV: 360/12960 used (2.8%)
 NAND: 1228/48600 used (2.5%)
 OR: 843/25920 used (3.3%)

------------------------------------------------------------
Summary:
  Total cell types in design: 6
  Total cell instances: 2899
  Validation errors: 0

============================================================
VALIDATION PASSED!
============================================================
```

## Key Findings

-  **All designs validated successfully**
-  **AES-128 is resource-intensive:** Uses 95.2% of NAND slots and 91.2% of OR slots
-  **Fabric headroom:** Most designs have significant room for optimization or additional features
- 🎯 **Arith is most efficient:** Uses <1% of fabric resources

## Requirements

- Python 3.6+
- No external dependencies (uses standard library only)

## Error Handling

The validator will exit with code 1 if:
- Fabric database file (`fabric_db.json`) is missing
- Logical database file is missing or invalid
- Any cell type requirement exceeds fabric availability

## Future Enhancements

- Physical placement validation
- Routing congestion analysis
- Power estimation
- Timing analysis

## License

Educational project for Digital Design 2 course.

