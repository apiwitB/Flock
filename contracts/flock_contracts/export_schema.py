"""เขียน JSON Schema ของ Sighting event: python -m flock_contracts.export_schema [path]"""

import json
import sys
from pathlib import Path

from flock_contracts.sighting import SCHEMA_VERSION, SightingEvent


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(f"schema/sighting.v{SCHEMA_VERSION}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = SightingEvent.model_json_schema()
    out.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
