"""End-to-end tests for the built-in commands."""

import hashlib
import io
import os
import subprocess
import sys

import pytest

from minigit.index import Index
from minigit.objects import flatten_tree, read_commit
from minigit.refs import head_commit

HELLO_BLOB = "ce013625030ba8dba906f756967f9e9ca394464a"


# -- cli ----------------------------------------------------------------------


def test_no_command_prints_help(workdir, run):
    result = run()
    assert result.code == 1
    assert "init" in result.out


def test_outside_a_repository(workdir, run):
    result = run("add", "x")
    assert result.code == 128
    assert result.err.startswith("fatal: not a minigit repository")


def test_works_from_a_subdirectory(repo, run, write, monkeypatch):
    write("src/app.py", "print(1)\n")
    monkeypatch.chdir(repo.worktree / "src")
    assert run("add", "app.py").code == 0
    assert "src/app.py" in Index.load(repo)


# -- init ---------------------------------------------------------------------


def test_init_creates_layout(workdir, run):
    result = run("init")
    assert result.code == 0
    assert "Initialized empty minigit repository" in result.out
    gitdir = workdir / ".minigit"
    assert (gitdir / "HEAD").read_text() == "ref: refs/heads/main\n"
    for directory in ("objects", "refs/heads", "refs/tags"):
        assert (gitdir / directory).is_dir()


def test_init_in_directory(workdir, run):
    run("init", "project")
    assert (workdir / "project" / ".minigit" / "HEAD").is_file()


def test_reinit_keeps_data(repo, run):
    (repo.gitdir / "HEAD").write_text("ref: refs/heads/dev\n")
    result = run("init")
    assert "Reinitialized existing" in result.out
    assert (repo.gitdir / "HEAD").read_text() == "ref: refs/heads/dev\n"


@pytest.mark.parametrize("option", ["-b", "--initial-branch"])
@pytest.mark.parametrize("branch", ["trunk", "feature/login"])
def test_init_with_initial_branch(workdir, run, option, branch):
    result = run("init", option, branch, "project")
    assert result.code == 0
    assert "Initialized empty minigit repository" in result.out
    assert result.err == ""
    assert (workdir / "project" / ".minigit" / "HEAD").read_text() == (
        f"ref: refs/heads/{branch}\n"
    )


@pytest.mark.parametrize(
    "branch",
    [
        "",
        "bad name",
        "bad..name",
        "-bad",
        "bad\tname",
        "bad\nname",
        "bad\x7fname",
        "/bad",
        "bad/",
        "bad//name",
        ".bad",
        "bad/.name",
        "bad.",
        "bad.lock",
        "bad.lock/name",
        "bad@{name",
        "bad~name",
        "bad^name",
        "bad:name",
        "bad?name",
        "bad*name",
        "bad[name",
        "bad\\name",
    ],
)
def test_init_rejects_invalid_initial_branch(workdir, run, branch):
    result = run("init", f"--initial-branch={branch}", "project")
    assert result.code == 128
    assert result.out == ""
    assert "fatal: invalid initial branch name:" in result.err
    assert not (workdir / "project").exists()


@pytest.mark.parametrize("option", ["-q", "--quiet"])
def test_init_quiet(workdir, run, option):
    result = run("init", option, "-b", "trunk", "project")
    assert result.code == 0
    assert result.out == result.err == ""
    assert (workdir / "project" / ".minigit" / "HEAD").read_text() == ("ref: refs/heads/trunk\n")
    result = run("init", option, "project")
    assert result.code == 0
    assert result.out == result.err == ""


@pytest.mark.parametrize("quiet", [False, True])
@pytest.mark.parametrize("head", ["ref: refs/heads/dev\n", "a" * 40 + "\n"])
@pytest.mark.parametrize("branch", ["trunk", "bad name"])
def test_reinit_ignores_initial_branch(repo, run, quiet, head, branch):
    (repo.gitdir / "HEAD").write_text(head)
    result = run("init", "--initial-branch", branch, *(["--quiet"] if quiet else []))
    assert result.code == 0
    assert result.err == f"warning: re-init: ignored --initial-branch={branch}\n"
    if quiet:
        assert result.out == ""
    else:
        assert "Reinitialized existing" in result.out
    assert (repo.gitdir / "HEAD").read_text() == head


