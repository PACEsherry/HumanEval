---
name: code-gen-eval
description: 一个标准化测评 AI 代码生成工具（Agent）的 Skill。在给定的 Benchmark（.jsonl 格式）上对 Agent 进行多维度自动评估，涵盖代码正确性（编译成功率、平均测试通过率、pass@k）、代码性能指标以及生成效率与资源消耗，最终输出结构化测评报告。
---

# CodeGenEval Skill

## 2. 输入参数说明

| 参数 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `agent_name` | string | 是 | — | 被测评的 AI 代码生成工具名称，用于标识报告中的 Agent |
| `benchmark_path` | string | 是 | — | Benchmark 文件路径（.jsonl），每行一个 JSON 对象，包含 Task 定义。每个 Task 对象至少包含：`task_id`（唯一标识）、`prompt`（需求描述与代码签名）、`entry_point`（入口函数名）、`test`（测试代码块）；可选包含 `canonical_solution`（规范最优解代码） |
| `samples_path` | string | 是 | — | 样本文件路径（.jsonl），每行一个 JSON 对象，包含：`task_id`（对应 Benchmark 中的 task_id）、`completion`（Agent 生成的代码补全）。每个 task_id 有且仅有 n 个条目。可选包含 `time_spent_sec`（该样本生成耗时）、`api_cost`（该样本 API 开销）、`input_tokens` / `output_tokens`（token 消耗），用于资源消耗统计 |
| `n` | integer | 是 | — | 每个 Task 的生成次数（n ≥ 1），samples.jsonl 中每个 task_id 应有 n 个条目 |
| `k_values` | integer[] | 否 | [1, 3] | 用于计算 pass@k 的 k 值列表，每个值需满足 1 ≤ k ≤ n |
| `enable_perf_metrics` | boolean | 否 | false | 是否启用代码性能指标（可选指标） |
| `score_weights` | object | 否 | null | 综合评分权重配置。若不指定则使用默认等权重（见 4.7.4）。若指定，格式示例（基础评估体系）：`{"compilation_success_rate": 0.20, "avg_test_pass_ratio": 0.20, "pass_at_k": 0.20, "avg_time_per_task": 0.10, "avg_input_tokens": 0.10, "avg_output_tokens": 0.10, "avg_api_cost": 0.10}`（所有权重之和须为 1）。若启用了可选指标，需额外包含性能指标权重。两种评估体系的权重独立配置 |
| `benchmark_name` | string | 否 | "Unnamed Benchmark" | Benchmark 的名称，用于报告标识 |
| `language` | string | 否 | "kotlin" | Benchmark 使用的编程语言，用于编译检查和测试执行，如 "kotlin"、"python"、"javascript" 等 |
| `output_dir` | string | 否 | "."（当前目录） | 报告输出目录，测评生成的 JSON 和 Markdown 报告将写入此目录 |
| `timeout` | integer | 否 | 120 | 每个样本的编译和测试执行超时秒数，超时视为编译失败 |

**在执行评测之前，Agent 须向用户展示所有输入参数并与用户确认，待用户确认后方可开始执行。**

**Benchmark .jsonl 文件格式示例（参照 HumanEval_kotlin.jsonl）：**

```json
{
  "task_id": "HumanEval/0",
  "prompt": "import kotlin.math.abs\n\nfun hasCloseElements(numbers: List<Double>, threshold: Double): Boolean {\n\n/**\n * Check if in given list of numbers, are any two numbers closer to each other than\n * given threshold.\n */",
  "entry_point": "hasCloseElements",
  "canonical_solution": "for ((idx, elem) in numbers.withIndex()) {\n    for ((idx2, elem2) in numbers.withIndex()) {\n        if (idx != idx2) {\n            val distance = abs(elem - elem2)\n            if (distance < threshold) {\n                return true\n            }\n        }\n    }\n}\nreturn false",
  "test": "val METADATA = mapOf(\"author\" to \"jt\", \"dataset\" to \"test\")\n\nfun check(candidate: (List<Double>, Double) -> Boolean) {\n    assert(candidate(listOf(1.0, 2.0, 3.9, 4.0, 5.0, 2.2), 0.3) == true)\n    assert(candidate(listOf(1.0, 2.0, 3.9, 4.0, 5.0, 2.2), 0.05) == false)\n    assert(candidate(listOf(1.0, 2.0, 5.9, 4.0, 5.0), 0.95) == true)\n    assert(candidate(listOf(1.0, 2.0, 5.9, 4.0, 5.0), 0.8) == false)\n}"
}
```

