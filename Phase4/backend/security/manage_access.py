"""Trusted operator CLI for live workspace membership changes; no public admin API."""
import argparse
import hashlib


def main():
    parser = argparse.ArgumentParser(description="Grant or revoke AegisGraph workspace membership")
    parser.add_argument("--uid", required=True, help="Firebase Authentication user UID")
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
    from firebase_admin import auth, firestore
    from backend.storage.firebase_store import get_firebase_app
    app = get_firebase_app()
    auth.get_user(args.uid, app=app)  # Fail on a mistyped or nonexistent identity.
    db = firestore.client(app=app)
    reference = db.collection("aegis_users").document(hashlib.sha256(args.uid.encode()).hexdigest())

    @firestore.transactional
    def update(transaction):
        old = reference.get(transaction=transaction).to_dict() or {}
        memberships = dict(old.get("workspaces", {}))
        if args.role == "remove":
            memberships.pop(args.workspace, None)
        else:
            memberships[args.workspace] = args.role
        old.update({"uid": args.uid, "workspaces": memberships})
        if args.platform_admin or args.revoke_platform_admin:
            old["platform_admin"] = args.platform_admin
        transaction.set(reference, old)

    update(db.transaction())
    print("Access updated. New API requests use the current membership record.")


if __name__ == "__main__":
    main()
