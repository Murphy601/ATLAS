# Project Neutron: GIS, least-cost path road alignment

**Task:** Cedar Bluff Quarry haul road, least-cost corridor from image-only survey deliverables (Rev D).

## 1. Prompt (paste as-is)

> I'm the civil lead on the new haul road for Cedar Bluff Aggregates. Before we start detailed design, I need the least-cost corridor from the tie-in on County Road CR-114 (point T1) to the quarry plant gate (G1). You'll find everything on drawing set CB-HR-C001-C004_RevD.pdf (C-001 site constraints plan; C-002 data register, unit rates and constraints; C-003 typical section and haul truck criteria; C-004 loaded haul, route geometry and cost basis) and in the two rasters it registers: CB-DEM-10m_heightmap_uint16.png (terrain) and CB-LC-20m_landcover.png (land cover). The rasters and the tables and notes on C-002 to C-004 govern; C-001 is only a picture of them. Work in the environment's GIS stack (GDAL/PROJ, through QGIS or Python), and georeference the data before routing.
>
> Our construction cost model for route studies is as follows. Route on the 10 m DEM grid, moving from a cell centre to any of its 8 neighbouring cell centres. A move's construction cost is its horizontal length, times the average of the two cells' base unit rates from C-002, times a grade factor f(g). Here g is the absolute grade of that move in percent: the elevation difference between the two cell centres divided by the horizontal length of the move. f = 1.00 for g ≤ 3; f = 1.00 + 0.05(g − 3) for 3 < g ≤ 6; f = 1.15 + 0.12(g − 6) for 6 < g ≤ 10. Apply every constraint, operating criterion and cost item on the drawing set. The route is the chain of moves from the start cell to the end cell that satisfies all of them and has the lowest total route cost as the drawing set defines it.
>
> Send me three files, with all coordinates in EPSG:32614 metres:
>
> 1. **CB_HaulRoad_Centreline.gpkg**: a GeoPackage with one layer named `centreline`. It holds a single LineString running from start (T1) to end (G1), with a vertex at every route cell centre in order.
> 2. **CB_HaulRoad_Vertices.csv**: one row per vertex from T1 to G1, with columns `seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, cum_cost_usd`. Give elevations in metres. Chainage is horizontal and starts at 0 at T1. Grade is signed, positive uphill in the direction of increasing chainage, and blank on the last row. `cum_cost_usd` is the accumulated total route cost at each vertex.
> 3. **CB_HaulRoad_RouteReport.pdf**: the total route cost and each of its components to the dollar; the horizontal length to 0.1 m; the maximum grade; the route length in each land-cover class; the start and end cell centres; which approved crossing window the route uses, and whether a compliant route through the other window exists; a short explanation of what controls the alignment; the unit rates, constraint values and coordinate conversions you applied; a plan of the route over the constraints; and a long section.
>
> This is for internal option selection, not for construction. Beyond what the drawing set asks for route screening, don't do geometric design (curve setting-out, superelevation, sight distance) or earthworks.

## 2. Input assets (upload all three from `inputs/`)

| File | Type | What it is |
|---|---|---|
| `CB-HR-C001-C004_RevD.pdf` | PDF, 4 pages, each one embedded 3400×2200 raster image; no text layer | C-001 site constraints plan; C-002 data register, rate table, control points and Notes 1–8; C-003 typical section A-A, Table 4 haul truck criteria and Notes C1–C4; C-004 Table 5 loaded haul / geometry / cost criteria D1–D7, Table 6 re-surveyed G1, Table 7 distractor values, Notes D1–D6 |
| `CB-DEM-10m_heightmap_uint16.png` | PNG, 16-bit greyscale, 360×280 | Terrain as a heightmap; DN maps to elevation in US survey feet |
| `CB-LC-20m_landcover.png` | PNG, 8-bit RGB, 190×150 | Land cover as exact RGB classes, on its own 20 m grid and origin |

All three assets are original. The terrain, land cover, place names and drawings were generated from scratch by `src/` (analytic surfaces; no third-party data). The location is a real UTM zone, but the site is fictional.

