"""
样本盲生成脚本 — 多语言支持，自动检测 Anthropic / OpenAI 兼容 API 批量生成代码补全。

原则:
  - 仅使用 task_id + prompt（来自各语言的 prompt_only.jsonl），盲生成
  - 每个 Task 生成 n 个 completion（默认 n=1）
  - 支持断点续传
  - Rust 特殊处理：拼接 prompt + declaration

用法:
  python generate_samples.py --language python --n 1
  python generate_samples.py --all --n 1
  python generate_samples.py --all --validate-only

自动读取环境变量:
  API_KEY       → API key
  API_BASE_URL  → API base URL
  MODEL_NAME    → 模型名称
"""

import json
import os
import sys
import time
import re
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 语言配置
# ---------------------------------------------------------------------------

LANG_CONFIG = {
    "python": {
        "dir": "humanEval_python",
        "suffix": "python",
        "extension": "py",
    },
    "java": {
        "dir": "humanEval_java",
        "suffix": "java",
        "extension": "java",
    },
    "cpp": {
        "dir": "humanEval_cpp",
        "suffix": "cpp",
        "extension": "cpp",
    },
    "go": {
        "dir": "humanEval_go",
        "suffix": "go",
        "extension": "go",
    },
    "rust": {
        "dir": "humanEval_rust",
        "suffix": "rust",
        "extension": "rs",
        "use_declaration": True,  # Rust prompt 仅含注释块，需拼入 declaration
    },
    "javascript": {
        "dir": "huamnEval_js",  # 目录名有typo，保留原样
        "suffix": "js",
        "extension": "js",
    },
    "kotlin": {
        "dir": "humanEval_kotlin",
        "suffix": "kotlin",
        "extension": "kt",
    },
    "arkts": {
        "dir": "humanEval_arkts",
        "suffix": "arkts",
        "extension": "ets",
    },
    "cangjie": {
        "dir": "humanEval_cangjie",
        "suffix": "cangjie",
        "extension": "cj",
        "no_opening_brace": True,  # prompt 无 {，模型需自行产出 { ... }
    },
    "swift": {
        "dir": "humanEval_swift",
        "suffix": "swift",
        "extension": "swift",
    },
}

# ---------------------------------------------------------------------------
# 各语言 System Prompt
# ---------------------------------------------------------------------------