**Samples .jsonl 文件格式示例（参照 samples_kotlin.jsonl）：**

```json
{"task_id": "HumanEval/0", "completion": "    for (i in numbers.indices) {\n        for (j in i + 1 until numbers.size) {\n            if (abs(numbers[i] - numbers[j]) < threshold) return true\n        }\n    }\n    return false\n}"}
```

也可选包含资源消耗字段：

```json
{"task_id": "HumanEval/0", "completion": "...", "time_spent_sec": 12.5, "api_cost": 0.015, "input_tokens": 800, "output_tokens": 150}
```

**资源消耗字段说明：** `time_spent_sec`、`api_cost`、`input_tokens`、`output_tokens` 需要在用户使用 Agent 进行代码生成时手动/要求 Agent 自行记录并提供。Agent 在执行评测之前，须向用户说明以下事项：
- 这些字段的含义与作用（用于统计耗费总时间、API 开销及 Token 消耗等指标）
- 用户需在 samples.jsonl 中为每个样本记录这些数据，缺失的字段将在报告中标记为 `N/A`
- 评测结果将完整呈现这些资源消耗数据

## 3. 执行步骤

### 步骤 1：数据加载（→ `data.py` + `pipeline.py`）

1. 调用 `data.read_problems(benchmark_path)` 读取 Benchmark `.jsonl`，得到以 `task_id` 为键的 Task 字典，记录 Task 总数 `N`。
2. 调用 `data.stream_jsonl(samples_path)` 读取样本，按 `task_id` 分组。验证每个 Task 恰好有 `n` 个样本，否则跳过该 Task 并记录警告。
3. 初始化全局累加器。

### 步骤 2：Task 循环

对每个有样本的 Task `i`（共 `N` 个 Task，每个有 `n` 个样本），按顺序调用以下脚本。若 `enable_perf_metrics=True` 且 Task 提供了 `canonical_solution`，需额外对其执行 `run_test(canonical_solution, enable_perf=True)` 获取规范最优解的性能数据，用于归一化计算：

#### 2.1 编译检查（→ `script/compile_check.py`）

调用 `compile_check(task, completion, language, timeout)`：
- 内部组装完整代码：将 `task.prompt` 与 `sample.completion` 拼接，保持 `import` 在文件头部。
- 根据 `language` 参数选择对应的编译方式（例如 Kotlin 使用 `kotlinc -script`，Python 使用 `py_compile`，JavaScript 使用相应运行时检查等），写入相应后缀的临时文件并编译。
- 返回 `{"compile_success": bool, "compile_error": str | None}`。
- 若编译失败，跳过该样本的测试执行和性能测量。

#### 2.2 测试执行（→ `script/test_execution.py`，同步记录性能数据）

对每个编译成功的样本调用 `run_test(task, completion, timeout, enable_perf=enable_perf_metrics)`，同步完成测试验证与性能数据采集：
- 组装含仪表化 `assert` 的完整测试程序（prompt + completion + closing + test + `check(::entry_point)` + 结果打印）。
- 运行程序，从 stdout 解析 `__ASSERT_RESULT: $passed/$total`，其中 `total` 由 `test` 代码中的 `assert(` 调用次数决定。
- 若 `enable_perf=True`，在子进程执行过程中同步记录：
  - **执行时间** `execution_time_sec`：通过 `time.perf_counter()` 记录进程端到端耗时。
  - **内存采样** `mem_samples`：以离散时间间隔（默认 10ms）通过 `psutil` 采样子进程的 RSS 内存，得到 `[{"timestamp": float, "rss_bytes": int}]` 序列。
  - **最大内存** `max_memory_mb`：从 `mem_samples` 中取最大值转换得到。
  - **总内存** `total_memory_mb_sec`：用梯形法从 `mem_samples` 计算 `∫ M(t) dt`。
- 返回 `{"passed": int, "total": int, "correct": bool, "error": str | None, "execution_time_sec": float | None, "max_memory_mb": float | None, "total_memory_mb_sec": float | None}`。

#### 2.3 资源消耗数据提取

若样本 JSON 中包含 `time_spent_sec`、`api_cost`、`input_tokens`、`output_tokens` 字段，则提取并累加到 Task 级计数器；若缺失，对应项标记为 `null`。

