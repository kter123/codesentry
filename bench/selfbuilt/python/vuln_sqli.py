# EXPECT: vulnerable | CWE-89 SQL 注入：用户输入拼进 f-string 查询
import sqlite3

def get_user(conn, user_id):
    return conn.execute(f"SELECT * FROM users WHERE id = {user_id}").fetchall()
