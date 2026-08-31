#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gsess - save and restore Ghostty windows/tabs/splits *including* the
Claude Code session running inside each pane.

Ghostty (>= 1.3.0) can rebuild the shape of a workspace, but not what was
running in it. `claude --resume <id>` can bring a conversation back, but only
if you know which conversation belonged in which pane. gsess is the piece in
between.

It is deliberately manual: you decide when a workspace is worth keeping and
when to bring it back. Nothing runs in the background.

How a pane is matched to a session (three sources, cross-checked):

  1. Ghostty terminal title ends with the first 16 chars of the sessionId
     (Claude Code writes "<dir> - <name> - <sid-prefix>"). The only source
     that can tell two panes in the *same* directory apart.
  2. ~/.claude/sessions/<pid>.json  - authoritative sessionId / cwd / name
     for sessions whose process is alive, and where the CLI flags come from.
  3. ~/.claude/projects/<esc-cwd>/<sessionId>.jsonl - expands a 16-char
     prefix into the full UUID, and proves the transcript still exists.

Requires: macOS, Ghostty >= 1.3.0 (AppleScript support), Python 3.8+.
No third-party dependencies.
"""

__version__ = "0.4.0"

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
CLAUDE_SESSIONS = os.path.join(CLAUDE_DIR, "sessions")
CLAUDE_PROJECTS = os.path.join(CLAUDE_DIR, "projects")


def _state_dir():
    override = os.environ.get("GSESS_STATE_DIR")
    if override:
        return os.path.expanduser(override)
    xdg = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state")
    return os.path.join(xdg, "gsess")


STATE_DIR = _state_dir()
LATEST = os.path.join(STATE_DIR, "state.json")
HISTORY_DIR = os.path.join(STATE_DIR, "history")

FS = "\x1f"   # field separator inside one AppleScript record
RS = "\x1e"   # record separator

# Claude Code appends the session id prefix to the terminal title: 8-4-2 hex.
SID_TAIL = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{2})\s*$")

# Flags that select *which* conversation to open. gsess supplies its own
# --resume, so replaying these would fight it.
SESSION_SELECT_FLAGS = {
    "--resume", "-r", "--continue", "-c", "--fork-session",
    "--session-id", "--name", "-n", "--cloud", "--from-pr",
}

# Where claude tends to live, checked last if nothing else resolved it.
CLAUDE_CANDIDATES = (
    "~/.local/bin/claude", "~/.claude/local/claude",
    "/usr/local/bin/claude", "/opt/homebrew/bin/claude",
    "~/.bun/bin/claude", "~/.npm-global/bin/claude",
)


# --------------------------------------------------------------- i18n

def _lang():
    v = os.environ.get("GSESS_LANG", "")
    if v:
        return "zh" if v.lower().startswith("zh") else "en"
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if "zh" in os.environ.get(key, "").lower():
            return "zh"
    return "en"


LANG = _lang()

MSG = {
    "not_running": ("Ghostty is not running", "Ghostty 没在运行"),
    "not_running_skip": (
        "Ghostty is not running - nothing to snapshot (previous snapshot kept)",
        "Ghostty 没在运行，没什么可存的（保留上一次快照）"),
    "saved": (
        "saved: %d window(s) / %d tab(s) / %d pane(s) / %d Claude session(s) -> %s",
        "已保存: %d 窗口 / %d tab / %d 分屏 / %d 个 Claude 会话 -> %s"),
    "no_sessions_keep": (
        "no Claude session found - previous snapshot kept (--force to overwrite)",
        "当前没有任何 Claude 会话，保留上一次快照（--force 强制覆盖）"),
    "no_snapshot": (
        "no snapshot yet - run `gsess save` first",
        "还没有快照，先跑 `gsess save`"),
    "cur_header": ("=== current Ghostty ===", "=== 当前 Ghostty ==="),
    "snap_header": ("=== latest snapshot ===", "=== 最新快照 ==="),
    "saved_at": ("saved at %s", "存于 %s"),
    "totals": (
        "total: %d window(s) / %d tab(s) / %d pane(s) / %d session(s)",
        "合计: %d 窗口 / %d tab / %d 分屏 / %d 会话"),
    "will_restore": (
        "will restore: %d window(s) / %d tab(s) / %d pane(s) / %d session(s)",
        "将恢复: %d 窗口 / %d tab / %d 分屏 / %d 会话"),
    "window_n": ("window %d - %d tab(s)", "窗口 %d — %d 个 tab"),
    "tab_n": ("tab %d", "tab %d"),
    "splits": (" (%d panes)", "（%d 分屏）"),
    "plain_shell": ("(plain shell)", "(普通 shell)"),
    "legend": (
        "(* = running right now, restore skips it; ~ = matched by directory, "
        "may be imprecise)",
        "(* = 此刻正在运行，restore 会跳过；~ = 按目录猜的，可能不准)"),
    "skip_running": (
        "skipping session %s (%s) - already running",
        "跳过已在运行的会话 %s（%s）"),
    "transcript_gone": (
        "transcript for %s is gone - that pane opens a plain shell",
        "会话 %s 的记录已不存在，该分屏只开普通 shell"),
    "dir_missing": ("directory no longer exists: %s", "目录不存在: %s"),
    "dry_run": (
        "--- AppleScript that would run (--dry-run, nothing executed) ---",
        "--- 将执行的 AppleScript（--dry-run，未执行）---"),
    "launching": ("starting Ghostty ...", "启动 Ghostty …"),
    "launch_timeout": ("Ghostty did not start in time", "Ghostty 启动超时"),
    "restoring": ("restoring ...", "恢复中 …"),
    "done": ("done.", "完成。"),
    "no_history": ("no snapshot history yet", "还没有历史快照"),
    "history_path": ("history: %s", "历史目录: %s"),
    "hist_line": (
        "%s  %dwin/%dtab/%dpane/%dsession",
        "%s  %d窗口/%dtab/%d分屏/%d会话"),
    "err": ("error: %s", "错误: %s"),
    "old_ghostty": (
        "Ghostty did not answer AppleScript. gsess needs Ghostty >= 1.3.0.",
        "Ghostty 没有响应 AppleScript。gsess 需要 Ghostty >= 1.3.0。"),
    "no_claude_bin": (
        "cannot find the `claude` executable - set GSESS_CLAUDE_BIN to its "
        "full path and try again",
        "找不到 `claude` 可执行文件 —— 把它的完整路径设进 GSESS_CLAUDE_BIN 再试"),
    "using_claude": ("using %s", "使用 %s"),
    "nothing_to_restore": (
        "nothing to restore - every session in the snapshot is already running",
        "没有需要恢复的：快照里的会话都已经在运行了"),
}


def t(key, *args):
    s = MSG[key][1 if LANG == "zh" else 0]
    return (s % args) if args else s


# --------------------------------------------------------------- helpers

class GsessError(RuntimeError):
    pass


def osa(script):
    """Run an AppleScript snippet, return stdout."""
    p = subprocess.run(["osascript", "-"], input=script,
                       capture_output=True, text=True)
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        if "-1708" in err or "Can't continue" in err:
            raise GsessError(t("old_ghostty") + "\n" + err)
        raise GsessError(err)
    return p.stdout


def ghostty_running():
    """Is Ghostty running? Must not use AppleScript - that would launch it.

    Uses ps rather than pgrep: pgrep needs proc_listpids and silently returns
    nothing in sandboxed/restricted contexts, which would look like "not
    running".
    """
    try:
        out = subprocess.run(["ps", "-ax", "-o", "comm="],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return False
    for line in out.splitlines():
        line = line.strip()
        if line.endswith("/ghostty") or "Ghostty.app/Contents/MacOS" in line:
            return True
    return False


def asq(s):
    """Quote a Python string as an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --------------------------------------------------------------- sources

