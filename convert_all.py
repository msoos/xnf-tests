#!/usr/bin/env python3
"""Convert many XNF files to CNF-XOR: ./convert_all.py *.cnf"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

CONVERT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "xorcle", "tools", "xnf_convert.py")


def out_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    return (base if ext else path) + ".cnf-xor"


def convert(path: str) -> tuple[str, str | None]:
    dst = out_path(path)
    res = subprocess.run([sys.executable, CONVERT, "cnf-xor", path, dst],
                         capture_output=True, text=True)
    if res.returncode != 0:
        return path, (res.stderr.strip() or f"exit {res.returncode}")
    return path, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert XNF files to CNF-XOR in place.")
    parser.add_argument("files", nargs="+")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()

    if not os.path.exists(CONVERT):
        print(f"error: {CONVERT} not found", file=sys.stderr)
        return 1

    failed = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for path, err in pool.map(convert, args.files):
            if err:
                failed += 1
                print(f"FAIL {path}: {err}", file=sys.stderr)
            else:
                print(f"{path} -> {out_path(path)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
