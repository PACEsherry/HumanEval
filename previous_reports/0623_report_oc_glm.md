# CodeGenEval 测评报告

**Agent**: opencode(GLM-5.1) | **Benchmark**: HumanEval_cangjie.jsonl (睿鸣修改版) | **语言**: cangjie
**生成时间**: 2026-06-23T15:39:18+08:00 | **n**: 1 | **k**: 1

## 总体指标

| 指标 | 值 | 单位 | 说明 |
|------|-----|------|------|
| Benchmark | HumanEval_cangjie.jsonl | — | — |
| 语言 | cangjie | — | — |
| 样本总数 | 164 | — | 所有 Task 样本之和 |
| 平均每 Task 样本数 | 1 | — | 由 samples.jsonl 决定 |
| k 值 | 1 | — | pass@k 参数 |
| Task 总数 | 164 | — | — |
| **compilation_success_rate** | 0.6768 | ratio | 平均编译成功率 |
| **avg_test_pass_ratio** | 0.5793 | ratio | 平均测试通过率（编译失败记为 0） |
| **pass@1** | 0.5793 | ratio | — |
| **total_time** | 82.59 | min | Agent 生成总耗时 |
| **avg_time_per_task** | 30.21 | s | 每个 Task 平均生成耗时 |
| **total_api_cost** | N/A | USD | 总 API 开销 |
| **avg_api_cost** | N/A | USD | 平均每 Task API 开销 |
| **total_tokens** | 696250 | tokens | 总 token 消耗（输入 + 输出） |
| **avg_total_tokens** | 4245.43 | tokens | 平均每 Task token 消耗 |
| **composite_score** | 48.93 | 分(0-100) | 综合评分（basic评估体系） |

> 注：total_tokens = total_input_tokens (423786) + total_output_tokens (272464)；input_tokens 为发送给模型的 prompt 所消耗的 token 数，output_tokens 为模型生成的 completion 所消耗的 token 数，二者之和反映单次盲生成的总 token 开销。

## 测试未通过原因分析

164 个 Task 中，**53 个编译失败**（CSR = 67.68%），**16 个测试运行失败**（编译通过但逻辑不正确）。最终 95 个 Task 完全通过（pass@1 = 57.93%）。

### 编译失败（53 个 Task）

| 失败类型 | 数量 | 说明 |
|----------|------|------|
| ArrayList/HashSet 未声明（缺 import） | 14 | 使用了 `ArrayList<T>()` 或 `HashSet<T>()` 但未导入 `std.collection.*` |
| Rune→Int64 类型转换禁止 | 9 | 写了 `Int64(r)` 其中 `r` 为 Rune，Cangjie 不支持数值类型转换于 Rune |
| Lambda 捕获可变变量 | 6 | lambda 中捕获 `var` 变量，Cangjie 要求捕获变量不可变或 lambda 直接调用 |
| 未声明的标准库符号（abs/sqrt/parse 等） | 7 | 调用了不存在于 Cangjie 的函数名，如 `abs()`、`sqrt()`、`_0`/`_1` 元组访问 |
| 函数体缺失（代码截断/不完整） | 5 | 生成了空函数体或 `return` 在顶层而非函数内 |
| 类型不匹配 | 4 | `??` 用于非 Option 类型、Rune 减法、跨类型传参等 |
| 方法不存在于内置类型 | 4 | 调用了 String/Array 不存在的成员如 `substring`、`toLower`、`reduce` |
| 语法错误 | 3 | catch 语法错、lambda 缺 `=>`、import 在函数体内 |
| 构造函数参数错误 | 1 | Array<Rune> 构造传参数量不匹配 |

**典型错误示例**：
- `HumanEval/14`：`error: undeclared identifier 'ArrayList'` — 缺少 `import std.collection.*`
- `HumanEval/27`：`error: the expression for numeric type conversion must have a numeric type` — `Int64(r)` 中 r 为 Rune
- `HumanEval/21`：`error: lambda capturing mutable variables needs to be called directly` — lambda 捕获了 var 变量
- `HumanEval/18`：`error: 'substring' is not a member of struct 'String'` — String 无 substring 方法

### 测试失败（16 个 Task，编译通过但运行结果错误）

| 失败类型 | 数量 | 说明 |
|----------|------|------|
| 逻辑完全错误（0/1 测试通过） | 16 | 代码编译执行成功，但算法逻辑不正确，所有测试用例均不通过 |

**典型错误示例**：
- `HumanEval/54`：函数返回值与预期不符
- `HumanEval/68`：逻辑完全错误
- `HumanEval/87`：算法输出不满足断言

### 原因总结

| 根本原因 | 涉及 Task 数 | 占比 |
|----------|-------------|------|
| 缺少标准库导入（ArrayList/HashSet/abs 等） | 21 | 30.4% |
| Rune 与数值类型转换规则不了解 | 9 | 13.0% |
| Lambda 捕获可变变量限制 | 6 | 8.7% |
| 函数体不完整/截断 | 5 | 7.2% |
| 类型系统不匹配（Option/Rune/跨类型） | 4 | 5.8% |
| 调用不存在的方法（String/Array API） | 4 | 5.8% |
| 语法错误 | 3 | 4.3% |
| 逻辑完全错误（编译通过但测试失败） | 16 | 23.2% |
| 其他 | 1 | 1.4% |

主要瓶颈在于 **标准库导入缺失**（30.4%，其中 ArrayList 缺 import 占14个）和 **Rune 类型转换限制**（13.0%）。与 DeepSeek V4 版（CSR 13.41%/pass@1 5.49%）相比，GLM-5.1 的 CSR 从 13.41% 提升至 67.68%，pass@1 从 5.49% 提升至 57.93%，提升幅度显著。动态 Skills 注入使模型获得了关键的 Cangjie 语法知识（括号规则、类型命名等），但标准库 API 知识（import 路径、方法名、Rune 转换）仍有不足。

---
*报告由 CodeGenEval 自动生成*
