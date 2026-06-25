"""
测试执行与性能采集模块。

对编译成功的样本运行测试，同步采集：
- 测试通过的 assert 数 (passed / total)
- 执行时间 (execution_time_sec)
- 最大内存 (max_memory_mb)
- 总内存积分 (total_memory_mb_sec, 梯形法)

支持多种编程语言。
"""

import subprocess
import tempfile
import os
import re
import time
import sys
from typing import Dict, List, Optional, Tuple

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def _find_python() -> str:
    """检测系统可用的 Python 命令 (python 优先，避免 Windows Store 假 python3)。"""
    import shutil
    for cmd in ("python", "python3"):
        if shutil.which(cmd):
            return cmd
    return "python"  # fallback


# ---------------------------------------------------------------------------
# 语言配置
# ---------------------------------------------------------------------------

LANGUAGE_CONFIG = {
    "kotlin": {
        "extension": ".kts",
        "run_cmd": ["kotlin"],
        "assert_pattern": r"\bassert\s*\(",
        "instrument_assert_fn": "_instrument_assert_kotlin",
        "result_pattern": r"__ASSERT_RESULT:\s*(\d+)\s*/\s*(\d+)",
    },
    "python": {
        "extension": ".py",
        "run_cmd": [_find_python()],
        "assert_pattern": r"\bassert\s+",
        "instrument_assert_fn": "_instrument_assert_python",
        "result_pattern": r"__ASSERT_RESULT:\s*(\d+)\s*/\s*(\d+)",
    },
    "javascript": {
        "extension": ".js",
        "run_cmd": ["node"],
        "assert_pattern": r"\bconsole\.assert\s*\(",
        "instrument_assert_fn": "_instrument_assert_javascript",
        "result_pattern": r"__ASSERT_RESULT:\s*(\d+)\s*/\s*(\d+)",
    },
    "swift": {
        "extension": ".swift",
        "run_cmd": ["swiftc"],
        "run_mode": "compile_and_run",       # 编译为 .exe 后执行
        "assert_pattern": r"\bassert\s*\(",
        "instrument_assert_fn": "_instrument_assert_swift",
        "result_pattern": r"__ASSERT_RESULT:\s*(\d+)\s*/\s*(\d+)",
    },
    "arkts": {
        "extension": ".ts",
        "run_cmd": ["ts-node", "--compiler-options",
                     '{"target":"ES2022","module":"commonjs","strict":false}'],
        "run_mode": "direct",
        "assert_pattern": r"\bif\s*\(\s*!\s*\(",
        "instrument_assert_fn": "_instrument_assert_arkts",
        "result_pattern": r"__ASSERT_RESULT:\s*(\d+)\s*/\s*(\d+)",
    },
}

# ---------------------------------------------------------------------------
# Assert 仪表化 (per language)
# ---------------------------------------------------------------------------

def _instrument_assert_kotlin(test_code: str) -> Tuple[str, int]:
    """
    将 Kotlin test 代码中的 assert(...) 替换为计数版本。

    Kotlin assert 语法: assert(condition)
    替换为:
      __total__++
      try { if (!(condition)) throw AssertionError(""); __passed__++ }
      catch (e: AssertionError) { }

    注意: Kotlin 的 assert 在非 -ea 模式下不抛异常，所以直接用 if 模拟。
    """
    total_count = 0

    result = []
    i = 0
    while i < len(test_code):
        m = re.search(r'assert\s*\(',test_code[i:])
        if not m:
            result.append(test_code[i:])
            break
        result.append(test_code[i:i + m.start()])
        start = i + m.end()
        depth = 1
        j = start
        while j < len(test_code) and depth > 0:
            if test_code[j] == '(':
                depth += 1
            elif test_code[j] == ')':
                depth -= 1
            j += 1
        
        if depth == 0:
            inner = test_code[start:j - 1]
            total_count += 1
            result.append(
                f"__total__++\n"
                f"  try {{ if (!({inner})) throw AssertionError(\"\"); __passed__++ }}"
                f"catch (e: AssertionError) {{ }}"
            )
            i = j
        else:
            result.append(test_code[i+m.start():])
            i = len(test_code)

    return "".join(result), total_count

