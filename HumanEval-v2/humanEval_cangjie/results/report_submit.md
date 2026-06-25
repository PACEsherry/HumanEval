# CodeGenEval 测评报告

**Agent**: opencode/GLM-5.1/optimize-636 | **Benchmark**: HumanEval-Cangjie | **语言**: cangjie
**生成时间**: 2026-06-24T15:33:46+08:00 | **n**: 1 | **k**: 1

## 总体指标

| 指标 | 值 | 单位 | 说明 |
|------|-----|------|------|
| Benchmark | HumanEval-Cangjie | — | — |
| 语言 | cangjie | — | — |
| 样本总数 | 164 | — | 所有 Task 样本之和 |
| 平均每 Task 样本数 | 1 | — | 由 samples.jsonl 决定 |
| k 值 | 1 | — | pass@k 参数 |
| Task 总数 | 164 | — | — |
| **compilation_success_rate** | 71.95% | ratio | 平均编译成功率 |
| **avg_test_pass_ratio** | 65.24% | ratio | 平均测试通过率（编译失败记为 0） |
| **pass@1** | 65.24% | ratio | — |
| **total_time** | 69.43 | min | Agent 生成总耗时 |
| **avg_time_per_task** | 25.40 | s | 每个 Task 平均生成耗时 |
| **total_tokens** | 910,268 | tokens | 总 token 消耗 |
| **avg_total_tokens** | 5,550.4 | tokens | 平均每 Task 总 token 数 |
| **composite_score** | 53.60 | 分(0-100) | 综合评分（基础评估体系） |

> 注：total_tokens = total_input_tokens (696,775) + total_output_tokens (213,493)；input_tokens 为发送给模型的 prompt 所消耗的 token 数，output_tokens 为模型生成的 completion 所消耗的 token 数，二者之和反映单次盲生成的总 token 开销。

## 测试未通过原因分析

164 个 Task 中，**46 个编译失败**（CSR = 71.95%），**11 个测试运行失败**（编译通过但结果错误）。最终 107 个 Task 完全通过（pass@1 = 65.24%）。

### 编译失败（46 个 Task）

| 失败类型 | 数量 | 说明 |
|----------|------|------|
| ArrayList/HashMap/HashSet 缺 import | 17 | 使用 `ArrayList<T>` 等但未写 `import std.collection.*`，为最高频错误 |
| lambda 捕获可变变量 | 5 | Cangjie 限制 Lambda 捕获 `var`，需改用函数参数传递 |
| 函数体缺失/截断 | 4 | API 返回空/截断代码，含 2 个 API 重试失败后的 TODO fallback |
| 类型/语法不匹配 | 6 | `Float64` 字面量比较、`return` 类型不匹配、括号错误等 |
| Unicode API 缺 import | 3 | `isUpperCase`/`isLowerCase` 未 `import std.unicode.*` |
| parse/sort/math 缺 import | 4 | `parse()`/`sort()`/`sqrt()` 未导入对应 std 包 |
| True vs true | 1 | Cangjie 用 `true`（小写），模型写了 `True`（大写） |
| Option coalescing 误用 | 1 | `??` 用于非 Option 类型 |
| API 名称错误 | 1 | `subString` 不是 String 的成员（应切片 `s[start..end]`） |
| stdx 不可用 | 1 | `Md5Digest` 需要 stdx.crypto.digest，单文件环境无法配置 |
| 其他 | 4 | trailing closure 语法错误等 |

**典型错误示例**：
- `HumanEval/1`：`undeclared identifier 'ArrayList'` — 使用 ArrayList 但未 `import std.collection.*`
- `HumanEval/0`：`undeclared identifier 'True'` — Cangjie 布尔值为小写 `true`
- `HumanEval/120`：`lambda capturing mutable variables needs to be called directly` — Lambda 捕获 var 限制
- `HumanEval/27`：`undeclared identifier 'isUpperCase'` — 未 `import std.unicode.*`
- `HumanEval/137`：`undeclared identifier 'parse'` — 未 `import std.convert.*`

### 测试失败（11 个 Task，编译通过但运行结果错误）

| 失败类型 | 数量 | 说明 |
|----------|------|------|
| 算法逻辑错误 | 11 | 编译通过但输出不符合预期，多为边界条件或算法实现偏差 |

**典型错误示例**：
- `HumanEval/103`、`HumanEval/105`、`HumanEval/108` 等：算法逻辑实现有偏差

### 原因总结

| 根本原因 | 涉及 Task 数 | 占比 |
|----------|-------------|------|
| 缺标准库 import（ArrayList/HashMap/HashSet/unicode/sort/parse/math） | 24 | 52.2% |
| Cangjie 语言特性不熟悉（lambda 捕获 var、True vs true、Option ??） | 7 | 15.2% |
| API 调用方式错误（.subString()、coalescing 非Option） | 2 | 4.3% |
| 代码截断/空返回（含 API 失败 fallback） | 4 | 8.7% |
| 类型/语法错误（字面量比较、类型不匹配） | 6 | 13.0% |
| stdx 不在单文件环境可用 | 1 | 2.2% |
| 其他 | 2 | 4.3% |

主要瓶颈在于**标准库导入缺失**（52.2%），尽管 P0 规则已明确要求 `import std.collection.*` / `import std.sort.*` 等，模型在生成代码时仍大量遗漏。这与上一轮（6规则版）的 30.4% 缺导入相比，占比反而上升，原因是 P0 规则涵盖了更多需要 import 的场景（unicode/convert/math/sort），但模型未能系统性地在代码开头补齐所有必要的 import 语句。

---
*报告由 CodeGenEval 自动生成，report_submit.md 由人工修订*
