#!/usr/bin/env python3
"""
Set a project up for the AI factory — no AI, no network: the folder, git, the kit, the FSD as V1.

    python setup.py --greenfield --dir <new folder> --name <Name> --fsd <file> --stack pytest|dotnet|react-vitest [--json]
    python setup.py --greenfield --dir <new folder> --name <Name> --fsd <file> --stacks backend=dotnet,frontend=react-vitest
    python setup.py --brownfield --dir <existing repository> [--fsd <file> --name <Name>] [--stack …] [--json]

Greenfield makes the folder, `git init -b main`, installs the kit (init.py), files the FSD as
`requirements/fsd/<Name> - V1.<ext>`, fills what the book can say without a model (the FSD's
place in project.md and the requirements read-mes, the build and test commands) and commits it
on main. Several stacks (`--stacks backend=dotnet,frontend=react-vitest`, or `--stack dotnet+react-vitest`)
each get a folder and a starting skeleton there (templates/skeletons/<stack>/); a single react-vitest
project gets its skeleton at the top. A single dotnet or pytest project gets none, as before. Brownfield installs the kit into an existing repository on a new branch `setup/factory`
— never overwriting a file, upgrading instead when the factory is already there — files the FSD
when one is given, commits, and reports what it added. Either way it ends by printing the next
command: the book run, `factory start book:project --new-branch`. A project with no remote (every
greenfield one) gets `check = "local-approval"` at the merge gate: a person approves each merge on this
computer (`factory approve merge`, or Approve in the Factory app), as there is no pull request to approve.

It refuses: an existing non-empty folder for greenfield; a folder that is not a git repository's
top level, or a working tree with uncommitted changes, for brownfield; git without a user name and
email; an FSD that is not .docx, .md, .txt or .pdf, or over 25 MB; a stack it cannot name.
`--json` prints one object for the factory console's setup wizard. Python 3.11+, standard library.

Why here and not in factory.py: setup runs before the project has a referee — the kit is what
installs factory.py — so it must work from the kit alone. It reuses init.py in-process, so the
installer stays the single source of what an install writes.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
FSD_TYPES = (".docx", ".md", ".txt", ".pdf")
FSD_MAX_BYTES = 25 * 1024 * 1024
FSD_DIR = "requirements/fsd"
BRANCH = "setup/factory"
# A file name holds the project's name: nothing a path or Windows would read as something else.
BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]|^\.|\.$')
SKELETONS = KIT / "templates" / "skeletons"
# What a skeleton's stack runs that its adapter cannot know: the .NET skeleton's solution and test project.
SKELETON_COMMANDS = {"dotnet": {"build": "dotnet build App.slnx", "test_projects_always": ["tests/App.Tests"]}}


class Refused(Exception):
    """Setup cannot go on: what is wrong, and what to do instead."""


def load_init():
    """The kit's installer, loaded in-process: one source for what an install writes."""
    spec = importlib.util.spec_from_file_location("kit_init", KIT / "init.py")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True  # no __pycache__ left in the kit
    spec.loader.exec_module(module)
    return module


