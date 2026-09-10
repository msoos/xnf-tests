#!/usr/bin/env python3
"""Fuzz xorcle/xorricane against CryptoMiniSat on the CNF-XOR translation, UNSAT checked by cake_xlrup: ./xnf_fuzzer.py [--limit N] [-t SECS]"""

from __future__ import annotations

import argparse
import os
import random
import resource
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from xnf_to_xcnf import convert as xnf_to_xcnf

HERE = os.path.dirname(os.path.abspath(__file__))

Lineral = tuple[tuple[int, ...], int]  # (sorted support, constant): true iff XOR of support ^ constant == 1
Clause = list[Lineral]

ONE: Lineral = ((), 1)


def lit(var: int, neg: int = 0) -> Lineral:
    return (var,), neg


def lineral(vs, const: int) -> Lineral:
    return tuple(sorted(vs)), const


def add(a: Lineral, b: Lineral) -> Lineral:
    return tuple(sorted(set(a[0]) ^ set(b[0]))), a[1] ^ b[1]


def neg(a: Lineral) -> Lineral:
    return a[0], a[1] ^ 1


def rand_lit(r: random.Random, n: int) -> Lineral:
    return lit(r.randint(1, n), r.randint(0, 1))


def rand_lineral(r: random.Random, n: int, size: int) -> Lineral:
    return lineral(r.sample(range(1, n + 1), min(size, n)), r.randint(0, 1))


def normalize(clause: Clause) -> Clause | None:
    """Drops repeated and constant-false linerals; None if the clause is always true."""
    seen: dict[tuple[int, ...], int] = {}
    for sup, c in clause:
        if not sup:
            if c:
                return None
            continue
        if seen.setdefault(sup, c) != c:
            return None
    return list(seen.items())


# The generators below are XNF versions of the CNF fuzzers in cryptominisat/utils/cnf-utils.