#### 2.4 规范最优解性能数据获取（可选）

若 `enable_perf_metrics=True` 且 Task 包含 `canonical_solution` 字段，调用 `run_test(task, task["canonical_solution"], timeout, enable_perf=True)` 执行规范最优解并采集其 `execution_time_sec`、`max_memory_mb`、`total_memory_mb_sec`，存入该 Task 的 `canonical_perf` 中。

#### 2.4 记录 Task 级原始数据

将每个 Task 的原始观测数据存入 `all_results`，结构如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | Task 唯一标识 |
| `n` | int | 该 Task 的样本总数 |
| `compile_success_count` | int | 编译成功的样本数 |
| `compile_results` | array | `[{"sample_index": int, "compile_success": bool, "compile_error": string\|null}]` |
| `test_results` | array | 编译成功样本的测试与性能数据 `[{"sample_index": int, "passed": int, "total": int, "test_pass_ratio": float, "correct": bool, "execution_time_sec": float\|null, "max_memory_mb": float\|null, "total_memory_mb_sec": float\|null}]` |
| `resource_consumption` | object\|null | 代码生成资源消耗数据 `{"time_spent_sec": float\|null, "api_cost": float\|null, "input_tokens": int\|null, "output_tokens": int\|null}` |
| `canonical_perf` | object\|null | 规范最优解 `canonical_solution` 的性能数据 `{"execution_time_sec": float\|null, "max_memory_mb": float\|null, "total_memory_mb_sec": float\|null}`；未提供或测量失败时为 `null` |

### 步骤 3：指标计算（→ `evaluation.py` + `pipeline.py`）

遍历 `all_results`，调用 `evaluation.estimate_pass_at_k()` 计算 pass@k，并按第 4 节公式计算其余指标。性能指标按以下方式聚合：
- **Task 级**：对该 Task 内所有编译成功样本的 `execution_time_sec`、`max_memory_mb`、`total_memory_mb_sec` 取平均，归一化执行时间对每个样本计算 `T_code_ij / T_canonical_i` 后取平均。
- **Benchmark 级**：将各 Task 的 Task 级平均值再取平均（除以Task 数 `N`）。

#### 3.1 综合评分计算

根据第 4.7 节公式计算综合评分：
1. 根据 `enable_perf_metrics` 确定评估体系（基础/完整）。
2. 将各 Benchmark 级指标按 4.7.2 节方法归一化到 [0,1]。
3. 若用户未提供 `score_weights`，使用默认等权重；否则使用自定义权重。
4. 计算 `CompositeScore = 100 × Σ(w_i · x_i)`，存入报告。

### 步骤 4：报告生成（→ `pipeline.py`）

按第 5 节模板输出 JSON 和/或 Markdown 格式报告。

## 4. 指标计算公式

### 4.1 编译成功率（Compilation Success Rate）

**每个 Task 的编译成功率：**

```
CSR_i = compile_success_count_i / n
```

其中 `compile_success_count_i` 为 Task `i` 的 `n` 个样本中编译成功的数量。

**整个 Benchmark 的编译成功率：**

```
CSR = (1 / N) * Σ CSR_i    (i = 1..N)
```

**约束**：若某个样本编译失败，该样本的性能指标标记为 `0`，测试通过率记为 `0`（参与该 Task 的平均测试通过率和性能指标计算）；该样本仍计入编译成功率分母 `n`。

### 4.2 平均测试通过率（Average Test Case Pass Ratio）

**每个样本的测试通过率：**

```
test_pass_ratio_ij = passed_ij / total_i
```

其中 `passed_ij` 为 Task `i` 的第 `j` 个样本通过的总断言数，`total_i` 为 Task `i` 的测试代码块中的总断言数。

**每个 Task 的平均测试通过率**（编译失败的样本视为测试通过率为 0，参与求平均）：

```
avg_test_pass_ratio_i = (1 / n) * Σ test_pass_ratio_ij   (j = 1..n)
```

其中若样本编译失败，`test_pass_ratio_ij = 0`。

**整个 Benchmark 的平均测试通过率：**

```
avg_test_pass_ratio = (1 / N) * Σ avg_test_pass_ratio_i   (i = 1..N)
```

### 4.3 pass@k

**每个 Task 的 pass@k：**

