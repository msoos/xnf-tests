#!/usr/bin/env python3
"""Run xnfsat on XNF files: ./run_all_xnf.py <files-or-dirs>..."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_XNFSAT = os.path.join(HERE, "xnfsat", "xnfsat")

# Tuned values from "XOR Local Search for Boolean Brent Equations", Section 5.
# cb=2.5 and xorweight=5.0 are already the solver defaults; the clause weights are not.
DEFAULT_OPTS = ["--cb=250", "--xorweight=500", "--weight2=200", "--weight3=200",
                "--weight4=450", "--weight5=450", "--weight6=500", "--weight7=500",
                "--weight8=500"]


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


def result_of(rc: int, out: str) -> str:
    if rc == 10:
        return "SATISFIABLE"
    if rc == 124:
        return "TIMEOUT"
    try:
        with open(out, errors="replace") as f:
            for line in f:
                if line.startswith("s "):
                    return line[2:].strip()
    except OSError:
        pass
    return "UNKNOWN" if rc == 0 else f"UNKNOWN(rc={rc})"


def run_one(binary: str, opts: list[str], timeout: int, seed: int,
            path: str) -> tuple[str, str, float]:
    out, tim = path + ".out-xnfsat", path + ".timeout-xnfsat"
    start = time.monotonic()
    with open(out, "w") as fout:
        rc = subprocess.call(["/usr/bin/time", "-v", "-o", tim,
                              "timeout", "-k", "10", str(timeout), binary]
                             + opts + [path, str(seed)],
                             stdout=fout, stderr=subprocess.STDOUT)
    return path, result_of(rc, out), time.monotonic() - start


def main() -> int:
    ap = argparse.ArgumentParser(description="Run xnfsat on XNF files in parallel.")
    ap.add_argument("paths", nargs="+", help="files, or dirs to search")
    ap.add_argument("-j", "--jobs", type=int, default=16)
    ap.add_argument("-t", "--timeout", type=int, default=300)
    ap.add_argument("-s", "--seed", type=int, default=0)
    ap.add_argument("--xnfsat", default=DEFAULT_XNFSAT)
    ap.add_argument("--ext", default=".xnf", help="comma-separated exact extensions to search dirs for")
    ap.add_argument("--skip-existing", action="store_true", help="skip files that already have .out-xnfsat")
    ap.add_argument("--xnfsat-opts", help="replace the default xnfsat options (space-separated)")
    args = ap.parse_args()

    binary = args.xnfsat
    if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
        print(f"error: no xnfsat binary at {binary} -- run './configure.sh && make' in xnfsat/",
              file=sys.stderr)
        return 1

    opts = args.xnfsat_opts.split() if args.xnfsat_opts is not None else DEFAULT_OPTS
    files = collect(args.paths, args.ext.split(","))
    if args.skip_existing:
        files = [f for f in files if not os.path.exists(f + ".out-xnfsat")]
    if not files:
        print("no files to run", file=sys.stderr)
        return 1

    total = len(files)
    print(f"{binary} {' '.join(opts)} <file> {args.seed}")
    print(f"{total} files, {args.jobs} parallel, {args.timeout}s timeout", flush=True)

    counts: dict[str, int] = {}
    done = 0
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(run_one, binary, opts, args.timeout, args.seed, f) for f in files]
        for fut in as_completed(futs):
            path, res, elapsed = fut.result()
            done += 1
            key = res.split("(")[0]
            counts[key] = counts.get(key, 0) + 1
            print(f"[{done}/{total}, {total - done} left] {res:13s} {elapsed:7.2f}s  {path}", flush=True)

    wall = time.monotonic() - start
    print(f"done in {wall:.1f}s: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
