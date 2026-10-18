# M1 覆盖矩阵验证报告（agent.md §4.2 / NFR-1）

> 2026-10-18。每「语言×引擎」组合至少 1 个可运行验证样例；不可用组合显式降级并写进扫描报告元数据。

## 组合矩阵实测

| 语言 | Joern | Semgrep | CodeQL | 备注 |
|---|---|---|---|---|
| Python | 待 joern 装好后实测 pysrc2cpg | ✅ 检出 CWE-918 @ app.py:11 | 用户自装探测 | flask SSRF 样例 |
| Java | 待前端实测 javasrc2cpg | ✅ 检出 CWE-22 @ FileService.java:9 | 同上 | 源码级（D15） |
| JS/TS | 待 jssrc2cpg 实测 | ✅ 检出 CWE-1321 @ gadget.js:1 | 同上 | 类模式规则面 |
| Go | 待 gosrc2cpg 实测（新前端重点验证） | ✅ 检出 CWE-78 @ main.go:11 | 同上 | |
| C/C++ | 待 fuzzyc2cpg 实测 | ✅ 检出 CWE-134 @ main.c:6 | 同上 | |
| PHP | 待 php2cpg 实测（实验性重点验证） | ✅ 检出 CWE-200 @ bootstrap.php:5 | ❌ 不支持（§4.2） | |

## 降级标注（写入扫描报告元数据）

- CodeQL：平台不分发（§3 红线）；`--oss` 声明 + 用户自装时才启用——缺失即为 unavailable 降级，不阻塞
- joern：本机安装到挂载盘后矩阵测试将自动启用（skip 条件为 binary 探测）
- Semgrep：规则面 = `rules/codesentry-core.yml`（自研 Apache-2.0，随包分发）+ 用户自备第三方规则通道（FR-8）
- 官方 semgrep-rules 未采用：许可仅限内部业务使用（§3 红线）
