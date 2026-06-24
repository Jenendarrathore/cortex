#!/usr/bin/env python3
"""Interactive PostgreSQL admin CLI.

Features:
- Create / drop databases
- Create / drop users (roles)
- Grant user access to database
- Change user password
- List databases and users
- Run ad-hoc SQL against a selected database

Requires:
    pip install psycopg[binary]
"""

from __future__ import annotations

import getpass
import os
import sys
from dataclasses import dataclass

try:
    import psycopg
    from psycopg import sql
except ImportError:
    print("Missing dependency: psycopg")
    print("Install with: pip install 'psycopg[binary]'")
    sys.exit(1)


@dataclass
class AdminConfig:
    host: str
    port: int
    admin_db: str
    admin_user: str
    admin_password: str


def ask(prompt: str, default: str | None = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    full_prompt = f"{prompt}{suffix}: "
    if secret:
        value = getpass.getpass(full_prompt)
    else:
        value = input(full_prompt).strip()
    if not value and default is not None:
        return default
    return value


def ask_yes_no(prompt: str, default_yes: bool = True) -> bool:
    default_label = "Y/n" if default_yes else "y/N"
    value = input(f"{prompt} [{default_label}]: ").strip().lower()
    if not value:
        return default_yes
    return value in {"y", "yes"}


def connect(config: AdminConfig, dbname: str | None = None):
    return psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=dbname or config.admin_db,
        user=config.admin_user,
        password=config.admin_password,
        autocommit=True,
    )


def create_database(config: AdminConfig):
    db_name = ask("New database name")
    owner = ask("Owner role (leave blank for none)", default="")

    with connect(config) as conn, conn.cursor() as cur:
        if owner:
            query = sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(db_name), sql.Identifier(owner)
            )
        else:
            query = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name))
        cur.execute(query)
    print(f"Database '{db_name}' created.")


def drop_database(config: AdminConfig):
    db_name = ask("Database name to drop")
    force = ask_yes_no("Terminate active connections and force drop?", default_yes=True)

    with connect(config) as conn, conn.cursor() as cur:
        if force:
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (db_name,),
            )
        cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(db_name)))
    print(f"Database '{db_name}' dropped.")


def drop_table(config: AdminConfig):
    db_name = ask("Database name")
    table_name = ask("Table name to drop")
    if not ask_yes_no(
        f"Are you sure you want to drop table '{table_name}' from '{db_name}'?",
        default_yes=False,
    ):
        print("Cancelled.")
        return

    with connect(config, dbname=db_name) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(table_name)))
    print(f"Table '{table_name}' dropped from '{db_name}'.")


def truncate_table(config: AdminConfig):
    db_name = ask("Database name")
    table_name = ask("Table name to clear data from")
    restart_identity = ask_yes_no("Restart identity/serial counters?", default_yes=True)
    cascade = ask_yes_no("Cascade to dependent tables?", default_yes=False)

    if not ask_yes_no(
        f"Delete all rows from '{table_name}' in '{db_name}'?", default_yes=False
    ):
        print("Cancelled.")
        return

    with connect(config, dbname=db_name) as conn, conn.cursor() as cur:
        query = sql.SQL("TRUNCATE TABLE {}").format(sql.Identifier(table_name))
        if restart_identity:
            query += sql.SQL(" RESTART IDENTITY")
        if cascade:
            query += sql.SQL(" CASCADE")
        cur.execute(query)
    print(f"All data cleared from '{table_name}' in '{db_name}'.")


def create_user(config: AdminConfig):
    username = ask("New username")
    password = ask("Password", secret=True)
    can_createdb = ask_yes_no("Allow CREATEDB?", default_yes=False)
    is_superuser = ask_yes_no("Grant SUPERUSER?", default_yes=False)

    with connect(config) as conn, conn.cursor() as cur:
        attrs = [sql.SQL("LOGIN")]
        if can_createdb:
            attrs.append(sql.SQL("CREATEDB"))
        if is_superuser:
            attrs.append(sql.SQL("SUPERUSER"))

        create_query = sql.SQL("CREATE ROLE {} WITH {}").format(
            sql.Identifier(username), sql.SQL(" ").join(attrs)
        )
        cur.execute(create_query)
        set_password_query = sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
            sql.Identifier(username), sql.Literal(password)
        )
        cur.execute(set_password_query)
    print(f"User '{username}' created.")


def drop_user(config: AdminConfig):
    username = ask("Username to drop")
    with connect(config) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(username)))
    print(f"User '{username}' dropped.")


def change_password(config: AdminConfig):
    username = ask("Username")
    password = ask("New password", secret=True)
    with connect(config) as conn, conn.cursor() as cur:
        query = sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
            sql.Identifier(username), sql.Literal(password)
        )
        cur.execute(query)
    print(f"Password updated for '{username}'.")


def assign_user_to_db(config: AdminConfig):
    db_name = ask("Database name")
    username = ask("Username")

    with connect(config) as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(db_name), sql.Identifier(username)
            )
        )

    with connect(config, dbname=db_name) as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(username))
        )
        cur.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(sql.Identifier(username))
        )
        cur.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(sql.Identifier(username))
        )

    print(f"User '{username}' granted basic access on database '{db_name}'.")


