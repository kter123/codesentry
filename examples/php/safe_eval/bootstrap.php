<?php
// CVE 模式：CWE-200 Stack Trace 泄漏——错误详情直接回显给用户
declare(strict_types=1);

ini_set('display_errors', '1'); // sink：line 5
error_reporting(E_ALL);

require __DIR__ . '/config.php';
