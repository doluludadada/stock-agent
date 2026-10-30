import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

IMPORT_EACH_MODULE_FIRST = """
import importlib, sys
from pathlib import Path

from sqlmodel import SQLModel

src = Path(sys.argv[1])
packages = ("a_domain", "b_application", "c_infrastructure", "d_presentation")
names = sorted(
    ".".join(path.relative_to(src).with_suffix("").parts).removesuffix(".__init__")
    for package in packages
    for path in (src / package).rglob("*.py")
)
failures = []

for name in names:
    for loaded in [loaded for loaded in sys.modules if loaded.split(".")[0] in packages]:
        del sys.modules[loaded]

    SQLModel.metadata.clear()

    try:
        importlib.import_module(name)
    except Exception as error:
        failures.append(f"{name}: {type(error).__name__}: {error}")

print("\\n".join(failures))
"""


def test_every_module_imports_when_it_is_the_first_project_module_loaded() -> None:
    """
    An import cycle stays hidden while some other module happens to load first, then breaks the one entry point that
    loads it first (main.py and the API once died this way). Each module is imported here with no project module loaded.
    """
    result = subprocess.run(
        [sys.executable, "-c", IMPORT_EACH_MODULE_FIRST, str(SRC)],
        cwd=SRC.parent,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )

    assert result.stdout.strip() == ""
