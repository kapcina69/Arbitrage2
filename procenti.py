# procenti.py
# -*- coding: utf-8 -*-
"""
Pipeline:
1) Parsira kvote_arbitraza_FULL.txt
2) Filtrira ženske mečeve (Women/Wom...)
3) Izbacuje kladionice koje imaju manje od 2 kvote za meč
4) Računa raspon kvota po tržištima i određuje best_market za meč
5) Sortira mečeve po profitu koji odgovara best_market-u (profit_for_best desc)
6) Piše kvote_procenti.txt:
   - ispisuje samo profit odgovarajući best_market-u:
        * ako je best_market u {1,X,2} -> Profit (1-X-2)
        * ako je best_market u {0-2,3+} -> Profit (0-2 / 3+)

7) Pravi tikete po kladionicama:
   - prolazi redom kroz analizirane mečeve (isti red kao u kvote_procenti.txt)
   - za svaki meč uzima jednu jedinu opkladu:
        kladionica = max_bkm tog meča
        kvota      = max_val za best_market
        market     = best_market
        diff_pct   = best_diff_pct
        pick_profit= profit_for_best
        opis_meča  = opis_oneline
   - ovaj pick ide u tiket te kladionice (gradi se product kvota)
   - tiket je gotov kad product >= TICKET_TARGET_TOTAL
   - posle toga ta kladionica kreće novi tiket

   Dodatna pravila:
   - ako je max_bkm == Topbet -> preskačemo taj meč u potpunosti
   - ako je profit_for_best > 10% -> preskačemo taj meč u potpunosti

8) Bankroll pravilo:
   - uzimamo gotove tikete po redosledu završavanja
   - dodajemo ih dok ukupni ulog (N_tiketa * stake) ne pređe
     najmanji potencijalni dobitak u tom skupu
   - čim bi prešlo, odbacimo taj poslednji i stajemo

9) tiketi.txt:
   - format tiketa (koef, ulog, dobitak, Σraspon, avg profit)
   - analiza koliko tiketa po kladionici, ukupno uloženo, min dobitak
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# folder za izlaz tiketa
TIKET_DIR = Path("TIKETI")
TIKET_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# CONFIG
# =========================

CONFIG = {
    # fajlovi
    "INPUT_FILE": Path("ALL_MATCHES_AND_ARBS/kvote_arbitraza_FULL.txt"),
    "OUTPUT_FILE": TIKET_DIR / "kvote_procenti.txt",
    "TICKET_FILE": TIKET_DIR / "tiketi.txt",

    # koje markete gledamo / dozvoljeni marketi
    "TARGET_MARKETS": ["1", "X", "2", "0-2", "3+"],

    # uzimamo u obzir SAMO kvote u ovom opsegu (za analizu)
    "ODDS_MIN": 1.0,
    "ODDS_MAX": 5.0,

    # maksimalan raspon (diff%) koji priznajemo po marketu / meču
    "MAX_DIFF_PCT": 40.0,

    # ključne reči koje znače da je ženski meč → preskačemo ceo meč
    "WOMEN_KEYWORDS": [
        "women",
        "wom.",
        "wom",
        "(wom.)",
        "(wom)",
        "(w)",
    ],

    # regex za header (vreme, datum, liga)
    "RE_HEADER": re.compile(
        r"^(?P<time>\d\d:\d\d)\s+(?P<date>\d\d\.\d\d\.)\s+\[(?P<liga>.+?)\]\s*$"
    ),

    # regex za liniju sa timovima
    "RE_VS": re.compile(
        r"^\s*(?P<t1>.+?)\s+vs\s+(?P<t2>.+?)\s*$",
        re.IGNORECASE
    ),

    # regex za bookmaker liniju
    "RE_BOOKMAKER_LINE": re.compile(
        r"^\s*-\s*(?P<bkm>\S+)\s+(?P<rest>.+)$"
    ),

    # regex za profit liniju (1-X-2)
    "RE_PROFIT_1X2": re.compile(
        r"^Arbitraža\s*\(1-X-2\):.*profit≈\s*(?P<p1>-?\d+(?:\.\d+)?)%",
        re.IGNORECASE
    ),

    # regex za profit liniju (0-2 / 3+)
    "RE_PROFIT_02_3P": re.compile(
        r"^Arbitraža\s*\(0-2\s*/\s*3\+\):.*profit≈\s*(?P<p2>-?\d+(?:\.\d+)?)%",
        re.IGNORECASE
    ),

    # regex da izvučemo samo čiste markete (1, X, 2, 0-2, 3+)
    "RE_KVOTA": re.compile(
        r"(^|\|)\s*(?P<key>1|X|2|0-2|3\+)\s*=\s*(?P<val>[0-9]+(?:\.[0-9]+)?)"
    ),

    # separator mečeva
    "SEPARATOR_MIN_DASHES": 5,  # min dužina linije od '-' da bi važila kao separator

    # sortiranje izveštaja po profitu_for_best (veće gore)
    "SORT_DESC": True,

    # parametri za tikete
    "TICKET_TARGET_TOTAL": 10.0,   # prag množioca da bi tiket bio gotov
    "TICKET_STAKE": 200.0,         # ulog po tiketu (din)

    # ograničenje profita za meč da bi ušao u tiket
    "MAX_MATCH_PROFIT_FOR_TICKET": 10.0,  # % ako je > ovoga, preskačemo meč
}


# =========================
# HELPER FUNKCIJE
# =========================

def is_separator(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= CONFIG["SEPARATOR_MIN_DASHES"] and set(stripped) == {"-"}


def parse_markets_from_rest(rest: str) -> Dict[str, float]:
    """
    Parsira kvote iz jedne bookmaker linije (1=..., X=..., 0-2=..., 3+=...)
    Vraća dict {market: kvota(float)} SAMO za TARGET_MARKETS.
    """
    markets: Dict[str, float] = {}
    for m in CONFIG["RE_KVOTA"].finditer(rest):
        key = m.group("key")
        val_str = m.group("val")
        try:
            val = float(val_str)
        except ValueError:
            continue
        if key in CONFIG["TARGET_MARKETS"]:
            markets[key] = val
    return markets


def procitaj_sve_meceve(tekst: List[str]) -> List[Dict]:
    """
    Parsiramo sve mečeve iz fajla.
    - Za svaku kladionicu računamo koliko različitih target market kvota ima.
    - Ako ima <2 → tu kladionicu IGNORIŠEMO (treat as if not there).
    """
    mecevi: List[Dict] = []
    curr_match: Dict[str, object] = {}
    state = "idle"

    for raw_line in tekst:
        line = raw_line.rstrip("\n")

        # separator = kraj prethodnog meča
        if is_separator(line):
            if curr_match and "kvote" in curr_match and curr_match.get("home"):
                mecevi.append(curr_match)
            curr_match = {}
            state = "idle"
            continue

        # header (vreme, datum, liga)
        m_h = CONFIG["RE_HEADER"].match(line)
        if m_h:
            # push prethodni ako postoji
            if curr_match and "kvote" in curr_match and curr_match.get("home"):
                mecevi.append(curr_match)

            curr_match = {
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

        # linija "TeamA vs TeamB"
        if state in ("have_header", "have_vs", "collecting_books"):
            m_vs = CONFIG["RE_VS"].match(line)
            if m_vs:
                curr_match["home"] = m_vs.group("t1").strip()
                curr_match["away"] = m_vs.group("t2").strip()
                state = "have_vs"
                continue

        # linija kladionice
        m_b = CONFIG["RE_BOOKMAKER_LINE"].match(line)
        if m_b and state in ("have_vs", "collecting_books"):
            state = "collecting_books"
            bkm = m_b.group("bkm").strip()
            rest = m_b.group("rest")
            markets = parse_markets_from_rest(rest)

            # ako ova kladionica ima <2 target market kvote -> ignorišemo je
            if len(markets) < 2:
                continue

            curr_match["kvote"].append({
                "bkm": bkm,
                "markets": markets,
            })
            continue

        # profit linija (1-X-2)
        m_p1 = CONFIG["RE_PROFIT_1X2"].match(line)
        if m_p1 and curr_match:
            curr_match["profit_1x2"] = m_p1.group("p1")
            continue

        # profit linija (0-2 / 3+)
        m_p2 = CONFIG["RE_PROFIT_02_3P"].match(line)
        if m_p2 and curr_match:
            curr_match["profit_02_3p"] = m_p2.group("p2")
            continue

    # push poslednji meč ako postoji
    if curr_match and "kvote" in curr_match and curr_match.get("home"):
        mecevi.append(curr_match)

    return mecevi


def is_women_team(name: str) -> bool:
    n = name.lower()
    return any(kw.lower() in n for kw in CONFIG["WOMEN_KEYWORDS"])


def mec_je_zenski(match: Dict) -> bool:
    return is_women_team(match.get("home", "")) or is_women_team(match.get("away", ""))


def procentualna_razlika(max_v: float, min_v: float) -> float:
    if min_v == 0:
        return 0.0
    return (max_v - min_v) / min_v * 100.0


def safe_float(val) -> Optional[float]:
    """
    Pretvori string u float ako može, inače None.
    Ako je već float, samo ga vrati.
    """
    if val is None:
        return None
    if isinstance(val, (float, int)):
        return float(val)
    try:
        return float(str(val))
    except (TypeError, ValueError):
        return None


def analiza_meča(match: Dict) -> Dict:
    """
    Za dati meč:
    - sakupljamo kvote po target marketima posle filtera kladionica
    - računamo diff% za svaki market (ograničeno na MAX_DIFF_PCT)
    - biramo market sa najvećim diff%
    - računamo profit_for_best:
        * ako je best_market ∈ {1,X,2}  -> profit_1x2
        * ako je best_market ∈ {0-2,3+} -> profit_02_3p
    """

    TARGET_MARKETS = CONFIG["TARGET_MARKETS"]
    ODDS_MIN = CONFIG["ODDS_MIN"]
    ODDS_MAX = CONFIG["ODDS_MAX"]
    MAX_DIFF = CONFIG["MAX_DIFF_PCT"]

    total_bookmakers = len({e["bkm"] for e in match["kvote"]})

    # kvote po marketu
    market_values: Dict[str, List[Tuple[str, float]]] = {m: [] for m in TARGET_MARKETS}
    for e in match["kvote"]:
        bkm = e["bkm"]
        for mkt, val in e["markets"].items():
            if mkt in market_values and ODDS_MIN <= val <= ODDS_MAX:
                market_values[mkt].append((bkm, val))

    # diff info za svaki market
    markets_info = {}
    for mkt, lst in market_values.items():
        if not lst:
            markets_info[mkt] = dict(
                diff_pct=0.0,
                max_bkm=None, max_val=None,
                min_bkm=None, min_val=None,
                count=0
            )
            continue

        max_bkm, max_val = max(lst, key=lambda x: x[1])
        min_bkm, min_val = min(lst, key=lambda x: x[1])

        if len(lst) >= 2:
            diff_pct_raw = procentualna_razlika(max_val, min_val)
        else:
            diff_pct_raw = 0.0

        diff_pct = diff_pct_raw if diff_pct_raw <= MAX_DIFF else MAX_DIFF

        markets_info[mkt] = dict(
            diff_pct=diff_pct,
            max_bkm=max_bkm, max_val=max_val,
            min_bkm=min_bkm, min_val=min_val,
            count=len(lst)
        )

    # best market po diff%
    best_market = max(TARGET_MARKETS, key=lambda m: markets_info[m]["diff_pct"])
    best_info = markets_info[best_market]

    # profit_for_best
    if best_market in ("1", "X", "2"):
        profit_for_best = safe_float(match.get("profit_1x2"))
    elif best_market in ("0-2", "3+"):
        profit_for_best = safe_float(match.get("profit_02_3p"))
    else:
        profit_for_best = None

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
        "best_market": best_market,
        "best_diff_pct": best_info["diff_pct"],
        "max_bkm": best_info["max_bkm"],
        "max_val": best_info["max_val"],
        "min_bkm": best_info["min_bkm"],
        "min_val": best_info["min_val"],
        "count_quotes_for_best": best_info["count"],
        "total_bookmakers": total_bookmakers,
        "profit_1x2": match.get("profit_1x2"),
        "profit_02_3p": match.get("profit_02_3p"),
        "profit_for_best": profit_for_best,  # koristi se i za sortiranje i za tikete
        "raw_match": match,
    }


def format_match_block(r: Dict) -> str:
    """
    Blok za kvote_procenti.txt
    - ispisujemo samo profit koji odgovara best_market-u
    """

    p1 = r["profit_1x2"] if r["profit_1x2"] is not None else "n/a"
    p2 = r["profit_02_3p"] if r["profit_02_3p"] is not None else "n/a"

    header = (
        f"{r['opis_multiline']}\n"
        f"Broj kladionica (ukupno): {r['total_bookmakers']}\n"
        f"Market sa najvećim rasponom: {r['best_market']} "
        f"(broj kladionica za ovaj market: {r['count_quotes_for_best']})"
    )

    # raspon i max/min
    if r["count_quotes_for_best"] == 0:
        body = "Raspon: 0.00% (nema kvota u dozvoljenom opsegu)\n"
    elif r["count_quotes_for_best"] == 1:
        max_val = r["max_val"] if r["max_val"] is not None else 0.0
        max_bkm = r["max_bkm"] if r["max_bkm"] is not None else "?"
        body = (
            "Raspon: 0.00% (samo jedna kvota u dozvoljenom opsegu)\n"
            f"  max {max_val:.2f} [{max_bkm}]\n"
        )
    else:
        body = (
            f"Raspon: {r['best_diff_pct']:.2f}%\n"
            f"  max {r['max_val']:.2f} [{r['max_bkm']}]\n"
            f"  min {r['min_val']:.2f} [{r['min_bkm']}]\n"
        )

    # profit prikaz – samo relevantan
    if r["best_market"] in ("1", "X", "2"):
        profit_line = f"Profit (1-X-2): {p1}%\n"
    elif r["best_market"] in ("0-2", "3+"):
        profit_line = f"Profit (0-2 / 3+): {p2}%\n"
    else:
        profit_line = ""

    footer = profit_line + "----------------------------------------"

    return header + "\n" + body + footer


# =========================
# TIKET LOGIKA
# =========================

def build_tickets_from_analyzed(analyzed_results: List[Dict]) -> Dict[str, List[Dict[str, object]]]:
    """
    Kreira tikete po pravilima:
    - prolazimo kroz analizirane mečeve REDOM (isti red kao u kvote_procenti.txt)
    - za svaki meč uzimamo SAMO najbolju kvotu:
        bkm        = r['max_bkm']
        odd        = r['max_val']
        market     = r['best_market']
        diff_pct   = r['best_diff_pct']
        pick_profit= r['profit_for_best']
        match_desc = r['opis_oneline']
    - taj pick ide u tiket te kladionice

    Tiket se puni dok proizvod kvota ne >= TICKET_TARGET_TOTAL,
    pa se zatvara i sledeći pick za tu kladionicu ide u novi tiket.

    Posebna pravila filtriranja:
    - ako je max_bkm == "Topbet" -> ovaj meč IGNORIŠEMO
    - ako je profit_for_best > MAX_MATCH_PROFIT_FOR_TICKET (npr. 10%) -> IGNORIŠEMO
    """

    target_total = CONFIG["TICKET_TARGET_TOTAL"]
    profit_limit = CONFIG["MAX_MATCH_PROFIT_FOR_TICKET"]

    tickets: Dict[str, List[Dict[str, object]]] = {}
    done_counter = 0  # redosled kojim tiketi postaju gotovi

    for r in analyzed_results:
        bkm = r.get("max_bkm")
        odd = r.get("max_val")
        market = r.get("best_market")
        diff_pct = r.get("best_diff_pct")
        pick_profit = r.get("profit_for_best")
        match_desc = r.get("opis_oneline")

        # 1) moramo imati sve bitne podatke
        if bkm is None or odd is None or market is None:
            continue

        # 2) ignoriši Topbet
        if str(bkm).strip().lower() == "topbet":
            continue

        # 3) ignoriši meč ako profit_for_best > 10%
        if pick_profit is not None:
            try:
                if float(pick_profit) > profit_limit:
                    continue
            except (TypeError, ValueError):
                pass  # ako ne može da se parsira u float, ne preskačemo zbog toga

        # 4) inicijalizuj listu tiketa za tu kladionicu
        if bkm not in tickets:
            tickets[bkm] = []

        # 5) ako nema aktivan tiket ili je poslednji gotov → otvori novi tiket
        if (not tickets[bkm]) or tickets[bkm][-1]["done"]:
            tickets[bkm].append({
                "picks": [],
                "product": 1.0,
                "done": False,
                "done_order": None,
            })

        active_ticket = tickets[bkm][-1]

        # 6) dodaj ovaj pick u aktivni tiket
        active_ticket["picks"].append({
            "match": match_desc,
            "market": market,
            "odd": odd,
            "diff_pct": diff_pct if diff_pct is not None else 0.0,
            "pick_profit": pick_profit,
        })

        # 7) apdejtuj proizvod kvota
        active_ticket["product"] *= float(odd)

        # 8) proveri da li je tiket završen
        if (not active_ticket["done"]) and (active_ticket["product"] >= target_total):
            active_ticket["done"] = True
            done_counter += 1
            active_ticket["done_order"] = done_counter

    return tickets


def _collect_done_tickets_with_meta(tickets: Dict[str, List[Dict[str, object]]]) -> List[Dict[str, object]]:
    """
    Vraća listu svih gotovih tiketa sa metapodacima potrebnim za ispis / bankroll.
    """
    stake = CONFIG["TICKET_STAKE"]

    flat: List[Dict[str, object]] = []
    for bkm, tlist in tickets.items():
        for idx, t in enumerate(tlist, start=1):
            if not t.get("done"):
                continue

            sum_diff = sum(p["diff_pct"] for p in t["picks"])

            prof_vals = [
                p["pick_profit"] for p in t["picks"]
                if p.get("pick_profit") is not None
            ]
            avg_prof = (sum(prof_vals) / len(prof_vals)) if prof_vals else None

            payout = t["product"] * stake

            flat.append({
                "bkm": bkm,
                "index": idx,
                "ticket": t,
                "sum_diff": sum_diff,
                "avg_profit": avg_prof,
                "payout": payout,
                "done_order": t.get("done_order", 10**9),
            })

    return flat


def _apply_bankroll_rule(flat_done: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """
    Bankroll pravilo:
    - Sortiramo tikete po done_order (hronološki).
    - Iterativno ih dodajemo u kept.
    - Posle svakog dodatog:
        total_stake = len(kept) * stake
        min_payout  = minimalni payout u kept
      Ako total_stake > min_payout → izbacujemo poslednji dodat i stajemo.
    """
    stake = CONFIG["TICKET_STAKE"]

    chron = sorted(flat_done, key=lambda x: x["done_order"])

    kept: List[Dict[str, object]] = []
    for tinfo in chron:
        kept.append(tinfo)

        total_stake = len(kept) * stake
        min_payout = min(k["payout"] for k in kept)

        if total_stake > min_payout:
            kept.pop()
            break

    return kept


def format_tickets_for_output(tickets: Dict[str, List[Dict[str, object]]]) -> str:
    """
    Finalni ispis tiketa + analiza po kladionici + bankroll info.
    """

    stake = CONFIG["TICKET_STAKE"]
    target_total = CONFIG["TICKET_TARGET_TOTAL"]

    # 1) svi gotovi tiketi
    flat_done = _collect_done_tickets_with_meta(tickets)

    if not flat_done:
        return (
            "============================================\n"
            "   Nema završenih tiketa.\n"
            "============================================\n"
        )

    # 2) bankroll selekcija
    kept = _apply_bankroll_rule(flat_done)

    if not kept:
        return (
            "============================================\n"
            "   Nema tiketa posle bankroll filtera.\n"
            "============================================\n"
        )

    # 3) za prikaz sort po sum_diff opadajuće
    kept_sorted_for_display = sorted(kept, key=lambda x: x["sum_diff"], reverse=True)

    # 4) generiši ispis tiketa
    lines: List[str] = []

    for item in kept_sorted_for_display:
        bkm = item["bkm"]
        idx = item["index"]
        t = item["ticket"]
        sum_diff = item["sum_diff"]
        avg_prof = item["avg_profit"]
        product = t["product"]
        payout = product * stake

        lines.append("============================================")
        lines.append(f"  KLADIONICA: {bkm}       TIKET #{idx}")
        lines.append("--------------------------------------------")
        lines.append(f"  Ukupni koeficijent : {product:.2f}  (cilj: {target_total:.2f})")
        lines.append(f"  Ulog               : {stake:.2f} RSD")
        lines.append(f"  Potencijalni dobitak: {payout:.2f} RSD")
        lines.append("")
        lines.append(f"  Ukupni raspon vrednosti (Σ diff%%): {sum_diff:.2f}%")
        lines.append(
            f"  Prosečan profit arbitraže        : {avg_prof:.2f}%"
            if avg_prof is not None else
            "  Prosečan profit arbitraže        : n/a"
        )
        lines.append("--------------------------------------------")
        lines.append("  SELEKCIJE:")

        for pick_idx, pick in enumerate(t["picks"], start=1):
            profit_txt = (
                f"{pick['pick_profit']:.2f}%" if pick["pick_profit"] is not None else "n/a"
            )
            lines.append(f"   {pick_idx}) {pick['match']}")
            lines.append(f"       Market           : {pick['market']} @ {pick['odd']:.2f}")
            lines.append(f"       Raspon kvote     : {pick['diff_pct']:.2f}%")
            lines.append(f"       Profit za par    : {profit_txt}")
            lines.append("       ------------------------------------")

        lines.append("============================================")
        lines.append("")

    # 5) ANALIZA TIKETA za zadržane tikete
    per_bookmaker_count: Dict[str, int] = {}
    total_tickets = 0
    for item in kept:
        per_bookmaker_count[item["bkm"]] = per_bookmaker_count.get(item["bkm"], 0) + 1
        total_tickets += 1

    total_stake_spent = total_tickets * stake
    min_payout_kept = min(item["payout"] for item in kept)

    lines.append("##########   ANALIZA TIKETA   ##########")
    lines.append("")
    lines.append("Broj završenih tiketa po kladionici (zadržani):")
    for bkm, cnt in sorted(per_bookmaker_count.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"  - {bkm}: {cnt} tiket(a)")
    lines.append("")
    lines.append(f"Ukupno zadržanih tiketa: {total_tickets}")
    lines.append(f"Ukupno uloženo: {total_stake_spent:.2f} RSD")
    lines.append(f"Najmanji potencijalni dobitak u tim tiketima: {min_payout_kept:.2f} RSD")
    lines.append("########################################")

    return "\n".join(lines) + "\n"


# =========================
# MAIN
# =========================

def main():
    # 1) učitaj ulazni fajl
    text_lines = CONFIG["INPUT_FILE"].read_text(
        encoding="utf-8",
        errors="ignore"
    ).splitlines()

    # 2) parsiraj sve mečeve (već filtrira kladionice sa <2 kvote)
    mecevi = procitaj_sve_meceve(text_lines)

    # 3) odbaci ženske mečeve
    mecevi = [m for m in mecevi if not mec_je_zenski(m)]

    # 4) analiziraj mečeve
    analyzed = [analiza_meča(m) for m in mecevi]

    # 5) sortiraj mečeve po profitu_for_best (veći bolje)
    def sort_key_by_profit_for_best(r: Dict) -> float:
        p = r.get("profit_for_best")
        if p is None:
            return -10**9  # nema profit -> šaljemo na dno
        return float(p)

    analyzed.sort(key=sort_key_by_profit_for_best, reverse=True)

    # 6) kvote_procenti.txt (isti redosled kao posle sortiranja)
    blokovi = [format_match_block(r) for r in analyzed]
    CONFIG["OUTPUT_FILE"].write_text("\n".join(blokovi) + "\n", encoding="utf-8")

    # 7) napravi tikete redom iz analyzed, po pravilima (skip Topbet, skip profit >10%)
    tickets = build_tickets_from_analyzed(analyzed)

    # 8) format + bankroll logika + analiza → tiketi.txt
    tiketi_txt = format_tickets_for_output(tickets)
    CONFIG["TICKET_FILE"].write_text(tiketi_txt, encoding="utf-8")


if __name__ == "__main__":
    main()
