from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import yaml

from claimledger import config
from claimledger.demo import create_demo
from claimledger.engine import load_rules, new_job, run_audit
from claimledger.models import JobRequest


SKILL_ROOT = Path(__file__).resolve().parents[1]


def test_skill_routes_ordinary_requests_to_lite_without_confusing_review_profiles():
    instructions = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "普通自然语言审计一律使用 `lite`" in instructions
    assert "用户在提问、比较或粘贴材料时提到 Balanced，不代表同意启用" in instructions
    assert "运营月报应使用运行模式 `lite` 加规则包 `operations-zh`" in instructions


def test_skill_keeps_review_in_qoder_without_automatic_professional_decisions():
    instructions = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "不要只返回复核链接" in instructions
    assert "需要我继续帮你处理吗？" in instructions
    assert "根据当前任务重新读取状态，并调用 `decide`、`status` 和 `export`" in instructions
    assert "不得自动提交专业责任决定" in instructions
    assert "修改、驳回或豁免" in instructions


def test_skill_front_screen_states_value_and_synthetic_metrics():
    instructions = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    body = instructions.split("---", 2)[-1]
    first_screen = "\n".join(body.strip().splitlines()[:20])
    assert "AI 写完以后，谁来证明它可以交付？" in first_screen
    assert "100 条结论" in first_screen
    assert "49 个植入风险" in first_screen
    assert "合成测试结果" in first_screen
    assert "真实客户数据" in first_screen


def test_qoder_widget_is_self_contained_and_sends_readable_chinese_intents():
    widget = (
        SKILL_ROOT / "assets" / "ui" / "claimledger-brief.html"
    ).read_text(encoding="utf-8")
    assert "window.__WIDGET_DATA__" in widget
    assert "window.sendToAgent(message, { submit: true })" in widget
    assert "请先复述修改前后文本、依据和影响" in widget
    assert "先按优先级解释未解决的高风险发现" in widget
    assert "http://" not in widget
    assert "https://" not in widget
    assert "fetch(" not in widget
    assert "token" not in widget.lower()
    assert "/Users/" not in widget


def test_wheel_data_files_cover_every_canonical_runtime_asset():
    project = tomllib.loads((SKILL_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    data_files = project["tool"]["setuptools"]["data-files"]
    assert data_files["share/claimledger/assets"] == [
        "assets/models.yaml",
        "assets/claimledger-icon-1024.png",
    ]
    assert data_files["share/claimledger/assets/rules"] == ["assets/rules/*.yaml"]
    assert data_files["share/claimledger/assets/profiles"] == ["assets/profiles/*.yaml"]
    assert data_files["share/claimledger/assets/ui"] == ["assets/ui/*.html"]
    assert (SKILL_ROOT / "assets" / "models.yaml").is_file()
    assert {path.name for path in (SKILL_ROOT / "assets" / "rules").glob("*.yaml")} == {
        "generic-zh.yaml",
        "procurement-zh.yaml",
        "operations-zh.yaml",
        "consulting-zh.yaml",
        "lithium-demo.yaml",
    }
    assert {path.name for path in (SKILL_ROOT / "assets" / "profiles").glob("*.yaml")} == {
        "generic.yaml",
        "audit.yaml",
        "operations.yaml",
        "consulting.yaml",
    }
    for path in (SKILL_ROOT / "assets" / "profiles").glob("*.yaml"):
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert profile["kind"] == "reviewer_memory_template"
        assert profile["execution_profile"] is None


def test_installed_wheel_asset_fallback_runs_a_real_audit(tmp_path, monkeypatch):
    installed_root = tmp_path / "prefix" / "share" / "claimledger"
    shutil.copytree(SKILL_ROOT / "assets", installed_root / "assets")
    fake_module = tmp_path / "lib" / "python3.11" / "site-packages" / "claimledger" / "config.py"
    monkeypatch.setattr(config, "__file__", str(fake_module))
    original_get_path = config.sysconfig.get_path
    monkeypatch.setattr(
        config.sysconfig,
        "get_path",
        lambda name: str(tmp_path / "prefix") if name == "data" else original_get_path(name),
    )
    monkeypatch.setenv("CLAIMLEDGER_DATA_DIR", str(tmp_path / "data"))

    assert config.skill_root() == installed_root
    assert load_rules("generic-zh")["name"] == "generic-zh"
    demo = create_demo(tmp_path / "demo", "operations")
    job = new_job(
        JobRequest(
            report_path=demo["report"],
            sources_path=demo["sources"],
            case_name="installed-wheel-smoke",
            profile="deterministic",
            rule_pack="operations-zh",
            as_of_date="2026-07-19",
        )
    )
    job, chunks = run_audit(job)
    assert job.status == "completed"
    assert job.coverage_status == "complete"
    assert chunks
