"""Choose rubric checkpoints on the golden route that single-rule misses avoid; refresh grade.py constants."""
import csv, json, re, sys
from pathlib import Path
sys.path.insert(0, "src")
import numpy as np
import solve as SV

ROOT = Path(".")
MISSES = ["revD_golden", "no_plateau", "plateau_all", "zone_per_move", "no_zone", "no_gate", "gate_3",
          "no_adverse", "no_vc", "no_radius", "no_haul", "haul_flip", "end_revc"]
N_CP, SPACING = 20, 6

r = SV.solve({}); rows, _ = SV.summarise(r)
PG = np.array([(x["easting"], x["northing"]) for x in rows])
off = {}
for m in MISSES:
    rw, _ = SV.summarise(SV.solve(SV.VARIANTS[m]))
    P = np.array([(x["easting"], x["northing"]) for x in rw])
    d = np.array([np.hypot(*(P - p).T).min() for p in PG])
    off[m] = set(np.nonzero(d > 0.5)[0].tolist())
    print(f"{m:14s} {len(off[m])} golden vertices off-route")
caught = {m: 0 for m in MISSES}
chosen = []
for _ in range(N_CP):
    best, bs = None, -1
    for v in range(1, len(PG) - 1):
        if any(abs(v - c) < SPACING for c in chosen):
            continue
        s = sum(1.0 / (1 + caught[m]) ** 3 for m in MISSES if v in off[m])
        if s > bs:
            best, bs = v, s
    chosen.append(best)
    for m in MISSES:
        if best in off[m]:
            caught[m] += 1
chosen.sort()
cov = {v: [m for m in MISSES if v in off[m]] for v in chosen}
print("caught per miss", caught)
ranked = sorted(chosen, key=lambda v: -len(cov[v]))
w7 = set(ranked[:6])
cps = "CPS = [  # (id, weight, E, N): golden cell centres that single-rule misses avoid\n"
for n, v in enumerate(chosen, 1):
    cps += f'    ("P{n}", 7, {PG[v][0]:.1f}, {PG[v][1]:.1f}),  # vertex {v + 1}: {" ".join(cov[v])}\n'
cps += "]\n"
print(cps)

sm = json.loads((ROOT / "work" / "golden_summary.json").read_text())
lb = sm["len_by"]
crow = list(csv.DictReader(open(ROOT / "golden" / "CB_HaulRoad_Vertices.csv")))
wc = [x for x in crow if x["landcover_class"] == "Watercourse"][0]
nmax = max(float(x["northing_m"]) for x in crow)
top = [x for x in crow if float(x["northing_m"]) == nmax][0]
ncharged = sum(1 for x in crow if x["grade_to_next_pct"] and float(x["grade_to_next_pct"]) < -1.0)
g = (f'LM = dict(wc_cost={float(wc["cum_cost_usd"]):.2f}, top_cost={float(top["cum_cost_usd"]):.2f}, '
     f'top_ch={float(top["chainage_m"]):.2f}, n_charged={ncharged}, lease={sm["lease_len_m"]:.2f})\n'
     f'G = dict(total={sm["cost_usd"]:.2f}, constr={sm["constr_usd"]:.2f}, haul={sm["haul_usd"]:.2f}, '
     f'length={sm["length_m"]:.2f}, rows={sm["n_vertices"]}, ndef={sm["n_deflections"]},\n'
     f'         wood={lb["Woodland"]:.1f}, grass={lb["Grassland / pasture"]:.1f}, '
     f'track={lb["Existing gravel track"]:.1f}, crop={lb["Cultivated cropland"]:.1f}, '
     f'max_rise={sm["max_grade_pct"]:.2f}, n_max={sm["n_max"]:.1f},\n'
     f'         adv={sm["max_adverse_loaded_pct"]:.2f}, min_k={sm["min_k"]:.3f}, min_tan={sm["min_tangent_m"]:.2f})\n')
print(g)
p = ROOT / "src" / "grade.py"
s = p.read_text()
s = re.sub(r'CPS = \[.*?\n\]\n', cps, s, flags=re.S)
s = re.sub(r'END = \(.*?\)\n', f'END = ({sm["end"][0]:.1f}, {sm["end"][1]:.1f})\n', s)
s = re.sub(r'LM = dict\(.*?\)\nG = dict\(total=.*?n_max=[\d.]+(,\n.*?min_tan=[\d.]+)?\)\n', g, s, flags=re.S)
p.write_text(s)
