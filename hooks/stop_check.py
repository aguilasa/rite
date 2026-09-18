"""Stop hook: when rite.toml sets [hooks].stop_check, warn if the turn left views out of sync.

Warns only (never blocks): the fix is always `rite.py sync`, which the next command runs anyway.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rite_lib import check, config  # noqa: E402
from rite_lib.model import Project  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except (json.JSONDecodeError, ValueError):
        event = {}
    try:
        cfg = config.load(start=Path(event.get("cwd") or "."))
    except config.ConfigError:
        return 0
    if not cfg["hooks"]["stop_check"]:
        return 0
    project = Project(cfg)
    errors = [f for f in check.run(project, project.live_cycles(), quick=True) if f.level == "error"]
    if errors:
        lines = [str(f) for f in errors[:10]] + ([f"... and {len(errors) - 10} more"] if len(errors) > 10 else [])
        print(json.dumps({"systemMessage": "rite check --quick found problems:\n" + "\n".join(lines)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
