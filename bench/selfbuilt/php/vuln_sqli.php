<?php
// EXPECT: vulnerable | CWE-89 拼接进 query
$conn->query("SELECT * FROM users WHERE id = " . $id);