### Why Rev D

Frontier rollouts solved Rev C: they built the expanded-state search for formation width, the 60 m sustained-grade run and the 45° turning limit. Rev D keeps every Rev C trap and adds sheet C-004. C-004 turns the problem into a directional, second-order, geodetically referenced optimisation that a least-cost raster tool cannot express and a naive expanded-state Dijkstra gets wrong.

New traps in Rev D (the prompt announces none of them):

1. **Directional loaded grade** (D1–D3, Note D2). Trucks run loaded from G1 to T1, which is *against* chainage. D3 limits *effective* grade (grade + 3.0 % rolling resistance) to 9.0 %, so moves that fall in the chainage direction are capped at 6.0 %. Moves that rise in chainage direction keep the 10 % T1 cap. The asymmetry makes the arc cost depend on direction. Reading 9.0 % as a plain grade (case F) or ignoring D3 moves the route.
2. **Rate of vertical curvature** (D5, Note D4). For every pair of consecutive moves, \(K = L / |\Delta g| \ge 1.4\) m/%, with L the distance between the two move midpoints, \((L_1+L_2)/2\). The allowed grade change is 7.14 % (orthogonal–orthogonal), 8.62 % (mixed) or 10.10 % (diagonal–diagonal). This is a second-order constraint: the state needs the previous move's grade.
3. **Minimum horizontal radius** (D6, Note D3). A 45 m arc at each 45° deflection vertex has tangent length \(T = R\tan 22.5^\circ = 18.64\) m. Arcs may not overlap (≥ 37.28 m between deflection vertices: 4 orthogonal or 3 diagonal moves) and may not run past the start or end (≥ 18.64 m to the first/last deflection). Applying one T between deflections (case C) is the classic slip. The state needs a tangent counter.
4. **Life-cycle haulage cost** (D7, Note D1). The total cost is construction plus 8,000 USD per metre of rise climbed loaded, charged only where the effective grade exceeds 4.0 %, i.e. actual grade > 1.0 %, with no credit for falls. It is charged in the *loaded* direction, which is opposite to chainage (case I charges the wrong way and prices the route at 3.97 M). Dropping the rolling resistance (case L) or the threshold (case M) changes the route.
5. **Re-surveyed G1 in state-plane surface coordinates** (Table 6, Note D5). G1 is given in TxDOT surface feet on NAD83 / Texas Central (EPSG:2277, US survey feet) with SAF 1.00012 scaled about the grid origin. A solver must divide by the SAF, read the US survey foot, and transform to EPSG:32614. Missing the SAF moves G1 about 110 m east and 368 m north (the scale acts on the full 3,001,506 / 10,073,680 ft). Reading international feet moves it south into another cell. Table 3 on C-002 still shows the superseded Rev C gate, and C-001 draws G1 at Rev C "for presentation".
6. **Distractors** (Table 7). In-pit rolling resistance 2.0 %, unsurfaced 6.0 %, turning radius 8.9 m, operator haul cost 450 USD/m of fall, and an empty-truck top-gear limit of 6.0 %. None of them is a route criterion.
7. **Threshold band clearing.** No neighbour move grades within 0.02 % above 1.0 %, 6.0 %, 8.0 % or 10.0 %. Rounding conventions, ≤ versus < and the foot definition cannot flip a move across any threshold.

Rev C traps retained: the 14.0 m formation width summed from Section A-A (X-1 infeasible), T3 sustained grade (spur), T4 turning (chute), the HS-1 saddle, US survey feet in the DEM, two grids with pixel-is-area, WGS 84 control points, the 2025 indicative route lure and the rate revision history.

The golden solver is a Numba Dijkstra over the state (cell, arrival heading, steep-run length, tangent counter), with the previous move's grade recovered from the heading. It applies D3 and D7 by move direction relative to the loaded direction.

## 3. Golden deliverable (upload all three from `golden/`)

