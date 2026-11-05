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


def cmd_serve(args) -> int:
    import uvicorn

    from moth_server.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="moth-server")
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("init-owner", help="one-time creation of the LK5T owner account (interactive)")
    o.add_argument("--email")
    o.add_argument("--password-stdin", action="store_true", help="read the password from stdin (automation)")
    o.set_defaults(fn=cmd_init_owner)
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
