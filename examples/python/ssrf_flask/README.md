# ssrf_flask — Python 样例（CWE-918）

用户可控 URL 直接 requests.get（app.py:10）。用于 M1 覆盖矩阵验证：joern(pysrc2cpg)/semgrep 检出 SSRF。
