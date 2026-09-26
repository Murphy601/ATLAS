# Project Neutron: GIS, least-cost path road alignment

**Task:** Cedar Bluff Quarry haul road, least-cost corridor from image-only survey deliverables (Rev C).

## 1. Prompt (paste as-is)

> I'm the civil lead on the new haul road for Cedar Bluff Aggregates. Before we start geometric design, I need the least-cost corridor from the tie-in on County Road CR-114 (point T1) to the quarry plant gate (G1). You'll find everything on drawing set CB-HR-C001-C003_RevC.pdf (C-001 site constraints plan; C-002 data register, unit rates and constraints; C-003 typical section and haul truck criteria) and in the two rasters it registers: CB-DEM-10m_heightmap_uint16.png (terrain) and CB-LC-20m_landcover.png (land cover). The rasters and the tables and notes on C-002 and C-003 govern; C-001 is only a picture of them. Work in the environment's GIS stack (GDAL/PROJ, through QGIS or Python), and georeference the data before routing.
>
> Our cost model for route studies is as follows. Route on the 10 m DEM grid, moving from a cell centre to any of its 8 neighbouring cell centres. A move costs its horizontal length, times the average of the two cells' base unit rates from C-002, times a grade factor f(g). Here g is the absolute grade of that move in percent: the elevation difference between the two cell centres divided by the horizontal length of the move. f = 1.00 for g ≤ 3; f = 1.00 + 0.05(g − 3) for 3 < g ≤ 6; f = 1.15 + 0.12(g − 6) for 6 < g ≤ 10. Apply every constraint and operating criterion on the drawing set. The route is the chain of moves with the lowest total cost from the start cell to the end cell that satisfies all of them, and the route cost is the sum of its move costs in USD.
>
> Send me three files, with all coordinates in EPSG:32614 metres:
>
> 1. **CB_HaulRoad_Centreline.gpkg**: a GeoPackage with one layer named `centreline`. It holds a single LineString running from start to end, with a vertex at every route cell centre in travel order.
> 2. **CB_HaulRoad_Vertices.csv**: one row per vertex in travel order, with columns `seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, cum_cost_usd`. Give elevations in metres. Chainage is horizontal and starts at 0. Grade is signed, positive uphill in the direction of travel, and blank on the last row. `cum_cost_usd` is the accumulated route cost at each vertex.
> 3. **CB_HaulRoad_RouteReport.pdf**: the total route cost to the dollar; the horizontal length to 0.1 m; the maximum grade; the route length in each land-cover class; the start and end cell centres; which approved crossing window the route uses, and whether a compliant route through the other window exists; a short explanation of what controls the alignment; the unit rates and constraint values you applied; a plan of the route over the constraints; and a long section.
>
> This is for internal option selection, not for construction. Don't do geometric design (curves, sight distance) or earthworks.

## 2. Input assets (upload all three from `inputs/`)

| File | Type | What it is |
|---|---|---|
| `CB-HR-C001-C003_RevC.pdf` | PDF, 3 pages, each one embedded 3400×2200 raster image; no text layer | C-001 site constraints plan; C-002 data register, rate table, control points and Notes 1–8; C-003 typical section A-A, Table 4 haul truck criteria and Notes C1–C4 |
| `CB-DEM-10m_heightmap_uint16.png` | PNG, 16-bit greyscale, 360×280 | Terrain as a heightmap; DN maps to elevation in US survey feet |
| `CB-LC-20m_landcover.png` | PNG, 8-bit RGB, 190×150 | Land cover as exact RGB classes, on its own 20 m grid and origin |

All three assets are original. The terrain, land cover, place names and drawings were generated from scratch by `src/` (analytic surfaces; no third-party data). The location is a real UTM zone, but the site is fictional.

### Why Rev C

Two frontier rollouts solved Rev B (C-001/C-002 only) at about 100%: vision plus a plain Dijkstra cleared every Rev B trap. Rev C adds three criteria that a cell-based least-cost tool cannot express. Each one, missed alone, changes the route, the crossing or the escarpment ascent.

The traps live in the assets; the prompt announces none of them:

