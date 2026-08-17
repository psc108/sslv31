"""Restore CLI — restore the application from an encrypted backup archive.

Usage:
    python -m app.restore --archive /path/to/backup-TIMESTAMP.enc [--force]
"""

import argparse
import sys
from pathlib import Path

from app.core.config import settings
from app.services.backup_engine import verify_backup, restore_backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore SSL Certificate Manager from backup")
    parser.add_argument("--archive", required=True, help="Path to encrypted backup archive")
    parser.add_argument("--force", action="store_true", help="Force restore without confirmation")
    parser.add_argument("--verify-only", action="store_true", help="Only verify, do not restore")

    args = parser.parse_args()
    filepath = Path(args.archive)

    if not filepath.exists():
        print(f"ERROR: Archive not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    # Verify
    print(f"Verifying backup: {filepath.name}")
    try:
        info = verify_backup(filepath)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: Verification failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  Valid: {info['valid']}")
    print(f"  Files: {len(info['files'])}")
    print(f"  Has database: {info['has_database']}")
    print(f"  Has self-certs: {info['has_self_certs']}")
    print(f"  Contents: {', '.join(info['files'])}")

    if args.verify_only:
        print("\nVerification passed. Archive is restorable.")
        sys.exit(0)

    # Confirmation
    if not args.force:
        print("\nWARNING: This will overwrite the current database and self-certificates.")
        print("         The service should be STOPPED before restoring.")
        confirm = input("Type 'yes' to proceed: ")
        if confirm.lower() != "yes":
            print("Restore cancelled.")
            sys.exit(0)

    # Restore
    print("\nRestoring...")
    try:
        result = restore_backup(filepath, force=args.force)
    except Exception as e:
        print(f"ERROR: Restore failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n✓ Restore complete.")
    print(f"  Source: {result['source']}")
    print(f"  Files restored: {', '.join(result['files_restored'])}")
    print(f"\n  Next steps:")
    print(f"  1. Run alembic upgrade head (if schema version differs)")
    print(f"  2. Start the certmanager service")
    print(f"  3. Verify: curl -sk https://localhost/api/v1/health")


if __name__ == "__main__":
    main()
