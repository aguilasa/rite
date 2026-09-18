"""PreToolUse hook: block Edit/Write on paths rite.toml declares read-only or generated.

Inert (exit 0) when the project has no rite.toml, so the plugin does nothing in repositories
that did not adopt it. Exit 2 blocks the tool call and shows stderr to the model.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rite_lib import config, guard  # noqa: E402


def target_paths(tool_input: dict) -> list[str]:
    paths = [tool_input.get(k) for k in ("file_path", "notebook_path", "path")]
    return [p for p in paths if isinstance(p, str) and p]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except (json.JSONDecodeError, ValueError):
        return 0
    cwd = Path(event.get("cwd") or ".")
    try:
        cfg = config.load(start=cwd)
    except config.NoConfig:
        return 0
    except config.ConfigError as exc:
        print(f"rite guard: rite.toml is invalid, guards not enforced: {exc}", file=sys.stderr)
        return 0
    for raw in target_paths(event.get("tool_input") or {}):
        path = Path(raw)
        if not path.is_absolute():
            path = cwd / path
        verdict = guard.classify(cfg, path)
        if verdict["blocked"]:
            print(verdict["message"], file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
