"""Score the two pasted Rev D rollouts (reconstructed) with the scripted grader."""
import csv
import math
import shutil
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import grade as GR  # noqa: E402
import solve as SV  # noqa: E402

LABEL1 = {"Cultivated cropland": "2 - Cultivated cropland", "Grassland / pasture": "1 - Grassland / pasture",
          "Woodland": "3 - Woodland", "Existing gravel track": "5 - Existing gravel track",
          "Watercourse": "Culvert (Watercourse at crossing window)"}


def report(name, res):
    s, got, pos = GR.score(res)
    lost = [k for k, w, _ in GR.RUBRIC if (res[k] if w < 0 else not res[k])]
    print(f"{name:40s} {s:6.1%} ({got}/{pos})  lost: {' '.join(lost)}")
    return s


def response1():
    d = Path(tempfile.mkdtemp())
    for f in ("CB_HaulRoad_Centreline.gpkg", "CB_HaulRoad_RouteReport.pdf"):
        shutil.copy(ROOT / "golden" / f, d / f)
    rows = list(csv.reader(open(ROOT / "golden" / "CB_HaulRoad_Vertices.csv")))
    with open(d / "CB_HaulRoad_Vertices.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(rows[0])
        for r in rows[1:]:
            r[6] = LABEL1.get(r[6], r[6])
            w.writerow(r)
    c = GR.golden_claims()
    c.update(S2=False)
    return report("Response 1 (golden route, own labels)", GR.grade_files(d, c))


def response2():
    r = SV.solve({"no_vc": True, "no_tangent": True, "no_sustain": True})
    rows, L = SV.summarise(r)
    cp = SV.check_path(r)
    print(f"  R2 reconstruction: cost {r['cost']:,.0f}  length {L:,.1f}  rows {len(rows)}")
    d = Path(tempfile.mkdtemp())
    gpd.GeoDataFrame(geometry=[LineString([(x["easting"], x["northing"]) for x in rows])], crs="EPSG:32614") \
        .to_file(d / "CB_HaulRoad_Centreline.gpkg", layer="centreline", driver="GPKG")
    with open(d / "CB_HaulRoad_Vertices.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(GR.HEADER)
        for x in rows:
            w.writerow([x["seq"], x["easting"], x["northing"], x["elev_m"], x["chainage_m"],
                        "" if math.isnan(x["grade_pct"]) else f"{x['grade_pct']:.3f}", x["landcover"],
                        x["cum_cost_usd"]])
    (d / "CB_HaulRoad_RouteReport.pdf").write_bytes(b"%PDF-1.4")
    lb = {}
    for a, c in zip(rows[:-1], rows[1:]):
        lb[a["landcover"]] = lb.get(a["landcover"], 0) + c["chainage_m"] - a["chainage_m"]
    claims = dict(cost=r["cost"], constr=rows[-1]["cum_constr_usd"], haul=rows[-1]["cum_haul_usd"], length=L,
                  max_grade=round(cp["max_rise"], 2), len_by=lb, n_max=max(x["northing"] for x in rows),
                  slump=False, S1=True, S2=False, S3=True, S4=True, S5=True, S6=True, S7=True, F6=True,
                  N2=False, N3=False, N4=False)
    return report("Response 2 (relaxed path, false compliance)", GR.grade_files(d, claims))


if __name__ == "__main__":
    a, b = response1(), response2()
    print(f"mean of the two rollouts {(a + b) / 2:.1%}")
