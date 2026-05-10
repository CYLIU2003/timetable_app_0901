from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Sequence

from .cache import FileCacheKey, TtlCache, file_mtime_ns
from .config import SCHEDULE_RESPONSE_TTL_SECONDS

logger = logging.getLogger(__name__)
_schedule_response_cache = TtlCache()
_LABS = ["先発", "次発", "次々発"]


def _day_tag_for_train() -> str:
    return "weekday" if datetime.now().weekday() < 5 else "holiday"


def _day_tag_for_bus_csv() -> str:
    wd = datetime.now().weekday()
    if wd == 5:
        return "saturday"
    if wd == 6:
        return "holiday"
    return "weekday"


def _normalize_text(value: object) -> str:
    text = str(value).strip()
    if text.lower() in {"nan", "na", "<na>", "-", "ー"}:
        return ""
    return text


def _source_key_for_direction(route: dict[str, object], direction: dict[str, object], data_dir: Path, sheet_name_fn: Callable[[str, str | None], str]) -> FileCacheKey:
    route_type = str(route.get("type", ""))
    if route_type == "train":
        path = data_dir / f"timetable_{route.get('line_code', '')}_{_day_tag_for_train()}_{direction.get('dest_tag', '')}.csv"
        return FileCacheKey(str(path), file_mtime_ns(path) if path.exists() else 0)

    if route_type == "bus_csv":
        path = data_dir / f"timetable_BUS_{_day_tag_for_bus_csv()}_{direction.get('dest_tag', '')}.csv"
        return FileCacheKey(str(path), file_mtime_ns(path) if path.exists() else 0)

    path = Path(route.get("file", ""))
    sheet_name = sheet_name_fn(route_type, direction.get("sheet_direction"))
    return FileCacheKey(str(path), file_mtime_ns(path) if path.exists() else 0, sheet_name=sheet_name, column=str(direction.get("column", "")))


