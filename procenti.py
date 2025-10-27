# procenti.py
# -*- coding: utf-8 -*-

import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# === putanje / folderi ===
TIKET_DIR = Path("TIKETI")
TIKET_DIR.mkdir(parents=True, exist_ok=True)

CONFIG = {
    "INPUT_FILE": Path("ALL_MATCHES_AND_ARBS/kvote_arbitraza_FULL.txt"),
    "OUTPUT_FILE": TIKET_DIR / "kvote_procenti.txt",
    "TICKET_FILE": TIKET_DIR / "tiketi.txt",

    # koje tržišta pratimo
    "TARGET_MARKETS": ["1", "X", "2", "0-2", "3+"],

    # kvote koje računamo za raspon
    "ODDS_MIN": 1.0,
    "ODDS_MAX": 5.0,

    # clamp diff%
    "MAX_DIFF_PCT": 60.0,

    # filter ženskih mečeva
    "WOMEN_KEYWORDS": [
        "women", "wom.", "wom", "(wom.)", "(wom)", "(w)",
    ],

    # regexi za parsiranje FULL fajla
    "RE_HEADER": re.compile(
        r"^(?P<time>\d\d:\d\d)\s+(?P<date>\d\d\.\d\d\.)\s+\[(?P<liga>.+?)\]\s*$"
    ),
    "RE_VS": re.compile(
        r"^\s*(?P<t1>.+?)\s+vs\s+(?P<t2>.+?)\s*$",
        re.IGNORECASE
    ),
    "RE_BOOKMAKER_LINE": re.compile(
        r"^\s*-\s*(?P<bkm>\S+)\s+(?P<rest>.+)$"
    ),
    "RE_PROFIT_1X2": re.compile(
        r"^Arbitraža\s*\(1-X-2\):.*profit≈\s*(?P<p1>-?\d+(?:\.\d+)?)%",
        re.IGNORECASE
    ),
    "RE_PROFIT_02_3P": re.compile(
        r"^Arbitraža\s*\(0-2\s*/\s*3\+\):.*profit≈\s*(?P<p2>-?\d+(?:\.\d+)?)%",
        re.IGNORECASE
    ),
    "RE_KVOTA": re.compile(
        r"(^|\|)\s*(?P<key>1|X|2|0-2|3\+)\s*=\s*(?P<val>[0-9]+(?:\.[0-9]+)?)"
    ),

    # separator u FULL fajlu
    "SEPARATOR_MIN_DASHES": 5,

    # pragovi profita za ulazak u kvote_procenti.txt
    # (ovo odlučuje šta uopšte ide u kvote_procenti.txt;
    #  tiketi kasnije rade dodatni filter po rasponu <2%)
    "MAX_PROFIT_FOR_OUTPUT": 10.0,   # >10% ne upisujemo
    "MIN_PROFIT_FOR_OUTPUT": -0.5,   # <=-1% ne upisujemo

    # ulog po tiketu
    "TICKET_STAKE": 200.0,
}


# ===========
# pomoćne za parsiranje FULL fajla
# ===========

