# -*- coding: utf-8 -*-
"""
Izveštaj po meču:
1) Kompletan ispis kvota po kladionici (svi dostupni marketi).
2) Ispod: najveća kvota za 1, X, 2, 0-2, 3+ (sa imenima kladionica).
3) Provera arbitraže: posebno za 1-X-2 i za 0-2 / 3+.
4) Poseban TXT sa samo mečevima koji imaju bilo kakvu arbitražu.
5) Sažetak: broj zapisa po kladionici, broj "spojenih", broj grupa sa veličinom ≥3, ≥4, ≥5, ≥6.
6) POPRAVKE: čuvamo datum i ligu iz prve linije, i deduplikuje se po bookmaker-u.

Ulaz:
    soccer_mecevi_pregled.txt, merkur_mecevi_pregled.txt, mozzart_mecevi_pregled.txt,
    balkanbet_mecevi_pregled.txt, meridian_mecevi_pregled.txt, betole_mecevi_pregled.txt

Izlaz:
    ALL_MATCHES_AND_ARBS/kvote_arbitraza_FULL.txt          # samo mečevi (bez sažetka)
    ALL_MATCHES_AND_ARBS/kvote_arbitraza_ONLY_arbs.txt     # samo mečevi sa arbitražom + SAŽETAK
"""

from pathlib import Path
import re
import unicodedata
from typing import Dict, List, Optional, Tuple
import pandas as pd
from functools import lru_cache

# Output folder
OUT_DIR = Path("ALL_MATCHES_AND_ARBS")
OUT_DIR.mkdir(parents=True, exist_ok=True)

INPUT_FILES = {
    "Soccer": "soccer/soccer_mecevi_pregled.txt",
    "Merkur": "merkur/merkur_mecevi_pregled.txt",
    "Mozzart": "mozzart/mozzart_mecevi_pregled.txt",
    "BalkanBet": "balkanbet/balkanbet_mecevi_pregled.txt",
    "Brazil_d": "brazil/brazil_mecevi_pregled.txt",
    "Brazil_s": "brazil/brazil_sutra_mecevi_pregled.txt",
    "Brazil_p": "brazil/brazil_prekosutra_mecevi_pregled.txt",
    "BetOle": "betole/betole_mecevi_pregled.txt",
    "Topbet": "topbet/topbet_mecevi_pregled.txt",
    "OktagonBet": "oktagonbet/oktagonbet_mecevi_pregled.txt",
    "MaxBet": "maxbet/maxbet_mecevi_pregled.txt"
}

ALL_MARKETS = ["1", "X", "2", "0-2", "2+", "3+", "GG", "IGG", "GG&3+", "GG&4+", "4+"]
FOCUS_MARKETS = ["1", "X", "2", "0-2", "3+"]

# Pre-kompajlirani regex izrazi
SEP_RE = re.compile(r"^=+\s*$", re.MULTILINE)
HEADER_RE = re.compile(
    r"^\s*(?P<time>\d{1,2}:\d{2})"
    r"(?:\s+(?:Pon|Uto|Sre|Čet|Pet|Sub|Ned))?"
    r"(?:\s+(?P<date>\d{1,2}\.\d{1,2}\.))?"
    r"(?:\s+\[(?P<league>[^\]]+)\])?\s*$"
)
TIME_RE = re.compile(r"^\s*(\d{1,2}:\d{2})")
VS_RE = re.compile(r"\bvs\b", re.IGNORECASE)
ID_RE = re.compile(r"\(ID:\s*\d+\)\s*")
KEY_VAL_RE = re.compile(r"((?:IGG|GG)(?:&[0-9]+\+)?|X|[0-9]+(?:-[0-9]+)?\+?)=([^\s]+)")

# Frozenset za brže lookup
TEAM_STOPWORDS = frozenset([
    "fc", "fk", "al", "cf", "sc", "ac", "bc", "ud", "cd", "sd", "ad", "ca",
    "the", "club", "de", "of", "sv", "ss", "ks", "ik", "if", "sk",
    "u19", "u20", "u21", "b", "c", "a", "u23", "u17", "u16", "u15", "u14", "u13",
    "wom.", "||", "h.kfar", "II", "wom", "u23 wom.", "ii", "(wom)", "hapoel"
])