def test_quiet_init_still_reports_errors(workdir, run):
    result = run("init", "-q", "-b", "bad name")
    assert result.code == 128
    assert result.out == ""
    assert "fatal: invalid initial branch name:" in result.err
    assert not (workdir / ".minigit").exists()


def test_commit_on_initial_branch(workdir, run, write):
    assert run("init", "-b", "feature/login").code == 0
    write("hello.txt", "hello\n")
    assert run("add", "hello.txt").code == 0
    result = run("commit", "-m", "first")
    assert result.code == 0
    assert result.out.startswith("[feature/login (root-commit) ")


# -- hash-object / cat-file ---------------------------------------------------


def test_hash_object(repo, run, write):
    write("hello.txt", "hello\n")
    assert run("hash-object", "hello.txt").out == HELLO_BLOB + "\n"
    assert not (repo.gitdir / "objects" / "ce").exists()
    run("hash-object", "-w", "hello.txt")
    assert (repo.gitdir / "objects" / "ce").is_dir()


def test_hash_object_missing_file(repo, run):
    assert run("hash-object", "nope.txt").code == 128


def test_hash_object_multiple_files(run, write):
    write("first.txt", "hello\n")
    write("second.txt", "world\n")

    result = run("hash-object", "first.txt", "second.txt")
    second_blob = hashlib.sha1(b"blob 6\0world\n").hexdigest()

    assert result.code == 0
    assert result.out == HELLO_BLOB + "\n" + second_blob + "\n"


def test_hash_object_stdin(run, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"hello\n")))
    result = run("hash-object", "--stdin")
    assert result.code == 0
    assert result.out == HELLO_BLOB + "\n"


def test_hash_object_stdin_write(repo, run, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"hello\n")))
    result = run("hash-object", "--stdin", "-w")
    assert result.code == 0
    assert result.out == HELLO_BLOB + "\n"
    assert (repo.gitdir / "objects" / HELLO_BLOB[:2] / HELLO_BLOB[2:]).is_file()


def test_hash_object_stdin_binary(run, monkeypatch):
    data = b"\x00\xffA"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))
    result = run("hash-object", "--stdin")
    header = b"blob " + str(len(data)).encode() + b"\0"
    expected = hashlib.sha1(header + data).hexdigest()

    assert result.code == 0
    assert result.out == expected + "\n"


def test_cat_file_blob(repo, run, write):
    write("hello.txt", "hello\n")
    run("hash-object", "-w", "hello.txt")
    assert run("cat-file", "-t", HELLO_BLOB).out == "blob\n"
    assert run("cat-file", "-s", HELLO_BLOB).out == "6\n"
    assert run("cat-file", "-p", HELLO_BLOB).out == "hello\n"


def test_cat_file_tree_and_commit(repo, run, write):
    write("hello.txt", "hello\n")
    write("src/app.py", "print(1)\n")
    run("add", ".")
    run("commit", "-m", "first")
    commit = run("cat-file", "-p", "HEAD").out
    assert commit.startswith("tree ")
    tree_sha = commit.split()[1]
    listing = run("cat-file", "-p", tree_sha).out.splitlines()
    assert listing[0] == f"100644 blob {HELLO_BLOB}\thello.txt"
    assert listing[1].startswith("040000 tree ") and listing[1].endswith("\tsrc")


def test_cat_file_unknown(repo, run):
    result = run("cat-file", "-p", "nope")
    assert result.code == 128
    assert "unknown revision" in result.err


# -- add ----------------------------------------------------------------------


def test_add_file(repo, run, write):
    write("hello.txt", "hello\n")
    result = run("add", "hello.txt")
    assert result.code == 0
    assert "hello.txt is staged" in result.out
    entry = Index.load(repo).get("hello.txt")
    assert entry.sha == HELLO_BLOB


def test_add_file_colored_green_when_color_enabled(repo, run, write, monkeypatch):
    monkeypatch.setattr("minigit.color._should_color", lambda: True)
    write("hello.txt", "hello\n")
    result = run("add", "hello.txt")
    assert result.code == 0
    assert "\033[32mhello.txt is staged\033[0m" in result.out


def test_add_directory_recursively(repo, run, write):
    write("a.txt", "a")
    write("src/b.py", "b")
    write("src/deep/c.py", "c")
    run("add", "src")
    assert [e.path for e in Index.load(repo)] == ["src/b.py", "src/deep/c.py"]
    run("add", ".")
    assert len(Index.load(repo)) == 3


