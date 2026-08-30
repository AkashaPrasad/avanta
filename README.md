# AVANTA

**Attribution of marine oil discharges from Sentinel-1 SAR, AIS and forward oil-drift simulation.**
Team Avanta · Smart India Hackathon problem statement SIH26143 · National Technical Research Organisation, Space Technology.

Deployed console: **https://avanta.spacesdrive.cc** · Deployed API: **https://avantaapi.spacesdrive.cc** (`/docs` serves the OpenAPI browser).

---

AVANTA turns a radar image of an oil slick into a ranked, calibrated, evidence-backed accusation. Existing systems detect slicks and hand a picture to a human analyst; they do not name a vessel. AVANTA takes every ship that was in the area, simulates forward the slick each one *would have* left along its own AIS track, compares each simulated slick to the observed one, and returns a probability per vessel with the full reasoning attached — plus an explicit "none of these" hypothesis, so it is able to decline to accuse anyone when the evidence does not support it. The output is a MARPOL Annex I Appendix 3 case file with a reproducibility manifest, not a dot on a map.

## Why the drift runs forwards

The obvious way to find the source of a slick is to run drift in reverse: take the oil you can see, integrate the currents backwards, and look for ships in the resulting origin box. It does not work, for two independent and individually fatal reasons.

The first is that turbulent diffusion is a random walk, and a random walk has no inverse. Running the stochastic term backwards does not retrace the particles' path; it disperses them again. The "origin" a backward run produces is an artefact of the diffusivity coefficient that was chosen, not a place on the sea. Breivik and colleagues set this out for reverse drift with stochastic terms in *Advances in search and rescue at sea* (Ocean Dynamics, 2013), in the search-and-rescue context where the same mathematics applies.

The second is that the slick being reversed is not the slick that was released. Oil evaporates, emulsifies and disperses continuously from the moment it enters the water, so its mass, its area and its drift properties at observation time are not the ones it had at release. Reversing the observed slick reverses the wrong object.

AVANTA therefore never integrates backwards. For each candidate vessel it seeds particles along that vessel's own AIS track, at that track's own timestamps, and integrates *forward* to the acquisition time, then asks how well the resulting slick explains the observation. That is a hypothesis test per vessel, not an inverse problem, and forward integration of a stochastic process is well-posed. The refusal is enforced in code rather than left to convention: `core/simulate/openoil_runner.assert_forward_only` is called on every run, and `tests/unit/test_forward_only.py` additionally greps the whole of `core/simulate` for negative time steps and reversed time arrays.

Two further consequences follow from taking the forward view seriously. A vessel discharging while under way lays oil down along its track at its own speed, so seeding is a **moving line source**, not a point — a point release produces a roughly circular cloud that fits almost any candidate equally well, which is why a point-source fallback here is a bug rather than a simplification. And a candidate that only explains the observation under one lucky wind realisation should not score as if it explained it under all of them, so the likelihood is marginalised over a perturbed-forcing ensemble rather than taking the best member.

## Quickstart from zero

Requires Docker with the Compose plugin. Nothing else — no managed cloud service is involved, which is the point: the same file that runs the demo is the on-premise deliverable.

```bash
cp .env.example .env      # then fill in the keys, see below
docker compose up --build
```

That brings up four services: Postgres (`db`), the API (`api`, port 8000), the built console (`web`, port 5173) and an nginx TLS terminator (`edge`, ports 80/443). The console is then at `http://localhost:5173` and the API at `http://localhost:8000/api/v1/health`. The `edge` service exists only so that a deployed origin can sit behind Cloudflare; on a workstation it can be ignored or removed.

The keys go in `.env`. All of them are free, and every one takes a few minutes of registration that cannot be automated:

