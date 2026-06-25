"""
主编排管道与报告生成模块。

负责:
  1. 串联 data.py / compile_check.py / test_execution.py / evaluation.py
  2. 管理 Task 循环与错误隔离
  3. 生成 JSON 与 Markdown 格式测评报告 (§5.1, §5.2)
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# 添加当前目录到 sys.path 以保证脚本间可互相导入
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from data import (
    read_problems,
    stream_jsonl,
    validate_task,
    group_samples_by_task,
    count_total_samples,
)
from compile_check import compile_check
from test_execution import run_test
from evaluation import compute_all_metrics, confirm_score_weights
from composite_score import compute_composite_score


# ===========================================================================
# 主编排
# ===========================================================================

def run_evaluation(
    agent_name: str,
    benchmark_path: str,
    samples_path: str,
    n: int,
    k_values: Optional[List[int]] = None,
    enable_perf_metrics: bool = False,
    score_weights: Optional[Dict[str, float]] = None,
    benchmark_name: str = "Unnamed Benchmark",
    language: str = "kotlin",
    timeout: float = 120.0,
    output_dir: Optional[str] = None,
) -> Dict:
    """
    执行完整评测流水线。

    参数:
        agent_name:          被测评 Agent 名称
        benchmark_path:      Benchmark .jsonl 路径
        samples_path:        Samples .jsonl 路径
        n:                   每个 Task 样本数
        k_values:            pass@k 的 k 值列表 (默认 [1, 3])
        enable_perf_metrics: 是否启用性能指标
        score_weights:       综合评分权重配置 (None 使用默认等权重, §4.7.4)
        benchmark_name:      Benchmark 名称
        language:            编程语言 (kotlin / python / javascript / swift)
        timeout:             编译/测试超时秒数 (默认 120)
        output_dir:          报告输出目录 (默认当前目录)

    返回:
        {
            "json": dict,       # JSON 格式报告
            "markdown": str,    # Markdown 格式报告
        }
    """
    if k_values is None:
        k_values = [1, 3]

    if output_dir is None:
        output_dir = os.getcwd()

    all_warnings: List[str] = []

    # =======================================================================
    # 步骤 1: 数据加载
    # =======================================================================
    print(f"[1/4] 加载数据...")
    print(f"  Benchmark: {benchmark_path}")
    print(f"  Samples:   {samples_path}")

    try:
        problems = read_problems(benchmark_path)
    except (FileNotFoundError, ValueError) as e:
        error_report = {
            "error": f"Benchmark 文件为空或不存在: {str(e)}",
            "benchmark_path": benchmark_path,
        }
        return _emit_error(error_report, output_dir, agent_name)

    total_tasks_in_benchmark = len(problems)
    print(f"  Benchmark 包含 {total_tasks_in_benchmark} 个 Task")

    # 验证每个 Task 的必要字段
    valid_task_ids = set()
    for task_id, task in problems.items():
        is_valid, missing = validate_task(task)
        if not is_valid:
            all_warnings.append(f"跳过 task_id='{task_id}': 缺少必要字段 '{missing}' (§6.2)")
        else:
            valid_task_ids.add(task_id)

    # 读取并分组样本
    try:
        samples_iter = list(stream_jsonl(samples_path))
    except FileNotFoundError:
        error_report = {
            "error": f"Samples 文件不存在: {samples_path}",
            "samples_path": samples_path,
        }
        return _emit_error(error_report, output_dir, agent_name)

    if not samples_iter:
        error_report = {
            "error": f"Samples 文件为空或无有效条目: {samples_path}",
            "samples_path": samples_path,
        }
        return _emit_error(error_report, output_dir, agent_name)

    try:
        grouped_samples, group_warnings = group_samples_by_task(
            samples_iter, n, valid_task_ids
        )
    except ValueError as e:
        error_report = {
            "error": str(e),
            "samples_path": samples_path,
        }
        return _emit_error(error_report, output_dir, agent_name)

    all_warnings.extend(group_warnings)

    # 取有效的交集 task_ids（既在 Benchmark 有效字段中，也在分组样本中）
    eval_task_ids = sorted(set(problems.keys()) & set(grouped_samples.keys()))
    N = len(eval_task_ids)

    if N == 0:
        error_report = {
            "error": "没有可评测的 Task（Benchmark 和 Samples 无交集）",
        }
        return _emit_error(error_report, output_dir, agent_name)

    total_samples = count_total_samples(
        {tid: grouped_samples[tid] for tid in eval_task_ids}
    )
    print(f"  有效 Task 数: {N}, 总样本数: {total_samples}")
    print(f"  语言: {language}, n={n}, k={k_values}, perf={enable_perf_metrics}")

    # =======================================================================
    # 步骤 2: Task 循环
    # =======================================================================
    print(f"\n[2/4] 执行 Task 循环 (编译 + 测试)...")
    all_results: List[Dict] = []

    for idx, task_id in enumerate(eval_task_ids):
        task = problems[task_id]
        samples = grouped_samples[task_id]

        print(f"  [{idx+1}/{N}] {task_id} ...", end=" ", flush=True)

        task_result = _process_task(
            task, samples, n, language, timeout, enable_perf_metrics, all_warnings
        )
        all_results.append(task_result)

        # 简要状态
        cs = task_result["compile_success_count"]
        correct = sum(1 for t in task_result["test_results"] if t.get("correct"))
        print(f"compile={cs}/{n}, correct={correct}")

    # =======================================================================
    # 步骤 3: 指标计算
    # =======================================================================
    print(f"\n[3/4] 计算指标...")
    metrics, optional_metrics, metric_warnings = compute_all_metrics(
        all_results, n, k_values, enable_perf_metrics
    )
    all_warnings.extend(metric_warnings)

    # §4.7 综合评分
    composite_score = compute_composite_score(
        metrics, optional_metrics, enable_perf_metrics, score_weights
    )

    # =======================================================================
    # 步骤 4: 报告生成
    # =======================================================================
    print(f"[4/4] 生成报告...")

    report = _build_full_report(
        agent_name=agent_name,
        benchmark_name=benchmark_name,
        language=language,
        n=n,
        k_values=k_values,
        N=N,
        total_samples=total_samples,
        metrics=metrics,
        optional_metrics=optional_metrics,
        composite_score=composite_score,
        all_results=all_results,
        warnings=all_warnings,
    )

    # 保存报告
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "report.json")
    md_path = os.path.join(output_dir, "report.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report["json"], f, indent=2, ensure_ascii=False)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report["markdown"])

    print(f"\n  报告已保存:")
    print(f"    JSON:     {json_path}")
    print(f"    Markdown: {md_path}")

    return report


# ===========================================================================
# 单个 Task 处理
# ===========================================================================

def _process_task(
    task: Dict,
    samples: List[Dict],
    n: int,
    language: str,
    timeout: float,
    enable_perf: bool,
    warnings: List[str],
) -> Dict:
    """
    处理单个 Task 的完整流水线。

    返回 Task 级原始数据 (SKILL.md §2.5 结构)。
    """
    task_id = task["task_id"]

    # ----- 2.1 编译检查 -----
    completions = [s.get("completion", "") for s in samples]
    compile_results = []
    successful_indices = []

    for j, completion in enumerate(completions):
        cr = compile_check(task, completion, language, timeout)
        cr["sample_index"] = j
        compile_results.append(cr)
        if cr["compile_success"]:
            successful_indices.append(j)

    compile_success_count = len(successful_indices)

    # ----- 2.2 测试执行 + 性能采集 -----
    test_results = []
    for j in successful_indices:
        tr = run_test(
            task,
            completions[j],
            language=language,
            timeout=timeout,
            enable_perf=enable_perf,
        )
        tr["sample_index"] = j
        # 若 test 为空，total=0 — 按 §6.3，correct 为未定义
        test_results.append(tr)

    # ----- 2.3 资源消耗提取 -----
    resource_consumption = {
        "time_spent_sec": None,
        "api_cost": None,
        "input_tokens": None,
        "output_tokens": None,
    }
    for sample in samples:
        for field in ["time_spent_sec", "api_cost", "input_tokens", "output_tokens"]:
            val = sample.get(field)
            if val is not None:
                if resource_consumption[field] is None:
                    resource_consumption[field] = 0.0
                resource_consumption[field] += float(val)

    # 若所有样本都缺失某字段，保持 None
    for field in list(resource_consumption.keys()):
        if resource_consumption[field] is None:
            resource_consumption[field] = None

    # ----- 2.4 规范最优解性能 (可选) -----
    canonical_perf = None
    if enable_perf and task.get("canonical_solution"):
        try:
            cp = run_test(
                task,
                task["canonical_solution"],
                language=language,
                timeout=timeout,
                enable_perf=True,
            )
            canonical_perf = {
                "execution_time_sec": cp.get("execution_time_sec"),
                "max_memory_mb": cp.get("max_memory_mb"),
                "total_memory_mb_sec": cp.get("total_memory_mb_sec"),
            }
        except Exception:
            canonical_perf = None

    # ----- 2.5 组装 Task 级原始数据 -----
    return {
        "task_id": task_id,
        "n": n,
        "compile_success_count": compile_success_count,
        "compile_results": compile_results,
        "test_results": test_results,
        "resource_consumption": resource_consumption,
        "canonical_perf": canonical_perf,
    }


# ===========================================================================
# 报告构建
# ===========================================================================

def _build_full_report(
    agent_name: str,
    benchmark_name: str,
    language: str,
    n: int,
    k_values: List[int],
    N: int,
    total_samples: int,
    metrics: Dict,
    optional_metrics: Dict,
    composite_score: Dict,
    all_results: List[Dict],
    warnings: List[str],
) -> Dict:
    """构建完整报告（JSON + Markdown）。"""
    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    json_report = _build_json_report(
        agent_name, benchmark_name, language, n, k_values,
        N, total_samples, timestamp, metrics, optional_metrics,
        composite_score, all_results, warnings,
    )
    markdown_report = _build_markdown_report(
        agent_name, benchmark_name, language, n, k_values,
        N, total_samples, timestamp, metrics, optional_metrics,
        composite_score, warnings,
    )

    return {"json": json_report, "markdown": markdown_report}


def _build_json_report(
    agent_name: str,
    benchmark_name: str,
    language: str,
    n: int,
    k_values: List[int],
    N: int,
    total_samples: int,
    timestamp: str,
    metrics: Dict,
    optional_metrics: Dict,
    composite_score: Dict,
    all_results: List[Dict],
    warnings: List[str],
) -> Dict:
    """按 SKILL.md §5.1 模板生成 JSON 报告。"""
    report = {
        "agent_name": agent_name,
        "benchmark_name": benchmark_name,
        "language": language,
        "k_values": k_values,
        "total_tasks": N,
        "total_samples": total_samples,
        "n_per_task": n,
        "timestamp": timestamp,
    }

    result = {
        "report": report,
        "metrics": metrics,
        "composite_score": {
            "value": composite_score.get("value"),
            "unit": composite_score.get("unit"),
            "evaluation_system": composite_score.get("evaluation_system"),
            "description": composite_score.get("description"),
        },
    }

    if optional_metrics:
        result["optional_metrics"] = optional_metrics

    result["per_task_results"] = all_results

    if warnings:
        result["warnings"] = warnings

    return result


def _build_markdown_report(
    agent_name: str,
    benchmark_name: str,
    language: str,
    n: int,
    k_values: List[int],
    N: int,
    total_samples: int,
    timestamp: str,
    metrics: Dict,
    optional_metrics: Dict,
    composite_score: Dict,
    warnings: List[str],
) -> str:
    """按 SKILL.md §5.2 模板生成 Markdown 表格报告。"""
    lines = []

    lines.append(f"# CodeGenEval 测评报告")
    lines.append(f"")
    lines.append(f"**Agent**: {agent_name} | **Benchmark**: {benchmark_name} | **语言**: {language}")
    lines.append(f"**生成时间**: {timestamp} | **n**: {n} | **k**: {', '.join(map(str, k_values))}")
    lines.append(f"")

    # ---- 总体指标表 ----
    lines.append(f"## 总体指标")
    lines.append(f"")
    lines.append(f"| 指标 | 值 | 单位 | 说明 |")
    lines.append(f"|------|-----|------|------|")
    lines.append(f"| Benchmark | {benchmark_name} | — | — |")
    lines.append(f"| 语言 | {language} | — | — |")
    lines.append(f"| 样本总数 | {total_samples} | — | 所有 Task 样本之和 |")
    lines.append(f"| 平均每 Task 样本数 | {n} | — | 由 samples.jsonl 决定 |")
    lines.append(f"| k 值 | {', '.join(map(str, k_values))} | — | pass@k 参数 |")
    lines.append(f"| Task 总数 | {N} | — | — |")

    def _fmt(val):
        """格式化指标值用于表格。"""
        if val == "N/A" or val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:.4f}"
        return str(val)

    # 核心指标行
    core_metric_keys = [
        ("compilation_success_rate", "ratio", "平均编译成功率"),
        ("avg_test_pass_ratio", "ratio", "平均测试通过率（编译失败记为 0）"),
    ]
    for key, unit, desc in core_metric_keys:
        m = metrics.get(key, {})
        lines.append(f"| **{key}** | {_fmt(m.get('value'))} | {unit} | {desc} |")

    # pass@k
    pass_at_k = metrics.get("pass_at_k", {})
    for k_name in sorted(pass_at_k.keys()):
        pk = pass_at_k[k_name]
        lines.append(f"| **{k_name}** | {_fmt(pk.get('value'))} | {pk.get('unit', 'ratio')} | — |")

    # 资源指标
    resource_keys = [
        ("total_time", "s", "Agent 生成总耗时"),
        ("avg_time_per_task", "s", "每个 Task 平均生成耗时"),
        ("total_api_cost", "USD", "总 API 开销"),
        ("avg_api_cost", "USD", "平均每 Task API 开销"),
        ("total_input_tokens", "tokens", "总输入 token 数"),
        ("avg_input_tokens", "tokens", "平均每 Task 输入 token 数"),
        ("total_output_tokens", "tokens", "总输出 token 数"),
        ("avg_output_tokens", "tokens", "平均每 Task 输出 token 数"),
    ]
    for key, unit, desc in resource_keys:
        m = metrics.get(key, {})
        if m:
            lines.append(f"| **{key}** | {_fmt(m.get('value'))} | {unit} | {desc} |")

    # §4.7 综合评分
    cs_val = composite_score.get("value", "N/A")
    cs_sys = composite_score.get("evaluation_system", "")
    cs_desc = f"综合评分（{cs_sys}评估体系）"
    lines.append(f"| **composite_score** | {_fmt(cs_val)} | 分(0-100) | {cs_desc} |")

    lines.append(f"")

    # ---- 可选指标：代码性能 ----
    if optional_metrics:
        code_perf = optional_metrics.get("code_performance", {})
        if code_perf:
            lines.append(f"## 可选指标：代码性能")
            lines.append(f"")
            lines.append(f"| 指标 | 值 | 单位 | 说明 |")
            lines.append(f"|------|-----|------|------|")
            perf_keys = [
                ("avg_execution_time_sec", "s", "编译失败样本记为 0"),
                ("avg_max_memory_mb", "MB", "编译失败样本记为 0"),
                ("avg_total_memory_mb_sec", "MB·s", "梯形法积分"),
                ("avg_normalized_execution_time", "ratio", ">1 表示不如规范最优解"),
            ]
            for key, unit, desc in perf_keys:
                val = code_perf.get(key, {}).get("value") if isinstance(code_perf.get(key), dict) else code_perf.get(key)
                lines.append(f"| {key} | {_fmt(val)} | {unit} | {desc} |")
            lines.append(f"")

    # ---- 警告 ----
    if warnings:
        lines.append(f"## 警告")
        lines.append(f"")
        for w in warnings:
            lines.append(f"- ⚠ {w}")
        lines.append(f"")

    # ---- 附录 ----
    lines.append(f"---")
    lines.append(f"*报告由 CodeGenEval 自动生成*")

    return "\n".join(lines)


# ===========================================================================
# 错误处理
# ===========================================================================

def _emit_error(error_report: Dict, output_dir: str, agent_name: str) -> Dict:
    """输出错误报告并终止。"""
    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    error_report["timestamp"] = timestamp
    error_report["agent_name"] = agent_name

    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "report.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(error_report, f, indent=2, ensure_ascii=False)

    print(f"\n  错误报告已保存: {json_path}")
    return {"json": error_report, "markdown": f"# Error\n\n{json.dumps(error_report, indent=2)}"}


# ===========================================================================
# 交互确认
# ===========================================================================

def _interactive_confirm(**params) -> None:
    """交互模式：展示全部入参供用户确认。"""
    print(f"\n{'=' * 60}")
    print(f"  评测参数确认 (SKILL.md §2)")
    print(f"{'=' * 60}")
    for key, val in params.items():
        print(f"  {key:<24} = {val}")
    print(f"{'=' * 60}")


# ===========================================================================
# CLI 入口
# ===========================================================================

def main():
    """命令行入口，使用 fire 解析参数。"""
    try:
        import fire
    except ImportError:
        print("请安装 fire: pip install fire")
        sys.exit(1)

    def entry_point(
        agent_name: str,
        benchmark_path: str,
        samples_path: str,
        n: int,
        k_values: str = "1,3",
        enable_perf_metrics: bool = False,
        score_weights: Optional[str] = None,
        interactive: bool = False,
        benchmark_name: str = "Unnamed Benchmark",
        language: str = "kotlin",
        timeout: float = 120.0,
        output_dir: str = "./results",
    ):
        """
        CodeGenEval — AI 代码生成 Agent 多维度自动评估。

        示例:
          python pipeline.py \\
            --agent_name "MyAgent" \\
            --benchmark_path "../data/HumanEval_kotlin.jsonl" \\
            --samples_path "../samples/samples_kotlin.jsonl" \\
            --n 10 \\
            --k_values "1,3,5" \\
            --language kotlin

          # 自定义权重:
          python pipeline.py \\
            --agent_name "MyAgent" \\
            --benchmark_path "../data/HumanEval_kotlin.jsonl" \\
            --samples_path "../samples/samples_kotlin.jsonl" \\
            --n 10 \\
            --score_weights '{"compilation_success_rate":0.3,"avg_test_pass_ratio":0.3,"pass_at_k":0.2,"avg_time_per_task":0.1,"avg_api_cost":0.1}'
        """
        if isinstance(k_values, str):
            k_vals = [int(x.strip()) for x in k_values.split(",") if x.strip()]
        else:
            k_vals = [int(x) for x in k_values]

        # 解析 score_weights JSON 字符串
        weights_dict = None
        if score_weights:
            try:
                weights_dict = json.loads(score_weights)
            except json.JSONDecodeError as e:
                print(f"错误: 无法解析 --score_weights JSON: {e}", file=sys.stderr)
                sys.exit(1)

        # 交互模式：展示全部入参 + 权重确认
        if interactive:
            _interactive_confirm(
                agent_name=agent_name,
                benchmark_path=benchmark_path,
                samples_path=samples_path,
                n=n,
                k_values=k_vals,
                enable_perf_metrics=enable_perf_metrics,
                score_weights=weights_dict,
                benchmark_name=benchmark_name,
                language=language,
                timeout=timeout,
                output_dir=output_dir,
            )
            weights_dict = confirm_score_weights(
                score_weights=weights_dict,
                enable_perf_metrics=enable_perf_metrics,
            )
            print()

        run_evaluation(
            agent_name=agent_name,
            benchmark_path=benchmark_path,
            samples_path=samples_path,
            n=n,
            k_values=k_vals,
            enable_perf_metrics=enable_perf_metrics,
            score_weights=weights_dict,
            benchmark_name=benchmark_name,
            language=language,
            timeout=timeout,
            output_dir=output_dir,
        )

    fire.Fire(entry_point)


if __name__ == "__main__":
    main()
