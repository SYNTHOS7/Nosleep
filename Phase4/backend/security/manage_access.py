"""Trusted operator CLI for live workspace membership changes; no public admin API."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Grant or revoke AegisGraph workspace membership")
    parser.add_argument("--uid", required=True, help="Neon Auth user ID (not an email address)")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--role", choices=["viewer", "editor", "admin", "remove"], required=True)
    parser.add_argument("--platform-admin", action="store_true", help="Grant platform administration explicitly")
    parser.add_argument("--revoke-platform-admin", action="store_true")
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args.workspace):
        parser.error("Workspace must use letters, digits, hyphens or underscores")
    if args.platform_admin and args.revoke_platform_admin:
        parser.error("Choose grant or revoke platform administrator, not both")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", args.uid):
        parser.error("Copy the exact user ID from Neon Auth")
    from backend.storage.neon_store import NeonStore
    flag = True if args.platform_admin else False if args.revoke_platform_admin else None
    NeonStore().set_access(args.uid, args.workspace, args.role, flag)
    print("Access updated. New API requests use the current membership record.")


if __name__ == "__main__":
    main()
