# Fabric Visualizer

## Basic run

---
```bash
python src/visualize.py \
  --fabric-db data/fabric_db.json \
  --out build/fabric/fabric_layout.png \
  --debug
```

## CLI Options (for visualize\_fabric\_db.py)


Required I/O
------------

*   **\--fabric-db PATH**Path to fabric\_db.json (master DB produced from fabric\_cells.yaml + pins.yaml). **Required**.
    
*   **\--out PATH**Output PNG path, e.g. build/fabric/fabric\_layout.png. **Required**.
    

Geometry & Fallbacks
--------------------

*   **\--slot-w FLOAT** (default: 0.46) – Fallback single-site **width (µm)** if a gate lacks width\_sites and w.
    
*   **\--slot-h FLOAT** (default: 2.72) – Fallback **row height (µm)** if DB doesn’t specify.
    

> The renderer prefers width\_sites \* site\_dimensions\_um.width. Otherwise it uses gate w; if missing, falls back to --slot-w. Height prefers site\_dimensions\_um.height, else --slot-h.

Coordinate System & Scaling
---------------------------

*   **\--y-origin {bottom,top}** (default: bottom) – Flip vertical origin (use bottom for lower-left physical origin).
    
*   **\--scale FLOAT** (default: auto) – Pixels per µm. If omitted, auto-fits to target width/height.
    
*   **\--target-width INT** (default: 6000) – Target canvas width (px) for auto-fit.
    
*   **\--target-height INT** (default: computed) – Optional auto-fit height (px).
    

Visual Style
------------

*   **\--alpha FLOAT** (default: 0.6) – Slot fill opacity (0..1).
    
*   **\--slot-fat-x FLOAT** (default: 0.0) – Add **pixels** to slot width post-scale (for poster “gap closing”).
    
*   **\--slot-fat-y FLOAT** (default: 0.0) – Add **pixels** to slot height post-scale.
    
*   **\--tile-grid-stride INT** (default: 50) – Draw a faint tile box every N tiles (0 disables).
    
*   **\--no-keepouts** – Hide corner keep-out overlays.
    
*   **\--title STRING** (default: Fabric Overview (Phase-1)) – Title text.
    

Canvas & UI
-----------

*   **\--ui-scale FLOAT** (default: 1.4) – Scales **only UI** (margins, fonts, legend).
    
*   **\--pin-label-mode {inline,outside,outside-smart,none,smart}** (default: outside-smart)
    
    *   inline: labels near pins inside die
        
    *   outside: label list on right + leaders
        
    *   outside-smart: split left/right, spaced to avoid collisions (recommended)
        
    *   smart: inline with overlap avoidance
        
    *   none: no labels
        
*   **\--pin-label-font INT** (default: 12) – Base pin label font size (px).
    
*   **\--no-core-dims / --no-die-dims / --no-rulers** – Hide dimension callouts and µm rulers.
    
*   **\--border-width INT** (default: 2) – Outer frame width in px (0 disables).
    
*   **\--tight** – “Die-only” render: no margins/title/legend/rulers; compact labels.
    

Debugging
---------

*   **\--debug** – Verbose summary: counts, bounds, die/core sizes, histogram, scaling.
    
*   **\--debug-samples INT** (default: 8) – How many sample slots to print.
    
*   **\--debug-cells** – One line per gate with µm→px coordinates/sizes.
    

Common Presets
--------------

### Dense, scaled view

```
python src/visualize.py \
  --fabric-db data/fabric_db.json \
  --out build/fabric/fabric_layout.png \
  --slot-w 0.46 --slot-h 2.72 \
  --alpha 0.5 --scale 10 \
  --y-origin bottom --debug
```

### Auto-fit poster with readable UI & rulers

```
python src/visualize.py \
  --fabric-db data/fabric_db.json \
  --out build/fabric/fabric_layout_poster.png \
  --alpha 0.4 --target-width 9000 \
  --ui-scale 1.6 --tile-grid-stride 25 \
  --pin-label-mode outside-smart --y-origin bottom
```
