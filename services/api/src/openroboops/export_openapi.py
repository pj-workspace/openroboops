from __future__ import annotations

import json
from pathlib import Path

from .main import app


def run() -> None:
    target = Path(__file__).resolve().parents[4] / "apps" / "web" / "openapi.json"
    target.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    run()
