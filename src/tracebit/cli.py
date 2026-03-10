import sys

if sys.version_info < (3, 8):
    sys.exit(
        f"Error: tracebit requires Python 3.8 or later "
        f"(you have {sys.version.split()[0]}). Please upgrade."
    )

import argparse
import json
import socket
import subprocess
from datetime import datetime, timezone

import requests

from .api import TracebitClient, TracebitError
from .aws import deploy_aws_credentials, remove_aws_credentials, profile_exists
from .config import load_token, save_token
from .ssh import (
    deploy_ssh_key, remove_ssh_key, key_exists, trigger_ssh,
    write_ssh_config, remove_ssh_config, validate_ssh_host,
)
from .state import (
    save_credential,
    load_credentials,
    remove_credential,
    get_expiring_credentials,
)


def _quiet(args):
    return getattr(args, "quiet", False)


def _log(args, msg):
    if not _quiet(args):
        print(msg)


def _get_client(args):
    token = getattr(args, "token", None) or load_token()
    if not token:
        print(
            "Error: No API token found. Set TRACEBIT_API_TOKEN, "
            "run 'tracebit configure', or pass --token.",
            file=sys.stderr,
        )
        sys.exit(1)
    base_url = getattr(args, "base_url", None)
    return TracebitClient(token, base_url=base_url)


def _parse_labels(label_args):
    if not label_args:
        return {}
    labels = {}
    for item in label_args:
        if "=" not in item:
            print(f"Error: Invalid label format '{item}', expected key=value",
                  file=sys.stderr)
            sys.exit(1)
        k, v = item.split("=", 1)
        labels[k] = v
    return labels


def cmd_configure(args):
    """Save API token to config file."""
    if args.token_value:
        token = args.token_value
    elif not sys.stdin.isatty():
        token = sys.stdin.read().strip()
    else:
        import getpass
        token = getpass.getpass("API token: ")

    if not token:
        print("Error: No token provided.", file=sys.stderr)
        sys.exit(1)

    save_token(token)
    _log(args, "Token saved to ~/.config/tracebit/token")


def cmd_deploy_aws(args):
    """Issue, deploy, and confirm AWS canary credentials."""
    client = _get_client(args)
    name = args.name or socket.gethostname()
    labels = _parse_labels(args.labels)

    # get defaults from API if profile/region not specified
    profile = args.profile
    region = args.region
    if not region:
        try:
            meta = client.generate_metadata()
            region = meta.get("awsRegion") or "us-east-1"
        except Exception:
            region = "us-east-1"
    if not profile:
        profile = "staging"

    # check for existing profile (don't clobber real credentials)
    if profile_exists(profile) and not args.force:
        # check if it's one of ours (from state) — suggest --force
        # if it's unknown, warn more strongly
        ours = any(
            c.get("profile") == profile
            for c in load_credentials()
            if c["type"] == "aws"
        )
        if ours:
            print(
                f"Error: AWS profile '{profile}' already has a canary deployed. "
                f"Use --force to replace it, or 'tracebit refresh' to renew.",
                file=sys.stderr,
            )
        else:
            print(
                f"Error: AWS profile '{profile}' already exists and is NOT a "
                f"known canary — refusing to overwrite. Use --profile to choose "
                f"a different name, or --force if you're sure.",
                file=sys.stderr,
            )
        sys.exit(1)

    # if --force and there's an existing canary for this profile, expire it first
    if args.force:
        existing = [
            c for c in load_credentials()
            if c["type"] == "aws" and c.get("profile") == profile
        ]
        for old in existing:
            try:
                client.remove_credentials(old["name"], "aws")
                _log(args, f"Expired previous canary '{old['name']}' on Tracebit.")
            except (TracebitError, requests.RequestException):
                pass
            remove_credential(old["name"], "aws")

    # issue credentials
    _log(args, f"Issuing AWS canary credentials (name={name}, profile={profile})...")
    try:
        result = client.issue_credentials(
            name=name, types=["aws"], source="tracebit-python",
            source_type="endpoint", labels=labels,
        )
    except (TracebitError, requests.RequestException) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    aws = result.get("aws")
    if not aws:
        print("Error: No AWS credentials in response.", file=sys.stderr)
        sys.exit(1)

    # deploy locally
    deploy_aws_credentials(
        profile=profile,
        region=region,
        access_key_id=aws["awsAccessKeyId"],
        secret_access_key=aws["awsSecretAccessKey"],
        session_token=aws["awsSessionToken"],
    )
    _log(args, f"Credentials written to ~/.aws/credentials [{profile}]")

    # confirm deployment
    try:
        client.confirm_credentials(aws["awsConfirmationId"])
        _log(args, "Deployment confirmed with Tracebit.")
    except (TracebitError, requests.RequestException) as e:
        print(f"Warning: Could not confirm deployment: {e}", file=sys.stderr)

    # save state
    save_credential({
        "name": name,
        "type": "aws",
        "profile": profile,
        "region": region,
        "expiration": aws["awsExpiration"],
        "confirmation_id": aws["awsConfirmationId"],
        "labels": labels,
    })

    if args.json_output:
        print(json.dumps({
            "profile": profile,
            "region": region,
            "access_key_id": aws["awsAccessKeyId"],
            "expiration": aws["awsExpiration"],
        }, indent=2))
    elif not _quiet(args):
        print(f"\nCanary deployed successfully!")
        print(f"  Profile:    {profile}")
        print(f"  Region:     {region}")
        print(f"  Access Key: {aws['awsAccessKeyId']}")
        print(f"  Expires:    {aws['awsExpiration']}")


