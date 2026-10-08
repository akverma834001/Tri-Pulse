"""Command Line Interface for administrative tasks such as password resets."""

import argparse
import secrets
import sys
from backend.database import SessionLocal, Base, engine
from backend.models import User
from backend.auth import hash_password


def reset_password(email: str, new_password: str = None) -> None:
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email.strip().lower()).first()
        if not user:
            print(f"Error: User with email '{email}' not found.", file=sys.stderr)
            sys.exit(1)

        if not new_password:
            # Generate a 12-char secure temporary password
            new_password = secrets.token_urlsafe(9) + "A1!"

        if len(new_password) < 10:
            print("Error: Password must be at least 10 characters.", file=sys.stderr)
            sys.exit(1)

        user.password_hash = hash_password(new_password)
        db.commit()
        print(f"Successfully reset password for user '{user.email}'.")
        print(f"New Password: {new_password}")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Project Pulse CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reset_parser = subparsers.add_parser("reset-password", help="Reset password for a user account")
    reset_parser.add_argument("email", help="User email address")
    reset_parser.add_argument("--password", "-p", help="Optional new password (generated if omitted)")

    args = parser.parse_args()
    if args.command == "reset-password":
        reset_password(args.email, args.password)


if __name__ == "__main__":
    main()