def _instrument_assert_python(test_code: str) -> Tuple[str, int]:
    """
    将 Python test 代码中的 assert ... 替换为计数版本。

    Python assert 语法: assert condition [, message]
    替换为带 __total__/__passed__ 计数的 try/except 块。

    使用括号深度匹配，支持跨行 assert 条件。
    """
    total_count = 0
    result = []
    i = 0

    while i < len(test_code):
        m = re.search(r'\bassert\s+', test_code[i:])
        if not m:
            result.append(test_code[i:])
            break

        line_start = test_code.rfind('\n', 0, i + m.start())
        if line_start == -1:
            line_start = 0
        else:
            line_start += 1
        indent = test_code[line_start:i + m.start()]

        result.append(test_code[i:line_start])

        pos = i + m.end()
        start = pos

        paren_depth = 0
        bracket_depth = 0
        brace_depth = 0

        while pos < len(test_code):
            ch = test_code[pos]

            if ch == '(':
                paren_depth += 1
            elif ch == ')':
                paren_depth -= 1
            elif ch == '[':
                bracket_depth += 1
            elif ch == ']':
                bracket_depth -= 1
            elif ch == '{':
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
            elif ch == '#' and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                break
            elif ch == '\n' and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                break

            pos += 1

        condition = test_code[start:pos].rstrip()
        total_count += 1

        result.append(
            f"{indent}global __total__, __passed__\n"
            f"{indent}__total__ += 1\n"
            f"{indent}try:\n"
            f"{indent}    assert {condition}\n"
            f"{indent}    __passed__ += 1\n"
            f"{indent}except AssertionError:\n"
            f"{indent}    pass"
        )

        i = pos

    return "".join(result), total_count


def _instrument_assert_javascript(test_code: str) -> Tuple[str, int]:
    """
    将 JavaScript test 代码中的 console.assert(...) 替换为计数版本。
    """
    total_count = 0

    def replace_assert(match):
        nonlocal total_count
        total_count += 1
        inner = match.group(1)
        return (
            f"__total__++;\n"
            f"try {{ if (!({inner})) throw new Error(); __passed__++; }} "
            f"catch (e) {{ }}"
        )

    instrumented = re.sub(
        r'console\.assert\s*\(((?:[^()]|\([^()]*\))*)\)',
        replace_assert,
        test_code,
    )
    return instrumented, total_count


def _instrument_assert_swift(test_code: str) -> Tuple[str, int]:
    """
    将 Swift test 代码中的 assert(condition) 替换为计数版本。

    Swift 的 assert() 在条件为 false 时会触发运行时陷阱（不可捕获），
    因此不能使用 try/catch。替代方案：用 if 语句直接判断条件。

    原: assert(candidate(...) == true)
    替: __total__ += 1
         if (candidate(...) == true) { __passed__ += 1 }
    """
    total_count = 0

    def replace_assert(match):
        nonlocal total_count
        total_count += 1
        inner = match.group(1)
        return (
            f"__total__ += 1\n"
            f"    if ({inner}) {{ __passed__ += 1 }}"
        )

    # 匹配 assert( 后到最近 ) 的内容（支持一层嵌套括号）
    instrumented = re.sub(
        r'assert\s*\(((?:[^()]|\([^()]*\))*)\)',
        replace_assert,
        test_code,
    )
    return instrumented, total_count


def _remove_trailing_check_call(test_code: str, entry_point: str) -> str:
    """
    从 test 代码末尾移除已有的 check(entry_point) 调用，
    避免在组装测试程序时重复调用 check()。

    匹配格式: check(entry_point) 或 check(entry_point_name)
    """
    # 移除末尾的 check(...) 调用行（包括前导空白和换行）
    pattern = r'\n?\s*check\s*\([^)]*\)\s*\n?\s*$'
    cleaned = re.sub(pattern, '', test_code)
    return cleaned.rstrip() + '\n'


# ---------------------------------------------------------------------------
# 程序组装 (per language)
# ---------------------------------------------------------------------------

def _assemble_kotlin_program(
    prompt: str, completion: str, test_code: str, entry_point: str,
) -> str:
    """
    组装 Kotlin 测试程序:

        var __passed__ = 0
        var __total__ = 0
        {prompt}
        {completion}
        {instrumented_test}
        check(::{entry_point})
        println("__ASSERT_RESULT: $__passed__/$__total__")
    """
    instrumented_test, assert_count = _instrument_assert_kotlin(test_code)
    lines = prompt.split("\n")
    imports = [l for l in lines if re.match(r"^\s*import\s+",l)]
    rest = "\n".join(l for l in lines if not re.match(r"^\s*import\s+",l))
    closing = "}" if not completion.rstrip().endswith("}") else ""
    header = "\n".join(imports) + "\n\n" if imports else ""
    return (
        f"{header}"
        "var __passed__ = 0\n"
        "var __total__ = 0\n\n"
        f"{prompt}\n"
        f"{completion}\n"
        f"{closing}\n\n"
        f"{instrumented_test}\n\n"
        f"check(::{entry_point})\n"
        'println("__ASSERT_RESULT: $__passed__/$__total__")\n'
    ), assert_count


