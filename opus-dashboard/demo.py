"""Render the states used for the README screenshot. All data is synthetic.

Needs a throwaway HOME containing a git repo, so the path shortens to `~/...`
and the git segment has something real to report:

    export DEMO_HOME=$(mktemp -d)
    mkdir -p "$DEMO_HOME/projects/acme-api"
    git -C "$DEMO_HOME/projects/acme-api" init -q -b main
    git -C "$DEMO_HOME/projects/acme-api" commit -q --allow-empty -m initial
    python3 demo.py
"""

import copy
import json
import os
import subprocess
import sys
import time

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "statusline.py")
HOME = os.environ.get("DEMO_HOME") or sys.exit("set DEMO_HOME first (see docstring)")
PROJECT = f"{HOME}/projects/acme-api"
now = int(time.time())

base = {
    "cwd": PROJECT,
    "session_id": "demo",
    "session_name": "refactor-auth",
    "version": "2.1.239",
    "model": {"id": "claude-opus-5", "display_name": "Opus 5 (1M context)"},
    "workspace": {"current_dir": PROJECT, "project_dir": f"{HOME}/projects",
                  "added_dirs": []},
    "output_style": {"name": "default"},
    "cost": {"total_cost_usd": 4.2718, "total_duration_ms": 9_240_000,
             "total_api_duration_ms": 640_000,
             "total_lines_added": 412, "total_lines_removed": 96},
    "context_window": {
        "total_input_tokens": 306_700, "total_output_tokens": 730,
        "context_window_size": 1_000_000, "used_percentage": 31.0,
        "current_usage": {"input_tokens": 1_900, "output_tokens": 730,
                          "cache_creation_input_tokens": 4_800,
                          "cache_read_input_tokens": 300_000}},
    "effort": {"level": "high"},
    "thinking": {"enabled": True},
    "rate_limits": {
        "five_hour": {"used_percentage": 18.0, "resets_at": now + 12_720},
        "seven_day": {"used_percentage": 41.0, "resets_at": now + 259_200}},
}

states = [("a normal session", base)]

full = copy.deepcopy(base)
full["context_window"]["used_percentage"] = 91.3
full["context_window"]["context_window_size"] = 200_000
full["rate_limits"]["five_hour"]["used_percentage"] = 94.0
full["pr"] = {"number": 482, "url": "https://example.com/pull/482",
              "review_state": "approved"}
states.append(("context filling up, PR approved", full))

api = copy.deepcopy(base)
del api["rate_limits"]
api["cost"]["total_cost_usd"] = 12.9377
states.append(("API user — no rate limits, cost only", api))

cols = str(max(40, int(os.environ.get("COLUMNS", "100")) - 3))

print()
for label, data in states:
    print(f"  \033[38;2;120;125;140m{label}\033[0m")
    p = subprocess.run(
        [sys.executable, SCRIPT], input=json.dumps(data),
        capture_output=True, text=True,
        env=dict(os.environ, HOME=HOME, COLUMNS=cols, COLORTERM="truecolor"),
    )
    for line in p.stdout.rstrip("\n").split("\n"):
        print("  " + line)
    print()
