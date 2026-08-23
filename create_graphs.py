#!/bin/python3
"""CDF plots from data.sqlite into pics/: ./create_graphs.py [--family F]"""

import argparse
import base64
import os
import re
import shutil
import sqlite3
import subprocess

DB = "data.sqlite"
OUT_DIR = "pics"

# preferred encoding when a solver was run on more than one, for the combined plot
EXT_PREF = [".xcnf", ".cnf-xor", ".xnf", ".lxnf", ".anf", ".cnf"]

COLORS = {
    "cms":       "#1f77b4",
    "cms-noxor": "#8c564b",
    "xorcle":    "#d62728",
    "xorricane": "#2ca02c",
    "xnfsat":    "#9467bd",
    "bosphorus": "#ff7f0e",
}
FALLBACK = "#7f7f7f"

SOLID_SOLVERS = {"cms"}

# distinct shades when one solver is plotted on several encodings
SHADES = {
    ("cms", ".cnf"): "#0d3d6b",
    ("cms", ".xcnf"): "#5ba3d9",
}


def color_for(solver, label):
    m = re.search(r"\((\.[\w-]+)\)", label)
    if m and (solver, m.group(1)) in SHADES:
        return SHADES[(solver, m.group(1))]
    return COLORS.get(solver, FALLBACK)


def png_dimensions(path):
    try:
        with open(path, "rb") as f:
            f.seek(16)
            return int.from_bytes(f.read(4), "big"), int.from_bytes(f.read(4), "big")
    except OSError:
        return 900, 700


def display_png(path):
    if not os.path.exists(path):
        return
    with open(path, "rb") as f:
        img = base64.b64encode(f.read()).decode()
    w, h = png_dimensions(path)
    print(f"\033]1337;File=inline=1;width={w}px;height={h}px:{img}\a")


def pick_ext(exts):
    return next((e for e in EXT_PREF if e in exts), sorted(exts)[0])


def exts_by_family(con, solver):
    by_fam = {}
    for fam, ext in con.execute(
            "SELECT family, ext FROM data WHERE solver=? GROUP BY family, ext", (solver,)):
        by_fam.setdefault(fam, []).append(ext)
    return by_fam


def combined_variants(con, solver):
    """One (label, {family: ext}) per encoding the solver was run on more than once.

    Each variant still spans every family: where the preferred encoding is absent,
    the family's only encoding is used, so all variants cover the same instances."""
    by_fam = exts_by_family(con, solver)
    alternatives = sorted({e for exts in by_fam.values() if len(exts) > 1 for e in exts},
                          key=lambda e: EXT_PREF.index(e) if e in EXT_PREF else 99)
    if not alternatives:
        return [(solver, {f: pick_ext(x) for f, x in by_fam.items()})]
    out = []
    for pref in alternatives:
        picks = {f: (pref if pref in x else pick_ext(x)) for f, x in by_fam.items()}
        out.append((f"{solver} ({pref})", picks))
    return out


def series_for(con, family, combined):
    """Return [(label, solver, sel)]; sel is an ext, or a {family: ext} map when combined."""
    if combined:
        out = []
        for (solver,) in con.execute("SELECT DISTINCT solver FROM data ORDER BY solver"):
            out.extend((label, solver, picks) for label, picks in combined_variants(con, solver))
        return out
    by_solver = {}
    for solver, ext in con.execute(
            "SELECT solver, ext FROM data WHERE family=? GROUP BY solver, ext", (family,)):
        by_solver.setdefault(solver, []).append(ext)
    out = []
    for solver in sorted(by_solver):
        exts = by_solver[solver]
        if len(exts) > 1:
            out.extend((f"{solver} ({e})", solver, e) for e in sorted(exts))
        else:
            out.append((solver, solver, None))
    return out


