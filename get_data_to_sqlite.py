#!/usr/bin/python3
"""Parse solver run logs into data.sqlite: ./get_data_to_sqlite.py [dirs...]"""

import argparse
import os
import re
import shutil
import sqlite3 as sqlite_mod
import subprocess

DB_NAME = "data.sqlite"

RE_RESULT = re.compile(r"^s\s+(?:ANF-)?(SATISFIABLE|UNSATISFIABLE)", re.M)
RE_OOM_MSG = re.compile(r"bad_alloc|out of memory|Cannot allocate memory", re.I)
RE_LIMIT = re.compile(r"timeout -k \d+ (\d+)")


def parse_elapsed(text):
    parts = text.strip().split(":")
    try:
        secs = float(parts[-1])
        if len(parts) > 1:
            secs += 60 * int(parts[-2])
        if len(parts) > 2:
            secs += 3600 * int(parts[-3])
        return secs
    except ValueError:
        return None


def timeout_parse(fname):
    """Parse the /usr/bin/time -v block written by the run_all_* scripts."""
    r = {"signal": None, "exit_status": 0, "call": None, "timeout_t": None,
         "user_time": None, "sys_time": None, "wall_time": None, "cpu_pct": None,
         "mem_MB": None, "major_faults": None, "minor_faults": None,
         "vol_ctx": None, "invol_ctx": None, "swaps": None,
         "fs_in": None, "fs_out": None}
    try:
        with open(fname, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    for line in lines:
        line = line.strip()
        if "Command terminated by signal" in line:
            r["signal"] = int(line.split()[4])
        elif "Command exited with non-zero status" in line:
            r["exit_status"] = int(line.split()[5])
        elif line.startswith("Command being timed:"):
            r["call"] = line.split(":", 1)[1].strip().strip('"')
            m = RE_LIMIT.search(r["call"])
            if m:
                r["timeout_t"] = int(m.group(1))
        elif "User time (seconds)" in line:
            r["user_time"] = float(line.split()[3])
        elif "System time (seconds)" in line:
            r["sys_time"] = float(line.split()[3])
        elif "Percent of CPU this job got" in line:
            r["cpu_pct"] = int(line.split()[6].rstrip("%"))
        elif "Elapsed (wall clock) time" in line:
            r["wall_time"] = parse_elapsed(line.rsplit(": ", 1)[-1])
        elif "Maximum resident set size (kbytes)" in line:
            r["mem_MB"] = float(line.split()[5]) / 1000
        elif "Major (requiring I/O) page faults" in line:
            r["major_faults"] = int(line.split()[5])
        elif "Minor (reclaiming a frame) page faults" in line:
            r["minor_faults"] = int(line.split()[6])
        elif "Voluntary context switches" in line:
            r["vol_ctx"] = int(line.split()[3])
        elif "Involuntary context switches" in line:
            r["invol_ctx"] = int(line.split()[3])
        elif line.startswith("Swaps:"):
            r["swaps"] = int(line.split()[1])
        elif "File system inputs" in line:
            r["fs_in"] = int(line.split()[3])
        elif "File system outputs" in line:
            r["fs_out"] = int(line.split()[3])
    return r


_SHA_CACHE = {}


def solver_sha(call):
    """10-char SHA of the repo holding the solver binary, resolved at parse time."""
    if not call:
        return None
    toks = call.split()
    binary = toks[4] if toks[:2] == ["timeout", "-k"] else toks[0]
    if binary in _SHA_CACHE:
        return _SHA_CACHE[binary]
    sha = None
    d = os.path.dirname(os.path.abspath(binary))
    while d != "/":
        if os.path.isdir(os.path.join(d, ".git")):
            try:
                sha = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                                     capture_output=True, text=True,
                                     timeout=10).stdout.strip()[:10] or None
            except (OSError, subprocess.SubprocessError):
                sha = None
            break
        d = os.path.dirname(d)
    _SHA_CACHE[binary] = sha
    return sha


def out_parse(fname):
    try:
        with open(fname, "r", errors="replace") as f:
            text = f.read()
    except OSError:
        return None, False
    m = RE_RESULT.search(text)
    result = None
    if m:
        result = "SAT" if m.group(1) == "SATISFIABLE" else "UNSAT"
    return result, bool(RE_OOM_MSG.search(text))


