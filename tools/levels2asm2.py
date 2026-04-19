#!/usr/bin/env python3
"""
levels2asm.py

Usage:
  python levels2asm.py level.txt tiles.s8085 > level_output.s8085

Description:
  Convert a simple ASCII level file (with legend) to 8085 assembly like the example in the prompt.

Assumptions / format:
  - Legend lines come first, one per line, e.g.
        . = TileEmpty #phony
        # = TileWallBrick #solid
        @ = TilePlayer #player
  - After a line that begins with "Level" comes exactly 8 lines each 24 chars wide.
  - tiles.s8085 contains tile labels such as:
        ;---------------------------------------
        TileWallBrick:
            db ...
    The script scans tiles.s8085 for labels ending with ":" and records their order (index).
  - SolidBitMap: 1 byte per column (24 bytes) where bit N (LSB=bit0) corresponds to row N (0..7).
  - Level data is emitted column-major: 24 rows (one per column), each "db" has 8 tile indices.
  - Characters mapped with tag "#phony" will still be allowed in the level but are treated as not producing a TileX equ (they map to a special label TE if provided).
"""

import sys
import re

if len(sys.argv) != 3:
    print("Usage: python levels2asm.py level.txt tiles.s8085", file=sys.stderr)
    sys.exit(2)

level_file = sys.argv[1]
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

# map tile name -> index (0-based)
tile_index = {name: i for i, name in enumerate(tile_labels)}

# --- parse level file ---
legend = {}   # char -> (tile_name_or_None, set(tags))
grid = []
with open(level_file, 'r', encoding='utf-8') as f:
    lines = [ln.rstrip('\n') for ln in f]

i = 0
# parse legend lines until a line that starts with "Level"
while i < len(lines) and not lines[i].strip().startswith("Level"):
    line = lines[i].strip()
    i += 1
    if not line:
        continue
    # expected: <char> = <TileName> #tag #tag...
    m = re.match(r'^(.?)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$', line)
    if not m:
        continue
    ch = m.group(1)
    tile = m.group(2)
    tags_str = m.group(3).strip()
    tags = set(re.findall(r'#([A-Za-z0-9_]+)', tags_str))
    legend[ch] = (tile, tags)

# advance past "Level" line
while i < len(lines) and not lines[i].strip().startswith("Level"):
    i += 1
if i < len(lines) and lines[i].strip().startswith("Level"):
    i += 1

# collect the next non-empty 8 lines (allow blank lines between)
while i < len(lines) and len(grid) < 8:
    ln = lines[i]
    i += 1
    if ln.strip() == '':
        continue
    grid.append(ln.rstrip())
if len(grid) != 8:
    print("Error: expected 8 non-empty level rows after 'Level'", file=sys.stderr)
    sys.exit(2)

# validate width 24
for r in grid:
    if len(r) != 24:
        print("Error: each level row must be exactly 24 characters wide", file=sys.stderr)
        sys.exit(2)

# --- compute solid bitmap and player position(s) ---
# columns 0..23, rows 0..7 (row 0 is top)
solid_bytes = [0] * 24
player_positions = []  # list of (x,y)
# Also build tile indices matrix [col][row]
col_tiles = [[None]*8 for _ in range(24)]

for y in range(8):
    row = grid[y]
    for x in range(24):
        ch = row[x]
        if ch not in legend:
            print(f"Error: character '{ch}' at ({x},{y}) not found in legend", file=sys.stderr)
            sys.exit(2)
        tile_name, tags = legend[ch]
        # set solid bit if tag 'solid'
        if 'solid' in tags:
            solid_bytes[x] |= (1 << y)
        if 'player' in tags:
            player_positions.append((x,y))
        # determine tile index; if tag 'phony' treat tile_name as placeholder (we still emit a name)
        if 'phony' in tags:
            # store special marker like None (we'll emit TE later)
            col_tiles[x][y] = ('__PHONY__', None)
        else:
            if tile_name not in tile_index:
                print(f"Error: tile '{tile_name}' not found in {tiles_file}", file=sys.stderr)
                sys.exit(2)
            col_tiles[x][y] = ('TILE', tile_index[tile_name], tile_name)

# Validate player positions: 1 allowed
if not player_positions or len(player_positions) == 0:
    print(f"Error: exactly one player must be placed", file=sys.stderr)
    sys.exit(2)
elif len(player_positions) > 1:
    coords = ", ".join(f"({x},{y})" for x,y in player_positions)
    print(f"Error: multiple player positions found at: {coords}", file=sys.stderr)
    sys.exit(2)

px, py = player_positions[0]

# Determine which tile names are referenced (non-phony) to emit EQUs for convenience.
referenced_tiles = {}
for x in range(24):
    for y in range(8):
        entry = col_tiles[x][y]
        if entry is None:
            continue
        if entry[0] == 'TILE':
            _, idx, name = entry
            referenced_tiles[name] = idx

# Prepare a reverse mapping to produce short labels like TE, TW etc.
# We'll create LABEL equ lines for each unique tile used, using the tile name prefixed with nothing.
# But to follow the example, produce small aliases: take up to two-letter alias from tile name:
alias_map = {}
def make_alias(name):
    # common replacements: TileEmpty -> TE, TileWallBrick -> TW, TilePlayer -> TP
    if name.startswith('Tile'):
        core = name[4:]
    else:
        core = name
    parts = re.findall(r'[A-Z][a-z]*', core)
    if parts:
        alias = ''.join(p[0] for p in parts)[:2].upper()
    else:
        alias = core[:2].upper()
    # ensure uniqueness
    base = alias
    n = 1
    while alias in alias_map.values():
        alias = f"{base}{n}"
        n += 1
    return alias

for name in referenced_tiles:
    alias_map[name] = make_alias(name)

# --- emit assembly ---
out = []

out.append(";---------------------------------------")
out.append("; Loaded level")
out.append(";---------------------------------------")
out.append("")
out.append("InitialPlayerPosition:")
out.append(f".Y: db {py}")
out.append(f".X: db {px}")
out.append("")
out.append("SolidBitMap: ; 1 byte per column each bit signifies solid wall")
out.append("\t; generated from level file")

for b in solid_bytes:
    out.append(f"\tdb 0b{b:08b}")

out.append("")

# Emit EQUs for aliases
for name, idx in referenced_tiles.items():
    alias = alias_map[name]
    out.append(f"{alias} equ ({name} - Tiles)")
# Also emit a phony alias if TileEmpty was marked phony in legend
# If legend had a phony mapping to some label, still produce an alias if that label exists in tiles.s8085
# (Already handled above.)

out.append("Level:")
# emit 24 db lines, one per column, each with 8 entries (row 0..7)
for x in range(24):
    entries = []
    for y in range(8):
        entry = col_tiles[x][y]
        if entry[0] == 'TILE':
            _, idx, name = entry
            alias = alias_map[name]
            entries.append(f"{alias}")
        else:
            # phony -> emit TE if present in legend mapping to a name and that name exists; else emit 0
            # find which legend char produced this phony
            # We'll search legend for a phony tile mapping that matches the character at grid[y][x]
            ch = grid[y][x]
            tile_name, tags = legend[ch]
            if tile_name in tile_index:
                alias = make_alias(tile_name) if tile_name not in alias_map else alias_map[tile_name]
                entries.append(alias)
            else:
                entries.append("TE")  # fallback to TE
    out.append("\tdb  " + ",  ".join(entries))

# Print result
print("\n".join(out))
