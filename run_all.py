# -*- coding: utf-8 -*-

import subprocess
import time
from pathlib import Path
from typing import List, Tuple, Dict
from datetime import datetime

# === Podesivo ===
PY = "python3"
START_DELAY_SEC = 10       # ← pauza između STARTOVA (ne čekamo završetak prethodne)
TIMEOUT_EACH = 10 * 60
MIN_BYTES = 100
STABILITY_CHECKS = 2
STABILITY_SLEEP = 1.0
MAX_WAIT_STABLE = 60
RUN_EVERY_MIN = 60
CONTINUOUS_MODE = True

# Redosled pokretanja = redosled u listi:
# Svaki scraper i fajlovi koje očekujemo da proizvede.
SCRAPERS: List[Tuple[str, List[Path]]] = [
    (
        "soccer.py",
        [
            Path("soccer/soccer_sledeci_mecevi.txt"),
            Path("soccer/soccer_mecevi_pregled.txt"),
        ],
    ),
    (
        "meridian.py",
        [
            Path("meridian/meridian_sledeci_mecevi.txt"),
            Path("meridian/meridian_mecevi_pregled.txt"),
        ],
    ),
    (
        "merkur.py",
        [
            Path("merkur/merkur_sledeci_mecevi.txt"),
            Path("merkur/merkur_mecevi_pregled.txt"),
        ],
    ),
    (
        "mozzart.py",
        [
            Path("mozzart/mozzart_sledeci_mecevi.txt"),
            Path("mozzart/mozzart_mecevi_pregled.txt"),
        ],
    ),
    (
        "betole.py",
        [
            Path("betole/betole_sledeci_mecevi.txt"),
            Path("betole/betole_mecevi_pregled.txt"),
        ],
    ),
    (
        "balkanbet.py",
        [
            Path("balkanbet/balkanbet_sledeci_mecevi.txt"),
            Path("balkanbet/balkanbet_mecevi_pregled.txt"),
        ],
    ),
    (
        "brazil.py",
        [
            Path("brazil/brazil_sledeci_mecevi.txt"),
            Path("brazil/brazil_mecevi_pregled.txt"),
        ],
    ),
    (
        "brazil_sutra.py",
        [
            Path("brazil/brazil_sutra_sledeci_mecevi.txt"),
            Path("brazil/brazil_sutra_mecevi_pregled.txt"),
        ],
    ),
    (
        "brazil_prekosutra.py",
        [
            Path("brazil/brazil_prekosutra_sledeci_mecevi.txt"),
            Path("brazil/brazil_prekosutra_mecevi_pregled.txt"),
        ],
    ),
    (
        "topbet.py",
        [
            Path("topbet/topbet_sledeci_mecevi.txt"),
            Path("topbet/topbet_mecevi_pregled.txt"),
        ],
    ),
    (
        "oktagon.py",
        [
            Path("oktagonbet/oktagonbet_sledeci_mecevi.txt"),
            Path("oktagonbet/oktagonbet_mecevi_pregled.txt"),
        ],
    ),
    (
        "maxbet.py",
        [
            Path("maxbet/maxbet_sledeci_mecevi.txt"),
            Path("maxbet/maxbet_mecevi_pregled.txt"),
        ],
    ),
]

# prvo ide proba.py (spajanje svih kladionica i pronalazak arbitraža)
MAIN_SCRIPT = "proba.py"

# odmah posle toga ide procenti.py (račun tiketa, procenti, itd.)
SECOND_SCRIPT = "procenti.py"

# proba.py sada upisuje u ALL_MATCHES_AND_ARBS/
MAIN_OUTPUTS = [
    Path("ALL_MATCHES_AND_ARBS/kvote_arbitraza_FULL.txt"),
    Path("ALL_MATCHES_AND_ARBS/kvote_arbitraza_ONLY_arbs.txt"),
]

# fajl koji pokušavamo da push-ujemo na git
TARGET_PUSH = Path("ALL_MATCHES_AND_ARBS/kvote_arbitraza_FULL.txt")

# folder gde će se čuvati izveštaji svakog ciklusa
REPORT_DIR = Path("izvestaji")