1. **Formation width** (C-003 Section A-A and Note C1). The road is the full formation, 1.00 + 1.00 + 10.00 + 1.00 + 1.00 = 14.00 m. The total is never printed and has to be added up from the dimension chain. Note C1 says the wetland setback and HS-1 exclusion are measured to the formation edge along every move, so a centreline needs 37.0 m clearance from W-1 and 157.0 m from HS-1. At X-1 the eastern creek column is exactly 35.0 m from W-1. A centreline-only model crosses there, giving 2,453,681 USD via X-1. With the formation applied, no route through X-1 exists.
2. **Sustained grade** (Table 4 T2/T3). Consecutive moves steeper than 8.0 % may total at most 60.0 m horizontal. The spur crest facing G1 grades at about 9.2 % for over 600 m: every move is legal under the 10 % limit, but the run breaks T3. Missing T3 gives the spur route, 2,081,106 USD.
3. **Turning limit** (Table 4 T4). Direction may change by at most 45° between consecutive moves. The southern chute is steeper than 10 % on the fall line and can only be climbed with 90°/135° switchbacks. Missing T4 gives the chute route, 2,333,848 USD.
4. **Path-dependent search.** T3 and T4 depend on the path, so a cell-cost raster plus `r.cost`/Dijkstra cannot enforce them. The solver needs an expanded state (cell × arrival heading × steep run).
5. **Heritage saddle** (C-002 Note 5 + C1). The easiest ascent is a saddle gap beside HS-1, closed by the 157 m formation-edge exclusion. Missing it gives 2,123,219 USD.
6. **Vertical units** (C-002 Table 1). `Elevation = 1150.00 + 0.01 × DN` in US survey feet. Without conversion no route under 10 % exists.
7. **Two grids and pixel-is-area.** The land-cover origin is E 582 900, N 3 351 620 with 20 m pixels. Cell centres end in 5.
8. **Control points in WGS 84** (Table 3). G1 was relocated at Rev C onto the plateau, south of the Rev B position.
9. **Indicative route lure** (C-001). The superseded 2025 route runs through X-1 and straight up the spur, the two moves Rev C forbids.
10. **Revision tension.** The woodland rate is 940 (Rev B, unchanged at Rev C; Rev A 690 withdrawn). C-002 Note 8 makes C-003 govern over C-002.

The DEM was post-processed so that no neighbour move grades within (8.00, 8.02] % or (10.00, 10.02] %. Rounding conventions, ≤ versus <, and the foot definition therefore cannot flip any move across a Table 4 threshold.

## 3. Golden deliverable (upload all three from `golden/`)

- `CB_HaulRoad_Centreline.gpkg`: layer `centreline`, one LineString with 455 vertices, EPSG:32614.
- `CB_HaulRoad_Vertices.csv`: 455 rows with the columns exactly as specified.
- `CB_HaulRoad_RouteReport.pdf`: result table, method (formation, Table 4, expanded-state search), rates applied, plan, long section with steep runs shaded, land-cover and grade breakdowns, a control explanation with sensitivity runs, and compliance.

Headline values:

- **Route cost:** 2,618,855.94 USD.
- **Horizontal length:** 5,513.40 m (219 orthogonal and 235 diagonal moves).
- **Start and end cells:** start E 583 155, N 3 349 105 at z 374.54 m; end E 586 315, N 3 350 315 at z 488.67 m.
- **Crossing:** approved window **X-2**, on two watercourse cells at N 3 349 605. **X-1:** no compliant route exists.
- **Escarpment:** the route runs north across the lowland, climbs the northern slump to N 3 351 475, and returns south along the plateau to G1.
- **Criteria:** max grade 9.96 % (steepest downhill −8.14 %); longest run of moves steeper than 8 % is 56.6 m; largest change of direction 45°.
- **Clearances:** the formation edge stays 643.5 m from W-1 and 310.9 m from HS-1.
- **Length by land-cover class:** grassland 3,935.3 m, existing track 876.1 m, woodland 467.0 m, cropland 215.0 m, watercourse (culvert) 20.0 m.

Each lever is decisive on its own (from `python3 src/solve.py`):

