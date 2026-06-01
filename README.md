# gitlab-mirror

Creates pull mirrors (bare repositories) of **all** projects visible to an
access token on a GitLab instance and updates existing mirrors. Ideal for
periodic backups, e.g. via cron.

- Clones new projects with `git clone --mirror`.
- Updates existing mirrors with `git remote update --prune`.
- Mirrors are stored under `<target-dir>/<group>/<project>.git`.
- Archived projects are skipped by default.
- Multiple projects are processed in parallel (`--jobs`).

## Installation

```sh
uv sync
```

## Usage

Configuration is provided via CLI argument or environment variable (arguments
take precedence):

| Argument           | Environment variable | Meaning                          |
| ------------------ | -------------------- | -------------------------------- |
| `--gitlab-url`     | `GITLAB_URL`         | Base URL of the GitLab instance  |
| `--token`          | `GITLAB_TOKEN`       | Personal/project access token    |
| `-d, --target-dir` | `GITLAB_MIRROR_DIR`  | Target directory for the mirrors |

The token needs the `read_api` scope (for listing) and, when cloning over HTTPS,
`read_repository`. In `--ssh` mode only `read_api` is required, since the Git
transfer uses your SSH key. Note that `/projects` only returns the projects
visible to the token, so use an admin account to mirror an entire instance.

```sh
# HTTPS with token (default), token from the environment
export GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
uv run gitlab-mirror \
    --gitlab-url https://gitlab.example.local \
    --target-dir /srv/backup/gitlab \
    --jobs 4

# SSH instead of HTTPS (requires a configured SSH key)
uv run gitlab-mirror -d /srv/backup/gitlab --ssh

# Include archived projects as well
uv run gitlab-mirror -d /srv/backup/gitlab --include-archived
```

Further options: `--timeout` (HTTP timeout in seconds, default 30),
`-v/--verbose` for DEBUG logging, `--help` for the full overview.

The exit code is `0` if all projects were mirrored successfully, otherwise the
number of failed projects (configuration and API errors return `1`).

## Development

```sh
uv run ruff format .
uv run ruff check .
uv run basedpyright
uv run pytest
```