| Variable | Source | Needed for | Without it |
|---|---|---|---|
| `CDSE_CLIENT_ID`, `CDSE_CLIENT_SECRET` | dataspace.copernicus.eu → Sentinel Hub → OAuth client | Live Sentinel-1 ingest | Bundled fixture scene and the content-addressed cache still work; the UI badges `FIXTURE` |
| `AISSTREAM_API_KEY` | aisstream.io | Live AIS over websocket | The collector reports `NOT_CONFIGURED` and the bundled AIS capture is used |
| `GFW_API_TOKEN` | globalfishingwatch.org/our-apis | Vessel identity and AIS-off events | Gap features are computed from raw AIS alone; identity fields print `NOT AVAILABLE` |
| `COPERNICUSMARINE_SERVICE_USERNAME`, `..._PASSWORD` | marine.copernicus.eu | CMEMS surface currents | Falls back to the Open-Meteo global ocean model and says so in provenance |
| `CDSAPI_URL`, `CDSAPI_KEY` | cds.climate.copernicus.eu (licence must be accepted in the browser) | ERA5 through the CDS queue | ERA5 is served through the Open-Meteo archive instead, which is the default interactive path anyway |

None of the five is required to get a working result: with an empty `.env` the system runs the bundled MSC ELSA 3 scene and the bundled AIS capture end to end and labels every panel `FIXTURE`.

To run the test suite outside the container:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest       # 104 tests; the network-gated ones skip without credentials
./scripts/verify.sh              # every stage, into reports/verification/<timestamp>/
make lint                        # ruff + mypy + tsc
```

Without credentials the network-gated tests skip loudly with the reason printed rather than passing vacuously: three Global Fishing Watch tests and two live CDSE ingest tests. With credentials and network the suite runs **103 passed / 1 skipped**, or 102 passed / 1 failed / 1 skipped when the Global Fishing Watch gap-events endpoint exceeds its 45-second read timeout, which it did on roughly half the attempts during verification. The one skip is `test_synthetic_set_meets_its_targets`, and it is skipping because its path constant is wrong rather than because the file it wants is absent — `VERIFY.md` records that under AC-12, along with why the Global Fishing Watch failure is more than an ordinary flake.

The browser suite is separate: `cd web && npx playwright test` runs 66 specs across three viewport projects — **198 checks in 53.2 s**, covering the whole Watch → Scene → Attribution → Evidence → Dossier spine, all four async states on all six routes, axe-core accessibility with nothing of critical or serious impact tolerated, keyboard-only traversal and viewport fit at 1440×900, 1024×768 and 768×1024.

## Architecture

```
                          ┌───────────────────────────────────────────────┐
   Copernicus CDSE ──────▶│ core/sar      ingest → cache → preprocess      │
   (Sentinel Hub          │               segment_classical → windgate     │
    Process API)          └──────────────┬────────────────────────────────┘
                                         │  slick / look-alike / ship / land
   Open-Meteo ERA5 ──────▶┌──────────────┴────────────────────────────────┐
   CMEMS / Open-Meteo ───▶│ core/env      wind + currents → CF netCDF      │
   ocean model            └──────────────┬────────────────────────────────┘
                                         │  forcing files, hashed and cached
   aisstream.io ─────────▶┌──────────────┴────────────────────────────────┐
   Global Fishing Watch ─▶│ core/ais      tracks · gaps · dark contacts    │
                          │ core/hypothesis   Stage A geometric prefilter  │
                          └──────────────┬────────────────────────────────┘
                                         │  K survivors + every dark contact
                          ┌──────────────┴────────────────────────────────┐
                          │ core/simulate  moving line source → OpenOil    │
                          │                forward only · 12-member        │
                          │                perturbed-forcing ensemble      │
                          └──────────────┬────────────────────────────────┘
                                         │  particle cloud → rasterised density
                          ┌──────────────┴────────────────────────────────┐
                          │ core/score    likelihood · behaviour prior     │
                          │               posterior with H0 · isotonic     │
                          │               calibration · evidence terms     │
                          └──────────────┬────────────────────────────────┘
                                         │  ranked posterior + every term
                          ┌──────────────┴────────────────────────────────┐
                          │ core/dossier  MARPOL Annex I Appendix 3        │
                          │ core/provenance  SHA-256 manifest, config hash │
                          └──────────────┬────────────────────────────────┘
                                         │
   ┌─────────────────────────────────────┴───────────────────────────────┐
   │ api/  FastAPI · SQLAlchemy · Postgres · thread-pool job runner       │
   └─────────────────────────────────────┬───────────────────────────────┘
                                         │  JSON + provenance on every response
   ┌─────────────────────────────────────┴───────────────────────────────┐
   │ web/  React · Vite · MapLibre · TanStack Query                       │
   │       Watch → Scene → Attribution → Evidence → Dossier               │
   └──────────────────────────────────────────────────────────────────────┘