| Run | Cost (USD) | Length (m) | Crossing | Ascent | Δ vs golden |
|---|---|---|---|---|---|
| Golden (all criteria) | 2,618,856 | 5,513.4 | X-2 | northern slump | — |
| Formation width ignored | 2,453,681 | 5,477.4 | X-1 | northern slump | −6.3 % |
| T4 turning limit ignored | 2,333,848 | 4,753.7 | X-2 | southern chute (135° turns) | −10.9 % |
| T3 sustained grade ignored | 2,081,106 | 4,077.2 | X-2 | spur (620 m steep run) | −20.5 % |
| C-003 ignored (Rev B rules) | 2,017,567 | 4,383.6 | X-1 | spur | −23.0 % |
| HS-1 exclusion ignored | 2,123,219 | 4,279.2 | X-2 | saddle gap | −18.9 % |
| Only X-1 allowed | no path | | | | |

How robust the answer is:

- Segment-based versus vertex-only clearance testing, international versus US survey foot, and reversed tie-break order all give the same route. Cost agrees within 1 USD.
- Moving each threshold slightly (run cap 59.99/60.01 m, steep grade 7.99/8.01 %, grade limit 9.99/10.01 %, formation 13.9/14.1 m, setback 29.9 m, HS-1 149.9 m) leaves the route and cost unchanged.

## 4. Key components

1. The route cost is **2,618,856 USD** over **5,513.4 m**, crossing at **X-2**. It comes only from applying C-002 and C-003 together.
2. The road is the 14.0 m formation (7.0 m each side, summed from Section A-A). The setbacks are measured to its edge, so X-1 (35.0 m centreline clearance, 28.0 m at the formation edge) is **infeasible**.
3. Table 4 T3 caps runs of moves steeper than 8.0 % at 60.0 m, which rules out the spur. T4 caps the change of direction at 45°, which rules out the chute. The adopted route climbs the northern slump (N 3 351 475) and returns along the plateau.
4. The saddle gap beside HS-1 is closed by the 150 m exclusion measured to the formation edge.
5. T3 and T4 are enforced by a search over the state (cell, heading, steep run). The adopted route's longest steep run is 56.6 m and its largest turn is 45°.
6. DEM values in US survey feet are converted to metres (first-vertex elevation 374.54 m). Both rasters are georeferenced from their own C-002 Table 1 entries. The control points are projected from WGS 84, with G1 at its Rev C position.
7. The three files use the exact names, layer name, CSV columns and EPSG:32614. The report is internal, with no curve, sight-distance or earthworks design.

## 5. Rubric (39 items)

Weights: +9 ×6, +7 ×5, +5 ×9, +3 ×1, +1 ×14, and 4 penalties (−7, −5, −5, −3). The golden deliverable scores 100% (151/151) with `python3 src/grade.py`. Every geometric item is checkable from the delivered files alone. R11 also uses the issued land-cover raster.

