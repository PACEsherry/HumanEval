#!/usr/bin/env bash
#
# CodeGenEval — 一键执行评测脚本
#
# 用法:
#   ./run_evaluation.sh [选项]
#
# 选项:
#   --agent-name NAME          被测评 Agent 名称 (必须)
#   --benchmark-path PATH      Benchmark .jsonl 路径 (必须)
#   --samples-path PATH        Samples .jsonl 路径 (必须)
#   --n N                      每个 Task 样本数 (必须)
#   --k-values "1,3"           pass@k 的 k 值列表 (默认: "1,3")
#   --enable-perf              启用代码性能指标 (可选)
#   --benchmark-name NAME      Benchmark 显示名称 (默认: "Unnamed Benchmark")
#   --language LANG            编程语言: kotlin|python|javascript|swift (默认: kotlin)
#   --timeout SECONDS          编译/测试超时秒数 (默认: 120)
#   --output-dir DIR           输出目录 (默认: ./results)
#   --help                     显示帮助
#
# 示例:
#   # 最简用法 (Kotlin)
#   ./run_evaluation.sh \
#     --agent-name "ClaudeAgent" \
#     --benchmark-path ../data/HumanEval_kotlin.jsonl \
#     --samples-path ../samples/samples_kotlin.jsonl \
#     --n 10
#
#   # 完整用法 (启用性能指标, 指定语言)
#   ./run_evaluation.sh \
#     --agent-name "ClaudeAgent" \
#     --benchmark-path ../data/HumanEval_kotlin.jsonl \
#     --samples-path ../samples/samples_kotlin.jsonl \
#     --n 10 \
#     --k-values "1,3,5" \
#     --enable-perf \
#     --benchmark-name "HumanEval Kotlin" \
#     --language kotlin \
#     --timeout 180 \
#     --output-dir ./results/2026-06-16
#

set -euo pipefail

# ============================================================================
# 默认参数
# ============================================================================

AGENT_NAME=""
BENCHMARK_PATH=""
SAMPLES_PATH=""
N=""
K_VALUES="1,3"
ENABLE_PERF="false"
BENCHMARK_NAME="Unnamed Benchmark"
LANGUAGE="kotlin"
TIMEOUT="120"
OUTPUT_DIR="./results"

# ============================================================================
# 帮助函数
# ============================================================================

show_help() {
    head -36 "$0" | tail -35
    exit 0
}

# ============================================================================
# 参数解析
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --agent-name)
            AGENT_NAME="$2"
            shift 2
            ;;
        --benchmark-path)
            BENCHMARK_PATH="$2"
            shift 2
            ;;
        --samples-path)
            SAMPLES_PATH="$2"
            shift 2
            ;;
        --n)
            N="$2"
            shift 2
            ;;
        --k-values)
            K_VALUES="$2"
            shift 2
            ;;
        --enable-perf)
            ENABLE_PERF="true"
            shift
            ;;
        --benchmark-name)
            BENCHMARK_NAME="$2"
            shift 2
            ;;
        --language)
            LANGUAGE="$2"
            shift 2
            ;;
        --timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            ;;
        *)
            echo "未知选项: $1"
            echo "使用 --help 查看帮助"
            exit 1
            ;;
    esac
done

# ============================================================================
# 参数校验
# ============================================================================

if [ -z "$AGENT_NAME" ]; then
    echo "错误: --agent-name 是必须的"
    exit 1
fi
if [ -z "$BENCHMARK_PATH" ]; then
    echo "错误: --benchmark-path 是必须的"
    exit 1
fi
if [ -z "$SAMPLES_PATH" ]; then
    echo "错误: --samples-path 是必须的"
    exit 1
fi
if [ -z "$N" ]; then
    echo "错误: --n 是必须的"
    exit 1
fi

# ============================================================================
# 环境检查
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REQUIRED_PYTHON="3.8"

echo "============================================"
echo "  CodeGenEval — 环境检查"
echo "============================================"

# Python (python 优先，避免 Windows Store 假 python3)
PYTHON=""
for candidate in python python3; do
    if command -v "$candidate" &> /dev/null && "$candidate" --version &> /dev/null; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "错误: 未找到 Python，请安装 Python >= ${REQUIRED_PYTHON}"
    exit 1
fi

PYTHON_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
echo "  Python:    $PYTHON_VERSION  [$PYTHON]"

# 检查 Python 依赖
echo -n "  numpy:     "
$PYTHON -c "import numpy; print(f'numpy {numpy.__version__}')" 2>/dev/null || {
    echo "未安装 → pip install numpy"
    exit 1
}

echo -n "  psutil:    "
$PYTHON -c "import psutil; print(f'psutil {psutil.__version__}')" 2>/dev/null || {
    echo "未安装 → 性能指标将被禁用; pip install psutil"
}

echo -n "  fire:      "
$PYTHON -c "import fire; print('ok')" 2>/dev/null || {
    echo "未安装 → pip install fire"
    exit 1
}

