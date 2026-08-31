# -*- coding: utf-8 -*-
"""Unit tests for gsess.

Everything here is pure logic: the AppleScript dump is fed in as a string and
the Claude session store is passed in as a dict, so the suite runs anywhere -
no Ghostty, no macOS, no ~/.claude required.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gsess  # noqa: E402

FS, RS = gsess.FS, gsess.RS

SID_A = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
SID_B = "9f8e7d6c-5b4a-4392-8817-6f5e4d3c2b1a"
CWD = "/Users/x/code/proj"


def rec(w_ord, w_id, t_idx, t_id, t_name, t_sel, s_ord, s_id, cwd, s_name):
    return FS.join([str(w_ord), w_id, str(t_idx), t_id, t_name, t_sel,
                    str(s_ord), s_id, cwd, s_name]) + RS


def title(name, sid):
    """Reproduce Claude Code's terminal title: '<dir> - <name> - <sid16>'."""
    return "proj · %s · %s" % (name, sid[:16])


class TestTitleParsing(unittest.TestCase):
    def test_extracts_prefix_from_claude_title(self):
        m = gsess.SID_TAIL.search(title("white river", SID_A))
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), SID_A[:16])

    def test_ignores_plain_shell_title(self):
        self.assertIsNone(gsess.SID_TAIL.search("~/code/proj"))

    def test_handles_cjk_and_truncated_prompt(self):
        m = gsess.SID_TAIL.search("dashboard · 我现在要 · " + SID_B[:16])
        self.assertEqual(m.group(1), SID_B[:16])


class TestParseEnum(unittest.TestCase):
    def test_two_panes_same_directory_are_told_apart(self):
        """The case directory-based tools get wrong."""
        raw = (rec(1, "w1", 1, "t1", "tab", "true", 1, "s1", CWD,
                   title("alpha", SID_A))
               + rec(1, "w1", 1, "t1", "tab", "true", 2, "s2", CWD,
                     title("beta", SID_B)))
        live = {
            SID_A: {"session_id": SID_A, "cwd": CWD, "name": "alpha", "pid": 1},
            SID_B: {"session_id": SID_B, "cwd": CWD, "name": "beta", "pid": 2},
        }
        win = gsess.parse_enum(raw, live)
        panes = win[0]["tabs"][0]["panes"]
        self.assertEqual([p["session_id"] for p in panes], [SID_A, SID_B])
        self.assertEqual([p["session_name"] for p in panes], ["alpha", "beta"])
        self.assertTrue(all(p["match"] == "live+title" for p in panes))

    def test_dead_session_resolved_via_transcript(self):
        raw = rec(1, "w1", 1, "t1", "tab", "true", 1, "s1", CWD,
                  title("gone", SID_A))
        win = gsess.parse_enum(raw, {}, resolver=lambda p: SID_A)
        pane = win[0]["tabs"][0]["panes"][0]
        self.assertEqual(pane["session_id"], SID_A)
        self.assertEqual(pane["match"], "title+transcript")

    def test_unresolvable_prefix_is_flagged_not_guessed(self):
        raw = rec(1, "w1", 1, "t1", "tab", "true", 1, "s1", CWD,
                  title("gone", SID_A))
        win = gsess.parse_enum(raw, {}, resolver=lambda p: None)
        pane = win[0]["tabs"][0]["panes"][0]
        self.assertIsNone(pane["session_id"])
        self.assertEqual(pane["match"], "title-only")
        self.assertEqual(pane["session_id_prefix"], SID_A[:16])

    def test_plain_shell_pane(self):
        raw = rec(1, "w1", 1, "t1", "tab", "true", 1, "s1", CWD, "~/code/proj")
        pane = gsess.parse_enum(raw, {})[0]["tabs"][0]["panes"][0]
        self.assertIsNone(pane["session_id"])
        self.assertEqual(pane["match"], "none")

    def test_tab_and_window_grouping_and_order(self):
        raw = (rec(1, "w1", 2, "t2", "second", "true", 1, "sB", CWD, "b")
               + rec(1, "w1", 1, "t1", "first", "false", 1, "sA", CWD, "a")
               + rec(2, "w2", 1, "t3", "other", "true", 1, "sC", CWD, "c"))
        win = gsess.parse_enum(raw, {})
        self.assertEqual(len(win), 2)
        self.assertEqual([t["title"] for t in win[0]["tabs"]],
                         ["first", "second"])   # sorted by tab index
        self.assertTrue(win[0]["tabs"][1]["selected"])
        self.assertEqual(len(win[1]["tabs"]), 1)

    def test_malformed_lines_are_skipped(self):
        raw = "garbage" + RS + rec(1, "w1", 1, "t1", "tab", "true", 1, "s1",
                                   CWD, "x") + RS
        self.assertEqual(len(gsess.parse_enum(raw, {})), 1)


