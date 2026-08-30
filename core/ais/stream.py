"""Live AIS collection from aisstream.io.

aisstream refuses direct browser connections and drops messages for any client
that does not consume fast enough, so the socket task does exactly one thing:
put raw frames on a queue. Parsing happens elsewhere.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import certifi
import websockets

from core.ais.tracks import Fix, Track, build_track, utc

log = logging.getLogger(__name__)

STREAM_URL = "wss://stream.aisstream.io/v0/stream"

# AIS ship type codes, per ITU-R M.1371. Only the coarse class matters for the
# behaviour prior, so the 90-odd codes collapse to the categories the prior
# weights are defined over.
SHIP_TYPE_BANDS: list[tuple[int, int, str]] = [
    (30, 30, "fishing"),
    (31, 32, "tug"),
    (33, 35, "cargo"),
    (36, 37, "passenger"),
    (40, 49, "passenger"),
    (50, 59, "tug"),
    (60, 69, "passenger"),
    (70, 79, "cargo"),
    (80, 89, "tanker"),
]


def ship_type_name(code: Any) -> str:
    try:
        value = int(code)
    except (TypeError, ValueError):
        return "unknown"
    for lo, hi, name in SHIP_TYPE_BANDS:
        if lo <= value <= hi:
            return name
    return "unknown"


class AisCollector:
    """Holds one websocket to aisstream and accumulates position fixes.

    Three connections per IP is the documented limit, so exactly one collector
    exists per process and the API proxies to clients from its buffer.
    """

    def __init__(self, api_key: str | None = None, retention_hours: float = 24.0) -> None:
        # None reads the environment; an explicit "" means no key, so an
        # unconfigured collector can be constructed deliberately.
        self.api_key = os.environ.get("AISSTREAM_API_KEY", "") if api_key is None else api_key
        self.retention = timedelta(hours=retention_hours)
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20000)
        self.fixes: dict[str, list[Fix]] = defaultdict(list)
        self.static: dict[str, dict[str, Any]] = {}
        self.connected = False
        self.messages_seen = 0
        self.last_message_utc: datetime | None = None
        self._bbox: list[float] | None = None
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def start(self, bbox: list[float]) -> None:
        if not self.configured:
            log.warning("AISSTREAM_API_KEY not set; live AIS is unavailable")
            return
        self._bbox = bbox
        self._tasks = [
            asyncio.create_task(self._socket(bbox), name="ais-socket"),
            asyncio.create_task(self._drain(), name="ais-drain"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self.connected = False

    async def _socket(self, bbox: list[float]) -> None:
        ctx = ssl.create_default_context(cafile=certifi.where())
        subscription = json.dumps(
            {
                "APIKey": self.api_key,
                "BoundingBoxes": [[[bbox[1], bbox[0]], [bbox[3], bbox[2]]]],
                "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
            }
        )
        backoff = 2.0
        while True:
            try:
                async with websockets.connect(STREAM_URL, ssl=ctx, open_timeout=30) as ws:
                    await ws.send(subscription)
                    self.connected = True
                    backoff = 2.0
                    async for raw in ws:
                        try:
                            self.queue.put_nowait(json.loads(raw))
                        except asyncio.QueueFull:
                            pass  # never block the socket; a dropped frame is cheaper
                            # than a dropped connection
            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on anything
                self.connected = False
                log.warning("AIS socket dropped (%s); reconnecting in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _drain(self) -> None:
        while True:
            message = await self.queue.get()
            try:
                self._ingest(message)
            except Exception as exc:  # noqa: BLE001
                log.debug("skipping malformed AIS frame: %s", exc)

    def _ingest(self, message: dict[str, Any]) -> None:
        kind = message.get("MessageType")
        meta = message.get("MetaData") or {}
        mmsi = str(meta.get("MMSI") or "").strip()
        if not mmsi:
            return
        self.messages_seen += 1

        if kind == "ShipStaticData":
            body = (message.get("Message") or {}).get("ShipStaticData") or {}
            dims = body.get("Dimension") or {}
            self.static[mmsi] = {
                "name": (body.get("Name") or meta.get("ShipName") or "").strip() or None,
                "imo": str(body.get("ImoNumber")) if body.get("ImoNumber") else None,
                "ship_type": ship_type_name(body.get("Type")),
                "length_m": (dims.get("A", 0) or 0) + (dims.get("B", 0) or 0) or None,
                "destination": (body.get("Destination") or "").strip() or None,
            }
            return

        if kind != "PositionReport":
            return
        body = (message.get("Message") or {}).get("PositionReport") or {}
        lat = meta.get("latitude")
        lon = meta.get("longitude")
        if lat is None or lon is None:
            return
        when = utc(meta.get("time_utc") or datetime.now(timezone.utc))
        self.last_message_utc = when
        self.fixes[mmsi].append(
            Fix(
                t=when,
                lon=float(lon),
                lat=float(lat),
                sog_kn=_num(body.get("Sog")),
                cog_deg=_num(body.get("Cog")),
            )
        )
        self._prune(mmsi)

    def _prune(self, mmsi: str) -> None:
        cutoff = datetime.now(timezone.utc) - self.retention
        self.fixes[mmsi] = [f for f in self.fixes[mmsi] if f.t >= cutoff]

    def tracks(self, min_fixes: int = 3) -> list[Track]:
        out: list[Track] = []
        for mmsi, fixes in self.fixes.items():
            if len(fixes) < min_fixes:
                continue
            meta = self.static.get(mmsi, {})
            out.append(
                build_track(
                    mmsi,
                    fixes,
                    name=meta.get("name"),
                    imo=meta.get("imo"),
                    ship_type=meta.get("ship_type", "unknown"),
                    length_m=meta.get("length_m"),
                    source="aisstream.io (live)",
                )
            )
        return out

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "connected": self.connected,
            "bbox": self._bbox,
            "vessels": len(self.fixes),
            "messages_seen": self.messages_seen,
            "last_message_utc": self.last_message_utc.isoformat() if self.last_message_utc else None,
        }


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    # 102.3 is the AIS "not available" sentinel for SOG; 360 for COG.
    return None if out in (102.3, 360.0) else out