```
pass@k_i = 1 - C(n - c_i, k) / C(n, k)
```

其中：
- `n` = 每个 Task 的样本数量（由输入参数指定）
- `c_i` = Task `i` 中 `correct = true` 的样本数量（即通过所有测试的样本数）
- `C(a, b)` = 二项式系数，当 `b > a` 时 `C(a, b) = 0`

**整个 Benchmark 的 pass@k：**

```
pass@k = (1 / N) * Σ pass@k_i    (i = 1..N)
```

对用户指定的每个 `k` 值（默认 `k=1, 3`）分别计算。

### 4.4 耗费的总时间

Agent 完成整个 Benchmark 的端到端生成耗时，由 samples.jsonl 中每个样本的可选字段 `time_spent_sec` 汇总得到。

```
total_time = Σ task_time_i    (i = 1..N)
task_time_i = Σ sample_time_ij    (j = 1..n)
```

**每个 Task 的平均耗时：**

```
avg_time_per_task = total_time / N
```

若 samples.jsonl 未提供 `time_spent_sec` 字段，该指标标记为 `N/A`。

### 4.5 平均 API 开销与 Token 消耗

从 samples.jsonl 中每个样本的可选字段（`api_cost`、`input_tokens`、`output_tokens`、`time_spent_sec`）提取。若所有样本均缺失某字段，对应指标标记为 `N/A`。

**每个 Task 的 API 开销与 Token 数：**

```
task_cost_i = Σ sample_cost_ij        （j = 1..n）
task_input_tokens_i = Σ sample_input_tokens_ij
task_output_tokens_i = Σ sample_output_tokens_ij
```

**整个 Benchmark 的平均值：**

```
avg_api_cost = (1 / N) * Σ task_cost_i
avg_input_tokens = (1 / N) * Σ task_input_tokens_i
avg_output_tokens = (1 / N) * Σ task_output_tokens_i
total_api_cost = Σ task_cost_i
total_input_tokens = Σ task_input_tokens_i
total_output_tokens = Σ task_output_tokens_i
```

### 4.6 代码性能指标（可选）

以下指标基于所有样本（包括编译失败的样本，其性能值记为 0）的测试执行过程同步采集的性能数据。

记 `N` 为 Benchmark 的 Task 总数，`n` 为每个 Task 的样本数，`compile_success_count_i` 为 Task `i` 的编译成功样本数。以下指标中的字段名与 2.5 节记录表中的 `test_results` 和 `canonical_perf` 字段一致。

**平均执行时间：**

```
task_avg_execution_time_sec_i = (1 / n) * Σ_j execution_time_sec_ij
avg_execution_time_sec = (1 / N) * Σ_i task_avg_execution_time_sec_i
```

其中 `execution_time_sec_ij` 为 Task `i` 第 `j` 个样本的执行时间，编译失败的样本 `execution_time_sec_ij = 0`。

**平均最大内存使用：**

```
task_avg_max_memory_mb_i = (1 / n) * Σ_j max_memory_mb_ij
avg_max_memory_mb = (1 / N) * Σ_i task_avg_max_memory_mb_i
```

其中 `max_memory_mb_ij` 为 Task `i` 第 `j` 个样本的最大内存使用，编译失败的样本 `max_memory_mb_ij = 0`。

**平均总内存使用（梯形法）：**

```
task_avg_total_memory_mb_sec_i = (1 / n) * Σ_j total_memory_mb_sec_ij
avg_total_memory_mb_sec = (1 / N) * Σ_i task_avg_total_memory_mb_sec_i
```

其中 `P` 为内存采样点数，`Δt` 为采样间隔，编译失败的样本 `total_memory_mb_sec_ij = 0`。

**归一化执行时间（需 canonical_solution）：**

```
task_avg_normalized_exec_time_i = (1 / n) * Σ_j (execution_time_sec_ij / canonical_perf.execution_time_sec_i)
avg_normalized_exec_time = (1 / N) * Σ_i task_avg_normalized_exec_time_i
```

编译失败的样本 `execution_time_sec_ij / canonical_perf.execution_time_sec_i = 0`。若比值 `> 1`，说明 code 性能不如规范最优解；若 `< 1` 则说明性能更优。

### 4.7 综合评分（Composite Score）

综合评分是对上述所有启用的评估指标进行归一化加权计算得到的百分制分数（0-100），用于从整体上衡量 Agent 在 Benchmark 上的表现。

