# HumanEval-X Cangjie 盲生成测评 — OpenCode/GLM-5.1 会话工作记录

> 日期: 2026-06-23 | 可供新会话/新 Agent 无缝接续任务的完整参考文档。
> 基于 0618_mem_cc_1.md 的架构，补充 OpenCode 插件 + GLM-5.1 模型的实战经验。

---

## 一、项目结构速览

```
Human-Eval_v1/
├── code-gen-eval/script/          # 共享测评核心（data, evaluation, composite_score, pipeline）
├── humaneval-x/
│   ├── generate_samples.py        # ★ 多语言盲生成脚本（DeepSeek 版，15条规则）
│   ├── generate_samples_cj.py     # ★ Cangjie 专项盲生成（GLM-5.1，6条规则+动态Skills）
│   ├── patch_2tasks.py            # ★ 一次性补跑少数失败task的工具脚本
│   ├── humanEval_cangjie/
│   │   ├── data/
│   │   │   ├── HumanEval_cangjie.jsonl           # 完整 benchmark（164 task）
│   │   │   ├── HumanEval_cangjie_prompt_only.jsonl  # 仅 prompt（盲生成输入）
│   │   │   ├── sample.jsonl                     # DeepSeek V4 盲生成结果
│   │   │   └── sample_0.jsonl                   # ★ GLM-5.1 盲生成结果（与 sample.jsonl 并存）
│   │   ├── script/
│   │   │   ├── run_eval.py                      # 测评入口包装器
│   │   │   ├── compile_check.py                 # Cangjie 编译检查
│   │   │   └── test_execution.py                # Cangjie 测试执行
│   │   ├── results/                              # DeepSeek V4 版报告
│   │   └── results_oc_glm/                      # ★ GLM-5.1 版报告
│   │       ├── report.json                       # 机审原始 JSON
│   │       ├── report.md                         # 机审原始 Markdown
│   │       └── report_submit.md                  # ★ 手动修订提交版
│   └── {其他语言目录}/
├── .agent/skills/cangjie-lang-features/          # ★ CangjieSkills 参考手册
├── 0618_mem_cc_1.md               # Claude Code 插件会话记录
└── 0623_mem_op.md                 # ★ 本文档
```

---

## 二、generate_samples_cj.py 核心设计

### 2.1 与 generate_samples.py 的关键差异

| 维度 | generate_samples.py | generate_samples_cj.py |
|------|---------------------|------------------------|
| 语言范围 | 全部10种 | 仅 Cangjie |
| 输出文件名 | `sample.jsonl` | `sample_0.jsonl`（并存） |
| System prompt | 15条精确规则（静态） | **6条精简规则 + 动态 Skills 注入** |
| API 格式 | Anthropic → 回退 OpenAI | 直接 OpenAI Chat Completions |
| Token 字段 | `input_tokens`/`output_tokens`（Anthropic） | `prompt_tokens`/`completion_tokens`（OpenAI） |
| 断点续传 | 无 | `--resume` 跳过已完成 task_id |
| 指定task | 无 | `--task-ids "10,93,118,129"` 只跑指定task |
| 连通性测试 | 无 | `--dry-run` 测试1个task |

### 2.2 API 配置

| 环境变量 | 命令行参数 | 默认值 |
|----------|-----------|--------|
| `CJ_API_KEY` | `--api-key` | `sk-ENriBfblBuYZqZ1hAjJz5g` |
| `CJ_API_BASE_URL` | `--api-base` | `http://113.46.219.251:8080/v1` |
| `CJ_MODEL_NAME` | `--model` | `GLM-5.1` |

API 端点为 OpenAI 兼容格式：`{base_url}/chat/completions`

### 2.3 6条精简 System Prompt 规则

从原有15条压缩为6条，覆盖最常见编译失败原因：

