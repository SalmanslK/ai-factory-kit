#!/usr/bin/env python3
"""
Prove the kit installs and works, in a minute, without a model or a network.

    python selftest.py [--stack pytest|dotnet|react-vitest|pytest+react-vitest|<root>=<stack>,...]

Creates a throwaway git repository with a one-function project, installs the kit
with init.py, then checks what an adopter relies on:

  1. the installer wrote the factory, the settings, the skills and the docs;
  2. the guard is live — it refuses an edit to a requirements snapshot and a push
     to a protected branch, and lets an ordinary edit through;
  3. the referee runs a factory run through intake, context and spec with a
     stand-in for the CLI (fake_claude.py), stops at the spec gate, and refuses
     the agent's own approval;
  4. `factory verify` and `factory index --check` pass;
  5. the book's shape: the task roll-up is installed and `--check` passes on a fresh
     install, docs/project.md carries its generated markers and headings, a first plan
     from the template passes the roll-up check, factory.toml has [book] and
     [requirements.sources], and every stack adapter renders a config.
  6. the kit's version stamp: factory.toml carries `kit_version`, `factory version --json`
     reads it back, and `init.py --upgrade` moves (or adds) that one line and nothing else.
  7. setup.py --greenfield for two stacks (dotnet + react-vitest): a folder and a skeleton each, and a
     factory.toml the referee loads with each stack's writes under its root.
  8. plan runs: a fresh greenfield project with an approved book starts `plan:<slug> --new-branch` and drives
     (the stand-in CLI; the draft-plan session played by the test) to the plan gate; once the plan is on
     main a task run (`plan:<stem>#<n>`) starts and drives to its spec gate; `init.py --upgrade` brings the
     plan steps, their kinds and [backlog] into a 1.1.0 factory.toml without changing a value it set.

With a stack that has a front end (react-vitest, alone or beside another), also a change run through
the stack's real toolchain — npm installs the skeleton's pinned packages (from npm's cache when it
can, so the first run needs the network): the tests step's writes held per stack root by the guard;
red proven by a missing symbol in TypeScript (and by a failing test in the other stack); green after
the fix; integrate and verify (lint, type-check) in each stack's root.

Prints PASS or FAIL per check and exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

KIT = Path(__file__).resolve().parent
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail and not ok else ''}")


def run(argv: list[str], cwd: Path, env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, input=stdin)


def git(repo: Path, *args: str) -> None:
    done = run(["git", *args], repo)
    if done.returncode != 0:
        # A commit the project's own hooks refused showed up only later, as "Commit first" from the referee.
        print(f"git {' '.join(args)[:60]} failed: {(done.stderr or done.stdout).strip()[-600:]}")


def load_init(name: str = "kit_init"):
    spec = importlib.util.spec_from_file_location(name, KIT / "init.py")
    init = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True  # no __pycache__ left in the kit
    spec.loader.exec_module(init)
    return init


def make_project(repo: Path, found: list[tuple[str, str]] = (("", "pytest"),)) -> str:
    """
    A one-function project per stack, each in its root: a pytest or dotnet stack's src/ and tests/
    (calc), a react-vitest stack's skeleton from the kit. Returns a product file an ordinary edit may change.
    """
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Kit Selftest")
    git(repo, "config", "user.email", "selftest@example.invalid")
    git(repo, "config", "core.autocrlf", "false")
    ordinary = ""
    for root, name in found:
        folder = repo / root if root else repo
        folder.mkdir(parents=True, exist_ok=True)
        if name == "react-vitest":
            shutil.copytree(KIT / "templates/skeletons/react-vitest", folder, dirs_exist_ok=True)
            (folder / "src" / "price.ts").write_text(
                "export function cents(amount: number): number {\n  return Math.round(amount * 100);\n}\n", encoding="utf-8")
            ordinary = ordinary or f"{root + '/' if root else ''}src/App.tsx"
            continue
        (folder / "src").mkdir()
        (folder / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (folder / "tests").mkdir()
        (folder / "tests" / "test_calc.py").write_text(
            "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
            "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
        ordinary = ordinary or f"{root + '/' if root else ''}src/calc.py"
    if any(root for root, _ in found):
        # A root .gitignore for what a front end's folder ignores, as the kit's skeleton does at the top.
        (repo / ".gitignore").write_text("node_modules/\ndist/\ncoverage/\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Seed")
    return ordinary


def guard_decision(repo: Path, payload: dict) -> str:
    env = {**os.environ, "FACTORY_GUARD_MODE": "enforce"}
    done = run([sys.executable, str(repo / "devtools/factory/hooks/guard.py")], repo, env, json.dumps(payload))
    if not done.stdout.strip():
        return "allow"
    output = json.loads(done.stdout)["hookSpecificOutput"]
    return output.get("permissionDecision", "warn")


# docs/project.md's shape (the console design, Phase D §3.1): what the book run and the roll-up rely on.
PROJECT_HEADINGS = ["# Project state", "## Contents", "## What the work needs", "# Part 1 — Features and phasing",
                    "## How plans work", "### Where things stand", "### Task progress", "### Open tasks",
                    "### Delivery pace", "### Phases", "#### Phase 0 — Foundation", "### Dependency map",
                    "### Sections that are not features", "# Part 2 — Questions", "# Part 3 — Requirements history"]
PHASE_COLUMNS = "| Feature | FSD | Plan | Owner | Depends on | Status |"


def rollup(repo: Path, *flags: str) -> subprocess.CompletedProcess:
    return run([sys.executable, "-B", "devtools/checks/gen-task-rollup.py", *flags], repo)


def book_shape_checks(repo: Path) -> None:
    """On the fresh install: the roll-up holds, project.md has its shape, the config its book settings."""
    import re
    import tomllib
    fresh = rollup(repo, "--check")
    check("gen-task-rollup.py --check passes on a fresh install", fresh.returncode == 0, fresh.stdout + fresh.stderr)

    lines = (repo / "docs/project.md").read_text(encoding="utf-8").splitlines()
    markers = [m for m in ("task-rollup", "open-tasks", "pace")
               if sum(l.startswith(f"<!-- {m}:begin") for l in lines) != 1 or lines.count(f"<!-- {m}:end -->") != 1]
    heads = [l for l in lines if l.startswith("#")]
    at = [heads.index(h) if h in heads else -1 for h in PROJECT_HEADINGS]
    check("docs/project.md has the three generated marker pairs, its headings in order, and the phase table",
          not markers and -1 not in at and at == sorted(at) and PHASE_COLUMNS in lines,
          f"markers missing: {markers}; headings missing or out of order: "
          f"{[h for h, i in zip(PROJECT_HEADINGS, at) if i == -1] or at}")

    config = tomllib.loads((repo / "devtools/factory/factory.toml").read_text(encoding="utf-8"))
    sources, book = config.get("requirements", {}).get("sources", {}), config.get("book", {})
    version = re.compile(sources.get("version", "(?!)"))
    named = [name for name in ("Shop FSD - V1.docx", "Shop FSD - V12.md", "Shop FSD - V3.txt", "Shop FSD - V2.pdf")
             if not version.search(name)]
    check("factory.toml has [requirements.sources] (fsd_dir, version for pdf/docx/md/txt, feature_depth 2) and [book]",
          sources.get("fsd_dir") == "requirements/fsd" and (repo / "requirements/fsd").is_dir() and not named
          and not version.search("Shop FSD - V1.xlsx") and sources.get("feature_depth") == 2
          and all(role in book.get("roles", []) for role in (book.get("our_role") if isinstance(book.get("our_role"), list)
                                                              else [book.get("our_role")]))
          and book.get("foundation"),
          f"sources {sources}, book {book}, versions not matched: {named}")

    init = load_init()
    rendered = {}
    for stack in init.stacks():
        args = argparse.Namespace(stack=stack, base_ref="main", protected=["main"], source_roots=["src/"],
                                  read_only=["requirements/**"])
        parsed = tomllib.loads(init.render_config(args))
        rendered[stack] = "kit" not in parsed and parsed["adapter"]["name"] == stack and parsed["impact"]["cross_cutting"]
    check("every stack adapter carries its own writes and cross-cutting files, and renders a config without them",
          len(rendered) >= 3 and all(rendered.values()), str(rendered))
    args = argparse.Namespace(stack="dotnet+react-vitest", base_ref="main", protected=["main"], source_roots=["src/"],
                              read_only=["requirements/**"])
    parsed = tomllib.loads(init.render_config(args))
    shape = [(entry["name"], entry["root"], entry["adapter"]["name"], entry["writes"]["tests"])
             for entry in parsed.get("stacks", [])]
    check("two stacks render as [[stacks]] in backend/ and frontend/: each its adapter and writes, no top-level [adapter]",
          "adapter" not in parsed and shape == [("backend", "backend", "dotnet", ["tests/**", "*.slnx", "*.sln"]),
                                                ("frontend", "frontend", "react-vitest", ["src/*.test.ts", "src/*.test.tsx"])]
          and parsed["commands"]["verify"] == ["python3 devtools/factory/factory.py index --check"]
          and parsed["impact"]["source_roots"] == ["backend/src/", "frontend/src/"]
          and "Bash(cd frontend*)" in parsed["drive"]["allowed_tools"], str(shape))


def first_plan_checks(repo: Path) -> None:
    """A first plan copied from the template: the roll-up sees it as stale, regenerates, then passes."""
    template = (repo / "docs/plans/_template.md").read_text(encoding="utf-8")
    plan = repo / "docs/plans/pricing.md"
    plan.write_text(template.replace("# <Feature> — Design", "# Pricing — Design", 1), encoding="utf-8", newline="\n")
    stale = rollup(repo, "--check")
    written = rollup(repo)
    fresh = rollup(repo, "--check")
    project = (repo / "docs/project.md").read_text(encoding="utf-8")
    check("a first plan from the template passes the roll-up check once regenerated",
          stale.returncode != 0 and written.returncode == 0 and fresh.returncode == 0
          and "[Pricing](plans/pricing.md#9-tasks)" in project,
          stale.stderr + written.stdout + written.stderr + fresh.stderr)
    git(repo, "add", "-A")
    book = run([sys.executable, "devtools/checks/check-book.py"], repo)
    check("the book keeps its rules with the plan and the regenerated roll-up", book.returncode == 0,
          book.stdout[-600:] + book.stderr[-300:])


def project_md_checker_checks(repo: Path) -> None:
    """The book run's checker on the kit's own files: the filled sample passes; the template lacks only content."""
    checker = [sys.executable, "-B", "devtools/factory/check_project_md.py"]
    sample = run([*checker, str(KIT / "samples/shop-project.md"), str(KIT / "samples/shop-fsd.md")], repo)
    check("check_project_md: the kit's sample project.md (the template, filled for the shop FSD) passes",
          sample.returncode == 0, sample.stdout[-600:] + sample.stderr[-300:])
    template = run([*checker, "docs/project.md", str(KIT / "samples/shop-fsd.md")], repo)
    shape = [line for line in template.stdout.splitlines() if line.strip().startswith("- shape:")]
    check("check_project_md: the installed template has the checker's shape, and its FILL slots are caught",
          template.returncode == 1 and not shape and "still holds a <!-- FILL placeholder" in template.stdout,
          "\n".join(shape) or template.stdout[-600:] + template.stderr[-300:])


def stamp_checks(repo: Path, stack: str) -> None:
    """The kit's version stamp: written at install, read back by the referee, moved (and only it) by --upgrade."""
    import re
    import tomllib
    init = load_init("kit_init_stamp")
    config = repo / "devtools/factory/factory.toml"
    installed = config.read_bytes()
    stamp = tomllib.loads(installed.decode("utf-8")).get("kit_version")
    check(f"factory.toml is stamped kit_version = \"{init.VERSION}\" at the top level", stamp == init.VERSION,
          f"kit_version {stamp!r}, the kit is {init.VERSION}")
    answer = run([sys.executable, "-B", "devtools/factory/factory.py", "version", "--json"], repo)
    said = json.loads(answer.stdout) if answer.stdout.strip().startswith("{") else {}
    shipped = re.search(r'^FACTORY_VERSION = "([0-9.]+)"', (repo / "devtools/factory/factory.py").read_text(encoding="utf-8"),
                        re.MULTILINE)
    check("`factory version --json` answers the referee's FACTORY_VERSION and the kit stamp",
          answer.returncode == 0 and shipped is not None and said == {"version": shipped.group(1), "kit": init.VERSION},
          answer.stdout + answer.stderr)
    upgrade = [sys.executable, "-B", str(KIT / "init.py"), str(repo), "--stack", stack, "--upgrade"]
    old = installed.decode("utf-8").replace(f'kit_version = "{init.VERSION}"', 'kit_version = "0.9.0"', 1)
    config.write_text(old, encoding="utf-8", newline="")
    moved = run(upgrade, KIT)
    after = config.read_text(encoding="utf-8", newline="") if config.is_file() else ""
    without = "\n".join(l for l in installed.decode("utf-8").split("\n") if not l.startswith("kit_version"))
    config.write_text(without, encoding="utf-8", newline="")
    added = run(upgrade, KIT)
    inserted = config.read_text(encoding="utf-8", newline="")
    check("init.py --upgrade moves the stamp (0.9.0 to the kit's), or adds it, and changes nothing else in factory.toml",
          moved.returncode == 0 and after.encode("utf-8") == installed and "kit_version 0.9.0" in moved.stdout
          and added.returncode == 0 and tomllib.loads(inserted).get("kit_version") == init.VERSION
          and "\n".join(l for l in inserted.split("\n") if not l.startswith("kit_version")).replace("\n\n\n", "\n\n")
          .strip() == without.strip(), moved.stdout[-400:] + added.stdout[-400:] + moved.stderr + added.stderr)
    config.write_bytes(installed)


