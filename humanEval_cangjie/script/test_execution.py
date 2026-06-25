"""Cangjie 测试执行 — cjc --test 编译 + 运行 + 结果解析。"""
import subprocess, tempfile, os, re, shutil
from typing import Dict, Tuple

LANGUAGE = "cangjie"
EXTENSION = ".cj"
CANGJIE_HOME = r"D:\Software\Cangjie"
CJC = os.path.join(CANGJIE_HOME, "bin", "cjc.exe")
RUNTIME_LIB = os.path.join(CANGJIE_HOME, "runtime", "lib", "windows_x86_64_cjnative")
LIB_PATH = os.path.join(CANGJIE_HOME, "lib", "windows_x86_64_cjnative")

def _get_env():
    env = os.environ.copy()
    env["CANGJIE_HOME"] = CANGJIE_HOME
    env["PATH"] = RUNTIME_LIB + ";" + LIB_PATH + ";" + os.path.join(CANGJIE_HOME, "bin") + ";" + env.get("PATH", "")
    return env

def _strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text)

def _count_expects(test_code):
    """统计 @Expect 调用次数。"""
    return len(re.findall(r'@Expect\s*\(', test_code))

def _extract_imports(completion):
    """从 completion 开头提取 import std.* 行，返回 (import_block, remaining_completion)。"""
    import_lines = []
    remaining_lines = []
    found_import_end = False
    for line in completion.split("\n"):
        stripped = line.strip()
        if not found_import_end and stripped.startswith("import std."):
            import_lines.append(stripped)
        else:
            found_import_end = True
            remaining_lines.append(line)
    import_block = "\n".join(import_lines) + "\n" if import_lines else ""
    remaining = "\n".join(remaining_lines)
    return import_block, remaining

def assemble_test_program(task, completion, language="cangjie"):
    prompt = task.get("prompt", "")
    test_code = task.get("test", "")
    entry_point = task.get("entry_point", "")

    test_code_fixed = test_code.replace("candidate", entry_point)

    import_block, body = _extract_imports(completion)

    code_before = prompt + "\n" + body
    depth = code_before.count("{") - code_before.count("}")
    closing = "\n" + "}" * depth if depth > 0 else ""

    program = (
        import_block + "\n"
        + prompt + "\n"
        + body + "\n"
        + closing + "\n\n"
        + test_code_fixed + "\n"
    )
    count = _count_expects(test_code)
    return program, count

def run_test(task, completion, language="cangjie", timeout=120.0, enable_perf=False):
    result = {
        "passed": 0, "total": 0, "test_pass_ratio": 0.0, "correct": False,
        "error": None, "execution_time_sec": None,
        "max_memory_mb": None, "total_memory_mb_sec": None,
    }
    tmp_dir = None
    try:
        program, total_asserts = assemble_test_program(task, completion, language)
        result["total"] = total_asserts
        if total_asserts == 0:
            result["error"] = "Test code is empty (no @Expect found)"
            return result

        # 创建临时目录，所有文件在此操作
        tmp_dir = tempfile.mkdtemp()
        src = os.path.join(tmp_dir, "test.cj")
        exe = os.path.join(tmp_dir, "test.exe")

        with open(src, "w", encoding="utf-8") as f:
            f.write(program)

        # 复制运行时 DLL 到临时目录
        for dll_dir in [RUNTIME_LIB, LIB_PATH]:
            if os.path.isdir(dll_dir):
                for fn in os.listdir(dll_dir):
                    if fn.endswith(".dll"):
                        dll_src = os.path.join(dll_dir, fn)
                        try: shutil.copy2(dll_src, tmp_dir)
                        except OSError: pass

        # 编译
        env = _get_env()
        cr = subprocess.run(
            [CJC, "--test", "-o", exe, src],
            capture_output=True, timeout=timeout, env=env,
        )
        if cr.returncode != 0:
            err = _strip_ansi(cr.stderr.decode("utf-8", errors="replace")[:500])
            result["error"] = f"Compile failed: {err}"
            return result

        # 运行测试
        r = subprocess.run([exe], capture_output=True, timeout=timeout, env=env)
        stdout = _strip_ansi(r.stdout.decode("utf-8", errors="replace"))

        # 解析输出: "PASSED: N" 和 "TOTAL: N"
        m_passed = re.search(r'PASSED:\s*(\d+)', stdout)
        m_total = re.search(r'TOTAL:\s*(\d+)', stdout)
        m_failed = re.search(r'FAILED:\s*(\d+)', stdout)

        if m_total:
            result["total"] = int(m_total.group(1))
        if m_passed:
            result["passed"] = int(m_passed.group(1))
        elif m_total and m_failed:
            result["passed"] = int(m_total.group(1)) - int(m_failed.group(1))
        else:
            result["error"] = f"Could not parse test output: {stdout[-300:]}"

    except subprocess.TimeoutExpired:
        result["error"] = f"Timeout ({timeout}s)"
    except FileNotFoundError:
        result["error"] = "cjc not found"
    except Exception as e:
        result["error"] = str(e)
    finally:
        # 彻底清理临时目录
        if tmp_dir and os.path.isdir(tmp_dir):
            try: shutil.rmtree(tmp_dir)
            except OSError: pass

    if result["total"] > 0:
        result["test_pass_ratio"] = result["passed"] / result["total"]
        result["correct"] = (result["passed"] == result["total"])

    return result