def _proc_commands():
    """pid -> full command line, from a single ps call."""
    try:
        out = subprocess.run(["ps", "-ax", "-o", "pid=,command="],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return {}
    table = {}
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid.isdigit():
            table[int(pid)] = cmd.strip()
    return table


def extract_flags(command_line, drop=SESSION_SELECT_FLAGS):
    """Flags worth replaying, read off a live `claude ...` command line.

    Positional arguments are dropped on purpose: replaying an initial prompt
    would re-send it to the model on restore. Session-selection flags are
    dropped because gsess supplies --resume itself.
    """
    try:
        toks = shlex.split(command_line)
    except ValueError:
        return []
    i = 0
    while i < len(toks) and not toks[i].startswith("-"):
        i += 1                       # executable, then any positional prompt
    out = []
    while i < len(toks):
        tok = toks[i]
        if not tok.startswith("-"):
            i += 1                   # stray positional
            continue
        takes_value = ("=" not in tok and i + 1 < len(toks)
                       and not toks[i + 1].startswith("-"))
        if tok.split("=", 1)[0] in drop:
            i += 2 if takes_value else 1
            continue
        out.append(tok)
        if takes_value:
            out.append(toks[i + 1])
            i += 2
        else:
            i += 1
    return out


def live_claude_sessions():
    """Alive interactive CLI sessions, keyed by sessionId."""
    out = {}
    procs = _proc_commands()
    if not os.path.isdir(CLAUDE_SESSIONS):
        return out
    for name in os.listdir(CLAUDE_SESSIONS):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(CLAUDE_SESSIONS, name), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        pid, sid = d.get("pid"), d.get("sessionId")
        if not pid or not sid or d.get("entrypoint") != "cli":
            continue
        try:
            os.kill(int(pid), 0)          # signal 0 = liveness probe
        except (OSError, ValueError):
            continue
        # Liveness alone is not enough: a stale sessions/<pid>.json plus a
        # recycled pid would mark a dead session "running", and restore would
        # skip it - losing it silently. Confirm the pid is actually claude.
        cmdline = procs.get(int(pid), "")
        if cmdline and "claude" not in cmdline.lower():
            continue
        out[sid] = {"pid": pid, "session_id": sid, "cwd": d.get("cwd"),
                    "name": d.get("name"),
                    "flags": extract_flags(procs.get(int(pid), ""))}
    return out


def _project_dirs():
    if not os.path.isdir(CLAUDE_PROJECTS):
        return []
    return [os.path.join(CLAUDE_PROJECTS, d)
            for d in os.listdir(CLAUDE_PROJECTS)
            if os.path.isdir(os.path.join(CLAUDE_PROJECTS, d))]


def resolve_prefix(prefix, dirs=None):
    """Expand a 16-char sessionId prefix to the full UUID, if unambiguous."""
    hits = set()
    for pdir in (dirs if dirs is not None else _project_dirs()):
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for n in names:
            if n.startswith(prefix) and n.endswith(".jsonl"):
                hits.add(n[:-6])
    return next(iter(hits)) if len(hits) == 1 else None


def transcript_path(session_id):
    for pdir in _project_dirs():
        p = os.path.join(pdir, session_id + ".jsonl")
        if os.path.exists(p):
            return p
    return None


# --------------------------------------------------------------- capture

ENUM_SCRIPT = """
tell application "Ghostty"
  set FS to (ASCII character 31)
  set RS to (ASCII character 30)
  set out to ""
  set wi to 0
  repeat with w in windows
    set wi to wi + 1
    repeat with tb in tabs of w
      set si to 0
      repeat with s in terminals of tb
        set si to si + 1
        set cwdv to ""
        try
          set cwdv to (working directory of s)
        end try
        set out to out & wi & FS & (id of w) & FS & (index of tb) & FS & (id of tb) & FS & (name of tb) & FS & (selected of tb) & FS & si & FS & (id of s) & FS & cwdv & FS & (name of s) & RS
      end repeat
    end repeat
  end repeat
  return out
end tell
"""


def parse_enum(raw, live, resolver=resolve_prefix):
    """Turn the AppleScript dump into the window/tab/pane tree.

    Kept free of I/O so it can be unit-tested: `live` is the session map and
    `resolver` expands a prefix to a full UUID.
    """
    live_by_prefix = {sid[:16]: rec for sid, rec in live.items()}
    windows = {}

    for rec in raw.split(RS):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split(FS)
        if len(parts) < 10:
            continue
        (w_ord, w_id, t_idx, t_id, t_name, t_sel,
         _s_ord, _s_id, cwd, s_name) = parts[:10]

        pane = {"cwd": cwd or None, "title": s_name, "session_id": None,
                "session_name": None, "match": "none"}

        m = SID_TAIL.search(s_name or "")
        if m:
            prefix = m.group(1)
            hit = live_by_prefix.get(prefix)
            if hit:
                pane["session_id"] = hit["session_id"]
                pane["session_name"] = hit.get("name")
                pane["match"] = "live+title"
                pane["cwd"] = pane["cwd"] or hit.get("cwd")
                pane["flags"] = hit.get("flags") or []
            else:
                full = resolver(prefix)
                if full:
                    pane["session_id"] = full
                    pane["match"] = "title+transcript"
                else:
                    pane["session_id_prefix"] = prefix
                    pane["match"] = "title-only"

        win = windows.setdefault(int(w_ord), {"window_id": w_id, "tabs": {}})
        tab = win["tabs"].setdefault(
            int(t_idx), {"tab_id": t_id, "title": t_name,
                         "selected": (t_sel == "true"), "panes": []})
        tab["panes"].append(pane)

    ordered = []
    for w_ord in sorted(windows):
        win = windows[w_ord]
        tabs = [win["tabs"][k] for k in sorted(win["tabs"])]
        for tab in tabs:
            tab["split_plan"] = default_split_plan(len(tab["panes"]))
        ordered.append({"window_id": win["window_id"], "tabs": tabs})
    return ordered


def apply_cwd_fallback(windows, live):
    """Last resort when the title carries no session id.

    Only fires for panes that matched nothing. Sessions are handed out per
    directory in pid order, so it is a guess - flagged as such in `match`.
    """
    used = {p["session_id"] for w in windows for tb in w["tabs"]
            for p in tb["panes"] if p.get("session_id")}
    pool = {}
    for sid, rec in live.items():
        if sid not in used:
            pool.setdefault(rec.get("cwd"), []).append(rec)
    for lst in pool.values():
        lst.sort(key=lambda r: int(r.get("pid") or 0))

    for w in windows:
        for tb in w["tabs"]:
            for p in tb["panes"]:
                if p.get("session_id"):
                    continue
                lst = pool.get(p.get("cwd"))
                if lst:
                    rec = lst.pop(0)
                    p["session_id"] = rec["session_id"]
                    p["session_name"] = rec.get("name")
                    p["match"] = "cwd-fallback"
                    p["flags"] = rec.get("flags") or []
    return windows


def capture(fallback=True):
    live = live_claude_sessions()
    windows = parse_enum(osa(ENUM_SCRIPT), live)
    if fallback:
        apply_cwd_fallback(windows, live)
    return windows


def default_split_plan(n):
    """[[pane_to_split, direction], ...] with n-1 entries.

    Ghostty's AppleScript API exposes the panes of a tab but not their
    geometry, so the arrangement is reconstructed from a sane default. It is
    stored in the snapshot and can be hand-edited.
    """
    if n <= 1:
        return []
    if n == 2:
        return [[0, "right"]]
    if n == 3:
        return [[0, "right"], [1, "down"]]
    if n == 4:                                   # 2x2 grid
        return [[0, "right"], [0, "down"], [1, "down"]]
    return [[i, "right"] for i in range(n - 1)]


# --------------------------------------------------------------- counting

def count_panes(windows):
    return sum(len(tb["panes"]) for w in windows for tb in w["tabs"])


def count_tabs(windows):
    return sum(len(w["tabs"]) for w in windows)


def count_sessions(windows):
    return sum(1 for w in windows for tb in w["tabs"] for p in tb["panes"]
               if p.get("session_id"))


# --------------------------------------------------------------- save

def cmd_save(args):
    if not ghostty_running():
        print(t("not_running_skip"))
        return 0

    windows = capture(fallback=not args.no_fallback)
    n_sess = count_sessions(windows)

    # Guard: never let an empty snapshot clobber the one you want to restore.
    if n_sess == 0 and not args.force and os.path.exists(LATEST):
        print(t("no_sessions_keep"))
        return 0

    snap = {
        "gsess_version": __version__,
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": os.uname().nodename,
        "counts": {"windows": len(windows), "tabs": count_tabs(windows),
                   "panes": count_panes(windows), "sessions": n_sess},
        "windows": windows,
    }
    atomic_write(LATEST, snap)
    atomic_write(os.path.join(HISTORY_DIR,
                              datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"),
                 snap)
    prune_history(args.keep)

    if not args.quiet:
        print(t("saved", len(windows), count_tabs(windows),
                count_panes(windows), n_sess, LATEST))
    return 0


def prune_history(keep):
    if keep <= 0 or not os.path.isdir(HISTORY_DIR):
        return
    files = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".json"))
    for f in files[:-keep]:
        try:
            os.remove(os.path.join(HISTORY_DIR, f))
        except OSError:
            pass