def _assemble_python_program(
    prompt: str, completion: str, test_code: str, entry_point: str,
) -> str:
    """
    组装 Python 测试程序:

        __passed__ = 0
        __total__ = 0
        {prompt}
        {completion}
        {instrumented_test}
        check({entry_point})
        print(f"__ASSERT_RESULT: {__passed__}/{__total__}")
    """
    instrumented_test, assert_count = _instrument_assert_python(test_code)
    return (
        "__passed__ = 0\n"
        "__total__ = 0\n\n"
        f"{prompt}\n"
        f"{completion}\n\n"
        f"{instrumented_test}\n\n"
        f"check({entry_point})\n"
        'print(f"__ASSERT_RESULT: {__passed__}/{__total__}")\n'
    ), assert_count


def _assemble_javascript_program(
    prompt: str, completion: str, test_code: str, entry_point: str,
) -> str:
    """
    组装 JavaScript 测试程序:

        let __passed__ = 0;
        let __total__ = 0;
        {prompt}
        {completion}
        {instrumented_test}
        check({entry_point});
        console.log(`__ASSERT_RESULT: ${__passed__}/${__total__}`);
    """
    instrumented_test, assert_count = _instrument_assert_javascript(test_code)
    return (
        "let __passed__ = 0;\n"
        "let __total__ = 0;\n\n"
        f"{prompt}\n"
        f"{completion}\n\n"
        f"{instrumented_test}\n\n"
        f"check({entry_point});\n"
        'console.log(`__ASSERT_RESULT: ${__passed__}/${__total__}`);\n'
    ), assert_count


def _assemble_swift_program(
    prompt: str, completion: str, test_code: str, entry_point: str,
) -> Tuple[str, int]:
    """
    组装 Swift 测试程序:

        import Foundation
        var __passed__ = 0
        var __total__ = 0
        {prompt}
        {completion}          ← 已包含 closing }，不额外添加
        {instrumented_test}   ← 已移除原 check() 调用
        check({entry_point})  ← 只调用一次
        print("__ASSERT_RESULT: ...")

    注意: Swift benchmark 中 completion 已含结尾 `}`，test 末尾已含 check()，
    与 Kotlin 格式不同，不能照搬 Kotlin 的组装逻辑。
    """
    # 移除 test 末尾已有的 check(entry_point) 调用，避免重复
    test_without_check = _remove_trailing_check_call(test_code, entry_point)
    instrumented_test, assert_count = _instrument_assert_swift(test_without_check)
    return (
        "import Foundation\n\n"
        "var __passed__ = 0\n"
        "var __total__ = 0\n\n"
        f"{prompt}\n"
        f"{completion}\n"         # ← completion 已含 }，不额外添加
        f"{instrumented_test}\n\n"
        f"check({entry_point})\n"
        'print("__ASSERT_RESULT: \\(__passed__)/\\(__total__)")\n'
    ), assert_count


# ---------------------------------------------------------------------------
# ArkTS: passed 布尔标记模式仪表化 + 程序组装
# ---------------------------------------------------------------------------

def _instrument_assert_arkts(test_code: str) -> Tuple[str, int]:
    """
    将 ArkTS test 代码中的 passed 布尔标记模式替换为计数版本。

    ArkTS 测试不使用 assert()，而是:
        let passed = true;
        if (!(func(args) === expected)) { passed = false; }

    替换为 __total/__failed 计数 + __ASSERT_RESULT 输出。
    """
    # 统计测试检查数量
    total = len(re.findall(r'if\s*\(\s*!\s*\(', test_code))
    if total == 0:
        return test_code, 0

    # 头部：重置 passed + 声明计数器
    header = (
        f'let passed = true;\n'
        f'let __total = {total};\n'
        f'let __failed = 0;\n'
    )

    # 移除原始 "let passed = true;" (在 test code 开头)
    body = re.sub(r'^\s*let\s+passed\s*=\s*true\s*;\s*\n?', '', test_code, count=1)

    # 将 "passed = false" 替换为同时计数失败
    body = body.replace('passed = false;', 'passed = false; __failed++;')

    # 尾部：输出结果
    footer = (
        '\nconsole.log(`__ASSERT_RESULT: ${__total - __failed}/${__total}`);\n'
    )

    return header + body + footer, total