def gen_random(r: random.Random, mode: str) -> tuple[int, list[Clause]]:
    n = r.randint(3, 60)
    kmax = 2 if mode == "2xnf" else r.randint(2, 5)
    width_weights = [r.random() for _ in range(kmax)]
    maxsz = r.randint(1, min(n, 8))
    m = r.randint(n // 2 + 1, n * r.choice([1, 2, 4, 8]))
    clauses = []
    for _ in range(m):
        k = r.choices(range(1, kmax + 1), width_weights)[0]
        clauses.append([rand_lineral(r, n, r.randint(1, maxsz)) for _ in range(k)])
    return n, clauses


def gen_cnf_xor(r: random.Random, mode: str) -> tuple[int, list[Clause]]:
    """cnf-fuzz-xor.py, with XORs as linerals and some clause literals widened to linerals."""
    n = r.randint(20, 200)
    wide = r.choice([0.0, 0.1, 0.3])

    def elem() -> Lineral:
        return rand_lineral(r, n, r.randint(2, 4)) if r.random() < wide else rand_lit(r, n)

    clauses = [[elem() for _ in range(r.randint(2, 5))] for _ in range(r.randint(n, 3 * n))]
    clauses += [[rand_lit(r, n)] for _ in range(r.randint(0, 15))]
    clauses += [[rand_lineral(r, n, r.randint(3, 7))] for _ in range(r.randint(min(100, n), n))]
    return n, clauses


def gen_xortester(r: random.Random, mode: str) -> tuple[int, list[Clause]]:
    """xortester.py, with XORs as linerals."""
    lo = r.choice([40, 60, 80, 100])
    n = r.randint(lo, lo + 10)
    clauses = [[lit(v, r.randint(0, 1)) for v in r.sample(range(1, n + 1), r.randint(3, 7))]
               for _ in range(r.randint(100, 900))]
    clauses += [[rand_lit(r, n)] for _ in range(r.randint(0, 10))]
    nxors = r.randint(int(n * 0.8), max(int(n * 1.4), int(n * 1.3) + 20))
    clauses += [[rand_lineral(r, n, r.randint(6, 9))] for _ in range(nxors)]
    return n, clauses


def gen_circuit(r: random.Random, mode: str) -> tuple[int, list[Clause]]:
    """cnf-fuzz-brummayer.py: a random AND/OR/XOR/IFF circuit, XOR/IFF gates as single linerals
    and gate inputs optionally linerals over several earlier nodes."""
    nin = r.randint(1, 25)
    min_refs = r.randint(1, 2)
    width = r.choice([1, 1, 2, 3])
    refs = [0] * nin
    need_refs = set(range(nin))
    roots: set[int] = set()
    gates: list[tuple[str, int, Lineral, Lineral]] = []

    def use(nodes: list[int]) -> None:
        for x in nodes:
            refs[x] += 1
            if refs[x] >= min_refs:
                need_refs.discard(x)
            roots.discard(x)

    def inp() -> Lineral:
        nodes = r.sample(range(len(refs)), min(len(refs), r.randint(1, width)))
        use(nodes)
        return lineral([x + 1 for x in nodes], r.randint(0, 1))

    def gate(a: Lineral, b: Lineral) -> None:
        roots.add(len(refs))
        refs.append(0)
        gates.append((r.choice("aoxi"), len(refs), a, b))

    while need_refs:
        gate(inp(), inp())
    while len(roots) > 1:
        a, b = r.sample(sorted(roots), 2)
        use([a, b])
        gate(lit(a + 1, r.randint(0, 1)), lit(b + 1, r.randint(0, 1)))

    clauses: list[Clause] = []
    for kind, x, a, b in gates:
        X = lit(x)
        if kind == "a":
            clauses += [[neg(X), a], [neg(X), b], [X, neg(a), neg(b)]]
        elif kind == "o":
            clauses += [[X, neg(a)], [X, neg(b)], [neg(X), a, b]]
        elif kind == "x":
            clauses.append([add(add(X, a), add(b, ONE))])
        else:
            clauses.append([add(add(X, a), b)])

    n = len(refs)
    nrand = round(r.randint(1, 10) / 100 * len(clauses))
    for _ in range(nrand):
        clauses.append([rand_lineral(r, n, r.randint(1, width)) for _ in range(r.randint(2, 6))])
    clauses.append([lit(roots.pop() + 1)])
    return n, clauses


NATIVE = {"random": gen_random, "cnf-xor": gen_cnf_xor, "xortester": gen_xortester, "circuit": gen_circuit}

# cnf-utils generators run as-is; their CNF is then lifted to XNF. Its xortester.py, cnf-fuzz-xor.py
# and spacer_test.py are left out: with their XORs blasted to CNF, xorcle mostly times out on them.
EXTERNAL = {
    "ext-brummayer": (["cnf-fuzz-brummayer.py", "-I", "50"], "-s", ("2xnf", "xnf")),
}

WEIGHTS = {"random": 3, "cnf-xor": 2, "xortester": 2, "circuit": 3, "ext-brummayer": 1}

# bigger instances are redrawn, so most finish within the per-instance time cap
MAX_VARS = 1000
MAX_CLAUSES = 3000


def gen_external(r: random.Random, name: str, cnf_utils: str) -> tuple[int, list[Clause]]:
    script, seedflag, _ = EXTERNAL[name]
    cmd = [sys.executable, os.path.join(cnf_utils, script[0]), *script[1:], seedflag, str(r.randrange(2**31))]
    text = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True, timeout=120,
                          start_new_session=True).stdout
    n = 0
    clauses: list[Clause] = []
    for line in text.splitlines():
        tok = line.split()
        if not tok or tok[0] == "c":
            continue
        if tok[0] == "p":
            n = int(tok[2])
        elif tok[0] == "x":
            vs = [int(t) for t in tok[1:-1]]
            clauses.append([lineral([abs(v) for v in vs], sum(v < 0 for v in vs) & 1)])
        else:
            lits = [int(t) for t in tok if t != "0"]
            if lits:
                clauses.append([lit(abs(v), int(v < 0)) for v in lits])
    return n, clauses


def plant(r: random.Random, n: int, clauses: list[Clause]) -> None:
    sol = [0] + [r.randint(0, 1) for _ in range(n)]
    for cl in clauses:
        if not any(c ^ (sum(sol[v] for v in sup) & 1) for sup, c in cl):
            j = r.randrange(len(cl))
            cl[j] = neg(cl[j])


def lift(r: random.Random, n: int, clauses: list[Clause]) -> list[Clause]:
    """Substitutes x -> My + c for a random invertible affine map, so satisfiability is preserved."""
    sup = [set()] + [{v} for v in range(1, n + 1)]
    const = [0] + [r.randint(0, 1) for _ in range(n)]
    cap = r.randint(2, 6)
    for _ in range(r.randint(0, 2 * n)):
        i, j = r.sample(range(1, n + 1), 2)
        s = sup[i] ^ sup[j]
        if len(s) <= cap:
            sup[i] = s
            const[i] ^= const[j]
    perm = list(range(1, n + 1))
    r.shuffle(perm)
    perm = [0] + perm

    def image(l: Lineral) -> Lineral:
        s: set[int] = set()
        c = l[1]
        for v in l[0]:
            s ^= sup[v]
            c ^= const[v]
        return lineral([perm[v] for v in s], c)

    return [[image(l) for l in cl] for cl in clauses]