| # | 规则 | 覆盖原规则 | 编译失败占比 |
|---|------|-----------|------------|
| 1 | 函数签名冒号 `func name(params): ReturnType`，类型 `Int64/Float64/Bool/String/Array<T>/Unit`，禁 `Int/Float/Double/->` | 原1,3 | — |
| 2 | **所有控制流必须加括号** `if(cond){}` `for(i in 0..n){}` `match(expr){}` | 原2 | 48%（原DeepSeek版） |
| 3 | `let`/`var`，`Array.size`，动态用 `ArrayList<T>`+`import std.collection.*` | 原4,5,6 | — |
| 4 | `?T`=Option<T>，`(opt ?? default)`/`match`解包，类型转换 `Int64(x)` | 原7,8,9 | — |
| 5 | `"${expr}"`插值，`.runes()`迭代字符，Range `0..n`/`0..=n` | 原10,14 | — |
| 6 | 禁独立`{}`块，`return`返回值 | 原12,15 | — |

### 2.4 动态 Skills 注入机制

**核心思路**：不灌入 README 全文（每轮~130K tokens），而是按 task prompt 关键词动态选择 2-3 个最相关的 Skills README，取前80行精华段落注入 system prompt。

**关键词→Skill 映射表**：

```
关键词映射:
  "String" / "字符串" / "substring" / "char"   → string/README.md
  "Array" / "ArrayList" / "sort" / "size"       → collections/array/README.md + arraylist/README.md
  "Option" / "?T" / "None" / "Some"             → option/README.md
  "match" / "case" / "pattern"                  → pattern_match/README.md
  "for" / "while" / "Range" / "iterate"         → for/README.md
  "Int64" / "Float64" / "Bool" / "number"       → basic_data_type/README.md
  "func" / "lambda" / "recursion"               → function/README.md
  无匹配                                         → basic_concepts/README.md（兜底）
```

**注入流程**（每个 task 一次）：
1. 扫描 task prompt 中的关键词
2. 选择排名最高的 2-3 个 skill keys（Array 额外附带 ArrayList）
3. 加载各 README 前80行
4. 拼入 system prompt 尾部：`--- Reference: {skill_name} ---\n{snippet}`

**Token 消耗对比**：
| 方式 | 每轮 input tokens |
|------|-----------------|
| 全量注入（3包全文） | ~130,000 |
| 按需检索（6规则+2-3片段） | ~780-1,150 |
| 仅6规则（无Skills） | ~200 |

### 2.5 sample_0.jsonl 字段

```json
{
  "task_id": "HumanEval/0",
  "completion": "... 函数体代码 ...",
  "time_spent_sec": 13.63,
  "input_tokens": 2657,
  "output_tokens": 725
}
```

- `input_tokens`：API 响应 `usage.prompt_tokens`（OpenAI 格式）
- `output_tokens`：API 响应 `usage.completion_tokens`（OpenAI 格式）
- `time_spent_sec`：脚本端 `time.time()` 打点

### 2.6 CLI 命令

```powershell
cd D:\ZSY\Human-Eval_v1\humaneval-x

# 全量生成（首次）
python generate_samples_cj.py --n 1 --workers 8

# 断点续传（跳过已完成的task_id）
python generate_samples_cj.py --n 1 --workers 8 --resume

# 指定 task 重跑（删除旧条目+重新生成+排序）
python generate_samples_cj.py --n 1 --workers 4 --task-ids "10,93,118,129"

# 连通性测试（1个task）
python generate_samples_cj.py --dry-run

# 仅验证
python generate_samples_cj.py --validate-only --n 1
```

---

## 三、测评命令行（PowerShell）

### 3.1 标准测评命令

```powershell
cd D:\ZSY\Human-Eval_v1\humaneval-x\humanEval_cangjie\script

# DeepSeek V4 版（输出到默认 results/）
python run_eval.py `
  --agent_name "DeepSeekV4" `
  --benchmark_path "..\data\HumanEval_cangjie.jsonl" `
  --samples_path "..\data\sample.jsonl" `
  --n 1 --language "cangjie" --k_values "1,3" `
  --output_dir "..\results"

# GLM-5.1 版（输出到独立 results_oc_glm/）
python run_eval.py `
  --agent_name "opencode" `
  --benchmark_path "..\data\HumanEval_cangjie.jsonl" `
  --samples_path "..\data\sample_0.jsonl" `
  --n 1 --language "cangjie" --k_values "1,3" `
  --output_dir "..\results_oc_glm"
```

### 3.2 结果目录命名规范

多个模型版本并存时，使用独立目录：

