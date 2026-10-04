# gitlab-harbor-sync

A small reconciliation controller intended to run as a Kubernetes CronJob. It
finds GitLab projects by project topic and maintains Harbor pull-replication
endpoints and policies for those projects.

## What it does

Given this configuration:

```yaml
- git-project-tag: harbor-prod-sync
  harbor-target: prod

- git-project-tag: harbor-platform-sync
  harbor-target: platform/gitlab
```

and a GitLab project whose registry prefix is:

```text
registry.gitlab.example.com/team/widgets
```

the first mapping produces a Harbor destination rooted at:

```text
harbor.example.com/prod/widgets
```

A nested GitLab repository such as `team/widgets/backend` maps to
`prod/widgets/backend`.

The reconciler:

1. Authenticates to GitLab with a personal access token.
2. Finds projects matching every configured `git-project-tag` topic.
3. Creates the destination Harbor project when it does not exist.
4. Creates or updates a Harbor registry endpoint for the GitLab container
   registry.
5. Refreshes the endpoint's GitLab PAT on every run so token rotation propagates
   to Harbor.
6. Creates root and nested pull-replication policies for every matched project.
7. Removes stale managed replication policies when mappings/topics/projects are
   removed.
8. Removes managed registry endpoints once no desired policy uses them.

Harbor projects are intentionally **not** deleted during cleanup because deleting
a project may delete replicated artifacts.

## Repository layout

```text
.
├── .github/
│   ├── dependabot.yml
│   └── workflows/
│       ├── ci.yml
│       └── release-container.yml
├── deploy/kubernetes/
│   ├── README.md
│   └── base/
│       ├── configmap.yaml
│       ├── cronjob.yaml
│       ├── kustomization.yaml
│       ├── namespace.yaml
│       └── secret.example.yaml
├── examples/targets.yaml
├── schema/targets.schema.json
├── src/gitlab_harbor_sync/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── constants.py
│   ├── controller.py
│   ├── models.py
│   └── utils.py
├── tests/
├── Dockerfile
├── Makefile
├── pyproject.toml
└── README.md
```

## Configuration

`targets.yaml` is normally a YAML list:

```yaml
- git-project-tag: harbor-prod-sync
  harbor-target: prod
- git-project-tag: another-topic
  harbor-target: platform/gitlab
```

A wrapped form is also accepted:

```yaml
targets:
  - git-project-tag: harbor-prod-sync
    harbor-target: prod
```

`git-project-tag` is treated as a GitLab **project topic**. `harbor-target` may
contain a subpath. Only its first component is the Harbor project name. For
example, `platform/gitlab` creates/uses the Harbor project `platform` and places
repositories below `platform/gitlab/...`.

## Environment variables

### Required

| Variable | Purpose |
| --- | --- |
| `GITLAB_URL` | GitLab base URL, for example `https://gitlab.example.com` |
| `GITLAB_ACCESS_TOKEN` | PAT used for GitLab API access and source-registry authentication |
| `HARBOR_URL` | Harbor base URL; `/api/v2.0` is added automatically when omitted |
| `HARBOR_USERNAME` | Harbor API username |
| `HARBOR_PASSWORD` | Harbor API password |

### Optional

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONFIG_PATH` | `/config/targets.yaml` | Mounted YAML configuration |
| `GITLAB_REGISTRY_URL` | derived from each project | Override the GitLab registry URL |
| `HARBOR_REGISTRY_TYPE` | auto | Force `gitlab` or `docker-registry` |
| `HARBOR_REPLICATION_CRON` | `0 0 * * * *` | Harbor six-field replication schedule |
| `GITLAB_VERIFY_TLS` | `true` | Verify GitLab API TLS |
| `GITLAB_REGISTRY_INSECURE` | `false` | Tell Harbor not to verify GitLab registry TLS |
| `HARBOR_VERIFY_TLS` | `true` | Verify Harbor API TLS |
| `LOG_LEVEL` | `INFO` | Python log level |

For a private CA, prefer mounting the CA bundle and configuring the process trust
store rather than disabling TLS verification.

## GitLab token permissions

The PAT must be able to query the GitLab API/project metadata and pull from every
matched project registry. In a typical GitLab deployment this means API-read
access plus container-registry read access. The PAT owner also needs access to
the projects being discovered.

The reconciler authenticates to the GitLab registry with the authenticated
GitLab username and the PAT as the password.

## Harbor permissions

The Harbor account must be able to:

- list/create/update/delete registry endpoints;
- list/create/update/delete replication policies;
- read projects; and
- create destination projects.

## Managed-object ownership

Cleanup is deliberately scoped. The controller only deletes registry endpoints
or replication policies that have both:

- a name beginning with `gitlab-harbor-sync-`; and
- a description beginning with `managed-by=gitlab-harbor-sync`.

This prevents an empty or changed ConfigMap from deleting unrelated Harbor
configuration.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
make check
```

To run the package directly:

```bash
export GITLAB_URL=https://gitlab.example.com
export GITLAB_ACCESS_TOKEN=...
export HARBOR_URL=https://harbor.example.com
export HARBOR_USERNAME=admin
export HARBOR_PASSWORD=...
export CONFIG_PATH="$PWD/examples/targets.yaml"

gitlab-harbor-sync
```

## Container

Build locally:

```bash
docker build -t gitlab-harbor-sync:dev .
```

Example run:

```bash
docker run --rm \
  -e GITLAB_URL=https://gitlab.example.com \
  -e GITLAB_ACCESS_TOKEN \
  -e HARBOR_URL=https://harbor.example.com \
  -e HARBOR_USERNAME \
  -e HARBOR_PASSWORD \
  -v "$PWD/examples:/config:ro" \
  gitlab-harbor-sync:dev
```

## Kubernetes

The repository includes a Kustomize-ready base under `deploy/kubernetes/base`.
The example Secret is intentionally excluded from the Kustomization.

```bash
kubectl apply -f deploy/kubernetes/base/namespace.yaml
kubectl -n harbor-sync create secret generic gitlab-harbor-sync-secrets \
  --from-literal=GITLAB_ACCESS_TOKEN='<token>' \
  --from-literal=HARBOR_USERNAME='<user>' \
  --from-literal=HARBOR_PASSWORD='<password>'

kubectl apply -k deploy/kubernetes/base
```

Replace `ghcr.io/OWNER/gitlab-harbor-sync:latest` in the CronJob with the image
published by your repository or internal registry.

No Kubernetes RBAC is required because the Job does not call the Kubernetes API.
It only reads the mounted configuration and credentials.

## CI and releases

`.github/workflows/ci.yml` runs formatting checks, linting, unit tests, and a
container build on pushes to `main` and pull requests.

`.github/workflows/release-container.yml` publishes the image to GitHub Container
Registry when a `v*` tag is pushed. For example:

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub automatically supplies `GITHUB_TOKEN` to that workflow; no registry
password needs to be stored for GHCR publishing.

## Failure and retry behavior

If Harbor rejects a policy update/delete because a replication execution is
active, the reconciler logs the precondition failure and leaves the object for a
future CronJob run. Kubernetes Job failures return a non-zero exit code so the
CronJob's retry policy can handle transient failures.

## License

No open-source license is included in this generated project. Add the license
appropriate for your organization before publishing the repository if needed.
