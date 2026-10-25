"""
Tests for setup.py — a project set up for the factory, greenfield and brownfield, in throwaway
folders. No model, no network.

    python -m unittest test_setup -v        (from the kit folder)
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
sys.dont_write_bytecode = True
import setup  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx_from_markdown(md: Path, target: Path) -> Path:
    """A minimal .docx: '#' headings become Heading<n> paragraphs, the rest body text."""
    body = []
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            body.append(f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr><w:r><w:t>{escape(line[level:].strip())}</w:t></w:r></w:p>')
        elif line.strip():
            body.append(f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>')
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{"".join(body)}</w:body></w:document>')
    return target


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, encoding="utf-8").stdout.strip()


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="factory-setup-test-")
        self.tmp = Path(self.folder.name)
        self.fsd = docx_from_markdown(KIT / "samples" / "shop-fsd.md", self.tmp / "shop-fsd.docx")
        # A git identity for the throwaway repositories, never the person's own configuration.
        self.environ = dict(os.environ)
        os.environ.update({"GIT_CONFIG_GLOBAL": str(self.tmp / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"})
        (self.tmp / "gitconfig").write_text("[user]\n\tname = Setup Test\n\temail = setup@example.invalid\n"
                                            "[core]\n\tautocrlf = false\n", encoding="utf-8")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.environ)
        self.folder.cleanup()

    def setup(self, *argv: str) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = setup.main([*argv, "--json"])
        return code, json.loads(out.getvalue())

    def greenfield(self, name: str = "shop") -> tuple[int, dict]:
        return self.setup("--greenfield", "--dir", str(self.tmp / name), "--name", "Shop", "--fsd", str(self.fsd),
                          "--stack", "pytest")

    def test_greenfield_makes_the_folder_installs_files_the_fsd_and_commits(self):
        code, result = self.greenfield()
        self.assertEqual(code, 0, result)
        repo = self.tmp / "shop"
        self.assertEqual((result["mode"], result["branch"], result["fsd"]), ("greenfield", "main", "requirements/fsd/Shop - V1.docx"))
        self.assertEqual(git(repo, "branch", "--show-current"), "main")
        self.assertEqual(git(repo, "status", "--porcelain"), "", "everything the setup wrote is committed")
        self.assertEqual(git(repo, "log", "--format=%s"), "Set up the AI factory (pytest) and file the FSD as V1")
        for rel in ("devtools/factory/factory.py", "devtools/factory/fsd_outline.py", "devtools/factory/check_project_md.py",
                    ".claude/agents/book-auditor.md", "devtools/factory/prompts/book-features.md", "docs/project.md"):
            self.assertTrue((repo / rel).is_file(), rel)
        self.assertEqual((repo / "requirements/fsd/Shop - V1.docx").read_bytes(), self.fsd.read_bytes())
        project = (repo / "docs/project.md").read_text(encoding="utf-8")
        self.assertIn("`requirements/fsd/Shop - V1.docx` is V1, filed at project setup", project)
        self.assertIn("No remote yet", project)
        self.assertNotIn("FILL: the remote", project)
        self.assertIn("Shop - V1.docx", (repo / "requirements/read-me.txt").read_text(encoding="utf-8"))
        self.assertIn("start book:project --title \"Book from FSD V1\" --new-branch", "\n".join(result["next"]))
        config = (repo / "devtools/factory/factory.toml").read_text(encoding="utf-8")
        self.assertIn('base_ref = "main"', config)
        version = setup.load_init().VERSION
        self.assertIn(f'kit_version = "{version}"', config, "the kit's release is stamped at the top")
        self.assertEqual(result["kit_version"], version)

    def test_the_install_turns_the_git_hooks_on_with_the_checks_the_agent_and_the_testing_rules(self):
        code, result = self.greenfield()
        self.assertEqual(code, 0, result)
        repo = self.tmp / "shop"
        for rel in (".githooks/pre-commit", ".githooks/commit-msg", "devtools/checks/check-commit-msg.py",
                    "devtools/checks/check-protected-paths.py", "devtools/checks/check-rules.py",
                    "devtools/checks/check-test-results.py", ".claude/agents/factory-spec-auditor.md", "tests/CLAUDE.md"):
            self.assertTrue((repo / rel).is_file(), rel)
        self.assertEqual(git(repo, "config", "--get", "core.hooksPath"), ".githooks")
        modes = git(repo, "ls-files", "-s", ".githooks").splitlines()
        self.assertTrue(modes and all(line.startswith("100755 ") for line in modes), modes)
        self.assertIn(".githooks/* text eol=lf", (repo / ".gitattributes").read_text(encoding="utf-8"))
        self.assertIn("](../CLAUDE.md#building-and-testing)", (repo / "tests/CLAUDE.md").read_text(encoding="utf-8"))
        # The hooks run: a message crediting a tool is refused, a plain one is not.
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
        git(repo, "add", "-A")
        refused = subprocess.run(["git", "commit", "-q", "-m", "Add a\n\nCo-Authored-By: Claude <claude@anthropic.com>"],
                                 cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
        self.assertIn("attribution", refused.stderr)
        done = subprocess.run(["git", "commit", "-q", "-m", "Add a"], cwd=repo, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_hooks_stay_off_beside_a_repositorys_own_rules_and_test_rules_go_in_each_stacks_test_folder(self):
        repo = self.existing()
        (repo / "CLAUDE.md").write_text("# Our own rules\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "Our rules")
        code, result = self.setup("--brownfield", "--dir", str(repo))
        self.assertEqual(code, 0, result)
        self.assertTrue((repo / ".githooks/pre-commit").is_file())
        self.assertEqual(git(repo, "config", "--get", "core.hooksPath"), "", "the project's own CLAUDE.md: off")
        self.assertTrue(any("core.hooksPath .githooks" in note for note in result["already_there"]), result)
        code, result = self.setup("--greenfield", "--dir", str(self.tmp / "two"), "--name", "Two", "--fsd",
                                  str(self.fsd), "--stack", "dotnet+react-vitest")
        self.assertEqual(code, 0, result)
        rules = (self.tmp / "two" / "backend/tests/CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("](../../docs/architecture.md#7-testing)", rules)
        self.assertFalse((self.tmp / "two" / "frontend/tests").exists(), "React's tests sit beside the code")

    def test_greenfield_refuses_a_folder_that_is_not_empty_and_an_fsd_it_cannot_read(self):
        (self.tmp / "busy").mkdir()
        (self.tmp / "busy" / "notes.txt").write_text("mine", encoding="utf-8")
        code, result = self.setup("--greenfield", "--dir", str(self.tmp / "busy"), "--name", "Shop", "--fsd",
                                  str(self.fsd), "--stack", "pytest")
        self.assertEqual(code, 1)
        self.assertIn("exists and is not empty", result["refused"])
        self.assertEqual(os.listdir(self.tmp / "busy"), ["notes.txt"], "nothing written")
        sheet = self.tmp / "fsd.xlsx"
        sheet.write_bytes(b"x")
        code, result = self.setup("--greenfield", "--dir", str(self.tmp / "new"), "--name", "Shop", "--fsd", str(sheet),
                                  "--stack", "pytest")
        self.assertEqual(code, 1)
        self.assertIn("must be .docx, .md, .txt, .pdf", result["refused"])
        self.assertFalse((self.tmp / "new").exists())
        code, result = self.setup("--greenfield", "--dir", str(self.tmp / "new"), "--name", "Sh/op", "--fsd",
                                  str(self.fsd), "--stack", "pytest")
        self.assertEqual(code, 1)
        self.assertIn("--name", result["refused"])

    def test_greenfield_refuses_without_a_git_identity(self):
        (self.tmp / "gitconfig").write_text("", encoding="utf-8")
        code, result = self.greenfield()
        self.assertEqual(code, 1)
        self.assertIn("git has no user.name", result["refused"])
        self.assertFalse((self.tmp / "shop").exists())

    def existing(self, name: str = "app") -> Path:
        repo = self.tmp / name
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "app.py").write_text("def ok():\n    return True\n", encoding="utf-8")
        (repo / "pyproject.toml").write_text("[project]\nname = 'app'\n", encoding="utf-8")
        (repo / "README.md").write_text("# App\n\nOurs.\n", encoding="utf-8")
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "Seed")
        return repo

    def test_brownfield_installs_on_a_branch_detects_the_stack_and_never_overwrites(self):
        repo = self.existing()
        (repo / "CLAUDE.md").write_text("# Our own rules\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "Our rules")
        code, result = self.setup("--brownfield", "--dir", str(repo), "--fsd", str(self.fsd), "--name", "App")
        self.assertEqual(code, 0, result)
        self.assertEqual((result["stack"], result["branch"], result["from"]), ("pytest", "setup/factory", "main"))
        self.assertIn("CLAUDE.md", result["already_there"])
        self.assertEqual((repo / "CLAUDE.md").read_text(encoding="utf-8"), "# Our own rules\n")
        self.assertEqual(result["fsd"], "requirements/fsd/App - V1.docx")
        self.assertEqual(git(repo, "branch", "--show-current"), "setup/factory")
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(git(repo, "log", "-1", "--format=%s", "main"), "Our rules", "main is untouched")

    def test_the_merge_gate_is_approved_locally_without_a_remote_and_in_bitbucket_with_one(self):
        import tomllib

        def merge_check(repo: Path) -> str:
            config = tomllib.loads((repo / "devtools/factory/factory.toml").read_text(encoding="utf-8"))
            return next(s["check"] for s in config["steps"] if s["name"] == "merge-gate")

        code, result = self.greenfield()
        self.assertEqual(code, 0, result)
        self.assertEqual(merge_check(self.tmp / "shop"), "local-approval", "a new folder has no remote")
        self.assertIn("Start Factory.cmd", result["written"])
        local = self.existing("local")
        code, result = self.setup("--brownfield", "--dir", str(local))
        self.assertEqual(code, 0, result)
        self.assertEqual(merge_check(local), "local-approval")
        remote = self.existing("remote")
        git(remote, "remote", "add", "origin", "https://bitbucket.org/example/remote.git")
        code, result = self.setup("--brownfield", "--dir", str(remote))
        self.assertEqual(code, 0, result)
        self.assertEqual(merge_check(remote), "bitbucket-approval")
        # A GitHub remote gets its own gate, read through the gh CLI; any other host is approved locally.
        github = self.existing("github")
        git(github, "remote", "add", "origin", "https://github.com/example/github.git")
        code, result = self.setup("--brownfield", "--dir", str(github))
        self.assertEqual(code, 0, result)
        self.assertEqual(merge_check(github), "github-approval")
        other = self.existing("gitlab")
        git(other, "remote", "add", "origin", "https://gitlab.com/example/other.git")
        code, result = self.setup("--brownfield", "--dir", str(other))
        self.assertEqual(code, 0, result)
        self.assertEqual(merge_check(other), "local-approval", "approved in the app, merged locally")

    def test_brownfield_on_an_installed_repository_upgrades_and_files_the_next_revision(self):
        repo = self.existing()
        self.assertEqual(self.setup("--brownfield", "--dir", str(repo), "--fsd", str(self.fsd), "--name", "App")[0], 0)
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--ff-only", "setup/factory")
        git(repo, "branch", "-m", "setup/factory", "setup/factory-1")
        (repo / "devtools/factory/factory.py").write_text("# an old referee\n", encoding="utf-8")
        config = repo / "devtools/factory/factory.toml"
        version = setup.load_init().VERSION
        config.write_text(config.read_text(encoding="utf-8").replace(f'kit_version = "{version}"', 'kit_version = "0.1.0"'),
                          encoding="utf-8", newline="\n")
        git(repo, "commit", "-q", "-am", "An old referee")
        code, result = self.setup("--brownfield", "--dir", str(repo), "--fsd", str(self.fsd), "--name", "App")
        self.assertEqual(code, 0, result)
        self.assertIn("devtools/factory/factory.py", result["upgraded"])
        self.assertIn(f"devtools/factory/factory.toml: kit_version 0.1.0 to {version}", result["upgraded"])
        self.assertIn(f'kit_version = "{version}"', config.read_text(encoding="utf-8"), "--upgrade moves the stamp")
        self.assertEqual(result["fsd"], "requirements/fsd/App - V2.docx", "never over an existing V<n>")
        self.assertTrue((repo / "requirements/fsd/App - V1.docx").is_file())

    def test_brownfield_refuses_a_dirty_tree_a_folder_that_is_not_a_repository_and_an_unknown_stack(self):
        repo = self.existing()
        (repo / "src" / "app.py").write_text("changed\n", encoding="utf-8")
        code, result = self.setup("--brownfield", "--dir", str(repo))
        self.assertEqual(code, 1)
        self.assertIn("uncommitted changes", result["refused"])
        self.assertEqual(git(repo, "branch", "--show-current"), "main")

        plain = self.tmp / "plain"
        plain.mkdir()
        code, result = self.setup("--brownfield", "--dir", str(plain))
        self.assertEqual(code, 1)
        self.assertIn("not the top of a git repository", result["refused"])
        code, result = self.setup("--brownfield", "--dir", str(repo / "src"))
        self.assertEqual(code, 1, "a sub-folder of a repository is not its top")

        node = self.tmp / "web"
        node.mkdir()
        (node / "package.json").write_text("{}", encoding="utf-8")
        git(node, "init", "-q", "-b", "main")
        git(node, "add", "-A")
        git(node, "commit", "-q", "-m", "Seed")
        code, result = self.setup("--brownfield", "--dir", str(node))
        self.assertEqual(code, 1)
        self.assertIn("no adapter for it yet", result["refused"])

    def test_greenfield_with_two_stacks_writes_a_folder_and_a_skeleton_each(self):
        code, result = self.setup("--greenfield", "--dir", str(self.tmp / "app"), "--name", "App", "--fsd", str(self.fsd),
                                  "--stack", "dotnet+react-vitest")
        self.assertEqual(code, 0, result)
        repo = self.tmp / "app"
        self.assertEqual(result["stack"], "backend=dotnet,frontend=react-vitest")
        for rel in ("backend/App.slnx", "backend/tests/App.Tests/GreetingTests.cs", "frontend/package.json",
                    "frontend/src/App.test.tsx", "frontend/.gitignore"):
            self.assertTrue((repo / rel).is_file(), rel)
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        import tomllib
        config = tomllib.loads((repo / "devtools/factory/factory.toml").read_text(encoding="utf-8"))
        self.assertNotIn("adapter", config)
        self.assertEqual([(s["name"], s["adapter"]["name"]) for s in config["stacks"]],
                         [("backend", "dotnet"), ("frontend", "react-vitest")])
        self.assertEqual(config["stacks"][0]["commands"]["test_projects_always"], ["tests/App.Tests"])
        project = (repo / "docs/project.md").read_text(encoding="utf-8")
        self.assertIn("`frontend/`: `npm run build`", project)
        # 18 Oct: the React rule pack joins the Code rules, its paths in the front end's own folder; the UI
        # standard it points to is installed with the docs.
        rules = (repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("### React and TypeScript", rules)
        self.assertIn("`frontend/src/ui/`", rules)
        self.assertLess(rules.index("## Code rules"), rules.index("### React and TypeScript"))
        self.assertTrue((repo / "docs/ui-standard.md").is_file())
        # The .NET pack beside it, and each stack's banned-pattern rules for check-code-rules.py.
        self.assertIn("### .NET", rules)
        self.assertEqual({s["name"]: bool(s.get("code_rules")) for s in config["stacks"]}, {"backend": True, "frontend": True})

    def test_a_single_react_vitest_greenfield_gets_its_skeleton_at_the_top_and_dotnet_none(self):
        code, result = self.setup("--greenfield", "--dir", str(self.tmp / "web"), "--name", "Web", "--fsd", str(self.fsd),
                                  "--stack", "react-vitest")
        self.assertEqual(code, 0, result)
        web = self.tmp / "web"
        self.assertTrue((web / "package.json").is_file())
        ignored = (web / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("node_modules/", ignored, "the skeleton's ignores join the root .gitignore")
        self.assertIn(".factory/", ignored)
        code, result = self.setup("--greenfield", "--dir", str(self.tmp / "api"), "--name", "Api", "--fsd", str(self.fsd),
                                  "--stack", "dotnet")
        self.assertEqual(code, 0, result)
        self.assertFalse((self.tmp / "api" / "App.slnx").exists(), "a single .NET project is set up as before")

    def test_stack_names_are_parsed_and_refused_plainly(self):
        init = setup.load_init()
        self.assertEqual(init.parse_stacks("pytest"), [("", "pytest")])
        self.assertEqual(init.parse_stacks("dotnet+react-vitest"), [("backend", "dotnet"), ("frontend", "react-vitest")])
        self.assertEqual(init.parse_stacks("api=pytest,web=react-vitest"), [("api", "pytest"), ("web", "react-vitest")])
        for bad, message in (("cobol", "no adapter"), ("a=pytest,a=dotnet", "folder of its own"),
                             ("a=pytest,a/b=dotnet", "folder of its own")):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, message):
                init.parse_stacks(bad)

    def test_brownfield_detects_a_react_vitest_project_and_refuses_stacks_whose_folders_are_missing(self):
        web = self.tmp / "web"
        web.mkdir()
        (web / "package.json").write_text(json.dumps({"dependencies": {"react": "18.3.1"},
                                                      "devDependencies": {"vitest": "3.2.4"}}), encoding="utf-8")
        git(web, "init", "-q", "-b", "main")
        git(web, "add", "-A")
        git(web, "commit", "-q", "-m", "Seed")
        code, result = self.setup("--brownfield", "--dir", str(web))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["stack"], "react-vitest")
        repo = self.existing()
        code, result = self.setup("--brownfield", "--dir", str(repo), "--stacks", "backend=pytest,frontend=react-vitest")
        self.assertEqual(code, 1)
        self.assertIn("backend/, frontend/", result["refused"])

    def test_the_set_up_project_starts_a_book_run_whose_outline_the_referee_reads_from_the_docx(self):
        self.assertEqual(self.greenfield()[0], 0)
        repo = self.tmp / "shop"
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        factory = [sys.executable, "-B", "devtools/factory/factory.py"]
        started = subprocess.run([*factory, "start", "book:project", "--title", "Book from FSD V1", "--new-branch"],
                                 cwd=repo, capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        self.assertEqual(git(repo, "branch", "--show-current"), "setup/book-project")
        checked = subprocess.run([*factory, "check"], cwd=repo, capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        run = (repo / "docs/factory/runs/R-001.md").read_text(encoding="utf-8")
        self.assertIn("14 sections", run)
        self.assertIn("- §2.5 Loyalty *(empty)*", run)


if __name__ == "__main__":
    unittest.main()
