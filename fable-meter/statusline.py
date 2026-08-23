#!/usr/bin/env python3
"""fable-meter — a status line built around what makes Claude Fable 5 different.

Fable 5 is priced at $10/$50 per MTok (twice Opus 5), thinks on every turn with
no way to disable it, and can spend many minutes inside a single turn on a 1M
context window. A generic dashboard answers "what is my state"; this one answers
the two questions that actually come up while waiting on Fable:

    is it still working, and what is this costing me?

So it keeps history between invocations. Claude Code re-runs the status line on
every assistant message and on a `refreshInterval` timer, and hands over a
`prompt_id` that changes once per user turn. Sampling cost and context on each
run gives:

  * a live turn timer, and the spend attributed to the current turn
  * sparklines of spend rate and context growth, rather than bare instants

State lives in one small JSON file per session under XDG_RUNTIME_DIR.

Two rows:
  1. identity   model, effort dial, directory, git
  2. the meter  turn timer + turn cost, context with trend, spend with trend,
                rate-limit windows
"""

import json
import os
import subprocess
import sys
import time

# ------------------------------------------------------------------ config --

MAX_SAMPLES = 48          # ~24 min of history at refreshInterval 30
SPARK = "▁▂▃▄▅▆▇█"
BRAILLE = " ⡀⡄⡆⡇⣇⣧⣷⣿"   # 9 levels of fill, for the context meter
EFFORTS = ["low", "medium", "high", "xhigh", "max"]

NO_COLOR = bool(os.environ.get("NO_COLOR"))
TRUECOLOR = os.environ.get("COLORTERM", "") in ("truecolor", "24bit")

# A warm, low-key palette — deliberately distinct from opus-dashboard's violet
# so the two are never mistaken for each other at a glance.
GOLD = (232, 184, 109)
EMBER = (224, 138, 92)
ASH = (128, 122, 116)
SOOT = (86, 82, 78)
PARCH = (238, 228, 210)
INK = (28, 24, 22)
MOSS = (150, 190, 140)
RUST = (214, 106, 96)


def rgb(r, g, b, bg=False):
    if NO_COLOR:
        return ""
    if TRUECOLOR:
        return f"\033[{48 if bg else 38};2;{r};{g};{b}m"
    idx = 16 + 36 * (r * 5 // 255) + 6 * (g * 5 // 255) + (b * 5 // 255)
    return f"\033[{48 if bg else 38};5;{idx}m"


RESET = "" if NO_COLOR else "\033[0m"
BOLD = "" if NO_COLOR else "\033[1m"


def paint(text, fg=None, bg=None, bold=False):
    if NO_COLOR:
        return str(text)
    pre = (BOLD if bold else "") + (rgb(*fg) if fg else "") + (rgb(*bg, bg=True) if bg else "")
    return f"{pre}{text}{RESET}" if pre else str(text)


def heat(pct):
    """Moss -> gold -> rust. Fable's palette, not a traffic light."""
    pct = max(0.0, min(100.0, pct))
    if pct <= 55:
        t = pct / 55
        return (int(150 + t * 82), int(190 - t * 6), int(140 - t * 31))
    t = (pct - 55) / 45
    return (int(232 - t * 18), int(184 - t * 78), int(109 - t * 13))


# ------------------------------------------------------------------- state --


def state_path(session_id):
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    safe = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in "-_")[:64]
    return os.path.join(base, f"cc-fable-meter-{safe or 'default'}.json")


def load_state(path):
    try:
        with open(path) as fh:
            s = json.load(fh)
        if isinstance(s, dict) and isinstance(s.get("samples"), list):
            return s
    except (OSError, ValueError):
        pass
    return {"prompt_id": None, "turn_started": None, "turn_start_cost": None,
            "samples": []}