# --------------------------------------------------------------- display

def load_snapshot(path=None):
    path = path or LATEST
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def describe(windows, live_ids=None, indent="  "):
    live_ids = live_ids or set()
    out = []
    for wi, w in enumerate(windows, 1):
        out.append("%s%s" % (indent, t("window_n", wi, len(w["tabs"]))))
        for ti, tb in enumerate(w["tabs"], 1):
            n = len(tb["panes"])
            head = t("tab_n", ti) + (t("splits", n) if n > 1 else "")
            out.append("%s  %s" % (indent, head))
            for p in tb["panes"]:
                cwd = (p.get("cwd") or "?").replace(HOME, "~")
                sid = p.get("session_id")
                if not sid:
                    out.append("%s      %s  %s" % (indent, cwd, t("plain_shell")))
                    continue
                mark = "*" if sid in live_ids else " "
                if p.get("match") == "cwd-fallback":
                    mark = "~"
                name = p.get("session_name") or ""
                out.append("%s    %s %s  [%s]  %s"
                           % (indent, mark, cwd, sid[:8], name))
    return "\n".join(out)


def cmd_status(args):
    live = live_claude_sessions()
    print(t("cur_header"))
    if ghostty_running():
        cur = capture(fallback=not args.no_fallback)
        print(describe(cur, set(live)))
        print("  " + t("totals", len(cur), count_tabs(cur),
                       count_panes(cur), count_sessions(cur)))
    else:
        print("  " + t("not_running"))

    snap = load_snapshot(args.file)
    print("\n" + t("snap_header"))
    if not snap:
        print("  " + t("no_snapshot"))
        return 0
    c = snap["counts"]
    print("  " + t("saved_at", snap["saved_at"]))
    print(describe(snap["windows"], set(live)))
    print("  " + t("totals", c["windows"], c["tabs"], c["panes"], c["sessions"]))
    print("\n" + t("legend"))
    return 0


