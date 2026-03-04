# tracebit-python

[![PyPI](https://img.shields.io/pypi/v/tracebit-python)](https://pypi.org/project/tracebit-python/)
[![Python](https://img.shields.io/pypi/pyversions/tracebit-python)](https://pypi.org/project/tracebit-python/)
[![License](https://img.shields.io/pypi/l/tracebit-python)](LICENSE)
![transrights](https://pride-badges.pony.workers.dev/static/v1?label=trans%20rights&stripeWidth=6&stripeColors=5BCEFA,F5A9B8,FFFFFF,F5A9B8,5BCEFA)
![enbyware](https://pride-badges.pony.workers.dev/static/v1?label=enbyware&labelColor=%23555&stripeWidth=8&stripeColors=FCF434%2CFFFFFF%2C9C59D1%2C2C2C2C)
![pluralmade](https://pride-badges.pony.workers.dev/static/v1?label=plural+made&labelColor=%23555&stripeWidth=8&stripeColors=2e0525%2C553578%2C7675c3%2C89c7b0%2Cf4ecbd)

Python CLI for deploying [Tracebit](https://community.tracebit.com/) canary
credentials on headless servers.

Tracebit provides canary tokens — fake credentials that trigger alerts when
used by an attacker. Their official CLI requires browser-based OAuth, which
doesn't work on headless servers. This tool uses the Tracebit API directly
with pre-generated API tokens.

## Installation

```bash
pip install tracebit-python
```

Or from source:

```bash
git clone https://github.com/SiteRelEnby/tracebit-python
cd tracebit-python
pip install -e .
```

## Quick Start

### 1. Get an API token

Log in to [community.tracebit.com](https://community.tracebit.com/) and
create an API token from the web UI.

### 2. Configure

```bash
tracebit configure
# paste your API token when prompted
```

Or use an environment variable:

```bash
export TRACEBIT_API_TOKEN=your-token-here
```

### 3. Deploy a canary

```bash
tracebit deploy aws --profile staging
```

This issues canary AWS credentials from Tracebit, writes them to
`~/.aws/credentials` under the specified profile, and confirms the
deployment. If anyone (or anything) uses these credentials, Tracebit
fires an alert.

### 4. Test it

```bash
tracebit trigger aws
```

Runs `aws sts get-caller-identity` against the canary profile. You should
see an alert on the Tracebit dashboard within a few minutes.

### 5. Keep credentials fresh

Canary credentials expire after ~12 hours. Set up a cron job to refresh them:

```bash
# crontab -e
0 */6 * * * /path/to/tracebit refresh --hours 4
```

## Commands

### `tracebit configure [TOKEN]`

Save an API token to `~/.config/tracebit/token`. Reads from argument, stdin,
or interactive prompt.

### `tracebit deploy aws`

Issue and deploy canary AWS credentials.

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | hostname | Credential name (shown on Tracebit dashboard) |
| `--profile` | `staging` | AWS profile name in `~/.aws/credentials` |
| `--region` | from API | AWS region |
| `--labels` | | Metadata as `key=value` pairs |
| `--force` | | Replace existing profile (expires old canary first) |

Choose a realistic profile name — `staging`, `backup`, `legacy-admin`, etc.
The whole point is for these to look like real credentials to an attacker.

### `tracebit refresh`

Re-issue any credentials expiring within the given threshold. Designed to run
from cron.

| Option | Default | Description |
|--------|---------|-------------|
| `--hours` | `2` | Refresh credentials expiring within this many hours |

### `tracebit trigger aws`

Test-fire a canary by calling `aws sts get-caller-identity` with the canary
profile. Requires the AWS CLI to be installed.

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | first found | Credential name to trigger |

### `tracebit show`

Display deployed canary credentials, their profiles, and expiration status.

### `tracebit remove`

Remove canary credentials locally and expire them on Tracebit's server.

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | all | Name of credential to remove |

## Global Options

| Option | Description |
|--------|-------------|
| `--token TOKEN` | API token (overrides env var and config file) |
| `--base-url URL` | Override Tracebit API URL |
| `--json` | JSON output (where supported) |

## Token Resolution

The API token is resolved in this order:

1. `--token` command-line flag
2. `TRACEBIT_API_TOKEN` environment variable
3. `~/.config/tracebit/token` file

## How It Works

1. **Issue** — requests canary AWS credentials from the Tracebit API
2. **Deploy** — writes them to `~/.aws/credentials` and `~/.aws/config`
   under the chosen profile name
3. **Confirm** — tells Tracebit the credentials were deployed, so it starts
   monitoring for usage
4. **Alert** — any AWS API call using these credentials triggers a detection
   on the Tracebit dashboard

The credentials have an explicit deny policy — they can't actually do anything
in AWS. But any attempt to use them (by an attacker who found them on disk,
in a config file, etc.) is logged and alerted on.

## File Permissions

- `~/.aws/` directory: `0700`
- `~/.aws/credentials`, `~/.aws/config`: `0600`
- `~/.config/tracebit/token`: `0600`
- `~/.config/tracebit/state.json`: `0600`

## License

[Apache License 2.0](LICENSE)
