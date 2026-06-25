"""Cangjie 编译检查 — 使用 cjc --output-type=staticlib 验证语法和类型。"""
import subprocess, tempfile, os, re
from typing import Dict, List

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

def compile_check(task, completion, language="cangjie", timeout=120.0):
    """组装: imports + prompt + completion → cjc --output-type=staticlib"""
    prompt = task.get("prompt", "")
    import_block, body = _extract_imports(completion)

    code_before = prompt + "\n" + body
    depth = code_before.count("{") - code_before.count("}")
    closing = "\n" + "}" * depth if depth > 0 else ""
    full_code = import_block + "\n" + code_before + closing

    if not prompt.strip():
        return {"compile_success": False, "compile_error": "prompt is empty"}

    tmp_path = out_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=EXTENSION, delete=False, encoding="utf-8"
        ) as f:
            f.write(full_code)
            tmp_path = f.name
        out_path = tmp_path + ".lib"

        r = subprocess.run(
            [CJC, tmp_path, "--output-type=staticlib", "-o", out_path],
            capture_output=True, timeout=timeout, env=_get_env(),
        )
        if r.returncode == 0:
            return {"compile_success": True, "compile_error": None}
        err = _strip_ansi(r.stderr.decode("utf-8", errors="replace").strip())
        if not err:
            err = _strip_ansi(r.stdout.decode("utf-8", errors="replace").strip())
        return {"compile_success": False, "compile_error": err[:1000] if err else "compile error"}
    except subprocess.TimeoutExpired:
        return {"compile_success": False, "compile_error": f"Timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"compile_success": False, "compile_error": f"cjc not found at: {CJC}"}
    except Exception as e:
        return {"compile_success": False, "compile_error": str(e)}
    finally:
        for p in [tmp_path, out_path]:
            if p and os.path.exists(p):
                try: os.unlink(p)
                except OSError: pass

def compile_check_batch(task, completions, language="cangjie", timeout=120.0):
    return [{"sample_index": i, **compile_check(task, c, language, timeout)} for i, c in enumerate(completions)]
