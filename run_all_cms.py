#!/usr/bin/env python3
"""Run cryptominisat on CNF-XOR files: ./run_all_cms.py <files-or-dirs>..."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CMS = os.path.join(HERE, "cryptominisat", "build", "cryptominisat5")


def collect(paths: list[str], ext: str) -> list[str]:
    ext = ext if ext.startswith(".") else "." + ext
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files.extend(os.path.join(root, n) for n in names
                             if os.path.splitext(n)[1] == ext)
        else:
            files.append(p)
    return sorted(set(files))


def result_of(rc: int) -> str:
    return {10: "SAT", 20: "UNSAT", 124: "TIMEOUT"}.get(rc, f"UNKNOWN(rc={rc})")


def run_one(cms: str, opts: list[str], timeout: int, tag: str,
            path: str) -> tuple[str, str, float]:
    out, tim = path + ".out-" + tag, path + ".timeout-" + tag
    start = time.monotonic()
    with open(out, "w") as fout:
        rc = subprocess.call(["/usr/bin/time", "-v", "-o", tim,
                              "timeout", "-k", "10", str(timeout), cms] + opts + [path],
                             stdout=fout, stderr=subprocess.STDOUT)
    return path, result_of(rc), time.monotonic() - start


def main() -> int:
    ap = argparse.ArgumentParser(description="Run cryptominisat on CNF-XOR files in parallel.")
    ap.add_argument("paths", nargs="+", help="files, or dirs to search for *.cnf-xor")
    ap.add_argument("-j", "--jobs", type=int, default=16)
    ap.add_argument("-t", "--timeout", type=int, default=300)
    ap.add_argument("--cms", default=DEFAULT_CMS)
    ap.add_argument("--ext", default=".cnf-xor", help="exact extension to search dirs for")
    ap.add_argument("--skip-existing", action="store_true", help="skip files that already have .out-cms")
    ap.add_argument("--tag", default="cms",
                    help="output suffix and series name, e.g. 'cms-noxor' (default: cms)")
    ap.add_argument("--cms-opts", default="", help="CMS options (space-separated)")
    args = ap.parse_args()

    cms = args.cms
    if not (os.path.isfile(cms) and os.access(cms, os.X_OK)):
        print(f"error: no cryptominisat binary at {cms} -- build it first", file=sys.stderr)
        return 1

    opts = args.cms_opts.split()
    files = collect(args.paths, args.ext)
    if args.skip_existing:
        files = [f for f in files if not os.path.exists(f + ".out-" + args.tag)]
    if not files:
        print("no files to run", file=sys.stderr)
        return 1

    total = len(files)
    print(f"{cms} {' '.join(opts)}   -> .out-{args.tag}")
    print(f"{total} files, {args.jobs} parallel, {args.timeout}s timeout", flush=True)

    counts: dict[str, int] = {}
    done = 0
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(run_one, cms, opts, args.timeout, args.tag, f) for f in files]
        for fut in as_completed(futs):
            path, res, elapsed = fut.result()
            done += 1
            counts[res.split("(")[0]] = counts.get(res.split("(")[0], 0) + 1
            print(f"[{done}/{total}, {total - done} left] {res:8s} {elapsed:7.2f}s  {path}", flush=True)

    wall = time.monotonic() - start
    print(f"done in {wall:.1f}s: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