def cmd_list(args):
    if not os.path.isdir(HISTORY_DIR):
        print(t("no_history"))
        return 0
    files = sorted(f for f in os.listdir(HISTORY_DIR) if f.endswith(".json"))
    if not files:
        print(t("no_history"))
        return 0
    for f in files:
        try:
            with open(os.path.join(HISTORY_DIR, f), encoding="utf-8") as fh:
                c = json.load(fh)["counts"]
            print(t("hist_line", f[:-5], c["windows"], c["tabs"],
                    c["panes"], c["sessions"]))
        except Exception:
            print("%s  (unreadable)" % f[:-5])
    print("\n" + t("history_path", HISTORY_DIR))
    return 0


# --------------------------------------------------------------- restore

_CLAUDE_BIN = []


def claude_binary(refresh=False):
    """Absolute path to the `claude` executable, or None.

    This matters more than it looks. A restored pane runs `zsh -lc ...`, which
    is a *login* shell but not an interactive one, so it never sources
    .zshrc - and .zshrc is exactly where most installs put claude on PATH.
    Calling it by bare name there yields `command not found: claude`, exit 127,
    and the `exec zsh -l` tail then hands the user a perfectly ordinary shell:
    the layout looks restored while every session is silently missing.
    """
    if _CLAUDE_BIN and not refresh:
        return _CLAUDE_BIN[0]
    _CLAUDE_BIN.clear()

    def accept(path):
        if path and os.access(path, os.X_OK) and not os.path.isdir(path):
            _CLAUDE_BIN.append(path)
            return True
        return False

    env = os.environ.get("GSESS_CLAUDE_BIN")
    if env and accept(os.path.expanduser(env)):
        return _CLAUDE_BIN[0]
    if accept(shutil.which("claude") or ""):
        return _CLAUDE_BIN[0]

    # Ask the user's own interactive shell - it does read .zshrc.
    shell = os.environ.get("SHELL") or "/bin/zsh"
    try:
        out = subprocess.run([shell, "-ic", "command -v claude"],
                             capture_output=True, text=True, timeout=20).stdout
        for line in out.splitlines():
            # shell integration may prefix escape sequences; take from the /
            if "/" in line and accept(line[line.index("/"):].strip()):
                return _CLAUDE_BIN[0]
    except Exception:
        pass

    for cand in CLAUDE_CANDIDATES:
        if accept(os.path.expanduser(cand)):
            return _CLAUDE_BIN[0]
    return None