```

`core/` is importable and testable with no web server and no database. The API is a thin transport over it, and the pipeline spine is `core/pipeline.py`.

## API

Every endpoint is under `/api/v1`. Long-running work returns a `job_id` immediately and is polled or streamed.

| Method | Path | Returns |
|---|---|---|
| `GET` | `/health` | Per-dependency status: db, CDSE, forcing, live AIS collector, segmenter checkpoint, plus `git_sha` and `config_sha` |
| `GET` | `/scenarios` | The three golden scenarios with their honesty labels |
| `POST` | `/scenes/search` | Sentinel-1 acquisitions for a bbox and time window, from the CDSE catalogue |
| `POST` | `/scenes/ingest` | `job_id`; ingests a scene by scenario id or by bbox + window, tracking `LIVE`/`CACHED`/`FIXTURE` |
| `GET` | `/scenes` | Ingested scenes, newest first |
| `GET` | `/scenes/{scene_id}` | Scene metadata, wind-gate verdict with the measured number, provenance block |
| `GET` | `/scenes/{scene_id}/detections` | Slick, look-alike, ship and land regions as RFC 7946 GeoJSON with per-region discriminating features |
| `GET` | `/scenes/{scene_id}/raster.png` | The σ⁰ VV band as a grey PNG for the map base, with `vmin`/`vmax` in dB |
| `GET` | `/scenes/{scene_id}/scene.tif` | The calibrated σ⁰ GeoTIFF itself, for pulling into an existing GIS |
| `POST` | `/candidates/generate` | `job_id`; builds AIS tracks, matches dark radar contacts, runs the geometric prefilter |
| `GET` | `/candidates?scene_id=` | The prefilter table with every geometric term, its value and its score |
| `POST` | `/attribution/run` | `job_id`; forward ensemble over the θ grid for each surviving candidate |
| `GET` | `/attribution/{run_id}` | Posterior including H0, per-candidate evidence breakdown, ensemble spread |
| `GET` | `/attribution/{run_id}/sim/{mmsi}` | Particle positions per output step, for the timeline scrubber |
| `POST` | `/dossier/generate` | Renders the Appendix 3 dossier and returns its field list and manifest hash |
| `GET` | `/dossier/{run_id}/{mmsi}/pdf` \| `/json` \| `/html` | The dossier in each form |
| `GET` | `/calibration` | Reliability bins, Brier score, ECE, isotonic mapping and case count |
| `POST` | `/handoff/oosa` | A GNOME/OOSA-shaped release specification for the selected candidate |
| `GET` | `/jobs/{job_id}` | Status, named stage, progress fraction, log tail |
| `WS` | `/jobs/{job_id}/stream` | The same, pushed every 500 ms until the job settles |

Two departures from the design brief's endpoint list are worth naming. There is no `/{z}/{x}/{y}` XYZ tile service: a single georeferenced PNG plus the GeoTIFF covers the console's needs at this scene size without a tiling pyramid. And there is no `WS /ais/live` proxy: the collector holds one server-side aisstream connection and its state is reported through `/health`, because a browser-facing AIS firehose was not needed by any screen that exists.

## Data sources and attribution

| Source | What it provides | Licence / terms | Honest caveat |
|---|---|---|---|
| **Copernicus Data Space Ecosystem**, Sentinel Hub Process API | Orthorectified, radiometrically calibrated Sentinel-1 IW σ⁰ GeoTIFF (VV, VH, VV−VH, dataMask) | Free account, monthly Processing Unit quota | One 1024×1024 request over the ELSA 3 position costs **10.67 processing units**. Every response is cached by content hash of the request and never re-requested. |
| **Open-Meteo ERA5 archive** | 10 m wind, used for the wind gate and as OpenDrift forcing | Free, keyless, non-commercial | This is the ERA5 reanalysis, served over HTTP instead of through the CDS queue, and it is named as such in provenance. ERA5 lags real time by about five days; for a window inside that lag the code falls back to the **ECMWF IFS analysis/forecast** and the provenance block says so instead of quietly substituting. |
| **Copernicus Marine Service (CMEMS)** | Surface currents (`cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m`) | Free account | The client is implemented and wired, but the credentials supplied for this build are rejected — CMEMS issues a service username distinct from the account e-mail. The system falls back to the **Open-Meteo global ocean model** and reports which source actually answered. |
| **aisstream.io** | Live AIS positions and static data over websocket | Free, server-side connections only | Coverage is crowd-sourced terrestrial receivers. See below. |
| **Global Fishing Watch API v3** | Vessel identity across 40+ public registries; AIS-off (gap) events | Free for non-commercial use | Identity and gap events work; **248 gap events** were found for the Arabian Sea over 2025 during the build. The client requests a single page of 200 events and does not paginate, so a full census needs pagination adding. The SAR fixed-infrastructure dataset returns **HTTP 403** for this token, and the look-alike test reports `infrastructure_distance_km` as *unavailable* rather than assuming no platforms are present. |
| **OpenDrift 1.14.11** — OpenOil, NOAA weathering, ADIOS oil database | The physics | GPLv2 | Forward integration only. |
| **GLOBE global land mask** (via `global-land-mask`) | Land and inland water exclusion, dilated by a 2 km coastal buffer | Public domain | A radiometric test alone cannot tell an inland lake from a slick. |

### Live AIS coverage is not uniform, and it matters

Measured on this build: about **21 position reports per second** over the North Sea against about **0.1 per second** over the Indian west coast. A 35-minute capture over the North Sea recorded **55,102 messages across 5,243 vessels**, of which **43,621 were position reports**, and of those vessels **484** have enough track depth to serve as a moving line source at all. The live scenario over the Indian EEZ can therefore legitimately return an empty candidate set, and the console presents that as a designed state rather than an error.

This is a property of receiver density in a free crowd-sourced network, not of this software. An operational deployment would use satellite AIS or the Indian Coast Guard's own feed, and the system is built so that swapping the AIS source is a change of collector, not a change of method.

## What is real and what is not

Read **[CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md)** before reading anything else. It marks every claim `REAL`, `PARTIAL`, `STUBBED` or `PLANNED` and names the test behind each one, and `scripts/selfcheck.py` fails the build if a `REAL` row cites a test that was not collected — so the file cannot drift from the suite without the harness saying so. **[VERIFY.md](VERIFY.md)** carries the acceptance-criteria table with an honest status per row. **[PROGRESS.md](PROGRESS.md)** is the build log, including the defects found along the way. **[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)** is the three-minute demo plan.

The single most useful thing the system does is refuse. Ask it for the real MSC ELSA 3 scene — Sentinel-1A IW GRDH, product `S1A_IW_GRDH_1SDV_20250528T004137_..._E8F1`, acquired 2025-05-28 00:41:37 UTC — and it fetches the real 1024×1024 σ⁰ raster, then reports:

> **12.1 m/s — above the 10 m/s detection ceiling.** Wind at this speed mixes surface oil into the water column and rebuilds the capillary wave field, so a slick that is present may leave no radar signature.

The measurement is ERA5 through the Open-Meteo archive — 12.07 m/s from 274°, reported to one decimal — and the scene was acquired under south-west monsoon wind. AVANTA declines to make a detection claim on that image. The detector then finds no dark regions, and rather than report a clean sea the console says *the scene is outside the wind band where oil produces radar contrast, so an absence of detections here carries no information* — and the *Find candidate vessels* action is disabled with a written reason beneath it. Where a slick **is** detected on a wind-gated scene the same control is disabled with a different sentence, naming the gate: attribution would rest on a detection the physics does not support. That is the correct answer: outside the 3–10 m/s band a negative radar detection carries almost no information, and a system that reports one as if it did is how a remote-sensing tool loses an analyst's trust. The enforcement case is demonstrated instead on the synthetic scenario, where the ground truth is exact.

## Validation

Attribution is validated on a generated set, because there is no corpus of adjudicated MARPOL discharge prosecutions at a scale that would support anything else. What makes the set worth something is how the cases are built. The AIS tracks are real, captured live from aisstream.io. The slick in each case is simulated along one of those real tracks under **one forcing realisation** and then attributed under **a different one**, so the test is not the code agreeing with itself. Vessels that hug a coastline are excluded, because oil released a few kilometres offshore beaches within hours and leaves nothing to attribute: of the 5,243 vessels in the capture, 484 have enough time depth and movement to serve as a moving line source at all, and **132 of those are at least 25 km offshore**. Those 132 are the population the cases are drawn from.

| Measure | Result |
|---|---|
| Attribution cases | **50** |
| Top-1 accuracy | **98%** — the true vessel ranks first in 49 of 50 |
| The exception | Case 13, where the true vessel ranks second at p = 0.355 behind a decoy at p = 0.644 |
| Negative controls | **16**, each the same case with the true vessel removed from the candidate set |
| Negative controls returning `NO ATTRIBUTION` | **16 of 16**, with p(H0) between 0.9985 and 0.9995 |
| Brier score, raw posterior | **0.0063** on 133 (probability, outcome) pairs |
| Expected calibration error, raw posterior | **0.0099** |
| Isotonic correction | Fitted, stored, and **deliberately not applied** |

The negative-control result is the one that matters most. A system that still confidently names a runner-up once the real culprit is gone was never conditioning its probability on the evidence, only on the shape of the candidate list. Sixteen out of sixteen is the answer this design exists to produce.

**On the calibration, and why the correction is switched off.** Isotonic regression was fitted on one split and scored on a held-out split of 67 pairs, exactly as the brief specifies. It made the numbers **worse** — Brier 0.0149 against the raw 0.0063, ECE 0.0149 against the raw 0.0099 — so `scripts/fit_calibration.py` records `applied: false` and `GET /api/v1/calibration` serves the raw figures. The mapping is stored alongside them for inspection. Shipping a correction that degrades the metric in order to be able to use the word *calibrated* would be the exact kind of decoration this project is trying not to produce.

Two caveats belong with those numbers and are carried in the API response itself, not only here. The first is that the decoys in this set are drawn at random from the offshore population, so the true source usually stands out clearly; a harder set built from near-duplicate tracks — vessels running the same lane minutes apart — would very likely need the isotonic correction that this one does not. Reading 0.0099 as a general property of the method rather than a property of this set would be a mistake. The second is that a Brier score this low partly reflects how decisive the posterior is: the top probability exceeds 0.999 in **48 of the 50 cases**. That is residual softmax saturation. Adjacent pixels of a 10 m SAR image are not independent observations — the errors that matter here are correlated across the whole feature — so a log-likelihood summed over a million cells drives every probability to 0.000 or 1.000. `core/score/likelihood.independent_observations` mitigates it by dividing the log-likelihood by a temperature derived from how many constraints a slick's geometry genuinely supplies, but at this sample size it is a mitigation and not a cure, and the remaining confidence is one more reason to treat the calibration story as unfinished.

The set lives in `fixtures/scenarios/synthetic_set.json` with per-case runtimes, ensemble spreads and posteriors, and the metrics in `fixtures/scenarios/calibration.json`. Both are regenerated by `scripts/make_synthetic_set.py` and `scripts/fit_calibration.py`; `make synthetic` runs the generator at its defaults, which are smaller than the committed set. Note that the set was generated at a reduced configuration — 4 candidates, 4 θ hypotheses, 3 ensemble members — so that 66 runs would complete in under an hour. `config/settings.yaml` ships a 12-member ensemble and a 3 × 4 θ grid, which is what an interactive run uses.

Also worth stating plainly: `test_synthetic_set_meets_its_targets` is the test that would enforce the 98% figure, and it is currently skipping because of a wrong path constant, not because the file is absent. The numbers above were read off the committed set by hand for this document. `VERIFY.md` records that under AC-12 rather than letting the accuracy claim pass as verified when it is not.

## Performance

Budgets live in `config/settings.yaml` under `performance_budgets_s`; they are the numbers the build is held to. Measured figures below were taken on the development workstation (Apple M4 Pro, 12 cores, Python 3.10.11); the container runs Python 3.11. Numbers marked *not measured* are exactly that, and are not estimated.

| Operation | Budget | Measured | Note |
|---|---|---|---|
| Scene read from the content-addressed cache | 1.5 s | **0.05 s** | 1024×1024 four-band float32 GeoTIFF |
| Live CDSE ingest | 25 s | *not measured* | Timing a fresh request spends Processing Unit quota; the cost per request is recorded instead (10.67 PU) |
| Segmentation, classical detector | 6.0 s | **1.13 s** | 1024×1024 scene. The brief's budget is quoted for 2048²; this build's scenes are 1024² |
| Geometric prefilter | 1.5 s | **0.00 s** (harness, 200 vessels) · **0.09 s** measured over 5,243 tracks | 3,881 of those 5,243 carried enough positions to score |
| Full attribution | 90 s | **10.0 s – 87.3 s**, median **49.7 s** | Measured over all 66 runs in the validation set, which was generated at a reduced configuration to keep 66 runs tractable: 4 candidates per case, 4 hypotheses on the θ grid, 3 ensemble members per candidate. `config/settings.yaml` ships `n_ensemble: 12` and a 3 × 4 θ grid, so an interactive run does more work than these figures reflect. **Not** the brief's 6 candidates × 5k particles × 12 members configuration. The top of the range is close to the ceiling and is quoted rather than rounded away |
| Dossier generation | 5.0 s | **0.05 s** | Fields, HTML, manifest and PDF. Measured on the plain PDF path; the container's WeasyPrint path is not separately timed |
| Python test suite | — | **~1 m 45 s** | 104 tests collected |
| Playwright suite | — | **53.2 s** | 198 checks across three viewport projects |

The first six rows come from `scripts/selfcheck.py`, which measures each budgeted operation, fails the build if one is exceeded, separately re-checks the posterior invariants and the forward-only static sweep, and cross-references every `REAL` row of `CAPABILITY_MATRIX.md` against collected test ids. It currently reports **8 of 8 checks passing**. `./scripts/verify.sh` runs it as one stage among nine and writes every stage's output to `reports/verification/<timestamp>/`; `VERIFY.md` records the stage-by-stage result, including the four stages re-run after the last stored sweep.

## Deviations from the design brief, and why

**Redis and Celery were replaced by a thread-pool job runner.** Every job in this system is one CPU-bound pipeline run owned by a single request. There is no fan-out, no second consumer, and no retry semantics worth the name. A `ThreadPoolExecutor` with one worker, writing stage and progress to a Postgres row, does everything a broker would do here — and it removes an entire service from the on-premise deployment, which is the deliverable. See `api/app/jobs.py`.

**The likelihood is not profiled over discharge rate.** The simulated particle density is normalised before it is compared to the observed mask, so scaling the released volume leaves the fit essentially unchanged: rate is only weakly identified from slick geometry. Profiling over it would mean running three identical simulations and reporting them as three distinct hypotheses. The θ grid therefore covers release start and duration, and the configured rate sets the released volume that the dossier and the OOSA handoff carry, reported as an order-of-magnitude estimate rather than a fitted quantity. The reasoning is written into `config/settings.yaml` next to the grid.

**PostGIS is present but not required.** Geometry is stored as RFC 7946 GeoJSON in JSON columns and all spatial computation happens in shapely and numpy inside `core/`. PostGIS is in the compose file so that spatial indexing is available to anyone who later wants to query scenes by area. The image is `imresamu/postgis:16-3.4` rather than the official `postgis/postgis`, because the official image is amd64-only and will not exec on an arm64 host — Graviton or Apple silicon.

**Deployment naming.** The API is served from `avantaapi.spacesdrive.cc`, not `api.avanta.spacesdrive.cc`. Cloudflare's Universal SSL wildcard covers one label only, and Advanced Certificate Manager is not enabled on this zone, so a two-level subdomain could not be issued a certificate. The console is on Cloudflare Pages; the API runs `docker compose` on an AWS EC2 `t4g.large` in `ap-south-1`, behind Cloudflare with nginx terminating TLS at the origin. Both are live and were exercised for this record: `/api/v1/health` reports `status: ok` with `db: UP` and the AIS collector connected, `/api/v1/scenarios` returns all three scenarios with their honesty labels, and `/api/v1/calibration` returns the computed metrics. `docker-compose.yml` still carries `api.avanta.spacesdrive.cc` as the default value of `ORIGIN_HOST`; the environment overrides it in the real deployment, but the default is stale.

## Limitations

These are the things a reviewer should hold against the system, stated before they have to find them.

**The validation set is synthetic.** It is no longer small — 50 attribution cases and 16 negative controls, against the ≥50 the acceptance criteria ask for — but it is still generated, and the figures above measure the method's internal consistency rather than field performance against adjudicated MARPOL prosecutions. The brief's calibration section asks for ≥200 cases and the set has 133 (probability, outcome) pairs, so it is short of that. It is also easier than reality: the decoys are drawn at random from the offshore population, so the true source usually stands out, and a set built from near-duplicate tracks would be a harder and more informative test.

**The test that enforces the accuracy target is not running.** `test_synthetic_set_meets_its_targets` asserts exactly the right thing — top-1 at or above 80%, every negative control passing — but its path constant resolves to a directory that does not exist, so the `skipif` fires on every run and the assertion never executes. The set on disk satisfies it comfortably; nothing in the suite currently checks that it does. A skipped assertion reads as a pass in every summary line, which is precisely the failure mode this project's verification contract exists to catch. The fix is two tokens and it is described in `VERIFY.md` under AC-12.

**The isotonic calibration is computed and switched off.** Fitted on a held-out split it raised Brier from 0.0063 to 0.0149 and ECE from 0.0099 to 0.0149, so `applied` is `false` and the raw posterior is what the API reports. That is the honest choice on this set, but it means the shipped system has no learned correction between its likelihood and its stated probability, and the first genuinely hard validation set will probably need one.

**The segmenter is the deterministic detector, not a learned model.** The Krestenitis et al. (2019) benchmark dataset is distributed on request from a supervisor's institutional address and did not arrive. `core/sar/segment_nn.py` loads `models/segmenter.pt` if it is present and otherwise falls back; the health endpoint and the UI both report *classical detector (no trained checkpoint loaded)*.

**AIS-off events degrade silently when Global Fishing Watch is slow.** `GfwClient.gaps_by_mmsi` catches an unavailable source and returns an empty result, so a read timeout reaches the caller as *there were no gaps* and quietly weakens the `ais_gap_overlap` prior. The same module handles the infrastructure refusal correctly, reporting `unavailable` rather than "none present"; the gap path should do the same. The endpoint exceeded its 45-second timeout on roughly half the attempts made during verification.

**Two smaller blemishes are live on the deployed API.** The image is not built from a git checkout, so `health.git_sha` reads `unavailable` and the manifest's code-revision field degrades to that string rather than a commit. And the ELSA 3 scene record on the server carries a null `product_id` with `acquired_utc` set to the search window's end instead of the acquisition instant, because `data/` is in `.dockerignore` and the `.meta.json` sidecars beside the cached GeoTIFF were never copied into the data volume. The provenance SHA-256 still matches the real Sentinel-1A product, so it is the right scene, but the wind gate was evaluated a day late: it reports 11.2 m/s from 261° where the acquisition instant gives 12.1 m/s from 274°. Both are above the ceiling and the scene gates either way, so the verdict is unaffected — but a missing sidecar should refuse or warn rather than quietly substituting a different time. `VERIFY.md` lists both under *Smaller defects*.

**The ELSA 3 case is a sinking, not a deliberate discharge.** It is used because the position, the time and the vessel identity are all public, which makes it a genuine test of whether forward simulation and scoring recover a source that is already known. AVANTA did not catch MSC ELSA 3 doing anything illegal, and the console says so on the scenario card.

**GFW AIS-off events are an investigative source, not a real-time one.** Coverage runs from 2020 to roughly 72 hours ago.

**The OOSA handoff is a format, not a connection.** `POST /handoff/oosa` emits the release specification GNOME needs, in the shape INCOIS OOSA expects, and checks the release point against the OOSA operational domain (60–100°E, 0–25°N). There is no live link to INCOIS.

## Licence and acknowledgements

Sentinel-1 data is © Copernicus, processed through the Copernicus Data Space Ecosystem. ERA5 and the Copernicus Marine products are Copernicus Climate Change Service and Copernicus Marine Service information respectively, served here through Open-Meteo. AIS position data is from aisstream.io. Vessel identity and AIS-off events are from Global Fishing Watch, used under their non-commercial terms. Drift and weathering physics are OpenDrift's OpenOil model with the NOAA ADIOS oil database.
