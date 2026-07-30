from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".txt"}
ARCHIVE_SUFFIXES = {".7z", ".gz", ".tar", ".tgz", ".zip"}
SENSITIVE_PATTERNS = {
    "resident_or_foreigner_registration_number_like": re.compile(
        r"(?<!\d)\d{6}-?[1-8]\d{6}(?!\d)"
    ),
    "mobile_phone_number_like": re.compile(
        r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)"
    ),
    "email_address_like": re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    ),
    "hyphenated_account_number_like": re.compile(
        r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,8}(?!\d)"
    ),
}


class DatasetPolicyError(ValueError):
    """Raised when an input violates the declared dataset policy."""


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _safe_run_id(run_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id).strip("._")
    return value or "manual"


def load_catalog(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise DatasetPolicyError("Unsupported dataset catalog schema")
    datasets = payload.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise DatasetPolicyError("Dataset catalog must contain datasets")

    required = {
        "dataset_key",
        "display_name",
        "directory_hint",
        "access_status",
        "reuse_terms_status",
        "allowed_pipeline_use",
        "external_model_prompt_use",
    }
    seen: set[str] = set()
    for dataset in datasets:
        if not isinstance(dataset, dict) or not required <= dataset.keys():
            raise DatasetPolicyError("Dataset catalog entry is incomplete")
        key = str(dataset["dataset_key"])
        if key in seen:
            raise DatasetPolicyError(f"Duplicate dataset key: {key}")
        if dataset["external_model_prompt_use"] != "PROHIBITED":
            raise DatasetPolicyError(
                f"External prompt use must remain prohibited: {key}"
            )
        seen.add(key)
    return datasets


def discover_datasets(
    dataset_root: Path,
    catalog: list[dict[str, Any]],
    data_mode: str,
) -> list[dict[str, Any]]:
    root = dataset_root.resolve()
    if not root.is_dir():
        raise DatasetPolicyError("AIHub dataset root does not exist")
    mode = data_mode.upper()
    if mode not in {"SAMPLE", "FULL"}:
        raise DatasetPolicyError("AIHUB_DATA_MODE must be SAMPLE or FULL")

    directories = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: _normalize(path.name),
    )
    discovered: list[dict[str, Any]] = []
    for policy in catalog:
        hint = _normalize(str(policy["directory_hint"])).casefold()
        matches = [
            path
            for path in directories
            if hint in _normalize(path.name).casefold()
        ]
        if len(matches) != 1:
            raise DatasetPolicyError(
                f"Expected one directory for dataset {policy['dataset_key']}, "
                f"found {len(matches)}"
            )
        discovered.append(
            {
                "dataset_key": str(policy["dataset_key"]),
                "dataset_path": str(matches[0].resolve()),
                "dataset_root": str(root),
                "data_mode": mode,
                "access_status": policy["access_status"],
                "reuse_terms_status": policy["reuse_terms_status"],
                "allowed_pipeline_use": policy["allowed_pipeline_use"],
                "external_model_prompt_use": policy[
                    "external_model_prompt_use"
                ],
            }
        )
    return discovered


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(
        root.rglob("*"),
        key=lambda item: _normalize(str(item.relative_to(root))),
    ):
        if (
            path.is_file()
            and not path.is_symlink()
            and path.name != ".DS_Store"
        ):
            yield path


