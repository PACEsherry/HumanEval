"""
Cangjie (仓颉) 专项盲生成脚本 — GLM-5.1 + 动态 Skills 注入。

基于 generate_samples.py，专门为 Cangjie 语言定制：
  - 6条精简 system prompt 规则（而非15条）
  - 按 task prompt 关键词动态加载 CangjieSkills README 精华段落
  - OpenAI Chat Completions 格式直接调用 GLM-5.1 API
  - 精确 token 统计（usage.prompt_tokens / usage.completion_tokens）
  - 输出 sample_0.jsonl（与现有 sample.jsonl 并存）

用法:
  python generate_samples_cj.py --n 1 --workers 8
  python generate_samples_cj.py --n 1 --validate-only

环境变量 (可命令行覆盖):
  CJ_API_KEY       → API key
  CJ_API_BASE_URL  → API base URL
  CJ_MODEL_NAME    → 模型名称
"""

import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))

LANG_DIR = os.path.join(SCRIPT_DIR, "humanEval_cangjie")
DATA_DIR = os.path.join(LANG_DIR, "data")
PROMPT_FILE = os.path.join(DATA_DIR, "HumanEval_cangjie_prompt_only.jsonl")
OUTPUT_FILE = os.path.join(DATA_DIR, "sample_0.jsonl")

SKILLS_DIR = os.path.join(PROJECT_DIR, ".agent", "skills", "cangjie-lang-features")

# ---------------------------------------------------------------------------
# API 配置
# ---------------------------------------------------------------------------

DEFAULT_API_KEY = "sk-ENriBfblBuYZqZ1hAjJz5g"
DEFAULT_API_BASE_URL = "http://113.46.219.251:8080/v1"
DEFAULT_MODEL_NAME = "GLM-5.1"