def test_add_stages_deletion_of_removed_file(repo, run, write):
    write("hello.txt", "hello\n")
    write("keep.txt", "keep\n")
    run("add", ".")
    (repo.worktree / "hello.txt").unlink()
    assert run("add", ".").code == 0
    assert [e.path for e in Index.load(repo)] == ["keep.txt"]


def test_add_updates_changed_file(repo, run, write):
    write("hello.txt", "hello\n")
    run("add", "hello.txt")
    write("hello.txt", "changed\n")
    run("add", "hello.txt")
    assert Index.load(repo).get("hello.txt").sha != HELLO_BLOB


def test_add_never_stages_metadata(repo, run, write):
    write("hello.txt", "hello\n")
    run("add", ".")
    assert all(not e.path.startswith(".minigit") for e in Index.load(repo))
    assert run("add", ".minigit/HEAD").code == 128


def test_add_missing_path(repo, run):
    result = run("add", "ghost.txt")
    assert result.code == 128
    assert "did not match any files" in result.err


def test_add_binary_file(repo, run, write):
    write("image.bin", bytes(range(256)))
    run("add", "image.bin")
    sha = Index.load(repo).get("image.bin").sha
    assert run("cat-file", "-s", sha).out == "256\n"


# -- commit -------------------------------------------------------------------


def test_first_commit(repo, run, write):
    write("hello.txt", "hello\n")
    run("add", "hello.txt")
    result = run("commit", "-m", "First commit")
    assert result.code == 0
    sha = head_commit(repo)
    assert result.out == f"[main (root-commit) {sha[:7]}] First commit\n"
    commit = read_commit(repo, sha)
    assert commit.parents == []
    assert commit.message == "First commit\n"
    assert commit.author.name == "Ada Lovelace"
    assert list(flatten_tree(repo, commit.tree)) == ["hello.txt"]


def test_commit_sha_matches_git(repo, run, write):
    # Same content, author and time always give the same SHA, and it is the
    # SHA real Git would produce (checked against an independent Git
    # implementation).
    write("hello.txt", "hello\n")
    write("src/app.py", "print(1)\n")
    run("add", ".")
    run("commit", "-m", "First commit")
    assert head_commit(repo) == "fb2368536aa0b5238a8c2e1443b3cec6e76a45a0"


def test_second_commit_has_parent(repo, run, write):
    write("a.txt", "1")
    run("add", "a.txt")
    run("commit", "-m", "one")
    first = head_commit(repo)
    write("a.txt", "2")
    run("add", "a.txt")
    result = run("commit", "-m", "two")
    assert result.out.startswith("[main ")
    assert read_commit(repo, head_commit(repo)).parents == [first]


def test_nothing_to_commit(repo, run, write):
    assert run("commit", "-m", "empty").code == 1
    write("a.txt", "1")
    run("add", "a.txt")
    run("commit", "-m", "one")
    result = run("commit", "-m", "again")
    assert result.code == 1
    assert "nothing to commit" in result.out


def test_multiple_messages_become_paragraphs(repo, run, write):
    write("a.txt", "1")
    run("add", "a.txt")
    run("commit", "-m", "Title", "-m", "Body text.")
    assert read_commit(repo, head_commit(repo)).message == "Title\n\nBody text.\n"


def test_commit_all_stages_modified_and_deleted_but_not_untracked(repo, run, write, workdir):
    write("keep.txt", "keep\n")
    write("change.txt", "old\n")
    write("gone.txt", "bye\n")
    run("add", ".")
    run("commit", "-m", "first")
    write("change.txt", "new\n")
    (workdir / "gone.txt").unlink()
    write("untracked.txt", "not added\n")
    result = run("commit", "-a", "-m", "Update")
    assert result.code == 0
    files = flatten_tree(repo, read_commit(repo, head_commit(repo)).tree)
    assert sorted(files) == ["change.txt", "keep.txt"]
    assert files["change.txt"].sha == hashlib.sha1(b"blob 4\x00new\n").hexdigest()


def test_empty_message_rejected(repo, run, write):
    write("a.txt", "1")
    run("add", "a.txt")
    assert run("commit", "-m", "   ").code == 128


# -- count-objects ------------------------------------------------------------


def test_count_objects_empty(repo, run):
    result = run("count-objects")
    assert result.code == 0
    assert result.out == "0 objects, 0 kilobytes\n"
    assert run("count-objects", "-v").out == "count: 0\nsize: 0\n"


