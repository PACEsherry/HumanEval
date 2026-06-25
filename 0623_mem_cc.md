# HumanEval-X 多语言盲生成测评 — 全流程操作手册

> 日期: 2026-06-23 | 基于 0618~0623 两个会话的完整实操经验。
> 用途: 新会话/新 Agent 可直接按此文档接续工作，无需重新探索。

---

## 一、项目结构速览

```
Human-Eval_v1/
├── code-gen-eval/script/              # 共享测评核心（不可改动）
│   ├── pipeline.py                     # 主编排
│   ├── data.py                         # JSONL 读写 + task 校验
│   ├── evaluation.py                   # 指标计算（CSR, pass@k 等）
│   └── composite_score.py              # 综合评分
│
├── humaneval-x/
│   ├── generate_samples.py             # ★ 多语言盲生成（核心脚本）
│   ├── {lang_dir}/                     # 每个语言一个目录
│   │   ├── data/
│   │   │   ├── HumanEval_{lang}.jsonl           # 完整 benchmark（164 task）
│   │   │   ├── HumanEval_{lang}_prompt_only.jsonl  # 仅 prompt（盲生成输入）
│   │   │   └── sample.jsonl                     # LLM 盲生成结果
│   │   ├── script/
│   │   │   ├── compile_check.py       # 语言特定编译检查
│   │   │   ├── test_execution.py      # 语言特定测试执行
│   │   │   └── run_eval.py            # ★ 测评入口包装器
│   │   └── results/                   # 机审输出（或 results_cc_ds 等命名）
│   │       ├── report.json
│   │       ├── report.md
│   │       └── report_submit.md       # ★ 手动微调后的提交版
│   └── _CangjieSkills_repo/           # CangjieSkills compatible 分支克隆
│
├── .agent/skills/                      # ★ OpenCode skills 目录（从 CangjieSkills 拷贝）
└── 0623_mem_cc.md                      # ★ 本文档
```

---

## 二、全流程速览（从零到 report_submit）

```
Step 1: 准备数据
  └── 确保 {lang}/data/ 下有 HumanEval_{lang}.jsonl（含 task_id, prompt, entry_point, test）

Step 2: 生成 prompt_only.jsonl（如不存在）
  └── 从 benchmark 提取 task_id + prompt

Step 3: 盲生成 sample.jsonl
  └── python generate_samples.py --language {lang} --n 1 --workers 8

Step 4: 测评
  └── cd {lang}/script && python run_eval.py ... → results/

Step 5: 出报告
  └── 基于 report.md 手动微调 → report_submit.md
```

---

## 三、Step 1-2：数据准备

### 3.1 benchmark 字段校验

测评 pipeline 要求 benchmark 每行必须包含 4 个字段：`task_id`, `prompt`, `entry_point`, `test`。

如果缺少 `entry_point`，需在测评前注入：
```python
import json, re
lines = []
with open('data/HumanEval_{lang}.jsonl', encoding='utf-8') as f:
    for line in f:
        obj = json.loads(line)
        if not obj.get('entry_point'):
            # JS: const name = (...) => {
            m = re.search(r'(?:const|function)\s+(\w+)\s*[=(]', obj.get('prompt',''))
            # Java: public Type name(
            m = m or re.search(r'public\s+(?:static\s+)?[\w<>\[\],\s]+\s+(\w+)\s*\(', obj.get('prompt',''))
            # Rust: fn name(
            m = m or re.search(r'fn\s+(\w+)\s*[<(]', obj.get('declaration',''))
            obj['entry_point'] = m.group(1) if m else 'unknown'
        lines.append(obj)
```

### 3.2 生成 prompt_only.jsonl

```python
lines = []
with open('HumanEval_{lang}.jsonl', encoding='utf-8') as f:
    for line in f:
        obj = json.loads(line)
        lines.append({'task_id': obj['task_id'], 'prompt': obj['prompt']})
```

---

## 四、Step 3：盲生成 sample.jsonl

### 4.1 基本用法

