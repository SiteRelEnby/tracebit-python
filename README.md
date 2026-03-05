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

### 3. Deploy canaries

**AWS credentials:**

```bash
tracebit deploy aws --profile staging
```

Writes canary AWS credentials to `~/.aws/credentials` under the given profile.
Any AWS API call using these credentials triggers an alert.

**SSH key:**

```bash
tracebit deploy ssh --key-file id_backup --ssh-host backup-server.internal
```

Writes a canary SSH private key to `~/.ssh/id_backup` and adds a `Host` block
to `~/.ssh/config` pointing `backup-server.internal` at Tracebit's honeypot.
Any SSH connection attempt using this key triggers an alert.

Choose names that look realistic to an attacker — `staging`, `id_backup`,
`backup-server.internal`. The whole point is that they look like real credentials.

### 4. Test it

```bash
tracebit trigger aws    # uses aws sts get-caller-identity
tracebit trigger ssh    # connects to Tracebit's honeypot
```

You should see an alert on the Tracebit dashboard within a few minutes.

### 5. Keep credentials fresh

Canary credentials expire after ~12 hours. Set up a cron job:

```bash
tracebit install-cron           # prints a ready-to-paste crontab line
tracebit install-cron --install # adds it to your crontab automatically
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

### `tracebit deploy ssh`

Issue and deploy a canary SSH private key.

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | hostname | Credential name (shown on Tracebit dashboard) |
| `--key-file` | from API | Key filename in `~/.ssh/` |
| `--ssh-host` | honeypot IP | Hostname alias for `~/.ssh/config` Host entry |
| `--ssh-config-file` | `~/.ssh/config` | SSH config file to write Host entry into |
| `--labels` | | Metadata as `key=value` pairs |
| `--force` | | Replace existing key/config entry |

The `--ssh-host` alias is what makes the canary effective: an attacker finding
`~/.ssh/config` with `Host backup-server.internal` pointing somewhere will try
to connect there, firing the alert. If omitted, the honeypot IP is used directly.

Use `--ssh-config-file` if your `~/.ssh/config` is tracked in git and you keep
local overrides in a separate file (e.g. `~/.ssh/config.local`).

### `tracebit refresh`

Re-issue any credentials expiring within the given threshold. Designed to run
from cron.

| Option | Default | Description |
|--------|---------|-------------|
| `--hours` | `2` | Refresh credentials expiring within this many hours |

### `tracebit trigger aws`

Test-fire an AWS canary by calling `aws sts get-caller-identity` with the canary
profile. Requires the AWS CLI to be installed.

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | first found | Credential name to trigger |

### `tracebit trigger ssh`

Test-fire an SSH canary by connecting to Tracebit's honeypot with the canary key.

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | first found | Credential name to trigger |

### `tracebit show`

Display deployed canary credentials, their profiles/keys, and expiration status.

### `tracebit remove`

Remove canary credentials locally and expire them on Tracebit's server.

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | all | Name of credential to remove |

### `tracebit install-cron`

Print or install a cron job that runs `tracebit refresh --quiet` on a schedule.

| Option | Default | Description |
|--------|---------|-------------|
| `--schedule` | `*/30 * * * *` | Cron schedule expression |
| `--install` | | Add entry to current user's crontab |
| `--system` | | Write `/etc/cron.d/tracebit` (requires root) |

## Global Options

| Option | Description |
|--------|-------------|
| `--token TOKEN` | API token (overrides env var and config file) |
| `--base-url URL` | Override Tracebit API URL |
| `--json` | JSON output (where supported) |
| `-q / --quiet` | Suppress informational output (errors still go to stderr) |

## Token Resolution

The API token is resolved in this order:

1. `--token` command-line flag
2. `TRACEBIT_API_TOKEN` environment variable
3. `~/.config/tracebit/token` file

## How It Works

**AWS canaries:**

1. **Issue** — requests canary AWS credentials from the Tracebit API
2. **Deploy** — writes them to `~/.aws/credentials` and `~/.aws/config`
3. **Confirm** — tells Tracebit the credentials are live
4. **Alert** — any AWS API call using these credentials fires a detection

The credentials have an explicit deny policy — they can't actually do anything
in AWS. But any attempt to use them is logged and alerted on.

**SSH canaries:**

1. **Issue** — requests a canary SSH private key from the Tracebit API
2. **Deploy** — writes the key to `~/.ssh/<key-file>` and adds a `Host` block
   to `~/.ssh/config` pointing the chosen hostname at Tracebit's honeypot
3. **Confirm** — tells Tracebit the key is deployed
4. **Alert** — any SSH connection attempt presenting this key to the honeypot
   fires a detection

## File Permissions

- `~/.aws/` directory: `0700`
- `~/.aws/credentials`, `~/.aws/config`: `0600`
- `~/.ssh/` directory: `0700`
- `~/.ssh/<key-file>`: `0600`
- `~/.ssh/config`: `0600`
- `~/.config/tracebit/token`: `0600`
- `~/.config/tracebit/state.json`: `0600`

## License

[Apache License 2.0](LICENSE)
