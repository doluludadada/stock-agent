"""A project folder whose settings name given ranking formulas, for the tests that switch the active formula on a live site."""

import re
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from a_domain.model.trading.ranking_formula import RankingFormula

ROOT = Path(__file__).resolve().parents[3]


def formulas_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *formulas: RankingFormula) -> Path:
    """A copy of config/ under `tmp_path` whose ranking holds `formulas` in place of the shipped ones, the first active."""
    shutil.copytree(ROOT / "config", tmp_path / "config")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ACCOUNTS_KEY", "A" * 43)
    settings = tmp_path / "config" / "appsetting.yaml"
    shipped = settings.read_text(encoding="utf-8")
    plain = [
        {**asdict(formula), "factors": [{**asdict(factor), "kind": factor.kind.value} for factor in formula.factors]}
        for formula in formulas
    ]
    start, end = shipped.index("  formulas:\n"), shipped.index("  # The revenue trend of the stock page")
    listed = "".join(f"  {line}\n" for line in yaml.safe_dump({"formulas": plain}, sort_keys=False).splitlines())
    active = re.sub(r"(?m)^  active_formula: .*$", f"  active_formula: {formulas[0].name}", shipped[:start], count=1)
    settings.write_text(active + listed + shipped[end:], encoding="utf-8")
    return tmp_path