# =========== Pomoćne ===========
def fmt_duration(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = seconds - mins * 60
    return f"{mins:02d}:{secs:05.2f}"

def _run(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


# =========== GIT ===========
def git_in_repo() -> bool:
    try:
        cp = _run(["git", "rev-parse", "--is-inside-work-tree"], check=False)
        return cp.returncode == 0 and cp.stdout.strip() == "true"
    except Exception:
        return False

def git_has_remote() -> bool:
    try:
        cp = _run(["git", "remote"], check=False)
        return bool(cp.stdout.strip())
    except Exception:
        return False

def git_push_file(path: Path) -> None:
    if not path.exists():
        print(f"[git] Preskačem push — ne postoji {path}")
        return
    if not git_in_repo():
        print("[git] Nisi u Git repou. Preskačem push.")
        return
    if not git_has_remote():
        print("[git] Nema remote-a. Preskačem push.")
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        _run(["git", "add", str(path)], check=False)
        msg = f"auto: update {path.name} @ {ts}"
        cp_commit = _run(["git", "commit", "-m", msg], check=False)
        if cp_commit.returncode != 0:
            print(f"[git] Nema promena za commit ({path.name}).")
            return
        print(f"[git] Commit ok: {msg}")
        cp_push = _run(["git", "push"], check=False)
        if cp_push.returncode != 0:
            print(f"[git] PUSH FAIL:\n{cp_push.stderr.strip()}")
        else:
            print("[git] Push uspešan.")
    except Exception as e:
        print(f"[git] Greška: {e}")


# =========== Stabilnost fajla ===========
def wait_for_file_stable(
    path: Path,
    min_bytes: int = MIN_BYTES,
    checks: int = STABILITY_CHECKS,
    sleep_s: float = STABILITY_SLEEP,
    max_wait: int = MAX_WAIT_STABLE
) -> bool:
    start_time = time.time()
    deadline = start_time + TIMEOUT_EACH
    max_stable_wait = start_time + max_wait

    # 1) čekaj nastanak
    while time.time() < deadline:
        if path.exists():
            break
        time.sleep(0.5)
    else:
        print(f"[!] Fajl {path} nije nastao u roku.")
        return False

    # 2) min veličina
    size_deadline = time.time() + max_wait
    while time.time() < size_deadline and time.time() < deadline:
        try:
            size = path.stat().st_size
            if size >= min_bytes:
                break
        except OSError:
            pass
        time.sleep(0.5)
    else:
        try:
            final_size = path.stat().st_size
            print(f"[!] Fajl {path} je premali ({final_size} < {min_bytes}). Preskačem.")
        except OSError:
            print(f"[!] Fajl {path} nije dostupan.")
        return False

    # 3) stabilnost
    last_size = None
    stable_count = 0
    while stable_count < checks and time.time() < max_stable_wait and time.time() < deadline:
        try:
            current_size = path.stat().st_size
        except OSError:
            print(f"[!] Greška pri čitanju {path}.")
            return False

        if last_size is None:
            last_size = current_size
        elif current_size == last_size:
            stable_count += 1
        else:
            last_size = current_size
            stable_count = 0

        if stable_count < checks:
            time.sleep(sleep_s)

    if stable_count >= checks:
        print(f"[OK] Fajl {path} je stabilan ({last_size} bytes).")
        return True
    else:
        print(f"[!] Fajl {path} nije postao stabilan u roku.")
        return False


# =========== Pokretanje scraper-a sa pauzom između STARTOVA ===========
def run_scrapers_staggered(scrapers: List[Tuple[str, List[Path]]]) -> None:
    """
    1) Skripte STARTUJEMO redom sa pauzom START_DELAY_SEC između startova.
    2) Ne čekamo da se prethodna završi — sve rade paralelno nakon što su pokrenute.
    3) Posle što su SVE startovane, prikupljamo rezultate i merimo trajanja.
    """
    procs: Dict[str, subprocess.Popen] = {}
    starts: Dict[str, float] = {}
    outputs_map: Dict[str, List[Path]] = {}

    # STARTUJ sve, sa pauzom između startova
    for idx, (script, outputs) in enumerate(scrapers, start=1):
        if not Path(script).exists():
            print(f"[!] Preskačem — ne postoji {script}")
        else:
            print(f"[*] START {idx}/{len(scrapers)}: {script}")
            try:
                p = subprocess.Popen([PY, script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                procs[script] = p
                starts[script] = time.time()
                outputs_map[script] = outputs
            except Exception as e:
                print(f"[!] Greška pri startovanju {script}: {e}")

        # pauza osim posle poslednjeg starta
        if idx < len(scrapers):
            print(f"[*] Pauza {START_DELAY_SEC}s pre narednog START-a...")
            time.sleep(START_DELAY_SEC)

    # SADA prikupljamo rezultate za sve pokrenute procese
    for script, p in procs.items():
        try:
            stdout, stderr = p.communicate(timeout=TIMEOUT_EACH)
        except subprocess.TimeoutExpired:
            p.kill()
            stdout, stderr = p.communicate()
            print(f"[!] TIMEOUT: {script}")

        duration = time.time() - starts.get(script, time.time())
        print(f"[TIME] {script} trajanje: {fmt_duration(duration)}")
        if stdout:
            print(f"[STDOUT:{script}]\n{stdout.strip()}\n")
        if stderr:
            print(f"[STDERR:{script}]\n{stderr.strip()}\n")

        if p.returncode == 0:
            print(f"[OK] {script} završen uspešno.")
        else:
            print(f"[!] {script} exit code: {p.returncode}")

        # (opciono) stabilnost izlaza svakog pojedinačno nakon završetka
        for outp in outputs_map.get(script, []):
            wait_for_file_stable(outp)


# =========== Main (spajanje + procenti) ===========
def run_main() -> int:
    """
    1. Pokreni proba.py (spajanje, ALL_MATCHES_AND_ARBS/...).
    2. Odmah zatim pokreni procenti.py (račun tiketa).
    3. Vrati 0 samo ako su oba prošla sa returncode == 0.
    """

    # --- prvo proba.py ---
    if not Path(MAIN_SCRIPT).exists():
        print(f"[!] Nema {MAIN_SCRIPT} — preskačem.")
        return 1

    print(f"\n[*] Pokrećem {MAIN_SCRIPT}...")
    start_t1 = time.time()
    try:
        p1 = subprocess.Popen([PY, MAIN_SCRIPT], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout1, stderr1 = p1.communicate(timeout=20 * 60)
        duration1 = time.time() - start_t1
        print(f"[TIME] {MAIN_SCRIPT} trajanje: {fmt_duration(duration1)}")

        if stdout1:
            print(f"[STDOUT:{MAIN_SCRIPT}]\n{stdout1.strip()}\n")
        if stderr1:
            print(f"[STDERR:{MAIN_SCRIPT}]\n{stderr1.strip()}\n")

        if p1.returncode == 0:
            print(f"[OK] {MAIN_SCRIPT} završen uspešno.")
        else:
            print(f"[!] {MAIN_SCRIPT} exit code: {p1.returncode}")
    except subprocess.TimeoutExpired:
        p1.kill()
        stdout1, stderr1 = p1.communicate()
        duration1 = time.time() - start_t1
        print(f"[TIME] {MAIN_SCRIPT} trajanje: {fmt_duration(duration1)}")
        print(f"[!] TIMEOUT: {MAIN_SCRIPT}")
        if stdout1:
            print(f"[STDOUT:{MAIN_SCRIPT}]\n{stdout1.strip()}\n")
        if stderr1:
            print(f"[STDERR:{MAIN_SCRIPT}]\n{stderr1.strip()}\n")
        # i dalje nastavljamo da probamo procenti.py posle timeout-a
        p1_return = -999
    except Exception as e:
        duration1 = time.time() - start_t1
        print(f"[TIME] {MAIN_SCRIPT} trajanje do greške: {fmt_duration(duration1)}")
        print(f"[!] Greška pri pokretanju {MAIN_SCRIPT}: {e}")
        p1_return = -1
    else:
        p1_return = p1.returncode

    # --- zatim procenti.py ---
    if not Path(SECOND_SCRIPT).exists():
        print(f"[!] Nema {SECOND_SCRIPT} — preskačem.")
        # vrati status samo iz proba.py
        return p1_return

    print(f"\n[*] Pokrećem {SECOND_SCRIPT}...")
    start_t2 = time.time()
    try:
        p2 = subprocess.Popen([PY, SECOND_SCRIPT], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout2, stderr2 = p2.communicate(timeout=10 * 60)
        duration2 = time.time() - start_t2
        print(f"[TIME] {SECOND_SCRIPT} trajanje: {fmt_duration(duration2)}")

        if stdout2:
            print(f"[STDOUT:{SECOND_SCRIPT}]\n{stdout2.strip()}\n")
        if stderr2:
            print(f"[STDERR:{SECOND_SCRIPT}]\n{stderr2.strip()}\n")

        if p2.returncode == 0:
            print(f"[OK] {SECOND_SCRIPT} završen uspešno.")
        else:
            print(f"[!] {SECOND_SCRIPT} exit code: {p2.returncode}")
        p2_return = p2.returncode

    except subprocess.TimeoutExpired:
        p2.kill()
        stdout2, stderr2 = p2.communicate()
        duration2 = time.time() - start_t2
        print(f"[TIME] {SECOND_SCRIPT} trajanje: {fmt_duration(duration2)}")
        print(f"[!] TIMEOUT: {SECOND_SCRIPT}")
        if stdout2:
            print(f"[STDOUT:{SECOND_SCRIPT}]\n{stdout2.strip()}\n")
        if stderr2:
            print(f"[STDERR:{SECOND_SCRIPT}]\n{stderr2.strip()}\n")
        p2_return = -999

    except Exception as e:
        duration2 = time.time() - start_t2
        print(f"[TIME] {SECOND_SCRIPT} trajanje do greške: {fmt_duration(duration2)}")
        print(f"[!] Greška pri pokretanju {SECOND_SCRIPT}: {e}")
        p2_return = -1

    # kombinovana odluka: uspeh samo ako oba su 0
    if p1_return == 0 and p2_return == 0:
        return 0
    return 1


# =========== Izveštaj ===========
def gather_report(scrapers: List[Tuple[str, List[Path]]]) -> str:
    lines = []
    now = datetime.now()
    header = f"Izveštaj od {now.strftime('%Y-%m-%d %H:%M:%S')}"
    lines.append(header)
    lines.append("=" * len(header))
    lines.append("")

    # dodaj pregled iz svakog *_pregled.txt
    for script, outs in scrapers:
        pregled = outs[1] if len(outs) > 1 else None
        if pregled and pregled.exists():
            try:
                content = pregled.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    lines.append(f"\n--- {script} :: {pregled.name} ---\n")
                    lines.append(content.strip())
                    lines.append("")
            except Exception as e:
                lines.append(f"\n[!] Greška pri čitanju {pregled}: {e}\n")

    # dodaj izlaze iz proba.py (FULL i ONLY_ARBS)
    for pth in MAIN_OUTPUTS:
        if pth.exists():
            try:
                content = pth.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    lines.append(f"\n--- MAIN :: {pth.name} ---\n")
                    lines.append(content.strip())
                    lines.append("")
            except Exception as e:
                lines.append(f"\n[!] Greška pri čitanju {pth}: {e}\n")

    return "\n".join(lines).rstrip() + "\n"


def write_timestamped_report(report_text: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = REPORT_DIR / f"izvestaj_{ts}.txt"
    try:
        out_path.write_text(report_text, encoding="utf-8")
        print(f"[OK] Sačuvan izveštaj: {out_path}")
    except Exception as e:
        print(f"[!] Greška pri čuvanju izveštaja {out_path}: {e}")
    return out_path


# =========== Ciklus ===========
def one_cycle():
    cycle_start = time.time()
    scrapers_to_run = [(s, o) for s, o in SCRAPERS if Path(s).exists()]
    if not scrapers_to_run:
        print("[!] Nema dostupnih scraper skripti!")
        return

    print(f"\n{'='*60}")
    print(f"NOVI CIKLUS: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    print(f"[*] Pokrećem {len(scrapers_to_run)} skripti sa pauzom {START_DELAY_SEC}s između STARTOVA...")
    run_scrapers_staggered(scrapers_to_run)

    ret = run_main()
    if ret == 0 and TARGET_PUSH.exists():
        print(f"\n[*] Provera stabilnosti {TARGET_PUSH} pre push-a...")
        if wait_for_file_stable(TARGET_PUSH, min_bytes=MIN_BYTES):
            git_push_file(TARGET_PUSH)
    elif ret == 0:
        print(f"[git] {TARGET_PUSH} ne postoji — nema šta da se pushuje.")

    print("\n[*] Generisanje izveštaja...")
    report_text = gather_report(scrapers_to_run)
    write_timestamped_report(report_text)

    cycle_duration = time.time() - cycle_start
    print(f"\n[OK] Ciklus završen za {fmt_duration(cycle_duration)}.")


def main_loop():
    if CONTINUOUS_MODE:
        print(f"[*] run_all.py — NEPREKIDNI REŽIM")
        print(f"[*] START-ovi sekvencijalno, pauza {START_DELAY_SEC}s (ne čeka se završetak)\n")
    else:
        print(f"[*] run_all.py — NORMALNI REŽIM")
        print(f"[*] Ciklus: {RUN_EVERY_MIN} min | Prekid: Ctrl+C\n")

    cycle_count = 0
    while True:
        cycle_count += 1
        start = time.time()
        try:
            one_cycle()
        except KeyboardInterrupt:
            print("\n\n[!] Prekid od korisnika. Izlazim.")
            break
        except Exception as e:
            print(f"\n[!] NEOČEKIVANA GREŠKA: {e}")
            import traceback
            traceback.print_exc()

        elapsed = time.time() - start
        if CONTINUOUS_MODE:
            cooldown = 10
            print(f"\n[*] Ciklus #{cycle_count} trajanje: {fmt_duration(elapsed)}")
            print(f"[*] Kratka pauza ({cooldown}s) pa sledeći ciklus...")
            print(f"{'='*60}\n")
            time.sleep(cooldown)
        else:
            sleep_sec = max(0, RUN_EVERY_MIN * 60 - elapsed)
            if sleep_sec > 0:
                mins = int(sleep_sec // 60)
                secs = int(sleep_sec % 60)
                print(f"\n[*] Ciklus #{cycle_count} trajanje: {fmt_duration(elapsed)}")
                print(f"[*] Sledeći ciklus za {mins} min {secs} sek.")
                print(f"{'='*60}\n")
                time.sleep(sleep_sec)
            else:
                print(f"\n[*] Ciklus duži od intervala — pokrećem odmah...")
                print(f"{'='*60}\n")


if __name__ == "__main__":
    main_loop()
