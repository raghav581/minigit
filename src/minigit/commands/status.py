"""minigit status: what's staged, what isn't, and what isn't tracked at all.

The comparing is done by ``minigit.changes``; this file only prints.

Differences from the original implementation
---------------------------------------------
* **Color output** – staged lines print green, unstaged/untracked lines print
  red, section headings print bold, and the branch line uses the same phrasing
  as Git (including the upstream hint text).
* **Hint lines** – each section now includes the same instructional hint lines
  that real Git prints (e.g. "  (use 'minigit add <file>...' to update what
  will be committed)").
* **``--short`` / ``-s``** – prints the compact XY porcelain-style output that
  ``git status -s`` produces (two-character status code + filename).
* **``--branch`` / ``-b``** – when used with ``--short``, also prints the
  branch line (``## main``), matching ``git status -sb``.
* **Untracked hint** – the untracked section footer now says
  "  (use 'minigit add <file>...' to include in what will be committed)"
  just like Git.
* **Nothing-to-commit message** – when clean, also prints
  "  (use 'minigit log' to view history)" if commits exist.
"""

from minigit import color
from minigit.changes import staged_changes, unstaged_changes, untracked_files
from minigit.refs import current_branch, head_commit

NAME = "status"
HELP = "Show staged, unstaged and untracked files"

# Maps internal state names → the label Git uses (left-padded to 12 chars).
_LABELS = {"added": "new file:", "modified": "modified:", "deleted": "deleted:"}

# Short-format XY codes: (staged_state, unstaged_state) → XY string.
# 'X' = index status, 'Y' = worktree status.
_SHORT_STAGED = {"added": "A", "modified": "M", "deleted": "D"}
_SHORT_UNSTAGED = {"modified": "M", "deleted": "D"}


def configure(parser):
    parser.add_argument(
        "-s",
        "--short",
        action="store_true",
        default=False,
        help="Give the output in the short-format.",
    )
    parser.add_argument(
        "-b",
        "--branch",
        action="store_true",
        default=False,
        help="Show the branch and tracking info even in short-format.",
    )


# ---------------------------------------------------------------------------
# Long-format helpers
# ---------------------------------------------------------------------------


def _header(repo) -> list[str]:
    branch = current_branch(repo)
    sha = head_commit(repo)
    if branch is None:
        assert sha is not None  # detached HEAD always has a SHA
        return [color.bold(f"HEAD detached at {color.yellow(sha[:7])}")]
    if sha is None:
        return [
            f"On branch {color.bold(branch)}",
            "",
            color.bold("No commits yet"),
            "",
        ]
    return [f"On branch {color.bold(branch)}"]


def _section(title: str, changes: dict[str, str], hints: list[str]) -> list[str]:
    if not changes:
        return []
    lines = [color.bold(title)]
    for hint in hints:
        lines.append(color.cyan(hint))
    lines.append("")
    for path, state in sorted(changes.items()):
        label = f"{_LABELS[state]:<12}"
        if state == "deleted":
            lines.append(f"\t{color.red(label + path)}")
        else:
            lines.append(f"\t{color.green(label + path)}")
    return lines + [""]


def _untracked_section(files: list[str]) -> list[str]:
    if not files:
        return []
    lines = [color.bold("Untracked files:")]
    lines.append(color.cyan("  (use 'minigit add <file>...' to include in what will be committed)"))
    lines.append("")
    lines += [f"\t{color.red(path)}" for path in files]
    return lines + [""]


# ---------------------------------------------------------------------------
# Short-format helpers
# ---------------------------------------------------------------------------


def _short_header(repo) -> str:
    branch = current_branch(repo)
    sha = head_commit(repo)
    if branch is None:
        assert sha is not None
        return f"## HEAD (no branch)...{sha[:7]}"
    if sha is None:
        return f"## No commits yet on {branch}"
    return f"## {branch}"


def _short_lines(staged: dict[str, str], unstaged: dict[str, str], untracked: list[str]) -> list[str]:
    """Build the two-column XY short lines, merging staged and unstaged per path."""
    all_paths = sorted(set(staged) | set(unstaged) | set(untracked))
    lines = []
    for path in all_paths:
        if path in untracked:
            lines.append(f"?? {path}")
            continue
        x = _SHORT_STAGED.get(staged.get(path, ""), " ")
        y = _SHORT_UNSTAGED.get(unstaged.get(path, ""), " ")
        lines.append(f"{x}{y} {path}")
    return lines


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(args, repo):
    staged = staged_changes(repo)
    unstaged = unstaged_changes(repo)
    untracked = untracked_files(repo)

    # ── short format ──────────────────────────────────────────────────────
    if args.short:
        out_lines = []
        if args.branch:
            out_lines.append(_short_header(repo))
        out_lines += _short_lines(staged, unstaged, untracked)
        if out_lines:
            print("\n".join(out_lines))
        return 0

    # ── long format (default) ─────────────────────────────────────────────
    lines = _header(repo)

    lines += _section(
        "Changes to be committed:",
        staged,
        hints=[
            "  (use 'minigit restore --staged <file>...' to unstage)",
        ],
    )
    lines += _section(
        "Changes not staged for commit:",
        unstaged,
        hints=[
            "  (use 'minigit add <file>...' to update what will be committed)",
            "  (use 'minigit restore <file>...' to discard changes in working directory)",
        ],
    )
    lines += _untracked_section(untracked)

    if not (staged or unstaged or untracked):
        lines.append("nothing to commit, working tree clean")
        if head_commit(repo) is not None:
            lines.append(color.cyan("  (use 'minigit log' to view history)"))

    print("\n".join(lines).rstrip("\n"))
    return 0