#### 4.7.1 评估体系划分

根据 `enable_perf_metrics` 的取值，分为两种评估体系：

1. **基础评估体系**（`enable_perf_metrics = false`）：仅基于必选指标计算
   - 编译成功率 `CSR`（正向）
   - 平均测试通过率 `avg_test_pass_ratio`（正向）
   - pass@k（取用户指定的最小 k 值对应的 pass@k，默认为 pass@1，正向）
   - 耗费的总时间 `total_time`（负向，取 `avg_time_per_task`）
   - 平均输入 token 数 `avg_input_tokens`（负向）
   - 平均输出 token 数 `avg_output_tokens`（负向）
   - 平均 API 开销 `avg_api_cost`（负向）

2. **完整评估体系**（`enable_perf_metrics = true`）：基于全部指标（必选 + 可选）计算
   - 上述所有必选指标
   - 代码性能指标中的各子指标：`avg_execution_time_sec`（负向）、`avg_max_memory_mb`（负向）、`avg_total_memory_mb_sec`（负向）、`avg_normalized_execution_time`（双向）

#### 4.7.2 指标归一化

在进行加权计算前，所有指标须归一化到 [0, 1] 区间：

- **正向指标**（越大越好）：编译成功率、平均测试通过率、pass@k
  ```
  normalized = raw_value
  ```

- **负向指标**（越小越好）：`avg_time_per_task`、`avg_api_cost`、`avg_input_tokens`、`avg_output_tokens`、`avg_execution_time_sec`、`avg_max_memory_mb`、`avg_total_memory_mb_sec`
  ```
  normalized = 1 / (1 + ln(1 + raw_value))
  ```
  说明：采用对数归一化替代线性归一化 `1/(1+x)`。对于量级跨越大的指标（如 token 数可达数千、耗时可达数百秒），线性归一会将大数值粗暴压制至接近 0，失去区分度。对数归一化在 raw→0 时与原公式一致（ln(1+x)≈x），但对大数值保留合理区分度，能更公平地反映指标差异。

- **双向指标**（越接近 1 越好）：`avg_normalized_execution_time`
  ```
  if raw_value <= 1:
      normalized = raw_value
  else:
      normalized = 1 / raw_value
  ```

若某个指标因数据缺失标记为 `N/A`，则该指标不参与评分，其权重按比例重新分配给其他参与评分的指标。

#### 4.7.3 加权计算公式

设共启用 `m` 个评估指标，第 `i` 个指标的归一化值为 `x_i`，权重为 `w_i`（`Σw_i = 1`），则综合评分为：

```
CompositeScore = 100 × Σ(w_i · x_i)    (i = 1..m)
```

最终综合评分以百分制呈现（0-100 分），分数越高表示整体表现越好。

#### 4.7.4 权重配置

**默认等权重（用户未指定 `score_weights` 时使用）：**

基础评估体系（7 项必选指标，代码正确性 66% + 资源效率 34%）：
```
compilation_success_rate : 0.22
avg_test_pass_ratio     : 0.22
pass_at_k               : 0.22
avg_time_per_task       : 0.08
avg_input_tokens        : 0.08
avg_output_tokens       : 0.08
avg_api_cost            : 0.10
```

权重分配说明：
- 代码正确性相关指标（编译成功率 + 平均测试通过率 + pass@k）合计权重 0.66，体现正确性在基础评估中的核心地位
- token 消耗（输入 + 输出）合计权重 0.16，与时间效率（0.08）和 API 开销（0.10）共同构成效率与资源消耗维度（合计 0.34）

完整评估体系（必选 7 项 + 可选 4 项，共 11 项；代码正确性 60% + 执行性能 25% + 资源效率 15%）：
```
# 代码正确性 60% (各 0.20)
compilation_success_rate    : 0.20
avg_test_pass_ratio        : 0.20
pass_at_k                  : 0.20
# 执行性能 25% (各 0.0625)
avg_execution_time_sec     : 0.0625
avg_max_memory_mb          : 0.0625
avg_total_memory_mb_sec    : 0.0625
avg_normalized_exec_time   : 0.0625
# 资源效率 15% (各 0.0375)
avg_time_per_task          : 0.0375
avg_input_tokens           : 0.0375
avg_output_tokens          : 0.0375
avg_api_cost               : 0.0375
```

