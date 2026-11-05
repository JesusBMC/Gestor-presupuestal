import pyodbc
import os

DB_PATH = os.environ["DB_PATH"]


def get_connection():
    conn = pyodbc.connect(
        rf"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={DB_PATH};",
        autocommit=False
    )
    conn.setdecoding(pyodbc.SQL_CHAR, encoding='latin1')
    conn.setdecoding(pyodbc.SQL_WCHAR, encoding='latin1')
    conn.setencoding(encoding='utf-8')
    return conn


def execute_query(query, params=(), fetch=True, is_write=False):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)

        if fetch:
            columns = [c[0] for c in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            conn.commit()
            return results

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        print(f"[DB ERROR] {e}")
        raise

    finally:
        conn.close()