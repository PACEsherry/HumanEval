"""
编译检查模块。

对每个样本的 completion 与 task.prompt 拼接后进行编译检查。
支持多种编程语言，通过 language 参数选择对应的编译方式。

支持的语言:
    - kotlin: 使用 kotlinc -script 编译 .kts 文件
    - python: 使用 py_compile 编译 .py 文件
    - javascript: 使用 node --check 检查 .js 文件
    - swift: 使用 swiftc -typecheck 检查 .swift 文件
"""

import subprocess
import tempfile
import os
import re
import shutil
import sys
from typing import Dict, List, Optional


def _find_python() -> str:
    """检测系统可用的 Python 命令 (python 优先，避免 Windows Store 假 python3)。"""
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
        "compile_cmd": ["kotlinc", "-script"],
        "description": "Kotlin Script",
    },
    "python": {
        "extension": ".py",
        "compile_cmd": [_find_python(), "-m", "py_compile"],
        "description": "Python",
    },
    "javascript": {
        "extension": ".js",
        "compile_cmd": ["node", "--check"],
        "description": "JavaScript (Node.js)",
    },
    "swift": {
        "extension": ".swift",
        "compile_cmd": ["swiftc", "-typecheck"],
        "description": "Swift",
    },
    "arkts": {
        "extension": ".ts",
        "compile_cmd": ["tsc", "--noEmit", "--target", "ES2022",
                         "--module", "commonjs", "--strict", "false"],
        "description": "ArkTS (TypeScript Compiler)",
    },
}

# ---------------------------------------------------------------------------
# 代码组装
# ---------------------------------------------------------------------------

def _extract_imports(code: str, language: str) -> str:
    """
    从代码中提取 import / include 等声明行，以便放在最前面。

    不同语言的正则模式:
        - kotlin/python: 以 import 或 from 开头的行
        - javascript: import / require 语句
        - swift: import 行
    """
    patterns = {
        "kotlin": r"^\s*import\s+.*$",
        "python": r"^\s*(import\s+|from\s+\S+\s+import\s+).*$",
        "javascript": r"^\s*(import\s+|const\s+\S+\s*=\s*require\().*$",
        "swift": r"^\s*import\s+.*$",
        "arkts": r"^\s*(import\s+|export\s+).*$",
    }
    pattern = patterns.get(language, r"^\s*import\s+.*$")
    imports = []
    others = []
    for line in code.split("\n"):
        if re.match(pattern, line):
            imports.append(line)
        else:
            others.append(line)
    return "\n".join(imports), "\n".join(others)


def assemble_code(task: Dict, completion: str, language: str) -> str:
    """
    将 task.prompt 与 completion 拼接成完整可编译的代码。

    对 Kotlin 等语言，保持 import 在文件头部。
    对 ArkTS 等语言，处理 prompt 末尾与 completion 开头的重叠（如重复的 `{`）。
    """
    prompt = task.get("prompt", "")

    # 提取 prompt 中的 import 行
    imports, rest = _extract_imports(prompt, language)

    # 处理 prompt/completion 重叠（ArkTS 等语言的 prompt 以 `{` 结尾，
    # completion 可能又以 `{` 开头，导致语法错误）
    if rest and completion:
        rest_stripped = rest.rstrip()
        comp_stripped = completion.lstrip()
        # 若 prompt 以 `{` 结尾且 completion 以 `{` 开头，去除 completion 前导的 `{`
        if rest_stripped.endswith('{') and comp_stripped.startswith('{'):
            completion = comp_stripped[1:].lstrip()

    # 组合: imports + rest_of_prompt + completion
    parts = []
    if imports:
        parts.append(imports)
    if rest:
        parts.append(rest)
    if completion:
        parts.append(completion)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 编译检查
# ---------------------------------------------------------------------------

def _resolve_windows_cmd(cmd:str, ext:str) -> Optional[str]:
    """在PATH中查找带指定扩展名的命令（如 kotlinc .bat）"""
    dirs = os.environ.get("PATH","").split(os.pathsep)
    for d in dirs:
        full = os.path.join(d,cmd+ext)
        if os.path.isfile(full):
            return full
    return None

def compile_check(
    task: Dict,
    completion: str,
    language: str = "kotlin",
    timeout: float = 120.0,
) -> Dict:
    """
    对单个样本进行编译检查。

    参数:
        task: Benchmark Task 对象
        completion: Agent 生成的代码补全
        language: 编程语言 ("kotlin" | "python" | "javascript" | "swift")
        timeout: 编译超时秒数

    返回:
        {
            "compile_success": bool,
            "compile_error": str | None,
        }
    """
    if language not in LANGUAGE_CONFIG:
        return {
            "compile_success": False,
            "compile_error": f"不支持的语言: {language}. "
                             f"支持: {list(LANGUAGE_CONFIG.keys())}",
        }

    config = LANGUAGE_CONFIG[language]
    ext = config["extension"]
    compile_cmd = config["compile_cmd"]
    # Windows 下 subprocess 找不到 .bat/.cmd， 自动补全扩展名
    if sys.platform == "win32":
        cmd_exe = compile_cmd[0]
        if not os.path.splitext(cmd_exe)[1]:
            for ext_candidate in (".bat",".cmd",".exe"):
                resolved = _resolve_windows_cmd(cmd_exe,ext_candidate)
                if resolved:
                    compile_cmd = [resolved] + compile_cmd[1:]
                    break
    # 组装完整代码
    full_code = assemble_code(task, completion, language)

    if not full_code.strip():
        return {
            "compile_success": False,
            "compile_error": "代码为空",
        }

    tmp_path = None
    try:
        # 写入临时文件
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=ext,
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(full_code)
            tmp_path = f.name

        # 执行编译命令
        result = subprocess.run(
            compile_cmd + [tmp_path],
            capture_output=True,
            timeout=timeout,
        )

        if result.returncode == 0:
            return {
                "compile_success": True,
                "compile_error": None,
            }
        else:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if not stderr:
                stderr = result.stdout.decode("utf-8", errors="replace").strip()
            return {
                "compile_success": False,
                "compile_error": stderr[:1000] if stderr else "Unknown compilation error",
            }

    except subprocess.TimeoutExpired:
        return {
            "compile_success": False,
            "compile_error": f"Timeout ({timeout}s)",
        }
    except FileNotFoundError:
        return {
            "compile_success": False,
            "compile_error": f"编译器 '{compile_cmd[0]}' 未找到，请确保已安装 {config['description']} 运行时",
        }
    except Exception as e:
        return {
            "compile_success": False,
            "compile_error": f"编译过程异常: {str(e)}",
        }
    finally:
        # 清理临时文件
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def compile_check_batch(
    task: Dict,
    completions: List[str],
    language: str = "kotlin",
    timeout: float = 120.0,
) -> List[Dict]:
    """
    对一批 completion 执行编译检查（顺序执行），返回结果列表。
    结果按 sample_index 排序保证与输入顺序一致。
    """
    results = []
    for idx, completion in enumerate(completions):
        result = compile_check(task, completion, language, timeout)
        result["sample_index"] = idx
        results.append(result)
    return results