def pane_command(pane, shell="zsh", use_flags=True, claude_bin=None):
    """Command for a pane, or None for a plain shell.

    `exec <shell> -l` after the agent means quitting Claude drops you into a
    live shell instead of closing the pane.
    """
    sid = pane.get("session_id")
    if not sid:
        return None
    argv = [claude_bin or claude_binary() or "claude", "--resume", sid]
    if use_flags:
        argv += [f for f in (pane.get("flags") or []) if isinstance(f, str)]

    # Leave the resume command behind for when Claude is quit. A pane started
    # through Ghostty's `command:` never routes through the shell's input
    # line, so unlike a hand-typed command it lands in neither the scrollback
    # nor the history - quit Claude and you face a shell with no idea what it
    # was, and no way back to the conversation.
    #
    # Printing it is not enough: `exec <shell> -l` starts an interactive shell
    # whose startup repaints the screen and wipes anything printed before it
    # (verified with oh-my-zsh). History survives that, and Up-arrow is where
    # someone actually looks. Both are emitted; history is the one that works.
    steps = [" ".join(shlex.quote(a) for a in argv)]
    display = _resume_display(sid, pane, use_flags)
    hist = _history_snippet(display, shell)
    if hist:
        steps.append(hist)
    steps.append('echo; echo "[gsess] %s"' % display)
    steps.append("exec %s -l" % shell)
    return "%s -lc %s" % (shell, shlex.quote("; ".join(steps)))