- 用户可通过 `score_weights` 参数自定义各指标的权重值
- 两种评估体系（基础/完整）的权重独立配置，切换评估体系时自动切换对应的权重方案
- 若 `score_weights` 中某指标在当前评估体系中未启用，则忽略该指标并将其权重按比例重新分配给其他已启用指标

## 5. 输出报告模板

### 5.1 JSON 格式报告

```json
{
  "report": {
    "benchmark_name": "example_benchmark",
    "k_values": [1, 3],
    "total_tasks": 50,
    "total_samples": 500,
    "timestamp": "2026-06-15T10:30:00Z"
  },
  "metrics": {
    "compilation_success_rate": {
      "value": 0.92,
      "unit": "ratio",
      "description": "平均编译成功率（所有 Task 平均）"
    },
    "avg_test_pass_ratio": {
      "value": 0.85,
      "unit": "ratio",
      "description": "平均测试通过率（所有 Task 平均，编译失败样本记为 0）"
    },
    "pass_at_k": {
      "pass@1": { "value": 0.45, "unit": "ratio" },
      "pass@3": { "value": 0.72, "unit": "ratio" }
    },
    "total_time": {
      "value": 3600,
      "unit": "seconds",
      "description": "Agent 代码生成总耗时（samples.jsonl 中 time_spent_sec 之和）"
    },
    "avg_time_per_task": {
      "value": 72.0,
      "unit": "seconds",
      "description": "每个 Task 平均生成耗时"
    },
    "total_api_cost": {
      "value": 2.50,
      "unit": "USD",
      "description": "总 API 开销"
    },
    "avg_api_cost": {
      "value": 0.05,
      "unit": "USD",
      "description": "平均每 Task API 开销"
    },
    "total_input_tokens": {
      "value": 250000,
      "unit": "tokens",
      "description": "总输入 token 数"
    },
    "avg_input_tokens": {
      "value": 5000,
      "unit": "tokens",
      "description": "平均每 Task 输入 token 数"
    },
    "total_output_tokens": {
      "value": 600000,
      "unit": "tokens",
      "description": "总输出 token 数"
    },
    "avg_output_tokens": {
      "value": 12000,
      "unit": "tokens",
      "description": "平均每 Task 输出 token 数"
    }
  },
  "composite_score": {
    "value": 72.5,
    "unit": "score (0-100)",
    "evaluation_system": "basic",
    "description": "综合评分（基础评估体系，等权重），分数越高整体表现越好"
  },
  "optional_metrics": {
    "code_performance": {
      "avg_execution_time_sec": { "value": 0.035, "unit": "seconds" },
      "avg_max_memory_mb": { "value": 6.1, "unit": "MB" },
      "avg_total_memory_mb_sec": { "value": 0.52, "unit": "MB·s" },
      "avg_normalized_execution_time": { "value": 1.15, "unit": "ratio" },
      "description": "代码性能指标（编译失败样本记为 0，按 Task 平均后对 Task 数取平均）"
    }
  },
  "per_task_results": [
    {
      "task_id": "HumanEval/0",
      "n": 10,
      "compile_success_count": 8,
      "compile_results": [
        {"sample_index": 0, "compile_success": true, "compile_error": null},
        {"sample_index": 1, "compile_success": true, "compile_error": null},
        {"sample_index": 2, "compile_success": false, "compile_error": "SyntaxError"}
      ],
      "test_results": [
        {"sample_index": 0, "passed": 4, "total": 4, "test_pass_ratio": 1.0, "correct": true},
        {"sample_index": 1, "passed": 2, "total": 4, "test_pass_ratio": 0.5, "correct": false}
      ],
      "resource_consumption": {
        "time_spent_sec": 72.0,
        "api_cost": 0.05,
        "input_tokens": 5000,
        "output_tokens": 12000
      },
      "canonical_perf": {
        "execution_time_sec": 0.019
      }
    }
  ]
}
```

### 5.2 Markdown 表格格式报告

#### 总体指标

