# forge-mirror

Creates pull mirrors (bare repositories) of **all** repositories visible to an
access token on a Git forge and updates existing mirrors. Supports **GitLab**
and **GitHub**. Ideal for periodic backups, e.g. via cron.

- Clones new repositories with `git clone --mirror`.
- Updates existing mirrors with `git remote update --prune`.
- Mirrors are stored under `<target-dir>/<namespace>/<repo>.git`.
- Archived repositories are skipped by default.
- Multiple repositories are processed in parallel (`--jobs`).

## Installation

Install the `forge-mirror` command with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/sniner/forge-mirror
```

Update later with `uv tool upgrade forge-mirror`. To pin a specific release,
append `@<tag>`, e.g. `git+https://github.com/sniner/forge-mirror@v0.2.0`.

## Usage

Select the forge with `--provider` (default: `gitlab`). Configuration is provided
via CLI argument or environment variable (arguments take precedence):

| Argument           | Environment variable          | Meaning                          |
| ------------------ | ----------------------------- | -------------------------------- |
| `--url`            | `GITLAB_URL` / `GITHUB_URL`   | Base URL of the forge API        |
| `--token`          | `GITLAB_TOKEN` / `GITHUB_TOKEN` | Access token                   |
| `-d, --target-dir` | `FORGE_MIRROR_DIR`            | Target directory for the mirrors |

The environment variable used for token and URL depends on the selected provider.
For GitHub, `--url` defaults to `https://api.github.com` (set it to your GitHub
Enterprise API endpoint, e.g. `https://ghe.example/api/v3`, when needed).

### GitLab

```sh
export GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
uv run forge-mirror \
    --provider gitlab \
    --url https://gitlab.example.local \
    --target-dir /srv/backup/gitlab \
    --jobs 4
```

The token needs the `read_api` scope (for listing) and, when cloning over HTTPS,
`read_repository`. In `--ssh` mode only `read_api` is required, since the Git
transfer uses your SSH key. Note that `/projects` only returns the projects
visible to the token, so use an admin account to mirror an entire instance.

### GitHub

```sh
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
# All repositories visible to the token (owner, collaborator, org member)
uv run forge-mirror --provider github -d /srv/backup/github

# Restrict to a single user or organization
uv run forge-mirror --provider github -d /srv/backup/github --owner my-org
```

The token needs read access to repository contents: a classic PAT with the
`repo` scope, or a fine-grained token with **Contents: Read** and
**Metadata: Read**. Without `--owner`, `GET /user/repos` lists everything the
token can see; with `--owner` only that user's or organization's repositories
are mirrored.

### Common options

```sh
# SSH instead of HTTPS (requires a configured SSH key)
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --ssh

# Include archived repositories as well
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --include-archived
```

Further options: `--timeout` (HTTP timeout in seconds, default 30),
`-v/--verbose` for DEBUG logging, `--help` for the full overview.

The exit code is `0` if all repositories were mirrored successfully, otherwise
the number of failed repositories (configuration and API errors return `1`).

## Development

```sh
uv sync                  # set up the project environment
uv run ruff format .
uv run ruff check .
uv run basedpyright
uv run pytest
```
