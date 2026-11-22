"""Preserve the public guide's relative links in the installed offline copy."""

from collections import defaultdict
from pathlib import Path

from setuptools import setup

groups = defaultdict(list)
for pattern in (
    "README.md", "LICENSE", "THIRD_PARTY.md", "docs/*.md", "examples/*.py",
    "requirements/*.txt", "firmware/*.py", "firmware/*.c", "firmware/*.h", "firmware/*.ld",
    "evidence/**/*.md", "evidence/**/*.json", "evidence/**/*.jsonl",
    "evidence/**/*.zip", "evidence/**/*.csv", "evidence/**/*.svg",
):
    for path in sorted(Path(".").glob(pattern)):
        destination = (Path("share/looptrial") / path.parent).as_posix()
        groups[destination].append(path.as_posix())

setup(data_files=sorted(groups.items()))
