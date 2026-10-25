# AI Factory kit — 1.7.1

Install an AI factory into any repository: Claude Code does the work, a referee decides whether
each step is done, and a person decides at the gates. It takes an existing project or a new one from its FSD to a working app.

Needs Python 3.11+, git, and the Claude Code CLI (for `factory drive`). Node.js for a React stack,
the .NET SDK for a .NET stack.

## For a team lead: install it

**A new project from nothing but its FSD** (no AI in the setup itself):

```
python setup.py --greenfield --dir <new folder> --name "Shop" --fsd "Shop FSD.docx" --stack pytest
python setup.py --greenfield --dir <new folder> --name "Shop" --fsd "Shop FSD.docx" --stacks backend=dotnet,frontend=react-vitest
```

This makes the folder, runs `git init -b main`, installs the kit, files the FSD as
`requirements/fsd/<Name> - V1.<ext>`, fills in what it knows (where the FSD is, the build and test
commands), writes a starting skeleton per stack when there are two, and commits.

**An existing repository:** `python setup.py --brownfield --dir <repo> [--fsd <file> --name <Name>]`
installs on a new `setup/factory` branch. It never overwrites a file; when the factory is already
there it upgrades it instead. It refuses a dirty tree, a folder that is not the repository's top,
and git with no user name and email.

Or install by hand: `python init.py <repo> --stack <stack> --base-ref origin/main --protected main,dev`
(`--stack` is `pytest`, `dotnet`, `react-vitest`, or two joined by `+`).

Then:

1. **Read `devtools/factory/factory.toml`.** Every rule is there and a person should agree with each:
   `[guard]` (read-only paths, what asks a person), `[adapter]` and `[commands]` (how the stack builds
   and tests), `[tier]` and `[budget]` (what is High risk, line limits), `[requirements]`.
2. **Fill the `<!-- FILL -->` slots** in `CLAUDE.md` and `docs/`.
3. **Choose who approves a merge** — the merge gate's `check` in `factory.toml`:
   - `bitbucket-approval`: a pull request in Bitbucket, approved by someone other than its author.
     Protect your branches there (one approval, one passing build; no force-push or delete);
     `factory protection --check` reads them back.
   - `local-approval`: **for a project with no remote.** There is no pull request, so a person
     approves the merge on their own computer — **Approve** in the Factory app, or
     `factory approve merge` in their own terminal — after reading the evidence. The referee holds it
     to the same evidence rules, then the person merges the branch.

   `setup.py` picks for you: `local-approval` when the project has no remote (every greenfield
   project), `bitbucket-approval` when it has one. `init.py` writes `bitbucket-approval` unless given
   `--merge-check local`.
4. **Double-click `Start Factory.cmd`** at the top of the repository. It opens the Factory app on this
   project in your browser. Hand that file to the business analyst.

## For a business analyst: use the app

Double-click **Start Factory.cmd**. A window opens (leave it open; closing it stops the app) and the
app opens in your browser. It shows the project in plain words, and never decides anything itself:
every button runs the referee's own command and shows what it said.

It shows each project as a book:

- **Overview** — the cover. **Needs you** lists everything waiting for a person: approve a spec, a
  design, a plan, the book, or a merge; answer a question the AI stopped on. Each item says what to
  read and has the button that decides it. Below it, where the book stands.
- **Contents** — every feature, read from `docs/project.md`.
- **A page per feature** — its plan, tasks, requirements, questions, defects and factory work.
  **Write the plan** on a feature without one; **Build the next task** on a plan (one task at a time).
- **Questions & defects** — every one, open or answered; **Fix this defect** starts a run for one.
- **Requirements** — every FSD version, and what an audit traced.
- **Factory work** — every piece of work, with its five steps: which it is on, and why it stopped.
- **Hold for the demo** sets a card aside (kept outside the repository); the app acts only in the
  folders a person gave it.
- **New project** (when the app is started with `--kit <this folder>`) — runs `setup.py` for you, then
  offers **Draft the book**: the AI reads the FSD and writes `docs/project.md`, and you approve it.

Approve only from the app or your own terminal: the referee refuses an approval made from inside a
Claude Code session, and the guard refuses the AI trying.

## What a run does

- **The book run** (`factory start book:project --new-branch`, then `factory drive`) writes
  `docs/project.md` from the FSD: the referee reads the FSD's outline itself (.docx, .md, .txt), a
  session sorts every section (an empty one becomes a question) and writes the phases and rows, the
  referee checks every citation, title, quote and dependency, an independent `book-auditor` reads it
  against the FSD, and a person approves it at the book gate.
- **A plan run** (`factory start plan:<feature-slug> --new-branch`) writes one feature's plan at
  `docs/plans/<slug>.md` and stops at the plan gate for a person.
