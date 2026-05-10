from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class BenchmarkTarget:
    label: str
    path: str


TARGETS = [
    BenchmarkTarget("/", "/"),
    BenchmarkTarget("/api/schedule", "/api/schedule"),
    BenchmarkTarget("/api/status", "/api/status?page=0&page_size=2"),
    BenchmarkTarget("/api/weather", "/api/weather"),
    BenchmarkTarget("/api/news", "/api/news"),
]


def build_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]

    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return ordered[rank]


def measure_endpoint(session: requests.Session, url: str, iterations: int, timeout: float) -> list[float]:
    timings: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        timings.append((time.perf_counter() - started) * 1000.0)
    return timings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the timetable app endpoints.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="Base URL of the running app")
    parser.add_argument("--iterations", type=int, default=8, help="Number of requests per endpoint")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout in seconds for each request")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = requests.Session()

    print(f"Benchmark target: {args.base_url}")
    print(f"Iterations per endpoint: {args.iterations}")
    print()
    print(f"{'Endpoint':<28} {'avg(ms)':>10} {'p95(ms)':>10} {'max(ms)':>10}")
    print("-" * 60)

    for target in TARGETS:
        url = build_url(args.base_url, target.path)
        timings = measure_endpoint(session, url, args.iterations, args.timeout)
        avg_ms = sum(timings) / len(timings)
        p95_ms = percentile(timings, 95)
        max_ms = max(timings)
        print(f"{target.label:<28} {avg_ms:10.2f} {p95_ms:10.2f} {max_ms:10.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())