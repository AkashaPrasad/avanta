"""Capture live AIS from aisstream.io into a fixture file.

Run for as long as you can spare: the longer the capture, the more time depth
each track has, and a line source needs a track, not a point.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
import time
from collections import defaultdict
from pathlib import Path

import certifi
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.ais.stream import ship_type_name  # noqa: E402

STREAM_URL = "wss://stream.aisstream.io/v0/stream"


async def capture(api_key: str, bbox: list[float], seconds: float, out: Path) -> None:
    fixes: dict[str, list[dict]] = defaultdict(list)
    static: dict[str, dict] = {}
    ctx = ssl.create_default_context(cafile=certifi.where())
    subscription = json.dumps(
        {
            "APIKey": api_key,
            "BoundingBoxes": [[[bbox[1], bbox[0]], [bbox[3], bbox[2]]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }
    )
    deadline = time.time() + seconds
    received = 0
    async with websockets.connect(STREAM_URL, ssl=ctx, open_timeout=30, ping_interval=20) as ws:
        await ws.send(subscription)
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=min(60.0, max(5.0, deadline - time.time())))
            except TimeoutError:
                continue
            message = json.loads(raw)
            meta = message.get("MetaData") or {}
            mmsi = str(meta.get("MMSI") or "")
            if not mmsi:
                continue
            received += 1
            kind = message.get("MessageType")
            if kind == "ShipStaticData":
                body = (message.get("Message") or {}).get("ShipStaticData") or {}
                dims = body.get("Dimension") or {}
                static[mmsi] = {
                    "name": (body.get("Name") or meta.get("ShipName") or "").strip() or None,
                    "imo": str(body.get("ImoNumber")) if body.get("ImoNumber") else None,
                    "ship_type": ship_type_name(body.get("Type")),
                    "length_m": (dims.get("A", 0) or 0) + (dims.get("B", 0) or 0) or None,
                    "destination": (body.get("Destination") or "").strip() or None,
                }
            elif kind == "PositionReport":
                body = (message.get("Message") or {}).get("PositionReport") or {}
                if meta.get("latitude") is None:
                    continue
                fixes[mmsi].append(
                    {
                        "t": str(meta.get("time_utc")),
                        "lon": float(meta["longitude"]),
                        "lat": float(meta["latitude"]),
                        "sog_kn": body.get("Sog"),
                        "cog_deg": body.get("Cog"),
                    }
                )
            if received % 2000 == 0:
                print(f"  {received} messages, {len(fixes)} vessels, "
                      f"{int(deadline - time.time())}s left", flush=True)

    payload = {
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bbox": bbox,
        "source": "aisstream.io live capture",
        "duration_s": seconds,
        "messages": received,
        "static": static,
        "fixes": {k: v for k, v in fixes.items() if len(v) >= 3},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload), encoding="utf-8")
    kept = payload["fixes"]
    print(f"captured {received} messages -> {len(kept)} vessels with >=3 fixes -> {out}")
    if kept:
        depth = {k: len(v) for k, v in kept.items()}
        top = sorted(depth.items(), key=lambda kv: -kv[1])[:5]
        print("  deepest tracks:", top)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=1200)
    ap.add_argument("--bbox", type=float, nargs=4, default=[68.0, 8.0, 78.0, 24.0],
                    help="lon_min lat_min lon_max lat_max")
    ap.add_argument("--out", type=Path, default=Path("fixtures/ais/arabian_sea_live.json"))
    ap.add_argument("--key", default=None)
    args = ap.parse_args()
    import os

    key = args.key or os.environ.get("AISSTREAM_API_KEY", "")
    if not key:
        raise SystemExit("AISSTREAM_API_KEY not set")
    asyncio.run(capture(key, args.bbox, args.seconds, args.out))


if __name__ == "__main__":
    main()
