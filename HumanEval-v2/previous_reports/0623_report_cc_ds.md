# CodeGenEval 测评报告

**Agent**: Claude Code (DeepSeekv4pro) | **Benchmark**: HumanEval_cangjie.jsonl (睿鸣修改版) | **语言**: cangjie
**生成时间**: 2026-06-23T10:30:00+08:00 | **n**: 1 | **k**: 1

## 总体指标

| 指标 | 值 | 单位 | 说明 |
|------|-----|------|------|
| Benchmark | HumanEval_cangjie.jsonl | — | — |
| 语言 | cangjie | — | — |
| 样本总数 | 164 | — | 所有 Task 样本之和 |
| 平均每 Task 样本数 | 1 | — | 由 samples.jsonl 决定 |
| k 值 | 1 | — | pass@k 参数 |
| Task 总数 | 164 | — | — |
| **compilation_success_rate** | 0.4024 | ratio | 平均编译成功率 |
| **avg_test_pass_ratio** | 0.3415 | ratio | 平均测试通过率（编译失败记为 0） |
| **pass@1** | 0.3415 | ratio | — |
| **total_time** | 56.94 | min | Agent 生成总耗时 |
| **avg_time_per_task** | 20.83 | s | 每个 Task 平均生成耗时 |
| **total_api_cost** | N/A | USD | 总 API 开销 |
| **avg_api_cost** | N/A | USD | 平均每 Task API 开销 |
| **total_tokens** | 231137 | tokens | 总 token 消耗（输入 + 输出） |
| **avg_total_tokens** | 1409.4 | tokens | 平均每 Task token 消耗 |
| **composite_score** | 19.49 | 分(0-100) | 综合评分（basic评估体系） |

> 注：system prompt 包含 15 条 Cangjie 精确语法规则（提炼自 CangjieSkills）。编译环境为 Cangjie SDK 1.0.5 (`cjc --output-type=staticlib`)，测试执行使用 `cjc --test`。本批次使用同事提供的修改版 benchmark，task_id 格式为 `HumanEval/0`~`HumanEval/163`。
> total_tokens = total_input_tokens + total_output_tokens；input_tokens 为发送给模型的 prompt 所消耗的 token 数，output_tokens 为模型生成的 completion 所消耗的 token 数，二者之和反映单次盲生成的总 token 开销

## 测试未通过原因分析

164 个 Task 中，**98 个编译失败**（CSR = 40.24%），**10 个测试运行失败**（测试通过率 = 84.85%）。最终 56 个 Task 完全通过（pass@1 = 34.15%）。

### 编译失败（98 个 Task）

| 失败类型 | 数量 | 说明 |
|----------|------|------|
| 函数体缺失 | 24 | LLM 未生成有效代码（空白或仅 TODO），函数体为空 |
| 未声明标识符 `ArrayList` | 20 | 使用了 `ArrayList` 但缺少 `import std.collection.*` |
| 其他未声明标识符 | 11 | `HashSet`(3)、`HashMap`、`parse`(2)、`isUpper`(2)、`sqrt`、`crypto`、`sort` 等未导入或不存在 |
| 成员/方法不存在 | 7 | `.trim`、`.reverse`、`.sort`、`.min`、`.toArray`、`.toRunes`、`.size` 等调用了不存在的 API |
| 括号/分隔符不闭合 | 5 | `(` 或 `[` 未闭合 |
| import 位置错误 | 4 | `import` 语句放在了代码块中间而非文件顶部 |
| 运算符类型不匹配 | 4 | `Rune` 与 `String`/`UInt8` 比较、`Option` 类型上使用 `??` 等 |
| Lambda/模式语法错误 | 3 | `=>` 误用、`var match` 等 |
| 其他 | 24 | 参数标签缺失、不可变赋值、数值类型转换等 |

**典型错误示例**：
- `HumanEval/10`：body of function is missing — 模型放弃生成，函数体为空（24 个 task 同样问题）
- `HumanEval/14`：undeclared identifier `ArrayList` — 使用了动态数组但忘记 `import std.collection.*`（20 个 task 同样问题）
- `HumanEval/101`：`trim` is not a member of `String` — Cangjie String 无 `.trim()` 方法，应使用标准库函数
- `HumanEval/116`：`sort` is not a member of `Array<Int64>` — `sort()` 是独立函数非方法，且需 `import std.sort.*`
- `HumanEval/56`：invalid binary operator `==` on `Rune` and `String` — 字符与字符串类型混淆

### 测试失败（10 个 Task，编译通过但运行报错）

10 个 task 编译通过但均为全部断言失败（passed=0/1），函数逻辑与预期完全不符。

### 原因总结

| 根本原因 | 涉及 Task 数 | 占比 |
|----------|-------------|------|
| 函数体缺失（生成失败） | 24 | 22.2% |
| 缺少 import（ArrayList 等） | 20 | 18.5% |
| 其他未声明标识符 | 11 | 10.2% |
| API/成员名称错误 | 7 | 6.5% |
| 括号不闭合 | 5 | 4.6% |
| import 位置错误 | 4 | 3.7% |
| 运算符类型不匹配 | 4 | 3.7% |
| 语法错误 | 13 | 12.0% |
| 逻辑错误（测试失败） | 10 | 9.3% |
| 其他 | 10 | 9.3% |

相比旧版 benchmark（70/140 编译失败为括号缺失），新版 benchmark 的 failure distribution 有明显变化：

1. **函数体缺失成为第一大问题**（24 → 之前仅 1 个）——新版 benchmark 的部分 task 可能 prompt 更复杂，模型选择放弃
2. **`ArrayList` 未 import 成为第二大问题**（20 个）——模型知道要用 `ArrayList` 但不知道需要 `import std.collection.*`。这是 system prompt 可以精准修复的：在 prompt 中明确 "若使用 ArrayList/HashSet/HashMap，需 import std.collection.*"
3. **括号缺失不再是主要问题**——从旧版的 68 个（47.9%）降至仅 5 个（4.6%），说明 system prompt 中的括号规则对模型有显著约束力

---
*报告由 CodeGenEval 自动生成*
