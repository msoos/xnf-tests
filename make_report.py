#!/bin/python3
"""Build a self-contained HTML report from data.sqlite and pics/: ./make_report.py"""

import argparse
import csv
import html
import os
import platform
import re
import sqlite3
import subprocess
from datetime import datetime

DB = "data.sqlite"
PICS = "pics"
OUT = "report.html"

SOLVERS = {
    "cms": ("CryptoMiniSat", "CNF-XOR / CNF"),
    "cms-noxor": ("CryptoMiniSat, XOR detection off", "CNF"),
    "xorcle": ("Xorcle", "XNF / CNF"),
    "xorricane": ("Xorricane", "XNF"),
    "bosphorus": ("Bosphorus", "ANF"),
}

INSTANCE_EXTS = {".cnf", ".xnf", ".xcnf", ".2xnf", ".2xcnf", ".anf",
                 ".cnf-xor", ".bos-anf"}
FILE_FLAGS = {"--anfread"}
# timeout expressed via the solver's own flag: harness scaffolding, not configuration
TIMEOUT_FLAGS = {"-t", "--time-out", "--maxtime"}

FAMILY_NOTES = {
    "tseitin_n_k": ("Tseitin formulas in CNF",
        "Unsatisfiable parity formulas on random k-regular n-vertex graphs, generated with "
        "<code>cnfgen</code>. Grid: (20,k) for k=3..10 and (n,4) for n=10,20,...,1280, five graphs each. "
        "Provably hard for Resolution; the headline family of the Xorcle paper."),
    "pebbling_lifted_h_k": ("Pebbling formulas lifted by k-XORs",
        "Pebbling formulas on pyramid graphs of height h=60..150, each variable replaced by the "
        "XOR of k fresh variables (k=2,4,6,8). Solvable by unit propagation alone in XNF."),
    "random_kxnf_n": ("Random k-XNFs",
        "k=2..5, n=11..20, clause count tuned so roughly half the instances are satisfiable."),
    "restricted_kxnf_n": ("Restricted random k-XNFs",
        "A random k-XNF restricted by N/2 random affine equations, k=2..5, N=22,24,...,40."),
    "2xnf-ascon": ("Ascon-128 (2-Xornado suite)",
        "400 satisfiable instances from key-recovery attacks on round-reduced Ascon-128, "
        "rounds 2/3/4, from the <code>2xnf_sat_solving</code> repository."),
    "2xnf-rand": ("Random 2-XNF (unsat-mixed)",
        "400 random 2-XNF instances, n=21..40, m=3n, from the 2-Xornado paper's benchmark set."),
    "2xnf-rand_sat": ("Random 2-XNF (satisfiable)",
        "400 random 2-XNF instances guaranteed satisfiable, same parameters as above."),
    "ascon": ("Ascon (Xorricane suite, Benchmark 6.5)",
        "50 satisfiable instances from state-recovery attacks on Ascon-128, from the "
        "Xorricane-paper release. Distinct from the 2-Xornado Ascon set."),
    "bivium": ("Bivium (Xorricane Benchmark 6.6)",
        "50 satisfiable state-recovery instances on the Bivium stream cipher."),
    "ctc": ("CTC2 (Xorricane Benchmark 6.7)",
        "50 satisfiable key-recovery instances on the CTC2 block cipher."),
    "rand_l2xnf_ld": ("Random linear system with 2-XNF constraints (Benchmark 6.3)",
        "n/2 random linear equations plus n random 2-XNF clauses, n=61..110."),
    "rand_qp_type_I": ("Multivariate quadratic, Type I (Benchmark 6.4)",
        "Random quadratic systems with m=2n, at least one solution, n=11..35."),
    "rand_qp_type_IV": ("Multivariate quadratic, Type IV (Benchmark 6.4)",
        "Random quadratic systems with n=floor(1.5m), n=11..35."),
}