def save_state(path, state):
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def update_state(d, now):
    """Record this invocation and return (state, is_new_turn)."""
    path = state_path(d.get("session_id"))
    st = load_state(path)

    cost = (d.get("cost") or {}).get("total_cost_usd")
    ctx = d.get("context_window") or {}
    cur = ctx.get("current_usage") or {}
    ctx_tokens = ((cur.get("input_tokens") or 0)
                  + (cur.get("cache_creation_input_tokens") or 0)
                  + (cur.get("cache_read_input_tokens") or 0))

    pid = d.get("prompt_id")
    new_turn = pid is not None and pid != st.get("prompt_id")
    if new_turn:
        st["prompt_id"] = pid
        st["turn_started"] = now
        st["turn_start_cost"] = cost
    # /clear resets cost to 0; drop stale history rather than render a negative
    # delta or a nonsense spike.
    if cost is not None and st.get("turn_start_cost") is not None \
            and cost < st["turn_start_cost"]:
        st = {"prompt_id": pid, "turn_started": now, "turn_start_cost": cost,
              "samples": []}

    st["samples"].append([round(now, 1), cost, ctx_tokens])
    st["samples"] = st["samples"][-MAX_SAMPLES:]
    save_state(path, st)
    return st


# ---------------------------------------------------------------- visuals --


