"""Run only the offline CommandCore business simulator."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cfh_disposition.harness.business_simulator import launch, worker  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--tests", nargs="+")
    parser.add_argument("--probe", choices=("network", "production-file", "production-adapter"))
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
    else:
        print(launch(args.tests, probe=args.probe))