def _resume_display(sid, pane, use_flags):
    """The command to hand back to the user - safe to sit inside "..."."""
    out = "claude --resume " + sid
    extra = [f for f in (pane.get("flags") or []) if isinstance(f, str)]
    if use_flags and extra and all(
            not set(f) & set('"\\$`\'') for f in extra):
        out += " " + " ".join(extra)
    return out


def _history_snippet(display, shell):
    """Append `display` to the user's shell history file.

    zsh reads the extended `: <epoch>:<elapsed>;<cmd>` form whether or not
    EXTENDED_HISTORY is set for writing, so emitting it is safe either way.
    Uses echo rather than printf so no backslash escape has to survive being
    wrapped in the single-quoted -c argument, and only double quotes appear
    inside it.
    """
    if shell == "zsh":
        return ('H="${HISTFILE:-$HOME/.zsh_history}"; '
                'echo ": $(date +%s):0;' + display + '" >> "$H" 2>/dev/null')
    if shell == "bash":
        return ('H="${HISTFILE:-$HOME/.bash_history}"; '
                'echo "' + display + '" >> "$H" 2>/dev/null')
    return None


def surface_cfg(pane, shell="zsh", use_flags=True, claude_bin=None):
    parts = []
    cwd = pane.get("cwd")
    if cwd and os.path.isdir(cwd):
        parts.append("initial working directory:%s" % asq(cwd))
    cmd = pane_command(pane, shell, use_flags, claude_bin)
    if cmd:
        parts.append("command:%s" % asq(cmd))
    return ("{" + ", ".join(parts) + "}") if parts else None


