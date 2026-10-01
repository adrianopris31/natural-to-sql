#!/usr/bin/env python3
"""CLI utility for managing Natural-to-SQL external API keys.

Usage:
    uv run python scripts/manage_keys.py new "Slack Bot" --scope query --quota 1000
    uv run python scripts/manage_keys.py new "Admin CI" --scope admin
    uv run python scripts/manage_keys.py list [--all]
    uv run python scripts/manage_keys.py revoke <key_hash_prefix>
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure 'backend' directory is in Python path
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Ensure working directory resolves to backend or app
os.environ.setdefault("APP_DB_PATH", str(BACKEND_DIR / "data" / "app.db"))

from app.core.auth import issue_api_key
from app.store.database import close_app_db, init_app_db, list_api_keys, revoke_api_key


async def cmd_new(args: argparse.Namespace) -> None:
    await init_app_db()
    try:
        plaintext_key, key_model = await issue_api_key(
            label=args.label,
            scope=args.scope,
            daily_quota=args.quota,
        )
        print("\n==================================================================")
        print("  NEW API KEY CREATED")
        print("==================================================================")
        print(f"  Key Secret:     {plaintext_key}")
        print("  ⚠️  SAVE THIS KEY NOW. It will NOT be shown again.")
        print("------------------------------------------------------------------")
        print(f"  Prefix:         {key_model.key_hash[:12]}")
        print(f"  Label:          {key_model.label}")
        print(f"  Scope:          {key_model.scope}")
        print(f"  Daily Quota:    {key_model.daily_quota} (0 = unlimited)")
        print(f"  Created At:     {key_model.created_at.isoformat()}")
        print("==================================================================\n")
    finally:
        await close_app_db()


async def cmd_list(args: argparse.Namespace) -> None:
    await init_app_db()
    try:
        keys = await list_api_keys(include_revoked=args.all)
        if not keys:
            print("No API keys found.")
            return

        print(
            f"{'PREFIX':<14} {'LABEL':<22} {'SCOPE':<8} {'QUOTA':<8} {'STATUS':<10} {'CREATED':<22} {'LAST USED'}"
        )
        print("-" * 105)
        for k in keys:
            status = "REVOKED" if k["revoked"] else "ACTIVE"
            last_used = k["last_used_at"] or "never"
            created = k["created_at"][:19]
            print(
                f"{k['key_hash_prefix']:<14} {k['label'][:20]:<22} {k['scope']:<8} "
                f"{k['daily_quota']:<8} {status:<10} {created:<22} {last_used}"
            )
    finally:
        await close_app_db()


async def cmd_revoke(args: argparse.Namespace) -> None:
    await init_app_db()
    try:
        success = await revoke_api_key(args.prefix)
        if success:
            print(f"Successfully revoked API key with prefix '{args.prefix}'.")
        else:
            print(f"Error: No active API key found matching prefix '{args.prefix}'.")
            sys.exit(1)
    finally:
        await close_app_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Natural-to-SQL external API keys.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # new
    p_new = subparsers.add_parser("new", help="Create a new API key")
    p_new.add_argument("label", help="Descriptive label (e.g. 'Slack Bot', 'ETL Worker')")
    p_new.add_argument(
        "--scope",
        choices=["query", "admin"],
        default="query",
        help="Access scope (default: query)",
    )
    p_new.add_argument(
        "--quota",
        type=int,
        default=0,
        help="Daily request quota (default: 0 = unlimited)",
    )
    p_new.set_defaults(func=cmd_new)

    # list
    p_list = subparsers.add_parser("list", help="List registered API keys")
    p_list.add_argument(
        "--all",
        action="store_true",
        help="Include revoked keys in listing",
    )
    p_list.set_defaults(func=cmd_list)

    # revoke
    p_revoke = subparsers.add_parser("revoke", help="Revoke an API key by its hash prefix")
    p_revoke.add_argument("prefix", help="API key hash prefix (at least 8 characters)")
    p_revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