# ============================================================
# 1) SINONIMI TIMOVA
# ============================================================
TEAM_SYNONYMS: Dict[str, List[str]] = {
    "Villarreal": ["Villareal", "Vila Real", "Villarreal CF"],
    "Dinamo Moscow": ["Dynamo Moscow", "Dinamo Moskva", "Dinamo M.", "FC Dynamo Moscow"],
    "CSKA Moscow": ["CSKA Moskva", "CSKA M.", "PFC CSKA Moscow"],
    "Spartak Moscow": ["Spartak Moskva", "Spartak M.", "FC Spartak Moscow"],
    "Lokomotiv Moscow": ["Lokomotiv Moskva", "Lokomotiv M.", "FC Lokomotiv Moscow"],
    "Brondby": ["Brøndby", "Brondby IF", "Broendby IF"],
    "Nordsjaelland": ["Nordsjalland", "Nordsjaelland FC"],
    "Hajduk Split": ["Hajduk", "HNK Hajduk Split"],
    "Dinamo Zagreb": ["Dinamo", "GNK Dinamo Zagreb"],
    "Soenderjyske": ["Sonderjyske", "Soenderjyske FK"],
    "Crvena Zvezda": ["Red Star", "Red Star Belgrade", "Crvena Zvezda Beograd", "FK Crvena Zvezda"],
    "Partizan": ["FK Partizan", "Partizan Beograd"],
    "Atletico Madrid": ["Atl Madrid", "Atletico de Madrid", "Atlético Madrid"],
    "Athletic Bilbao": ["Athletic Club", "Ath Bilbao", "Athl. Bilbao"],
    "Inter": ["Inter Milan", "Inter Milano", "Internazionale", "FC Internazionale"],
    "AC Milan": ["Milan", "A.C. Milan"],
    "Manchester United": ["Man Utd", "Manchester Utd", "Man United", "Man. United"],
    "Manchester City": ["Man City", "Manchester C", "Man. City"],
    "Newcastle United": ["Newcastle Utd"],
    "Sporting CP": ["Sporting Lisbon", "Sporting Clube de Portugal"],
    "Marseille": ["Olympique Marseille", "OM", "O. Marseille"],
    "Real Betis": ["Betis", "Real Betis Balompie"],
    "Sevilla": ["Sevilla FC"],
    "Bayern Munich": ["Bayern Munchen", "Bayern München", "FC Bayern"],
    "Koln": ["Cologne", "1. FC Koln", "1. FC Köln", "FC Koln", "FC Köln"],
    "Fenerbahce": ["Fenerbahçe", "Fener"],
    "Besiktas": ["Beşiktaş", "Besiktas JK"],
    "Galatasaray": ["Gala", "Galata", "Galatasaray SK"],
    "AIK": ["AIK Stockholm"],
    "Rangers": ["Glasgow Rangers"],
    "Celtic": ["Celtic Glasgow"],
    "LASK Linz": ["LASK", "LASK Linz"],
}


