#!/usr/bin/env python3
"""Summarise run outcomes and spot memory-outs: ./check_runs.py [dirs...]"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

RE_SIGNAL = re.compile(r"Command terminated by signal (\d+)")
RE_STATUS = re.compile(r"Command exited with non-zero status (\d+)")
RE_RSS = re.compile(r"Maximum resident set size \(kbytes\): (\d+)")
RE_ELAPSED = re.compile(r"Elapsed \(wall clock\)[^\n]*")
RE_LIMIT = re.compile(r"timeout -k \d+ (\d+)")
RE_OOM_MSG = re.compile(r"bad_alloc|out of memory|Cannot allocate memory|std::bad_alloc", re.I)


def parse_elapsed(text: str) -> float:
    parts = text.strip().split(":")
    try:
        secs = float(parts[-1])
        if len(parts) > 1:
            secs += 60 * int(parts[-2])
        if len(parts) > 2:
            secs += 3600 * int(parts[-3])
        return secs
    except ValueError:
        return -1.0


def parse(path: str) -> dict | None:
    try:
        with open(path, errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    rss = RE_RSS.search(text)
    elapsed = RE_ELAPSED.search(text)
    limit = RE_LIMIT.search(text)
    signal = RE_SIGNAL.search(text)
    status = RE_STATUS.search(text)
    return {
        "rss_kb": int(rss.group(1)) if rss else 0,
        "elapsed": parse_elapsed(elapsed.group(0).rsplit(": ", 1)[-1]) if elapsed else -1.0,
        "limit": int(limit.group(1)) if limit else 0,
        "signal": int(signal.group(1)) if signal else 0,
        "status": int(status.group(1)) if status else 0,
    }


def classify(rec: dict, out_path: str) -> str:
    # a kill well before the wall-clock limit is the OOM killer, not `timeout -k`
    early = rec["limit"] and 0 <= rec["elapsed"] < rec["limit"] * 0.9
    if rec["signal"] == 9:
        return "MEMOUT" if early else "TIMEOUT"
    if rec["status"] == 124 or rec["signal"] == 15:
        return "TIMEOUT"
    if rec["status"] in (10, 20):
        return "SOLVED"
    try:
        with open(out_path, errors="replace") as f:
            text = f.read()
    except OSError:
        text = ""
    if RE_OOM_MSG.search(text):
        return "MEMOUT"
    if re.search(r"^s (SATISFIABLE|UNSATISFIABLE)", text, re.M):
        return "SOLVED"
    if rec["status"]:
        return f"ERROR({rec['status']})"
    return "NOSOLVE"


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarise solver runs from /usr/bin/time -v output.")
    ap.add_argument("paths", nargs="*", default=["."], help="dirs to scan (default: .)")
    ap.add_argument("-n", "--top", type=int, default=10, help="how many top-RSS runs to list")
    ap.add_argument("--min-gb", type=float, default=0.0, help="only list runs above this RSS")
    ap.add_argument("-x", "--exclude", action="append", default=[], help="skip dirs with this name")
    args = ap.parse_args()

    by_solver: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    peak: dict[str, int] = defaultdict(int)
    rows = []
    seen = set()

    for root_path in args.paths:
        for root, _, names in os.walk(root_path):
            parts = root.split(os.sep)
            if ".git" in parts or any(e in parts for e in args.exclude):
                continue
            for n in names:
                if ".timeout-" not in n:
                    continue
                path = os.path.join(root, n)
                real = os.path.realpath(path)
                if real in seen:
                    continue
                seen.add(real)
                rec = parse(path)
                if rec is None:
                    continue
                stem, solver = n.rsplit(".timeout-", 1)
                verdict = classify(rec, os.path.join(root, stem + ".out-" + solver))
                by_solver[solver][verdict] += 1
                peak[solver] = max(peak[solver], rec["rss_kb"])
                rows.append((rec["rss_kb"], solver, verdict, rec["elapsed"],
                             rec["limit"], os.path.join(root, stem)))

    if not rows:
        print("no .timeout-* files found", file=sys.stderr)
        return 1

    verdicts = sorted({v for counts in by_solver.values() for v in counts})
    width = max(len(s) for s in by_solver) + 2
    print(f"{'solver':<{width}}" + "".join(f"{v:>12}" for v in verdicts) + f"{'peak RSS':>12}")
    for solver in sorted(by_solver):
        line = f"{solver:<{width}}" + "".join(f"{by_solver[solver].get(v, 0):>12}" for v in verdicts)
        print(line + f"{peak[solver] / 1048576:>10.1f}G")

    memouts = [r for r in rows if r[2] == "MEMOUT"]
    if memouts:
        print(f"\n{len(memouts)} memory-out(s):")
        for rss, solver, _, elapsed, limit, stem in sorted(memouts, reverse=True):
            print(f"  {rss / 1048576:7.1f}G  {solver:<10} killed at {elapsed:7.1f}s of {limit}s  {stem}")

    rows.sort(reverse=True)
    shown = [r for r in rows if r[0] / 1048576 >= args.min_gb][: args.top]
    if shown:
        print(f"\ntop {len(shown)} by peak RSS:")
        for rss, solver, verdict, elapsed, _, stem in shown:
            print(f"  {rss / 1048576:7.1f}G  {solver:<10} {verdict:<12} {elapsed:7.1f}s  {stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
