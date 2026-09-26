"""Replay the two Rev D rollouts' behaviour against the Rev E prompt and rubric."""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import grade as GR  # noqa: E402
import solve as SV  # noqa: E402

LABEL1 = {"Cultivated cropland": "2 - Cultivated cropland", "Grassland / pasture": "1 - Grassland / pasture",
          "Woodland": "3 - Woodland", "Existing gravel track": "5 - Existing gravel track",
          "Watercourse": "Culvert (Watercourse at crossing window)"}
DP1 = dict(elev_m=2, chainage_m=1, grade_to_next_pct=2, cum_constr_usd=0, cum_haul_usd=0, cum_cost_usd=0)


def report(name, res):
    s, got, pos = GR.score(res)
    lost = [k for k, w, _ in GR.RUBRIC if (res[k] if w < 0 else not res[k])]
    print(f"{name:62s} {s:6.1%} ({got}/{pos})  lost: {' '.join(lost)}")
    return s


def run(name, opts, labels=None, dp=None, **claim_over):
    r = SV.solve(opts)
    rows, L = SV.summarise(r)
    cp = SV.check_path(r)
    d = Path(tempfile.mkdtemp())
    GR.write_deliverables(d, rows, L, r["cost"], labels=labels, dp=dp)
    lb = {}
    for a, c in zip(rows[:-1], rows[1:]):
        lb[a["landcover"]] = lb.get(a["landcover"], 0) + (c["chainage_m"] - a["chainage_m"]) / 2
        lb[c["landcover"]] = lb.get(c["landcover"], 0) + (c["chainage_m"] - a["chainage_m"]) / 2
    claims = dict(cost=r["cost"], constr=rows[-1]["cum_constr_usd"], haul=rows[-1]["cum_haul_usd"], length=L,
                  max_grade=round(cp["max_rise"], 2), len_by=lb, n_max=max(x["northing"] for x in rows),
                  lease=GR.lease_length(rows), slump=True, S1=True, S2=True, S3=True, S4=True, S5=True, S6=True,
                  S7=True, E5=True, E6=True, F6=True, N2=False, N3=False, N4=False)
    claims.update(claim_over)
    return report(name, GR.grade_files(d, claims))


def golden_own_format():
    d = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "golden" / "CB_HaulRoad_RouteReport.pdf", d)
    r = SV.solve({})
    rows, L = SV.summarise(r)
    GR.write_deliverables(d, rows, L, r["cost"], labels=LABEL1, dp=DP1)
    c = GR.golden_claims()
    c.update(S2=False)
    return report("Reference: every rule right, Response 1's labels and rounding", GR.grade_files(d, c))


if __name__ == "__main__":
    a = run("Response 1 behaviour: exact Rev D answer, own labels/rounding", SV.REV_E_OFF, labels=LABEL1, dp=DP1,
            S2=False, E5=False, E6=False)
    b = run("Response 2 behaviour: relaxed path, updates ignored",
            dict(SV.REV_E_OFF, no_vc=True, no_tangent=True, no_sustain=True),
            slump=False, S2=False, E5=False, E6=False)
    print(f"mean of the two replays {(a + b) / 2:.1%}")
    golden_own_format()
