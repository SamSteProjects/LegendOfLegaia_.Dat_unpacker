Legend of Legaia PROT.DAT Unpacker (lol_dat_unpacker_2.0.py)

A reverse-engineered extractor for Legend of Legaia’s PROT.DAT, rebuilt using the same delta-math logic identified inside the game’s executable via Ghidra.
This tool reconstructs the original table-of-contents (TOC) math used by the PS1 engine to locate, size, and load internal asset banks such as battle models, maps, and texture packs.

Features

In-Game Accurate Offsets: Replicates the functions discovered in Ghidra (Prot_TOC_Delta, start_lba, size_sectors) to calculate file positions directly from the internal TOC.

Automatic TOC Detection: Finds the header block dynamically (0x000 or 0x800) and verifies the number of files and header sector size.

TIM Pack Recognition: Detects and extracts texture containers (TIM packs) using structural heuristics from the retail binary.

Structured Output: Generates extracted .BIN assets, decomposed .TIM textures, and metadata in both XML and CSV index formats.

Strong Validation: Includes bounds checks, header guards, and sector-level consistency rules to prevent false extractions.

Output Example
PROT.DAT/
 ├── Prot_0.BIN
 ├── Prot_1.BIN
 ├── Prot_1/
 │    ├── Prot_1_0.TIM
 │    ├── Prot_1_1.TIM
 │    └── ...
 ├── DATInfo.xml
 └── index.csv

Usage
python lol_dat_unpacker_2.0.py PROT.DAT -o ./PROT_EXTRACTED

Requirements

Python 3.10+

Standard library only (no external dependencies)

Notes

This unpacker forms the foundation for reconstructing Legend of Legaia’s internal file system.
It exposes the sector math and delta-based addressing the engine used to resolve packed assets inside PROT.DAT, enabling further analysis of LZSS blocks, TMD models, MIM textures, and sound banks.
