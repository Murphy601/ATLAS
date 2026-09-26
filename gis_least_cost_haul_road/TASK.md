# Project Neutron: GIS, least-cost path road alignment

**Task:** Cedar Bluff Quarry haul road, least-cost corridor from image-only survey deliverables (Rev E: Rev D drawing set and rasters unchanged, three brief-level updates and a strict output format).

## 1. Prompt (paste as-is)

> I'm the civil lead on the new haul road for Cedar Bluff Aggregates. Before we start detailed design, I need the least-cost corridor from the tie-in on County Road CR-114 (point T1) to the quarry plant gate (G1). You'll find everything on drawing set CB-HR-C001-C004_RevD.pdf (C-001 site constraints plan; C-002 data register, unit rates and constraints; C-003 typical section and haul truck criteria; C-004 loaded haul, route geometry and cost basis) and in the two rasters it registers: CB-DEM-10m_heightmap_uint16.png (terrain) and CB-LC-20m_landcover.png (land cover). The rasters and the tables and notes on C-002 to C-004 govern; C-001 is only a picture of them. Work in the environment's GIS stack (GDAL/PROJ, through QGIS or Python), and georeference the data before routing.
>
> Our construction cost model for route studies is as follows. Route on the 10 m DEM grid, moving from a cell centre to any of its 8 neighbouring cell centres. A move's construction cost is its horizontal length, times the average of the two cells' base unit rates from C-002, times a grade factor f(g). Here g is the absolute grade of that move in percent: the elevation difference between the two cell centres divided by the horizontal length of the move. f = 1.00 for g ≤ 3; f = 1.00 + 0.05(g − 3) for 3 < g ≤ 6; f = 1.15 + 0.12(g − 6) for 6 < g ≤ 10. Apply every constraint, operating criterion and cost item on the drawing set. The route is the chain of moves from the start cell to the end cell that satisfies all of them and has the lowest total route cost as the drawing set defines it.
>
> Three things have changed since Rev D was issued. They are not on the drawings yet, and where they differ from the drawing set they govern:
>
> (a) **Plateau lease.** Grassland on the Cedar Bluff plateau is now leased ground. A DEM cell whose land-cover class is Grassland / pasture and whose ground elevation is 1,500.00 ft or higher (NAVD 88, in the units the DEM is published in) takes a base unit rate of 1,300 USD/m instead of the C-002 grassland rate. No other rate changes.
>
> (b) **Cedar Branch slip zone.** The valley sides between N 3 349 600 and N 3 349 800 (EPSG:32614) are unstable. A continuous run of moves steeper than 8.0 % that contains at least one move with either end cell centre inside that band may not exceed 30.0 m of horizontal length. The limit applies to the whole run, including any part of it outside the band. Elsewhere the C-003 limit stands.
>
> (c) **Gate approach.** The weighbridge lies immediately east of G1. The last 40.0 m of the route must be one straight run over it, travelling due west into the G1 cell (four consecutive westward moves ending at the G1 cell). Every drawing-set rule applies on this run as it does everywhere else.
>
> Send me three files, with all coordinates in EPSG:32614 metres:
>
> 1. **CB_HaulRoad_Centreline.gpkg**: a GeoPackage with one layer named `centreline`. It holds a single LineString running from start (T1) to end (G1), with a vertex at every route cell centre in order, and the attribute fields `route_id` (the text `CB-HR-01E`), `total_cost_usd` and `length_m`.
> 2. **CB_HaulRoad_Vertices.csv**: one row per vertex from T1 to G1, with exactly these columns in this order: `seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, unit_rate_usd_per_m, cum_constr_usd, cum_haul_usd, cum_cost_usd`. Give elevations in metres. Chainage is horizontal and starts at 0 at T1. Grade is signed, positive uphill in the direction of increasing chainage, and blank on the last row. `landcover_class` is the class name exactly as written in C-002 Table 2 (culvert cells keep the watercourse class name). `unit_rate_usd_per_m` is the base unit rate you applied to that vertex's cell. `cum_constr_usd`, `cum_haul_usd` and `cum_cost_usd` are the accumulated construction cost, loaded haulage cost and total route cost at each vertex. Write easting, northing, chainage and the four USD columns with exactly 2 decimals, elevation and grade with exactly 3 decimals, and no thousands separators.
> 3. **CB_HaulRoad_RouteReport.pdf**: the total route cost and each of its components to the dollar; the horizontal length to 0.1 m; the maximum grade; the route length in each land-cover class, and on the plateau lease; the start and end cell centres; which approved crossing window the route uses, and whether a compliant route through the other window exists; a short explanation of what controls the alignment; the unit rates, constraint values and coordinate conversions you applied; a plan of the route over the constraints; and a long section.
>
> This is for internal option selection, not for construction. Beyond what the drawing set and this brief ask for route screening, don't do geometric design (curve setting-out, superelevation, sight distance) or earthworks.