def to_2xnf(n: int, clauses: list[Clause]) -> tuple[int, list[Clause]]:
    """(l1 v l2 v ... v lk) is equisatisfiable with (l1 v y) & (l2 v ... v lk+y+1) for fresh y."""
    out = []
    for cl in clauses:
        while len(cl) > 2:
            n += 1
            out.append([cl[0], lit(n)])
            cl = cl[1:-1] + [add(cl[-1], ((n,), 1))]
        out.append(cl)
    return n, out


def build(r: random.Random, gen: str, mode: str, cnf_utils: str) -> tuple[int, list[Clause], str]:
    tags = [gen]
    if gen in NATIVE:
        n, clauses = NATIVE[gen](r, mode)
        if r.random() < 0.3:
            plant(r, n, clauses)
            tags.append("plant")
        lift_prob = 0.5
    else:
        n, clauses = gen_external(r, gen, cnf_utils)
        lift_prob = 0.9
    if n >= 2 and r.random() < lift_prob:
        clauses = lift(r, n, clauses)
        tags.append("lift")
    if r.random() < 0.9:
        clauses = [c for c in map(normalize, clauses) if c is not None]
    for cl in clauses:
        r.shuffle(cl)
    if mode == "2xnf":
        n, clauses = to_2xnf(n, clauses)
    r.shuffle(clauses)
    return n, clauses, "+".join(tags)


def fmt_lineral(r: random.Random, l: Lineral) -> str:
    vs = list(l[0])
    r.shuffle(vs)
    if l[1]:
        vs[0] = -vs[0]  # xorcle only accepts the '-' on the first variable
    return "+".join(map(str, vs))


def check_assign(clauses: list[Clause], assign: dict[int, int]) -> str | None:
    for i, cl in enumerate(clauses, 1):
        undecided = False
        for sup, c in cl:
            if any(v not in assign for v in sup):
                undecided = True
            elif c ^ (sum(assign[v] for v in sup) & 1):
                break
        else:
            return f"clause {i} is {'undecided (unassigned vars)' if undecided else 'false'}"
    return None


def xorcle_opts(r: random.Random) -> list[str]:
    opts = ["-d", r.choice(["fixed_literals", "variable_vsids", "clause_vsids", "berkmin", "cmtf"]),
            "-p", r.choice(["unsat", "sat", "random"]),
            "-c", r.choice(["cyclic", "lt_watchlist", "exact_watchlist"]),
            "--seed", str(r.randrange(2**32))]
    opts += r.choice([["--restart", "none"],
                      ["--restart", "geometric", r.choice(["1.1", "1.5", "2"]), str(r.randint(1, 200))],
                      ["--restart", "luby", str(r.randint(1, 200))]])
    opts += r.choice([["-x", "on", str(r.randint(1, 64))], ["-x", "off"]])
    return opts


def xorricane_opts(r: random.Random) -> list[str]:
    opts = ["-dh", r.choice(["vsids", "lwl", "swl", "lex"]),
            "-po", r.choice(["save", "save_inv", "rand"]),
            "-rh", r.choice(["no", "fixed", "luby", "lbd"]),
            "-delh", r.choice(["avg_util", "util", "lbd"]),
            "-il", str(r.choice([0, 0, 1, 5])),
            "-ip", r.choice(["no", "nbu", "full"]),
            "-pp", r.choice(["no", "scc", "fls_scc"])]
    opts += [f for f in ("-no-lgj", "-no-eq") if r.random() < 0.3]
    if r.random() < 0.1:
        opts += ["-ca", "no"]
    return opts


@dataclass
class Run:
    name: str
    cmd: list[str]
    status: str = "ERROR"  # SAT, UNSAT, UNKNOWN, TIMEOUT, MEMOUT, KILLED, CRASH, ERROR
    rc: int | None = None
    secs: float = 0.0
    out: str = ""
    assign: dict[int, int] = field(default_factory=dict)
    conflict: bool = False