LANG_SYSTEM_PROMPTS = {
    "python": (
        "You are an expert Python programmer. Complete the given Python function body. "
        "Return ONLY the indented function body. "
        "Do NOT repeat the function signature or docstring. "
        "No explanation. No markdown fences."
    ),
    "java": (
        "You are an expert Java programmer. Complete the given Java method body. "
        "Return ONLY the indented method body ending with a closing brace '}'. "
        "Do NOT repeat the method signature, class wrapper, or imports. "
        "No explanation. No markdown fences."
    ),
    "cpp": (
        "You are an expert C++ programmer. Complete the given C++ function body. "
        "Return ONLY the function body ending with a closing brace '}'. "
        "Do NOT repeat the function signature, includes, or namespace declarations. "
        "No explanation. No markdown fences."
    ),
    "go": (
        "You are an expert Go programmer. Complete the given Go function body. "
        "Return ONLY the indented function body ending with a closing brace '}'. "
        "Do NOT repeat the function signature or package declarations. "
        "No explanation. No markdown fences."
    ),
    "rust": (
        "You are an expert Rust programmer. Complete the given Rust function. "
        "A comment block describes the problem; a function stub with imports follows. "
        "Return ONLY the complete function (signature + body) ending with a closing brace '}'. "
        "Do NOT repeat the imports. No explanation. No markdown fences."
    ),
    "javascript": (
        "You are an expert JavaScript programmer. Complete the given JavaScript function body. "
        "Return ONLY the function body. "
        "Do NOT repeat the arrow function signature or const declaration. "
        "No explanation. No markdown fences."
    ),
    "kotlin": (
        "You are an expert Kotlin programmer. Complete the given Kotlin function body. "
        "Return ONLY the function body. "
        "Do NOT repeat the function signature or import statements. "
        "No explanation. No markdown fences."
    ),
    "arkts": (
        "You are an expert ArkTS programmer. Complete the given ArkTS function body. "
        "Return ONLY the function body ending with a closing brace '}'. "
        "Do NOT repeat the function signature. "
        "No explanation. No markdown fences."
    ),
    "cangjie": (
        "You are an expert Cangjie (仓颉) programmer. Complete the given Cangjie function body "
        "starting with '{' and ending with '}'.\n\n"
        "CRITICAL syntax rules (Cangjie differs from Swift/Rust/TS):\n"
        "1. Function signature: `func name(params): ReturnType` — colon before return type, NO '->'\n"
        "2. ALL control flow REQUIRES parentheses: `if (cond) { }`, `for (i in 0..n) { }`, `while (cond) { }`, `match (expr) { }`\n"
        "3. Types: `Int64`, `Float64`, `Bool`, `String`, `Array<T>`, `Unit` (void). NO `Int`/`Float`/`Double`.\n"
        "4. `let` for immutable, `var` for mutable. Type annotation: `let x: Int64 = 0`\n"
        "5. Array/ArrayList: use `.size` property (NOT `.length` or `.count`). `Array<T>` is fixed-size; use `ArrayList<T>` for dynamic.\n"
        "6. ArrayList needs import: `import std.collection.*`. Sort needs: `import std.sort.*`\n"
        "7. Type conversion uses constructor: `Int64(x)`, `Float64(n)` (NOT `.toInt64()`)\n"
        "8. Option type `?T` / `Option<T>`. Unwrap: `opt ?? default` (use parentheses: `(opt ?? 0) != val`), or `match (opt) { case Some(v) => ... case None => ... }`\n"
        "9. if-let pattern: `if (let Some(v) <- opt) { }`. Option chaining: `obj?.field`\n"
        "10. String interpolation: `\"${expr}\"`. Iterate chars via `s.runes()`, NOT raw `for (c in s)` (iterates bytes).\n"
        "11. Lambda: `{ params => body }`. Trailing lambda goes outside parens.\n"
        "12. Return values with `return` statement. Last expression IS also returned.\n"
        "13. `Rune` type for characters, NO arithmetic on Rune (convert via `UInt32(c)`).\n"
        "14. Range: `start..end` (half-open), `start..=end` (closed). Step: `start..end:step`.\n"
        "15. NO standalone `{ }` expression blocks. Blocks only with control flow/functions.\n"
        "Return ONLY the function body. Do NOT repeat the function signature. No explanation. No markdown fences."
    ),
    "swift": (
        "You are an expert Swift programmer. Complete the given Swift function body. "
        "Return ONLY the indented function body ending with a closing brace '}'. "
        "Do NOT repeat the function signature. No explanation. No markdown fences."
    ),
}


def get_prompt_file(lang_key: str) -> str:
    """获取指定语言的 prompt_only.jsonl 绝对路径。"""
    cfg = LANG_CONFIG[lang_key]
    return os.path.join(SCRIPT_DIR, cfg["dir"], "data", f"HumanEval_{cfg['suffix']}_prompt_only.jsonl")


def get_output_file(lang_key: str) -> str:
    """获取指定语言的 sample.jsonl 输出绝对路径。"""
    cfg = LANG_CONFIG[lang_key]
    return os.path.join(SCRIPT_DIR, cfg["dir"], "data", "sample.jsonl")


# ---------------------------------------------------------------------------
# API 配置 (自动检测环境变量)
# ---------------------------------------------------------------------------

API_KEY = (
    os.environ.get("ANTHROPIC_AUTH_TOKEN")
    or os.environ.get("ANTHROPIC_API_KEY")
    or os.environ.get("API_KEY", "")
)
API_BASE_URL = (
    os.environ.get("ANTHROPIC_BASE_URL")
    or os.environ.get("API_BASE_URL", "")
).rstrip("/")
MODEL_NAME = (
    os.environ.get("ANTHROPIC_MODEL")
    or os.environ.get("MODEL_NAME", "claude-sonnet-4-6")
)


# ---------------------------------------------------------------------------
# Prompt 组装
# ---------------------------------------------------------------------------