| # | Wt | Type | Criterion |
|---|---|---|---|
| R1 | 9 | implicit | The PDF report states a total route cost of 2,618,856 USD (+/- 0.5 percent, 2,605,762 to 2,631,950 USD). |
| R2 | 7 | implicit | The PDF report states a horizontal route length of 5,513.4 m (+/- 0.5 percent, 5,485.8 to 5,541.0 m). |
| R3 | 9 | implicit | The PDF report states that no compliant route exists through crossing window X-1. |
| R4 | 7 | implicit | The PDF report attributes the infeasibility of crossing window X-1 to the road formation width: a centreline that clears the 30 m wetland setback at X-1 still leaves the formation edge within 30 m of wetland W-1. |
| R5 | 9 | implicit | The GeoPackage centreline has a vertex within 30 m of E 584 613.5, N 3 349 580.0 (EPSG:32614), the centre of approved crossing window X-2. |
| R6 | 5 | implicit | The GeoPackage centreline has a vertex within 25 m of E 584 325, N 3 349 705 (EPSG:32614). |
| R7 | 9 | implicit | The GeoPackage centreline has a vertex within 25 m of E 585 715, N 3 351 105 (EPSG:32614). |
| R8 | 7 | implicit | The GeoPackage centreline has a vertex within 25 m of E 586 305, N 3 350 855 (EPSG:32614). |
| R9 | 9 | implicit | No two consecutive segments of the GeoPackage centreline differ in direction by more than 45 degrees. |
| R10 | 9 | implicit | In the CSV vertex table, no unbroken sequence of rows with |grade_to_next_pct| greater than 8.0 spans more than 60.0 m of chainage (span = chainage of the row after the sequence minus chainage of its first row). |
| R11 | 7 | implicit | No point of the GeoPackage centreline lies within 37.0 m of any pixel of CB-LC-20m_landcover.png coloured RGB (150, 200, 210) (wetland), with the raster placed at UL corner E 582 900, N 3 351 620, 20 m pixels. |
| R12 | 1 | implicit | No point of the GeoPackage centreline lies within 157.0 m of E 586 011.9, N 3 350 201.9 (EPSG:32614), heritage point HS-1. |
| R13 | 1 | implicit | The first vertex of the GeoPackage centreline is at E 583 155.0, N 3 349 105.0 (EPSG:32614, +/- 1 m on each). |
| R14 | 1 | implicit | The last vertex of the GeoPackage centreline is at E 586 315.0, N 3 350 315.0 (EPSG:32614, +/- 1 m on each). |
| R15 | 1 | implicit | The CSV vertex table gives an elev_m of 374.54 m (+/- 0.05 m) on its first row. |
| R16 | 5 | implicit | The PDF report states a maximum route grade of 9.96 percent (+/- 0.03 percentage points). |
| R17 | 5 | implicit | The PDF report states that a road formation width of 14.0 m (7.0 m either side of the centreline) was applied to the wetland setback and the HS-1 exclusion. |
| R18 | 5 | implicit | The PDF report states that the direct spur ascent of the escarpment towards G1 breaks the 60 m sustained-grade limit for moves steeper than 8.0 percent. |
| R19 | 5 | implicit | The PDF report states that the southern fall-line (chute) ascent of the escarpment needs changes of direction greater than 45 degrees between consecutive moves. |
| R20 | 5 | implicit | The PDF report states the longest continuous run of moves steeper than 8.0 percent on the adopted route as 56.6 m (+/- 0.5 m). |
| R21 | 1 | explicit | Every pair of consecutive GeoPackage centreline vertices is separated by 10 m in easting, northing or both, with no other separation. |
| R22 | 1 | explicit | The cum_cost_usd value on the last row of the CSV vertex table equals the total route cost stated in the PDF report within 1 USD. |
| R23 | 1 | explicit | The GeoPackage centreline layer CRS is EPSG:32614 (WGS 84 / UTM zone 14N). |
| R24 | 1 | explicit | The GeoPackage contains a layer named 'centreline' holding exactly one LineString feature. |
| R25 | 1 | explicit | The response delivers a GeoPackage file named exactly 'CB_HaulRoad_Centreline.gpkg'. |
| R26 | 1 | explicit | The response delivers a CSV file named exactly 'CB_HaulRoad_Vertices.csv'. |
| R27 | 1 | explicit | The CSV header row is exactly: seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, cum_cost_usd. |
| R28 | 1 | explicit | The response delivers a PDF file named exactly 'CB_HaulRoad_RouteReport.pdf'. |
| R29 | 1 | explicit | The PDF report contains a plan figure showing the route centreline. |
| R30 | 1 | explicit | The PDF report contains a long section plotting elevation against chainage along the route. |
| R31 | 5 | implicit | The PDF report states a route length in woodland of 467.0 m (+/- 3 percent). |
| R32 | 5 | implicit | The PDF report states a route length in grassland / pasture of 3,935.3 m (+/- 3 percent). |
| R33 | 7 | implicit | The PDF report states that the adopted route climbs the escarpment by the northern slump, reaching N 3 351 475 (+/- 25 m) before returning south along the plateau to G1. |
| R34 | 3 | implicit | The CSV vertex table has 455 data rows (+/- 2), one per route cell from start to end. |
| R35 | 5 | implicit | The PDF report states that the saddle gap in the escarpment beside HS-1 is closed by the 150 m HS-1 exclusion measured to the edge of the road formation. |
| N1 | −7 | implicit | The CSV vertex table contains a grade_to_next_pct value whose absolute value exceeds 10.0. |
| N2 | −5 | explicit | The response presents the alignment as approved, issued or released for construction. |
| N3 | −3 | explicit | The PDF report states horizontal curve radii, sight distances or earthworks volumes for the route. |
| N4 | −5 | implicit | The PDF report states two different total cost values for the adopted route. |

