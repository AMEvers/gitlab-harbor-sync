# Kubernetes deployment

The `base` directory is a Kustomize-ready deployment. The example Secret is not
included in `kustomization.yaml` so credentials are not accidentally committed.

## 1. Create the Secret

```bash
kubectl apply -f deploy/kubernetes/base/namespace.yaml
kubectl -n harbor-sync create secret generic gitlab-harbor-sync-secrets \
  --from-literal=GITLAB_ACCESS_TOKEN='<token>' \
  --from-literal=HARBOR_USERNAME='<user>' \
  --from-literal=HARBOR_PASSWORD='<password>'
```

Or manage the Secret through External Secrets, Sealed Secrets, SOPS, or your
cluster's existing secret-management mechanism.

## 2. Customize endpoints and image

Edit `base/cronjob.yaml` or create an overlay for:

- `GITLAB_URL`
- `HARBOR_URL`
- the container image
- the CronJob schedule
- optional TLS/adapter settings

Edit `base/configmap.yaml` with the desired topic mappings.

## 3. Deploy

```bash
kubectl apply -k deploy/kubernetes/base
```

No ServiceAccount permissions or Kubernetes RBAC are required because the Job
only reads its mounted ConfigMap/Secret and calls the GitLab and Harbor APIs.
