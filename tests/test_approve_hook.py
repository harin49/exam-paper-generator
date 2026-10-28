"""Tests for the plugin's hooks (hooks/approve.py, hooks/guard_agents.py), each run as Claude Code
runs it: a separate process given the hook's JSON on stdin. Run from the project root:
    python3 -m unittest discover tests
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "exam-papers")
HOOK = os.path.join(PLUGIN, "hooks", "approve.py")
sys.path.insert(0, os.path.join(PLUGIN, "skills", "make-paper", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import TEST_DATA, load_json  # noqa: E402
import next_step as ns  # noqa: E402
from approvals import is_approved, read_approvals  # noqa: E402

STEPS = ns.read_workflow(ns.WORKFLOW)


class Hook(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def run_hook(self, event):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.root, CLAUDE_PLUGIN_ROOT=PLUGIN)
        run = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True,
                             text=True, env=env, cwd=self.root)
        self.assertEqual(run.returncode, 0, run.stderr)
        return run.stdout.strip()


class Approve(Hook):
    def task_waiting_for_blueprint(self, name="icse-9-physics"):
        folder = os.path.join(self.root, "papers", name)
        os.makedirs(folder)
        for f in ("spec.json", "blueprint.json", "concepts.json"):
            shutil.copy(os.path.join(TEST_DATA, f), folder)
        self.assertIsNone(ns.record_done(folder, STEPS, "make_blueprint"))
        return folder

    def typed(self, args, **extra):
        return self.run_hook(dict({"hook_event_name": "UserPromptExpansion",
                                   "prompt": f"/exam-papers:approve {args}".strip(),
                                   "command_name": "exam-papers:approve", "command_source": "plugin",
                                   "expansion_type": "slash_command", "cwd": self.root}, **extra))

    def blocked(self, out):
        doc = json.loads(out)
        self.assertEqual(doc["decision"], "block")
        return doc["reason"]

    def test_records_the_one_waiting_task(self):
        folder = self.task_waiting_for_blueprint()
        out = self.typed("blueprint")
        self.assertIn("Approval recorded", out)
        self.assertTrue(is_approved(folder, "blueprint"))
        record = read_approvals(folder)[0]
        self.assertEqual((record["gate"], record["file"], record["command"]),
                         ("blueprint", "blueprint.json", "/exam-papers:approve blueprint"))
        self.assertEqual(ns.next_step(folder, STEPS)[1]["id"], "draft_questions")
        with open(os.path.join(folder, "run.jsonl"), encoding="utf-8") as f:
            self.assertEqual([json.loads(x)["event"] for x in f], ["done", "approved"])

    def test_text_before_the_command_is_ignored(self):
        # The app may put other text in front of what the user typed.
        folder = self.task_waiting_for_blueprint()
        self.typed("blueprint", prompt="<system-reminder>x</system-reminder>\n/exam-papers:approve blueprint")
        self.assertTrue(is_approved(folder, "blueprint"))

    def test_no_waiting_task_is_blocked(self):
        self.assertIn("No paper", self.blocked(self.typed("blueprint")))

    def test_a_gate_that_is_not_next_is_blocked(self):
        folder = self.task_waiting_for_blueprint()
        self.assertIn("No paper", self.blocked(self.typed("paper")))
        self.assertEqual(read_approvals(folder), [])

    def test_several_waiting_tasks_need_a_folder(self):
        self.task_waiting_for_blueprint("a")
        b = self.task_waiting_for_blueprint("b")
        self.assertIn("a, b", self.blocked(self.typed("blueprint")))
        self.assertIn("Approval recorded", self.typed("blueprint b"))
        self.assertTrue(is_approved(b, "blueprint"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "papers", "a", "approvals.json")))

    def test_a_named_folder_that_is_not_waiting_is_blocked(self):
        self.task_waiting_for_blueprint("a")
        self.assertIn("nope is not waiting", self.blocked(self.typed("blueprint nope")))

    def test_bad_arguments_show_the_usage(self):
        self.task_waiting_for_blueprint()
        for args in ("", "concepts", "blueprint a b"):
            self.assertIn("Type /exam-papers:approve", self.blocked(self.typed(args)), args)

    def test_a_subagent_cannot_approve(self):
        folder = self.task_waiting_for_blueprint()
        self.assertIn("teacher types", self.blocked(self.typed("blueprint", agent_id="a1")))
        self.assertFalse(is_approved(folder, "blueprint"))

    def test_other_commands_are_left_alone(self):
        folder = self.task_waiting_for_blueprint()
        self.assertEqual(self.typed("blueprint", command_name="exam-papers:make-paper"), "")
        self.assertFalse(is_approved(folder, "blueprint"))


class Guard(Hook):
    def tool(self, name, **tool_input):
        out = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input})
        if not out:
            return None
        doc = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(doc["hookEventName"], "PreToolUse")
        return doc["permissionDecision"]

    def test_writing_approvals_is_denied(self):
        path = os.path.join(self.root, "papers", "x", "approvals.json")
        self.assertEqual(self.tool("Write", file_path=path, content="[]"), "deny")
        self.assertEqual(self.tool("Edit", file_path=path, old_string="a", new_string="b"), "deny")

    def test_bash_that_mentions_approvals_is_denied(self):
        self.assertEqual(self.tool("Bash", command="echo [] > papers/x/approvals.json"), "deny")
        self.assertEqual(self.tool("Bash", command="cat papers/x/approvals.json 2>&1"), "deny")

    def test_other_files_and_commands_are_allowed(self):
        self.assertIsNone(self.tool("Write", file_path=os.path.join(self.root, "questions.json"), content=""))
        self.assertIsNone(self.tool("Bash", command="ls 2>&1"))


class AgentGuard(unittest.TestCase):
    """hooks/guard_agents.py, run as a separate process like the approval hook."""

    def call(self, agent_type, tool, **tool_input):
        event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
        if agent_type:
            event.update(agent_id="a1", agent_type=agent_type)
        run = subprocess.run([sys.executable, os.path.join(PLUGIN, "hooks", "guard_agents.py")],
                             input=json.dumps(event), capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)["hookSpecificOutput"]["permissionDecision"] if run.stdout.strip() else None

    def test_solver_sees_only_the_blind_paper(self):
        solver = "exam-papers:blind-solver"
        self.assertIsNone(self.call(solver, "Read", file_path="/t/review/solver-input.json"))
        self.assertIsNone(self.call(solver, "Write", file_path="/t/review/solver-answers.json", content="{}"))
        self.assertIsNone(self.call(solver, "Bash", command="python3 -c 'print(8*5)'"))
        self.assertEqual(self.call(solver, "Read", file_path="/t/questions.json"), "deny")
        self.assertEqual(self.call(solver, "Read", file_path="/t/review/compare-output.txt"), "deny")
        self.assertEqual(self.call(solver, "Write", file_path="/t/questions.json", content=""), "deny")
        self.assertEqual(self.call(solver, "Bash", command="cat ../questions.json"), "deny")
        self.assertEqual(self.call(solver, "Grep", pattern="answer", path="/t"), "deny")

    def test_writer_never_sees_the_solver(self):
        writer = "exam-papers:writer"
        self.assertIsNone(self.call(writer, "Read", file_path="/t/review/reviewer-report.json"))
        self.assertIsNone(self.call(writer, "Edit", file_path="/t/questions.json", old_string="a", new_string="b"))
        self.assertEqual(self.call(writer, "Read", file_path="/t/review/solver-answers.json"), "deny")
        self.assertEqual(self.call(writer, "Read", file_path="/t/review/compare-output.txt"), "deny")
        self.assertEqual(self.call(writer, "Bash", command="cat review/compare-output.txt"), "deny")
        self.assertEqual(self.call(writer, "Write", file_path="/t/blueprint.json", content=""), "deny")

    def test_main_claude_and_the_reviewer_are_not_limited(self):
        for agent in (None, "exam-papers:reviewer"):
            self.assertIsNone(self.call(agent, "Read", file_path="/t/review/solver-answers.json"))
            self.assertIsNone(self.call(agent, "Read", file_path="/t/questions.json"))


class PluginFiles(unittest.TestCase):
    def test_hooks_run_scripts_that_exist(self):
        doc = load_json(os.path.join(PLUGIN, "hooks", "hooks.json"))
        args = [a for groups in doc["hooks"].values() for g in groups for h in g["hooks"] for a in h["args"]]
        self.assertTrue(args)
        for a in args:
            self.assertTrue(os.path.isfile(a.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN)), a)
        self.assertEqual(set(doc["hooks"]), {"UserPromptExpansion", "PreToolUse"})
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/guard_agents.py", args)

    def test_approve_command_cannot_be_run_by_claude(self):
        with open(os.path.join(PLUGIN, "commands", "approve.md"), encoding="utf-8") as f:
            head = f.read().split("---")[1]
        self.assertIn("disable-model-invocation: true", head)

    def test_every_approval_gate_in_the_workflow_has_a_step_id_the_hook_finds(self):
        gates = re.findall(r'"approved": "(\w+)"', json.dumps(STEPS))
        self.assertEqual(sorted(gates), ["blueprint", "paper"])
        for g in gates:
            self.assertIn(f"approve_{g}", [s["id"] for s in STEPS])


if __name__ == "__main__":
    unittest.main()
