from __future__ import annotations

import argparse
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from claimledger import cli
from claimledger.config import model_api_token
from claimledger.model_gateway import create_model_app


class StubRuntime:
    device = "CPU"

    def status(self):
        return {
            "device": self.device,
            "models": {"generation": "local-generation"},
            "loaded": {"generation": False, "embedding": False, "reranker": False},
            "timings_ms": {},
        }

    def generate(self, request):
        if request.model != "local-generation":
            raise ValueError("wrong model")
        return '[{"paragraph_index":0,"exact_text":"结论"}]'

    def embed(self, request):
        return [[float(index), 1.0] for index, _text in enumerate(request.input)]

    def rerank(self, request):
        return [(0, 0.9)]

    def release(self, role):
        if role not in {"generation", "embedding", "reranker", "all"}:
            raise ValueError("unknown model role")


def _client():
    client = TestClient(create_model_app(StubRuntime()))
    headers = {"Authorization": f"Bearer {model_api_token()}"}
    return client, headers


def test_model_gateway_requires_token():
    client, _headers = _client()
    assert client.get("/v3/models").status_code == 401


def test_model_gateway_contract():
    client, headers = _client()
    assert client.get("/v3/models", headers=headers).status_code == 200
    chat = client.post(
        "/v3/chat/completions",
        headers=headers,
        json={
            "model": "local-generation",
            "messages": [{"role": "user", "content": "抽取结论"}],
        },
    )
    assert chat.status_code == 200
    assert chat.json()["choices"][0]["message"]["content"].startswith("[")

    embeddings = client.post(
        "/v3/embeddings",
        headers=headers,
        json={"model": "local-embedding", "input": ["a", "b"]},
    )
    assert embeddings.status_code == 200
    assert len(embeddings.json()["data"]) == 2

    rerank = client.post(
        "/v3/rerank",
        headers=headers,
        json={
            "model": "local-reranker",
            "query": "a",
            "documents": ["a", "b"],
            "top_n": 2,
        },
    )
    assert rerank.status_code == 200
    assert rerank.json()["results"][0]["index"] == 0


def test_model_gateway_rejects_unknown_release_role():
    client, headers = _client()
    response = client.post("/v3/admin/release/cloud", headers=headers)
    assert response.status_code == 400


def _gateway_args() -> argparse.Namespace:
    return argparse.Namespace(
        profile="balanced",
        model_port=8899,
        model_device="CPU",
        report="report.docx",
        sources="evidence",
        case_name="case",
        rule_pack="generic-zh",
        as_of_date="2026-07-30",
        review_profile=None,
        no_serve=True,
        port=8765,
        open=False,
        json=True,
    )


def test_audit_stops_temporary_gateway_when_job_setup_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    stopped = []
    monkeypatch.setattr(cli, "ensure_model_gateway", lambda *a, **k: {"temporary": True, "pid": 4242})
    monkeypatch.setattr(cli, "_stop_temporary_gateway", lambda pid: stopped.append(pid))

    def failing_new_job(request, store):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(cli, "new_job", failing_new_job)
    with pytest.raises(RuntimeError, match="snapshot failed"):
        cli.audit(_gateway_args())
    assert stopped == [4242]


def test_audit_stops_temporary_gateway_after_successful_run(monkeypatch, tmp_path):
    from claimledger.models import AuditJob, JobRequest

    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    stopped = []
    monkeypatch.setattr(cli, "ensure_model_gateway", lambda *a, **k: {"temporary": True, "pid": 4242})
    monkeypatch.setattr(cli, "_stop_temporary_gateway", lambda pid: stopped.append(pid))
    job = AuditJob(
        id="job-test",
        request=JobRequest(report_path="report.docx", sources_path="evidence"),
    )
    monkeypatch.setattr(cli, "new_job", lambda request, store: job)
    monkeypatch.setattr(cli, "run_audit", lambda job, store: (job, []))
    monkeypatch.setattr(cli, "export_standard_artifacts", lambda job: None)

    assert cli.audit(_gateway_args()) == 0
    assert stopped == [4242]