class TestCwdFallback(unittest.TestCase):
    def test_fills_unmatched_pane_and_flags_it(self):
        raw = rec(1, "w1", 1, "t1", "tab", "true", 1, "s1", CWD, "~/code/proj")
        live = {SID_A: {"session_id": SID_A, "cwd": CWD, "name": "a", "pid": 1}}
        win = gsess.apply_cwd_fallback(gsess.parse_enum(raw, {}), live)
        pane = win[0]["tabs"][0]["panes"][0]
        self.assertEqual(pane["session_id"], SID_A)
        self.assertEqual(pane["match"], "cwd-fallback")

    def test_never_steals_a_session_already_matched(self):
        raw = (rec(1, "w1", 1, "t1", "tab", "true", 1, "s1", CWD,
                   title("alpha", SID_A))
               + rec(1, "w1", 1, "t1", "tab", "true", 2, "s2", CWD, "plain"))
        live = {SID_A: {"session_id": SID_A, "cwd": CWD, "name": "a", "pid": 1}}
        win = gsess.apply_cwd_fallback(gsess.parse_enum(raw, live), live)
        panes = win[0]["tabs"][0]["panes"]
        self.assertEqual(panes[0]["session_id"], SID_A)
        self.assertIsNone(panes[1]["session_id"])   # nothing left to hand out


class TestSplitPlan(unittest.TestCase):
    def test_lengths(self):
        for n in range(1, 8):
            self.assertEqual(len(gsess.default_split_plan(n)), max(0, n - 1))

    def test_four_panes_form_a_grid(self):
        self.assertEqual(gsess.default_split_plan(4),
                         [[0, "right"], [0, "down"], [1, "down"]])

    def test_parent_always_exists_when_emitted(self):
        for n in range(2, 8):
            for k, (parent, _) in enumerate(gsess.default_split_plan(n), start=1):
                self.assertLess(parent, k, "pane %d split before it exists" % parent)


class TestQuoting(unittest.TestCase):
    def test_escapes_quotes_and_backslashes(self):
        self.assertEqual(gsess.asq('a"b'), '"a\\"b"')
        self.assertEqual(gsess.asq("a\\b"), '"a\\\\b"')

    def test_path_with_space_and_quote_survives(self):
        out = gsess.asq('/Users/x/my "dir"/p')
        self.assertTrue(out.startswith('"') and out.endswith('"'))
        self.assertNotIn('""', out)


class TestCommandGeneration(unittest.TestCase):
    def test_plain_shell_gets_no_command(self):
        self.assertIsNone(gsess.pane_command({"session_id": None}))

    def test_resume_command_shape(self):
        cmd = gsess.pane_command({"session_id": SID_A})
        self.assertIn("claude --resume " + SID_A, cmd)
        self.assertIn("exec zsh -l", cmd)     # quitting claude keeps the pane

    def test_respects_shell(self):
        self.assertTrue(gsess.pane_command({"session_id": SID_A},
                                           shell="bash").startswith("bash -lc "))

    def test_cfg_omits_missing_directory(self):
        cfg = gsess.surface_cfg({"session_id": None, "cwd": "/no/such/dir"})
        self.assertIsNone(cfg)

    def test_cfg_includes_existing_directory(self):
        cfg = gsess.surface_cfg({"session_id": None, "cwd": "/tmp"})
        self.assertIn("initial working directory", cfg)


