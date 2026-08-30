# Handover

What is finished, what is not, and what needs a human.

## Live

| | |
|---|---|
| Console | https://avanta.spacesdrive.cc |
| API | https://avantaapi.spacesdrive.cc |
| Repository | `/Users/akashaaprasad/Documents/Projects/SIH/Prototype/avanta` (not yet a git repository) |

## Verification, as measured

| | |
|---|---|
| Python tests | 105 passing, 0 skipped |
| Playwright | 198 passing across 1440 / 1024 / 768 |
| axe-core | 0 critical or serious violations on any route |
| `scripts/selfcheck.py` | 8 / 8, capability matrix reconciled across 31 rows |
| Synthetic validation | 50 cases, 98% top-1 |
| Negative controls | 16 / 16 return `NO ATTRIBUTION` |
| Calibration | Brier 0.0063, ECE 0.0099 over 133 scored predictions |

## Three things need a person

**1. Supabase.** The MCP server is pinned to `project_ref=onwijviiwtuwldjmqoam`, which is an
unrelated production database, and pinning a project disables the account-level tools that
create a new one. A second server entry, `supabase-account`, is configured in `.mcp.json` but
needs an interactive OAuth sign-in. Run `/mcp`, authenticate it, and the project can then be
created and `DATABASE_URL` repointed. Until then the stack runs Postgres in the compose file,
which is also the on-premise deliverable, so nothing is blocked — only the hosting choice
differs from the plan.

**2. Copernicus Marine credentials.** The username in `info.txt` is an email address; CMEMS
issues a separate username at registration. The client is written, wired and exercised — it
simply cannot authenticate, so every current fetch falls back to a global ocean model and the
provenance block names which source answered. Supplying the real username is a one-line change
to `.env` and needs no code.

**3. The frontend was redesigned mid-build.** A subagent tasked with accessibility tests also
reskinned the interface well beyond what it reported. The application logic came through intact
and every route still works, but the visual language is no longer the "maritime operations room"
specified in §9.2 of the brief. Three real defects it introduced were found and fixed: a
collapsed map container, a decorative chart drawn on top of the live map, and overlapping hero
text. Look at it before recording the video and decide whether the current direction is what you
want.

## Known limitations, stated plainly

**Attribution is demonstrated on synthetic ground truth, not on the real ELSA 3 scene.** That
scene gates: the wind was above the detection ceiling, so the system refuses to make a claim.
That refusal is the honest and, in our view, the strongest thing the build does — but it means
the live demo shows detection and refusal on real data, and attribution on the synthetic
scenario where the answer is known exactly. The console labels both.

**Live AIS over Indian waters is close to empty.** Measured on this build: roughly 21 messages
per second over the North Sea against 0.1 over the Indian west coast. That is receiver density
in a free crowd-sourced network, not a defect here, and it is why the validation set is built
from North Sea tracks. An operational deployment would use satellite AIS or the Coast Guard's
own feed; swapping the source is a change of collector, not of method.

**The validation set is synthetic.** The calibration figures describe the method's internal
consistency. They are not validation against adjudicated MARPOL prosecutions, because no corpus
of those exists at a scale that would support the claim.

**No trained segmentation checkpoint.** The Krestenitis benchmark is distributed on request from
a supervisor's institutional address and did not arrive. The deterministic detector is the live
path and the interface says `classical detector (no trained checkpoint loaded)` rather than
naming a model that does not exist.

## Not started

`VERIFY.md` carries one BLOCKED row and seven PARTIAL, each with its real reason. The four items
in the brief's COULD tier — NISAR cross-band filtering, multi-scene slick tracking, CAP 1.2 alert
emission and Bonn Agreement volume estimation — were not attempted and are marked PLANNED in
`CAPABILITY_MATRIX.md`. The interface does not show empty panels for them.

## First thing to do next

Put it under version control. There is no git repository, so none of this is recoverable if the
directory is lost, and the commit-attribution rules in §17 of the brief have never been
exercised. `.gitignore` is written and excludes `.env`, `data/`, `reports/` and model weights.