def test_count_objects_normal_and_verbose(repo, run, write):
    write("hello.txt", "hello\n")
    run("add", "hello.txt")
    run("commit", "-m", "First commit")

    result = run("count-objects")
    assert result.code == 0
    assert result.out.startswith("3 objects, ")
    assert result.out.endswith(" kilobytes\n")

    lines = run("count-objects", "-v").out.splitlines()
    assert lines[0] == "count: 3"
    assert lines[1].startswith("size: ")


def test_count_objects_deduplication(repo, run, write):
    write("file1.txt", "identical content\n")
    run("add", "file1.txt")
    assert run("count-objects", "-v").out.splitlines()[0] == "count: 1"

    # Adding a different file with identical content should NOT create another object
    write("file2.txt", "identical content\n")
    run("add", "file2.txt")
    assert run("count-objects", "-v").out.splitlines()[0] == "count: 1"


def test_count_objects_ignores_tmp_files(repo, run, write):
    write("file.txt", "content\n")
    run("add", "file.txt")

    before = run("count-objects", "-v").out

    # Leftover .tmp file inside the object directory should not affect count or size
    fanout = next(d for d in (repo.gitdir / "objects").iterdir() if d.is_dir() and len(d.name) == 2)
    (fanout / "temp.tmp").write_bytes(b"x" * 8192)

    after = run("count-objects", "-v").out
    assert after == before


# -- cat-file -e / --batch-check ----------------------------------------------


def test_cat_file_exists(repo, run, write):
    write("hello.txt", "hello\n")
    run("hash-object", "-w", "hello.txt")

    result = run("cat-file", "-e", HELLO_BLOB)
    assert result.code == 0
    assert result.out == ""
    assert result.err == ""


def test_cat_file_exists_missing_sha(repo, run, write):
    write("hello.txt", "hello\n")
    run("hash-object", "-w", "hello.txt")
    missing = HELLO_BLOB[:-1] + ("0" if HELLO_BLOB[-1] != "0" else "1")

    result = run("cat-file", "-e", missing)
    assert result.code == 1
    assert result.out == ""
    assert result.err == ""


def test_cat_file_exists_bad_name(repo, run):
    result = run("cat-file", "-e", "nope")
    assert result.code == 1
    assert result.out == ""
    assert result.err == ""


def test_cat_file_exists_head(repo, run, write):
    write("hello.txt", "hello\n")
    run("add", ".")
    run("commit", "-m", "first")

    assert run("cat-file", "-e", "HEAD").code == 0


def _stdin(monkeypatch, text: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(text.encode())))


def _batch_names(run) -> str:
    sha = run("rev-parse", "HEAD").out.strip()
    return f"{sha}\nHEAD\nmain\nnope\n{HELLO_BLOB}\n"


def _real_git_batch(workdir, names: str) -> str:
    env = {**os.environ, "GIT_DIR": str(workdir / ".minigit"), "GIT_WORK_TREE": str(workdir)}
    done = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=workdir,
        env=env,
        input=names,
        text=True,
        capture_output=True,
        check=True,
    )
    return done.stdout


def test_cat_file_batch_check(repo, run, write, monkeypatch):
    write("hello.txt", "hello\n")
    run("add", ".")
    run("commit", "-m", "first")
    names = _batch_names(run)
    _stdin(monkeypatch, names)

    result = run("cat-file", "--batch-check")
    assert result.code == 0
    lines = result.out.splitlines()
    sha = names.splitlines()[0]
    assert lines[0].startswith(f"{sha} commit ")
    assert lines[1].startswith(f"{sha} commit ")
    assert lines[2].startswith(f"{sha} commit ")
    assert lines[3] == "nope missing"
    assert lines[4] == f"{HELLO_BLOB} blob 6"


def test_cat_file_batch_check_matches_git(repo, run, write, git, monkeypatch, workdir):
    write("hello.txt", "hello\n")
    run("add", ".")
    run("commit", "-m", "first")
    names = _batch_names(run)
    _stdin(monkeypatch, names)

    assert run("cat-file", "--batch-check").out == _real_git_batch(workdir, names)


def test_cat_file_batch_check_empty(repo, run, monkeypatch):
    _stdin(monkeypatch, "")

    result = run("cat-file", "--batch-check")
    assert result.code == 0
    assert result.out == ""
