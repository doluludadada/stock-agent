"""
The backup steps of frontend/docs/deployment.md, run as written against a stand-in for /srv: the archives hold the
accounts key and the database dumps, so they land outside the checkout, in a folder and in files only their owner reads.
"""

import re
import subprocess
from pathlib import Path

DEPLOYMENT = Path(__file__).resolve().parents[2] / "frontend" / "docs" / "deployment.md"


def backup_commands() -> str:
    """The commands of step 2 of "Back up the site", as the guide prints them."""
    section = DEPLOYMENT.read_text(encoding="utf-8").split("### Back up the site")[1].split("\n### ")[0]
    blocks = re.findall(r"```bash\n(.*?)```", section, flags=re.DOTALL)
    return "\n".join(line.strip() for line in blocks[1].splitlines())


def test_the_documented_backup_writes_only_owner_readable_archives_outside_the_checkout(tmp_path: Path) -> None:
    server, checkout = tmp_path / "srv", tmp_path / "checkout"
    (server / "stock-agent-state" / "secrets").mkdir(parents=True)
    (server / "stock-agent-state" / "secrets" / "accounts.key").write_text("key")
    (server / "stock-agent-state" / "postgres").mkdir()
    checkout.mkdir()
    (checkout / ".env").write_text("DB_PASSWORD=secret\n")
    before = sorted(path.name for path in checkout.iterdir())
    commands = backup_commands().replace("sudo ", "").replace("/srv", str(server))

    subprocess.run(["bash", "-c", f"umask 022\n{commands}"], cwd=checkout, check=True)

    backups = server / "stock-agent-backups"
    written = sorted(backups.iterdir())
    assert sorted(path.name for path in checkout.iterdir()) == before
    assert backups.stat().st_mode & 0o777 == 0o700
    assert len(written) == 2 and all(path.stat().st_mode & 0o777 == 0o600 for path in written)
