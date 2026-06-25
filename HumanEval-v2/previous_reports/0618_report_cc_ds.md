# CodeGenEval 测评报告

**Agent**: opencode | **Benchmark**: HumanEval_cangjie.jsonl | **语言**: cangjie
**生成时间**: 2026-06-18T16:00:00+08:00 | **n**: 1 | **k**: 1

## 总体指标

| 指标 | 值 | 单位 | 说明 |
|------|-----|------|------|
| Benchmark | HumanEval_cangjie.jsonl | — | — |
| 语言 | cangjie | — | — |
| 样本总数 | 164 | — | 所有 Task 样本之和 |
| 平均每 Task 样本数 | 1 | — | 由 samples.jsonl 决定 |
| k 值 | 1 | — | pass@k 参数 |
| Task 总数 | 164 | — | — |
| **compilation_success_rate** | 0.1341 | ratio | 平均编译成功率 |
| **avg_test_pass_ratio** | 0.0689 | ratio | 平均测试通过率（编译失败记为 0） |
| **pass@1** | 0.0549 | ratio | — |
| **total_time** | 78.85 | min | Agent 生成总耗时 |
| **avg_time_per_task** | 28.85 | s | 每个 Task 平均生成耗时 |
| **total_api_cost** | N/A | USD | 总 API 开销 |
| **avg_api_cost** | N/A | USD | 平均每 Task API 开销 |
| **total_tokens** | 270205 | tokens | 总 token 消耗（输入 + 输出） |
| **avg_total_tokens** | 1647.6 | tokens | 平均每 Task token 消耗 |
| **composite_score** | 3.15 | 分(0-100) | 综合评分（basic评估体系） |

> 注：本批次 system prompt 依据 `CangjieSkills/` 语法参考手册重写，包含 15 条精确的 Cangjie 语法规则（函数签名、控制流括号、类型名、Option 解包、Array/ArrayList 差异、字符串插值等）。编译环境为 Cangjie SDK 1.0.5 (`cjc --output-type=staticlib`)。
>
> 迭代记录：
> - v1（基础 prompt）：CSR 6.10%，pass@1 1.83%
> - v2（+10条关键规则）：CSR 14.63%，pass@1 3.66%
> - **v3（+CangjieSkills 15条精确规则）：CSR 13.41%，pass@1 5.49%**
>
> v3 的 token 消耗增长显著（270k vs 174k），因长 system prompt 在每轮 API 调用中重复发送。TODO 占位从 ~25 降至 1，pass@1 略有提升，但括号语法问题仍占编译失败的 48%。

## 测试未通过原因分析

164 个 Task 中，**142 个编译失败**（CSR = 13.41%），**13 个测试运行失败**。最终 9 个 Task 完全通过（pass@1 = 5.49%）。

### 编译失败（142 个 Task）

| 失败类型 | 数量 | 占比 | 说明 |
|----------|------|------|------|
| 语法缺括号 | 68 | 47.9% | `if`/`for`/`while` 条件缺少必需的小括号，LLM 仍倾向于 Swift/Rust/Kotlin 风格 |
| 未声明变量 | 28 | 19.7% | LLM 使用了 prompt 参数名之外的变量名（如函数签名参数为 `numbers`，代码中引用 `arr`） |
| Option 类型误用 | 10 | 7.0% | 对 `Option<T>` 值直接调用成员方法或进行比较，未使用 `??` 或 `match` 解包 |
| 未声明类型 | 8 | 5.6% | 使用 `List`→应为 `ArrayList`，`Float`→应为 `Float64`，`HashSet`→需 import |
| 成员不存在 | 4 | 2.8% | 调用 `.length`/`.count` 而非 `.size`，`.append` 而非 `.add` |
| 其他 | 24 | 16.9% | 包括 `import` 路径错误（×5）、运算符类型不匹配（×4）、lambda 语法错（×3）、`match` 分支不完整等 |

**典型错误示例**：
- `Cangjie/0`：**编译成功**，7/7 断言全部通过 — 使用 `for (i in 0..numbers.size)` 和 `if ((numbers[i] - numbers[j]).abs() < threshold)`，语法完全正确
- `Cangjie/25`：expected '(' found keyword 'if' — 嵌套 if 缺少外层括号
- `Cangjie/38`：invalid binary operator on `Option<Int64>` — prompt 参数类型为 `?Int64`，模型直接用 `>=` 比较
- `Cangjie/62`：`size` is not a member of `Option<Array<Int64>>` — 对 `?Array<Int64>` 直接取 `.size` 而非先解包
- `Cangjie/5`：undeclared type name 'Float' — 使用了训练数据中的其他语言类型名

### 测试失败（13 个 Task，编译通过但运行报错）

22 个编译通过的 task 中，9 个全部 `@Expect` 通过，13 个出现断言失败——函数逻辑不正确。

**典型错误示例**：
- `Cangjie/46`：passed=2/8 — 8 个测试用例中 2 个通过，函数部分正确
- `Cangjie/115`：passed=0/5 — 5 个断言全部失败，函数逻辑方向错误
- `Cangjie/79`：passed=6/8 — 接近正确，边界条件处理有误

### 原因总结

| 根本原因 | 涉及 Task 数 | 占比 |
|----------|-------------|------|
| 语法缺括号（if/for/while） | 68 | 47.9% |
| 变量名不匹配 prompt | 28 | 19.7% |
| Option 类型处理不当 | 10 | 7.0% |
| 类型名/API 引用错误 | 12 | 8.5% |
| 其他语法/语义错误 | 24 | 16.9% |

### 结论

CangjieSkills 参考手册提供的 15 条精确语法规则，对模型生成质量有边际改善（TODO 率从 18% 降至 0.6%，pass@1 从 3.66% 升至 5.49%），但无法改变根本问题：**DeepSeekV4 缺乏 Cangjie 训练数据**，且 system prompt 中的语法规则在 164 次独立生成中无法被模型稳定内化——48% 的编译失败仍然是最基础的括号语法问题。

总 token 消耗从 v2 的 174k 增至 270k（+55%），主要因长 system prompt 的重复发送。对于未经训练的语言，投入更多 token 的边际收益递减明显。

要获得可用的 Cangjie 测评结果，仍需换用经过 Cangjie 代码训练的模型。

---
*报告由 CodeGenEval 自动生成，手动微调*
