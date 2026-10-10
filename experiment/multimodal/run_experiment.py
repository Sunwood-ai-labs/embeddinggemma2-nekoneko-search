"""Run the frozen native EmbeddingGemma 2 retrieval benchmark in the isolated container."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import resource
import sys
import time
import traceback
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import psutil
import torch
from sentence_transformers import SentenceTransformer


RUN_ROOT = Path("/benchmark/run")
MANIFEST_PATH = Path(os.environ.get("MANIFEST_PATH", str(RUN_ROOT / "run_manifest.json")))
INDEX_PATH = RUN_ROOT / "index.jsonl"
MODEL_ID = os.environ["MODEL_ID"]
MODEL_REVISION = os.environ["MODEL_REVISION"]
MODEL_SNAPSHOT = Path(os.environ["MODEL_SNAPSHOT"])
TORCH_THREADS = int(os.environ.get("TORCH_THREADS", "4"))
QUERY_PROMPT_NAME = "QuestionAnswering"
QUERY_PROMPT_TEXT = "task: question answering | query: "
VIDEO_PROCESSING = {
    "fps": 1,
    "max_frames": 32,
    "overflow_strategy": "uniform",
    "add_timestamps": False,
}
ATTEMPT_ID = os.environ.get("RUN_ATTEMPT_ID", "attempt-01")
OUTPUT_ROOT = RUN_ROOT / "results" / ATTEMPT_ID
VECTOR_PATH = OUTPUT_ROOT / "index-vectors.npy"
VECTOR_MAP_PATH = OUTPUT_ROOT / "index-vector-map.jsonl"
DOC_TIMINGS_PATH = OUTPUT_ROOT / "document-embedding-timings.jsonl"
DOC_ERRORS_PATH = OUTPUT_ROOT / "index-embedding-errors.jsonl"
DEV_RESULTS_PATH = OUTPUT_ROOT / "dev-query-results.jsonl"
TEST_RESULTS_PATH = OUTPUT_ROOT / "test-query-results.jsonl"
RUNTIME_PATH = OUTPUT_ROOT / "runtime.json"
RUN_RESULT_PATH = OUTPUT_ROOT / "run-result.json"
EVENTS_PATH = OUTPUT_ROOT / "run-events.jsonl"
PROCESS = psutil.Process()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def event(name: str, **values: Any) -> None:
    append_jsonl(EVENTS_PATH, {"event": name, "elapsed_seconds": round(time.perf_counter() - WALL_START, 6), **values})


def cgroup_value(name: str) -> int | None:
    try:
        return int(Path("/sys/fs/cgroup", name).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def peak_rss_bytes() -> int | None:
    try:
        # Linux reports ru_maxrss in KiB.
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    except (AttributeError, OSError, ValueError):
        return None


def cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON in {path.name}:{line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise RuntimeError(f"Expected JSON object in {path.name}:{line_number}")
        records.append(record)
    return records


def query_fields(record: dict[str, Any]) -> tuple[str, str]:
    query_id = record.get("id", record.get("query_id", record.get("question_id")))
    question = record.get("question", record.get("query", record.get("query_text", record.get("text"))))
    if query_id is None or not isinstance(question, str) or not question.strip():
        raise RuntimeError(f"Could not identify query id/question fields; keys={sorted(record)}")
    return str(query_id), question


def normalized(vector: np.ndarray, label: str) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32)
    if value.shape != (768,):
        raise RuntimeError(f"{label}: expected vector shape (768,), got {value.shape}")
    if not np.isfinite(value).all():
        raise RuntimeError(f"{label}: vector contains NaN or infinity")
    norm = float(np.linalg.norm(value))
    if not np.isfinite(norm) or abs(norm - 1.0) > 1e-3:
        raise RuntimeError(f"{label}: expected unit norm within 1e-3, got {norm}")
    return value


def load_locked_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], str, str]:
    require(MANIFEST_PATH.is_file(), f"Missing frozen manifest: {MANIFEST_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    require(manifest.get("status") == "locked_before_model_evaluation", "Run manifest is not locked for evaluation")
    require(manifest["model"]["id"] == MODEL_ID, "MODEL_ID differs from frozen manifest")
    require(manifest["model"]["revision"] == MODEL_REVISION, "MODEL_REVISION differs from frozen manifest")
    require(manifest["model"]["snapshot_path"] == str(MODEL_SNAPSHOT), "MODEL_SNAPSHOT differs from frozen manifest")
    require(MODEL_SNAPSHOT.is_dir(), f"Missing pinned local snapshot: {MODEL_SNAPSHOT}")
    require(MODEL_SNAPSHOT.name == MODEL_REVISION, "Snapshot directory name does not match pinned revision")
    require(sha256_file(INDEX_PATH) == manifest["index"]["sha256"], "Index checksum differs from frozen manifest")
    require(not (RUN_ROOT / "gold.json").exists(), "Gold data must not be mounted into the experiment container")
    chunks = load_jsonl(INDEX_PATH)
    require(len(chunks) == manifest["index"]["chunk_count"], "Index chunk count differs from frozen manifest")
    require(len({chunk["chunk_id"] for chunk in chunks}) == len(chunks), "Index contains duplicate chunk IDs")
    asset_paths = {item["path"] for item in manifest["inputs"]["assets"]}
    require(all(chunk["source_path"] in asset_paths for chunk in chunks), "Index references a path outside frozen input allowlist")
    manifest_sha = sha256_file(MANIFEST_PATH)
    index_sha = sha256_file(INDEX_PATH)
    return manifest, chunks, manifest_sha, index_sha


def load_model() -> tuple[SentenceTransformer, dict[str, Any], float]:
    load_start = time.perf_counter()
    model = SentenceTransformer(
        str(MODEL_SNAPSHOT),
        device="cpu",
        model_kwargs={"dtype": torch.float32, "local_files_only": True},
    )
    load_seconds = time.perf_counter() - load_start
    auto_model = getattr(model[0], "auto_model", None)
    config = getattr(auto_model, "config", None)
    supports = {modality: bool(model.supports(modality)) for modality in ("text", "image", "audio", "video")}
    parameter_dtypes = sorted({str(parameter.dtype) for parameter in auto_model.parameters()})
    require(type(auto_model).__name__ == "EmbeddingGemma2Model", f"Unexpected model architecture: {type(auto_model).__name__}")
    require(getattr(config, "vision_config", None) is not None, "Vision tower config is not loaded")
    require(getattr(config, "audio_config", None) is not None, "Audio tower config is not loaded")
    require(all(supports.values()), f"Required model modalities unsupported: {supports}")
    require(parameter_dtypes == ["torch.float32"], f"Expected float32 model parameters, found {parameter_dtypes}")
    prompts = getattr(model, "prompts", {})
    require(prompts.get(QUERY_PROMPT_NAME) == QUERY_PROMPT_TEXT, "QuestionAnswering prompt differs from frozen benchmark contract")
    model_info = {
        "architecture": type(auto_model).__name__,
        "parameter_count": sum(parameter.numel() for parameter in auto_model.parameters()),
        "parameter_dtypes": parameter_dtypes,
        "supports": supports,
        "vision_tower_loaded": getattr(config, "vision_config", None) is not None,
        "audio_tower_loaded": getattr(config, "audio_config", None) is not None,
        "prompt_config_question_answering": prompts.get(QUERY_PROMPT_NAME),
        "load_seconds": round(load_seconds, 6),
    }
    return model, model_info, load_seconds


def embed_documents(model: SentenceTransformer, chunks: list[dict[str, Any]]) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, float]]:
    doc_errors: list[dict[str, Any]] = []
    vectors: list[np.ndarray | None] = [None] * len(chunks)
    timings: dict[str, float] = {}
    stage_start = time.perf_counter()
    with DOC_TIMINGS_PATH.open("w", encoding="utf-8", newline="\n") as timing_stream, DOC_ERRORS_PATH.open("w", encoding="utf-8", newline="\n") as error_stream:
        for position, chunk in enumerate(chunks):
            encode_start = time.perf_counter()
            modality = chunk["modality"]
            input_representation = "derived_text" if chunk.get("text") else "native_media"
            try:
                common = {
                    "normalize_embeddings": True,
                    "convert_to_numpy": True,
                    "batch_size": 1,
                    "show_progress_bar": False,
                }
                if chunk.get("text"):
                    title = str(chunk.get("title") or "").strip()
                    if not title:
                        raise RuntimeError(f"Text chunk has no source-derived title: {chunk['chunk_id']}")
                    prompt = f"title: {title} | text: "
                    raw = model.encode_document([str(chunk["text"])], prompt=prompt, **common)[0]
                else:
                    media_path = RUN_ROOT / str(chunk["media_path"])
                    if not media_path.is_file():
                        raise RuntimeError(f"Missing prepared native media segment: {media_path}")
                    raw_media = {modality: str(media_path)}
                    media_kwargs = dict(common)
                    media_kwargs["prompt"] = ""
                    if modality == "video":
                        media_kwargs["processing_kwargs"] = {"video": VIDEO_PROCESSING}
                    raw = model.encode_document([raw_media], **media_kwargs)[0]
                    prompt = ""
                vector = normalized(raw, chunk["chunk_id"])
                vectors[position] = vector
                elapsed = time.perf_counter() - encode_start
                record = {
                    "status": "ok",
                    "position": position,
                    "chunk_id": chunk["chunk_id"],
                    "asset_id": chunk["asset_id"],
                    "source_path": chunk["source_path"],
                    "modality": modality,
                    "input_representation": input_representation,
                    "prompt": prompt,
                    "elapsed_ms": round(elapsed * 1000, 4),
                    "dimension": int(vector.shape[0]),
                    "norm": float(np.linalg.norm(vector)),
                }
                timing_stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                timing_stream.flush()
            except Exception as exc:
                elapsed = time.perf_counter() - encode_start
                error = {
                    "status": "error",
                    "position": position,
                    "chunk_id": chunk.get("chunk_id"),
                    "asset_id": chunk.get("asset_id"),
                    "source_path": chunk.get("source_path"),
                    "modality": modality,
                    "input_representation": input_representation,
                    "elapsed_ms": round(elapsed * 1000, 4),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
                doc_errors.append(error)
                error_stream.write(json.dumps(error, ensure_ascii=False, separators=(",", ":")) + "\n")
                error_stream.flush()
            if (position + 1) % 5 == 0 or position + 1 == len(chunks):
                event("document_embedding_progress", completed=position + 1, total=len(chunks), errors=len(doc_errors), current_chunk=chunk.get("chunk_id"))
    timings["document_embedding_wall_seconds"] = time.perf_counter() - stage_start
    if doc_errors:
        return np.empty((0, 768), dtype=np.float32), doc_errors, timings
    matrix = np.stack([vector for vector in vectors if vector is not None]).astype(np.float32, copy=False)
    require(matrix.shape == (len(chunks), 768), f"Unexpected document vector matrix shape: {matrix.shape}")
    require(np.isfinite(matrix).all(), "Document vector matrix contains nonfinite values")
    norms = np.linalg.norm(matrix, axis=1)
    require(np.all(np.abs(norms - 1.0) <= 1e-3), "At least one document vector is not unit-normalized")
    return matrix, doc_errors, timings


def write_vector_index(chunks: list[dict[str, Any]], vectors: np.ndarray) -> dict[str, Any]:
    started = time.perf_counter()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    np.save(VECTOR_PATH, vectors, allow_pickle=False)
    vector_hash = sha256_file(VECTOR_PATH)
    with VECTOR_MAP_PATH.open("w", encoding="utf-8", newline="\n") as stream:
        for position, chunk in enumerate(chunks):
            record = {
                "position": position,
                "chunk_id": chunk["chunk_id"],
                "asset_id": chunk["asset_id"],
                "source_path": chunk["source_path"],
                "modality": chunk["modality"],
                "locator": chunk["locator"],
                "evidence_units": chunk.get("evidence_units", []),
                "interval_seconds": chunk.get("interval_seconds"),
                "title": chunk.get("title"),
                "text": chunk.get("text"),
                "media_path": chunk.get("media_path"),
            }
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {
        "write_seconds": round(time.perf_counter() - started, 6),
        "vector_path": str(VECTOR_PATH.relative_to(RUN_ROOT)),
        "vector_sha256": vector_hash,
        "vector_map_path": str(VECTOR_MAP_PATH.relative_to(RUN_ROOT)),
        "vector_map_sha256": sha256_file(VECTOR_MAP_PATH),
        "shape": list(vectors.shape),
        "dtype": str(vectors.dtype),
    }


def parse_queries(path: Path, expected_sha: str) -> tuple[list[dict[str, Any]], str]:
    actual_sha = sha256_file(path)
    require(actual_sha == expected_sha, f"Frozen query checksum mismatch for {path.name}: expected {expected_sha}, got {actual_sha}")
    records = load_jsonl(path)
    parsed = []
    seen: set[str] = set()
    for order, record in enumerate(records, 1):
        query_id, question = query_fields(record)
        if query_id in seen:
            raise RuntimeError(f"Duplicate query id {query_id} in {path.name}")
        seen.add(query_id)
        parsed.append({"id": query_id, "question": question, "canonical_order": order})
    return parsed, actual_sha


def rank_query(
    model: SentenceTransformer,
    question: str,
    chunks: list[dict[str, Any]],
    vectors: np.ndarray,
    total_start: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float, float, float]:
    total_start = total_start if total_start is not None else time.perf_counter()
    encode_start = time.perf_counter()
    query = model.encode_query(
        [question],
        prompt_name=QUERY_PROMPT_NAME,
        normalize_embeddings=True,
        convert_to_numpy=True,
        batch_size=1,
        show_progress_bar=False,
    )[0]
    query = normalized(query, "query")
    query_encode_ms = (time.perf_counter() - encode_start) * 1000

    rank_start = time.perf_counter()
    scores = np.asarray(vectors @ query, dtype=np.float32)
    order = np.argsort(-scores, kind="stable")
    chunk_ranking = []
    for rank, position in enumerate(order, 1):
        chunk = chunks[int(position)]
        chunk_ranking.append({
            "rank": rank,
            "chunk_id": chunk["chunk_id"],
            "score": float(scores[position]),
            "asset_id": chunk["asset_id"],
            "source_path": chunk["source_path"],
            "modality": chunk["modality"],
            "locator": chunk["locator"],
            "evidence_units": chunk.get("evidence_units", []),
            "interval_seconds": chunk.get("interval_seconds"),
            "title": chunk.get("title"),
            "text": chunk.get("text"),
            "media_path": chunk.get("media_path"),
            "input_representation": "derived_text" if chunk.get("text") else "native_media",
        })

    best_by_asset: dict[str, dict[str, Any]] = {}
    for item in chunk_ranking:
        current = best_by_asset.get(item["asset_id"])
        if current is None:
            best_by_asset[item["asset_id"]] = {
                "asset_id": item["asset_id"],
                "score": item["score"],
                "source_path": item["source_path"],
                "best_chunk_id": item["chunk_id"],
                "best_locator": item["locator"],
                "best_modality": item["modality"],
                "best_chunk_rank": item["rank"],
            }
    asset_ranking = sorted(best_by_asset.values(), key=lambda item: (-item["score"], item["best_chunk_rank"]))
    for rank, item in enumerate(asset_ranking, 1):
        item["rank"] = rank
    rank_ms = (time.perf_counter() - rank_start) * 1000
    elapsed_ms = (time.perf_counter() - total_start) * 1000
    return chunk_ranking, asset_ranking, query_encode_ms, rank_ms, elapsed_ms


def run_split(
    model: SentenceTransformer,
    split: str,
    records: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    vectors: np.ndarray,
    output_path: Path,
    global_order_start: int,
    test_call_order_start: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    results: list[dict[str, Any]] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        for repetition in range(1, (4 if split == "test" else 2)):
            for query in records:
                global_order = global_order_start + len(results) + 1
                test_call_order = test_call_order_start + len(results) + 1 if split == "test" else None
                result: dict[str, Any] = {
                    "status": "ok",
                    "query_id": query["id"],
                    "split": split,
                    "repetition": repetition,
                    "canonical_order": query["canonical_order"],
                    "global_order": global_order,
                    "test_call_order": test_call_order,
                    "is_first_test_call": bool(split == "test" and test_call_order == 1),
                    "elapsed_ms": None,
                    "query_encode_ms": None,
                    "rank_ms": None,
                    "query_text": query["question"],
                    "prompt_name": QUERY_PROMPT_NAME,
                    "prompt_text": QUERY_PROMPT_TEXT,
                    "model_id": MODEL_ID,
                    "model_revision": MODEL_REVISION,
                    "index_sha256": sha256_file(INDEX_PATH),
                    "manifest_sha256": sha256_file(MANIFEST_PATH),
                    "concurrency": "serial",
                    "batch_size": 1,
                }
                query_call_started = time.perf_counter()
                try:
                    chunks_ranked, assets_ranked, query_encode_ms, rank_ms, elapsed_ms = rank_query(
                        model, query["question"], chunks, vectors, total_start=query_call_started
                    )
                    result["chunk_ranking"] = chunks_ranked
                    result["asset_ranking"] = assets_ranked
                    result["query_encode_ms"] = round(query_encode_ms, 4)
                    result["rank_ms"] = round(rank_ms, 4)
                    result["elapsed_ms"] = round(elapsed_ms, 4)
                except Exception as exc:
                    result.update({
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                        "elapsed_ms": round((time.perf_counter() - query_call_started) * 1000, 4),
                        "chunk_ranking": [],
                        "asset_ranking": [],
                    })
                output.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
                output.flush()
                results.append(result)
                if split == "test" and test_call_order in {1, 60, 120, 180}:
                    event("test_query_checkpoint", test_call_order=test_call_order, query_id=query["id"], elapsed_ms=result["elapsed_ms"], status=result["status"])
                elif split == "dev" and query["canonical_order"] in {1, 15}:
                    event("dev_query_checkpoint", canonical_order=query["canonical_order"], query_id=query["id"], elapsed_ms=result["elapsed_ms"], status=result["status"])
    return results, global_order_start + len(results)


def main() -> int:
    global OUTPUT_CREATED
    global WALL_START
    WALL_START = time.perf_counter()
    OUTPUT_ROOT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ROOT.exists():
        raise RuntimeError(f"Refusing to overwrite existing attempt folder: {OUTPUT_ROOT}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    OUTPUT_CREATED = True
    for output in (DOC_TIMINGS_PATH, DOC_ERRORS_PATH, DEV_RESULTS_PATH, TEST_RESULTS_PATH, EVENTS_PATH):
        if output.exists():
            raise RuntimeError(f"Refusing to overwrite existing output file: {output}")

    manifest, chunks, manifest_sha, index_sha = load_locked_inputs()
    event("manifest_verified", manifest_sha256=manifest_sha, index_sha256=index_sha, chunk_count=len(chunks))
    torch.set_num_threads(TORCH_THREADS)
    model, model_info, load_seconds = load_model()
    event("model_loaded", architecture=model_info["architecture"], parameter_count=model_info["parameter_count"], load_seconds=model_info["load_seconds"])

    vectors, doc_errors, doc_timing = embed_documents(model, chunks)
    if doc_errors:
        result = {
            "schema": "embeddinggemma2-run-result/v1",
            "status": "failed_document_embedding",
            "manifest_sha256": manifest_sha,
            "index_sha256": index_sha,
            "model": model_info,
            "model_load_seconds": round(load_seconds, 6),
            "document_embedding": doc_timing,
            "document_embedding_errors": len(doc_errors),
            "process_rss_bytes": PROCESS.memory_info().rss,
            "process_max_rss_bytes": peak_rss_bytes(),
            "cgroup_peak_bytes": cgroup_value("memory.peak"),
            "wall_seconds": round(time.perf_counter() - WALL_START, 6),
        }
        write_json(RUN_RESULT_PATH, result)
        event("run_stopped_after_document_errors", errors=len(doc_errors))
        return 2

    document_index = write_vector_index(chunks, vectors)
    event("document_index_written", vector_sha256=document_index["vector_sha256"], shape=document_index["shape"])

    # Query files are opened only after the source-only document index is fully embedded and written.
    dev_path = Path("/benchmark/queries-dev.jsonl")
    test_path = Path("/benchmark/queries-test.jsonl")
    dev_queries, dev_sha = parse_queries(dev_path, manifest["inputs"]["queries"]["dev"]["sha256_from_evaluation_contract"])
    test_queries, test_sha = parse_queries(test_path, manifest["inputs"]["queries"]["test"]["sha256_from_evaluation_contract"])
    require(len(dev_queries) == 15, f"Expected 15 dev queries, found {len(dev_queries)}")
    require(len(test_queries) == 60, f"Expected 60 test queries, found {len(test_queries)}")
    event("frozen_queries_verified_after_index", dev_count=len(dev_queries), test_count=len(test_queries), dev_sha256=dev_sha, test_sha256=test_sha)

    query_stage_start = time.perf_counter()
    dev_results, global_after_dev = run_split(model, "dev", dev_queries, chunks, vectors, DEV_RESULTS_PATH, 0)
    test_results, global_after_test = run_split(model, "test", test_queries, chunks, vectors, TEST_RESULTS_PATH, global_after_dev, 0)
    query_wall = time.perf_counter() - query_stage_start
    dev_errors = sum(result["status"] != "ok" for result in dev_results)
    test_errors = sum(result["status"] != "ok" for result in test_results)

    runtime = {
        "schema": "embeddinggemma2-accuracy-speed-runtime-measurement/v1",
        "manifest_sha256": manifest_sha,
        "index_sha256": index_sha,
        "model_id": MODEL_ID,
        "resolved_model_revision": MODEL_REVISION,
        "snapshot_path": str(MODEL_SNAPSHOT),
        "weights_cached_local": True,
        "model_loaded_before_queries_for_document_embedding": True,
        "actual_document_representations": {
            "office_pdf_text": "derived source text with title prompt",
            "audio": "native audio path input, prompt empty, mono 16kHz segments",
            "video": "native video path input, prompt empty, fixed fps/max_frames/uniform/timestamps settings",
        },
        "query_input_representation": "question text only",
        "device": "cpu",
        "dtype": "torch.float32",
        "torch_threads": torch.get_num_threads(),
        "visible_logical_cpus": os.cpu_count(),
        "cpu_model": cpu_model(),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            name: package_version(name)
            for name in ("torch", "torchvision", "transformers", "sentence-transformers", "numpy", "av", "torchcodec", "librosa", "psutil")
        },
        "container_cpu_limit_cores": 4,
        "container_memory_limit_bytes": cgroup_value("memory.max"),
        "cgroup_cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text(encoding="ascii").strip() if Path("/sys/fs/cgroup/cpu.max").is_file() else None,
        "network_mode": "none",
        "batch_size": 1,
        "concurrency": "serial",
        "vector_dimension": 768,
        "vector_file_sha256": document_index["vector_sha256"],
        "vector_map_sha256": document_index["vector_map_sha256"],
        "index_path_sha256": index_sha,
        "timing_boundary": "query encode through cosine scoring, stable sort, and in-memory ranked-result construction; no network",
        "process_rss_current_bytes": PROCESS.memory_info().rss,
        "process_max_rss_bytes": peak_rss_bytes(),
        "cgroup_peak_bytes": cgroup_value("memory.peak"),
    }
    write_json(RUNTIME_PATH, runtime)

    successful_test = len(test_results) == 180 and test_errors == 0
    result = {
        "schema": "embeddinggemma2-run-result/v1",
        "status": "complete" if dev_errors == 0 and successful_test else "complete_with_query_errors",
        "attempt_id": ATTEMPT_ID,
        "manifest_sha256": manifest_sha,
        "evaluation_contract_sha256": manifest["contracts"]["evaluation"]["sha256"],
        "aggregation_contract_sha256": manifest["contracts"]["aggregation"]["sha256"],
        "index_sha256": index_sha,
        "input_count": manifest["inputs"]["input_count"],
        "chunk_count": len(chunks),
        "model": model_info,
        "model_load_seconds": round(load_seconds, 6),
        "input_extraction_seconds": manifest["index"]["extraction_seconds"],
        "document_embedding": doc_timing,
        "vector_index_write": document_index,
        "query_execution_wall_seconds": round(query_wall, 6),
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
            "dev_results": str(DEV_RESULTS_PATH.relative_to(RUN_ROOT)),
            "test_results": str(TEST_RESULTS_PATH.relative_to(RUN_ROOT)),
            "document_embedding_timings": str(DOC_TIMINGS_PATH.relative_to(RUN_ROOT)),
            "document_embedding_errors": str(DOC_ERRORS_PATH.relative_to(RUN_ROOT)),
            "vectors": str(VECTOR_PATH.relative_to(RUN_ROOT)),
            "vector_map": str(VECTOR_MAP_PATH.relative_to(RUN_ROOT)),
            "runtime": str(RUNTIME_PATH.relative_to(RUN_ROOT)),
            "events": str(EVENTS_PATH.relative_to(RUN_ROOT)),
        },
        "runtime": runtime,
        "wall_seconds": round(time.perf_counter() - WALL_START, 6),
    }
    write_json(RUN_RESULT_PATH, result)
    event("run_complete", status=result["status"], dev_errors=dev_errors, test_errors=test_errors, test_records=len(test_results))
    print(json.dumps({
        "status": result["status"],
        "attempt_id": ATTEMPT_ID,
        "manifest_sha256": manifest_sha,
        "index_sha256": index_sha,
        "chunk_count": len(chunks),
        "dev_records": len(dev_results),
        "dev_errors": dev_errors,
        "test_records": len(test_results),
        "test_errors": test_errors,
        "model_load_seconds": result["model_load_seconds"],
        "document_embedding_wall_seconds": doc_timing["document_embedding_wall_seconds"],
        "query_execution_wall_seconds": round(query_wall, 6),
        "process_max_rss_bytes": runtime["process_max_rss_bytes"],
        "cgroup_peak_bytes": runtime["cgroup_peak_bytes"],
        "run_result": str(RUN_RESULT_PATH),
    }, ensure_ascii=False))
    return 0 if result["status"] == "complete" else 3


if __name__ == "__main__":
    WALL_START = time.perf_counter()
    OUTPUT_CREATED = False
    try:
        exit_code = main()
    except Exception as exc:
        failure = {
            "schema": "embeddinggemma2-run-failure/v1",
            "status": "fatal_error",
            "attempt_id": ATTEMPT_ID,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "manifest_sha256": sha256_file(MANIFEST_PATH) if MANIFEST_PATH.exists() else None,
            "index_sha256": sha256_file(INDEX_PATH) if INDEX_PATH.exists() else None,
            "process_rss_bytes": PROCESS.memory_info().rss,
            "process_max_rss_bytes": peak_rss_bytes(),
            "cgroup_peak_bytes": cgroup_value("memory.peak"),
            "wall_seconds": round(time.perf_counter() - WALL_START, 6),
        }
        if OUTPUT_CREATED:
            write_json(RUN_RESULT_PATH, failure)
        try:
            if OUTPUT_CREATED:
                event("fatal_error", error_type=type(exc).__name__, error=str(exc))
        except Exception:
            pass
        print(json.dumps({"status": "fatal_error", "error_type": type(exc).__name__, "error": str(exc), "run_result": str(RUN_RESULT_PATH) if OUTPUT_CREATED else None}, ensure_ascii=False))
        exit_code = 4
    raise SystemExit(exit_code)