def run(name: str, cmd: list[str], deadline: float, out_path: str, mem_mb: int = 0) -> Run:
    res = Run(name, cmd)
    timeout = max(0.1, deadline - time.monotonic())

    def limit_mem() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb << 20, mem_mb << 20))

    t0 = time.monotonic()
    try:
        # own session: a Ctrl-C must not kill solvers mid-run, that would look like a crash
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                           preexec_fn=limit_mem if mem_mb else None, start_new_session=True)
        res.rc = p.returncode
        res.out = p.stdout.decode(errors="replace")
    except subprocess.TimeoutExpired as e:
        res.status = "TIMEOUT"
        res.out = (e.output or b"").decode(errors="replace")
    res.secs = time.monotonic() - t0
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(shlex.join(cmd) + "\n" + res.out)
    if res.status == "TIMEOUT":
        return res
    for line in res.out.splitlines():
        if line.startswith("s "):
            res.status = {"SATISFIABLE": "SAT", "UNSATISFIABLE": "UNSAT", "INDEFINITE": "TIMEOUT",
                          "INDETERMINATE": "TIMEOUT"}.get(line[2:].strip(), "UNKNOWN")
        elif line.startswith("v "):
            for tok in line.split()[1:]:
                l = int(tok)
                if l and res.assign.setdefault(abs(l), int(l > 0)) != int(l > 0):
                    res.conflict = True
    if res.status not in ("SAT", "UNSAT"):
        if "bad_alloc" in res.out or "out of memory" in res.out.lower():
            res.status = "MEMOUT"
        elif res.rc in (-signal.SIGTERM, -signal.SIGKILL):
            res.status = "KILLED"  # e.g. earlyoom, not the solver's doing
        elif res.rc is not None and res.rc < 0:
            res.status = "CRASH"
    return res


def tail(out: str, lines: int = 6) -> str:
    return "\n".join("      " + l for l in out.strip().splitlines()[-lines:])


