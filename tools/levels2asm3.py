#!/usr/bin/env python3
"""
convert_sokoban_levels.py

Usage:
  python convert_sokoban_levels.py levels.txt tiles.s8085 > levels_output.s8085

Features:
  - Accepts multiple levels in one input file. Each level starts with a line "LevelName"
    (any non-empty token not matching legend syntax) followed by 8 lines, each 24 chars wide.
  - Legend lines at top map characters to tile names and tags:
        . = TileEmpty #phony
        # = TileWallBrick #solid #static
        @ = TileBoxKidDown #player
        s = TileCrateStone
  - Parses tiles.s8085 for tile labels (order -> indices).
  - Produces global tile alias equates at top for all non-phony tiles used in any level.
  - Emits per-level blocks:
      <LevelName>:
        .PlayerStartY/.PlayerStartX (errors if >1 player in level)
        .SolidBitMap: 24 db bytes (one per column, bit y = solid)
        .TileOffsets: 24 lines (columns) each with 8 entries (row0..row7)
  - Exits with error if a non-phony tile referenced isn't found in tiles.s8085
  - Enforces rows are exactly 24 characters and exactly 8 rows per level
"""

import sys
import re
from collections import OrderedDict

if len(sys.argv) != 3:
    print("Usage: python convert_sokoban_levels.py levels.txt tiles.s8085", file=sys.stderr)
    sys.exit(2)

levels_file = sys.argv[1]
tiles_file = sys.argv[2]

# --- parse tiles.s8085 to get tile label order ---
tile_labels = []
label_re = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(;.*)?$')
with open(tiles_file, 'r', encoding='utf-8') as f:
    for line in f:
        m = label_re.match(line.strip())
        if m:
            name = m.group(1)
            tile_labels.append(name)
tile_index = {name: i for i, name in enumerate(tile_labels)}

# --- parse levels file ---
with open(levels_file, 'r', encoding='utf-8') as f:
    raw_lines = [ln.rstrip('\n') for ln in f]

legend = {}   # char -> (tile_name, set(tags))
i = 0
# parse legend until we hit a line that appears to be a level name or empty
legend_re = re.compile(r'^(.?)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$')
while i < len(raw_lines):
    line = raw_lines[i].strip()
    if line == "":
        i += 1
        continue
    m = legend_re.match(line)
    if not m:
        break
    ch = m.group(1)
    tile = m.group(2)
    tags = set(re.findall(r'#([A-Za-z0-9_]+)', m.group(3) or ""))
    legend[ch] = (tile, tags)
    i += 1

# Now parse multiple levels: each level starts with a non-empty line that is NOT legend
levels = OrderedDict()  # name -> list of 8 strings
while i < len(raw_lines):
    # skip blank lines
    if raw_lines[i].strip() == "":
        i += 1
        continue
    level_name = raw_lines[i].strip()
    i += 1
    # collect next 8 non-empty lines as the level rows
    rows = []
    while i < len(raw_lines) and len(rows) < 8:
        ln = raw_lines[i]
        i += 1
        if ln.strip() == "":
            continue
        rows.append(ln.rstrip())
    if len(rows) != 8:
        print(f"Error: level '{level_name}' expects 8 non-empty rows, found {len(rows)}", file=sys.stderr)
        sys.exit(2)
    # validate width 24
    for r in rows:
        if len(r) != 24:
            print(f"Error: level '{level_name}' row length must be 24 chars: '{r}'", file=sys.stderr)
            sys.exit(2)
    levels[level_name] = rows

if not levels:
    print("Error: no levels found in input", file=sys.stderr)
    sys.exit(2)

# --- process levels to compute per-level data and collect referenced tiles ---
all_referenced_tiles = OrderedDict()  # tile_name -> index (for non-phony tiles)
per_level_data = OrderedDict()

