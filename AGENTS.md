# AGENTS.md — Guidelines for AI Agents and Contributors

This file is for AI coding agents (Claude Code, Copilot, Codex, Cursor, etc.) and human contributors working on tracebit-python. Read this before writing code or opening a PR.

## What This Is

A Python CLI for deploying [Tracebit](https://community.tracebit.com/) canary credentials on headless servers. It hits the Tracebit Community API to issue fake AWS credentials, deploys them to `~/.aws/`, and monitors their expiration for refresh. These credentials are honeypots — any use triggers a security alert.

## Guiding Principles

### Don't leak canary credentials

The whole point of canary credentials is that they look real. Treat them accordingly:

- Never log credential values (access key, secret key, session token) except during initial deploy output
- Don't include credentials in error messages or state files
- State file (`~/.config/tracebit/state.json`) stores metadata only (profile name, expiration, confirmation ID) — not the credentials themselves
- The API token grants the ability to issue credentials — protect it like a secret

### File permissions matter

Credential and config files must have restrictive permissions:

- `~/.aws/` directory: `0700`
- `~/.aws/credentials`, `~/.aws/config`: `0600`
- `~/.config/tracebit/token`: `0600`
- `~/.config/tracebit/state.json`: `0600`

If you add new files that contain secrets or sensitive config, set permissions before writing content.

### Don't clobber real credentials

The tool writes to `~/.aws/credentials` which may contain real AWS credentials. The profile existence check and `--force` flag exist for a reason. Never overwrite an existing profile without explicit user consent. When in doubt, error out.

### Match the official CLI's API contract

The C# CLI at [tracebit-com/tracebit-community-cli](https://github.com/tracebit-com/tracebit-community-cli) is the reference implementation. Use the same field names (`types`, `sourceType`, etc.), the same endpoints, and the same confirmation flow. If the API changes, check the official CLI first.

### Profile names should look realistic

The default profile name should not contain "tracebit", "canary", "honeypot", or anything that reveals its purpose. The whole value of canary credentials is that attackers mistake them for real ones.

### Handle API failures gracefully

This tool runs unattended via cron. When the Tracebit API is down:

- Don't crash with a traceback — catch `requests.RequestException`
- Don't destroy existing credentials — leave the old ones in place
- Exit non-zero so cron/monitoring can detect the failure
- Print errors to stderr only

### Keep dependencies minimal

This is a CLI tool that gets copied to servers. The only external dependency is `requests`. Don't add more without good reason.

## Project Structure

```
src/tracebit/
├── __init__.py     # __version__
├── cli.py          # argparse CLI, all subcommands
├── api.py          # TracebitClient — API calls
├── aws.py          # ~/.aws/ credential file read/write
├── config.py       # Token loading (env var / config file)
└── state.py        # Local state tracking (deployed credentials)
```

## Test & Build

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

tracebit --help              # verify CLI loads
tracebit --version           # check version
python -m build              # build sdist + wheel
```

## PR Expectations

- Explain *why*, not just *what*
- Don't introduce new dependencies without justification
- Test manually with a real Tracebit API token if touching API code
- If you're an AI agent: state that in the PR description
