import json
import tempfile
import unittest
from pathlib import Path

from kb_ai_pipeline.aihub import (
    DatasetPolicyError,
    audit_dataset,
    discover_datasets,
    load_catalog,
    publish_run,
)


class AIHubPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input_root = self.root / "input"
        self.artifact_root = self.root / "artifacts"
        self.input_root.mkdir()
        self.catalog_path = self.root / "datasets.json"
        self.catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "datasets": [
                        {
                            "dataset_key": "test-1",
                            "display_name": "TEST_ONLY",
                            "directory_hint": "sample dataset",
                            "access_status": "TEST_ONLY",
                            "reuse_terms_status": "TEST_ONLY",
                            "allowed_pipeline_use": ["LOCAL_STRUCTURE_AUDIT"],
                            "external_model_prompt_use": "PROHIBITED",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_audit_writes_only_aggregate_artifacts(self) -> None:
        dataset_dir = self.input_root / "aihub-sample dataset"
        dataset_dir.mkdir()
        (dataset_dir / "label.json").write_text(
            '{"account": "123-456-789012"}',
            encoding="utf-8",
        )
        (dataset_dir / "image.png").write_bytes(b"TEST_ONLY_IMAGE")

        records = discover_datasets(
            self.input_root,
            load_catalog(self.catalog_path),
            "SAMPLE",
        )
        result = audit_dataset(records[0], self.artifact_root, "manual:test")
        summary = publish_run(
            [result],
            self.artifact_root,
            "manual:test",
            "SAMPLE",
        )

        audit_payload = json.loads(
            Path(result["artifact_path"]).read_text(encoding="utf-8")
        )
        run_payload = json.loads(
            Path(summary["artifact_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(audit_payload["file_count"], 2)
        self.assertTrue(
            audit_payload["potential_sensitive_data_requires_review"]
        )
        self.assertFalse(audit_payload["raw_content_in_artifact"])
        self.assertNotIn("123-456-789012", json.dumps(audit_payload))
        self.assertEqual(run_payload["dataset_count"], 1)

    def test_external_prompt_permission_fails_closed(self) -> None:
        payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        payload["datasets"][0]["external_model_prompt_use"] = "ALLOWED"
        self.catalog_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(DatasetPolicyError):
            load_catalog(self.catalog_path)

    def test_missing_dataset_is_not_silently_skipped(self) -> None:
        with self.assertRaises(DatasetPolicyError):
            discover_datasets(
                self.input_root,
                load_catalog(self.catalog_path),
                "SAMPLE",
            )


if __name__ == "__main__":
    unittest.main()