```powershell
cd D:\ZSY\Human-Eval_v1\humaneval-x
python generate_samples.py --language cangjie --n 1 --workers 8
```

语言 key: `python|java|cpp|go|rust|javascript|kotlin|arkts|cangjie|swift`

### 4.2 API 配置（环境变量）

| 变量 | 含义 |
|------|------|
| `API_KEY` | API key |
| `API_BASE_URL` | API 端点 |
| `MODEL_NAME` | 模型名 |

脚本自动尝试 Anthropic Messages → 失败回退 OpenAI Chat Completions。

### 4.3 sample.jsonl 输出格式

```json
{
  "task_id": "HumanEval/0",
  "completion": "... 函数体代码 ...",
  "time_spent_sec": 8.77,
  "input_tokens": 88,
  "output_tokens": 412
}
```

- `input_tokens`/`output_tokens`：API 服务端 `usage` 字段直接返回
- `time_spent_sec`：脚本端 `time.time()` 打点
- 排序已修复：按 task_id 中数字部分数值排序（0→1→2，非 0→1→10→100）

### 4.4 特殊语言

| 语言 | generate_samples.py 中的处理 |
|------|------|
| Rust | `assemble_prompt()` 拼接 `prompt + declaration`（prompt 仅含注释块） |
| Cangjie | `no_opening_brace: True`；v3 system prompt 含 15 条精确语法规则 |

---

## 五、Step 4：测评

### 5.1 命令行

```powershell
cd D:\ZSY\Human-Eval_v1\humaneval-x\{lang_dir}\script

python run_eval.py `
  --agent_name "AgentName" `
  --benchmark_path "..\data\HumanEval_{lang}.jsonl" `
  --samples_path "..\data\sample.jsonl" `
  --n 1 --language "{lang}" --k_values "1,3" `
  --output_dir "..\results"
```

### 5.2 脚本镜像架构

`run_eval.py` 是各语言通用的薄包装器，核心逻辑：

```python
# 1) 共享目录 → 导入 pipeline
sys.path.insert(0, _SHARED_DIR)   # code-gen-eval/script/
import pipeline as _pipeline

# 2) 语言目录 → 覆盖 compile_check + test_execution
sys.path.insert(0, _LANG_DIR)     # {lang}/script/
for _mod in ("compile_check", "test_execution"):
    if _mod in sys.modules: del sys.modules[_mod]  # ★ 关键：清除缓存
import compile_check as _lang_cc
import test_execution as _lang_te
_pipeline.compile_check = _lang_cc.compile_check
_pipeline.run_test = _lang_te.run_test

main = _pipeline.main
```

**踩坑**：忘记 `del sys.modules` 会导致共享版模块被缓存，镜像版不生效→测试全返回 correct=0。

### 5.3 已验证的路径层级

从 `humaneval-x/{lang}/script/run_eval.py` 到共享模块：
```
../../../code-gen-eval/script/
```
即：`script/` → `{lang}/` → `humaneval-x/` → `Human-Eval_v1/` → `code-gen-eval/script/`

### 5.4 各语言 compile_check 和 test_execution 关键点

| 语言 | compile_check | test_execution |
|------|--------------|----------------|
| JS | `node --check` | `console.assert` 括号深度匹配仪表化 |
| Java | `javac`, declaration→class头+completion+`}` | `Main.java` 固定文件名, 运行时 `Arrays.asList` 计数 |
| Swift | `swiftc -typecheck`, 自动注入 `import Foundation` | assert→if 计数, 移除末尾 `check()` 调用 |
| Rust | `rustc --edition 2021 --crate-type lib`, 去外部 crate import | `AtomicU32` 计数器, `assert_eq!` 逗号分割注意 `[]` 深度 |
| ArkTS | `tsc.cmd --noEmit --lib es2020`, brace 平衡 | 双模式 `if (!(cond))` + `if (cond !== expected)` 仪表化 |
| Cangjie | `cjc --output-type=staticlib`, 需设 `CANGJIE_HOME` 环境变量 | `cjc --test`, 复制运行时 DLL, 解析 `PASSED/FAILED` |

**通用模式**：
- brace 自动平衡：`depth = code.count("{") - code.count("}")` → 补 `"}" * depth`
- 临时文件在 `finally` 块清理（`os.unlink` / `shutil.rmtree`）
- Windows 下 `.cmd` 后缀（如 `tsc.cmd`），编译器使用完整路径

---

## 六、Step 5：生成 report_submit.md

### 6.1 格式规范（mentor 要求）

对比 report.md 的改动：

| 项目 | report.md（机审原始） | report_submit.md（提交版） |
|------|---------------------|--------------------------|
| Agent 名 | 测评时传入的值 | `opencode` |
| k 值 | `k: 1, 3` | `k: 1`（删除 pass@3 行） |
| total_time | 秒（如 2227.03s） | 手动转 min（÷60） |
| tokens | input/output 分开两行 | `total_tokens` = input+output 合并一行 |
| avg tokens | avg_input / avg_output 分开 | `avg_total_tokens` 合并 |
| 警告模块 | 有 | 删除 |
| 失败分析 | 无 | 新增：分类表 + 典型错误 + 根因分析表 + 文字总结 |
| 表下注释 | 无 | 说明 token 含义 |

### 6.2 失败分析模板

```markdown
## 测试未通过原因分析