How each criterion traces back to the prompt:

- **Cost, length, maximum grade:** R1, R2, R16.
- **Crossing window and the other window:** R3, R4, R5.
- **What controls the alignment:** R17, R18, R19, R33, R35, R20.
- **Operating criteria satisfied by the delivered route:** R9 (T4), R10 (T3), R11 (formation to wetland), R12 (formation to HS-1), N1 (T1).
- **Minimum-cost route:** R6, R7, R8, R34.
- **Land-cover lengths:** R31, R32.
- **Start and end cells:** R13, R14.
- **Vertex at every route cell centre:** R21.
- **Elevation in metres:** R15.
- **Files and format:** R22 to R30.
- **Scope limits:** N2, N3.
- **Internal consistency:** N4.

## 6. Calibration against simulated failures

`python3 src/grade.py sim` writes complete GeoPackage and CSV deliverables for each failure mode, then scores them. The claims are generous: a rollout that applies a rule is assumed to explain it correctly, which gives it R4/R17/R35 for width, R18 for T3 and R19 for T4.

| Simulated failure | Cost (USD) | Crossing | Score |
|---|---|---|---|
| A. C-003 not read (Rev B rules only) | 2,017,567 | X-1 | 9.3% |
| B. T3 + T4 applied, formation width missed | 2,453,681 | X-1 | 43.7% |
| C. Width + T4 applied, T3 sustained grade missed | 2,081,106 | X-2 | 53.0% |
| D. Width + T3 applied, T4 turning limit missed | 2,333,848 | X-2 | 53.0% |
| E. Width only | 2,080,492 | X-2 | 43.7% |
| F. T4 only | 2,017,984 | X-1 | 18.5% |
| G. T3 only | 2,333,848 | X-1 | 35.8% |
| H. All of C-003 applied, HS-1 exclusion missed | 2,123,219 | X-2 | 55.0% |
| **Mean** | | | **39.0%** |

Missing any one lever loses the cost, length, slump and plateau checkpoints, the vertex count and the lever's own compliance item, which caps the score at about 55%. Case A is how the Rev B rollouts actually behaved: they read C-002 and routed the centreline with a cell Dijkstra. It scores 9.3%. Implementing T3/T4 needs a state-expanded search that no GIS tool offers out of the box, so rollouts are most likely to cluster in A, E, F and G.

## 7. Judging the rollouts

For each rollout:

1. Overlay its centreline on the golden one in QGIS. Check the crossing (X-1 means the formation width was missed) and the ascent (spur means T3 was missed; chute means T4 was missed).
2. Check its CSV for runs of |grade| > 8 % longer than 60 m (R10), and its GeoPackage for turns over 45° (R9).
3. Read the first `elev_m`: 374.5 is correct, and about 1228.8 means feet were not converted.
4. Check that its report states the 14.0 m formation. Look for "14", "berm" and "formation".

Write up each failure with concrete values, the way the Building8 example does.

## 8. Reproducing

```bash
cd src
python3 make_rasters.py     # DEM + land-cover PNGs (with threshold-band clearing), published brief values
python3 make_sheets.py      # C-001 / C-002 / C-003 image-only PDF
python3 solve.py            # golden + every lever/robustness variant
python3 make_golden.py      # golden GPKG / CSV / PDF
python3 grade.py            # golden vs rubric
python3 grade.py sim        # simulated failure calibration
```

Dependencies: Python 3.12, numpy, numba, pillow, pyproj, shapely, geopandas, pyogrio, matplotlib, reportlab, pypdf.
