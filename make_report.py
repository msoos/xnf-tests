#!/bin/python3
"""Render report.md to report.html, filling its {{...}} blocks from data.sqlite: ./make_report.py"""

import argparse
import csv
import os
import platform
import re
import sqlite3
import subprocess
from datetime import datetime

import yaml

DB = "data.sqlite"
PICS = "pics"
SRC = "report.md"
CSS = "report.css"
TEMPLATE = "template.html"
OUT = "report.html"

SOLVERS = {
    "cms": ("CryptoMiniSat", "CNF-XOR / CNF"),
    "cms-improved": ("CryptoMiniSat, newer build", "CNF-XOR / CNF"),
    "cms-noxor": ("CryptoMiniSat, XOR detection off", "CNF"),
    "xorcle": ("Xorcle", "XNF / CNF"),
    "xorricane": ("Xorricane", "XNF"),
    "bosphorus": ("Bosphorus", "ANF"),
}

INSTANCE_EXTS = {".cnf", ".xnf", ".xcnf", ".2xnf", ".2xcnf", ".anf", ".cnf-xor", ".bos-anf"}
FILE_FLAGS = {"--anfread"}
# timeout expressed via the solver's own flag: harness scaffolding, not configuration
TIMEOUT_FLAGS = {"-t", "--time-out", "--maxtime"}


def sh(cmd, default=""):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=10).stdout.strip() or default
    except Exception:
        return default


def cell(s):
    """A pipe-table cell: bars would end the column, newlines the row."""
    return str(s).replace("|", "\\|").replace("\n", " ")


def git_sha(path):
    """10-char SHA of the repo containing the solver binary."""
    d = os.path.dirname(os.path.abspath(path))
    while d != "/":
        if os.path.isdir(os.path.join(d, ".git")):
            sha = sh(f"git -C {d} rev-parse HEAD")
            return sha[:10] if sha else "?"
        d = os.path.dirname(d)
    return "?"


def clean_call(call):
    """Strip the timeout wrapper, binary directory, and every instance filename."""
    toks = call.split()
    if toks[:2] == ["timeout", "-k"]:
        toks = toks[4:]
    binary_path = toks[0]
    kept = [os.path.basename(binary_path)]
    skip_next = False
    for t in toks[1:]:
        if skip_next:
            skip_next = False
            continue
        if t in TIMEOUT_FLAGS:
            skip_next = True
            continue
        if "/" in t or os.path.splitext(t)[1] in INSTANCE_EXTS:
            if kept and kept[-1] in FILE_FLAGS:
                kept.pop()
            continue
        kept.append(t)
    return binary_path, " ".join(kept)


def table(header, cols, rows):
    """A pandoc pipe table. cols is (width, align) per column: the dash count sets the
    rendered column width, the : marker its alignment."""
    seps = []
    for w, a in cols:
        dashes = "-" * max(w - 2, 3)
        seps.append(f":{dashes}-" if a == "l" else f"-{dashes}:")
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(seps) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def par2_table(name):
    path = os.path.join(PICS, f"{name}_par2.csv")
    if not os.path.exists(path):
        return ""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return ""
    return table(
        ["Solver", "Solved", "Attempted", "PAR2 (s)", "Avg time solved (s)", "Peak RSS (MB)"],
        [(22, "l"), (8, "r"), (10, "r"), (9, "r"), (19, "r"), (14, "r")],
        [[cell(r["solver"]), cell(r["solved"]), cell(r["attempted"]), cell(r["par2"]),
          cell(r["avg_time_solved_s"] or "-"), cell(r["max_mem_MB"])] for r in rows])


def solver_table(con):
    rows = []
    for solver, (name, fmt) in SOLVERS.items():
        if not con.execute("SELECT COUNT(*) FROM data WHERE solver=?", (solver,)).fetchone()[0]:
            continue
        raw = con.execute(
            "SELECT call, solver_sha FROM data WHERE solver=? AND call IS NOT NULL LIMIT 1",
            (solver,)).fetchone()
        binary_path, call = clean_call(raw[0]) if raw else ("", "")
        sha = (raw[1] if raw else None) or git_sha(binary_path)
        rows.append([cell(name), f"`{cell(sha)}`", cell(fmt), f"`{cell(call)}`"])
    return table(["Solver", "Git SHA", "Input", "Command line"],
                 [(24, "l"), (12, "l"), (14, "l"), (60, "l")], rows)


