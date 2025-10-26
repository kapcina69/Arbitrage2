# maxbet_full_pipeline.py
# -*- coding: utf-8 -*-
#
# Radi sledeće:
# 1) Ode na MaxBet "vremenska ponuda"
# 2) Pokuša da klikne ikonicu sporta (heuristika)
# 3) Skroluje 30 puta
# 4) Uhvati sav vidljiv tekst sa strane
# 5) Snimi ga u maxbet/maxbet_sledeci_mecevi.txt
#
# 6) Parsira taj tekst u mečeve:
#    - liga
#    - datum, vreme
#    - domaćin vs gost
#    - kvote (1,X,2)
#
# 7) Formatira lep izlaz
# 8) Snimi ga u maxbet/maxbet_mecevi_pregled.txt
#
# Zahtevi:
#   pip install playwright
#   playwright install chromium
#
# Pokretanje:
#   python3 maxbet_full_pipeline.py
#

import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# -------------------------------------------------
# PODEŠAVANJA
# -------------------------------------------------

URL = "https://www.maxbet.rs/sr/sportsko-kladjenje/vremenska-ponuda"

OUT_DIR = Path("maxbet")
RAW_FILE = OUT_DIR / "maxbet_sledeci_mecevi.txt"
PRETTY_FILE = OUT_DIR / "maxbet_mecevi_pregled.txt"

HEADLESS = True          # True = bez prozora; False = vidiš šta radi
SCROLL_STEPS = 60         # koliko puta skrolujemo
SCROLL_DELTA_PX = 2000    # jačina skrola u px po koraku
SCROLL_PAUSE_SEC = 0.25   # pauza između skrolova

# regex da prepoznamo liniju sa datumom i vremenom, npr "26.10 03:00"
RE_DATETIME = re.compile(r'^\d{2}\.\d{2}\s+\d{2}:\d{2}$')


# -------------------------------------------------
# POMOĆNE FUNKCIJE ZA PLAYWRIGHT
# -------------------------------------------------