def fuzz_one(seed: int, args: argparse.Namespace, gens: list[str]) -> dict:
    t_start = time.monotonic()
    r = random.Random(seed)
    # always draw, so the "--mode X" in a failure's repro line replays the same random stream
    picked = r.choice(("2xnf", "xnf"))
    mode = picked if args.mode == "both" else args.mode
    usable = [g for g in gens if g in NATIVE or mode in EXTERNAL[g][2]]
    gen = r.choices(usable, [WEIGHTS[g] for g in usable])[0]
    n, clauses, desc = build(r, gen, mode, args.cnf_utils)
    for _ in range(19):
        if n <= MAX_VARS and len(clauses) <= MAX_CLAUSES:
            break
        n, clauses, desc = build(r, gen, mode, args.cnf_utils)

    tmp = tempfile.mkdtemp(prefix=f"xnf_fuzz_{seed}_")
    try:
        xnf = os.path.join(tmp, "inst.xnf")
        xcnf = os.path.join(tmp, "inst.xcnf")
        proof = os.path.join(tmp, "cms.xlrup")
        with open(xnf, "w", encoding="utf-8") as f:
            f.write(f"p xnf {n} {len(clauses)}\n")
            f.writelines(" ".join(fmt_lineral(r, l) for l in cl) + " 0\n" for cl in clauses)
        total_vars, xlines = xnf_to_xcnf(n, clauses)
        with open(xcnf, "w", encoding="utf-8") as f:
            f.write(f"p cnf {total_vars} {len(xlines)}\n" + "\n".join(xlines) + "\n")

        cmds = {"cms": [args.cms, "--verb", "0", *shlex.split(args.cms_opts), xcnf, proof],
                "xorcle": [args.xorcle, *([] if args.default_opts else xorcle_opts(r)), xnf]}
        if mode == "2xnf":
            opts = [] if args.default_opts else xorricane_opts(r)
            cmds["xorricane"] = [args.xorricane, *opts, "-t", str(max(1, int(args.timeout))), xnf]
        deadline = time.monotonic() + args.timeout

        def solve(name: str) -> tuple[Run, Run | None]:
            res = run(name, cmds[name], deadline, os.path.join(tmp, f"{name}.out"), args.mem)
            if name != "cms" or res.status != "UNSAT":
                return res, None
            # a floor, so an UNSAT found just before the deadline can still be verified
            return res, run("cake_xlrup", [args.cake, xcnf, proof], max(deadline, time.monotonic() + 1),
                            os.path.join(tmp, "cake.out"))

        with ThreadPoolExecutor(len(cmds)) as pool:
            results = list(pool.map(solve, cmds))
        runs = [res for res, _ in results]
        cake = results[0][1]

        problems: list[str] = []
        sol_err = {x.name: check_assign(clauses, x.assign) or ("variable assigned both ways" if x.conflict else None)
                   for x in runs if x.status == "SAT"}
        truth = ""
        witness = ""
        if "cms" in sol_err:
            if sol_err["cms"]:
                problems.append(f"cms: solution of the CNF-XOR translation does not satisfy the XNF: "
                                f"{sol_err['cms']} (CMS or xnf_to_xcnf bug)")
            else:
                truth, witness = "SAT", "cms"
        elif cake:
            if "s VERIFIED UNSAT" in cake.out:
                truth = "UNSAT"
            elif cake.status != "TIMEOUT":
                problems.append("cms: cake_xlrup rejected the UNSAT proof:\n" + tail(cake.out))

        for res in runs:
            if "runtime error:" in res.out or "Sanitizer" in res.out:
                problems.append(f"{res.name}: sanitizer report:\n" + tail(res.out))
            if res.status in ("CRASH", "ERROR"):
                problems.append(f"{res.name}: {res.status.lower()} (exit {res.rc}):\n" + tail(res.out))

        for res in runs[1:]:
            if res.status != "SAT":
                continue
            if sol_err[res.name]:
                problems.append(f"{res.name}: wrong solution: {sol_err[res.name]}")
            elif truth == "UNSAT":
                problems.append(f"{res.name}: found a valid solution but CMS's UNSAT proof was verified "
                                "(xnf_to_xcnf or cake_xlrup bug?)")
            elif not truth:
                truth, witness = "SAT", res.name
        for res in runs[1:]:
            if res.status == "UNSAT" and truth == "SAT":
                problems.append(f"{res.name}: says UNSAT, but {witness} found a valid solution")

        def short(cmd: list[str]) -> str:
            return shlex.join([os.path.basename(cmd[0])] + [a.replace(tmp + os.sep, "") for a in cmd[1:]])

        lines = [f"seed {seed} | {mode} {desc} | {n} vars, {len(clauses)} clauses"]
        lines += [f"  {x.name:10} {x.status:8} {x.secs:5.2f}s  {short(x.cmd)}" for x in runs[1:] + runs[:1]]
        if cake:
            verdict = {"UNSAT": "s VERIFIED UNSAT"}.get(truth, "timed out" if cake.status == "TIMEOUT" else "REJECTED")
            lines.append(f"  {'check':10} {short(cake.cmd)}: {verdict}")
        if sol_err:
            lines.append(f"  {'check':10} solutions against all {len(clauses)} XNF clauses: "
                         + ", ".join(f"{k} {'WRONG, ' + v if v else 'OK'}" for k, v in sol_err.items()))
        if not cake and not sol_err:
            lines.append(f"  {'check':10} nothing to check, no solver answered within {args.timeout:g}s")
        took = f"{time.monotonic() - t_start:.1f}s"
        if not problems:
            note = {"SAT": "SAT, solution checked", "UNSAT": "UNSAT, proof checked"}.get(truth, "undecided")
            lines.append(f"  {'result':10} OK: {note}, {took}")
            return {"ok": True, "truth": truth, "lines": lines}

        dest = os.path.join(args.failures, f"{seed}-{mode}-{gen}")
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(tmp, dest)
        repro = [sys.argv[0], "--limit", "1", "-j", "1", "-t", f"{args.timeout:g}", "--seed", str(seed),
                 "--mode", mode, "--gen", gen] + (["--default-opts"] if args.default_opts else [])
        with open(os.path.join(dest, "report.txt"), "w", encoding="utf-8") as f:
            f.write(f"reproduce: {shlex.join(repro)}\n\n")
            f.write("\n".join(problems) + "\n\n")
            for res in runs:
                f.write(f"{res.name}: {res.status} in {res.secs:.2f}s: {shlex.join(res.cmd).replace(tmp, dest)}\n")
        lines.append(f"  {'result':10} BUG, {took}")
        lines += ["    " + p.replace("\n", "\n    ") for p in problems]
        return {"ok": False, "truth": truth, "lines": lines, "seed": seed, "problems": problems,
                "repro": shlex.join(repro), "dest": dest}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Differential fuzzer for XNF solvers.")
    ap.add_argument("-l", "--limit", type=int, default=0, help="stop after this many instances (default: never)")
    ap.add_argument("-s", "--seed", type=int, default=None, help="base seed; instance i uses seed+i")
    ap.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                    help="instances in parallel, each running its 2-3 solvers at once (default: half the cores)")
    ap.add_argument("-t", "--timeout", type=float, default=5,
                    help="wall-clock cap per instance in seconds, all solvers together (default: 5)")
    ap.add_argument("-m", "--mem", type=int, default=2048,
                    help="per-solver address-space limit in MiB, 0 = none (default: 2048)")
    ap.add_argument("--mode", choices=["2xnf", "xnf", "both"], default="both",
                    help="2xnf: xorcle and xorricane on 2-XNF; xnf: xorcle on general XNF (default: both)")
    ap.add_argument("--gen", action="append", choices=list(WEIGHTS), help="only use these generators")
    ap.add_argument("--default-opts", action="store_true", help="don't randomise the XNF solvers' options")
    ap.add_argument("--xorcle", default=os.path.join(HERE, "xorcle/bin/xorcle"))
    ap.add_argument("--xorricane", default=os.path.join(HERE, "Xorricane/xorricane"))
    ap.add_argument("--cms", default=os.path.join(HERE, "cryptominisat/build/cryptominisat5"))
    ap.add_argument("--cms-opts", default="", help="extra CryptoMiniSat options")
    cakes = [shutil.which("cake_xlrup") or "", os.path.join(HERE, "cryptominisat/scripts/fuzz/cake_xlrup"),
             os.path.join(HERE, "../frat-xor/cake_xlrup/cake_xlrup")]
    ap.add_argument("--cake", default=next((c for c in cakes if os.access(c, os.X_OK)), cakes[1]))
    ap.add_argument("--cnf-utils", default=os.path.join(HERE, "cryptominisat/utils/cnf-utils"))
    ap.add_argument("--failures", default="fuzz_failures", help="where failing instances go")
    args = ap.parse_args()

    needed = [args.xorcle, args.cms, args.cake] + ([args.xorricane] if args.mode != "xnf" else [])
    missing = [p for p in needed if not os.access(p, os.X_OK)]
    if missing:
        print("not found or not executable: " + ", ".join(missing), file=sys.stderr)
        return 1
    args.xorcle, args.xorricane, args.cms, args.cake = map(os.path.abspath, (
        args.xorcle, args.xorricane, args.cms, args.cake))

    gens = args.gen or list(WEIGHTS)
    if not os.path.isfile(os.path.join(args.cnf_utils, "xortester.py")):
        print(f"no cnf-utils at {args.cnf_utils}, skipping its generators "
              "(git -C cryptominisat submodule update --init utils/cnf-utils)", file=sys.stderr)
        gens = [g for g in gens if g in NATIVE]
    if not gens:
        return 1
    if args.seed is None:
        args.seed = random.randrange(2**31)
    print(f"base seed {args.seed}, generators: {', '.join(gens)}", flush=True)

    counts = {"SAT": 0, "UNSAT": 0, "": 0}
    done = submitted = 0
    bug = None
    interrupted: list[int] = []
    # a flag, not KeyboardInterrupt: that can land inside futures.wait's lock handling and escape as a RuntimeError
    signal.signal(signal.SIGINT, lambda *_: interrupted.append(1))
    with ProcessPoolExecutor(max_workers=args.jobs, initializer=signal.signal,
                             initargs=(signal.SIGINT, signal.SIG_IGN)) as pool:
        pending: set = set()
        while not bug and not interrupted and (pending or not args.limit or submitted < args.limit):
            while len(pending) < 2 * args.jobs and (not args.limit or submitted < args.limit):
                pending.add(pool.submit(fuzz_one, args.seed + submitted, args, gens))
                submitted += 1
            finished, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            for fut in finished:
                res = fut.result()
                done += 1
                counts[res["truth"]] += 1
                print("\n".join(res["lines"]), flush=True)
                if not res["ok"] and not bug:
                    bug = res
        for fut in pending:
            fut.cancel()
        if bug or interrupted:
            print(f"{'bug found' if bug else 'interrupted'}, waiting for the running instances to stop...",
                  flush=True)

    print(f"\n{done} instances: {counts['SAT']} SAT (solution checked), {counts['UNSAT']} UNSAT "
          f"(proof checked), {counts['']} undecided")
    if not bug:
        return 0
    print(f"\nBUG in seed {bug['seed']}:\n  " + "\n  ".join(p.replace("\n", "\n  ") for p in bug["problems"]))
    print(f"files:     {bug['dest']}/ (exact commands in report.txt)")
    print(f"reproduce: {bug['repro']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