for lname, grid in levels.items():
    # grid: list of 8 rows (y=0..7), each 24 chars (x=0..23)
    solid_bytes = [0] * 24
    player_positions = []
    col_tiles = [[None]*8 for _ in range(24)]
    for y in range(8):
        row = grid[y]
        for x in range(24):
            ch = row[x]
            if ch not in legend:
                print(f"Error: character '{ch}' at ({x},{y}) in level '{lname}' not found in legend", file=sys.stderr)
                sys.exit(2)
            tile_name, tags = legend[ch]
            if 'solid' in tags:
                solid_bytes[x] |= (1 << y)
            if 'player' in tags:
                player_positions.append((x,y))
            if 'phony' in tags:
                col_tiles[x][y] = ('PHONY', tile_name)  # store tile_name for potential TE mapping
            else:
                if tile_name not in tile_index:
                    print(f"Error: tile '{tile_name}' used in level '{lname}' not found in {tiles_file}", file=sys.stderr)
                    sys.exit(2)
                idx = tile_index[tile_name]
                col_tiles[x][y] = ('TILE', tile_name, idx)
                if tile_name not in all_referenced_tiles:
                    all_referenced_tiles[tile_name] = idx

    # Validate player count: error if more than one
    if len(player_positions) > 1:
        coords = ", ".join(f"({x},{y})" for x,y in player_positions)
        print(f"Error: multiple player positions found in level '{lname}': {coords}", file=sys.stderr)
        sys.exit(2)
    px, py = player_positions[0] if player_positions else (0,0)

    per_level_data[lname] = {
        'grid': grid,
        'solid_bytes': solid_bytes,
        'col_tiles': col_tiles,
        'player': (px, py)
    }

# --- create alias map for all referenced tiles (consistent across levels) ---
alias_map = {}
def make_alias(name, existing_aliases):
    # prefer TileEmpty -> TE, TileWallBrick -> WB etc by taking initials of camel-case
    if name.startswith('Tile'):
        core = name[4:]
    else:
        core = name
    parts = re.findall(r'[A-Z][a-z]*|[a-z]+', core)
    if parts:
        alias = ''.join(p[0] for p in parts).upper()[:2]
    else:
        alias = core[:2].upper()
    base = alias
    n = 1
    while alias in existing_aliases.values():
        alias = f"{base}{n}"
        n += 1
    return alias

for name in list(all_referenced_tiles.keys()):
    alias_map[name] = make_alias(name, alias_map)

# Ensure TE exists for empty/phony fallback if legend mapped a phony to some name or '.' used
# If TileEmpty is present in tile labels, map TE to it; else TE is left as fallback only as a label (no equ)
if 'TileEmpty' in tile_index and 'TileEmpty' not in alias_map:
    alias_map['TileEmpty'] = 'TE'
elif 'TileEmpty' in alias_map:
    # ensure alias is TE if possible
    alias_map['TileEmpty'] = alias_map['TileEmpty']  # keep existing

# --- emit assembly ---
out = []

out.append(";")
out.append("; Tile offset definitions")
out.append(";")
out.append("")

# Emit global equs for referenced tiles (sorted in order of first usage)
for name, idx in all_referenced_tiles.items():
    alias = alias_map[name]
    out.append(f"{alias} equ ({name} - Tiles)")
out.append("") 

# Emit per-level blocks
for lname, data in per_level_data.items():
    out.append(";-------------------------------------------------------------------------------")
    out.append(f"{lname}:")
    out.append(";-------------------------------------------------------------------------------")
    out.append("")
    px, py = data['player']
    out.append(f".PlayerStartY: db {py}")
    out.append(f".PlayerStartX: db {px}")
    out.append("")
    out.append(".SolidBitMap: ; 1 byte per column each bit signifies solid wall")
    for b in data['solid_bytes']:
        out.append(f"\tdb 0b{b:08b}")
    out.append("")
    out.append(".TileOffsets:")
    # 24 columns
    for x in range(24):
        entries = []
        for y in range(8):
            entry = data['col_tiles'][x][y]
            if entry[0] == 'TILE':
                _, tile_name, _ = entry
                alias = alias_map[tile_name]
                entries.append(alias)
            else:  # PHONY -> map to TE if TileEmpty alias exists, otherwise TE literal
                # If the phony tile maps to a real tile name that was in tiles.s8085, use its alias,
                # otherwise fallback to TE
                _, tile_name = entry
                if tile_name in alias_map:
                    entries.append(alias_map[tile_name])
                elif 'TileEmpty' in alias_map:
                    entries.append(alias_map['TileEmpty'])
                else:
                    entries.append("TE")
        out.append("\tdb  " + ",  ".join(entries))
    out.append("")

print("\n".join(out))
