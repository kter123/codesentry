// EXPECT: vulnerable | CWE-89 fmt.Sprintf 拼 SQL
package main

import (
	"database/sql"
	"fmt"
)

func GetUser(db *sql.DB, id string) (*sql.Row, error) {
	return db.Query(fmt.Sprintf("SELECT * FROM users WHERE id = %s", id))
}
