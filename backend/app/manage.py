"""Local operator administration. Password input is hidden; device keys print only once."""
import argparse
import getpass
import json
import secrets
import sys
from pathlib import Path
from sqlalchemy import delete, select
from .auth import create_password_reset, digest, hasher
from .config import ROOT, settings
from .db import Session, iso, parse, transaction, utcnow
from .models import AuthSession, PasswordReset, Device, Runtime, SecurityAudit, User
from .provider_contracts import NetworkImport, TimetableImport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for action in ["promote-admin", "reset-password", "create-password-reset", "disable-user", "verify-contributor"]:
        command = commands.add_parser(action)
        command.add_argument("username")
    command = commands.add_parser("provision-device")
    command.add_argument("node_id")
    command = commands.add_parser("revoke-device")
    command.add_argument("node_id")
    command = commands.add_parser("install-network")
    command.add_argument("file")
    command = commands.add_parser("import-timetable")
    command.add_argument("file")
    commands.add_parser("worker-health")
    commands.add_parser("export-schemas")
    args = parser.parse_args()
    if args.command == "create-password-reset":
        from urllib.parse import urlencode
        with transaction() as session:
            user = session.scalar(select(User).where(User.username == args.username.strip().lower()).with_for_update())
            if not user:
                raise ValueError("Unknown account")
            token, expires_at = create_password_reset(session, user.id)
            username = user.username
        origin = settings.cors_origins.split(",")[0].strip().rstrip("/")
        print("Private, one-time recovery link (expires "+expires_at+"):")
        print(origin+"/#"+urlencode({"reset-password": token, "username": username}))
        print("Share only with the account owner. Existing password and sessions work until the link is redeemed.")
        return
    if args.command == "install-network":
        source = Path(args.file)
        if source.stat().st_size > 16*1024*1024:
            raise ValueError("Network configuration exceeds 16 MB")
        network = NetworkImport.model_validate_json(source.read_text(encoding="utf-8-sig"))
        target = ROOT / ".local" / "provider" / "network.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(network.model_dump_json(indent=2))
        temporary.replace(target)
        print("Validated network installed. Set NETWORK_FILE=.local/provider/network.json and restart both API and worker.")
        return
    if args.command == "export-schemas":
        target = ROOT / "hardware" / "contracts"
        target.mkdir(exist_ok=True)
        for name, model in [("network", NetworkImport), ("timetable", TimetableImport)]:
            (target / (name+".schema.json")).write_text(json.dumps(model.model_json_schema(), indent=2))
        print("Operator integration schemas exported to hardware/contracts.")
        return
    if args.command == "worker-health":
        with Session() as session:
            worker = session.get(Runtime, "worker")
            valid = worker and 0 <= (utcnow()-parse(worker.value["at"])).total_seconds() < 10
        sys.exit(0 if valid else 1)
    if args.command == "import-timetable":
        from .operations import import_timetable
        body = TimetableImport.model_validate_json(Path(args.file).read_text(encoding="utf-8-sig"))
        with transaction() as session:
            result = import_timetable(session, body, utcnow())
            session.add(SecurityAudit(at=iso(utcnow()), actor_id="local-operator", action="timetable_imported"))
        print(json.dumps(result))
        return
    with transaction() as session:
        if args.command in {"provision-device", "revoke-device"}:
            device = session.get(Device, args.node_id)
            if args.command == "provision-device":
                from .network import CONFIG
                if not CONFIG or not any(cp["node_id"] == args.node_id for cp in CONFIG["checkpoints"]):
                    raise ValueError("Provision only a node present in the approved network configuration")
                token = secrets.token_urlsafe(48)
                if device is None:
                    device = Device(node_id=args.node_id, created_at=iso(utcnow()))
                    session.add(device)
                device.key_hash, device.disabled = digest(token), False
            elif device:
                device.disabled = True
            else:
                raise ValueError("Unknown device")
            session.add(SecurityAudit(at=iso(utcnow()), actor_id=args.node_id, action=args.command))
        else:
            user = session.scalar(select(User).where(User.username == args.username.lower()).with_for_update())
            if not user:
                raise ValueError("Create the account in the app before administering it")
            if args.command == "promote-admin":
                user.role = "admin"
            elif args.command == "verify-contributor":
                user.verified_contributor = True
            elif args.command == "disable-user":
                user.disabled = True
            else:
                password = getpass.getpass("New password (12–128 characters): ")
                if not 12 <= len(password) <= 128 or password != getpass.getpass("Confirm new password: "):
                    raise ValueError("Password length or confirmation is invalid")
                user.password_hash = hasher.hash(password)
            session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            session.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
            session.add(SecurityAudit(at=iso(utcnow()), actor_id=user.id, action=args.command))
    if args.command == "provision-device":
        print("Save this device credential securely; it cannot be retrieved again:")
        print(token)
    else:
        print("Change saved; affected sessions or device access have been revoked.")


if __name__ == "__main__":
    main()