def app_checks(repo: Path) -> None:
    """The Factory app installed with its launcher, and it reads this project: a read-only snapshot, no server."""
    app = [f"devtools/factory/console/{name}" for name in
           ("console.py", "app_data.py", "wizard.py", "index.html", "Start Factory.cmd", "Start Factory.ps1")]
    launcher = repo / "Start Factory.cmd"
    text = launcher.read_text(encoding="utf-8") if launcher.is_file() else ""
    check("installed the Factory app (devtools/factory/console/) and Start Factory.cmd, which opens this project",
          all((repo / rel).is_file() for rel in app)
          and "devtools\\factory\\console\\console.py --open --project ." in text,
          ", ".join(rel for rel in app if not (repo / rel).is_file()) or text[:300])
    snapshot = repo / ".factory" / "app-snapshot.html"
    exported = run([sys.executable, "-B", "devtools/factory/console/console.py", "--export", str(snapshot),
                    "--project", "."], repo)
    check("the Factory app reads the installed project (a read-only snapshot)",
          exported.returncode == 0 and snapshot.is_file(), exported.stdout[-400:] + exported.stderr[-400:])
    config = tomllib.loads((repo / "devtools/factory/factory.toml").read_text(encoding="utf-8"))
    gate = next((s for s in config.get("steps", []) if s.get("name") == "merge-gate"), {})
    check("init.py's merge gate is a Bitbucket approval by default", gate.get("check") == "bitbucket-approval",
          str(gate))