- `CB_HaulRoad_Centreline.gpkg`: layer `centreline`, one LineString with 492 vertices, EPSG:32614.
- `CB_HaulRoad_Vertices.csv`: 492 rows with the columns exactly as specified.
- `CB_HaulRoad_RouteReport.pdf`: result table with cost components, method (formation, Table 4, C-004 D1–D7, G1 datum chain), rates applied, plan, long section, land-cover and grade breakdowns, a control explanation with sensitivity runs, and compliance.

Headline values:

- **Total route cost:** 3,110,904 USD = construction 2,926,731 USD + loaded haulage 184,173 USD (23.02 m of charged loaded rise).
- **Horizontal length:** 5,974.5 m, 492 vertices, 33 deflection vertices.
- **Start and end cells:** start E 583 155, N 3 349 105 at z 374.54 m; end E 586 455, N 3 350 105 at z 484.97 m. G1 from Table 6 is E 586 454.9, N 3 350 102.5.
- **Crossing:** approved window **X-2**. **X-1:** no compliant route exists (formation width).
- **Escarpment:** north across the lowland, up the northern slump to N 3 351 475, then south along the plateau to G1.
- **Criteria:** max grade 9.98 %; max loaded uphill grade 5.88 %; min K 1.427 m/%; min tangent between deflections 40.0 m (start 30.0 m, end 183.8 m); longest run steeper than 8 % is 56.6 m; largest change of direction 45°.
- **Clearances:** the formation edge stays 664.7 m from W-1 and 453.6 m from HS-1.
- **Length by land-cover class:** grassland 4,215.1 m, cropland 632.3 m, existing track 573.3 m, woodland 533.9 m, watercourse (culvert) 20.0 m.

Each lever changes the route on its own (from `python3 src/solve.py`):

| Run | Total (USD) | Length (m) | Vertices | Crossing | Max loaded uphill (%) | Min K | Min tangent (m) |
|---|---|---|---|---|---|---|---|
| **Golden (all criteria)** | **3,110,904** | **5,974.5** | **492** | X-2 | 5.88 | 1.43 | 40.0 |
| D3 ignored, or 9.0 % read as grade | 3,079,905 | 5,966.2 | 492 | X-2 | 8.11 | 1.43 | 40.0 |
| D5 vertical curvature ignored | 3,108,097 | 5,962.8 | 490 | X-2 | 5.88 | 1.35 | 40.0 |
| D6 radius ignored | 3,037,459 | 5,988.1 | 483 | X-2 | 5.49 | 1.40 | 10.0 |
| D6 with one T between deflections | 3,050,379 | 5,997.4 | 486 | X-2 | 5.49 | 1.40 | 20.0 |
| D7 haulage ignored | 2,890,615 | 6,058.4 | 495 | X-2 | 5.49 | 1.44 | 40.0 |
| D7 charged in chainage direction | 3,967,261 | 5,982.8 | 492 | X-2 | 5.88 | 1.43 | 40.0 |
| D7 threshold without rolling resistance | 2,964,315 | 6,094.9 | 497 | X-2 | 5.49 | 1.44 | 40.0 |
| D7 threshold ignored | 3,131,810 | 5,974.5 | 492 | X-2 | 5.88 | 1.43 | 40.0 |
| G1 at superseded Rev C position | 2,890,113 | 5,623.7 | 471 | X-2 | 5.88 | 1.44 | 40.0 |
| EPSG:2277 read as international feet | 3,274,997 | 6,401.1 | 533 | X-2 | 5.88 | 1.43 | 40.0 |
| G1 SAF ignored (surface used as grid) | 2,862,024 | 5,552.4 | 456 | X-2 | 5.88 | 1.43 | 40.0 |
| C-004 ignored entirely (Rev C rules) | 2,618,852 | 5,513.4 | 455 | X-2 | 8.14 | 1.19 | 10.0 |
| T4 turning limit ignored | 2,976,243 | 5,738.0 | 470 | X-2 | 5.75 | 1.45 | 40.0 |
| T3 sustained grade ignored | 2,567,344 | 4,621.3 | 401 | X-2 | 5.73 | 1.73 | 40.0 |
| HS-1 exclusion ignored | 2,217,326 | 4,000.9 | 346 | X-2 | 5.73 | 1.52 | 40.0 |

