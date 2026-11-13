# PlayNYU facility data

Where the facility data comes from, what it means, and what we checked. This is the written record for #4, #5, #6, #7, #8, #10 and #11.

## Selected dataset (#6)

NYC Open Data **Athletic Facilities** (`qnem-b8re`), published by NYC Parks: facilities designed specifically with sports in mind, one row per facility with per-sport flags, a stable `SYSTEM` ID, and WGS84 coordinates. Some rows are not available for permitting; the dataset does not say which, so the app treats every row as informational until a permit check says otherwise.

Shortlist (#4) and why the others lost:

| Candidate | Verdict |
|---|---|
| Athletic Facilities (`qnem-b8re`) | **Selected.** Per-facility sport flags, stable IDs, coordinates. |
| Parks Properties (`enfh-gkve`) | Rejected. Park-level rows: no per-court/field sports, so it can't answer "where can we play soccer". |
| OpenStreetMap | Rejected. Sport tagging is inconsistent (`sport=soccer` vs `sport=football`, missing courts); no stable IDs for upserts. |
| Manual NYU list | Kept as a supplement, not the base. The city dataset excludes campuses, so NYU venues are compiled by hand (#9). |

## PlayNYU sports and city sport codes (#7)

`seed_league_data` creates these nine sports. City dataset flags map onto them as follows:

| PlayNYU sport | City dataset flag(s) |
|---|---|
| Basketball | `BASKETBALL` |
| Cricket | `CRICKET` |
| Flag football | `FLAGFOOTBALL` |
| Futsal | None (NYU venues only, e.g. Palladium) |
| Pickleball | `Pickleball` |
| Soccer | `REGULATION_SOCCER`, `NONREGULATION_SOCCER` |
| Softball | `ADULT_SOFTBALL`, `LL_SOFTBALL` |
| Ultimate frisbee | `FRISBEE` |
| Volleyball | `VOLLEYBALL` |

Deliberately excluded: baseball (`ADULT_BASEBALL`, little-league flags, `T_BALL`), tennis, bocce, handball, hockey, kickball, lacrosse, netball, rugby, track and field. Baseball diamonds are not softball diamonds, so they don't map to Softball.

## Seed files

- `facilities/data/city_facilities_near_nyu.csv`: 154 active city facilities within 3 km of Washington Square Park that permit a PlayNYU sport. Upsert key is the dataset's `SYSTEM` id (`external_id`), the same key `import_facilities` (#129) uses, so a later full import updates these rows instead of duplicating them.
- `facilities/data/nyu_venues.csv`: 8 NYU and partner venues, compiled by hand. The city dataset doesn't include them.

Sports are linked by name and never created: run `seed_league_data` first. Values with no matching Sport link nothing. Today that drops `Squash`, `Swimming` and `Fitness` on NYU venue rows, which is intended: PlayNYU doesn't offer those sports.

Load order locally and on deploy: `seed_league_data` → `seed_semester_seasons` → `seed_facilities` → `seed_demo_league` (testing site only, when `SEED_DEMO_LEAGUE` is set; it also needs `seed_demo_users`).

## Data dictionary (#11)

`facilities/data/city_facilities_near_nyu.csv` columns:

| Column | Meaning | Example |
|---|---|---|
| `external_id` | Dataset `SYSTEM` id. Unique, stable across exports. | `M116-BASKETBALL-1` |
| `name` | Facility name. Always present. | `ABC Playground – Half Court 1` |
| `address` | Street address. Always present. | `164 ESSEX STREET` |
| `borough` | City borough code: `M` Manhattan, `B` Brooklyn, `Q` Queens, `X` Bronx, `R` Staten Island. | `M` |
| `sports` | PlayNYU sport names, `;`-separated. Every row has at least one. | `Basketball; Volleyball` |
| `latitude` / `longitude` | WGS84 degrees, 6 places. Always both or neither. | `40.721667` / `-73.986114` |

`nyu_venues.csv` has the same columns except `external_id` (empty for NYU rows: the `Facility` model requires a dataset ID only for city rows) and adds `managed_by` (e.g. `NYU`, `Hudson River Park Trust`).

`borough` on the model uses the full names (`manhattan`, `brooklyn`, `queens`, `bronx`, `staten_island`); blank means unknown and stays blank rather than blocking the row.

## Quality analysis (#5)

Audit of the seed files, re-run after every refresh:

- City rows: 154. Missing names, addresses, coordinates, `external_id`: 0. Duplicate `external_id`: 0. Out-of-range coordinates: 0.
- Borough mix: 154 Manhattan (152 coded `M`, 2 fixed by hand, below). Expected: the file is cut to 3 km around Washington Square Park.
- Sport mix: Basketball 90 (incl. 5 shared with Volleyball), Softball 24, Soccer 23 (incl. 2 shared with Ultimate frisbee), Volleyball 20 total, Pickleball 1. No tennis, no baseball: correct per the mapping above.
- NYU rows: 8, all fields complete.

Known gap fixed in this PR: two rows shipped with a blank borough (`M105-SOCCER-3` Sara D. Roosevelt Park soccer, `M082-BASKETBALL-3` Seward Park basketball). Both parks are in Manhattan (verified against nycgovparks.org in #8), so both now read `M`.

## Spot-check near campus (#8)

Checked 12 Nov 2026 against nycgovparks.org and the Parks field/court map:

- Sara D. Roosevelt Park (106 Chrystie St, Manhattan) lists a soccer field, basketball and volleyball courts. Matches the seed row.
- Seward Park (Essex St at E Broadway, Manhattan) lists basketball courts. Matches the seed row.
- ABC Playground half courts (164 Essex St) carry real coordinates in the seed file at the park's block.

Method for future checks: pick a row, confirm the park and amenity on nycgovparks.org, confirm the pin against the address. If a row is wrong, fix the CSV, not the importer.

## Permits and access rules (#10)

From NYC Parks Rule §2-12 and the Field and Court Permits pages:

- Organized league play on a city ballfield or court needs a **written permit** (covers basketball, softball, cricket, volleyball, football, lacrosse, rugby, ultimate frisbee, soccer and other field/court sports). Pickup and informal use need no permit.
- Permits are requested per season through the Field and Court Requests system. Fees are due 14 days before the season start (3 business days if granted later). Tournaments of 3 days or fewer count as short-term permits.
- Permit misuse or unused permitted time is reported to 311.

What this means for PlayNYU: league matches on city fields need permits arranged with NYC Parks; casual pickup doesn't. The app shows facility locations and availability info, not permit status. NYU venues follow NYU athletics booking, not city permits.

## Refreshing the data

1. Download the Athletic Facilities export (CSV or GeoJSON) from NYC Open Data.
2. Keep rows with `FEATURESTATUS` active, within the campus radius, with at least one mapped sport from the table above.
3. `import_facilities` (#129, on `nihal/facility-import` until merged) upserts by `system`; re-running never duplicates.
4. Re-run the quality audit above and record the outcome on the tracking issue.