def setup_checks(env: dict) -> None:
    """setup.py: a greenfield project from the sample FSD, its book run's outline read by the referee; a refusal."""
    with tempfile.TemporaryDirectory(prefix="factory-kit-setup-") as folder:
        root = Path(folder)
        gitconfig = root / "gitconfig"
        gitconfig.write_text("[user]\n\tname = Kit Selftest\n\temail = selftest@example.invalid\n[core]\n\tautocrlf = false\n",
                             encoding="utf-8")
        hermetic = {**env, "GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1"}
        project = root / "shop"
        made = run([sys.executable, "-B", str(KIT / "setup.py"), "--greenfield", "--dir", str(project), "--name", "Shop",
                    "--fsd", str(KIT / "samples/shop-fsd.md"), "--stack", "pytest", "--json"], root, hermetic)
        result = json.loads(made.stdout) if made.stdout.strip().startswith("{") else {}
        clean = run(["git", "status", "--porcelain"], project, hermetic).stdout.strip() if project.is_dir() else "?"
        check("setup.py --greenfield makes the project, files the FSD as V1 and commits it",
              made.returncode == 0 and result.get("fsd") == "requirements/fsd/Shop - V1.md" and not clean
              and any("start book:project" in line for line in result.get("next", [])),
              made.stdout[-600:] + made.stderr[-300:])
        config = project / "devtools/factory/factory.toml"
        steps = tomllib.loads(config.read_text(encoding="utf-8")).get("steps", []) if config.is_file() else []
        gate = next((s for s in steps if s.get("name") == "merge-gate"), {})
        check("a greenfield project (no remote) has a local merge approval: check = \"local-approval\"",
              gate.get("check") == "local-approval" and (project / "Start Factory.cmd").is_file(), str(gate))
        factory = [sys.executable, "-B", "devtools/factory/factory.py"]
        started = run([*factory, "start", "book:project", "--title", "Book from FSD V1", "--new-branch"], project, hermetic)
        checked = run([*factory, "check"], project, hermetic)
        record = project / "docs/factory/runs/R-001.md"
        text = record.read_text(encoding="utf-8") if record.is_file() else ""
        check("the set-up project's book run: the referee reads the FSD's outline itself, Loyalty empty",
              started.returncode == 0 and checked.returncode == 0 and "14 sections" in text
              and "- §2.5 Loyalty *(empty)*" in text, started.stdout + started.stderr + checked.stdout + checked.stderr)
        refused = run([sys.executable, "-B", str(KIT / "setup.py"), "--greenfield", "--dir", str(project), "--name", "Shop",
                       "--fsd", str(KIT / "samples/shop-fsd.md"), "--stack", "pytest"], root, hermetic)
        check("setup.py refuses a greenfield setup into a folder that is not empty",
              refused.returncode == 1 and "not empty" in refused.stderr, refused.stdout + refused.stderr)
        two_stack_setup_checks(root, hermetic)
        plan_run_checks(root, hermetic)
        upgrade_merge_checks(root, hermetic)