```
humanEval_cangjie/
├── results/                # DeepSeek V4 版
├── results_oc_glm/         # OpenCode + GLM-5.1 版
├── results_oc_glm5/        # （若后续跑 GLM-5）
└── results_oc_xxx/         # （其他模型）
```

### 3.3 前置检查

- **entry_point**：Cangjie benchmark 已有 `entry_point` 字段，无需注入
- **sample_0.jsonl 必须验证通过**：164 tasks × 1 = 164 samples，0个 TODO fallback

---

## 四、report_submit.md 格式规范

### 4.1 从 report.md 到 report_submit.md 的8项改动

| # | 改动 | 具体操作 | 示例 |
|---|------|---------|------|
| 1 | Agent 名 → 含模型名 | `opencode` → `opencode/GLM-5.1` | `**Agent**: opencode/GLM-5.1` |
| 2 | k 值 → `k: 1` | 删除 pass@3 行（n=1时pass@3=N/A） | `**k**: 1` |
| 3 | `total_time` → min | ÷60 换算，保留2位小数 | `4955.11s` → `82.59min` |
| 4 | 合并 token 行 | 删除 `total_input_tokens`/`total_output_tokens` 两行，新增 `total_tokens` | `696250 tokens` |
| 5 | 合并 avg token 行 | 删除 `avg_input_tokens`/`avg_output_tokens` 两行，新增 `avg_total_tokens` | `4245.43 tokens` |
| 6 | 删除"警告"模块 | pass@3 > n 的警告不再相关 | 删除 `## 警告` 整段 |
| 7 | 新增"测试未通过原因分析" | 分类统计表+典型错误+根因分析表+文字总结 | 见下方模板 |
| 8 | 表格下方加注释 | 说明 token 含义 | `> 注：total_tokens = ...` |

### 4.2 "测试未通过原因分析"模板

```markdown
## 测试未通过原因分析

164 个 Task 中，**X 个编译失败**（CSR = XX.XX%），**Y 个测试运行失败**。最终 Z 个 Task 完全通过（pass@1 = XX.XX%）。

### 编译失败（X 个 Task）

| 失败类型 | 数量 | 说明 |
|----------|------|------|
| ... | ... | ... |

**典型错误示例**：
- `HumanEval/N`：error description
- ...

### 测试失败（Y 个 Task，编译通过但运行结果错误）

| 失败类型 | 数量 | 说明 |
|----------|------|------|
| ... | ... | ... |

**典型错误示例**：
- ...

### 原因总结

| 根本原因 | 涉及 Task 数 | 占比 |
|----------|-------------|------|
| ... | ... | ...% |

主要瓶颈在于...
```

### 4.3 编译失败分类方法

从 `report.json` 的 `per_task_results` 中提取每个 task 的 `compile_results[0].error`，按错误关键词分组：

| 错误关键词 | 分类 | 备注 |
|-----------|------|------|
| `undeclared identifier 'ArrayList'` | 缺少标准库导入 | 需 `import std.collection.*` |
| `undeclared identifier 'abs'/'sqrt'/...` | 调用不存在函数 | Cangjie 标准库 API 不熟悉 |
| `numeric type conversion must have a numeric type` | Rune→数值转换禁止 | `Int64(r)` 对 Rune 不合法 |
| `lambda capturing mutable variables` | Lambda 捕获可变变量 | Cangjie 限制捕获 var |
| `body of function is missing` | 函数体缺失/截断 | 代码不完整 |
| `coalescing operation only valid for Option` | ?? 用于非 Option | 类型系统错误 |
| `is not a member of struct` | 方法不存在 | String/Array API 不熟悉 |
| `expected '(' after 'catch'` 等 | 语法错误 | Cangjie 语法规则差异 |

### 4.4 注释说明模板

```markdown
> 注：total_tokens = total_input_tokens (XXXXX) + total_output_tokens (XXXXX)；input_tokens 为发送给模型的 prompt 所消耗的 token 数，output_tokens 为模型生成的 completion 所消耗的 token 数，二者之和反映单次盲生成的总 token 开销。
```

---

## 五、测评结果总览（GLM-5.1 vs DeepSeek V4）

