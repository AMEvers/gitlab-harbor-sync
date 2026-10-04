from gitlab_harbor_sync.controller import SyncController
from gitlab_harbor_sync.models import DesiredProject


def make_controller() -> SyncController:
    controller = object.__new__(SyncController)
    controller.registry_type = "docker-registry"
    controller.replication_cron = "0 0 * * * *"
    return controller


def make_project() -> DesiredProject:
    return DesiredProject(
        gitlab_project_id=123,
        gitlab_project_name="widget",
        gitlab_project_path="group/subgroup/widget",
        gitlab_topic="harbor-prod-sync",
        source_registry_url="https://registry.gitlab.example.com",
        source_repository="group/subgroup/widget",
        harbor_target="prod/apps",
        harbor_project="prod",
    )


def test_build_desired_policies_creates_root_and_nested_rules() -> None:
    controller = make_controller()
    project = make_project()
    policies = controller.build_desired_policies(
        [project], {project.source_registry_url: 7}
    )

    assert len(policies) == 2
    filters = {policy.name_filter for policy in policies.values()}
    assert filters == {
        "group/subgroup/widget",
        "group/subgroup/widget/**",
    }
    assert {policy.flatten_count for policy in policies.values()} == {2}
    assert {policy.dest_namespace for policy in policies.values()} == {"prod/apps"}
