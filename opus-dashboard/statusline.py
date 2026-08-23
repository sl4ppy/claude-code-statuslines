#!/usr/bin/env python3
"""Claude Code status line.

Three rows:
  1. identity   model / effort / cwd / git / PR            [right: session, version]
  2. context    gradient context bar, tokens, cache efficiency, throughput
  3. budget     5h + 7d limits with reset countdowns, cost, burn rate, diffstat

Design notes
------------
* Every field is optional. The status line JSON marks most fields absent or null
  in some state: no `rate_limits` off a Claude.ai subscription, `current_usage`
  null before the first API call and again right after /compact.
* Bars are truecolor gradients (green -> amber -> red) so the colour carries the
  reading even at a glance; falls back to 256-colour, then to no colour.
* Width-adaptive. Claude Code exports COLUMNS; `tput cols` cannot work here
  because stdout is captured rather than attached to the terminal.
* Style is configurable below: "powerline" (Nerd Font required) or "thin".
"""

import json
import os
import re
import subprocess
import sys
import time
import unicodedata

# ------------------------------------------------------------------ config --

STYLE = os.environ.get("CC_STATUSLINE_STYLE", "powerline")  # powerline | thin
BAR_WIDE, BAR_NARROW = 18, 10
CONTEXT_WARN = 85.0        # where the compact hint and bar marker appear

NO_COLOR = bool(os.environ.get("NO_COLOR"))
TRUECOLOR = os.environ.get("COLORTERM", "") in ("truecolor", "24bit")

PL_SEP = ""          # nf-pl-left_hard_divider
PL_END = ""

# ------------------------------------------------------------------ colour --

ANSI_RE = re.compile(r"\033\[[0-9;]*m|\033]8;[^\033]*\033\\")


