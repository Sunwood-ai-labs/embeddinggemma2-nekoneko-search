"""Resume only the query stage after a pre-query mount-path failure."""

from __future__ import annotations

import json
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import run_experiment as runner


RUN_ROOT = runner.RUN_ROOT
OUT = runner.OUTPUT_ROOT
INITIAL_RESULT = OUT / "run-result.json"
FAILED_RESULT_COPY = OUT / "run-result-before-query-mount-recovery.json"
RECOVERY_NOTE = OUT / "recovery-note.json"
RUNTIME_PATH = runner.RUNTIME_PATH
RUN_RESULT_PATH = runner.RUN_RESULT_PATH
SOURCE_MANIFEST_PATH = RUN_ROOT / "run_manifest.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    started = time.perf_counter()
    runner.WALL_START = started
    require(OUT.is_dir(), f"Expected existing completed embedding attempt: {OUT}")
    require(INITIAL_RESULT.is_file(), "Missing initial run result")
    initial_result = read_json(INITIAL_RESULT)
    require(initial_result.get("status") == "fatal_error", "Initial attempt is not a preserved fatal pre-query result")
    require("/benchmark/run/queries-dev.jsonl" in initial_result.get("error", ""), "Failure was not the expected query mount path issue")
    require(not FAILED_RESULT_COPY.exists(), f"Refusing to overwrite preserved failure: {FAILED_RESULT_COPY}")
    for path in (runner.DEV_RESULTS_PATH, runner.TEST_RESULTS_PATH, RECOVERY_NOTE):
        require(not path.exists(), f"Refusing to overwrite an existing query-stage output: {path}")

    manifest, chunks, manifest_sha, index_sha = runner.load_locked_inputs()
    source_manifest = read_json(SOURCE_MANIFEST_PATH)
    source_manifest_sha = runner.sha256_file(SOURCE_MANIFEST_PATH)
    require(source_manifest_sha == initial_result.get("manifest_sha256"), "Source manifest SHA differs from the preserved initial embedding failure")
    require(index_sha == initial_result.get("index_sha256"), "Frozen chunk index changed since original embedding run")
    require(manifest_sha != source_manifest_sha, "Formal query attempt must use the separately frozen current-contract manifest")
    require(manifest["contracts"]["evaluation"]["sha256"] == source_manifest["contracts"]["evaluation"]["sha256"], "Evaluation contract changed since source indexing")
    require(manifest["contracts"]["research"]["sha256"] == source_manifest["contracts"]["research"]["sha256"], "Research contract changed since source indexing")
    require(manifest["contracts"]["aggregation"]["sha256"] != source_manifest["contracts"]["aggregation"]["sha256"], "Expected current aggregation contract to differ from the source manifest")
    require(runner.sha256_file(RUN_ROOT / "verification" / "evaluation-contract.json") == manifest["contracts"]["evaluation"]["sha256"], "Current evaluation contract SHA differs from the formal manifest")
    require(runner.sha256_file(RUN_ROOT / "analysis" / "aggregation-contract.json") == manifest["contracts"]["aggregation"]["sha256"], "Current aggregation contract SHA differs from the formal manifest")
    for section in ("inputs", "index", "model", "embedding_protocol", "evaluation_protocol"):
        require(manifest[section] == source_manifest[section], f"Formal manifest changed source-indexing condition section: {section}")
    for key in ("packages", "ffmpeg_version", "ffprobe_version", "cpu_model", "logical_cpus_visible", "process_affinity_cpu_count", "container_cpu_limit_cores", "container_memory_limit_bytes", "network_mode", "cgroup_cpu_max"):
        require(manifest["runtime"].get(key) == source_manifest["runtime"].get(key), f"Runtime condition changed since source indexing: {key}")
    runtime_probe_path = RUN_ROOT / "container-runtime.json"
    runtime_probe = read_json(runtime_probe_path)
    runtime_probe_sha = runner.sha256_file(runtime_probe_path)
    require(source_manifest["runtime"]["sha256"] == manifest["runtime"]["sha256"] == runtime_probe_sha, "Same-image runtime probe file changed since source indexing")
    require(runtime_probe["torch_threads"] == 4 and manifest["runtime"]["torch_threads_from_same_image_runtime_probe"] == 4, "Same-image runtime probe does not confirm four PyTorch threads")
    index_runner_source = (RUN_ROOT / "run_experiment.py").read_text(encoding="utf-8")
    compose_source = (RUN_ROOT / "compose.yaml").read_text(encoding="utf-8")
    require("torch.set_num_threads(TORCH_THREADS)" in index_runner_source and runner.TORCH_THREADS == 4, "Source indexing runner no longer sets four PyTorch threads before model load")
    require('TORCH_THREADS: "4"' in compose_source, "Compose no longer fixes TORCH_THREADS to four")

    timings = read_jsonl(runner.DOC_TIMINGS_PATH)
    require(len(timings) == len(chunks), f"Expected one successful embedding record per chunk: {len(timings)} of {len(chunks)}")
    require(all(item.get("status") == "ok" for item in timings), "One or more document embedding timings record a failure")
    require(runner.DOC_ERRORS_PATH.is_file() and runner.DOC_ERRORS_PATH.stat().st_size == 0, "Document embedding error file is not empty")

    vectors = np.load(runner.VECTOR_PATH, allow_pickle=False)
    require(vectors.shape == (len(chunks), 768), f"Unexpected vector index shape: {vectors.shape}")
    require(vectors.dtype == np.float32 and np.isfinite(vectors).all(), "Vector index dtype/value validation failed")
    vector_hash = runner.sha256_file(runner.VECTOR_PATH)
    vector_map = read_jsonl(runner.VECTOR_MAP_PATH)
    require(len(vector_map) == len(chunks), "Vector map length differs from frozen index")
    require(all(row["position"] == position and row["chunk_id"] == chunks[position]["chunk_id"] for position, row in enumerate(vector_map)), "Vector map order differs from frozen index")

    prior_events = read_jsonl(runner.EVENTS_PATH)
    model_event = next(event for event in prior_events if event.get("event") == "model_loaded")
    index_event = next(event for event in prior_events if event.get("event") == "document_index_written")
    completed_event = next(event for event in reversed(prior_events) if event.get("event") == "document_embedding_progress" and event.get("completed") == len(chunks))
    require(index_event.get("shape") == [len(chunks), 768], "Original index write event shape mismatch")
    require(index_event.get("vector_sha256") == vector_hash, "Vector checksum differs from original completed index event")
    document_wall_seconds = round(index_event["elapsed_seconds"] - model_event["elapsed_seconds"], 6)
    vector_write_seconds = round(index_event["elapsed_seconds"] - completed_event["elapsed_seconds"], 6)

    # The frozen source-only document index is already complete; read queries from their declared mount points.
    dev_path = Path("/benchmark/queries-dev.jsonl")
    test_path = Path("/benchmark/queries-test.jsonl")
    require(dev_path.is_file() and test_path.is_file(), "Frozen query files are not visible at their Compose mount points")
    dev_queries, dev_sha = runner.parse_queries(dev_path, manifest["inputs"]["queries"]["dev"]["sha256_from_evaluation_contract"])
    test_queries, test_sha = runner.parse_queries(test_path, manifest["inputs"]["queries"]["test"]["sha256_from_evaluation_contract"])
    require(len(dev_queries) == 15 and len(test_queries) == 60, "Frozen query counts differ from evaluation contract")

    # Preserve the initial mount-path failure before replacing the top-level status with the recovered outcome.
    shutil.copy2(INITIAL_RESULT, FAILED_RESULT_COPY)
    runner.event("query_stage_recovery_started", cause="query mount path in runner differed from Compose mount", dev_count=len(dev_queries), test_count=len(test_queries))
    runner.torch.set_num_threads(runner.TORCH_THREADS)
    require(runner.torch.get_num_threads() == 4, f"Expected exactly four PyTorch threads, got {runner.torch.get_num_threads()}")
    model, model_info, query_model_load_seconds = runner.load_model()
    runner.event("query_model_loaded", architecture=model_info["architecture"], load_seconds=model_info["load_seconds"], torch_threads=runner.torch.get_num_threads())

    query_started = time.perf_counter()
    dev_results, global_after_dev = runner.run_split(model, "dev", dev_queries, chunks, vectors, runner.DEV_RESULTS_PATH, 0)
    test_results, _ = runner.run_split(model, "test", test_queries, chunks, vectors, runner.TEST_RESULTS_PATH, global_after_dev, 0)
    query_wall_seconds = time.perf_counter() - query_started
    dev_errors = sum(result["status"] != "ok" for result in dev_results)
    test_errors = sum(result["status"] != "ok" for result in test_results)

    current_rss = runner.PROCESS.memory_info().rss
    process_peak = runner.peak_rss_bytes()
    cgroup_peak = runner.cgroup_value("memory.peak")
    runtime = {
        "schema": "embeddinggemma2-accuracy-speed-runtime-measurement/v1",
        "manifest_sha256": manifest_sha,
        "source_document_manifest_sha256": source_manifest_sha,
        "index_sha256": index_sha,
        "vector_file_sha256": vector_hash,
        "resolved_model_revision": runner.MODEL_REVISION,
        "query_stage_model_load_seconds": round(query_model_load_seconds, 6),
        "document_embedding_container_model_load_seconds": model_event.get("load_seconds"),
        "document_embedding_wall_seconds_from_container_events": document_wall_seconds,
        "vector_index_write_seconds_from_container_events": vector_write_seconds,
        "input_extraction_seconds": manifest["index"]["extraction_seconds"],
        "device": "cpu",
        "dtype": "torch.float32",
        "torch_threads": runner.torch.get_num_threads(),
        "source_document_runner_thread_setter": "run_experiment.py calls torch.set_num_threads(TORCH_THREADS) before model load; compose.yaml sets TORCH_THREADS=4",
        "source_document_process_thread_readback_serialized": source_manifest["runtime"].get("index_process_thread_readback_serialized", False),
        "cpu_model": runner.cpu_model(),
        "visible_logical_cpus": runner.os.cpu_count(),
        "container_cpu_limit_cores": 4,
        "container_memory_limit_bytes": runner.cgroup_value("memory.max"),
        "cgroup_cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text(encoding="ascii").strip(),
        "network_mode": "none",
        "batch_size": 1,
        "concurrency": "serial",
        "vector_dimension": 768,
        "weights_cached_local": True,
        "model_loaded_before_query_calls": True,
        "first_test_call_is_cold": False,
        "timing_boundary": "question text entering query encoding through cosine scoring, stable sort, and in-memory ranking construction; no network",
        "process_rss_after_queries_bytes": current_rss,
        "process_max_rss_bytes_query_container": process_peak,
        "cgroup_peak_bytes_query_container": cgroup_peak,
        "original_document_container_process_max_rss_bytes": initial_result.get("process_max_rss_bytes"),
        "original_document_container_cgroup_peak_bytes": initial_result.get("cgroup_peak_bytes"),
        "actual_document_representations": {
            "office_pdf_text": "derived source text with title prompt",
            "audio": "native audio path input, prompt empty, mono 16kHz fixed segments",
            "video": "native video path input, prompt empty, fixed 1fps/max32/uniform/timestamps disabled",
        },
        "query_input_representation": "question text only",
    }
    runner.write_json(RUNTIME_PATH, runtime)

    result = {
        "schema": "embeddinggemma2-run-result/v1",
        "status": "complete" if dev_errors == 0 and len(test_results) == 180 and test_errors == 0 else "complete_with_query_errors",
        "attempt_id": runner.ATTEMPT_ID,
        "recovered_after_pre_query_mount_failure": True,
        "initial_failure_record": str(FAILED_RESULT_COPY.relative_to(RUN_ROOT)),
        "recovery_reason": "Runner looked for query JSONL under /benchmark/run; Compose mounts them under /benchmark. No query call occurred in the initial run.",
        "manifest_sha256": manifest_sha,
        "source_document_manifest_sha256": source_manifest_sha,
        "evaluation_contract_sha256": manifest["contracts"]["evaluation"]["sha256"],
        "aggregation_contract_sha256": manifest["contracts"]["aggregation"]["sha256"],
        "dev_query_sha256": dev_sha,
        "test_query_sha256": test_sha,
        "index_sha256": index_sha,
        "vector_file_sha256": vector_hash,
        "input_count": manifest["inputs"]["input_count"],
        "chunk_count": len(chunks),
        "document_embedding": {
            "status": "complete; reused without re-embedding",
            "successful_chunk_records": len(timings),
            "errors": 0,
            "wall_seconds_from_container_events": document_wall_seconds,
            "vector_index_write_seconds_from_container_events": vector_write_seconds,
            "timing_records_path": str(runner.DOC_TIMINGS_PATH.relative_to(RUN_ROOT)),
        },
        "initial_document_container_model_load_seconds": model_event.get("load_seconds"),
        "query_container_model_load_seconds": round(query_model_load_seconds, 6),
        "query_execution_wall_seconds": round(query_wall_seconds, 6),
        "query_counts": {
            "dev_expected": 15,
            "dev_records": len(dev_results),
            "dev_errors": dev_errors,
            "test_expected": 180,
            "test_records": len(test_results),
            "test_errors": test_errors,
            "test_first_call_query_id": next((row["query_id"] for row in test_results if row["is_first_test_call"]), None),
        },
        "outputs": {
            "dev_results": str(runner.DEV_RESULTS_PATH.relative_to(RUN_ROOT)),
            "test_results": str(runner.TEST_RESULTS_PATH.relative_to(RUN_ROOT)),
            "document_embedding_timings": str(runner.DOC_TIMINGS_PATH.relative_to(RUN_ROOT)),
            "document_embedding_errors": str(runner.DOC_ERRORS_PATH.relative_to(RUN_ROOT)),
            "vectors": str(runner.VECTOR_PATH.relative_to(RUN_ROOT)),
            "vector_map": str(runner.VECTOR_MAP_PATH.relative_to(RUN_ROOT)),
            "runtime": str(RUNTIME_PATH.relative_to(RUN_ROOT)),
            "initial_failure": str(FAILED_RESULT_COPY.relative_to(RUN_ROOT)),
            "recovery_note": str(RECOVERY_NOTE.relative_to(RUN_ROOT)),
        },
        "runtime": runtime,
        "wall_seconds_query_recovery_container": round(time.perf_counter() - started, 6),
    }
    runner.write_json(RUN_RESULT_PATH, result)
    recovery_note = {
        "schema": "embeddinggemma2-query-stage-recovery/v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "root_cause": "Query paths in run_experiment.py were incorrectly resolved beneath /benchmark/run, while compose.yaml mounts query files directly beneath /benchmark.",
        "initial_queries_executed": 0,
        "document_embeddings_repeated": False,
        "source_document_embedding_attempt": "attempt-01",
        "source_document_manifest_sha256": source_manifest_sha,
        "formal_query_manifest": str(runner.MANIFEST_PATH.relative_to(RUN_ROOT)),
        "formal_query_manifest_sha256": manifest_sha,
        "evaluation_contract_sha256": manifest["contracts"]["evaluation"]["sha256"],
        "aggregation_contract_sha256": manifest["contracts"]["aggregation"]["sha256"],
        "dev_query_sha256": dev_sha,
        "test_query_sha256": test_sha,
        "excluded_query_attempt": {
            "attempt_id": "attempt-01",
            "reason": "actual PyTorch thread count was 1, below the frozen 4-thread condition",
            "records_preserved_at": ["results/attempt-01/dev-query-results.jsonl", "results/attempt-01/test-query-results.jsonl", "results/attempt-01/runtime.json"],
        },
        "excluded_prior_attempts": [
            {
                "attempt_id": "attempt-01",
                "reason": "actual PyTorch thread count was 1, below the frozen 4-thread condition",
                "records_preserved_at": ["results/attempt-01/dev-query-results.jsonl", "results/attempt-01/test-query-results.jsonl", "results/attempt-01/runtime.json"],
            },
            {
                "attempt_id": "attempt-02",
                "reason": "the manifest captured the prior aggregation-contract SHA and does not satisfy the current frozen aggregation contract",
                "records_preserved_at": ["results/attempt-02/dev-query-results.jsonl", "results/attempt-02/test-query-results.jsonl", "results/attempt-02/runtime.json", "results/attempt-02/raw-record-validation.json"],
            },
            {
                "attempt_id": "attempt-03-query-threads4",
                "reason": "pre-query provenance guard expected a runtime-probe metadata field absent from the source manifest; no query model call occurred",
                "records_preserved_at": ["results/attempt-03-query-threads4/query-resume-failure.json"],
            },
            {
                "attempt_id": "attempt-04-query-threads4",
                "reason": "all 195 query outputs were written, but completion recording failed because the source manifest predates an added thread-setter metadata field",
                "records_preserved_at": ["results/attempt-04-query-threads4/dev-query-results.jsonl", "results/attempt-04-query-threads4/test-query-results.jsonl", "results/attempt-04-query-threads4/run-events.jsonl", "results/attempt-04-query-threads4/query-resume-failure.json"],
            },
        ],
        "frozen_manifest_sha256": manifest_sha,
        "frozen_index_sha256": index_sha,
        "preserved_initial_failure": str(FAILED_RESULT_COPY.relative_to(RUN_ROOT)),
        "recovered_query_result_paths": [str(runner.DEV_RESULTS_PATH.relative_to(RUN_ROOT)), str(runner.TEST_RESULTS_PATH.relative_to(RUN_ROOT))],
    }
    runner.write_json(RECOVERY_NOTE, recovery_note)
    runner.event("query_stage_recovery_complete", status=result["status"], dev_records=len(dev_results), test_records=len(test_results), test_errors=test_errors)
    print(json.dumps({
        "status": result["status"],
        "attempt_id": runner.ATTEMPT_ID,
        "manifest_sha256": manifest_sha,
        "index_sha256": index_sha,
        "dev_records": len(dev_results),
        "dev_errors": dev_errors,
        "test_records": len(test_results),
        "test_errors": test_errors,
        "first_test_query_id": result["query_counts"]["test_first_call_query_id"],
        "query_model_load_seconds": result["query_container_model_load_seconds"],
        "query_execution_wall_seconds": result["query_execution_wall_seconds"],
        "process_max_rss_bytes": process_peak,
        "cgroup_peak_bytes": cgroup_peak,
        "run_result": str(RUN_RESULT_PATH),
    }, ensure_ascii=False))
    return 0 if result["status"] == "complete" else 3


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:
        failure = {
            "schema": "embeddinggemma2-query-resume-failure/v1",
            "status": "fatal_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "manifest_sha256": runner.sha256_file(runner.MANIFEST_PATH) if runner.MANIFEST_PATH.exists() else None,
            "index_sha256": runner.sha256_file(runner.INDEX_PATH) if runner.INDEX_PATH.exists() else None,
        }
        failure_path = OUT / "query-resume-failure.json"
        if not failure_path.exists():
            runner.write_json(failure_path, failure)
        print(json.dumps({"status": "fatal_error", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False))
        exit_code = 4
    raise SystemExit(exit_code)
