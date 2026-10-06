"""Generate the values needed to protect the app with a password.

    python scripts/set_password.py

Asks for a password (twice, not echoed) and prints the two settings the app
needs. Put them in the environment of the web app (on PythonAnywhere: the WSGI
file, see README). Run it again to change the password: every existing login
is invalidated.
"""
import getpass
import secrets
import sys

from werkzeug.security import generate_password_hash


def main():
    pw = getpass.getpass('New password: ')
    if len(pw) < 10:
        sys.exit('Use at least 10 characters.')
    if pw != getpass.getpass('Repeat password: '):
        sys.exit('The two passwords differ.')
    print('\nAdd these lines to the WSGI file (before the app is imported):\n')
    print("import os")
    print(f"os.environ['APP_PASSWORD_HASH'] = {generate_password_hash(pw)!r}")
    print(f"os.environ['SECRET_KEY'] = {secrets.token_hex(32)!r}   # keep the same value across restarts")


if __name__ == '__main__':
    main()
