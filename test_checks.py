"""
Tests for the checks and git hooks the kit installs (templates/checks/, templates/githooks/), each run
in throwaway repositories. No model, no network.

    python -m unittest test_checks -v        (from the kit folder)

The checks find the guard at devtools/factory/hooks/ beside them, as an installed project holds it, so
they are copied into such a layout for the tests and loaded from there.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KIT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
_harness = tempfile.TemporaryDirectory(prefix="kit-checks-")
HARNESS = Path(_harness.name)
CHECKS = HARNESS / "devtools" / "checks"
CHECKS.mkdir(parents=True)
(HARNESS / "devtools" / "factory" / "hooks").mkdir(parents=True)
shutil.copy2(KIT / "factory" / "hooks" / "guard.py", HARNESS / "devtools" / "factory" / "hooks" / "guard.py")
for script in (KIT / "templates" / "checks").glob("*.py"):
    shutil.copy2(script, CHECKS / script.name)
_saved_env: dict[str, str | None] = {}
_empty_config = tempfile.NamedTemporaryFile(delete=False)
_empty_config.close()


def setUpModule() -> None:
    # The person's own git settings never reach a test repository, and no background maintenance runs.
    isolated = {"GIT_CONFIG_GLOBAL": _empty_config.name, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CEILING_DIRECTORIES": str(Path(tempfile.gettempdir()).resolve()),
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "maintenance.auto", "GIT_CONFIG_VALUE_0": "false",
                "GIT_CONFIG_KEY_1": "gc.auto", "GIT_CONFIG_VALUE_1": "0"}
    for key, value in isolated.items():
        _saved_env[key] = os.environ.get(key)
        os.environ[key] = value


def tearDownModule() -> None:
    for key, value in _saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    os.unlink(_empty_config.name)
    _harness.cleanup()


def load(script: str):
    """Import a hyphenated script as a module, from the harness."""
    spec = importlib.util.spec_from_file_location(script.replace("-", "_"), CHECKS / f"{script}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


commit_msg = load("check-commit-msg")
protected_paths = load("check-protected-paths")
check_rules = load("check-rules")
test_results = load("check-test-results")
rollup = load("gen-task-rollup")


class Repo:
    """A throwaway git repository."""

    def __init__(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                              cwd=self.root, capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            raise AssertionError(f"git {' '.join(args)}: {done.stderr}")
        return done.stdout

    def write(self, rel: str, content: str, add: bool = True) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        if add:
            self.git("add", "--", rel)
        return path

    def commit(self, message: str = "Change") -> None:
        # The repository under test holds no hooks; the hooks are tested on their own below.
        self.git("commit", "-q", "-m", message)

    def close(self) -> None:
        self._dir.cleanup()


class RepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo()
        self.addCleanup(self.repo.close)


def run_main(function, *args, **kwargs) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = function(*args, **kwargs)
    return code, out.getvalue()


# ---------------------------------------------------------------- check-commit-msg

class CommitMessageTests(unittest.TestCase):
    def problems(self, message: str, branch: str = "chore/x") -> list[str]:
        return commit_msg.problems(message, branch)

    def test_a_plain_message_passes(self):
        self.assertEqual(self.problems("Add the widget\n\nIt draws widgets.\n"), [])

    def test_attribution_in_the_middle_of_the_body_is_refused(self):
        found = self.problems("Add the widget\n\nCo-Authored-By: Claude <claude@anthropic.com>\nNotes follow\n")
        self.assertTrue(any("attribution" in p for p in found))
        self.assertTrue(any("trailer" in p for p in found))

    def test_a_generated_with_footer_is_refused(self):
        found = self.problems("Add the widget\n\n\U0001F916 Generated with [Claude Code](https://claude.com/claude-code)\n")
        self.assertTrue(any("attribution" in p for p in found))

    def test_a_trailer_before_prose_is_still_refused(self):
        found = self.problems("Add the widget\n\nSigned-off-by: T <t@example.invalid>\nMore prose here.\n")
        self.assertTrue(any("trailer" in p and "Signed-off-by" in p for p in found))

    def test_a_capitalised_hyphenated_key_is_a_trailer(self):
        self.assertTrue(self.problems("Add the widget\n\nX-Foo-Bar: baz\n"))
        self.assertTrue(self.problems("Add the widget\n\nChange-Id: I1234\n"))

    def test_prose_with_a_colon_is_allowed(self):
        self.assertEqual(self.problems("Add the widget\n\nNote: this is prose.\n"), [])
        self.assertEqual(self.problems("Add the widget\n\nSelf-tests: 32 pass.\nbest-effort: a failure is logged.\n"), [])

    def test_a_tracker_key_opening_the_subject_is_not_a_trailer(self):
        self.assertEqual(self.problems("SHOP-12: Fix login\n", "fix/SHOP-12-login"), [])

    def test_prose_that_mentions_a_trailer_mid_sentence_is_allowed(self):
        self.assertEqual(self.problems("Log D1\n\nThe commit carried a Co-Authored-By: Claude trailer.\n"), [])

    def test_a_fix_branch_needs_an_id(self):
        self.assertTrue(any("fix branch" in p for p in self.problems("Fix the login\n", "fix/login")))

    def test_a_fix_branch_accepts_a_defect_question_or_tracker_id(self):
        for message in ("Fix the login (D4)", "Answer Q3", "Fix SHOP-12"):
            self.assertEqual(self.problems(message, "fix/login"), [], message)

    def test_merges_and_reverts_are_exempt_from_the_id_rule(self):
        self.assertEqual(self.problems("Merge branch 'dev' into fix/login\n", "fix/login"), [])
        self.assertEqual(self.problems('Revert "Fix the login"\n\nThis reverts commit abc.\n', "fix/login"), [])

    def test_text_below_the_scissors_line_is_not_the_message(self):
        message = ("Add the widget\n# ------------------------ >8 ------------------------\n"
                   "Co-Authored-By: Claude <claude@anthropic.com>\n")
        self.assertEqual(self.problems(message), [])
        self.assertTrue(self.problems("Fix the login\n# ------------------------ >8 ------------------------\n+ D4\n",
                                      "fix/login"))

    def test_the_fix_branch_and_the_id_come_from_factory_toml(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "factory.toml"
            config.write_text('[backlog.branches]\ndefect = "bugfix/{item}"\n[checks]\nfix_id = \'\\bBUG\\d+\\b\'\n',
                              encoding="utf-8")
            prefix, pattern = commit_msg.settings(config)
            self.assertEqual(prefix, "bugfix/")
            self.assertTrue(commit_msg.problems("Fix the login (D4)", "bugfix/D4", prefix, pattern))
            self.assertEqual(commit_msg.problems("Fix the login (BUG7)", "bugfix/BUG7", prefix, pattern), [])
            self.assertEqual(commit_msg.problems("Fix the login", "fix/login", prefix, pattern), [],
                             "fix/ is not this project's fix branch")
            self.assertEqual(commit_msg.settings(Path(folder) / "none.toml")[0], "fix/", "no factory.toml: fix/")


class CommitMessageRangeTests(RepoTestCase):
    """`--commits <range>`, as CI runs it over a pull request's commits."""

    RULE = "devtools/checks/check-commit-msg.py"

    def setUp(self) -> None:
        super().setUp()
        self.repo.write("readme.txt", "base\n")
        self.repo.commit("Base")
        self.repo.git("checkout", "-q", "-b", "work")

    def commit_with_the_rule(self, message: str, rel: str = "a.txt") -> str:
        """A commit whose tree holds the check: one the hook would have run for."""
        self.repo.write(self.RULE, "# the rule\n")
        self.repo.write(rel, message + "\n")
        self.repo.commit(message)
        return self.repo.git("rev-parse", "HEAD").strip()

    def run_ci(self, branch: str = "chore/x") -> subprocess.CompletedProcess:
        env = {**os.environ, "BITBUCKET_BRANCH": branch}
        return subprocess.run([sys.executable, str(CHECKS / "check-commit-msg.py"), "--commits", "main..HEAD"],
                              cwd=self.repo.root, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace")

    def test_a_bad_message_in_the_range_fails_naming_its_commit(self):
        self.commit_with_the_rule("Add the widget")
        bad = self.commit_with_the_rule("Add the gadget\n\nSigned-off-by: T <t@example.invalid>", "b.txt")
        done = self.run_ci()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn(f"commit-msg: {bad[:10]}", done.stderr)

    def test_a_fix_branch_commit_is_judged_by_the_ci_branch(self):
        self.commit_with_the_rule("Fix the login")
        self.assertEqual(self.run_ci("fix/login").returncode, 1)
        self.assertEqual(self.run_ci("chore/login").returncode, 0)

    def test_commits_made_before_the_check_are_not_judged(self):
        self.repo.write("old.txt", "old\n")
        self.repo.commit("Old work\n\nSigned-off-by: T <t@example.invalid>")
        self.commit_with_the_rule("Add the widget")
        done = self.run_ci()
        self.assertEqual(done.returncode, 0, done.stderr)


# ---------------------------------------------------------------- the hooks

class HooksTests(RepoTestCase):
    """The kit's hooks, run by sh with stand-ins for Python: they refuse without one, and use `py -3`."""

    def setUp(self) -> None:
        super().setUp()
        self.sh = shutil.which("sh")
        if self.sh is None:
            self.fail("no sh on PATH to run the hooks with")
        for hook in ("pre-commit", "commit-msg"):
            self.repo.write(f".githooks/{hook}", (KIT / "templates" / "githooks" / hook).read_text(encoding="utf-8"))
        self.bin = self.repo.root / "stub-bin"
        self.bin.mkdir()

    def python_stubs(self, code: int, launcher: int | None = None) -> dict[str, str]:
        """`python3` and `python` exit with `code`; `py` with `launcher` (or `code`), only as `py -3`,
        logging every call's arguments to py.log."""
        for name in ("python3", "python"):
            stub = self.bin / name
            stub.write_text(f"#!/bin/sh\nexit {code}\n", encoding="utf-8", newline="\n")
            stub.chmod(0o755)
        stub = self.bin / "py"
        stub.write_text(f'#!/bin/sh\necho "$*" >> "{(self.bin / "py.log").as_posix()}"\n'
                        f'[ "$1" = -3 ] || exit 9\nexit {code if launcher is None else launcher}\n',
                        encoding="utf-8", newline="\n")
        stub.chmod(0o755)
        return {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "")}

    def py_calls(self) -> list[str]:
        log = self.bin / "py.log"
        return [line.replace("\\", "/") for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def hook(self, name: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.sh, f".githooks/{name}", *args], cwd=self.repo.root, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_pre_commit_refuses_without_python_and_names_what_it_could_not_run(self):
        done = self.hook("pre-commit", self.python_stubs(1))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("no working Python", done.stderr)
        self.assertIn("protected-paths", done.stderr)
        self.assertEqual(self.py_calls(), ["-3 -c pass"])

    def test_pre_commit_runs_every_kit_check_with_the_py_launcher(self):
        done = self.hook("pre-commit", self.python_stubs(1, launcher=0))
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.py_calls()
        for check in ("check-book.py", "check-private-data.py --staged", "check-protected-paths.py --staged",
                      "gen-task-rollup.py --check", "check-rules.py --check"):
            self.assertTrue(any(call.startswith("-3 ") and call.endswith(f"/devtools/checks/{check}") for call in calls),
                            (check, calls))

    def test_commit_msg_runs_the_check_and_refuses_without_python(self):
        message = self.repo.write("msg.txt", "Add the widget\n", add=False)
        done = self.hook("commit-msg", self.python_stubs(1, launcher=0), str(message))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("/devtools/checks/check-commit-msg.py ", self.py_calls()[-1])
        (self.bin / "py.log").unlink()
        done = self.hook("commit-msg", self.python_stubs(1), str(message))
        self.assertEqual(done.returncode, 1)
        self.assertIn("no working Python", done.stderr)

    def test_the_hooks_have_unix_line_endings(self):
        for hook in ("pre-commit", "commit-msg"):
            self.assertNotIn(b"\r\n", (KIT / "templates" / "githooks" / hook).read_bytes(), hook)


# ---------------------------------------------------------------- check-protected-paths

GUARD_TOML = """base_ref = "main"

[guard]
read_only = ["requirements/**"]
read_only_maintained = ["requirements/read-me.txt", "requirements/**/read-me.txt"]
read_only_reason = "is a requirements snapshot and is read-only."
applied = ["db/migrations/*.sql"]
applied_reason = "is a migration already on the base."
never_by_hand = ["db/migrations/schema-snapshot.sql"]
"""
FSD_V1 = "requirements/fsd/Shop - V1.pdf"
MIGRATIONS = "db/migrations/"
SNAPSHOT = MIGRATIONS + "schema-snapshot.sql"
APPLIED = MIGRATIONS + "001_orders.sql"


class ProtectedPathsTests(RepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo.write(protected_paths.FACTORY_TOML, GUARD_TOML)
        self.repo.write("requirements/read-me.txt", "index v1\n")
        self.repo.write("requirements/fsd/read-me.txt", "fsd v1\n")
        self.repo.write(FSD_V1, "fsd one\n")
        self.repo.write(APPLIED, "create table orders ();\n")
        self.repo.write(SNAPSHOT, "snapshot v1\n")
        self.repo.commit("Base")
        self.repo.git("checkout", "-q", "-b", "work")

    def check(self, *argv: str, env: dict[str, str] | None = None, **kwargs) -> tuple[int, str]:
        return run_main(protected_paths.main, list(argv) or ["--base", "main"], root=self.repo.root,
                        env=env or {}, **kwargs)

    def change(self, rel: str, content: str = "changed\n") -> None:
        self.repo.write(rel, content)
        self.repo.commit()

    def assertFails(self, *named: str, argv: tuple[str, ...] = ()) -> str:
        code, out = self.check(*argv)
        self.assertEqual(code, 1, out)
        for text in named:
            self.assertIn(text, out)
        return out

    def assertPasses(self, argv: tuple[str, ...] = ()) -> str:
        code, out = self.check(*argv)
        self.assertEqual(code, 0, out)
        return out

    def test_nothing_protected_changed_passes(self):
        self.change("src/orders.py")
        self.assertIn("nothing protected changed", self.assertPasses())

    def test_modifying_an_existing_snapshot_fails_naming_the_path_never_the_contents(self):
        self.change(FSD_V1, "edited\n")
        out = self.assertFails(FSD_V1, "modified", "is a requirements snapshot")
        self.assertNotIn("edited", out)

    def test_adding_a_new_snapshot_and_editing_a_read_me_pass(self):
        self.repo.write("requirements/fsd/Shop - V2.pdf", "fsd two\n")
        self.change("requirements/fsd/read-me.txt", "fsd v2\n")
        self.assertPasses()

    def test_deleting_or_renaming_a_maintained_read_me_fails(self):
        self.repo.git("mv", "requirements/read-me.txt", "requirements/read-me (old).txt")
        self.repo.commit()
        out = self.assertFails("requirements/read-me.txt", "renamed away", "edited, never deleted")
        self.assertNotIn("read-me (old).txt", out)

    def test_editing_an_applied_migration_fails_and_a_new_one_with_its_snapshot_passes(self):
        self.repo.write(MIGRATIONS + "002_lines.sql", "create table lines ();\n")
        self.change(SNAPSHOT, "snapshot v2\n")
        self.assertPasses()
        self.change(APPLIED, "create table orders (id int);\n")
        self.assertFails(APPLIED, "is a migration already on the base")

    def test_a_branch_may_still_change_its_own_unmerged_migration(self):
        self.change(MIGRATIONS + "002_lines.sql", "create table lines ();\n")
        self.change(MIGRATIONS + "002_lines.sql", "create table lines (id int);\n")
        self.assertPasses()

    def test_a_branch_that_merged_the_base_answers_only_for_its_own_changes(self):
        self.change("src/feature.py", "feature\n")
        self.repo.git("checkout", "-q", "main")
        self.repo.write("requirements/fsd/Shop - V2.pdf", "fsd two\n")
        self.change(SNAPSHOT, "snapshot v2\n")
        self.repo.git("checkout", "-q", "work")
        self.repo.git("merge", "-q", "--no-edit", "main")
        self.assertPasses()

    def test_an_accepted_commit_is_excused_and_no_other_change_to_the_file(self):
        self.repo.git("branch", "qa", "main")
        self.repo.git("checkout", "-q", "main")
        self.change(FSD_V1, "replaced in place\n")
        commit = self.repo.git("rev-parse", "HEAD").strip()
        argv = ("--base", "qa", "--head", "main")
        self.assertEqual(self.check(*argv, accepted={})[0], 1)
        self.assertEqual(self.check(*argv, accepted={(commit, FSD_V1): "before the rule"})[0], 0)
        self.change(FSD_V1, "edited again\n")
        self.assertEqual(self.check(*argv, accepted={(commit, FSD_V1): "before the rule"})[0], 1)

    def test_the_base_defaults_to_the_pull_requests_destination_then_base_ref(self):
        self.change(FSD_V1, "edited\n")
        code, out = run_main(protected_paths.main, [], root=self.repo.root,
                             env={"BITBUCKET_PR_DESTINATION_BRANCH": "no-such-destination"})
        self.assertEqual(code, 1)
        self.assertIn("origin/no-such-destination", out)
        code, out = run_main(protected_paths.main, [], root=self.repo.root, env={})
        self.assertEqual(code, 1, out)
        self.assertIn("that main already holds", out, "base_ref from factory.toml")

    def test_could_not_check_fails_closed(self):
        self.assertIn("could not check", self.assertFails(argv=("--base", "no-such-branch")))
        real = protected_paths.git

        def failing_diff(*args, root):
            if args[0] == "diff":
                return subprocess.CompletedProcess(args, 128, "", "fatal: bad object")
            return real(*args, root=root)

        with mock.patch.object(protected_paths, "git", failing_diff):
            self.assertIn("could not check", self.assertFails())

    def test_a_branch_cannot_loosen_the_rules_it_is_judged_by(self):
        self.repo.write(protected_paths.FACTORY_TOML, GUARD_TOML.replace('read_only = ["requirements/**"]', "read_only = []"))
        self.change(FSD_V1, "edited\n")
        self.assertIn("main:" + protected_paths.FACTORY_TOML, self.assertFails(FSD_V1))

    def test_a_base_without_factory_toml_lends_the_heads_rules(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.git("rm", "-q", "--", protected_paths.FACTORY_TOML)
        self.repo.commit()
        self.repo.git("checkout", "-q", "work")
        self.change(FSD_V1, "edited\n")
        self.assertIn("HEAD:" + protected_paths.FACTORY_TOML, self.assertFails(FSD_V1))

    def test_a_guard_that_protects_nothing_fails_closed(self):
        self.repo.git("checkout", "-q", "main")
        self.change(protected_paths.FACTORY_TOML, "[guard]\nread_only = []\napplied = []\n")
        self.repo.git("checkout", "-q", "work")
        self.assertIn("neither read_only nor applied", self.assertFails())

    def test_staged_judges_what_the_commit_about_to_be_made_holds(self):
        self.repo.write(FSD_V1, "edited, staged only\n")
        self.assertFails(FSD_V1, "the staged commit", argv=("--staged",))
        self.repo.git("reset", "-q", "--", FSD_V1)
        self.repo.git("checkout", "--", FSD_V1)
        self.repo.write("requirements/fsd/Shop - V2.pdf", "fsd two\n")
        self.assertPasses(argv=("--staged",))

    def test_staged_on_the_first_commit_passes_and_an_unfetched_base_is_replaced_by_head(self):
        fresh = Repo()
        self.addCleanup(fresh.close)
        fresh.write(protected_paths.FACTORY_TOML, GUARD_TOML)
        code, out = run_main(protected_paths.main, ["--staged"], root=fresh.root, env={})
        self.assertEqual(code, 0, out)
        self.assertIn("first commit", out)
        self.repo.write(protected_paths.FACTORY_TOML, GUARD_TOML.replace('base_ref = "main"', 'base_ref = "origin/main"'))
        self.repo.commit()
        self.repo.write(FSD_V1, "edited\n")
        code, out = self.check("--staged")
        self.assertEqual(code, 1, out)
        self.assertIn("origin/main is not here", out)


# ---------------------------------------------------------------- check-rules

class RulesJudgeTests(RepoTestCase):
    CI = "steps:\n  - script:\n      - python3 devtools/checks/check-x.py\n"

    def setUp(self) -> None:
        super().setUp()
        self.repo.write("devtools/checks/check-x.py", "")
        self.repo.write("devtools/checks/check-commit-msg.py", "")
        self.repo.write(".githooks/pre-commit", '#!/bin/sh\npython3 "$root/devtools/checks/check-x.py"\n')
        self.repo.write(".githooks/commit-msg", '#!/bin/sh\nexec python3 "$root/devtools/checks/check-commit-msg.py" "$1"\n')
        self.repo.git("update-index", "--chmod=+x", ".githooks/pre-commit", ".githooks/commit-msg")

    def judge(self, marker: str, ci: str = CI, precommit: str | None = None, config: str = ""):
        context = {"files": check_rules.tracked(self.repo.root), "ci": ci, "config": config,
                   "precommit": check_rules.read(".githooks/pre-commit", self.repo.root) if precommit is None else precommit}
        return check_rules.judge(marker, context, root=self.repo.root)

    def test_an_intact_script_rule_is_ok(self):
        enforcers, runs, problems = self.judge(": `check-x.py`, CI + pre-commit")
        self.assertEqual((enforcers, runs, problems), (["check-x.py"], ["CI", "pre-commit"], []))

    def test_a_script_named_by_its_path_is_found(self):
        self.assertEqual(self.judge(": `devtools/checks/check-x.py`")[2], [])
        self.assertIn("devtools/checks/check-gone.py is gone", self.judge(": `devtools/checks/check-gone.py`")[2])

    def test_a_marker_naming_nothing_is_broken(self):
        self.assertEqual(self.judge(": the reviewers")[2], ["names no test or check — say which one enforces it"])

    def test_a_script_run_only_in_a_comment_or_as_another_names_tail_is_broken(self):
        self.assertIn("check-x.py is not in CI", self.judge(": `check-x.py`, CI", "      # - python3 check-x.py\n")[2])
        self.assertIn("check-x.py is not in CI", self.judge(": `check-x.py`, CI", "      - python3 precheck-x.py\n")[2])

    def test_a_script_that_runs_only_from_factory_toml_runs(self):
        self.assertEqual(self.judge(": `check-x.py`", ci="", precommit="",
                                    config='checks = ["python3 devtools/checks/check-x.py"]\n')[1], ["factory.toml"])
        self.assertIn("check-x.py runs nowhere", self.judge(": `check-x.py`", ci="", precommit="")[2])

    def test_a_test_is_found_where_it_is_defined_and_not_in_a_comment_or_a_document(self):
        self.repo.write("tests/test_rules.py", "class LiveTests:\n    pass\n# class GoneTests\n")
        self.repo.write("docs/notes.md", "class DocTests\n")
        self.assertEqual(self.judge(": `LiveTests`")[2], [])
        self.assertIn("no test DocTests in the tracked code", self.judge(": `DocTests`")[2])

    def test_the_commit_msg_hook_must_run_the_check_and_be_executable(self):
        self.assertEqual(self.judge(": `commit-msg` hook")[1:], (["every commit"], []))
        self.repo.git("update-index", "--chmod=-x", ".githooks/commit-msg")
        self.assertIn(".githooks/commit-msg is not committed executable (mode 100755)", self.judge(": `commit-msg` hook")[2])
        self.repo.write(".githooks/commit-msg", "#!/bin/sh\n# devtools/checks/check-commit-msg.py\nexit 0\n")
        self.assertIn("the commit-msg hook no longer runs check-commit-msg.py", self.judge(": `commit-msg` hook")[2])

    def test_the_guard_must_be_there_and_wired_in(self):
        self.assertIn("the guard is gone", self.judge(": guard")[2])
        self.repo.write("devtools/factory/hooks/guard.py", "")
        self.assertIn("the guard is not wired into .claude/settings.json", self.judge(": guard")[2])
        self.repo.write(".claude/settings.json", '{"hooks": {"PreToolUse": [{"command": "guard.py"}]}}\n')
        self.assertEqual(self.judge(": guard")[1:], (["every session"], []))

    def test_every_tracked_claude_md_is_read_and_the_notation_is_skipped(self):
        self.repo.write("CLAUDE.md", "*[enforced: X]* marks a rule.\n\n- **Run the x check** *[enforced: `check-x.py`, pre-commit]*.\n")
        self.repo.write("tests/CLAUDE.md", "- **A rule no check holds** *[enforced: the reviewers]*.\n")
        found = check_rules.rules(self.repo.root)
        self.assertEqual([(r.file, bool(r.problems)) for r in found], [("CLAUDE.md", False), ("tests/CLAUDE.md", True)])
        self.assertEqual(run_main(check_rules.main, root=self.repo.root)[0], 1)


# ---------------------------------------------------------------- check-test-results

JUNIT = '<testsuites><testsuite name="s">{cases}</testsuite></testsuites>'
TRX = ('<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010"><Results>{results}</Results>'
       '<ResultSummary><Counters total="{total}" executed="{executed}" passed="{executed}" notExecuted="0"/>'
       '</ResultSummary></TestRun>')


class TestResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.folder = Path(self._dir.name)

    def write(self, name: str, text: str) -> str:
        (self.folder / name).write_text(text, encoding="utf-8")
        return str(self.folder / name)

    def check(self, *paths: str) -> tuple[int, str]:
        return run_main(test_results.main, list(paths))

    def test_a_run_that_executed_and_skipped_nothing_passes(self):
        code, out = self.check(self.write("results.xml", JUNIT.format(cases='<testcase name="a"/><testcase name="b"/>')))
        self.assertEqual(code, 0, out)
        self.assertIn("2 executed, 0 skipped", out)

    def test_a_skipped_test_fails(self):
        cases = '<testcase name="a"/><testcase name="b"><skipped message="no database"/></testcase>'
        code, out = self.check(self.write("results.xml", JUNIT.format(cases=cases)))
        self.assertEqual(code, 1)
        self.assertIn("1 test(s) skipped", out)

    def test_a_run_that_executed_nothing_or_left_no_results_fails(self):
        self.assertIn("no tests executed", self.check(self.write("results.xml", JUNIT.format(cases="")))[1])
        self.assertIn("no results file", self.check(str(self.folder / "missing.xml"))[1])
        empty = self.folder / "empty"
        empty.mkdir()
        self.assertEqual(self.check(str(empty))[0], 1)

    def test_a_trx_skip_is_counted_from_its_results_not_only_its_summary(self):
        results = ('<UnitTestResult testName="a" outcome="Passed"/>'
                   '<UnitTestResult testName="b" outcome="NotExecuted"/>')
        code, out = self.check(self.write("results.trx", TRX.format(results=results, total=2, executed=1)))
        self.assertEqual(code, 1, out)
        self.assertIn("1 test(s) skipped", out)
        passed = '<UnitTestResult testName="a" outcome="Passed"/>'
        self.assertEqual(self.check(self.write("ok.trx", TRX.format(results=passed, total=1, executed=1)))[0], 0)

    def test_a_folder_is_read_file_by_file_and_a_file_that_is_not_results_fails(self):
        self.write("a.xml", JUNIT.format(cases='<testcase name="a"/>'))
        self.write("b.xml", "<html></html>")
        code, out = self.check(str(self.folder))
        self.assertEqual(code, 1)
        self.assertIn("neither JUnit XML nor .trx", out)



class RollupPathTests(unittest.TestCase):
    """The kit audit, 18 Oct: the roll-up read docs/plans and docs/project.md whatever factory.toml said."""

    def test_the_plans_folder_and_the_tracker_come_from_factory_toml(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / "devtools" / "factory" / "factory.toml"
            config.parent.mkdir(parents=True)
            self.assertEqual(rollup.configured_paths(config, root), (root / "docs/plans", root / "docs/project.md"),
                             "the kit's own layout without the keys")
            config.write_text('[backlog]\nplans_dir = "design/plans"\n[requirements]\ntracker = "planning/book.md"\n',
                              encoding="utf-8")
            self.assertEqual(rollup.configured_paths(config, root), (root / "design/plans", root / "planning/book.md"))
            plan = root / "design" / "plans" / "loans.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# Loans\n\n## 9. Tasks\n\n| # | Task | FSD | Role | Status | Jira | PR | Merged |\n"
                            "|---|---|---|---|---|---|---|---|\n| 1 | Lend a book | 2.1 | BE | Built | — | — | — |\n",
                            encoding="utf-8")
            tables, _ = rollup.render(root / "design" / "plans", rollup.Roles(), root / "planning" / "book.md")
            self.assertIn("](../design/plans/loans.md#", "\n".join(tables.values()), "linked from the tracker's own folder")


# ---------------------------------------------------------------- check-code-rules

code_rules = load("check-code-rules")
CLOCK_RULE = r"""
[[code_rules]]
id = "clock"
pattern = '\bclock_read\(\)'
files = ["src/**/*.py"]
exempt = ["src/**/clock.py"]
skip_lines = '^\s*#'
message = "take the time from the injected clock."
"""


class CodeRulesTests(RepoTestCase):
    """The language-agnostic banned-pattern check: every tracked file, or the lines a commit stages."""

    def check(self, *args: str) -> tuple[int, str]:
        return run_main(code_rules.main, list(args), root=self.repo.root)

    def test_a_hit_is_reported_with_its_file_and_line(self):
        self.repo.write(code_rules.FACTORY_TOML, CLOCK_RULE)
        self.repo.write("src/shop/orders.py", "def total():\n    return 1\n\nstamp = clock_read()\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("src/shop/orders.py:4: clock — `clock_read()`: take the time from the injected clock.", out)

    def test_an_exempt_file_a_comment_and_a_file_outside_the_globs_pass(self):
        self.repo.write(code_rules.FACTORY_TOML, CLOCK_RULE)
        self.repo.write("src/clock.py", "now = clock_read()\n")
        self.repo.write("src/shop/orders.py", "# never clock_read() here\n")
        self.repo.write("tests/test_orders.py", "now = clock_read()\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("1 code rule(s) hold in every tracked file", out)

    def test_staged_judges_only_the_lines_the_commit_adds(self):
        self.repo.write(code_rules.FACTORY_TOML, CLOCK_RULE)
        self.repo.write("src/old.py", "a = clock_read()\nb = 2\n")
        self.repo.commit("Base")
        self.repo.write("src/new.py", "c = 3\n")
        self.repo.write("src/loose.py", "d = clock_read()\n", add=False)  # not staged: not this commit's
        code, out = self.check("--staged")
        self.assertEqual(code, 0, out)
        self.assertIn("the lines this commit adds", out)
        self.repo.write("src/old.py", "a = clock_read()\nb = 2\nc = clock_read()\n")
        code, out = self.check("--staged")
        self.assertEqual(code, 1, out)
        self.assertIn("src/old.py:3: clock", out)
        self.assertNotIn("src/old.py:1:", out, "a breach already committed is the full run's to report")
        self.assertNotIn("loose.py", out)

    def test_staged_works_on_the_first_commit_and_reads_the_staged_rules(self):
        self.repo.write(code_rules.FACTORY_TOML, CLOCK_RULE)
        self.repo.write("src/first.py", "x = clock_read()\n")
        code, out = self.check("--staged")
        self.assertEqual(code, 1, out)
        self.assertIn("src/first.py:1: clock", out)

    def test_each_stack_judges_its_own_root(self):
        self.repo.write(code_rules.FACTORY_TOML, r"""
[[stacks]]
name = "web"
root = "web"

[[stacks.code_rules]]
id = "console"
pattern = '\bconsole\.log\('
files = ["src/**/*.ts"]
exempt = ["src/**/*.test.ts"]
message = "no console.log."

[[stacks]]
name = "api"
root = "api"
""")
        self.repo.write("web/src/cart/total.ts", "console.log(1);\n")
        self.repo.write("web/src/cart/total.test.ts", "console.log(1);\n")
        self.repo.write("api/src/total.ts", "console.log(1);\n")
        self.repo.write("src/total.ts", "console.log(1);\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("web/src/cart/total.ts:1: console", out)
        for elsewhere in ("total.test.ts", "api/src/total.ts", "\n  src/total.ts"):
            self.assertNotIn(elsewhere, out)

    def test_a_factory_toml_without_rules_passes(self):
        self.repo.write(code_rules.FACTORY_TOML, 'base_ref = "main"\n\n[adapter]\nname = "pytest"\n')
        self.repo.write("src/orders.py", "x = clock_read()\n")
        for args in ((), ("--staged",)):
            code, out = self.check(*args)
            self.assertEqual(code, 0, out)
            self.assertIn("no code rules", out)

    def test_a_broken_rule_or_no_config_could_not_be_checked(self):
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("could not check", out)
        self.repo.write(code_rules.FACTORY_TOML, '[[code_rules]]\nid = "x"\npattern = "("\nfiles = ["**"]\nmessage = "m"\n')
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("not a valid expression", out)
        self.repo.write(code_rules.FACTORY_TOML, '[[code_rules]]\nid = "x"\npattern = "a"\n')
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("lacks files, message", out)

    def test_globs_cross_folders_only_where_they_say(self):
        regex = code_rules.glob_regex
        self.assertTrue(regex("src/**/*.cs").fullmatch("src/Orders.cs"))
        self.assertTrue(regex("src/**/*.cs").fullmatch("src/a/b/Orders.cs"))
        self.assertFalse(regex("src/*.cs").fullmatch("src/a/Orders.cs"))
        self.assertFalse(regex("src/**/*.cs").fullmatch("tests/Orders.cs"))
        self.assertTrue(regex("src/clock.ts").fullmatch("src/clock.ts"))
        self.assertFalse(regex("src/clock.ts").fullmatch("src/clockXts"))

    def test_staged_reads_a_path_with_a_space_and_a_line_that_starts_with_plus_signs(self):
        self.repo.write(code_rules.FACTORY_TOML, CLOCK_RULE)
        self.repo.write("src/order lines.py", "a = 1\n")
        self.repo.commit("Base")
        self.repo.write("src/order lines.py", "a = 1\n++ b = clock_read()\n")
        code, out = self.check("--staged")
        self.assertEqual(code, 1, out)
        self.assertIn("src/order lines.py:2: clock", out)

    def test_every_adapter_pack_loads_and_the_pre_commit_hook_runs_the_check(self):
        for adapter in sorted((KIT / "templates" / "adapters").glob("*.toml")):
            text = adapter.read_text(encoding="utf-8")
            body = text[text.index("# ----------------------------------------------------------------"):]
            rules = code_rules.load_rules(body)
            self.assertTrue(rules, f"{adapter.name} holds no code rules")
            self.assertTrue(all(rule.message for rule in rules), adapter.name)
        hook = (KIT / "templates" / "githooks" / "pre-commit").read_text(encoding="utf-8")
        self.assertTrue(check_rules.runs("check-code-rules.py", hook), "pre-commit no longer runs the check")
        self.assertIn('check-code-rules.py" --staged', hook)


if __name__ == "__main__":
    unittest.main()
