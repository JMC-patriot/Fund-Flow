import os
from contextlib import contextmanager
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

# Supabase: Render에서는 IPv4 호환 'Session pooler' 연결 문자열 사용
pool = ConnectionPool(
    os.environ["DATABASE_URL"], min_size=1, max_size=5, open=False,
    kwargs={"row_factory": dict_row, "prepare_threshold": None},
)


@contextmanager
def cursor():
    with pool.connection() as con, con.cursor() as cur:
        yield cur


def fetch_all(sql, params=None):
    with cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


def fetch_one(sql, params=None):
    with cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchone()