def _assemble_arkts_program(
    prompt: str, completion: str, test_code: str, entry_point: str,
) -> Tuple[str, int]:
    """
    组装 ArkTS 测试程序。

    ArkTS benchmark 无 entry_point 字段，函数签名已包含在 prompt 中。
    组装方式：prompt + completion + 仪表化后的 test code。
    处理 prompt 末尾与 completion 开头重叠的 `{`。
    """
    # 处理 prompt/completion 重叠 — prompt 以 `{` 结尾时，
    # completion 可能又以 `{` 开头，导致重复花括号
    if prompt.rstrip().endswith('{') and completion.lstrip().startswith('{'):
        completion = completion.lstrip()[1:].lstrip()

    instrumented, count = _instrument_assert_arkts(test_code)
    program = f"{prompt}\n{completion}\n\n{instrumented}"
    return program, count


_ASSEMBLERS = {
    "kotlin": _assemble_kotlin_program,
    "python": _assemble_python_program,
    "javascript": _assemble_javascript_program,
    "swift": _assemble_swift_program,
    "arkts": _assemble_arkts_program,
}


def assemble_test_program(
    task: Dict,
    completion: str,
    language: str = "kotlin",
) -> Tuple[str, int]:
    """
    组装可执行的仪表化测试程序。

    返回:
        (program_code, total_asserts)
    """
    prompt = task.get("prompt", "")
    test_code = task.get("test", "")
    entry_point = task.get("entry_point", "")

    assembler = _ASSEMBLERS.get(language)
    if assembler is None:
        raise ValueError(f"不支持的语言: {language}. 支持: {list(_ASSEMBLERS.keys())}")

    return assembler(prompt, completion, test_code, entry_point)


# ---------------------------------------------------------------------------
# 性能采集
# ---------------------------------------------------------------------------

def trapezoidal_integral(times: List[float], values: List[float]) -> float:
    """
    用梯形法计算 ∫ M(t) dt。

    公式: Σ (t[i+1] - t[i]) * (v[i] + v[i+1]) / 2
    """
    if len(times) < 2:
        return 0.0
    total = 0.0
    for i in range(len(times) - 1):
        dt = times[i + 1] - times[i]
        avg_val = (values[i] + values[i + 1]) / 2.0
        total += dt * avg_val
    return total