def _seed_gateway_pid_file(monkeypatch, tmp_path, pid_text: str = "4242"):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    service_dir = tmp_path / "model-service"
    service_dir.mkdir(parents=True)
    pid_path = service_dir / "model-gateway-8877.pid"
    pid_path.write_text(pid_text, encoding="utf-8")
    monkeypatch.setattr(cli, "jobs_dir", lambda: tmp_path / "jobs")
    return pid_path


def test_orphaned_gateway_pid_is_detected(monkeypatch, tmp_path):
    _seed_gateway_pid_file(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli.subprocess,
        "check_output",
        lambda *a, **k: (
            " 1 /usr/bin/python -m uvicorn claimledger.model_gateway:app "
            "--host 127.0.0.1 --port 8877\n"
        ),
    )
    assert cli._read_orphaned_gateway_pid(8877) == 4242


def test_live_gateway_with_real_parent_is_not_orphaned(monkeypatch, tmp_path):
    _seed_gateway_pid_file(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli.subprocess,
        "check_output",
        lambda *a, **k: (
            " 288 /usr/bin/python -m uvicorn claimledger.model_gateway:app "
            "--host 127.0.0.1 --port 8877\n"
        ),
    )
    assert cli._read_orphaned_gateway_pid(8877) is None


def test_reused_pid_is_never_treated_as_claimledger_gateway(monkeypatch, tmp_path):
    pid_path = _seed_gateway_pid_file(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli.subprocess,
        "check_output",
        lambda *a, **k: " 1 /usr/bin/python unrelated-worker.py --port 8877\n",
    )
    assert cli._read_orphaned_gateway_pid(8877) is None
    assert not pid_path.exists()


def test_stale_pid_file_is_removed_without_touching_listener(monkeypatch, tmp_path):
    pid_path = _seed_gateway_pid_file(monkeypatch, tmp_path)

    def dead_process(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(cli.subprocess, "check_output", dead_process)
    assert cli._read_orphaned_gateway_pid(8877) is None
    assert not pid_path.exists()


def test_missing_pid_file_means_manually_started_gateway(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "jobs_dir", lambda: tmp_path / "jobs")
    assert cli._read_orphaned_gateway_pid(8877) is None


def test_ensure_gateway_reclaims_orphan_and_starts_fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    stopped = []
    popen_calls = []

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(cli, "_read_orphaned_gateway_pid", lambda port: 4242)
    monkeypatch.setattr(cli, "_stop_temporary_gateway", lambda pid: stopped.append(pid))
    monkeypatch.setattr(cli, "model_status", lambda profile: {"offline_ready": True})
    monkeypatch.setattr(cli, "rotate_model_api_token", lambda: "fresh-token")

    class FakeProcess:
        pid = 4343

        def poll(self):
            return None

    def fake_popen(*args, **kwargs):
        popen_calls.append(kwargs)
        return FakeProcess()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)

    result = cli.ensure_model_gateway(8877, "CPU")

    assert stopped == [4242]
    assert result["status"] == "started"
    assert result["temporary"] is True
    assert result["pid"] == 4343
    assert popen_calls


def test_ensure_gateway_reuses_healthy_manually_started_gateway(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(cli, "_read_orphaned_gateway_pid", lambda port: None)

    result = cli.ensure_model_gateway(8877, "CPU")
    assert result["status"] == "already_running"
    assert result["temporary"] is False


def test_gateway_startup_timeout_force_stops_process(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    stopped = []
    requests = {"count": 0}

    def unavailable(*args, **kwargs):
        requests["count"] += 1
        raise httpx.ConnectError("not ready")

    monkeypatch.setattr(httpx, "get", unavailable)
    monkeypatch.setattr(cli, "model_status", lambda profile: {"offline_ready": True})
    monkeypatch.setattr(cli, "rotate_model_api_token", lambda: "fresh-token")
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(cli, "_stop_temporary_gateway", lambda pid: stopped.append(pid))

    class FakeProcess:
        pid = 4343

        def poll(self):
            return None

    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: FakeProcess())

    with pytest.raises(RuntimeError, match="did not become healthy"):
        cli.ensure_model_gateway(8877, "CPU")

    assert requests["count"] == 101
    assert stopped == [4343]