# 语言运行时检查
case "$LANGUAGE" in
    kotlin)
        if command -v kotlinc &> /dev/null; then
            echo "  kotlinc:   $(kotlinc -version 2>&1 | head -1 || echo 'found')"
        else
            echo "  kotlinc:   未找到 → 请安装 Kotlin"
            exit 1
        fi
        if command -v kotlin &> /dev/null; then
            echo "  kotlin:    $(kotlin -version 2>&1 | head -1 || echo 'found')"
        else
            echo "  kotlin:    未找到 → 请安装 Kotlin"
            exit 1
        fi
        ;;
    python)
        echo "  Python 运行时: 使用 $PYTHON"
        ;;
    javascript)
        if command -v node &> /dev/null; then
            echo "  node:      $(node --version)"
        else
            echo "  node:      未找到 → 请安装 Node.js"
            exit 1
        fi
        ;;
    swift)
        if command -v swiftc &> /dev/null; then
            echo "  swiftc:    $(swiftc --version 2>&1 | head -1 || echo 'found')"
        else
            echo "  swiftc:    未找到 → 请安装 Swift"
            exit 1
        fi
        ;;
    *)
        echo "  [警告] 对 '$LANGUAGE' 无运行时检查，请确保已安装对应编译器"
        ;;
esac

# 检查文件存在性
echo ""
echo "  输入文件检查:"
if [ -f "$BENCHMARK_PATH" ]; then
    echo "    Benchmark: $BENCHMARK_PATH ✓"
else
    echo "    Benchmark: $BENCHMARK_PATH ✗ 文件不存在"
    exit 1
fi
if [ -f "$SAMPLES_PATH" ]; then
    echo "    Samples:   $SAMPLES_PATH ✓"
else
    echo "    Samples:   $SAMPLES_PATH ✗ 文件不存在"
    exit 1
fi

# ============================================================================
# 运行评测
# ============================================================================

echo ""
echo "============================================"
echo "  CodeGenEval — 运行评测"
echo "============================================"
echo "  Agent:       $AGENT_NAME"
echo "  Benchmark:   $BENCHMARK_PATH"
echo "  Samples:     $SAMPLES_PATH"
echo "  n:           $N"
echo "  k:           $K_VALUES"
echo "  语言:        $LANGUAGE"
echo "  性能指标:    $ENABLE_PERF"
echo "  超时:        ${TIMEOUT}s"
echo "  输出:        $OUTPUT_DIR"
echo "============================================"
echo ""

# 构建 Python 启动参数
PYTHON_ARGS=(
    "$SCRIPT_DIR/pipeline.py"
    --agent_name "$AGENT_NAME"
    --benchmark_path "$BENCHMARK_PATH"
    --samples_path "$SAMPLES_PATH"
    --n "$N"
    --k_values "$K_VALUES"
    --benchmark_name "$BENCHMARK_NAME"
    --language "$LANGUAGE"
    --timeout "$TIMEOUT"
    --output_dir "$OUTPUT_DIR"
)

if [ "$ENABLE_PERF" = "true" ]; then
    PYTHON_ARGS+=(--enable_perf_metrics)
fi

# 执行
START_TIME=$(date +%s)
$PYTHON "${PYTHON_ARGS[@]}"
EXIT_CODE=$?
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

# ============================================================================
# 结果输出
# ============================================================================

echo ""
echo "============================================"
echo "  CodeGenEval — 完成"
echo "============================================"
echo "  耗时: ${ELAPSED}s"
echo "  退出码: $EXIT_CODE"

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "  报告文件:"
    if [ -f "$OUTPUT_DIR/report.json" ]; then
        echo "    JSON:     $OUTPUT_DIR/report.json"
    fi
    if [ -f "$OUTPUT_DIR/report.md" ]; then
        echo "    Markdown: $OUTPUT_DIR/report.md"
    fi

    # 尝试打印摘要
    if [ -f "$OUTPUT_DIR/report.json" ]; then
        echo ""
        echo "  快速摘要 (来自 report.json):"
        $PYTHON -c "
import json
with open('$OUTPUT_DIR/report.json', 'r') as f:
    r = json.load(f)
if 'error' in r:
    print(f'  错误: {r[\"error\"]}')
else:
    m = r.get('metrics', {})
    tasks = r.get('report', {}).get('total_tasks', '?')
    print(f'  Task 总数: {tasks}')
    csr = m.get('compilation_success_rate', {}).get('value', 'N/A')
    print(f'  编译成功率: {csr}')
    atpr = m.get('avg_test_pass_ratio', {}).get('value', 'N/A')
    print(f'  平均测试通过率: {atpr}')
    for k, v in m.get('pass_at_k', {}).items():
        print(f'  {k}: {v.get(\"value\", \"N/A\")}')
" 2>/dev/null || true
    fi
else
    echo "  评测异常终止"
fi

exit $EXIT_CODE