## 2. Input assets (upload all three from `inputs/`, unchanged from Rev D)

| File | Type | What it is |
|---|---|---|
| `CB-HR-C001-C004_RevD.pdf` | PDF, 4 pages, each one embedded 3400×2200 raster image; no text layer | C-001 site constraints plan; C-002 data register, rate table, control points and Notes 1–8; C-003 typical section A-A, Table 4 haul truck criteria and Notes C1–C4; C-004 Table 5 loaded haul / geometry / cost criteria D1–D7, Table 6 re-surveyed G1, Table 7 distractor values, Notes D1–D6 |
| `CB-DEM-10m_heightmap_uint16.png` | PNG, 16-bit greyscale, 360×280 | Terrain as a heightmap; DN maps to elevation in US survey feet |
| `CB-LC-20m_landcover.png` | PNG, 8-bit RGB, 190×150 | Land cover as exact RGB classes, on its own 20 m grid and origin |

All three assets are original. The terrain, land cover, place names and drawings were generated from scratch by `src/` (analytic surfaces; no third-party data). The location is a real UTM zone, but the site is fictional.

### Why Rev E

A Rev D rollout solved the drawing set exactly (97 %). Rev E keeps every file and adds three rules in the prompt, each tied to something only the images carry, plus a strict output format. Together they move the optimum to a different route: the Rev D answer now scores 20.6 %.

New traps in Rev E:

1. **Plateau lease in feet** (a). The threshold is 1,500.00 ft in the DEM's own units (US survey feet, C-002 Table 1), i.e. 457.201 m. Comparing 1,500 with elevations in metres puts no cell on the lease; applying the rate to all grassland, or not at all, moves the route. The lease cannot be avoided (G1 is on the plateau). At 1,300 USD/m the grade factor multiplies a much larger base, so the plateau leg re-balances grade, length and haulage and moves 129 cells.
2. **Slip zone applies to the whole run** (b). The Rev D route climbs out of the Cedar Branch valley on two 56.6 m steep runs inside the band. A run is limited to 30 m over its whole length once any move of it touches the band. The search state needs a zone flag carried with the steep-run length. Testing 30 m only on moves inside the band (the natural shortcut) gives a different, non-compliant line.
3. **Gate approach inside the search** (c). The last four moves must run due west into G1, and D5 (K), D6 (tangents), D3 and D7 still apply to them. Routing to the start of the approach and then appending it gives a cheaper line that breaks D6 (a 28.3 m tangent). Arriving travelling east has no compliant route. With G1's SAF ignored, the approach would leave the DEM.
4. **Strict output format** (option 4). Eleven exact CSV columns, including a per-vertex `unit_rate_usd_per_m` (this exposes the lease rule row by row) and separate cumulative construction and haulage. Exact C-002 class names (Response 1 wrote "1 - Grassland / pasture" and "Culvert (…)"). Fixed decimals. GeoPackage attribute fields.
5. **Compliance claims are checked** (N5, −7). A report that says every criterion is met while its files break C1–C7, E1 or E2 is penalised, which is what Response 2 did.

All Rev D traps are retained (C-004 D1–D7, the G1 datum chain, the Table 7 distractors, threshold-band clearing), as are the Rev C traps (14.0 m formation, T3, T4, HS-1, US survey feet, two grids, WGS 84 control points).

## 3. Golden deliverable (upload all three from `golden/`)

- `CB_HaulRoad_Centreline.gpkg`: layer `centreline`, one LineString with 507 vertices, EPSG:32614, fields `route_id = CB-HR-01E`, `total_cost_usd`, `length_m`.
- `CB_HaulRoad_Vertices.csv`: 507 rows, 11 columns exactly as specified.
- `CB_HaulRoad_RouteReport.pdf`: result table, method (including Rev E a–c), rates applied, plan with slip zone and lease edge, long section, breakdowns, control explanation with sensitivity runs, and compliance.

Headline values:

- **Total route cost:** 4,899,457 USD = construction 4,709,286 USD + loaded haulage 190,171 USD (23.77 m of charged loaded rise).
- **Horizontal length:** 6,062.4 m, 507 vertices, 34 deflection vertices.
- **Plateau lease:** 1,826.7 m of the route on leased grassland (at or above 1,500.00 ft = 457.201 m).
- **Start and end cells:** start E 583 155, N 3 349 105 at z 374.54 m; end E 586 455, N 3 350 105 at z 484.97 m. The gate approach runs E 586 495 → E 586 455 along N 3 350 105.
- **Crossing:** approved window **X-2**. **X-1:** no compliant route exists (formation width).
- **Escarpment:** north across the lowland, up the northern slump to N 3 351 495, then south along the plateau to G1.
- **Criteria:** max grade 10.00 % (9.997 %); max loaded uphill grade 5.73 %; min K 1.404 m/%; min tangent between deflections 40.0 m (start 30.0 m, end 40.0 m); longest run steeper than 8 % is 56.6 m (outside the slip zone); longest steep run touching the slip zone is 28.3 m; largest change of direction 45°.
- **Length by land-cover class:** grassland 4,260.2 m, cropland 624.0 m, existing track 573.3 m, woodland 584.9 m, watercourse (culvert) 20.0 m.

Each lever changes the route on its own (from `python3 src/solve.py`):

| Run | Total (USD) | Length (m) | Vertices |
|---|---|---|---|
| **Golden (Rev D drawing set + Rev E a–c)** | **4,899,457** | **6,062.4** | **507** |
| Rev E updates ignored (the Rev D answer) | 3,110,904 | 5,974.5 | 492 |
| (a) lease not applied, or 1,500 compared with metres | 3,158,560 | 6,028.3 | 504 |
| (a) lease applied to all grassland | 6,898,660 | 5,963.8 | 493 |
| (b) 30 m tested only on moves inside the band | 4,891,903 | 6,033.1 | 502 |
| (b) slip zone ignored | 4,859,069 | 6,032.1 | 499 |
| (c) gate approach ignored | 4,871,082 | 6,039.0 | 503 |
| (c) gate approach as 3 moves (30 m) | 4,890,415 | 6,056.5 | 506 |
| (c) approach appended after routing to its start (breaks D6) | 4,897,291 | 6,062.4 | 507 |
| (c) approach read as travelling east | no route | | |
| D3 ignored, or 9.0 % read as grade | 4,866,975 | 6,029.7 | 500 |
| D5 vertical curvature ignored | 4,773,748 | 6,071.7 | 510 |
| D6 radius ignored | 4,784,702 | 6,069.1 | 494 |
| D7 haulage ignored | 4,683,990 | 6,121.8 | 503 |
| D7 charged in chainage direction | 5,752,017 | 6,087.2 | 507 |
| G1 at superseded Rev C position | 4,423,038 | 5,744.7 | 486 |
| EPSG:2277 read as international feet | 5,407,733 | 6,465.5 | 544 |
| G1 SAF ignored (surface used as grid) | no route (approach leaves the DEM) | | |
| T3 sustained grade ignored | 3,821,690 | 4,644.8 | 405 |
| HS-1 exclusion ignored | 2,948,058 | 4,167.8 | 366 |

How robust the answer is: the lease threshold at 1,500.00 ± 0.005 ft, international versus US survey foot for the DEM, the tie-break order, and segment versus vertex clearance testing all give the same route. The closest grassland cell on the route is 0.12 ft from 1,500 ft.

## 4. Key components

1. The total route cost is **4,899,457 USD** (construction 4,709,286 + haulage 190,171) over **6,062.4 m**, with 507 vertices and 34 deflections, crossing at **X-2**.
2. Plateau lease: grassland cells at or above 1,500.00 ft (457.201 m, US survey feet) at 1,300 USD/m, giving 1,826.7 m on the lease; `unit_rate_usd_per_m` shows it per row.
3. Slip zone: any steep run touching N 3 349 600–3 349 800 is at most 30 m over its whole length (golden 28.3 m).
4. Gate: the last four moves run due west into G1, found inside the search so D5/D6 hold at the junction.
5. All Rev D items still hold: loaded direction G1 → T1 with a 6.0 % loaded-uphill cap, K ≥ 1.4, 45 m radius tangents (37.28 / 18.64 m), 8,000 USD/m loaded haulage above 1.0 % grade, and G1 from Table 6 via the SAF and EPSG:2277.
6. All Rev C items still hold: 14.0 m formation (X-1 infeasible), T3 60 m, T4 45°, HS-1 157 m, DEM in US survey feet (first elevation 374.54 m).
7. Exact file names, layer, fields, the 11 CSV columns, C-002 class names, decimals, EPSG:32614, and no earthworks.

## 5. Rubric (77 items)

