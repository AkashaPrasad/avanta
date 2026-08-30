# Demo video plan

Hard limit 3:00. Only the first three minutes are evaluated, so nothing is held back for a fourth. Screen recording of the real deployed system at 1920×1080, 30 fps, against `https://avanta.spacesdrive.cc`. No slides, no mockups, no dead air.

The beat structure follows §18 of the brief. Four deliberate adjustments were made, because this build's real behaviour is better than the scripted version and because two of the scripted beats no longer describe what the system does.

**The detection beat is a refusal, not a pass.** The brief has the wind gate passing at 6.4 m/s. The real MSC ELSA 3 scene gates: ERA5 puts the wind above the 10 m/s ceiling at that place and time, the console shows the number that made it gate, and the primary action — *Find candidate vessels* — is correctly disabled with a written reason beneath it. That refusal is the single strongest thing in the build, so it is promoted ahead of everything else and given twenty seconds.

**Attribution is demonstrated on the synthetic ground-truth scenario, and the video says so.** The deployed demo shows detection and honest refusal on the *real* ELSA 3 scene; it shows attribution on the *synthetic discharge* scenario, where a slick was simulated along a known real AIS track under one forcing realisation and attributed under another, so the true answer is known exactly. Both scenario cards carry their own honesty label in the console, and the narration repeats it rather than letting the viewer assume the enforcement case ran on real oil.

**The validation beat now has real numbers to show.** The generated set carries 50 attribution cases and 16 negative controls, and the Calibration route serves computed metrics rather than the unavailable state it showed a day ago. That is worth fourteen seconds: it is the difference between "the method is sound" and "here is what it scored".

**The negative control cannot be triggered by clicking**, because the console runs attribution over every surviving candidate and does not expose per-candidate deselection. It is driven by one API call before recording starts, and the resulting run is opened by URL. The `NO ATTRIBUTION` screen shown is the real one, rendered from a real posterior; the 16-of-16 figure quoted over it comes from the committed validation set, not from that single run.

---

## Before you record