D7 with the threshold ignored matches the golden route but not its cost, so it fails R1, R3, R20 to R22 and R24.

How robust the answer is: moving K by ±0.01, the loaded cap by ±0.02 %, R by ±1 m, the haul rate by ±10 USD/m, the haul threshold by ±0.02 %, the foot definition of the DEM, the tie-break order, or segment versus vertex clearance testing all give the same route. The cost agrees within 2 USD.

## 4. Key components

1. The total route cost is **3,110,904 USD** (construction 2,926,731 + haulage 184,173) over **5,974.5 m**, with 492 vertices and 33 deflections, crossing at **X-2**.
2. Loaded trucks travel G1 → T1. Moves falling in chainage direction are capped at 6.0 % (9.0 % effective − 3.0 % rolling resistance). Max loaded uphill is 5.88 %.
3. \(K = L/|\Delta g| \ge 1.4\) with L the midpoint-to-midpoint distance: 7.14 / 8.62 / 10.10 % limits. Min K is 1.427.
4. A 45 m radius gives 18.64 m tangents: at least 37.28 m between deflection vertices and 18.64 m to each end.
5. Haulage is 8,000 USD/m of loaded rise on moves with loaded grade > 1.0 %, no credit for falls, and the route minimises the sum.
6. G1 from Table 6: surface ftUS ÷ 1.00012 → EPSG:2277 grid → EPSG:32614, giving E 586 454.9, N 3 350 102.5 and end cell E 586 455, N 3 350 105.
7. All Rev C items still hold: 14.0 m formation (X-1 infeasible), T3 60 m steep-run cap, T4 45°, HS-1 157 m, DEM in US survey feet (first elevation 374.54 m).
8. Exact file names, layer name, CSV columns, EPSG:32614, and no earthworks.

## 5. Rubric (58 items)

Weights: +9 ×10, +7 ×11, +5 ×14, +3 ×2, +1 ×17, and 4 penalties (−7, −5, −5, −3). Positive total 260. The golden deliverable scores **100% (260/260)** with `python3 src/grade.py`. Every geometric item is checked from the delivered files alone. C6 also uses the issued land-cover raster. P1–P13 are golden cell centres placed by `work/calib.py` where the single-rule misses leave the golden route.