def with_cfg(pane, shell="zsh", use_flags=True, claude_bin=None):
    cfg = surface_cfg(pane, shell, use_flags, claude_bin)
    return (" with configuration " + cfg) if cfg else ""


def plan_restore(snap, skip_ids, force, check_transcript=True):
    """Filter the snapshot down to what should actually be recreated."""
    notes, windows = [], []
    for w in snap["windows"]:
        tabs = []
        for tb in w["tabs"]:
            panes = []
            for p in tb["panes"]:
                p = dict(p)
                sid = p.get("session_id")
                if sid and not force and sid in skip_ids:
                    notes.append(t("skip_running", sid[:8],
                                   p.get("session_name") or ""))
                    p["session_id"] = None
                elif sid and check_transcript and not transcript_path(sid):
                    notes.append(t("transcript_gone", sid[:8]))
                    p["session_id"] = None
                cwd = p.get("cwd")
                if cwd and not os.path.isdir(cwd):
                    notes.append(t("dir_missing", cwd))
                panes.append(p)
            tabs.append({"panes": panes,
                         "split_plan": tb.get("split_plan")
                                       or default_split_plan(len(panes)),
                         "selected": tb.get("selected", False)})
        if tabs:
            windows.append({"tabs": tabs})
    return windows, notes


def build_script(windows, shell="zsh", scale=1.0, use_flags=True,
                 claude_bin=None):
    def d(x):
        return "  delay %.2f" % (x * scale)

    def cfg(pane):
        return with_cfg(pane, shell, use_flags, claude_bin)

    L = ['tell application "Ghostty"']
    for wi, w in enumerate(windows):
        tabs = w["tabs"]
        L.append("  set w%d to new window%s" % (wi, cfg(tabs[0]["panes"][0])))
        L.append(d(1.4))
        L.append("  set t%d_0 to selected tab of w%d" % (wi, wi))
        emit_splits(L, wi, 0, tabs[0], cfg, d)
        for ti, tb in enumerate(tabs[1:], start=1):
            L.append("  set t%d_%d to new tab in w%d%s"
                     % (wi, ti, wi, cfg(tb["panes"][0])))
            L.append(d(1.2))
            emit_splits(L, wi, ti, tb, cfg, d)
        for ti, tb in enumerate(tabs):
            if tb.get("selected"):
                L.append("  select tab t%d_%d" % (wi, ti))
                break
    if windows:
        L.append("  activate window w0")
    L.append("end tell")
    return "\n".join(L)


def emit_splits(L, wi, ti, tab, cfg, d):
    panes = tab["panes"]
    if len(panes) <= 1:
        return
    L.append("  set s%d_%d_0 to focused terminal of t%d_%d" % (wi, ti, wi, ti))
    for k, step in enumerate(tab["split_plan"], start=1):
        if k >= len(panes):
            break
        parent, direction = step[0], step[1]
        if parent >= k:                  # can only split a pane that exists
            parent = 0
        L.append("  set s%d_%d_%d to split s%d_%d_%d direction %s%s"
                 % (wi, ti, k, wi, ti, parent, direction, cfg(panes[k])))
        L.append(d(0.9))


def window_ids():
    try:
        out = osa('tell application "Ghostty" to get id of every window')
    except GsessError:
        return []
    return [x.strip() for x in out.strip().split(",") if x.strip()]


