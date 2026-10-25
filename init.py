#!/usr/bin/env python3
"""
Install the AI factory into a repository.

    python init.py <repository> --stack pytest|dotnet|react-vitest [--base-ref main]
                   [--protected main,dev] [--source-roots src/] [--read-only "specs/**"]
    python init.py <repository> --stacks backend=dotnet,frontend=react-vitest   (two stacks, two folders)
    python init.py <repository> --stack dotnet+react-vitest                     (the same: backend, frontend)

Writes devtools/factory/ (the referee, the guard, the Factory app, the step
instructions and a factory.toml for the stack), "Start Factory.cmd" at the top (opens
the app on this project), the Claude Code settings that wire the guard in, the
reviewer agent, the skills, and a documentation skeleton. --merge-check local is for
a project with no remote: a person approves the merge locally, not in Bitbucket. It never overwrites a file the repository already has: settings and
.gitignore are merged, and everything else it skips is listed at the end.
Python 3.11+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib  # Python 3.11+, as the factory itself needs
from pathlib import Path

KIT = Path(__file__).resolve().parent
TEMPLATES = KIT / "templates"
# This kit's release: MAJOR.MINOR.PATCH, raised with every change to what an install writes or how it
# behaves. An install stamps it at the top of factory.toml as `kit_version`, and --upgrade moves the
# stamp; `factory version` and the Factory app read it back per project.
VERSION = "1.7.1"
# The container files at a repository's top, which the build step writes from the start: a step that needed one
# stopped at its plan for a person to allow it. Pipelines stay out; they are a person's.
ROOT_BUILD_WRITES = ["Dockerfile", ".dockerignore", "compose.yaml", ".env.example"]
# The merge gate's check: a Bitbucket pull request's approval, or a person's local `factory approve merge`
# for a project with no remote.
MERGE_CHECKS = {"bitbucket": "bitbucket-approval", "github": "github-approval", "local": "local-approval"}
# The Factory app's double-click launcher, placed at the repository's top: it opens this project in the app.
LAUNCHER = "Start Factory.cmd"
KIT_STAMP_KEY = "kit_version"
KIT_STAMP_LINE = re.compile(rf"^{KIT_STAMP_KEY}[ \t]*=[^\r\n]*", re.MULTILINE)
GUARD_COMMAND = ('for py in python3 python; do if "$py" -c pass >/dev/null 2>&1; then exec "$py" '
                 '"${CLAUDE_PROJECT_DIR:-.}/devtools/factory/hooks/guard.py"; fi; done')
# Before a tool runs, no Python means the guard could not judge the call: refuse it rather than let it through unjudged.
NO_PYTHON_DENY = ('; echo \'{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",'
                  '"permissionDecisionReason":"guard: no working Python on PATH, so the guard could not judge '
                  'this call and refuses it. Install Python 3.11+ and put it on PATH."}}\'')
ADAPTERS = TEMPLATES / "adapters"
# An adapter file opens with its [kit] table — what the installer needs, kept out of factory.toml —
# and the factory.toml part starts at the first section rule.
ADAPTER_BODY = "# ----------------------------------------------------------------"
KIT_KEYS = ("test_writes", "build_writes", "cross_cutting", "guard_dotnet_ef", "guard_appsettings_secrets")
# The git hooks, tracked in the repository (.git/hooks is per clone): the install turns them on with
# core.hooksPath, so the checks hold from the first commit.
HOOKS_DIR = ".githooks"
# A hook stays LF wherever it is checked out: sh reads a CRLF line as a different command.
HOOKS_ATTRIBUTES = ".githooks/* text eol=lf"


def stacks() -> list[str]:
    """Every stack the kit can install: one adapter file each. A new stack is a new file, no code."""
    return sorted(path.stem for path in ADAPTERS.glob("*.toml"))


# Two stacks named `a+b` sit in these folders, in that order; `--stacks root=stack,...` names its own.
DEFAULT_ROOTS = ("backend", "frontend")
# A verify command that runs the referee's own tools runs once, at the repository's root; a stack's other
# verify commands (lint, type-check) run in its root.
REPO_VERIFY = "python3 devtools/"


def parse_stacks(spec: str) -> list[tuple[str, str]]:
    """
    `pytest` -> [("", "pytest")]; `dotnet+react-vitest` -> backend, frontend; `backend=dotnet,frontend=react-vitest`
    -> as named. Refuses a stack the kit has no adapter for, a root used twice, or one inside another.
    """
    known = stacks()
    if "=" in spec:
        pairs = [part.split("=", 1) for part in spec.split(",") if part.strip()]
        found = [(root.strip().strip("/"), name.strip()) for root, name in pairs]
    elif "+" in spec:
        names = [name.strip() for name in spec.split("+") if name.strip()]
        if len(names) > len(DEFAULT_ROOTS):
            raise ValueError(f"{spec}: name more than {len(DEFAULT_ROOTS)} stacks with --stacks root=stack,...")
        found = list(zip(DEFAULT_ROOTS, names))
    else:
        found = [("", spec.strip())]
    unknown = [name for _, name in found if name not in known]
    if unknown:
        raise ValueError(f"no adapter for {', '.join(unknown)}; the kit has {', '.join(known)}")
    roots = [root for root, _ in found]
    if len(found) > 1 and (not all(roots) or len(set(roots)) != len(roots)
                           or any(a != b and (b + "/").startswith(a + "/") for a in roots for b in roots)):
        raise ValueError(f"{spec}: each stack needs a folder of its own (backend=...,frontend=...)")
    return found


def stack_label(found: list[tuple[str, str]]) -> str:
    """How factory.toml's header and setup's report name the stacks: `pytest`, or `backend=dotnet,frontend=react-vitest`."""
    return found[0][1] if len(found) == 1 and not found[0][0] else ",".join(f"{root}={name}" for root, name in found)


def install_stacks(args: argparse.Namespace) -> list[tuple[str, str]]:
    """The stacks an install writes, as (root, adapter): args.stacks when parsed, else args.stack."""
    return getattr(args, "stacks", None) or parse_stacks(args.stack)


def adapter(stack: str) -> tuple[dict, str]:
    """The stack's [kit] settings, and the adapter text that goes into factory.toml."""
    text = (ADAPTERS / f"{stack}.toml").read_text(encoding="utf-8")
    kit = tomllib.loads(text).get("kit", {})
    missing = [key for key in KIT_KEYS if key not in kit]
    if missing:
        raise SystemExit(f"templates/adapters/{stack}.toml: [kit] lacks {', '.join(missing)}")
    if ADAPTER_BODY not in text:
        raise SystemExit(f"templates/adapters/{stack}.toml: no '{ADAPTER_BODY}' line starts the adapter")
    return kit, text[text.index(ADAPTER_BODY):]