def two_stack_setup_checks(root: Path, env: dict) -> None:
    """setup.py --greenfield --stacks: a folder and a skeleton per stack, and a config the referee loads."""
    import tomllib
    project = root / "app"
    made = run([sys.executable, "-B", str(KIT / "setup.py"), "--greenfield", "--dir", str(project), "--name", "App",
                "--fsd", str(KIT / "samples/shop-fsd.md"), "--stacks", "backend=dotnet,frontend=react-vitest", "--json"],
               root, env)
    result = json.loads(made.stdout) if made.stdout.strip().startswith("{") else {}
    expected = ["backend/App.slnx", "backend/src/App/Greeting.cs", "backend/tests/App.Tests/App.Tests.csproj",
                "frontend/package.json", "frontend/package-lock.json", "frontend/src/App.tsx", "frontend/src/App.test.tsx",
                "frontend/vite.config.ts", "frontend/eslint.config.js"]
    missing = [rel for rel in expected if not (project / rel).is_file()]
    clean = run(["git", "status", "--porcelain"], project, env).stdout.strip() if project.is_dir() else "?"
    check("setup.py --greenfield --stacks backend=dotnet,frontend=react-vitest writes a skeleton in each folder and commits",
          made.returncode == 0 and result.get("stack") == "backend=dotnet,frontend=react-vitest" and not missing and not clean,
          f"missing {missing}; {made.stdout[-400:]}{made.stderr[-300:]}")
    config = tomllib.loads((project / "devtools/factory/factory.toml").read_text(encoding="utf-8")) if project.is_dir() else {}
    backend = next((s for s in config.get("stacks", []) if s["root"] == "backend"), {})
    loaded = run([sys.executable, "-B", "-c",
                  "import sys; sys.path.insert(0, 'devtools/factory'); import factory; c = factory.load_config(__import__('pathlib').Path('.'));"
                  " print(list(c.step('tests').writes)); print(factory.adapter(c)['test_files'])"], project, env)
    check("the two-stack project's factory.toml: the referee loads it; the tests step writes under each root; the "
          "skeleton's solution and test project are the backend's commands",
          loaded.returncode == 0 and "'backend/tests/**', 'backend/*.slnx', 'backend/*.sln', 'frontend/src/*.test.ts', 'frontend/src/*.test.tsx'" in loaded.stdout
          and backend.get("commands", {}).get("build") == "dotnet build App.slnx"
          and backend.get("commands", {}).get("test_projects_always") == ["tests/App.Tests"],
          loaded.stdout[-400:] + loaded.stderr[-400:])


# The plan a draft-plan session writes for the sample book's Pricing feature (§2.1 of the shop FSD), in
# the template's shape: status line, §1 citing the feature's section, §9 Tasks all Not started.
PRICING_PLAN = """# Pricing — Design

**Status:** `Not started` · **Owner:** Kit Selftest · **FSD:** §2.1 · **Checked against:** FSD V1 · **Depends on:** Authentication plumbing

## 1. What the FSD says

§2.1.1 Price list: every product has one price. §2.1.2 Price changes: a change applies from the next cart.

## 9. Tasks

| # | Task | FSD | Role | Status | Jira | PR | Merged |
|---|---|---|---|---|---|---|---|
| 1 | The price list | §2.1.1 | BE | Not started | — | — | — |
| 2 | Price changes | §2.1.2 | BE | Not started | — | — | — |
"""
# Writes the Design section a draft-plan session writes: the link to the plan, from the run file.
DESIGN_LINK = """
import sys
from pathlib import Path
sys.path.insert(0, "devtools/factory")
import factory
root = Path(".")
path = root / "docs/factory/runs" / (sys.argv[1] + ".md")
run = factory.parse_run(path.read_text(encoding="utf-8"), path)
run.sections["Design"] = "**Plan:** [pricing](../../plans/pricing.md)"
path.write_text(factory.render_run(run, factory.load_config(root)), encoding="utf-8")
"""


def run_record(text: str) -> dict:
    """A run file's Record, or {} when it has none."""
    found = re.search(r"```json factory-record\n(.*?)\n```", text, re.S)
    return json.loads(found.group(1)) if found else {}


