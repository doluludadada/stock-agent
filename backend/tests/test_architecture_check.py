from pathlib import Path

import architecture_check
import pytest

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND / "tests" / "fixtures" / "architecture"

# Every (file, line) the rule must report in its failing example; a line reported twice is listed twice.
EXPECTED_FAILURES: dict[str, list[tuple[str, int]]] = {
    "LAYER": [
        ("a_domain/model/order.py", 3),
        ("a_domain/model/order.py", 4),
        ("a_domain/model/order.py", 5),
        ("a_domain/rules/discount.py", 1),
        ("b_application/use_cases/place_order.py", 1),
        ("b_application/use_cases/place_order.py", 3),
        ("c_infrastructure/database/order_repository.py", 5),
    ],
    "MODEL-ONE-CLASS": [
        ("a_domain/model/order/order.py", 10),
        ("a_domain/model/order/order.py", 15),
        ("a_domain/model/order/totals.py", 1),
    ],
    "ERRORS-LOCATION": [("a_domain/model/order.py", 4), ("a_domain/rules/parsing.py", 1), ("a_domain/rules/parsing.py", 5)],
    "ENUM-STR": [
        ("a_domain/types/enums.py", 5),
        ("a_domain/types/enums.py", 9),
        ("a_domain/types/enums.py", 13),
        ("a_domain/types/enums.py", 17),
    ],
    "PORT-PROTOCOL": [
        ("a_domain/ports/market/news_provider.py", 4),
        ("a_domain/ports/market/price_provider.py", 8),
        ("a_domain/ports/market/price_provider.py", 8),
        ("a_domain/ports/market/price_provider.py", 12),
        ("a_domain/ports/market/price_provider.py", 12),
        ("a_domain/ports/system/clock.py", 5),
    ],
    "RULE-APPLY": [
        ("a_domain/rules/shipping.py", 11),
        ("a_domain/rules/shipping.py", 15),
        ("a_domain/rules/shipping.py", 19),
        ("a_domain/rules/shipping.py", 21),
    ],
    "USECASE-EXECUTE": [
        ("b_application/use_cases/order/place_order.py", 11),
        ("b_application/use_cases/order/place_order.py", 14),
        ("b_application/use_cases/order/place_order.py", 17),
        ("b_application/use_cases/order/place_order.py", 21),
        ("b_application/use_cases/order/refund.py", 1),
        ("b_application/use_cases/order/refund.py", 2),
        ("b_application/use_cases/order/refund.py", 3),
        ("b_application/use_cases/order/refund.py", 6),
        ("b_application/use_cases/order/refund.py", 11),
    ],
    "ONE-PIPELINE": [
        ("b_application/pipeline.py", 6),
        ("b_application/schemas/pipeline_status.py", 1),
        ("b_application/schemas/status.py", 5),
        ("b_application/valuation_pipeline.py", 1),
        ("b_application/workflows.py", 1),
    ],
    "SETTINGS-LOCATION": [("b_application/schemas/config.py", 9), ("c_infrastructure/technical/settings.py", 4)],
    "INFRA-OVERRIDE": [
        ("c_infrastructure/market/price_adapter.py", 14),
        ("c_infrastructure/market/price_adapter.py", 17),
        ("c_infrastructure/market/price_adapter.py", 20),
        ("c_infrastructure/market/price_adapter.py", 23),
        ("c_infrastructure/market/price_adapter.py", 28),
        ("c_infrastructure/market/quote_parser.py", 1),
    ],
    "FACTORY-ONLY": [
        ("b_application/pipeline.py", 6),
        ("d_presentation/container.py", 5),
        ("d_presentation/web/routers/orders.py", 8),
        ("d_presentation/web/routers/orders.py", 9),
        ("d_presentation/web/routers/orders.py", 10),
        ("d_presentation/web/routers/orders.py", 11),
    ],
    "PRESENTATION-DECIDES-NOTHING": [
        ("d_presentation/cli/menu.py", 1),
        ("d_presentation/cli/menu.py", 7),
        ("d_presentation/cli/menu.py", 8),
        ("d_presentation/web/routers/orders.py", 1),
        ("d_presentation/web/routers/orders.py", 11),
        ("d_presentation/web/schemas.py", 7),
    ],
    "STRATEGY-FROM-SETTINGS": [
        ("b_application/use_cases/scan/nightly_scan.py", 6),
        ("c_infrastructure/technical/strategy_factory.py", 7),
        ("c_infrastructure/technical/strategy_factory.py", 9),
    ],
    "FUNC-LENGTH": [("module.py", 1), ("module.py", 35)],
    "COMPLEXITY": [("module.py", 1)],
    "NAMES": [("module.py", line) for line in (1, 4, 5, 6, 9, 10, 14, 16, 18)],
    "STORY-ID": [("module.py", 1), ("module.py", 5), ("module.py", 6), ("module.py", 12)],
    "TYPE-IGNORE": [("module.py", 5), ("module.py", 6), ("module.py", 7)],
    "ENGLISH": [("module.py", 1), ("module.py", 2), ("module.py", 6)],
    "HARDCODED-URL": [("module.py", 1), ("module.py", 5), ("module.py", 9)],
    "PARSE": [("broken.py", 1)],
    "PYRIGHT": [("adapter.py", 10)],
}