| # | Wt | Criterion |
|---|---|---|
| R1 | +9 | The PDF report states a total route cost (construction plus loaded haulage) of 3,110,904 USD (+/- 0.01 percent, 3,110,593 to 3,111,215 USD). |
| R2 | +9 | The PDF report states a construction cost component of 2,926,731 USD (+/- 0.01 percent, 2,926,438 to 2,927,024 USD). |
| R3 | +9 | The PDF report states a loaded haulage cost component of 184,173 USD (+/- 0.05 percent, 184,081 to 184,265 USD). |
| R4 | +9 | The PDF report states a horizontal route length of 5,974.5 m (+/- 1.0 m). |
| R5 | +9 | The CSV vertex table has exactly 492 data rows. |
| R6 | +7 | The GeoPackage centreline has exactly 33 interior vertices at which the direction of the line changes. |
| R7 | +9 | The last vertex of the GeoPackage centreline is at E 586 455.0, N 3 350 105.0 (EPSG:32614, +/- 1 m on each). |
| P1 | +7 | The GeoPackage centreline has a vertex within 1 m of E 583 625, N 3 349 445 (EPSG:32614). |
| P2 | +7 | The GeoPackage centreline has a vertex within 1 m of E 583 705, N 3 349 445 (EPSG:32614). |
| P3 | +5 | The GeoPackage centreline has a vertex within 1 m of E 585 775, N 3 351 075 (EPSG:32614). |
| P4 | +5 | The GeoPackage centreline has a vertex within 1 m of E 585 855, N 3 351 145 (EPSG:32614). |
| P5 | +5 | The GeoPackage centreline has a vertex within 1 m of E 585 965, N 3 351 295 (EPSG:32614). |
| P6 | +5 | The GeoPackage centreline has a vertex within 1 m of E 585 965, N 3 351 375 (EPSG:32614). |
| P7 | +7 | The GeoPackage centreline has a vertex within 1 m of E 586 295, N 3 350 715 (EPSG:32614). |
| P8 | +7 | The GeoPackage centreline has a vertex within 1 m of E 586 375, N 3 350 635 (EPSG:32614). |
| P9 | +7 | The GeoPackage centreline has a vertex within 1 m of E 586 455, N 3 350 555 (EPSG:32614). |
| P10 | +7 | The GeoPackage centreline has a vertex within 1 m of E 586 545, N 3 350 465 (EPSG:32614). |
| P11 | +5 | The GeoPackage centreline has a vertex within 1 m of E 586 555, N 3 350 385 (EPSG:32614). |
| P12 | +5 | The GeoPackage centreline has a vertex within 1 m of E 586 585, N 3 350 245 (EPSG:32614). |
| P13 | +5 | The GeoPackage centreline has a vertex within 1 m of E 586 515, N 3 350 165 (EPSG:32614). |
| R20 | +9 | The cum_cost_usd value on the last row of the CSV vertex table is 3,110,904 USD (+/- 0.01 percent). |
| R21 | +7 | On the first CSV row whose landcover_class is Watercourse, cum_cost_usd is 888,233 USD (+/- 0.05 percent). |
| R22 | +7 | On the first CSV row with the largest northing_m, cum_cost_usd is 2,284,982 USD (+/- 0.05 percent). |
| R23 | +5 | On the first CSV row with the largest northing_m, chainage_m is 4,295.3 m (+/- 1.0 m). |
| R24 | +7 | Exactly 54 rows of the CSV vertex table have grade_to_next_pct below -1.000 (moves climbed by loaded trucks above the 4.0 percent effective top-gear limit). |
| R12 | +5 | The PDF report states a route length in woodland of 533.9 m (+/- 0.2 percent). |
| R13 | +7 | The PDF report states a route length in grassland / pasture of 4,215.1 m (+/- 0.2 percent). |
| R14 | +5 | The PDF report states a route length on existing gravel track of 573.3 m (+/- 0.2 percent). |
| R15 | +5 | The PDF report states a route length in cultivated cropland of 632.3 m (+/- 0.2 percent). |
| R16 | +1 | The PDF report states a maximum route grade of 9.98 percent (+/- 0.02 percentage points). |
| R17 | +1 | The PDF report states that the route climbs the escarpment by the northern slump, reaching N 3 351 475 (+/- 25 m) before returning south along the plateau to G1. |
| R18 | +1 | The GeoPackage centreline has a vertex within 30 m of E 584 613.5, N 3 349 580.0 (EPSG:32614), the centre of approved crossing window X-2. |
| C1 | +9 | No row of the CSV vertex table has grade_to_next_pct below -6.00 (no move climbed by loaded trucks, travelling G1 to T1, is steeper than 6.0 percent). |
| C2 | +9 | For every two consecutive moves in the CSV vertex table, the absolute difference of grade_to_next_pct is at most (L1 + L2) / 2 / 1.4 (+ 0.002), where L1 and L2 are the two moves' horizontal lengths in m from chainage_m. |
| C3 | +9 | Along the GeoPackage centreline, successive direction-change vertices are at least 37.28 m apart, and the first and last direction-change vertices are at least 18.64 m from the first and last vertex. |
| C4 | +1 | No two consecutive segments of the GeoPackage centreline differ in direction by more than 45 degrees. |
| C5 | +1 | In the CSV vertex table, no unbroken sequence of rows with \|grade_to_next_pct\| greater than 8.0 spans more than 60.0 m of chainage (span = chainage of the row after the sequence minus chainage of its first row). |
| C6 | +1 | No point of the GeoPackage centreline lies within 37.0 m of any pixel of CB-LC-20m_landcover.png coloured RGB (150, 200, 210), with the raster placed at UL corner E 582 900, N 3 351 620, 20 m pixels. |
| C7 | +1 | No point of the GeoPackage centreline lies within 157.0 m of E 586 011.9, N 3 350 201.9 (EPSG:32614). |
| C8 | +1 | The first vertex of the GeoPackage centreline is at E 583 155.0, N 3 349 105.0 (EPSG:32614, +/- 1 m). |
| C9 | +1 | The CSV vertex table gives an elev_m of 374.54 m (+/- 0.05 m) on its first row. |
| S1 | +1 | The PDF report states that no compliant route exists through crossing window X-1. |
| S2 | +1 | The PDF report attributes the infeasibility of X-1 to the formation width: a centreline clearing the 30 m wetland setback still leaves the formation edge within 30 m of wetland W-1. |
| S3 | +3 | The PDF report states that loaded trucks travel from G1 to T1 and that moves climbed loaded are limited to a 6.0 percent grade (9.0 percent effective grade minus 3.0 percent rolling resistance). |
| S4 | +5 | The PDF report states that the 45 m minimum radius requires at least 37.28 m (+/- 0.05 m) between successive deflection vertices and at least 18.64 m (+/- 0.05 m) between the start or end and the nearest deflection vertex. |
| S5 | +5 | The PDF report states that the allowable grade change between consecutive moves depends on the two move lengths, (L1 + L2) / (2 x 1.4), e.g. 7.14 percent between two orthogonal moves and 10.10 percent between two diagonal moves. |
| S6 | +5 | The PDF report states that the route minimises construction cost plus loaded haulage of 8,000 USD per metre of rise climbed by loaded trucks, charged only on moves whose loaded grade exceeds 1.0 percent (4.0 percent effective grade minus 3.0 percent rolling resistance), with no credit for falls. |
| S7 | +3 | The PDF report states that G1 was taken from C-004 Table 6 as TxDOT surface coordinates, divided by the surface adjustment factor 1.00012 to NAD83 / Texas Central grid in US survey feet (EPSG:2277), and transformed to EPSG:32614. |
| F1 | +1 | The cum_cost_usd value on the last row of the CSV vertex table equals the total route cost stated in the PDF report (construction plus haulage) within 1 USD. |
| F2 | +1 | Every pair of consecutive GeoPackage centreline vertices is separated by 10 m in easting, northing or both, with no other separation. |
| F3 | +1 | The GeoPackage centreline layer CRS is EPSG:32614 and the layer 'centreline' holds exactly one LineString feature. |
| F4 | +1 | The response delivers files named exactly 'CB_HaulRoad_Centreline.gpkg', 'CB_HaulRoad_Vertices.csv' and 'CB_HaulRoad_RouteReport.pdf'. |
| F5 | +1 | The CSV header row is exactly: seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, cum_cost_usd. |
| F6 | +1 | The PDF report contains a plan figure showing the route centreline and a long section plotting elevation against chainage. |
| N1 | -7 | The CSV vertex table contains a grade_to_next_pct value whose absolute value exceeds 10.0. |
| N2 | -5 | The response presents the alignment as approved, issued or released for construction. |
| N3 | -5 | The PDF report states two different total cost values for the adopted route. |
| N4 | -3 | The PDF report states earthworks volumes for the route. |

