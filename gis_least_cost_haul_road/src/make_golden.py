"""Produce the golden deliverables: GeoPackage centreline, vertex CSV and PDF route report."""
import collections
import csv
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)
from shapely.geometry import LineString

import solve as SV

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "golden"
WORK = ROOT / "work"
GPKG = "CB_HaulRoad_Centreline.gpkg"
CSVF = "CB_HaulRoad_Vertices.csv"
PDFF = "CB_HaulRoad_RouteReport.pdf"


def main():
    OUT.mkdir(exist_ok=True)
    b = SV.BRIEF
    res = SV.solve({})
    rows, L = SV.summarise(res)
    cost = res["cost"]
    g = np.array([r["grade_pct"] for r in rows[:-1]])

    with open(OUT / CSVF, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seq", "easting_m", "northing_m", "elev_m", "chainage_m", "grade_to_next_pct",
                    "landcover_class", "cum_cost_usd"])
        for r in rows:
            w.writerow([r["seq"], f"{r['easting']:.2f}", f"{r['northing']:.2f}", f"{r['elev_m']:.3f}",
                        f"{r['chainage_m']:.2f}", "" if np.isnan(r["grade_pct"]) else f"{r['grade_pct']:.3f}",
                        r["landcover"], f"{r['cum_cost_usd']:.2f}"])

    line = LineString([(r["easting"], r["northing"]) for r in rows])
    gdf = gpd.GeoDataFrame(
        dict(route_id=["CB-HR-01"], length_m=[round(L, 2)], cost_usd=[round(cost, 2)],
             max_grade_pct=[round(float(np.abs(g).max()), 3)], crossing=["X-2"]),
        geometry=[line], crs=f"EPSG:{b['epsg']}")
    (OUT / GPKG).unlink(missing_ok=True)
    gdf.to_file(OUT / GPKG, layer="centreline", driver="GPKG")

    # breakdowns: each move's length and cost split equally between its two end cells' classes
    len_by = collections.defaultdict(float)
    cost_by = collections.defaultdict(float)
    for a, c in zip(rows[:-1], rows[1:]):
        d = c["chainage_m"] - a["chainage_m"]
        seg = c["cum_cost_usd"] - a["cum_cost_usd"]
        ca, cc = b_cost(a["landcover"]), b_cost(c["landcover"])
        for cls, share in ((a["landcover"], ca / (ca + cc)), (c["landcover"], cc / (ca + cc))):
            len_by[cls] += d / 2
            cost_by[cls] += seg * share
    bands = [(0, 3), (3, 6), (6, 8), (8, 10)]
    dists = np.diff([r["chainage_m"] for r in rows])
    band_len = [float(dists[(np.abs(g) > lo) & (np.abs(g) <= hi) | ((lo == 0) & (np.abs(g) == 0))].sum())
                for lo, hi in bands]

    variants = [
        ("Adopted route (all constraints)", {}),
        ("Check: without 30 m wetland setback", {"no_setback": True}),
        ("Check: without HS-1 exclusion", {"no_heritage": True}),
        ("Check: Rev A woodland rate 690 USD/m", "revA"),
    ]
    var_rows = []
    for name, o in variants:
        if o == "revA":
            keep = SV.BRIEF["classes"]["3"]["cost"]
            SV.BRIEF["classes"]["3"]["cost"] = 690.0
            rr = SV.solve({})
            SV.BRIEF["classes"]["3"]["cost"] = keep
        else:
            rr = SV.solve(o)
        rws, LL = SV.summarise(rr)
        xw = [x for x in rws if x["landcover"] == "Watercourse"][0]
        xname = "X-2" if xw["northing"] < 3350200 else "X-1"
        var_rows.append([name, f"{rr['cost']:,.0f}", f"{LL:,.1f}", xname])
    only_x1 = SV.solve({"drop_X2": True})
    assert only_x1 is None

    figs = plan_and_profile(res, rows)
    write_pdf(rows, L, cost, g, len_by, cost_by, band_len, var_rows, figs)
    summary = dict(cost_usd=cost, length_m=L, n_vertices=len(rows), max_grade_pct=float(np.abs(g).max()),
                   start=[rows[0]["easting"], rows[0]["northing"]], end=[rows[-1]["easting"], rows[-1]["northing"]],
                   start_elev_m=rows[0]["elev_m"], end_elev_m=rows[-1]["elev_m"],
                   len_by=len_by, cost_by=cost_by, band_len=band_len, variants=var_rows)
    (WORK / "golden_summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps(summary, indent=1, default=float))


def b_cost(name):
    for info in SV.BRIEF["classes"].values():
        if info["name"] == name:
            return info["cost"] if info["cost"] is not None else SV.BRIEF["culvert_cost"]
    raise KeyError(name)


def plan_and_profile(res, rows):
    b = SV.BRIEF
    lcd, EX, EY, z = res["lcd"], res["EX"], res["EY"], res["z"]
    rgb = np.zeros(lcd.shape + (3,))
    for c, info in b["classes"].items():
        rgb[lcd == int(c)] = np.array(info["rgb"]) / 255
    fig, ax = plt.subplots(figsize=(11, 8.2))
    ext = [b["dem_ul_e"], b["dem_ul_e"] + 3600, b["dem_ul_n"] - 2800, b["dem_ul_n"]]
    ax.imshow(rgb, extent=ext, origin="upper", interpolation="nearest")
    blocked = np.isnan(res["base"]) & (lcd != 6)
    ax.imshow(np.ma.masked_where(~blocked, blocked), extent=ext, origin="upper", cmap="Greys", alpha=0.35,
              vmin=0, vmax=1, interpolation="nearest")
    cs = ax.contour(EX, EY, z, levels=np.arange(360, 520, 5), colors="k", linewidths=0.3)
    ax.clabel(cs, cs.levels[::2], fontsize=6, fmt="%d m")
    p = np.array([(r["easting"], r["northing"]) for r in rows])
    ax.plot(p[:, 0], p[:, 1], color="red", lw=2.2, label="Adopted centreline CB-HR-01")
    h = res["pts"]["HERITAGE"]
    ax.add_patch(plt.Circle(h, 150, fill=False, ec="darkred", lw=1.5, ls="--", label="HS-1 150 m exclusion"))
    for k, lab in (("START", "T1"), ("END", "G1"), ("X1", "X-1"), ("X2", "X-2"), ("HERITAGE", "HS-1")):
        ax.plot(*res["pts"][k], "k^", ms=7)
        ax.annotate(lab, res["pts"][k], (res["pts"][k][0] + 40, res["pts"][k][1] + 40), fontsize=9, weight="bold")
    for ch in range(0, int(rows[-1]["chainage_m"]), 500):
        r = min(rows, key=lambda x: abs(x["chainage_m"] - ch))
        ax.annotate(f"{ch/1000:.1f} km", (r["easting"], r["northing"]), fontsize=7, color="darkred",
                    xytext=(4, -10), textcoords="offset points")
    ax.set_aspect("equal"); ax.legend(loc="lower right", fontsize=8)
    ax.set_xlabel("Easting (m), EPSG:32614"); ax.set_ylabel("Northing (m)")
    ax.ticklabel_format(useOffset=False, style="plain"); ax.tick_params(labelsize=7)
    ax.set_title("Plan - adopted least-cost centreline (grey = prohibited / setback cells)")
    fig.tight_layout(); f1 = WORK / "golden_plan.png"; fig.savefig(f1, dpi=170); plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 3.6))
    ch = [r["chainage_m"] for r in rows]; el = [r["elev_m"] for r in rows]
    ax.plot(ch, el, "k", lw=1.2)
    ax.set_xlabel("Chainage (m)"); ax.set_ylabel("Elevation (m, NAVD 88)"); ax.grid(alpha=0.4)
    ax.set_title("Long section along adopted centreline (terrain at DEM cell centres)")
    fig.tight_layout(); f2 = WORK / "golden_profile.png"; fig.savefig(f2, dpi=170); plt.close(fig)
    return f1, f2


