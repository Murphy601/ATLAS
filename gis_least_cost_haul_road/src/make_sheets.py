"""Render drawing sheets C-001 to C-004 (Rev D) as raster images and embed them in an image-only PDF."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrow
import numpy as np
from PIL import Image
from pyproj import Transformer
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas

import sitedef as S

ROOT = Path(__file__).resolve().parent.parent
B = json.loads((ROOT / "work" / "brief_values.json").read_text())
DPI = 200
W_IN, H_IN = 17.0, 11.0
TITLE = "CEDAR BLUFF AGGREGATES LLC  -  QUARRY HAUL ROAD ROUTE STUDY"


def title_block(fig, sheet, name):
    ax = fig.add_axes([0.80, 0.02, 0.185, 0.96])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, fill=False, lw=2))
    y = 0.97
    def line(txt, size=11, weight="normal", dy=0.03):
        nonlocal y
        ax.text(0.05, y, txt, fontsize=size, weight=weight, va="top", family="DejaVu Sans")
        y -= dy
    line("CLIENT", 8, "bold", 0.02); line("Cedar Bluff Aggregates LLC", 11, dy=0.045)
    line("PROJECT", 8, "bold", 0.02); line("Quarry Haul Road", 11, dy=0.025)
    line("Route Optioneering Study", 11, dy=0.045)
    line("DRAWING", 8, "bold", 0.02)
    for t in name:
        line(t, 12, "bold", 0.028)
    y -= 0.02
    line("REVISIONS", 8, "bold", 0.025)
    line("A  2026-08-03  Issued for route study", 8.5, dy=0.02)
    line("B  2026-09-14  Woodland clearing rate", 8.5, dy=0.016)
    line("                   revised (C-002 Table 2)", 8.5, dy=0.02)
    line("C  2026-09-24  Plant gate G1 relocated;", 8.5, dy=0.016)
    line("                   haul truck criteria and", 8.5, dy=0.016)
    line("                   typical section (C-003)", 8.5, dy=0.02)
    line("D  2026-09-26  G1 re-surveyed; loaded", 8.5, dy=0.016)
    line("                   haul, curve geometry and", 8.5, dy=0.016)
    line("                   life-cycle cost basis", 8.5, dy=0.016)
    line("                   added (Sheet C-004)", 8.5, dy=0.024)
    line("Rev D supersedes Rev C in full.", 9, "bold", 0.035)
    line("Horizontal: WGS 84 / UTM zone 14N", 9, dy=0.02)
    line("(EPSG:32614), metres", 9, dy=0.025)
    line("Vertical: NAVD 88, US survey feet", 9, dy=0.04)
    line("NOT FOR CONSTRUCTION", 12, "bold", 0.06)
    ax.plot([0, 1], [0.16, 0.16], "k", lw=1)
    ax.text(0.05, 0.14, "SHEET", fontsize=8, weight="bold", va="top")
    ax.text(0.05, 0.11, sheet, fontsize=30, weight="bold", va="top")
    ax.text(0.62, 0.14, "REV", fontsize=8, weight="bold", va="top")
    ax.text(0.62, 0.11, "D", fontsize=30, weight="bold", va="top")
    ax.text(0.05, 0.035, "Drawn: R.O.  Checked: J.M.  Date: 2026-09-26", fontsize=8)


def hillshade(z, cell, az=315, alt=45):
    gy, gx = np.gradient(z, cell)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azr, altr = np.radians(az), np.radians(alt)
    hs = np.sin(altr) * np.cos(slope) + np.cos(altr) * np.sin(slope) * np.cos(azr - aspect)
    return np.clip(hs, 0, 1)


def sheet1(path):
    dn = np.array(Image.open(ROOT / "inputs" / B["dem_file"]), float)
    zft = B["dn_base_ft"] + B["dn_step_ft"] * dn
    lc = np.array(Image.open(ROOT / "inputs" / B["lc_file"]).convert("RGB"))
    fig = plt.figure(figsize=(W_IN, H_IN), dpi=DPI)
    fig.patch.set_facecolor("white")
    fig.add_artist(Rectangle((0.005, 0.005), 0.99, 0.99, fill=False, lw=2.5, transform=fig.transFigure))
    ax = fig.add_axes([0.05, 0.08, 0.72, 0.86])
    ext_dem = [B["dem_ul_e"], B["dem_ul_e"] + 3600, B["dem_ul_n"] - 2800, B["dem_ul_n"]]
    ext_lc = [B["lc_ul_e"], B["lc_ul_e"] + 20 * lc.shape[1], B["lc_ul_n"] - 20 * lc.shape[0], B["lc_ul_n"]]
    hs = hillshade(zft * S.FT_US, 10.0)
    ax.imshow(lc, extent=ext_lc, origin="upper", interpolation="nearest")
    ax.imshow(hs, extent=ext_dem, origin="upper", cmap="gray", alpha=0.35, vmin=0, vmax=1)
    ex = B["dem_ul_e"] + 10 * (np.arange(dn.shape[1]) + 0.5)
    ey = B["dem_ul_n"] - 10 * (np.arange(dn.shape[0]) + 0.5)
    cs = ax.contour(ex, ey, zft, levels=np.arange(1200, 1700, 10), colors="#3a2a1a", linewidths=0.35)
    maj = [l for l in cs.levels if l % 50 == 0]
    ax.contour(ex, ey, zft, levels=maj, colors="#3a2a1a", linewidths=0.9)
    ax.clabel(ax.contour(ex, ey, zft, levels=maj, colors="none"), fmt="%d", fontsize=7)

    to_utm = Transformer.from_crs(4326, B["epsg"], always_xy=True)
    P = {k: to_utm.transform(v[1], v[0]) for k, v in B["points_latlon"].items()}
    P["END"] = P.pop("END_REVC")
    # indicative 2025 desk-study route (superseded)
    ind = [P["START"], (583420, 3349390), (583760, 3349700), (583980, 3350260), (584060, 3350600),
           (584180, 3350760), P["X1"], (584700, 3350700), (585250, 3350505), (585900, 3350505),
           (586150, 3350400), P["END"]]
    ind = np.array(ind)
    ax.plot(ind[:, 0], ind[:, 1], ls=(0, (6, 4)), color="#7a1fa2", lw=1.6)
    ax.annotate("INDICATIVE ROUTE - 2025 DESK STUDY\n(SUPERSEDED, NOT VERIFIED - SEE NOTE 7)",
                (584700, 3350850), (584750, 3351300), fontsize=8, color="#7a1fa2", weight="bold",
                arrowprops=dict(arrowstyle="->", color="#7a1fa2"))
    # county road
    ax.plot([583000, 583000], [3348700, 3351500], color="k", lw=4, solid_capstyle="butt")
    ax.text(583030, 3348760, "COUNTY ROAD CR-114 (EXISTING PAVED)", rotation=90, fontsize=8, weight="bold", va="bottom")
    sym = dict(START=("s", "TIE-IN T1\n(CR-114)"), END=("s", "QUARRY PLANT\nGATE G1 (SEE C-004)"),
               X1=("D", "APPROVED CROSSING\nWINDOW X-1"), X2=("D", "APPROVED CROSSING\nWINDOW X-2"),
               HERITAGE=("*", "HERITAGE SITE HS-1\n(SYMBOL NOT TO SCALE)"))
    offs = dict(START=(40, 60), END=(-420, 90), X1=(60, 40), X2=(60, -120), HERITAGE=(60, -140))
    for k, (m, lab) in sym.items():
        ax.plot(*P[k], marker=m, ms=11 if m != "*" else 18, mfc="yellow" if k != "HERITAGE" else "red",
                mec="k", mew=1.2, ls="none", zorder=5)
        ax.annotate(lab, P[k], (P[k][0] + offs[k][0], P[k][1] + offs[k][1]), fontsize=8, weight="bold",
                    bbox=dict(fc="white", ec="k", lw=0.6, alpha=0.85), zorder=6)
    ax.text(584420, 3348780, "CEDAR BRANCH\n(PERENNIAL)", color="#1b4fa0", fontsize=9, weight="bold", rotation=80)
    ax.text(583950, 3351250, "FARMSTEAD", fontsize=8, weight="bold", color="#8a1010")
    ax.text(584120, 3350330, "WETLAND W-1", fontsize=8, weight="bold", color="#135c6b")
    ax.text(583300, 3349330, "EXISTING GRAVEL\nFARM TRACK", fontsize=8, weight="bold", color="#5a2d10", rotation=40)
    ax.text(585950, 3349050, "CEDAR BLUFF\nESCARPMENT", fontsize=9, weight="bold", color="#40342a")
    ax.set_xlim(582880, 586720); ax.set_ylim(3348600, 3351640)
    ax.set_aspect("equal")
    xt = np.arange(583000, 586700, 500); yt = np.arange(3348700, 3351600, 500)
    ax.set_xticks(xt); ax.set_xticklabels([f"E {v:,.0f}" for v in xt], fontsize=7)
    ax.set_yticks(yt); ax.set_yticklabels([f"N {v:,.0f}" for v in yt], fontsize=7)
    ax.grid(True, color="k", lw=0.25, alpha=0.4)
    # north arrow + scale bar
    ax.add_patch(FancyArrow(586560, 3351300, 0, 230, width=25, head_width=90, head_length=110, color="k"))
    ax.text(586560, 3351230, "N", ha="center", va="top", fontsize=14, weight="bold")
    for i in range(5):
        ax.add_patch(Rectangle((585700 + i * 100, 3348680), 100, 30, fc="k" if i % 2 == 0 else "w", ec="k"))
    ax.text(585700, 3348725, "0", fontsize=7); ax.text(586180, 3348725, "500 m", fontsize=7)
    ax.set_title("SITE CONSTRAINTS PLAN  -  PRESENTATION ONLY, DO NOT SCALE (SEE C-002 NOTE 1)", fontsize=13, weight="bold", loc="left")
    # legend
    lx = fig.add_axes([0.05, 0.005, 0.72, 0.065]); lx.axis("off"); lx.set_xlim(0, 1); lx.set_ylim(0, 1)
    items = [(B["classes"][c]["name"], np.array(B["classes"][c]["rgb"]) / 255) for c in sorted(B["classes"])]
    for n, (lab, col) in enumerate(items):
        x = 0.01 + (n % 4) * 0.25; y = 0.66 - (n // 4) * 0.36
        lx.add_patch(Rectangle((x, y), 0.03, 0.26, fc=col, ec="k"))
        lx.text(x + 0.035, y + 0.13, lab, va="center", fontsize=8)
    lx.text(0.01, 0.08, "Contours from CB-DEM-10m, 10 ft interval (50 ft index), NAVD 88 US survey feet.  "
            "Land-cover colours as C-002 Table 2.", fontsize=7.5)
    title_block(fig, "C-001", ["SITE CONSTRAINTS", "PLAN"])
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def table(ax, x, y, cols, rows, widths, size=9.5, rh=0.0255, head_fc="#d9d9d9"):
    xs = np.concatenate([[0], np.cumsum(widths)]) + x
    for c, t in enumerate(cols):
        ax.add_patch(Rectangle((xs[c], y - rh), widths[c], rh, fc=head_fc, ec="k", lw=0.8))
        ax.text(xs[c] + 0.004, y - rh / 2, t, va="center", fontsize=size, weight="bold")
    for r, row in enumerate(rows):
        yy = y - rh * (r + 2)
        for c, t in enumerate(row):
            ax.add_patch(Rectangle((xs[c], yy), widths[c], rh, fc="white", ec="k", lw=0.6))
            ax.text(xs[c] + 0.004, yy + rh / 2, t, va="center", fontsize=size)
    return y - rh * (len(rows) + 1)


def sheet2(path):
    fig = plt.figure(figsize=(W_IN, H_IN), dpi=DPI)
    fig.add_artist(Rectangle((0.005, 0.005), 0.99, 0.99, fill=False, lw=2.5, transform=fig.transFigure))
    ax = fig.add_axes([0.02, 0.02, 0.77, 0.96]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.text(0.0, 0.985, "DATA REGISTER, UNIT RATES AND ROUTING CONSTRAINTS", fontsize=15, weight="bold", va="top")
    ax.text(0.0, 0.945, "TABLE 1 - RASTER DATA REGISTER (issued with this drawing)", fontsize=11, weight="bold", va="top")
    y = table(ax, 0.0, 0.93, ["Item", "CB-DEM-10m_heightmap_uint16.png", "CB-LC-20m_landcover.png"], [
        ["Content", "Bare-earth terrain model (LiDAR 2026-03)", "Land-cover classification (field verified 2026-07)"],
        ["Raster size", "360 columns x 280 rows, 1 band", "190 columns x 150 rows, 3 bands"],
        ["Pixel type", "16-bit unsigned integer (DN)", "8-bit RGB, classes per Table 2"],
        ["CRS", "WGS 84 / UTM zone 14N (EPSG:32614)", "WGS 84 / UTM zone 14N (EPSG:32614)"],
        ["UL corner of UL pixel", "E 583 000.00 m   N 3 351 500.00 m", "E 582 900.00 m   N 3 351 620.00 m"],
        ["Pixel size", "10.00 m x 10.00 m (square)", "20.00 m x 20.00 m (square)"],
        ["Row / column order", "Row 1 = north edge, column 1 = west edge", "Row 1 = north edge, column 1 = west edge"],
        ["Value", "Elevation = 1150.00 + 0.01 x DN  (US survey feet, NAVD 88)", "Exact RGB triplet = class (no anti-aliasing)"],
    ], [0.15, 0.40, 0.40], size=9)

    ax.text(0.0, y - 0.012, "TABLE 2 - LAND-COVER CLASSES AND BASE UNIT RATES (REV B, UNCHANGED AT REV C AND REV D)", fontsize=11, weight="bold", va="top")
    rows = []
    for c in sorted(B["classes"]):
        info = B["classes"][c]
        r, g, b = info["rgb"]
        if info["cost"] is None:
            rate = "PROHIBITED" if info["name"] != "Watercourse" else "PROHIBITED (Note 3)"
        elif info["name"] == "Woodland":
            rate = "940   (Rev B;  Rev A value 690 withdrawn)"
        else:
            rate = f"{info['cost']:,.0f}"
        rows.append([c, info["name"], f"({r}, {g}, {b})", rate])
    rows.append(["-", "Culvert at approved crossing window", "-", f"{B['culvert_cost']:,.0f}  (Note 3)"])
    y = table(ax, 0.0, y - 0.027, ["Code", "Class", "RGB", "Base unit rate  c  (USD per metre of road)"], rows,
              [0.06, 0.29, 0.13, 0.47], size=9)

    ax.text(0.0, y - 0.012, "TABLE 3 - CONTROL POINTS (WGS 84 geographic, decimal degrees)", fontsize=11, weight="bold", va="top")
    lab = dict(START="T1  Tie-in to CR-114 (route start)",
               END_REVC="G1  Quarry plant gate (route end) - REV C VALUE, SUPERSEDED: SEE C-004 TABLE 6",
               X1="X-1  Approved crossing window centre", X2="X-2  Approved crossing window centre",
               HERITAGE="HS-1  Heritage site (recorded point)")
    order = ["START", "END_REVC", "X1", "X2", "HERITAGE"]
    rows = [[lab[k], f"{B['points_latlon'][k][0]:.7f}", f"{B['points_latlon'][k][1]:.7f}"] for k in order]
    y = table(ax, 0.0, y - 0.027, ["Point", "Latitude", "Longitude"], rows, [0.55, 0.15, 0.15], size=9)

    notes = [
        "NOTES",
        "1. The two rasters in Table 1 govern. Sheet C-001 is a presentation plot of them and is not to be scaled or digitised.",
        "2. Route start and end are the DEM cells containing control points T1 and G1.",
        "3. Watercourse cells may be traversed only at approved crossing windows X-1 and X-2: a watercourse cell is passable where",
        "    its DEM cell centre lies within 30.0 m of a window centre, and is then costed at the culvert rate. All other watercourse cells are prohibited.",
        "4. Wetland W-1: wetland cells are prohibited and no part of the road may lie within 30.0 m of the mapped wetland boundary.",
        "5. Heritage site HS-1: exclusion zone of radius 150.0 m about the recorded point (Texas Historical Commission consultation, 2026).",
        "6. Maximum grade 10.0 percent for loaded 40 t haul trucks, in either direction of travel.",
        "7. The indicative route on C-001 is from a 2025 desk study that pre-dates the LiDAR, the land-cover survey and Notes 3 to 5.",
        "8. Haul truck criteria: Sheets C-003 and C-004. Precedence where sheets differ: C-004, then C-003, then this sheet.",
    ]
    yy = y - 0.02
    for i, t in enumerate(notes):
        ax.text(0.0, yy, t, fontsize=9.5 if i else 11, weight="bold" if i == 0 else "normal", va="top")
        yy -= 0.023
    title_block(fig, "C-002", ["DATA REGISTER,", "UNIT RATES AND", "CONSTRAINTS"])
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def dim(ax, x0, x1, y, txt, size=9):
    ax.annotate("", (x0, y), (x1, y), arrowprops=dict(arrowstyle="<|-|>", lw=0.8, color="k", shrinkA=0, shrinkB=0))
    ax.text((x0 + x1) / 2, y + 0.12, txt, ha="center", va="bottom", fontsize=size)


def sheet3(path):
    fig = plt.figure(figsize=(W_IN, H_IN), dpi=DPI)
    fig.add_artist(Rectangle((0.005, 0.005), 0.99, 0.99, fill=False, lw=2.5, transform=fig.transFigure))
    ax0 = fig.add_axes([0.02, 0.02, 0.77, 0.96]); ax0.axis("off"); ax0.set_xlim(0, 1); ax0.set_ylim(0, 1)
    ax0.text(0.0, 0.985, "HAUL ROAD TYPICAL SECTION AND HAUL TRUCK OPERATING CRITERIA", fontsize=15, weight="bold", va="top")
    ax0.text(0.0, 0.945, "TYPICAL SECTION A-A  (TANGENT, CUT/FILL NOT SHOWN)   SCALE 1:100 AT A3 - DO NOT SCALE FROM THIS PLOT",
             fontsize=11, weight="bold", va="top")

    ax = fig.add_axes([0.04, 0.50, 0.73, 0.40]); ax.axis("off")
    ax.set_xlim(-12, 12); ax.set_ylim(-3.2, 4.2)
    # ground and formation
    ax.fill_between([-12, 12], -3.2, -1.2, color="#d8c7a8", zorder=0)
    ax.plot([-12, -10, 10, 12], [-1.2, -1.2, -1.2, -1.2], color="#6b5a3a", lw=1)
    xs = [-7, -6, -5, 5, 6, 7]
    ax.fill([-7, -7, -6.4, -6, -6], [-1.2, -0.2, 0.25, 0.25, -1.2], color="#9c8f7a", ec="k", lw=0.8)   # berm
    ax.fill([7, 7, 6.4, 6, 6], [-1.2, -0.2, 0.25, 0.25, -1.2], color="#9c8f7a", ec="k", lw=0.8)
    ax.fill([-6, -5, -5, -6], [-1.2, -1.2, -0.05, -0.1], color="#c9bda3", ec="k", lw=0.8)                 # shoulder
    ax.fill([6, 5, 5, 6], [-1.2, -1.2, -0.05, -0.1], color="#c9bda3", ec="k", lw=0.8)
    ax.fill([-5, 0, 5, 5, -5], [-0.05, 0.0, -0.05, -1.2, -1.2], color="#8a8a8a", ec="k", lw=0.8)          # running surface
    ax.plot([0, 0], [-1.6, 3.9], color="k", lw=0.8, ls=(0, (8, 3, 2, 3)))
    ax.text(0, 3.95, "CL  (route centreline =\nDEM cell centres, C-002 Note 2)", ha="center", va="bottom", fontsize=9)
    for x in (-7, -6, -5, 5, 6, 7):
        ax.plot([x, x], [0.35, 2.55], color="k", lw=0.5)
    y = 1.1
    dim(ax, -7, -6, y, "1.00"); dim(ax, -6, -5, y, "1.00"); dim(ax, -5, 5, y, "10.00")
    dim(ax, 5, 6, y, "1.00"); dim(ax, 6, 7, y, "1.00")
    ax.text(-6.5, 2.0, "SAFETY\nBERM", ha="center", fontsize=8.5, weight="bold")
    ax.text(-5.5, 2.0, "SHLDR", ha="center", fontsize=8.5, weight="bold")
    ax.text(0, 2.0, "RUNNING SURFACE (2 LANES, 150 mm CRUSHED LIMESTONE)", ha="center", fontsize=8.5, weight="bold")
    ax.text(5.5, 2.0, "SHLDR", ha="center", fontsize=8.5, weight="bold")
    ax.text(6.5, 2.0, "SAFETY\nBERM", ha="center", fontsize=8.5, weight="bold")
    ax.text(-7.1, -0.2, "FORMATION\nEDGE", ha="right", va="center", fontsize=8.5, weight="bold")
    ax.text(7.1, -0.2, "FORMATION\nEDGE", ha="left", va="center", fontsize=8.5, weight="bold")
    ax.annotate("CLEARING LIMIT 3.0 m BEYOND FORMATION EDGE\n(CLEARING QUANTITIES ONLY - SEE NOTE C3)",
                (-10, -1.2), (-11.8, -2.9), fontsize=8, arrowprops=dict(arrowstyle="->"))
    ax.plot([-10, -10], [-1.2, -0.6], color="#2a6a2a", lw=1.2, ls="--")
    ax.plot([10, 10], [-1.2, -0.6], color="#2a6a2a", lw=1.2, ls="--")
    ax.text(2.2, -0.55, "3.0 % CROSSFALL", fontsize=8)
    ax.text(6.5, 0.6, "1.2 m", fontsize=7.5, ha="center")
    ax.text(8.2, -2.7, "DIMENSIONS IN METRES", fontsize=8, style="italic")

    y = 0.46
    ax0.text(0.0, y, "TABLE 4 - HAUL TRUCK OPERATING CRITERIA (40 t ARTICULATED HAUL TRUCK, LOADED)", fontsize=11, weight="bold", va="top")
    y = table(ax0, 0.0, y - 0.017, ["Ref", "Criterion", "Value", "Application to the route study"], [
        ["T1", "Maximum grade, either direction", "10.0 %", "Every move; as C-002 Note 6"],
        ["T2", "Sustained steep grade", "> 8.0 %", "A move steeper than 8.0 % is a steep move"],
        ["T3", "Maximum continuous run of steep moves", "60.0 m", "Horizontal length; any move at 8.0 % or flatter ends the run"],
        ["T4", "Maximum change of direction between", "45 deg", "Measured between consecutive grid moves; the first move"],
        ["", "   consecutive moves", "", "   from the start cell is unrestricted"],
        ["T5", "Design speed (loaded)", "40 km/h", "Information only"],
        ["T6", "Rated payload / gross vehicle mass", "40 t / 72 t", "Information only"],
    ], [0.04, 0.29, 0.09, 0.53], size=9)
    notes = [
        "NOTES",
        "C1. 'The road' in C-002 Notes 4 and 5 means the full formation shown in Section A-A. Wetland setback and heritage exclusion are",
        "      measured to the formation edge on either side of the centreline, along every straight move between cell centres.",
        "C2. The crossing-window test of C-002 Note 3 is applied to centreline cell centres only.",
        "C3. The clearing limit and batters are for quantities only and are not routing constraints.",
        "C4. Criteria T1 to T4 apply together. Unit rates (C-002 Table 2) and the grade factor are unchanged by this sheet.",
    ]
    yy = y - 0.025
    for i, t in enumerate(notes):
        ax0.text(0.0, yy, t, fontsize=9.5 if i else 11, weight="bold" if i == 0 else "normal", va="top")
        yy -= 0.022
    title_block(fig, "C-003", ["TYPICAL SECTION", "AND HAUL TRUCK", "CRITERIA"])
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def sheet4(path):
    fig = plt.figure(figsize=(W_IN, H_IN), dpi=DPI)
    fig.add_artist(Rectangle((0.005, 0.005), 0.99, 0.99, fill=False, lw=2.5, transform=fig.transFigure))
    ax0 = fig.add_axes([0.02, 0.02, 0.77, 0.96]); ax0.axis("off"); ax0.set_xlim(0, 1); ax0.set_ylim(0, 1)
    ax0.text(0.0, 0.985, "LOADED HAUL, ROUTE GEOMETRY AND LIFE-CYCLE COST BASIS  (REV D)", fontsize=15, weight="bold", va="top")
    ax0.text(0.0, 0.948, "TABLE 5 - ADDITIONAL ROUTE SCREENING CRITERIA (APPLY WITH C-003 TABLE 4)", fontsize=11, weight="bold", va="top")
    y = table(ax0, 0.0, 0.933, ["Ref", "Criterion", "Value", "Definition / application"], [
        ["D1", "Direction of loaded travel", "G1 to T1", "Product leaves the plant gate loaded and is hauled to CR-114; trucks return empty"],
        ["D2", "Rolling resistance, running surface", "3.0 %", "Section A-A crushed limestone surface - applies to every move of the route"],
        ["D3", "Max. effective grade, loaded uphill", "9.0 %", "Effective grade = grade resistance + rolling resistance, loaded direction (D1)"],
        ["D4", "Max. grade, loaded downhill / empty", "T1", "C-003 Table 4 T1 (10.0 %) - unchanged"],
        ["D5", "Min. rate of vertical curvature  K", "1.4 m/%", "K = L / A  (m per 1 % grade change) for every pair of consecutive moves; A = algebraic"],
        ["", "", "", "   difference of the two grades (%); L = distance along the centreline between the two move midpoints"],
        ["D6", "Min. horizontal curve radius  R", "45.0 m", "A circular arc of radius R is fitted at every deflection vertex, tangent to both moves;"],
        ["", "", "", "   arcs may not overlap and may not extend past the start or end cell centre (Note D3)"],
        ["D7", "Loaded haulage cost (PV, 20-year life)", f"{B['haul_rise_cost']:,.0f} /m", "USD per metre of vertical rise climbed by loaded trucks (D1), charged only on moves whose"],
        ["", "", "", f"   effective grade (as D3) exceeds {B['haul_eff_threshold']:.1f} % (top-gear range); falls are not credited"],
    ], [0.04, 0.26, 0.09, 0.56], size=9)
    y -= 0.012
    ax0.text(0.0, y, "TABLE 6 - CONTROL POINT G1, RE-SURVEYED 2026-09-25 (SUPERSEDES C-002 TABLE 3 ROW G1)", fontsize=11, weight="bold", va="top")
    e_ft, n_ft = B["g1_surface_ftus"]
    y = table(ax0, 0.0, y - 0.015, ["Point", "CRS / coordinate type", "Easting", "Northing"], [
        ["G1  Quarry plant gate (route end)", "NAD83 / Texas Central (ftUS), EPSG:2277 - TxDOT SURFACE", f"{e_ft:,.2f} ft", f"{n_ft:,.2f} ft"],
        ["", f"Surface adjustment factor SAF = {B['g1_saf']:.5f}, scaled about grid origin (0, 0): grid = surface / SAF", "", ""],
    ], [0.22, 0.47, 0.11, 0.11], size=9)
    y -= 0.012
    ax0.text(0.0, y, "TABLE 7 - REFERENCE VALUES (INFORMATION ONLY - NOT ROUTE CRITERIA)", fontsize=11, weight="bold", va="top")
    y = table(ax0, 0.0, y - 0.015, ["Item", "Value", "Source"], [
        ["Rolling resistance, in-pit ramps (not this road)", "2.0 %", "Mine plan 2025"],
        ["Rolling resistance, unsurfaced haul road (not permitted)", "6.0 %", "Mine plan 2025"],
        ["Haul truck minimum turning radius (outer front wheel)", "8.9 m", "Manufacturer data"],
        ["Haulage cost per metre of fall, loaded (brake wear, info)", "450 USD", "Operator estimate - not in life-cycle basis"],
        ["Top-gear effective grade limit, empty truck", "6.0 %", "Manufacturer data"],
    ], [0.44, 0.09, 0.28], size=9)
    notes = [
        "NOTES",
        "D1. The route to be selected minimises the TOTAL route cost = construction cost (C-002 Table 2 rates x grade factor, unchanged)",
        "       + loaded haulage cost (Table 5 D7). Report both components and the total.",
        "D2. Grades on long sections and in vertex schedules are signed in the direction of increasing chainage (T1 to G1). Criteria D3 and D7",
        "       are defined in the loaded direction (D1), which is opposite to increasing chainage.",
        "D3. A deflection vertex is an interior route vertex at which the direction of travel changes; on the 10 m grid each deflection is 45 deg",
        "       (C-003 T4). The start and end cell centres are not deflection vertices. The arcs are a screening check only: costs, grades and",
        "       clearances stay on the straight moves between cell centres.",
        "D4. D5 applies to every pair of consecutive moves, including pairs meeting at a deflection vertex. It does not apply before the first move.",
        "D5. Table 6 replaces the G1 latitude/longitude on C-002. C-001 still shows G1 at its Rev C position (presentation only).",
        "D6. Where this sheet differs from C-002 or C-003 this sheet governs. C-003 Table 4 T1 to T4 remain in force.",
    ]
    yy = y - 0.022
    for i, t in enumerate(notes):
        ax0.text(0.0, yy, t, fontsize=9.5 if i else 11, weight="bold" if i == 0 else "normal", va="top")
        yy -= 0.021
    title_block(fig, "C-004", ["LOADED HAUL,", "GEOMETRY AND", "COST BASIS"])
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def main():
    w = ROOT / "work"
    ps = [w / f"C-00{k}.png" for k in (1, 2, 3, 4)]
    sheet1(ps[0]); sheet2(ps[1]); sheet3(ps[2]); sheet4(ps[3])
    for old in (ROOT / "inputs").glob("CB-HR-*.pdf"):
        old.unlink()
    out = ROOT / "inputs" / "CB-HR-C001-C004_RevD.pdf"
    c = canvas.Canvas(str(out), pagesize=landscape((11 * 72, 17 * 72)))
    for p in ps:
        c.drawImage(str(p), 0, 0, width=17 * 72, height=11 * 72)
        c.showPage()
    c.save()
    print("wrote", out)


if __name__ == "__main__":
    main()