164 个 Task 中，**X 个编译失败**（CSR = ...），**Y 个测试运行失败**。最终 Z 个通过（pass@1 = ...）。

### 编译失败（X 个 Task）
| 失败类型 | 数量 | 说明 |
|----------|------|------|
...

### 测试失败（Y 个 Task）
...

### 原因总结
| 根本原因 | 涉及 Task 数 | 占比 |
|----------|-------------|------|
...
```

---

## 七、编译环境汇总

| 语言 | 编译器 | 路径 | 状态 |
|------|--------|------|:--:|
| Python | python 3.12.5 | 系统 | ✅ |
| JavaScript | node v24.16.0 | 系统 | ✅ |
| Java | javac JDK 26 | 系统 | ✅ |
| Kotlin | kotlinc 2.4.0 | 系统 | ✅ |
| Swift | swiftc 6.3.2 | 系统 | ✅ |
| Go | go 1.26.4 | `C:\Program Files\Go\bin\go.exe` | ✅ |
| Rust | rustc 1.96.0 | `%USER%\.cargo\bin\rustc.exe` | ✅ |
| C++ | g++ | 未安装 | ❌ |
| ArkTS | tsc 6.0.3 | TS 代理（`tsc.cmd` + node） | ✅ |
| Cangjie | cjc 1.0.5 | `D:\Software\Cangjie\bin\cjc.exe` | ✅ |

### Cangjie 特别配置

环境变量（脚本中硬编码）：
```python
CANGJIE_HOME = r"D:\Software\Cangjie"
PATH += f"{CANGJIE_HOME}\\runtime\\lib\\windows_x86_64_cjnative;{CANGJIE_HOME}\\bin"
```

测试执行时需复制运行时 DLL 到临时目录。

---

## 八、CangjieSkills 集成

### 8.1 仓库

- 地址: `https://gitcode.com/Cangjie-SIG/CangjieSkills`
- 分支: `cangjie-harmonyos-cbgSR-6.0.2.636-compatible`
- Skills 路径: `.agents/skills/`（注意复数 `agents`）
- 已克隆到: `_CangjieSkills_repo/`
- 已拷贝到: `.agent/skills/`（17 包，供 OpenCode 加载）

### 8.2 Skills 注入方式讨论

| 方式 | 描述 | Token 消耗 | 结论 |
|------|------|-----------|------|
| A: RAG 全量注入 | 把所有 README 拼入 system prompt | 极大（~130K/轮） | ❌ 不推荐 |
| B: OpenCode 原生检索 | skills 作为工具，Agent 按需检索 | 极小（仅命中片段） | ✅ 推荐 |
| 当前折中 | system prompt 15 条精确规则（提炼自 Skills） | ~1.5K/轮 | 用着 |