| 指标 | 值 | 单位 | 说明 |
|------|-----|------|------|
| Benchmark | example_benchmark | — | — |
| 样本总数 | 500 | — | 所有 Task 样本之和 |
| 平均每 Task 样本数 | 10 | — | 由 samples.jsonl 决定 |
| k 值 | 1, 3 | — | pass@k 参数 |
| Task 总数 | 50 | — | — |
| **compilation_success_rate** | 0.92 | — | 平均编译成功率 |
| **avg_test_pass_ratio** | 0.85 | — | 平均测试通过率（编译失败记为 0） |
| **pass@1** | 0.45 | — | — |
| **pass@3** | 0.72 | — | — |
| **total_time** | 3600 | s | Agent 生成总耗时 |
| **avg_time_per_task** | 72.0 | s | — |
| **total_api_cost** | 2.50 | USD | — |
| **avg_api_cost** | 0.05 | USD | — |
| **total_input_tokens** | 250000 | — | — |
| **avg_input_tokens** | 5000 | — | — |v
| **total_output_tokens** | 600000 | — | — |
| **avg_output_tokens** | 12000 | — | — |
| **composite_score** | 72.5 | 分(0-100) | 综合评分（基础评估体系，等权重） |

#### 可选指标：代码性能

| 指标 | 值 | 单位 | 说明 |
|------|-----|------|------|
| avg_execution_time_sec | 0.035 | s | 编译失败样本记为 0 |
| avg_max_memory_mb | 6.1 | MB | 编译失败样本记为 0 |
| avg_total_memory_mb_sec | 0.52 | MB·s | 梯形法积分 |
| avg_normalized_execution_time | 1.15 | — | >1 表示不如规范最优解 |

## 6. 错误处理与边界情况说明

### 6.1 空 Benchmark

若 `benchmark_path` 对应的 `.jsonl` 文件为空或不存在，报告应输出错误并终止：

```json
{ "error": "Benchmark 文件为空或不存在", "benchmark_path": "..." }
```

### 6.2 Task 缺少必要字段

若某个 Task JSON 缺少 `task_id`、`prompt`、`entry_point` 或 `test` 字段，跳过该 Task 并在报告中记录警告，不影响其他 Task 的计算。

### 6.3 Task 测试代码为空（test 为空字符串）

- 该 Task 无法计算测试通过率。`avg_test_pass_ratio` 标记为 `N/A`。
- 若代码编译成功，该样本的 `correct` 状态为 **未定义**（无法判断是否正确），在 pass@k 中不计入 `c`（正确样本数）。

### 6.4 k > n

若用户指定的某个 `k` 值大于 `n`：
- 该 `k` 值的所有 `pass@k` 标记为 `N/A`。
- 在报告中给出警告提示。

### 6.5 samples.jsonl 为空或缺失 / Task 样本数不为 n

若 `samples_path` 对应的 `.jsonl` 文件为空、不存在或解析后无有效条目，报告应输出错误并终止。
若某个 Task 的样本数不等于输入参数 `n`，跳过该 Task 并在报告中记录警告。

### 6.6 编译全部失败

若某个 Task 的 `n` 个样本全部编译失败：
- `compile_success_rate_i = 0`
- `avg_test_pass_ratio_i = 0`
- `pass@k_i = 0`（没有正确样本，`c_i = 0`）
- 性能指标标记为 `0`
- 该 Task 正常计入 Benchmark 的编译成功率、测试通过率以及性能指标分母

### 6.7 部分样本编译失败

对于编译失败的样本：
- 测试通过率记为 `0`（参与该 Task 的平均测试通过率计算）
- 性能指标标记为 `0`
- 计入编译成功率、测试通过率以及性能指标分母

### 6.8 samples.jsonl 中 task_id 不匹配

若 samples.jsonl 中的某个 `task_id` 在 benchmark 中不存在，跳过该样本并记录警告，不影响其他 Task 的计算。

### 6.9 至少一个样本编译成功但无规范最优解

若 `enable_perf_metrics = true` 但某 Task 未提供 `canonical_solution`：
- 执行时间和内存指标正常计算
- 归一化执行时间标记为 `N/A`

### 6.10 超时处理

若某个样本的编译、测试或性能测量超时（可配置超时阈值，默认 120 秒）：
- 按编译失败处理（标记 `compile_success = false`，错误信息为 `"Timeout"`）。

### 6.11 缺少资源消耗数据

若 samples.jsonl 中未包含 `api_cost`、`input_tokens`、`output_tokens`、`time_spent_sec` 等字段：
- 对应的指标（平均 API 开销、平均 Token 消耗、总耗时）标记为 `N/A`。
- 报告中给出提示说明数据来源缺失。