def family_of(dirname):
    parts = [p for p in dirname.split(os.sep) if p not in (".", "")]
    for i, p in enumerate(parts):
        if p == "generated" and i + 1 < len(parts):
            return parts[i + 1]
        if p == "xorricane-bench" and i + 1 < len(parts):
            return parts[i + 1]
        if p == "matrix-challenges":
            return "matrix-" + "-".join(parts[i + 1:]) if len(parts) > i + 1 else "matrix"
        if p == "benchmark" and i + 1 < len(parts):
            # ascon splits into r2/r3/r4, rand into rand/rand_sat
            if parts[i + 1] == "rand" and len(parts) > i + 2:
                return "2xnf-" + parts[i + 2]
            return "2xnf-" + parts[i + 1]
    return parts[-1] if parts else "unknown"


def main():
    ap = argparse.ArgumentParser(description="Parse run logs into " + DB_NAME)
    ap.add_argument("paths", nargs="*", default=["."], help="dirs to scan (default: .)")
    ap.add_argument("-x", "--exclude", action="append", default=["backup"],
                    help="skip dirs with this name (default: backup)")
    args = ap.parse_args()

    if os.path.exists(DB_NAME):
        os.unlink(DB_NAME)
    conn = sqlite_mod.connect(DB_NAME)
    conn.executescript("""
        CREATE TABLE data (
          solver TEXT NOT NULL,
          family TEXT NOT NULL,
          dirname TEXT NOT NULL,
          fname TEXT NOT NULL,
          instance TEXT NOT NULL,
          ext TEXT NOT NULL,
          solved INT NOT NULL,
          result TEXT,
          solve_time FLOAT,
          wall_time FLOAT,
          user_time FLOAT,
          sys_time FLOAT,
          cpu_pct INT,
          mem_MB FLOAT,
          timeout_t INT,
          timed_out INT NOT NULL,
          mem_out INT NOT NULL,
          errored INT NOT NULL,
          exit_status INT,
          signal INT,
          call TEXT,
          solver_sha TEXT,
          major_faults INT,
          minor_faults INT,
          vol_ctx INT,
          invol_ctx INT,
          swaps INT,
          fs_in INT,
          fs_out INT
        );
        CREATE INDEX idx_solver ON data(solver);
        CREATE INDEX idx_family ON data(family);
        CREATE INDEX idx_inst ON data(instance);
    """)

    rows = []
    for root_path in args.paths:
        for root, _, names in os.walk(root_path):
            parts = root.split(os.sep)
            if ".git" in parts or any(e in parts for e in args.exclude):
                continue
            for n in sorted(names):
                if ".timeout-" not in n:
                    continue
                stem, solver = n.rsplit(".timeout-", 1)
                t = timeout_parse(os.path.join(root, n))
                if t is None:
                    continue
                result, oom_msg = out_parse(os.path.join(root, stem + ".out-" + solver))

                early = t["timeout_t"] and t["wall_time"] is not None \
                    and t["wall_time"] < t["timeout_t"] * 0.9
                mem_out = int(oom_msg or (t["signal"] == 9 and early))
                timed_out = int(not mem_out and (t["exit_status"] == 124
                                                 or t["signal"] in (9, 15)))
                solved = int(result is not None)
                errored = int(not solved and not timed_out and not mem_out
                              and t["exit_status"] not in (0, 10, 20))

                rows.append((
                    solver, family_of(root), root, stem,
                    os.path.splitext(stem)[0], os.path.splitext(stem)[1],
                    solved, result,
                    t["wall_time"] if solved else None,
                    t["wall_time"], t["user_time"], t["sys_time"], t["cpu_pct"],
                    t["mem_MB"], t["timeout_t"], timed_out, mem_out, errored,
                    t["exit_status"], t["signal"], t["call"], solver_sha(t["call"]),
                    t["major_faults"], t["minor_faults"], t["vol_ctx"],
                    t["invol_ctx"], t["swaps"], t["fs_in"], t["fs_out"],
                ))

    conn.executemany("INSERT INTO data VALUES (" + ",".join(["?"] * 29) + ")", rows)
    conn.commit()

    print(f"wrote {len(rows)} rows to {DB_NAME}")
    for solver, family, n, s in conn.execute(
            "SELECT solver, family, COUNT(*), SUM(solved) FROM data "
            "GROUP BY solver, family ORDER BY solver, family"):
        print(f"  {solver:<10} {family:<22} {n:5d} runs, {s:5d} solved")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
