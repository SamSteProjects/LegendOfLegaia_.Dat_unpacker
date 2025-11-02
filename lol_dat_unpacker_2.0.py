#!/usr/bin/env python3
# lol_dat_unpacker_from_game_math.py
# Legend of Legaia PROT.DAT extractor using the in-game TOC/delta math.

import argparse, base64, csv, struct
from pathlib import Path
import xml.etree.ElementTree as ET

SECTOR = 0x800
def u32le(b, o=0): return struct.unpack_from("<I", b, o)[0]
def i32le(b, o=0): return struct.unpack_from("<i", b, o)[0]

# ---------- Header / TOC ----------

def probe_header(dat: bytes, hdr_off: int):
    # Mirrors Neto: fileNum = *(+0x04)+1, headerSize(sectors) = *(+0x08)
    if hdr_off + 12 > len(dat): return None
    file_num = i32le(dat, hdr_off + 0x04) + 1
    header_sectors = i32le(dat, hdr_off + 0x08)
    if file_num <= 1 or header_sectors <= 0: return None
    if hdr_off + header_sectors * SECTOR > len(dat): return None
    return file_num, header_sectors

def detect_header(dat: bytes):
    for off in (0x000, 0x800):
        got = probe_header(dat, off)
        if got:
            file_num, header_sectors = got
            return off, file_num, header_sectors
    return None

