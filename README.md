# forge-mirror

Creates pull mirrors (bare repositories) of **all** repositories visible to an
access token on a Git forge and updates existing mirrors. Supports **GitLab**,
**GitHub** and **Forgejo**. Ideal for periodic backups, e.g. via cron.

- Clones new repositories with `git clone --mirror`.
- Updates existing mirrors with `git remote update --prune`.
- Mirrors are stored under `<target-dir>/<namespace>/<repo>.git`.
- The token is passed to git on each run and never stored in a mirror, so a new
  token applies to all existing mirrors. A credential helper in your git
  configuration, such as the macOS keychain, does not save it either.
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

A run mirrors exactly one forge, and each of the four settings is given either as
a CLI argument or as an environment variable (arguments take precedence):

| Argument           | Environment variable    | Meaning                          |
| ------------------ | ----------------------- | -------------------------------- |
| `--provider`       | `FORGE_MIRROR_PROVIDER` | Forge to mirror from             |
| `--url`            | `FORGE_MIRROR_URL`      | Base URL of the forge API        |
| `--token`          | `FORGE_MIRROR_TOKEN`    | Access token                     |
| `-d, --target-dir` | `FORGE_MIRROR_DIR`      | Target directory for the mirrors |

### Which forge

`--provider` defaults to `auto`, which asks GitLab, GitHub and Forgejo in turn
for a single page of repositories — each with that forge's own authentication
scheme, on its own listing endpoint. The others are being asked for a route they
do not serve and answer `404`, so the one that returns a list is the forge that
is there. That makes the answer a guarantee rather than a guess: whatever
answered can also list the repositories, so a mistyped URL or a token missing a
scope is reported before the first clone instead of halfway through the run.

Naming the forge with `--provider gitlab|github|forgejo` skips that request, and
for GitHub it supplies the default URL `https://api.github.com`. The other two
are self-hosted and have no default, so they need `--url`. A bare
`https://github.com` is rewritten to `https://api.github.com`, since github.com
serves its API from a separate host — unlike Enterprise, which uses `/api/v3` on
the web host and is given in full as `https://ghe.example/api/v3`.

To see what autodetection makes of a URL without mirroring anything, add
`--list` (below).

### GitLab

```sh
export FORGE_MIRROR_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
uv run forge-mirror \
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
export FORGE_MIRROR_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
# All repositories visible to the token (owner, collaborator, org member).
# --provider github is what supplies the default URL https://api.github.com
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
export FORGE_MIRROR_TOKEN=xxxxxxxxxxxxxxxxxxxx
uv run forge-mirror \
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

### Listing without mirroring

`--list` prints the repositories a run would take, one per line, and stops
there. Nothing is cloned, so `--target-dir` is not needed:

```sh
uv run forge-mirror --url https://gitlab.example.local --list
```

The names go to standard output and everything the run has to say about itself
to the log, so the list can be counted or filtered:

```sh
forge-mirror --url https://gitlab.example.local --list | wc -l
```

This is the cheapest way to check that autodetection lands on the right forge
and that the token carries the scopes it needs, before a first run pulls
gigabytes. `--include-archived` widens the list exactly as it widens a run;
`--prune` is refused alongside it, since a listing has nothing to delete.

`--list` answers what the forge has. What a run would *do* with it is the
question `--dry-run` answers, and the two are refused together.

### Trying a run without making it

`--dry-run` reports what a run would clone, update and — together with
`--prune` — delete, and does none of it:

```sh
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --dry-run
```

```
INFO Dry run: nothing is cloned, updated or deleted
INFO 71 repositories: 3 to clone, 68 to update (-v names the updates too)
INFO Would clone group/newcomer
WARNING 1 mirror(s) have no repository on the forge; add --prune to see them as
WARNING   deletions, and drop --dry-run to carry them out:
WARNING   /srv/backup/old-group/tools.git
INFO Dry run finished, nothing was touched
```

Repositories that would only be updated are the unremarkable majority of a
settled mirror directory, so they are counted rather than listed; `-v` names
them as well. `--dry-run --prune` is the pairing worth having before a real
prune: it prints exactly the mirrors that deletion would take, and says so when
`--prune-limit` would cancel the whole thing.

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
# SSH instead of HTTPS (requires a configured SSH key); existing mirrors are
# switched to SSH as well, and back to HTTPS on a run without --ssh
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --ssh

# Include archived repositories as well
uv run forge-mirror --url https://gitlab.example.local -d /srv/backup --include-archived
```

Further options: `--timeout` (HTTP timeout in seconds, default 30),
`-v/--verbose` for DEBUG logging, `--help` for the full overview.

A clone or update over HTTPS that receives less than 1 KB/s for two minutes is
aborted and counts as failed, so a stalled connection does not hang the run.

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
