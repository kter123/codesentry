<?php
// EXPECT: vulnerable | CWE-79 echo 直接输出 $_GET
echo($_GET["id"]);
