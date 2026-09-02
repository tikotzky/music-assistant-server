"""
Release the 24six fork of Music Assistant on top of an upstream stable release.

The fork's stable branch is upstream stable rebased with the 24six provider on top. A fork
release is named after the upstream release the branch is based on, with a 24six counter
appended: ``2.10.1-24six.1`` is the Git tag, the container image tag and the Home Assistant
add-on version, and ``2.10.1+24six.1`` is the PEP 440 version of the Python package inside it.
The counter restarts at 1 whenever the branch moves to a newer upstream release.

The command-line interface emits values to ``$GITHUB_OUTPUT`` when requested so the fork
release workflow keeps its version logic in tested Python.
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

FORK_LABEL = "24six"
UPSTREAM_TAG_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
FORK_VERSION_PATTERN = re.compile(
    rf"^(?P<base>\d+\.\d+\.\d+)-{FORK_LABEL}\.(?P<number>[1-9]\d*)$",
)
BASE_IMAGE_PATTERN = re.compile(
    r'^\s*BASE_IMAGE_VERSION_STABLE:\s*"(?P<version>[^"]+)"\s*$',
    re.MULTILINE,
)


class ForkReleaseError(RuntimeError):
    """Report a release request that cannot be fulfilled safely."""


@dataclass(frozen=True)
class ForkVersion:
    """A fork release: an upstream stable version plus the 24six counter on top of it."""

    base: str
    number: int

    @classmethod
    def parse(cls, version: str) -> ForkVersion:
        """
        Parse a fork version such as ``2.10.1-24six.3``.

        :param version: Version string to parse.
        """
        match = FORK_VERSION_PATTERN.fullmatch(version)
        if match is None:
            raise ForkReleaseError(
                f"Version {version} must look like <upstream version>-{FORK_LABEL}.<number>",
            )
        return cls(base=match["base"], number=int(match["number"]))

    @property
    def tag(self) -> str:
        """Return the Git tag, image tag and add-on version, e.g. ``2.10.1-24six.3``."""
        return f"{self.base}-{FORK_LABEL}.{self.number}"

    @property
    def package_version(self) -> str:
        """Return the PEP 440 version of the Python package, e.g. ``2.10.1+24six.3``."""
        return f"{self.base}+{FORK_LABEL}.{self.number}"


class GitRepository:
    """Read tags and commit relationships from a Git repository."""

    def __init__(self, path: Path) -> None:
        """
        Wrap the repository at ``path``.

        :param path: Repository working directory.
        """
        self.path = path

    def upstream_base(self, tag_namespace: str) -> str:
        """
        Return the newest upstream stable release that is part of ``HEAD``.

        :param tag_namespace: Ref prefix the upstream tags were fetched into,
            e.g. ``refs/upstream-tags``.
        """
        refs = self._run("for-each-ref", "--format=%(refname)", f"{tag_namespace}/").splitlines()
        prefix = f"{tag_namespace}/"
        candidates = [
            ref.removeprefix(prefix)
            for ref in refs
            if UPSTREAM_TAG_PATTERN.fullmatch(ref.removeprefix(prefix))
        ]
        for tag in sorted(candidates, key=_version_tuple, reverse=True):
            if self._is_ancestor(f"{prefix}{tag}^{{commit}}", "HEAD"):
                return tag
        raise ForkReleaseError(
            f"No upstream stable release tag under {tag_namespace} is part of HEAD; "
            "is the branch rebased on upstream stable?",
        )

    def tags(self) -> set[str]:
        """Return every tag in the repository."""
        return set(self._run("tag", "--list").splitlines())

    def commit_subjects(self, since: str) -> list[str]:
        """
        Return the commit subjects on top of ``since``, oldest first.

        :param since: Revision the listed commits are on top of.
        """
        output = self._run("log", "--reverse", "--format=%s", f"{since}..HEAD")
        return [line for line in output.splitlines() if line]

    def _is_ancestor(self, ancestor: str, descendant: str) -> bool:
        command = ["git", "-C", str(self.path), "merge-base", "--is-ancestor", ancestor, descendant]
        result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
        return result.returncode == 0

    def _run(self, *args: str) -> str:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(self.path), *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()


def resolve_version(
    repository: GitRepository,
    requested: str | None,
    tag_namespace: str,
) -> ForkVersion:
    """
    Decide which fork version to release from the checked-out branch.

    :param repository: Repository holding the release source at ``HEAD``.
    :param requested: Explicit version, or ``None``/empty to bump the 24six counter.
    :param tag_namespace: Ref prefix the upstream tags were fetched into.
    """
    base = repository.upstream_base(tag_namespace)
    existing = repository.tags()
    if requested:
        version = ForkVersion.parse(requested)
        if version.base != base:
            raise ForkReleaseError(
                f"Version {requested} is based on {version.base} but the branch is based on "
                f"upstream {base}",
            )
    else:
        version = ForkVersion(base=base, number=next_number(existing, base))
    if version.tag in existing:
        raise ForkReleaseError(f"Version {version.tag} has already been released")
    return version


def next_number(tags: Iterable[str], base: str) -> int:
    """
    Return the next free 24six counter for an upstream base version.

    :param tags: Existing tags of the fork.
    :param base: Upstream stable version the branch is based on.
    """
    numbers = [
        version.number
        for version in map(_parse_fork_tag, tags)
        if version is not None and version.base == base
    ]
    return max(numbers, default=0) + 1


def base_image_version(release_workflow: Path) -> str:
    """
    Read the stable base image version from upstream's release workflow.

    :param release_workflow: Path to upstream's ``release.yml``.
    """
    match = BASE_IMAGE_PATTERN.search(release_workflow.read_text(encoding="utf-8"))
    if match is None:
        raise ForkReleaseError(f"No BASE_IMAGE_VERSION_STABLE found in {release_workflow}")
    return match["version"]


def release_notes(
    version: ForkVersion,
    subjects: Iterable[str],
    *,
    image: str,
    upstream_repository: str,
) -> str:
    """
    Render the release notes for a fork release.

    :param version: Version being released.
    :param subjects: Commit subjects the fork carries on top of upstream, oldest first.
    :param image: Container image repository, e.g. ``ghcr.io/tikotzky/server``.
    :param upstream_repository: Upstream GitHub repository, e.g. ``music-assistant/server``.
    """
    changes = "\n".join(f"- {subject}" for subject in subjects) or "- (none)"
    return (
        f"Music Assistant {version.base} with the {FORK_LABEL} provider.\n"
        "\n"
        f"- Upstream release: https://github.com/{upstream_repository}/releases/tag/{version.base}\n"
        f"- Container image: `{image}:{version.tag}`\n"
        f"- Python package version: `{version.package_version}`\n"
        "\n"
        f"## {FORK_LABEL} changes on top of upstream\n"
        "\n"
        f"{changes}\n"
    )


def main() -> int:
    """Run the command-line interface."""
    args = _build_parser().parse_args()
    try:
        outputs = _dispatch(args)
    except (ForkReleaseError, subprocess.CalledProcessError) as err:
        print(err, file=sys.stderr)
        return 1
    _write_outputs(outputs, args.github_output)
    return 0


def _dispatch(args: argparse.Namespace) -> dict[str, str]:
    if args.command == "resolve-version":
        version = resolve_version(
            GitRepository(args.repository),
            args.requested,
            args.upstream_tag_namespace,
        )
        return {
            "version": version.tag,
            "package_version": version.package_version,
            "base": version.base,
        }
    if args.command == "base-image-version":
        return {"base_image_version": base_image_version(args.release_workflow)}
    version = ForkVersion.parse(args.version)
    notes = release_notes(
        version,
        GitRepository(args.repository).commit_subjects(
            f"{args.upstream_tag_namespace}/{version.base}"
        ),
        image=args.image,
        upstream_repository=args.upstream_repository,
    )
    args.output.write_text(notes, encoding="utf-8")
    return {}


def _parse_fork_tag(tag: str) -> ForkVersion | None:
    match = FORK_VERSION_PATTERN.fullmatch(tag)
    if match is None:
        return None
    return ForkVersion(base=match["base"], number=int(match["number"]))


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _write_outputs(outputs: dict[str, str], github_output: Path | None) -> None:
    for key, value in outputs.items():
        print(f"{key}={value}")
    if github_output is None:
        return
    with github_output.open("a", encoding="utf-8") as file_handle:
        for key, value in outputs.items():
            file_handle.write(f"{key}={value}\n")


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-tag-namespace", default="refs/upstream-tags")
    parser.add_argument("--github-output", type=Path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve-version")
    resolve_parser.add_argument("--requested", default="")
    _add_common_arguments(resolve_parser)

    image_parser = subparsers.add_parser("base-image-version")
    image_parser.add_argument("--release-workflow", type=Path, required=True)
    _add_common_arguments(image_parser)

    notes_parser = subparsers.add_parser("release-notes")
    notes_parser.add_argument("--version", required=True)
    notes_parser.add_argument("--image", required=True)
    notes_parser.add_argument("--upstream-repository", required=True)
    notes_parser.add_argument("--output", type=Path, required=True)
    _add_common_arguments(notes_parser)
    return parser


if __name__ == "__main__":
    sys.exit(main())
