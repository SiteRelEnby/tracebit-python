# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-03-11

### Added
- SSH canary support: `deploy ssh` and `trigger ssh` subcommands
- `~/.ssh/config` Host entry written on SSH deploy, removed on remove/refresh
- `--ssh-host` flag on `deploy ssh` for a believable hostname alias
  (e.g. `backup-server.internal`); defaults to honeypot IP directly
- `--ssh-config-file` flag on `deploy ssh` for split ssh config setups
- `install-cron` command — prints or installs a crontab entry for unattended refresh
  (`--install` for user crontab, `--system` for `/etc/cron.d/`, `--schedule` to override)
- `cleanup` command — removes already-expired credentials (local files + state)
- `-q`/`--quiet` now accepted after the subcommand as well as before it
- Python version check: friendly error message if running Python < 3.8

### Fixed
- API credential types field corrected to `types` (was `credentialTypes`, broke all issuance since 0.1.1)
- SSH config: `--ssh-config-file` with missing parent directory now fails cleanly instead of traceback
- SSH config: `--ssh-host` values with whitespace/newlines now rejected before any API calls
- SSH deploy: `--ssh-host` uniqueness enforced across deployed credentials; reuse requires `--force`

## [0.1.1] - 2025-XX-XX

### Added
- `-q` / `--quiet` flag
- `--version` flag
- `--hours` flag on `refresh`
- AGENTS.md
- Test suite (51 tests)

### Fixed
- Default refresh threshold was 13h, causing refresh on every run (credentials are ~12h-lived)
- Corrupt state file now handled gracefully
- Bad/missing expiration timestamps in state no longer crash refresh
- `requests.RequestException` now caught in deploy, refresh, and remove
- `~/.aws/` permission warning added (warns, does not modify)

## [0.1.0] - 2025-XX-XX

### Added
- Initial release
- `configure`, `deploy aws`, `refresh`, `trigger aws`, `show`, `remove` commands
- Local state tracking in `~/.config/tracebit/state.json`
- File permissions enforced (`0600`/`0700`)
- `--token`, `--base-url`, `--json` global flags
- GitHub Actions CI and trusted PyPI publishing workflow

[Unreleased]: https://github.com/SiteRelEnby/tracebit-python/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/SiteRelEnby/tracebit-python/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/SiteRelEnby/tracebit-python/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/SiteRelEnby/tracebit-python/releases/tag/v0.1.0
