# M1 覆盖矩阵验证报告（agent.md §4.2 / NFR-1）— 実测版

> 2026-10-18 实测（Joern v4.0.658 @ /Volumes/macOS/codesentry/tools/joern-cli；semgrep 1.181.0；JDK 24）

## 组合矩阵実測結果（tests/test_examples_matrix.py 真跑）

| 语言 | Joern 前端 | 実际命中 | Semgrep | CodeQL | 结论 |
|---|---|---|---|---|---|
| Python | pysrc2cpg ✅ | jssrf-sink @10,11（requests.get） | ✅ CWE-918 @11 | 用户自装 | **可用** |
| Java | javasrc2cpg ✅ | file-read @10（readString on concat path） | ✅ CWE-22 @8（拼串） | 用户自装 | **可用（源码级 D15）** |
| JS/TS | jssrc2cpg ✅ | proto-pollution @2（Object.keys 循环） | ✅ CWE-1321 @2 | 用户自装 | **可用** |
| Go | gosrc2cpg ✅ | cmd-injection @11（exec.Command 成员调用拆分形态） | ✅ CWE-78 @11 | 用户自装 | **可用**（memberCall 拆分形态 sink 名 `Command`） |
| C/C++ | c2cpg ✅（fuzzy 基础上语义完整） | format-string @6（printf 用户格式串） | ✅ CWE-134 @6 | 用户自装 | **可用** |
| PHP | php2cpg ❌ **实测崩溃**（X2CpgFrontend.run） | 降级 | ✅ CWE-200 @5 | 不支持（§4.2） | **显式降级：Semgrep 主力** |

## 关键实测发现（指针 M3）

1. **joern v4 的 println 走 stderr**，stdout 只有 overlay 提示——引擎解析必须合并两流
2. **joern-parse --language java 目录模式走 jimple2cpg**（吃字节码），源码级 Java 必须直接调 `javasrc2cpg`——已在引擎实现按前端直调
3. gosrc2cpg 把 `exec.Command(...)` 拆为 member-call `Command` 节点，sink 名按前端特性配置
4. CPG 文件名：pysrc2cpg 只存相对短名（`a`），M3 归一层需补全 relative path（当前 file 列为短名——SARIF 里 uri 仍可读）
5. joern 工作目录必须绝对路径（joern 的 project workspace 相对 CWD 会写进被扫仓——已修复）

## 降级标注（写入扫描报告元数据）

- CodeQL：平台不分发（§3）；`--oss` + 用户自装才启用；缺失/unavailable 不阻塞
- PHP：Joern 崩溃已实测（php2cpg at v4.0.658）——扫描元数据自动标「joern crashed → semgrep 单引擎输出」
- Semgrep 规则面：自研 `rules/codesentry-core.yml`（Apache-2.0）+ 用户通道（FR-8）；官方规则未使用（§3）