def git(folder: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if check and done.returncode != 0:
        raise Refused(f"`git {' '.join(args)}` failed: {(done.stderr or done.stdout).strip()[:400]}")
    return done


def identity(folder: Path) -> None:
    for key in ("user.name", "user.email"):
        if not git(folder, "config", "--get", key, check=False).stdout.strip():
            raise Refused(f"git has no {key}. Set it first: git config --global {key} \"…\" — every commit names its author.")


def detect_stack(folder: Path, stacks: list[str]) -> str:
    """Brownfield: the stack from what is there, or a refusal saying what was found."""
    package = folder / "package.json"
    if package.is_file() and "react-vitest" in stacks:
        try:
            manifest = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        packages = {**(manifest.get("dependencies") or {}), **(manifest.get("devDependencies") or {})}
        if "vitest" in packages and "react" in packages:
            return "react-vitest"
    def has(*patterns: str) -> bool:
        return any(next((p for p in folder.rglob(pattern) if ".git" not in p.parts and "node_modules" not in p.parts),
                        None) for pattern in patterns)
    if has("*.sln", "*.slnx", "*.csproj") and "dotnet" in stacks:
        return "dotnet"
    if (folder / "pyproject.toml").is_file() or (folder / "pytest.ini").is_file() or (folder / "setup.py").is_file() \
            or (folder / "setup.cfg").is_file() or has("test_*.py"):
        if "pytest" in stacks:
            return "pytest"
    if (folder / "package.json").is_file():
        raise Refused("This is a Node project (package.json) without React and Vitest; the kit has no adapter for it yet. "
                      "A backend and a front end in folders of their own: --stacks backend=…,frontend=…. Name a stack with "
                      f"--stack ({', '.join(stacks)}) only if it really is one, or add templates/adapters/<name>.toml.")
    raise Refused(f"Could not tell the stack from the files here. Name it with --stack ({', '.join(stacks)}).")


def check_fsd(fsd: Path | None, name: str | None) -> None:
    if fsd is None:
        return
    if not fsd.is_file():
        raise Refused(f"No FSD at {fsd}.")
    if fsd.suffix.lower() not in FSD_TYPES:
        raise Refused(f"{fsd.name}: the FSD must be {', '.join(FSD_TYPES)} — .docx is best: its headings are read "
                      "without a model.")
    if fsd.stat().st_size > FSD_MAX_BYTES:
        raise Refused(f"{fsd.name} is over 25 MB.")
    if not name or BAD_NAME.search(name) or not name.strip():
        raise Refused(f"--name {name!r}: the FSD is filed as `<Name> - V1{fsd.suffix.lower()}`, so the name needs letters, "
                      "and none of \\ / : * ? \" < > |.")


def file_fsd(folder: Path, fsd: Path, name: str) -> str:
    """The FSD as the next revision under requirements/fsd/ — V1 in a new project; never over an existing V<n>."""
    target_dir = folder / FSD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(re.escape(name.strip()) + r" - V(\d+)\.[A-Za-z]+$")
    taken = [int(m.group(1)) for p in target_dir.iterdir() if (m := pattern.match(p.name))]
    target = target_dir / f"{name.strip()} - V{max(taken, default=0) + 1}{fsd.suffix.lower()}"
    shutil.copy2(fsd, target)
    return target.relative_to(folder).as_posix()


def fill(folder: Path, rel: str, replacements: list[tuple[str, str]]) -> bool:
    """Replace FILL slots the install just wrote; a slot already filled by hand is left alone."""
    path = folder / rel
    if not path.is_file():
        return False
    text = original = path.read_text(encoding="utf-8")
    for pattern, value in replacements:
        text = re.sub(pattern, lambda _match: value, text, count=1, flags=re.DOTALL)
    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
    return text != original


def fill_book(folder: Path, written: list[str], fsd_rel: str | None, name: str, stack: str, remote: str) -> list[str]:
    """
    What the book can say without a model, in files this install wrote: where the FSD is and that it
    is V1, the build and test commands, the remote. Everything else stays a FILL for the book run or a person.
    """
    import tomllib
    config = tomllib.loads((folder / "devtools/factory/factory.toml").read_text(encoding="utf-8"))

    def plain(command: str) -> str:
        """A test command as a person types it: no results file, no logger."""
        command = command.replace(' --junitxml "{results}/results.xml"', "")
        command = re.sub(r'\s*--(logger|results-directory)\s+"?[^ ]+"?', "", command)
        return re.sub(r'\s*--(reporter=\S+|outputFile\.junit="[^"]*")', "", command)

    if config.get("stacks"):
        build = "; ".join(f"`{s['root']}/`: `{s['commands']['build']}`" for s in config["stacks"])
        tests = "; ".join(f"`{s['root']}/`: `{plain(s['adapter']['run_tests'])}`" for s in config["stacks"])
        build_line = (f"{remote}. Build {build}. Tests {tests} (each stack's [[stacks]] entry in "
                      "`devtools/factory/factory.toml`, run in its folder)")
    else:
        build = config.get("commands", {}).get("build", "")
        tests = plain(config.get("adapter", {}).get("run_tests", ""))
        build_line = (f"{remote}. Build `{build}`; tests `{tests}` ([commands] and [adapter] in "
                      "`devtools/factory/factory.toml`)" if build else f"{remote}. No build or test command yet ({stack} adapter)")
    today = datetime.date.today().isoformat()
    filled = []
    if "docs/project.md" in written and fill(folder, "docs/project.md", [
        (r"<!-- FILL: the remote, and the build and test commands.*?-->",
         build_line),
        *([(r"## V1 · received <!-- FILL: date --> — the baseline\s*<!-- FILL: the file under requirements/fsd/.*?-->",
            f"## V1 · received {today} — the baseline\n\n`{fsd_rel}` is V1, filed at project setup. V1 is the first "
            "revision; there is nothing to compare it with yet.")] if fsd_rel else []),
    ]):
        filled.append("docs/project.md")
    if fsd_rel and "requirements/read-me.txt" in written and fill(folder, "requirements/read-me.txt", [
        (r"<!-- FILL: name the spec source.*?-->",
         f"The requirements are the FSD for {name}: `{fsd_rel}` (V1), filed at project\nsetup on {today}. "
         "Its owner and live copy: not recorded yet - delivered as a file."),
        (r"<!-- FILL: one line per source.*?-->",
         f"{fsd_rel} -> the FSD -> none recorded - delivered as a file -> versioned (V<n>)"),
        (r"<!-- FILL: one block per source.*?-->",
         f"Name:         {name} FSD\nRole:         requirements\nLive:         none recorded - delivered as a file\n"
         f"Export:       save each revision as requirements/fsd/{name} - V<n>.docx\nComments:     no\n"
         "Snapshot:     versioned\nLast checked: never"),
    ]):
        filled.append("requirements/read-me.txt")
    if fsd_rel and "docs/open-questions.md" in written and fill(folder, "docs/open-questions.md", [
        (r"<!-- FILL: the requirement documents.*?-->", f"the FSD, `{fsd_rel}` — the highest V<n> in `requirements/fsd/` is authoritative."),
    ]):
        filled.append("docs/open-questions.md")
    return filled


def next_commands(folder: Path, fsd_rel: str | None) -> list[str]:
    factory = "python3 devtools/factory/factory.py"
    if not fsd_rel:
        return [f"cd \"{folder}\"",
                "# No FSD: add one (setup.py --brownfield --fsd <file>) to generate the book from it; "
                "the book from the code alone (book:code, Phase D §3.6) is not built yet."]
    return [f"cd \"{folder}\"", f"{factory} start book:project --title \"Book from FSD V1\" --new-branch",
            f"{factory} drive"]


def greenfield(args: argparse.Namespace, init) -> dict:
    folder = args.dir
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise Refused(f"{folder} exists and is not empty. Greenfield needs a new or empty folder; for an existing "
                      "repository use --brownfield.")
    if not args.name or not args.fsd or not args.stack:
        raise Refused("Greenfield needs --name, --fsd and --stack.")
    check_fsd(args.fsd, args.name)
    identity(folder.parent if folder.parent.exists() else Path.cwd())
    folder.mkdir(parents=True, exist_ok=True)
    git(folder, "init", "-q", "-b", "main")
    # A new folder has no remote: a person approves each merge locally (`factory approve merge`, or the app).
    install = install_args(args, base_ref="main", protected=["main"], merge_check="local")
    skeletons = skeleton_stacks(init, install)
    install.stack_overrides = {root: SKELETON_COMMANDS[name] for root, name in skeletons if name in SKELETON_COMMANDS}
    install.skeletons = skeletons   # a stack's rule pack describes the kit's own starter, so it goes only with one
    installer = init.install(folder, install)
    for root, name in skeletons:
        place_skeleton(installer, root, name)
    fsd_rel = file_fsd(folder, args.fsd, args.name)
    filled = fill_book(folder, installer.written, fsd_rel, args.name, args.stack,
                       "No remote yet — `git remote add origin <url>` (https or ssh, never with credentials)")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", f"Set up the AI factory ({args.stack}) and file the FSD as V1")
    return {"mode": "greenfield", "branch": "main", "written": installer.written, "already_there": installer.skipped,
            "upgraded": [], "settings_to_add": [], "fsd": fsd_rel, "filled": filled}


def skeleton_stacks(init, install: argparse.Namespace) -> list[tuple[str, str]]:
    """
    The stacks a greenfield project gets a skeleton for: every stack of several, each in its folder; a
    single react-vitest project at the top. A single dotnet or pytest project gets none, as before.
    """
    found = init.install_stacks(install)
    wanted = found if len(found) > 1 or found[0][0] else [(root, name) for root, name in found if name == "react-vitest"]
    return [(root, name) for root, name in wanted if (SKELETONS / name).is_dir()]


def place_skeleton(installer, root: str, name: str) -> None:
    """A stack's starting files under its root. Never over a file; a .gitignore already there gains its lines."""
    source = SKELETONS / name
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = "/".join(part for part in (root, path.relative_to(source).as_posix()) if part)
        target = installer.repository / rel
        if path.name == ".gitignore" and target.is_file():
            have = target.read_text(encoding="utf-8").splitlines()
            more = [line for line in path.read_text(encoding="utf-8").splitlines() if line and line not in have]
            if more:
                text = target.read_text(encoding="utf-8")
                target.write_text(text + ("" if text.endswith("\n") else "\n") + "\n".join(more) + "\n",
                                  encoding="utf-8", newline="\n")
                installer.written.append(f"{rel} (merged)")
            continue
        installer.place(rel, source=path)


def brownfield(args: argparse.Namespace, init) -> dict:
    folder = args.dir
    if not folder.is_dir():
        raise Refused(f"{folder} does not exist. Brownfield is for an existing repository; for a new one use --greenfield.")
    top = git(folder, "rev-parse", "--show-toplevel", check=False)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != folder:
        raise Refused(f"{folder} is not the top of a git repository. Run setup on the repository's own folder, or "
                      "`git init` it first.")
    if git(folder, "status", "--porcelain").stdout.strip():
        raise Refused(f"{folder} has uncommitted changes. Commit or stash them first, so the setup's commit holds "
                      "only what the setup added.")
    identity(folder)
    if args.fsd:
        check_fsd(args.fsd, args.name or folder.name)
    stack = args.stack or detect_stack(folder, init.stacks())
    if args.stack_list:
        missing = [root for root, _ in args.stack_list if root and not (folder / root).is_dir()]
        if missing:
            raise Refused(f"--stacks names {', '.join(f'{root}/' for root in missing)}, which this repository does not "
                          "have. Each stack is a folder that is already there.")
    if git(folder, "rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH}", check=False).returncode == 0:
        raise Refused(f"A branch {BRANCH} already exists here. Merge or rename it, then run setup again.")
    installed = (folder / "devtools/factory/factory.toml").is_file()
    head = git(folder, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    remote = git(folder, "remote", "get-url", "origin", check=False).stdout.strip()
    git(folder, "checkout", "-q", "--no-track", "-b", BRANCH)
    args.stack = stack
    base_ref = args.base_ref or (f"origin/{head}" if remote else head)
    # The merge gate reads a pull-request approval only where the remote is Bitbucket's or GitHub's; any other host
    # (GitLab) or none is approved by a person in the app, which merges locally — a Bitbucket gate there could
    # never pass (the kit audit, 18 Oct).
    install = install_args(args, base_ref=base_ref, protected=args.protected or [head],
                           merge_check=("bitbucket" if "bitbucket.org" in remote.lower()
                                        else "github" if "github.com" in remote.lower() else "local"))
    if installed:
        replaced, added, missing, changed = init.upgrade_files(folder, install)
        result = {"written": added, "already_there": [], "upgraded": replaced, "settings_to_add": missing + changed}
    else:
        installer = init.install(folder, install)
        result = {"written": installer.written, "already_there": installer.skipped, "upgraded": [], "settings_to_add": []}
    fsd_rel = file_fsd(folder, args.fsd, args.name or folder.name) if args.fsd else None
    result["filled"] = fill_book(folder, result["written"], fsd_rel, args.name or folder.name, stack,
                                 f"`{remote}`" if remote else "No remote yet — `git remote add origin <url>`")
    git(folder, "add", "-A")
    if git(folder, "status", "--porcelain").stdout.strip():
        what = "Upgrade the AI factory" if installed else f"Set up the AI factory ({stack})"
        committed = git(folder, "commit", "-q", "-m", what + (" and file the FSD" if fsd_rel else ""), check=False)
        if committed.returncode != 0:
            raise Refused(f"The commit on {BRANCH} failed — the repository's own hooks said: "
                          f"{(committed.stderr or committed.stdout).strip()[:600]}. The files are staged on {BRANCH}; "
                          "fix what the hook names and commit by hand. Hooks are never skipped.")
    return {"mode": "brownfield", "branch": BRANCH, "from": head, "fsd": fsd_rel, **result}


def install_args(args: argparse.Namespace, base_ref: str, protected: list[str], merge_check: str) -> argparse.Namespace:
    """init.py's arguments. `merge_check`: `local` for a project with no remote (no pull request to approve)."""
    return argparse.Namespace(stack=args.stack, stacks=getattr(args, "stack_list", None), base_ref=base_ref,
                              protected=protected, source_roots=args.source_roots, read_only=["requirements/**"],
                              merge_check=merge_check, upgrade=False)


def report(result: dict) -> str:
    lines = [f"Set up {result['dir']} ({result['mode']}, {result['stack']}, kit {result['kit_version']}) on branch {result['branch']} "
             f"— commit {result.get('commit', '—')[:10]}.", ""]
    if result["fsd"]:
        lines.append(f"FSD filed as {result['fsd']}.")
    for title, key in (("Written", "written"), ("Replaced with the kit's current code", "upgraded"),
                       ("Already there — left as they are", "already_there"),
                       ("Filled from what setup knows (no model)", "filled"),
                       ("factory.toml: the kit's template has these and this project's does not — add them by hand",
                        "settings_to_add")):
        if result.get(key):
            lines += [f"{title}:"] + [f"  {item}" for item in result[key]]
    lines += ["", "Next:"] + [f"  {command}" for command in result["next"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # A Windows console's code page cannot show "—" or "§"; the wizard reads JSON either way.
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    init = load_init()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--greenfield", action="store_true", help="a new project in a new or empty folder")
    mode.add_argument("--brownfield", action="store_true", help="an existing git repository")
    parser.add_argument("--dir", required=True, type=Path, help="the project's folder")
    parser.add_argument("--name", help="the project's name: the FSD is filed as '<Name> - V1.<ext>'")
    parser.add_argument("--fsd", type=Path, help="the FSD: .docx (best), .md, .txt or .pdf")
    parser.add_argument("--stack", help=f"{', '.join(init.stacks())}, or two joined by + (backend/, frontend/); "
                                         "greenfield: this or --stacks; brownfield: detected when left out")
    parser.add_argument("--stacks", help="several stacks, each in its folder: backend=dotnet,frontend=react-vitest")
    parser.add_argument("--base-ref", help="brownfield: the branch runs are measured from (default: origin/<current branch>, "
                                           "or the current branch with no remote)")
    parser.add_argument("--protected", type=lambda s: [b for b in s.split(",") if b],
                        help="brownfield: branches nobody pushes to (default: the current branch)")
    parser.add_argument("--source-roots", default=["src/"], type=lambda s: [r for r in s.split(",") if r])
    parser.add_argument("--json", action="store_true", help="one JSON object, for the console's setup wizard")
    args = parser.parse_args(argv)
    if args.stack and args.stacks:
        parser.error("name the stack with --stack, or several with --stacks: not both")
    args.stack_list = None
    if args.stack or args.stacks:
        try:
            args.stack_list = init.parse_stacks(args.stacks or args.stack)
        except ValueError as error:
            parser.error(str(error))
        args.stack = init.stack_label(args.stack_list)
    args.dir = args.dir.expanduser().resolve()
    args.fsd = args.fsd.expanduser().resolve() if args.fsd else None
    try:
        result = greenfield(args, init) if args.greenfield else brownfield(args, init)
        result.update({"ok": True, "dir": str(args.dir), "stack": args.stack, "kit_version": init.VERSION,
                       "commit": git(args.dir, "rev-parse", "HEAD").stdout.strip(),
                       "next": next_commands(args.dir, result["fsd"])})
    except Refused as refusal:
        if args.json:
            print(json.dumps({"ok": False, "dir": str(args.dir), "refused": str(refusal)}, indent=2))
        else:
            print(f"setup: {refusal}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2) if args.json else report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
