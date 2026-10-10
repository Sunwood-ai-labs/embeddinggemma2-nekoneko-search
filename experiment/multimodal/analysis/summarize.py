#!/usr/bin/env python3
"""Reproducibly aggregate frozen EmbeddingGemma 2 retrieval-run records.

The ranking JSONL schema is configurable with dotted field-path arguments.
The default assumes one JSON object per query call and a ranked ``results``
array whose items include ``chunk_id`` and ``score``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = DEFAULT_ROOT / "verification" / "evaluation-contract.json"
CONTENT_FIELDS = ("text", "content", "extracted_text", "transcript", "ocr_text")
TIME_COMPARISON_TOLERANCE_SECONDS = 1e-6
VERIFIER_CASE_NOTES = {
    "NKB-017": "独立検収メモ: P-QAにも3.0%の値がある。gold source-matchのmissは回答正誤を意味しない。",
    "NKB-018": "独立検収メモ: P-QAに3ロット合計の入力値がある。gold source-matchはこの代替資料を得点対象にしない。",
    "NKB-019": "独立検収メモ: P-QAに3ロット合計の入力値がある。gold source-matchはこの代替資料を得点対象にしない。",
    "NKB-021": "独立検収メモ: P-QAにも1.0%がありasset rank 2。top-1はA-QA。gold source-matchと回答の正誤を分けて読む。",
    "NKB-023": "独立検収メモ: EXP102の14,500行はD-HRに存在せず、別資料で確認できた同値入力ではない。",
    "NKB-024": "独立検収メモ: D-HRに2,000の値はあるが、取得top chunkは期限の locator で、手当額の取得根拠とはみなさない。",
}


def field(value: Any, path: str | None, default: Any = None) -> Any:
    if not path:
        return default
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def records(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for key in ("records", "queries", "results", "items"):
                if isinstance(value.get(key), list):
                    return [item for item in value[key] if isinstance(item, dict)]
            return [value]
    except json.JSONDecodeError:
        pass
    output = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{line_number}: each JSONL row must be an object")
        output.append(item)
    return output


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(char for char in text if char.isalnum())


def normalized_path(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.casefold().strip("/")


def evidence_key(evidence: dict[str, Any]) -> str:
    return "|".join((str(evidence.get("asset_id") or ""), normalized_path(evidence.get("path")), normalized(evidence.get("location"))))


def load_locator_resolutions(path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = data.get("entries", [])
    output = {}
    for entry in entries:
        key = str(entry.get("entry_key") or evidence_key(entry))
        if key in output:
            raise ValueError(f"duplicate locator resolution key: {key}")
        output[key] = entry
    return output, entries


def resolution_for(evidence: dict[str, Any], resolutions: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    return resolutions.get(evidence_key(evidence))


def to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(to_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(to_text(item) for item in value.values())
    return str(value)


_TIME_TOKEN = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?"
_TIME_RANGE = re.compile(rf"({_TIME_TOKEN})\s*(?:-|–|—|to)\s*({_TIME_TOKEN})", re.IGNORECASE)


def seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def time_range(value: Any) -> tuple[float, float] | None:
    text = str(value or "")
    match = _TIME_RANGE.search(text)
    if not match:
        return None
    # Avoid treating hyphenated identifiers such as ``TEST-F2-118`` as a
    # time range. Numeric-only ranges need an explicit seconds unit; timestamps
    # and decimal second ranges already carry an unambiguous time shape.
    start_text, end_text = match.group(1), match.group(2)
    unit_after = re.match(r"\s*(?:s\b|sec(?:ond)?s?\b)", text[match.end():], re.IGNORECASE)
    if ":" not in start_text + end_text and "." not in start_text + end_text and not unit_after:
        return None
    try:
        start, end = seconds(start_text), seconds(end_text)
    except ValueError:
        return None
    return (start, end) if end > start else None


def interval(row: dict[str, Any]) -> tuple[float, float] | None:
    value = row.get("interval_seconds")
    if isinstance(value, dict):
        start, end = number(value.get("start")), number(value.get("end"))
        if start is not None and end is not None and end > start:
            return start, end
    for candidate in (row.get("locator"), *as_list(row.get("evidence_units"))):
        parsed = time_range(candidate)
        if parsed:
            return parsed
    return None


def page_number(value: str) -> int | None:
    match = re.search(r"(?:\bp(?:age)?\s*[:#]?\s*|ページ\s*[:#]?\s*)(\d+)\b", value, re.IGNORECASE)
    return int(match.group(1)) if match else None


def slide_number(value: str) -> int | None:
    match = re.search(r"(?:\bslide\s*[:#]?\s*|スライド\s*[:#]?\s*)(\d+)\b", value, re.IGNORECASE)
    return int(match.group(1)) if match else None


def cell_refs(value: str) -> set[str]:
    return {match.group(0).replace("$", "").upper() for match in re.finditer(r"(?<![A-Z0-9])[A-Z]{1,3}\$?\d+(?![A-Z0-9])", value.upper())}


def cell_parts(value: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", value.upper().replace("$", ""))
    return (match.group(1), int(match.group(2))) if match else None


def column_number(value: str) -> int:
    result = 0
    for char in value:
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def column_label(value: int) -> str:
    label = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


def expanded_cells(value: str) -> set[str]:
    result = cell_refs(value)
    for match in re.finditer(r"(?<![A-Z0-9])(\$?[A-Z]{1,3}\$?\d+)\s*:\s*(\$?[A-Z]{1,3}\$?\d+)(?![A-Z0-9])", value.upper()):
        first = cell_parts(match.group(1))
        last = cell_parts(match.group(2))
        if not first or not last:
            continue
        c1, r1 = column_number(first[0]), first[1]
        c2, r2 = column_number(last[0]), last[1]
        width, height = abs(c2 - c1) + 1, abs(r2 - r1) + 1
        if width * height <= 5000:
            for column in range(min(c1, c2), max(c1, c2) + 1):
                for row in range(min(r1, r2), max(r1, r2) + 1):
                    result.add(f"{column_label(column)}{row}")
    return result


def candidate_locator_row(candidate: dict[str, Any]) -> dict[str, Any]:
    row = dict(candidate.get("index") or {})
    row["locator"] = candidate.get("locator") or row.get("locator")
    return row


def asset_path_matches(candidate: dict[str, Any], evidence: dict[str, Any], asset_paths: dict[str, str]) -> bool:
    expected_asset = str(evidence.get("asset_id") or "")
    if expected_asset and candidate["asset_id"] != expected_asset:
        return False
    expected_path = normalized_path(evidence.get("path") or asset_paths.get(expected_asset, ""))
    actual_path = normalized_path(candidate.get("path") or asset_paths.get(candidate.get("asset_id", ""), ""))
    return not expected_path or expected_path == actual_path


def candidate_in_resolution(candidate: dict[str, Any], resolution: dict[str, Any]) -> bool:
    chunk_ids = set(str(value) for value in resolution.get("matched_chunk_ids", []))
    if candidate.get("chunk_id") and str(candidate["chunk_id"]) in chunk_ids:
        return True
    locators = set(str(value) for value in resolution.get("matched_index_locators", []))
    return bool(candidate.get("locator") and str(candidate["locator"]) in locators)


def rounded_interval(value: tuple[float, float] | None) -> tuple[float, float] | None:
    if value is None:
        return None
    return (round(value[0], 3), round(value[1], 3))


def gold_interval_from_resolution(resolution: dict[str, Any]) -> tuple[float, float] | None:
    value = resolution.get("gold_interval_seconds")
    if not isinstance(value, dict):
        return None
    start, end = number(value.get("start")), number(value.get("end"))
    if start is None or end is None or end <= start:
        return None
    return rounded_interval((start, end))


def overlapping_overlong_candidates(
    candidates: list[dict[str, Any]], evidence: dict[str, Any], asset_paths: dict[str, str],
    resolutions: dict[str, dict[str, Any]],
) -> list[tuple[dict[str, Any], tuple[float, float], float, float]]:
    resolution = resolution_for(evidence, resolutions)
    if not resolution or resolution.get("status") != "resolved" or resolution.get("kind") != "time_interval":
        return []
    gold_interval = gold_interval_from_resolution(resolution)
    if not gold_interval:
        return []
    gold_start, gold_end = gold_interval
    gold_duration = gold_end - gold_start
    excluded = []
    for candidate in candidates:
        if not (asset_path_matches(candidate, evidence, asset_paths)
                and candidate_in_resolution(candidate, resolution)):
            continue
        candidate_interval = rounded_interval(interval(candidate_locator_row(candidate)))
        if not candidate_interval:
            continue
        start, end = candidate_interval
        duration = end - start
        overlaps = start < gold_end and end > gold_start
        if overlaps and duration > gold_duration + TIME_COMPARISON_TOLERANCE_SECONDS:
            excluded.append((candidate, candidate_interval, duration, gold_duration))
    return excluded


def structurally_matches(
    candidate: dict[str, Any], evidence: dict[str, Any], asset_paths: dict[str, str],
    resolutions: dict[str, dict[str, Any]],
) -> bool:
    resolution = resolution_for(evidence, resolutions)
    return bool(resolution and resolution.get("status") == "resolved"
                and asset_path_matches(candidate, evidence, asset_paths)
                and candidate_in_resolution(candidate, resolution)
                and locator_matches(str(evidence.get("location") or ""), candidate_locator_row(candidate), resolution))


def evidence_entry_fraction(
    candidates: list[dict[str, Any]], evidence: dict[str, Any], asset_paths: dict[str, str],
    resolutions: dict[str, dict[str, Any]],
) -> float | None:
    resolution = resolution_for(evidence, resolutions)
    if not resolution or resolution.get("status") != "resolved":
        return None
    eligible = [candidate for candidate in candidates
                if asset_path_matches(candidate, evidence, asset_paths) and candidate_in_resolution(candidate, resolution)]
    location = str(evidence.get("location") or "")
    target_time = time_range(location)
    if target_time:
        target_time = gold_interval_from_resolution(resolution) or rounded_interval(target_time)
        gold_duration = target_time[1] - target_time[0]
        intervals = []
        for candidate in eligible:
            item = rounded_interval(interval(candidate_locator_row(candidate)))
            if item and item[1] - item[0] <= gold_duration + TIME_COMPARISON_TOLERANCE_SECONDS:
                intervals.append(item)
        intervals.sort(key=lambda item: item[0])
        cursor = target_time[0]
        covered = 0.0
        for start, end in intervals:
            start = max(start, target_time[0])
            end = min(end, target_time[1])
            if end <= start or end <= cursor:
                continue
            covered += max(0.0, end - max(cursor, start))
            cursor = max(cursor, end)
        return min(1.0, covered / (target_time[1] - target_time[0]))

    target_cells = set(resolution.get("required_cells") or []) if resolution.get("kind") == "spreadsheet_cells" else set()
    if target_cells:
        found = set()
        for candidate in eligible:
            row = candidate_locator_row(candidate)
            for locator in (row.get("locator"), *as_list(row.get("evidence_units"))):
                found.update(expanded_cells(str(locator or "")))
        return len(target_cells & found) / len(target_cells)

    return 1.0 if any(locator_matches(location, candidate_locator_row(candidate), resolution) for candidate in eligible) else 0.0


def evidence_entry_covered(candidates: list[dict[str, Any]], evidence: dict[str, Any], asset_paths: dict[str, str],
                           resolutions: dict[str, dict[str, Any]]) -> bool:
    fraction = evidence_entry_fraction(candidates, evidence, asset_paths, resolutions)
    resolution = resolution_for(evidence, resolutions)
    if fraction is None or not resolution:
        return False
    if resolution.get("kind") == "time_interval":
        gold_interval = gold_interval_from_resolution(resolution)
        if not gold_interval:
            return False
        uncovered_seconds = (1.0 - fraction) * (gold_interval[1] - gold_interval[0])
        return uncovered_seconds <= TIME_COMPARISON_TOLERANCE_SECONDS
    return fraction >= 1.0


def evidence_coverage(candidates: list[dict[str, Any]], evidence_entries: list[Any], asset_paths: dict[str, str],
                      resolutions: dict[str, dict[str, Any]]) -> set[int]:
    return {
        index for index, entry in enumerate(evidence_entries)
        if isinstance(entry, dict) and evidence_entry_covered(candidates, entry, asset_paths, resolutions)
    }


def evidence_entry_fractions(candidates: list[dict[str, Any]], evidence_entries: list[Any], asset_paths: dict[str, str],
                             resolutions: dict[str, dict[str, Any]]) -> list[float | None]:
    return [
        evidence_entry_fraction(candidates, entry, asset_paths, resolutions) if isinstance(entry, dict) else None
        for entry in evidence_entries
    ]


def granularity_diagnostic_row(
    query_id: str, split: str, repetition: int, k: int, evidence_index: int,
    candidates: list[dict[str, Any]], evidence: dict[str, Any], asset_paths: dict[str, str],
    resolutions: dict[str, dict[str, Any]], asset_hit_at_k: bool,
) -> dict[str, Any] | None:
    resolution = resolution_for(evidence, resolutions)
    if not resolution or resolution.get("status") != "resolved" or resolution.get("kind") != "time_interval":
        return None
    gold_time = gold_interval_from_resolution(resolution)
    if not gold_time:
        return None
    fraction = evidence_entry_fraction(candidates, evidence, asset_paths, resolutions)
    if fraction is None:
        return None

    gold_duration = gold_time[1] - gold_time[0]
    overlong = overlapping_overlong_candidates(candidates, evidence, asset_paths, resolutions)
    structurally_eligible = [candidate for candidate in candidates
                             if asset_path_matches(candidate, evidence, asset_paths)
                             and candidate_in_resolution(candidate, resolution)]
    admissible = []
    for candidate in structurally_eligible:
        candidate_time = rounded_interval(interval(candidate_locator_row(candidate)))
        if candidate_time and candidate_time[1] - candidate_time[0] <= gold_duration + TIME_COMPARISON_TOLERANCE_SECONDS:
            admissible.append((candidate, candidate_time))

    fully_covered = evidence_entry_covered(candidates, evidence, asset_paths, resolutions)
    if fully_covered and not overlong:
        return None
    if fully_covered:
        fine_status = "full"
        reason = "full_coverage_from_admissible_intervals; longer overlapping intervals excluded"
    elif fraction > 0:
        fine_status = "partial"
        reason = ("partial_union_after_excluding_overlong_intervals" if overlong
                  else "admissible_interval_union_covers_only_part_of_gold")
    elif overlong:
        fine_status = "zero"
        reason = ("asset_hit_but_all_overlapping_source_intervals_exceed_gold_duration" if asset_hit_at_k
                  else "all_overlapping_source_intervals_exceed_gold_duration")
    elif asset_hit_at_k:
        fine_status = "zero"
        reason = "asset_hit_without_a_qualifying_segment_specific_interval"
    else:
        fine_status = "zero"
        reason = "no_qualifying_segment_specific_interval_retrieved"

    def candidate_summary(candidate: dict[str, Any], value: tuple[float, float]) -> str:
        return f"{candidate.get('chunk_id','')}|{candidate.get('locator','')}|{value[0]:.3f}-{value[1]:.3f}s"

    return {
        "query_id": query_id,
        "split": split,
        "repetition": repetition,
        "k": k,
        "evidence_index": evidence_index,
        "asset_id": evidence.get("asset_id", ""),
        "source_path": evidence.get("path", ""),
        "gold_location": evidence.get("location", ""),
        "gold_start_seconds": gold_time[0],
        "gold_end_seconds": gold_time[1],
        "gold_duration_seconds": gold_duration,
        "asset_hit_at_k": asset_hit_at_k,
        "fine_coverage_fraction": fraction,
        "fine_status": fine_status,
        "admissible_interval_candidates": len(admissible),
        "overlong_overlapping_candidates": len(overlong),
        "admissible_candidate_ranges": ";".join(candidate_summary(candidate, value) for candidate, value in admissible),
        "excluded_overlong_candidate_ranges": ";".join(candidate_summary(candidate, value) for candidate, value, _, _ in overlong),
        "excluded_overlong_candidate_ids": ";".join(str(candidate.get("chunk_id", "")) for candidate, _, _, _ in overlong),
        "reason": reason,
    }


def locator_matches(gold_location: str, row: dict[str, Any], resolution: dict[str, Any] | None = None) -> bool:
    locators = [str(row.get("locator") or ""), *(str(item) for item in as_list(row.get("evidence_units")))]
    locators = [value for value in locators if value]
    if not locators:
        return False

    if resolution is not None:
        if resolution.get("status") != "resolved":
            return False
        kind = resolution.get("kind")
        if kind == "docx_section":
            return str(resolution.get("index_locator") or "") in locators
        if kind == "pdf_page":
            return any(page_number(locator) == resolution.get("page_number") for locator in locators)
        if kind == "presentation_slide":
            return any(slide_number(locator) == resolution.get("slide_number") for locator in locators)
        if kind == "spreadsheet_cells":
            expected_sheet = resolution.get("index_sheet_number")
            row_locator = str(row.get("locator") or "")
            match = re.search(r"\bsheet:(\d+)\b", row_locator)
            if match is None or int(match.group(1)) != expected_sheet:
                return False
            gold_cells = set(resolution.get("required_cells") or [])
            candidate_cells = set().union(*(expanded_cells(locator) for locator in locators))
            return bool(gold_cells & candidate_cells)
        if kind == "time_interval":
            gold_time = gold_interval_from_resolution(resolution)
            candidate_time = rounded_interval(interval(row))
            if not gold_time or not candidate_time:
                return False
            gold_duration = gold_time[1] - gold_time[0]
            candidate_duration = candidate_time[1] - candidate_time[0]
            return bool(candidate_duration <= gold_duration + TIME_COMPARISON_TOLERANCE_SECONDS
                        and candidate_time[0] < gold_time[1] and candidate_time[1] > gold_time[0])

    gold_time = time_range(gold_location)
    if gold_time:
        candidate_time = interval(row)
        if candidate_time:
            return candidate_time[0] < gold_time[1] and candidate_time[1] > gold_time[0]
        return False

    gold_page = page_number(gold_location)
    if gold_page is not None:
        for locator in locators:
            candidate_page = page_number(locator)
            if candidate_page == gold_page:
                return True

    gold_slide = slide_number(gold_location)
    if gold_slide is not None:
        for locator in locators:
            if slide_number(locator) == gold_slide:
                return True

    gold_cells = cell_refs(gold_location)
    if gold_cells:
        candidate_cells = set().union(*(cell_refs(locator) for locator in locators))
        if gold_cells & candidate_cells:
            return True

    # For section headings (including a page plus heading), require the
    # annotated heading text itself to occur in a source-derived locator.
    heading = re.sub(r"\bp(?:age)?\s*[:#]?\s*\d+\b", "", gold_location, flags=re.IGNORECASE)
    heading = re.sub(r"\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*s?", "", heading, flags=re.IGNORECASE)
    key = normalized(heading)
    if key and any(key in normalized(locator) for locator in locators):
        return True
    return any(normalized(locator) in normalized(gold_location) for locator in locators if len(normalized(locator)) >= 3)


def load_contract_assets(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    assets = data.get("frozen_inputs", {}).get("assets", [])
    return {str(item["asset_id"]): str(item["path"]) for item in assets if item.get("asset_id") and item.get("path")}


def index_map(index_rows: list[dict[str, Any]], chunk_field: str) -> dict[str, dict[str, Any]]:
    output = {}
    for row in index_rows:
        chunk_id = field(row, chunk_field)
        if chunk_id is None:
            continue
        chunk_id = str(chunk_id)
        if chunk_id in output:
            raise ValueError(f"duplicate index chunk_id: {chunk_id}")
        output[chunk_id] = row
    return output


def index_source_map(index_rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[tuple[str, str, str], dict[str, Any]]:
    output = {}
    for row in index_rows:
        asset_id = field(row, args.index_asset_id_field)
        source_path = field(row, args.index_path_field)
        locator = field(row, args.index_locator_field)
        if asset_id is None or source_path is None or locator is None:
            continue
        output[(str(asset_id), normalized_path(source_path), normalized(locator))] = row
    return output


def scored(value: Any) -> tuple[float | None, str]:
    if value is None:
        return None, "missing"
    parsed = number(value)
    if parsed is None:
        try:
            raw = float(value)
            if not math.isfinite(raw):
                return None, "nonfinite"
        except (TypeError, ValueError):
            return None, "invalid"
    return parsed, "known"


def make_candidates(
    call: dict[str, Any],
    index_by_chunk: dict[str, dict[str, Any]],
    index_by_source: dict[tuple[str, str, str], dict[str, Any]],
    asset_paths: dict[str, str],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    result_values = field(call["raw"], args.results_field, [])
    if result_values is None:
        result_values = []
    if isinstance(result_values, dict):
        result_values = result_values.get("items", result_values.get("results", []))
    if not isinstance(result_values, list):
        raise ValueError(f"query {call['query_id']}: result field must be an array")
    candidates = []
    for position, raw_item in enumerate(result_values):
        if not isinstance(raw_item, dict):
            continue
        chunk_id = field(raw_item, args.result_chunk_id_field)
        index_row = index_by_chunk.get(str(chunk_id)) if chunk_id is not None else None
        asset_id = field(raw_item, args.result_asset_id_field)
        locator = field(raw_item, args.result_locator_field)
        source_path = field(raw_item, args.result_path_field)
        raw_chunk_id = str(chunk_id) if chunk_id is not None else ""
        if index_row is None and asset_id is not None and locator:
            lookup_path = source_path or asset_paths.get(str(asset_id), "")
            index_row = index_by_source.get((str(asset_id), normalized_path(lookup_path), normalized(locator)))
        if index_row:
            chunk_id = field(index_row, args.index_chunk_id_field, chunk_id)
            asset_id = field(index_row, args.index_asset_id_field, asset_id)
            locator = field(index_row, args.index_locator_field, locator)
            source_path = field(index_row, args.index_path_field, source_path)
        asset_id = str(asset_id) if asset_id is not None else ""
        source_path = str(source_path or asset_paths.get(asset_id, ""))
        score_value = field(raw_item, args.result_score_field)
        score, score_state = scored(score_value)
        explicit_rank = number(field(raw_item, args.result_rank_field))
        row = index_row or {}
        candidates.append({
            "chunk_id": str(chunk_id) if chunk_id is not None else "",
            "raw_chunk_id": raw_chunk_id,
            "index_resolved": index_row is not None,
            "index_resolution_method": "chunk_id" if raw_chunk_id and raw_chunk_id in index_by_chunk else ("source_locator" if index_row is not None else "unresolved"),
            "asset_id": asset_id,
            "path": source_path,
            "locator": str(locator or ""),
            "score": score,
            "score_raw": score_value,
            "score_state": score_state,
            "rank": explicit_rank,
            "position": position,
            "index": row,
        })
    return candidates


def deduplicate(candidates: list[dict[str, Any]], unit: str, order_mode: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        if unit == "asset":
            key = candidate["asset_id"] or f"missing-asset:{candidate['position']}"
        else:
            path = normalized_path(candidate["path"])
            locator = normalized(candidate["locator"])
            key = f"{path}|{locator}" if path and locator else f"missing-locator:{candidate['position']}"
        groups[key].append(candidate)

    selected = []
    for values in groups.values():
        finite = [item for item in values if item["score"] is not None]
        if finite and len(finite) == len(values):
            best = max(item["score"] for item in finite)
            chosen = next(item for item in finite if item["score"] == best)
        else:
            chosen = min(values, key=lambda item: item["rank"] if item["rank"] is not None else item["position"])
        chosen = dict(chosen)
        chosen["duplicate_score_unknown"] = len(values) > 1 and len(finite) != len(values)
        selected.append(chosen)

    mode = order_mode
    if mode == "auto":
        if selected and all(item["rank"] is not None for item in selected):
            mode = "rank"
        elif selected and all(item["score"] is not None for item in selected):
            mode = "score"
        else:
            mode = "list"
    if mode == "rank":
        selected.sort(key=lambda item: (item["rank"] if item["rank"] is not None else math.inf, item["position"]))
    elif mode == "score":
        selected.sort(key=lambda item: (-(item["score"] if item["score"] is not None else -math.inf), item["position"]))
    else:
        selected.sort(key=lambda item: item["position"])
    for rank, item in enumerate(selected, 1):
        item["dedup_rank"] = rank
    return selected


def compare_asset_ranking(raw: dict[str, Any], computed: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    supplied = field(raw, args.asset_results_field, [])
    if not isinstance(supplied, list):
        supplied = []
    supplied_ids = [str(field(item, args.result_asset_id_field, "")) for item in supplied if isinstance(item, dict)]
    computed_ids = [str(item.get("asset_id", "")) for item in computed]
    supplied_scores = [number(field(item, args.result_score_field)) for item in supplied if isinstance(item, dict)]
    computed_scores = [item.get("score") for item in computed]
    ids_match = supplied_ids == computed_ids
    scores_match = len(supplied_scores) == len(computed_scores) and all(
        left is not None and right is not None and abs(left - right) <= 1e-6
        for left, right in zip(supplied_scores, computed_scores)
    )
    return {
        "status": "match" if ids_match and scores_match else "mismatch",
        "computed_asset_count": len(computed_ids),
        "runner_asset_count": len(supplied_ids),
        "asset_order_match": ids_match,
        "score_match_within_1e-6": scores_match,
        "first_computed_asset": computed_ids[0] if computed_ids else "",
        "first_runner_asset": supplied_ids[0] if supplied_ids else "",
    }


def content_support(index_row: dict[str, Any], required_facts: list[Any], content_fields: list[str]) -> tuple[bool | None, list[str]]:
    content = "\n".join(to_text(index_row.get(name)) for name in content_fields if index_row.get(name) is not None)
    if not content.strip():
        return None, []
    content_key = normalized(content)
    matched = [str(fact) for fact in required_facts if normalized(fact) and normalized(fact) in content_key]
    return bool(matched), matched


def relevance_for_query(
    candidates: list[dict[str, Any]],
    gold_row: dict[str, Any],
    asset_paths: dict[str, str],
    resolutions: dict[str, dict[str, Any]],
    content_fields: list[str],
) -> list[dict[str, Any]]:
    evidence = as_list(gold_row.get("evidence"))
    facts = as_list(gold_row.get("required_facts"))
    diagnostics = []
    for candidate in candidates:
        # Precision counts structurally valid overlap; complete coverage is a separate metric.
        candidate["fine_relevant"] = any(
            fraction is not None and fraction > 0
            for entry in evidence if isinstance(entry, dict)
            for fraction in [evidence_entry_fraction([candidate], entry, asset_paths, resolutions)]
        )
        for evidence_index, entry in enumerate(evidence):
            if not isinstance(entry, dict):
                continue
            candidate["required_facts"] = facts
            if structurally_matches(candidate, entry, asset_paths, resolutions):
                support, matched = content_support(candidate["index"], facts, content_fields)
                diagnostics.append({
                    "query_id": gold_row.get("id", ""),
                    "split": gold_row.get("split", ""),
                    "repetition": candidate.get("repetition", ""),
                    "rank": candidate.get("dedup_rank", ""),
                    "evidence_index": evidence_index + 1,
                    "chunk_id": candidate.get("chunk_id", ""),
                    "asset_id": candidate.get("asset_id", ""),
                    "path": candidate.get("path", ""),
                    "locator": candidate.get("locator", ""),
                    "status": "text_missing" if support is None else ("literal_match" if support else "literal_not_found"),
                    "matched_facts": ";".join(matched),
                })
    return diagnostics


def latency_stats(calls: list[dict[str, Any]], expected_calls: int, include_first_query: bool) -> dict[str, Any]:
    timed = [call for call in calls if call["latency_ms"] is not None]
    values = sorted(call["latency_ms"] for call in timed)
    first_value = calls[0]["latency_ms"] if include_first_query and calls else None
    p95 = values[math.ceil(0.95 * len(values)) - 1] if values else None
    return {
        "expected_calls": expected_calls,
        "recorded_calls": len(calls),
        "timed_calls": len(timed),
        "failed_calls": sum(bool(call["error"]) for call in calls),
        "median_ms": statistics.median(values) if values else None,
        "mean_ms": math.fsum(values) / len(values) if values else None,
        "p95_ms": p95,
        "max_ms": max(values) if values else None,
        "first_query_ms": first_value,
    }


def timing_distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "median_ms": statistics.median(ordered) if ordered else None,
        "mean_ms": math.fsum(ordered) / len(ordered) if ordered else None,
        "p95_ms_nearest_rank": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None,
        "max_ms": max(ordered) if ordered else None,
        "sum_ms": math.fsum(ordered) if ordered else None,
    }


def execution_measurement(args: argparse.Namespace, index_sha: str, evaluation_sha: str,
                         aggregation_sha: str) -> dict[str, Any] | None:
    if not args.run_result:
        return None

    query_result = json.loads(args.run_result.read_text(encoding="utf-8-sig"))
    if query_result.get("status") != "complete":
        raise ValueError("query run-result.json is not complete")
    if query_result.get("index_sha256") != index_sha:
        raise ValueError("query run-result index SHA does not match the aggregation index")
    if query_result.get("evaluation_contract_sha256") != evaluation_sha:
        raise ValueError("query run-result evaluation contract SHA does not match the current frozen contract")
    if query_result.get("aggregation_contract_sha256") != aggregation_sha:
        raise ValueError("query run-result aggregation contract SHA does not match the current frozen aggregation contract")

    manifest = json.loads(args.run_manifest.read_text(encoding="utf-8-sig")) if args.run_manifest else None
    if args.run_manifest and sha256(args.run_manifest) != query_result.get("manifest_sha256"):
        raise ValueError("query run-result manifest SHA does not match the supplied formal manifest")
    if manifest:
        contracts = manifest.get("contracts", {})
        if contracts.get("evaluation", {}).get("sha256") != evaluation_sha:
            raise ValueError("formal manifest evaluation contract SHA mismatch")
        if contracts.get("aggregation", {}).get("sha256") != aggregation_sha:
            raise ValueError("formal manifest aggregation contract SHA mismatch")
        if manifest.get("index", {}).get("sha256") != index_sha:
            raise ValueError("formal manifest index SHA mismatch")

    query_runtime = json.loads(args.runtime.read_text(encoding="utf-8-sig")) if args.runtime else None
    if args.runtime:
        for key, expected in (("manifest_sha256", query_result.get("manifest_sha256")),
                              ("index_sha256", index_sha),
                              ("vector_file_sha256", query_result.get("vector_file_sha256"))):
            if query_runtime.get(key) != expected:
                raise ValueError(f"query runtime {key} does not match run-result.json")
        if query_runtime.get("resolved_model_revision") != query_result.get("model_revision", query_runtime.get("resolved_model_revision")):
            # Some runner versions record revision only in runtime.json; run-result may omit it.
            if query_result.get("model_revision"):
                raise ValueError("query runtime model revision does not match run-result.json")
        if manifest and query_runtime.get("resolved_model_revision") != manifest.get("model", {}).get("revision"):
            raise ValueError("query runtime model revision does not match formal manifest")

    doc_result = json.loads(args.document_run_result.read_text(encoding="utf-8-sig")) if args.document_run_result else None
    doc_runtime = json.loads(args.document_runtime.read_text(encoding="utf-8-sig")) if args.document_runtime else None
    doc_timing_rows = records(args.document_timings) if args.document_timings else []
    if doc_result:
        if doc_result.get("status") != "complete":
            raise ValueError("document run-result.json is not complete")
        if doc_result.get("index_sha256") != index_sha or doc_result.get("vector_file_sha256") != query_result.get("vector_file_sha256"):
            raise ValueError("document build and query runs do not share the same frozen index/vector hashes")
        doc_summary = doc_result.get("document_embedding", {})
        if int(doc_summary.get("successful_chunk_records", -1)) != len(doc_timing_rows):
            raise ValueError("document embedding timing row count does not match document run-result.json")
        if doc_summary.get("errors") != 0 or any(row.get("status") != "ok" for row in doc_timing_rows):
            raise ValueError("document embedding timings contain errors")
    if doc_runtime:
        if doc_runtime.get("index_sha256") != index_sha or doc_runtime.get("vector_file_sha256") != query_result.get("vector_file_sha256"):
            raise ValueError("document runtime hashes do not match the frozen query index/vector")
    if args.document_timings and not doc_result:
        raise ValueError("document timings were supplied without their source run-result.json")

    timing_groups: dict[str, list[float]] = defaultdict(list)
    for row in doc_timing_rows:
        elapsed = number(row.get("elapsed_ms"))
        if elapsed is not None:
            timing_groups[str(row.get("input_representation") or row.get("modality") or "unknown")].append(elapsed)
    input_files = {}
    for path in (args.run_manifest, args.run_result, args.runtime, args.document_run_result,
                 args.document_runtime, args.document_timings):
        if path:
            input_files[str(path)] = sha256(path)

    query_counts = query_result.get("query_counts", {})
    prior_manifest_path = DEFAULT_ROOT / "run_manifest.json"
    prior_manifest = json.loads(prior_manifest_path.read_text(encoding="utf-8-sig")) if prior_manifest_path.is_file() else {}
    prior_aggregation = prior_manifest.get("contracts", {}).get("aggregation", {})
    freeze_record_path = DEFAULT_ROOT / "analysis" / "snapshots" / "attempt-02" / "freeze-record.json"
    freeze_record = json.loads(freeze_record_path.read_text(encoding="utf-8-sig")) if freeze_record_path.is_file() else {}
    for path in (prior_manifest_path, freeze_record_path):
        if path.is_file():
            input_files[str(path)] = sha256(path)
    return {
        "formal_query_run": {
            "attempt_id": query_result.get("attempt_id"),
            "status": query_result.get("status"),
            "model_id": (manifest or {}).get("model", {}).get("id"),
            "model_revision": (manifest or {}).get("model", {}).get("revision"),
            "manifest_sha256": query_result.get("manifest_sha256"),
            "evaluation_contract_sha256": query_result.get("evaluation_contract_sha256"),
            "aggregation_contract_sha256": query_result.get("aggregation_contract_sha256"),
            "index_sha256": query_result.get("index_sha256"),
            "vector_file_sha256": query_result.get("vector_file_sha256"),
            "query_counts": query_counts,
            "query_execution_wall_seconds": query_result.get("query_execution_wall_seconds"),
            "query_container_wall_seconds": query_result.get("wall_seconds_query_recovery_container"),
            "source_path": str(args.run_result),
        },
        "query_runtime": ({
            "source_path": str(args.runtime),
            "device": query_runtime.get("device"),
            "dtype": query_runtime.get("dtype"),
            "torch_threads": query_runtime.get("torch_threads"),
            "model_revision": query_runtime.get("resolved_model_revision"),
            "model_loaded_before_query_calls": query_runtime.get("model_loaded_before_query_calls"),
            "first_test_call_is_cold": query_runtime.get("first_test_call_is_cold"),
            "model_load_seconds": query_runtime.get("query_stage_model_load_seconds"),
            "container_cpu_limit_cores": query_runtime.get("container_cpu_limit_cores"),
            "container_memory_limit_bytes": query_runtime.get("container_memory_limit_bytes"),
            "process_max_rss_bytes": query_runtime.get("process_max_rss_bytes_query_container"),
            "cgroup_peak_bytes": query_runtime.get("cgroup_peak_bytes_query_container"),
            "timing_boundary": query_runtime.get("timing_boundary"),
        } if query_runtime else None),
        "document_index_build": ({
            "source_attempt_id": doc_result.get("attempt_id"),
            "source_path": str(args.document_run_result),
            "timing_path": str(args.document_timings) if args.document_timings else None,
            "runtime_path": str(args.document_runtime) if args.document_runtime else None,
            "index_sha256": doc_result.get("index_sha256"),
            "vector_file_sha256": doc_result.get("vector_file_sha256"),
            "input_count": doc_result.get("input_count"),
            "chunk_count": doc_result.get("chunk_count"),
            "successful_chunk_records": doc_result.get("document_embedding", {}).get("successful_chunk_records"),
            "errors": doc_result.get("document_embedding", {}).get("errors"),
            "model_load_seconds": doc_result.get("initial_document_container_model_load_seconds"),
            "input_extraction_seconds": (doc_runtime or {}).get("input_extraction_seconds"),
            "embedding_wall_seconds": (doc_runtime or {}).get("document_embedding_wall_seconds_from_container_events",
                                                               doc_result.get("document_embedding", {}).get("wall_seconds_from_container_events")),
            "vector_index_write_seconds": (doc_runtime or {}).get("vector_index_write_seconds_from_container_events",
                                                                  doc_result.get("document_embedding", {}).get("vector_index_write_seconds_from_container_events")),
            "source_runtime_setting": (manifest or {}).get("runtime", {}).get("index_runner_thread_setter"),
            "index_process_thread_readback_serialized": (manifest or {}).get("runtime", {}).get("index_process_thread_readback_serialized"),
            "per_chunk_timings_by_input_representation": {key: timing_distribution(values) for key, values in sorted(timing_groups.items())},
        } if doc_result else None),
        "input_file_sha256": input_files,
        "historical_query_attempts": {
            "excluded_ranking_attempts": ["attempt-01", "attempt-03", "attempt-04"],
            "reason": "Only the formal attempt-05 query JSONL is used for quality ranking metrics; older query rankings are retained but excluded.",
            "prior_aggregation_contract_sha256": prior_aggregation.get("sha256"),
            "prior_aggregation_contract_bytes": prior_aggregation.get("bytes"),
            "prior_contract_body_available": freeze_record.get("history_limits", {}).get("prior_c0_body_found", False),
            "document_timing_reused_from_attempt": doc_result.get("attempt_id") if doc_result else None,
            "note": "Attempt-01 contributes only the source build timing for the same frozen index/vector hashes, not ranking outcomes.",
        },
    }


def add_metric(rows: list[dict[str, Any]], split: str, repetition: int, metric: str, k: int | str, value: Any,
               denominator: int, special_case_queries: int = 0, note: str = "") -> None:
    rows.append({
        "split": split,
        "repetition": repetition,
        "population": "answerable",
        "metric": metric,
        "k": k,
        "value": value,
        "denominator": denominator,
        "special_case_queries": special_case_queries,
        "note": note,
    })


def query_quality_at_k(gold_row: dict[str, Any], ranked: dict[str, list[dict[str, Any]]], k: int,
                       asset_paths: dict[str, str], resolutions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    top_assets = ranked.get("assets", [])[:k]
    top_chunks = ranked.get("chunks", [])[:k]
    evidence_entries = [entry for entry in as_list(gold_row.get("evidence")) if isinstance(entry, dict)]
    gold_assets = {str(entry.get("asset_id")) for entry in evidence_entries if entry.get("asset_id")}
    asset_hit = any(item.get("asset_id") in gold_assets for item in top_assets)
    resolvable = [entry for entry in evidence_entries
                  if (resolution_for(entry, resolutions) or {}).get("status") == "resolved"]
    represented = evidence_coverage(top_chunks, resolvable, asset_paths, resolutions)
    fractions = [value for value in evidence_entry_fractions(top_chunks, resolvable, asset_paths, resolutions)
                 if value is not None]
    fine_hit = bool(represented) if resolvable else None
    all_resolved = len(resolvable) == len(evidence_entries)
    complete = (len(represented) == len(evidence_entries)) if all_resolved and evidence_entries else None
    return {
        "asset_hit": asset_hit,
        "fine_evidence_hit": fine_hit,
        "complete_evidence": complete,
        "fine_evidence_coverage": len(represented) / len(resolvable) if resolvable else None,
        "fine_evidence_unit_fraction_coverage": sum(fractions) / len(fractions) if fractions else None,
        "evidence_entries": evidence_entries,
        "resolvable_entries": resolvable,
        "represented_indices": represented,
        "fractions": fractions,
        "top_assets": top_assets,
        "top_chunks": top_chunks,
        "gold_asset_ids": sorted(gold_assets),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, nargs="+", required=True, help="one or more raw per-query ranking JSONL/JSON files")
    parser.add_argument("--index", type=Path, required=True, help="source index JSONL/JSON")
    parser.add_argument("--gold", type=Path, required=True, help="frozen gold JSON")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT, help="frozen evaluation contract")
    parser.add_argument("--resolution", type=Path, default=DEFAULT_ROOT / "analysis" / "locator-resolution.json",
                        help="source-verified gold locator resolution map")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--run-manifest", type=Path, help="formal manifest for the query-ranking attempt")
    parser.add_argument("--run-result", type=Path, help="complete run-result.json for the query-ranking attempt")
    parser.add_argument("--runtime", type=Path, help="runtime.json for the query-ranking attempt")
    parser.add_argument("--document-run-result", type=Path, help="run-result.json for the original frozen index build")
    parser.add_argument("--document-runtime", type=Path, help="runtime.json for the original frozen index build")
    parser.add_argument("--document-timings", type=Path, help="per-source-unit embedding timings from the original index build")
    parser.add_argument("--query-id-field", default="query_id")
    parser.add_argument("--repetition-field", default="repetition")
    parser.add_argument("--order-field", default="canonical_order")
    parser.add_argument("--test-call-order-field", default="test_call_order")
    parser.add_argument("--latency-field", default="elapsed_ms")
    parser.add_argument("--error-field", default="error")
    parser.add_argument("--results-field", default="chunk_ranking")
    parser.add_argument("--asset-results-field", default="asset_ranking")
    parser.add_argument("--result-chunk-id-field", default="chunk_id")
    parser.add_argument("--result-asset-id-field", default="asset_id")
    parser.add_argument("--result-path-field", default="source_path")
    parser.add_argument("--result-locator-field", default="locator")
    parser.add_argument("--result-score-field", default="score")
    parser.add_argument("--result-rank-field", default="rank")
    parser.add_argument("--index-chunk-id-field", default="chunk_id")
    parser.add_argument("--index-asset-id-field", default="asset_id")
    parser.add_argument("--index-path-field", default="source_path")
    parser.add_argument("--index-locator-field", default="locator")
    parser.add_argument("--content-fields", default=",".join(CONTENT_FIELDS),
                        help="comma-separated index text fields used only to check literal required-fact support")
    parser.add_argument("--ranking-order", choices=("auto", "score", "rank", "list"), default="auto")
    parser.add_argument("--test-repetitions", type=int, default=3)
    args = parser.parse_args()

    optional_paths = (args.run_manifest, args.run_result, args.runtime, args.document_run_result,
                      args.document_runtime, args.document_timings)
    for path in (*args.raw, args.index, args.gold, *(path for path in optional_paths if path)):
        if not path.is_file():
            raise FileNotFoundError(path)
    gold_value = json.loads(args.gold.read_text(encoding="utf-8-sig"))
    if isinstance(gold_value, dict):
        gold_value = gold_value.get("queries", gold_value.get("items", []))
    if not isinstance(gold_value, list):
        raise ValueError("gold must be a JSON array or an object containing queries/items")
    gold_rows = [item for item in gold_value if isinstance(item, dict)]
    gold_by_id = {str(item["id"]): item for item in gold_rows if item.get("id") is not None}
    if len(gold_by_id) != len(gold_rows):
        raise ValueError("gold contains missing or duplicate query ids")
    index_rows = records(args.index)
    index_by_chunk = index_map(index_rows, args.index_chunk_id_field)
    index_by_source = index_source_map(index_rows, args)
    asset_paths = load_contract_assets(args.contract)
    for item in gold_rows:
        for evidence in as_list(item.get("evidence")):
            if isinstance(evidence, dict) and evidence.get("asset_id") and evidence.get("path"):
                asset_paths.setdefault(str(evidence["asset_id"]), str(evidence["path"]))

    if not args.resolution.is_file():
        raise FileNotFoundError(args.resolution)
    resolution_data = json.loads(args.resolution.read_text(encoding="utf-8-sig"))
    expected_hashes = resolution_data.get("inputs", {})
    if expected_hashes.get("gold_sha256") != sha256(args.gold) or expected_hashes.get("index_sha256") != sha256(args.index):
        raise ValueError("locator-resolution.json does not match the current gold/index hashes")
    resolutions, resolution_rows = load_locator_resolutions(args.resolution)
    for asset_id, source in expected_hashes.get("source_files", {}).items():
        source_path = DEFAULT_ROOT.parent / "multimodal-benchmark" / source.get("path", "")
        if not source_path.is_file() or sha256(source_path) != source.get("sha256"):
            raise ValueError(f"locator-resolution.json source hash mismatch: {asset_id}")
    unresolved_locator_rows = []
    for gold_row in gold_rows:
        for evidence_index, evidence in enumerate(as_list(gold_row.get("evidence")), 1):
            if not isinstance(evidence, dict):
                continue
            resolved = resolution_for(evidence, resolutions)
            if not resolved or resolved.get("status") != "resolved":
                unresolved_locator_rows.append({
                    "query_id": gold_row.get("id", ""), "split": gold_row.get("split", ""),
                    "evidence_index": evidence_index, "asset_id": evidence.get("asset_id", ""),
                    "path": evidence.get("path", ""), "gold_location": evidence.get("location", ""),
                    "resolution_status": (resolved or {}).get("status", "missing_resolution"),
                    "kind": (resolved or {}).get("kind", ""),
                    "notes": ";".join((resolved or {}).get("notes", [])),
                })

    raw_rows = [(path, row) for path in args.raw for row in records(path)]
    current_index_sha = sha256(args.index)
    current_evaluation_sha = sha256(args.contract)
    aggregation_contract_path = DEFAULT_ROOT / "analysis" / "aggregation-contract.json"
    current_aggregation_sha = sha256(aggregation_contract_path)
    execution = execution_measurement(args, current_index_sha, current_evaluation_sha, current_aggregation_sha)
    calls = []
    seen_calls = set()
    for source_position, (source_file, raw) in enumerate(raw_rows, 1):
        query_id = field(raw, args.query_id_field)
        if query_id is None or str(query_id) not in gold_by_id:
            raise ValueError(f"raw row {source_position}: missing or unknown query id")
        query_id = str(query_id)
        repetition = integer(field(raw, args.repetition_field), 1)
        order = integer(field(raw, args.order_field), source_position)
        key = (repetition, query_id) if gold_by_id[query_id].get("split") == "test" else ("dev", repetition, query_id)
        if key in seen_calls:
            raise ValueError(f"duplicate query call: {key}")
        seen_calls.add(key)
        latency = number(field(raw, args.latency_field))
        error_value = field(raw, args.error_field)
        result_status = str(raw.get("status") or "").casefold()
        if not error_value and result_status and result_status not in {"ok", "success", "complete"}:
            error_value = f"raw status: {result_status}"
        if execution:
            expected_manifest_sha = execution["formal_query_run"]["manifest_sha256"]
            if raw.get("manifest_sha256") != expected_manifest_sha:
                raise ValueError(f"query {query_id}: raw manifest SHA does not match formal run-result.json")
            if raw.get("index_sha256") != current_index_sha:
                raise ValueError(f"query {query_id}: raw index SHA does not match frozen index")
            expected_revision = (execution.get("query_runtime") or {}).get("model_revision")
            if expected_revision and raw.get("model_revision") != expected_revision:
                raise ValueError(f"query {query_id}: raw model revision does not match runtime.json")
        calls.append({
            "raw": raw,
            "source_file": str(source_file),
            "query_id": query_id,
            "split": str(gold_by_id[query_id].get("split", "")),
            "repetition": repetition,
            "order": order,
            "test_call_order": integer(field(raw, args.test_call_order_field), 0),
            "latency_ms": latency,
            "error": "" if error_value in (None, "", False) else str(error_value),
            "source_position": source_position,
        })

    calls.sort(key=lambda item: (item["repetition"], item["order"], item["source_position"]))
    if execution:
        counts = execution["formal_query_run"]["query_counts"]
        actual_dev = [call for call in calls if call["split"] == "dev"]
        actual_test = [call for call in calls if call["split"] == "test"]
        if len(actual_dev) != integer(counts.get("dev_records"), -1) or len(actual_test) != integer(counts.get("test_records"), -1):
            raise ValueError("raw JSONL call counts do not match complete run-result.json")
        if len(actual_dev) != integer(counts.get("dev_expected"), -1) or len(actual_test) != integer(counts.get("test_expected"), -1):
            raise ValueError("complete run-result.json reports missing query calls")
        if sum(bool(call["error"]) for call in actual_dev) != integer(counts.get("dev_errors"), -1):
            raise ValueError("raw dev error count does not match run-result.json")
        if sum(bool(call["error"]) for call in actual_test) != integer(counts.get("test_errors"), -1):
            raise ValueError("raw test error count does not match run-result.json")
        orders = sorted(call["test_call_order"] for call in actual_test)
        if orders != list(range(1, len(actual_test) + 1)):
            raise ValueError("test_call_order must be a unique complete chronology starting at 1")
    rankings: dict[tuple[str, int, str], dict[str, list[dict[str, Any]]]] = {}
    unknown_score_rows = []
    unanswerable_rows = []
    fact_support_rows = []
    unresolved_candidate_rows = []
    asset_ranking_consistency_rows = []
    granularity_diagnostic_rows = []
    for call in calls:
        gold_row = gold_by_id[call["query_id"]]
        all_candidates = make_candidates(call, index_by_chunk, index_by_source, asset_paths, args)
        for candidate in all_candidates:
            candidate["repetition"] = call["repetition"]
            if not candidate["index_resolved"]:
                unresolved_candidate_rows.append({
                    "query_id": call["query_id"], "split": call["split"], "repetition": call["repetition"],
                    "order": call["order"], "result_position": candidate["position"] + 1,
                    "raw_chunk_id": candidate["raw_chunk_id"], "asset_id": candidate["asset_id"],
                    "path": candidate["path"], "locator": candidate["locator"],
                    "reason": "candidate could not be resolved to a frozen index chunk",
                })
            if candidate["score_state"] != "known":
                unknown_score_rows.append({
                    "query_id": call["query_id"], "split": call["split"], "repetition": call["repetition"],
                    "order": call["order"], "result_position": candidate["position"] + 1,
                    "chunk_id": candidate["chunk_id"], "asset_id": candidate["asset_id"],
                    "locator": candidate["locator"], "score_value": candidate["score_raw"],
                    "score_state": candidate["score_state"],
                })
        candidates = [candidate for candidate in all_candidates if candidate["index_resolved"]]
        call_key = (call["split"], call["repetition"], call["query_id"])
        assets = deduplicate(candidates, "asset", args.ranking_order)
        chunks = deduplicate(candidates, "chunk", args.ranking_order)
        comparison = compare_asset_ranking(call["raw"], assets, args)
        asset_ranking_consistency_rows.append({
            "query_id": call["query_id"], "split": call["split"], "repetition": call["repetition"],
            "order": call["order"], **comparison,
        })
        support_rows = relevance_for_query(chunks, gold_row, asset_paths, resolutions,
                                            [part.strip() for part in args.content_fields.split(",") if part.strip()])
        for row in support_rows:
            row["repetition"] = call["repetition"]
        fact_support_rows.extend(support_rows)
        rankings[call_key] = {
            "assets": assets,
            "chunks": chunks,
            "evidence_count": len(as_list(gold_row.get("evidence"))),
        }
        if not bool(gold_row.get("answerable")):
            unanswerable_rows.append({
                "query_id": call["query_id"], "split": call["split"], "repetition": call["repetition"],
                "order": call["order"], "error": call["error"],
                "top_asset_ids": ";".join(item["asset_id"] for item in assets[:5]),
                "top_asset_scores": ";".join(str(item["score"]) if item["score"] is not None else "unknown" for item in assets[:5]),
                "top_chunks": ";".join(f"{item['asset_id']}|{item['locator']}" for item in chunks[:5]),
                "top_chunk_scores": ";".join(str(item["score"]) if item["score"] is not None else "unknown" for item in chunks[:5]),
            })

    metric_rows = []
    split_repetitions: dict[str, set[int]] = defaultdict(set)
    for call in calls:
        split_repetitions[call["split"]].add(call["repetition"])
    if any(item.get("split") == "test" for item in gold_rows):
        split_repetitions["test"].update(range(1, args.test_repetitions + 1))
    for split, repetitions in sorted(split_repetitions.items()):
        answerable = [item for item in gold_rows if item.get("split") == split and bool(item.get("answerable"))]
        for repetition in sorted(repetitions):
            for k in (1, 3, 5, 10):
                asset_hits = []
                asset_rr = []
                asset_precision = []
                evidence_hits = []
                evidence_rr = []
                complete = []
                coverage = []
                unit_coverage = []
                evidence_precision = []
                for gold_row in answerable:
                    query_id = str(gold_row["id"])
                    key = (split, repetition, query_id)
                    ranked = rankings.get(key, {"assets": [], "chunks": [], "evidence_count": len(as_list(gold_row.get("evidence")))})
                    top_assets = ranked["assets"][:k]
                    top_chunks = ranked["chunks"][:k]
                    gold_assets = {str(item.get("asset_id")) for item in as_list(gold_row.get("evidence")) if isinstance(item, dict)}
                    relevant_asset_positions = [rank for rank, item in enumerate(ranked["assets"][:10], 1) if item["asset_id"] in gold_assets]
                    asset_hit_at_k = bool(relevant_asset_positions and relevant_asset_positions[0] <= k)
                    asset_hits.append(asset_hit_at_k)
                    asset_rr.append(1.0 / relevant_asset_positions[0] if relevant_asset_positions else 0.0)
                    asset_precision.append(sum(item["asset_id"] in gold_assets for item in top_assets) / min(k, len(ranked["assets"])) if ranked["assets"] else None)

                    evidence_entries = as_list(gold_row.get("evidence"))
                    for evidence_index, entry in enumerate(evidence_entries, 1):
                        if not isinstance(entry, dict):
                            continue
                        diagnostic = granularity_diagnostic_row(
                            query_id, split, repetition, k, evidence_index, top_chunks, entry,
                            asset_paths, resolutions, asset_hit_at_k,
                        )
                        if diagnostic:
                            granularity_diagnostic_rows.append(diagnostic)
                    resolvable_entries = [entry for entry in evidence_entries
                                          if isinstance(entry, dict) and (resolution_for(entry, resolutions) or {}).get("status") == "resolved"]
                    all_entries_resolved = len(resolvable_entries) == len(evidence_entries)
                    represented_at_k = evidence_coverage(ranked["chunks"][:k], resolvable_entries, asset_paths, resolutions)
                    if resolvable_entries:
                        evidence_hits.append(bool(represented_at_k))
                        first_full_rank = next((rank for rank in range(1, min(10, len(ranked["chunks"])) + 1)
                                                if evidence_coverage(ranked["chunks"][:rank], resolvable_entries, asset_paths, resolutions)), None)
                        evidence_rr.append(1.0 / first_full_rank if first_full_rank else 0.0)
                        coverage.append(len(represented_at_k) / len(resolvable_entries))
                        fractions = [value for value in evidence_entry_fractions(ranked["chunks"][:k], resolvable_entries, asset_paths, resolutions) if value is not None]
                        unit_coverage.append(sum(fractions) / len(fractions) if fractions else None)
                        evidence_precision.append(sum(bool(item.get("fine_relevant")) for item in top_chunks) / min(k, len(ranked["chunks"])) if ranked["chunks"] else None)
                    else:
                        evidence_hits.append(None)
                        evidence_rr.append(None)
                        coverage.append(None)
                        unit_coverage.append(None)
                        evidence_precision.append(None)
                    if all_entries_resolved and evidence_entries:
                        complete.append(len(represented_at_k) == len(evidence_entries))
                    else:
                        complete.append(None)
                denominator = len(answerable)
                fine_hit_values = [value for value in evidence_hits if value is not None]
                fine_rr_values = [value for value in evidence_rr if value is not None]
                complete_values = [value for value in complete if value is not None]
                coverage_values = [value for value in coverage if value is not None]
                unit_coverage_values = [value for value in unit_coverage if value is not None]
                asset_p_values = [value for value in asset_precision if value is not None]
                evidence_p_values = [value for value in evidence_precision if value is not None]
                asset_p_note = f"N/A for {denominator - len(asset_p_values)} queries with no returned asset" if denominator != len(asset_p_values) else ""
                fine_excluded = denominator - len(fine_hit_values)
                complete_excluded = denominator - len(complete_values)
                evidence_p_note = f"N/A for {denominator - len(evidence_p_values)} queries with no returned chunk or unresolved gold locator" if denominator != len(evidence_p_values) else ""
                add_metric(metric_rows, split, repetition, "asset_hit", k, sum(asset_hits) / denominator if denominator else None, denominator)
                add_metric(metric_rows, split, repetition, "asset_precision", k, sum(asset_p_values) / len(asset_p_values) if asset_p_values else None, denominator, denominator - len(asset_p_values), asset_p_note)
                add_metric(metric_rows, split, repetition, "fine_evidence_hit", k, sum(fine_hit_values) / len(fine_hit_values) if fine_hit_values else None, len(fine_hit_values), fine_excluded, "structural source locator; unresolved gold entries are excluded")
                add_metric(metric_rows, split, repetition, "fine_evidence_precision", k, sum(evidence_p_values) / len(evidence_p_values) if evidence_p_values else None, len(evidence_p_values), denominator - len(evidence_p_values), evidence_p_note)
                add_metric(metric_rows, split, repetition, "complete_evidence", k, sum(complete_values) / len(complete_values) if complete_values else None, len(complete_values), complete_excluded, "all entries must resolve and be fully covered")
                add_metric(metric_rows, split, repetition, "fine_evidence_coverage", k, sum(coverage_values) / len(coverage_values) if coverage_values else None, len(coverage_values), denominator - len(coverage_values), "fraction of resolvable evidence entries fully covered")
                add_metric(metric_rows, split, repetition, "fine_evidence_unit_fraction_coverage", k, sum(unit_coverage_values) / len(unit_coverage_values) if unit_coverage_values else None, len(unit_coverage_values), denominator - len(unit_coverage_values), "partial interval duration/cell coverage; gaps are not bridged")
                if k == 10:
                    add_metric(metric_rows, split, repetition, "asset_mrr", 10, sum(asset_rr) / denominator if denominator else None, denominator)
                    add_metric(metric_rows, split, repetition, "fine_evidence_mrr", 10, sum(fine_rr_values) / len(fine_rr_values) if fine_rr_values else None, len(fine_rr_values), denominator - len(fine_rr_values), "structural locator rank; unresolved gold entries are excluded")

    modality_metric_rows = []
    retrieval_failure_rows = []
    for split, repetitions in sorted(split_repetitions.items()):
        answerable = [item for item in gold_rows if item.get("split") == split and bool(item.get("answerable"))]
        modalities = sorted({str(item.get("modality") or "unknown") for item in answerable})
        for repetition in sorted(repetitions):
            for modality in modalities:
                group = [item for item in answerable if str(item.get("modality") or "unknown") == modality]
                for k in (1, 3, 5, 10):
                    per_query = []
                    for gold_row in group:
                        key = (split, repetition, str(gold_row["id"]))
                        ranked = rankings.get(key, {"assets": [], "chunks": []})
                        per_query.append(query_quality_at_k(gold_row, ranked, k, asset_paths, resolutions))
                    for metric_name in ("asset_hit", "fine_evidence_hit", "complete_evidence",
                                        "fine_evidence_coverage", "fine_evidence_unit_fraction_coverage"):
                        values = [row[metric_name] for row in per_query if row[metric_name] is not None]
                        modality_metric_rows.append({
                            "split": split, "repetition": repetition, "modality": modality,
                            "metric": metric_name, "k": k,
                            "value": sum(values) / len(values) if values else None,
                            "denominator": len(values),
                            "excluded_queries": len(group) - len(values),
                        })

            for gold_row in answerable:
                query_id = str(gold_row["id"])
                key = (split, repetition, query_id)
                ranked = rankings.get(key, {"assets": [], "chunks": []})
                for k in (1, 3, 5, 10):
                    quality = query_quality_at_k(gold_row, ranked, k, asset_paths, resolutions)
                    reasons = []
                    if not quality["asset_hit"]:
                        reasons.append("asset_miss")
                    if quality["fine_evidence_hit"] is False:
                        reasons.append("no_fully_covered_evidence_entry")
                    if quality["complete_evidence"] is False:
                        reasons.append("not_all_evidence_entries_fully_covered")
                    unit_fraction = quality["fine_evidence_unit_fraction_coverage"]
                    if quality["complete_evidence"] is False and unit_fraction is not None and unit_fraction < 1.0:
                        reasons.append("partial_interval_or_cell_coverage")
                    if not reasons:
                        continue
                    entry_details = []
                    for evidence_index, entry in enumerate(quality["evidence_entries"], 1):
                        resolution = resolution_for(entry, resolutions)
                        fraction = evidence_entry_fraction(quality["top_chunks"], entry, asset_paths, resolutions)
                        entry_details.append({
                            "evidence_index": evidence_index,
                            "asset_id": entry.get("asset_id"), "path": entry.get("path"), "location": entry.get("location"),
                            "resolution_status": (resolution or {}).get("status", "missing_resolution"),
                            "fine_coverage_fraction": fraction,
                            "fully_covered": evidence_entry_covered(quality["top_chunks"], entry, asset_paths, resolutions)
                            if resolution and resolution.get("status") == "resolved" else None,
                        })
                    top_assets = [{"rank": i, "asset_id": row.get("asset_id"), "score": row.get("score"), "path": row.get("path")}
                                  for i, row in enumerate(quality["top_assets"], 1)]
                    top_chunks = [{"rank": i, "chunk_id": row.get("chunk_id"), "asset_id": row.get("asset_id"),
                                   "source_path": row.get("path"), "locator": row.get("locator"), "score": row.get("score")}
                                  for i, row in enumerate(quality["top_chunks"], 1)]
                    retrieval_failure_rows.append({
                        "query_id": query_id, "split": split, "repetition": repetition,
                        "modality": gold_row.get("modality", ""), "task": gold_row.get("task", ""),
                        "k": k, "question": gold_row.get("question", ""),
                        "failure_reasons": ";".join(reasons),
                        "asset_hit_at_k": quality["asset_hit"],
                        "fine_evidence_hit_at_k": quality["fine_evidence_hit"],
                        "complete_evidence_at_k": quality["complete_evidence"],
                        "fine_evidence_entry_coverage": quality["fine_evidence_coverage"],
                        "fine_evidence_unit_fraction_coverage": unit_fraction,
                        "gold_asset_ids": ";".join(quality["gold_asset_ids"]),
                        "interpretation_note": VERIFIER_CASE_NOTES.get(query_id, ""),
                        "gold_evidence_entries": json.dumps(entry_details, ensure_ascii=False, separators=(",", ":")),
                        "top_assets": json.dumps(top_assets, ensure_ascii=False, separators=(",", ":")),
                        "top_chunks": json.dumps(top_chunks, ensure_ascii=False, separators=(",", ":")),
                    })

    test_calls = sorted([call for call in calls if call["split"] == "test"], key=lambda item: (item["test_call_order"] or math.inf, item["repetition"], item["order"], item["source_position"]))
    warmed_calls = test_calls[1:] if test_calls else []
    latency_rows = [
        {"population": "test_all_calls", **latency_stats(test_calls, 60 * args.test_repetitions, True)},
        {"population": "test_warmed_only", **latency_stats(warmed_calls, max(0, 60 * args.test_repetitions - 1), False)},
    ]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "quality_metrics.csv", metric_rows,
              ["split", "repetition", "population", "metric", "k", "value", "denominator", "special_case_queries", "note"])
    write_csv(args.out_dir / "latency_summary.csv", latency_rows,
              ["population", "expected_calls", "recorded_calls", "timed_calls", "failed_calls", "median_ms", "mean_ms", "p95_ms", "max_ms", "first_query_ms"])
    write_csv(args.out_dir / "unknown_scores.csv", unknown_score_rows,
              ["query_id", "split", "repetition", "order", "result_position", "chunk_id", "asset_id", "locator", "score_value", "score_state"])
    write_csv(args.out_dir / "fact_support_diagnostics.csv", fact_support_rows,
              ["query_id", "split", "repetition", "rank", "evidence_index", "chunk_id", "asset_id", "path", "locator", "status", "matched_facts"])
    write_csv(args.out_dir / "unanswerable.csv", unanswerable_rows,
              ["query_id", "split", "repetition", "order", "error", "top_asset_ids", "top_asset_scores", "top_chunks", "top_chunk_scores"])
    write_csv(args.out_dir / "unresolved_gold_locators.csv", unresolved_locator_rows,
              ["query_id", "split", "evidence_index", "asset_id", "path", "gold_location", "resolution_status", "kind", "notes"])
    write_csv(args.out_dir / "unresolved_candidates.csv", unresolved_candidate_rows,
              ["query_id", "split", "repetition", "order", "result_position", "raw_chunk_id", "asset_id", "path", "locator", "reason"])
    write_csv(args.out_dir / "asset_ranking_consistency.csv", asset_ranking_consistency_rows,
              ["query_id", "split", "repetition", "order", "status", "computed_asset_count", "runner_asset_count", "asset_order_match", "score_match_within_1e-6", "first_computed_asset", "first_runner_asset"])
    write_csv(args.out_dir / "fine_granularity_diagnostics.csv", granularity_diagnostic_rows,
              ["query_id", "split", "repetition", "k", "evidence_index", "asset_id", "source_path", "gold_location",
               "gold_start_seconds", "gold_end_seconds", "gold_duration_seconds", "asset_hit_at_k", "fine_coverage_fraction",
               "fine_status", "admissible_interval_candidates", "overlong_overlapping_candidates", "admissible_candidate_ranges",
               "excluded_overlong_candidate_ranges", "excluded_overlong_candidate_ids", "reason"])
    write_csv(args.out_dir / "modality_metrics.csv", modality_metric_rows,
              ["split", "repetition", "modality", "metric", "k", "value", "denominator", "excluded_queries"])
    write_csv(args.out_dir / "retrieval_failures.csv", retrieval_failure_rows,
              ["query_id", "split", "repetition", "modality", "task", "k", "question", "failure_reasons",
               "asset_hit_at_k", "fine_evidence_hit_at_k", "complete_evidence_at_k", "fine_evidence_entry_coverage",
               "fine_evidence_unit_fraction_coverage", "gold_asset_ids", "interpretation_note", "gold_evidence_entries", "top_assets", "top_chunks"])

    expected_test = 60 * args.test_repetitions
    test_ids = {str(item["id"]) for item in gold_rows if item.get("split") == "test"}
    test_keys = {(call["repetition"], call["query_id"]) for call in test_calls}
    expected_keys = {(rep, query_id) for rep in range(1, args.test_repetitions + 1) for query_id in test_ids}
    missing_test_calls = len(expected_keys - test_keys)
    metrics_json = {
        "inputs": {str(path): sha256(path) for path in (
            *args.raw, args.index, args.gold, args.resolution,
            *(path for path in optional_paths if path),
        ) if path.is_file()},
        "contract": {"path": str(args.contract), "sha256": sha256(args.contract) if args.contract.is_file() else None},
        "aggregation_contract": {"path": str(DEFAULT_ROOT / "analysis" / "aggregation-contract.json"),
                                 "sha256": sha256(DEFAULT_ROOT / "analysis" / "aggregation-contract.json")
                                 if (DEFAULT_ROOT / "analysis" / "aggregation-contract.json").is_file() else None},
        "locator_resolution": {
            "path": str(args.resolution), "sha256": sha256(args.resolution),
            "unique_entries": len(resolution_rows),
            "resolved_entries": sum(row.get("status") == "resolved" for row in resolution_rows),
            "unresolved_entries": sum(row.get("status") != "resolved" for row in resolution_rows),
            "docx_page_labels_unverified": sum(row.get("page_label_status") == "unverified_physical_pagination" for row in resolution_rows),
        },
        "population": {
            split: {"total": sum(item.get("split") == split for item in gold_rows),
                    "answerable": sum(item.get("split") == split and bool(item.get("answerable")) for item in gold_rows),
                    "unanswerable": sum(item.get("split") == split and not bool(item.get("answerable")) for item in gold_rows)}
            for split in ("test", "dev")
        },
        "test_calls": {"expected": expected_test, "recorded": len(test_calls), "missing": missing_test_calls,
                       "complete": len(test_calls) == expected_test and missing_test_calls == 0},
        "quality_metrics": metric_rows,
        "latency": latency_rows,
        "unknown_scores": {"count": len(unknown_score_rows), "rows": unknown_score_rows},
        "fact_support_diagnostics": {"count": len(fact_support_rows), "rows": fact_support_rows},
        "unresolved_gold_locators": {"count": len(unresolved_locator_rows), "rows": unresolved_locator_rows},
        "unresolved_candidates": {"count": len(unresolved_candidate_rows), "rows": unresolved_candidate_rows},
        "asset_ranking_consistency": {
            "calls": len(asset_ranking_consistency_rows),
            "matches": sum(row["status"] == "match" for row in asset_ranking_consistency_rows),
            "mismatches": sum(row["status"] != "match" for row in asset_ranking_consistency_rows),
            "rows": asset_ranking_consistency_rows,
        },
        "fine_granularity_diagnostics": {"count": len(granularity_diagnostic_rows), "rows": granularity_diagnostic_rows},
        "modality_metrics": modality_metric_rows,
        "retrieval_failures": {"count": len(retrieval_failure_rows), "rows": retrieval_failure_rows},
        "execution_measurement": execution,
        "ranking_order": args.ranking_order,
        "fine_evidence_rule": "primary metrics use gold asset/path plus structural locator match. Coverage requires full time-interval union of only segment intervals no longer than the annotated gold duration (1e-6 second tolerance) and all annotated spreadsheet cells; index text/fact support is a separate literal diagnostic only.",
    }
    (args.out_dir / "metrics.json").write_text(json.dumps(json_safe(metrics_json), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = render_report(metrics_json, metric_rows, latency_rows, unanswerable_rows, unknown_score_rows,
                           fact_support_rows, unresolved_locator_rows, unresolved_candidate_rows,
                           asset_ranking_consistency_rows, granularity_diagnostic_rows,
                           modality_metric_rows, retrieval_failure_rows, execution)
    (args.out_dir / "REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"out_dir": str(args.out_dir.resolve()), "test_calls": metrics_json["test_calls"],
                      "unknown_scores": len(unknown_score_rows), "fact_support_diagnostics": len(fact_support_rows),
                      "unresolved_gold_locators": len(unresolved_locator_rows),
                      "unresolved_candidates": len(unresolved_candidate_rows),
                      "fine_granularity_diagnostics": len(granularity_diagnostic_rows),
                      "modality_metric_rows": len(modality_metric_rows),
                      "retrieval_failure_rows": len(retrieval_failure_rows),
                      "asset_ranking_mismatches": metrics_json["asset_ranking_consistency"]["mismatches"],
                      "quality_rows": len(metric_rows)}, ensure_ascii=False))


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "未計測"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_report(metrics: dict[str, Any], metric_rows: list[dict[str, Any]], latency_rows: list[dict[str, Any]],
                  unanswerable_rows: list[dict[str, Any]], unknown_scores: list[dict[str, Any]],
                  fact_support_rows: list[dict[str, Any]], unresolved_locator_rows: list[dict[str, Any]],
                  unresolved_candidate_rows: list[dict[str, Any]], asset_ranking_consistency_rows: list[dict[str, Any]],
                  granularity_diagnostic_rows: list[dict[str, Any]], modality_metric_rows: list[dict[str, Any]],
                  retrieval_failure_rows: list[dict[str, Any]], execution: dict[str, Any] | None) -> str:
    lines = [
        "# EmbeddingGemma 2 検索評価レポート",
        "",
        "このレポートは検索ランキングを評価し、生成回答の正解率や計算能力は評価しない。testの一次成績は反復1。反復2・3は順位の再現性確認に使う。",
        "",
        "## 入力と実行完全性",
        "",
        f"- test: 期待 {metrics['test_calls']['expected']} calls、記録 {metrics['test_calls']['recorded']} calls、不足 {metrics['test_calls']['missing']} calls。完全性: {'確認' if metrics['test_calls']['complete'] else '未達'}。",
        f"- test: {metrics['population']['test']['answerable']} answerable / {metrics['population']['test']['unanswerable']} unanswerable。dev: {metrics['population']['dev']['answerable']} answerable / {metrics['population']['dev']['unanswerable']} unanswerable。",
        f"- scores が欠落・不正・非有限の順位行: {len(unknown_scores)} 件（詳細は `unknown_scores.csv`）。",
        f"- 構造locatorがgold根拠と合った候補の本文文字列診断: {len(fact_support_rows)} 件（詳細は `fact_support_diagnostics.csv`）。本文なし/文字列不一致は主指標の失敗に数えない。",
        f"- gold位置表記の未解決: {len(unresolved_locator_rows)} 件、indexへ結び付かない候補locator: {len(unresolved_candidate_rows)} 件（詳細は別CSV）。この件数はmodel false hit/missへ混ぜない。",
        f"- DOCXの物理ページ番号を明示改ページで検証できなかった位置: {metrics['locator_resolution']['docx_page_labels_unverified']} 件。これらはソースで一致したsection見出し単位へ限定して採点する。",
        f"- runner提供asset_rankingとchunk_rankingからの独立dedup照合: {sum(row['status'] == 'match' for row in asset_ranking_consistency_rows)}/{len(asset_ranking_consistency_rows)} calls一致。詳細は `asset_ranking_consistency.csv`。",
    ]
    if execution:
        history = execution.get("historical_query_attempts", {})
        lines.append(f"- ranking品質の正式入力は {execution['formal_query_run']['attempt_id']} のrawのみ。旧query attempt 01/03/04は保持したまま除外し、attempt-01のdocument timingだけを同じindex/vector SHAの由来記録として再利用した。旧aggregation contract c0 bodyは未保存（sha256={str(history.get('prior_aggregation_contract_sha256') or '')[:12]}…）で、旧query成績を現契約へ再採点していない。")
    lines.extend(["", "## 品質指標", "",
        "Hit@k、MRR@10、根拠エントリ coverage は answerable 問題を分母に計算した。Fine evidence の主指標はgoldで指定したasset/pathとsource locatorへの到達を測り、生成回答やfacts理解の正解率は示さない。",
        "",
        "| split | rep | 指標 | k | 値 | 分母 | 特記対象数 |",
        "|---|---:|---|---:|---:|---:|---:|",
    ])
    for row in metric_rows:
        value = fmt(row["value"])
        lines.append(f"| {row['split']} | {row['repetition']} | {row['metric']} | {row['k']} | {value} | {row['denominator']} | {row['special_case_queries']} |")
    test_modality = [row for row in modality_metric_rows
                     if row["split"] == "test" and row["repetition"] == 1 and row["k"] == 1
                     and row["metric"] in {"asset_hit", "fine_evidence_hit"}]
    modalities = sorted({row["modality"] for row in test_modality})
    lines.extend(["", "### test modality別 Hit@1", "",
                  "| modality | answerable数 | asset Hit@1 | fine evidence Hit@1 | fine分母 |",
                  "|---|---:|---:|---:|---:|"])
    for modality in modalities:
        asset_row = next((row for row in test_modality if row["modality"] == modality and row["metric"] == "asset_hit"), None)
        fine_row = next((row for row in test_modality if row["modality"] == modality and row["metric"] == "fine_evidence_hit"), None)
        lines.append(f"| {modality} | {asset_row['denominator'] if asset_row else 0} | {fmt(asset_row['value'] if asset_row else None)} | {fmt(fine_row['value'] if fine_row else None)} | {fine_row['denominator'] if fine_row else 0} |")
    spreadsheet_asset_h1 = next((row for row in test_modality
                                 if row["modality"] == "spreadsheet" and row["metric"] == "asset_hit"), None)
    if spreadsheet_asset_h1:
        matched = round((spreadsheet_asset_h1["value"] or 0) * spreadsheet_asset_h1["denominator"])
        total = spreadsheet_asset_h1["denominator"]
        lines.extend(["",
                      f"Spreadsheet test asset Hit@1 は {matched}/{total}（{fmt(spreadsheet_asset_h1['value'] * 100 if spreadsheet_asset_h1['value'] is not None else None, 1)}%）。これはgold指定Excelへのsource-retrieval比率であり、回答正答率・計算能力を表さない。独立検収ではHit@1 miss 6件中5件について、別資料にも同値または計算入力が見つかった（NKB-017/018/019/021/024）。ただし取得locator自体が答えを含む証拠とは限らず、NKB-024ではtop chunkが期限の行である。NKB-023（EXP102）の14,500取引行はD-HRに存在せず、確認されたrow-level source miss。goldで指定したExcelだけを数える指標は、別資料にある正当な代替根拠を網羅しない。個別の注記は `retrieval_failures.csv` に記録した。"])
    incomplete_asset_rows = [row for row in granularity_diagnostic_rows
                             if row["asset_hit_at_k"] and row["fine_status"] != "full"]
    overlong_rows = [row for row in granularity_diagnostic_rows if row["overlong_overlapping_candidates"]]
    lines.extend([
        "",
        "## 音声・動画の区間粒度診断",
        "",
        "audio_videoのfine coverageには、gold区間と重なり、かつcandidate区間の長さがgold区間以下（1e-6秒許容）のsegment-specific locatorだけを使った。長すぎる区間・ファイル全体のlocatorはfine unionから除外し、asset_hitは別のasset指標として保持する。この診断は区間locatorの検索粒度を示し、音声・映像内容の理解度ではない。",
        f"- asset hitはあるがfine entryが未完了の診断行: {len(incomplete_asset_rows)}。長すぎて除外した重複区間を含む診断行: {len(overlong_rows)}（全行は `fine_granularity_diagnostics.csv`）。",
        "",
        "| split | rep | k | asset hitあり・fine未完了 | 長すぎるoverlap候補あり |",
        "|---|---:|---:|---:|---:|",
    ])
    for split in ("test", "dev"):
        for k in (1, 3, 5, 10):
            rows = [row for row in granularity_diagnostic_rows
                    if row["split"] == split and row["repetition"] == 1 and row["k"] == k]
            incomplete = sum(row["asset_hit_at_k"] and row["fine_status"] != "full" for row in rows)
            overlong = sum(bool(row["overlong_overlapping_candidates"]) for row in rows)
            lines.append(f"| {split} | 1 | {k} | {incomplete} | {overlong} |")
    examples = [row for row in granularity_diagnostic_rows
                if row["repetition"] == 1 and row["k"] == 5 and row["asset_hit_at_k"] and row["fine_status"] != "full"]
    lines.extend(["", "代表行（test/dev・rep1・k=5）:", "",
                  "| query | asset | gold区間 | fine coverage | 除外した候補 | 理由 |",
                  "|---|---|---|---:|---|---|"])
    for row in examples[:20]:
        lines.append(f"| {row['query_id']} | {row['asset_id']} | {row['gold_location']} | {fmt(row['fine_coverage_fraction'])} | {row['excluded_overlong_candidate_ranges'] or 'なし'} | {row['reason']} |")
    if not examples:
        lines.append("| 該当なし | — | — | — | — | k=5でasset hitとfine未完了が同時に起きた行はありません。 |")
    if len(examples) > 20:
        lines.append(f"| … | … | … | … | … | 残り{len(examples)-20}行はCSVを参照。 |")
    primary_failures = [row for row in retrieval_failure_rows
                        if row["split"] == "test" and row["repetition"] == 1 and row["k"] == 5]
    lines.extend(["", "## 個別のretrieval failure", "",
                  f"`retrieval_failures.csv` にanswerable queryのasset miss、fine evidence未到達、全根拠未完了、部分coverageをquery・repetition・cutoff別に保存した。全データのfailure行は {len(retrieval_failure_rows)} 行。testの主成績（rep1, k=5）でのfailureは {len(primary_failures)} 行。", "",
                  "| query | modality/task | failure | gold asset | top asset | top locator |",
                  "|---|---|---|---|---|---|"])
    for row in primary_failures[:15]:
        assets = json.loads(row["top_assets"])
        chunks = json.loads(row["top_chunks"])
        top_asset = ", ".join(f"{item.get('asset_id')} ({fmt(item.get('score'), 4)})" for item in assets[:3]) or "なし"
        top_chunk = "; ".join(f"{item.get('asset_id')}|{item.get('locator')} ({fmt(item.get('score'), 4)})" for item in chunks[:3]) or "なし"
        lines.append(f"| {row['query_id']} | {row['modality']}/{row['task']} | {row['failure_reasons']} | {row['gold_asset_ids']} | {top_asset} | {top_chunk} |")
    if not primary_failures:
        lines.append("| 該当なし | — | — | — | — | test rep1 k=5で記録されたretrieval failureはありません。 |")
    if len(primary_failures) > 15:
        lines.append(f"| … | … | … | … | … | 残り{len(primary_failures)-15}行はCSVを参照。 |")
    lines.extend(["", "## test検索時間", "", "p95 は nearest-rank `ceil(0.95*n)`。初回は最初の test query call として扱い、warmed-only はその1回を除外する。", "",
                  "| 集計範囲 | 期待calls | 記録calls | 計測数 | 失敗数 | median ms | mean ms | p95 ms | max ms | 初回 ms |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for row in latency_rows:
        lines.append("| {population} | {expected_calls} | {recorded_calls} | {timed_calls} | {failed_calls} | {median_ms} | {mean_ms} | {p95_ms} | {max_ms} | {first_query_ms} |".format(
            population=row["population"], expected_calls=row["expected_calls"], recorded_calls=row["recorded_calls"],
            timed_calls=row["timed_calls"], failed_calls=row["failed_calls"], median_ms=fmt(row["median_ms"], 2),
            mean_ms=fmt(row["mean_ms"], 2), p95_ms=fmt(row["p95_ms"], 2), max_ms=fmt(row["max_ms"], 2),
            first_query_ms=fmt(row["first_query_ms"], 2)))
    if execution:
        qrun = execution["formal_query_run"]
        qrt = execution.get("query_runtime") or {}
        doc = execution.get("document_index_build") or {}
        lines.extend(["", "## CPU実行・index作成・query段階", "",
                      f"- 正式query run: {qrun.get('attempt_id')}、status={qrun.get('status')}、model revision `{qrt.get('model_revision')}`、device={qrt.get('device')}、dtype={qrt.get('dtype')}。query processのtorch threads={qrt.get('torch_threads')}、CPU limit={qrt.get('container_cpu_limit_cores')} cores、memory limit={qrt.get('container_memory_limit_bytes')} bytes。",
                      f"- query processのmodel load={fmt(qrt.get('model_load_seconds'), 3)}秒。query実行wall={fmt(qrun.get('query_execution_wall_seconds'), 3)}秒、query container wall={fmt(qrun.get('query_container_wall_seconds'), 3)}秒。modelはquery call前にロード済み（first test call cold={qrt.get('first_test_call_is_cold')}）で、上の1回あたりlatencyはこのmodel load時間を含まない。",
                      f"- index作成は `{doc.get('source_attempt_id')}` の別記録を参照（正式query runでは同じindex/vectorを再利用）。{doc.get('successful_chunk_records')} chunks成功、errors={doc.get('errors')}、index SHA `{doc.get('index_sha256')}`。input extraction={fmt(doc.get('input_extraction_seconds'), 3)}秒、document-process model load={fmt(doc.get('model_load_seconds'), 3)}秒、document embedding wall={fmt(doc.get('embedding_wall_seconds'), 3)}秒、vector index write={fmt(doc.get('vector_index_write_seconds'), 3)}秒。",
                      f"- index process thread setting: {doc.get('source_runtime_setting') or '記録なし'}。per-process thread readbackはmanifestに保存されていない（`index_process_thread_readback_serialized={doc.get('index_process_thread_readback_serialized')}`）ため、index build中の実torch thread数は未確認。query processの4-thread readbackをindex処理へ流用していない。", ""])
    lines.extend(["", "## Unanswerable 問題", "", f"実際の未回答ケース一覧は `unanswerable.csv` に保存した（記録 {len(unanswerable_rows)} 行）。検索ヒットは回答可能性や正しい棄却の証明として扱わない。", "",
                  "## 制約と出力", "", "全文字列によるrequired fact診断は `fact_support_diagnostics.csv` に分離した保守的な診断であり、ネイティブ音声・動画の内容理解や生成回答の正解率ではない。時間区間は全幅を連続して覆い、表計算の範囲は全セルが取得された場合にevidence entryをcoverage済みとする。部分時間/セルcoverage率は `fine_evidence_unit_fraction_coverage` に別記する。", "",
                  "出力: `metrics.json`, `quality_metrics.csv`, `modality_metrics.csv`, `retrieval_failures.csv`, `latency_summary.csv`, `unknown_scores.csv`, `unanswerable.csv`, `fact_support_diagnostics.csv`, `fine_granularity_diagnostics.csv`, `unresolved_gold_locators.csv`, `unresolved_candidates.csv`, `asset_ranking_consistency.csv`。", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    main()