def write_series(con, base, label, solver, ext, family, combined):
    """Write the raw csv and the cdf data file; return (dat_path, n_solved)."""
    if combined:
        times = []
        for fam, fam_ext in ext.items():
            times += [r[0] for r in con.execute(
                "SELECT solve_time FROM data WHERE solver=? AND family=? AND ext=?"
                " AND solve_time IS NOT NULL", (solver, fam, fam_ext))]
        times.sort()
    else:
        q = "SELECT solve_time FROM data WHERE solver=? AND family=? AND solve_time IS NOT NULL"
        args = [solver, family]
        if ext is not None:
            q += " AND ext=?"
            args.append(ext)
        q += " ORDER BY solve_time"
        times = [r[0] for r in con.execute(q, args)]

    safe = label.replace(" ", "").replace("(", "").replace(")", "")
    csv_path = f"{base}_{safe}.csv"
    dat_path = f"{base}_{safe}.dat"
    with open(csv_path, "w") as f:
        f.write("solve_time\n")
        for t in times:
            f.write(f"{t}\n")
    with open(dat_path, "w") as f:
        for i, t in enumerate(times):
            f.write(f"{i + 1}\t{t}\n")
    return dat_path, len(times)


def par2_row(con, solver, ext, family, combined):
    """PAR2 = mean over attempted instances, unsolved counted as 2x that family's timeout."""
    if combined:
        fams = sorted(ext.items())
    else:
        fams = [(family, ext)]
    attempted = solved = 0
    penalty = 0.0
    times = []
    mem = 0.0
    for fam, fam_ext in fams:
        q = "SELECT solve_time, mem_MB FROM data WHERE solver=? AND family=?"
        args = [solver, fam]
        if fam_ext is not None:
            q += " AND ext=?"
            args.append(fam_ext)
        rows = con.execute(q, args).fetchall()
        if not rows:
            continue
        limit = con.execute(
            "SELECT MIN(timeout_t) FROM data WHERE family=?", (fam,)).fetchone()[0] or 0
        for t, m in rows:
            attempted += 1
            mem = max(mem, m or 0.0)
            if t is None:
                penalty += 2 * limit
            else:
                solved += 1
                times.append(t)
                penalty += t
    if not attempted:
        return None
    return {"attempted": attempted, "solved": solved,
            "par2": penalty / attempted,
            "avg_solved_t": (sum(times) / len(times)) if times else None,
            "max_mem_MB": mem}


def write_par2_csv(path, rows):
    with open(path, "w") as f:
        f.write("solver,attempted,solved,par2,avg_time_solved_s,max_mem_MB\n")
        for label, r in rows:
            avg = "" if r["avg_solved_t"] is None else f"{r['avg_solved_t']:.2f}"
            f.write(f"{label},{r['attempted']},{r['solved']},{r['par2']:.2f},"
                    f"{avg},{r['max_mem_MB']:.0f}\n")