1. **Check the deployed API is answering.** All three of the following must return HTTP 200 before you roll. They did at the time of writing, but the scenario deck is the first thing on screen and a 500 there ends the take.

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' https://avantaapi.spacesdrive.cc/api/v1/health
   curl -s -o /dev/null -w '%{http_code}\n' https://avantaapi.spacesdrive.cc/api/v1/scenarios
   curl -s -o /dev/null -w '%{http_code}\n' https://avantaapi.spacesdrive.cc/api/v1/calibration
   ```

2. **Run the synthetic scenario once on the deployment.** As of this writing the deployed database holds the ELSA 3 scene and nothing else, so the entire attribution half of the script has no run behind it until you create one. Click through `Synthetic discharge` end to end, all the way to a dossier, and leave the resulting run in place. Everything after that is warm.
3. **Warm every cache.** The SAR scene, the ERA5 and current netCDF subsets and the raster PNG are all content-addressed on disk; a warm run is seconds and a cold one is not. A live CDSE request also spends 10.67 processing units you do not need to spend on camera.
4. **Pre-run the negative control.** Take the synthetic run's `scene_id`, then post an attribution run with `candidate_ids` set to the surviving candidates *minus* the true vessel:

   ```bash
   curl -s -X POST "$API/api/v1/attribution/run" \
     -H 'content-type: application/json' \
     -d '{"scene_id":"<scene_id>","candidate_ids":["<other>","<other>"]}'
   ```

   Poll `/api/v1/jobs/{job_id}` until it succeeds, note the run id, and confirm `/attribution/{runId}` shows the `NO ATTRIBUTION` header. Keep the URL in a second browser tab.
5. **Open five tabs in this order**, so no beat costs you a page load: Watch (`/`), About (`/about`), the negative-control run, Calibration (`/calibration`), and the API's `/docs`. Everything else is reached by clicking.
6. **Set the browser to 1920×1080** with no bookmarks bar, dark system theme, extension icons hidden, zoom at 100%.
7. **Rehearse the click path once, timed.** The centrepiece beat is 30 seconds and it is the only one with slack; every other beat is exactly as long as it needs to be.

---

## The 3:00 timeline

| Time | Length | Beat | On screen | Narration |
|---|---|---|---|---|
| 0:00 | 0:14 | **The gap** | Watch. Full-bleed EEZ map, acquisition footprints, the scenario deck with its three data-mode badges. | "Radar sees the slick. It cannot see who put it there. Europe's CleanSeaNet detects a discharge and sends a picture to an analyst — it does not name a vessel. Detection without attribution stops at a photograph." |
| 0:14 | 0:12 | **Why the obvious approach fails** | Click `Method` in the header rail → About. Hold on the forward-versus-reverse diagram. | "The obvious fix is to run the drift backwards. It does not work. Diffusion is a random walk and a random walk has no inverse. And oil weathers, so the slick you reverse is not the slick that was released. So we invert the workflow instead." |
| 0:26 | **0:20** | **It refuses when it cannot answer** | Back to Watch. Click `MSC ELSA 3`. The Scene loads on the real σ⁰ raster. Hold on the wind-gate card with its `GATED` chip, then on the *No dark regions in this scene* panel, then on the disabled primary action. | "This is a real Sentinel-1 scene over the MSC ELSA 3 position, from Copernicus. ERA5 puts the wind above the ten-metre-per-second ceiling where oil still holds radar contrast — the console shows the number that made it gate. The detector then finds nothing, and rather than call that a clean sea, the panel says the absence of detections here carries no information. And the button is disabled: there is no slick to attribute, so there is nothing to accuse anyone of. It is refusing on an image it cannot read." |
| 0:46 | 0:16 | **Detection, with its reasoning** | Watch → `Synthetic discharge`. Scene loads; the wind gate passes. Scroll to `Why each region was classified`. | "Attribution is shown on the synthetic scenario, where the ground truth is exact: a real SAR scene, real AIS tracks, and a slick we simulated ourselves so we know who did it. Inside the detectable band the detector separates sea, oil, look-alikes, ships and land — and every region carries the five tests that classified it, with values, thresholds and weights. Not a confidence score. A reason." |
| 1:02 | 0:14 | **From a crowd to a shortlist** | Click `FIND CANDIDATE VESSELS`. The candidates table renders in place while the attribution job runs behind it; pan across the per-term columns. | "Every AIS track in the window is scored on geometry: perpendicular distance to the slick's own axis, course alignment, whether drift could physically have carried oil across in the time available. That is a feasibility cone, not a reverse trajectory. Every term stays visible — and any radar contact with no AIS at all is kept unconditionally." |
| 1:16 | **0:30** | **The centrepiece** | Attribution. Select the top candidate. Press `Play` on the timeline and let it run once. Then drag the scrubber back and step through the seeding phase by hand. Cycle the overlay toggle: `observed` → `simulated` → `both` → `difference`. | "Now the physics. For each candidate we seed particles along that ship's own AIS track, at that track's own timestamps — a moving line source, which is what a discharge under way actually is. Watch them enter along the track over time, not from a point. OpenDrift's OpenOil model then integrates them forward under real ERA5 wind and real ocean currents, with evaporation and emulsification, to the moment the satellite passed. Observed. Simulated. Both. And the difference — which is what the likelihood actually scores." |
| 1:46 | 0:16 | **An answer with its reasoning attached** | Scroll the ranking so the `H0 — unknown source` row is visible alongside the top candidate. Click `OPEN EVIDENCE BREAKDOWN`; the drawer opens on the signed contribution bars. | "The result is a posterior over every candidate — and over an explicit unknown-source hypothesis that is always in the ranking. Every term is here: coverage of the observed oil, the penalty for simulated oil that landed where none was seen, the ensemble adjustment, and each behaviour-prior feature with its published weight. They sum to the score." |
| 2:02 | 0:14 | **The negative control** | Switch to the pre-loaded tab: the same scene with the true vessel removed. Full-width `NO ATTRIBUTION — insufficient evidence`. | "Take the real source out of the candidate set and ask again. It does not accuse the next ship along. The unknown-source hypothesis wins and the board says so. We ran that sixteen times across the validation set. Sixteen out of sixteen returned no attribution. A tool that cannot say *I don't know* has no business in an enforcement chain." |
| 2:16 | 0:14 | **What it scored** | Calibration tab. Hold on the Brier and ECE tiles and the reliability diagram, then scroll to the note beneath it. | "Fifty cases, each one a slick simulated under one forcing realisation and attributed under another. The true vessel ranks first in forty-nine of the fifty. Brier score 0.006, expected calibration error 0.010. We fitted an isotonic correction on a held-out split, it made both worse, so it is computed, stored and deliberately not applied — and the page says exactly that." |
| 2:30 | 0:16 | **Output an officer can send** | Back to the attribution tab. `GENERATE DOSSIER` → Dossier. Scroll the Appendix 3 fields, pausing on a `NOT AVAILABLE`, then on the provenance block and the manifest hash. Click `DOWNLOAD PDF`. | "The output is a MARPOL Annex I Appendix 3 evidence dossier, laid out field by field against the IMO's own itemised list — identity, position, the slick described in the Appendix's own vocabulary, sea state and wind, method of observation. Anything we cannot fill says NOT AVAILABLE rather than sitting blank. Underneath it: every input by SHA-256, both config files by content hash. Reproducible." |
| 2:46 | 0:10 | **Where it plugs in** | Scroll to the OOSA handoff block on the Dossier screen. | "INCOIS already runs OOSA, a GNOME trajectory model the Coast Guard is trained on. It answers *where will this oil go*, and it cannot start without a release point, which in a routine discharge nobody has. We produce exactly that, in the format it expects." |
| 2:56 | 0:04 | **What is real** | About → the `Runtime capability` panel. Hold still, no scrolling. | "And here is the live capability state, including the parts that are not built. Stated plainly." |

Total 3:00.

---

## Shot list

| # | Shot | Screen | Duration | Capture note |
|---|---|---|---|---|
| 1 | Watch, cold, scenario deck in frame with all three data-mode badges | `/` | 14 s | Do not move the cursor for the first three seconds. Let the map settle. |
| 2 | About, forward-versus-reverse diagram | `/about` | 12 s | Scroll once, slowly, to bring the diagram to centre. Do not scroll past it. |
| 3 | ELSA 3 Scene, wind-gate card with the `GATED` chip | `/scene/:id` | 12 s | The verdict sentence must be legible at 1080p. Hold on it for at least five seconds. Read the speed off the card, not off this document — see the note below. |
| 4 | ELSA 3 Scene, the `No dark regions in this scene` panel and the disabled `FIND CANDIDATE VESSELS` beneath it | same | 8 s | The empty-state body and the greyed control must be in frame together. This is the half of the refusal beat that people miss. Note the body text is the wind-gated variant — *an absence of detections here carries no information* — not the clean-scene variant; if it reads *that is a valid result for a clean scene* you are on the wrong scene. |
| 5 | Synthetic Scene, look-alike reasoning panel | `/scene/:id` | 16 s | Scroll so at least two regions' feature rows are visible together. |
| 6 | Candidates table, terms visible | `/scene/:id?candidates=1` | 14 s | This view is on screen only while the attribution job runs, so the job's own duration is the shot length. Pan horizontally only if the terms do not fit; prefer a wider window. |
| 7 | Attribution, timeline playback | `/attribution/:runId` | 30 s | **The money shot.** One clean full playback, then a manual scrub back through the seeding phase. |
| 8 | Attribution, overlay toggle cycle | same | within shot 7 | Roughly two seconds per state. Land on `difference`. |
| 9 | Attribution, ranking with the H0 row, then the evidence drawer | same | 16 s | The H0 row and the top candidate must be in frame together before the drawer opens. |
| 10 | Negative control, `NO ATTRIBUTION` state | `/attribution/:otherRunId` | 14 s | Pre-loaded tab. Do not show the tab switch as a hunt — one keystroke. |
| 11 | Calibration, metric tiles and reliability diagram, then the note | `/calibration` | 14 s | The note beneath the diagram carries the isotonic-not-applied rationale in the system's own words. Let it be readable for at least four seconds. |
| 12 | Dossier, Appendix 3 fields → provenance → manifest → PDF download | `/dossier/:runId/:mmsi` | 16 s | The PDF is served with a download disposition; let the browser's download indicator appear on camera. |
| 13 | OOSA handoff block | same | 10 s | Steady, no scrolling during narration. |
| 14 | About, `Runtime capability` panel | `/about` | 4 s | Static hold. This is the last frame. The `model` row reads *classical detector (no trained checkpoint loaded)*, which is the point of ending here. |

---

## Exact click path

Recorded as a single continuous take. Every element below is real and present in the built console; the `data-testid` in brackets is the stable hook if you want to script the run rather than drive it by hand. All of them are exercised by the Playwright suite.

1. Open `/`. **Do not click anything for three seconds.** *(shot 1)*
2. Click **`Method`** in the header rail → `/about`. Scroll once to centre the forward-versus-reverse diagram. *(shot 2)*
3. Browser back → `/`. In the scenario deck `[scenario-list]`, click **`MSC ELSA 3`** `[run-scenario-elsa3]`. Wait for the job to settle; the console navigates to the Scene.
4. Hold on the **wind-gate card** `[wind-gate]`. The `GATED` chip, the measured speed, the direction and the 3–10 m/s band are all on it, with the verdict sentence beneath. *(shot 3)*
5. Scroll down the detection rail. The regions panel shows **`No dark regions in this scene`** with the wind-gated body text, and beneath it **`FIND CANDIDATE VESSELS`** `[find-candidates]` is greyed out with *Attribution needs a segmented slick to compare simulations against.* under it. *(shot 4)*

   The console has a second, differently worded refusal for the case where a slick *is* detected on a wind-gated scene — *attribution is disabled on a wind-gated scene: it would rest on a detection the physics does not support* — but the ELSA 3 scene detects zero slicks, so that is not the sentence you will see. Do not narrate it.
6. Browser back → `/`. Click **`Synthetic discharge`** `[run-scenario-synthetic-discharge]`. Wait for the Scene.
7. Scroll to **`Why each region was classified`** `[lookalike-panel]`. *(shot 5)*
8. Click **`FIND CANDIDATE VESSELS`** `[find-candidates]` — enabled here, because this gate passed. Candidates are generated, the Scene switches to the prefilter table with every term, and the attribution job starts immediately behind it. *(shot 6)*
9. When the attribution job settles the console navigates itself to `/attribution/:runId`.
10. In the ranking `[candidate-ranking]`, click the top candidate row `[candidate-row]`.
11. On the timeline `[timeline]`, click **`Play`** and let it run to the end once. Then drag the *Simulation time* slider back to the start and step forward by hand through the seeding phase. *(shot 7)*
12. Cycle the overlay toggle: **`observed`** → **`simulated`** → **`both`** → **`difference`**. *(shot 8)*
13. Scroll the ranking so the **`H0 — unknown source`** row `[h0-row]` is visible alongside the top candidate. Click **`OPEN EVIDENCE BREAKDOWN`** `[open-evidence]`; the drawer `[evidence-drawer]` opens on the signed contribution bars. *(shot 9)*
14. Press **`Escape`** to close the drawer. Switch to the pre-loaded negative-control tab. Hold on **`NO ATTRIBUTION — insufficient evidence`** `[no-attribution]`. *(shot 10)*
15. Switch to the Calibration tab. Hold on the metric tiles and the reliability diagram `[reliability-diagram]`, then scroll to **`What these numbers are computed on`**. *(shot 11)*
16. Switch back to the attribution tab. Click **`GENERATE DOSSIER`** `[generate-dossier]` → `/dossier/:runId/:mmsi`.
17. Scroll the Appendix 3 fields, pausing on one **`NOT AVAILABLE`**, then on the provenance block and the manifest SHA-256. Click **`DOWNLOAD PDF`** `[download-pdf]` and let the browser's download indicator appear. *(shot 12)*
18. Scroll to the **OOSA handoff** block `[oosa-handoff]`. *(shot 13)*
19. Click **`Method`** → `/about`, scroll to the **`Runtime capability`** panel, and hold. **End on this frame.** *(shot 14)*

---

## Rules for the take

**Every number spoken must be a number on screen.** If the run produces a different candidate count or a different probability from the rehearsal, say the number that is showing, not the number that was rehearsed. The point of the whole system is that it reports what it computed.

**Read the wind speed off the card, and know which number you will get.** ERA5 gives 12.07 m/s from 274° at the true acquisition instant, 2025-05-28 00:41:37 UTC. The scene record currently in the deployed database was evaluated at the end of the search window instead and gives 11.15 m/s from 261°. Both are above the 10 m/s ceiling and both gate, so the beat works either way — but the record on the deployment predates a rounding fix, so its large *Speed* statistic reads **11.2** while the verdict sentence directly beneath it reads **11.1**. Say the statistic, do not draw attention to the sentence's copy of it, and if the scene has been re-ingested before you record, expect 12.1 and say that instead.

**Say where each number comes from.** The 98% top-1, the sixteen negative controls and the calibration metrics are all from the *synthetic* validation set — real AIS tracks, a simulated slick. Saying so costs two seconds and is the difference between a defensible claim and an indefensible one.

**Do not say "detects oil spills".** Say what it does: it names a vessel, with a probability, with the reasoning attached, and it declines when it cannot.

**Do not claim the segmenter is learned.** The health endpoint says *classical detector (no trained checkpoint loaded)*, that string is visible in the console, and it is the last thing on screen. Contradicting it on camera costs more than the claim is worth.

**Do not imply AVANTA caught MSC ELSA 3 doing anything illegal.** It was a sinking, the scenario card says so, and the beat is about the refusal rather than the vessel.

**Do not claim NISAR cross-band filtering, multi-scene tracking, CAP alerting or Bonn Agreement volume estimation.** None of them is built, `CAPABILITY_MATRIX.md` marks all four `PLANNED`, and the console deliberately shows no panel for any of them.

**If a job runs long on the day, do not cut to a frozen screen.** The progress rail shows a named stage rather than an indeterminate spinner, and three seconds of *simulating candidate 2 of 4* is a better shot than a jump cut.
