# Security

Do not open a public issue containing credentials, private registry URLs, tokens,
or other sensitive deployment details.

This project intentionally reads GitLab and Harbor credentials from environment
variables so Kubernetes Secrets or an external secret manager can supply them.
The example Secret contains placeholders only and is not included in the
Kustomize resource list.

When reporting a security issue in a real repository, use that repository's
private GitHub security-advisory workflow or the maintainer contact channel.
