#!/usr/bin/env python3
"""Rewrite CNF-XOR 'x' lines as XNF linerals so xorcle can read them: ./xcnf_to_xnf.py *.xnf"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor


def convert_file(src: str, suffix: str) -> tuple[str, str | None, int]:
    dst = os.path.splitext(src)[0] + suffix
    xors = 0
    try:
        out = []
        with open(src, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line[0] == "c":
                    continue
                if line[0] == "p":
                    fields = line.split()
                    out.append(f"p xnf {fields[2]} {fields[3]}")
                elif line[0] == "x":
                    tokens = line.split()[1:]
                    if tokens[-1] != "0":
                        raise ValueError(f"unterminated xor: {line}")
                    xors += 1
                    out.append("+".join(tokens[:-1]) + " 0")
                else:
                    out.append(line)
        with open(dst, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
    except (OSError, ValueError, IndexError) as exc:
        return src, str(exc), 0
    return src, None, xors


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert CNF-XOR (x-lines) to XNF (+ linerals).")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--suffix", default=".lxnf", help="output extension (default: .lxnf)")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    failed = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for src, err, xors in pool.map(lambda f: convert_file(f, args.suffix), args.files):
            if err:
                failed += 1
                print(f"FAIL {src}: {err}", file=sys.stderr)
            elif not args.quiet:
                print(f"{src} -> {os.path.splitext(src)[0]}{args.suffix}  ({xors} xors)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
