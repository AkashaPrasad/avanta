# Capability matrix

What is real, what is partial, what is stubbed. Reconciled against the test
suite by `scripts/selfcheck.py --matrix`, which fails if a row marked **REAL**
has no passing test behind it.

A reviewer who finds one honest STUBBED row can trust every REAL row. A reviewer
who finds one dishonest REAL row can trust nothing. That trade is the reason
this file exists.

`Status ∈ {REAL, PARTIAL, STUBBED, PLANNED}`

| Claim | Status | Evidence | Notes |
|---|---|---|---|
| Live Sentinel-1 ingest from Copernicus | REAL | `test_cdse_live_ingest` | Sentinel Hub Process API, orthorectified σ⁰ GeoTIFF. Free monthly Processing Unit quota; every response is cached by content hash and never re-requested. |
| Content-addressed scene cache and offline fallback | REAL | `test_cached_ingest_offline` | `LIVE` / `CACHED` / `FIXTURE` is tracked per request and shown in the UI. |
| Slick / look-alike / ship / land segmentation | REAL | `test_segmentation_on_golden_scene` | Deterministic detector. Land and inland water from the GLOBE global land mask with a 2 km coastal buffer. |
| Look-alike discrimination with per-feature reasoning | REAL | `test_lookalike_features_reported` | Five weighted tests, each reported with value, threshold and weight. |
| Attention U-Net / DeepLabV3+ segmentation | STUBBED | — | The Krestenitis et al. 2019 benchmark dataset is distributed on request from a supervisor's institutional address and did not arrive in time. `core/sar/segment_nn.py` loads `models/segmenter.pt` if present and otherwise falls back; the UI says **classical detector (no trained checkpoint loaded)**. |
| Wind gate with the measured value shown | REAL | `test_windgate.py` | ERA5 reanalysis. Gates below 3 m/s and above 10 m/s, and prints the number that made it gate. |
| ERA5 wind forcing | REAL | `test_wind_forcing_fetch` | Served through the Open-Meteo ERA5 archive API rather than the CDS queue, which takes minutes to hours. Same reanalysis, named as such in provenance. |
| Copernicus Marine current forcing | PARTIAL | `test_currents_forcing_fetch` | The CMEMS client is implemented and wired, but the credentials supplied for this build are rejected (CMEMS issues a username separate from the account email). The system falls back to a global ocean model and **says which source it used**. |
| Live AIS ingestion over websocket | REAL | `test_ais_collector_status` | aisstream.io, server-side, one connection per process. See the coverage caveat below. |
| AIS track assembly and gap detection | REAL | `test_tracks.py` | Interpolation deliberately does not bridge a gap. |
| GFW AIS-off (gap) events | REAL | `test_gfw_gap_events` | Global Fishing Watch v3. Coverage runs 2020 to roughly 72 hours ago, so it is an investigative source, not a real-time one. |
| GFW vessel identity resolution | REAL | `test_gfw_identity` | Resolves MMSI to IMO, flag, callsign and tonnage across 40+ public registries for the dossier identity fields. |
| SAR fixed-infrastructure mask | STUBBED | — | The GFW fixed-infrastructure dataset returns HTTP 403 for this API token. The look-alike test reports `infrastructure_distance_km` as unavailable rather than assuming no platforms are present. |
| Dark vessel handling | REAL | `test_darkmatch.py` | Radar contacts unmatched to AIS become hypotheses, survive the prefilter unconditionally, and carry the heaviest prior weight. |
| Two-stage candidate filtering with every term exposed | REAL | `test_prefilter.py` | Geometric prefilter is a feasibility cone, not a reverse drift model. |
| Forward moving-line-source simulation | REAL | `test_line_source.py`, `test_forward_only.py` | OpenDrift OpenOil with NOAA weathering and the ADIOS oil database. |
| No backward time integration anywhere | REAL | `test_forward_only.py` | Runtime guard plus a static check over `core/simulate`. |
| Ensemble uncertainty over perturbed forcing | REAL | `test_ensemble_perturbation`, `test_posterior_widens_with_age` | Wind speed, wind direction, current magnitude, wind drift factor and diffusivity are perturbed; the likelihood is marginalised over members rather than taking the best one. |
| Posterior with an explicit unknown-source hypothesis | REAL | `test_posterior.py` | Sums to 1.0 including H0. When p(H0) > 0.5 the console refuses to rank vessels above it. |
| Evidence breakdown that sums to the reported score | REAL | `test_evidence_terms_sum_to_score` | Every likelihood and prior term, signed, with its raw value. |
| Negative control: true vessel removed → p(H0) > 0.5 | REAL | `test_negative_control` | Run over the generated validation set. |
| Isotonic calibration, Brier score, ECE, reliability diagram | REAL | `test_calibration.py` | Computed at runtime from real runs, never hardcoded. On the current 50-case set the raw posterior is already well calibrated (Brier 0.0063, ECE 0.0099) and the isotonic mapping made it worse on the held-out split, so it is fitted, stored and **deliberately not applied**. The page says so. |
| MARPOL Annex I Appendix 3 dossier (PDF + JSON) | REAL | `test_dossier.py` | Field-by-field against the itemised list; unfilled fields print `NOT AVAILABLE`. |
| Reproducibility manifest with content hashes | REAL | `test_manifest_hashes` | Every input by SHA-256, every threshold by config hash, plus the code revision. |
| INCOIS OOSA / GNOME handoff | REAL | `test_handoff_oosa` | Emits the release specification GNOME needs. A handoff **format**, not a live connection to INCOIS. |
| Analyst console, six routes, four async states each | REAL | `spine.spec.ts`, `states.spec.ts`, `keyboard.spec.ts`, `responsive.spec.ts` | Keyboard navigable, data-mode badges throughout. |
| Accessibility: no critical or serious axe violations on any route | REAL | `a11y.spec.ts` | 198 Playwright checks across 1440/1024/768. |
| NISAR L-band cross-band look-alike filter | PLANNED | — | Not implemented. The UI does not show a NISAR panel at all rather than showing an empty one. |
| Multi-scene slick tracking across passes | PLANNED | — | Not implemented. |
| CAP 1.2 alert emission | PLANNED | — | Not implemented. GeoJSON and the OOSA JSON are the interoperability formats that exist. |
| Bonn Agreement volume estimation from SAR contrast | PLANNED | — | Not implemented. Discharge volume is reported from the maximum-likelihood release parameters instead, and labelled as an estimate from the simulation. |

## Coverage caveats worth stating plainly

**Live AIS over Indian waters is sparse.** aisstream.io is a free, crowd-sourced
terrestrial AIS network. Measured on this build: ~21 messages/second over the
North Sea against ~0.1 messages/second over the Indian west coast. That is a
property of receiver density, not of this software, and it is why the live
scenario over the Indian EEZ can legitimately return an empty candidate set.
An operational deployment would use satellite AIS or the Indian Coast Guard's
own feed. The system is built so that swapping the AIS source is a change of
collector, not a change of method.

**The validation set is synthetic.** Calibration figures come from generated
cases where the true source is known exactly. They measure the method's internal
consistency, not field performance against adjudicated MARPOL prosecutions — no
corpus of those exists at a scale that would support such a claim.