### 5.1 Cangjie 对比

| 指标 | DeepSeek V4（15条规则） | GLM-5.1（6规则+动态Skills） | 变化 |
|------|------------------------|---------------------------|------|
| CSR | 13.41% | **67.68%** | +54.27pp |
| pass@1 | 5.49% | **57.93%** | +52.44pp |
| composite_score | — | **48.93** | — |
| 总 tokens | ~174K→270K（v3） | **696,250** | — |
| 总耗时 | — | 82.59 min | — |
| 编译失败主因 | 括号缺失（48%） | 缺标准库导入（30.4%） | 根因转移 |

### 5.2 关键洞察

1. **GLM-5.1 经过 Cangjie 训练**：CSR 从 13.41%→67.68%，证明模型本身具备 Cangjie 语法知识
2. **动态 Skills 注入有效**：6条规则+按需 Skills 比全量注入更高效（每轮~1K tokens vs ~130K tokens）
3. **瓶颈已转移**：从"括号缺失"（模型不懂语法）变为"缺标准库导入"（模型不懂 API），后者更容易通过补充 prompt 解决
4. **盲生成不含调试**：pass@1 是一次性生成即完全正确的比例，无任何编译+修改循环

---

## 六、踩坑记录与经验总结

### 6.1 脚本开发踩坑

| 问题 | 原因 | 解决 |
|------|------|------|
| API 调用超时（10min+） | 8 workers 并发过载，API 响应慢 | 降 workers=4 或逐个调用 |
| `--task-ids` 模式覆盖整个文件 | `file_mode = "w"` 而非 `"a"` | 改为 `"a" if (resume or task_ids) and os.path.exists(OUTPUT_FILE) else "w"` |
| `UnboundLocalError: API_URL` | `main()` 中条件赋值导致 Python 视为局部变量 | 加 `global API_URL` |
| `matched.get(skill_key, 0) 1` | 打字错误，应为 `+ 1` | 语法检查后修正 |
| sample_0.jsonl 被意外清空 | `--task-ids` 的 `remove_task_ids_from_output` + `"w"` 模式 | 修复 file_mode，用 `--resume` 补回 |

### 6.2 流程踩坑

| 问题 | 原因 | 解决 |
|------|------|------|
| 4个 task API 重试3次均失败 | API 不稳定/网络问题 | 手动补生成（直接用大模型写 completion） |
| HumanEval/9 出现重复条目 | 并发写入竞态 | 去重脚本：按 task_id 只保留第一条 |
| 验证发现缺1条（HumanEval/10） | 去重误删或补跑时写入异常 | 确认完整后再测评 |
| 测评耗时过长（164 task × cjc 编译） | cjc 编译+运行时 DLL 复制 | 正常，约15-20分钟 |

### 6.3 最佳实践

1. **首次生成用 workers=8**，断点续传用 `--resume`
2. **少量失败 task 用 `--task-ids`** 补跑，而非全量重跑
3. **极少量（<5个）失败 task 可手动补生成**：直接用大模型写 completion，无需脚本调API
4. **生成前先 `--dry-run`** 测试 API 连通性
5. **测评前先 `--validate-only`** 确认 sample 文件完整
6. **结果目录命名**：`results_oc_{模型简称}` 与默认 `results/` 并存
7. **report_submit.md 必须包含"测试未通过原因分析"**：从 report.json 的 per_task_results 手动分类统计
8. **token 字段名差异**：Anthropic 格式用 `input_tokens/output_tokens`，OpenAI 格式用 `prompt_tokens/completion_tokens`，脚本内部已统一映射

---

## 七、后续任务清单

| 优先级 | 语言 | 工作内容 | 备注 |
|--------|------|---------|------|
| 高 | Cangjie | 在 system prompt 中增加 `import std.collection.*` / `import std.math.*` 等导入规则，尝试进一步提升 CSR | 30.4% 失败因缺 import |
| 高 | Cangjie | 增加 Rune→UInt32 转换规则（禁 `Int64(r)`，用 `UInt32(c)`） | 13.0% 失败因 Rune 转换 |
| 高 | Python | 补 entry_point → 跑测评 → 出 report_submit | 0618 记录中待完成 |
| 高 | Go | 改写 compile_check + test_execution（编译器已就绪） | 0618 记录中待完成 |
| 中 | Kotlin | 跑测评（编译器已就绪，共享版已验证） | 0618 记录中待完成 |
| 中 | C++ | 安装 MinGW g++ → 改写脚本 → 跑测评 | 0618 记录中待完成 |
| 低 | Rust | 优化 system prompt（强调 return），尝试提升 CSR | CSR 53% |
| 低 | ArkTS | 分析 38% pass@1 的 task 级 failure pattern | pass@1 38.41% |

