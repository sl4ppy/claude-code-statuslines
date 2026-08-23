# opus-dashboard

A three-row, information-dense status line for Claude Code. Python 3, standard
library only, no dependencies.

```
 Opus 5 (1M context) ❯ ◆high ✻think ❯  ~/projects/acme-api ❯  master        my-session  v2.1.239
ctx ████▌░░░░░░░░░╎░░  31.0% 306.7k/1.00M │ cache 100% r305.8k w826 new2 │ last out 730
 5h █░░░░  2% ↻3h32m   7d ████░  41% ↻3d0h   $34.1817 1.68/h   20h21m api 6%   +632 -175
```

## Rows

**1 — identity.** Model, reasoning effort, thinking/fast-mode flags, working
directory, git branch with staged/unstaged counts and ahead/behind, PR or MR
badge with review state (a clickable OSC 8 link), worktree, subagent name, vim
mode. Session name and Claude Code version sit right-aligned.

**2 — context.** Gradient context-window bar with a marker at the 85% warning
threshold, percentage, tokens used against the window size, prompt-cache hit
rate with read/write/new breakdown, and the last response's output tokens.

**3 — budget.** The 5-hour and 7-day rate-limit windows with usage bars and
reset countdowns, session cost with a per-hour burn rate, wall-clock duration
with the share spent waiting on the API, and the session diffstat.

Segments appear only when their data does, so an API user (no rate limits), a
fresh session (no context usage yet), and a non-git directory all render
cleanly.

## Install

```bash
curl -o ~/.claude/statusline.py \
  https://raw.githubusercontent.com/sl4ppy/claude-code-statuslines/main/opus-dashboard/statusline.py
chmod +x ~/.claude/statusline.py
```

Then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.py",
    "refreshInterval": 30,
    "hideVimModeIndicator": true
  }
}
```

## Configuration

Environment variables, read at each run:

| Variable | Effect |
| --- | --- |
| `CC_STATUSLINE_STYLE` | `powerline` (default) or `thin`. Use `thin` without a Nerd Font. |
| `NO_COLOR` | Any value disables all colour. |
| `COLORTERM` | `truecolor`/`24bit` enables 24-bit gradients; otherwise falls back to the 256-colour cube. |

Constants at the top of the script set bar widths and the context warning
threshold.

## Requirements

Python 3.8+. A Nerd Font for the default powerline style — set
`CC_STATUSLINE_STYLE=thin` if you don't have one. Truecolor terminal recommended
for the gradients, with automatic 256-colour fallback.

## Development

`preview.py` renders the status line against synthetic sessions covering the
states that are awkward to reach by hand — near-full context, exhausted rate
limits, API users with no rate-limit data, a just-compacted session, everything
enabled at once, and a narrow terminal:

```bash
python3 preview.py
```

## Notes on the data

A few details from the [status line
documentation](https://code.claude.com/docs/en/statusline) that shape this
script:

- `rate_limits` is absent for API users, and each window can be absent
  independently. `current_usage` is `null` before the first API call and again
  right after `/compact`. Every field is treated as optional.
- `used_percentage` is calculated from input tokens only. When recomputing it
  from `current_usage`, this script uses the same input-only formula so the two
  agree.
- `total_output_tokens` is the most recent response, not a session total, so it
  is reported as "last out" and deliberately never divided by the
  session-cumulative API duration to produce a tokens/sec figure.
- `tput cols` cannot detect width here because Claude Code captures stdout
  rather than attaching it to the terminal. The script reads `COLUMNS`, which
  Claude Code sets, and drops trailing segments to fit rather than wrapping.
- `git status` is cached for 3 seconds; the status line re-runs on every
  assistant message and shelling out is the only expensive thing it does.
  A full run takes roughly 30 ms.

## License

MIT
