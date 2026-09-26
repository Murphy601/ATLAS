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
    chk = SV.check_path(res)
    clr = SV.clearances(res)
    assert chk["max_grade"] <= b["max_grade"] and chk["max_turn_deg"] <= b["max_deflection_deg"]
    assert chk["max_steep_run"] <= b["steep_run_max"] + 1e-9
    half = b["formation_width"] / 2
    assert clr["wetland_m"] - half >= b["wetland_setback"] and clr["heritage_m"] - half >= b["heritage_radius"]

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
             max_grade_pct=[round(float(np.abs(g).max()), 3)], crossing=[SV.xing(rows)]),
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
        ("Adopted route (all C-002 and C-003 criteria)", {}),
        ("Check: centreline only (14.0 m formation ignored)", {"no_width": True}),
        ("Check: 45 deg direction-change limit (T4) ignored", {"no_turn": True}),
        ("Check: 60 m sustained-grade limit (T3) ignored", {"no_sustain": True}),
        ("Check: C-003 ignored entirely (Rev B rules only)", {"no_width": True, "no_turn": True, "no_sustain": True}),
        ("Check: without HS-1 exclusion", {"no_heritage": True}),
        ("Check: without 30 m wetland setback", {"no_setback": True}),
    ]
    var_rows = []
    for name, o in variants:
        rr = SV.solve(o)
        rws, LL = SV.summarise(rr)
        cp = SV.check_path(rr)
        var_rows.append([name, f"{rr['cost']:,.0f}", f"{LL:,.1f}", SV.xing(rws),
                         f"{cp['max_turn_deg']:.0f}", f"{cp['max_steep_run']:.1f}"])
    only_x1 = SV.solve({"drop_X2": True})
    assert only_x1 is None

    figs = plan_and_profile(res, rows)
    write_pdf(rows, L, cost, g, len_by, cost_by, band_len, var_rows, figs, chk, clr, res["pts"])
    summary = dict(cost_usd=cost, length_m=L, n_vertices=len(rows), max_grade_pct=float(np.abs(g).max()),
                   max_turn_deg=chk["max_turn_deg"], max_steep_run_m=float(chk["max_steep_run"]),
                   wetland_clear_m=clr["wetland_m"], heritage_clear_m=clr["heritage_m"],
                   crossing=SV.xing(rows), n_max=max(r["northing"] for r in rows),
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
    for a, c in zip(rows[:-1], rows[1:]):
        if abs(a["grade_pct"]) > b["steep_grade"]:
            ax.axvspan(a["chainage_m"], c["chainage_m"], color="orange", alpha=0.5, lw=0)
    ax.plot([], [], color="orange", lw=6, alpha=0.5, label="moves steeper than 8.0 % (each run <= 60.0 m)")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_xlabel("Chainage (m)"); ax.set_ylabel("Elevation (m, NAVD 88)"); ax.grid(alpha=0.4)
    ax.set_title("Long section along adopted centreline (terrain at DEM cell centres)")
    fig.tight_layout(); f2 = WORK / "golden_profile.png"; fig.savefig(f2, dpi=170); plt.close(fig)
    return f1, f2


def write_pdf(rows, L, cost, g, len_by, cost_by, band_len, var_rows, figs, chk, clr, pts):
    b = SV.BRIEF
    half = b["formation_width"] / 2
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
    S.append(Paragraph("Basis: drawing set CB-HR C-001 to C-003 Rev C and the two rasters it registers. "
                       "Horizontal CRS WGS 84 / UTM zone 14N (EPSG:32614); lengths are horizontal. "
                       "Status: route study only, not for construction.", body))
    S.append(Spacer(1, 4))
    S.append(Paragraph("1. Result", h2))
    x2 = [r for r in rows if r["landcover"] == "Watercourse"]
    top = max(rows, key=lambda r: r["northing"])
    res_tab = [
        ["Quantity", "Value"],
        ["Total accumulated route cost (USD)", f"{cost:,.2f}"],
        ["Horizontal length, start cell centre to end cell centre (m)", f"{L:,.2f}"],
        ["Vertices (DEM cell centres) / moves", f"{len(rows)} / {len(rows) - 1}"],
        ["Start cell centre (T1 on CR-114)", f"E {rows[0]['easting']:.2f}  N {rows[0]['northing']:.2f}  z {rows[0]['elev_m']:.2f} m"],
        ["End cell centre (G1 quarry gate)", f"E {rows[-1]['easting']:.2f}  N {rows[-1]['northing']:.2f}  z {rows[-1]['elev_m']:.2f} m"],
        ["Creek crossing", f"Approved window {SV.xing(rows)}, culvert on {len(x2)} watercourse cells at N {x2[0]['northing']:.0f}"],
        ["Crossing through the other window (X-1)", "None compliant: no route exists through X-1 (Section 5)"],
        ["Maximum grade on any move (T1 limit 10.0 %)", f"{chk['max_grade']:.2f} %"],
        ["Longest continuous run of moves > 8.0 % (T3 limit 60.0 m)", f"{chk['max_steep_run']:.1f} m"],
        ["Largest change of direction between moves (T4 limit 45 deg)", f"{chk['max_turn_deg']:.0f} deg"],
        ["Escarpment ascent", f"northern slump; route reaches N {top['northing']:.0f} at E {top['easting']:.0f}, "
                              f"then returns south along the plateau to G1"],
        ["Min. distance centreline to wetland W-1 boundary / formation edge",
         f"{clr['wetland_m']:.1f} m / {clr['wetland_m'] - half:.1f} m (limit 30.0 m)"],
        ["Min. distance centreline to HS-1 / formation edge", f"{clr['heritage_m']:.1f} m / {clr['heritage_m'] - half:.1f} m (limit 150.0 m)"],
    ]
    t = Table(res_tab, colWidths=[120 * mm, 140 * mm]); t.setStyle(ts); S.append(t)
    S.append(PageBreak())
    S.append(Paragraph("2. Method", h2))
    for p in [
        "<b>Terrain.</b> DEM DN converted with Elevation(ft) = 1150.00 + 0.01 x DN (C-002 Table 1), then to metres with the US "
        "survey foot (1200/3937 m). Grades use metres on both axes.",
        "<b>Georeferencing.</b> Both rasters are pixel-is-area with the registered upper-left corner. DEM cell centres are at "
        "E 583 005 + 10i, N 3 351 495 - 10j. The land-cover raster has its own origin (E 582 900, N 3 351 620) and 20 m pixels; "
        "each DEM cell takes the class of the land-cover pixel containing its centre (exact RGB match).",
        f"<b>Control points.</b> Table 3 WGS 84 lat/long converted to EPSG:32614 with PROJ. "
        f"T1 -> E {pts['START'][0]:,.2f}, N {pts['START'][1]:,.2f}; G1 (relocated at Rev C) -> E {pts['END'][0]:,.2f}, "
        f"N {pts['END'][1]:,.2f}; HS-1 -> E {pts['HERITAGE'][0]:,.2f}, N {pts['HERITAGE'][1]:,.2f}.",
        f"<b>Road footprint (C-003).</b> The road is the full formation of Section A-A: 1.00 + 1.00 + 10.00 + 1.00 + 1.00 = "
        f"{b['formation_width']:.2f} m, i.e. {half:.2f} m either side of the centreline. Per C-003 Note C1 the wetland setback and "
        f"HS-1 exclusion are measured to the formation edge along every straight move, so a move is allowed only if its centreline "
        f"segment stays more than {b['wetland_setback'] + half:.1f} m from every wetland pixel and more than "
        f"{b['heritage_radius'] + half:.1f} m from HS-1. The crossing-window test (Note 3) stays on cell centres (Note C2).",
        "<b>Haul truck criteria (C-003 Table 4).</b> T1: every move at most 10.0 %. T2/T3: a move steeper than 8.0 % is a steep "
        "move; consecutive steep moves may total at most 60.0 m horizontal; any move at 8.0 % or flatter resets the run. "
        "T4: direction may change by at most 45 deg between consecutive moves (the first move is free).",
        "<b>Search.</b> T3 and T4 depend on the path taken, so a cell-only Dijkstra cannot enforce them. The search runs on an "
        "expanded state (cell, arrival heading 1 of 8, steep run so far in 10 m steps); a move is expanded only if its heading "
        "is within one octant of the arrival heading and the updated run is within 60 m. A move of horizontal length d between "
        "cells i and j costs d x (c_i + c_j)/2 x f(g), g = |z_j - z_i| / d, with the brief's grade factor. The best of the "
        "arrival states at the G1 cell is taken.",
    ]:
        S.append(Paragraph(p, body)); S.append(Spacer(1, 3))
    rt = [["Item applied", "Value"],
          ["Grassland / pasture", "420 USD/m"], ["Cultivated cropland", "480 USD/m"],
          ["Woodland (Rev B; Rev A 690 withdrawn)", "940 USD/m"], ["Rock outcrop", "1,150 USD/m"],
          ["Existing gravel track", "160 USD/m"], ["Watercourse cell within 30.0 m of X-1 / X-2 centre (culvert)", "3,800 USD/m"],
          ["Watercourse elsewhere, wetland, farmstead", "prohibited"],
          ["Formation width (C-003 Section A-A)", f"{b['formation_width']:.1f} m ({half:.1f} m each side)"],
          ["Wetland W-1 setback, to formation edge", "30.0 m"],
          ["HS-1 exclusion radius, to formation edge", "150.0 m"],
          ["Maximum grade on any move (T1)", "10.0 %"],
          ["Steep-move threshold / max continuous steep run (T2, T3)", "> 8.0 % / 60.0 m"],
          ["Max change of direction between consecutive moves (T4)", "45 deg"],
          ["Grade factor f(g)", "1.00 (g<=3); 1.00+0.05(g-3) (3<g<=6); 1.15+0.12(g-6) (6<g<=10)"]]
    t = Table(rt, colWidths=[120 * mm, 140 * mm]); t.setStyle(ts)
    S.append(Paragraph("Rates and constraint values applied (C-002 Rev C, C-003 Rev C)", h2)); S.append(t)
    S.append(PageBreak())
    S.append(Paragraph("3. Plan and long section", h2))
    S.append(RLImage(str(figs[0]), width=190 * mm, height=141 * mm))
    S.append(PageBreak())
    S.append(RLImage(str(figs[1]), width=260 * mm, height=85 * mm))
    S.append(Paragraph("4. Breakdown", h2))
    order = ["Grassland / pasture", "Cultivated cropland", "Woodland", "Rock outcrop", "Existing gravel track", "Watercourse"]
    bt = [["Land-cover class", "Length (m)", "Cost (USD)"]]
    for k in order:
        if len_by.get(k, 0) > 0:
            bt.append([k if k != "Watercourse" else "Watercourse at X-2 (culvert)", f"{len_by[k]:,.1f}", f"{cost_by[k]:,.0f}"])
    bt.append(["Total", f"{sum(len_by.values()):,.1f}", f"{sum(cost_by.values()):,.0f}"])
    t = Table(bt, colWidths=[80 * mm, 35 * mm, 40 * mm]); t.setStyle(ts); S.append(t)
    S.append(Paragraph("Each move's length is split equally between its two end cells; its cost is split in proportion to the "
                       "two cells' unit rates.", body))
    gt = [["Grade band (abs)", "0-3 %", "3-6 %", "6-8 %", "8-10 %"], ["Length (m)"] + [f"{v:,.1f}" for v in band_len]]
    t = Table(gt, colWidths=[45 * mm] + [28 * mm] * 4); t.setStyle(ts); S.append(Spacer(1, 4)); S.append(t)
    S.append(PageBreak())
    S.append(Paragraph("5. What controls the alignment", h2))
    S.append(Paragraph(
        f"<b>Creek crossing - X-1 is not feasible.</b> At X-1 the eastern watercourse column is 35.0 m from the W-1 boundary. "
        f"A centreline there passes the 30 m setback, but the formation edge would be 35.0 - {half:.1f} = {35.0 - half:.1f} m "
        f"from the wetland. With X-2 removed the search finds no compliant route, so the only crossing is X-2. A centreline-only "
        f"model crosses at X-1 instead (run table below).", body))
    S.append(Spacer(1, 3))
    S.append(Paragraph(
        "<b>Cedar Bluff escarpment.</b> The escarpment between the creek lowland and the G1 plateau has four candidate ascents. "
        "(a) The saddle gap next to HS-1 is closed by the 150 m exclusion measured to the formation edge. "
        "(b) The spur crest facing G1 grades at about 9.2 % for over 600 m: every move is under 10 %, but it breaks T3 (60 m). "
        "(c) The chute to the south climbs steeper than 10 % on the fall line and needs 90 and 135 deg switchbacks, "
        "which breaks T4. (d) The northern slump is flatter and allows short steep runs broken by flatter moves. "
        "The adopted route uses (d): it follows the southern farm track, crosses at X-2, runs north across the lowland, climbs "
        "the slump and returns south along the plateau to G1. That detour is why it is longer and dearer than the routes that "
        "ignore C-003.", body))
    S.append(Spacer(1, 3))
    S.append(Paragraph("Sensitivity runs (each 'Check' breaks a stated criterion and is not an option):", body))
    vt = [["Run", "Cost (USD)", "Length (m)", "Crossing", "Max turn (deg)", "Max steep run (m)"]] + var_rows
    t = Table(vt, colWidths=[95 * mm, 30 * mm, 27 * mm, 20 * mm, 27 * mm, 32 * mm]); t.setStyle(ts)
    S.append(Spacer(1, 4)); S.append(t)
    S.append(Spacer(1, 6))
    S.append(Paragraph("6. Compliance and limitations", h2))
    for p in [
        f"Every move is at or below 10.0 % (max {chk['max_grade']:.2f} %); the longest run of moves over 8.0 % is "
        f"{chk['max_steep_run']:.1f} m; no change of direction exceeds {chk['max_turn_deg']:.0f} deg; the formation edge stays "
        f"{clr['wetland_m'] - half:.1f} m from W-1 and {clr['heritage_m'] - half:.1f} m from HS-1; the only watercourse cells "
        f"used are within 30 m of X-2.",
        "The centreline is a 10 m raster least-cost path: a corridor for alignment design, not a geometric design. Curve radii, "
        "sight distance, earthworks and culvert hydraulics are not assessed. Tie-break order, international versus US survey "
        "foot, and segment versus vertex clearance testing all give the same route (cost within 1 USD).",
        "Deliverables: CB_HaulRoad_Centreline.gpkg (layer 'centreline', one LineString, EPSG:32614), "
        "CB_HaulRoad_Vertices.csv (one row per vertex, start to end), this report.",
    ]:
        S.append(Paragraph(p, body)); S.append(Spacer(1, 3))
    doc.build(S)


if __name__ == "__main__":
    main()