### 8.3 各 skill 包大小（仅供参考）

| 包 | 大小 | HumanEval 相关 |
|------|------|:--:|
| cangjie-lang-features | 235K | ✅ |
| cangjie-std | 148K | ✅ |
| cangjie-stdx | 140K | ✅ |
| cangjie-original-docs | 5.8M | ❌ |
| cangjie-hmos-doc-search | 26M | ❌ |
| 其他 11 个 hmos-* 包 | ~80K | ❌ |

---

## 九、常见问题与解决

| 问题 | 症状 | 根因 | 解决 |
|------|------|------|------|
| 测试全返回 correct=0 | 所有 task test 结果显示 passed=0 | Python 模块缓存导致镜像 test_execution 未生效 | `del sys.modules["test_execution"]` 后 re-import |
| WinError 193 | 脚本调用编译器失败 | 调用了无后缀的脚本文件（`tsc` 非 `tsc.cmd`） | 统一用 `.cmd` 后缀 |
| public class 文件名不匹配(Java) | javac 报错 | tempfile 随机名 ≠ `Main.java` | `mkdtemp()` + 写固定文件名 |
| f-string `{{}}` 错误 | 生成的脚本中变量未替换 | `_create_mirrors.py` 中 `.format()` 与 f-string 冲突 | 改用 `.replace()` 逐变量替换 |
| sample.jsonl 排序错乱 | task_id: 0,1,10,100... | 字符串排序导致 `"10"<"2"` | 提取数字部分做数值排序 |
| entry_point 缺失 | pipeline 报 "缺少必要字段" | benchmark 格式不含 entry_point | 测评前从 prompt 提取函数名注入 |
| cjc 找不到 DLL | Cangjie 编译器报错 | 未设 CANGJIE_HOME 和 PATH | 脚本中硬编码环境变量 + 复制 DLL |
| CangjieSkills 未生效 | OpenCode 不识别 skills | 目录名为 `.agents`(复数) 非 `.agent` | 拷贝时重命名为 `.agent/skills/` |

---

## 十、已完成测评结果总览（截至 0623）

| 语言 | CSR | pass@1 | 编译器 | 备注 |
|------|-----|--------|--------|------|
| JavaScript | 92.07% | 81.10% | node | |
| ArkTS | 91.46% | 38.41% | tsc (代理) | |
| Swift | 87.80% | 71.95% | swiftc | |
| Java | 86.59% | 82.32% | javac | |
| Rust | 53.05% | 44.51% | rustc | |
| Cangjie(新版benchmark) | 40.24% | 34.15% | cjc | 同事修改版 benchmark |
| Cangjie(旧版benchmark) | 13.41% | 5.49% | cjc | 原始 benchmark |
| Python | — | — | — | 待跑（缺 entry_point） |
| C++ | — | — | — | 待装编译器 |
| Go | — | — | — | 编译器已装，待适配脚本 |
| Kotlin | — | — | — | 待跑 |

---

## 十一、常用命令速查

```powershell
# 盲生成（单语言）
cd D:\ZSY\Human-Eval_v1\humaneval-x
python generate_samples.py --language rust --n 1 --workers 8

# 测评
cd D:\ZSY\Human-Eval_v1\humaneval-x\{lang}\script
python run_eval.py --agent_name "Agent" --benchmark_path "..\data\HumanEval_{lang}.jsonl" --samples_path "..\data\sample.jsonl" --n 1 --language "{lang}" --k_values "1,3" --output_dir "..\results"

# 快速验证编译检查（不跑全量）
python -c "
import sys, json
sys.path.insert(0, '{lang}/script')
from compile_check import compile_check
with open('{lang}/data/HumanEval_{lang}.jsonl', encoding='utf-8') as f: t = json.loads(f.readline())
with open('{lang}/data/sample.jsonl', encoding='utf-8') as f: s = json.loads(f.readline())
print(compile_check(t, s['completion']))
"
```

---

*文档结束 — 新会话中可直接引用本文档的所有路径、命令和架构说明。*
