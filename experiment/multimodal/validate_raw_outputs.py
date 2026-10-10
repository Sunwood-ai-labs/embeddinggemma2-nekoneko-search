"""Verify raw native benchmark artifacts without computing evaluation metrics."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


RUN_DIR = Path(__file__).resolve().parent
REPO_DIR = RUN_DIR.parent
ATTEMPT_ID = os.environ.get("VALIDATION_ATTEMPT_ID", "attempt-01")
MANIFEST_NAME = os.environ.get("VALIDATION_MANIFEST_NAME", "run_manifest.json")
OUT = RUN_DIR / "results" / ATTEMPT_ID
REPORT_PATH = OUT / "raw-record-validation.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise RuntimeError(f"Non-object JSONL record at {path.name}:{line_no}")
        records.append(record)
    return records


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def check_rankings(records: list[dict[str, Any]], split: str, query_count: int) -> dict[str, Any]:
    failures: list[str] = []
    for row_no, row in enumerate(records, 1):
        if row.get("status") != "ok":
            failures.append(f"{split} record {row_no} has status={row.get('status')}")
        chunks = row.get("chunk_ranking")
        assets = row.get("asset_ranking")
        if not isinstance(chunks, list) or len(chunks) != 63:
            failures.append(f"{split} record {row_no} has {len(chunks) if isinstance(chunks, list) else 'no'} chunks")
            continue
        if not isinstance(assets, list) or len(assets) != 14:
            failures.append(f"{split} record {row_no} has {len(assets) if isinstance(assets, list) else 'no'} assets")
        if [item.get("rank") for item in chunks] != list(range(1, 64)):
            failures.append(f"{split} record {row_no} chunk ranks are incomplete or out of order")
        if isinstance(assets, list) and [item.get("rank") for item in assets] != list(range(1, 15)):
            failures.append(f"{split} record {row_no} asset ranks are incomplete or out of order")
        for item in chunks:
            score = item.get("score")
            if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                failures.append(f"{split} record {row_no} has invalid chunk score")
                break
            if not all(key in item for key in ("asset_id", "source_path", "modality", "locator", "input_representation")):
                failures.append(f"{split} record {row_no} has incomplete source metadata")
                break
    return {"record_count": len(records), "query_count_expected": query_count, "ranking_failures": failures}


def main() -> None:
    manifest_path = RUN_DIR / MANIFEST_NAME
    source_manifest_path = RUN_DIR / "run_manifest.json"
    index_path = RUN_DIR / "index.jsonl"
    manifest = read_json(manifest_path)
    source_manifest = read_json(source_manifest_path)
    result = read_json(OUT / "run-result.json")
    runtime = read_json(OUT / "runtime.json")
    original_failure = read_json(OUT / "run-result-before-query-mount-recovery.json")
    recovery = read_json(OUT / "recovery-note.json")
    dev_records = read_jsonl(OUT / "dev-query-results.jsonl")
    test_records = read_jsonl(OUT / "test-query-results.jsonl")
    doc_timings = read_jsonl(OUT / "document-embedding-timings.jsonl")
    doc_errors_path = OUT / "index-embedding-errors.jsonl"

    manifest_sha = sha256_file(manifest_path)
    index_sha = sha256_file(index_path)
    vector_sha = sha256_file(OUT / "index-vectors.npy")
    evaluation_contract_path = RUN_DIR / "verification" / "evaluation-contract.json"
    aggregation_contract_path = RUN_DIR / "analysis" / "aggregation-contract.json"
    runtime_probe_path = RUN_DIR / "container-runtime.json"
    evaluation_contract_sha = sha256_file(evaluation_contract_path)
    aggregation_contract_sha = sha256_file(aggregation_contract_path)
    runtime_probe_sha = sha256_file(runtime_probe_path)
    runtime_probe = read_json(runtime_probe_path)
    source_manifest_sha = sha256_file(source_manifest_path)

    require(manifest["status"] == "locked_before_model_evaluation", "Run manifest is not marked locked")
    require(result["status"] == "complete", f"Recovered run status is {result['status']}")
    require(result["attempt_id"] == ATTEMPT_ID, "Run-result attempt ID differs from selected attempt folder")
    require(result["manifest_sha256"] == manifest_sha, "Run-result manifest SHA mismatch")
    require(runtime["manifest_sha256"] == manifest_sha, "Runtime manifest SHA mismatch")
    require(result["index_sha256"] == index_sha, "Run-result source-index SHA mismatch")
    require(result["vector_file_sha256"] == vector_sha == runtime["vector_file_sha256"], "Vector file SHA mismatch")
    require(result["evaluation_contract_sha256"] == evaluation_contract_sha == manifest["contracts"]["evaluation"]["sha256"], "Evaluation contract SHA mismatch")
    require(result["aggregation_contract_sha256"] == aggregation_contract_sha == manifest["contracts"]["aggregation"]["sha256"], "Aggregation contract SHA mismatch")
    require(result["source_document_manifest_sha256"] == source_manifest_sha == original_failure["manifest_sha256"], "Reused document index source-manifest SHA mismatch")
    require(manifest["inputs"] == source_manifest["inputs"] and manifest["index"] == source_manifest["index"] and manifest["model"] == source_manifest["model"], "Formal query manifest changed frozen source/index/model conditions")
    require(manifest["runtime"]["sha256"] == source_manifest["runtime"]["sha256"] == runtime_probe_sha, "Same-image runtime probe SHA differs between manifests")
    require(runtime_probe["torch_threads"] == 4 and manifest["runtime"]["torch_threads_from_same_image_runtime_probe"] == 4, "Same-image runtime probe does not confirm four PyTorch threads")
    require(result["query_counts"]["dev_records"] == 15 and result["query_counts"]["dev_errors"] == 0, "Dev query counts/errors mismatch")
    require(result["query_counts"]["test_records"] == 180 and result["query_counts"]["test_errors"] == 0, "Test query counts/errors mismatch")
    require(runtime["torch_threads"] == 4, f"Expected four actual PyTorch threads, got {runtime['torch_threads']}")
    require(runtime["first_test_call_is_cold"] is False, "First test call is incorrectly marked as a cold model run")
    require(len(dev_records) == 15 and len(test_records) == 180, "Raw JSONL line counts differ from run result")
    require(len(doc_timings) == 63 and all(row["status"] == "ok" for row in doc_timings), "Document embedding records incomplete")
    require(doc_errors_path.stat().st_size == 0, "Document embedding errors file is nonempty")
    require(original_failure["status"] == "fatal_error" and "queries-dev.jsonl" in original_failure["error"], "Original pre-query failure record not preserved")
    require(recovery["initial_queries_executed"] == 0 and recovery["document_embeddings_repeated"] is False, "Recovery note does not document query-only resumption")

    allowed_assets = {asset["asset_id"]: asset["path"] for asset in manifest["inputs"]["assets"]}
    for split, rows in (("dev", dev_records), ("test", test_records)):
        for row in rows:
            require(row["manifest_sha256"] == manifest_sha, f"{split} record references a different manifest")
            require(row["index_sha256"] == index_sha, f"{split} record references a different source index")
            require(row["model_revision"] == manifest["model"]["revision"], f"{split} record references a different model revision")
            require(row["prompt_name"] == "QuestionAnswering" and row["prompt_text"] == "task: question answering | query: ", f"{split} record prompt mismatch")
            for item in row["chunk_ranking"]:
                require(allowed_assets.get(item["asset_id"]) == item["source_path"], f"{split} result references a source outside the allowlist")

    require([row["canonical_order"] for row in dev_records] == list(range(1, 16)), "Dev query canonical order is incorrect")
    require([row["test_call_order"] for row in test_records] == list(range(1, 181)), "Test call order is incomplete or incorrect")
    require([row["repetition"] for row in test_records] == [1] * 60 + [2] * 60 + [3] * 60, "Test repetition order is incorrect")
    require([row["canonical_order"] for row in test_records] == list(range(1, 61)) * 3, "Test canonical question order changed across repetitions")
    require(sum(bool(row["is_first_test_call"]) for row in test_records) == 1 and test_records[0]["is_first_test_call"], "First test call marker mismatch")
    require(result["query_counts"]["test_first_call_query_id"] == test_records[0]["query_id"], "First test call ID mismatch")

    query_hashes: dict[str, Any] = {}
    for split in ("dev", "test"):
        expected = manifest["inputs"]["queries"][split]["sha256_from_evaluation_contract"]
        recorded = result[f"{split}_query_sha256"]
        require(recorded == expected, f"Run-result {split} query SHA differs from frozen contract")
        relative = manifest["inputs"]["queries"][split]["path"]
        actual_path = REPO_DIR / "multimodal-benchmark" / Path(relative).relative_to("multimodal-benchmark")
        actual = sha256_file(actual_path)
        require(actual == expected, f"Actual {split} query file SHA differs from locked contract")
        query_hashes[split] = {"path": relative, "sha256": actual, "expected_sha256": expected, "match": True}

    dev_check = check_rankings(dev_records, "dev", 15)
    test_check = check_rankings(test_records, "test", 60)
    require(not dev_check["ranking_failures"] and not test_check["ranking_failures"], "Raw ranking structural validation found failures")
    require(recovery["frozen_index_sha256"] == index_sha, "Recovery note source index SHA mismatch")

    report = {
        "schema": "embeddinggemma2-raw-record-validation/v1",
        "status": "pass",
        "checked_at": "2026-10-10",
        "manifest_sha256": manifest_sha,
        "source_document_manifest_sha256": source_manifest_sha,
        "evaluation_contract_sha256": evaluation_contract_sha,
        "aggregation_contract_sha256": aggregation_contract_sha,
        "source_index_sha256": index_sha,
        "vector_file_sha256": vector_sha,
        "query_file_hashes": query_hashes,
        "input_count": manifest["inputs"]["input_count"],
        "chunk_count": manifest["index"]["chunk_count"],
        "document_embedding_records": len(doc_timings),
        "document_embedding_errors": 0,
        "native_smoke_rss_after_smokes_bytes": manifest["model"]["native_smoke_rss_after_smokes_bytes"],
        "native_smoke_cgroup_peak_bytes": manifest["model"]["native_smoke_cgroup_peak_bytes"],
        "original_document_container_process_max_rss_bytes": original_failure.get("process_max_rss_bytes"),
        "original_document_container_cgroup_peak_bytes": original_failure.get("cgroup_peak_bytes"),
        "query_container_process_max_rss_bytes": runtime["process_max_rss_bytes_query_container"],
        "query_container_cgroup_peak_bytes": runtime["cgroup_peak_bytes_query_container"],
        "dev": dev_check,
        "test": test_check,
        "first_test_call": {
            "query_id": test_records[0]["query_id"],
            "elapsed_ms": test_records[0]["elapsed_ms"],
            "is_cold_model_run": False,
        },
        "query_model_load_seconds": result["query_container_model_load_seconds"],
        "recovery_record": str(recovery.get("schema")),
        "accuracy_metrics_computed": False,
        "gold_content_read": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "dev_records": len(dev_records),
        "test_records": len(test_records),
        "test_repetitions": 3,
        "chunk_rankings_per_call": 63,
        "asset_rankings_per_call": 14,
        "query_hashes_match": True,
        "manifest_sha256": manifest_sha,
        "index_sha256": index_sha,
        "report": str(REPORT_PATH),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
