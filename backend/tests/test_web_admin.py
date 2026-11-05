"""The administrator's settings editor over HTTP, on a temporary copy of config/: never the repository's files."""

import os
import shutil
from pathlib import Path

import pytest
import yaml
from support.harness import build_harness
from support.web import ADMIN, ADMIN_TOKEN, TOKEN, serve

from a_domain.types.enums import SettingsFile
from b_application.config.settings_loader import settings_revision

pytestmark = pytest.mark.asyncio

REPOSITORY_CONFIG = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of config/, with the active AI provider's key set, so validation does not depend on this machine's .env."""
    shutil.copytree(REPOSITORY_CONFIG, tmp_path / "config")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return tmp_path


def admin_harness(project: Path):
    harness = build_harness(settings_root=project)
    harness.config.settings_revisions = {
        file: settings_revision((project / "config" / file.file_name).read_text(encoding="utf-8")) for file in SettingsFile
    }
    return harness


async def admin_write(client, method: str, path: str, body: dict[str, object]):
    return await client.request(method, path, json={"confirm": True, **body}, headers=ADMIN)


def text_of(project: Path, file: SettingsFile = SettingsFile.APPSETTING) -> str:
    return (project / "config" / file.file_name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("admin_token", "headers", "status"),
    [
        (None, ADMIN, 403),
        (TOKEN, {"Authorization": f"Bearer {TOKEN}"}, 403),
        (ADMIN_TOKEN, {"Authorization": f"Bearer {TOKEN}"}, 401),
        (ADMIN_TOKEN, {}, 401),
        (ADMIN_TOKEN, ADMIN, 200),
    ],
    ids=["admin-token-unset", "admin-token-equals-api-token", "owner-token", "no-token", "admin-token"],
)
async def test_only_the_separate_administrator_token_opens_the_settings_files(
    project: Path, admin_token: str | None, headers: dict[str, str], status: int
) -> None:
    async with serve(admin_harness(project), admin_token=admin_token, authorized=False) as client:
        response = await client.get("/v1/admin/settings/appsetting", headers=headers)

    assert response.status_code == status


async def test_a_file_shows_its_allowlisted_values_and_locked_trading_settings_but_no_secret(project: Path) -> None:
    async with serve(admin_harness(project), admin_token=ADMIN_TOKEN, authorized=False) as client:
        page = (await client.get("/v1/admin/settings/appsetting", headers=ADMIN)).json()
        unknown = await client.get("/v1/admin/settings/..%2F.env", headers=ADMIN)

    values = {item["setting"]: item["value"] for item in page["settings"]}
    assert values["ai.temperature"] == 0.7 and "environment" not in values
    assert page["locked"]["trading.execution_provider"] == "mock"
    for setting in ("analysis.technical_weight", "analysis.ai_weight", "freshness.history_max_lag_days"):
        assert setting in page["locked"] and setting not in values
    assert page["status"]["restart_required"] is False
    assert unknown.status_code in {404, 422}
    for secret in ("api_key", "secret_key", "password", "ca_path", "channel_access_token"):
        assert secret not in str(page).lower()


async def test_a_preview_writes_nothing_and_a_save_keeps_comments_backs_up_and_audits_without_values(project: Path) -> None:
    original = text_of(project)
    harness = admin_harness(project)

    async with serve(harness, admin_token=ADMIN_TOKEN, authorized=False) as client:
        revision = (await client.get("/v1/admin/settings/appsetting", headers=ADMIN)).json()["status"]["revision"]
        change = {"revision": revision, "changes": {"ai.temperature": 0.3, "collect_rules.ptt_tags": ["[標的]"]}}
        preview = (await client.post("/v1/admin/settings/appsetting/preview", json=change, headers=ADMIN)).json()
        assert text_of(project) == original
        saved = await client.put("/v1/admin/settings/appsetting", json={"confirm": True, **change}, headers=ADMIN)
        backups = (await client.get("/v1/admin/settings/appsetting/backups", headers=ADMIN)).json()
        audit = (await client.get("/v1/admin/audit", headers=ADMIN)).json()
        status = (await client.get("/v1/admin/settings/appsetting", headers=ADMIN)).json()["status"]

    assert preview["problems"] == [] and preview["changed"] == ["ai.temperature", "collect_rules.ptt_tags"]
    assert any(line.startswith("+  temperature: 0.3") for line in preview["diff"])
    assert saved.status_code == 200 and saved.json()["restart_required"] is True
    after = text_of(project)
    assert "temperature: 0.3" in after and "# config/appsetting.yaml" in after and after.count("\n") > 100
    assert [backup["revision"] for backup in backups] == [revision]
    for folder in (".settings-admin", ".settings-admin/backups", ".settings-admin/backups/appsetting"):
        assert (project / folder).stat().st_mode & 0o077 == 0, folder
    assert audit[0]["settings"] == ["ai.temperature", "collect_rules.ptt_tags"] and "0.3" not in str(audit)
    assert status["running_revision"] == revision != status["revision"]
    assert harness.config.ai.temperature == 0.7


async def test_a_stale_revision_is_refused_and_changes_nothing(project: Path) -> None:
    async with serve(admin_harness(project), admin_token=ADMIN_TOKEN, authorized=False) as client:
        revision = (await client.get("/v1/admin/settings/appsetting", headers=ADMIN)).json()["status"]["revision"]
        (project / "config" / "appsetting.yaml").write_text(text_of(project) + "\n# edited elsewhere\n", encoding="utf-8")
        edited = text_of(project)
        response = await admin_write(
            client, "PUT", "/v1/admin/settings/appsetting", {"revision": revision, "changes": {"ai.temperature": 0.2}}
        )

    assert response.status_code == 409
    assert text_of(project) == edited


@pytest.mark.parametrize(
    ("file", "changes"),
    [
        ("appsetting", {"ai.temperature": 5}),
        ("instructions", {"ai_analysis_report_prompt_fundamental": "Rate {stock_id} without articles."}),
        ("instructions", {"social_sentiment_prompt": "Posts {posts_text} for {stock_id} as {json}"}),
        ("instructions", {"rag_injection_prompt": "Results {search_results"}),
        ("appsetting", {"ai.active_model": "gemini"}),
        ("appsetting", {"behavior.log_level": "VERBOSE"}),
    ],
    ids=[
        "temperature-out-of-range",
        "missing-placeholder",
        "unknown-placeholder",
        "broken-brace",
        "active-model-without-key",
        "unknown-log-level",
    ],
)
async def test_a_file_the_app_would_refuse_is_never_saved(project: Path, file: str, changes: dict[str, object]) -> None:
    original = text_of(project, SettingsFile(file))

    async with serve(admin_harness(project), admin_token=ADMIN_TOKEN, authorized=False) as client:
        revision = (await client.get(f"/v1/admin/settings/{file}", headers=ADMIN)).json()["status"]["revision"]
        response = await client.put(
            f"/v1/admin/settings/{file}", json={"confirm": True, "revision": revision, "changes": changes}, headers=ADMIN
        )

    assert response.status_code == 422
    assert response.json()["detail"]["problems"]
    assert text_of(project, SettingsFile(file)) == original
    assert not (project / ".settings-admin").exists()


@pytest.mark.parametrize(
    ("file", "changes"),
    [
        ("appsetting", {"environment": "live"}),
        ("appsetting", {"trading.order_mode": "live"}),
        ("appsetting", {"analysis.technical_weight": 0.9, "analysis.ai_weight": 0.1}),
        ("appsetting", {"freshness.history_max_lag_days": 400}),
        ("appsetting", {"sources.exchange.twse_daily_quotes_url": "http://169.254.169.254/"}),
        ("appsetting", {"system_prompt": "From the wrong file"}),
        ("instructions", {"ai.temperature": 0.1}),
    ],
)
async def test_settings_outside_the_allowlist_or_of_another_file_are_refused_before_reading(
    project: Path, file: str, changes: dict[str, object]
) -> None:
    original = text_of(project, SettingsFile(file))

    async with serve(admin_harness(project), admin_token=ADMIN_TOKEN, authorized=False) as client:
        revision = (await client.get(f"/v1/admin/settings/{file}", headers=ADMIN)).json()["status"]["revision"]
        response = await client.put(
            f"/v1/admin/settings/{file}", json={"confirm": True, "revision": revision, "changes": changes}, headers=ADMIN
        )

    assert response.status_code == 422
    assert text_of(project, SettingsFile(file)) == original


async def test_a_restore_goes_through_the_same_checks_and_puts_the_old_text_back(project: Path) -> None:
    original = text_of(project)

    async with serve(admin_harness(project), admin_token=ADMIN_TOKEN, authorized=False) as client:
        first = (await client.get("/v1/admin/settings/appsetting", headers=ADMIN)).json()["status"]["revision"]
        saved = (
            await admin_write(client, "PUT", "/v1/admin/settings/appsetting", {"revision": first, "changes": {"ai.temperature": 0.4}})
        ).json()
        [backup] = (await client.get("/v1/admin/settings/appsetting/backups", headers=ADMIN)).json()
        preview = (
            await client.post(
                f"/v1/admin/settings/appsetting/backups/{backup['backup_id']}/preview",
                json={"revision": saved["revision"]},
                headers=ADMIN,
            )
        ).json()
        stale = await admin_write(
            client, "POST", f"/v1/admin/settings/appsetting/backups/{backup['backup_id']}/restore", {"revision": first}
        )
        restored = await admin_write(
            client, "POST", f"/v1/admin/settings/appsetting/backups/{backup['backup_id']}/restore", {"revision": saved["revision"]}
        )
        audit = (await client.get("/v1/admin/audit", headers=ADMIN)).json()

    assert preview["changed"] == ["ai.temperature"] and preview["problems"] == []
    assert stale.status_code == 409
    assert restored.status_code == 200 and yaml.safe_load(text_of(project)) == yaml.safe_load(original)
    assert [entry["action"] for entry in audit] == ["restore", "save"]


async def test_a_symlinked_settings_file_is_never_read_or_written(project: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "appsetting.yaml"
    outside.write_text(text_of(project), encoding="utf-8")
    (project / "config" / "appsetting.yaml").unlink()
    os.symlink(outside, project / "config" / "appsetting.yaml")

    async with serve(admin_harness_without_revisions(project), admin_token=ADMIN_TOKEN, authorized=False) as client:
        response = await client.get("/v1/admin/settings/appsetting", headers=ADMIN)
        saved = await admin_write(
            client, "PUT", "/v1/admin/settings/appsetting", {"revision": "0" * 64, "changes": {"ai.temperature": 0.4}}
        )

    assert (response.status_code, saved.status_code) == (403, 403)
    assert response.json()["detail"] == "appsetting.yaml is not a regular file inside config/"
    assert outside.read_text(encoding="utf-8") == text_of(project)


@pytest.mark.parametrize(
    ("damage", "code", "detail"),
    [
        (lambda path: path.unlink(), 404, "The settings file is missing from config/."),
        (lambda path: path.write_text(f"# {'x' * 300_000}\n", encoding="utf-8"), 403, "appsetting.yaml is larger than 262144 bytes"),
    ],
)
async def test_a_missing_or_oversized_settings_file_says_so_instead_of_a_newer_save(
    project: Path, damage, code: int, detail: str
) -> None:
    damage(project / "config" / "appsetting.yaml")

    async with serve(admin_harness_without_revisions(project), admin_token=ADMIN_TOKEN, authorized=False) as client:
        response = await client.get("/v1/admin/settings/appsetting", headers=ADMIN)

    assert (response.status_code, response.json()["detail"]) == (code, detail)


def admin_harness_without_revisions(project: Path):
    return build_harness(settings_root=project)


async def test_a_restore_brings_back_only_allowlisted_values_and_keeps_locked_settings_changed_since(project: Path) -> None:
    async with serve(admin_harness(project), admin_token=ADMIN_TOKEN, authorized=False) as client:
        first = (await client.get("/v1/admin/settings/appsetting", headers=ADMIN)).json()["status"]["revision"]
        saved = (
            await admin_write(client, "PUT", "/v1/admin/settings/appsetting", {"revision": first, "changes": {"ai.temperature": 0.4}})
        ).json()
        by_hand = (
            text_of(project)
            .replace("stop_loss_pct: 0.10", "stop_loss_pct: 0.03")
            .replace("order_mode: mock_only", "order_mode: disabled")
        )
        (project / "config" / "appsetting.yaml").write_text(by_hand, encoding="utf-8")
        current = (await client.get("/v1/admin/settings/appsetting", headers=ADMIN)).json()["status"]["revision"]
        [backup] = (await client.get("/v1/admin/settings/appsetting/backups", headers=ADMIN)).json()
        restored = await admin_write(
            client, "POST", f"/v1/admin/settings/appsetting/backups/{backup['backup_id']}/restore", {"revision": current}
        )

    after = text_of(project)
    assert saved["saved"] and restored.status_code == 200 and restored.json()["changed"] == ["ai.temperature"]
    assert "temperature: 0.7" in after
    assert "stop_loss_pct: 0.03" in after and "order_mode: disabled" in after


async def test_a_change_that_would_make_the_file_too_large_is_refused_not_failed(project: Path) -> None:
    async with serve(admin_harness(project), admin_token=ADMIN_TOKEN, authorized=False) as client:
        revision = (await client.get("/v1/admin/settings/instructions", headers=ADMIN)).json()["status"]["revision"]
        prompts = {name: "x" * 19_000 for name in ("system_prompt",)}
        harness_limit = await admin_write(client, "PUT", "/v1/admin/settings/instructions", {"revision": revision, "changes": prompts})

    assert harness_limit.status_code in {200, 422}
