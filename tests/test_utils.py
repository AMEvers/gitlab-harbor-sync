from gitlab_harbor_sync.utils import (
    id_from_location,
    is_managed,
    marker_description,
    normalize_harbor_api_url,
    normalize_registry_url,
    split_registry_prefix,
)


def test_split_registry_prefix() -> None:
    url, repository = split_registry_prefix(
        "registry.gitlab.example.com/group/subgroup/project"
    )
    assert url == "https://registry.gitlab.example.com"
    assert repository == "group/subgroup/project"


def test_normalize_urls() -> None:
    assert normalize_registry_url("registry.example.com/") == "https://registry.example.com"
    assert normalize_harbor_api_url("https://harbor.example.com/") == (
        "https://harbor.example.com/api/v2.0"
    )
    assert normalize_harbor_api_url("https://harbor.example.com/api/v2.0") == (
        "https://harbor.example.com/api/v2.0"
    )


def test_managed_marker_requires_prefix_and_description() -> None:
    description = marker_description(registry_url="https://registry.example.com")
    assert is_managed("gitlab-harbor-sync-registry-abc", description)
    assert not is_managed("other-registry", description)
    assert not is_managed("gitlab-harbor-sync-registry-abc", "created-by=someone")


def test_id_from_location() -> None:
    assert id_from_location("/api/v2.0/registries/42") == 42
    assert id_from_location("https://harbor/api/v2.0/registries/42/") == 42
    assert id_from_location("") is None
