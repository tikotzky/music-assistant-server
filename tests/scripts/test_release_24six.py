"""Tests for the 24six fork release helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.release_24six import (
    ForkReleaseError,
    ForkVersion,
    GitRepository,
    base_image_version,
    next_number,
    release_notes,
    resolve_version,
)

TAG_NAMESPACE = "refs/upstream-tags"


@pytest.fixture(name="repository")
def repository_fixture(tmp_path: Path) -> tuple[Path, GitRepository]:
    """Create a fork checkout: upstream 2.10.1 with two 24six commits on top."""
    _git(tmp_path, "init", "-b", "stable")
    _git(tmp_path, "config", "user.name", "Release Test")
    _git(tmp_path, "config", "user.email", "release@example.com")
    _commit(tmp_path, "upstream 2.10.0")
    _git(tmp_path, "update-ref", f"{TAG_NAMESPACE}/2.10.0", "HEAD")
    _commit(tmp_path, "upstream 2.10.1")
    _git(tmp_path, "update-ref", f"{TAG_NAMESPACE}/2.10.1", "HEAD")
    _git(tmp_path, "update-ref", f"{TAG_NAMESPACE}/2.11.0b1", "HEAD")
    _commit(tmp_path, "Add 24six provider")
    _commit(tmp_path, "Add 24six radio")
    return tmp_path, GitRepository(tmp_path)


def test_fork_version_round_trips_tag_and_package_version() -> None:
    """The tag carries a dash for Docker and the package a plus for PEP 440."""
    version = ForkVersion.parse("2.10.1-24six.3")

    assert version == ForkVersion(base="2.10.1", number=3)
    assert version.tag == "2.10.1-24six.3"
    assert version.package_version == "2.10.1+24six.3"


@pytest.mark.parametrize(
    "version",
    [
        "2.10.1",
        "2.10.1-24six.01",
        "2.10.1-24six.0",
        "2.10.1+24six.1",
        "2.10.1-24six",
        "2.10-24six.1",
    ],
)
def test_fork_version_rejects_other_shapes(version: str) -> None:
    """Only <upstream>-24six.<counter without leading zeros> is a fork version."""
    with pytest.raises(ForkReleaseError):
        ForkVersion.parse(version)


def test_next_number_counts_only_the_current_base() -> None:
    """The counter restarts at 1 for every new upstream base."""
    tags = {"2.10.0-24six.1", "2.10.0-24six.2", "2.10.1-24six.1", "2.8.0", "nightly"}

    assert next_number(tags, "2.10.0") == 3
    assert next_number(tags, "2.10.1") == 2
    assert next_number(tags, "2.10.2") == 1


def test_resolve_version_bumps_the_counter_on_the_reachable_upstream_release(
    repository: tuple[Path, GitRepository],
) -> None:
    """The newest upstream stable tag inside HEAD is the base; pre-releases are ignored."""
    path, repo = repository
    _git(path, "tag", "2.10.1-24six.1")

    assert resolve_version(repo, "", TAG_NAMESPACE) == ForkVersion(base="2.10.1", number=2)


def test_resolve_version_ignores_upstream_releases_outside_the_branch(
    repository: tuple[Path, GitRepository],
) -> None:
    """An upstream tag on another branch does not become the base."""
    path, repo = repository
    _git(path, "checkout", "--quiet", "-b", "other", f"{TAG_NAMESPACE}/2.10.0")
    _commit(path, "upstream 2.10.2 elsewhere")
    _git(path, "update-ref", f"{TAG_NAMESPACE}/2.10.2", "HEAD")
    _git(path, "checkout", "--quiet", "stable")

    assert resolve_version(repo, "", TAG_NAMESPACE) == ForkVersion(base="2.10.1", number=1)


def test_resolve_version_accepts_an_explicit_version_on_the_same_base(
    repository: tuple[Path, GitRepository],
) -> None:
    """An explicit version may skip counters but must match the branch's base."""
    _path, repo = repository

    assert resolve_version(repo, "2.10.1-24six.5", TAG_NAMESPACE) == ForkVersion(
        base="2.10.1", number=5
    )
    with pytest.raises(ForkReleaseError, match=r"based on upstream 2\.10\.1"):
        resolve_version(repo, "2.10.2-24six.1", TAG_NAMESPACE)


def test_resolve_version_refuses_a_released_tag(repository: tuple[Path, GitRepository]) -> None:
    """A version that already has a tag cannot be released twice."""
    path, repo = repository
    _git(path, "tag", "2.10.1-24six.1")

    with pytest.raises(ForkReleaseError, match="already been released"):
        resolve_version(repo, "2.10.1-24six.1", TAG_NAMESPACE)


def test_resolve_version_needs_an_upstream_base(tmp_path: Path) -> None:
    """Without a reachable upstream stable tag there is nothing to name the release after."""
    _git(tmp_path, "init", "-b", "stable")
    _git(tmp_path, "config", "user.name", "Release Test")
    _git(tmp_path, "config", "user.email", "release@example.com")
    _commit(tmp_path, "orphan")

    with pytest.raises(ForkReleaseError, match="No upstream stable release tag"):
        resolve_version(GitRepository(tmp_path), "", TAG_NAMESPACE)


def test_commit_subjects_lists_the_fork_commits_oldest_first(
    repository: tuple[Path, GitRepository],
) -> None:
    """Release notes list what the fork carries on top of the upstream base."""
    _path, repo = repository

    assert repo.commit_subjects(f"{TAG_NAMESPACE}/2.10.1") == [
        "Add 24six provider",
        "Add 24six radio",
    ]


def test_base_image_version_reads_upstream_release_workflow(tmp_path: Path) -> None:
    """The stable base image version follows whatever upstream's workflow pins."""
    workflow = tmp_path / "release.yml"
    workflow.write_text(
        'env:\n  BASE_IMAGE_VERSION_STABLE: "1.6.3"\n  BASE_IMAGE_VERSION_BETA: "1.7.0"\n',
        encoding="utf-8",
    )

    assert base_image_version(workflow) == "1.6.3"

    workflow.write_text("env:\n  OTHER: 1\n", encoding="utf-8")
    with pytest.raises(ForkReleaseError):
        base_image_version(workflow)


def test_release_notes_link_upstream_and_list_changes() -> None:
    """Notes name the upstream release, the image and the fork's commits."""
    notes = release_notes(
        ForkVersion.parse("2.10.1-24six.2"),
        ["Add 24six provider", "Add 24six radio"],
        image="ghcr.io/tikotzky/server",
        upstream_repository="music-assistant/server",
    )

    assert notes.startswith("Music Assistant 2.10.1 with the 24six provider.\n")
    assert "https://github.com/music-assistant/server/releases/tag/2.10.1" in notes
    assert "`ghcr.io/tikotzky/server:2.10.1-24six.2`" in notes
    assert "`2.10.1+24six.2`" in notes
    assert notes.endswith("- Add 24six provider\n- Add 24six radio\n")


def _git(path: Path, *args: str) -> str:
    command = ["git", "-C", str(path), "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    result = subprocess.run(  # noqa: S603
        [*command, *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(path: Path, message: str) -> None:
    _git(path, "commit", "--quiet", "--allow-empty", "-m", message)
