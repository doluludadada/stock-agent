"""A project folder whose settings name given ranking formulas, for the tests that switch the active formula on a live site."""

import shutil
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from a_domain.model.trading.ranking_formula import RankingFormula

ROOT = Path(__file__).resolve().parents[3]


def formulas_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *formulas: RankingFormula) -> Path:
    """A copy of config/ under `tmp_path` whose ranking holds `formulas` in place of the shipped ones."""
    shutil.copytree(ROOT / "config", tmp_path / "config")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    settings = tmp_path / "config" / "appsetting.yaml"
    shipped = settings.read_text(encoding="utf-8")
    plain = [
        {**asdict(formula), "factors": [{**asdict(factor), "kind": factor.kind.value} for factor in formula.factors]}
        for formula in formulas
    ]
    start, end = shipped.index("  formulas:\n"), shipped.index("  # The ranking page compares")
    listed = "".join(f"  {line}\n" for line in yaml.safe_dump({"formulas": plain}, sort_keys=False).splitlines())
    settings.write_text(shipped[:start] + listed + shipped[end:], encoding="utf-8")
    return tmp_path