def family_table(con, notes):
    rows = []
    for fam, n, lim in con.execute("""
            SELECT family, COUNT(DISTINCT instance), MIN(timeout_t)
            FROM data GROUP BY family ORDER BY family"""):
        note = notes.get(fam, {})
        rows.append([f'{cell(fam)}<br><span class="fam">{cell(note.get("label", fam))}</span>',
                     str(n), str(lim), cell(note.get("desc", ""))])
    return table(["Family", "Instances", "Timeout (s)", "Description"],
                 [(22, "l"), (11, "r"), (13, "r"), (62, "l")], rows)


def per_family(con, notes):
    out = []
    for (fam,) in con.execute(
            "SELECT family FROM data GROUP BY family ORDER BY COUNT(DISTINCT instance) DESC"):
        label = notes.get(fam, {}).get("label", fam)
        out.append(f"### {fam} — {label} {{#f_{fam}}}\n")
        svg = os.path.join(PICS, f"cdf_{fam}.svg")
        if os.path.exists(svg):
            out.append(f"![]({svg})\n")
        par2 = par2_table(f"cdf_{fam}")
        if par2:
            out.append(f"::: scroll\n{par2}\n:::\n")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Render " + SRC + " to " + OUT)
    ap.add_argument("-o", "--output", default=OUT)
    ap.add_argument("-i", "--input", default=SRC)
    args = ap.parse_args()

    for path, hint in [(DB, "./get_data_to_sqlite.py"), (PICS, "./create_graphs.py"),
                       (args.input, None), (CSS, None), (TEMPLATE, None)]:
        if not os.path.exists(path):
            raise SystemExit(f"{path} not found" + (f" -- run {hint}" if hint else ""))

    src = open(args.input).read()
    notes = {}
    if src.startswith("---"):
        notes = (yaml.safe_load(src.split("---", 2)[1]) or {}).get("families", {})

    con = sqlite3.connect(DB)
    n_fam = con.execute("SELECT COUNT(DISTINCT family) FROM data").fetchone()[0]
    total_runs = con.execute("SELECT COUNT(*) FROM data").fetchone()[0]
    total_inst = con.execute(
        "SELECT COUNT(DISTINCT family || '/' || instance) FROM data").fetchone()[0]

    blocks = {
        "solver_table": lambda: solver_table(con),
        "family_table": lambda: family_table(con, notes),
        "per_family": lambda: per_family(con, notes),
        "total_instances": lambda: str(total_inst),
    }

    def expand(m):
        key, _, arg = m.group(1).strip().partition(" ")
        if key == "par2":
            return par2_table(arg.strip())
        if key not in blocks:
            raise SystemExit(f"{args.input}: unknown placeholder {{{{{m.group(1)}}}}}")
        return blocks[key]()

    md = re.sub(r"\{\{([^}\n]+)\}\}", expand, src)
    con.close()

    cpu = sh("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2", platform.processor()).strip()
    ram = sh("free -g | awk 'NR==2{print $2}'", "?")
    subtitle = (f"{total_runs} solver runs over {total_inst} instances in {n_fam} benchmark "
                f"families · {cpu}, {ram} GB RAM · "
                f"generated {datetime.now().strftime('%Y-%m-%d')}")

    proc = subprocess.run(
        ["pandoc", "--from", "markdown", "--to", "html5", "--standalone",
         "--embed-resources", "--toc", "--toc-depth=2",
         "--template", TEMPLATE, "--css", CSS,
         "--metadata", f"subtitle={subtitle}",
         "--output", args.output, "-"],
        input=md, text=True)
    if proc.returncode != 0:
        return proc.returncode

    size = os.path.getsize(args.output) / 1024
    print(f"wrote {args.output} ({size:.0f} KB, {n_fam} families, self-contained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