Weights: +9 ×11, +7 ×27, +5 ×11, +3 ×4, +1 ×19, and 5 penalties (−7, −7, −5, −5, −3). Positive total 374. The golden deliverable scores **100 % (374/374)** with `python3 src/grade.py`. Every geometric item is checked from the delivered files alone. C6 also uses the issued land-cover raster. P1–P20 are golden cell centres placed by `work/calib.py` where the single-rule misses (Rev E and Rev D) leave the golden route.

The full table is in `work/rubric_table.md`; it is generated from `src/grade.py`, so the two always agree. Rev E items:

| # | Wt | Criterion |
|---|---|---|
| E1 | +9 | The last four segments of the GeoPackage centreline each run due west (easting decreasing by 10 m, northing unchanged), ending at the G1 cell. |
| E2 | +9 | In the CSV vertex table, no unbroken sequence of rows with \|grade_to_next_pct\| greater than 8.0 that contains a move with either end row's northing_m between 3 349 600 and 3 349 800 spans more than 30.0 m of chainage. |
| E3 | +9 | In the CSV vertex table, unit_rate_usd_per_m is 1300.00 on every grassland row (any label containing 'grassland') with elev_m at or above 457.20 m (1,500 ft) and 420.00 on every other grassland row (rows within 0.006 m of 457.201 m are not tested). |
| E4 | +7 | The PDF report states a route length on the plateau lease of 1,826.7 m (+/- 0.5 percent). |
| E5 | +3 | The PDF report states that the 1,300 USD/m lease rate replaces the grassland rate only on grassland cells at or above 1,500 ft (457.20 m). |
| E6 | +7 | The PDF report states that the 30 m slip-zone limit applies over the whole length of any steep run that touches the band, including the part outside it. |
| R25 | +9 | The cum_haul_usd value on the last row of the CSV vertex table is 190,171 USD (+/- 0.05 percent). |
| F5 | +3 | The CSV header row is exactly: seq, easting_m, northing_m, elev_m, chainage_m, grade_to_next_pct, landcover_class, unit_rate_usd_per_m, cum_constr_usd, cum_haul_usd, cum_cost_usd. |
| F7 | +5 | Every landcover_class value in the CSV is exactly one of the class names in C-002 Table 2 (for example 'Grassland / pasture'; culvert cells 'Watercourse'), with no codes, prefixes or other labels. |
| F8 | +1 | In the CSV, easting_m, northing_m, chainage_m and the four USD columns have exactly 2 decimals, elev_m and grade_to_next_pct exactly 3 decimals, and no value has a thousands separator. |
| F9 | +1 | On every CSV row cum_cost_usd equals cum_constr_usd plus cum_haul_usd within 1 USD. |
| F10 | +1 | The GeoPackage feature has route_id 'CB-HR-01E', total_cost_usd within 1 USD of the last CSV cum_cost_usd, and length_m within 0.1 m of the last CSV chainage_m. |
| N5 | −7 | The PDF report states that the route meets every criterion, while the delivered files fail at least one of C1 to C7, E1 or E2. |

The Rev D items are unchanged in wording, with values updated to the Rev E golden: R1–R7, R12–R24, P1–P20, C1–C9, S1–S7, F1–F6, N1–N4. C1–C3 are now +5.

How each criterion traces back to the prompt:

- **Total cost and components, length, maximum grade:** R1–R4, R16, R20, R25.
- **Minimum-cost route (one cell per vertex):** R5, R6, P1–P20, R21–R23.
- **Brief updates (a)–(c):** E1 (gate), E2 (slip zone), E3/E4/E5 (lease), E6.
- **End cell (G1 datum chain):** R7, S7. **Start cell and metres:** C8, C9.
- **Every constraint, criterion and cost item on the drawing set:** C1 (D3), C2 (D5), C3 (D6), R24 (D7 charged moves), C4 (T4), C5 (T3), C6/C7 (formation clearances), N1 (T1).
- **What controls the alignment:** S3–S6, R17. **Crossing window and the other window:** R18, S1, S2.
- **Land-cover and lease lengths:** R12–R15, E4.
- **Files and format:** F1–F10. **Scope and consistency:** N2–N5.

## 6. Calibration

### Replays of the two Rev D rollouts under Rev E (`python3 work/score_rollouts.py`)

| Replay | Score |
|---|---|
| Response 1 behaviour: exact Rev D answer, its own labels and rounding | 18.7 % |
| Response 2 behaviour: relaxed path (no D5, D6, T3), updates ignored, claims compliance | 15.0 % |
| **Mean** | **16.8 %** |
| Reference only: every rule right, but Response 1's labels and rounding | 96.3 % |

