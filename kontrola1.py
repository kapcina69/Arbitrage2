# kontrola1.py
# -*- coding: utf-8 -*-
"""
Ovaj skript:
1. Učita kvote_arbitraza_FULL.txt
2. Gleda svaki meč kao blok (od header linije do separator linije crtica)
3. Ako u tom meču postoji bar jedna kladionica koja ima manje od 2 kvote
   u target marketima (1, X, 2, 0-2, 3+), ceo meč se briše iz izlaza.
   Inače meč ostaje 1:1.
4. Sve linije unutar preživelih mečeva ostaju identične
   (ne diramo "Najveća...", "Arbitraža...", itd.)
5. Original fajl se bekapuje (*.bak), a zatim prepisuje filtriranom verzijom.

Dakle: "prljav" meč => kompletno izbacivanje.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

# ======================================================
# PODEŠAVANJE FAJLOVA
# ======================================================
INPUT_FILE = Path("ALL_MATCHES_AND_ARBS/kvote_arbitraza_FULL.txt")
BACKUP_FILE = INPUT_FILE.with_suffix(INPUT_FILE.suffix + ".bak")

# ======================================================
# REGEX PATTERNI
# ======================================================

# Header linija meča, npr:
# 20:00   25.10.   [Belgija 2]
RE_HEADER = re.compile(
    r"^(?P<time>\d\d:\d\d)\s+(?P<date>\d\d\.\d\d\.)\s+\[(?P<liga>.+?)\]\s*$"
)

# Linija sa timovima:
# Eupen  vs  U23 Genk
RE_VS = re.compile(
    r"^\s*(?P<t1>.+?)\s+vs\s+(?P<t2>.+?)\s*$",
    re.IGNORECASE
)

# Linija kladionice:
# - BalkanBet  1=1.53  |  X=4  |  2=5.65  |  0-2=2.15  |  3+=1.62 ...
RE_BOOKMAKER_LINE = re.compile(
    r"^\s*-\s*(?P<bkm>\S+)\s+(?P<rest>.+)$"
)

# Kvote po marketima koji nas zanimaju:
# 1=..., X=..., 2=..., 0-2=..., 3+=...
RE_KVOTA = re.compile(
    r"(^|\|)\s*(?P<key>1|X|2|0-2|3\+)\s*=\s*(?P<val>[0-9]+(?:\.[0-9]+)?)"
)

SEPARATOR_MIN_DASHES = 5  # linija sa ----- je kraj meča
TARGET_MARKETS = ["1", "X", "2", "0-2", "3+"]


def is_separator(line: str) -> bool:
    s = line.strip()
    return len(s) >= SEPARATOR_MIN_DASHES and set(s) == {"-"}


def parse_markets(rest: str) -> Dict[str, float]:
    """
    Izvuče target kvote iz jedne bookmaker linije.
    """
    mk: Dict[str, float] = {}
    for m in RE_KVOTA.finditer(rest):
        key = m.group("key")
        val_s = m.group("val")
        try:
            kv = float(val_s)
        except ValueError:
            continue
        mk[key] = kv
    return mk


def match_block_has_bad_bookmaker(block_lines: List[str]) -> Tuple[bool, List[str], str, str]:
    """
    Gleda linije jednog meča (od header-a do separator-a, separator uključen).
    Vraća:
      (ima_lošu_kladionicu, bad_bookies[], header_info, vs_info)

    ima_lošu_kladionicu = True ako je bar jedna kladionica imala <2 kvote.
    """

    bad_bookies: List[str] = []
    header_info = ""
    vs_info = ""

    for ln in block_lines:
        # zapamti header i vs samo da eventualno prijavimo šta smo obrisali
        if not header_info:
            if RE_HEADER.match(ln):
                header_info = ln.strip()
        if not vs_info:
            if RE_VS.match(ln):
                vs_info = ln.strip()

        # proveri da li je bookmaker linija
        mb = RE_BOOKMAKER_LINE.match(ln)
        if not mb:
            continue

        bkm = mb.group("bkm").strip()
        rest = mb.group("rest")

        markets = parse_markets(rest)
        # prebroj koliko target marketa postoji
        num_valid = sum(1 for mkt in TARGET_MARKETS if mkt in markets)

        if num_valid < 2:
            bad_bookies.append(bkm)

    return (len(bad_bookies) > 0, bad_bookies, header_info, vs_info)


def split_into_match_blocks(lines: List[str]) -> List[List[str]]:
    """
    U fajlu:
    [HEADER]
    ...
    --------------------------------------------------------------------------------------
    [HEADER]
    ...
    --------------------------------------------------------------------------------------
    ...

    Ovo vrati listu blokova po meču,
    gde je svaki blok lista linija od headera do separatora (separator uključen).
    Napomena: ako poslednji meč nema separator, i dalje ga vraćamo.
    """

    blocks: List[List[str]] = []
    curr_block: List[str] = []
    in_match = False

    for ln in lines:
        if RE_HEADER.match(ln):
            # ako je već počeo jedan blok, push ga pre otvaranja novog
            if in_match and curr_block:
                blocks.append(curr_block)
            # start novog bloka
            curr_block = [ln]
            in_match = True
        else:
            if in_match:
                curr_block.append(ln)

        # ako je separator -> kraj bloka
        if in_match and is_separator(ln):
            blocks.append(curr_block)
            curr_block = []
            in_match = False

    # ako smo završili fajl bez separatora za poslednji blok
    if in_match and curr_block:
        blocks.append(curr_block)

    return blocks


def kontrolisi_i_ocisti():
    # 1) učitaj original fajl
    orig_lines: List[str] = INPUT_FILE.read_text(
        encoding="utf-8",
        errors="ignore"
    ).splitlines()

    # 2) napravi .bak
    BACKUP_FILE.write_text("\n".join(orig_lines) + "\n", encoding="utf-8")

    # 3) podeli fajl na blokove/mečeve
    blocks = split_into_match_blocks(orig_lines)

    cleaned_blocks: List[List[str]] = []

    for block in blocks:
        has_bad, bad_bookies, header_info, vs_info = match_block_has_bad_bookmaker(block)

        if has_bad:
            # ceo meč brišemo iz izlaznog fajla
            print("--------------------------------------------------")
            print("OBRISAN CEO MEČ ZBOG KLADIONICE SA SAMO JEDNOM KVOTOM:")
            if header_info:
                print(header_info)
            if vs_info:
                print(vs_info)
            if bad_bookies:
                print("\nProblematične kladionice:")
                for b in bad_bookies:
                    print(f"  - {b}")
            print("--------------------------------------------------\n")
            continue  # skip ovaj blok u cleaned_blocks

        # nema loših kladionica -> blok ostaje netaknut
        cleaned_blocks.append(block)

    # 4) spoji nazad sve dozvoljene blokove u linije
    cleaned_lines: List[str] = []
    for block in cleaned_blocks:
        cleaned_lines.extend(block)

    # 5) upiši nazad u original fajl
    INPUT_FILE.write_text("\n".join(cleaned_lines) + "\n", encoding="utf-8")

    print("Završeno čišćenje fajla.")
    print(f"Original sačuvan kao {BACKUP_FILE.name}")
    print("Mečevi sa kladionicom koja ima <2 kvote su kompletno uklonjeni.")


if __name__ == "__main__":
    kontrolisi_i_ocisti()
