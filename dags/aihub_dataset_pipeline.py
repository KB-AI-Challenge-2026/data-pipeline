from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from airflow.sdk import dag, get_current_context, task

from kb_ai_pipeline.aihub import (
    audit_dataset,
    discover_datasets,
    load_catalog,
    publish_run,
)

CATALOG_PATH = Path("/opt/kb-ai/config/datasets.json")
DATASET_ROOT = Path(os.environ.get("AIHUB_DATASET_ROOT", "/opt/kb-ai/input"))
ARTIFACT_ROOT = Path(
    os.environ.get("AIHUB_ARTIFACT_ROOT", "/opt/kb-ai/artifacts")
)
DATA_MODE = os.environ.get("AIHUB_DATA_MODE", "SAMPLE").upper()


@dag(
    dag_id="aihub_dataset_governance",
    description="Audit approved AIHub inputs without emitting raw content",
    schedule=None,
    start_date=datetime(2026, 7, 30, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["aihub", "governance", "local-only"],
)
def aihub_dataset_governance():
    @task
    def discover() -> list[dict]:
        return discover_datasets(
            DATASET_ROOT,
            load_catalog(CATALOG_PATH),
            DATA_MODE,
        )

    @task(max_active_tis_per_dag=3)
    def audit(dataset: dict) -> dict:
        run_id = get_current_context()["run_id"]
        return audit_dataset(dataset, ARTIFACT_ROOT, run_id)

    @task
    def publish(results: list[dict]) -> dict:
        run_id = get_current_context()["run_id"]
        return publish_run(results, ARTIFACT_ROOT, run_id, DATA_MODE)

    publish(audit.expand(dataset=discover()))


aihub_dataset_governance()