class TestPlanRestore(unittest.TestCase):
    def snap(self, sid):
        return {"windows": [{"tabs": [{"panes": [
            {"cwd": "/tmp", "session_id": sid, "session_name": "n"}],
            "split_plan": [], "selected": True}]}]}

    def test_skips_session_already_running(self):
        win, notes = gsess.plan_restore(self.snap(SID_A), {SID_A}, force=False,
                                        check_transcript=False)
        self.assertIsNone(win[0]["tabs"][0]["panes"][0]["session_id"])
        self.assertTrue(any("skip" in n.lower() or "跳过" in n for n in notes))

    def test_force_keeps_running_session(self):
        win, _ = gsess.plan_restore(self.snap(SID_A), {SID_A}, force=True,
                                    check_transcript=False)
        self.assertEqual(win[0]["tabs"][0]["panes"][0]["session_id"], SID_A)

    def test_does_not_mutate_the_snapshot(self):
        snap = self.snap(SID_A)
        gsess.plan_restore(snap, {SID_A}, force=False, check_transcript=False)
        self.assertEqual(snap["windows"][0]["tabs"][0]["panes"][0]["session_id"],
                         SID_A)


class TestBuildScript(unittest.TestCase):
    def windows(self):
        pane = lambda sid: {"cwd": "/tmp", "session_id": sid}
        return [{"tabs": [
            {"panes": [pane(SID_A), pane(SID_B)],
             "split_plan": [[0, "right"]], "selected": False},
            {"panes": [pane(None)], "split_plan": [], "selected": True},
        ]}]

    def test_script_shape(self):
        s = gsess.build_script(self.windows())
        self.assertTrue(s.startswith('tell application "Ghostty"'))
        self.assertTrue(s.rstrip().endswith("end tell"))
        self.assertEqual(s.count("new window"), 1)
        self.assertEqual(s.count("new tab in w0"), 1)
        self.assertEqual(s.count(" split "), 1)
        self.assertIn("select tab t0_1", s)      # the selected tab
        self.assertIn("activate window w0", s)

    def test_both_sessions_are_resumed(self):
        s = gsess.build_script(self.windows())
        self.assertIn(SID_A, s)
        self.assertIn(SID_B, s)

    def test_delay_scale(self):
        base = gsess.build_script(self.windows(), scale=1.0)
        slow = gsess.build_script(self.windows(), scale=2.0)
        self.assertIn("delay 1.40", base)
        self.assertIn("delay 2.80", slow)

    def test_empty_input_is_valid_script(self):
        s = gsess.build_script([])
        self.assertNotIn("activate window", s)
        self.assertTrue(s.rstrip().endswith("end tell"))


class TestExtractFlags(unittest.TestCase):
    def test_session_selection_flags_are_dropped(self):
        for cmd in ("claude --resume abc", "claude -r abc", "claude --continue",
                    "claude -c", "claude --resume", "claude --fork-session"):
            self.assertEqual(gsess.extract_flags(cmd), [], cmd)

    def test_value_flags_survive_with_their_value(self):
        self.assertEqual(
            gsess.extract_flags("claude --continue --model sonnet"),
            ["--model", "sonnet"])

    def test_boolean_flags_survive(self):
        self.assertIn("--dangerously-skip-permissions",
                      gsess.extract_flags(
                          "claude -r x --dangerously-skip-permissions"))

    def test_inline_value_form(self):
        self.assertEqual(gsess.extract_flags("claude --effort=max"),
                         ["--effort=max"])

    def test_initial_prompt_is_not_replayed(self):
        """Replaying a positional prompt would re-send it to the model."""
        self.assertEqual(
            gsess.extract_flags("claude write me a function --model opus"),
            ["--model", "opus"])

    def test_absolute_executable_path(self):
        self.assertEqual(gsess.extract_flags("/opt/bin/claude --chrome"),
                         ["--chrome"])

    def test_unparsable_line_is_not_fatal(self):
        self.assertEqual(gsess.extract_flags('claude --model "unclosed'), [])