def list_databases(config: AdminConfig):
    with connect(config) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT datname
            FROM pg_database
            WHERE datistemplate = false
            ORDER BY datname
            """
        )
        rows = cur.fetchall()

    print("\nDatabases:")
    for (name,) in rows:
        print(f"- {name}")


def list_users(config: AdminConfig):
    with connect(config) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT rolname, rolsuper, rolcreatedb
            FROM pg_roles
            ORDER BY rolname
            """
        )
        rows = cur.fetchall()

    print("\nUsers/Roles:")
    for name, is_super, can_createdb in rows:
        tags = []
        if is_super:
            tags.append("SUPERUSER")
        if can_createdb:
            tags.append("CREATEDB")
        tag_str = f" ({', '.join(tags)})" if tags else ""
        print(f"- {name}{tag_str}")


def list_db_info(config: AdminConfig):
    with connect(config) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT datname
            FROM pg_database
            WHERE datistemplate = false
            ORDER BY datname
            """
        )
        db_rows = cur.fetchall()

    if not db_rows:
        print("No databases found.")
        return

    print("\nAvailable databases:")
    for idx, (db_name,) in enumerate(db_rows, start=1):
        print(f"{idx}. {db_name}")

    choice = ask("Select database number")
    if not choice.isdigit():
        print("Invalid selection.")
        return

    db_index = int(choice)
    if db_index < 1 or db_index > len(db_rows):
        print("Invalid selection.")
        return

    selected_db = db_rows[db_index - 1][0]

    with connect(config) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.datname, r.rolname
            FROM pg_database d
            JOIN pg_roles r ON d.datdba = r.oid
            WHERE d.datname = %s
            """,
            (selected_db,),
        )
        db_info = cur.fetchone()

        cur.execute(
            """
            SELECT r.rolname, r.rolsuper, r.rolcreatedb, has_database_privilege(r.rolname, %s, 'CONNECT')
            FROM pg_roles r
            ORDER BY r.rolname
            """,
            (selected_db,),
        )
        role_rows = cur.fetchall()

    print("\nDatabase Info:")
    print(f"Name: {db_info[0]}")
    print(f"Owner: {db_info[1]}")

    print("\nUsers with CONNECT privilege:")
    any_connect = False
    for role_name, is_super, can_createdb, can_connect in role_rows:
        if not can_connect:
            continue
        any_connect = True
        tags = []
        if is_super:
            tags.append("SUPERUSER")
        if can_createdb:
            tags.append("CREATEDB")
        tag_str = f" ({', '.join(tags)})" if tags else ""
        print(f"- {role_name}{tag_str} | password: not readable (stored securely)")
    if not any_connect:
        print("- None")


def run_sql(config: AdminConfig):
    db_name = ask("Database to connect")
    print("Enter SQL (end with a single line containing only ';'):")

    lines: list[str] = []
    while True:
        line = input()
        if line.strip() == ";":
            break
        lines.append(line)

    query = "\n".join(lines).strip()
    if not query:
        print("No SQL entered.")
        return

    with connect(config, dbname=db_name) as conn, conn.cursor() as cur:
        cur.execute(query)
        if cur.description:
            rows = cur.fetchall()
            headers = [d.name for d in cur.description]
            print(" | ".join(headers))
            print("-+-".join("-" * len(h) for h in headers))
            for row in rows:
                print(" | ".join(str(c) for c in row))
        else:
            print(f"Query executed. Rows affected: {cur.rowcount}")


MENU = {
    "1": ("Create database", create_database),
    "2": ("Drop/Delete database", drop_database),
    "3": ("Create user", create_user),
    "4": ("Drop user", drop_user),
    "5": ("Change user password", change_password),
    "6": ("Assign user to database (basic grants)", assign_user_to_db),
    "7": ("List databases", list_databases),
    "8": ("List users/roles", list_users),
    "9": ("Run SQL on a database", run_sql),
    "10": ("Drop/Delete table", drop_table),
    "11": ("Clear table data (TRUNCATE)", truncate_table),
    "12": ("List DB info (select DB, show owner/users)", list_db_info),
    "0": ("Exit", None),
}

# Optional local fallback password. Prefer setting PGPASSWORD in your shell.
DEFAULT_ADMIN_PASSWORD = "admin"


def main():
    print("PostgreSQL Interactive Admin CLI")
    print("-" * 34)

    config = AdminConfig(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        admin_db=os.getenv("PGDATABASE", "postgres"),
        admin_user=os.getenv("PGUSER", getpass.getuser()),
        admin_password=os.getenv("PGPASSWORD", DEFAULT_ADMIN_PASSWORD),
    )

    print(
        f"Using connection: host={config.host} port={config.port} "
        f"db={config.admin_db} user={config.admin_user}"
    )

    try:
        with connect(config) as _:
            pass
    except Exception as exc:
        print(f"Connection failed: {exc}")
        sys.exit(1)

    while True:
        print("\nSelect an operation:")
        for key, (label, _) in MENU.items():
            print(f"{key}. {label}")

        choice = input("Choice: ").strip()
        if choice == "0":
            print("Bye.")
            return

        item = MENU.get(choice)
        if not item:
            print("Invalid choice. Try again.")
            continue

        _, action = item
        try:
            action(config)
        except Exception as exc:
            print(f"Error: {exc}")


if __name__ == "__main__":
    main()