def write_pdf(rows, L, cost, g, len_by, cost_by, band_len, var_rows, figs):
    b = SV.BRIEF
    ss = getSampleStyleSheet()
    body = ss["BodyText"]; body.fontSize = 9.5; body.leading = 12.5
    h1, h2 = ss["Heading1"], ss["Heading2"]
    doc = SimpleDocTemplate(str(OUT / PDFF), pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title="CB Haul Road - Least-Cost Route Report", author="Route study team")
    ts = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                     ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])
    S = []
    S.append(Paragraph("Cedar Bluff Quarry Haul Road - Least-Cost Route Report (route CB-HR-01)", h1))
    S.append(Paragraph("Basis: drawing CB-HR C-001/C-002 Rev B and the two rasters it registers. "
                       "Horizontal CRS WGS 84 / UTM zone 14N (EPSG:32614); lengths are horizontal. "
                       "Status: route study only, not for construction.", body))
    S.append(Spacer(1, 4))
    S.append(Paragraph("1. Result", h2))
    x2 = [r for r in rows if r["landcover"] == "Watercourse"]
    res_tab = [
        ["Quantity", "Value"],
        ["Total accumulated route cost (USD)", f"{cost:,.2f}"],
        ["Horizontal length, start cell centre to end cell centre (m)", f"{L:,.2f}"],
        ["Vertices (DEM cell centres) / moves", f"{len(rows)} / {len(rows) - 1}  ({sum(1 for a, c in zip(rows, rows[1:]) if a['easting'] != c['easting'] and a['northing'] != c['northing'])} diagonal)"],
        ["Start cell centre (T1 on CR-114)", f"E {rows[0]['easting']:.2f}  N {rows[0]['northing']:.2f}  z {rows[0]['elev_m']:.2f} m"],
        ["End cell centre (G1 quarry gate)", f"E {rows[-1]['easting']:.2f}  N {rows[-1]['northing']:.2f}  z {rows[-1]['elev_m']:.2f} m"],
        ["Creek crossing", f"Approved window X-2, culvert on 2 watercourse cells at N {x2[0]['northing']:.0f} "
                           f"(E {x2[0]['easting']:.0f} to {x2[-1]['easting']:.0f})"],
        ["Maximum grade on any move (limit 10.0 %)", f"{np.abs(g).max():.2f} % (uphill towards G1); steepest downhill {g.min():.2f} %"],
        ["Northernmost point (route passes round the north end of Cedar Bluff Ridge)",
         f"E {max(rows, key=lambda r: r['northing'])['easting']:.0f}  N {max(r['northing'] for r in rows):.0f}"],
        ["Closest approach to HS-1 recorded point (exclusion 150 m)",
         f"{min(np.hypot(r['easting'] - 585511.9, r['northing'] - 3350201.9) for r in rows):.0f} m"],
    ]
    t = Table(res_tab, colWidths=[120 * mm, 140 * mm]); t.setStyle(ts); S.append(t)
    S.append(Spacer(1, 6))
    S.append(Paragraph("2. Method", h2))
    for p in [
        "<b>Terrain.</b> DEM DN converted to elevation with Elevation(ft) = 1150.00 + 0.01 x DN (Table 1), then to metres "
        "with the US survey foot (1 ft = 1200/3937 m). The drawing's vertical unit is feet while the grid is in metres; "
        "without the conversion every grade is 3.28 times too large and no route under 10 % exists.",
        "<b>Georeferencing.</b> Both rasters are pixel-is-area with the upper-left corner of the upper-left pixel as registered "
        "on C-002 Table 1. DEM cell centres are at E 583 005 + 10i, N 3 351 495 - 10j. The land-cover raster has its own "
        "origin (E 582 900, N 3 351 620) and 20 m pixels; its edges coincide with DEM cell edges, so each land-cover pixel covers "
        "exactly 2 x 2 DEM cells, and each DEM cell takes the class of the land-cover pixel containing its centre. "
        "Colours were matched on exact RGB (every pixel matched one of the 8 classes).",
        "<b>Control points.</b> Table 3 WGS 84 lat/long converted to EPSG:32614 with PROJ (pyproj). "
        "T1 -> E 583 153.23, N 3 349 102.62 (cell centre E 583 155, N 3 349 105); "
        "G1 -> E 586 318.42, N 3 350 996.91 (cell centre E 586 315, N 3 350 995).",
        "<b>Constraints.</b> Prohibited: wetland, farmstead, and watercourse cells except those whose centre is within 30.0 m of "
        "X-1 or X-2 (costed at 3 800 USD/m); every cell whose centre is within 30.0 m of the mapped wetland boundary (the edges of "
        "the wetland pixels); every cell whose centre is within 150.0 m of HS-1. Woodland at the Rev B rate of 940 USD/m.",
        "<b>Search.</b> Dijkstra accumulated-cost search on the 10 m DEM grid, 8-connected (queen's case). A move of horizontal "
        "length d (10 m or 14.142 m) between cells i and j costs d x (c_i + c_j)/2 x f(g), where g = |z_j - z_i| / d is the grade "
        "along that move and f is the brief's grade factor; any move with g above 10.0 % is not allowed. Grade therefore depends on "
        "the direction of travel: a hillside too steep to climb straight up can still be traversed on the diagonal. A single "
        "isotropic terrain-slope raster does not model this and gives a different route.",
    ]:
        S.append(Paragraph(p, body)); S.append(Spacer(1, 3))
    rt = [["Item applied", "Value"],
          ["Grassland / pasture", "420 USD/m"], ["Cultivated cropland", "480 USD/m"],
          ["Woodland (Rev B; Rev A 690 withdrawn)", "940 USD/m"], ["Rock outcrop", "1,150 USD/m"],
          ["Existing gravel track", "160 USD/m"], ["Watercourse cell within 30.0 m of X-1 / X-2 centre (culvert)", "3,800 USD/m"],
          ["Watercourse elsewhere, wetland, farmstead", "prohibited"],
          ["Wetland W-1 setback from mapped boundary", "30.0 m, prohibited"],
          ["HS-1 exclusion radius", "150.0 m, prohibited"], ["Maximum grade on any move", "10.0 %"],
          ["Grade factor f(g)", "1.00 (g<=3); 1.00+0.05(g-3) (3<g<=6); 1.15+0.12(g-6) (6<g<=10)"]]
    t = Table(rt, colWidths=[120 * mm, 140 * mm]); t.setStyle(ts)
    S.append(Paragraph("Rates and constraint values applied (C-002 Rev B)", h2)); S.append(t)
    S.append(PageBreak())
    S.append(Paragraph("3. Plan and long section", h2))
    S.append(RLImage(str(figs[0]), width=190 * mm, height=141 * mm))
    S.append(PageBreak())
    S.append(RLImage(str(figs[1]), width=260 * mm, height=85 * mm))
    S.append(Paragraph("4. Breakdown", h2))
    order = ["Grassland / pasture", "Cultivated cropland", "Woodland", "Existing gravel track", "Watercourse"]
    bt = [["Land-cover class", "Length (m)", "Cost (USD)"]]
    for k in order:
        bt.append([k if k != "Watercourse" else "Watercourse at X-2 (culvert)", f"{len_by[k]:,.1f}", f"{cost_by[k]:,.0f}"])
    bt.append(["Total", f"{sum(len_by.values()):,.1f}", f"{sum(cost_by.values()):,.0f}"])
    t = Table(bt, colWidths=[80 * mm, 35 * mm, 40 * mm]); t.setStyle(ts); S.append(t)
    S.append(Paragraph("Each move's length is split equally between its two end cells; its cost is split in proportion to the "
                       "two cells' unit rates.", body))
    gt = [["Grade band (abs)", "0-3 %", "3-6 %", "6-8 %", "8-10 %"], ["Length (m)"] + [f"{v:,.1f}" for v in band_len]]
    t = Table(gt, colWidths=[45 * mm] + [28 * mm] * 4); t.setStyle(ts); S.append(Spacer(1, 4)); S.append(t)
    S.append(PageBreak())
    S.append(Paragraph("5. Options and checks", h2))
    S.append(Paragraph(
        "<b>Crossing X-1 is not feasible.</b> The only land between wetland W-1 and Cedar Branch at X-1 is one 20 m land-cover "
        "column, and all of it lies within the 30 m wetland setback. X-1 cannot be reached from the west bank, and with X-2 "
        "removed the search finds no compliant route. The northern end of the farm track (towards the farmstead) and the 2025 "
        "indicative route through X-1 and HS-1 are therefore not viable. The adopted route uses the southern 0.88 km of the "
        "track and then leaves it towards X-2. <b>Cedar Bluff Ridge saddle:</b> the lowest pass over the ridge lies inside the "
        "HS-1 150 m exclusion. Without the exclusion the least-cost route would take the saddle (run below). With it, the "
        "adopted route climbs round the north end of the ridge. The runs below were made only as sensitivity checks; each "
        "breaks a stated constraint and none is an option.", body))
    vt = [["Run", "Cost (USD)", "Length (m)", "Crossing"]] + var_rows
    t = Table(vt, colWidths=[95 * mm, 35 * mm, 30 * mm, 25 * mm]); t.setStyle(ts); S.append(Spacer(1, 4)); S.append(t)
    S.append(Spacer(1, 6))
    S.append(Paragraph("6. Compliance", h2))
    for p in [
        f"No vertex lies in a prohibited, setback or HS-1 cell; the only watercourse cells used are within 30 m of X-2. "
        f"Every move is at or below 10.0 % (maximum {np.abs(g).max():.2f} %).",
        "Limitations: the centreline is a 10 m raster least-cost path, i.e. a corridor for alignment design, not a geometric "
        "design. Curvature, sight distance, earthworks balance and culvert hydraulics are not assessed. In flat, uniform-cost "
        "ground several paths tie on cost; tie-break and foot-definition checks gave the same cost and length, with paths no "
        "more than 10 m from this one.",
        "Deliverables: CB_HaulRoad_Centreline.gpkg (layer 'centreline', one LineString, EPSG:32614), "
        "CB_HaulRoad_Vertices.csv (one row per vertex, start to end), this report.",
    ]:
        S.append(Paragraph(p, body)); S.append(Spacer(1, 3))
    doc.build(S)


if __name__ == "__main__":
    main()