# Keširanje funkcija za bolju performansu
@lru_cache(maxsize=10000)
def strip_accents(s: str) -> str:
    """Uklanja akcente - keširana verzija."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


@lru_cache(maxsize=10000)
def norm_word(w: str) -> str:
    """Normalizuje reč - keširana verzija."""
    w = strip_accents(w).lower()
    return re.sub(r"[^a-z0-9]+", "", w)


@lru_cache(maxsize=5000)
def split_team_words(name: str) -> Tuple[str, ...]:
    """Split i normalizacija - vraća tuple radi keširanja."""
    parts = re.split(r"[\s\-\._/]+", name)
    clean = [norm_word(p) for p in parts if norm_word(p)]
    return tuple(w for w in clean if w not in TEAM_STOPWORDS and len(w) >= 2)


@lru_cache(maxsize=5000)
def make_key(name: str) -> str:
    """Pravi ključ za mapiranje aliasa."""
    s = strip_accents(name).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)


# Inicijalizacija mapiranja aliasa
ALIAS_TO_CANON: Dict[str, str] = {}
for canon, aliases in TEAM_SYNONYMS.items():
    all_forms = [canon] + list(aliases)
    for form in all_forms:
        ALIAS_TO_CANON[make_key(form)] = canon


@lru_cache(maxsize=5000)
def alias_normalize(name: str) -> str:
    """Normalizuje alias na kanonski naziv."""
    key = make_key(name)
    return ALIAS_TO_CANON.get(key, name)


@lru_cache(maxsize=10000)
def share_meaningful_word(a: str, b: str) -> bool:
    """Proverava da li timovi dele smislenu reč."""
    a_n = alias_normalize(a)
    b_n = alias_normalize(b)
    A = set(split_team_words(a_n))
    B = set(split_team_words(b_n))
    return bool(A & B)  # Brži način za intersection check


def parse_block(block: str) -> Optional[Dict]:
    """Parsira blok teksta u strukturu meča."""
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if not lines:
        return None

    # Pokušaj da parsira header
    m_hdr = HEADER_RE.match(lines[0])
    if not m_hdr:
        m_time = TIME_RE.match(lines[0])
        if not m_time:
            return None
        match_time = m_time.group(1)
        match_date = match_league = None
    else:
        match_time = m_hdr.group("time")
        match_date = m_hdr.group("date")
        match_league = m_hdr.group("league")

    # Nađi liniju sa timovima
    teams_line = None
    for ln in lines[1:4]:  # Ograničeno pretraživanje
        if VS_RE.search(ln):
            teams_line = ln
            break
    
    if not teams_line:
        return None

    # Izvuci timove
    clean_teams = ID_RE.sub("", teams_line).strip()
    m_vs = VS_RE.split(clean_teams)
    if len(m_vs) != 2:
        return None
    
    home = m_vs[0].strip(" -\t")
    away = m_vs[1].strip(" -\t")

    # Parsiranje kvota
    odds: Dict[str, str] = {}
    for ln in lines[1:]:
        for key, val in KEY_VAL_RE.findall(ln):
            odds[key] = val
    
    # Normalizovane vrednosti za sve markete
    normalized = {m: odds.get(m, "-") for m in ALL_MARKETS}

    return {
        "time": match_time,
        "date": match_date,
        "league": match_league,
        "home": home,
        "away": away,
        **normalized
    }


def parse_file(path: Path) -> List[Dict]:
    """Parsira fajl i vraća listu mečeva."""
    if not path.exists():
        return []
    
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = [b.strip() for b in SEP_RE.split(text) if b.strip()]
    
    # List comprehension je brži od iterativnog append-a
    return [rec for b in blocks if (rec := parse_block(b)) is not None]


def to_float(x: str) -> Optional[float]:
    """Konvertuje string u float."""
    try:
        v = float(str(x).replace(",", "."))
        return v if v > 1.0 else None
    except (ValueError, TypeError):
        return None


def best_odds_for_market(subset: pd.DataFrame, market: str) -> Tuple[Optional[float], List[str]]:
    """Pronalazi najbolje kvote za dati market."""
    vals = []
    for _, r in subset.iterrows():
        val_str = r.get(market, "-")
        if val_str and val_str != "-":
            fv = to_float(val_str)
            if fv:
                vals.append((fv, r["bookmaker"]))
    
    if not vals:
        return None, []
    
    best = max(vals, key=lambda x: x[0])
    best_val = best[0]
    best_books = [bk for v, bk in vals if abs(v - best_val) < 0.005]
    return best_val, best_books


def arbitrage_1x2(a: Optional[float], b: Optional[float], c: Optional[float]):
    """Proverava arbitražu za 1-X-2."""
    if not all([a, b, c]):
        return False, None, None
    inv = 1.0 / a + 1.0 / b + 1.0 / c
    profit = (1.0 - inv) * 100.0  # Može biti negativan
    return inv < 1.0, inv, profit


def arbitrage_two_way(a: Optional[float], b: Optional[float]):
    """Proverava arbitražu za dvosmernu opkladu."""
    if not all([a, b]):
        return False, None, None
    inv = 1.0 / a + 1.0 / b
    profit = (1.0 - inv) * 100.0  # Može biti negativan
    return inv < 1.0, inv, profit


def compose_line_all_markets(r: pd.Series) -> str:
    """Sastavlja liniju sa svim marketima."""
    parts = [f"{k}={v}" for k in ALL_MARKETS if (v := r.get(k, "-")) and v != "-"]
    return "  |  ".join(parts) if parts else "-"


def nonempty_markets_count(r: pd.Series) -> int:
    """Broji neprazne markete."""
    return sum(1 for k in ALL_MARKETS if r.get(k, "-") not in ("-", None, ""))


def create_match_groups(df_all: pd.DataFrame) -> List[List[int]]:
    """Grupiše mečeve po vremenu i timovima - optimizovana verzija."""
    match_groups: List[List[int]] = []
    used = set()
    
    # Konvertuj DataFrame u list of tuples za brži pristup
    rows_data = [(i, row["time"], row["home"], row["away"]) 
                 for i, row in df_all.iterrows()]
    
    for i, t0, h0, a0 in rows_data:
        if i in used:
            continue
        
        group = [i]
        used.add(i)
        
        # Pretraži samo preostale redove
        for j, tj, hj, aj in rows_data[i+1:]:
            if j in used or tj != t0:
                continue
            
            if share_meaningful_word(h0, hj) and share_meaningful_word(a0, aj):
                group.append(j)
                used.add(j)
        
        match_groups.append(group)
    
    return match_groups


def format_match_block(subset: pd.DataFrame, base: pd.Series) -> List[str]:
    """Formatira blok za jedan meč."""
    block: List[str] = []
    
    # Header
    hdr_parts = [base["time"]]
    if date_str := base.get("date"):
        hdr_parts.append(date_str)
    if league_str := base.get("league"):
        hdr_parts.append(f"[{league_str}]")
    
    block.append("   ".join(hdr_parts).rstrip())
    block.append(f"{base['home']}  vs  {base['away']}")
    block.append("")
    
    # Kvote po kladionicama
    for _, r in subset.sort_values("bookmaker").iterrows():
        block.append(f"- {r['bookmaker']:<10} {compose_line_all_markets(r)}")
    
    # Najveće kvote
    block.append("")
    best_map = {}
    for m in FOCUS_MARKETS:
        best_val, best_books = best_odds_for_market(subset, m)
        best_map[m] = (best_val, best_books)
        if best_val:
            block.append(f"Najveća {m:<3}: {best_val:.2f}  [{', '.join(best_books)}]")
        else:
            block.append(f"Najveća {m:<3}: -")
    
    # Arbitraže
    block.append("")
    best1, _ = best_map.get("1", (None, []))
    bestX, _ = best_map.get("X", (None, []))
    best2, _ = best_map.get("2", (None, []))
    
    ok3, inv3, prof3 = arbitrage_1x2(best1, bestX, best2)
    if inv3 is not None:
        arb_status = "DA" if ok3 else "NE"
        block.append(f"Arbitraža (1-X-2): {arb_status}   inv_sum={inv3:.4f}   profit≈{prof3:.2f}%")
    else:
        block.append("Arbitraža (1-X-2): nedovoljno podataka")
    
    best_u, _ = best_map.get("0-2", (None, []))
    best_o, _ = best_map.get("3+", (None, []))
    
    ok2, inv2, prof2 = arbitrage_two_way(best_u, best_o)
    if inv2 is not None:
        arb_status = "DA" if ok2 else "NE"
        block.append(f"Arbitraža (0-2 / 3+): {arb_status}   inv_sum={inv2:.4f}   profit≈{prof2:.2f}%")
    else:
        block.append("Arbitraža (0-2 / 3+): nedovoljno podataka")
    
    block.append("")
    
    return block, (ok3, ok2, inv3, inv2)


def create_summary(df_all: pd.DataFrame, match_groups: List[List[int]], 
                   arb_counts: Tuple[int, int, int]) -> List[str]:
    """Kreira sažetak."""
    arb_1x2_groups, arb_uo_groups, arb_any_groups = arb_counts
    
    total_per_book = df_all.groupby("bookmaker").size().to_dict()
    paired_indices = {idx for g in match_groups if len(g) > 1 for idx in g}
    paired_per_book = (
        df_all.loc[list(paired_indices)].groupby("bookmaker").size().to_dict()
        if paired_indices else {}
    )
    
    # Statistike grupa
    total_groups = len(match_groups)
    paired_groups = sum(1 for g in match_groups if len(g) > 1)
    group_counts = {i: sum(1 for g in match_groups if len(g) >= i) 
                    for i in range(3, 8)}
    
    summary_lines: List[str] = []
    summary_lines.append("=" * 86)
    summary_lines.append("SAŽETAK".center(86))
    summary_lines.append("=" * 86)
    summary_lines.append(f"Ukupno mečeva (grupa): {total_groups}")
    summary_lines.append(f"Mečeva spojenih sa ≥2 kladionice (grupa size>1): {paired_groups}")
    
    for i in range(3, 8):
        summary_lines.append(f"Grupa sa veličinom ≥{i}: {group_counts[i]}")
    
    summary_lines.append("")
    summary_lines.append("Po kladionici:")
    
    for bk in sorted(set(df_all["bookmaker"].tolist())):
        total_bk = total_per_book.get(bk, 0)
        paired_bk = paired_per_book.get(bk, 0)
        summary_lines.append(f"  - {bk:<10} ukupno zapisa: {total_bk:>4}   "
                            f"spojeno (u grupama >1): {paired_bk:>4}")
    
    summary_lines.append("")
    summary_lines.append("Arbitraže (broj mečeva/grupa):")
    summary_lines.append(f"  - 1-X-2: {arb_1x2_groups}")
    summary_lines.append(f"  - 0-2 / 3+: {arb_uo_groups}")
    summary_lines.append(f"  - Barem jedna arbitraža: {arb_any_groups}")
    summary_lines.append("")
    
    return summary_lines


def main():
    """Glavna funkcija."""
    # Učitavanje podataka
    rows = []
    for bk_name, fname in INPUT_FILES.items():
        p = Path(fname)
        recs = parse_file(p)
        for r in recs:
            row = {"bookmaker": bk_name, **r}
            rows.append(row)

    if not rows:
        (OUT_DIR / "kvote_arbitraza_FULL.txt").write_text(
            "Nije nađen nijedan meč u ulaznim fajlovima.\n",
            encoding="utf-8"
        )
        (OUT_DIR / "kvote_arbitraza_ONLY_arbs.txt").write_text("", encoding="utf-8")
        return

    df_all = pd.DataFrame(rows)

    # Grupisanje mečeva
    match_groups = create_match_groups(df_all)

    all_lines: List[str] = []
    arb_only_lines: List[str] = []
    
    arb_1x2_groups = arb_uo_groups = arb_any_groups = 0

    # Procesiranje grupa
    for g in match_groups:
        subset = df_all.loc[g].copy()

        # Deduplikacija po bookmaker-u
        subset["__filled"] = subset.apply(nonempty_markets_count, axis=1)
        subset = subset.sort_values(["bookmaker", "__filled"], ascending=[True, False])
        subset = subset.drop_duplicates("bookmaker", keep="first")
        subset = subset.drop(columns="__filled")

        base = subset.iloc[0]
        
        # Formatiranje bloka
        block, (ok3, ok2, inv3, inv2) = format_match_block(subset, base)

        # Dodaj u FULL izlaz
        if not all_lines:
            all_lines.append("-" * 86)
        all_lines.extend(block)
        all_lines.append("-" * 86)

        # Provera arbitraže
        any_arb = False
        if inv3 is not None and ok3:
            arb_1x2_groups += 1
            any_arb = True
        if inv2 is not None and ok2:
            arb_uo_groups += 1
            any_arb = True
        if any_arb:
            arb_any_groups += 1
            arb_only_lines.extend(block)

    # Kreiranje sažetka
    summary_lines = create_summary(df_all, match_groups, 
                                   (arb_1x2_groups, arb_uo_groups, arb_any_groups))

    # Pisanje fajlova
    (OUT_DIR / "kvote_arbitraza_FULL.txt").write_text(
        "\n".join(all_lines).rstrip() + "\n" if all_lines else "",
        encoding="utf-8"
    )

    only_arbs_out = []
    if arb_only_lines:
        only_arbs_out.extend(arb_only_lines)
        only_arbs_out.append("")
    only_arbs_out.extend(summary_lines)

    (OUT_DIR / "kvote_arbitraza_ONLY_arbs.txt").write_text(
        "\n".join(only_arbs_out).rstrip() + "\n" if only_arbs_out else "\n".join(summary_lines),
        encoding="utf-8"
    )


if __name__ == "__main__":
    main()
