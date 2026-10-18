// EXPECT: vulnerable | CWE-89 字符串拼接进 query
const db = { query: () => {} };

function getUser(id) {
  return db.query("SELECT * FROM users WHERE id = " + id);
}
