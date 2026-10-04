"""Internal data models used by the reconciler."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import MANAGED_PREFIX
from .utils import short_hash


@dataclass(frozen=True)
class TargetConfig:
    """One GitLab project-topic to Harbor destination mapping."""

    git_project_tag: str
    harbor_target: str


@dataclass(frozen=True)
class DesiredProject:
    """Resolved GitLab project and its desired Harbor destination."""

    gitlab_project_id: int
    gitlab_project_name: str
    gitlab_project_path: str
    gitlab_topic: str
    source_registry_url: str
    source_repository: str
    harbor_target: str
    harbor_project: str

    def policy_name(self, scope: str) -> str:
        # The target hash allows one GitLab project to replicate to more than
        # one Harbor destination without policy-name collisions.
        target_hash = short_hash(self.harbor_target)
        return f"{MANAGED_PREFIX}p{self.gitlab_project_id}-{target_hash}-{scope}"

    @property
    def flatten_count(self) -> int:
        # GitLab repository prefix is namespace/project. Remove the namespace
        # components while preserving the project component:
        #   group/subgroup/project       -> harbor-target/project
        #   group/subgroup/project/image -> harbor-target/project/image
        parts = [part for part in self.source_repository.split("/") if part]
        return max(len(parts) - 1, 0)


@dataclass(frozen=True)
class DesiredPolicy:
    """Desired Harbor replication-policy state."""

    name: str
    description: str
    endpoint_name: str
    endpoint_id: int
    dest_namespace: str
    flatten_count: int
    name_filter: str