- **A task run** (`factory start plan:<stem>#<n> --new-branch`) builds one of the plan's tasks: spec,
  design, tests proven red, build green, an independent review, then the merge gate. It writes itself
  back into its task row.

## What the kit contains

| Piece | What it does |
|---|---|
| **The referee** — `devtools/factory/factory.py` | Runs a piece of work step by step. Claude writes a step's section of the run file; the referee runs the step's check itself and moves on only on a pass. Tests are proven red before the fix, then locked by hash. |
| **The guard** — `devtools/factory/hooks/guard.py` | A Claude Code hook on every file write and shell command. It refuses what your rules forbid (change a read-only file, push to a protected branch, delete a branch, skip hooks, write a secret, approve its own gate) and asks a person before anyone changes the factory or settings. Installed warn-only: it lets your rules' refusals through with a warning until you set `"mode": "enforce"` in `devtools/factory/hooks/guard-config.json`, what it refuses in every mode (a gate's approval, a locked test, the run's Record) it refuses from the start. |
| **The Factory app** — `devtools/factory/console/`, started by `Start Factory.cmd` | The referee's commands in plain words in a browser, for a non-technical approver. Runs on this computer only, with a session key. |
| **`factory drive`** | Runs the steps unattended — a fresh Claude session per step — retries a failed check, stops when there is no progress, records each step's cost, and stops at every gate. |
| **The reviewer, the book auditor and the spec auditor** — `.claude/agents/` | Fresh, read-only agents that never saw the work being written. The referee starts them and reads their verdict itself. The spec auditor checks a change requirement by requirement at verify once `[audit]` in `factory.toml` is uncommented. |
| **The run file** — `docs/factory/runs/R-nnn.md` | One file per run: intent, criteria, design, the red and green evidence per commit, gates and who approved, review, cost. |
| **The book** — `docs/`, `CLAUDE.md`, `devtools/checks/` | One owner document per topic; requirements as read-only snapshots; a plan before code; defects logged the day they are found. `check-book.py` holds the rules a program can; `gen-task-rollup.py` keeps `docs/project.md`'s task progress current. |
| **Git hooks** — `.githooks/`, turned on with `core.hooksPath` | `pre-commit`: the book's rules, nothing personal or secret, no protected file changed, the task roll-up current, every *[enforced]* rule still enforced. `commit-msg`: no AI attribution or trailers, and a fix branch's commit names what it fixes. Build-free, so a commit stays quick. |
| **Checks** — `devtools/checks/` | Beside the book's: `check-commit-msg.py`, `check-protected-paths.py`, `check-rules.py`, and `check-test-results.py` (a results file that skipped, ran nothing or is missing fails). Configured from `[guard]`, `[backlog]` and `[checks]` in `factory.toml`. |
| **The testing rules** — `tests/CLAUDE.md` | What a feature must prove, reporting the skip count, test data that cleans up after itself. Written in each stack's own test folder (none for React, whose tests sit beside the code). |
| **Skills** — `.claude/skills/` | /factory, /change-impact, /review-branch, /commit, /review-pr, /fsd-audit, /docs-vs-code, /docs-update-from-code, /docs-consistency, /docs-trim, /requirements-check. |
| **Stack adapters** — `templates/adapters/` | `pytest`, `dotnet`, `react-vitest`: how each stack builds, tags a test with its criterion, runs tests and reports results. A new stack is one new file. |

**Two stacks in one repository** (a .NET back end and a React front end, each in its own folder) is
`[[stacks]]` in `factory.toml`. A run reaches only the stacks whose folder it changed; the referee
builds, proves red and green, integrates and verifies each in its own folder.

## Proving the kit works

Run these from the kit folder, one at a time:

```
python selftest.py                                   # 65 checks (pytest)
python selftest.py --stack dotnet                    # 65 checks
python selftest.py --stack react-vitest              # 73 checks
python selftest.py --stack pytest+react-vitest       # 73 checks
python selftest.py --stack dotnet+react-vitest       # 73 checks
python -m unittest test_setup                        # 14 tests
python -m unittest test_checks                       # the hooks and the carried checks
```

Each installs the kit into a throwaway repository and drives it with a stand-in for Claude: no model,
no network.

## Limits

- Needs Python 3.11+, git and the Claude Code CLI; Node.js for React stacks, the .NET SDK for .NET stacks.
- Merge approval is `local-approval` (no remote) or `bitbucket-approval` (a Bitbucket pull request). Other hosts need a new check.
- The guard installs warn-only; set `"mode": "enforce"` in `devtools/factory/hooks/guard-config.json` to enforce.