How each criterion traces back to the prompt:

- **Total cost and components, length, maximum grade:** R1–R4, R16, R20.
- **Minimum-cost route (one cell per vertex):** R5, R6, P1–P13, R21–R23.
- **End cell (G1 datum chain):** R7, S7. **Start cell and metres:** C8, C9.
- **Every constraint, criterion and cost item on the drawing set:** C1 (D3), C2 (D5), C3 (D6), R24 (D7 charged moves), C4 (T4), C5 (T3), C6/C7 (formation clearances), N1 (T1).
- **What controls the alignment:** S3–S6, R17. **Crossing window and the other window:** R18, S1, S2.
- **Land-cover lengths:** R12–R15.
- **Files and format:** F1–F6. **Scope and consistency:** N2–N4.

## 6. Calibration against simulated failures

`python3 src/grade.py sim` writes complete GeoPackage and CSV deliverables for each failure mode with the Rev D solver, then scores them. The claims are generous: every rule a simulated rollout applied is assumed to be explained correctly in its report, and all Rev C items (formation, T3, T4, HS-1, units) are assumed to be correct.

| Simulated failure | Total (USD) | Haulage (USD) | Length (m) | Score |
|---|---|---|---|---|
| A. C-004 not applied (Rev C rules and Rev C gate) | 2,618,852 | 0 | 5,513.4 | 6.5% |
| B. All but D6 radius (curves treated as out of scope) | 3,037,459 | 202,363 | 5,988.1 | 39.6% |
| C. D6 with one tangent length between deflections | 3,050,379 | 208,825 | 5,997.4 | 26.9% |
| D. All but D7 haulage (construction cost only) | 2,890,615 | 0 | 6,058.4 | 38.1% |
| E. All but D5 vertical curvature | 3,108,097 | 184,173 | 5,962.8 | 59.6% |
| F. D3 9.0 % read as a grade limit | 3,079,905 | 216,262 | 5,966.2 | 43.1% |
| G. G1 from superseded C-002 Table 3 | 2,890,113 | 114,434 | 5,623.7 | 52.7% |
| H. G1 surface coordinates used as grid (SAF ignored) | 2,862,024 | 117,141 | 5,552.4 | 50.0% |
| H2. EPSG:2277 read as international feet | 3,274,997 | 170,396 | 6,401.1 | 50.0% |
| I. D7 rise charged in chainage direction | 3,967,261 | 1,032,323 | 5,982.8 | 48.1% |
| L. D7 threshold read as 4.0 % grade (rolling resistance dropped) | 2,964,315 | 46,354 | 6,094.9 | 34.2% |
| M. D7 threshold ignored (every loaded rise charged) | 3,131,810 | 204,338 | 5,974.5 | 57.3% |
| N. "Effective grade" misread in both D3 and D7 | 2,944,717 | 60,668 | 6,041.8 | 29.6% |
| J. D5 and D6 both missed | 3,017,166 | 202,363 | 5,955.4 | 30.4% |
| K. D6 and D7 both missed | 2,822,303 | 0 | 5,985.7 | 29.6% |
| **Mean** | | | | **39.7%** |