def _schedule_cache_key(routes: Sequence[dict[str, object]], data_dir: Path, sheet_name_fn: Callable[[str, str | None], str]) -> str:
    payload: list[dict[str, object]] = []
    for route in routes:
        route_payload = {
            "label": str(route.get("label", "")),
            "type": str(route.get("type", "")),
            "max": int(route.get("max", 0) or 0),
            "walk": int(route.get("walk", 0) or 0),
            "run": int(route.get("run", 0) or 0),
            "directions": [],
        }
        directions_payload: list[dict[str, object]] = []
        for direction in route.get("directions", []):
            if not isinstance(direction, dict):
                continue
            source_key = _source_key_for_direction(route, direction, data_dir, sheet_name_fn)
            directions_payload.append(
                {
                    "column": direction.get("column"),
                    "dest_tag": direction.get("dest_tag"),
                    "sheet_direction": direction.get("sheet_direction"),
                    "source": asdict(source_key),
                }
            )
        route_payload["directions"] = directions_payload
        payload.append(route_payload)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _build_direction_schedules(
    route: dict[str, object],
    direction: dict[str, object],
    remaining_fn: Callable[[str], timedelta],
    fetch_train_schedule_fn: Callable[[str, str], list[dict[str, str]]],
    fetch_bus_schedule_csv_fn: Callable[[str, str], list[dict[str, str]]],
    fetch_bus_schedule_fn: Callable[[str, str, Path], list[str]],
    sheet_name_fn: Callable[[str, str | None], str],
) -> tuple[list[str], list[dict[str, object]]]:
    route_type = str(route.get("type", ""))
    if route_type == "train":
        lst = fetch_train_schedule_fn(str(route.get("line_code", "")), str(direction.get("dest_tag", "")))
    elif route_type == "bus_csv":
        lst = fetch_bus_schedule_csv_fn(route_type, str(direction.get("dest_tag", "")))
    else:
        sheet = sheet_name_fn(route_type, direction.get("sheet_direction"))
        lst = fetch_bus_schedule_fn(sheet, str(direction.get("column", "")), Path(route.get("file", "")))

    filtered: list[tuple[timedelta, dict[str, str] | str, int, str]] = []
    run_threshold = int(route.get("run", 0) or 0)
    for item in lst:
        if isinstance(item, dict):
            current_time_str = str(item.get("time", "")).strip()
        elif isinstance(item, str):
            current_time_str = item.strip()
        else:
            continue

        if not current_time_str:
            continue

        try:
            remaining_time = remaining_fn(current_time_str)
        except Exception:
            continue

        if not (0 < remaining_time.total_seconds() < 86400):
            continue

        minutes = int(remaining_time.total_seconds() // 60)
        if minutes < run_threshold:
            continue
        filtered.append((remaining_time, item, minutes, current_time_str))

    filtered.sort(key=lambda entry: entry[0])

    schedule_lines: list[str] = []
    structured_lines: list[dict[str, object]] = []
    max_count = int(route.get("max", 0) or 0)
    walk_threshold = int(route.get("walk", 0) or 0)

    for index, (_, item, minutes, current_time_str) in enumerate(filtered[:max_count]):
        advice = "walk" if minutes >= walk_threshold else "run"
        advice_label = "歩けば間に合います" if advice == "walk" else "走れば間に合います"
        display_parts = [f"{current_time_str}発"]
        train_type = ""
        destination = ""

        if isinstance(item, dict):
            train_type = _normalize_text(item.get("type", ""))
            destination = _normalize_text(item.get("dest", ""))
            if train_type:
                display_parts.append(f"【{train_type}】")
            if destination:
                display_parts.append(f"{destination}行")

        display_parts.append(f"- {minutes}分 {advice_label}")
        schedule_lines.append(f"{_LABS[index]}: {' '.join(display_parts)}")
        structured_lines.append(
            {
                "rank": _LABS[index],
                "time": current_time_str,
                "type": train_type,
                "destination": destination,
                "minutes": minutes,
                "advice": advice,
                "advice_label": advice_label,
            }
        )

    return schedule_lines, structured_lines


def build_schedule_response(
    routes: Sequence[dict[str, object]],
    data_dir: Path,
    remaining_fn: Callable[[str], timedelta],
    fetch_train_schedule_fn: Callable[[str, str], list[dict[str, str]]],
    fetch_bus_schedule_csv_fn: Callable[[str, str], list[dict[str, str]]],
    fetch_bus_schedule_fn: Callable[[str, str, Path], list[str]],
    sheet_name_fn: Callable[[str, str | None], str],
) -> dict[str, object]:
    cache_key = _schedule_cache_key(routes, data_dir, sheet_name_fn)

    def loader() -> dict[str, object]:
        response = {"current_time": datetime.now().strftime("%H:%M:%S"), "routes": []}

        for route in routes:
            route_entry: dict[str, object] = {"label": route["label"], "schedules": {}, "structured_schedules": {}}
            schedules: dict[str, list[str]] = {}
            structured_schedules: dict[str, list[dict[str, object]]] = {}

            for direction in route.get("directions", []):
                if not isinstance(direction, dict):
                    continue
                direction_label = str(direction.get("column", ""))
                schedule_lines, structured_lines = _build_direction_schedules(
                    route,
                    direction,
                    remaining_fn,
                    fetch_train_schedule_fn,
                    fetch_bus_schedule_csv_fn,
                    fetch_bus_schedule_fn,
                    sheet_name_fn,
                )
                schedules[direction_label] = schedule_lines
                structured_schedules[direction_label] = structured_lines

            route_entry["schedules"] = schedules
            route_entry["structured_schedules"] = structured_schedules
            response["routes"].append(route_entry)

        return response

    return _schedule_response_cache.get_or_set(cache_key, SCHEDULE_RESPONSE_TTL_SECONDS, loader)