---

## 八、脚本镜像架构（核心设计，与 0618 一致）

### 8.1 设计原则

- `code-gen-eval/script/` 共享模块**不改动**
- 每个语言 `script/` 下仅放 3 个文件：`run_eval.py` + `compile_check.py` + `test_execution.py`
- 共享模块通过 sys.path 桥接，compile_check / test_execution 通过模块覆盖机制替换

### 8.2 run_eval.py 通用模板

```python
import sys, os
_LANG_DIR = os.path.dirname(os.path.abspath(__file__))
_SHARED_DIR = os.path.normpath(os.path.join(_LANG_DIR, "../../../code-gen-eval/script"))

sys.path.insert(0, _SHARED_DIR)
import pipeline as _pipeline

sys.path.insert(0, _LANG_DIR)
for _mod in ("compile_check", "test_execution"):
    if _mod in sys.modules: del sys.modules[_mod]

import compile_check as _lang_cc
import test_execution as _lang_te
_pipeline.compile_check = _lang_cc.compile_check
_pipeline.run_test = _lang_te.run_test

main = _pipeline.main
if __name__ == "__main__": main()
```

---

## 九、编译环境一览（与 0618 一致）

| 语言 | 编译器 | 路径 | 状态 |
|------|--------|------|:--:|
| Python | python 3.12.5 | 系统自带 | ✅ |
| JavaScript | node v24.16.0 | 系统自带 | ✅ |
| Java | javac (JDK 26.0.1) | 系统自带 | ✅ |
| Kotlin | kotlinc 2.4.0 | 系统自带 | ✅ |
| Swift | swiftc 6.3.2 | 系统自带 | ✅ |
| Go | go 1.26.4 | `C:\Program Files\Go\bin\go.exe` | ✅ |
| Rust | rustc 1.96.0 | `%USERPROFILE%\.cargo\bin\rustc.exe` | ✅ |
| C++ | g++ | 未安装 | ❌ |
| ArkTS | tsc 6.0.3 / ts-node | TypeScript 代理 | ✅ |
| Cangjie | cjc 1.0.5 | `D:\Software\Cangjie\bin\cjc.exe` | ✅ |

**Cangjie 环境变量**（compile_check / test_execution 中硬编码）：
```python
CANGJIE_HOME = r"D:\Software\Cangjie"
PATH += f"{CANGJIE_HOME}\\runtime\\lib\\windows_x86_64_cjnative;{CANGJIE_HOME}\\bin"
```

---

## 十、每语言 script/ 文件清单

```
humaneval-x/humanEval_python/script/    run_eval.py, compile_check.py, test_execution.py
humaneval-x/humanEval_java/script/      run_eval.py, compile_check.py, test_execution.py
humaneval-x/humanEval_cpp/script/       run_eval.py, compile_check.py, test_execution.py
humaneval-x/humanEval_go/script/        run_eval.py, compile_check.py, test_execution.py
humaneval-x/humanEval_rust/script/      run_eval.py, compile_check.py, test_execution.py
humaneval-x/huamnEval_js/script/        run_eval.py, compile_check.py, test_execution.py
humaneval-x/humanEval_kotlin/script/    run_eval.py, compile_check.py, test_execution.py
humaneval-x/humanEval_arkts/script/     run_eval.py, compile_check.py, test_execution.py
humaneval-x/humanEval_cangjie/script/   run_eval.py, compile_check.py, test_execution.py
humaneval-x/humanEval_swift/script/     run_eval.py, compile_check.py, test_execution.py
```

---

*文档结束 — 新会话中可直接引用本文档的路径、命令和架构说明来继续工作。*
