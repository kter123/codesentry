# EXPECT: clean | 参数化查询
import sqlite3

def get_user(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchall()