def assemble_prompt(entry: Dict, lang_key: str) -> str:
    """
    组装发给 LLM 的 prompt。
    普通语言直接用 prompt 字段；Rust 需要拼接 prompt + declaration。
    """
    prompt = entry.get("prompt", "")
    cfg = LANG_CONFIG.get(lang_key, {})

    if cfg.get("use_declaration"):
        declaration = entry.get("declaration", "")
        # Rust: prompt 是注释块 /* ... */, declaration 是 use 语句 + fn 签名
        if declaration:
            prompt = prompt.rstrip() + "\n" + declaration

    return prompt


# ---------------------------------------------------------------------------
# API 调用 (自动检测 Anthropic / OpenAI 格式)
# ---------------------------------------------------------------------------

def _api_headers() -> Dict[str, str]:
    """构建请求头，兼容 Anthropic (x-api-key) 和 OpenAI (Authorization: Bearer)。"""
    return {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "Authorization": f"Bearer {API_KEY}",
    }


def call_api(prompt: str, task_id: str, lang_key: str) -> Dict:
    """
    调用 API 生成一个 completion。自动尝试 Anthropic Messages 格式，
    失败则回退到 OpenAI Chat Completions 格式。

    返回:
        {"completion": str, "time_spent_sec": float,
         "input_tokens": int, "output_tokens": int}
    """
    if not API_KEY:
        raise RuntimeError("API_KEY 未设置。请检查环境变量 API_KEY")

    import urllib.request
    import urllib.error

    system_prompt = LANG_SYSTEM_PROMPTS.get(lang_key, LANG_SYSTEM_PROMPTS["swift"])
    t0 = time.time()

    # --- 尝试 Anthropic Messages 格式 ---
    body = {
        "model": MODEL_NAME,
        "max_tokens": 2048,
        "temperature": 0.8,
        "system": system_prompt,
        "messages": [{"role": "user", "content": prompt}],
    }

    url = f"{API_BASE_URL}/v1/messages"
    data_bytes = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data_bytes, headers=_api_headers())
    req.get_method = lambda: "POST"

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # Anthropic 格式响应
        content = "".join(
            b["text"] for b in data.get("content", []) if b.get("type") == "text"
        )
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        # 回退到 OpenAI Chat Completions 格式
        try:
            content, input_tokens, output_tokens = _call_openai_format(prompt, lang_key)
        except Exception:
            raise RuntimeError(f"API HTTP {e.code}: {err_body}")
    except Exception as e:
        raise RuntimeError(f"API 调用失败: {e}")

    elapsed = time.time() - t0
    completion = _clean_completion(content, lang_key)

    return {
        "completion": completion,
        "time_spent_sec": round(elapsed, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _call_openai_format(prompt: str, lang_key: str):
    """OpenAI Chat Completions 格式回退。尝试 /v1/ 和 /chat/completions 两种 URL。"""
    import urllib.request
    import urllib.error

    system_prompt = LANG_SYSTEM_PROMPTS.get(lang_key, LANG_SYSTEM_PROMPTS["swift"])

    body = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 2048,
    }
    urls_to_try = [
        f"{API_BASE_URL}/v1/chat/completions",
        f"{API_BASE_URL}/chat/completions",
    ]
    for url in urls_to_try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        )
        req.get_method = lambda: "POST"
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage = data.get("usage", {})
            return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        except urllib.error.HTTPError:
            continue
    raise RuntimeError(f"OpenAI format fallback failed for all URLs: {urls_to_try}")


# ---------------------------------------------------------------------------
# Completion 清理（语言感知）
# ---------------------------------------------------------------------------

