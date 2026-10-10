"""One-item-per-modality native API smoke test using source assets, not QA data."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import traceback
from pathlib import Path

import fitz
import psutil
import torch
from sentence_transformers import SentenceTransformer


REVISION = os.environ["MODEL_REVISION"]
SNAPSHOT = Path(os.environ["MODEL_SNAPSHOT"])
RUN_ROOT = Path("/benchmark/run")
INPUT_ROOT = Path("/benchmark/inputs")
VIDEO_PROCESSING = {
    "fps": 1,
    "max_frames": 32,
    "overflow_strategy": "uniform",
    "add_timestamps": False,
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cgroup_peak_bytes() -> int | None:
    path = Path("/sys/fs/cgroup/memory.peak")
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def run_command(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def main() -> None:
    torch.set_num_threads(4)
    run_root = RUN_ROOT / "smoke"
    run_root.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []
    started = time.perf_counter()
    report = {
        "schema": "embeddinggemma2-native-smoke/v1",
        "model_id": os.environ["MODEL_ID"],
        "requested_revision": REVISION,
        "snapshot_path": str(SNAPSHOT),
        "cpu_threads": torch.get_num_threads(),
        "device": "cpu",
        "dtype_requested": "torch.float32",
        "text_query_prompt": "task: question answering | query: ",
        "text_document_prompt": "title: none | text: ",
        "media_document_prompt": "",
        "video_processing": VIDEO_PROCESSING,
        "inputs": {},
        "modalities": {},
    }
    process = psutil.Process()
    if SNAPSHOT.name != REVISION or not SNAPSHOT.is_dir():
        error = f"fixed snapshot missing or path suffix differs from revision: {SNAPSHOT}"
        report["fatal_error"] = error
        (run_root / "smoke-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (run_root / "smoke.log").write_text(error + "\n", encoding="utf-8")
        raise SystemExit(1)

    text_path = INPUT_ROOT / "documents" / "quality_notice.pdf"
    with fitz.open(text_path) as pdf:
        text_sample = pdf[0].get_text("text").strip()
    image_source = INPUT_ROOT / "video" / "f2_inspection.mp4"
    image_path = run_root / "first-frame.png"
    audio_source = INPUT_ROOT / "audio" / "quality_meeting.wav"
    audio_path = run_root / "first-audio-4s.wav"
    video_path = image_source
    run_command(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "0", "-i", str(image_source), "-frames:v", "1", str(image_path)])
    run_command(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "0", "-i", str(audio_source), "-t", "4", "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)])
    report["inputs"] = {
        "text": {"asset_id": "P-QA", "source": "first source PDF page text", "source_sha256": digest(text_path)},
        "image": {"asset_id": "V-F2", "source": "first decoded video frame at 0 seconds", "source_sha256": digest(image_source), "derived_sha256": digest(image_path)},
        "audio": {"asset_id": "A-QA", "source_interval_seconds": [0, 4], "source_sha256": digest(audio_source), "derived_sha256": digest(audio_path)},
        "video": {"asset_id": "V-F2", "source_interval_seconds": [0, 24], "source_sha256": digest(video_path)},
    }

    load_start = time.perf_counter()
    try:
        model = SentenceTransformer(
            str(SNAPSHOT),
            device="cpu",
            model_kwargs={"dtype": torch.float32, "local_files_only": True},
        )
        report["model_load_seconds"] = round(time.perf_counter() - load_start, 6)
        auto_model = getattr(model[0], "auto_model", None)
        config = getattr(auto_model, "config", None)
        report["architecture"] = type(auto_model).__name__ if auto_model is not None else None
        report["vision_config_loaded"] = getattr(config, "vision_config", None) is not None
        report["audio_config_loaded"] = getattr(config, "audio_config", None) is not None
        report["supports_api"] = {
            modality: bool(model.supports(modality))
            for modality in ("text", "image", "audio", "video")
        }
        parameters = list(auto_model.parameters()) if auto_model is not None else []
        report["parameters_loaded"] = sum(parameter.numel() for parameter in parameters)
        report["parameter_dtypes"] = sorted({str(parameter.dtype) for parameter in parameters})
        report["max_seq_length"] = model.max_seq_length
        report["prompt_config"] = getattr(model, "prompts", {})
        if not report["vision_config_loaded"] or not report["audio_config_loaded"]:
            raise RuntimeError("native towers not loaded: expected both vision_config and audio_config")
        if not all(report["supports_api"].values()):
            raise RuntimeError(f"model.supports() did not confirm every required modality: {report['supports_api']}")
        if report["parameter_dtypes"] != ["torch.float32"]:
            raise RuntimeError(f"expected float32 parameters, got {report['parameter_dtypes']}")
    except Exception as exc:
        report["fatal_error"] = f"model load/contract check failed: {type(exc).__name__}: {exc}"
        log_lines.append(traceback.format_exc())
        report["rss_after_model_load_bytes"] = process.memory_info().rss
        report["cgroup_peak_bytes"] = cgroup_peak_bytes()
        report["smoke_wall_seconds"] = round(time.perf_counter() - started, 6)
        (run_root / "smoke-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (run_root / "smoke.log").write_text("\n".join(log_lines), encoding="utf-8")
        raise SystemExit(1)

    cases = {
        "text": {"kind": "text", "payload": text_sample},
        "image": {"kind": "image", "payload": {"image": str(image_path)}},
        "audio": {"kind": "audio", "payload": {"audio": str(audio_path)}},
        "video": {"kind": "video", "payload": {"video": str(video_path)}},
    }
    for modality, payload in cases.items():
        item_started = time.perf_counter()
        try:
            kwargs = {
                "normalize_embeddings": True,
                "convert_to_numpy": True,
                "batch_size": 1,
                "show_progress_bar": False,
            }
            if modality == "text":
                vector = model.encode_document([payload["payload"]], **kwargs)[0]
            else:
                kwargs["prompt"] = ""
                if modality == "video":
                    kwargs["processing_kwargs"] = {"video": VIDEO_PROCESSING}
                vector = model.encode_document([payload["payload"]], **kwargs)[0]
            norm = float((vector * vector).sum() ** 0.5)
            if vector.shape != (768,) or not torch.isfinite(torch.from_numpy(vector)).all():
                raise RuntimeError(f"invalid vector shape or values: {vector.shape}")
            if abs(norm - 1.0) > 1e-3:
                raise RuntimeError(f"expected unit-norm vector, got norm={norm}")
            report["modalities"][modality] = {
                "status": "ok",
                "dimension": int(vector.shape[0]),
                "dtype": str(vector.dtype),
                "norm": norm,
                "encode_seconds": round(time.perf_counter() - item_started, 6),
                "rss_bytes_after": process.memory_info().rss,
            }
            log_lines.append(f"{modality}: status=ok dimension=768 norm={norm:.6f}")
        except Exception as exc:
            report["modalities"][modality] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "encode_seconds": round(time.perf_counter() - item_started, 6),
            }
            log_lines.append(f"{modality}: status=error {type(exc).__name__}: {exc}")
            log_lines.append(traceback.format_exc())

    query_start = time.perf_counter()
    try:
        query_vector = model.encode_query([text_sample], prompt_name="QuestionAnswering", normalize_embeddings=True,
                                          convert_to_numpy=True, batch_size=1,
                                          show_progress_bar=False)[0]
        report["modalities"]["text_query"] = {
            "status": "ok",
            "dimension": int(query_vector.shape[0]),
            "dtype": str(query_vector.dtype),
            "norm": float((query_vector * query_vector).sum() ** 0.5),
            "encode_seconds": round(time.perf_counter() - query_start, 6),
        }
    except Exception as exc:
        report["modalities"]["text_query"] = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "encode_seconds": round(time.perf_counter() - query_start, 6),
        }
        log_lines.append(f"text_query: status=error {type(exc).__name__}: {exc}")
        log_lines.append(traceback.format_exc())

    report["rss_after_smokes_bytes"] = process.memory_info().rss
    report["cgroup_peak_bytes"] = cgroup_peak_bytes()
    report["smoke_wall_seconds"] = round(time.perf_counter() - started, 6)
    report["all_modalities_ok"] = all(result["status"] == "ok" for result in report["modalities"].values())
    (run_root / "smoke-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_root / "smoke.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "all_modalities_ok": report["all_modalities_ok"],
        "architecture": report.get("architecture"),
        "parameters_loaded": report.get("parameters_loaded"),
        "modalities": {key: value["status"] for key, value in report["modalities"].items()},
        "smoke_wall_seconds": report["smoke_wall_seconds"],
        "cgroup_peak_bytes": report["cgroup_peak_bytes"],
    }, ensure_ascii=False))
    if not report["all_modalities_ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
