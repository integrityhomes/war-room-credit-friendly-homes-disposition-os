"""One read-only scheduled-worker iteration; no scheduler or checkpoint writes."""
import argparse
import json
import os
import tomllib
from pathlib import Path

from cfh_disposition.property_baseline import load_baseline_source
from cfh_disposition.property_change_detection import DetectionState, detect_property_changes
from cfh_disposition.property_sync_preview import read_canonical_records
from supabase import create_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, help="Read a previous hash-only checkpoint; never modify it")
    args = parser.parse_args()
    try:
        secrets = dict(os.environ)
        local = Path(".streamlit/secrets.toml")
        if local.exists():
            secrets.update(tomllib.loads(local.read_text(encoding="utf-8")))
        previous = DetectionState.from_checkpoint(json.loads(args.checkpoint.read_text())) if args.checkpoint else DetectionState()
        rows, source = load_baseline_source(secrets)
        client = create_client(secrets["SUPABASE_URL"], secrets["SUPABASE_SERVICE_ROLE_KEY"])
        result = detect_property_changes(rows, read_canonical_records(client, "properties"), source_reference=source, previous=previous)
        print(json.dumps({"counts": result.counts, "new_events": len(result.new_events), "review_rows": result.review_rows,
                          "records_written": 0, "checkpoint": result.state.checkpoint()}))
    except Exception:
        print(json.dumps({"ok": False, "error": "Complete read-only detection failed; retain the previous checkpoint."}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