def make_plot(con, name, title, family, combined, exclude, verbose):
    base = os.path.join(OUT_DIR, name)
    entries = []
    for label, solver, ext in series_for(con, family, combined):
        if solver in exclude:
            continue
        dat, n = write_series(con, base, label, solver, ext, family, combined)
        if n:
            entries.append((dat, label, solver, n))
    if not entries:
        return None

    if combined:
        total = con.execute(
            "SELECT COUNT(DISTINCT family || '/' || instance) FROM data").fetchone()[0]
        limit = con.execute(
            "SELECT MAX(m) FROM (SELECT MIN(timeout_t) AS m FROM data GROUP BY family)").fetchone()[0]
    else:
        total = con.execute(
            "SELECT COUNT(DISTINCT instance) FROM data WHERE family=?", (family,)).fetchone()[0]
        limit = con.execute(
            "SELECT MIN(timeout_t) FROM data WHERE family=?", (family,)).fetchone()[0]

    entries.sort(key=lambda e: -e[3])
    gp_path, pdf_path, png_path = base + ".gnuplot", base + ".pdf", base + ".png"
    svg_path = base + ".svg"
    ymax = int(max(e[3] for e in entries) * 1.08) + 1

    seen_solver = {}
    lines = []
    for dat, label, solver, n in entries:
        variant = seen_solver.get(solver, 0)
        seen_solver[solver] = variant + 1
        # cms variants stay solid and are told apart by shade (see SHADES)
        dt = 1 if solver in SOLID_SOLVERS else variant + 1
        lines.append(
            f'  "{os.path.basename(dat)}" u 2:1 with linespoints pt 7 ps 0.4 lw 2 '
            f'dt {dt} lc rgb "{color_for(solver, label)}" title "{label} ({n})"')
    plot = ",\\\n".join(lines)

    with open(gp_path, "w") as f:
        for term, out in [
            ('pdfcairo size 24cm,18cm font ",12"', os.path.basename(pdf_path)),
            ('pngcairo size 1100,800 font ",12"', os.path.basename(png_path)),
            ('svg size 1000,720 font "sans,13"', os.path.basename(svg_path)),
        ]:
            f.write(f"set terminal {term}\n")
            f.write(f'set output "{out}"\n')
            f.write(f'set title "{title}  ({total} instances, {limit}s timeout)"\n')
            f.write("set key bottom right box\n")
            f.write("unset logscale x\nunset logscale y\n")
            f.write('set xlabel "Time (s)"\n')
            f.write('set ylabel "Instances solved"\n')
            f.write("set grid\n")
            f.write(f"plot [0:{limit}][0:{ymax}]\\\n{plot}\n\n")

    rc = subprocess.run(["gnuplot", os.path.basename(gp_path)], cwd=OUT_DIR).returncode
    if rc != 0 and verbose:
        print(f"  gnuplot failed for {name}")

    par2 = []
    for label, solver, ext in series_for(con, family, combined):
        if solver in exclude:
            continue
        r = par2_row(con, solver, ext, family, combined)
        if r:
            par2.append((label, r))
    par2.sort(key=lambda x: x[1]["par2"])
    write_par2_csv(base + "_par2.csv", par2)
    return png_path, entries, total, limit, par2


def main():
    ap = argparse.ArgumentParser(description="Generate CDF plots from " + DB)
    ap.add_argument("--family", action="append", default=[], help="only these families")
    ap.add_argument("--no-display", action="store_true", help="do not print PNGs inline")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(DB):
        raise SystemExit(f"{DB} not found -- run ./get_data_to_sqlite.py first")
    if os.path.exists(OUT_DIR) and not args.family:
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)

    con = sqlite3.connect(DB)
    families = [r[0] for r in con.execute("SELECT DISTINCT family FROM data ORDER BY family")]
    if args.family:
        families = [f for f in families if f in args.family]

    todo = [] if args.family else [
        ("cdf_all", "All benchmarks (bosphorus, xnfsat, cms-noxor excluded: not run everywhere)",
         None, True, {"bosphorus", "xnfsat", "cms-noxor"})]
    todo += [(f"cdf_{f}", f, f, False, set()) for f in families]

    for name, title, family, combined, exclude in todo:
        res = make_plot(con, name, title, family, combined, exclude, args.verbose)
        if res is None:
            continue
        png, entries, total, limit, par2 = res
        print(f"\n=== {title} -- {total} instances, {limit}s ===")
        print(f"    {'solver':<24} {'solved':>8} {'attempt':>8} {'PAR2':>10} {'avg t':>8} {'maxMB':>8}")
        for label, r in par2:
            avg = "-" if r["avg_solved_t"] is None else f"{r['avg_solved_t']:.1f}"
            print(f"    {label:<24} {r['solved']:>8} {r['attempted']:>8} "
                  f"{r['par2']:>10.1f} {avg:>8} {r['max_mem_MB']:>8.0f}")
        if not args.no_display:
            display_png(png)

    con.close()
    print(f"\nwrote {len(os.listdir(OUT_DIR))} files to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