def plan_run_checks(root: Path, env: dict) -> None:
    """
    A fresh greenfield project whose book is approved (the kit's sample book) starts a plan run, drives
    it with the stand-in CLI to the plan gate — the draft-plan session played here, with the roll-up
    regenerated as its prompt says — and, once the plan is on main, starts a task run (`plan:<stem>#<n>`)
    that drives to its spec gate.
    """
    project = root / "plans"
    made = run([sys.executable, "-B", str(KIT / "setup.py"), "--greenfield", "--dir", str(project), "--name", "Shop",
                "--fsd", str(KIT / "samples/shop-fsd.md"), "--stack", "pytest", "--json"], root, env)
    if made.returncode != 0:
        check("a greenfield project for the plan run", False, made.stdout[-400:] + made.stderr[-400:])
        return
    factory = [sys.executable, "-B", "devtools/factory/factory.py"]
    shutil.copy2(KIT / "samples/shop-project.md", project / "docs/project.md")
    config = project / "devtools/factory/factory.toml"
    fake = (project / "devtools/factory/fake_claude.py").as_posix()
    config.write_text(config.read_text(encoding="utf-8").replace('claude = "claude"', f'claude = "{fake}"'), encoding="utf-8")
    rollup(project)
    run(["git", "add", "-A"], project, env)
    run(["git", "commit", "-q", "-m", "The approved book"], project, env)
    good = {**env, "FAKE_CLAUDE_MODE": "good"}

    started = run([*factory, "start", "plan:pricing", "--title", "Pricing — plan", "--new-branch"], project, good)
    branch = run(["git", "branch", "--show-current"], project, env).stdout.strip()
    check("a fresh greenfield project starts a plan run: `factory start plan:pricing --new-branch`",
          started.returncode == 0 and "a plan run" in started.stdout and branch == "chore/docs-plan-pricing",
          started.stdout[-400:] + started.stderr[-400:] + f" branch {branch}")
    if started.returncode != 0:
        return
    run_id = re.search(r"Started (R-\d+)", started.stdout).group(1)
    early = run([*factory, "drive", "--steps", "3"], project, good)
    record = (project / f"docs/factory/runs/{run_id}.md").read_text(encoding="utf-8")
    check("drive runs the plan run's intake, context and sources (the kit's plan prompts, the stand-in CLI)",
          early.returncode == 0 and "next is draft-plan" in early.stdout,
          early.stdout[-600:] + early.stderr[-300:] + record[-300:])

    (project / "docs/plans/pricing.md").write_text(PRICING_PLAN, encoding="utf-8", newline="\n")
    tracker = project / "docs/project.md"
    tracker.write_text(tracker.read_text(encoding="utf-8").replace(
        "| Pricing | §2.1 Pricing | |", "| Pricing | §2.1 Pricing | [`pricing.md`](plans/pricing.md) |", 1), encoding="utf-8")
    rollup(project)
    run([sys.executable, "-B", "-c", DESIGN_LINK, run_id], project, env)
    run(["git", "add", "-A"], project, env)
    run(["git", "commit", "-q", "-m", f"The Pricing plan (plan:pricing, {run_id})"], project, env)
    drafted = run([*factory, "check"], project, env)
    gate = run([*factory, "drive"], project, good)
    check("draft-plan passes the referee's plan-doc check (the roll-up's check as evidence), and drive stops at plan-gate",
          drafted.returncode == 0 and "waits at plan-gate" in gate.stdout,
          drafted.stdout[-700:] + drafted.stderr[-300:] + gate.stdout[-300:])

    # The referee's own writes at the gate (the run file, INDEX.md) are committed, as a person would before
    # leaving the branch; then the plan reaches main as its merge would bring it.
    run(["git", "add", "-A"], project, env)
    run(["git", "commit", "-q", "-m", f"Record {run_id} at its plan gate"], project, env)
    run(["git", "checkout", "-q", "main"], project, env)
    run(["git", "checkout", "chore/docs-plan-pricing", "--", "docs/plans/pricing.md", "docs/project.md"], project, env)
    run(["git", "commit", "-q", "-m", "The Pricing plan, merged"], project, env)
    task = run([*factory, "start", "plan:pricing#1", "--title", "The price list", "--new-branch"], project, good)
    branch = run(["git", "branch", "--show-current"], project, env).stdout.strip()
    driven = run([*factory, "drive"], project, good) if task.returncode == 0 else task
    # The stand-in writes a spec with no **FSD:** line, which a project with an FSD refuses: the drive stops
    # there, after the task run's intake and context have passed with the task's row as its brief.
    record = (project / "docs/factory/runs/R-002.md").read_text(encoding="utf-8") if task.returncode == 0 else ""
    check("once the plan is on main, a task run starts (`plan:pricing#1`, a change run on feature/pricing-t1) and "
          "drive takes it through intake and context to its spec",
          task.returncode == 0 and branch == "feature/pricing-t1" and "R-002 · context · attempt 1" in driven.stdout
          and run_record(record).get("kind", "change") == "change" and run_record(record).get("item") == "plan:pricing#1"
          and "**FSD:**" in driven.stdout,
          task.stdout[-400:] + task.stderr[-300:] + driven.stdout[-600:] + f" branch {branch}")
    run(["git", "add", "-A"], project, env)
    run(["git", "commit", "-q", "-m", "Record the task run at its spec gate"], project, env)
    run(["git", "checkout", "-q", "main"], project, env)
    refused = run([*factory, "start", "plan:pricing", "--title", "Pricing again", "--new-branch"], project, env)
    check("a feature that has a plan refuses a second plan run, and names its tasks instead",
          refused.returncode != 0 and "plan:pricing#<n>" in refused.stdout + refused.stderr,
          refused.stdout[-300:] + refused.stderr[-300:])


def older_plan_template() -> bytes:
    """The plan template as kit 1.1.0 wrote it: today's, with this release's two changes taken back out."""
    text = (KIT / "templates/docs/plans/_template.md").read_text(encoding="utf-8")
    text = text.replace("## 1. What the FSD says", "## 1. What the requirements say", 1).replace(
        "  progress counts, and the only one a factory run builds (`factory start plan:<stem>#<number>`).\n"
        "  Where this team builds every stack, back end and front end alike, each of its tasks is\n"
        "  `our_role`'s; the Task cell says which part it is. Other roles' tasks are listed when our\n"
        "  work waits on them or theirs on ours.\n",
        "  progress counts. Other roles' tasks are listed when our work waits on them or theirs on ours.\n", 1)
    return text.encode("utf-8")


