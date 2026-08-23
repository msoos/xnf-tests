#!/usr/bin/env python3
"""Convert XNF to CNF-XOR the way the Xorricane paper does: ./xnf_to_xcnf.py *.xnf"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

Lineral = tuple[tuple[int, ...], int]  # (sorted support, constant)


def parse_lineral(token: str) -> Lineral:
    support: set[int] = set()
    const = 0
    for part in token.split("+"):
        lit = int(part)
        if lit == 0:
            const ^= 1  # xorricane reads a bare '0' inside a lineral as a negation
            continue
        if lit < 0:
            const ^= 1
            lit = -lit
        support ^= {lit}
    return tuple(sorted(support)), const


def parse_xnf(path: str) -> tuple[int, list[list[Lineral]]]:
    nvars = 0
    clauses: list[list[Lineral]] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line[0] == "c":
                continue
            if line[0] == "p":
                nvars = int(line.split()[2])
                continue
            tokens = line.split()
            if tokens[-1] != "0":
                raise ValueError(f"{path}: unterminated clause: {line}")
            clauses.append([parse_lineral(t) for t in tokens[:-1]])
    return nvars, clauses


def xor_line(support: tuple[int, ...], negations: int) -> str:
    lits = list(support)
    if negations:
        lits[0] = -lits[0]
    return "x " + " ".join(str(l) for l in lits) + " 0"


def convert(nvars: int, clauses: list[list[Lineral]], reuse: bool = True) -> tuple[int, list[str]]:
    next_var = nvars + 1
    ydef: dict[tuple[int, ...], tuple[int, int]] = {}
    out: list[str] = []

    for clause in clauses:
        # a lineral with empty support is the constant `const`
        if any(not sup and const for sup, const in clause):
            continue
        clause = [(sup, const) for sup, const in clause if sup]

        if not clause:
            out.append("0")
            continue

        if len(clause) == 1:
            support, const = clause[0]
            if len(support) == 1:
                out.append(f"{-support[0] if const else support[0]} 0")
            else:
                out.append(xor_line(support, const))
            continue

        lits = []
        for support, const in clause:
            if len(support) == 1:
                lits.append(-support[0] if const else support[0])
                continue
            if not reuse or support not in ydef:
                ydef[support] = (next_var, const)
                out.append(xor_line(tuple(sorted(support + (next_var,))), const))
                next_var += 1
            y, first_const = ydef[support]
            lits.append(-y if const == first_const else y)
        out.append(" ".join(str(l) for l in lits) + " 0")

    return next_var - 1, out


def convert_file(src: str, reuse: bool = True, suffix: str = ".xcnf") -> tuple[str, str | None]:
    dst = os.path.splitext(src)[0] + suffix
    try:
        nvars, clauses = parse_xnf(src)
        total_vars, lines = convert(nvars, clauses, reuse=reuse)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(f"p cnf {total_vars} {len(lines)}\n")
            f.write("\n".join(lines) + "\n")
    except (OSError, ValueError, IndexError) as exc:
        return src, str(exc)
    return src, None


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert XNF to CNF-XOR (Xorricane-paper encoding).")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--suffix", default=".xcnf", help="output extension (default: .xcnf)")
    ap.add_argument("--no-reuse", action="store_true",
                    help="fresh variable per lineral occurrence instead of per distinct support")
    args = ap.parse_args()

    failed = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for src, err in pool.map(lambda f: convert_file(f, not args.no_reuse, args.suffix), args.files):
            if err:
                failed += 1
                print(f"FAIL {src}: {err}", file=sys.stderr)
            elif not args.quiet:
                print(f"{src} -> {os.path.splitext(src)[0]}{args.suffix}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
