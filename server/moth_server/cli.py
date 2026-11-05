"""``moth-server`` command-line interface (run on the server by the owner)."""

from __future__ import annotations

import argparse
import getpass
import sys

from moth_server.config import Settings


def cmd_init_owner(args) -> int:
    from moth_server.accounts import AccountError, init_owner, owner_exists
    from moth_server.db import Database
    from moth_server.security import EMAIL_RE, OWNER_USERNAME, password_problem

    s = Settings.from_env().ensure_dirs()
    db = Database(s.db_url)
    db.migrate()
    if owner_exists(db):
        print("The owner account already exists. This command can only be used once.", file=sys.stderr)
        return 1
    email = args.email or input("Owner email: ").strip()
    if not EMAIL_RE.match(email):
        print("Invalid email address.", file=sys.stderr)
        return 1
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass(f"Choose a password for {OWNER_USERNAME}: ")
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords do not match.", file=sys.stderr)
            return 1
    if problem := password_problem(password, OWNER_USERNAME, email):
        print(problem, file=sys.stderr)
        return 1
    try:
        uid = init_owner(db, email, password)
    except AccountError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"Owner account {OWNER_USERNAME} created (id {uid}).")
    return 0


def cmd_training_init(args) -> int:
    from pathlib import Path

    from moth.community.coordinator import init_coordinator
    from moth.community.protocol import TrainSpec

    s = Settings.from_env().ensure_dirs()
    cfg = init_coordinator(s.data_dir / "coordinator", Path(args.model), Path(args.dataset), args.shards,
                           TrainSpec(steps=args.steps, lr=args.lr, batch_size=args.batch_size, seq_len=args.seq_len),
                           args.min_contributions)
    print(f"Training coordinator initialised: {len(cfg['shards'])} shards, round 0, checkpoint v0.")
    return 0


def cmd_worker_release(args) -> int:
    import hashlib
    import json
    import shutil
    from pathlib import Path

    s = Settings.from_env().ensure_dirs()
    src = Path(args.tarball)
    h = hashlib.sha256(src.read_bytes()).hexdigest()
    dest = s.storage_dir / "worker"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest / src.name)
    (dest / "manifest.json").write_text(json.dumps({"version": args.version, "file": src.name, "sha256": h}, indent=2))
    print(f"Published MOTH Worker {args.version}: {src.name} sha256={h}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from moth_server.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=False)
    return 0


def cmd_migrate(args) -> int:
    """Schema migrations. ``--plan`` prints JSON for the update agent and changes nothing."""
    import json

    from moth_server.db import SCHEMA_VERSION, Database, MigrationApprovalRequired

    s = Settings.from_env().ensure_dirs()
    db = Database(s.db_url)
    if args.plan:
        print(json.dumps({"current": db.schema_version(), "target": SCHEMA_VERSION, "pending": db.pending_migrations()}))
        return 0
    if args.approve:
        approved = sorted(db.approved_migrations() | set(args.approve))
        db.set_config("approved_destructive_migrations", approved)
    try:
        applied = db.migrate(approve_destructive=args.approve_destructive)
    except MigrationApprovalRequired as e:
        print(f"error: {e}. Approve it in the Owner Dashboard or re-run with --approve-destructive.", file=sys.stderr)
        return 3
    print(f"schema version {db.schema_version()} (applied: {applied or 'none'})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="moth-server")
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("init-owner", help="one-time creation of the LK5T owner account (interactive)")
    o.add_argument("--email")
    o.add_argument("--password-stdin", action="store_true", help="read the password from stdin (automation)")
    o.set_defaults(fn=cmd_init_owner)
    t = sub.add_parser("training-init", help="initialise the training coordinator from a base model and dataset")
    t.add_argument("--model", required=True, help="exported MOTH model directory (initial checkpoint)")
    t.add_argument("--dataset", required=True, help="prepared dataset directory (licensed, public data only)")
    t.add_argument("--shards", type=int, default=16)
    t.add_argument("--steps", type=int, default=200)
    t.add_argument("--lr", type=float, default=3e-4)
    t.add_argument("--batch-size", type=int, default=8)
    t.add_argument("--seq-len", type=int, default=512)
    t.add_argument("--min-contributions", type=int, default=2)
    t.set_defaults(fn=cmd_training_init)
    w = sub.add_parser("worker-release", help="publish a MOTH Worker release tarball for one-command enrollment")
    w.add_argument("tarball")
    w.add_argument("--version", required=True)
    w.set_defaults(fn=cmd_worker_release)
    m = sub.add_parser("migrate", help="apply database migrations (destructive ones need approval)")
    m.add_argument("--plan", action="store_true", help="print pending migrations as JSON and exit")
    m.add_argument("--approve-destructive", action="store_true")
    m.add_argument("--approve", type=int, action="append", default=[], help="approve one destructive migration")
    m.set_defaults(fn=cmd_migrate)
    s = sub.add_parser("serve", help="run the server")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8900)
    s.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