The reference row shows the limit of any rubric: a response that implements every rule still passes. Rev E only stumps a model that misses at least one of (a)–(c) or a drawing-set rule.

### Simulated single failures (`python3 src/grade.py sim`)

Each case writes complete GeoPackage and CSV deliverables with the solver, then scores them. The claims are generous: the files are perfectly formatted, every rule the case applied is assumed to be explained correctly, and all Rev C items are assumed correct.

| Simulated failure | Total (USD) | Length (m) | Score |
|---|---|---|---|
| A. Rev E updates ignored (exact Rev D answer) | 3,110,904 | 5,974.5 | 20.6 % |
| B. Plateau lease not applied | 3,158,560 | 6,028.3 | 56.1 % |
| C. Lease rate applied to all grassland | 6,898,660 | 5,963.8 | 45.5 % |
| D. Slip-zone 30 m tested only on moves inside the band | 4,891,903 | 6,033.1 | 60.4 % |
| E. Slip-zone limit ignored | 4,859,069 | 6,032.1 | 48.7 % |
| F. Gate approach ignored | 4,871,082 | 6,039.0 | 67.6 % |
| G. Gate approach as 3 moves | 4,890,415 | 6,056.5 | 75.1 % |
| G2. Gate approach appended after routing to its start | 4,897,291 | 6,062.4 | 82.9 % |
| H. Slip zone per move and gate ignored | 4,863,527 | 6,009.7 | 43.9 % |
| I. All but D6 radius | 4,784,702 | 6,069.1 | 37.7 % |
| J. All but D7 haulage | 4,683,990 | 6,121.8 | 39.0 % |
| K. All but D5 vertical curvature | 4,773,748 | 6,071.7 | 61.5 % |
| L. D3 9.0 % read as grade limit | 4,866,975 | 6,029.7 | 43.9 % |
| M. G1 from superseded C-002 Table 3 | 4,423,038 | 5,744.7 | 51.3 % |
| N. D7 rise charged in chainage direction | 5,752,017 | 6,087.2 | 55.3 % |
| O. Rev D relaxed path, updates ignored | 2,524,885 | 4,657.3 | 15.2 % |
| **Mean** | | | **50.3 %** |

Read the two sections together. The observed Rev D failure patterns score 15–21 % under Rev E. A near-perfect response that slips on one rule and is otherwise flawless scores 38–83 %. The gate cases score highest because the gate only changes the last few cells. The single-failure mean is above 40 % because these simulated responses are generous: perfect formatting, full reports, and every other rule right. Real rollouts have been losing labels, rounding and report items as well.

## 7. Judging the rollouts

For each rollout:

1. Read the last five GeoPackage vertices. They should run E 586 495 → 586 455 at N 3 350 105 (E1). An arrival from the north-east is the Rev D ending; any other end point means the G1 datum chain failed (R7).
2. Check the CSV's `unit_rate_usd_per_m` on grassland rows: 1,300.00 at elev ≥ 457.201 m, 420.00 below (E3). All 420 means (a) was missed; all 1,300 means the elevation test was dropped.
3. Find steep runs (|grade| > 8) around N 3 349 600–3 349 800: none may span more than 30 m once it touches the band (E2).
4. Check the rest as for Rev D: grades below −6.00 fail D3 (C1), grade changes above (L1 + L2)/2.8 fail D5 (C2), deflection spacing below 37.28 m or 18.64 m at the ends fails D6 (C3), R24 = number of rows below −1.000.
5. Compare the totals with 4,899,457 / 4,709,286 / 190,171 USD. About 3.11 M is the Rev D answer; about 3.16 M means the lease was missed; about 6.9 M means the lease was applied to all grassland.
6. If the report claims full compliance while any of C1–C7, E1 or E2 fails, apply N5.

Write up each failure with concrete values, the way the Building8 example does.

## 8. Reproducing

```bash
cd src
python3 make_rasters.py     # DEM + land-cover PNGs (threshold-band clearing), published brief values
python3 make_sheets.py      # C-001 to C-004 image-only PDF
python3 solve.py            # golden + every lever/robustness variant (Rev E values in work/prompt_e.json)
python3 make_golden.py      # golden GPKG / CSV / PDF
python3 ../work/calib.py    # checkpoints P1-P20 and grader constants (run from the task root)
python3 grade.py            # golden vs rubric
python3 grade.py sim        # simulated failure calibration
python3 ../work/score_rollouts.py   # replays of the two Rev D rollouts under Rev E
```

Dependencies: Python 3.12, numpy, numba, pillow, pyproj, shapely, geopandas, pyogrio, matplotlib, reportlab, pypdf.
