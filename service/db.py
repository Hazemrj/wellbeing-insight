"""Reads a member snapshot from MySQL. This is the ONLY place where the insight service talks to the database.

The service connects as wb_app_user, the account that can only SELECT from member_snapshots (see sql/roles.sql).
Settings come from environment variables, never from the code:
    APP_DB_HOST, APP_DB_PORT, APP_DB_USER, APP_DB_PASSWORD, APP_DB_NAME
"""
import json
import os

import pymysql


class MemberNotFound(Exception):
    """The database is fine, but there is no snapshot for this member code. The API turns it into 404."""


class DatabaseUnavailable(Exception):
    """We could not reach the database, or it refused the query. The API turns it into 503."""


# The "%s" is a placeholder. PyMySQL sends the member code separately from the SQL text,
# so whatever the caller types can never become part of the SQL. This is what prevents SQL injection.
SNAPSHOT_SQL = (
    "SELECT snapshot FROM member_snapshots "
    "WHERE member_code = %s "                       # member_code is the column added by migration 007
    "ORDER BY as_of DESC LIMIT 1"                    # the newest snapshot of this member
)


def connect():
    """Open a new connection as the read-only user. The settings are read now, not when the file is imported."""
    return pymysql.connect(
        host=os.environ.get("APP_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("APP_DB_PORT", "3306")),
        user=os.environ.get("APP_DB_USER", "wb_app_user"),
        password=os.environ.get("APP_DB_PASSWORD", ""),
        database=os.environ.get("APP_DB_NAME", "wellbeing"),
        charset="utf8mb4",
        connect_timeout=int(os.environ.get("APP_DB_TIMEOUT", "3")),    # do not wait forever for a dead database
        read_timeout=int(os.environ.get("APP_DB_TIMEOUT", "3")),
    )


def fetch_snapshot(member_code: str) -> dict:
    """Return the newest snapshot of one member as a Python dict.

    Raises MemberNotFound if the member has no snapshot, DatabaseUnavailable if MySQL cannot be used.
    """
    try:
        conn = connect()
    except (pymysql.MySQLError, OSError) as e:        # refused, timed out, wrong password ...
        raise DatabaseUnavailable(f"cannot connect: {type(e).__name__}") from e
    try:
        with conn.cursor() as cur:                      # "with" closes the cursor for us
            cur.execute(SNAPSHOT_SQL, (member_code,))   # the member code travels as a parameter, not inside the text
            row = cur.fetchone()
    except (pymysql.MySQLError, OSError) as e:
        raise DatabaseUnavailable(f"query failed: {type(e).__name__}") from e
    finally:
        conn.close()                                    # always give the connection back, even after an error
    if row is None:
        raise MemberNotFound(member_code)
    value = row[0]
    return json.loads(value) if isinstance(value, (str, bytes)) else value    # MySQL returns JSON as text
