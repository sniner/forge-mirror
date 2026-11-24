# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Fixed

- **Unreachable forge**: a run stops after 10 seconds without a connection, for example when the
  forge is only reachable through a VPN that is not connected, and reports the host as
  unreachable. Before, it waited the full `--timeout` of 30 seconds, and during forge detection
  without any output. Detection now logs the URL when it starts

## [0.6.0] - 2026-11-20

### Fixed

- **Updates** of existing mirrors use the token of the current run. git used the token stored in
  the mirror when it was cloned, so once that token had expired or was replaced, every private
  repository failed with `Authentication failed`
- **Stalled transfers** over HTTPS no longer hang the run: a clone or update that receives less
  than 1 KB/s for two minutes is aborted and reported as a git error

### Changed

- **Token storage**: the token is no longer written into the remote URL of a mirror, and a
  credential helper in your git configuration (such as the macOS keychain) no longer saves a copy.
  Mirrors cloned by an earlier version have the token removed from their URL on their next update.
  A token that a helper has already saved stays there until you delete it
- **`--ssh`** also switches existing mirrors to SSH, and back to HTTPS on a run without it

## [0.5.0] - 2026-08-10

### Breaking changes

- **Environment variables** are no longer one set per forge: `FORGE_MIRROR_URL` and
  `FORGE_MIRROR_TOKEN` replace `GITLAB_URL`/`GITHUB_URL`/`FORGEJO_URL` and
  `GITLAB_TOKEN`/`GITHUB_TOKEN`/`FORGEJO_TOKEN`, which are no longer read — rename them in the cron
  jobs and unit files that call the tool. A run mirrors one forge, so one URL and one token were
  always all it needed. `FORGE_MIRROR_DIR` is unchanged

### Added

- **Autodetection** of the forge: `--provider` now defaults to `auto`, which asks GitLab, GitHub
  and Forgejo in turn for one page of repositories, each with its own authentication scheme and its
  own listing endpoint. The forge that answers is the one that will work, so a wrong URL or a token
  without the necessary scopes is reported before the first clone instead of surfacing later as a
  bare `404`
- **`FORGE_MIRROR_PROVIDER`** names the forge from the environment; `--provider auto` overrides it
  back to autodetection for a single run
- **`--list`** prints the repositories a run would take, one per line, and stops there; nothing is
  cloned, so `--target-dir` is not needed. The names go to standard output and the reporting to the
  log, so the list can be piped into `wc -l` or a filter. `--prune` is refused alongside it
- **`--dry-run`** reports what a run would clone, update and — together with `--prune` — delete,
  and does none of it. Repositories that would only be updated are counted rather than listed
  (`-v` names them as well), and `--dry-run --prune` shows exactly which mirrors a deletion would
  take, `--prune-limit` cancelling it included

### Changed

- **`--provider`** defaults to `auto` instead of `gitlab`; name the forge explicitly to skip the
  detection request
- **Missing options** are reported with the environment variable that would have supplied them
- **Request logging** by the HTTP library has moved behind `-v`, so a normal run reports what it is
  doing rather than one line per API request

## [0.4.1] - 2026-08-10

### Fixed

- **API errors** now quote what the forge answered instead of only the status code, so a rejected
  token names the scope it is missing rather than pointing at an HTTP reference page; a reply from
  a reverse proxy in front of the forge is passed through as text and is recognisable as such
- **Forgejo** the documented token scopes were wrong: the listing needs `read:user` **and**
  `read:repository`, because Forgejo derives the required scope from the route group and the
  endpoint sits under `/api/v1/user/`

Forgejo support has since been verified against a live instance — listing, authentication, Link
header pagination across 20 pages, and cloning over HTTPS.

## [0.4.0] - 2026-08-10

### Added

- **Forgejo** support via `--provider forgejo`, using the Forgejo REST API v1 at `/api/v1` on the
  instance given with `--url`; the token needs the `read:repository` scope
- **`FORGEJO_TOKEN`** and **`FORGEJO_URL`** environment variables

Listing mirrors what the token's user owns plus what they reach as a collaborator or through an
organisation team. `--owner` remains GitHub-only. The provider has been written against the
documented API and is covered by tests, but has not been run against a live instance yet.

## [0.3.0] - 2026-08-10

### Added

- **`--prune`** deletes mirrors whose repository no longer exists on the forge, together with the
  namespace directories they leave empty — the case where a repository was moved to another group
  and its mirror stayed behind at the old path
- **`--prune-limit`** cancels the deletion completely when more candidates than the limit turn up
  (default 10, `0` turns the check off); such a jump is usually a token that lost access to a group
  rather than repositories that are really gone

### Changed

- **Stale mirrors** are listed at the end of every run, so a plain run shows what `--prune` would
  delete; deletion only ever happens with `--prune`, never on an API error or an empty listing, and
  archived repositories are kept regardless of `--include-archived`
- **Exit code** now also counts stale mirrors that `--prune` was asked to remove but could not

## [0.2.1] - 2026-06-01

### Fixed

- **GitLab** listing now restricts to projects the token's user is a member of (`membership=true`);
  on `gitlab.com` it previously paginated through every public project on the platform
- **GitHub** a bare `https://github.com` URL is rewritten to `https://api.github.com`, avoiding a
  `404` from the web host (Enterprise endpoints under `/api/v3` are unaffected)

## [0.2.0] - 2026-06-01

### Breaking changes

- **Command** is now `forge-mirror` instead of `gitlab-mirror`; reinstall the tool under the new
  name (`uv tool install git+https://github.com/sniner/forge-mirror`)
- **`--gitlab-url`** has been replaced by `--url`; GitLab remains the default provider, so existing
  invocations only need the flag renamed
- **`GITLAB_MIRROR_DIR`** environment variable is now `FORGE_MIRROR_DIR`

### Added

- **GitHub** support via `--provider github`; mirrors all repositories visible to the token, or a
  single user/organization with `--owner`
- **`--provider`** to choose the forge (`gitlab` or `github`, default `gitlab`)
- **`GITHUB_TOKEN`** and **`GITHUB_URL`** environment variables; for GitHub the API URL defaults to
  `https://api.github.com`

### Changed

- **Mirroring** is now provider-neutral; repository listing, authentication and clone-URL handling
  are abstracted behind a provider interface

## [0.1.0] - 2026-06-01

### Added

- **`gitlab-mirror`** initial release: mirror all GitLab projects visible to an access token as bare
  repositories, cloning new ones and updating existing ones with prune
- **`--jobs`** for parallel mirroring, `--include-archived` to include archived projects, and SSH or
  HTTPS-token cloning
