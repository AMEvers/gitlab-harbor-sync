from gitlab_harbor_sync.models import DesiredProject


def project(repository: str = "group/subgroup/widget") -> DesiredProject:
    return DesiredProject(
        gitlab_project_id=123,
        gitlab_project_name="widget",
        gitlab_project_path="group/subgroup/widget",
        gitlab_topic="harbor-prod-sync",
        source_registry_url="https://registry.gitlab.example.com",
        source_repository=repository,
        harbor_target="prod/apps",
        harbor_project="prod",
    )


def test_flatten_count_removes_gitlab_namespace_but_keeps_project() -> None:
    assert project().flatten_count == 2


def test_policy_name_is_stable_and_scoped() -> None:
    value = project()
    assert value.policy_name("root").startswith("gitlab-harbor-sync-p123-")
    assert value.policy_name("root").endswith("-root")
    assert value.policy_name("nested").endswith("-nested")