def cmd_restore(args):
    snap = load_snapshot(args.file)
    if not snap:
        print(t("no_snapshot"))
        return 1

    live = live_claude_sessions()
    windows, notes = plan_restore(snap, set(live), args.force)

    print(t("saved_at", snap["saved_at"]))
    print(describe(windows))
    print(t("will_restore", len(windows), count_tabs(windows),
            count_panes(windows), count_sessions(windows)))
    for n in dict.fromkeys(notes):
        print("  ! " + n)

    exe = claude_binary()
    if count_sessions(windows) and not exe:
        print(t("no_claude_bin"), file=sys.stderr)
        return 1
    if exe and not args.quiet:
        print(t("using_claude", exe))

    script = build_script(windows, args.shell, args.delay_scale,
                          use_flags=not args.no_flags, claude_bin=exe)

    if args.dry_run:
        print("\n" + t("dry_run"))
        print(script)
        return 0

    if count_sessions(windows) == 0 and not args.force:
        print(t("nothing_to_restore"))
        return 0

    started_by_us = False
    if not ghostty_running():
        print("\n" + t("launching"))
        subprocess.run(["open", "-a", "Ghostty"])
        started_by_us = True
        for _ in range(40):
            time.sleep(0.5)
            if ghostty_running() and window_ids():
                break
        else:
            print(t("launch_timeout"))
            return 1
        time.sleep(1.0)
    pre_ids = set(window_ids()) if started_by_us else set()

    print("\n" + t("restoring"))
    osa(script)

    if pre_ids:                 # drop the blank window Ghostty opened on launch
        time.sleep(0.8)
        close_empty_windows(pre_ids)

    print(t("done"))
    return 0


CLOSE_WINDOW = '''
tell application "Ghostty"
  repeat with w in windows
    if (id of w) is %s then
      close window w
      exit repeat
    end if
  end repeat
end tell
'''


def close_empty_windows(ids):
    """Close the blank window Ghostty opens on launch.

    Re-reads the live tree and only closes a window that is still one tab,
    one pane, with nothing resumable in it - never guesses from the title.
    """
    try:
        windows = parse_enum(osa(ENUM_SCRIPT), live_claude_sessions())
    except GsessError:
        return
    for w in windows:
        if w["window_id"] not in ids:
            continue
        if len(w["tabs"]) != 1 or len(w["tabs"][0]["panes"]) != 1:
            continue
        if w["tabs"][0]["panes"][0].get("match") != "none":
            continue
        try:
            osa(CLOSE_WINDOW % asq(w["window_id"]))
        except GsessError:
            pass


# --------------------------------------------------------------- CLI

def build_parser():
    ap = argparse.ArgumentParser(
        prog="gsess",
        description="Save and restore Ghostty windows/tabs/splits including "
                    "the Claude Code session in each pane.")
    ap.add_argument("--version", action="version",
                    version="gsess " + __version__)
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("save", help="snapshot the current workspace")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--force", action="store_true",
                   help="overwrite even when no session was found")
    s.add_argument("--keep", type=int, default=20,
                   help="how many history snapshots to keep (default 20)")
    s.add_argument("--no-fallback", action="store_true",
                   help="do not guess sessions by working directory")
    s.set_defaults(func=cmd_save)

    s = sub.add_parser("status", help="current workspace vs latest snapshot")
    s.add_argument("--file")
    s.add_argument("--no-fallback", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("list", help="snapshot history")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("restore", help="recreate the workspace")
    s.add_argument("--file")
    s.add_argument("--dry-run", action="store_true",
                   help="print the AppleScript, run nothing")
    s.add_argument("--force", action="store_true",
                   help="also restore sessions that are already running")
    s.add_argument("--shell", default=os.path.basename(
        os.environ.get("SHELL", "zsh")) or "zsh")
    s.add_argument("--delay-scale", type=float, default=1.0,
                   help="multiply the built-in delays on slow machines")
    s.add_argument("--no-flags", action="store_true",
                   help="do not replay the CLI flags each session ran with")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_restore)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    try:
        return args.func(args)
    except GsessError as e:
        print(t("err", e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
