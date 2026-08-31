# ghostty-claude-layout-restore

Save and restore your Ghostty workspace — windows, tabs, **splits**, and the
Claude Code session that was running in each pane.

```console
$ gsess save
saved: 1 window(s) / 4 tab(s) / 7 pane(s) / 7 Claude session(s)

# ...quit Ghostty, reboot, come back...

$ gsess restore
will restore: 1 window(s) / 4 tab(s) / 7 pane(s) / 7 session(s)
restoring ...
done.
```

Every pane comes back in its own directory, running `claude --resume <its own
id>` with the flags it originally had. The CLI is `gsess`.

It is a **manual** tool. Nothing runs in the background — see
[Why manual](#why-manual).

## Why another one of these

[`ghostty-claude-code-session-restore`](https://github.com/AtAFork/ghostty-claude-code-session-restore)
got here first and does the core idea well — if it covers your setup, use it.
This tool exists for one reason: **it restores splits.**

That project drives Ghostty by sending `Cmd+T` through System Events and typing
the command into the new tab. That predates Ghostty 1.3.0 (March 2026), which
added a real AppleScript dictionary with a `split` command. So a tab that had
four panes comes back as four separate tabs, and multi-window layouts are
flattened — its README says as much.

| | AtAFork | this |
|---|---|---|
| splits / multi-window | flattened into tabs | **preserved** |
| how tabs are made | `Cmd+T` via System Events, command typed in | native AppleScript `command:` |
| macOS permission | Accessibility | Automation |
| snapshot / restore | automatic, daemon + shell hook | **manual, on purpose** |
| Codex, Cmux | ✅ | ❌ Claude Code only |

If your workspace is a flat list of tabs, that first row doesn't matter to you
and the other tool does more.

## Install

macOS, **Ghostty ≥ 1.3.0**, Python 3.8+. No third-party dependencies, one file.

```bash
git clone https://github.com/zsychn/ghostty-claude-layout-restore.git
cd ghostty-claude-layout-restore
ln -s "$PWD/gsess.py" /usr/local/bin/gsess
```

The first run asks macOS for permission to control Ghostty (Automation). No
Accessibility permission needed.

## Usage

```
gsess save                  snapshot the current workspace
gsess status                current workspace vs. latest snapshot
gsess restore               recreate it
gsess restore --dry-run     print the AppleScript, run nothing
gsess list                  snapshot history (20 kept)
```

Snapshots live in `~/.local/state/gsess/` (override with `GSESS_STATE_DIR`).
`GSESS_LANG=zh` switches the interface to Chinese.

Two guards, so a careless `save` can't cost you the thing you wanted back:

- Ghostty not running → nothing is written
- Ghostty running but no Claude session found → the previous snapshot is kept
  (`--force` overrides)

## Why manual

Automatic snapshotting sounds obviously better and isn't:

**You don't always want the current state recorded.** A workspace mid-experiment,
or one you've just torn down, will happily overwrite the arrangement you
actually wanted back. Deciding when a layout is worth keeping is the whole
job, and only you know the answer.

**And on macOS it costs more than it looks.** Taking a snapshot needs
AppleScript — it is the only way to see tabs and splits. macOS grants
automation rights per *responsible process*: a LaunchAgent is its own
responsible process with no grant, and being headless it cannot even prompt for
one. It just fails:

```
error: Not authorized to send Apple events to Ghostty. (-1743)
```

A process spawned from a shell *inside* Ghostty does inherit the grant, so the
way out is a background daemon started from your shell rc — a resident process
plus lines in your `.zshrc`, to automate a decision you probably wanted to make
yourself. (Tools that poll `ps`/`lsof` instead of AppleScript avoid this, which
is also why they can't see your splits.)

So: `gsess save` when a workspace is worth keeping, `gsess restore` when you
want it back.

## How pane → session matching works

This has to be exact: several panes in the same directory is a normal thing to
have, and it's where directory-based matching quietly breaks. Three sources,
cross-checked:

1. **Ghostty terminal title** — Claude Code writes the first 16 characters of
   the session id into it (`proj · my-session · 1a2b3c4d-5e6f-4a`). The only
   source that separates two panes in the *same* directory, so it leads.
2. **`~/.claude/sessions/<pid>.json`** — authoritative id, cwd and display name
   for sessions whose process is alive. The CLI flags come from its pid.
3. **`~/.claude/projects/<dir>/<session-id>.jsonl`** — expands the 16-char
   prefix to the full UUID and proves the transcript still exists.

`gsess status` shows how each pane matched. If your terminal title is
overridden, it falls back to matching by directory and marks those panes `~` —
that fallback *cannot* separate same-directory panes, and it says so rather
than guessing silently.

### Flags are replayed

A session started as `claude --model sonnet --dangerously-skip-permissions`
comes back with those flags. Session-selection flags (`--resume`, `--continue`,
…) are dropped since gsess supplies its own, and so are positional arguments —
replaying an initial prompt would re-send it to the model. `--no-flags` turns
replay off.

## What is and isn't restored

Restored: window/tab/split structure, the selected tab, each pane's working
directory, `claude --resume <id>` with the original flags, and a live shell if
you quit Claude instead of the pane closing.

Not restored:

- **Scrollback**, and any non-agent process (a running `npm run dev` doesn't
  come back)
- **Exact split ratios** — Ghostty's AppleScript can create splits but not size
  them, so every split returns at 50/50
- **Split arrangement** — the API exposes a tab's panes but not their layout
  tree, so it's rebuilt from a default (2 panes → side by side, 4 → 2×2 grid),
  stored in the snapshot as `split_plan` and hand-editable:

  ```json
  "split_plan": [[0, "right"], [0, "down"], [1, "down"]]
  ```

  Each entry is `[pane_to_split, direction]`, applied in order.

Sessions already running are skipped, so `restore` is safe to run twice — it
won't open a second copy of a live conversation. `--force` if you want that.

## Also worth knowing about

- [gtab](https://github.com/Franvy/gtab) — named Ghostty workspaces with more
  precise split geometry (it reads pane frames via Accessibility). Doesn't
  restore running processes, so agent sessions come back empty.
- [gpane](https://github.com/minorole/gsx) — launches a *predefined* layout with
  a command per pane. Good for starting a project; not a snapshot.
- [tabkeep](https://github.com/rohansx/tabkeep) — same idea on Linux (reads
  `/proc`); resolves sessions by directory, so same-directory panes collapse.

## Development

```bash
python3 -m unittest discover -s tests -v
```

39 tests, no Ghostty and no macOS needed — the AppleScript dump goes in as a
string and the session store as a dict.

## License

MIT
