<?php
// EXPECT: clean | htmlspecialchars 转义后再输出
echo(htmlspecialchars($_GET["id"], ENT_QUOTES));
