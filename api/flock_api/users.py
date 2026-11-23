"""จัดการผู้ใช้จากเครื่องเซิร์ฟเวอร์

    flock-users create <username> --role investigator    (ถามรหัสผ่าน ไม่รับทาง argument)
    flock-users disable <username>
"""

from __future__ import annotations

import argparse
import getpass

import psycopg

from flock_api import auth
from flock_api.config import Settings


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("username")
    c.add_argument("--role", choices=auth.ROLES, required=True)
    d = sub.add_parser("disable")
    d.add_argument("username")
    a = p.parse_args()

    with psycopg.connect(Settings.from_env().database_url) as conn:
        if a.cmd == "create":
            password = getpass.getpass("password (อย่างน้อย 12 ตัว): ")
            if password != getpass.getpass("again: "):
                raise SystemExit("รหัสผ่านไม่ตรงกัน")
            print("user_id", auth.create_user(conn, a.username, password, a.role))
        else:
            n = conn.execute("UPDATE users SET active = false WHERE username = %s", (a.username,)).rowcount
            conn.execute("DELETE FROM sessions WHERE user_id IN (SELECT user_id FROM users WHERE username = %s)",
                         (a.username,))
            print("disabled" if n else "not found")


if __name__ == "__main__":
    main()
