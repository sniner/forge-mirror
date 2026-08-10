# forge-mirror

Creates pull mirrors (bare repositories) of **all** repositories visible to an
access token on a Git forge and updates existing mirrors. Supports **GitLab**,
**GitHub** and **Forgejo**. Ideal for periodic backups, e.g. via cron.

- Clones new repositories with `git clone --mirror`.
- Updates existing mirrors with `git remote update --prune`.
- Mirrors are stored under `<target-dir>/<namespace>/<repo>.git`.
- Archived repositories are skipped by default.
- Mirrors whose repository is gone from the forge are reported, and deleted on request (`--prune`).
- Multiple repositories are processed in parallel (`--jobs`).

## Installation

Install the `forge-mirror` command with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/sniner/forge-mirror
```

Update later with `uv tool upgrade forge-mirror`. To pin a specific release,
append `@<tag>`, e.g. `git+https://github.com/sniner/forge-mirror@v0.2.0`.

## Usage

Select the forge with `--provider` (`gitlab`, `github` or `forgejo`, default:
`gitlab`). Configuration is provided via CLI argument or environment variable
(arguments take precedence):

| Argument           | Environment variable                            | Meaning                          |
| ------------------ | ----------------------------------------------- | -------------------------------- |
| `--url`            | `GITLAB_URL` / `GITHUB_URL` / `FORGEJO_URL`     | Base URL of the forge API        |
| `--token`          | `GITLAB_TOKEN` / `GITHUB_TOKEN` / `FORGEJO_TOKEN` | Access token                   |
| `-d, --target-dir` | `FORGE_MIRROR_DIR`                              | Target directory for the mirrors |

The environment variable used for token and URL depends on the selected provider.
For GitHub, `--url` defaults to `https://api.github.com` (set it to your GitHub
Enterprise API endpoint, e.g. `https://ghe.example/api/v3`, when needed). A bare
`https://github.com` is rewritten to `https://api.github.com`, since github.com
serves its API from a separate host — unlike Enterprise, which uses `/api/v3` on
the web host.

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
transfer uses your SSH key. Listing uses `membership=true`, so only projects the
token's user belongs to are mirrored — on a self-hosted instance use an admin
account to cover everything; on `gitlab.com` this avoids pulling in every public
project on the platform.

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

### Forgejo

```sh
export FORGEJO_TOKEN=xxxxxxxxxxxxxxxxxxxx
uv run forge-mirror \
    --provider forgejo \
    --url https://forgejo.example.local \
    --target-dir /srv/backup/forgejo
```

Forgejo is self-hosted, so `--url` has no default; point it at the instance
itself, the API path `/api/v1` is appended.

The token needs **two** scopes, both at **Read** level: **`user`** and
**`repository`**. The `user` scope is the counter-intuitive one — Forgejo
derives the required scope from the route group, and the listing endpoint is
`/api/v1/user/repos`, so reaching it takes `read:user` on top of the
`read:repository` that covers the repositories themselves and the Git transfer
over HTTPS. Tick only one of them and the API answers `403` naming the other:

```
token does not have at least one of required scope(s): [read:user]
```

None of the remaining categories (`admin`, `organization`, `package`, `misc`, …)
is required; organisation repositories are covered by `read:repository`. A token
with no scope at all is refused even for public repositories. In `--ssh` mode
the Git transfer uses your SSH key, but the listing still needs both scopes.
Listing uses
`/api/v1/user/repos`, which returns the repositories the token's user owns plus
those they reach as a collaborator or through an organisation team — public
repositories of *other* users on the instance are not pulled in.

`--owner` is not available for Forgejo. The same API also serves **Gitea**,
which this provider has not been tested against.

### Stale mirrors

When a repository is moved to a different group, its mirror stays behind at the
old path and the repository is cloned again under the new one. Every run
therefore lists the mirrors that no longer have a repository on the forge:

```
WARNING 2 mirror(s) have no repository on the forge, pass --prune to delete them:
WARNING   /srv/backup/old-group/tools.git
WARNING   /srv/backup/retired/prototype.git
```

Deleting them is opt-in, since a mirror is usually the last copy of a repository:

```sh
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --prune
```

`--prune` deletes the listed mirrors and the namespace directories they leave
empty. Deletion never happens when it cannot be justified by a complete listing:

- An API error aborts the run before anything is deleted — the listing is read
  in full before the first mirror is touched, so a connection lost halfway
  through pagination can never be mistaken for deleted repositories.
- An empty listing (typically a token that lost its access) deletes nothing.
- Archived repositories are kept, whether or not `--include-archived` is set.
- More candidates than `--prune-limit` (default 10) cancels the deletion
  completely — nothing is removed and the run exits non-zero. A jump like that
  is usually a token that lost access to a group rather than a group that was
  really deleted. Check the listed paths, then raise the limit for that run;
  `0` turns the check off.
- Only directories that are actually bare repositories are removed. Symlinks
  and the `.git` directory of a working copy are left alone.

Give each forge its own `--target-dir`: mirrors of a *different* forge below the
same directory have no counterpart in the listing and count as stale. With
`--owner`, only that owner's subdirectory is examined.

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
the number of repositories that failed to mirror or that `--prune` was unable to
clean up (configuration and API errors return `1`).

## Development

```sh
uv sync                  # set up the project environment
uv run ruff format .
uv run ruff check .
uv run basedpyright
uv run pytest
```