def wait_idle(page, timeout_ms=1500):
    """Pokušaj kratko da sačeka 'networkidle'. Ako pukne timeout, samo ignoriši."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except TimeoutError:
        pass
    except PWTimeoutError:
        pass

def human_scroll(page, steps: int, delta_px: int, pause_s: float):
    """Skroluje naniže više puta da učita lazy-load sadržaj."""
    for _ in range(steps):
        page.mouse.wheel(0, delta_px)
        time.sleep(pause_s)
def _robust_click_candidate(page, cand) -> bool:
    """
    Pokuša dva načina klika nad jednim kandidatom:
    1) Playwright .click(force=True)
    2) Klik mišem u centar bounding box-a
    Vrati True ako bar jedan prođe bez exception-a.
    """
    h = cand["handle"]
    x = cand["x"]
    y = cand["y"]
    w = cand["w"]
    hgt = cand["h"]

    # 1) direktan click(force=True)
    try:
        print("[CLICK] .click(force=True)")
        h.click(timeout=800, force=True)
        time.sleep(0.25)
        return True
    except Exception as e:
        print(f"[CLICK WARN] force click nije uspeo: {e}")

    # 2) ručni klik mišem po koordinatama centra
    try:
        cx = x + w / 2.0
        cy = y + hgt / 2.0
        print(f"[CLICK] mouse.click @ ({cx:.1f},{cy:.1f})")
        page.mouse.move(cx, cy)
        time.sleep(0.05)
        page.mouse.click(cx, cy)
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"[CLICK ERR] mouse.click nije uspeo: {e}")

    return False


def try_click_sport_icon_smart(page) -> bool:
    """
    Cilj: kliknuti fudbal tab (druga ikonica s leva u traci sportova).
    Poboljšano:
    - identifikujemo horizontalnu traku sportova grupisanjem po y
    - uzimamo 2. s leva (fallback 1. s leva)
    - za svaki kandidat radimo robustan klik (_robust_click_candidate),
      koji pokušava .click(force=True), pa klik po koordinatama.
    - ako sve to padne, fallback: najmanje dugme globalno.
    """

    selectors = [
        "nav button",
        "nav [role=button]",
        "button",
        "[role=button]",
        "div[role=button]",
    ]

    handles = []
    for sel in selectors:
        try:
            for h in page.locator(sel).element_handles():
                handles.append(h)
        except Exception:
            pass

    if not handles:
        print("[WARN] Nisu pronađena dugmad za klik.")
        return False

    # Sakupi kandidate sa bounding box-om i tekstom
    candidates = []
    for h in handles:
        try:
            box = h.bounding_box()
            if not box:
                continue
            if box["width"] <= 0 or box["height"] <= 0:
                continue

            try:
                txt = h.inner_text()
            except Exception:
                txt = ""

            candidates.append({
                "handle": h,
                "x": box["x"],
                "y": box["y"],
                "w": box["width"],
                "h": box["height"],
                "txt": txt.strip(),
            })
        except Exception:
            pass

    if not candidates:
        print("[WARN] Nema kandidata sa validnim bounding box-om.")
        return False

    # Grupisanje po horizontali: bucket po y visini
    rows = {}
    for cand in candidates:
        bucket_y = round(cand["y"] / 20.0) * 20.0
        rows.setdefault(bucket_y, []).append(cand)

    # Izaberi "najgušći" red -> verovatno traka sportova
    best_row_y = None
    best_row_list = []
    for bucket_y, row_list in rows.items():
        if len(row_list) > len(best_row_list):
            best_row_y = bucket_y
            best_row_list = row_list

    if not best_row_list:
        print("[WARN] Nije detektovana traka sportova, fallback by size.")
        # fallback odmah ide na najmanje dugme
        smallest = sorted(candidates, key=lambda c: (c["w"] * c["h"]))[0]

        print(
            "[TRY] Fallback najmanje dugme: "
            f"x={smallest['x']:.1f}, y={smallest['y']:.1f}, "
            f"w={smallest['w']:.1f}, h={smallest['h']:.1f}, "
            f"txt='{smallest['txt'][:40]}'"
        )

        if _robust_click_candidate(page, smallest):
            return True

        print("[ERR] Ni fallback najmanje dugme nije kliknuto.")
        return False

    # Sortiraj red po x (sleva nadesno)
    row_sorted = sorted(best_row_list, key=lambda c: c["x"])

    # probaj DRUGOG s leva (idx 1), pa ako ne uspe, PRVOG (idx 0)
    preferred = []
    if len(row_sorted) >= 2:
        preferred.append(row_sorted[1])
    preferred.append(row_sorted[0])

    for cand in preferred:
        print(
            "[TRY] Klik sport ikonica iz reda: "
            f"x={cand['x']:.1f}, y={cand['y']:.1f}, "
            f"w={cand['w']:.1f}, h={cand['h']:.1f}, "
            f"txt='{cand['txt'][:40]}'"
        )

        if _robust_click_candidate(page, cand):
            return True

    # Ako drugi/Prvi u sport traci nisu uspeli, poslednji fallback:
    smallest = sorted(candidates, key=lambda c: (c["w"] * c["h"]))[0]
    print(
        "[TRY] Second fallback najmanje dugme: "
        f"x={smallest['x']:.1f}, y={smallest['y']:.1f}, "
        f"w={smallest['w']:.1f}, h={smallest['h']:.1f}, "
        f"txt='{smallest['txt'][:40]}'"
    )
    if _robust_click_candidate(page, smallest):
        return True

    print("[ERR] Second fallback klik nije uspeo.")
    return False

# -------------------------------------------------
# POMOCNE FUNKCIJE ZA PARSIRANJE
# -------------------------------------------------

def is_datetime_line(s: str) -> bool:
    # "26.10 03:00"
    return bool(RE_DATETIME.match(s.strip()))

def is_league_line(s: str) -> bool:
    """
    Liga je uppercase string (može da sadrži cifre), npr "COSTA RICA 1".
    Ne sme da bude prazan, ne sme da počinje sa '+',
    ne sme da izgleda kao "26.10 03:00",
    mora imati bar jedno veliko slovo,
    i nije samo brojevi/tačke/dvotačke.
    """
    s_stripped = s.strip()
    if len(s_stripped) < 3:
        return False
    if is_datetime_line(s_stripped):
        return False
    if s_stripped.startswith('+'):
        return False
    if not re.search(r'[A-ZČĆŽŠĐ]', s_stripped):
        return False
    if s_stripped != s_stripped.upper():
        return False
    if re.fullmatch(r'[0-9:.\-\s]+', s_stripped):
        return False
    return True

def parse_matches_from_lines(lines):
    """
    lines: lista stringova iz RAW fajla
    Vrati listu dict mečeva:
        {
          "league": ...,
          "date": "26.10",
          "time": "03:00",
          "home": "Herediano",
          "away": "Cartagines",
          "odds": {
             "1": "2.12",
             "X": "3.15",
             "2": "3.30",
             ...
          }
        }
    """
    matches = []
    current_league = None
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i].strip()

        # ažuriraj ligu kad naiđemo na novu
        if is_league_line(line):
            current_league = line

        # početak meča ako je linija "DD.MM HH:MM"
        if is_datetime_line(line):
            parts = line.split()
            date_part = parts[0] if len(parts) >= 1 else ""
            time_part = parts[1] if len(parts) >= 2 else ""

            j = i + 1

            # preskoči prazno
            while j < n and lines[j].strip() == "":
                j += 1

            # opcioni kod meča "+806"
            if j < n and lines[j].strip().startswith("+"):
                # match_code = lines[j].strip().lstrip("+").strip()  # trenutno ga ne koristimo
                j += 1

            # opet preskoči prazno
            while j < n and lines[j].strip() == "":
                j += 1
            if j >= n:
                break

            # home team
            home_team = lines[j].strip()
            j += 1
            if j >= n:
                break

            # away team
            away_team = lines[j].strip()
            j += 1

            # sad skupljamo kvote u formatu:
            #   oznaka (1/X/2/0-2/3+...)
            #   vrednost (2.12 itd.)
            odds = {}

            while j < n:
                tok = lines[j].strip()

                # ako smo naleteli na novi meč (datum/vreme), novu ligu ili "+kod",
                # prestajemo sa skupljanjem kvota za ovaj meč
                if tok == "":
                    j += 1
                    continue
                if is_datetime_line(tok) or is_league_line(tok) or tok.startswith("+"):
                    break

                if j + 1 >= n:
                    break

                val = lines[j + 1].strip()
                # kvota je broj, npr "2.12"
                if re.fullmatch(r'\d+(\.\d+)?', val):
                    odds[tok] = val
                    j += 2
                else:
                    # ne liči na kvotu => kraj liste kvota
                    break

            matches.append({
                "league": current_league,
                "date": date_part,
                "time": time_part,
                "home": home_team,
                "away": away_team,
                "odds": odds,
            })

            # skoči tamo gde smo stali
            i = j - 1

        i += 1

    return matches

def format_match_block(m):
    """
    Format za jedan meč:

    ======================================================================
    03:00  26.10.  [COSTA RICA 1]
    Herediano  vs  Cartagines
    1=2.12   X=3.15   2=3.30
    0-2=-   2+=-   3+=-
    GG=-   IGG=-   GG&3+=-
    ======================================================================

    Napomena:
    - Nemamo dan u nedelji → ne štampamo
    - Nemamo ID → ne štampamo
    - Ako nema kvote za nešto → "-"
    """

    league = m["league"] or ""
    line_header = f"{m['time']}  {m['date']}.  [{league}]"

    home = m["home"]
    away = m["away"]

    # osnovne kvote
    odd1 = m["odds"].get("1", "-")
    oddX = m["odds"].get("X", "-")
    odd2 = m["odds"].get("2", "-")

    # ostalo za sad ne parsiramo → "-"
    line_1x2   = f"1={odd1}   X={oddX}   2={odd2}"
    line_uOver = "0-2=-   2+=-   3+=-"
    line_gg    = "GG=-   IGG=-   GG&3+=-"

    block = []
    block.append("=" * 70)
    block.append(line_header)
    block.append(f"{home}  vs  {away}")
    block.append(line_1x2)
    block.append(line_uOver)
    block.append(line_gg)
    block.append("=" * 70)
    return "\n".join(block)


# -------------------------------------------------
# PIPELINE
# -------------------------------------------------

def main():
    # 0) napravi folder maxbet ako ne postoji
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # 1) pokreni browser
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="sr-RS",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            geolocation={"latitude": 44.817, "longitude": 20.457},
            permissions=["geolocation"],
        )

        page = context.new_page()

        # 2) idi na stranicu
        print(f"[*] Otvaram {URL} ...")
        page.goto(URL, timeout=60_000, wait_until="domcontentloaded")

        # kratko čekanje da se sve nacrta
        wait_idle(page, 2000)
        time.sleep(1.0)

        # 3) probaj da klikneš ikonicu sporta/tab
        print("[*] Pokušavam klik na sport/tab ikonici ...")
        clicked = try_click_sport_icon_smart(page)
        print(f"[INFO] Klik uspeo? {clicked}")

        # 4) skroluj 30 puta
        print(f"[*] Skrolujem {SCROLL_STEPS} puta ...")
        human_scroll(page, SCROLL_STEPS, SCROLL_DELTA_PX, SCROLL_PAUSE_SEC)

        # posle skrola, daj sajtu da dovuče sve
        wait_idle(page, 2000)
        time.sleep(1.0)

        # 5) pokupi samo vidljiv tekst
        print("[*] Čitam document.body.innerText ...")
        try:
            body_text = page.evaluate("() => document.body.innerText")
        except Exception as e:
            body_text = f"[GREŠKA body.innerText] {e}"

        # zatvori browser
        browser.close()

    # 6) snimi RAW tekst u maxbet_sledeci_mecevi.txt
    RAW_FILE.write_text(body_text, encoding="utf-8")
    print(f"[OK] Sačuvan RAW: {RAW_FILE} (dužina: {len(body_text)} bajtova)")

    # 7) parsiraj RAW tekst u mečeve
    lines = body_text.splitlines()
    matches = parse_matches_from_lines(lines)

    print(f"[OK] Prepoznato mečeva: {len(matches)}")

    # 8) napravi "lep" pregled
    pretty_blocks = [format_match_block(m) for m in matches]
    pretty_text = "\n".join(pretty_blocks) + ("\n" if pretty_blocks else "")

    # 9) snimi pretty fajl maxbet_mecevi_pregled.txt
    PRETTY_FILE.write_text(pretty_text, encoding="utf-8")
    print(f"[OK] Sačuvan pregled: {PRETTY_FILE}")

    # 10) kratki preview u konzoli
    if pretty_blocks:
        print("=== PREVIEW ===")
        print("\n".join(pretty_blocks[:1]))  # samo prvi meč za pregled
    else:
        print("[WARN] Nema prepoznatih mečeva za PREVIEW.")


if __name__ == "__main__":
    main()
