from pathlib import Path

import pytest

from gitlab_harbor_sync.config import load_targets


def write(tmp_path: Path, value: str) -> str:
    path = tmp_path / "targets.yaml"
    path.write_text(value, encoding="utf-8")
    return str(path)


def test_load_targets_direct_list(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
- git-project-tag: prod
  harbor-target: production/apps
""",
    )
    targets = load_targets(path)
    assert len(targets) == 1
    assert targets[0].git_project_tag == "prod"
    assert targets[0].harbor_target == "production/apps"


def test_load_targets_wrapper_and_dedup(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
targets:
  - git-project-tag: prod
    harbor-target: /production/apps/
  - git-project-tag: prod
    harbor-target: production/apps
""",
    )
    targets = load_targets(path)
    assert len(targets) == 1
    assert targets[0].harbor_target == "production/apps"


@pytest.mark.parametrize(
    "value",
    [
        "- harbor-target: prod\n",
        "- git-project-tag: prod\n",
        "- git-project-tag: prod\n  harbor-target: https://bad.example\n",
        "- git-project-tag: prod\n  harbor-target: prod/../bad\n",
    ],
)
def test_load_targets_rejects_invalid_entries(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError):
        load_targets(write(tmp_path, value))