def rgb(r, g, b, bg=False):
    if NO_COLOR:
        return ""
    if TRUECOLOR:
        return f"\033[{48 if bg else 38};2;{r};{g};{b}m"
    # 6x6x6 cube fallback
    idx = 16 + 36 * (r * 5 // 255) + 6 * (g * 5 // 255) + (b * 5 // 255)
    return f"\033[{48 if bg else 38};5;{idx}m"


RESET = "" if NO_COLOR else "\033[0m"
BOLD = "" if NO_COLOR else "\033[1m"

# palette
FG_MUTED = (128, 132, 146)
FG_FAINT = (88, 92, 104)
C_MODEL = (198, 160, 246)
C_PATH = (138, 173, 244)
C_GIT = (166, 218, 149)
C_ACCENT = (145, 215, 227)
C_WARN = (245, 169, 127)
C_BAD = (237, 135, 150)
C_GOOD = (166, 218, 149)
INK_DARK = (26, 22, 38)     # for light chip backgrounds
INK_LIGHT = (226, 230, 244)  # for dark chip backgrounds


def paint(text, fg=None, bold=False):
    if NO_COLOR:
        return str(text)
    out = ""
    if bold:
        out += BOLD
    if fg:
        out += rgb(*fg)
    return f"{out}{text}{RESET}" if out else str(text)


def gradient(pct):
    """Green -> amber -> red, positioned by percentage."""
    pct = max(0.0, min(100.0, pct))
    if pct <= 50:
        t = pct / 50
        return (int(122 + t * 123), int(222 - t * 42), int(140 - t * 13))
    t = (pct - 50) / 50
    return (int(245 - t * 8), int(180 - t * 45), int(127 - t * 0))


def vlen(s):
    """Visible width: strip ANSI/OSC8, count East-Asian wide cells as 2."""
    s = ANSI_RE.sub("", s)
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def fit(parts, width, joiner=" "):
    """Join parts, dropping from the end until the row fits the terminal.
    Segments are ordered most- to least-important, so trailing drops first."""
    while parts:
        line = joiner.join(parts)
        if vlen(line) <= width:
            return line
        parts = parts[:-1]
    return ""


def osc8(url, label):
    if NO_COLOR or not url:
        return label
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


# -------------------------------------------------------------------- bars --


def bar(pct, width, marker=None):
    """Gradient bar with eighth-block partial cell and an optional marker."""
    if pct is None:
        return paint("░" * width, FG_FAINT)
    pct = max(0.0, min(100.0, float(pct)))
    exact = pct / 100.0 * width
    full = int(exact)
    frac = exact - full
    eighths = " ▏▎▍▌▋▊▉"

    cells = []
    for i in range(full):
        cells.append(rgb(*gradient((i + 0.5) / width * 100)) + "█")
    # eighths[0] is a space, which would paint a blank cell mid-bar; clamp to
    # at least a one-eighth sliver so a small remainder still reads as filled.
    if full < width and frac > 0.05:
        cells.append(rgb(*gradient(pct)) + eighths[max(1, int(frac * 8))])
    used = len(cells)
    for i in range(used, width):
        ch = "░"
        if marker is not None and i == int(marker / 100.0 * width):
            ch = "╎"
        cells.append(rgb(*FG_FAINT) + ch)
    return "".join(cells) + RESET


# ------------------------------------------------------------------ format --


def human_tokens(n):
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def human_duration(seconds):
    if seconds is None or seconds < 0:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        h, m = divmod(seconds // 60, 60)
        return f"{h}h{m:02d}m"
    d, h = divmod(seconds // 3600, 24)
    return f"{d}d{h}h"


def shorten_path(path, budget):
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
    out = f"{parts[0]}{os.sep}…{os.sep}{parts[-1]}"
    for i in range(len(parts) - 2, 0, -1):
        cand = os.sep.join([parts[0], "…"] + parts[i:])
        if len(cand) <= budget:
            out = cand
        else:
            break
    return out


# --------------------------------------------------------------------- git --


def git_info(cwd):
    """Cached ~3s: this runs on every assistant message and it is the only
    thing here that shells out."""
    cache = os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
        f"cc-statusline-git-{abs(hash(cwd)) % 10**10}.json",
    )
    try:
        if time.time() - os.stat(cache).st_mtime < 3:
            with open(cache) as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass

    info = {}
    try:
        p = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain=v2", "--branch"],
            capture_output=True, text=True, timeout=1.0,
        )
        if p.returncode == 0:
            dirty = staged = 0
            for line in p.stdout.splitlines():
                if line.startswith("# branch.head "):
                    info["branch"] = line.split(" ", 2)[2]
                elif line.startswith("# branch.ab "):
                    ab = line.split(" ", 2)[2].split()
                    info["ahead"] = int(ab[0].lstrip("+"))
                    info["behind"] = int(ab[1].lstrip("-"))
                elif line[:1] in ("1", "2"):
                    if line.split(" ")[1][0] != ".":
                        staged += 1
                    else:
                        dirty += 1
                elif line[:1] in ("u", "?"):
                    dirty += 1
            info["dirty"], info["staged"] = dirty, staged
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        info = {}

    try:
        with open(cache, "w") as fh:
            json.dump(info, fh)
    except OSError:
        pass
    return info


# ------------------------------------------------------------------ layout --


class Row:
    """Collects segments and renders them powerline- or thin-separated."""

    def __init__(self):
        self.segs = []          # (text, bg, fg) — bg/fg only in powerline mode
        self.right = []

    def add(self, text, bg=None, fg=None):
        if text:
            self.segs.append((text, bg, fg))

    def add_right(self, text):
        if text:
            self.right.append(text)

    def render(self, width):
        if STYLE == "powerline":
            left = self._powerline()
        else:
            sep = paint(" │ ", FG_FAINT)
            left = sep.join(t for t, _, _ in self.segs)
        if not self.right:
            return left
        right = paint("  ".join(self.right), FG_FAINT)
        gap = width - vlen(left) - vlen(right) - 1
        # Only right-align when it genuinely fits; otherwise drop it rather
        # than let the row wrap onto a fourth line.
        return left + " " * gap + right if gap >= 1 else left

    def _powerline(self):
        out = []
        for i, (text, bg, fg) in enumerate(self.segs):
            bg = bg or (48, 52, 64)
            body = rgb(*bg, bg=True) + (rgb(*fg) if fg else "") + " " + text + " "
            out.append(body + RESET + rgb(*bg, bg=True))
            nxt = self.segs[i + 1][1] if i + 1 < len(self.segs) else None
            if nxt:
                out.append(RESET + rgb(*bg) + rgb(*nxt, bg=True) + PL_SEP + RESET)
            else:
                out.append(RESET + rgb(*bg) + PL_END + RESET)
        return "".join(out)


# -------------------------------------------------------------------- main --


def main():
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print(paint(" statusline: bad JSON on stdin ", C_BAD))
        return

    width = max(40, int(os.environ.get("COLUMNS") or 120) - 2)
    wide = width >= 100
    bw = BAR_WIDE if wide else BAR_NARROW

    # ---- row 1: identity ------------------------------------------------
    r1 = Row()

    model = (d.get("model") or {}).get("display_name") or "?"
    # Dark ink on the light-purple chip: the terminal's default foreground is
    # light, which is unreadable on this background.
    r1.add(model, C_MODEL, INK_DARK)

    flags = []
    effort = (d.get("effort") or {}).get("level")
    if effort:
        flags.append(f"◆{effort}")
    if d.get("fast_mode"):
        flags.append("⚡fast")
    if (d.get("thinking") or {}).get("enabled"):
        flags.append("✻think")
    if flags:
        hot = effort in ("xhigh", "max")
        r1.add(" ".join(flags),
               (96, 58, 74) if hot else (74, 58, 110), INK_LIGHT)

    ws = d.get("workspace") or {}
    cwd = ws.get("current_dir") or d.get("cwd") or ""
    r1.add(f" {shorten_path(cwd, 40 if wide else 22)}", (58, 68, 98), INK_LIGHT)

    g = git_info(cwd) if cwd else {}
    if g.get("branch"):
        br = g["branch"]
        txt = " detached" if br == "(detached)" else f" {br}"
        staged, dirty = g.get("staged", 0), g.get("dirty", 0)
        if staged:
            txt += f" ●{staged}"
        if dirty:
            txt += f" ✚{dirty}"
        if g.get("ahead"):
            txt += f" ↑{g['ahead']}"
        if g.get("behind"):
            txt += f" ↓{g['behind']}"
        clean = not (staged or dirty)
        r1.add(txt, (52, 78, 56) if clean else (92, 78, 40), INK_LIGHT)

    pr = d.get("pr") or {}
    if pr.get("number"):
        kind = "MR" if pr.get("kind") == "mr" else "PR"
        state = pr.get("review_state")
        mark = {"approved": "✓", "changes_requested": "✗",
                "draft": "◌", "pending": "•"}.get(state, "")
        bg = {"approved": (52, 78, 56), "changes_requested": (104, 46, 58),
              "draft": (60, 60, 70)}.get(state, (92, 78, 40))
        r1.add(osc8(pr.get("url"), f"{kind}#{pr['number']}{mark}"), bg, INK_LIGHT)

    wt = ws.get("git_worktree") or (d.get("worktree") or {}).get("name")
    if wt:
        r1.add(f"wt {wt}", (74, 56, 98), INK_LIGHT)

    agent = (d.get("agent") or {}).get("name")
    if agent:
        r1.add(f"@{agent}", (44, 74, 86), INK_LIGHT)

    vim = (d.get("vim") or {}).get("mode")
    if vim:
        r1.add(vim, (52, 78, 56) if vim == "NORMAL" else (92, 78, 40), INK_LIGHT)

    if wide:
        name = d.get("session_name")
        if name:
            r1.add_right(name[:28])
        style = (d.get("output_style") or {}).get("name")
        if style and style != "default":
            r1.add_right(style)
        if d.get("version"):
            r1.add_right(f"v{d['version']}")
    print(r1.render(width))

    # ---- row 2: context --------------------------------------------------
    ctx = d.get("context_window") or {}
    size = ctx.get("context_window_size") or 200_000
    used = ctx.get("used_percentage")
    cur = ctx.get("current_usage") or {}
    inp = cur.get("input_tokens") or 0
    cw = cur.get("cache_creation_input_tokens") or 0
    cr = cur.get("cache_read_input_tokens") or 0
    total_in = inp + cw + cr
    if used is None and total_in:
        used = total_in / size * 100      # input-only, matching used_percentage

    parts = [paint(" ctx", FG_MUTED), bar(used, bw, marker=CONTEXT_WARN)]
    parts.append(paint("  --" if used is None else f"{used:5.1f}%",
                       gradient(used) if used is not None else FG_FAINT, bold=True))
    parts.append(paint(f"{human_tokens(total_in)}/{human_tokens(size)}", FG_MUTED))

    if total_in:
        hit = cr / total_in * 100
        parts.append(paint("│", FG_FAINT))
        parts.append(paint(f"cache {hit:.0f}%",
                           C_GOOD if hit >= 70 else C_WARN if hit >= 40 else FG_MUTED))
        if wide:
            parts.append(paint(f"r{human_tokens(cr)} w{human_tokens(cw)} "
                               f"new{human_tokens(inp)}", FG_FAINT))

    out_tok = ctx.get("total_output_tokens") or 0
    api_ms = (d.get("cost") or {}).get("total_api_duration_ms") or 0
    if out_tok:
        parts.append(paint("│", FG_FAINT))
        # total_output_tokens is the most recent response only, so it cannot be
        # divided by the session-cumulative api duration to get a rate.
        parts.append(paint(f"last out {human_tokens(out_tok)}", FG_MUTED))

    if used is not None and used >= CONTEXT_WARN:
        parts.append(paint("  ⚠ /compact", C_BAD, bold=True))
    print(fit(parts, width))

    # ---- row 3: budget ---------------------------------------------------
    parts = []
    now = time.time()
    rl = d.get("rate_limits") or {}
    for key, label in (("five_hour", " 5h"), ("seven_day", " 7d")):
        w = rl.get(key) or {}
        pct = w.get("used_percentage")
        if pct is None:
            continue
        seg = [paint(label, FG_MUTED), bar(pct, bw // 2),
               paint(f"{pct:.0f}%", gradient(pct))]
        if w.get("resets_at"):
            seg.append(paint(f"↻{human_duration(w['resets_at'] - now)}", FG_FAINT))
        parts.append(" ".join(seg))

    cost = d.get("cost") or {}
    usd = cost.get("total_cost_usd")
    dur_ms = cost.get("total_duration_ms") or 0
    if usd is not None:
        seg = paint(" $", FG_MUTED) + paint(f"{usd:.4f}", C_GOOD, bold=True)
        hours = dur_ms / 3_600_000
        if hours > 0.05:
            seg += " " + paint(f"{usd / hours:.2f}/h", FG_FAINT)
        parts.append(seg)

    if dur_ms:
        seg = paint(" " + human_duration(dur_ms / 1000), FG_MUTED)
        if api_ms:
            seg += paint(f" api {api_ms / dur_ms * 100:.0f}%", FG_FAINT)
        parts.append(seg)

    added = cost.get("total_lines_added") or 0
    removed = cost.get("total_lines_removed") or 0
    if added or removed:
        parts.append(paint(f"+{added}", C_GOOD) + " " + paint(f"-{removed}", C_BAD))

    if parts:
        print(fit(parts, width, joiner=paint("  ", FG_FAINT)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:              # never break the UI
        print(paint(f" statusline error: {exc} ", C_BAD))