@pytest.fixture(autouse=True)
def run_from_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(BACKEND)


def reported(rule: str, tree: Path) -> list[tuple[str, int]]:
    violations = architecture_check.run_pyright([tree]) if rule == "PYRIGHT" else architecture_check.check([tree])
    return sorted(
        (Path(violation.path).resolve().relative_to(tree).as_posix(), violation.line)
        for violation in violations
        if violation.rule == rule
    )


def summary_counts(output: str) -> dict[str, int]:
    rows = output.split("Violations per rule:\n", 1)[1].splitlines()
    return {name: int(count) for name, count in (row.split() for row in rows)}


def test_every_rule_has_a_failing_and_a_passing_example() -> None:
    rules = {*architecture_check.RULES, "PARSE", "PYRIGHT"}

    assert set(EXPECTED_FAILURES) == rules
    assert all((FIXTURES / rule.lower() / kind).is_dir() for rule in rules for kind in ("fail", "pass"))


@pytest.mark.parametrize("rule", sorted(EXPECTED_FAILURES))
def test_rule_reports_every_violation_in_its_failing_example(rule: str) -> None:
    assert reported(rule, FIXTURES / rule.lower() / "fail") == sorted(EXPECTED_FAILURES[rule])


@pytest.mark.parametrize("rule", sorted(EXPECTED_FAILURES))
def test_rule_reports_nothing_in_its_passing_example(rule: str) -> None:
    assert reported(rule, FIXTURES / rule.lower() / "pass") == []


def test_project_shaped_like_the_guide_passes_every_rule(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = architecture_check.main([str(FIXTURES / "clean")])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.startswith("\nViolations per rule:\n")
    assert set(summary_counts(output).values()) == {0}


def test_cli_prints_one_line_per_violation_and_a_count_per_rule_then_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = architecture_check.main(["tests/fixtures/architecture/type-ignore/fail"])
    output = capsys.readouterr().out
    counts = summary_counts(output)

    assert exit_code == 1
    assert [line.split(" ", 2)[:2] for line in output.splitlines()[:3]] == [
        ["TYPE-IGNORE", "tests/fixtures/architecture/type-ignore/fail/module.py:5"],
        ["TYPE-IGNORE", "tests/fixtures/architecture/type-ignore/fail/module.py:6"],
        ["TYPE-IGNORE", "tests/fixtures/architecture/type-ignore/fail/module.py:7"],
    ]
    assert set(counts) == {*architecture_check.RULES, "PARSE", "TOTAL"}
    assert counts["TYPE-IGNORE"] == 3
    assert counts["TOTAL"] == 3


def test_cli_rejects_a_path_that_does_not_exist() -> None:
    with pytest.raises(SystemExit) as exit_info:
        architecture_check.main(["tests/fixtures/architecture/no-such-folder"])

    assert exit_info.value.code == 2
