import argparse
import json
import socket
import subprocess
import sys
from datetime import datetime, timezone

import requests

from .api import TracebitClient, TracebitError
from .aws import deploy_aws_credentials, remove_aws_credentials, profile_exists
from .config import load_token, save_token
from .state import (
    save_credential,
    load_credentials,
    remove_credential,
    get_expiring_credentials,
)


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
    print("Token saved to ~/.config/tracebit/token")


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
                print(f"Expired previous canary '{old['name']}' on Tracebit.")
            except TracebitError:
                pass
            remove_credential(old["name"], "aws")

    # issue credentials
    print(f"Issuing AWS canary credentials (name={name}, profile={profile})...")
    try:
        result = client.issue_credentials(
            name=name, types=["aws"], source="tracebit-python",
            source_type="endpoint", labels=labels,
        )
    except TracebitError as e:
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
    print(f"Credentials written to ~/.aws/credentials [{profile}]")

    # confirm deployment
    try:
        client.confirm_credentials(aws["awsConfirmationId"])
        print("Deployment confirmed with Tracebit.")
    except TracebitError as e:
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
    else:
        print(f"\nCanary deployed successfully!")
        print(f"  Profile:    {profile}")
        print(f"  Region:     {region}")
        print(f"  Access Key: {aws['awsAccessKeyId']}")
        print(f"  Expires:    {aws['awsExpiration']}")


def cmd_refresh(args):
    """Refresh credentials expiring within the given threshold."""
    client = _get_client(args)
    hours = args.hours
    expiring = get_expiring_credentials(hours=hours)

    if not expiring:
        print("No credentials need refreshing.")
        return

    failures = 0
    for cred in expiring:
        if cred["type"] != "aws":
            print(f"Skipping non-AWS credential: {cred['name']}")
            continue

        exp = cred.get("expiration", "")
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            remaining = (exp_dt - datetime.now(timezone.utc)).total_seconds() / 3600
            print(f"Refreshing AWS credential '{cred['name']}' "
                  f"(expires in {remaining:.1f}h, threshold {hours}h)...")
        except (ValueError, TypeError):
            print(f"Refreshing AWS credential '{cred['name']}'...")
        try:
            result = client.issue_credentials(
                name=cred["name"], types=["aws"], source="tracebit-python",
                source_type="endpoint", labels=cred.get("labels", {}),
            )
        except (TracebitError, requests.RequestException) as e:
            print(f"Error refreshing {cred['name']}: {e}", file=sys.stderr)
            failures += 1
            continue

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
            "name": cred["name"],
            "type": "aws",
            "profile": cred["profile"],
            "region": cred["region"],
            "expiration": aws["awsExpiration"],
            "confirmation_id": aws["awsConfirmationId"],
            "labels": cred.get("labels", {}),
        })
        print(f"  Refreshed. New expiration: {aws['awsExpiration']}")

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
    print(f"Triggering canary credential (profile={profile})...")

    try:
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--profile", profile],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "arn:aws:sts::" in result.stdout:
            print("Canary triggered successfully!")
            print(result.stdout.strip())
        else:
            print("Trigger command ran but output was unexpected:")
            if result.stdout:
                print(result.stdout.strip())
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
        print("No canary credentials deployed.")
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

        print(f"  Name:       {c['name']}")
        print(f"  Type:       {c['type']}")
        if c["type"] == "aws":
            print(f"  Profile:    {c.get('profile', 'n/a')}")
            print(f"  Region:     {c.get('region', 'n/a')}")
        print(f"  Expires:    {exp_str}{status}")
        if c.get("labels"):
            print(f"  Labels:     {c['labels']}")
        print()


def cmd_remove(args):
    """Remove deployed canary credentials."""
    client = _get_client(args)
    creds = load_credentials()

    if args.name:
        matches = [c for c in creds if c["name"] == args.name]
    else:
        matches = creds

    if not matches:
        print("No matching credentials found.")
        return

    for c in matches:
        # expire server-side
        try:
            client.remove_credentials(c["name"], c["type"])
            print(f"Expired '{c['name']}' ({c['type']}) on Tracebit.")
        except TracebitError as e:
            print(f"Warning: Could not expire server-side: {e}", file=sys.stderr)

        if c["type"] == "aws":
            remove_aws_credentials(c.get("profile", ""))
            print(f"Removed AWS profile '{c.get('profile')}' from ~/.aws/")
        remove_credential(c["name"], c["type"])
        print(f"Removed credential '{c['name']}' ({c['type']}) from state.")


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
                             "e.g. 'staging', 'backup', 'legacy-admin' (default: from API)")
    p_aws.add_argument("--region", help="AWS region (default: from API)")
    p_aws.add_argument("--labels", nargs="*", metavar="KEY=VALUE",
                        help="Labels as key=value pairs")
    p_aws.add_argument("--force", action="store_true",
                        help="Overwrite existing profile")

    # refresh
    p_refresh = sub.add_parser("refresh", help="Refresh expiring credentials")
    p_refresh.add_argument("--hours", type=float, default=2,
                           help="Refresh credentials expiring within this many hours (default: 2)")

    # trigger
    p_trigger = sub.add_parser("trigger", help="Test-fire a canary credential")
    trigger_sub = p_trigger.add_subparsers(dest="trigger_type")
    p_trig_aws = trigger_sub.add_parser("aws", help="Trigger AWS canary")
    p_trig_aws.add_argument("--name", help="Credential name to trigger")

    # show
    sub.add_parser("show", help="Show deployed credentials")

    # remove
    p_remove = sub.add_parser("remove", help="Remove deployed credentials")
    p_remove.add_argument("--name", help="Name of credential to remove (all if omitted)")

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
    elif args.command == "refresh":
        cmd_refresh(args)
    elif args.command == "trigger":
        if not getattr(args, "trigger_type", None):
            p_trigger.print_help()
            sys.exit(1)
        if args.trigger_type == "aws":
            cmd_trigger_aws(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "remove":
        cmd_remove(args)


if __name__ == "__main__":
    main()