def spark(values, width=8):
    """Unicode sparkline. Flat or too-short series render as a faint floor."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return paint("·" * width, SOOT)
    vals = vals[-width:]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return paint("▁" * len(vals), SOOT)
    # One muted hue on purpose. Colouring by rank within the window made every
    # rising series end in alarm-red, which says nothing about magnitude — the
    # shape is the signal here.
    out = ""
    for v in vals:
        level = int((v - lo) / (hi - lo) * (len(SPARK) - 1))
        out += SPARK[level]
    return paint(out, GOLD)


def meter(pct, width=10):
    """Braille fill meter — denser than block bars at the same width."""
    if pct is None:
        return paint("·" * width, SOOT)
    pct = max(0.0, min(100.0, pct))
    exact = pct / 100.0 * width
    full = int(exact)
    out = ""
    for i in range(full):
        out += paint(BRAILLE[-1], heat((i + 0.5) / width * 100))
    if full < width:
        # BRAILLE[0] is a space: clamp so any non-zero remainder still shows ink.
        part = int((exact - full) * (len(BRAILLE) - 1))
        if part == 0 and pct > 0:
            part = 1
        out += paint(BRAILLE[part], heat(pct))
        out += paint("·" * (width - full - 1), SOOT)
    return out


def effort_dial(level):
    """Thinking is always on for Fable, so effort is the only real dial."""
    if not level:
        return ""
    try:
        idx = EFFORTS.index(level)
    except ValueError:
        return paint(level, GOLD)
    marks = ""
    last = len(EFFORTS) - 1
    for i in range(len(EFFORTS)):
        if i <= idx:
            # Spread 5 effort levels across 8 glyphs; naive i*2+1 overruns.
            g = SPARK[round(i / last * (len(SPARK) - 1))]
            marks += paint(g, heat(i / last * 100))
        else:
            marks += paint("▁", SOOT)
    return marks + " " + paint(level, GOLD if idx < 3 else EMBER, bold=idx >= 3)


# ---------------------------------------------------------------- format --


def tokens(n):
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def clock(seconds):
    if seconds is None or seconds < 0:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    h, m = divmod(seconds // 60, 60)
    return f"{h}h{m:02d}m"


def until(seconds):
    if seconds is None or seconds < 0:
        return "?"
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"{seconds // 86400}d{(seconds % 86400) // 3600}h"


def short_path(path, budget):
    if not path:
        return "?"
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        path = "~" + path[len(home):]
    if len(path) <= budget:
        return path
    parts = path.split(os.sep)
    if len(parts) <= 2:
        return path[-budget:]
    for i in range(1, len(parts) - 1):
        cand = os.sep.join([parts[0], "…"] + parts[i + 1:])
        if len(cand) <= budget:
            return cand
    return os.sep.join([parts[0], "…", parts[-1]])


def git_branch(cwd):
    cache = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                         f"cc-fable-git-{abs(hash(cwd)) % 10**10}.json")
    try:
        if time.time() - os.stat(cache).st_mtime < 3:
            with open(cache) as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    info = {}
    try:
        p = subprocess.run(["git", "-C", cwd, "status", "--porcelain=v2", "--branch"],
                           capture_output=True, text=True, timeout=1.0)
        if p.returncode == 0:
            dirty = 0
            for line in p.stdout.splitlines():
                if line.startswith("# branch.head "):
                    info["branch"] = line.split(" ", 2)[2]
                elif line[:1] in ("1", "2", "u", "?"):
                    dirty += 1
            info["dirty"] = dirty
    except (OSError, subprocess.SubprocessError, ValueError):
        info = {}
    try:
        with open(cache, "w") as fh:
            json.dump(info, fh)
    except OSError:
        pass
    return info


# ------------------------------------------------------------------- main --


def main():
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(paint(" fable-meter: bad JSON on stdin ", RUST))
        return

    now = time.time()
    st = update_state(d, now)
    width = max(40, int(os.environ.get("COLUMNS") or 120) - 2)
    wide = width >= 100

    # ---- row 1: identity -------------------------------------------------
    model = (d.get("model") or {}).get("display_name") or "?"
    row = [paint(f" ⟡ {model} ", INK, GOLD, bold=True)]

    dial = effort_dial((d.get("effort") or {}).get("level"))
    if dial:
        row.append(paint("effort", ASH) + " " + dial)

    ws = d.get("workspace") or {}
    cwd = ws.get("current_dir") or d.get("cwd") or ""
    row.append(paint(short_path(cwd, 38 if wide else 20), PARCH))

    g = git_branch(cwd) if cwd else {}
    if g.get("branch"):
        seg = paint(f" {g['branch']}", MOSS if not g.get("dirty") else GOLD)
        if g.get("dirty"):
            seg += paint(f" +{g['dirty']}", GOLD)
        row.append(seg)

    pr = d.get("pr") or {}
    if pr.get("number"):
        row.append(paint(f"#{pr['number']}", ASH))
    if wide and d.get("session_name"):
        row.append(paint(d["session_name"][:24], SOOT))
    print(paint("  ", SOOT).join(row))

    # ---- row 2: the meter ------------------------------------------------
    row = []
    cost = (d.get("cost") or {}).get("total_cost_usd")

    # Turn timer + what this turn has cost so far. The reason this status line
    # exists: Fable turns are long and expensive enough to want both live.
    if st.get("turn_started"):
        elapsed = now - st["turn_started"]
        seg = paint("⏱ ", ASH) + paint(clock(elapsed), PARCH, bold=elapsed > 60)
        if cost is not None and st.get("turn_start_cost") is not None:
            delta = cost - st["turn_start_cost"]
            if delta > 0:
                seg += " " + paint(f"+${delta:.3f}", EMBER)
        row.append(seg)

    ctx = d.get("context_window") or {}
    size = ctx.get("context_window_size") or 1_000_000
    used = ctx.get("used_percentage")
    cur = ctx.get("current_usage") or {}
    total_in = ((cur.get("input_tokens") or 0)
                + (cur.get("cache_creation_input_tokens") or 0)
                + (cur.get("cache_read_input_tokens") or 0))
    if used is None and total_in:
        used = total_in / size * 100

    seg = paint("ctx ", ASH) + meter(used, 10 if wide else 6)
    seg += " " + paint("--" if used is None else f"{used:.1f}%",
                       heat(used) if used is not None else SOOT, bold=True)
    if wide:
        seg += " " + paint(f"{tokens(total_in)}/{tokens(size)}", ASH)
    seg += " " + spark([s[2] for s in st["samples"]], 8 if wide else 5)
    row.append(seg)

    if cost is not None:
        seg = paint(f"${cost:.2f}", MOSS, bold=True)
        seg += " " + spark([s[1] for s in st["samples"]], 8 if wide else 5)
        dur_h = ((d.get("cost") or {}).get("total_duration_ms") or 0) / 3_600_000
        if dur_h > 0.05:
            seg += " " + paint(f"${cost / dur_h:.2f}/h", ASH)
        row.append(seg)

    rl = d.get("rate_limits") or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = rl.get(key) or {}
        pct = w.get("used_percentage")
        if pct is None:
            continue
        seg = paint(label, ASH) + " " + meter(pct, 5 if wide else 3)
        seg += " " + paint(f"{pct:.0f}%", heat(pct))
        if w.get("resets_at"):
            seg += paint(f"·{until(w['resets_at'] - now)}", SOOT)
        row.append(seg)

    line = paint("  ", SOOT).join(row)
    print(line)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(paint(f" fable-meter error: {exc} ", RUST))