def cmd_deploy_ssh(args):
    """Issue and deploy a canary SSH private key."""
    client = _get_client(args)
    name = args.name or socket.gethostname()
    labels = _parse_labels(args.labels)

    # validate --ssh-host early before any API calls
    if args.ssh_host:
        try:
            validate_ssh_host(args.ssh_host)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        existing_host = next(
            (c for c in load_credentials()
             if c["type"] == "ssh" and c.get("ssh_host") == args.ssh_host),
            None,
        )
        if existing_host and not args.force:
            print(
                f"Error: SSH host '{args.ssh_host}' is already used by canary "
                f"'{existing_host['name']}'. Use --force to replace it.",
                file=sys.stderr,
            )
            sys.exit(1)

    # get default key filename from API if not specified
    key_filename = args.key_file
    if not key_filename:
        try:
            meta = client.generate_metadata()
            key_filename = meta.get("sshKeyFileName") or "id_backup"
        except Exception:
            key_filename = "id_backup"

    if key_exists(key_filename) and not args.force:
        from .ssh import key_exists as ke
        from .state import load_credentials as lc
        ours = any(
            c.get("key_filename") == key_filename
            for c in lc()
            if c["type"] == "ssh"
        )
        if ours:
            print(
                f"Error: SSH key '{key_filename}' already has a canary deployed. "
                f"Use --force to replace it, or 'tracebit refresh' to renew.",
                file=sys.stderr,
            )
        else:
            print(
                f"Error: ~/.ssh/{key_filename} already exists and is NOT a known canary. "
                f"Use --key-file to choose a different name, or --force if you're sure.",
                file=sys.stderr,
            )
        sys.exit(1)

    if args.force:
        existing = [
            c for c in load_credentials()
            if c["type"] == "ssh" and c.get("key_filename") == key_filename
        ]
        for old in existing:
            try:
                client.remove_credentials(old["name"], "ssh")
                _log(args, f"Expired previous SSH canary '{old['name']}' on Tracebit.")
            except (TracebitError, requests.RequestException):
                pass
            remove_credential(old["name"], "ssh")

    _log(args, f"Issuing SSH canary key (name={name}, file=~/.ssh/{key_filename})...")
    try:
        result = client.issue_credentials(
            name=name, types=["ssh"], source="tracebit-python",
            source_type="endpoint", labels=labels,
        )
    except (TracebitError, requests.RequestException) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    ssh = result.get("ssh")
    if not ssh:
        print("Error: No SSH credentials in response.", file=sys.stderr)
        sys.exit(1)

    ssh_ip = ssh.get("sshIp", "")
    ssh_host = args.ssh_host or ssh_ip
    config_file = args.ssh_config_file or None

    key_path = deploy_ssh_key(key_filename, ssh["sshPrivateKey"])
    _log(args, f"Private key written to {key_path}")

    if ssh_host:
        try:
            write_ssh_config(ssh_host, key_path, ssh_ip, config_file)
            _log(args, f"SSH config entry written for host '{ssh_host}'")
        except OSError as e:
            print(f"Error: Could not write SSH config: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        client.confirm_credentials(ssh["sshConfirmationId"])
        _log(args, "Deployment confirmed with Tracebit.")
    except (TracebitError, requests.RequestException) as e:
        print(f"Warning: Could not confirm deployment: {e}", file=sys.stderr)

    save_credential({
        "name": name,
        "type": "ssh",
        "key_filename": key_filename,
        "ssh_host": ssh_host,
        "ssh_config_file": config_file,
        "ssh_ip": ssh_ip,
        "expiration": ssh.get("sshExpiration", ""),
        "confirmation_id": ssh["sshConfirmationId"],
        "labels": labels,
    })

    if args.json_output:
        print(json.dumps({
            "key_file": str(key_path),
            "ssh_host": ssh_host,
            "ssh_ip": ssh_ip,
            "expiration": ssh.get("sshExpiration", ""),
        }, indent=2))
    elif not _quiet(args):
        print(f"\nSSH canary deployed successfully!")
        print(f"  Key file:   {key_path}")
        print(f"  SSH host:   {ssh_host}")
        print(f"  SSH IP:     {ssh_ip or 'n/a'}")
        print(f"  Expires:    {ssh.get('sshExpiration', 'n/a')}")


def cmd_trigger_ssh(args):
    """Test-fire an SSH canary by connecting to Tracebit's honeypot."""
    creds = load_credentials()
    ssh_creds = [c for c in creds if c["type"] == "ssh"]

    if not ssh_creds:
        print("No SSH canary credentials deployed.", file=sys.stderr)
        sys.exit(1)

    if args.name:
        match = [c for c in ssh_creds if c["name"] == args.name]
        if not match:
            print(f"No SSH credential found with name '{args.name}'.", file=sys.stderr)
            sys.exit(1)
        cred = match[0]
    else:
        cred = ssh_creds[0]

    key_filename = cred["key_filename"]
    ssh_ip = cred.get("ssh_ip", "")
    if not ssh_ip:
        print("Error: No SSH IP stored for this canary.", file=sys.stderr)
        sys.exit(1)

    _log(args, f"Triggering SSH canary (key=~/.ssh/{key_filename}, ip={ssh_ip})...")
    try:
        trigger_ssh(key_filename, ssh_ip)
        # SSH to a honeypot always fails auth — the alert fires server-side
        _log(args, "SSH connection attempted — canary should fire on Tracebit's side.")
    except FileNotFoundError:
        print("Error: 'ssh' not found in PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("Error: SSH connection timed out.", file=sys.stderr)
        sys.exit(1)


def cmd_refresh(args):
    """Refresh credentials expiring within the given threshold."""
    client = _get_client(args)
    hours = args.hours
    expiring = get_expiring_credentials(hours=hours)

    if not expiring:
        _log(args, "No credentials need refreshing.")
        return

    failures = 0
    for cred in expiring:
        ctype = cred["type"]
        if ctype not in ("aws", "ssh"):
            _log(args, f"Skipping unsupported credential type: {cred['name']} ({ctype})")
            continue

        exp = cred.get("expiration", "")
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            remaining = (exp_dt - datetime.now(timezone.utc)).total_seconds() / 3600
            _log(args, f"Refreshing {ctype.upper()} credential '{cred['name']}' "
                       f"(expires in {remaining:.1f}h, threshold {hours}h)...")
        except (ValueError, TypeError):
            _log(args, f"Refreshing {ctype.upper()} credential '{cred['name']}'...")

        try:
            result = client.issue_credentials(
                name=cred["name"], types=[ctype], source="tracebit-python",
                source_type="endpoint", labels=cred.get("labels", {}),
            )
        except (TracebitError, requests.RequestException) as e:
            print(f"Error refreshing {cred['name']}: {e}", file=sys.stderr)
            failures += 1
            continue

        if ctype == "aws":
            aws = result.get("aws")
            if not aws:
                print(f"Error: No AWS credentials in refresh response for {cred['name']}.",
                      file=sys.stderr)
                failures += 1
                continue
            deploy_aws_credentials(
                profile=cred["profile"],
                region=cred["region"],
                access_key_id=aws["awsAccessKeyId"],
                secret_access_key=aws["awsSecretAccessKey"],
                session_token=aws["awsSessionToken"],
            )
            try:
                client.confirm_credentials(aws["awsConfirmationId"])
            except (TracebitError, requests.RequestException) as e:
                print(f"Warning: Could not confirm refresh for {cred['name']}: {e}",
                      file=sys.stderr)
            save_credential({
                "name": cred["name"], "type": "aws",
                "profile": cred["profile"], "region": cred["region"],
                "expiration": aws["awsExpiration"],
                "confirmation_id": aws["awsConfirmationId"],
                "labels": cred.get("labels", {}),
            })
            _log(args, f"  Refreshed. New expiration: {aws['awsExpiration']}")

        elif ctype == "ssh":
            ssh = result.get("ssh")
            if not ssh:
                print(f"Error: No SSH credentials in refresh response for {cred['name']}.",
                      file=sys.stderr)
                failures += 1
                continue
            new_ip = ssh.get("sshIp", cred.get("ssh_ip", ""))
            ssh_host = cred.get("ssh_host", "")
            config_file = cred.get("ssh_config_file")
            key_path = deploy_ssh_key(cred["key_filename"], ssh["sshPrivateKey"])
            if ssh_host:
                try:
                    write_ssh_config(ssh_host, key_path, new_ip, config_file)
                except OSError as e:
                    print(f"Warning: Could not update SSH config for {cred['name']}: {e}",
                          file=sys.stderr)
            try:
                client.confirm_credentials(ssh["sshConfirmationId"])
            except (TracebitError, requests.RequestException) as e:
                print(f"Warning: Could not confirm refresh for {cred['name']}: {e}",
                      file=sys.stderr)
            save_credential({
                "name": cred["name"], "type": "ssh",
                "key_filename": cred["key_filename"],
                "ssh_host": ssh_host,
                "ssh_config_file": config_file,
                "ssh_ip": new_ip,
                "expiration": ssh.get("sshExpiration", ""),
                "confirmation_id": ssh["sshConfirmationId"],
                "labels": cred.get("labels", {}),
            })
            _log(args, f"  Refreshed. New expiration: {ssh.get('sshExpiration', 'n/a')}")

    if failures:
        print(f"\n{failures} credential(s) failed to refresh.", file=sys.stderr)
        sys.exit(1)


def cmd_trigger_aws(args):
    """Test-fire an AWS canary credential."""
    creds = load_credentials()
    aws_creds = [c for c in creds if c["type"] == "aws"]

    if not aws_creds:
        print("No AWS canary credentials deployed.", file=sys.stderr)
        sys.exit(1)

    if args.name:
        match = [c for c in aws_creds if c["name"] == args.name]
        if not match:
            print(f"No AWS credential found with name '{args.name}'.",
                  file=sys.stderr)
            sys.exit(1)
        cred = match[0]
    else:
        cred = aws_creds[0]

    profile = cred["profile"]
    _log(args, f"Triggering canary credential (profile={profile})...")

    try:
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--profile", profile],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "arn:aws:sts::" in result.stdout:
            _log(args, "Canary triggered successfully!")
            _log(args, result.stdout.strip())
        else:
            _log(args, "Trigger command ran but output was unexpected:")
            if result.stdout:
                _log(args, result.stdout.strip())
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)
    except FileNotFoundError:
        print(
            "Error: 'aws' CLI not found. Install it to use the trigger command.",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("Error: Trigger command timed out.", file=sys.stderr)
        sys.exit(1)


def cmd_show(args):
    """Display deployed canary credentials."""
    creds = load_credentials()
    if not creds:
        _log(args, "No canary credentials deployed.")
        return

    if args.json_output:
        print(json.dumps(creds, indent=2))
        return

    now = datetime.now(timezone.utc)
    for c in creds:
        exp_str = c.get("expiration", "unknown")
        status = ""
        if exp_str and exp_str != "unknown":
            try:
                exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                if exp_dt < now:
                    status = " [EXPIRED]"
                elif (exp_dt - now).total_seconds() < 7200:
                    status = " [EXPIRING SOON]"
            except ValueError:
                pass

        _log(args, f"  Name:       {c['name']}")
        _log(args, f"  Type:       {c['type']}")
        if c["type"] == "aws":
            _log(args, f"  Profile:    {c.get('profile', 'n/a')}")
            _log(args, f"  Region:     {c.get('region', 'n/a')}")
        elif c["type"] == "ssh":
            _log(args, f"  Key file:   ~/.ssh/{c.get('key_filename', 'n/a')}")
            if c.get("ssh_host"):
                _log(args, f"  SSH host:   {c['ssh_host']}")
            _log(args, f"  SSH IP:     {c.get('ssh_ip', 'n/a')}")
        _log(args, f"  Expires:    {exp_str}{status}")
        if c.get("labels"):
            _log(args, f"  Labels:     {c['labels']}")
        _log(args, "")


def _remove_one(args, client, c):
    """Expire and remove a single credential. Shared by remove and cleanup."""
    try:
        client.remove_credentials(c["name"], c["type"])
        _log(args, f"Expired '{c['name']}' ({c['type']}) on Tracebit.")
    except (TracebitError, requests.RequestException) as e:
        print(f"Warning: Could not expire server-side: {e}", file=sys.stderr)

    if c["type"] == "aws":
        remove_aws_credentials(c.get("profile", ""))
        _log(args, f"Removed AWS profile '{c.get('profile')}' from ~/.aws/")
    elif c["type"] == "ssh":
        remove_ssh_key(c.get("key_filename", ""))
        _log(args, f"Removed SSH key '~/.ssh/{c.get('key_filename')}' from disk")
        if c.get("ssh_host"):
            remove_ssh_config(c["ssh_host"], c.get("ssh_config_file"))
            _log(args, f"Removed SSH config entry for host '{c['ssh_host']}'")
    remove_credential(c["name"], c["type"])
    _log(args, f"Removed credential '{c['name']}' ({c['type']}) from state.")


def cmd_remove(args):
    """Remove deployed canary credentials."""
    client = _get_client(args)
    creds = load_credentials()

    if args.name:
        matches = [c for c in creds if c["name"] == args.name]
    else:
        matches = creds

    if not matches:
        _log(args, "No matching credentials found.")
        return

    for c in matches:
        _remove_one(args, client, c)


def cmd_cleanup(args):
    """Remove credentials that have already expired."""
    client = _get_client(args)
    now = datetime.now(timezone.utc)
    creds = load_credentials()

    expired = []
    for c in creds:
        exp = c.get("expiration", "")
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt < now:
                expired.append(c)
        except (ValueError, TypeError):
            pass  # missing/bad expiration — skip, don't clean up blindly

    if not expired:
        _log(args, "No expired credentials found.")
        return

    for c in expired:
        _log(args, f"Cleaning up expired credential '{c['name']}' ({c['type']})...")
        _remove_one(args, client, c)


def cmd_install_cron(args):
    """Print or install a crontab entry for tracebit refresh."""
    import shutil

    tracebit_bin = shutil.which("tracebit") or sys.argv[0]
    schedule = args.schedule
    line = f"{schedule} {tracebit_bin} refresh --quiet"

    if args.system:
        cron_file = "/etc/cron.d/tracebit"
        entry = f"{schedule} root {tracebit_bin} refresh --quiet\n"
        try:
            with open(cron_file, "w") as f:
                f.write("# Tracebit canary credential refresh\n")
                f.write(entry)
            print(f"Wrote {cron_file}")
        except OSError as e:
            print(f"Error: Could not write {cron_file}: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.install:
        import subprocess
        try:
            existing = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True,
            )
            current = existing.stdout if existing.returncode == 0 else ""
            if tracebit_bin in current and "refresh" in current:
                print("A tracebit refresh entry already exists in your crontab:")
                for ln in current.splitlines():
                    if "tracebit" in ln and "refresh" in ln:
                        print(f"  {ln}")
                print("Remove it manually first if you want to replace it.")
                sys.exit(1)
            new_crontab = current.rstrip("\n") + ("\n" if current else "") + line + "\n"
            subprocess.run(["crontab", "-"], input=new_crontab, text=True, check=True)
            print(f"Installed crontab entry: {line}")
        except FileNotFoundError:
            print("Error: 'crontab' not found in PATH.", file=sys.stderr)
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"Error: crontab installation failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Add this line to your crontab (crontab -e):\n")
        print(f"  {line}\n")
        print("Or run with --install to add it automatically.")


def main():
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="tracebit",
        description="Manage Tracebit canary credentials",
    )
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument("--token", help="API token (overrides env/config)")
    parser.add_argument("--base-url", help="Override Tracebit API base URL")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Output in JSON format where supported")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress informational output (errors still print to stderr)")

    sub = parser.add_subparsers(dest="command")

    # configure
    p_conf = sub.add_parser("configure", help="Save API token")
    p_conf.add_argument("token_value", nargs="?", help="Token to save")

    # deploy
    p_deploy = sub.add_parser("deploy", help="Deploy canary credentials")
    deploy_sub = p_deploy.add_subparsers(dest="deploy_type")

    p_aws = deploy_sub.add_parser("aws", help="Deploy AWS canary credentials")
    p_aws.add_argument("--name", help="Credential name for Tracebit dashboard (default: hostname)")
    p_aws.add_argument("--profile",
                        help="AWS profile name — pick something realistic "
                             "e.g. 'staging', 'backup', 'legacy-admin' (default: staging)")
    p_aws.add_argument("--region", help="AWS region (default: from API)")
    p_aws.add_argument("--labels", nargs="*", metavar="KEY=VALUE",
                        help="Labels as key=value pairs")
    p_aws.add_argument("--force", action="store_true",
                        help="Overwrite existing profile")

    p_ssh = deploy_sub.add_parser("ssh", help="Deploy SSH canary key")
    p_ssh.add_argument("--name", help="Credential name for Tracebit dashboard (default: hostname)")
    p_ssh.add_argument("--key-file", dest="key_file",
                       help="Key filename in ~/.ssh/ — pick something realistic "
                            "e.g. 'id_backup', 'id_rsa_old' (default: from API)")
    p_ssh.add_argument("--ssh-host", dest="ssh_host", metavar="HOSTNAME",
                       help="Hostname alias for ~/.ssh/config — pick something believable "
                            "e.g. 'backup-server.internal', 'git.prod' (default: use IP directly)")
    p_ssh.add_argument("--ssh-config-file", dest="ssh_config_file", metavar="PATH",
                       help="Path to ssh config file to write Host entry into "
                            "(default: ~/.ssh/config)")
    p_ssh.add_argument("--labels", nargs="*", metavar="KEY=VALUE",
                       help="Labels as key=value pairs")
    p_ssh.add_argument("--force", action="store_true",
                       help="Overwrite existing key file")

    # refresh
    p_refresh = sub.add_parser("refresh", help="Refresh expiring credentials")
    p_refresh.add_argument("--hours", type=float, default=2,
                           help="Refresh credentials expiring within this many hours (default: 2)")

    # trigger
    p_trigger = sub.add_parser("trigger", help="Test-fire a canary credential")
    trigger_sub = p_trigger.add_subparsers(dest="trigger_type")
    p_trig_aws = trigger_sub.add_parser("aws", help="Trigger AWS canary")
    p_trig_aws.add_argument("--name", help="Credential name to trigger")

    p_trig_ssh = trigger_sub.add_parser("ssh", help="Trigger SSH canary")
    p_trig_ssh.add_argument("--name", help="Credential name to trigger")

    # show
    sub.add_parser("show", help="Show deployed credentials")

    # remove
    p_remove = sub.add_parser("remove", help="Remove deployed credentials")
    p_remove.add_argument("--name", help="Name of credential to remove (all if omitted)")

    # cleanup
    sub.add_parser("cleanup", help="Remove already-expired credentials")

    # install-cron
    p_cron = sub.add_parser("install-cron", help="Print or install a cron job for refresh")
    p_cron.add_argument("--schedule", default="*/30 * * * *",
                        help="Cron schedule expression (default: '*/30 * * * *')")
    p_cron.add_argument("--install", action="store_true",
                        help="Add entry to current user's crontab")
    p_cron.add_argument("--system", action="store_true",
                        help="Write /etc/cron.d/tracebit (requires root)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "configure":
        cmd_configure(args)
    elif args.command == "deploy":
        if not getattr(args, "deploy_type", None):
            p_deploy.print_help()
            sys.exit(1)
        if args.deploy_type == "aws":
            cmd_deploy_aws(args)
        elif args.deploy_type == "ssh":
            cmd_deploy_ssh(args)
    elif args.command == "refresh":
        cmd_refresh(args)
    elif args.command == "trigger":
        if not getattr(args, "trigger_type", None):
            p_trigger.print_help()
            sys.exit(1)
        if args.trigger_type == "aws":
            cmd_trigger_aws(args)
        elif args.trigger_type == "ssh":
            cmd_trigger_ssh(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "remove":
        cmd_remove(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)
    elif args.command == "install-cron":
        cmd_install_cron(args)


if __name__ == "__main__":
    main()
