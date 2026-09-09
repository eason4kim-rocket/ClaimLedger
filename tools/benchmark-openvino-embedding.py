#!/usr/bin/env python3
"""Run a small, reproducible OpenVINO embedding benchmark on one device."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path


TEXTS = [
    "采购委员会仅批准供应商B先试供30%，供应商A保留70%。",
    "供应商B比供应商A每年多支出72.16万元。",
    "供应商B综合到岸成本排名第三。",
    "扫描报价单有效期至2026年8月31日。",
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device", choices=("CPU", "GPU", "NPU"), required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    import openvino
    import openvino_genai as ov_genai

    available = list(openvino.Core().available_devices)
    if args.device not in available:
        raise SystemExit(f"device {args.device} unavailable; available={available}")
    model = args.model.resolve()
    weights = model / "openvino_model.bin"
    started = time.perf_counter()
    pipeline = ov_genai.TextEmbeddingPipeline(model, args.device)
    load_ms = round((time.perf_counter() - started) * 1000, 3)

    timings = []
    shape = None
    checksum = None
    for _ in range(args.runs):
        started = time.perf_counter()
        vectors = pipeline.embed_documents(TEXTS)
        timings.append(round((time.perf_counter() - started) * 1000, 3))
        shape = [len(vectors), len(vectors[0])]
        checksum = round(sum(float(value) for value in vectors[0][:32]), 8)

    payload = {
        "schema": "claimledger-openvino-embedding-benchmark-v1",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": platform.node(),
        "platform": platform.platform(),
        "pid": os.getpid(),
        "openvino_version": openvino.__version__,
        "available_devices": available,
        "device": args.device,
        "model": model.name,
        "model_weights_bytes": weights.stat().st_size,
        "model_weights_sha256": digest(weights),
        "input_count": len(TEXTS),
        "vector_shape": shape,
        "vector_checksum": checksum,
        "load_ms": load_ms,
        "inference_ms": timings,
        "warm_inference_mean_ms": round(sum(timings[1:]) / max(1, len(timings) - 1), 3),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
