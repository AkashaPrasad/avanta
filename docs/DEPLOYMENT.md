# Deployment

AVANTA runs in two places and they are deliberately the same system.

`docker compose up` is the on-premise deliverable: Postgres, the API and an
nginx TLS edge, with no managed cloud service and no external database. The
hosted demo is that same compose file on one AWS instance. Nothing about the
science changes between them; only `DATABASE_URL` and the origin hostname do.

## What is running

| Component | Where | Notes |
|---|---|---|
| Console | Cloudflare Pages, project `avanta` | https://avanta.spacesdrive.cc |
| API | AWS EC2 `t4g.large`, `ap-south-1` | https://avantaapi.spacesdrive.cc |
| Database | Postgres (PostGIS image) in the same compose stack | Swappable for Supabase by changing `DATABASE_URL` |
| TLS edge | nginx in the compose stack | Cloudflare proxies to it over HTTPS |

The API instance is `ap-south-1` (Mumbai) because the problem is Indian
maritime domain awareness and the Copernicus and AIS calls should not cross an
ocean to reach a box that then serves Indian users.

## The API hostname is not `api.avanta.spacesdrive.cc`

It is `avantaapi.spacesdrive.cc`, and the reason is worth recording because it
is not obvious. Cloudflare Universal SSL issues a certificate for the apex plus
a **single-level** wildcard, `*.spacesdrive.cc`. A two-level name such as
`api.avanta.spacesdrive.cc` is not covered by that wildcard, so the edge
terminates the connection with a TLS handshake failure before it ever reaches
the origin — the DNS record resolves and everything looks correct right up to
the point where nothing works. Covering it needs Advanced Certificate Manager,
which is not enabled on this zone. A single-level name avoids the problem
entirely.

## Origin TLS

The zone's SSL mode is **Full**, so Cloudflare connects to the origin over
HTTPS on 443 and does not validate the origin certificate. The `edge` service
generates a self-signed certificate on first boot, which is sufficient for that
mode. For **Full (strict)** the change is to mount a Cloudflare Origin CA
certificate at the same two paths; no configuration in `deploy/edge.conf`
changes.

## Rebuilding the API

    ssh -i ~/.ssh/avanta-key.pem ubuntu@<ip>
    cd /opt/avanta
    docker compose up -d --build api

The image takes roughly fifteen minutes on a cold cache: several scientific
wheels (rasterio, Cartopy, numcodecs, roaring-landmask) have no prebuilt arm64
distribution and are compiled from source. A rebuild that only changes Python
source reuses those layers and takes about a minute.

## Deploying the console

    cd web
    VITE_API_BASE=https://avantaapi.spacesdrive.cc npx vite build
    npx wrangler pages deploy dist --project-name=avanta --branch=main

`VITE_API_BASE` is inlined at build time, not read at runtime, so the console
must be rebuilt if the API moves.

## Two traps worth knowing

**The PostGIS image is amd64-only.** `postgis/postgis` will pull an amd64 image
onto an arm64 host and fail with `exec format error` the moment the container
starts. `imresamu/postgis` is the multi-arch build of the same thing and is what
the compose file uses.

**macOS sidecar files break the image.** Archiving the tree from macOS without
`COPYFILE_DISABLE=1` includes AppleDouble resource forks named `._thing.yaml`.
They are binary, they match a `*.yaml` glob, and they took the scenarios
endpoint down in production while every file looked fine locally. The loader now
skips dotfiles, the archive excludes them and `.dockerignore` lists them, but the
deploy command should still set `COPYFILE_DISABLE=1`.

## Seeding the validation set and calibration

The reliability figures the console shows are computed from real runs, so a
fresh deployment has none until they are generated:

    docker compose exec api python scripts/make_synthetic_set.py \
      --ais fixtures/ais/north_sea_live.json --offshore-km 25
    docker compose exec api python scripts/fit_calibration.py --store

Until that has been run, `/api/v1/calibration` returns 404 and the Calibration
page shows an empty state explaining why — which is the correct behaviour. It
must never show numbers it has not computed.

## Cost and shutdown

The instance is the only meaningful cost. Stopping it when the demo is not
needed costs nothing but the EBS volume:

    aws ec2 stop-instances --instance-ids <id> --profile claude-dev --region ap-south-1

The public IP is not elastic, so restarting the instance changes it and the
`avantaapi` A record has to be updated.
