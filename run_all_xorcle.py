#!/usr/bin/env python3
"""Run xorcle on XNF files: ./run_all_xorcle.py <files-or-dirs>..."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_XORCLE = os.path.join(HERE, "xorcle", "bin", "xorcle")


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


def run_one(binary: str, opts: list[str], timeout: int, path: str) -> tuple[str, str, float]:
    out, tim = path + ".out-xorcle", path + ".timeout-xorcle"
    start = time.monotonic()
    with open(out, "w") as fout:
        rc = subprocess.call(["/usr/bin/time", "-v", "-o", tim,
                              "timeout", "-k", "10", str(timeout), binary] + opts + [path],
                             stdout=fout, stderr=subprocess.STDOUT)
    return path, result_of(rc, out), time.monotonic() - start


def main() -> int:
    ap = argparse.ArgumentParser(description="Run xorcle on XNF files in parallel.")
    ap.add_argument("paths", nargs="+", help="files, or dirs to search")
    ap.add_argument("-j", "--jobs", type=int, default=16)
    ap.add_argument("-t", "--timeout", type=int, default=300)
    ap.add_argument("--xorcle", default=DEFAULT_XORCLE)
    ap.add_argument("--ext", default=".xnf", help="comma-separated exact extensions to search dirs for")
    ap.add_argument("--skip-existing", action="store_true", help="skip files that already have .out-xorcle")
    ap.add_argument("--xorcle-opts", default="", help="extra xorcle options (space-separated)")
    args = ap.parse_args()

    binary = args.xorcle
    if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
        print(f"error: no xorcle binary at {binary} -- run 'make' in xorcle/", file=sys.stderr)
        return 1

    opts = args.xorcle_opts.split()
    files = collect(args.paths, args.ext.split(","))
    if args.skip_existing:
        files = [f for f in files if not os.path.exists(f + ".out-xorcle")]
    if not files:
        print("no files to run", file=sys.stderr)
        return 1

    total = len(files)
    print(f"{binary} {' '.join(opts)}")
    print(f"{total} files, {args.jobs} parallel, {args.timeout}s timeout", flush=True)

    counts: dict[str, int] = {}
    done = 0
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(run_one, binary, opts, args.timeout, f) for f in files]
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