def upgrade_merge_checks(root: Path, env: dict) -> None:
    """
    `init.py --upgrade` on a project installed before plan runs: the plan steps, their kinds and [backlog]
    are added to its factory.toml, every value it set is kept, an unedited plan template is refreshed and
    an edited one left alone; and the upgraded project starts a plan run.
    """
    import tomllib
    project = root / "older"
    made = run([sys.executable, "-B", str(KIT / "setup.py"), "--greenfield", "--dir", str(project), "--name", "Shop",
                "--fsd", str(KIT / "samples/shop-fsd.md"), "--stack", "pytest", "--json"], root, env)
    if made.returncode != 0:
        check("a greenfield project to upgrade", False, made.stdout[-400:] + made.stderr[-400:])
        return
    config = project / "devtools/factory/factory.toml"
    # The 1.1.0 shape: no plan steps, no [backlog]; a value the project set; a plan template it edited.
    text = config.read_text(encoding="utf-8")
    for name in ("sources", "draft-plan", "plan-gate"):
        text = re.sub(rf"\[\[steps\]\]\nname = \"{name}\"\n(?:[^\[\n][^\n]*\n)*\n", "", text)
    text = text.replace('kinds = ["change", "plan"]\n', "").replace('kinds = ["change", "plan", "book"]', 'kinds = ["change", "book"]')
    text = text.replace('check = "bitbucket-approval"\nkinds = ["change", "plan"]', 'check = "bitbucket-approval"')
    text = text[:text.index("# ---------------------------------------------------------------- plans")] + \
        text[text.index("[impact]"):]
    text = text.replace("max_attempts = 3", "max_attempts = 5")
    config.write_text(text, encoding="utf-8")
    before = tomllib.loads(text)
    edited = project / "devtools/factory/prompts/package.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nOur own rule.\n", encoding="utf-8")
    template = project / "docs/plans/_template.md"
    template.write_bytes(older_plan_template())
    for rel in ("intake.plan.md", "context.plan.md", "sources.md", "draft-plan.md", "package.plan.md"):
        (project / "devtools/factory/prompts" / rel).unlink()
    run(["git", "add", "-A"], project, env)
    run(["git", "commit", "-q", "-m", "As kit 1.1.0 left it"], project, env)
    upgraded = run([sys.executable, "-B", str(KIT / "init.py"), str(project), "--stack", "pytest", "--upgrade"], KIT, env)
    after = tomllib.loads(config.read_text(encoding="utf-8"))
    steps = {s["name"]: s for s in after.get("steps", [])}
    kept = all(after.get(k) == v for k, v in before.items() if k != "steps") and \
        after["drive"]["max_attempts"] == 5 and [s["name"] for s in after["steps"]][:5] == \
        ["intake", "context", "sources", "draft-plan", "plan-gate"]
    check("init.py --upgrade adds the plan steps, their kinds and [backlog] to an older factory.toml, keeping its values",
          upgraded.returncode == 0 and kept and "plan" in steps["intake"].get("kinds", [])
          and "plan" in steps["merge-gate"].get("kinds", []) and "docs/plans/**" in steps["package"]["writes"]
          and after.get("backlog", {}).get("plan_check") and "Our own rule." in edited.read_text(encoding="utf-8")
          and "## 1. What the FSD says" in template.read_text(encoding="utf-8")
          and (project / "devtools/factory/prompts/draft-plan.md").is_file(),
          upgraded.stdout[-900:] + upgraded.stderr[-400:])
    shutil.copy2(KIT / "samples/shop-project.md", project / "docs/project.md")
    rollup(project)
    run(["git", "add", "-A"], project, env)
    run(["git", "commit", "-q", "-m", "Upgrade the kit; the approved book"], project, env)
    started = run([sys.executable, "-B", "devtools/factory/factory.py", "start", "plan:discounts", "--title",
                   "Discounts — plan", "--new-branch"], project, env)
    check("the upgraded project starts a plan run", started.returncode == 0 and "a plan run" in started.stdout,
          started.stdout[-400:] + started.stderr[-400:])


# A run through the real toolchain: one criterion per stack. The front end's test names what the build
# step will add (`formatPrice`), so TypeScript proves it red by a missing symbol; a pytest stack's test
# fails on a wrong answer; the fix makes both green.
FRONT_TEST = ('import { describe, expect, it } from "vitest";\nimport { formatPrice } from "./price";\n\n'
              'describe("price", () => {\n  it("formats cents as dollars [AC {ac}]", () => {\n'
              '    expect(formatPrice(1999)).toBe("$19.99");\n  });\n});\n')
FRONT_FIX = ('export function cents(amount: number): number {\n  return Math.round(amount * 100);\n}\n\n'
             'export function formatPrice(value: number): string {\n  return `$${(value / 100).toFixed(2)}`;\n}\n')
BACK_TEST = ("import sys\nfrom pathlib import Path\n\nimport pytest\n\n"
             "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\nfrom calc import add  # noqa: E402\n\n\n"
             "@pytest.mark.ac(\"{ac}\")\ndef test_adds_negative_numbers():\n    assert add(-2, -3) == -5\n")
BACK_BUG = "def add(a, b):\n    return abs(a) + abs(b)\n"
BACK_FIX = "def add(a, b):\n    return a + b\n"
# Puts the run at its tests step as a person leaves it after approving the spec (the referee's own
# tests do the same): every step before tests passed, the spec gate recorded against this Spec.
AT_TESTS = """
import sys
from pathlib import Path
sys.path.insert(0, "devtools/factory")
import factory
root = Path(".")
path = root / "docs/factory/runs/R-001.md"
run = factory.parse_run(path.read_text(encoding="utf-8"), path)
run.sections["Spec"] = sys.argv[1]
run.sections["Plan"] = sys.argv[2]
run.record["steps"] = {name: {"status": "passed"} for name in ("intake", "context", "spec", "design", "plan")}
run.record["gates"] = {"spec-gate": {"by": "Kit Selftest", "at": "t", "section_sha256": factory.section_digest(run, "Spec")}}
path.write_text(factory.render_run(run, factory.load_config(root)), encoding="utf-8")
"""


