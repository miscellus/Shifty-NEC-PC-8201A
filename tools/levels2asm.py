#!/usr/bin/env python3
"""
levels2asm.py

Usage:
  python3 levels2asm.py maps.txt tiles.s8085 out.asm

Input plaintext map format (example):
. Empty
# TileWallBrick
@ TileBoxKid

Map1
# # # ... (24 cols)
...
(8 rows)

Special: the label "Empty" is allowed in the maps even if tiles.s8085 does not define it;
it will be mapped to index EMPTY_INDEX (default 0). If tiles.s8085 defines "Empty",
that index is used instead.

You may have multiple maps in the same file: each map starts with a name line (no leading whitespace)
followed by exactly 8 rows of 24 tokens (tokens separated by spaces). Tokens are single chars
mapped to labels by the header lines at top.

tiles.s8085 should contain tile labels in the order they appear in your tiles bank (one label
per tile, typically as "Label:" lines). The script assigns indices 0.. based on that order.

Output:
  Assembly file with a label per map (Map_<name>) containing compressed bytes (RLE marker 0xFF).
"""
from pathlib import Path
import sys
import re

RLE_MARKER = 0xFF
WIDTH = 24
HEIGHT = 8
PACKED_BYTES = (WIDTH * HEIGHT) // 2  # 192/2 = 96
EMPTY_INDEX = 0

def load_tiles_order(tiles_path):
    text = Path(tiles_path).read_text(encoding='utf-8')
    labels = []
    # find lines that look like labels: start of line, word chars and colon
    for line in text.splitlines():
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*:', line)
        if m:
            labels.append(m.group(1))
    if not labels:
        raise SystemExit(f"No labels found in {tiles_path}")
    return labels  # index = position

def parse_maps(txt_path):
    lines = [ln.rstrip() for ln in Path(txt_path).read_text(encoding='utf-8').splitlines()]
    # parse mapping header: lines like "<char> <label>"
    mapping = {}
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln == '':
            i += 1
            break
        # if line appears to be a map name (no space), stop header
        if re.match(r'^[A-Za-z0-9_]+$', ln) and (i+1)<len(lines) and lines[i+1].strip().split():
            # This could be a map name if next lines are grid rows.
            # But safer: header lines expected to have a space
            if ' ' not in ln:
                # assume header ended
                break
        parts = ln.split(None, 1)
        if len(parts) != 2:
            raise SystemExit(f"Bad mapping header line: '{lines[i]}'")
        ch, label = parts[0], parts[1].strip()
        if len(ch) != 1:
            raise SystemExit(f"Map char must be single char, got '{ch}' on line: {lines[i]}")
        mapping[ch] = label
        i += 1

    # now parse maps: expecting blocks with a name line then 8 rows
    maps = {}
    while i < len(lines):
        # skip blank lines
        while i < len(lines) and lines[i].strip() == '':
            i += 1
        if i >= len(lines):
            break
        name = lines[i].strip()
        i += 1
        # read next 8 non-blank lines as rows
        rows = []
        while len(rows) < HEIGHT and i < len(lines):
            if lines[i].strip() == '':
                i += 1
                continue
            rows.append(lines[i].strip())
            i += 1
        if len(rows) != HEIGHT:
            raise SystemExit(f"Map '{name}' expects {HEIGHT} rows, got {len(rows)}")
        # parse tokens per row (split by whitespace)
        grid = []
        for r in rows:
            toks = r.split()
            if len(toks) != WIDTH:
                raise SystemExit(f"Map '{name}' row expected {WIDTH} tokens, got {len(toks)}: '{r}'")
            grid.append(toks)
        maps[name] = grid
    return mapping, maps

def map_chars_to_indices(mapping, maps, tiles_order):
    # build label -> index map from tiles_order
    label2idx = {lab: idx for idx, lab in enumerate(tiles_order)}
    out_maps = {}
    for name, grid in maps.items():
        idx_grid = []
        for y in range(HEIGHT):
            for x in range(WIDTH):
                ch = grid[y][x]
                if ch not in mapping:
                    raise SystemExit(f"Unknown map char '{ch}' in map '{name}' at {x},{y}")
                label = mapping[ch]
                if label in label2idx:
                    idx = label2idx[label]
                else:
                    if label == "Empty":
                        idx = EMPTY_INDEX
                    else:
                        raise SystemExit(f"Label '{label}' (from char '{ch}') not found in tiles.s8085")
                if idx >= 16:
                    raise SystemExit(f"Tile index for '{label}' >=16 (only 0..15 supported)")
                idx_grid.append(idx)
        if len(idx_grid) != WIDTH*HEIGHT:
            raise SystemExit("internal size mismatch")
        out_maps[name] = idx_grid
    return out_maps

def pack_nibbles(idx_list):
    packed = bytearray()
    for i in range(0, len(idx_list), 2):
        a = idx_list[i] & 0xF      # left tile -> low nibble
        b = idx_list[i+1] & 0xF    # right tile -> high nibble
        packed.append((b<<4) | a)
    if len(packed) != PACKED_BYTES:
        raise RuntimeError("packed size mismatch")
    return packed

def rle_encode(data: bytes):
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        v = data[i]
        j = i+1
        while j < n and data[j] == v and (j-i) < 255:
            j += 1
        run_len = j - i
        if run_len >= 3 or v == RLE_MARKER:
            out.append(RLE_MARKER)
            out.append(run_len if run_len < 256 else 255)
            out.append(v)
            i = j
        else:
            out.append(v)
            i += 1
    return out

def emit_asm(out_path, maps_compressed):
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("; Generated by levels2asm.py\n\n")
        for name, comp in maps_compressed.items():
            label = f"Level_{re.sub(r'[^0-9A-Za-z_]', '_', name)}"
            f.write(f"{label}:\n")
            # write length as two bytes (big-endian) then data
            f.write(f"\t; compressed length = {len(comp)}\n")
            # output in db chunks
            if len(comp) == 0:
                f.write("\tdb 0\n\n")
                continue
            for i in range(0, len(comp), 16):
                chunk = comp[i:i+16]
                f.write("\tdb " + ", ".join(f"0x{b:02X}" for b in chunk) + "\n")
            f.write("\n")
    print(f"Wrote {out_path} ({len(maps_compressed)} maps)")

def main(args):
    if len(args) != 4:
        print("Usage: levels2asm.py maps.txt tiles.s8085 out.asm")
        return 1
    maps_txt, tiles_s, out_asm = args[1], args[2], args[3]
    tiles_order = load_tiles_order(tiles_s)
    mapping, maps = parse_maps(maps_txt)
    mapped = map_chars_to_indices(mapping, maps, tiles_order)
    maps_compressed = {}
    for name, idx_list in mapped.items():
        packed = pack_nibbles(idx_list)
        comp = rle_encode(packed)
        maps_compressed[name] = comp
    emit_asm(out_asm, maps_compressed)
    return 0

if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
