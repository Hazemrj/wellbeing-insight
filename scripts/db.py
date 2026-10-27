"""One place to open a MySQL connection. Settings come from environment variables, never from code."""
import os

import pymysql
from pymysql.constants import CLIENT

DB_NAME = os.environ.get("DB_NAME", "wellbeing")
ETL_USER = os.environ.get("ETL_USER", "wb_etl_user")
ETL_PASSWORD = os.environ.get("ETL_PASSWORD", "")      # set it with:  set ETL_PASSWORD=...


def connect(local_infile=False, multi_statements=False):
    """Connect as the wb_etl user (the account that loads and cleans data)."""
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=ETL_USER, password=ETL_PASSWORD, database=DB_NAME, charset="utf8mb4",
        local_infile=local_infile,                                           # client side of LOAD DATA LOCAL
        client_flag=CLIENT.MULTI_STATEMENTS if multi_statements else 0,
        autocommit=False,
    )
