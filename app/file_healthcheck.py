"""Validate process-owned health files without depending on another container."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(2)
    kind, filename = sys.argv[1:]
    payload = json.loads(Path(filename).read_text(encoding="utf-8"))
    if time.time() - float(payload["updatedAt"]) > 20:
        raise SystemExit(1)
    if kind == "gateway":
        healthy = (
            payload.get("connected") and payload.get("subscribed") and payload.get("workersAlive")
            and payload.get("commandWorkerAlive") and payload.get("supervisorAlive")
        )
    elif kind == "domain":
        workers = payload.get("workers") or {}
        now = time.time()
        offline = payload.get("offline", {})
        healthy = offline.get("alive") and offline.get("lastSuccessAt", 0) > now - 60 and workers and all(
            value.get("alive") and value.get("lastSuccessAt", 0) > now - 60
            for value in workers.values()
        )
    else:
        raise SystemExit(2)
    if not healthy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