def _clean_completion(raw: str, lang_key: str) -> str:
    """清理 API 返回的 completion：去除 markdown 代码块包装和多余内容。"""
    text = raw.strip()

    # 移除 markdown 代码块标记 ```lang ... ``` (通用匹配)
    m = re.search(r"```(?:\w+)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        text = m.group(1)

    # 语言特定的函数签名剥离
    text = _strip_function_signature(text, lang_key)

    text = text.strip()
    if not text:
        return _fallback_completion(lang_key)

    # 语言特定的收尾处理
    text = _ensure_closing(text, lang_key)

    return text


def _strip_function_signature(text: str, lang_key: str) -> str:
    """如果 API 返回了完整的函数签名，尝试剥离，只保留函数体。"""
    patterns = {
        # Python: def function_name(...):  → 从冒号后第一行开始取
        "python": [
            r'^\s*def\s+\w+\s*\([^)]*\)\s*(->\s*\w+)?\s*:',
        ],
        # Java: public/private/protected Type methodName(...) {  → 从 { 之后取
        "java": [
            r'^\s*(public|private|protected|static|\s)+[\w<>\[\],\s]+\s+\w+\s*\([^)]*\)\s*\{',
        ],
        # C++: Type functionName(...) {  → 从 { 之后取
        "cpp": [
            r'^\s*[\w:<>\[\],\s*&]+\s+\w+\s*\([^)]*\)\s*\{',
        ],
        # Go: func Name(...) Type {  → 从 { 之后取
        "go": [
            r'^\s*func\s+\w+\s*\([^)]*\)\s*[\w\[\]*.,\s]*\{',
        ],
        # Rust: fn name(...) -> Type {  → 从 { 之后取
        "rust": [
            r'^\s*(pub\s+)?fn\s+\w+\s*[<(][^)>]*[>)]\s*(->\s*[\w:<>\s,+]*)?\s*\{',
        ],
        # JavaScript: const name = (...) => {  → 从 { 之后取
        "javascript": [
            r'^\s*(const|let|var)\s+\w+\s*=\s*\([^)]*\)\s*=>\s*\{',
            r'^\s*function\s+\w+\s*\([^)]*\)\s*\{',
        ],
        # Kotlin: fun name(...): Type {  → 从 { 之后取
        "kotlin": [
            r'^\s*(suspend\s+)?fun\s+\w+\s*\([^)]*\)\s*(:\s*\w+)?\s*\{',
        ],
        # ArkTS: function name(...): Type {  → 从 { 之后取
        "arkts": [
            r'^\s*function\s+\w+\s*\([^)]*\)\s*(:\s*\w+)?\s*\{',
        ],
        # Cangjie: func name(...): Type {  → 从 { 之后取
        "cangjie": [
            r'^\s*func\s+\w+\s*\([^)]*\)\s*(:\s*\w+[<?\w>?]*)?\s*\{',
        ],
        # Swift: func name(...) -> Type {  → 从 { 之后取
        "swift": [
            r'^\s*func\s+\w+\s*[<(][^)>]*[>)]\s*(throws\s+)?(->\s*\w+)?\s*\{',
        ],
    }

    lang_patterns = patterns.get(lang_key, [])
    for pat in lang_patterns:
        func_match = re.match(pat, text)
        if func_match:
            # 从第一个 { 之后取
            brace_idx = text.find('{', func_match.end() - 1)
            if brace_idx != -1:
                text = text[brace_idx + 1:]
            else:
                # 没有 {，可能是 Python 风格
                text = text[func_match.end():]
            break

    return text


def _ensure_closing(text: str, lang_key: str) -> str:
    """确保 completion 以合适的括号包裹。"""
    cfg = LANG_CONFIG.get(lang_key, {})
    # 需要闭合大括号的语言
    brace_langs = {"java", "cpp", "go", "rust", "javascript", "kotlin", "arkts", "cangjie", "swift"}

    if lang_key in brace_langs:
        # 如果 prompt 中没有 {，而模型也没有产出 {，则补上
        if cfg.get("no_opening_brace") and not text.strip().startswith('{'):
            text = '{\n' + text.strip()
        # 确保以 } 结尾
        if not text.rstrip().endswith('}'):
            text = text.rstrip() + '\n}'

    # Python 不需要额外处理，缩进即可
    return text


def _fallback_completion(lang_key: str) -> str:
    """API 返回空内容时的占位 completion。"""
    fallbacks = {
        "python": "    # TODO: implement\n    pass\n",
        "java": "    // TODO: implement\n    return null;\n}\n",
        "cpp": "    // TODO: implement\n    return {};\n}\n",
        "go": "    // TODO: implement\n    return nil\n}\n",
        "rust": "    // TODO: implement\n    todo!()\n}\n",
        "javascript": "    // TODO: implement\n    return undefined;\n}\n",
        "kotlin": "    // TODO: implement\n    return TODO()\n",
        "arkts": "    // TODO: implement\n    return undefined;\n}\n",
        "cangjie": "    // TODO: implement\n    return\n",
        "swift": "    // TODO: implement\n    return\n}\n",
    }
    return fallbacks.get(lang_key, "    // TODO: implement\n")


# ---------------------------------------------------------------------------
# 批量生成
# ---------------------------------------------------------------------------

def generate_all_samples(
    lang_key: str,
    n: int,
    start_from: int = 0,
    delay: float = 0.1,
    workers: int = 8,
) -> int:
    """
    并发批量生成 sample.jsonl。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    prompt_file = get_prompt_file(lang_key)
    output_file = get_output_file(lang_key)

    if not os.path.exists(prompt_file):
        print(f"错误: {prompt_file} 不存在")
        return 0

    prompts = []
    with open(prompt_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                prompts.append(json.loads(line))

    total_tasks = len(prompts)
    expected_total = total_tasks * n
    print(f"[{lang_key}] Task 总数: {total_tasks} | n={n} | 总计 {expected_total} 样本")
    print(f"  模型: {MODEL_NAME} | 并发: {workers} | API: {API_BASE_URL}")
    print(f"  输出: {output_file}")
    print()

    # 构建任务列表 (跳过已完成)
    tasks = []
    for i in range(start_from, total_tasks):
        entry = prompts[i]
        for j in range(n):
            tasks.append((entry, j, i))

    print(f"  待生成: {len(tasks)} 个 API 调用")
    print()

    write_lock = threading.Lock()
    total_written = [0]
    failed = [0]

    def do_call(task_info):
        entry, j, task_idx = task_info
        tid = entry["task_id"]
        prompt = assemble_prompt(entry, lang_key)

        attempt = 0
        while attempt < 3:
            try:
                result = call_api(prompt, tid, lang_key)
                sample = {"task_id": tid, "completion": result["completion"]}
                for field in ["time_spent_sec", "input_tokens", "output_tokens"]:
                    if field in result and result[field] is not None:
                        sample[field] = result[field]
                return ("ok", sample, None)
            except Exception as e:
                attempt += 1
                if attempt >= 3:
                    return ("fail", {
                        "task_id": tid,
                        "completion": _fallback_completion(lang_key),
                        "time_spent_sec": 0,
                    }, str(e))
                time.sleep(2 ** attempt)
        return ("fail", None, "unreachable")

    with open(output_file, "w", encoding="utf-8") as out:
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
                    if len(completed_tasks) % 20 == 0 or len(completed_tasks) == total_tasks - start_from:
                        print(f"  [{lang_key}] {len(completed_tasks)}/{total_tasks - start_from} Tasks "
                              f"({total_written[0]} 样本, {failed[0]} 失败)")

                if delay > 0:
                    time.sleep(delay)

    print(f"\n[{lang_key}] 完成: {total_written[0]} 样本 ({failed[0]} 失败) → {output_file}")

    # 按 task_id 排序
    _sort_output(output_file)

    return total_written[0]


def _sort_output(output_file: str) -> None:
    """按 task_id 对输出文件排序（同 task 样本聚在一起）。"""
    if not os.path.exists(output_file):
        return
    samples = []
    with open(output_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))
    # 按 task_id 中的数字部分数值排序（避免 "10" < "2"）
    def _num_key(s):
        m = re.search(r'(\d+)', s.get("task_id", ""))
        return int(m.group(1)) if m else 0
    samples.sort(key=_num_key)
    with open(output_file, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------

def validate_samples(lang_key: str, n: int) -> bool:
    """验证 sample.jsonl 格式和数量。"""
    output_file = get_output_file(lang_key)

    if not os.path.exists(output_file):
        print(f"[{lang_key}] 错误: {output_file} 不存在")
        return False

    task_counts: Dict[str, int] = {}
    total = 0
    with open(output_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            tid = obj.get("task_id", "")
            task_counts[tid] = task_counts.get(tid, 0) + 1
            total += 1

    issues = [tid for tid, cnt in task_counts.items() if cnt != n]

    if issues:
        print(f"[{lang_key}] 验证失败 — {len(issues)} 个 Task 样本数 ≠ {n}:")
        for tid in issues[:10]:
            print(f"    {tid}: {task_counts[tid]}")
        return False

    print(f"[{lang_key}] 验证通过: {len(task_counts)} Tasks × {n} = {total} 样本")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def validate_all_languages(n: int) -> Dict[str, bool]:
    """验证所有语言的 sample.jsonl。"""
    results = {}
    for lang_key in LANG_CONFIG:
        results[lang_key] = validate_samples(lang_key, n)
    return results


def main():
    global MODEL_NAME, API_KEY, API_BASE_URL

    import argparse
    p = argparse.ArgumentParser(description="盲生成多语言代码补全样本")
    p.add_argument("--language", default=None,
                   choices=list(LANG_CONFIG.keys()),
                   help="目标语言 (python/java/cpp/go/rust/javascript/kotlin/arkts/cangjie/swift)")
    p.add_argument("--all", action="store_true",
                   help="为所有 10 种语言生成 sample.jsonl")
    p.add_argument("--n", type=int, default=1,
                   help="每个 Task 生成样本数 (默认 1)")
    p.add_argument("--start-from", type=int, default=0,
                   help="从第几个 Task 开始 (用于断点续传)")
    p.add_argument("--delay", type=float, default=0.1,
                   help="API 调用间隔秒数")
    p.add_argument("--workers", type=int, default=8,
                   help="并发线程数 (默认 8)")
    p.add_argument("--model", default=None,
                   help=f"模型名称 (默认: {MODEL_NAME})")
    p.add_argument("--api-key", default=None,
                   help="API key (默认: $API_KEY)")
    p.add_argument("--api-base", default=None,
                   help=f"API base URL (默认: {API_BASE_URL})")
    p.add_argument("--validate-only", action="store_true",
                   help="仅验证已有 sample.jsonl，不生成")
    args = p.parse_args()

    # 用命令行参数覆盖全局配置
    if args.model:
        MODEL_NAME = args.model
    if args.api_key:
        API_KEY = args.api_key
    if args.api_base:
        API_BASE_URL = args.api_base

    # --- 仅验证模式 ---
    if args.validate_only:
        if args.all:
            results = validate_all_languages(args.n)
            all_ok = all(results.values())
            print(f"\n总计: {sum(results.values())}/{len(results)} 语言通过")
            sys.exit(0 if all_ok else 1)
        elif args.language:
            ok = validate_samples(args.language, args.n)
            sys.exit(0 if ok else 1)
        else:
            print("请指定 --language 或 --all")
            sys.exit(1)

    # --- 生成模式 ---
    if not API_KEY:
        print("错误: 请设置 API_KEY 环境变量或通过 --api-key 参数提供")
        print("用法: export API_KEY=your_key")
        print("  或: python generate_samples.py --api-key your_key --language python")
        sys.exit(1)

    if args.all:
        # 为所有语言生成
        results = {}
        for lang_key in LANG_CONFIG:
            print(f"\n{'='*60}")
            print(f"  开始: {lang_key}")
            print(f"{'='*60}\n")
            try:
                total = generate_all_samples(
                    lang_key=lang_key,
                    n=args.n,
                    start_from=args.start_from,
                    delay=args.delay,
                    workers=args.workers,
                )
                results[lang_key] = total
                validate_samples(lang_key, args.n)
            except Exception as e:
                print(f"[{lang_key}] 错误: {e}")
                results[lang_key] = 0

        print(f"\n{'='*60}")
        print("  全部完成")
        print(f"{'='*60}")
        for lang_key, count in results.items():
            status = "✓" if count > 0 else "✗"
            print(f"  {status} {lang_key}: {count} 样本")
        return

    if args.language:
        total = generate_all_samples(
            lang_key=args.language,
            n=args.n,
            start_from=args.start_from,
            delay=args.delay,
            workers=args.workers,
        )
        validate_samples(args.language, args.n)
        return

    # 未指定语言
    p.print_help()


if __name__ == "__main__":
    main()