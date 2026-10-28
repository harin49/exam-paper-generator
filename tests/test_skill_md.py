"""Guards for the plugin's files: SKILL.md names every script by its full path inside the skill, every
file it names exists, agents are started by type, and the plugin manifests agree.
Run from the project root:
    python3 -m unittest discover tests
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "exam-papers")
SKILL_DIR = os.path.join(PLUGIN, "skills", "make-paper")
AGENTS = os.path.join(PLUGIN, "agents")

with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
    TEXT = f.read()
with open(os.path.join(SKILL_DIR, "workflow.json"), encoding="utf-8") as f:
    WORKFLOW = f.read()

# A file inside the skill, named as ${CLAUDE_SKILL_DIR}/some/path.ext
SKILL_PATH_RE = re.compile(r"\$\{CLAUDE_SKILL_DIR\}/([\w./-]+\.(?:py|md|json))")
SCRIPTS = sorted(f for f in os.listdir(os.path.join(SKILL_DIR, "scripts")) if f.endswith(".py"))


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class SkillMd(unittest.TestCase):
    def test_frontmatter_name_matches_the_folder(self):
        self.assertIn("\nname: make-paper\n", TEXT.split("---")[1] + "\n")

    def test_every_named_skill_file_exists(self):
        for text in (TEXT, WORKFLOW):
            missing = [p for p in sorted(set(SKILL_PATH_RE.findall(text)))
                       if not os.path.exists(os.path.join(SKILL_DIR, p))]
            self.assertEqual(missing, [])

    def test_every_script_is_named_by_its_full_path(self):
        unnamed = [s for s in SCRIPTS if "${CLAUDE_SKILL_DIR}/scripts/" + s not in TEXT]
        self.assertEqual(unnamed, [])

    def test_no_old_repo_paths(self):
        for text in (TEXT, WORKFLOW):
            self.assertEqual(re.findall(r"\bskill/(?:scripts|schemas|references)/", text), [])
            self.assertNotIn("output/", text)

    def test_every_command_runs_a_script_inside_the_skill(self):
        for text in (TEXT, WORKFLOW.replace('\\"', '"')):
            cmds = re.findall(r"python3 (\S+)", text)
            self.assertTrue(cmds)
            for c in cmds:
                if c == '"RENDER_REVIEW"':
                    continue
                m = re.fullmatch(r'"\$\{CLAUDE_SKILL_DIR\}/(scripts/\w+\.py)"', c)
                self.assertTrue(m, c)
                self.assertTrue(os.path.isfile(os.path.join(SKILL_DIR, m.group(1))), c)

    def test_steps_are_recorded_with_done(self):
        self.assertIn('"${CLAUDE_SKILL_DIR}/scripts/next_step.py" TASK --done STEP_ID', TEXT)

    def test_agents_are_started_by_type_not_pasted(self):
        # Pasting an agent file into a general-purpose subagent drops its tool limits.
        for text in (TEXT, WORKFLOW):
            self.assertNotIn("full text of", text)
        for name in ("blind-solver", "reviewer"):
            self.assertIn(f"`exam-papers:{name}` subagent by its type", TEXT)
            self.assertIn(f"exam-papers:{name} subagent by its type", WORKFLOW)


class AgentFiles(unittest.TestCase):
    def test_blind_solver_prompt_names_no_other_file(self):
        with open(os.path.join(AGENTS, "blind-solver.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(re.findall(r"`[\w/.-]+\.(?:md|py)`", text), [])

    def test_agent_tools_are_limited(self):
        for name in ("blind-solver", "reviewer"):
            with open(os.path.join(AGENTS, f"{name}.md"), encoding="utf-8") as f:
                head = f.read().split("---")[1]
            self.assertIn(f"name: {name}", head)
            self.assertIn("tools: Read, Write, Bash", head, name)

    def test_agents_name_no_repo_paths(self):
        # Agents run from the teacher's workspace; they get every path in their prompt.
        for name in ("blind-solver", "reviewer"):
            with open(os.path.join(AGENTS, f"{name}.md"), encoding="utf-8") as f:
                self.assertEqual(re.findall(r"\bskill/\w+/", f.read()), [], name)


class Manifests(unittest.TestCase):
    def test_marketplace_lists_the_plugin_by_its_manifest_name(self):
        market = load(os.path.join(ROOT, ".claude-plugin", "marketplace.json"))
        plugin = load(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"))
        self.assertEqual(plugin["name"], "exam-papers")
        entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
        self.assertEqual(os.path.normpath(os.path.join(ROOT, entry["source"])), PLUGIN)
        self.assertNotIn("..", entry["source"])

    def test_no_top_level_bin(self):
        # A top-level bin/ makes Cowork and claude.ai refuse the whole plugin.
        self.assertFalse(os.path.exists(os.path.join(PLUGIN, "bin")))


if __name__ == "__main__":
    unittest.main()