def _scan_text_file(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    overlap = ""
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            text = overlap + chunk.decode("utf-8", errors="replace")
            overlap_length = len(overlap)
            for name, pattern in SENSITIVE_PATTERNS.items():
                counts[name] += sum(
                    match.end() > overlap_length
                    for match in pattern.finditer(text)
                )
            overlap = text[-128:]
    return counts


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def audit_dataset(
    dataset: dict[str, Any],
    artifact_root: Path,
    run_id: str,
) -> dict[str, Any]:
    root = Path(str(dataset["dataset_root"])).resolve()
    dataset_path = Path(str(dataset["dataset_path"])).resolve()
    if dataset_path == root or root not in dataset_path.parents:
        raise DatasetPolicyError("Dataset path escapes the configured root")
    if dataset["external_model_prompt_use"] != "PROHIBITED":
        raise DatasetPolicyError("External model prompt use is prohibited")

    digest = hashlib.sha256()
    suffix_counts: Counter[str] = Counter()
    sensitive_counts: Counter[str] = Counter()
    file_count = 0
    size_bytes = 0
    archive_count = 0

    for path in _iter_files(dataset_path):
        relative = _normalize(str(path.relative_to(dataset_path)))
        relative_bytes = relative.encode("utf-8")
        digest.update(len(relative_bytes).to_bytes(4, "big"))
        digest.update(relative_bytes)
        file_count += 1
        size_bytes += path.stat().st_size
        suffix = path.suffix.lower() or "[no_suffix]"
        suffix_counts[suffix] += 1
        if suffix in ARCHIVE_SUFFIXES:
            archive_count += 1
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if suffix in TEXT_SUFFIXES:
            sensitive_counts.update(_scan_text_file(path))

    result = {
        "classification": (
            "AIHUB_LIGHTWEIGHT_SAMPLE_LOCAL_AUDIT"
            if dataset["data_mode"] == "SAMPLE"
            else "AIHUB_FULL_DATASET_LOCAL_AUDIT"
        ),
        "dataset_key": dataset["dataset_key"],
        "data_mode": dataset["data_mode"],
        "file_count": file_count,
        "size_bytes": size_bytes,
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "path_and_content_sha256": digest.hexdigest(),
        "sensitive_pattern_counts": {
            name: sensitive_counts[name] for name in SENSITIVE_PATTERNS
        },
        "potential_sensitive_data_requires_review": any(
            sensitive_counts.values()
        ),
        "archive_count": archive_count,
        "archive_content_privacy_review": (
            "REVIEW_REQUIRED" if archive_count else "NOT_APPLICABLE"
        ),
        "image_content_privacy_review": "NOT_AUTOMATED",
        "reuse_terms_status": dataset["reuse_terms_status"],
        "external_model_calls": 0,
        "external_model_prompt_use": "PROHIBITED",
        "raw_content_in_artifact": False,
        "raw_data_committed": False,
    }
    output = (
        artifact_root
        / "dataset-audits"
        / str(dataset["dataset_key"])
        / f"{_safe_run_id(run_id)}.json"
    )
    _write_json_atomic(output, result)
    return {
        "dataset_key": dataset["dataset_key"],
        "artifact_path": str(output),
        "file_count": file_count,
        "size_bytes": size_bytes,
        "potential_sensitive_data_requires_review": result[
            "potential_sensitive_data_requires_review"
        ],
        "archive_content_privacy_review": result[
            "archive_content_privacy_review"
        ],
    }


def publish_run(
    audit_results: list[dict[str, Any]],
    artifact_root: Path,
    run_id: str,
    data_mode: str,
) -> dict[str, Any]:
    ordered = sorted(audit_results, key=lambda item: item["dataset_key"])
    report = {
        "classification": "AIHUB_DATASET_GOVERNANCE_RUN",
        "run_id": run_id,
        "data_mode": data_mode.upper(),
        "dataset_count": len(ordered),
        "total_file_count": sum(item["file_count"] for item in ordered),
        "total_size_bytes": sum(item["size_bytes"] for item in ordered),
        "datasets": ordered,
        "raw_content_in_report": False,
        "external_model_calls": 0,
    }
    output = artifact_root / "runs" / f"{_safe_run_id(run_id)}.json"
    _write_json_atomic(output, report)
    return {
        "artifact_path": str(output),
        "dataset_count": len(ordered),
        "total_file_count": report["total_file_count"],
        "total_size_bytes": report["total_size_bytes"],
    }
