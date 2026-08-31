#!/usr/bin/env python3
"""Check SATISFIABLE answers against the instance they came from: ./verify_sat.py xorricane-bench"""

from __future__ import annotations

import argparse
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial

RE_STATUS = re.compile(r"^s +(\S+)", re.M)
RE_INPUT = re.compile(r"^c reading XNF from (.+)$", re.M)  # xorricane echoes the file it parsed


def parse_solution(path: str) -> tuple[str, str | None, dict[int, int], list[str]]:
    problems: list[str] = []
    assign: dict[int, int] = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    m = RE_STATUS.search(text)
    status = m.group(1) if m else "NONE"
    logged = RE_INPUT.search(text)
    for line in text.splitlines():
        if not line.startswith("v "):
            continue
        for tok in line.split()[1:]:
            lit = int(tok)
            if lit == 0:
                continue
            val = 0 if lit < 0 else 1
            var = abs(lit)
            if assign.get(var, val) != val:
                problems.append(f"variable {var} assigned both ways")
            assign[var] = val
    return status, logged.group(1).strip() if logged else None, assign, problems


def eval_lineral(parts: list[str], assign: dict[int, int]) -> int | None:
    """XOR of the literals: 1 = true, None = some variable is unassigned."""
    val = 0
    for part in parts:
        lit = int(part)
        if lit == 0:  # a bare 0 inside a lineral is a negation
            val ^= 1
            continue
        if lit < 0:
            val ^= 1
            lit = -lit
        v = assign.get(lit)
        if v is None:
            return None
        val ^= v
    return val


def check_instance(path: str, assign: dict[int, int]) -> tuple[int, int, int]:
    """Returns (nvars, index of the first false clause or 0, count of undecided clauses)."""
    nvars = idx = unknown = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line[0] == "c":
                continue
            if line[0] == "p":
                nvars = int(line.split()[2])
                continue
            idx += 1
            tokens = line.split()
            if tokens[-1] != "0":
                raise ValueError(f"unterminated clause: {line[:60]}")
            if tokens[0][0] == "x":
                # a CNF-XOR line is one lineral; "x 1 -2 0" and the glued "x-2 1 0" both occur
                linerals = [[t for t in [tokens[0][1:]] + tokens[1:-1] if t]]
            else:
                linerals = [t.split("+") for t in tokens[:-1]]
            sat = unk = False
            for parts in linerals:
                v = eval_lineral(parts, assign) if parts else 0
                if v == 1:
                    sat = True
                    break
                unk = unk or v is None
            if not sat:
                if not unk:
                    return nvars, idx, unknown
                unknown += 1
    return nvars, 0, unknown


def check(out_path: str, suffix: str) -> tuple[str, str, str]:
    src = out_path[: -len(suffix)]
    try:
        status, logged, assign, problems = parse_solution(out_path)
    except (OSError, ValueError) as exc:
        return out_path, "ERROR", str(exc)
    if logged and os.path.abspath(logged) != os.path.abspath(src):
        return out_path, "ERROR", f"solver read {logged}, not {src}"
    if status != "SATISFIABLE":
        return out_path, "SKIP", status
    if not assign:
        return out_path, "ERROR", "SATISFIABLE but no v-lines"

    try:
        nvars, false_clause, unknown = check_instance(src, assign)
    except (OSError, ValueError, IndexError) as exc:
        return out_path, "ERROR", f"{os.path.basename(src)}: {exc}"
    if false_clause:
        return out_path, "WRONG", f"clause {false_clause} of {os.path.basename(src)} is false"

    missing = [v for v in range(1, nvars + 1) if v not in assign]
    if missing:
        problems.append(f"{len(missing)} of {nvars} variables unassigned (first: {missing[0]})")
    if unknown:
        problems.append(f"{unknown} clauses undecided (unassigned variables)")
    return out_path, "OK", "; ".join(problems)


def collect(paths: list[str], suffix: str) -> list[str]:
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files.extend(os.path.join(root, n) for n in names if n.endswith(suffix))
        else:
            files.append(p)
    return sorted(set(files))


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify SATISFIABLE answers against their XNF/CNF input.")
    ap.add_argument("paths", nargs="+", help="output files, or dirs to search")
    ap.add_argument("-s", "--suffix", default=".out-xorricane",
                    help="solver output extension (default: .out-xorricane)")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("-v", "--verbose", action="store_true", help="also print the OK lines")
    args = ap.parse_args()

    files = collect(args.paths, args.suffix)
    if not files:
        print(f"no {args.suffix} files found", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    bad = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for path, verdict, detail in pool.map(partial(check, suffix=args.suffix), files):
            counts[verdict] = counts.get(verdict, 0) + 1
            if verdict in ("WRONG", "ERROR"):
                bad += 1
            if verdict in ("WRONG", "ERROR") or (verdict == "OK" and detail) or args.verbose:
                print(f"{verdict:5s} {path}" + (f"  -- {detail}" if detail else ""))

    print(f"{len(files)} files: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
