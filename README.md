# ghostty-claude-layout-restore

Save and restore your Ghostty workspace — windows, tabs, **splits**, and the
Claude Code session that was running in each pane.

```console
$ gsess save
saved: 1 window(s) / 5 tab(s) / 8 pane(s) / 8 Claude session(s)

# ...quit Ghostty, reboot, come back, open a terminal...
# every pane is back in its own directory, running `claude --resume <its own id>`
```

The CLI is `gsess`.

## Why another one of these

[`ghostty-claude-code-session-restore`](https://github.com/AtAFork/ghostty-claude-code-session-restore)
got here first and does the core idea well — if it covers your setup, use it.
This tool exists for one reason: **it restores splits.**

That project drives Ghostty by sending `Cmd+T` through System Events and typing
the command into the new tab. That predates Ghostty 1.3.0 (March 2026), which
added a real AppleScript dictionary with a `split` command. So a tab that had
four panes comes back as four separate tabs, and multi-window layouts are
flattened — its README says as much.

If your workspace is a flat list of tabs, that difference doesn't matter and
the other tool gives you Codex and Cmux support, which this one doesn't.

| | AtAFork | this |
|---|---|---|
| splits / multi-window | flattened into tabs | **preserved** |
| how tabs are made | `Cmd+T` via System Events, command typed in | native AppleScript `command:` |
| macOS permission | Accessibility | Automation |
| Codex, Cmux | ✅ | ❌ Claude Code only |
| install | ~40 lines into your shell rc | one symlink + 6 lines |

## Install

macOS, **Ghostty ≥ 1.3.0**, Python 3.8+. No third-party dependencies.

```bash
git clone https://github.com/zsychn/ghostty-claude-layout-restore.git
cd ghostty-claude-layout-restore
ln -s "$PWD/gsess.py" /usr/local/bin/gsess
```

Then turn on the two automatic halves:

```bash
gsess agent install                        # snapshots every 30s
gsess shell-init zsh >> ~/.zshrc           # restores after Ghostty was quit
```

`shell-init` also takes `bash` and `fish`. The first run asks for permission to
control Ghostty (Automation).

## Usage

```
gsess save                  snapshot the current workspace
gsess status                current workspace vs. latest snapshot
gsess restore               recreate it (new windows)
gsess restore --dry-run     print the AppleScript, run nothing
gsess autorestore           recreate it *around the calling shell* (used by shell-init)
gsess list                  snapshot history
gsess agent install|uninstall|status
gsess shell-init zsh|bash|fish
```

### How the automatic path works

The launchd timer snapshots every 30s while Ghostty is up. When it notices
Ghostty has quit — with a populated snapshot behind it — it arms a pending
marker. Next time you open a Ghostty terminal, the shell snippet sees the
marker and calls `gsess autorestore`, which:

- builds every other tab, split and window around the shell that called it
- prints the command for the tab you're already in, which the snippet `eval`s

so you don't end up with a stray empty window. Restored panes carry
`GSESS_RESTORED=1`, which stops the snippet from firing inside them (they run
a login shell, so it would otherwise recurse).

Three guards keep this from misfiring:

- Ghostty not running → snapshot skipped entirely
- Ghostty running but no Claude session found → previous snapshot kept
  (`--force` overrides)
- the marker is claimed with an atomic rename, so opening several tabs at once
  restores exactly once; and autorestore refuses unless Ghostty is freshly
  launched (one window, one tab, one pane)

Restore is otherwise manual — a login should not spawn fifteen windows you
didn't ask for.

## How pane → session matching works

This has to be exact: several panes in the same directory is a normal thing to
have, and it's where directory-based matching quietly breaks. Three sources,
cross-checked:

1. **Ghostty terminal title** — Claude Code writes the first 16 characters of
   the session id into it (`proj · my-session · 1a2b3c4d-5e6f-4a`). The only
   source that separates two panes in the *same* directory, so it leads.
2. **`~/.claude/sessions/<pid>.json`** — authoritative id, cwd and display name
   for sessions whose process is alive. Also where the CLI flags come from.
3. **`~/.claude/projects/<dir>/<session-id>.jsonl`** — expands the 16-char
   prefix to the full UUID and proves the transcript still exists.

`gsess status` shows how each pane matched. If your terminal title is
overridden, it falls back to matching by directory and marks those panes `~` —
that fallback *cannot* separate same-directory panes, and it says so rather
than guessing silently.

### Flags are replayed too

A session started as `claude --model sonnet --dangerously-skip-permissions`
comes back with those flags. Session-selection flags (`--resume`, `--continue`,
`--fork-session`, …) are dropped, since gsess supplies its own `--resume`, and
so are positional arguments — replaying an initial prompt would re-send it to
the model. `restore --no-flags` turns replay off.

## What is and isn't restored

Restored: window/tab/split structure, the selected tab, each pane's working
directory, `claude --resume <id>` with the original flags, and a live shell
when you quit Claude instead of the pane closing.

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
  a command per pane. Good for starting a project; not a snapshot of what you
  had open.
- [tabkeep](https://github.com/rohansx/tabkeep) — same idea on Linux (reads
  `/proc`); resolves sessions by directory, so same-directory panes collapse.

## Development

```bash
python3 -m unittest discover -s tests -v
```

47 tests, no Ghostty and no macOS needed — the AppleScript dump goes in as a
string and the session store as a dict.

## License

MIT
