"""
JS 语言测评入口包装器。
"""

import sys
import os

# ---- 路径 ----
_LANG_DIR = os.path.dirname(os.path.abspath(__file__))
_SHARED_DIR = os.path.normpath(
    os.path.join(_LANG_DIR, "..", "..", "code-gen-eval", "script")
)

# 1) 只加共享目录，导入 pipeline（此时 compile_check/test_execution 来自共享）
sys.path.insert(0, _SHARED_DIR)
import pipeline as _pipeline

# 2) 加语言目录到最前，清除共享模块缓存后重新导入本地版本
sys.path.insert(0, _LANG_DIR)
for _mod in ("compile_check", "test_execution"):
    if _mod in sys.modules:
        del sys.modules[_mod]

import compile_check as _lang_cc      # 现在从 _LANG_DIR 加载
import test_execution as _lang_te    # 现在从 _LANG_DIR 加载

# 3) 覆盖 pipeline 中引用的函数
_pipeline.compile_check = _lang_cc.compile_check
_pipeline.run_test = _lang_te.run_test

main = _pipeline.main

if __name__ == "__main__":
    main()