API_KEY = os.environ.get("CJ_API_KEY", DEFAULT_API_KEY)
API_BASE_URL = os.environ.get("CJ_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
MODEL_NAME = os.environ.get("CJ_MODEL_NAME", DEFAULT_MODEL_NAME)

API_URL = f"{API_BASE_URL}/chat/completions"

# ---------------------------------------------------------------------------
# 6条精简 system prompt 规则
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_BASE = (
    "You are an expert Cangjie (仓颉) programmer. "
    "Complete the given Cangjie function body starting with '{' and ending with '}'. "
    "Return ONLY the function body. Do NOT repeat the function signature. "
    "No explanation. No markdown fences.\n\n"
    "CRITICAL syntax rules (Cangjie differs from Swift/Rust/TS):\n"
    "1. Function signature: `func name(params): ReturnType` — colon before return type, NO '->'. "
    "Types: Int64, Float64, Bool, String, Array<T>, Unit. NO Int/Float/Double.\n"
    "2. ALL control flow REQUIRES parentheses: `if (cond) { }`, `for (i in 0..n) { }`, "
    "`while (cond) { }`, `match (expr) { }`.\n"
    "3. `let` for immutable, `var` for mutable. Array uses `.size` (NOT .length). "
    "Dynamic list: ArrayList<T> needs `import std.collection.*`. Sort needs `import std.sort.*`.\n"
    "4. Option: `?T` = Option<T>. Unwrap: `(opt ?? default)` or `match (opt) { case Some(v) => ... case None => ... }`. "
    "Type conversion: Int64(x), Float64(n) (NOT .toInt64()).\n"
    "5. String interpolation: \"${expr}\". Char iteration via `.runes()` (NOT raw for-in on String, which iterates bytes). "
    "Range: 0..n (half-open), 0..=n (closed). Step: 0..10:2.\n"
    "6. No standalone { } expression blocks. Blocks only with control flow/functions. "
    "Use `return` for explicit return. Last expression also returned."
)

# ---------------------------------------------------------------------------
# Skills 关键词映射 + 动态加载
# ---------------------------------------------------------------------------

SKILL_KEYWORD_MAP: Dict[str, List[str]] = {
    "string": [
        "String", "字符串", "substring", "split", "concat", "replace",
        "lowercase", "uppercase", "trim", "char", "letter", "text",
        "encode", "decode", "format",
    ],
    "array": [
        "Array", "ArrayList", "列表", "list", "append", "remove", "sort",
        "filter", "map", "reverse", "slice", "index", "size", "collection",
    ],
    "option": [
        "Option", "?T", "None", "Some", "nullable", "optional",
    ],
    "pattern_match": [
        "match", "case", "switch", "pattern",
    ],
    "for": [
        "for", "while", "循环", "loop", "iterate", "iteration", "Range",
        "区间", "range",
    ],
    "function": [
        "func", "函数", "lambda", "closure", "递归", "recursion", "callback",
        "compose",
    ],
    "basic_data_type": [
        "Int64", "Float64", "Bool", "Rune", "Tuple", "元组", "整数", "浮点",
        "integer", "float", "boolean", "number",
    ],
    "basic_concepts": [
        "let", "var", "变量", "variable", "scope", "作用域", "包", "package",
        "import",
    ],
    "error_handle": [
        "try", "catch", "throw", "exception", "error", "异常",
    ],
}

SKILL_README_PATHS: Dict[str, str] = {
    "string": os.path.join(SKILLS_DIR, "string", "README.md"),
    "array": os.path.join(SKILLS_DIR, "collections", "array", "README.md"),
    "arraylist": os.path.join(SKILLS_DIR, "collections", "arraylist", "README.md"),
    "option": os.path.join(SKILLS_DIR, "option", "README.md"),
    "pattern_match": os.path.join(SKILLS_DIR, "pattern_match", "README.md"),
    "for": os.path.join(SKILLS_DIR, "for", "README.md"),
    "function": os.path.join(SKILLS_DIR, "function", "README.md"),
    "basic_data_type": os.path.join(SKILLS_DIR, "basic_data_type", "README.md"),
    "basic_concepts": os.path.join(SKILLS_DIR, "basic_concepts", "README.md"),
    "error_handle": os.path.join(SKILLS_DIR, "error_handle", "README.md"),
}

MAX_SKILL_LINES = 80
MAX_SKILL_SNIPPETS = 3

_skill_cache: Dict[str, str] = {}


def load_skill_snippet(skill_key: str) -> str:
    """加载指定 skill README 的前 MAX_SKILL_LINES 行作为精华段落。"""
    if skill_key in _skill_cache:
        return _skill_cache[skill_key]

    path = SKILL_README_PATHS.get(skill_key)
    if not path or not os.path.exists(path):
        return ""

    with open(path, "r", encoding="utf-8") as f:
        lines = []
        for i, line in enumerate(f):
            if i >= MAX_SKILL_LINES:
                break
            lines.append(line.rstrip("\n"))

    snippet = "\n".join(lines)
    _skill_cache[skill_key] = snippet
    return snippet


def select_skills_for_task(prompt: str) -> List[str]:
    """根据 task prompt 关键词选择最相关的 skill keys。"""
    matched: Dict[str, int] = {}
    lower_prompt = prompt.lower()

    for skill_key, keywords in SKILL_KEYWORD_MAP.items():
        for kw in keywords:
            if kw.lower() in lower_prompt:
                matched[skill_key] = matched.get(skill_key, 0) + 1
                break

    if not matched:
        return ["basic_concepts"]

    ranked = sorted(matched.keys(), key=lambda k: matched[k], reverse=True)
    result = []
    for k in ranked[:MAX_SKILL_SNIPPETS]:
        if k == "array":
            result.append("array")
            if len(result) < MAX_SKILL_SNIPPETS:
                result.append("arraylist")
        else:
            result.append(k)

    return result[:MAX_SKILL_SNIPPETS]


def build_system_prompt(task_prompt: str) -> str:
    """构建完整 system prompt：6条规则 + 动态 skill 段落。"""
    skill_keys = select_skills_for_task(task_prompt)

    snippets = []
    for sk in skill_keys:
        snippet = load_skill_snippet(sk)
        if snippet:
            skill_name = sk.replace("_", " ").title()
            snippets.append(f"\n\n--- Reference: {skill_name} ---\n{snippet}")

    skill_section = "".join(snippets)
    return SYSTEM_PROMPT_BASE + skill_section


# ---------------------------------------------------------------------------
# Completion 清理（Cangjie 专用）
# ---------------------------------------------------------------------------

def clean_completion(raw: str) -> str:
    """清理 API 返回的 completion：去除 markdown 代码块和函数签名。"""
    text = raw.strip()

    m = re.search(r"```(?:\w+)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        text = m.group(1)

    text = strip_function_signature(text)
    text = text.strip()

    if not text:
        return "{\n    // TODO: implement\n    return\n}"

    text = ensure_closing(text)
    return text


def strip_function_signature(text: str) -> str:
    """如果 API 返回了完整的函数签名，剥离只保留函数体。"""
    pat = r'^\s*func\s+\w+\s*\([^)]*\)\s*(:\s*\w+[<?\w>?]*)?\s*\{'
    func_match = re.match(pat, text)
    if func_match:
        brace_idx = text.find('{', func_match.end() - 1)
        if brace_idx != -1:
            text = text[brace_idx + 1:]
    return text


def ensure_closing(text: str) -> str:
    """确保 completion 以 { 开头、} 结尾（Cangjie prompt 无 {）。"""
    if not text.strip().startswith('{'):
        text = '{\n' + text.strip()
    if not text.rstrip().endswith('}'):
        text = text.rstrip() + '\n}'
    return text


# ---------------------------------------------------------------------------
# API 调用 (OpenAI Chat Completions)
# ---------------------------------------------------------------------------

def call_api(prompt: str, task_id: str, system_prompt: str) -> Dict:
    """调用 GLM-5.1 API 生成一个 completion，返回精确 token 统计。"""
    import urllib.request
    import urllib.error

    body = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 2048,
    }

    data_bytes = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    req = urllib.request.Request(API_URL, data=data_bytes, headers=headers)
    req.get_method = lambda: "POST"

    t0 = time.time()

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"API HTTP {e.code}: {err_body}")
    except Exception as e:
        raise RuntimeError(f"API call failed: {e}")

    elapsed = time.time() - t0

    choice = data["choices"][0]
    content = choice["message"]["content"]

    usage = data.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    completion = clean_completion(content)

    return {
        "completion": completion,
        "time_spent_sec": round(elapsed, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


# ---------------------------------------------------------------------------
# 批量生成
# ---------------------------------------------------------------------------

def load_existing_task_ids(output_file: str) -> set:
    """从已有的输出文件中读取已完成的 task_id集合。"""
    existing = set()
    if os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    obj = json.loads(line)
                    tid = obj.get("task_id", "")
                    existing.add(tid)
    return existing


def remove_task_ids_from_output(task_ids: set) -> None:
    """从 OUTPUT_FILE 中删除指定 task_id 的条目。"""
    if not os.path.exists(OUTPUT_FILE):
        return
    samples = []
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                obj = json.loads(line)
                if obj.get("task_id") not in task_ids:
                    samples.append(obj)
    print(f"  Removed {len(task_ids)} task_ids from existing output")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def generate_all_samples(n: int, workers: int, delay: float = 0.05, resume: bool = False,
                         task_ids: Optional[set] = None) -> int:
    """并发批量生成 sample_0.jsonl。支持 resume 断点续传。"""
    if not os.path.exists(PROMPT_FILE):
        print(f"Error: {PROMPT_FILE} does not exist")
        return 0

    prompts = []
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                prompts.append(json.loads(line))

    total_tasks = len(prompts)

    existing_ids = set()
    if resume:
        existing_ids = load_existing_task_ids(OUTPUT_FILE)
        print(f"  Resume mode: {len(existing_ids)} tasks already completed")

    tasks = []
    for i in range(total_tasks):
        entry = prompts[i]
        tid = entry["task_id"]
        if task_ids and tid not in task_ids:
            continue
        if resume and tid in existing_ids:
            continue
        for j in range(n):
            tasks.append((entry, j, i))

    new_tasks = len(tasks)
    if task_ids:
        print(f"[Cangjie/GLM-5.1] Target tasks: {len(task_ids)} | New: {new_tasks} | n={n}")
    else:
        print(f"[Cangjie/GLM-5.1] Total tasks: {total_tasks} | New: {new_tasks} | n={n}")
    print(f"  Model: {MODEL_NAME} | Workers: {workers} | API: {API_URL}")
    print(f"  Output: {OUTPUT_FILE}")
    print()

    if new_tasks == 0:
        print("  All tasks already completed. Nothing to generate.")
        sort_output(OUTPUT_FILE)
        return 0

    print(f"  To generate: {new_tasks} API calls")
    print()

    write_lock = threading.Lock()
    total_written = [0]
    failed = [0]

    def do_call(task_info):
        entry, j, task_idx = task_info
        tid = entry["task_id"]
        prompt = entry.get("prompt", "")

        system_prompt = build_system_prompt(prompt)

        attempt = 0
        while attempt < 3:
            try:
                result = call_api(prompt, tid, system_prompt)
                sample = {
                    "task_id": tid,
                    "completion": result["completion"],
                    "time_spent_sec": result["time_spent_sec"],
                    "input_tokens": result["input_tokens"],
                    "output_tokens": result["output_tokens"],
                }
                return ("ok", sample, None)
            except Exception as e:
                attempt += 1
                if attempt >= 3:
                    return ("fail", {
                        "task_id": tid,
                        "completion": "{\n    // TODO: implement\n    return\n}",
                        "time_spent_sec": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                    }, str(e))
                time.sleep(2 ** attempt)
        return ("fail", None, "unreachable")

    file_mode = "a" if (resume or task_ids) and os.path.exists(OUTPUT_FILE) else "w"
    with open(OUTPUT_FILE, file_mode, encoding="utf-8") as out:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(do_call, t): t for t in tasks}
            completed_tasks = set()

            for future in as_completed(futures):
                status, sample, err = future.result()
                with write_lock:
                    out.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    out.flush()
                    total_written[0] += 1
                    if status == "fail":
                        failed[0] += 1

                task_info = futures[future]
                task_idx = task_info[2]
                if task_idx not in completed_tasks:
                    completed_tasks.add(task_idx)
                    if len(completed_tasks) % 20 == 0 or len(completed_tasks) == new_tasks:
                        print(f"  [Cangjie] {len(completed_tasks)}/{total_tasks} Tasks "
                              f"({total_written[0]} samples, {failed[0]} failed)")

                if delay > 0:
                    time.sleep(delay)

    print(f"\n[Cangjie/GLM-5.1] Done: {total_written[0]} samples ({failed[0]} failed) -> {OUTPUT_FILE}")

    sort_output(OUTPUT_FILE)
    return total_written[0]


# ---------------------------------------------------------------------------
# 排序
# ---------------------------------------------------------------------------

def sort_output(output_file: str) -> None:
    """按 task_id 数字排序输出文件。"""
    if not os.path.exists(output_file):
        return
    samples = []
    with open(output_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))

    def num_key(s):
        m = re.search(r'(\d+)', s.get("task_id", ""))
        return int(m.group(1)) if m else 0

    samples.sort(key=num_key)
    with open(output_file, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------

def validate_samples(n: int) -> bool:
    """验证 sample_0.jsonl 格式和数量。"""
    if not os.path.exists(OUTPUT_FILE):
        print(f"[Cangjie] Error: {OUTPUT_FILE} does not exist")
        return False

    task_counts: Dict[str, int] = {}
    total = 0
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            tid = obj.get("task_id", "")
            task_counts[tid] = task_counts.get(tid, 0) + 1
            total += 1

    issues = [tid for tid, cnt in task_counts.items() if cnt != n]

    if issues:
        print(f"[Cangjie] Validation FAILED — {len(issues)} tasks with count != {n}:")
        for tid in issues[:10]:
            print(f"    {tid}: {task_counts[tid]}")
        return False

    print(f"[Cangjie] Validation passed: {len(task_counts)} tasks x {n} = {total} samples")

    total_input = 0
    total_output = 0
    total_time = 0.0
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            total_input += obj.get("input_tokens", 0)
            total_output += obj.get("output_tokens", 0)
            total_time += obj.get("time_spent_sec", 0)

    print(f"  Total tokens: input={total_input}, output={total_output}, "
          f"combined={total_input + total_output}")
    print(f"  Total time: {total_time:.2f}s ({total_time/60:.2f}min)")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    global API_KEY, API_BASE_URL, MODEL_NAME, API_URL

    import argparse
    p = argparse.ArgumentParser(description="Cangjie 盲生成 — GLM-5.1 + 动态 Skills 注入")
    p.add_argument("--n", type=int, default=1, help="Samples per task (default 1)")
    p.add_argument("--workers", type=int, default=8, help="Concurrent threads (default 8)")
    p.add_argument("--delay", type=float, default=0.05, help="API call interval seconds")
    p.add_argument("--model", default=None, help=f"Model name (default: {MODEL_NAME})")
    p.add_argument("--api-key", default=None, help="API key (default: built-in)")
    p.add_argument("--api-base", default=None, help=f"API base URL (default: {API_BASE_URL})")
    p.add_argument("--validate-only", action="store_true", help="Only validate existing sample_0.jsonl")
    p.add_argument("--resume", action="store_true",
                   help="Resume from existing sample_0.jsonl, skip already completed task_ids")
    p.add_argument("--task-ids", default=None,
                   help="Only generate specific task_ids, comma-separated numeric (e.g. '10,93,118,129'). "
                        "Overwrites existing entries for those task_ids in sample_0.jsonl.")
    p.add_argument("--dry-run", action="store_true",
                   help="Test API connectivity with 1 task, no output file written")
    args = p.parse_args()

    if args.task_ids:
        specified_ids = {f"HumanEval/{int(x.strip())}" for x in args.task_ids.split(",") if x.strip()}
        remove_task_ids_from_output(specified_ids)
        total = generate_all_samples(
            n=args.n, workers=args.workers, delay=args.delay,
            resume=False, task_ids=specified_ids,
        )
        sort_output(OUTPUT_FILE)
        validate_samples(args.n)
        return total

    if args.model:
        MODEL_NAME = args.model
    if args.api_key:
        API_KEY = args.api_key
    if args.api_base:
        API_BASE_URL = args.api_base.rstrip("/")
        API_URL = f"{API_BASE_URL}/chat/completions"

    if args.validate_only:
        ok = validate_samples(args.n)
        sys.exit(0 if ok else 1)

    if args.dry_run:
        print("--- Dry Run: testing API connectivity ---")
        print(f"  API: {API_URL}")
        print(f"  Model: {MODEL_NAME}")
        if not os.path.exists(PROMPT_FILE):
            print(f"  Error: {PROMPT_FILE} does not exist")
            sys.exit(1)
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            first_task = json.loads(f.readline())
        prompt = first_task.get("prompt", "")
        system_prompt = build_system_prompt(prompt)
        print(f"  Task: {first_task['task_id']}")
        print(f"  System prompt length: {len(system_prompt)} chars")
        skill_keys = select_skills_for_task(prompt)
        print(f"  Injected skills: {skill_keys}")
        try:
            result = call_api(prompt, first_task["task_id"], system_prompt)
            print(f"  Completion length: {len(result['completion'])} chars")
            print(f"  Tokens: input={result['input_tokens']}, output={result['output_tokens']}")
            print(f"  Time: {result['time_spent_sec']}s")
            print(f"  Completion preview:\n{result['completion'][:200]}...")
            print("\n--- Dry Run SUCCESS ---")
        except Exception as e:
            print(f"  Error: {e}")
            print("\n--- Dry Run FAILED ---")
            sys.exit(1)
        return

    if not API_KEY:
        print("Error: API key not set")
        sys.exit(1)

    total = generate_all_samples(n=args.n, workers=args.workers, delay=args.delay, resume=args.resume)
    validate_samples(args.n)
    return total


if __name__ == "__main__":
    main()
