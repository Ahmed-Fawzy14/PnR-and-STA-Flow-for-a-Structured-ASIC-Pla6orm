"""
Design Validator Module (Phase 1)

This module validates if a given design can be built on the structured ASIC fabric.
It compares the required cell types from the design against available fabric slots.

Tasks:
1. Load Platform: Read fabric_db.json (pre-processed fabric database)
2. Load Design: Read build/<design>/<design>_logical_db.json (pre-processed logical database)
3. Validate: Compare required cells against available slots
4. Report: Print fabric utilization report
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Optional


def load_fabric_db(fabric_db_path: str = "fabric_db.json") -> Dict[str, List[Dict[str, Any]]]:
    """
    Load fabric database from JSON file.
    
    The fabric_db.json should contain a dictionary mapping cell type names
    to lists of cell slots. Each cell slot should have at least:
    - name: Physical cell name
    - type: Cell type (e.g., "NAND", "DFF")
    - x, y: Coordinates
    
    Args:
        fabric_db_path: Path to fabric_db.json file
        
    Returns:
        Dictionary mapping cell type names to lists of cell slots:
        {
            "NAND": [{"name": "T0Y0__R0_NAND_2", "x": 10.0, "y": 20.0, ...}, ...],
            "DFF": [...],
            ...
        }
    """
    file_path = Path(fabric_db_path)
    if not file_path.exists():
        raise FileNotFoundError(
            f"Fabric database file not found: {fabric_db_path}\n"
            f"Please ensure fabric_db.json exists. It should be created by parsing fabric_cells.yaml"
        )
    
    try:
        with open(file_path, 'r') as f:
            fabric_db = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse fabric database JSON file: {e}")
    
    # Validate structure
    if not isinstance(fabric_db, dict):
        raise ValueError("Fabric database must be a dictionary mapping cell types to cell lists")
    
    return fabric_db


def load_logical_db(logical_db_path: str) -> Dict[str, Any]:
    """
    Load logical database from JSON file.
    
    The logical_db.json should follow the schema defined in logical_db.schema.json.
    It must contain at minimum:
    - version: Schema version
    - design: Design name
    - type_counts: Dictionary mapping cell types to counts
    - instances: Dictionary of all cell instances
    
    Args:
        logical_db_path: Path to logical_db.json file (e.g., build/6502/6502_logical_db.json)
        
    Returns:
        Dictionary containing the logical database:
        {
            "version": "1.0",
            "design": "6502",
            "type_counts": {"sky130_fd_sc_hd__nand2_1": 100, ...},
            "instances": {...},
            "net_graph": {...},
            ...
        }
    """
    file_path = Path(logical_db_path)
    if not file_path.exists():
        raise FileNotFoundError(
            f"Logical database file not found: {logical_db_path}\n"
            f"Please ensure the logical_db.json file exists. It should be created by parsing the mapped.json file"
        )
    
    try:
        with open(file_path, 'r') as f:
            logical_db = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse logical database JSON file: {e}")
    
    # Validate required fields
    if "type_counts" not in logical_db:
        raise ValueError("Logical database must contain 'type_counts' field")
    
    if "version" not in logical_db:
        raise ValueError("Logical database must contain 'version' field")
    
    return logical_db


def normalize_cell_type(cell_type: str) -> str:
    """
    Normalize cell type names to match between fabric and design.
    
    The fabric uses short names like "NAND", "DFF", etc.
    The design uses full names like "sky130_fd_sc_hd__nand2_1".
    
    This function extracts the base type from full names.
    
    Args:
        cell_type: Full cell type name (e.g., "sky130_fd_sc_hd__nand2_1")
        
    Returns:
        Normalized type name (e.g., "NAND")
    """
    # If already normalized (uppercase, short name), return as-is
    if cell_type.isupper() and len(cell_type) < 10:
        return cell_type
    
    # Pattern to extract base type from sky130 cell names
    # sky130_fd_sc_hd__nand2_1 -> nand2 -> NAND
    # sky130_fd_sc_hd__dfxtp_1 -> dfxtp -> DFF
    pattern = re.compile(r"sky130_fd_sc_hd__([a-z0-9]+)")
    match = pattern.match(cell_type.lower())
    
    if match:
        base_name = match.group(1)
        # Extract the gate type (nand, nor, and, or, etc.)
        # Handle common patterns - check in order of specificity
        if base_name.startswith("nand"):
            return "NAND"
        elif base_name.startswith("nor"):
            return "NOR"
        elif base_name.startswith("xnor"):
            return "XNOR"
        elif base_name.startswith("xor"):
            return "XOR"
        elif base_name.startswith("and"):
            return "AND"
        elif base_name.startswith("or") and not base_name.startswith("xnor"):
            return "OR"
        elif base_name.startswith("inv") or base_name.startswith("clkinv"):
            return "INV"
        elif base_name.startswith("clkbuf") or base_name.startswith("buf"):
            return "BUF"
        elif base_name.startswith("dfx") or base_name.startswith("dff"):
            return "DFF"
        elif base_name.startswith("mux"):
            return "MUX"
        elif base_name.startswith("conb"):
            return "CONB"
        elif base_name.startswith("tap"):
            return "TAP"
        elif base_name.startswith("fill"):
            return "FILL"
        else:
            # Extract first meaningful part (remove numbers)
            # e.g., "a21oi" -> "A21OI" but we want just the base
            base_clean = re.sub(r'\d+', '', base_name)
            if base_clean:
                return base_clean.upper()
            return base_name.upper().split("_")[0]
    
    # If no match, try to extract meaningful part
    # Remove common prefixes and suffixes
    normalized = cell_type.upper()
    # Remove library prefix if present
    normalized = re.sub(r'^SKY130_FD_SC_HD__', '', normalized)
    # Extract first part before numbers/underscores
    match = re.match(r'^([A-Z]+)', normalized)
    if match:
        return match.group(1)
    
    # Last resort: return uppercase
    return normalized


def validate_design(
    fabric_db: Dict[str, List[Dict[str, Any]]],
    logical_db: Dict[str, Any],
    design_name: str,
    output_file: Optional[str] = None
) -> bool:
    """
    Validate if the design can be built on the fabric.
    
    Compares required cell types from the design against available fabric slots.
    Exits with error code 1 if any cell type requirement exceeds availability.
    
    Args:
        fabric_db: Fabric database (from load_fabric_db)
        logical_db: Logical database (from load_logical_db)
        design_name: Name of the design being validated
        output_file: Optional path to save validation report (if None, only prints to console)
        
    Returns:
        True if design is valid, False otherwise (and exits with code 1)
    """
    # Collect output lines for potential file output
    output_lines = []
    
    def log_print(msg: str):
        """Print to console and optionally collect for file output"""
        print(msg)
        output_lines.append(msg)
    
    log_print(f"\n{'='*60}")
    log_print(f"Validating Design: {design_name}")
    log_print(f"{'='*60}\n")
    
    # Get required cell types from design
    required_type_counts = logical_db.get("type_counts", {})
    
    if not required_type_counts:
        log_print("ERROR: No cell types found in design netlist!")
        sys.exit(1)
    
    # Count fabric slots by normalized type
    fabric_slots_by_type = defaultdict(int)
    fabric_cells_by_type = defaultdict(list)
    
    for fabric_type, cells in fabric_db.items():
        fabric_slots_by_type[fabric_type] = len(cells)
        fabric_cells_by_type[fabric_type] = cells
    
    # Validate each required cell type
    validation_errors = []
    utilization_report = []
    
    log_print("Fabric Utilization Report:")
    log_print("-" * 60)
    
    # Group design cells by normalized type
    required_by_normalized = defaultdict(int)
    design_type_mapping = {}  # Map normalized -> original design types
    
    for design_type, count in required_type_counts.items():
        normalized = normalize_cell_type(design_type)
        required_by_normalized[normalized] += count
        if normalized not in design_type_mapping:
            design_type_mapping[normalized] = []
        design_type_mapping[normalized].append(design_type)
    
    # Check each normalized type
    for normalized_type, required_count in sorted(required_by_normalized.items()):
        available_count = fabric_slots_by_type.get(normalized_type, 0)
        
        if required_count > available_count:
            error_msg = (
                f"ERROR: {normalized_type}: Required {required_count}, "
                f"but only {available_count} available in fabric!"
            )
            validation_errors.append(error_msg)
            log_print(f" {error_msg}")
        else:
            utilization_pct = (required_count / available_count * 100) if available_count > 0 else 0.0
            utilization_report.append({
                "type": normalized_type,
                "required": required_count,
                "available": available_count,
                "utilization": utilization_pct
            })
            log_print(f" {normalized_type}: {required_count}/{available_count} used ({utilization_pct:.1f}%)")
    
    # Print summary
    log_print("\n" + "-" * 60)
    log_print("Summary:")
    log_print(f"  Total cell types in design: {len(required_by_normalized)}")
    log_print(f"  Total cell instances: {sum(required_by_normalized.values())}")
    log_print(f"  Validation errors: {len(validation_errors)}")
    
    # If there are errors, exit with code 1
    if validation_errors:
        log_print("\n" + "="*60)
        log_print("VALIDATION FAILED!")
        log_print("="*60)
        for error in validation_errors:
            log_print(f"  {error}")
        
        # Save to file if requested
        if output_file:
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, 'w') as f:
                f.write('\n'.join(output_lines))
            log_print(f"\nValidation report saved to: {output_file}")
        
        sys.exit(1)
    
    log_print("\n" + "="*60)
    log_print("VALIDATION PASSED!")
    log_print("="*60)
    
    # Save to file if requested
    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            f.write('\n'.join(output_lines))
        log_print(f"\nValidation report saved to: {output_file}")
    
    return True


def main():
    """
    Main entry point for the validator.
    
    Usage:
        python validator.py <design_name>
        
    Or set DESIGN environment variable:
        DESIGN=6502 python validator.py
    
    The validator expects:
    - fabric_db.json in the project root (pre-processed fabric database)
    - build/<design>/<design>_logical_db.json (pre-processed logical database)
    """
    import os
    
    # Get design name from command line or environment
    if len(sys.argv) > 1:
        design_name = sys.argv[1]
    elif "DESIGN" in os.environ:
        design_name = os.environ["DESIGN"]
    else:
        print("ERROR: Design name not provided!")
        print("Usage: python validator.py <design_name>")
        print("   or: DESIGN=<design_name> python validator.py")
        sys.exit(1)
    
    # Construct file paths
    fabric_db_path = "../build/fabric/fabric_db.json"
    logical_db_path = f"build/{design_name}/{design_name}_logical_db.json"
    
    try:
        # Load fabric database
        print("Loading fabric database...")
        fabric_db = load_fabric_db(fabric_db_path)
        
        # Count total cells in fabric
        total_fabric_cells = sum(len(cells) for cells in fabric_db.values())
        print(f"  Found {len(fabric_db)} cell types in fabric")
        print(f"  Total fabric cells: {total_fabric_cells}")
        
        # Load logical database
        print(f"\nLoading logical database: {logical_db_path}")
        logical_db = load_logical_db(logical_db_path)
        
        # Verify design name matches
        if "design" in logical_db and logical_db["design"] != design_name:
            print(f"  Warning: Design name mismatch! Expected '{design_name}', found '{logical_db['design']}'")
        
        print(f"  Found {len(logical_db['type_counts'])} cell types in design")
        print(f"  Total instances: {sum(logical_db['type_counts'].values())}")
        
        # Set output file path
        output_file = f"build/{design_name}/{design_name}_validation.rpt"
        
        # Validate design
        validate_design(fabric_db, logical_db, design_name, output_file)
        
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

