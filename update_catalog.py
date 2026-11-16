#!/usr/bin/env python3
"""Build and append-only refresh the runtime story catalog.

The GitHub Actions workflow runs this with no arguments. It downloads the PRTS
story navigation template, keeps every existing arc/episode in place, appends
new arcs at the end and new episodes at the end of their existing arc, then
writes ``catalog.json``.

Usage:
    python3 update_catalog.py
    python3 update_catalog.py --seed ../tools/story_catalog.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "catalog.json"
NAV_PAGE = "Template:剧情导航"
USER_AGENT = "ArknightsStoryReader/1.0 (catalog publisher)"
API = "https://prts.wiki/index.php?"


def fetch_nav() -> str:
    url = API + urllib.parse.urlencode({"title": NAV_PAGE, "action": "raw"})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"PRTS returned HTTP {response.status}")
        return response.read().decode("utf-8")


def parse_nav(text: str) -> list[dict]:
    arcs: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        if line.startswith("!"):
            match = re.match(r'^!\s*(?:width="(\d+)px"\s*\|)?(.+)$', line)
            if not match:
                continue
            width, value = match.group(1), match.group(2).strip()
            if width == "40":
                if current is not None:
                    current["type"] = value
                continue
            if (
                value
                and value not in ("剧情", "主线", "支线", "特殊")
                and not value.startswith("colspan")
            ):
                current = {"name": value, "type": "其他", "episodes": []}
                arcs.append(current)
            continue
        if current is None or "[[" not in line:
            continue
        for raw in line.split("[["):
            if "]]" not in raw:
                continue
            body = raw.split("]]", 1)[0]
            title, _, label = body.partition("|")
            title = title.strip()
            label = (label or title).strip()
            if not title or title.startswith("剧情一览"):
                continue
            if not title.endswith(("/BEG", "/END", "/NBT")):
                continue
            current["episodes"].append({"title": title, "label": label})
    return [arc for arc in arcs if arc["episodes"]]


def seed_from_local(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("arcs", [])
    arcs = []
    for arc in data:
        arcs.append(
            {
                "name": arc["name"],
                "type": arc.get("type", "其他"),
                "episodes": [
                    {"title": ep["title"], "label": ep["label"]}
                    for ep in arc.get("episodes", [])
                ],
            }
        )
    return arcs


def merge_append_only(existing: list[dict], fresh: list[dict]) -> tuple[list[dict], int]:
    """Keep old order/content; append only new arcs and new episodes."""
    merged = [
        {
            "name": arc["name"],
            "type": arc.get("type", "其他"),
            "episodes": [dict(ep) for ep in arc.get("episodes", [])],
        }
        for arc in existing
    ]
    by_name = {(arc["name"], arc.get("type", "其他")): arc for arc in merged}
    added = 0
    for arc in fresh:
        key = (arc["name"], arc.get("type", "其他"))
        target = by_name.get(key)
        if target is None:
            target = {"name": arc["name"], "type": arc.get("type", "其他"), "episodes": []}
            merged.append(target)
            by_name[key] = target
        known = {ep["title"] for ep in target["episodes"]}
        for episode in arc["episodes"]:
            if episode["title"] not in known:
                target["episodes"].append(dict(episode))
                known.add(episode["title"])
                added += 1
    return merged, added


def load_existing() -> list[dict]:
    if not CATALOG.exists():
        return []
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return data.get("arcs", [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, help="seed from tools/story_catalog.json")
    args = parser.parse_args()

    if args.seed:
        arcs = seed_from_local(args.seed)
        existing = []
    else:
        existing = load_existing()
        if not existing and not CATALOG.exists():
            print("catalog.json not found; use --seed once or upload an initial catalog", file=sys.stderr)
            return 2
        try:
            fresh = parse_nav(fetch_nav())
        except Exception as exc:
            print(f"catalog refresh failed: {exc}", file=sys.stderr)
            return 1
        arcs, added = merge_append_only(existing, fresh)
        if added == 0 and existing:
            print("catalog unchanged")
            return 0

    episodes = sum(len(arc["episodes"]) for arc in arcs)
    revision = int(time.time())
    payload = {
        "format": 1,
        "revision": revision,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "PRTS Wiki " + NAV_PAGE,
        "arc_count": len(arcs),
        "episode_count": episodes,
        "arcs": arcs,
    }
    CATALOG.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {CATALOG.name}: {len(arcs)} arcs, {episodes} episodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
