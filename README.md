# gsess

Save and restore your Ghostty workspace — windows, tabs, splits, **and the
Claude Code session that was running in each pane**.

```console
$ gsess save
saved: 1 window(s) / 5 tab(s) / 8 pane(s) / 8 Claude session(s) -> ~/.local/state/gsess/state.json

# ...quit Ghostty, reboot, come back...

$ gsess restore
will restore: 1 window(s) / 5 tab(s) / 8 pane(s) / 8 session(s)
restoring ...
done.
```

Every pane comes back in its own directory with `claude --resume <its own id>`
already running.

## Why

Two halves of this problem are already solved, and they don't talk to each other:

- Ghostty's `window-save-state` restores the *shape* of a workspace, but every
  pane comes back as an empty shell.
- `claude --resume <id>` restores a *conversation*, but only if you know which
  conversation belonged in which pane.

Anthropic closed the built-in version of this as not planned
([claude-code#43262](https://github.com/anthropics/claude-code/issues/43262)).
gsess is the piece in between.

## Install

Requires macOS, **Ghostty ≥ 1.3.0** (for AppleScript support), and Python 3.8+.
No third-party dependencies.

```bash
git clone https://github.com/zsychn/gsess.git
cd gsess
ln -s "$PWD/gsess.py" /usr/local/bin/gsess    # or anywhere on your PATH
```

The first run asks macOS for permission to control Ghostty (Automation). No
Accessibility permission is needed.

## Usage

```
gsess save                  snapshot the current workspace
gsess status                current workspace vs. latest snapshot
gsess restore               recreate it
gsess restore --dry-run     print the AppleScript, run nothing
gsess list                  snapshot history
gsess agent install         launchd timer, snapshots every 60s
gsess agent uninstall       stop it
```

### Surviving a reboot

A snapshot is only useful if it was taken *before* you quit. Install the timer:

```bash
gsess agent install --interval 60
```

Two guards keep it from destroying the thing you want to restore:

- if Ghostty isn't running, the snapshot is skipped entirely
- if Ghostty is running but no Claude session is found, the previous snapshot
  is kept (`--force` to override)

So the state that survives is always your last *populated* workspace, not the
empty one you left behind.

Restore is deliberately manual — a login should not spawn fifteen windows you
didn't ask for.

## How pane → session matching works

This is the part that has to be exact, because two panes in the same directory
are a completely normal thing to have. Three sources, cross-checked:

1. **Ghostty terminal title** — Claude Code writes the first 16 characters of
   the session id into the title (`proj · my-session · 1a2b3c4d-5e6f-4a`).
   This is the only source that can tell two panes in the *same directory*
   apart, so it's the primary one.
2. **`~/.claude/sessions/<pid>.json`** — authoritative session id, cwd and
   display name for sessions whose process is still alive.
3. **`~/.claude/projects/<dir>/<session-id>.jsonl`** — expands the 16-char
   prefix into the full UUID and proves the transcript still exists.

`gsess status` shows how each pane was matched. If your terminal title is
overridden or disabled, gsess falls back to matching by working directory and
marks those panes `~` — that fallback *cannot* tell same-directory panes apart,
and it says so rather than silently guessing.

## What is and isn't restored

Restored:

- window / tab / split structure, and which tab was selected
- each pane's working directory
- `claude --resume <id>` per pane, in the right directory
- quitting Claude drops you into a live shell instead of closing the pane

Not restored:

- **Scrollback** and any non-agent process (a running `npm run dev` does not
  come back)
- **Exact split ratios.** Ghostty's AppleScript API can create splits but not
  size them, so every split comes back at 50/50.
- **Split geometry.** The API exposes the panes of a tab but not their layout
  tree, so the arrangement is reconstructed from a default plan (2 panes →
  side by side, 4 panes → 2×2 grid). The plan is stored in the snapshot as
  `split_plan` and can be hand-edited:

  ```json
  "split_plan": [[0, "right"], [0, "down"], [1, "down"]]
  ```

  Each entry is `[pane_to_split, direction]`, applied in order.

Sessions that are already running are skipped, so `gsess restore` is safe to
run twice — it won't open a second copy of a live conversation. Use `--force`
if you really want that.

## Other tools

- [gtab](https://github.com/Franvy/gtab) — named Ghostty workspaces, with more
  precise split geometry (it reads pane frames via Accessibility). It doesn't
  restore running processes, so agent sessions come back empty.
- [gpane](https://github.com/minorole/gsx) — launches a *predefined* layout with
  a command per pane. Great for starting a project; it isn't a snapshot of what
  you actually had open.
- [tabkeep](https://github.com/rohansx/tabkeep) — same idea, Linux only (reads
  `/proc`), and resolves sessions by directory, so same-directory panes collapse
  to one id.

## Development

```bash
python3 -m unittest discover -s tests -v
```

29 tests, no Ghostty or macOS required — the AppleScript dump is fed in as a
string and the session store as a dict.

## License

MIT