class Installer:
    def __init__(self, repository: Path):
        self.repository = repository
        self.written: list[str] = []
        self.skipped: list[str] = []

    def place(self, rel: str, content: str | None = None, source: Path | None = None) -> None:
        target = self.repository / rel
        if target.exists():
            self.skipped.append(rel)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        if source is not None:
            shutil.copy2(source, target)
        else:
            target.write_text(content or "", encoding="utf-8", newline="\n")
        self.written.append(rel)

    def place_tree(self, source: Path, rel: str) -> None:
        for path in sorted(source.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                self.place(f"{rel}/{path.relative_to(source).as_posix()}", source=path)


# The kit's own code: replaced on --upgrade. The guard's mode file is the project's choice, so it stays.
KIT_CODE = ("factory.py", "bitbucket.py", "drive.py", "jira.py", "fake_claude.py", "hooks/guard.py",
            "fsd_outline.py", "check_project_md.py",
            # The Factory app: the referee's commands in plain words, in a browser.
            "console/console.py", "console/app_data.py", "console/wizard.py", "console/index.html",
            "console/Start Factory.cmd", "console/Start Factory.ps1")


def upgrade(repository: Path, args: argparse.Namespace) -> int:
    """
    Bring an installed repository's factory up to this kit. Code is replaced; anything the
    project owns — factory.toml, its prompts, its docs, the guard's mode — is never touched,
    except the one `kit_version` line at the top of factory.toml, which says which kit it now holds.
    A setting the new template has and the project's config lacks is listed for a person.
    """
    if not (repository / "devtools" / "factory" / "factory.toml").exists():
        print(f"{repository} has no devtools/factory/factory.toml. Install first, without --upgrade.")
        return 1
    replaced, added, missing, changed_steps = upgrade_files(repository, args)
    print(f"Upgraded the AI factory in {repository} to kit {VERSION}\n")
    print("Replaced:\n" + ("\n".join(f"  {rel}" for rel in replaced) or "  nothing, already current"))
    print("Added step instructions, checks and agents:\n" + ("\n".join(f"  {rel}" for rel in added) or "  none"))
    if missing or changed_steps:
        print("\nfactory.toml: the kit's template has these and this project's does not. Add them by hand\n"
              "(the template is templates/factory.toml and templates/adapters/):\n"
              + "\n".join(f"  {key}" for key in [*missing, *changed_steps]))
    print("\nNext: commit on a branch, and run `python3 devtools/factory/factory.py verify --all`.")
    return 0


def upgrade_files(repository: Path, args: argparse.Namespace) -> tuple[list[str], list[str], list[str], list[str]]:
    """
    The upgrade itself: the kit's code replaced; step instructions, checks and agents the project lacks
    added (never one it has); and, for a person, the settings and steps the template has that the
    project's factory.toml lacks or checks differently. `setup.py --brownfield` reports the same lists.
    """
    factory_dir = repository / "devtools" / "factory"
    replaced = []
    stamped = stamp_kit_version(factory_dir / "factory.toml")
    if stamped:
        replaced.append(f"devtools/factory/factory.toml: {stamped}")
    for rel in KIT_CODE:
        source, target = KIT / "factory" / rel, factory_dir / rel
        if source.read_bytes() != (target.read_bytes() if target.exists() else b""):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            replaced.append(f"devtools/factory/{rel}")
    installer = Installer(repository)
    installer.place_tree(TEMPLATES / "prompts", "devtools/factory/prompts")
    installer.place_tree(TEMPLATES / "checks", "devtools/checks")
    installer.place_tree(TEMPLATES / "agents", ".claude/agents")
    installer.place(LAUNCHER, source=TEMPLATES / LAUNCHER)
    place_test_rules(installer, args)
    place_hooks(installer, turn_on=False)
    # What the person must do to turn the hooks on goes out with what was added.
    installer.written += [note for note in installer.skipped if "core.hooksPath" in note]
    replaced += refresh_unedited(repository)
    rendered = render_config(args)
    replaced += [f"devtools/factory/factory.toml: {change}"
                 for change in merge_template_into_config(factory_dir / "factory.toml", rendered)]

    project = tomllib.loads((factory_dir / "factory.toml").read_text(encoding="utf-8"))
    template = tomllib.loads(rendered)
    missing = [key for key in flat_keys(template) if key not in set(flat_keys(project))]
    # Each stack's own settings, matched by name: an adapter key a new kit adds (install_package) is listed too.
    project_stacks = {s.get("name"): s for s in project.get("stacks", []) if isinstance(s, dict)}
    missing += [f"stacks {s.get('name')}: {key}" for s in template.get("stacks", []) if s.get("name") in project_stacks
                for key in flat_keys(s) if key not in set(flat_keys(project_stacks[s["name"]]))]
    project_steps = {s["name"]: s for s in project.get("steps", [])}
    missing += [f"step {s['name']} ({', '.join(s.get('kinds', ['change']))})" for s in template.get("steps", [])
                if s["name"] not in project_steps]
    # Bitbucket or local approval at the merge gate is the project's choice, not a difference to report.
    approvals = set(MERGE_CHECKS.values())
    changed_steps = [f"step {s['name']}: the kit checks `{s.get('check')}`, this project `{project_steps[s['name']].get('check')}`"
                     for s in template.get("steps", [])
                     if s["name"] in project_steps and s.get("check") != project_steps[s["name"]].get("check")
                     and not {s.get("check"), project_steps[s["name"]].get("check")} <= approvals]
    return replaced, installer.written, missing, changed_steps


# Files a project owns but the kit wrote, refreshed on --upgrade only while they are byte for byte (line
# endings aside) a version an earlier kit release wrote: never a file the project has edited. Each names
# its template and the sha256 of every earlier release's text.
KIT_REFRESH = {
    "docs/plans/_template.md": ("templates/docs/plans/_template.md", {
        "b603716b9bdbe5eea68b225b3835adfd7e6d7b2d9c01b4b3b29d1b958ad4e2b7",   # 1.0.x
        "12adbba185d20e95a8d697e6d32fd308e003230cb4ee1615bdf7a3d3fac04964"}),  # 1.1.0
    "devtools/factory/prompts/package.md": ("templates/prompts/package.md", {
        "68c151873c791729f139db3e4443af2a6bab4e744f17fad235006cded4991307",    # 1.0.x-1.1.0
        "f2d8ccaa24297a8283f65915e2330588f0a6e5fc32276cb739396c70e10f9442"}),  # 1.2.0
    # 1.6.0: plain-words questions, an approved design's packages, the system overview, the revision audit.
    "devtools/factory/prompts/_preamble.md": ("templates/prompts/_preamble.md", {
        "3e3187bda9b7ed6a38745ed1b24beb6eba47ed2d7cfbedca468578ee5712b8d2"}),  # 1.4.0-1.5.0
    "devtools/factory/prompts/book-features.md": ("templates/prompts/book-features.md", {
        "1ea6424e130fe8b5af6efe13e90159167ad432d3aa76ba89d6795838c536b847"}),  # 1.4.0-1.5.0
    "devtools/factory/prompts/book-inventory.md": ("templates/prompts/book-inventory.md", {
        "ed3c7119279188744db2e38c15885ac93b577bb5d00c5496bdc73e3c0a711ac7"}),  # 1.4.0-1.5.0
    "devtools/factory/prompts/design.md": ("templates/prompts/design.md", {
        "3dbbfbc66f46d2809a9f579787a9296981a11e38022852c12c90b5eb6b901b00",   # 1.4.0
        "f0fb88b6a583d853355fe8e21d4783ec32e192ba276b15c894b296d75a775e2b",   # 1.5.0
        "b206be53397a54d743ab1a3d39065d33b26368e6224b8342f1f479b315b9cfb1"}),  # 1.6.0
    ".claude/agents/book-auditor.md": ("templates/agents/book-auditor.md", {
        "0ad070b583a33554dcda58922d5bc71579c81890cf7fc98e192be111a194279b"}),  # 1.4.0-1.5.0
}


def text_sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def refresh_unedited(repository: Path) -> list[str]:
    """Replace each KIT_REFRESH file the project still holds exactly as an earlier kit wrote it."""
    refreshed = []
    for rel, (source, earlier) in KIT_REFRESH.items():
        target, new = repository / rel, (KIT / source).read_bytes()
        if target.is_file() and text_sha(target.read_bytes()) in earlier and text_sha(new) != text_sha(target.read_bytes()):
            shutil.copy2(KIT / source, target)
            refreshed.append(f"{rel} (unedited since an earlier kit)")
    return refreshed


# Tables --upgrade never adds whole: they are the stack's, and an install writes them from the adapter.
STACK_TABLES = ("adapter", "stacks", "commands", "drive", "impact")
STEP_HEADER = re.compile(r"^\[\[steps\]\][ \t]*\r?$", re.MULTILINE)
TABLE_HEADER = re.compile(r"^\[\[?[A-Za-z0-9_.\"-]+\]\]?[ \t]*(#[^\r\n]*)?\r?$", re.MULTILINE)


def step_blocks(text: str) -> list[dict]:
    """
    Each [[steps]] entry in a factory.toml's text: its name, where its header starts, where its own
    lines end (before the blank and comment lines that lead into the next table), and its values.
    """
    headers = [m.start() for m in TABLE_HEADER.finditer(text)]
    blocks = []
    for match in STEP_HEADER.finditer(text):
        start = match.start()
        after = next((h for h in headers if h > start), len(text))
        lines = text[start:after].splitlines(keepends=True)
        while len(lines) > 1 and (not lines[-1].strip() or lines[-1].lstrip().startswith("#")):
            lines.pop()
        end = start + len("".join(lines))
        values = tomllib.loads("[[steps]]\n" + "".join(lines[1:]))["steps"][0]
        blocks.append({"name": values.get("name"), "start": start, "end": end, "values": values})
    return blocks


def set_list(block: str, key: str, values: list[str], before: str = "writes") -> str:
    """A step block with `key = [...]` set to these values: its line (one or several) replaced, or added."""
    line = f"{key} = {toml_list(values)}"
    found = re.search(rf"^{key}[ \t]*=[ \t]*\[[^\]]*\][^\r\n]*", block, re.MULTILINE)
    if found:
        return block[:found.start()] + line + block[found.end():]
    newline = "\r\n" if "\r\n" in block else "\n"
    anchor = re.search(rf"^{before}[ \t]*=", block, re.MULTILINE)
    if anchor:
        return block[:anchor.start()] + line + newline + block[anchor.start():]
    return block.rstrip("\r\n") + newline + line + (newline if block.endswith(("\n", "\r\n")) else "")


def merge_template_into_config(config: Path, rendered: str) -> list[str]:
    """
    Bring the kit's steps and settings tables into an installed factory.toml without touching a value
    the project set: a step the template has and the project lacks is added beside its neighbours, with
    its comments; a step both have gains the run kinds the template gives it and the `docs/` paths it
    may write (never loses one); a whole table the project lacks (`[backlog]`) is added at the end. Every
    setting already there keeps its value — checked after the merge, and nothing is written otherwise.
    Returns what changed, for the person.
    """
    original = config.read_text(encoding="utf-8", newline="")
    newline = "\r\n" if "\r\n" in original else "\n"
    template = rendered.replace("\r\n", "\n")
    text = original
    changes: list[str] = []
    wanted = step_blocks(template)
    # 1. Steps the project lacks: each run of them goes in after the template step before it.
    while True:
        have = {block["name"]: block for block in step_blocks(text)}
        missing = [i for i, block in enumerate(wanted) if block["name"] not in have]
        if not missing:
            break
        first = missing[0]
        last = first
        while last + 1 < len(wanted) and wanted[last + 1]["name"] not in have:
            last += 1
        if first == 0:
            # Before the project's first step (or at the end, with none): the steps and a blank line.
            chunk = template[wanted[0]["start"]:wanted[last]["end"]] + "\n"
            at = step_blocks(text)[0]["start"] if have else len(text)
        else:
            # After the step the template puts before them: the blank and comment lines between, then them.
            chunk = template[wanted[first - 1]["end"]:wanted[last]["end"]]
            at = have[wanted[first - 1]["name"]]["end"]
        text = text[:at] + chunk.replace("\n", newline) + text[at:]
        names = [block["name"] for block in wanted[first:last + 1]]
        kinds = sorted({k for block in wanted[first:last + 1] for k in block["values"].get("kinds", ["change"])})
        changes.append(f"added step{'s' if len(names) > 1 else ''} {', '.join(names)} ({', '.join(kinds)} runs)")
    # 2. Steps both have: the template's kinds, and its docs/ paths, added to the project's.
    for block in wanted:
        current = {b["name"]: b for b in step_blocks(text)}[block["name"]]
        own, values = text[current["start"]:current["end"]], current["values"]
        kinds = values.get("kinds", ["change"])
        more_kinds = [k for k in block["values"].get("kinds", ["change"]) if k not in kinds]
        writes = values.get("writes")
        more_writes = [w for w in block["values"].get("writes", []) if w.startswith("docs/")
                       and writes is not None and w not in writes]
        if not more_kinds and not more_writes:
            continue
        if more_kinds:
            own = set_list(own, "kinds", [*kinds, *more_kinds])
            changes.append(f"step {block['name']} now also serves {', '.join(more_kinds)} runs")
        if more_writes:
            own = set_list(own, "writes", [*writes, *more_writes])
            changes.append(f"step {block['name']} may also write {', '.join(more_writes)}")
        text = text[:current["start"]] + own + text[current["end"]:]
    # 3. Whole tables the project lacks, with the comments that lead into them.
    project = tomllib.loads(text)
    tables = [m for m in TABLE_HEADER.finditer(template) if not m.group(0).startswith("[[")]
    for match in tables:
        name = match.group(0).strip().strip("[]").split(".")[0].strip('"')
        if name in project or name in STACK_TABLES or name == "steps" or not isinstance(tomllib.loads(template).get(name), dict):
            continue
        if f"[{name}]" != match.group(0).split("#")[0].strip():
            continue  # a sub-table goes in with its parent
        lines = template[:match.start()].split("\n")[:-1]
        lead = []
        while lines and lines[-1].startswith("#"):
            lead.insert(0, lines.pop())
        after = next((m.start() for m in TABLE_HEADER.finditer(template, match.end())
                      if m.group(0).strip().strip("[]").split(".")[0].strip('"') != name), len(template))
        body = template[match.start():after].split("\n")
        while body and (not body[-1].strip() or body[-1].startswith("#")):
            body.pop()
        chunk = "\n".join([*lead, *body]) + "\n"
        text = text.rstrip("\r\n") + newline + newline + chunk.replace("\n", newline)
        project = tomllib.loads(text)
        changes.append(f"added [{name}]")
    if not changes:
        return []
    # Nothing the project set may have moved: every setting it had keeps its value, every step its fields.
    before, after = tomllib.loads(original), tomllib.loads(text)
    kept = all(lookup(after, path) == value for path, value in flat_items(before))
    steps_after = {s["name"]: s for s in after.get("steps", [])}
    kept = kept and all(
        all(steps_after.get(s["name"], {}).get(k) == v for k, v in s.items() if k not in ("kinds", "writes"))
        and set(s.get("kinds", ["change"])) <= set(steps_after.get(s["name"], {}).get("kinds", ["change"]))
        and set(s.get("writes", [])) <= set(steps_after.get(s["name"], {}).get("writes", []))
        for s in before.get("steps", []))
    if not kept:
        return ["could not merge the kit's steps and tables without changing a setting; add them by hand"]
    config.write_text(text, encoding="utf-8", newline="")
    return changes


def flat_items(table: dict, path: tuple = ()) -> list[tuple[tuple, object]]:
    """Every setting with its value, by its path of keys; the steps are compared on their own."""
    items = []
    for key, value in table.items():
        if not path and key == "steps":
            continue
        items += flat_items(value, (*path, key)) if isinstance(value, dict) else [((*path, key), value)]
    return items


def lookup(table: dict, path: tuple):
    for part in path:
        table = table.get(part) if isinstance(table, dict) else None
    return table


def flat_keys(table: dict, prefix: str = "") -> list[str]:
    """Every setting as section.key; arrays of tables (the steps) are compared separately."""
    keys = []
    for key, value in table.items():
        if key == "steps":
            continue
        name = f"{prefix}{key}"
        keys += flat_keys(value, name + ".") if isinstance(value, dict) else [name]
    return keys


def stamp_kit_version(config: Path, version: str = VERSION) -> str:
    """
    Set the top-level `kit_version` in an installed factory.toml to this kit's VERSION: the existing
    line replaced, or one line added before the first setting (above every table, so it stays top
    level). Every other byte of the file is left as it was. Returns what changed, or "" when current.
    """
    text = config.read_text(encoding="utf-8")
    line = f'{KIT_STAMP_KEY} = "{version}"'
    found = KIT_STAMP_LINE.search(text)
    if found:
        if found.group(0).strip() == line:
            return ""
        was = found.group(0).split("=", 1)[1].strip().strip('"') or "none"
        text = text[:found.start()] + line + text[found.end():]
        config.write_text(text, encoding="utf-8", newline="")
        return f"{KIT_STAMP_KEY} {was} to {version}"
    lines = text.splitlines(keepends=True)
    at = next((i for i, l in enumerate(lines) if l.strip() and not l.lstrip().startswith("#")), len(lines))
    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    lines.insert(at, line + newline + (newline if at < len(lines) and lines[at].lstrip().startswith("[") else ""))
    config.write_text("".join(lines), encoding="utf-8", newline="")
    return f"{KIT_STAMP_KEY} added: {version}"


def merge_check(args: argparse.Namespace) -> str:
    """The merge gate's check for factory.toml: `bitbucket` (the default) or `local`, from --merge-check."""
    return MERGE_CHECKS[getattr(args, "merge_check", None) or "bitbucket"]


def toml_list(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(value) for value in values) + "]"


# The role whose tasks each adapter's stack builds; any other is a back end's.
ADAPTER_ROLE = {"react-vitest": "FE"}


def our_role_toml(adapters: list[str]) -> str:
    """`[book] our_role` for the stacks installed: "BE", "FE", or ["BE", "FE"] for a team that builds both halves --
    with "BE" alone a .NET + React project's front-end tasks were never ours, so a plan labelled them BE."""
    roles = list(dict.fromkeys(ADAPTER_ROLE.get(name, "BE") for name in adapters))
    return json.dumps(roles[0]) if len(roles) == 1 else toml_list(roles)


def render_config(args: argparse.Namespace) -> str:
    found = install_stacks(args)
    if len(found) > 1 or found[0][0]:
        return render_multi(args, found)
    kit, adapter_text = adapter(found[0][1])
    fields = {
        "{{STACK}}": args.stack,
        "{{KIT_VERSION}}": VERSION,
        "{{BASE_REF}}": args.base_ref,
        "{{PROTECTED_BRANCHES}}": toml_list(args.protected),
        "{{READ_ONLY}}": toml_list(args.read_only),
        "{{DOTNET_EF}}": "true" if kit["guard_dotnet_ef"] else "false",
        "{{APPSETTINGS}}": "true" if kit["guard_appsettings_secrets"] else "false",
        "{{MERGE_CHECK}}": merge_check(args),
        "{{SOURCE_ROOTS}}": toml_list(args.source_roots),
        "{{CROSS_CUTTING}}": toml_list(kit["cross_cutting"]),
        "{{TEST_WRITES}}": toml_list(kit["test_writes"]),
        "{{BUILD_WRITES}}": toml_list(list(dict.fromkeys([*kit["build_writes"], *ROOT_BUILD_WRITES]))),
        "{{MEDIUM_TIER}}": toml_list([f"^{root}" for root in args.source_roots]),
        "{{OUR_ROLE}}": our_role_toml([found[0][1]]),
        "{{ADAPTER}}": adapter_text.strip(),
    }
    text = (TEMPLATES / "factory.toml").read_text(encoding="utf-8")
    for key, value in fields.items():
        text = text.replace(key, value)
    return text


def toml_value(value) -> str:
    """One TOML value from an adapter's parsed tables: a regex reads as it was written, in a literal string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        literal = "'" not in value and "\n" not in value and ("\\" in value or '"' in value)
        return f"'{value}'" if literal else json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        items = [toml_value(item) for item in value]
        one_line = "[" + ", ".join(items) + "]"
        return one_line if len(one_line) <= 100 else "[\n" + "".join(f"  {item},\n" for item in items) + "]"
    raise SystemExit(f"init.py: cannot write {value!r} into factory.toml")


def toml_table(header: str, table: dict) -> str:
    return f"[{header}]\n" + "".join(f"{key} = {toml_value(value)}\n" for key, value in table.items()) + "\n"


def code_rules_text(rules: list[dict]) -> str:
    """
    A stack's banned-pattern rules (its adapter's [[code_rules]]) as [[stacks.code_rules]] tables under its
    [[stacks]] entry, their globs relative to its root, for devtools/checks/check-code-rules.py. A list of tables,
    which toml_table cannot write; a JSON string or list is a valid TOML basic string or array.
    """
    return "".join("[[stacks.code_rules]]\n" + "".join(f"{key} = {json.dumps(value)}\n" for key, value in rule.items()) + "\n"
                   for rule in rules)


def render_multi(args: argparse.Namespace, found: list[tuple[str, str]]) -> str:
    """
    factory.toml for a repository of several stacks, each in its own folder: one [[stacks]] entry per
    stack -- its adapter, commands and writes from its adapter file, every path relative to its root --
    the repository's own verify commands, one [drive] for the run, and [impact] and [tier] under the roots.
    `args.stack_overrides` ({root: {command: value}}) sets a stack's commands, as setup does for a skeleton.
    """
    import tomllib
    kits, parsed = {}, {}
    for root, name in found:
        kit, text = adapter(name)
        kits[root], parsed[root] = kit, tomllib.loads(text)
    overrides = getattr(args, "stack_overrides", None) or {}
    roots = [root for root, _ in found]
    repo_verify: list[str] = []
    stack_text = []
    for root, name in found:
        tables = parsed[root]
        commands = dict(tables.get("commands", {}))
        commands.update(overrides.get(root, {}))
        verify = commands.get("verify", [])
        repo_verify += [command for command in verify if command.startswith(REPO_VERIFY) and command not in repo_verify]
        commands["verify"] = [command for command in verify if not command.startswith(REPO_VERIFY)]
        writes = {"tests": kits[root]["test_writes"],
                  "build": [path for path in kits[root]["build_writes"] if path != "docs/**"]}
        stack_text.append(f"[[stacks]]\nname = {json.dumps(root)}\nroot = {json.dumps(root)}\n\n"
                          f"# {root}/: the {name} adapter (templates/adapters/{name}.toml in the kit).\n"
                          + toml_table("stacks.adapter", tables["adapter"])
                          + toml_table("stacks.commands", commands) + toml_table("stacks.writes", writes)
                          + code_rules_text(tables.get("code_rules", [])))
    drive = dict(parsed[roots[0]].get("drive", {}))
    tools: list[str] = []
    for root in roots:
        for tool in [*parsed[root].get("drive", {}).get("allowed_tools", []), f"Bash(cd {root}*)"]:
            if tool not in tools:
                tools.append(tool)
    drive["allowed_tools"] = tools
    drive["max_budget_usd_per_step"] = max(parsed[root].get("drive", {}).get("max_budget_usd_per_step", 0)
                                           for root in roots)
    blocks = [
        "# ---------------------------------------------------------------- the stacks: "
        + ", ".join(f"{root}/ ({name})" for root, name in found) + "\n"
        "# Each [[stacks]] entry is one stack in its own folder: its adapter, its commands and what each step\n"
        "# may write there -- every path relative to its root. The referee runs a stack's commands in its root,\n"
        "# and only for the stacks a run reaches: those whose folder holds a path the run changed, a test it\n"
        "# locked, or a criterion's test; a run that reaches none (documentation only) reaches every stack.\n\n"
        "# The repository's own checks: run once, at its root, before each reached stack's own verify.\n"
        + toml_table("commands", {"verify": repo_verify}),
        *stack_text,
        "# One unattended session per step for the whole repository: every stack's tools, and `cd <root>`.\n"
        + toml_table("drive", drive),
    ]
    source_roots = [f"{root}/{source}" for root in roots for source in args.source_roots]
    fields = {
        "{{STACK}}": stack_label(found),
        "{{KIT_VERSION}}": VERSION,
        "{{BASE_REF}}": args.base_ref,
        "{{PROTECTED_BRANCHES}}": toml_list(args.protected),
        "{{READ_ONLY}}": toml_list(args.read_only),
        "{{DOTNET_EF}}": "true" if any(kit["guard_dotnet_ef"] for kit in kits.values()) else "false",
        "{{APPSETTINGS}}": "true" if any(kit["guard_appsettings_secrets"] for kit in kits.values()) else "false",
        "{{MERGE_CHECK}}": merge_check(args),
        "{{SOURCE_ROOTS}}": toml_list(source_roots),
        "{{CROSS_CUTTING}}": toml_list([f"{root}/{path}" for root in roots for path in kits[root]["cross_cutting"]]),
        # The tests and build steps write in each stack's root ([stacks.writes]); the build step also the docs.
        "{{TEST_WRITES}}": toml_list([]),
        "{{BUILD_WRITES}}": toml_list(["docs/**", "README.md", *ROOT_BUILD_WRITES]),
        "{{MEDIUM_TIER}}": toml_list([f"^{root}" for root in source_roots]),
        "{{OUR_ROLE}}": our_role_toml([name for _, name in found]),
        "{{ADAPTER}}": "\n\n".join(block.strip() for block in blocks),
    }
    text = (TEMPLATES / "factory.toml").read_text(encoding="utf-8")
    for key, value in fields.items():
        text = text.replace(key, value)
    return text


def merge_settings(installer: Installer) -> None:
    """Wire the guard in for the file and shell tools and as the Stop hook; no AI attribution."""
    rel = ".claude/settings.json"
    path = installer.repository / rel
    settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    settings.setdefault("attribution", {"commit": "", "pr": ""})
    hooks = settings.setdefault("hooks", {})
    wanted = {
        "PreToolUse": {"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell|Monitor|Read|Grep|Glob|NotebookRead",
                       "hooks": [{"type": "command", "command": GUARD_COMMAND + NO_PYTHON_DENY, "timeout": 30}]},
        "Stop": {"hooks": [{"type": "command", "command": GUARD_COMMAND, "timeout": 20}]},
    }
    for event, entry in wanted.items():
        entries = hooks.setdefault(event, [])
        if not any("devtools/factory/hooks/guard.py" in json.dumps(existing) for existing in entries):
            entries.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8", newline="\n")
    installer.written.append(f"{rel} (merged)")


def merge_gitignore(installer: Installer) -> None:
    path = installer.repository / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if ".factory/" not in text.splitlines():
        text += ("" if text.endswith("\n") or not text else "\n") + \
            "\n# The AI factory's local evidence and guard log\n.factory/\n__pycache__/\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        installer.written.append(".gitignore (merged)")


def merge_gitattributes(installer: Installer) -> None:
    path = installer.repository / ".gitattributes"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if HOOKS_ATTRIBUTES not in text.splitlines():
        text += ("" if text.endswith("\n") or not text else "\n") + \
            "# The git hooks run under sh, which needs LF line endings on every platform\n" + HOOKS_ATTRIBUTES + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        installer.written.append(".gitattributes (merged)")


def place_hooks(installer: Installer, turn_on: bool) -> None:
    """
    The kit's git hooks in .githooks/, executable and staged so (git runs a hook off Windows only when
    it is), and the line endings pinned. core.hooksPath is pointed at them when `turn_on` and nothing
    points it elsewhere; otherwise the person is told what to run, and decides.

    An install turns them on only when it wrote the root CLAUDE.md: the hooks hold the kit's book rules
    (its owner table among them), which a repository's own CLAUDE.md does not have yet. An upgrade never
    turns them on, so it cannot block its own commit on the project's existing state.
    """
    before = set(installer.written)
    installer.place_tree(TEMPLATES / "githooks", HOOKS_DIR)
    for rel in [r for r in installer.written if r not in before]:
        os.chmod(installer.repository / rel, 0o755)
        git_in(installer.repository, "update-index", "--add", "--chmod=+x", "--", rel)
    merge_gitattributes(installer)
    current = git_in(installer.repository, "config", "--get", "core.hooksPath").stdout.strip()
    turn_on_by_hand = f"`git config core.hooksPath {HOOKS_DIR}` turns them on"
    if current.rstrip("/") == HOOKS_DIR:
        return
    if current:
        installer.skipped.append(f"git config core.hooksPath is {current}, not {HOOKS_DIR}: the kit's hooks are "
                                 f"off until you point it at {HOOKS_DIR} or call them from yours")
    elif turn_on:
        git_in(installer.repository, "config", "--local", "core.hooksPath", HOOKS_DIR)
        installer.written.append(f"git config core.hooksPath {HOOKS_DIR} (the hooks are on)")
    else:
        installer.skipped.append(f"{HOOKS_DIR}/: the hooks are off — CLAUDE.md is not the one the kit installed, "
                                 f"so check its book rules first; then {turn_on_by_hand}")


def git_in(repository: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repository, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def test_folders(args: argparse.Namespace) -> list[str]:
    """
    Where each stack keeps its tests, when it keeps them in a folder of their own (tests/ for pytest and
    .NET): the first folder of its adapter's test_writes, prefixed with the stack's root. A stack whose
    tests sit beside the code (React's src/*.test.tsx) has none; its rules are the root CLAUDE.md's.
    """
    folders = []
    for root, name in install_stacks(args):
        kit, _ = adapter(name)
        first = next((path.split("/", 1)[0] for path in kit["test_writes"] if "/" in path), "")
        if "test" in first.lower():
            folders.append("/".join(part for part in (root, first) if part))
    return folders


def place_test_rules(installer: Installer, args: argparse.Namespace) -> None:
    """The testing rules, tests/CLAUDE.md, in each stack's test folder, its links set for its depth."""
    text = (TEMPLATES / "tests" / "CLAUDE.md").read_text(encoding="utf-8")
    for folder in test_folders(args):
        up = "../" * (folder.count("/") + 1)
        installer.place(f"{folder}/CLAUDE.md", text.replace("](../", f"]({up}"))


def add_pytest_plugin(installer: Installer, root: str = "") -> None:
    rel = f"{root}/tests/conftest.py" if root else "tests/conftest.py"
    path = installer.repository / rel
    plugin = (TEMPLATES / "pytest" / "conftest_ac.py").read_text(encoding="utf-8")
    if not path.exists():
        installer.place(rel, plugin)
    elif "--ac" not in path.read_text(encoding="utf-8"):
        path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n\n\n" + plugin, encoding="utf-8", newline="\n")
        installer.written.append(f"{rel} (merged)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("repository", type=Path)
    parser.add_argument("--version", action="version", version=f"AI factory kit {VERSION}")
    parser.add_argument("--stack", help=f"one of {', '.join(stacks())}, or two joined by + (in backend/, frontend/)")
    parser.add_argument("--stacks", help="several stacks, each in its folder: backend=dotnet,frontend=react-vitest")
    parser.add_argument("--base-ref", default="origin/main", help="the branch runs are measured from")
    parser.add_argument("--protected", default="main,dev", type=lambda s: [b for b in s.split(",") if b])
    parser.add_argument("--source-roots", default="src/", type=lambda s: [r for r in s.split(",") if r])
    parser.add_argument("--read-only", default="requirements/**", type=lambda s: [p for p in s.split(",") if p],
                        help="paths the guard keeps read-only; default: the requirements snapshots")
    parser.add_argument("--merge-check", choices=sorted(MERGE_CHECKS), default="bitbucket",
                        help="who approves a merge: bitbucket (a Bitbucket pull request, the default), github (a GitHub pull request, "
                             "read through the gh CLI) or local (no remote: a person's `factory approve merge`)")
    parser.add_argument("--upgrade", action="store_true",
                        help="an installed repository: replace the kit's own code, add missing step instructions, "
                             "and list the settings the new template has that factory.toml lacks — never edit them "
                             "(only its kit_version stamp moves)")
    args = parser.parse_args()
    if bool(args.stack) == bool(args.stacks):
        parser.error("name the stack with --stack, or several with --stacks: one of the two")
    try:
        args.stacks = parse_stacks(args.stacks or args.stack)
    except ValueError as error:
        parser.error(str(error))
    args.stack = stack_label(args.stacks)

    repository = args.repository.resolve()
    if not (repository / ".git").exists():
        parser.error(f"{repository} is not a git repository")
    if args.upgrade:
        return upgrade(repository, args)
    installer = install(repository, args)

    print(f"Installed the AI factory ({args.stack}, kit {VERSION}) into {repository}\n")
    print("Written:\n" + "\n".join(f"  {rel}" for rel in installer.written))
    if installer.skipped:
        print("\nAlready there — left as they are; compare with the kit's templates:\n"
              + "\n".join(f"  {rel}" for rel in installer.skipped))
    print("\nNext:\n"
          "  1. Read devtools/factory/factory.toml — [guard], [requirements], [adapter], [tier] — and fill\n"
          "     the <!-- FILL --> slots in CLAUDE.md.\n"
          "  2. Commit it on a branch; a person reviews the rules the guard will enforce.\n"
          "  3. Start the first run on a work branch:\n"
          "       python3 devtools/factory/factory.py start <item> --title \"...\"\n"
          "       python3 devtools/factory/factory.py drive\n"
          f"  Or double-click \"{LAUNCHER}\" at the top of the repository: the Factory app, in plain words.")
    return 0


def install(repository: Path, args: argparse.Namespace) -> Installer:
    """
    Install the kit into a git repository: what was written, and what was already there and left
    alone. Never overwrites. `setup.py` calls it for a new project and for an existing one.
    """
    installer = Installer(repository)
    installer.place_tree(KIT / "factory", "devtools/factory")
    installer.place_tree(KIT / "checks", "devtools/checks")
    installer.place_tree(TEMPLATES / "checks", "devtools/checks")
    installer.place("devtools/factory/factory.toml", render_config(args))
    installer.place_tree(TEMPLATES / "prompts", "devtools/factory/prompts")
    installer.place_tree(TEMPLATES / "skills", ".claude/skills")
    installer.place_tree(TEMPLATES / "agents", ".claude/agents")
    installer.place_tree(TEMPLATES / "docs", "docs")
    installer.place_tree(TEMPLATES / "requirements", "requirements")
    installer.place("CLAUDE.md", source=TEMPLATES / "CLAUDE.md")
    place_test_rules(installer, args)
    place_stack_rules(installer, args)
    installer.place(LAUNCHER, source=TEMPLATES / LAUNCHER)
    merge_settings(installer)
    merge_gitignore(installer)
    for root, name in install_stacks(args):
        if name == "pytest":
            add_pytest_plugin(installer, root)
    if "docs/project.md" in installer.written:
        regenerate_rollup(installer)
    place_hooks(installer, turn_on="CLAUDE.md" in installer.written)
    return installer


STACK_RULES = {"react-vitest": "react.md", "dotnet": "dotnet.md"}


def place_stack_rules(installer: Installer, args: argparse.Namespace) -> None:
    """
    Each stack's rule pack (templates/rules/), written into the CLAUDE.md this install wrote, at the end of its
    Code rules section: the React pack for a React stack, its `src/` paths under the stack's own folder
    (`frontend/src/ui/` beside a back end). Only for a stack whose starter the kit writes (`args.skeletons`, set by
    setup.py): the pack's *[enforced]* marks name the starter's own tsconfig, scripts and lint rules, which an
    existing project need not have. A CLAUDE.md the project already had is its own, and is left alone.
    """
    if "CLAUDE.md" not in installer.written:
        return
    packs = []
    for root, name in getattr(args, "skeletons", None) or []:
        if name in STACK_RULES:
            text = (TEMPLATES / "rules" / STACK_RULES[name]).read_text(encoding="utf-8").strip()
            if root:
                text = text.replace("`src/", f"`{root}/src/").replace("(src/", f"({root}/src/")
            packs.append(text)
    if not packs:
        return
    path = installer.repository / "CLAUDE.md"
    text = path.read_text(encoding="utf-8")
    start = text.index("## Code rules")
    end = text.find("\n## ", start + 1)
    end = len(text) if end == -1 else end
    path.write_text(text[:end].rstrip() + "\n\n" + "\n\n".join(packs) + "\n" + text[end:], encoding="utf-8", newline="\n")


def regenerate_rollup(installer: Installer) -> None:
    """
    docs/project.md's generated task tables, written for the roles this install builds ([book] our_role):
    the template's are a back end's, so a front-end project's would be stale from its first commit.
    """
    done = subprocess.run([sys.executable, "devtools/checks/gen-task-rollup.py"], cwd=installer.repository,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        installer.skipped.append("docs/project.md: the task roll-up could not be regenerated — run "
                                 "`python3 devtools/checks/gen-task-rollup.py`: " + (done.stderr or done.stdout).strip()[:200])


if __name__ == "__main__":
    raise SystemExit(main())