def is_separator(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= CONFIG["SEPARATOR_MIN_DASHES"] and set(stripped) == {"-"}


def parse_markets_from_rest(rest: str) -> Dict[str, float]:
    mkts: Dict[str, float] = {}
    for m in CONFIG["RE_KVOTA"].finditer(rest):
        key = m.group("key")
        val_str = m.group("val")
        if key not in CONFIG["TARGET_MARKETS"]:
            continue
        try:
            val = float(val_str)
        except ValueError:
            continue
        mkts[key] = val
    return mkts


def procitaj_sve_meceve(lines: List[str]) -> List[Dict]:
    """
    Iz FULL fajla pravimo listu mečeva:
      {
        time,date,liga,home,away,
        kvote=[{"bkm":..., "markets":{mkt:kvota,...}}, ...],
        profit_1x2, profit_02_3p
      }
    Odbacujemo kladionice sa <2 tržišta.
    """
    mecevi: List[Dict] = []
    curr = {}
    state = "idle"

    for raw_line in lines:
        line = raw_line.rstrip("\n")

        if is_separator(line):
            if curr and curr.get("home") and curr.get("kvote"):
                mecevi.append(curr)
            curr = {}
            state = "idle"
            continue

        m_h = CONFIG["RE_HEADER"].match(line)
        if m_h:
            if curr and curr.get("home") and curr.get("kvote"):
                mecevi.append(curr)
            curr = {
                "time": m_h.group("time"),
                "date": m_h.group("date"),
                "liga": m_h.group("liga"),
                "home": None,
                "away": None,
                "kvote": [],
                "profit_1x2": None,
                "profit_02_3p": None,
            }
            state = "have_header"
            continue

        if state in ("have_header", "have_vs", "collecting_books"):
            m_vs = CONFIG["RE_VS"].match(line)
            if m_vs:
                curr["home"] = m_vs.group("t1").strip()
                curr["away"] = m_vs.group("t2").strip()
                state = "have_vs"
                continue

        m_b = CONFIG["RE_BOOKMAKER_LINE"].match(line)
        if m_b and state in ("have_vs", "collecting_books"):
            state = "collecting_books"
            bkm = m_b.group("bkm").strip()
            rest = m_b.group("rest")
            mkts = parse_markets_from_rest(rest)
            if len(mkts) < 2:
                continue
            curr["kvote"].append({
                "bkm": bkm,
                "markets": mkts,
            })
            continue

        m_p1 = CONFIG["RE_PROFIT_1X2"].match(line)
        if m_p1 and curr:
            curr["profit_1x2"] = m_p1.group("p1")
            continue

        m_p2 = CONFIG["RE_PROFIT_02_3P"].match(line)
        if m_p2 and curr:
            curr["profit_02_3p"] = m_p2.group("p2")
            continue

    if curr and curr.get("home") and curr.get("kvote"):
        mecevi.append(curr)

    return mecevi


def is_women_team(name: str) -> bool:
    low = name.lower()
    return any(w.lower() in low for w in CONFIG["WOMEN_KEYWORDS"])


def mec_je_zenski(match: Dict) -> bool:
    return is_women_team(match.get("home","")) or is_women_team(match.get("away",""))


def procentualna_razlika(max_v: float, min_v: float) -> float:
    if min_v == 0:
        return 0.0
    return (max_v - min_v) / min_v * 100.0


def safe_float(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v,(int,float)):
        return float(v)
    try:
        return float(str(v))
    except Exception:
        return None


def analiza_meča(match: Dict) -> Dict:
    """
    - Računamo diff_pct po marketu (ograničavamo na MAX_DIFF_PCT).
    - Čuvamo max_bkm, max_val po marketu.
    - Čuvamo profite.
    """

    TARGET_MKTS = CONFIG["TARGET_MARKETS"]
    MIN_ODD = CONFIG["ODDS_MIN"]
    MAX_ODD = CONFIG["ODDS_MAX"]
    MAX_DIFF = CONFIG["MAX_DIFF_PCT"]

    market_values: Dict[str, List[Tuple[str,float]]] = {m: [] for m in TARGET_MKTS}
    for entry in match["kvote"]:
        bkm = entry["bkm"]
        for mkt, odd in entry["markets"].items():
            if mkt in market_values and (MIN_ODD <= odd <= MAX_ODD):
                market_values[mkt].append((bkm, odd))

    markets_info: Dict[str, Dict[str, object]] = {}
    for mkt, lst in market_values.items():
        if not lst:
            markets_info[mkt] = {
                "diff_pct": 0.0,
                "max_bkm": None, "max_val": None,
                "min_bkm": None, "min_val": None,
                "count": 0,
            }
            continue

        max_bkm, max_val = max(lst, key=lambda x: x[1])
        min_bkm, min_val = min(lst, key=lambda x: x[1])

        if len(lst) >= 2:
            raw_diff = procentualna_razlika(max_val, min_val)
        else:
            raw_diff = 0.0
        diff_pct = raw_diff if raw_diff <= MAX_DIFF else MAX_DIFF

        markets_info[mkt] = {
            "diff_pct": diff_pct,
            "max_bkm":  max_bkm,
            "max_val":  max_val,
            "min_bkm":  min_bkm,
            "min_val":  min_val,
            "count":    len(lst),
        }

    best_market = max(CONFIG["TARGET_MARKETS"], key=lambda m: markets_info[m]["diff_pct"])
    best_info   = markets_info[best_market]

    profit_1x2   = safe_float(match.get("profit_1x2"))
    profit_02_3p = safe_float(match.get("profit_02_3p"))

    if best_market in ("1","X","2"):
        profit_for_best = profit_1x2
    else:
        profit_for_best = profit_02_3p

    opis_multiline = (
        f"{match['time']} {match['date']} [{match['liga']}]\n"
        f"{match['home']} vs {match['away']}"
    )
    opis_oneline = (
        f"{match['time']} {match['date']} {match['home']} vs {match['away']} "
        f"({match['liga']})"
    )

    return {
        "opis_multiline": opis_multiline,
        "opis_oneline": opis_oneline,

        "markets_info": markets_info,
        "best_market": best_market,
        "best_diff_pct": best_info["diff_pct"],
        "max_bkm": best_info["max_bkm"],
        "max_val": best_info["max_val"],
        "min_bkm": best_info["min_bkm"],
        "min_val": best_info["min_val"],

        "profit_1x2": profit_1x2,
        "profit_02_3p": profit_02_3p,
        "profit_for_best": profit_for_best,
    }


# ===========
# kvote_procenti.txt blokovi
# ===========

def build_blocks_for_output(r: Dict) -> Tuple[List[str], bool]:
    """
    Od jednog meča pravimo blok(ove) za kvote_procenti.txt:
    - Ako profit_1x2 je (-1%, 10%] -> ispiši 1, X, 2
    - Ako profit_02_3p je (-1%, 10%] -> ispiši 0-2, 3+
    Svaki market je POSEBAN blok.
    """
    out_blocks: List[str] = []
    qualifies = False

    profit_cap = CONFIG["MAX_PROFIT_FOR_OUTPUT"]   # 10.0
    profit_min = CONFIG["MIN_PROFIT_FOR_OUTPUT"]   # -1.0

    prof1 = r.get("profit_1x2")
    prof2 = r.get("profit_02_3p")

    def block_for_market(market_key: str, profit_val: Optional[float]) -> Optional[str]:
        info = r["markets_info"].get(market_key, {})
        max_val = info.get("max_val")
        max_bkm = info.get("max_bkm")
        diff_pct = info.get("diff_pct")

        if max_val is None or max_bkm is None:
            return None

        lines = []
        lines.append(r["opis_multiline"])
        lines.append(f"{market_key}: {max_val:.2f} [{max_bkm}]")
        lines.append(
            "Raspon kvote: " +
            (f"{float(diff_pct):.2f}%" if diff_pct is not None else "n/a")
        )
        lines.append(
            "Profit grupa: " +
            (f"{float(profit_val):.2f}%" if profit_val is not None else "n/a")
        )
        lines.append("----------------------------------------")
        return "\n".join(lines)

    # grupa 1/X/2
    if prof1 is not None:
        try:
            p = float(prof1)
            if p > profit_min and p <= profit_cap:
                for mk in ("1","X","2"):
                    blk = block_for_market(mk, p)
                    if blk:
                        out_blocks.append(blk)
                        qualifies = True
        except ValueError:
            pass

    # grupa 0-2 / 3+
    if prof2 is not None:
        try:
            p = float(prof2)
            if p > profit_min and p <= profit_cap:
                for mk in ("0-2","3+"):
                    blk = block_for_market(mk, p)
                    if blk:
                        out_blocks.append(blk)
                        qualifies = True
        except ValueError:
            pass

    return out_blocks, qualifies


# ===========
# parsiranje kvote_procenti.txt nazad → pickovi
# ===========

HEADER1_RE = re.compile(
    r"^(?P<time>\d{1,2}:\d{2})\s+(?P<date>\d{1,2}\.\d{1,2}\.)\s+\[(?P<liga>.+?)\]\s*$"
)
HEADER2_RE = re.compile(
    r"^(?P<home>.+?)\s+vs\s+(?P<away>.+?)\s*$",
    re.IGNORECASE
)
MARKET_LINE_RE = re.compile(
    r"^(?P<market>1|X|2|0-2|3\+):\s+(?P<odd>\d+(?:\.\d+)?)\s+\[(?P<bkm>[^\]]+)\]\s*$"
)
RASPON_RE = re.compile(
    r"^Raspon kvote:\s+(?P<raspon>[0-9.]+)%"
)
PROFIT_RE = re.compile(
    r"^Profit grupa:\s+(?P<profit>-?[0-9.]+)%"
)


def parse_kvote_procenti_blocks(kp_text: str) -> List[Dict[str, object]]:
    """
    Svaki blok u kvote_procenti.txt postaje jedan pick:
    {
      match: "19:00 29.10. Havre vs Brest (Francuska 1)",
      market: "X",
      odd: 3.50,
      bkm: "BalkanBet",
      raspon_pct: float | None,
      profit_pct: float | None,
    }
    """
    lines = kp_text.splitlines()
    picks: List[Dict[str, object]] = []
    i = 0
    n = len(lines)

    while i < n:
        m1 = HEADER1_RE.match(lines[i].strip()) if i < n else None
        if not m1:
            i += 1
            continue

        # sakupi block do "-----"
        block_lines = []
        j = i
        while j < n and not (lines[j].strip().startswith("-") and set(lines[j].strip()) == {"-"}):
            block_lines.append(lines[j].rstrip("\n"))
            j += 1
        # preskoči dashed line
        if j < n:
            j += 1

        if len(block_lines) >= 3:
            m_head1 = HEADER1_RE.match(block_lines[0].strip())
            m_head2 = HEADER2_RE.match(block_lines[1].strip()) if len(block_lines) > 1 else None
            m_mkt   = MARKET_LINE_RE.match(block_lines[2].strip()) if len(block_lines) > 2 else None

            raspon_val = None
            profit_val = None
            if len(block_lines) > 3:
                m_r = RASPON_RE.match(block_lines[3].strip())
                if m_r:
                    try:
                        raspon_val = float(m_r.group("raspon"))
                    except ValueError:
                        raspon_val = None
            if len(block_lines) > 4:
                m_p = PROFIT_RE.match(block_lines[4].strip())
                if m_p:
                    try:
                        profit_val = float(m_p.group("profit"))
                    except ValueError:
                        profit_val = None

            if m_head1 and m_head2 and m_mkt:
                time_s = m_head1.group("time")
                date_s = m_head1.group("date")
                liga_s = m_head1.group("liga")
                home_s = m_head2.group("home")
                away_s = m_head2.group("away")

                market_key = m_mkt.group("market")
                odd_val = float(m_mkt.group("odd"))
                bkm_val = m_mkt.group("bkm")

                match_id = f"{time_s} {date_s} {home_s} vs {away_s} ({liga_s})"

                picks.append({
                    "match": match_id,
                    "market": market_key,
                    "odd": odd_val,
                    "bkm": bkm_val,
                    "raspon_pct": raspon_val,
                    "profit_pct": profit_val,
                })

        i = j

    return picks


# ===========
# pravljenje tiketa (grupisanje)
# ===========

def _ticket_product_odds(picks: List[Dict[str, object]]) -> float:
    prod = 1.0
    for p in picks:
        prod *= float(p["odd"])
    return prod


def group_picks_into_tickets_by_bookmaker(picks_all: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """
    Logika pravljenja tiketa (bez formatiranja):

    - Pickovi sa rasponom < 2% NE ULAZE u tikete.
    - Tiket sadrži samo jednu kladionicu.
    - Idealno 2 para po tiketu.
    - U istom tiketu ne smeju kvote iz istog meča.
    - Singl tiket pokušavamo da spojimo u neki višemeč tiket iste
      kladionice sa najmanjim koeficijentom (max 3 para, bez istog meča).
    - Ako ne može da se spoji, ostaje singl i dobija "star": True.
      (ovo star koristimo samo ako uključimo prikaz kasnije)
    """

    # 0) filtriraj pickove po rasponu (<2% izbaci)
    filtered_picks = []
    for pk in picks_all:
        rspan = pk.get("raspon_pct")
        if rspan is not None and rspan < 2.0:
            continue
        filtered_picks.append(pk)

    # 1) grupišemo po kladionici
    picks_by_bkm: Dict[str, List[Dict[str, object]]] = {}
    for pk in filtered_picks:
        picks_by_bkm.setdefault(pk["bkm"], []).append(pk)

    final_tickets: List[Dict[str, object]] = []

    for bkm, picks in picks_by_bkm.items():
        # 2) prvi prolaz: gradimo tikete sa max 2, bez duplog meča
        raw_tickets: List[Dict[str, object]] = []

        current_ticket: List[Dict[str, object]] = []
        used_matches_in_ticket = set()

        def flush_ticket():
            nonlocal current_ticket, used_matches_in_ticket
            if current_ticket:
                raw_tickets.append({
                    "bkm": bkm,
                    "picks": current_ticket[:],
                })
            current_ticket = []
            used_matches_in_ticket = set()

        for pk in picks:
            # ako već imamo 2 u trenutnom tiketu -> zatvori pa kreni novi
            if len(current_ticket) >= 2:
                flush_ticket()

            # ako bi duplirali isti meč u istom tiketu -> zatvori pa kreni novi
            if pk["match"] in used_matches_in_ticket and current_ticket:
                flush_ticket()

            # ubaci sadašnji pick
            if len(current_ticket) < 2:
                current_ticket.append(pk)
                used_matches_in_ticket.add(pk["match"])
            else:
                flush_ticket()
                current_ticket.append(pk)
                used_matches_in_ticket.add(pk["match"])

        flush_ticket()

        # 3) sad imamo raw_tickets (svaki 1 ili 2 picka). Rešavamo singlove.
        multis = [t for t in raw_tickets if len(t["picks"]) >= 2]
        singles = [t for t in raw_tickets if len(t["picks"]) == 1]

        leftovers: List[Dict[str, object]] = []

        for s in singles:
            spick = s["picks"][0]

            # kandidati: postojeći multis sortirani po najmanjem koeficijentu
            candidates = sorted(
                multis,
                key=lambda t: _ticket_product_odds(t["picks"])
            )

            merged = False
            for mt in candidates:
                # tiket posle merge max 3
                if len(mt["picks"]) >= 3:
                    continue
                # ne dupliraj isti meč
                existing_matches = {pp["match"] for pp in mt["picks"]}
                if spick["match"] in existing_matches:
                    continue

                # možemo da ga ubacimo
                mt["picks"].append(spick)
                merged = True
                break

            if not merged:
                # ostaje solo tiket za ovu kladionicu
                s["star"] = True  # označi kao singl tiket
                leftovers.append(s)

        final_for_bkm = multis + leftovers
        final_tickets.extend(final_for_bkm)

    return final_tickets


# ===========
# pomoćne za formatiranje
# ===========

def _avg_profit_pct(picks: List[Dict[str, object]]) -> Optional[float]:
    vals = [p["profit_pct"] for p in picks if p.get("profit_pct") is not None]
    if not vals:
        return None
    return sum(vals) / float(len(vals))


def _collect_topbet_matches(tickets: List[Dict[str, object]]) -> set:
    """
    Vrati skup svih match ID-ova koji se pojavljuju u tiketima
    gde se kladionica zove 'Topbet'. (optionally koristi se za zvezdicu)
    """
    topbet_matches = set()
    for t in tickets:
        for p in t["picks"]:
            if str(p["bkm"]).strip().lower() == "topbet":
                topbet_matches.add(p["match"])
    return topbet_matches


def format_tickets_for_output(tickets: List[Dict[str, object]]) -> str:
    """
    Štampa sve tikete.

    Trenutni default:
    - Bez zvezdica uopšte.

    Ali ostavljamo flagove da lako možeš da ih uključiš:
      USE_SINGLETON_STAR = False   # stavi True ako želiš * u naslovu singl tiketa
      USE_TOPBET_STAR    = False   # stavi True ako želiš * pored svakog meča koji je viđen u Topbet tiketu
    """

    USE_SINGLETON_STAR = False
    USE_TOPBET_STAR = False

    stake = CONFIG["TICKET_STAKE"]

    if not tickets:
        return (
            "============================================\n"
            "   Nema tiketa (nema validnih parova za tikete).\n"
            "============================================\n"
        )

    # skup svih mečeva koji se pojavljuju sa Topbet kvotom
    topbet_matches = _collect_topbet_matches(tickets) if USE_TOPBET_STAR else set()

    lines: List[str] = []

    for idx, t in enumerate(tickets, start=1):
        picks = t["picks"]
        bkm = t["bkm"]

        product = _ticket_product_odds(picks)
        payout = product * stake

        avg_profit = _avg_profit_pct(picks)
        avg_profit_txt = f"{avg_profit:.2f}%" if avg_profit is not None else "n/a"

        # naslov tiketa
        title_line = f"  KLADIONICA: {bkm}       TIKET #{idx}"
        if USE_SINGLETON_STAR and t.get("star"):
            title_line += " *"

        lines.append("============================================")
        lines.append(title_line)
        lines.append("--------------------------------------------")
        lines.append(f"  Broj mečeva          : {len(picks)}")
        lines.append(f"  Ukupni koeficijent   : {product:.2f}")
        lines.append(f"  Ulog                 : {stake:.2f} RSD")
        lines.append(f"  Potencijalni dobitak : {payout:.2f} RSD")
        lines.append(f"  Prosečan profit      : {avg_profit_txt}")
        lines.append("--------------------------------------------")
        lines.append("  SELEKCIJE:")

        for pick_idx, p in enumerate(picks, start=1):
            raspon_txt = f"{p['raspon_pct']:.2f}%" if p["raspon_pct"] is not None else "n/a"
            profit_txt = f"{p['profit_pct']:.2f}%" if p["profit_pct"] is not None else "n/a"

            # po defaultu ne stavljamo zvezdicu
            match_line = f"   {pick_idx}) {p['match']}"

            # ako želiš kasnije:
            # ako je USE_TOPBET_STAR uključen i ovaj meč se pojavljuje u Topbet tiketu => dodaj *
            if USE_TOPBET_STAR and (p["match"] in topbet_matches):
                match_line += " *"

            lines.append(match_line)
            lines.append(f"       Market           : {p['market']} @ {p['odd']:.2f}")
            lines.append(f"       Raspon kvote     : {raspon_txt}")
            lines.append(f"       Profit za par    : {profit_txt}")
            lines.append("       ------------------------------------")

        lines.append("============================================")
        lines.append("")

    return "\n".join(lines) + "\n"


# ===========
# MAIN
# ===========

def main():
    # --- A) generišemo kvote_procenti.txt ---

    full_lines = CONFIG["INPUT_FILE"].read_text(
        encoding="utf-8", errors="ignore"
    ).splitlines()

    # svi mečevi
    mecevi = procitaj_sve_meceve(full_lines)
    # skloni ženske
    mecevi = [m for m in mecevi if not mec_je_zenski(m)]
    # analiza
    analyzed = [analiza_meča(m) for m in mecevi]

    # sortiramo po profit_for_best opadajuće da izlaz bude stabilan/koristan
    def sort_key(r: Dict) -> float:
        p = r.get("profit_for_best")
        if p is None:
            return -10**9
        return float(p)
    analyzed.sort(key=sort_key, reverse=True)

    # generišemo blokove za kvote_procenti.txt
    all_blocks: List[str] = []
    for r in analyzed:
        blks, _qualifies = build_blocks_for_output(r)
        all_blocks.extend(blks)

    out_text = ("\n".join(all_blocks) + "\n") if all_blocks else ""
    CONFIG["OUTPUT_FILE"].write_text(out_text, encoding="utf-8")

    # --- B) pravimo tikete ISKLJUČIVO iz kvote_procenti.txt ---

    # parsiramo nazad svaki blok => pick
    picks_all = parse_kvote_procenti_blocks(out_text)

    # grupišemo u tikete uz sva pravila
    tickets = group_picks_into_tickets_by_bookmaker(picks_all)

    # format + snimi tiketi.txt
    tiketi_txt = format_tickets_for_output(tickets)
    CONFIG["TICKET_FILE"].write_text(tiketi_txt, encoding="utf-8")


if __name__ == "__main__":
    main()
