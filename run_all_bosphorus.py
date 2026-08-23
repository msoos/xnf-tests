#!/usr/bin/env python3
"""Run bosphorus --solve-xnf on ANF files: ./run_all_bosphorus.py <files-or-dirs>..."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BOSPHORUS = os.path.join(HERE, "bosphorus", "build", "bosphorus")


def collect(paths: list[str], exts: list[str]) -> list[str]:
    wanted = {e if e.startswith(".") else "." + e for e in exts}
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files.extend(os.path.join(root, n) for n in names
                             if os.path.splitext(n)[1] in wanted)
        else:
            files.append(p)
    return sorted(set(files))


def to_bosphorus_anf(src: str, dst: str) -> None:
    """First line lists the indeterminates (comma+space separated), rest are polynomials."""
    lines = [l.strip() for l in open(src) if l.strip() and not l.startswith("#")]
    idx = {n.strip(): i + 1 for i, n in enumerate(re.split(r",\s+", lines[0])) if n.strip()}
    out = []
    for line in lines[1:]:
        terms = []
        for term in line.split("+"):
            term = term.strip()
            if not term:
                continue
            if term in ("0", "1"):
                terms.append(term)
                continue
            factors = []
            for v in term.split("*"):
                v = v.strip()
                if v not in idx:
                    raise ValueError(f"{src}: undeclared indeterminate '{v}'")
                factors.append(f"x({idx[v]})")
            terms.append("*".join(factors))
        out.append(" + ".join(terms))
    with open(dst, "w") as f:
        f.write("\n".join(out) + "\n")


def needs_convert(path: str) -> bool:
    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith(("#", "c ")):
                return "," in line and "+" not in line
    return False


def result_of(rc: int, out: str) -> str:
    if rc == 124:
        return "TIMEOUT"
    try:
        with open(out, errors="replace") as f:
            for line in f:
                if line.startswith("s "):
                    return line[2:].strip()
    except OSError:
        pass
    return f"UNKNOWN(rc={rc})"


def run_one(binary: str, opts: list[str], timeout: int, convert: str, path: str) -> tuple[str, str, float]:
    out, tim = path + ".out-bosphorus", path + ".timeout-bosphorus"
    start = time.monotonic()
    anf = path
    if convert == "always" or (convert == "auto" and needs_convert(path)):
        anf = path + ".bos-anf"
        try:
            to_bosphorus_anf(path, anf)
        except (ValueError, OSError, IndexError) as e:
            with open(out, "w") as fout:
                fout.write(f"c convert failed: {e}\n")
            return path, "CONVERT-FAIL", time.monotonic() - start
    with open(out, "w") as fout:
        rc = subprocess.call(["/usr/bin/time", "-v", "-o", tim,
                              "timeout", "-k", "10", str(timeout), binary,
                              "--anfread", anf, "--solve-xnf"] + opts,
                             stdout=fout, stderr=subprocess.STDOUT)
    return path, result_of(rc, out), time.monotonic() - start


def main() -> int:
    ap = argparse.ArgumentParser(description="Run bosphorus on ANF files in parallel.")
    ap.add_argument("paths", nargs="+", help="files, or dirs to search")
    ap.add_argument("-j", "--jobs", type=int, default=16)
    ap.add_argument("-t", "--timeout", type=int, default=300)
    ap.add_argument("--bosphorus", default=DEFAULT_BOSPHORUS)
    ap.add_argument("--ext", default=".anf", help="comma-separated exact extensions to search dirs for")
    ap.add_argument("--convert", choices=["auto", "always", "never"], default="auto",
                    help="rewrite named-indeterminate ANF into bosphorus x(i) syntax")
    ap.add_argument("--skip-existing", action="store_true", help="skip files that already have .out-bosphorus")
    ap.add_argument("--bosphorus-opts", default="", help="extra bosphorus options (space-separated)")
    args = ap.parse_args()

    binary = args.bosphorus
    if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
        print(f"error: no bosphorus binary at {binary}", file=sys.stderr)
        return 1

    opts = args.bosphorus_opts.split()
    exts = args.ext.split(",")
    files = [f for f in collect(args.paths, exts) if not f.endswith(".bos-anf")]
    if args.skip_existing:
        files = [f for f in files if not os.path.exists(f + ".out-bosphorus")]
    if not files:
        print("no files to run", file=sys.stderr)
        return 1

    total = len(files)
    print(f"{binary} --solve-xnf {' '.join(opts)}")
    print(f"{total} files, {args.jobs} parallel, {args.timeout}s timeout", flush=True)

    counts: dict[str, int] = {}
    done = 0
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(run_one, binary, opts, args.timeout, args.convert, f) for f in files]
        for fut in as_completed(futs):
            path, res, elapsed = fut.result()
            done += 1
            key = res.split("(")[0]
            counts[key] = counts.get(key, 0) + 1
            print(f"[{done}/{total}, {total - done} left] {res:17s} {elapsed:7.2f}s  {path}", flush=True)

    wall = time.monotonic() - start
    print(f"done in {wall:.1f}s: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