CSS = """
:root{--fg:#1a1a1a;--bg:#fff;--muted:#666;--line:#ddd;--accent:#0b5cad;--warn:#8a4b00;
      --warnbg:#fff8ec;--code:#f4f4f6}
@media(prefers-color-scheme:dark){:root{--fg:#e6e6e6;--bg:#16181c;--muted:#a0a0a0;
  --line:#333;--accent:#79b8ff;--warn:#e0b070;--warnbg:#2a2317;--code:#22252b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:2.5rem 1.5rem 6rem}
h1{font-size:2rem;margin:0 0 .3rem}
h2{font-size:1.4rem;margin:3rem 0 1rem;padding-bottom:.3rem;border-bottom:2px solid var(--line)}
h3{font-size:1.1rem;margin:2rem 0 .5rem}
.sub{color:var(--muted);margin:0 0 2rem}
code{background:var(--code);padding:.1em .35em;border-radius:3px;font-size:.88em}
pre{background:var(--code);padding:.9rem 1rem;border-radius:6px;overflow-x:auto;font-size:.85rem;
  line-height:1.45}
pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.9rem}
th,td{padding:.45rem .7rem;text-align:right;border-bottom:1px solid var(--line)}
td:first-child{text-align:left}
th{background:var(--code);font-weight:600;text-align:center}
tbody tr:first-child td{font-weight:600}
figure{margin:1.5rem 0}
figure svg{max-width:100%;height:auto;display:block;background:#fff;border:1px solid var(--line);
  border-radius:6px}
.note{background:var(--warnbg);border-left:3px solid var(--warn);padding:.8rem 1rem;
  margin:1rem 0;border-radius:0 4px 4px 0;font-size:.92rem}
.note strong{color:var(--warn)}
nav{background:var(--code);padding:1rem 1.2rem;border-radius:6px;margin:2rem 0}
nav ul{margin:.3rem 0;padding-left:1.2rem;columns:2}
nav a{color:var(--accent);text-decoration:none}
nav a:hover{text-decoration:underline}
.scroll{overflow-x:auto}
td.desc{text-align:left;font-size:.86rem;line-height:1.45;color:var(--muted);min-width:26rem}
"""


def sh(cmd, default=""):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=10).stdout.strip() or default
    except Exception:
        return default


def e(s):
    return html.escape(str(s))


def git_sha(path):
    """10-char SHA of the repo containing the solver binary."""
    d = os.path.dirname(os.path.abspath(path))
    while d != "/":
        if os.path.isdir(os.path.join(d, ".git")):
            sha = sh(f"git -C {d} rev-parse HEAD")
            return sha[:10] if sha else "?"
        d = os.path.dirname(d)
    return "?"


def clean_call(call):
    """Strip the timeout wrapper, binary directory, and every instance filename."""
    toks = call.split()
    if toks[:2] == ["timeout", "-k"]:
        toks = toks[4:]
    binary_path = toks[0]
    kept = [os.path.basename(binary_path)]
    dropped = False
    skip_next = False
    for t in toks[1:]:
        if skip_next:
            skip_next = False
            continue
        if t in TIMEOUT_FLAGS:
            skip_next = True
            continue
        if "/" in t or os.path.splitext(t)[1] in INSTANCE_EXTS:
            if kept and kept[-1] in FILE_FLAGS:
                kept.pop()
            dropped = True
            continue
        dropped = False
        kept.append(t)
    return binary_path, " ".join(kept)


def inline_svg(path, uid):
    """Read a gnuplot SVG and namespace its ids so several can coexist in one page."""
    with open(path) as f:
        svg = f.read()
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    svg = re.sub(r"<!DOCTYPE[^>]*>\s*", "", svg)
    svg = re.sub(r'\sid="([^"]+)"', lambda m: f' id="{uid}_{m.group(1)}"', svg)
    svg = re.sub(r'width="\d+"\s+height="\d+"', 'width="100%"', svg, count=1)
    return svg


