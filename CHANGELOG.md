# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com).

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