def _collect_performance(
    process: subprocess.Popen,
    timeout: float,
) -> Tuple[float, List[float], List[float]]:
    """
    在子进程执行期间同步采集性能数据。

    返回:
        (execution_time_sec, timestamps, rss_bytes_list)
    """
    timestamps: List[float] = []
    rss_samples: List[int] = []
    interval = 0.01  # 10ms 采样间隔

    start_time = time.perf_counter()
    deadline = start_time + timeout

    try:
        psutil_proc = psutil.Process(process.pid)
    except (psutil.NoSuchProcess, Exception):
        psutil_proc = None

    while process.poll() is None:
        now = time.perf_counter()
        if now > deadline:
            process.kill()
            process.wait()
            raise subprocess.TimeoutExpired(process.args, timeout)

        if psutil_proc is not None and HAS_PSUTIL:
            try:
                mem_info = psutil_proc.memory_info()
                timestamps.append(now)
                rss_samples.append(mem_info.rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        time.sleep(interval)

    end_time = time.perf_counter()
    execution_time = end_time - start_time

    return execution_time, timestamps, rss_samples


# ---------------------------------------------------------------------------
# 主函数: run_test
# ---------------------------------------------------------------------------

def _resolve_windows_cmd(cmd:str, ext:str) -> Optional[str]:
    """在PATH中查找带指定扩展名的命令（如 kotlinc .bat）"""
    dirs = os.environ.get("PATH","").split(os.pathsep)
    for d in dirs:
        full = os.path.join(d,cmd+ext)
        if os.path.isfile(full):
            return full
    return None

def run_test(
    task: Dict,
    completion: str,
    language: str = "kotlin",
    timeout: float = 120.0,
    enable_perf: bool = False,
) -> Dict:
    """
    对单个样本执行测试并可选采集性能数据。

    参数:
        task: Benchmark Task 对象
        completion: Agent 生成的代码补全
        language: 编程语言
        timeout: 超时秒数
        enable_perf: 是否启用性能指标采集

    返回:
        {
            "passed": int,              # 通过的 assert 数
            "total": int,               # 总 assert 数
            "test_pass_ratio": float,   # passed / total
            "correct": bool,            # passed == total
            "error": str | None,
            "execution_time_sec": float | None,
            "max_memory_mb": float | None,
            "total_memory_mb_sec": float | None,
        }
    """
    if language not in LANGUAGE_CONFIG:
        return {
            "passed": 0,
            "total": 0,
            "test_pass_ratio": 0.0,
            "correct": False,
            "error": f"不支持的语言: {language}",
            "execution_time_sec": None,
            "max_memory_mb": None,
            "total_memory_mb_sec": None,
        }

    config = LANGUAGE_CONFIG[language]
    ext = config["extension"]
    run_cmd = config["run_cmd"]
    # Windows 下 subprocess 找不到 .bat/.cmd， 自动补全扩展名
    if sys.platform == "win32":
        cmd_exe = run_cmd[0]
        if not os.path.splitext(cmd_exe)[1]:
            for ext_candidate in (".bat",".cmd",".exe"):
                resolved = _resolve_windows_cmd(cmd_exe,ext_candidate)
                if resolved:
                    run_cmd = [resolved] + run_cmd[1:]
                    break
    result = {
        "passed": 0,
        "total": 0,
        "test_pass_ratio": 0.0,
        "correct": False,
        "error": None,
        "execution_time_sec": None,
        "max_memory_mb": None,
        "total_memory_mb_sec": None,
    }

    tmp_path = None
    exe_path = None
    try:
        # 组装仪表化测试程序
        program, total_asserts = assemble_test_program(task, completion, language)
        result["total"] = total_asserts

        if total_asserts == 0:
            # test 为空字符串 — correct 为未定义，不参与 pass@k 的 c 计数
            # 这里返回 total=0, passed=0, correct=False（外部需特殊处理）
            result["error"] = "Test code is empty (no assertions found)"
            return result

        # 写入临时文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=ext, delete=False, encoding="utf-8",
        ) as f:
            f.write(program)
            tmp_path = f.name

        # 执行程序 (direct 模式 vs compile_and_run 模式)
        run_mode = config.get("run_mode", "direct")

        def _run_with_perf(cmd):
            """性能模式：Popen + RSS 采样"""
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                exec_time, timestamps, rss_list = _collect_performance(proc, timeout)
                out, err = proc.communicate(timeout=1)
                result["execution_time_sec"] = exec_time
                if rss_list:
                    result["max_memory_mb"] = max(rss_list) / (1024.0 * 1024.0)
                    result["total_memory_mb_sec"] = (
                        trapezoidal_integral(timestamps, [float(r) for r in rss_list])
                        / (1024.0 * 1024.0)
                    )
                return out, err
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise

        def _run_simple(cmd):
            """非性能模式：subprocess.run"""
            pr = subprocess.run(cmd, capture_output=True, timeout=timeout)
            return pr.stdout, pr.stderr

        if run_mode == "compile_and_run":
            # Swift: swiftc -o exe → 执行 exe
            exe_path = tmp_path + ".exe"
            cr = subprocess.run(run_cmd + ["-o", exe_path, tmp_path],
                                capture_output=True, timeout=timeout)
            if cr.returncode != 0:
                err_str = cr.stderr.decode("utf-8", errors="replace")
                result["error"] = f"Compilation failed: {err_str[:500]}"
                result["passed"] = 0
                return result
            run_fn = _run_with_perf if (enable_perf and HAS_PSUTIL) else _run_simple
            stdout, stderr = run_fn([exe_path])
        else:
            # Kotlin / Python / JS: 直接执行
            run_fn = _run_with_perf if (enable_perf and HAS_PSUTIL) else _run_simple
            stdout, stderr = run_fn(run_cmd + [tmp_path])

        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

        # 解析 stdout 中的 __ASSERT_RESULT
        match = re.search(config["result_pattern"], stdout_str)
        if match:
            result["passed"] = int(match.group(1))
            parsed_total = int(match.group(2))
            result["total"] = parsed_total  # 始终使用程序实际执行次数, 因为 assert 可能在循环内
        else:
            # 程序可能崩溃或在输出结果之前退出
            result["error"] = (
                f"未找到 __ASSERT_RESULT (stdout: {stdout_str[-200:]}, "
                f"stderr: {stderr_str[-200:]})"
            )
            result["passed"] = 0
            # total 保持不变（已从 test 代码中统计）

        # 计算派生指标
        if result["total"] > 0:
            result["test_pass_ratio"] = result["passed"] / result["total"]
            result["correct"] = (result["passed"] == result["total"])
        else:
            result["test_pass_ratio"] = 0.0
            result["correct"] = False

    except subprocess.TimeoutExpired:
        result["error"] = f"Timeout ({timeout}s)"
        result["passed"] = 0
    except FileNotFoundError:
        result["error"] = f"运行时 '{run_cmd[0]}' 未找到"
        result["passed"] = 0
    except Exception as e:
        result["error"] = f"执行异常: {str(e)}"
        result["passed"] = 0
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if exe_path and os.path.exists(exe_path):
            try:
                os.unlink(exe_path)
            except OSError:
                pass

    return result