def load_toc(dat: bytes, hdr_off: int, header_sectors: int):
    """
    TOC starts at hdr_off + 0x08 (first two u32 are header fields).
    Units are sectors (2048 bytes). We expose it as a list of u32.
    """
    start = hdr_off + 0x08
    end   = hdr_off + header_sectors * SECTOR
    hdr   = dat[start:end]
    return list(struct.unpack("<" + "I" * (len(hdr) // 4), hdr))

# ---------- Game-observed math ----------

def delta(toc, i):
    # Prot_TOC_Delta(i) == toc[i+3] - toc[i+2]   (sectors)
    return toc[i + 3] - toc[i + 2]

def start_lba(toc, p):
    # Δ(p)+Δ(p+1)+Δ(p+2) = toc[p+5] - toc[p+2]
    return toc[p + 5] - toc[p + 2]

def size_sectors(toc, p):
    # Δ(p+1)+Δ(p+2)+4 = toc[p+5] - toc[p+3] + 4
    return (toc[p + 5] - toc[p + 3]) + 4

# ---------- TIM pack helpers (with stronger guards) ----------

def is_tim_pack(blob: bytes) -> bool:
    # Heuristic from Neto + extra sanity: header area must exist.
    if len(blob) < 12:  # needs at least 4-byte hdr + u32 count + first table entry
        return False
    if not (blob[3] == 0x01 and blob[2] < 0x10):
        return False
    tim_num = i32le(blob, 4)
    # Table is at 8..(8+4*tim_num); also entries themselves must plausibly fit
    if tim_num < 0 or 8 + 4 * tim_num > len(blob):
        return False
    return True

def unpack_tim_pack(out_dir: Path, stem: str, blob: bytes):
    tim_header = blob[:4]
    tim_num = i32le(blob, 4)
    table_start = 8

    # Hard guard: table must fit entirely
    table_end = table_start + 4 * tim_num
    if table_end > len(blob):
        # Bail out gracefully; treat as non-tim pack by returning empty list
        return tim_header, []

    # Build offsets; each entry gives a word index; byteOffset = entry*4 + 4
    tim_offsets = []
    for x in range(tim_num):
        entry = i32le(blob, table_start + 4 * x)
        off = entry * 4 + 4
        if off < 0 or off > len(blob):
            # Skip bogus entries
            continue
        tim_offsets.append(off)

    # Ensure sorted, unique, and clamp with sentinel
    tim_offsets = sorted(set(tim_offsets))
    tim_offsets.append(len(blob))

    subdir = out_dir / stem
    subdir.mkdir(parents=True, exist_ok=True)

    rel_written = []
    for x in range(len(tim_offsets) - 1):
        s, e = tim_offsets[x], tim_offsets[x + 1]
        if not (0 <= s < e <= len(blob)): 
            continue
        item = blob[s:e]
        ext = "TIM" if item and item[0] == 0x10 else "BIN"
        name = f"{stem}_{x}.{ext}"
        (subdir / name).write_bytes(item)
        rel_written.append(f"{stem}/{name}")
    return tim_header, rel_written

# ---------- Output helpers ----------

def write_xml(xml_path: Path, dat_stem: str, files_meta):
    root = ET.Element("FILES", {"Name": dat_stem})
    for rec in files_meta:
        fe = ET.SubElement(root, "FILE", {
            "Name": rec["Name"],
            "Header": base64.b64encode(rec["Header"]).decode() if rec["Header"] else ""
        })
        for t in rec["TIMs"]:
            ET.SubElement(fe, "TIM", {"Name": t})
    xml_path.write_text(ET.tostring(root, encoding="unicode"))

def write_index_csv(csv_path: Path, rows):
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["p_index", "offset_hex", "size", "is_tim_pack", "bin_path"])
        w.writerows(rows)

# ---------- Extract ----------

def extract(dat_path: Path, out_dir: Path):
    dat = dat_path.read_bytes()
    dat_stem = dat_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    got = detect_header(dat)
    if not got:
        raise SystemExit("Header not recognized (tried 0x00 and 0x800).")
    hdr_off, file_num, header_sectors = got
    header_size = header_sectors * SECTOR

    print(f"[info] header_off=0x{hdr_off:X}, header_size=0x{header_size:X}, file_num={file_num}")

    toc = load_toc(dat, hdr_off, header_sectors)


    # Optional sanity: the TOC (now starting at +0x08) should be mostly non-decreasing
    bad = next((i for i in range(min(len(toc)-1, 64)) if toc[i + 1] < toc[i]), None)
    if bad is not None:
        print(f"[warn] TOC shows a drop near index {bad}: {toc[bad]} -> {toc[bad+1]} (may be expected in early header words)")

    files_meta, csv_rows = [], []

    for p in range(file_num - 1):
        lba   = start_lba(toc, p)
        nsec  = size_sectors(toc, p)

        start = lba * SECTOR
        size  = nsec * SECTOR
        end   = start + size

        if start < 0 or size <= 0 or end > len(dat):
            print(f"[skip] p={p} off=0x{start:X} size=0x{size:X} (out of bounds)")
            continue

        blob = dat[start:end]
        stem = f"{dat_stem}_{p}"
        bin_path = out_dir / f"{stem}.BIN"
        bin_path.write_bytes(blob)

        rec = {"Name": f"{stem}.BIN", "Header": b"", "TIMs": []}
        timpack = False
        if is_tim_pack(blob):
            try:
                timpack = True
                hdr, tims = unpack_tim_pack(out_dir, stem, blob)
                rec["Header"], rec["TIMs"] = hdr, tims
            except Exception as e:
                print(f"[warn] TIM unpack failed for p={p}: {e}")
                timpack = False

        files_meta.append(rec)
        csv_rows.append([p, f"0x{start:08X}", size, int(timpack), str(bin_path.relative_to(out_dir))])

    write_xml(out_dir / "DATInfo.xml", dat_stem, files_meta)
    write_index_csv(out_dir / "index.csv", csv_rows)
    print(f"[+] Extracted {len(csv_rows)} subfiles to {out_dir}")

# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="LoL PROT.DAT extractor (uses in-game TOC delta math)")
    ap.add_argument("input", help="Path to PROT.DAT")
    ap.add_argument("-o", "--out", default=None, help="Output dir (default: alongside input, no .DAT)")
    args = ap.parse_args()

    dat_path = Path(args.input)
    out_dir = Path(args.out) if args.out else dat_path.with_suffix("")
    extract(dat_path, out_dir)

if __name__ == "__main__":
    main()
