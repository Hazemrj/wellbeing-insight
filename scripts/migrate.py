import os 
from pathlib import Path

import pymysql
from pymysql.constants import CLIENT

#read env variable DB_NAME, if not set, read wellbeing
DB_NAME = os.environ.get("DB_NAME", "wellbeing")

#find the path to the migration folder
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "sql" / "migrations"

#database connection
def main():
    conn = pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        charset="utf8mb4",
        client_flag=CLIENT.MULTI_STATEMENTS,
    )
    cur = conn.cursor()

    #creating database, using it, then creating table shema_migrations
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    cur.execute(f"USE `{DB_NAME}`")
    cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                     version    VARCHAR(100) NOT NULL PRIMARY KEY,
                     applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                   ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""")

    cur.execute("SELECT version FROM schema_migrations")
    applied = {row[0] for row in cur.fetchall()}


    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):         # 001_..., 002_... sort in the right order
        if path.name in applied:
            print("skip   ", path.name)
            continue
        try:
            cur.execute(path.read_text(encoding="utf-8"))      # run the file
            while cur.nextset():                               # read every result so an error in a later statement is raised
                pass
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            conn.commit()                                      # the file and its record are saved together
            print("applied", path.name)
        except Exception:
            conn.rollback()                                    
            raise
    conn.close()


if __name__ == "__main__":
    main()
