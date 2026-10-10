#!/usr/bin/env python3
"""Independent raw-output verification for the frozen EmbeddingGemma 2 run.

Reads frozen inputs, source resolution, and raw query records. It never edits
the experiment outputs. The only written file is the JSON receipt beside this
script. Temporal coverage follows evaluation-contract.json, including the
maximum segment-duration rule.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import unicodedata
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
PROJECT = BASE.parent
RESULTS = BASE / "results"
OUTPUT = HERE / "independent-reaggregation.json"

FROZEN_EVALUATION_SHA = "fdbcc59d04e75d1d32af0bce7ab23cbb934b687d718d5767f5fba90aea6c632a"
FROZEN_AGGREGATION_SHA = "173743e7aa28519ef383b2cf710aa4790fc630529b8d7a6cfdf1ddb825dcf5a0"
FROZEN_INDEX_SHA = "2675ef297502febc2aaeed260d4f8aa4621d37afcc6e10445aabdbff24c6adda"
FROZEN_VECTOR_SHA = "551ec5c4ba9d3cc554d3e60981a3efa97b8152061de6aa394001c5940b6a6356"
FROZEN_MODEL_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
EXPECTED_QUERY_PROMPT = "task: question answering | query: "
K_VALUES = (1, 3, 5, 10)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def normalized_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return unicodedata.normalize("NFKC", text).casefold()


def normalized_locator(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


def column_number(label: str) -> int:
    result = 0
    for char in label.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def column_label(number: int) -> str:
    label = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


def cell_parts(value: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", value.upper().replace("$", ""))
    return (match.group(1), int(match.group(2))) if match else None


def expanded_cells(value: Any) -> set[str]:
    text = str(value or "").upper()
    cells = {m.group(0).replace("$", "") for m in re.finditer(r"(?<![A-Z0-9])\$?[A-Z]{1,3}\$?\d+(?![A-Z0-9])", text)}
    for match in re.finditer(r"(?<![A-Z0-9])(\$?[A-Z]{1,3}\$?\d+)\s*:\s*(\$?[A-Z]{1,3}\$?\d+)(?![A-Z0-9])", text):
        first = cell_parts(match.group(1))
        last = cell_parts(match.group(2))
        if not first or not last:
            continue
        c1, r1 = column_number(first[0]), first[1]
        c2, r2 = column_number(last[0]), last[1]
        if (abs(c2 - c1) + 1) * (abs(r2 - r1) + 1) <= 5000:
            for col in range(min(c1, c2), max(c1, c2) + 1):
                for row in range(min(r1, r2), max(r1, r2) + 1):
                    cells.add(f"{column_label(col)}{row}")
    return cells


def candidate_interval(candidate: dict[str, Any]) -> tuple[float, float] | None:
    value = candidate.get("interval_seconds")
    if isinstance(value, dict):
        try:
            start, end = float(value["start"]), float(value["end"])
            return (start, end) if end > start else None
        except (KeyError, TypeError, ValueError):
            return None
    return None


def candidate_matches_asset_path(candidate: dict[str, Any], evidence: dict[str, Any]) -> bool:
    return (str(candidate.get("asset_id") or "") == str(evidence.get("asset_id") or "")
            and normalized_path(candidate.get("source_path")) == normalized_path(evidence.get("path")))


def _resolution_index(resolutions: dict[tuple[str, str, str], dict[str, Any]], evidence: dict[str, Any]) -> dict[str, Any]:
    key = (str(evidence.get("asset_id") or ""), normalized_path(evidence.get("path")), normalized_locator(evidence.get("location")))
    result = resolutions.get(key)
    if result is None:
        raise ValueError(f"source resolution missing for evidence key {key!r}")
    if result.get("status") != "resolved":
        raise ValueError(f"source resolution is not resolved: {key!r}")
    return result


def entry_fraction(
    candidates: list[dict[str, Any]], evidence: dict[str, Any], resolution: dict[str, Any]
) -> float:
    eligible = [row for row in candidates if candidate_matches_asset_path(row, evidence)]
    kind = resolution.get("kind")

    if kind == "time_interval":
        target = resolution.get("gold_interval_seconds") or {}
        start, end = float(target["start"]), float(target["end"])
        duration = end - start
        if duration <= 0:
            raise ValueError(f"invalid gold interval for {evidence!r}")
        # The locator precision is 0.001 s. Only segment-specific source units
        # no longer than the annotated interval may contribute (frozen rule).
        lo, hi = round(start, 3), round(end, 3)
        intervals: list[tuple[float, float]] = []
        for row in eligible:
            interval = candidate_interval(row)
            if not interval:
                continue
            rstart, rend = interval
            if rend - rstart > duration + 1e-6:
                continue
            rstart, rend = round(rstart, 3), round(rend, 3)
            a, b = max(lo, rstart), min(hi, rend)
            if b > a:
                intervals.append((a, b))
        intervals.sort()
        covered = 0.0
        cursor = lo
        for a, b in intervals:
            if b <= cursor:
                continue
            covered += max(0.0, b - max(cursor, a))
            cursor = max(cursor, b)
        return min(1.0, covered / max(hi - lo, 1e-12))

    if kind == "spreadsheet_cells":
        required = set(str(x).upper() for x in resolution.get("required_cells", []))
        if not required:
            raise ValueError(f"spreadsheet resolution has no required cells: {evidence!r}")
        sheet_number = resolution.get("index_sheet_number")
        found: set[str] = set()
        for row in eligible:
            locator = str(row.get("locator") or "")
            match = re.search(r"\bsheet:(\d+)\b", locator, re.IGNORECASE)
            if sheet_number is not None and (match is None or int(match.group(1)) != int(sheet_number)):
                continue
            for text in (locator, *(row.get("evidence_units") or [])):
                found.update(expanded_cells(text))
        return len(required & found) / len(required)

    # Page, section, and slide coverage is determined by the pre-ranking,
    # source-verified resolution ledger's exact chunk IDs / locators.
    chunk_ids = {str(value) for value in resolution.get("matched_chunk_ids", [])}
    locators = {str(value) for value in resolution.get("matched_index_locators", [])}
    return 1.0 if any(str(row.get("chunk_id") or "") in chunk_ids
                      or str(row.get("locator") or "") in locators for row in eligible) else 0.0


def deduplicate_chunks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
    for pos, row in enumerate(rows, 1):
        key = (normalized_path(row.get("source_path")), normalized_locator(row.get("locator")))
        if not key[0] or not key[1]:
            key = (normalized_path(row.get("source_path")), f"chunk:{row.get('chunk_id') or pos}")
        previous = best.get(key)
        score = float(row.get("score", float("-inf")))
        previous_score = float(previous[1].get("score", float("-inf"))) if previous else float("-inf")
        if previous is None or score > previous_score or (score == previous_score and pos < previous[0]):
            best[key] = (pos, row)
    return [row for _, row in sorted(best.values(), key=lambda item: item[0])]


def deduplicate_assets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for pos, row in enumerate(rows, 1):
        asset = str(row.get("asset_id") or "")
        previous = best.get(asset)
        score = float(row.get("score", float("-inf")))
        previous_score = float(previous[1].get("score", float("-inf"))) if previous else float("-inf")
        if previous is None or score > previous_score or (score == previous_score and pos < previous[0]):
            best[asset] = (pos, row)
    return [row for _, row in sorted(best.values(), key=lambda item: item[0])]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _ratio(value: float, denominator: int) -> dict[str, Any]:
    return {"value": value / denominator if denominator else None, "numerator": value, "denominator": denominator}


def score_population(
    records: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]],
    resolutions: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    per_query: list[dict[str, Any]] = []
    for record in records:
        gold = gold_by_id[str(record["query_id"])]
        if not gold.get("answerable"):
            continue
        evidence = gold.get("evidence") or []
        if not evidence:
            raise ValueError(f"answerable query has no evidence: {gold['id']}")
        resolved = [_resolution_index(resolutions, entry) for entry in evidence]
        chunks = deduplicate_chunks(record["chunk_ranking"])
        assets = deduplicate_assets(record["asset_ranking"])
        gold_assets = {str(entry.get("asset_id") or "") for entry in evidence}
        per_query.append({
            "id": str(gold["id"]),
            "modality": str(gold.get("modality") or "unknown"),
            "evidence": evidence,
            "resolutions": resolved,
            "chunks": chunks,
            "assets": assets,
            "gold_assets": gold_assets,
        })

    def at_k(items: list[dict[str, Any]], query: dict[str, Any], k: int) -> dict[str, Any]:
        chunks = query["chunks"][:k]
        assets = query["assets"][:k]
        fractions = [entry_fraction(chunks, evidence, resolution)
                     for evidence, resolution in zip(query["evidence"], query["resolutions"])]
        return {
            "fractions": fractions,
            "asset_hit": any(str(row.get("asset_id") or "") in query["gold_assets"] for row in assets),
            "fine_hit": any(value >= 1.0 - 1e-9 for value in fractions),
            "complete": all(value >= 1.0 - 1e-9 for value in fractions),
            "coverage": sum(fractions) / len(fractions),
            "full_entry_coverage": sum(value >= 1.0 - 1e-9 for value in fractions) / len(fractions),
            "asset_precision": (sum(str(row.get("asset_id") or "") in query["gold_assets"] for row in assets) / len(assets)) if assets else None,
            "chunk_precision": (sum(any(entry_fraction([row], evidence, resolution) > 0.0
                                         for evidence, resolution in zip(query["evidence"], query["resolutions"]))
                                     for row in chunks) / len(chunks)) if chunks else None,
        }

    def summarize(queries: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(queries)
        out: dict[str, Any] = {"answerable_queries": n, "metrics": {}}
        for k in K_VALUES:
            rows = [at_k([], query, k) for query in queries]
            metrics = {
                "asset_hit_at_k": _ratio(sum(row["asset_hit"] for row in rows), n),
                "fine_evidence_hit_at_k": _ratio(sum(row["fine_hit"] for row in rows), n),
                "fine_evidence_coverage_at_k": {"value": _mean([row["coverage"] for row in rows]), "denominator": n},
                "fine_evidence_full_entry_coverage_at_k": {"value": _mean([row["full_entry_coverage"] for row in rows]), "denominator": n},
                "complete_evidence_at_k": _ratio(sum(row["complete"] for row in rows), n),
                "asset_precision_at_k": {"value": _mean([row["asset_precision"] for row in rows if row["asset_precision"] is not None]), "denominator": n},
                "chunk_precision_at_k": {"value": _mean([row["chunk_precision"] for row in rows if row["chunk_precision"] is not None]), "denominator": n},
            }
            out["metrics"][str(k)] = metrics

        asset_rr: list[float] = []
        fine_rr: list[float] = []
        for query in queries:
            first_asset = next((i for i, row in enumerate(query["assets"][:10], 1)
                                if str(row.get("asset_id") or "") in query["gold_assets"]), None)
            asset_rr.append(1.0 / first_asset if first_asset else 0.0)
            first_fine = None
            for rank in range(1, min(10, len(query["chunks"])) + 1):
                if any(entry_fraction(query["chunks"][:rank], evidence, resolution) >= 1.0 - 1e-9
                       for evidence, resolution in zip(query["evidence"], query["resolutions"])):
                    first_fine = rank
                    break
            fine_rr.append(1.0 / first_fine if first_fine else 0.0)
        out["metrics"]["mrr"] = {
            "asset_mrr_at_10": {"value": _mean(asset_rr), "denominator": n},
            "fine_evidence_mrr_at_10": {"value": _mean(fine_rr), "denominator": n},
        }
        return out

    overall = summarize(per_query)
    modalities = sorted({row["modality"] for row in per_query})
    by_modality = {modality: summarize([row for row in per_query if row["modality"] == modality])
                   for modality in modalities}
    return {"overall": overall, "by_modality": by_modality}


def nearest_rank(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def timing_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: int(row.get("test_call_order") or 0))
    def stats(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
        values = [float(row[field]) for row in rows if row.get(field) is not None]
        return {"n": len(values), "median_ms": statistics.median(values) if values else None,
                "mean_ms": statistics.mean(values) if values else None,
                "p95_nearest_rank_ms": nearest_rank(values, 0.95) if values else None,
                "max_ms": max(values) if values else None}
    if not ordered:
        return {"n": 0}
    return {
        "n": len(ordered),
        "first_chronological_test_call": {"query_id": ordered[0].get("query_id"), "test_call_order": ordered[0].get("test_call_order"),
                                           "elapsed_ms": ordered[0].get("elapsed_ms"), "query_encode_ms": ordered[0].get("query_encode_ms"),
                                           "rank_ms": ordered[0].get("rank_ms")},
        "all_calls": {field: stats(ordered, field) for field in ("elapsed_ms", "query_encode_ms", "rank_ms")},
        "warm_calls_after_first": {field: stats(ordered[1:], field) for field in ("elapsed_ms", "query_encode_ms", "rank_ms")},
    }


def validate_attempt(
    attempt_number: int,
    gold: list[dict[str, Any]],
    frozen_evaluation: dict[str, Any],
    frozen_aggregation: dict[str, Any],
    index_sha: str,
    expected_dev: list[dict[str, Any]],
    expected_test: list[dict[str, Any]],
) -> dict[str, Any]:
    label = f"attempt-{attempt_number:02d}-query-threads4"
    manifest_path = BASE / f"run_manifest-attempt-{attempt_number:02d}-query-threads4.json"
    attempt_dir = RESULTS / label
    manifest = read_json(manifest_path)
    manifest_sha = sha256(manifest_path)
    eval_sha = manifest["contracts"]["evaluation"]["sha256"]
    agg_sha = manifest["contracts"]["aggregation"]["sha256"]
    if eval_sha != FROZEN_EVALUATION_SHA or sha256(BASE / "verification/evaluation-contract.json") != FROZEN_EVALUATION_SHA:
        raise ValueError(f"frozen evaluation contract hash mismatch for {label}")
    if agg_sha != FROZEN_AGGREGATION_SHA or sha256(BASE / "analysis/aggregation-contract.json") != FROZEN_AGGREGATION_SHA:
        raise ValueError(f"frozen aggregation contract hash mismatch for {label}")
    if index_sha != FROZEN_INDEX_SHA:
        raise ValueError("frozen index SHA mismatch")
    if manifest["model"]["revision"] != FROZEN_MODEL_REVISION:
        raise ValueError(f"frozen model revision mismatch for {label}")

    all_records: dict[str, list[dict[str, Any]]] = {}
    raw_hashes: dict[str, str] = {}
    checks: dict[str, bool] = {}
    for split, expected_queries in (("dev", expected_dev), ("test", expected_test)):
        raw_path = attempt_dir / f"{split}-query-results.jsonl"
        records = read_jsonl(raw_path)
        raw_hashes[split] = sha256(raw_path)
        expected_repetitions = int(manifest["evaluation_protocol"][f"{split}_repetitions"])
        checks[f"{split}_count"] = len(records) == len(expected_queries) * expected_repetitions
        checks[f"{split}_status_ok"] = all(row.get("status") == "ok" for row in records)
        checks[f"{split}_manifest_sha"] = all(row.get("manifest_sha256") == manifest_sha for row in records)
        checks[f"{split}_index_sha"] = all(row.get("index_sha256") == index_sha for row in records)
        checks[f"{split}_model_revision"] = all(row.get("model_revision") == FROZEN_MODEL_REVISION for row in records)
        checks[f"{split}_query_prompt"] = all(row.get("prompt_name") == "QuestionAnswering" and row.get("prompt_text") == EXPECTED_QUERY_PROMPT for row in records)
        checks[f"{split}_rank_sizes"] = all(len(row.get("chunk_ranking", [])) == 63 and len(row.get("asset_ranking", [])) == 14 for row in records)
        expected_by_id = {str(row.get("id")): row for row in expected_queries}
        checks[f"{split}_query_text"] = all(
            str(row.get("query_id")) in expected_by_id
            and row.get("query_text") == expected_by_id[str(row["query_id"])].get("question", expected_by_id[str(row["query_id"])].get("query_text"))
            for row in records
        )
        checks[f"{split}_query_prompts_by_manifest"] = (
            manifest["embedding_protocol"].get("query_prompt_name") == "QuestionAnswering"
            and manifest["embedding_protocol"].get("query_prompt_text") == EXPECTED_QUERY_PROMPT
        )
        if split == "test":
            order = [int(row.get("test_call_order") or 0) for row in records]
            checks["test_call_order_1_to_180"] = order == list(range(1, 181))
            repetitions = [int(row.get("repetition") or 0) for row in records]
            checks["test_repetitions_canonical"] = repetitions == ([1] * 60 + [2] * 60 + [3] * 60)
            checks["test_canonical_order_each_rep"] = all(
                [int(row.get("canonical_order") or 0) for row in records[start:start + 60]] == list(range(1, 61))
                for start in (0, 60, 120)
            )
            checks["test_query_id_repetitions"] = all(
                [str(row.get("query_id")) for row in records[start:start + 60]]
                == [str(row.get("id")) for row in expected_test]
                for start in (0, 60, 120)
            )
        else:
            checks["dev_single_canonical_order"] = [int(row.get("canonical_order") or 0) for row in records] == list(range(1, 16))
        all_records[split] = records

    runtime_path = attempt_dir / "runtime.json"
    runtime = read_json(runtime_path) if runtime_path.exists() else None
    runtime_ok = bool(runtime and runtime.get("torch_threads") == 4
                       and runtime.get("resolved_model_revision") == FROZEN_MODEL_REVISION
                       and runtime.get("index_sha256") == index_sha
                       and runtime.get("vector_file_sha256") == FROZEN_VECTOR_SHA
                       and runtime.get("manifest_sha256") == manifest_sha)
    checks["runtime_receipt_4_threads_same_index_vectors"] = runtime_ok

    failure_path = attempt_dir / "query-resume-failure.json"
    failure = read_json(failure_path) if failure_path.exists() else None
    result_path = attempt_dir / "run-result.json"
    run_result = read_json(result_path) if result_path.exists() else None
    validation_path = attempt_dir / "raw-record-validation.json"
    validation = read_json(validation_path) if validation_path.exists() else None
    checks["run_result_complete_and_bound"] = bool(
        run_result
        and run_result.get("status") == "complete"
        and run_result.get("attempt_id") == label
        and run_result.get("manifest_sha256") == manifest_sha
        and run_result.get("index_sha256") == index_sha
    )
    checks["raw_validation_receipt_pass_and_bound"] = bool(
        validation
        and validation.get("status") == "pass"
        and validation.get("manifest_sha256") == manifest_sha
        and validation.get("evaluation_contract_sha256") == FROZEN_EVALUATION_SHA
        and validation.get("aggregation_contract_sha256") == FROZEN_AGGREGATION_SHA
        and validation.get("source_index_sha256") == index_sha
        and validation.get("vector_file_sha256") == FROZEN_VECTOR_SHA
    )
    raw_complete = all(checks.get(k, False) for k in checks if k not in {"runtime_receipt_4_threads_same_index_vectors"})
    formal_candidate = raw_complete and runtime_ok and failure is None

    gold_by_id = {str(row["id"]): row for row in gold}
    quality_all_splits_repetitions: dict[str, Any] = {}
    for split, records in all_records.items():
        for repetition in sorted({int(row.get("repetition") or 0) for row in records}):
            subset = [row for row in records if int(row.get("repetition") or 0) == repetition]
            quality_all_splits_repetitions[f"{split}_rep{repetition}"] = score_population(subset, gold_by_id, GLOBAL_RESOLUTIONS)
    quality = quality_all_splits_repetitions["test_rep1"]
    test_repetition_1 = [row for row in all_records["test"] if int(row.get("repetition") or 0) == 1]
    unanswerable = []
    for record in test_repetition_1:
        qgold = gold_by_id[str(record["query_id"])]
        if qgold.get("answerable"):
            continue
        assets = deduplicate_assets(record["asset_ranking"])
        chunks = deduplicate_chunks(record["chunk_ranking"])
        unanswerable.append({
            "id": qgold["id"], "evidence_entry_count": len(qgold.get("evidence") or []),
            "top_asset": assets[0].get("asset_id") if assets else None,
            "top_asset_score": assets[0].get("score") if assets else None,
            "top_chunk_id": chunks[0].get("chunk_id") if chunks else None,
            "ranked_results_returned": bool(assets or chunks),
        })

    timing = timing_summary(all_records["test"])
    if runtime:
        timing["runtime_state"] = {k: runtime.get(k) for k in (
            "torch_threads", "model_loaded_before_query_calls", "first_test_call_is_cold",
            "query_stage_model_load_seconds", "process_rss_after_queries_bytes",
            "process_max_rss_bytes_query_container", "cgroup_peak_bytes_query_container",
        )}
    return {
        "attempt": label,
        "formal_candidate": formal_candidate,
        "manifest_sha256": manifest_sha,
        "raw_sha256": raw_hashes,
        "raw_record_counts": {split: len(rows) for split, rows in all_records.items()},
        "checks": checks,
        "failed_check_names": [name for name, value in checks.items() if not value],
        "failure_receipt": failure,
        "run_result_status": (run_result or {}).get("status"),
        "run_result_attempt_id": (run_result or {}).get("attempt_id"),
        "raw_validation_status": (validation or {}).get("status"),
        "quality_primary_test_repetition_1": quality,
        "quality_all_splits_repetitions": quality_all_splits_repetitions,
        "unanswerable_test_repetition_1": unanswerable,
        "test_timing": timing,
    }


def main() -> None:
    evaluation_path = BASE / "verification/evaluation-contract.json"
    aggregation_path = BASE / "analysis/aggregation-contract.json"
    evaluation = read_json(evaluation_path)
    aggregation = read_json(aggregation_path)
    if sha256(evaluation_path) != FROZEN_EVALUATION_SHA:
        raise ValueError("evaluation-contract.json changed from its frozen SHA")
    if sha256(aggregation_path) != FROZEN_AGGREGATION_SHA:
        raise ValueError("aggregation-contract.json changed from its frozen SHA")

    gold_path = PROJECT / evaluation["frozen_inputs"]["gold_path"]
    gold = read_json(gold_path)
    index_path = BASE / "index.jsonl"
    index_sha = sha256(index_path)
    index_rows = read_jsonl(index_path)
    resolution_path = BASE / "analysis/locator-resolution.json"
    resolution_data = read_json(resolution_path)
    if resolution_data.get("inputs", {}).get("index_sha256") != index_sha:
        raise ValueError("source resolution ledger index SHA does not match current index")
    if resolution_data.get("inputs", {}).get("gold_sha256") != sha256(gold_path):
        raise ValueError("source resolution ledger gold SHA does not match current gold")

    resolution_map = {
        (str(row.get("asset_id") or ""), normalized_path(row.get("path")), normalized_locator(row.get("gold_location"))): row
        for row in resolution_data.get("entries", [])
    }
    global GLOBAL_RESOLUTIONS
    GLOBAL_RESOLUTIONS = resolution_map

    attempts: list[dict[str, Any]] = []
    for attempt_number in (4, 5):
        manifest_path = BASE / f"run_manifest-attempt-{attempt_number:02d}-query-threads4.json"
        manifest = read_json(manifest_path)
        query_files: dict[str, list[dict[str, Any]]] = {}
        for split in ("dev", "test"):
            input_path = PROJECT / manifest["inputs"]["queries"][split]["path"]
            expected_sha = manifest["inputs"]["queries"][split]["sha256_from_evaluation_contract"]
            if sha256(input_path) != expected_sha:
                raise ValueError(f"{split} query file SHA mismatch")
            query_files[split] = read_jsonl(input_path)
        attempts.append(validate_attempt(attempt_number, gold, evaluation, aggregation, index_sha,
                                         query_files["dev"], query_files["test"]))

    # Attempt 03's exclusion is verified from the actual failure receipt and
    # the original run's measured thread count, not inferred from its title.
    source_manifest = read_json(BASE / "run_manifest.json")
    attempt03_manifest = read_json(BASE / "run_manifest-attempt-03-query-threads4.json")
    attempt03_failure = read_json(RESULTS / "attempt-03-query-threads4/query-resume-failure.json")
    runtime_probe_path = BASE / "container-runtime.json"
    runtime_probe = read_json(runtime_probe_path)
    source_runtime = source_manifest.get("runtime", {})
    attempt03_runtime = attempt03_manifest.get("runtime", {})
    attempt03_traceback = str(attempt03_failure.get("traceback") or "")
    attempt03_audit = {
        "failure_status": attempt03_failure.get("status"),
        "failure_type": attempt03_failure.get("error_type"),
        "failure_reason": attempt03_failure.get("error"),
        "source_manifest_sha256": sha256(BASE / "run_manifest.json"),
        "source_manifest_has_runtime_probe_field": "torch_threads_from_same_image_runtime_probe" in source_runtime,
        "attempt03_manifest_runtime_probe_field": attempt03_runtime.get("torch_threads_from_same_image_runtime_probe"),
        "runtime_probe_file_sha256": sha256(runtime_probe_path),
        "source_manifest_runtime_sha256": source_runtime.get("sha256"),
        "attempt03_manifest_runtime_sha256": attempt03_runtime.get("sha256"),
        "runtime_probe_torch_threads": runtime_probe.get("torch_threads"),
        "same_runtime_probe_file_bound_in_both_manifests": (
            source_runtime.get("sha256") == attempt03_runtime.get("sha256") == sha256(runtime_probe_path)
        ),
        "failure_trace_is_manifest_value_equality_guard": (
            'manifest["runtime"].get(key) == source_manifest["runtime"].get(key)' in attempt03_traceback
        ),
        "source_index_runner_setter": attempt03_runtime.get("index_runner_thread_setter"),
        "source_index_process_thread_readback_serialized": attempt03_runtime.get("index_process_thread_readback_serialized"),
        "source_index_actual_thread_count_verifiable": attempt03_runtime.get("index_process_thread_readback_serialized") is True,
        "attempt03_vector_sha256": sha256(RESULTS / "attempt-03-query-threads4/index-vectors.npy"),
        "attempt05_vector_sha256": sha256(RESULTS / "attempt-05-query-threads4/index-vectors.npy"),
        "exclusion_cause": "The added same-image probe field was absent from the source manifest, so the resume guard rejected the differing manifest value. This does not show that the live probe differed; the referenced probe file and measured value are both 4 threads. The source indexing process thread readback was not serialized.",
        "exclusion_reason_supported": (
            attempt03_failure.get("status") == "fatal_error"
            and attempt03_failure.get("error_type") == "RuntimeError"
            and not ("torch_threads_from_same_image_runtime_probe" in source_runtime)
            and attempt03_runtime.get("torch_threads_from_same_image_runtime_probe") == 4
            and runtime_probe.get("torch_threads") == 4
            and source_runtime.get("sha256") == attempt03_runtime.get("sha256") == sha256(runtime_probe_path)
            and 'manifest["runtime"].get(key) == source_manifest["runtime"].get(key)' in attempt03_traceback
            and attempt03_runtime.get("index_process_thread_readback_serialized") is False
        ),
    }

    chunk_by_id = {str(row.get("chunk_id")): row for row in index_rows}
    temporal_counts: dict[str, int] = {
        "audio_evidence_entries": 0, "audio_mapped_chunk_refs": 0, "audio_overlong_chunk_refs": 0,
        "audio_evidence_entries_with_overlong_chunks": 0,
        "video_evidence_entries": 0, "video_mapped_chunk_refs": 0, "video_overlong_chunk_refs": 0,
    }
    for entry in resolution_data.get("entries", []):
        if entry.get("kind") != "time_interval":
            continue
        interval = entry.get("gold_interval_seconds") or {}
        gold_duration = float(interval["end"]) - float(interval["start"])
        media = "audio" if "/audio/" in normalized_path(entry.get("path")) else "video"
        temporal_counts[f"{media}_evidence_entries"] += 1
        entry_overlong = False
        for chunk_id in entry.get("matched_chunk_ids", []):
            indexed = chunk_by_id.get(str(chunk_id))
            if not indexed or not indexed.get("interval_seconds"):
                continue
            unit = indexed["interval_seconds"]
            unit_duration = float(unit["end"]) - float(unit["start"])
            temporal_counts[f"{media}_mapped_chunk_refs"] += 1
            if unit_duration > gold_duration + 1e-6:
                temporal_counts[f"{media}_overlong_chunk_refs"] += 1
                entry_overlong = True
        if media == "audio" and entry_overlong:
            temporal_counts["audio_evidence_entries_with_overlong_chunks"] += 1

    helper_path = BASE / "analysis/summarize.py"
    helper_hash = sha256(helper_path)
    attempt04, attempt05 = attempts
    quality_equal = attempt04["quality_primary_test_repetition_1"] == attempt05["quality_primary_test_repetition_1"]
    quality_tables_equal = attempt04["quality_all_splits_repetitions"] == attempt05["quality_all_splits_repetitions"]
    report = {
        "schema": "embeddinggemma2-independent-raw-reaggregation/v1",
        "scope": "Raw independent reaggregation for primary test repetition 1, plus complete-record and timing checks. No model was run.",
        "contracts": {
            "evaluation_contract_sha256": sha256(evaluation_path),
            "aggregation_contract_sha256": sha256(aggregation_path),
            "aggregation_helper_sha256_at_reaggregation": helper_hash,
            "locator_resolution_sha256": sha256(resolution_path),
            "gold_sha256": sha256(gold_path),
            "index_sha256": index_sha,
            "index_chunk_count": len(index_rows),
            "frozen_temporal_rule": evaluation["metrics"]["locator_coverage"]["audio_video"],
        },
        "attempt03_runtime_probe_exclusion_audit": attempt03_audit,
        "frozen_temporal_unit_audit": {
            "counts": temporal_counts,
            "contract_implication": "Overlong retrieved audio chunks remain asset-level hits but are excluded from fine interval coverage. This is a locator-granularity constraint, not an audio-understanding score.",
        },
        "attempts": attempts,
        "attempt04_attempt05_primary_quality_metrics_equal": quality_equal,
        "attempt04_attempt05_all_repetition_quality_tables_equal": quality_tables_equal,
        "formal_attempt_selected_by_independent_evidence": "attempt-05-query-threads4" if attempt05["formal_candidate"] else None,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "formal_attempt": report["formal_attempt_selected_by_independent_evidence"],
        "attempt04_failed_checks": attempt04["failed_check_names"],
        "attempt05_failed_checks": attempt05["failed_check_names"],
        "attempt05_quality_at_1": attempt05["quality_primary_test_repetition_1"]["overall"]["metrics"]["1"],
        "attempt05_mrr": attempt05["quality_primary_test_repetition_1"]["overall"]["metrics"]["mrr"],
        "attempt05_timing": attempt05["test_timing"],
        "attempt03_exclusion_supported": attempt03_audit["exclusion_reason_supported"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
