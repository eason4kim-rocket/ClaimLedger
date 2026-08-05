from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import webbrowser
from pathlib import Path

import uvicorn
import yaml
from pydantic import ValidationError

from . import __version__
from .benchmark import run_benchmark
from .brief import build_brief
from .config import (
    api_token,
    ensure_private_dir,
    ensure_private_file,
    jobs_dir,
    model_api_token,
    models_dir,
    rotate_api_token,
    rotate_model_api_token,
    skill_root,
)
from .demo import create_demo
from .engine import new_job, recheck_replacement, run_audit
from .exporters import export_final, export_standard_artifacts
from .models import DecisionRequest, JobRequest, PolicyRule, ReviewerProfile
from .storage import JobStore


def emit(payload, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    elif isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")
    else:
        print(payload)


def _model_manifest() -> dict:
    return yaml.safe_load(
        (skill_root() / "assets" / "models.yaml").read_text(encoding="utf-8")
    )["profiles"]


def _openvino_devices() -> list[str]:
    try:
        from openvino import Core

        return list(Core().available_devices)
    except Exception:
        return []


def _physical_memory_bytes() -> int | None:
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def model_status(profile: str) -> dict:
    selected = _model_manifest()[profile]
    payload = {
        "profile": profile,
        "models": selected,
        "destination": str(models_dir()),
        "packages": {
            name: importlib.util.find_spec(name) is not None
            for name in ("paddle", "paddleocr", "openvino", "openvino_genai")
        },
        "openvino_devices": _openvino_devices(),
        "disk_free_bytes": shutil.disk_usage(models_dir()).free,
        "installed": False,
        "offline_ready": False,
    }
    if profile == "deterministic":
        payload.update(installed=True, offline_ready=True)
        return payload
    if profile == "lite":
        roots = [
            Path.home() / ".paddlex" / "official_models",
            Path.home() / ".paddleocr" / "whl",
        ]
        expected = (
            "PP-LCNet_x1_0_doc_ori",
            "PP-LCNet_x1_0_textline_ori",
            "PP-OCRv5_mobile_det",
            "PP-OCRv5_mobile_rec",
        )
        discovered = {
            name: next(
                (
                    str(path)
                    for root in roots
                    for path in root.glob(f"**/{name}")
                    if path.is_dir()
                ),
                None,
            )
            for name in expected
        }
        ready = all(payload["packages"][name] for name in ("paddle", "paddleocr")) and all(
            discovered.values()
        )
        payload.update(
            installed=ready,
            offline_ready=ready,
            model_paths=discovered,
            ocr_cache_roots=[str(root) for root in roots],
        )
        return payload
    installations = {}
    ready = True
    for role in ("generation", "embeddings", "reranker"):
        model_id = selected[role]
        path = models_dir() / model_id.replace("/", "--")
        manifest_path = path / "installation.json"
        installed = path.is_dir() and (path / "openvino_model.xml").is_file()
        ready = ready and installed
        installations[role] = {
            "model_id": model_id,
            "path": str(path),
            "installed": installed,
            "installation_manifest": (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.is_file()
                else None
            ),
        }
    packages_ready = all(
        payload["packages"][name] for name in ("openvino", "openvino_genai")
    )
    compile_cache = models_dir() / ".openvino-cache"
    compile_cache_bytes = sum(
        path.stat().st_size
        for path in compile_cache.rglob("*")
        if path.is_file()
    ) if compile_cache.is_dir() else 0
    payload.update(
        installed=ready and packages_ready,
        offline_ready=ready and packages_ready,
        installations=installations,
        compile_cache_path=str(compile_cache),
        compile_cache_bytes=compile_cache_bytes,
        resource_guidance={
            "explicit_opt_in_required": True,
            "default_for_natural_language_audits": False,
            "tested_peak_rss_bytes": 17_459_937_280,
            "system_memory_bytes": _physical_memory_bytes(),
            "warning": (
                "Balanced can make a 24 GB Mac unresponsive. Use lite for normal audits; "
                "start Balanced only after an explicit user request and a successful verify."
            ),
        },
    )
    return payload


def doctor(as_json: bool, deep: bool = False) -> int:
    required = ["fastapi", "docx", "openpyxl", "fitz", "yaml"]
    optional = ["paddle", "paddleocr", "openvino", "openvino_genai"]
    payload = {
        "status": "ok",
        "version": __version__,
        "python": sys.version.split()[0],
        "data_dir": str(jobs_dir().parent),
        "disk_free_bytes": shutil.disk_usage(jobs_dir().parent).free,
        "required": {name: importlib.util.find_spec(name) is not None for name in required},
        "optional_local_ai": {name: importlib.util.find_spec(name) is not None for name in optional},
        "model_gateway_url": "http://127.0.0.1:8877/v3 (override with CLAIMLEDGER_MODEL_GATEWAY_URL)",
        "privacy": "localhost-only; no cloud fallback",
        "supported_rule_packs": ["generic-zh", "procurement-zh", "operations-zh", "consulting-zh", "lithium-demo"],
        "schema_version": JobStore().schema_version(),
        "models": {
            "lite": model_status("lite"),
            "balanced": model_status("balanced"),
        },
    }
    if not all(payload["required"].values()):
        payload["status"] = "error"
        payload["action"] = "install the project with: pip install -e ."
    if deep:
        payload["deep_checks"] = {
            "lite": verify_models("lite", "CPU", run_inference=True),
            "balanced": verify_models("balanced", "CPU", run_inference=False),
        }
        if not payload["deep_checks"]["lite"]["ok"]:
            payload["status"] = "warning"
    emit(payload, as_json)
    return 0 if payload["status"] == "ok" else 2


def install_models(profile: str, execute: bool, as_json: bool) -> int:
    selected = _model_manifest()[profile]
    required_free = 12 * 1024**3 if profile == "balanced" else 2 * 1024**3
    free_bytes = shutil.disk_usage(models_dir()).free
    payload = {
        "profile": profile,
        "models": selected,
        "destination": str(models_dir()),
        "installed": False,
        "disk_free_bytes": free_bytes,
        "required_free_bytes": required_free,
    }
    if execute and profile != "deterministic" and free_bytes < required_free:
        payload["error"] = (
            f"insufficient disk space: {free_bytes} bytes free; "
            f"{required_free} bytes required"
        )
        emit(payload, as_json)
        return 2
    if profile == "deterministic":
        payload["installed"] = True
    elif profile == "lite":
        packages_ready = importlib.util.find_spec("paddle") is not None and importlib.util.find_spec("paddleocr") is not None
        if not packages_ready:
            payload["action"] = "run: python scripts/bootstrap.py --local-ai"
        elif execute:
            try:
                from .parsers import OcrEngine

                OcrEngine(enabled=True).warmup()
                payload["installed"] = True
                payload["offline_ready"] = True
            except Exception as exc:
                payload["error"] = f"PaddleOCR model warmup failed: {type(exc).__name__}: {exc}"
                emit(payload, as_json)
                return 2
        else:
            payload["action"] = "re-run with --execute to download and initialize PP-OCRv5 before offline use"
    elif execute:
        try:
            from huggingface_hub import HfApi, snapshot_download

            for role in ("generation", "embeddings", "reranker"):
                model_id = selected.get(role)
                if not model_id or model_id == "lexical":
                    continue
                destination = models_dir() / model_id.replace("/", "--")
                revision = HfApi().model_info(model_id).sha
                snapshot_download(
                    repo_id=model_id,
                    revision=revision,
                    local_dir=destination,
                )
                files = []
                for path in sorted(item for item in destination.rglob("*") if item.is_file()):
                    if ".cache" in path.parts or path.name == "installation.json":
                        continue
                    digest = hashlib.sha256()
                    with path.open("rb") as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(block)
                    files.append(
                        {
                            "path": str(path.relative_to(destination)),
                            "size": path.stat().st_size,
                            "sha256": digest.hexdigest(),
                        }
                    )
                installation = {
                    "model_id": model_id,
                    "role": role,
                    "revision": revision,
                    "files": files,
                }
                (destination / "installation.json").write_text(
                    json.dumps(installation, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                ensure_private_file(destination / "installation.json")
            payload["installed"] = True
        except ImportError:
            payload["error"] = "install the local-ai extra before downloading models"
            emit(payload, as_json)
            return 2
    else:
        payload["action"] = "re-run with --execute after installing the local-ai extra"
    emit(payload, as_json)
    return 0


def verify_models(
    profile: str,
    device: str,
    *,
    run_inference: bool = True,
) -> dict:
    status = model_status(profile)
    payload = {
        "profile": profile,
        "device": device,
        "ok": bool(status["offline_ready"]),
        "status": status,
        "checks": [],
    }
    if not status["offline_ready"]:
        payload["checks"].append(
            "models are not offline-ready; run models install with --execute"
        )
        return payload
    if profile == "balanced":
        try:
            for role, installation in status["installations"].items():
                manifest = installation.get("installation_manifest")
                if not manifest:
                    raise RuntimeError(f"{role} installation manifest is missing")
                root = Path(installation["path"])
                for item in manifest.get("files", []):
                    path = root / item["path"]
                    if not path.is_file() or path.stat().st_size != int(item["size"]):
                        raise RuntimeError(f"{role} model file is missing or truncated: {item['path']}")
                    digest = hashlib.sha256()
                    with path.open("rb") as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(block)
                    if digest.hexdigest() != item["sha256"]:
                        raise RuntimeError(f"{role} model hash mismatch: {item['path']}")
            payload["checks"].append("model revisions, file sizes, and SHA-256 verified")
        except Exception as exc:
            payload["ok"] = False
            payload["error"] = f"{type(exc).__name__}: {exc}"
            return payload
    if not run_inference or profile == "deterministic":
        return payload
    try:
        if profile == "lite":
            from PIL import Image, ImageDraw
            from .parsers import OcrEngine

            with tempfile.TemporaryDirectory(prefix="claimledger-ocr-") as temporary:
                image_path = Path(temporary) / "smoke.png"
                image = Image.new("RGB", (700, 160), "white")
                ImageDraw.Draw(image).text((24, 50), "ClaimLedger 2026 120", fill="black")
                image.save(image_path)
                engine = OcrEngine(enabled=True)
                engine.warmup()
                engine.read_lines(image_path)
                if engine.error:
                    raise RuntimeError(engine.error)
            payload["checks"].append("PP-OCRv5 inference completed")
        else:
            os.environ["CLAIMLEDGER_MODEL_DEVICE"] = device
            from .model_gateway import ModelRuntime, EmbeddingsRequest, RerankRequest

            runtime = ModelRuntime()
            selected = _model_manifest()["balanced"]
            vectors = runtime.embed(
                EmbeddingsRequest(
                    model=selected["embeddings"],
                    input=["证据审计", "运营报告"],
                )
            )
            if len(vectors) != 2:
                raise RuntimeError("embedding smoke test returned an unexpected shape")
            runtime.release("embedding")
            ranked = runtime.rerank(
                RerankRequest(
                    model=selected["reranker"],
                    query="证据审计",
                    documents=["审计报告证据", "天气预报"],
                    top_n=2,
                )
            )
            if not ranked:
                raise RuntimeError("reranker smoke test returned no result")
            runtime.release("all")
            payload["checks"].append("OpenVINO embedding and reranker inference completed")
        payload["ok"] = True
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = f"{type(exc).__name__}: {exc}"
    return payload


def _model_health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/v3/models"


def ensure_model_gateway(port: int = 8877, device: str = "CPU") -> dict:
    import httpx

    url = _model_health_url(port)
    token = model_api_token()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = httpx.get(url, headers=headers, timeout=1.0, trust_env=False)
        if response.status_code == 200:
            orphan_pid = _read_orphaned_gateway_pid(port)
            if orphan_pid is None:
                os.environ["CLAIMLEDGER_MODEL_GATEWAY_URL"] = f"http://127.0.0.1:{port}/v3"
                return {"status": "already_running", "health_url": url, "temporary": False}
            # A previous audit was interrupted before its finally block could
            # run; reclaim the orphaned temporary gateway instead of reusing
            # (and permanently keeping) its multi-GB model residency.
            _stop_temporary_gateway(orphan_pid)
    except Exception:
        pass
    readiness = model_status("balanced")
    if not readiness["offline_ready"]:
        raise RuntimeError(
            "balanced models are not installed; run "
            "claimledger models install --profile balanced --execute"
        )
    token = rotate_model_api_token()
    service_dir = ensure_private_dir(jobs_dir().parent / "model-service")
    log_path = service_dir / f"model-gateway-{port}.log"
    log_handle = log_path.open("ab")
    log_path.chmod(0o600)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "claimledger.model_gateway:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        cwd=str(skill_root()),
        env={
            **os.environ,
            "PYTHONPATH": str(skill_root() / "src"),
            "CLAIMLEDGER_MODEL_DEVICE": device,
        },
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    headers = {"Authorization": f"Bearer {token}"}
    ready = False
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f"local model gateway exited; inspect {log_path}")
            try:
                response = httpx.get(url, headers=headers, timeout=1.0, trust_env=False)
                if response.status_code == 200:
                    os.environ["CLAIMLEDGER_MODEL_GATEWAY_URL"] = f"http://127.0.0.1:{port}/v3"
                    pid_path = service_dir / f"model-gateway-{port}.pid"
                    pid_path.write_text(str(process.pid), encoding="utf-8")
                    ensure_private_file(pid_path)
                    ready = True
                    return {
                        "status": "started",
                        "pid": process.pid,
                        "health_url": url,
                        "log": str(log_path),
                        "temporary": True,
                    }
            except Exception:
                time.sleep(0.2)
        raise RuntimeError(f"local model gateway did not become healthy; inspect {log_path}")
    finally:
        # Also cover health-check timeout and pid-file write failures. Merely
        # calling terminate() is insufficient when native inference is stuck.
        if not ready and process.poll() is None:
            _stop_temporary_gateway(process.pid)


def _read_orphaned_gateway_pid(port: int) -> int | None:
    """Return the pid of a temporary gateway whose owning audit has exited.

    Temporary gateways are detached (``start_new_session``), so once the
    owning audit process dies the gateway is reparented to init/launchd and
    keeps its models resident. A live pid file entry with PPID 1 therefore
    marks an orphan. Manually started ``models serve`` gateways have no pid
    file and are never reclaimed here. Non-POSIX platforms (no ``ps``) fall
    back to reusing the running gateway.
    """

    pid_path = jobs_dir().parent / "model-service" / f"model-gateway-{port}.pid"
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        process_row = subprocess.check_output(
            ["ps", "-o", "ppid=,command=", "-p", str(pid)], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        # The recorded process is gone; drop the stale pid file without
        # touching whatever currently listens on the port.
        pid_path.unlink(missing_ok=True)
        return None
    parts = process_row.split(maxsplit=1)
    if len(parts) != 2:
        return None
    ppid, command = parts
    expected_gateway = "claimledger.model_gateway:app" in command
    expected_port = f"--port {port}" in command
    if not (expected_gateway and expected_port):
        # The operating system may have reused a stale pid. Never terminate a
        # process based on pid and parentage alone.
        pid_path.unlink(missing_ok=True)
        return None
    return pid if ppid == "1" else None


def _stop_temporary_gateway(pid: int, grace_seconds: float = 5.0) -> None:
    """Stop an audit-owned gateway even when native inference blocks graceful exit."""

    def clean_pid_file() -> None:
        service_dir = jobs_dir().parent / "model-service"
        if not service_dir.is_dir():
            return
        for pid_path in service_dir.glob("model-gateway-*.pid"):
            try:
                if pid_path.read_text(encoding="utf-8").strip() == str(pid):
                    pid_path.unlink()
            except (OSError, UnicodeError):
                continue

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        clean_pid_file()
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            finished, _status = os.waitpid(pid, os.WNOHANG)
            if finished == pid:
                clean_pid_file()
                return
        except ChildProcessError:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                clean_pid_file()
                return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        clean_pid_file()
        return
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    clean_pid_file()


def profiles_command(args) -> int:
    store = JobStore()
    try:
        if args.profiles_command == "create":
            profile = store.create_profile(
                ReviewerProfile(name=args.name, role_template=args.role)
            )
            emit(profile.model_dump(mode="json"), args.json)
            return 0
        if args.profiles_command == "list":
            emit(
                {"items": [item.model_dump(mode="json") for item in store.list_profiles()]},
                args.json,
            )
            return 0
        if args.profiles_command == "show":
            profile = store.get_profile(args.name)
            if not profile:
                raise ValueError("reviewer profile not found")
            payload = profile.model_dump(mode="json")
            payload["active_policies"] = [
                item.model_dump(mode="json")
                for item in store.list_policies(profile.id, state="active")
            ]
            emit(payload, args.json)
            return 0
        if args.profiles_command == "export":
            from .memory import export_profile

            profile = store.get_profile(args.name)
            if not profile:
                raise ValueError("reviewer profile not found")
            payload = export_profile(profile, store.list_policies(profile.id))
            if args.output:
                output = Path(args.output).expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                ensure_private_file(output)
                emit({"output": str(output), "profile": profile.name}, args.json)
            else:
                emit(payload, True)
            return 0
        if args.profiles_command == "import":
            from .memory import stable_hash

            payload = json.loads(Path(args.file).expanduser().read_text(encoding="utf-8"))
            if payload.get("format") != "claimledger-review-profile-v1":
                raise ValueError("unsupported profile export format")
            source = payload["profile"]
            profile = store.create_profile(
                ReviewerProfile(
                    name=args.name or source["name"],
                    role_template=source.get("role_template", "generic"),
                    preferences=source.get("preferences", {}),
                )
            )
            imported = 0
            for raw in payload.get("policies", []):
                raw = dict(raw)
                raw["id"] = f"policy-{uuid.uuid4().hex[:12]}"
                raw["profile_id"] = profile.id
                raw["state"] = "active"
                raw["hash"] = stable_hash(
                    {
                        "profile_id": profile.id,
                        "version": raw.get("version"),
                        "source_memory_id": raw.get("source_memory_id"),
                        "rule": raw.get("rule"),
                        "reason": raw.get("reason"),
                    }
                )
                store.save_policy(PolicyRule.model_validate(raw))
                imported += 1
            emit(
                {"profile": profile.model_dump(mode="json"), "imported_policies": imported},
                args.json,
            )
            return 0
        deleted = store.delete_profile(args.name)
        if not deleted:
            raise ValueError("reviewer profile not found")
        emit({"deleted": True, "profile": args.name}, args.json)
        return 0
    except (ValueError, KeyError, json.JSONDecodeError, ValidationError) as exc:
        emit({"error": str(exc)}, args.json)
        return 2


def memory_command(args) -> int:
    store = JobStore()
    profile = store.get_profile(args.profile)
    if not profile:
        emit({"error": "reviewer profile not found"}, args.json)
        return 2
    if args.memory_command == "list":
        events = store.list_memories(profile.id, include_expired=args.include_expired)
        emit({"items": [item.model_dump(mode="json") for item in events]}, args.json)
        return 0
    removed = store.prune_memories(profile.id, before=args.before)
    emit({"profile": profile.name, "removed": removed}, args.json)
    return 0


def policy_command(args) -> int:
    from .memory import draft_policy, transition_policy

    store = JobStore()
    try:
        if args.policy_command == "draft":
            policy = draft_policy(
                store,
                args.from_memory,
                actor=args.actor,
                reason=args.reason,
                kind=args.kind,
            )
        else:
            policy = transition_policy(
                store,
                args.policy_id,
                target="active" if args.policy_command == "activate" else "retired",
                actor=args.actor,
                reason=args.reason,
            )
        emit(policy.model_dump(mode="json"), args.json)
        return 0
    except ValueError as exc:
        emit({"error": str(exc)}, args.json)
        return 2


def blind_command(args) -> int:
    from .reviewer import (
        export_blind_workbook,
        import_blind_workbook,
        write_blind_metrics,
    )

    store = JobStore()
    job = store.get(args.job_id)
    if not job:
        emit({"error": "job not found"}, args.json)
        return 1
    try:
        if args.blind_command == "export":
            path = export_blind_workbook(job, Path(args.output).expanduser().resolve())
            emit({"job_id": job.id, "output": str(path)}, args.json)
        else:
            payload = import_blind_workbook(job, Path(args.file).expanduser().resolve())
            if args.output:
                path = write_blind_metrics(payload, Path(args.output).expanduser().resolve())
                payload["output"] = str(path)
            emit(payload, args.json)
        return 0
    except ValueError as exc:
        emit({"error": str(exc)}, args.json)
        return 2


def audit(args) -> int:
    store = JobStore()
    model_gateway = None
    try:
        if args.profile == "balanced":
            try:
                model_gateway = ensure_model_gateway(args.model_port, args.model_device)
            except Exception as exc:
                emit({"error": f"balanced model startup failed: {type(exc).__name__}: {exc}"}, args.json)
                return 2
        request = JobRequest(
            report_path=str(Path(args.report).expanduser().resolve()),
            sources_path=str(Path(args.sources).expanduser().resolve()),
            case_name=args.case_name,
            profile=args.profile,
            rule_pack=args.rule_pack,
            as_of_date=args.as_of_date,
            review_profile=args.review_profile,
        )
        job = new_job(request, store)
        store.save(job)
        try:
            job, _chunks = run_audit(job, store)
            export_standard_artifacts(job)
            store.save(job)
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            store.save(job)
            emit({"job_id": job.id, "status": job.status, "error": job.error}, args.json)
            return 1
    finally:
        # Covers request validation and snapshot failures between gateway
        # startup and audit completion, not just audit-body exceptions.
        if model_gateway and model_gateway.get("temporary") and model_gateway.get("pid"):
            _stop_temporary_gateway(int(model_gateway["pid"]))
    service = None
    if not args.no_serve:
        try:
            service = ensure_service(args.port)
        except Exception as exc:
            job.warnings.append(f"review service did not start: {type(exc).__name__}: {exc}")
            store.save(job)
    url = f"http://127.0.0.1:{args.port}/review/{job.id}?token={api_token()}"
    summary = job.summary()
    payload = {
        "job_id": job.id,
        "status": job.status,
        "profile": job.request.profile,
        "rule_pack": job.request.rule_pack,
        "summary": summary,
        "brief": build_brief(job, top=5),
        "unresolved_blockers": summary["unresolved_high"],
        "review_url": url,
        "next_step": (
            "请先查看中文审计简报。需要我继续帮你处理吗？"
            "我可以逐条解释、先处理高风险，或在你明确确认后执行修正、驳回或豁免。"
        ),
        "artifacts": job.artifacts,
    }
    if service:
        payload["service"] = service
    emit(payload, args.json)
    if args.open:
        webbrowser.open(url)
    return 0


def status(job_id: str, as_json: bool) -> int:
    job = JobStore().get(job_id)
    if not job:
        emit({"error": "job not found", "job_id": job_id}, as_json)
        return 1
    emit({"job_id": job.id, "status": job.status, "summary": job.summary(), "artifacts": job.artifacts, "error": job.error}, as_json)
    return 0


def brief(job_id: str, top: int, as_json: bool) -> int:
    job = JobStore().get(job_id)
    if not job:
        emit({"error": "job not found", "job_id": job_id}, as_json)
        return 1
    emit(build_brief(job, top=top), as_json)
    return 0


def decide(args) -> int:
    store = JobStore()
    try:
        request = DecisionRequest(
            finding_id=args.finding_id,
            action=args.action,
            replacement_text=args.replacement,
            reason=args.reason,
            selected_evidence_ids=args.evidence_id or [],
            actor=args.actor,
            risk_owner=args.risk_owner,
            waiver_expires_at=args.waiver_expires_at,
        )
        decision = request.to_decision()
    except ValidationError as exc:
        emit({"error": "invalid decision", "detail": str(exc)}, args.json)
        return 2

    def apply(job):
        finding = next((item for item in job.findings if item.id == decision.finding_id), None)
        if not finding:
            raise ValueError("finding does not belong to this job")
        valid_evidence_ids = {item.id for item in finding.evidence}
        if not set(decision.selected_evidence_ids).issubset(valid_evidence_ids):
            raise ValueError("selected evidence does not belong to this finding")
        if decision.action == "replace" and decision.replacement_text:
            passed, message = recheck_replacement(job, decision.finding_id, decision.replacement_text)
            decision.recheck_status = "passed" if passed else "failed"
            decision.recheck_message = message
        job.record_decision(decision)
        return {"decision": decision.model_dump(mode="json"), "summary": job.summary()}

    try:
        updated = store.mutate(args.job_id, apply)
    except ValueError as exc:
        emit({"error": str(exc)}, args.json)
        return 1
    if updated is None:
        emit({"error": "job not found"}, args.json)
        return 1
    if updated[0].policy_snapshot.profile_id:
        from .memory import memory_from_decision

        finding = next(item for item in updated[0].findings if item.id == decision.finding_id)
        claim = next(item for item in updated[0].claims if item.id == finding.claim_id)
        event = memory_from_decision(updated[0], finding, claim, decision)
        if event:
            store.add_memory(event)
    emit(updated[1], args.json)
    return 0


def export(args) -> int:
    store = JobStore()

    def build(job):
        if args.final:
            export_final(job)
            return dict(job.artifacts)
        return export_standard_artifacts(job)

    try:
        updated = store.mutate(args.job_id, build)
        if updated is None:
            emit({"error": "job not found"}, args.json)
            return 1
        emit(updated[1], args.json)
        return 0
    except ValueError as exc:
        emit({"error": str(exc)}, args.json)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claimledger", description="Local report evidence audit and delivery")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--deep", action="store_true")
    doctor_parser.add_argument("--json", action="store_true")
    models_parser = sub.add_parser("models")
    models_sub = models_parser.add_subparsers(dest="models_command", required=True)
    install_parser = models_sub.add_parser("install")
    install_parser.add_argument("--profile", choices=["deterministic", "lite", "balanced"], default="lite")
    install_parser.add_argument("--execute", action="store_true")
    install_parser.add_argument("--json", action="store_true")
    model_status_parser = models_sub.add_parser("status")
    model_status_parser.add_argument(
        "--profile",
        choices=["deterministic", "lite", "balanced"],
        default="lite",
    )
    model_status_parser.add_argument("--json", action="store_true")
    verify_parser = models_sub.add_parser("verify")
    verify_parser.add_argument(
        "--profile",
        choices=["deterministic", "lite", "balanced"],
        default="lite",
    )
    verify_parser.add_argument("--device", choices=["CPU", "GPU", "AUTO"], default="CPU")
    verify_parser.add_argument("--no-inference", action="store_true")
    verify_parser.add_argument("--json", action="store_true")
    model_serve_parser = models_sub.add_parser("serve")
    model_serve_parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    model_serve_parser.add_argument("--port", type=int, default=8877)
    model_serve_parser.add_argument("--device", choices=["CPU", "GPU", "AUTO"], default="CPU")
    model_serve_parser.add_argument("--json", action="store_true")
    profiles_parser = sub.add_parser("profiles")
    profiles_sub = profiles_parser.add_subparsers(dest="profiles_command", required=True)
    profile_create = profiles_sub.add_parser("create")
    profile_create.add_argument("name")
    profile_create.add_argument(
        "--role",
        choices=["generic", "audit", "operations", "consulting"],
        default="generic",
    )
    profile_create.add_argument("--json", action="store_true")
    profile_list = profiles_sub.add_parser("list")
    profile_list.add_argument("--json", action="store_true")
    profile_show = profiles_sub.add_parser("show")
    profile_show.add_argument("name")
    profile_show.add_argument("--json", action="store_true")
    profile_export = profiles_sub.add_parser("export")
    profile_export.add_argument("name")
    profile_export.add_argument("--output")
    profile_export.add_argument("--json", action="store_true")
    profile_import = profiles_sub.add_parser("import")
    profile_import.add_argument("file")
    profile_import.add_argument("--name")
    profile_import.add_argument("--json", action="store_true")
    profile_delete = profiles_sub.add_parser("delete")
    profile_delete.add_argument("name")
    profile_delete.add_argument("--json", action="store_true")
    memory_parser = sub.add_parser("memory")
    memory_sub = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_list = memory_sub.add_parser("list")
    memory_list.add_argument("--profile", required=True)
    memory_list.add_argument("--include-expired", action="store_true")
    memory_list.add_argument("--json", action="store_true")
    memory_prune = memory_sub.add_parser("prune")
    memory_prune.add_argument("--profile", required=True)
    memory_prune.add_argument("--before")
    memory_prune.add_argument("--json", action="store_true")
    policy_parser = sub.add_parser("policy")
    policy_sub = policy_parser.add_subparsers(dest="policy_command", required=True)
    policy_draft = policy_sub.add_parser("draft")
    policy_draft.add_argument("--from-memory", required=True)
    policy_draft.add_argument(
        "--kind",
        choices=["attention", "severity_floor", "terminology", "replacement_style"],
        default="attention",
    )
    policy_draft.add_argument("--actor", default="local-user")
    policy_draft.add_argument("--reason", required=True)
    policy_draft.add_argument("--json", action="store_true")
    for action in ("activate", "retire"):
        policy_transition = policy_sub.add_parser(action)
        policy_transition.add_argument("policy_id")
        policy_transition.add_argument("--actor", default="local-user")
        policy_transition.add_argument("--reason", required=True)
        policy_transition.add_argument("--json", action="store_true")
    blind_parser = sub.add_parser("blind")
    blind_sub = blind_parser.add_subparsers(dest="blind_command", required=True)
    blind_export = blind_sub.add_parser("export")
    blind_export.add_argument("job_id")
    blind_export.add_argument("--output", required=True)
    blind_export.add_argument("--json", action="store_true")
    blind_import = blind_sub.add_parser("import")
    blind_import.add_argument("job_id")
    blind_import.add_argument("--file", required=True)
    blind_import.add_argument("--output")
    blind_import.add_argument("--json", action="store_true")
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--daemon", action="store_true")
    serve_parser.add_argument("--json", action="store_true")
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--report", required=True)
    audit_parser.add_argument("--sources", required=True)
    audit_parser.add_argument("--case-name", default="claimledger-audit")
    audit_parser.add_argument("--profile", choices=["deterministic", "lite", "balanced"], default="lite")
    audit_parser.add_argument(
        "--rule-pack",
        choices=["generic-zh", "procurement-zh", "operations-zh", "consulting-zh", "lithium-demo"],
        default="generic-zh",
    )
    audit_parser.add_argument("--as-of-date", default=__import__("datetime").date.today().isoformat())
    audit_parser.add_argument("--review-profile")
    audit_parser.add_argument("--port", type=int, default=8765)
    audit_parser.add_argument("--model-port", type=int, default=8877)
    audit_parser.add_argument("--model-device", choices=["CPU", "GPU", "AUTO"], default="CPU")
    audit_parser.add_argument("--no-serve", action="store_true")
    audit_parser.add_argument("--open", action="store_true")
    audit_parser.add_argument("--json", action="store_true")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("job_id")
    status_parser.add_argument("--json", action="store_true")
    brief_parser = sub.add_parser(
        "brief",
        help="输出供 Qoder 和人工复核使用的中文审计简报",
    )
    brief_parser.add_argument("job_id")
    brief_parser.add_argument("--top", type=int, default=5)
    brief_parser.add_argument("--json", action="store_true")
    decision_parser = sub.add_parser("decide")
    decision_parser.add_argument("job_id")
    decision_parser.add_argument("finding_id")
    decision_parser.add_argument("--action", choices=["accept", "reject", "replace", "waive"], required=True)
    decision_parser.add_argument("--replacement")
    decision_parser.add_argument("--reason")
    decision_parser.add_argument("--evidence-id", action="append")
    decision_parser.add_argument("--actor", default="local-user")
    decision_parser.add_argument("--risk-owner")
    decision_parser.add_argument("--waiver-expires-at")
    decision_parser.add_argument("--json", action="store_true")
    export_parser = sub.add_parser("export")
    export_parser.add_argument("job_id")
    export_parser.add_argument("--annotated", action="store_true")
    export_parser.add_argument("--ledger", action="store_true")
    export_parser.add_argument("--final", action="store_true")
    export_parser.add_argument("--json", action="store_true")
    demo_parser = sub.add_parser("demo")
    demo_parser.add_argument("--output", required=True)
    demo_parser.add_argument(
        "--scenario",
        choices=["procurement", "lithium", "operations", "consulting", "golden-v2"],
        default="procurement",
    )
    demo_parser.add_argument("--json", action="store_true")
    benchmark_parser = sub.add_parser("benchmark")
    benchmark_parser.add_argument("--dataset", required=True)
    benchmark_parser.add_argument("--output")
    benchmark_parser.add_argument("--export-cases", action="store_true")
    benchmark_parser.add_argument("--json", action="store_true")
    return parser


def _health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/v1/health"


def ensure_service(port: int = 8765) -> dict:
    import httpx

    url = _health_url(port)
    try:
        response = httpx.get(url, timeout=1.0, trust_env=False)
        if response.status_code == 200:
            return {"status": "already_running", "health_url": url}
    except Exception:
        pass
    service_dir = ensure_private_dir(jobs_dir().parent / "service")
    rotate_api_token()
    log_path = service_dir / f"uvicorn-{port}.log"
    log_handle = log_path.open("ab")
    log_path.chmod(0o600)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "claimledger.service:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        cwd=str(skill_root()),
        env={**os.environ, "PYTHONPATH": str(skill_root() / "src")},
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    for _ in range(40):
        if process.poll() is not None:
            raise RuntimeError(f"review service exited; inspect {log_path}")
        try:
            response = httpx.get(url, timeout=1.0, trust_env=False)
            if response.status_code == 200:
                pid_path = service_dir / f"uvicorn-{port}.pid"
                pid_path.write_text(str(process.pid), encoding="utf-8")
                ensure_private_file(pid_path)
                return {"status": "started", "pid": process.pid, "health_url": url, "log": str(log_path)}
        except Exception:
            time.sleep(0.15)
    process.terminate()
    raise RuntimeError(f"review service did not become healthy; inspect {log_path}")


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "doctor":
        code = doctor(args.json, args.deep)
    elif args.command == "models":
        if args.models_command == "install":
            code = install_models(args.profile, args.execute, args.json)
        elif args.models_command == "status":
            emit(model_status(args.profile), args.json)
            code = 0
        elif args.models_command == "verify":
            result = verify_models(
                args.profile,
                args.device,
                run_inference=not args.no_inference,
            )
            emit(result, args.json)
            code = 0 if result["ok"] else 2
        else:
            rotate_model_api_token()
            os.environ["CLAIMLEDGER_MODEL_DEVICE"] = args.device
            uvicorn.run(
                "claimledger.model_gateway:app",
                host=args.host,
                port=args.port,
                reload=False,
                access_log=False,
            )
            code = 0
    elif args.command == "profiles":
        code = profiles_command(args)
    elif args.command == "memory":
        code = memory_command(args)
    elif args.command == "policy":
        code = policy_command(args)
    elif args.command == "blind":
        code = blind_command(args)
    elif args.command == "serve":
        if args.daemon:
            emit(ensure_service(args.port), args.json)
        else:
            rotate_api_token()
            uvicorn.run(
                "claimledger.service:app",
                host=args.host,
                port=args.port,
                reload=False,
                access_log=False,
            )
        code = 0
    elif args.command == "audit":
        code = audit(args)
    elif args.command == "status":
        code = status(args.job_id, args.json)
    elif args.command == "brief":
        code = brief(args.job_id, args.top, args.json)
    elif args.command == "decide":
        code = decide(args)
    elif args.command == "export":
        code = export(args)
    elif args.command == "benchmark":
        result = run_benchmark(Path(args.dataset), export_cases=args.export_cases)
        if args.output:
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            ensure_private_file(output)
            result = {**result, "output": str(output)}
        emit(result, args.json)
        code = 0
    else:
        emit(create_demo(Path(args.output).expanduser().resolve(), args.scenario), args.json)
        code = 0
    raise SystemExit(code)


if __name__ == "__main__":
    main()
