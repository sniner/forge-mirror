# forge-mirror

Creates and updates bare mirrors of all repositories an access token can see on a
Git forge. Supports **GitLab**, **GitHub** and **Forgejo**. Meant for periodic
backups, for example from cron.

- New repositories are cloned with `git clone --mirror`, existing mirrors are
  updated with `git remote update --prune`.
- Mirrors are stored under `<target-dir>/<namespace>/<repo>.git`.
- The token is passed to git on each run and never stored in a mirror, so a new
  token applies to all existing mirrors. A credential helper in your git
  configuration, such as the macOS keychain, does not save it either.
- Archived repositories are skipped by default.
- Mirrors whose repository no longer exists on the forge are reported, and
  deleted with `--prune`.
- Several repositories are processed in parallel (`--jobs`).

## Installation

Install the `forge-mirror` command with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/sniner/forge-mirror
```

Update it with `uv tool upgrade forge-mirror`. To install a specific release,
append `@<tag>`, e.g. `git+https://github.com/sniner/forge-mirror@v0.2.0`.

## Usage

A run mirrors one forge. Each of the four settings can be given as an option or
as an environment variable; the option takes precedence:

| Argument           | Environment variable    | Meaning                          |
| ------------------ | ----------------------- | -------------------------------- |
| `--provider`       | `FORGE_MIRROR_PROVIDER` | Forge to mirror from             |
| `--url`            | `FORGE_MIRROR_URL`      | Base URL of the forge API        |
| `--token`          | `FORGE_MIRROR_TOKEN`    | Access token                     |
| `-d, --target-dir` | `FORGE_MIRROR_DIR`      | Target directory for the mirrors |

### Detecting the forge

With the default `--provider auto`, forge-mirror requests one page of the
repository listing from the GitLab, GitHub and Forgejo API in turn, each with
that forge's authentication. The forges that are not there return `404`, and the
first one that returns a list is used. Since this request already lists
repositories with the token, a wrong URL or a token without the required scopes
is reported before the first clone.

`--provider gitlab|github|forgejo` skips the detection. For GitHub it also sets
the default URL `https://api.github.com`. GitLab and Forgejo are self-hosted and
need `--url`. A plain `https://github.com` is changed to `https://api.github.com`,
because github.com serves its API from a separate host. GitHub Enterprise serves
it under `/api/v3` on the web host; give that URL in full, e.g.
`https://ghe.example/api/v3`.

To see which forge is detected without mirroring anything, use `--list` (see
below).

### GitLab

```sh
export FORGE_MIRROR_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
uv run forge-mirror \
    --url https://gitlab.example.local \
    --target-dir /srv/backup/gitlab \
    --jobs 4
```

The token needs the `read_api` scope for the listing and `read_repository` for
cloning over HTTPS. With `--ssh` only `read_api` is needed, because git uses your
SSH key. Only projects the token's user is a member of are mirrored. On a
self-hosted instance, use the token of an admin account to get all projects; on
`gitlab.com` this keeps out the public projects of all other users.

### GitHub

```sh
export FORGE_MIRROR_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
# All repositories the token can see (owner, collaborator, organization member).
# --provider github sets the default URL https://api.github.com
uv run forge-mirror --provider github -d /srv/backup/github

# Only the repositories of one user or organization
uv run forge-mirror --provider github -d /srv/backup/github --owner my-org
```

The token needs read access to repository contents: a classic token with the
`repo` scope, or a fine-grained token with **Contents: Read** and
**Metadata: Read**.

### Forgejo

```sh
export FORGE_MIRROR_TOKEN=xxxxxxxxxxxxxxxxxxxx
uv run forge-mirror \
    --url https://forgejo.example.local \
    --target-dir /srv/backup/forgejo
```

Forgejo is self-hosted, so `--url` is required. Give the URL of the instance;
forge-mirror appends the API path `/api/v1`.

The token needs two scopes, both at **Read** level: **`user`** and
**`repository`**. `repository` covers the repositories and git over HTTPS. `user`
is needed because Forgejo derives the required scope from the API path, and the
listing is at `/api/v1/user/repos`. With only one of the two, the API returns
`403` and names the missing one:

```
token does not have at least one of required scope(s): [read:user]
```

No other scope is needed; organization repositories are covered by `repository`.
A token without any scope is rejected even for public repositories. With
`--ssh`, git uses your SSH key, but the listing still needs both scopes.

The listing contains the repositories the token's user owns and those the user
can access as a collaborator or through an organization team. Public
repositories of other users on the instance are not included.

`--owner` is not available for Forgejo. Gitea serves the same API, but has not
been tested.

### Listing without mirroring

`--list` prints the repositories a run would mirror, one per line, and exits.
Nothing is cloned, so `--target-dir` is not needed:

```sh
uv run forge-mirror --url https://gitlab.example.local --list
```

The names go to standard output and the log to standard error, so the list can
be counted or filtered:

```sh
forge-mirror --url https://gitlab.example.local --list | wc -l
```

Use it to check the detected forge and the token's scopes before a first run
downloads everything. `--include-archived` adds the archived repositories to the
list, as it does for a run. `--list` cannot be combined with `--prune` or
`--dry-run`.

### Dry run

`--dry-run` shows what a run would clone, update and, with `--prune`, delete,
and changes nothing:

```sh
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --dry-run
```

```
INFO Dry run: nothing is cloned, updated or deleted
INFO 71 repositories: 3 to clone, 68 to update (-v lists the updates)
INFO Would clone group/newcomer
WARNING 1 mirror(s) have no repository on the forge; with --prune they would be deleted:
WARNING   /srv/backup/old-group/tools.git
INFO Dry run finished, nothing was changed
```

Repositories that would only be updated are counted, not listed; `-v` lists them
too. Before a real prune, run `--dry-run --prune`: it lists the mirrors that
would be deleted, and says so when `--prune-limit` would stop the deletion.

### Stale mirrors

When a repository is moved to another group, the mirror at the old path remains
and the repository is cloned again under the new path. Every run lists the
mirrors that no longer have a repository on the forge:

```
WARNING 2 mirror(s) have no repository on the forge, pass --prune to delete them:
WARNING   /srv/backup/old-group/tools.git
WARNING   /srv/backup/retired/prototype.git
```

They are deleted only with `--prune`, because a mirror may be the last copy of a
repository:

```sh
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --prune
```

`--prune` deletes the listed mirrors and the namespace directories left empty.
It deletes nothing unless the listing is complete:

- An API error aborts the run before anything is deleted. The listing is read in
  full before the first mirror is changed, so an error during pagination cannot
  make repositories look deleted.
- An empty listing, usually caused by a token that lost its access, deletes
  nothing.
- Mirrors of archived repositories are kept, with or without
  `--include-archived`.
- If more mirrors would be deleted than `--prune-limit` allows (default 10),
  nothing is deleted and the run exits non-zero. That many usually means the
  token lost access to a group. Check the listed paths, then run again with a
  higher limit; `0` disables the check.
- Only bare repositories are deleted. Symlinks and the `.git` directory of a
  working copy are left alone.

Use a separate `--target-dir` for each forge: mirrors of another forge in the
same directory are not in the listing and count as stale. With `--owner`, only
that owner's subdirectory is checked.

### Common options

```sh
# SSH instead of HTTPS (requires a configured SSH key); existing mirrors are
# switched to SSH as well, and back to HTTPS on a run without --ssh
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --ssh

# Include archived repositories
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --include-archived
```

Further options: `--timeout` (seconds to wait for a response from the forge
API, default 30), `-v/--verbose` for DEBUG logging, `--help` for the full
overview.

A forge that does not accept a connection within 10 seconds, for example because
it is only reachable through a VPN that is not connected, is reported as
unreachable and the run exits with `1`. A `--timeout` below 10 seconds also
shortens this wait.

A clone or update over HTTPS that receives less than 1 KB/s for two minutes is
aborted and counts as failed, so a stalled connection does not hang the run.

The exit code is `0` if all repositories were mirrored, otherwise the number of
repositories that could not be mirrored or that `--prune` could not delete (at
most 125). Configuration and API errors exit with `1`.

## Development

```sh
uv sync                  # set up the project environment
uv run ruff format .
uv run ruff check .
uv run basedpyright
uv run pytest
```