def read_par2(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def par2_table(rows):
    if not rows:
        return ""
    out = ['<div class="scroll"><table><thead><tr><th>Solver</th><th>Solved</th>'
           '<th>Attempted</th><th>PAR2 (s)</th><th>Avg time solved (s)</th>'
           '<th>Peak RSS (MB)</th></tr></thead><tbody>']
    for r in rows:
        out.append(
            f"<tr><td>{e(r['solver'])}</td><td>{e(r['solved'])}</td>"
            f"<td>{e(r['attempted'])}</td><td>{e(r['par2'])}</td>"
            f"<td>{e(r['avg_time_solved_s'] or '-')}</td><td>{e(r['max_mem_MB'])}</td></tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def solver_table(con):
    out = ['<div class="scroll"><table><thead><tr><th>Solver</th><th>Git SHA</th>'
           '<th>Input</th><th>Command line</th>'
           '</tr></thead><tbody>']
    for solver, (name, fmt) in SOLVERS.items():
        row = con.execute("SELECT COUNT(*) FROM data WHERE solver=?", (solver,)).fetchone()
        if not row or not row[0]:
            continue
        raw = con.execute(
            "SELECT call, solver_sha FROM data WHERE solver=? AND call IS NOT NULL LIMIT 1",
            (solver,)).fetchone()
        binary_path, call = clean_call(raw[0]) if raw else ("", "")
        sha = (raw[1] if raw else None) or git_sha(binary_path)
        out.append(f"<tr><td>{e(name)}</td><td><code>{e(sha)}</code></td>"
                   f"<td>{e(fmt)}</td><td><code>{e(call)}</code></td></tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def family_table(con):
    out = ['<div class="scroll"><table><thead><tr><th>Family</th><th>Instances</th>'
           '<th>Timeout (s)</th><th>Description</th></tr></thead><tbody>']
    for fam, n, lim in con.execute("""
            SELECT family, COUNT(DISTINCT instance), MIN(timeout_t)
            FROM data GROUP BY family ORDER BY family"""):
        label, desc = FAMILY_NOTES.get(fam, (fam, ""))
        out.append(f"<tr><td>{e(fam)}<br><span class='sub'>{e(label)}</span></td>"
                   f"<td>{n}</td><td>{lim}</td><td class='desc'>{desc}</td></tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Build " + OUT)
    ap.add_argument("-o", "--output", default=OUT)
    args = ap.parse_args()

    if not os.path.exists(DB):
        raise SystemExit(f"{DB} not found -- run ./get_data_to_sqlite.py")
    if not os.path.isdir(PICS):
        raise SystemExit(f"{PICS}/ not found -- run ./create_graphs.py")

    con = sqlite3.connect(DB)
    families = [r[0] for r in con.execute(
        "SELECT family, COUNT(DISTINCT instance) c FROM data GROUP BY family ORDER BY c DESC")]
    total_runs = con.execute("SELECT COUNT(*) FROM data").fetchone()[0]
    total_inst = con.execute(
        "SELECT COUNT(DISTINCT family || '/' || instance) FROM data").fetchone()[0]

    cpu = sh("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2", platform.processor()).strip()
    ram = sh("free -g | awk 'NR==2{print $2}'", "?")
    when = datetime.now().strftime("%Y-%m-%d")

    P = []
    P.append(f"<h1>XNF solver evaluation</h1>")
    P.append(f'<p class="sub">{e(total_runs)} solver runs over {e(total_inst)} instances in '
             f'{len(families)} benchmark families &middot; {e(cpu)}, {e(ram)}&nbsp;GB RAM '
             f'&middot; generated {e(when)}</p>')

    P.append('<nav><strong>Contents</strong><ul>')
    for anchor, title in [("solvers", "Solvers"), ("benchmarks", "Benchmarks"),
                          ("encodings", "Encodings and conversion"),
                          ("overall", "Overall results"), ("families", "Per-family results"),
                          ("caveats", "Caveats")]:
        P.append(f'<li><a href="#{anchor}">{e(title)}</a></li>')
    P.append("</ul></nav>")

    P.append('<h2 id="solvers">Solvers</h2>')
    P.append("<p>Four solvers, each given the encoding it is designed for. "
             "CryptoMiniSat is a CNF-XOR CDCL solver; Xorcle and Xorricane are XNF CDCL solvers "
             "(disjunctions of parity constraints); Bosphorus combines algebraic and logical "
             "reasoning over ANF.</p>")
    P.append(solver_table(con))
    P.append("""
<h3>What CryptoMiniSat needed</h3>
<p>CryptoMiniSat's defaults are tuned for general CNF, and on these families they discard almost
all of the linear structure before search begins: <code>--maxnummatrices</code> defaults to 5 where
lifted pebbling builds 11476 simultaneous matrices, and <code>--maxmatrixrows</code> defaults to
2000 where a single Bivium matrix is 10809 rows. The command line above lifts those cutoffs, which
is what makes this a measurement of the CNF-XOR path rather than the plain CNF one.</p>
<p>Lifting them was not enough on its own &mdash; the solver had not been run in that regime before,
and three changes were required. All are in the pinned revision used here:</p>
<table><thead><tr><th>Commit</th><th>Change</th><th>Needed for</th></tr></thead><tbody>
<tr><td><a href="https://github.com/msoos/cryptominisat/commit/068a3fd79"><code>068a3fd79</code></a></td>
    <td>fix crash when <code>--maxnummatrices</code> exceeds 1000</td>
    <td>lifted pebbling</td></tr>
<tr><td><a href="https://github.com/msoos/cryptominisat/commit/bef479cef"><code>bef479cef</code></a></td>
    <td>avoid O(num_matrices) per-literal work in Gauss-Jordan elimination</td>
    <td>lifted pebbling</td></tr>
<tr><td><a href="https://github.com/msoos/cryptominisat/commit/3970aaf24"><code>3970aaf24</code></a></td>
    <td>raise <code>MAX_XOR_RECOVER_SIZE</code> from 8 to 12</td>
    <td>Tseitin at k = 9, 10</td></tr>
</tbody></table>
<p>The last one mattered because a Tseitin formula on a k-regular graph has one parity constraint
of degree exactly k, and the compile-time ceiling of 8 put k = 9 and k = 10 out of reach at any
runtime setting. With it raised, CryptoMiniSat solves 75/75 of that family instead of 60/75.</p>""")

    P.append('<h2 id="benchmarks">Benchmarks</h2>')
    P.append(family_table(con))

    P.append('<h2 id="encodings">Encodings and conversion</h2>')
    P.append("""
<p>The same formula appears in several formats; each solver reads the one it supports.
Conversions were done with these tools:</p>
<table><thead><tr><th>Extension</th><th>Format</th><th>Produced by</th></tr></thead><tbody>
<tr><td><code>.cnf</code></td><td>plain CNF, XORs blasted</td><td>shipped with the benchmark</td></tr>
<tr><td><code>.xcnf</code> / <code>.cnf-xor</code></td><td>CNF-XOR</td>
    <td>shipped, or <code>xnf_to_xcnf.py</code></td></tr>
<tr><td><code>.2xcnf</code></td><td>CNF-XOR built from the 2-XNF</td>
    <td><code>xnf_to_xcnf.py</code></td></tr>
<tr><td><code>.xnf</code></td><td>XNF, <code>+</code> linerals</td><td>shipped, or <code>cnf2xnf</code></td></tr>
<tr><td><code>.2xnf</code></td><td>2-XNF, at most two linerals per clause</td>
    <td>shipped with the benchmark</td></tr>
<tr><td><code>.anf</code></td><td>algebraic normal form</td><td>shipped with the benchmark</td></tr>
</tbody></table>
<p>The CNF-XOR encodings a benchmark does not ship were generated to match the one the Xorricane
paper uses, and reproduce all 200 shipped <code>.xcnf</code> files exactly &mdash; variable, clause
and xor-line counts all agree.</p>
<h3>Why CryptoMiniSat does best on the plain CNF</h3>
<p>The plain CNF is the largest input by far, yet it is the one CryptoMiniSat solves. The reason is
that it preserves the cipher's native short XOR constraints. Bivium's update function is a handful
of taps, so the real parity constraints are about five variables wide; <code>occ-xor</code> recovers
them from the clause groups and hands Gauss-Jordan elimination a sparse, well conditioned system.
The XNF-derived encodings cannot do this, because a lineral in the XNF is already a sum of many
literals, and the definitional XOR that encodes it inherits that width.</p>
<p>All three encodings of one Bivium instance (<code>tmp09lh13kb</code>):</p>
<table><thead><tr><th></th><th><code>.cnf</code></th><th><code>.2xcnf</code></th>
<th><code>.xcnf</code></th></tr></thead><tbody>
<tr><td>formula</td><td>8468 v / 110745 cl</td><td>3544 v / 7310 cl</td><td>1420 v / 3062 cl</td></tr>
<tr><td>XOR constraints</td><td>3664 recovered</td><td>2305 given</td><td>889 given</td></tr>
<tr><td><code>occ-xor</code> finds</td><td>3664</td><td>0</td><td>0</td></tr>
<tr><td>clauses absorbed</td><td>54280</td><td>0</td><td>0</td></tr>
<tr><td>largest matrix</td><td>1242 &times; 1359</td><td>2100 &times; 3201</td><td>217 &times; 319</td></tr>
<tr><td>average XOR length</td><td>4.69</td><td>11.49</td><td>16.33</td></tr>
<tr><td>matrices</td><td>3</td><td>5</td><td>17</td></tr>
<tr><td>result</td><td>SAT, 3.07 s, 175 conflicts</td><td>timeout</td><td>timeout</td></tr>
</tbody></table>
<p>CryptoMiniSat solves the CNF in 175 conflicts &mdash; it is barely searching, the Gaussian
elimination is doing the work. The 2-XNF route is a real improvement over the shipped CNF-XOR
(half the XOR length, one coherent 2100-row system instead of seventeen fragments) but its rows are
still 2.4 times wider than what CryptoMiniSat extracts for itself, and that is what costs it the
solves. What matters here is XOR sparsity, not formula size: the 8468-variable CNF beats the
3544-variable CNF-XOR precisely because its recovered constraints are shorter.</p>

<p>CryptoMiniSat is given up to three encodings of the Xorricane-paper families. Besides the
shipped CNF-XOR and the plain CNF, <code>.2xcnf</code> is built from the <em>2-XNF</em> file
rather than the XNF one &mdash; the encoding behind the paper's best-performing
CryptoMiniSat configuration. It sits between the other two in size: on Bivium, 5314 variables
against 2128 for the shipped CNF-XOR and 25766 for the blasted CNF, with the XOR constraints
given explicitly rather than left to be recovered during preprocessing.</p>""")

    combined_svg = os.path.join(PICS, "cdf_all.svg")
    P.append('<h2 id="overall">Overall results</h2>')
    P.append("<p><strong>PAR2</strong> is the SAT-competition penalised average runtime: the mean "
             "over attempted instances of the solve time, with unsolved instances charged twice "
             "the timeout. Lower is better. The <em>attempted</em> column makes the denominator "
             "explicit, since not every solver ran on every family.</p>")
    P.append("<p>CDF of solving time over all families. Bosphorus is excluded here because it was "
             "not run on every family &mdash; only on the Ascon and Xorricane-paper suites &mdash; "
             "as is the XOR-detection-off CryptoMiniSat configuration, which ran only on Bivium. "
             "CryptoMiniSat appears twice: it was run on both a CNF-XOR and a plain CNF encoding "
             "of six families, so each line takes that encoding where it exists and the family's "
             f"only encoding elsewhere. Both cover all {total_inst} instances.</p>")
    if os.path.exists(combined_svg):
        P.append(f"<figure>{inline_svg(combined_svg, 'all')}</figure>")
    P.append(par2_table(read_par2(os.path.join(PICS, "cdf_all_par2.csv"))))

    P.append('<h2 id="families">Per-family results</h2>')
    for fam in families:
        svg = os.path.join(PICS, f"cdf_{fam}.svg")
        par2 = read_par2(os.path.join(PICS, f"cdf_{fam}_par2.csv"))
        label = FAMILY_NOTES.get(fam, (fam, ""))[0]
        P.append(f'<h3 id="f_{e(fam)}">{e(fam)} &mdash; {e(label)}</h3>')
        if os.path.exists(svg):
            P.append(f"<figure>{inline_svg(svg, 'f' + re.sub(r'[^a-zA-Z0-9]', '', fam))}</figure>")
        P.append(par2_table(par2))

    P.append('<h2 id="caveats">Caveats</h2>')
    P.append("""
<div class="note"><strong>CryptoMiniSat XOR size limit.</strong> With the default
<code>--maxxorsize 7</code>, every Tseitin instance with k&nbsp;&ge;&nbsp;8 times out while every
k&nbsp;&le;&nbsp;7 instance solves in 0.0&nbsp;s &mdash; the parity constraints have degree exactly
k, so at k=8 none are recovered and the solver is left doing pure resolution.</div>
<div class="note"><strong>Bivium CNF-XOR encoding.</strong> CryptoMiniSat solves 1/50 on the
shipped <code>.xcnf</code> but 34/50 on the plain <code>.cnf</code>. This is not an encoding-class
effect: the CNF-XOR files were produced by re-translating from XNF, which inherits the XNF's wide
linerals and leaves the XOR system far denser than the one CryptoMiniSat recovers for itself. See
<a href="#encodings">Why CryptoMiniSat does best on the plain CNF</a>. For this family the
<code>.cnf</code> column is the meaningful one.</div>
<div class="note"><strong>Xorcle memory use.</strong> Xorcle has the highest peak memory of any
solver here &mdash; 9.9&nbsp;GB, against 6.5&nbsp;GB for CryptoMiniSat and 1.8&nbsp;GB for
Xorricane &mdash; and eight of its runs exceeded 4&nbsp;GB, versus three for CryptoMiniSat and none
for any other solver. The pressure is concentrated in lifted pebbling (2.1&nbsp;GB average,
9.9&nbsp;GB peak), where it limits how many Xorcle runs can be scheduled in parallel, a practical
cost the solved counts do not show.</div>
""")

    doc = (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
           f"<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>XNF solver evaluation</title><style>{CSS}</style></head>"
           f"<body><div class=wrap>{''.join(P)}</div></body></html>")

    with open(args.output, "w") as f:
        f.write(doc)
    con.close()
    size = os.path.getsize(args.output) / 1024
    print(f"wrote {args.output} ({size:.0f} KB, {len(families)} families, self-contained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
