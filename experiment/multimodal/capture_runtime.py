"""Capture experiment-container versions and limits without loading the model."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import psutil
import torch


RUN_ROOT = Path("/benchmark/run")
SNAPSHOT = Path(os.environ["MODEL_SNAPSHOT"])
PACKAGES = [
    "torch", "torchvision", "transformers", "sentence-transformers", "numpy", "Pillow",
    "fastapi", "uvicorn", "soundfile", "PyMuPDF", "python-docx", "openpyxl",
    "python-pptx", "av", "psutil", "librosa", "torchcodec", "scipy", "numba", "llvmlite",
]


def first_line(command: list[str]) -> str:
    proc = subprocess.run(command, check=True, capture_output=True, text=True)
    return proc.stdout.splitlines()[0] if proc.stdout else proc.stderr.splitlines()[0]


def read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="ascii").strip()
    except OSError:
        return None


def main() -> None:
    torch.set_num_threads(4)
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    report = {
        "schema": "embeddinggemma2-accuracy-speed-container-runtime/v1",
        "python": sys.version,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "logical_cpus_visible": os.cpu_count(),
        "process_affinity_cpu_count": len(psutil.Process().cpu_affinity()) if hasattr(psutil.Process(), "cpu_affinity") else None,
        "torch_threads": torch.get_num_threads(),
        "device": "cpu",
        "dtype": "torch.float32",
        "packages": versions,
        "ffmpeg_version": first_line(["ffmpeg", "-version"]),
        "ffprobe_version": first_line(["ffprobe", "-version"]),
        "cgroup_cpu_max": read_text("/sys/fs/cgroup/cpu.max"),
        "cgroup_memory_max_bytes": read_text("/sys/fs/cgroup/memory.max"),
        "cgroup_memory_peak_bytes": read_text("/sys/fs/cgroup/memory.peak"),
        "snapshot_path": str(SNAPSHOT),
        "snapshot_path_exists": SNAPSHOT.is_dir(),
        "offline_environment": {
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
            "network_mode": "none",
        },
    }
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    (RUN_ROOT / "container-runtime.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"python": sys.version.split()[0], "torch": versions["torch"], "sentence_transformers": versions["sentence-transformers"], "transformers": versions["transformers"], "torchcodec": versions["torchcodec"], "librosa": versions["librosa"], "ffmpeg": report["ffmpeg_version"], "cgroup_cpu_max": report["cgroup_cpu_max"], "cgroup_memory_max_bytes": report["cgroup_memory_max_bytes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
