from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from claimledger.config import rotate_api_token
from claimledger.demo import create_demo
from claimledger.engine import new_job, run_audit
from claimledger.exporters import export_standard_artifacts
from claimledger.models import JobRequest
from claimledger.service import create_app
from claimledger.storage import JobStore


def test_health_and_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    app = create_app(JobStore(tmp_path / "jobs.sqlite3"))
    client = TestClient(app)
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/jobs/missing").status_code == 401
    assert client.get(f"/api/v1/jobs/missing?token={app.state.token}").status_code == 404


def test_service_bootstrap_token_rotates_between_service_starts(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    first = create_app(JobStore(tmp_path / "first.sqlite3"))
    first_token = first.state.token

    rotated = rotate_api_token()
    second = create_app(JobStore(tmp_path / "second.sqlite3"))
    assert rotated == second.state.token
    assert second.state.token != first_token

    client = TestClient(second)
    client.cookies.set("claimledger_session", first_token)
    assert client.get("/api/v1/jobs/missing").status_code == 401
    assert client.get(
        "/api/v1/jobs/missing",
        headers={"Authorization": f"Bearer {second.state.token}"},
    ).status_code == 404


def test_review_links_open_hash_verified_source_locations(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    demo = create_demo(tmp_path / "demo")
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = new_job(
        JobRequest(
            report_path=demo["report"],
            sources_path=demo["sources"],
            case_name="source-jump",
            rule_pack="lithium-demo",
        )
    )
    job, _ = run_audit(job)
    store.save(job)
    app = create_app(store)
    client = TestClient(app)
    token = app.state.token

    bootstrap = client.get(f"/review/{job.id}?token={token}", follow_redirects=False)
    assert bootstrap.status_code == 303
    assert bootstrap.headers["location"] == f"/review/{job.id}"
    assert "HttpOnly" in bootstrap.headers["set-cookie"]
    assert "SameSite=strict" in bootstrap.headers["set-cookie"]

    review = client.get(f"/review/{job.id}")
    assert review.status_code == 200
    assert "打开原始证据定位" in review.text
    assert "打开报告原文定位" in review.text
    assert "ClaimLedger 可信交付台" in review.text
    assert "本地离线" in review.text
    assert f'id="{job.findings[0].id}"' in review.text
    assert 'id="review-modal"' in review.text
    assert "修正内容只有复验通过后才会解除交付阻断" in review.text
    assert "prompt(" not in review.text
    assert "@media(prefers-color-scheme:dark)" in review.text
    assert token not in review.text
    assert "?token=" not in review.text
    assert "data-token=" not in review.text

    finding = job.findings[0]
    evidence = finding.evidence[0]
    evidence_view = client.get(f"/review/{job.id}/evidence/{evidence.id}")
    assert evidence_view.status_code == 200
    assert evidence.file_name in evidence_view.text
    report_view = client.get(f"/review/{job.id}/report/{finding.id}")
    assert report_view.status_code == 200
    assert "报告原文" in report_view.text
    raw = client.get(f"/review/{job.id}/evidence/{evidence.id}/raw")
    assert raw.status_code == 200
    assert raw.content
    assert TestClient(app).get(f"/review/{job.id}/evidence/{evidence.id}/raw").status_code == 401

    evidence.file_hash = "0" * 64
    store.save(job)
    changed = client.get(f"/review/{job.id}/evidence/{evidence.id}/raw")
    assert changed.status_code == 404


def test_decisions_are_scoped_and_accept_does_not_unlock_high_risk(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    demo = create_demo(tmp_path / "demo")
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = new_job(
        JobRequest(
            report_path=demo["report"],
            sources_path=demo["sources"],
            case_name="decision-contract",
            rule_pack="lithium-demo",
        )
    )
    job, _ = run_audit(job)
    store.save(job)
    app = create_app(store)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    finding = next(item for item in job.findings if item.severity == "high")
    unresolved_before = job.summary()["unresolved_high"]

    invalid = client.post(
        f"/api/v1/jobs/{job.id}/decisions",
        headers=headers,
        json={
            "finding_id": finding.id,
            "action": "accept",
            "selected_evidence_ids": ["evidence-from-another-finding"],
        },
    )
    assert invalid.status_code == 400

    accepted = client.post(
        f"/api/v1/jobs/{job.id}/decisions",
        headers=headers,
        json={"finding_id": finding.id, "action": "accept"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["summary"]["unresolved_high"] == unresolved_before

    rejected = client.post(
        f"/api/v1/jobs/{job.id}/decisions",
        headers=headers,
        json={"finding_id": finding.id, "action": "reject", "reason": "verified false positive"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["unresolved_high"] == unresolved_before - 1
    assert len(store.get(job.id).decisions) == 2


def test_profile_api_is_local_authenticated_and_deletes_dependents(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    store = JobStore(tmp_path / "jobs.sqlite3")
    app = create_app(store)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}

    assert client.get("/api/v1/profiles").status_code == 401
    created = client.post(
        "/api/v1/profiles",
        headers=headers,
        json={"name": "ops-local", "role_template": "operations"},
    )
    assert created.status_code == 200
    profile_id = created.json()["id"]
    listed = client.get("/api/v1/profiles", headers=headers)
    assert listed.json()["items"][0]["name"] == "ops-local"
    details = client.get(f"/api/v1/profiles/{profile_id}", headers=headers)
    assert details.status_code == 200
    assert details.json()["policies"] == []
    deleted = client.delete(f"/api/v1/profiles/{profile_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/profiles/{profile_id}", headers=headers).status_code == 404


def test_artifact_downloads_are_current_authenticated_hash_verified_and_whitelisted(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    demo = create_demo(tmp_path / "demo", "operations")
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = new_job(
        JobRequest(
            report_path=demo["report"],
            sources_path=demo["sources"],
            case_name="artifact-downloads",
            profile="deterministic",
            rule_pack="operations-zh",
        )
    )
    job, _ = run_audit(job)
    export_standard_artifacts(job)
    store.save(job)
    app = create_app(store)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {app.state.token}"}

    assert client.get(
        f"/api/v1/jobs/{job.id}/artifacts/annotated_report"
    ).status_code == 401
    annotated = client.get(
        f"/api/v1/jobs/{job.id}/artifacts/annotated_report",
        headers=headers,
    )
    assert annotated.status_code == 200
    assert annotated.content.startswith(b"PK")
    assert "annotated_report.docx" in annotated.headers["content-disposition"]
    manifest = client.get(
        f"/api/v1/jobs/{job.id}/artifacts/manifest",
        headers=headers,
    )
    assert manifest.status_code == 200
    assert manifest.json()["job_id"] == job.id
    assert client.get(
        f"/api/v1/jobs/{job.id}/artifacts/delivery_report",
        headers=headers,
    ).status_code == 404
    assert client.get(
        f"/api/v1/jobs/{job.id}/artifacts/not-a-real-kind",
        headers=headers,
    ).status_code == 404
    assert client.get(
        f"/api/v1/jobs/{job.id}/artifacts/%2e%2e%2fclaimledger.sqlite3",
        headers=headers,
    ).status_code != 200

    path = Path(job.artifacts["annotated_report"])
    path.write_bytes(path.read_bytes() + b"tampered")
    changed = client.get(
        f"/api/v1/jobs/{job.id}/artifacts/annotated_report",
        headers=headers,
    )
    assert changed.status_code == 409
    assert "哈希发生变化" in changed.json()["detail"]


def test_review_page_shows_delivery_stages_and_disables_final_export_until_ready(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))
    demo = create_demo(tmp_path / "demo", "operations")
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = new_job(
        JobRequest(
            report_path=demo["report"],
            sources_path=demo["sources"],
            case_name="review-journey",
            profile="deterministic",
            rule_pack="operations-zh",
        )
    )
    job, _ = run_audit(job)
    export_standard_artifacts(job)
    store.save(job)
    app = create_app(store)
    client = TestClient(app)

    review = client.get(f"/review/{job.id}?token={app.state.token}")
    assert review.status_code == 200
    assert "1. 自动审计" in review.text
    assert "2. 人工复核" in review.text
    assert "3. 可信交付" in review.text
    assert "下载带批注报告" in review.text
    assert "下载证据台账" in review.text
    assert "data-export-final disabled" in review.text
