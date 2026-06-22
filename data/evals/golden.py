from __future__ import annotations

import json
from pathlib import Path
from typing import Any


GOLDEN_DATASET_PATH = Path(__file__).with_name("compass_golden_v1.json")


def load_golden_dataset() -> dict[str, Any]:
    return json.loads(GOLDEN_DATASET_PATH.read_text(encoding="utf-8"))
