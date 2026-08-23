"""Render the status line against synthetic sessions, for development.

Usage: python3 preview.py
"""

import json, subprocess, time, os, sys
now = int(time.time())
base = {
  "cwd": "/home/dev/projects/acme-api",
  "session_id": "abc123", "session_name": "statusline build", "version": "2.1.239",
  "model": {"id": "claude-opus-5", "display_name": "Opus 5"},
  "workspace": {"current_dir": "/home/dev/projects/acme-api",
                "project_dir": "/home/dev/projects", "added_dirs": []},
  "output_style": {"name": "default"},
  "cost": {"total_cost_usd": 3.8421, "total_duration_ms": 5400000,
           "total_api_duration_ms": 990000, "total_lines_added": 156, "total_lines_removed": 23},
  "context_window": {"total_input_tokens": 84500, "total_output_tokens": 12400,
    "context_window_size": 1000000, "used_percentage": 8.45, "remaining_percentage": 91.55,
    "current_usage": {"input_tokens": 4200, "output_tokens": 12400,
                      "cache_creation_input_tokens": 9800, "cache_read_input_tokens": 70500}},
  "exceeds_200k_tokens": False, "fast_mode": False,
  "effort": {"level": "high"}, "thinking": {"enabled": True},
  "rate_limits": {"five_hour": {"used_percentage": 23.5, "resets_at": now + 8100},
                  "seven_day": {"used_percentage": 78.2, "resets_at": now + 320000}},
}

def run(label, data, cols=140):
    env = dict(os.environ, COLUMNS=str(cols))
    p = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "statusline.py")],
                       input=json.dumps(data), capture_output=True, text=True, env=env)
    print(f"\n\033[1m── {label}  (COLUMNS={cols})\033[0m")
    print(p.stdout.rstrip("\n"))
    if p.stderr.strip():
        print("STDERR:", p.stderr.strip())

import copy
run("typical session, subscription", base)

d = copy.deepcopy(base)
d["context_window"]["used_percentage"] = 91.3
d["context_window"]["context_window_size"] = 200000
d["rate_limits"]["five_hour"]["used_percentage"] = 96.0
run("context nearly full + 5h nearly exhausted", d)

d = copy.deepcopy(base)
del d["rate_limits"]
d["cost"]["total_cost_usd"] = 12.9377
run("API user (no rate_limits)", d)

d = copy.deepcopy(base)
d["context_window"]["current_usage"] = None
d["context_window"]["used_percentage"] = None
d["cost"] = {"total_cost_usd": 0.0, "total_duration_ms": 1200, "total_api_duration_ms": 0,
             "total_lines_added": 0, "total_lines_removed": 0}
run("fresh session / just after /compact", d)

d = copy.deepcopy(base)
d["pr"] = {"number": 1234, "url": "x", "review_state": "changes_requested"}
d["vim"] = {"mode": "INSERT"}
d["fast_mode"] = True
d["effort"] = {"level": "max"}
d["agent"] = {"name": "code-reviewer"}
d["workspace"]["git_worktree"] = "feature-xyz"
run("everything on at once", d)

run("narrow terminal", base, cols=70)
