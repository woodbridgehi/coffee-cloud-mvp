"""Bounded HTTP capacity probe with percentile and error-rate reporting."""
from __future__ import annotations

import argparse
import asyncio
import math
import time
from dataclasses import dataclass

import httpx


@dataclass
class Result:
    latency: float
    status: int | None
    error: str | None = None


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return math.inf
    values = sorted(values)
    return values[min(len(values) - 1, math.ceil(len(values) * fraction) - 1)]


async def run(base_url: str, path: str, concurrency: int, requests: int, timeout: float) -> list[Result]:
    counter = 0
    counter_lock = asyncio.Lock()
    results: list[Result] = []
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout, limits=limits) as client:
        async def worker() -> None:
            nonlocal counter
            while True:
                async with counter_lock:
                    if counter >= requests:
                        return
                    counter += 1
                started = time.perf_counter()
                try:
                    response = await client.get(path)
                    results.append(Result(time.perf_counter() - started, response.status_code))
                except Exception as exc:
                    results.append(Result(time.perf_counter() - started, None, type(exc).__name__))

        await asyncio.gather(*(worker() for _ in range(concurrency)))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--path", default="/health")
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--requests", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=500)
    args = parser.parse_args()
    if args.concurrency < 1 or args.requests < args.concurrency:
        parser.error("requests must be greater than or equal to positive concurrency")

    started = time.perf_counter()
    results = asyncio.run(run(args.base_url, args.path, args.concurrency, args.requests, args.timeout))
    elapsed = time.perf_counter() - started
    successes = [item.latency for item in results if item.status is not None and 200 <= item.status < 400]
    failures = len(results) - len(successes)
    error_rate = failures / max(1, len(results))
    p50 = percentile(successes, 0.50) * 1000
    p95 = percentile(successes, 0.95) * 1000
    p99 = percentile(successes, 0.99) * 1000
    print(
        f"requests={len(results)} concurrency={args.concurrency} elapsed={elapsed:.3f}s "
        f"rps={len(results) / elapsed:.1f} errors={failures} error_rate={error_rate:.4f} "
        f"p50_ms={p50:.1f} p95_ms={p95:.1f} p99_ms={p99:.1f}"
    )
    if error_rate > args.max_error_rate or p95 > args.max_p95_ms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
