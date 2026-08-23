"""Render fable-meter against synthetic sessions, for the README and for
development. All data is invented.

The interesting parts of this status line are stateful — the turn timer and the
sparklines only mean anything across several invocations — so this seeds a
state file with a plausible history before rendering, rather than showing a
cold first run.

Needs a throwaway HOME with a git repo so the path shortens to `~/...` and the
git segment has something to report:

    export DEMO_HOME=$(mktemp -d)
    mkdir -p "$DEMO_HOME/projects/atlas"
    git -C "$DEMO_HOME/projects/atlas" init -q -b main
    git -C "$DEMO_HOME/projects/atlas" commit -q --allow-empty -m initial
    python3 demo.py
"""

import copy
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "statusline.py")
HOME = os.environ.get("DEMO_HOME") or sys.exit("set DEMO_HOME first (see docstring)")
PROJECT = f"{HOME}/projects/atlas"
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
now = time.time()


def seed(session_id, prompt_id, turn_age, start_cost, points):
    """Write a state file so the sparklines and turn timer have something to
    show. `points` is a list of (cost, context_tokens) oldest-first."""
    path = os.path.join(RUNTIME, f"cc-fable-meter-{session_id}.json")
    span = max(turn_age, 1)
    samples = [
        [round(now - span + i * span / max(len(points) - 1, 1), 1), c, t]
        for i, (c, t) in enumerate(points)
    ]
    with open(path, "w") as fh:
        json.dump({"prompt_id": prompt_id, "turn_started": now - turn_age,
                   "turn_start_cost": start_cost, "samples": samples}, fh)


# A turn that is partway through: cost accelerating, context climbing.
ramp = [(9.80 + 0.42 * (i ** 1.35) / 6, 180_000 + int(62_000 * math.log1p(i)))
        for i in range(14)]

base = {
    "session_id": "demo-a", "prompt_id": "turn-7",
    "session_name": "atlas-migration", "version": "2.1.239",
    "cwd": PROJECT,
    "model": {"id": "claude-fable-5", "display_name": "Fable 5"},
    "workspace": {"current_dir": PROJECT, "project_dir": f"{HOME}/projects",
                  "added_dirs": []},
    "effort": {"level": "xhigh"},
    "thinking": {"enabled": True},
    "cost": {"total_cost_usd": ramp[-1][0], "total_duration_ms": 4_920_000,
             "total_api_duration_ms": 2_180_000,
             "total_lines_added": 903, "total_lines_removed": 241},
    "context_window": {
        "total_input_tokens": ramp[-1][1], "total_output_tokens": 1_840,
        "context_window_size": 1_000_000,
        "used_percentage": ramp[-1][1] / 1_000_000 * 100,
        "current_usage": {"input_tokens": 3_100, "output_tokens": 1_840,
                          "cache_creation_input_tokens": 7_400,
                          "cache_read_input_tokens": ramp[-1][1] - 10_500}},
    "rate_limits": {
        "five_hour": {"used_percentage": 62.0, "resets_at": now + 7_500},
        "seven_day": {"used_percentage": 38.0, "resets_at": now + 291_000}},
}

states = []

a = copy.deepcopy(base)
seed("demo-a", "turn-7", 214, ramp[0][0], ramp)
states.append(("mid-turn: the timer and per-turn spend keep running", a))

b = copy.deepcopy(base)
b["session_id"] = "demo-b"
b["prompt_id"] = "turn-12"   # must match the seeded state, else the timer resets
b["effort"] = {"level": "max"}
b["context_window"]["used_percentage"] = 88.4
b["context_window"]["current_usage"]["cache_read_input_tokens"] = 878_000
b["rate_limits"]["five_hour"]["used_percentage"] = 91.0
deep = [(28.0 + i * 0.9, 500_000 + i * 29_000) for i in range(14)]
b["cost"]["total_cost_usd"] = deep[-1][0]
seed("demo-b", "turn-12", 1_042, deep[0][0], deep)
states.append(("a long turn at max effort, context filling up", b))

c = copy.deepcopy(base)
c["session_id"] = "demo-c"
c["prompt_id"] = "turn-1"
c["effort"] = {"level": "low"}
del c["rate_limits"]
c["cost"] = {"total_cost_usd": 0.06, "total_duration_ms": 14_000}
c["context_window"]["used_percentage"] = 1.2
c["context_window"]["current_usage"] = {"input_tokens": 900, "output_tokens": 40,
                                        "cache_creation_input_tokens": 11_100,
                                        "cache_read_input_tokens": 0}
seed("demo-c", "turn-1", 9, 0.0, [(0.0, 0), (0.06, 12_000)])
states.append(("a fresh turn at low effort, no history to trend yet", c))

cols = str(max(40, int(os.environ.get("COLUMNS", "110")) - 3))

print()
for label, data in states:
    print(f"  \033[38;2;120;114;108m{label}\033[0m")
    p = subprocess.run(
        [sys.executable, SCRIPT], input=json.dumps(data),
        capture_output=True, text=True,
        env=dict(os.environ, HOME=HOME, COLUMNS=cols, COLORTERM="truecolor"),
    )
    for line in p.stdout.rstrip("\n").split("\n"):
        print("  " + line)
    if p.stderr.strip():
        print("  STDERR:", p.stderr.strip())
    print()