Every single-rule miss scores below 60 %, because it loses the total, the component it misses, the length, the vertex and deflection counts, R21–R23 and the checkpoints where its route leaves the golden one. The simulated claims are generous, so real rollouts should score lower: a rollout also has to get every Rev C item right, and none of the text items are free.

## 7. Judging the rollouts

For each rollout:

1. Read the end vertex. E 586 455, N 3 350 105 is correct. The Rev C gate (G), a point about 110 m east and 368 m north (SAF ignored, H) or a cell further south (international feet, H2) each shows the datum chain failing.
2. Check its CSV: any grade below −6.00 fails D3 (C1), and any consecutive grade change above (L1+L2)/2.8 fails D5 (C2). Count the rows below −1.000 (R24 = 54).
3. Check its GeoPackage for deflection vertices closer than 37.28 m, or within 18.64 m of either end (C3).
4. Compare the reported haulage with 184,173 USD. About 1.03 M means haulage was charged in the chainage direction. About 46 k means the rolling resistance was dropped from the threshold. 0 means D7 was ignored.
5. Overlay the centreline on the golden one in QGIS and note which of P1–P13 it misses.

Write up each failure with concrete values, the way the Building8 example does.

## 8. Reproducing

```bash
cd src
python3 make_rasters.py     # DEM + land-cover PNGs (threshold-band clearing), published brief values
python3 make_sheets.py      # C-001 to C-004 image-only PDF
python3 solve.py            # golden + every lever/robustness variant
python3 make_golden.py      # golden GPKG / CSV / PDF
python3 ../work/calib.py    # checkpoints P1-P13 and grader constants
python3 grade.py            # golden vs rubric
python3 grade.py sim        # simulated failure calibration
```

Dependencies: Python 3.12, numpy, numba, pillow, pyproj, shapely, geopandas, pyogrio, matplotlib, reportlab, pypdf.