class TestFlagReplay(unittest.TestCase):
    PANE = {"session_id": SID_A, "cwd": "/tmp",
            "flags": ["--model", "sonnet", "--chrome"]}

    def test_flags_are_replayed_in_order(self):
        cmd = gsess.pane_command(self.PANE)
        self.assertIn("claude --resume %s --model sonnet --chrome" % SID_A, cmd)

    def test_no_flags_switch(self):
        cmd = gsess.pane_command(self.PANE, use_flags=False)
        self.assertNotIn("--model", cmd)

    def test_argv_string_includes_cd(self):
        line = gsess.pane_argv_string(self.PANE)
        self.assertTrue(line.startswith("cd /tmp && claude --resume "))
        self.assertIn("--model sonnet", line)

    def test_argv_string_empty_without_session(self):
        self.assertEqual(gsess.pane_argv_string({"session_id": None}), "")

    def test_flag_with_space_is_quoted(self):
        cmd = gsess.pane_command({"session_id": SID_A,
                                  "flags": ["--add-dir", "/a b/c"]})
        self.assertIn("'/a b/c'", cmd)


class TestEnvTagging(unittest.TestCase):
    def test_env_reaches_the_configuration(self):
        cfg = gsess.surface_cfg({"session_id": SID_A, "cwd": "/tmp"},
                                env=["GSESS_RESTORED=1"])
        self.assertIn('environment variables:{"GSESS_RESTORED=1"}', cfg)

    def test_no_env_by_default(self):
        cfg = gsess.surface_cfg({"session_id": SID_A, "cwd": "/tmp"})
        self.assertNotIn("environment variables", cfg)


class TestReuseFrontWindow(unittest.TestCase):
    def windows(self):
        pane = lambda sid: {"cwd": "/tmp", "session_id": sid}
        return [{"tabs": [
            {"panes": [pane(SID_A), pane(SID_B)],
             "split_plan": [[0, "right"]], "selected": True},
            {"panes": [pane(None)], "split_plan": [], "selected": False},
        ]}]

    def test_adopts_the_existing_window_instead_of_creating_one(self):
        s = gsess.build_script(self.windows(), reuse_front=True)
        self.assertIn("set w0 to front window", s)
        self.assertNotIn("new window", s)
        self.assertNotIn("activate window", s)   # we are already in it

    def test_first_pane_is_left_to_the_caller_but_split_still_happens(self):
        s = gsess.build_script(self.windows(), reuse_front=True)
        self.assertNotIn(SID_A, s)      # the shell runs this one
        self.assertIn(SID_B, s)         # split off the adopted pane
        self.assertEqual(s.count(" split "), 1)

    def test_remaining_tabs_go_into_the_adopted_window(self):
        s = gsess.build_script(self.windows(), reuse_front=True)
        self.assertIn("new tab in w0", s)

    def test_normal_mode_still_creates_the_window(self):
        s = gsess.build_script(self.windows(), reuse_front=False)
        self.assertIn("new window", s)
        self.assertIn(SID_A, s)


class TestCounting(unittest.TestCase):
    def test_counts(self):
        raw = (rec(1, "w1", 1, "t1", "a", "true", 1, "s1", CWD,
                   title("x", SID_A))
               + rec(1, "w1", 1, "t1", "a", "true", 2, "s2", CWD, "plain")
               + rec(1, "w1", 2, "t2", "b", "false", 1, "s3", CWD,
                     title("y", SID_B)))
        win = gsess.parse_enum(raw, {}, resolver=lambda p: None)
        self.assertEqual(gsess.count_tabs(win), 2)
        self.assertEqual(gsess.count_panes(win), 3)
        self.assertEqual(gsess.count_sessions(win), 0)   # unresolvable prefixes


if __name__ == "__main__":
    unittest.main(verbosity=2)
