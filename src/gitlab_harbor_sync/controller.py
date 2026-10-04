"""GitLab-to-Harbor reconciliation controller."""

from __future__ import annotations

import logging
import os
import re
from typing import Iterable

import gitlab
from gitlab.v4.objects import Project
from harborapi import HarborAsyncClient
from harborapi.exceptions import NotFound, PreconditionFailed, StatusError
from harborapi.models import (
    ProjectReq,
    Registry,
    RegistryCredential,
    RegistryUpdate,
    ReplicationFilter,
    ReplicationPolicy,
    ReplicationTrigger,
    ReplicationTriggerSettings,
)

from .config import env_bool, load_targets, require_env
from .constants import DEFAULT_CONFIG_PATH, DEFAULT_REPLICATION_CRON, MANAGED_PREFIX
from .models import DesiredPolicy, DesiredProject, TargetConfig
from .utils import (
    id_from_location,
    is_managed,
    marker_description,
    normalize_harbor_api_url,
    normalize_registry_url,
    short_hash,
    split_registry_prefix,
)

LOG = logging.getLogger("gitlab-harbor-sync")


class SyncController:
    """Reconcile desired GitLab project replication state into Harbor."""

    def __init__(self) -> None:
        self.gitlab_url = require_env("GITLAB_URL").rstrip("/")
        self.gitlab_token = require_env("GITLAB_ACCESS_TOKEN")
        self.config_path = os.getenv("CONFIG_PATH", DEFAULT_CONFIG_PATH)
        self.registry_url_override = os.getenv("GITLAB_REGISTRY_URL")
        self.registry_type_override = os.getenv("HARBOR_REGISTRY_TYPE")
        self.gitlab_registry_insecure = env_bool("GITLAB_REGISTRY_INSECURE", False)
        self.gitlab_verify_tls = env_bool("GITLAB_VERIFY_TLS", True)

        self.harbor_api_url = normalize_harbor_api_url(require_env("HARBOR_URL"))
        self.harbor_username = require_env("HARBOR_USERNAME")
        self.harbor_password = require_env("HARBOR_PASSWORD")
        self.harbor_verify_tls = env_bool("HARBOR_VERIFY_TLS", True)
        self.replication_cron = os.getenv(
            "HARBOR_REPLICATION_CRON", DEFAULT_REPLICATION_CRON
        )

        self.gitlab = gitlab.Gitlab(
            self.gitlab_url,
            private_token=self.gitlab_token,
            ssl_verify=self.gitlab_verify_tls,
            timeout=30,
        )
        self.harbor = HarborAsyncClient(
            url=self.harbor_api_url,
            username=self.harbor_username,
            secret=self.harbor_password,
            verify=self.harbor_verify_tls,
            timeout=30.0,
        )
        self.gitlab_username = ""
        self.registry_type = ""

    async def close(self) -> None:
        """Close the Harbor HTTP client."""
        await self.harbor.client.aclose()

    async def run(self) -> None:
        targets = load_targets(self.config_path)
        LOG.info("Loaded %d target mapping(s) from %s", len(targets), self.config_path)

        # Authenticate early so configuration/auth errors fail the Job clearly.
        self.gitlab.auth()
        if not self.gitlab.user:
            raise RuntimeError("GitLab authentication succeeded without a current user")
        self.gitlab_username = self.gitlab.user.username
        LOG.info("Authenticated to GitLab as %s", self.gitlab_username)

        await self.harbor.get_system_info()
        LOG.info("Authenticated to Harbor at %s", self.harbor_api_url)

        self.registry_type = await self.choose_registry_type()
        desired_projects = self.discover_gitlab_projects(targets)

        for project_name in sorted({p.harbor_project for p in desired_projects.values()}):
            await self.ensure_harbor_project(project_name)

        # One managed endpoint is shared by all projects using the same source
        # registry. Credentials are refreshed unconditionally on every run.
        endpoint_ids: dict[str, int] = {}
        desired_endpoint_names: set[str] = set()
        for registry_url in sorted({p.source_registry_url for p in desired_projects.values()}):
            endpoint_name = self.endpoint_name(registry_url)
            endpoint_ids[registry_url] = await self.ensure_registry_endpoint(
                name=endpoint_name,
                registry_url=registry_url,
            )
            desired_endpoint_names.add(endpoint_name)

        desired_policies = self.build_desired_policies(
            desired_projects.values(), endpoint_ids
        )
        await self.reconcile_policies(desired_policies)
        await self.cleanup_registry_endpoints(desired_endpoint_names)

        LOG.info(
            "Reconciliation complete: %d GitLab project target(s), "
            "%d Harbor replication policy/policies",
            len(desired_projects),
            len(desired_policies),
        )

    def endpoint_name(self, registry_url: str) -> str:
        # Registry type is part of the name because Harbor does not allow the
        # endpoint type to be changed with RegistryUpdate.
        safe_type = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.registry_type)
        return f"{MANAGED_PREFIX}registry-{safe_type}-{short_hash(registry_url)}"

    async def choose_registry_type(self) -> str:
        if self.registry_type_override:
            LOG.info(
                "Using configured Harbor registry adapter type %s",
                self.registry_type_override,
            )
            return self.registry_type_override

        try:
            adapters = await self.harbor.get_registry_adapters()
            names = {
                str(getattr(adapter, "type", adapter))
                for adapter in adapters
            }
        except Exception as exc:  # Adapter-list behavior varies by Harbor release.
            LOG.warning("Could not list Harbor registry adapters: %s", exc)
            names = set()

        if "gitlab" in names:
            LOG.info("Harbor advertises the gitlab replication adapter; using it")
            return "gitlab"

        LOG.info("Using Harbor's generic docker-registry adapter for GitLab")
        return "docker-registry"

    def discover_gitlab_projects(
        self, targets: list[TargetConfig]
    ) -> dict[tuple[int, str], DesiredProject]:
        desired: dict[tuple[int, str], DesiredProject] = {}
        project_cache: dict[int, Project] = {}

        for target in targets:
            LOG.info("Finding GitLab projects with topic %r", target.git_project_tag)
            projects = self.gitlab.projects.list(
                topic=target.git_project_tag,
                get_all=True,
                simple=False,
            )
            LOG.info(
                "Topic %r matched %d GitLab project(s)",
                target.git_project_tag,
                len(projects),
            )

            for listed in projects:
                project = project_cache.get(listed.id)
                if project is None:
                    project = self.gitlab.projects.get(listed.id)
                    project_cache[listed.id] = project

                prefix = getattr(project, "container_registry_image_prefix", None)
                if not prefix:
                    LOG.warning(
                        "Skipping GitLab project %s (%s): container registry is "
                        "unavailable/disabled",
                        project.path_with_namespace,
                        project.id,
                    )
                    continue

                derived_registry_url, source_repository = split_registry_prefix(prefix)
                source_registry_url = normalize_registry_url(
                    self.registry_url_override or derived_registry_url
                )
                harbor_project = target.harbor_target.split("/", 1)[0]

                item = DesiredProject(
                    gitlab_project_id=int(project.id),
                    gitlab_project_name=str(project.path),
                    gitlab_project_path=str(project.path_with_namespace),
                    gitlab_topic=target.git_project_tag,
                    source_registry_url=source_registry_url,
                    source_repository=source_repository,
                    harbor_target=target.harbor_target,
                    harbor_project=harbor_project,
                )
                key = (item.gitlab_project_id, item.harbor_target)
                if key in desired:
                    LOG.info(
                        "Project %s already maps to %s through another configured "
                        "topic; deduplicating",
                        item.gitlab_project_path,
                        item.harbor_target,
                    )
                else:
                    desired[key] = item

        return desired

    async def ensure_harbor_project(self, project_name: str) -> None:
        try:
            await self.harbor.get_project(project_name)
            LOG.info("Harbor project %s already exists", project_name)
        except NotFound:
            LOG.info("Creating Harbor project %s", project_name)
            await self.harbor.create_project(
                ProjectReq(project_name=project_name, public=False)
            )

    async def all_registries(self) -> list[Registry]:
        return await self.harbor.get_registries(limit=10000)

    async def all_policies(self) -> list[ReplicationPolicy]:
        return await self.harbor.get_replication_policies(limit=10000)

    async def ensure_registry_endpoint(self, name: str, registry_url: str) -> int:
        registries = await self.all_registries()
        existing = next((registry for registry in registries if registry.name == name), None)
        description = marker_description(registry_url=registry_url)

        if existing is not None:
            if existing.id is None:
                raise RuntimeError(f"Harbor registry endpoint {name} has no ID")

            # Intentionally send the token every run so PAT rotations are copied
            # into Harbor on the next reconcile.
            await self.harbor.update_registry(
                existing.id,
                RegistryUpdate(
                    name=name,
                    description=description,
                    url=registry_url,
                    credential_type="basic",
                    access_key=self.gitlab_username,
                    access_secret=self.gitlab_token,
                    insecure=self.gitlab_registry_insecure,
                ),
            )
            LOG.info(
                "Updated Harbor registry endpoint %s and refreshed credentials", name
            )
            return existing.id

        registry = Registry(
            name=name,
            description=description,
            url=registry_url,
            type=self.registry_type,
            insecure=self.gitlab_registry_insecure,
            credential=RegistryCredential(
                type="basic",
                access_key=self.gitlab_username,
                access_secret=self.gitlab_token,
            ),
        )
        location = await self.harbor.create_registry(registry)
        registry_id = id_from_location(location)
        if registry_id is None:
            registries = await self.all_registries()
            created = next((registry for registry in registries if registry.name == name), None)
            if created is None or created.id is None:
                raise RuntimeError(
                    f"Created Harbor registry endpoint {name} but could not determine its ID"
                )
            registry_id = created.id

        LOG.info("Created Harbor registry endpoint %s (id=%s)", name, registry_id)
        return registry_id

    def build_desired_policies(
        self,
        projects: Iterable[DesiredProject],
        endpoint_ids: dict[str, int],
    ) -> dict[str, DesiredPolicy]:
        desired: dict[str, DesiredPolicy] = {}

        for project in projects:
            endpoint_id = endpoint_ids[project.source_registry_url]
            endpoint_name = self.endpoint_name(project.source_registry_url)
            common_description = marker_description(
                gitlab_project_id=project.gitlab_project_id,
                gitlab_project=project.gitlab_project_path,
                gitlab_topic=project.gitlab_topic,
                harbor_target=project.harbor_target,
            )

            # Two policies ensure both the project's root repository and GitLab
            # child repositories are matched across Harbor versions.
            root_name = project.policy_name("root")
            desired[root_name] = DesiredPolicy(
                name=root_name,
                description=f"{common_description}; scope=root",
                endpoint_name=endpoint_name,
                endpoint_id=endpoint_id,
                dest_namespace=project.harbor_target,
                flatten_count=project.flatten_count,
                name_filter=project.source_repository,
            )

            nested_name = project.policy_name("nested")
            desired[nested_name] = DesiredPolicy(
                name=nested_name,
                description=f"{common_description}; scope=nested",
                endpoint_name=endpoint_name,
                endpoint_id=endpoint_id,
                dest_namespace=project.harbor_target,
                flatten_count=project.flatten_count,
                name_filter=f"{project.source_repository}/**",
            )

        return desired

    def policy_model(self, desired: DesiredPolicy) -> ReplicationPolicy:
        return ReplicationPolicy(
            name=desired.name,
            description=desired.description,
            src_registry=Registry(id=desired.endpoint_id),
            dest_namespace=desired.dest_namespace,
            dest_namespace_replace_count=desired.flatten_count,
            trigger=ReplicationTrigger(
                type="scheduled",
                trigger_settings=ReplicationTriggerSettings(
                    cron=self.replication_cron
                ),
            ),
            filters=[
                ReplicationFilter(type="name", value=desired.name_filter),
                ReplicationFilter(type="resource", value="image"),
            ],
            replicate_deletion=False,
            override=True,
            enabled=True,
        )

    @staticmethod
    def policy_needs_update(
        current: ReplicationPolicy, wanted: ReplicationPolicy
    ) -> bool:
        def registry_id(policy: ReplicationPolicy) -> int | None:
            return policy.src_registry.id if policy.src_registry else None

        def trigger_tuple(policy: ReplicationPolicy) -> tuple[object, object]:
            trigger = policy.trigger
            settings = trigger.trigger_settings if trigger else None
            return (
                trigger.type if trigger else None,
                settings.cron if settings else None,
            )

        def filters_tuple(
            policy: ReplicationPolicy,
        ) -> tuple[tuple[object, object, object], ...]:
            return tuple(
                (filter_.type, filter_.value, filter_.decoration)
                for filter_ in (policy.filters or [])
            )

        return any(
            [
                current.name != wanted.name,
                current.description != wanted.description,
                registry_id(current) != registry_id(wanted),
                current.dest_namespace != wanted.dest_namespace,
                current.dest_namespace_replace_count
                != wanted.dest_namespace_replace_count,
                trigger_tuple(current) != trigger_tuple(wanted),
                filters_tuple(current) != filters_tuple(wanted),
                bool(current.replicate_deletion) != bool(wanted.replicate_deletion),
                bool(current.override) != bool(wanted.override),
                bool(current.enabled) != bool(wanted.enabled),
            ]
        )

    async def reconcile_policies(self, desired: dict[str, DesiredPolicy]) -> None:
        existing = await self.all_policies()
        by_name = {policy.name: policy for policy in existing if policy.name}

        for name, wanted in desired.items():
            model = self.policy_model(wanted)
            current = by_name.get(name)
            if current is None:
                location = await self.harbor.create_replication_policy(model)
                LOG.info("Created replication policy %s (%s)", name, location)
                continue

            if current.id is None:
                raise RuntimeError(f"Harbor replication policy {name} has no ID")
            if not self.policy_needs_update(current, model):
                LOG.info("Replication policy %s is already up to date", name)
                continue

            try:
                await self.harbor.update_replication_policy(current.id, model)
                LOG.info("Updated replication policy %s", name)
            except PreconditionFailed as exc:
                LOG.warning(
                    "Could not update replication policy %s because an execution "
                    "may be active; will retry next run: %s",
                    name,
                    exc,
                )

        desired_names = set(desired)
        stale = [
            policy
            for policy in existing
            if is_managed(policy.name, policy.description)
            and policy.name not in desired_names
        ]
        for policy in stale:
            if policy.id is None:
                LOG.warning(
                    "Cannot delete stale policy %s because it has no ID", policy.name
                )
                continue
            try:
                await self.harbor.delete_replication_policy(policy.id)
                LOG.info("Deleted stale managed replication policy %s", policy.name)
            except PreconditionFailed as exc:
                LOG.warning(
                    "Could not delete stale policy %s because Harbor reports a "
                    "precondition failure; it will be retried next run: %s",
                    policy.name,
                    exc,
                )

    async def cleanup_registry_endpoints(self, desired_names: set[str]) -> None:
        registries = await self.all_registries()
        for registry in registries:
            if not is_managed(registry.name, registry.description):
                continue
            if registry.name in desired_names:
                continue
            if registry.id is None:
                LOG.warning(
                    "Cannot delete stale registry %s because it has no ID", registry.name
                )
                continue
            try:
                await self.harbor.delete_registry(registry.id)
                LOG.info("Deleted stale managed registry endpoint %s", registry.name)
            except StatusError as exc:
                # Usually a stale replication policy is still executing.
                LOG.warning(
                    "Could not delete stale registry endpoint %s; it will be retried "
                    "next run: %s",
                    registry.name,
                    exc,
                )