def change_run_checks(repo: Path, found: list[tuple[str, str]], env: dict) -> None:
    """A change run through the real toolchain, from the tests step to verify, per stack in its root."""
    factory = [sys.executable, "-B", "devtools/factory/factory.py"]
    fronts = [root for root, name in found if name == "react-vitest"]
    backs = [root for root, name in found if name == "pytest"]
    npm = shutil.which("npm")
    installs = []
    for root in fronts:
        folder = repo / root if root else repo
        installs.append(run([npm or "npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"], folder, env)
                        if npm else None)
    check("npm installs each front end's pinned packages (from its lock file)",
          bool(npm) and all(done is not None and done.returncode == 0 for done in installs),
          "no npm on PATH" if not npm else "".join((done.stdout + done.stderr)[-500:] for done in installs if done))
    if not npm or any(done.returncode != 0 for done in installs):
        return

    def at(root: str, rel: str) -> str:
        return f"{root}/{rel}" if root else rel

    criteria, tests_files, fix_files = [], [], []
    for index, root in enumerate([*fronts, *backs], 1):
        criteria.append(f"- **R-001.AC-{index}** — " + ("Given 1999 cents, when shown, then it reads $19.99." if root in fronts
                                                         else "Given -2 and -3, when added, then the sum is -5."))
        tests_files.append(at(root, "src/price.test.ts") if root in fronts else at(root, "tests/test_negative.py"))
        fix_files.append(at(root, "src/price.ts") if root in fronts else at(root, "src/calc.py"))
    plan = ("| Task | Files | Verify |\n|---|---|---|\n"
            f"| 1. Tests | {', '.join(f'`{f}`' for f in tests_files)} | red |\n"
            f"| 2. Fix | {', '.join(f'`{f}`' for f in fix_files)} | green |")
    for root in backs:  # a bug for the backend's criterion to prove red against
        (repo / at(root, "src/calc.py")).write_text(BACK_BUG, encoding="utf-8")
    git(repo, "commit", "-q", "-am", "A bug in add (D1)")
    seeded = run([sys.executable, "-B", "-c", AT_TESTS, "\n".join(criteria), plan], repo, env)
    check("the run is put at its tests step, the spec gate recorded as a person leaves it", seeded.returncode == 0,
          seeded.stderr[-400:])

    first = repo / tests_files[0]
    check("the guard lets the tests step write a test file under its stack's root, and asks for a product file there",
          guard_decision(repo, {"tool_name": "Write", "cwd": str(repo),
                                "tool_input": {"file_path": str(first), "content": "x"}}) == "allow"
          and guard_decision(repo, {"tool_name": "Write", "cwd": str(repo),
                                    "tool_input": {"file_path": str(repo / fix_files[0]), "content": "x"}}) == "ask")

    for index, rel in enumerate(tests_files, 1):
        template = FRONT_TEST if rel.endswith(".ts") else BACK_TEST
        (repo / rel).write_text(template.replace("{ac}", f"R-001.AC-{index}"), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Tests (D1)")
    red = run([*factory, "check"], repo, env)
    record = json.loads(re.search(r"```json factory-record\n(.*?)\n```",
                                  (repo / "docs/factory/runs/R-001.md").read_text(encoding="utf-8"), re.S).group(1))
    acs = (record.get("red") or {}).get("acs", {})
    expected = {f"R-001.AC-{i}": ("does not compile yet — missing symbol" if rel.endswith(".ts") else "1 failing")
                for i, rel in enumerate(tests_files, 1)}
    names = {c["name"] for c in record.get("checks", []) if c["step"] == "tests"}
    check("tests-red: TypeScript proves the front end's criterion red by a missing symbol"
          + (", pytest the backend's by a failing test, each stack built in its own root" if backs else "")
          + ("; a stack the run does not reach is not built" if len(found) > len(fronts) + len(backs) else ""),
          red.returncode == 0 and acs == expected
          and all(f"build {root}" in names for root in [*fronts, *backs] if root)
          # A stack the run does not reach (a .NET backend beside a front-end change) is not built.
          and not any(f"build {root}" in names for root, name in found if root and root not in [*fronts, *backs]),
          red.stdout[-900:] + red.stderr[-400:] + f" red={acs}")
    locked = sorted(record.get("lock", {}))
    check("the red tests are locked, and the front end's whole test project with them",
          all(rel in locked for rel in tests_files) and at(fronts[0], "src/App.test.tsx") in locked, str(locked))

    for rel in fix_files:
        (repo / rel).write_text(FRONT_FIX if rel.endswith(".ts") else BACK_FIX, encoding="utf-8")
    git(repo, "commit", "-q", "-am", "The fix (D1)")
    built = run([*factory, "check"], repo, env)
    check("build: every criterion's tests pass after the fix (Vitest's filtered run counts only its own tests)",
          built.returncode == 0, built.stdout[-900:] + built.stderr[-400:])
    integrated = run([*factory, "check"], repo, env)
    check("integrate: each stack's whole suite passes in its root", integrated.returncode == 0,
          integrated.stdout[-900:] + integrated.stderr[-400:])
    verified = run([*factory, "check"], repo, {**env, "FAKE_CLAUDE_MODE": "good"})
    record = json.loads(re.search(r"```json factory-record\n(.*?)\n```",
                                  (repo / "docs/factory/runs/R-001.md").read_text(encoding="utf-8"), re.S).group(1))
    ran = {c["name"]: c["ok"] for c in record.get("checks", []) if c["step"] == "verify"}
    lint = [name for name in ran if name.endswith(("run lint", "lint"))]
    check("verify: the repository's own check at its root, then each front end's lint and type-check in its root",
          ran.get("factory.py") is True and lint and all(ran[name] for name in lint)
          and any(name.endswith("typecheck") and ok for name, ok in ran.items()),
          f"{ran}; {verified.stdout[-600:]}{verified.stderr[-300:]}")


def main() -> int:
    # A referee message may carry a sign the console's code page cannot print (a Windows console).
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stack", default="pytest",
                        help="pytest, dotnet, react-vitest, or two joined by + (backend/, frontend/), or root=stack,...")
    args = parser.parse_args()
    try:
        found = load_init().parse_stacks(args.stack)
    except ValueError as error:
        parser.error(str(error))

    with tempfile.TemporaryDirectory(prefix="factory-kit-selftest-", ignore_cleanup_errors=True) as folder:
        repo = Path(folder)
        ordinary = make_project(repo, found)

        installed = run([sys.executable, str(KIT / "init.py"), str(repo), "--stack", args.stack,
                         "--base-ref", "main", "--protected", "main"], KIT)
        check("init.py installs", installed.returncode == 0, installed.stderr[-300:])
        for rel in ("devtools/factory/factory.py", "devtools/factory/hooks/guard.py", "devtools/factory/factory.toml",
                    ".claude/settings.json", ".claude/agents/factory-reviewer.md", ".claude/skills/factory/SKILL.md",
                    "docs/defects.md", "requirements/read-me.txt", "CLAUDE.md", "devtools/checks/check-book.py",
                    "devtools/checks/gen-task-rollup.py", "requirements/fsd/read-me.txt", "docs/project.md",
                    "devtools/factory/fsd_outline.py", "devtools/factory/check_project_md.py",
                    ".claude/agents/book-auditor.md", "devtools/factory/prompts/book-features.md",
                    "devtools/factory/prompts/draft-plan.md", "devtools/factory/prompts/sources.md",
                    ".githooks/pre-commit", ".githooks/commit-msg", ".claude/agents/factory-spec-auditor.md",
                    "devtools/checks/check-commit-msg.py", "devtools/checks/check-rules.py"):
            check(f"installed {rel}", (repo / rel).exists())
        app_checks(repo)
        settings = json.loads((repo / ".claude/settings.json").read_text(encoding="utf-8"))
        check("settings wire the guard in and switch attribution off",
              "guard.py" in json.dumps(settings.get("hooks", {})) and settings.get("attribution") == {"commit": "", "pr": ""})
        git(repo, "add", "-A")
        book = run([sys.executable, "devtools/checks/check-book.py"], repo)
        check("the installed book keeps its own rules (links, owners, history)", book.returncode == 0,
              book.stdout[-600:] + book.stderr[-300:])
        book_shape_checks(repo)
        project_md_checker_checks(repo)
        stamp_checks(repo, args.stack)
        git(repo, "commit", "-q", "-m", "Install the AI factory kit")

        snapshot = repo / "requirements" / "spec - V1.md"
        snapshot.parent.mkdir(exist_ok=True)
        snapshot.write_text("# Spec V1\n", encoding="utf-8")
        check("guard refuses changing a requirements snapshot",
              guard_decision(repo, {"tool_name": "Edit", "cwd": str(repo),
                                    "tool_input": {"file_path": str(snapshot), "new_string": "x"}}) == "deny")
        check("guard refuses a push to a protected branch",
              guard_decision(repo, {"tool_name": "Bash", "cwd": str(repo),
                                    "tool_input": {"command": "git push origin main"}}) == "deny")
        check("guard lets an ordinary edit through",
              guard_decision(repo, {"tool_name": "Edit", "cwd": str(repo),
                                    "tool_input": {"file_path": str(repo / ordinary), "new_string": "x"}}) == "allow")
        snapshot.unlink()

        config = repo / "devtools/factory/factory.toml"
        fake = (repo / "devtools/factory/fake_claude.py").as_posix()
        config.write_text(config.read_text(encoding="utf-8").replace('claude = "claude"', f'claude = "{fake}"'),
                          encoding="utf-8")
        git(repo, "checkout", "-q", "--no-track", "-b", "fix/D1-selftest")
        # The referee starts a run only on a defect the book already holds: log D1 first, as a person would.
        defects = repo / "docs/defects.md"
        header = "|---|---|---|---|---|---|---|\n"
        row = ("| **D1** | 🟠 | Open | **A discount over 100% gives a negative price.** | `src/calc.py` "
               "| selftest | No requirements angle |\n")
        defects.write_text(defects.read_text(encoding="utf-8").replace(header, header + row, 1), encoding="utf-8")
        git(repo, "commit", "-q", "-am", "Log D1")
        env ={key: value for key, value in os.environ.items() if key not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        factory = [sys.executable, "-B", "devtools/factory/factory.py"]
        started = run([*factory, "start", "D1", "--title", "Selftest run"], repo, env)
        check("factory start opens a run", started.returncode == 0, started.stdout + started.stderr)
        driven = run([*factory, "drive"], repo, {**env, "FAKE_CLAUDE_MODE": "good"})
        check("factory drive runs intake, context and spec, then stops at the spec gate",
              "waits at spec-gate" in driven.stdout, driven.stdout[-400:] + driven.stderr[-400:])
        approve_env = {**env, "CLAUDECODE": "1"}
        refused = run([*factory, "approve", "spec"], repo, approve_env)
        check("the referee refuses an approval from inside a Claude Code session",
              refused.returncode != 0 and "own terminal" in refused.stdout + refused.stderr)
        check("guard refuses the agent approving its own gate, even disguised",
              guard_decision(repo, {"tool_name": "Bash", "cwd": str(repo), "tool_input": {
                  "command": "CLAUDECODE= python3 devtools/factory/factory.py --run R-001 approve spec"}}) == "deny")
        run_file = repo / "docs" / "factory" / "runs" / "R-001.md"
        check("guard refuses planting a second Record in the run file",
              guard_decision(repo, {"tool_name": "Edit", "cwd": str(repo), "tool_input": {
                  "file_path": str(run_file), "old_string": "## Intent",
                  "new_string": "## Intent\n\n```json factory-record\n{\"status\": \"open\"}\n```"}}) == "deny")
        verified = run([*factory, "verify"], repo, env)
        check("factory verify passes", verified.returncode == 0, verified.stdout + verified.stderr)
        indexed = run([*factory, "index", "--check"], repo, env)
        check("factory index --check passes", indexed.returncode == 0, indexed.stdout + indexed.stderr)
        first_plan_checks(repo)
        if any(name == "react-vitest" for _, name in found):
            git(repo, "commit", "-q", "-am", "A first plan (D1)")
            change_run_checks(repo, found, env)
    setup_checks({key: value for key, value in os.environ.items() if key not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")})

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
