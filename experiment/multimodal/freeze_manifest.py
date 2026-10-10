"""Freeze the input, index, model, and evaluation conditions before benchmark scoring."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUN_DIR = Path(__file__).resolve().parent
REPO_DIR = RUN_DIR.parent
BENCH_DIR = REPO_DIR / "multimodal-benchmark"
OUTPUT = RUN_DIR / "run_manifest.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(REPO_DIR)).replace("\\", "/"), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    global OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="run_manifest.json", help="New manifest filename inside this run directory")
    arguments = parser.parse_args()
    requested_output = Path(arguments.output)
    OUTPUT = requested_output if requested_output.is_absolute() else RUN_DIR / requested_output
    OUTPUT = OUTPUT.resolve()
    require(not OUTPUT.exists(), f"Refusing to replace frozen manifest: {OUTPUT}")

    evaluation_path = RUN_DIR / "verification" / "evaluation-contract.json"
    research_path = RUN_DIR / "research" / "contract.json"
    aggregation_path = RUN_DIR / "analysis" / "aggregation-contract.json"
    source_manifest_path = BENCH_DIR / "manifest.json"
    prep_path = RUN_DIR / "preparation-summary.json"
    input_hashes_path = RUN_DIR / "input-hashes.json"
    index_path = RUN_DIR / "index.jsonl"
    runtime_path = RUN_DIR / "container-runtime.json"
    smoke_path = RUN_DIR / "smoke" / "smoke-report.json"

    evaluation = read_json(evaluation_path)
    research = read_json(research_path)
    aggregation = read_json(aggregation_path)
    source_manifest = read_json(source_manifest_path)
    preparation = read_json(prep_path)
    input_hashes = read_json(input_hashes_path)
    runtime = read_json(runtime_path)
    smoke = read_json(smoke_path)

    frozen = evaluation["frozen_inputs"]
    assets_by_path = {asset["path"]: asset for asset in frozen["assets"]}
    source_assets_by_path = {asset["path"]: asset for asset in source_manifest["assets"]}
    prep_assets_by_path = {asset["path"]: asset for asset in input_hashes["inputs"]}

    require(sha256_file(source_manifest_path) == frozen["manifest_sha256"], "Source manifest hash differs from evaluation contract")
    require(len(assets_by_path) == evaluation["frozen_inputs"]["checks"]["input_count"] == 14, "Expected exactly 14 frozen assets")
    require(set(assets_by_path) == set(source_assets_by_path) == set(prep_assets_by_path), "Asset allowlist differs across frozen contract, source manifest, and prep record")
    require(input_hashes.get("allowlist_match") is True, "Preparation did not report allowlist match")
    require(input_hashes.get("gold_or_query_files_read") is False, "Preparation reports reading gold or query files")
    require(preparation.get("qa_or_source_material_used") is False, "Preparation reports using QA/source material")
    require(preparation.get("chunk_id_uniqueness") is True, "Preparation did not verify unique chunk IDs")
    require(preparation["chunk_count"] == 63, "Unexpected prepared chunk count")

    input_asset_records: list[dict[str, Any]] = []
    for source_path, expected in assets_by_path.items():
        source_record = source_assets_by_path[source_path]
        prep_record = prep_assets_by_path[source_path]
        require(source_record["asset_id"] == expected["asset_id"], f"Asset ID mismatch: {source_path}")
        require(source_record["sha256"] == expected["sha256"], f"Source manifest SHA mismatch: {source_path}")
        require(prep_record["sha256"] == expected["sha256"], f"Preparation SHA mismatch: {source_path}")
        actual_path = BENCH_DIR / Path(source_path)
        require(actual_path.is_file(), f"Missing input asset: {actual_path}")
        actual_sha = sha256_file(actual_path)
        actual_bytes = actual_path.stat().st_size
        require(actual_sha == expected["sha256"], f"Actual input SHA mismatch: {source_path}")
        require(actual_bytes == source_record["bytes"] == prep_record["bytes"], f"Input byte-count mismatch: {source_path}")
        input_asset_records.append({
            "asset_id": expected["asset_id"],
            "path": source_path,
            "bytes": actual_bytes,
            "sha256": actual_sha,
        })

    index_bytes = index_path.read_bytes()
    index_sha = sha256_bytes(index_bytes)
    require(index_sha == preparation["index_sha256"], "Index SHA differs from preparation summary")
    chunks = [json.loads(line) for line in index_bytes.decode("utf-8").splitlines() if line.strip()]
    require(len(chunks) == preparation["chunk_count"], "Index record count differs from preparation summary")
    require(len({chunk["chunk_id"] for chunk in chunks}) == len(chunks), "Index contains duplicate chunk IDs")
    allowed_paths = set(assets_by_path)
    require(all(chunk["source_path"] in allowed_paths for chunk in chunks), "Index contains a source path outside the input allowlist")
    chunk_by_modality: dict[str, int] = {}
    for chunk in chunks:
        modality = str(chunk["modality"])
        chunk_by_modality[modality] = chunk_by_modality.get(modality, 0) + 1

    derived_records: list[dict[str, Any]] = []
    for media_group in preparation.get("media_segments", []):
        for segment in media_group.get("segments", []):
            relative = Path(segment["path"])
            path = RUN_DIR / relative
            require(path.is_file(), f"Missing derived media segment: {path}")
            actual_sha = sha256_file(path)
            require(actual_sha == segment["sha256"], f"Derived media SHA mismatch: {relative.as_posix()}")
            derived_records.append({
                "path": relative.as_posix(),
                "asset_id": media_group["asset_id"],
                "bytes": path.stat().st_size,
                "sha256": actual_sha,
            })

    model = evaluation["model"]
    require(model["id"] == research["checkpoint"]["model_id"], "Model IDs differ between contracts")
    require(model["revision"] == research["checkpoint"]["revision"] == preparation["model_revision"], "Model revisions differ between contracts and preparation")
    require(smoke["requested_revision"] == model["revision"], "Smoke revision differs from frozen model revision")
    require(smoke["all_modalities_ok"] is True and all(value["status"] == "ok" for value in smoke["modalities"].values()), "Native modality smoke did not pass")
    require(runtime["snapshot_path"].endswith(model["revision"]), "Runtime snapshot path does not end with frozen revision")
    require(runtime["device"] == "cpu" and runtime["dtype"] == "torch.float32", "Runtime device/dtype differs from expected benchmark condition")
    require(runtime["torch_threads"] == 4 and runtime["cgroup_cpu_max"] == "400000 100000", "Runtime CPU/thread condition mismatch")
    require(runtime["cgroup_memory_max_bytes"] == "8589934592", "Runtime memory limit mismatch")
    require(runtime["offline_environment"].get("network_mode") == "none", "Runtime was not recorded offline")

    queries = frozen["queries"]
    require(queries["dev"]["sha256"] == evaluation["population"]["dev_test"]["dev"]["query_sha256"], "Dev query hashes differ inside evaluation contract")
    require(queries["test"]["sha256"] == evaluation["population"]["dev_test"]["test"]["query_sha256"], "Test query hashes differ inside evaluation contract")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = {
        "schema": "embeddinggemma2-locked-run-manifest/v1",
        "status": "locked_before_model_evaluation",
        "freeze_scope": "benchmark retrieval run; the separately recorded native smoke is non-scoring",
        "frozen_at_utc": now,
        "frozen_at_local_date": "2026-10-10",
        "contracts": {
            "evaluation": {**file_record(evaluation_path), "schema": evaluation["schema"]},
            "research": {**file_record(research_path), "schema": research["schema"]},
            "aggregation": {**file_record(aggregation_path), "schema": aggregation["schema"], "status": aggregation["status"]},
        },
        "inputs": {
            "source_manifest": {**file_record(source_manifest_path), "expected_sha256": frozen["manifest_sha256"]},
            "allowlist_root": "multimodal-benchmark/inputs",
            "input_count": len(input_asset_records),
            "assets": sorted(input_asset_records, key=lambda item: item["asset_id"]),
            "gold": {
                "path": frozen["gold_path"],
                "sha256_from_evaluation_contract": frozen["gold_sha256"],
                "content_read_by_freezer": False,
            },
            "queries": {
                split: {
                    "path": record["path"],
                    "sha256_from_evaluation_contract": record["sha256"],
                    "content_read_by_freezer": False,
                }
                for split, record in queries.items()
            },
        },
        "index": {
            **file_record(index_path),
            "chunk_count": len(chunks),
            "chunk_counts_by_modality": dict(sorted(chunk_by_modality.items())),
            "source_path_allowlist_match": True,
            "derived_media_segments": derived_records,
            "extraction_seconds": preparation["extraction_seconds"],
        },
        "model": {
            "id": model["id"],
            "revision": model["revision"],
            "snapshot_path": runtime["snapshot_path"],
            "architecture": smoke["architecture"],
            "parameter_count": smoke["parameters_loaded"],
            "output_dimensions": research["checkpoint"]["output_dimensions"],
            "device": runtime["device"],
            "dtype": runtime["dtype"],
            "torch_threads": runtime["torch_threads"],
            "all_native_modalities_smoke_passed": smoke["all_modalities_ok"],
            "native_smoke_file": file_record(smoke_path),
            "native_smoke_load_seconds": smoke["model_load_seconds"],
            "native_smoke_rss_after_smokes_bytes": smoke["rss_after_smokes_bytes"],
            "native_smoke_rss_label_note": "Point-in-time process RSS sampled after smoke encodes; this is not process peak RSS. The cgroup peak is recorded separately.",
            "native_smoke_cgroup_peak_bytes": smoke["cgroup_peak_bytes"],
        },
        "runtime": {
            **file_record(runtime_path),
            "packages": runtime["packages"],
            "ffmpeg_version": runtime["ffmpeg_version"],
            "ffprobe_version": runtime["ffprobe_version"],
            "cpu_model": runtime.get("cpu_model"),
            "logical_cpus_visible": runtime["logical_cpus_visible"],
            "process_affinity_cpu_count": runtime["process_affinity_cpu_count"],
            "container_cpu_limit_cores": 4,
            "container_memory_limit_bytes": runtime["cgroup_memory_max_bytes"],
            "network_mode": runtime["offline_environment"]["network_mode"],
            "cgroup_cpu_max": runtime["cgroup_cpu_max"],
            "torch_threads_from_same_image_runtime_probe": runtime["torch_threads"],
            "index_runner_thread_setter": "torch.set_num_threads(TORCH_THREADS) before model load; TORCH_THREADS=4 in compose environment",
            "index_process_thread_readback_serialized": False,
        },
        "embedding_protocol": {
            "query_method": research["api"]["query_method"],
            "query_prompt_name": evaluation["model_api_condition"]["query_prompt_name"],
            "query_prompt_text": evaluation["model_api_condition"]["query_prompt_text"],
            "text_document_method": research["api"]["document_method"],
            "text_document_prompt_template": "title: {title} | text: {body}",
            "media_document_prompt": evaluation["model_api_condition"]["media_document"],
            "audio": {
                "sample_rate_hz": research["modalities"]["audio"]["required_sample_rate_hz"],
                "channels": research["modalities"]["audio"]["required_channels"],
                "segment_seconds": preparation["media_rules"]["audio_chunk_seconds"],
                "tail_rule": preparation["media_rules"]["audio_tail_rule"],
            },
            "video": preparation["media_rules"]["video_processor"],
            "batch_size": 1,
            "concurrency": "serial",
            "normalization": True,
            "vector_dimension": research["checkpoint"]["output_dimensions"],
            "similarity": research["checkpoint"]["similarity"],
        },
        "evaluation_protocol": {
            "population": evaluation["population"],
            "k": evaluation["metrics"]["k"],
            "ranking_units": evaluation["metrics"]["ranking_units"],
            "locator_coverage": evaluation["metrics"]["locator_coverage"],
            "primary_metrics": evaluation["metrics"]["primary_metrics"],
            "test_repetitions": 3,
            "test_calls_expected": 180,
            "dev_repetitions": 1,
            "dev_calls_expected": 15,
            "primary_test_repetition": 1,
            "unanswerable_threshold": None,
            "latency_boundary": evaluation["speed"]["measurement"],
            "first_query_rule": evaluation["speed"]["first_query"],
            "test_order_rule": "Canonical order within each frozen query file; repetition 1, then repetition 2, then repetition 3.",
            "retry_policy": "No retries or silent omissions; preserve error records.",
        },
        "freeze_checks": {
            "source_manifest_matches_contract": True,
            "all_input_assets_match_contract_and_preparation": True,
            "index_sha_matches_preparation": True,
            "index_uses_only_allowlisted_sources": True,
            "no_gold_or_query_content_read": True,
            "runtime_matches_cpu_float32_caps": True,
            "native_smoke_passed_pre_run": True,
        },
    }

    encoded = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    temporary.replace(OUTPUT)
    print(json.dumps({
        "status": result["status"],
        "manifest_path": str(OUTPUT),
        "manifest_sha256": sha256_file(OUTPUT),
        "index_sha256": index_sha,
        "input_count": len(input_asset_records),
        "chunk_count": len(chunks),
        "query_content_read": False,
        "gold_content_read": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
