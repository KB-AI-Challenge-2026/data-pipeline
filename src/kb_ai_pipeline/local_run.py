from __future__ import annotations

import argparse
import json
from pathlib import Path

from kb_ai_pipeline.aihub import (
    audit_dataset,
    discover_datasets,
    load_catalog,
    publish_run,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("config/datasets.json"),
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts"),
    )
    parser.add_argument("--data-mode", choices=("SAMPLE", "FULL"), default="SAMPLE")
    parser.add_argument("--run-id", default="manual-local")
    args = parser.parse_args()

    datasets = discover_datasets(
        args.dataset_root,
        load_catalog(args.catalog),
        args.data_mode,
    )
    results = [
        audit_dataset(dataset, args.artifact_root, args.run_id)
        for dataset in datasets
    ]
    summary = publish_run(
        results,
        args.artifact_root,
        args.run_id,
        args.data_mode,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
