from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("DEVICE_TOKEN", "openapi-device-token-at-least-24-characters")
os.environ.setdefault("ADMIN_TOKEN", "openapi-admin-token-at-least-24-characters")

from app.main import app  # noqa: E402


TARGET = ROOT / "openapi" / "openapi.json"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(TARGET)


if __name__ == "__main__":
    main()
