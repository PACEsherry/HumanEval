"""
指标计算引擎模块。

根据 SKILL.md §4 中的公式，从 all_results 原始数据计算全部 13 个评价指标。

指标清单:
  §4.1 — compilation_success_rate (CSR)
  §4.2 — avg_test_pass_ratio
  §4.3 — pass@k
  §4.4 — total_time / avg_time_per_task
  §4.5 — api_cost / tokens (total & avg)
  §4.6 — execution_time / max_memory / total_memory / normalized_exec_time (可选)
"""

import itertools
import json
from typing import Dict, List, Optional, Tuple, Union

import numpy as np


# ===========================================================================
# pass@k 无偏估计
# ===========================================================================

def estimate_pass_at_k(
    num_samples: Union[int, List[int], np.ndarray],
    num_correct: Union[List[int], np.ndarray],
    k: int,
) -> np.ndarray:
    """
    对每个 Task 计算 pass@k 的无偏估计。

    公式 (§4.3):
        pass@k_i = 1 - C(n - c_i, k) / C(n, k)

    数值实现 (等效):
        if n - c < k: pass@k = 1.0
        else: pass@k = 1.0 - Π_j=1..k (1 - k / (n - c + j))

    参数:
        num_samples: 每个 Task 的 n 值（int 或数组）
        num_correct: 每个 Task 的 c 值数组
        k: 采样次数

    返回:
        每个 Task 的 pass@k 值 np.ndarray
    """
    def estimator(n: int, c: int, k_val: int) -> float:
        if n - c < k_val:
            return 1.0
        return 1.0 - float(np.prod(1.0 - k_val / np.arange(n - c + 1, n + 1)))

    if isinstance(num_samples, int):
        num_samples_it = itertools.repeat(num_samples, len(num_correct))
    else:
        assert len(num_samples) == len(num_correct)
        num_samples_it = iter(num_samples)

    return np.array([
        estimator(int(n), int(c), k) for n, c in zip(num_samples_it, num_correct)
    ])


# ===========================================================================
# §4.1 编译成功率 (CSR)
# ===========================================================================

def compute_compile_success_rate(all_results: List[Dict]) -> Dict:
    """
    计算编译成功率。

    公式:
        CSR_i  = compile_success_count_i / n           [每个 Task]
        CSR    = (1 / N) * Σ CSR_i                     [Benchmark 整体]
    """
    N = len(all_results)
    if N == 0:
        return {"value": 0.0, "unit": "ratio"}

    csr_sum = 0.0
    for tr in all_results:
        n = tr.get("n", 1)
        compile_success_count = tr.get("compile_success_count", 0)
        csr_i = compile_success_count / n if n > 0 else 0.0
        csr_sum += csr_i

    return {
        "value": csr_sum / N,
        "unit": "ratio",
    }


# ===========================================================================
# §4.2 平均测试通过率
# ===========================================================================

def compute_avg_test_pass_ratio(all_results: List[Dict]) -> Dict:
    """
    计算平均测试通过率。

    公式:
        test_pass_ratio_ij   = passed_ij / total_i        (compile fail → 0)
        avg_test_pass_ratio_i = (1/n) * Σ_j test_pass_ratio_ij
        avg_test_pass_ratio   = (1/N) * Σ_i avg_test_pass_ratio_i

    test 为空字符串的 Task 不参与计算 (mark N/A)。
    """
    N = len(all_results)
    if N == 0:
        return {"value": "N/A", "unit": "ratio"}

    total_avg = 0.0
    valid_tasks = 0

    for tr in all_results:
        n = tr.get("n", 1)
        if n == 0:
            continue

        compile_results = tr.get("compile_results", [])
        test_results = tr.get("test_results", [])

        # test_results 只包含编译成功样本 — 需要补齐编译失败样本
        # 构建 sample_index → test_result 映射
        test_by_idx = {t.get("sample_index"): t for t in test_results}

        ratio_sum = 0.0
        task_has_empty_test = False

        for j in range(n):
            # 查找编译结果
            compile_success = True
            for cr in compile_results:
                if cr.get("sample_index") == j:
                    compile_success = cr.get("compile_success", False)
                    break

            if not compile_success:
                # 编译失败 → test_pass_ratio = 0 (§4.2 + §6.7)
                ratio_sum += 0.0
                continue

            tr_j = test_by_idx.get(j)
            if tr_j is None:
                ratio_sum += 0.0
                continue

            total_i = tr_j.get("total", 0)
            if total_i == 0:
                # test 为空 — 特殊标记
                task_has_empty_test = True
                continue

            passed = tr_j.get("passed", 0)
            ratio_sum += passed / total_i

        if task_has_empty_test:
            # test 为空字符串的 Task: avg_test_pass_ratio 标为 N/A (§6.3)
            # 但仍需检查是否有非空的测试结果
            non_empty_results = [
                t for t in test_results
                if t.get("total", 0) > 0
            ]
            if not non_empty_results:
                continue  # 跳过该 Task，不计入 N
            # 若 test 代码为空但 test_results 中 total 均为 0，跳过

        total_avg += ratio_sum / n
        valid_tasks += 1

    if valid_tasks == 0:
        return {"value": "N/A", "unit": "ratio"}

    return {
        "value": total_avg / valid_tasks,
        "unit": "ratio",
    }


# ===========================================================================
# §4.3 pass@k
# ===========================================================================

def compute_pass_at_k(
    all_results: List[Dict],
    n: int,
    k_values: List[int],
    warnings: Optional[List[str]] = None,
) -> Dict[str, Dict]:
    """
    计算 pass@k。

    公式:
        c_i     = Task i 中 correct=true 的样本数
        pass@k_i = 1 - C(n - c_i, k) / C(n, k)
        pass@k   = (1 / N) * Σ pass@k_i

    特殊处理:
        - test 为空时，correct=未定义，该样本不参与 c_i 计数 (§6.3)
        - k > n 时该 pass@k 标为 N/A (§6.4)
        - 编译失败样本 correct=false → c_i 不包含
    """
    if warnings is None:
        warnings = []

    N = len(all_results)
    if N == 0:
        return {f"pass@{k}": {"value": "N/A", "unit": "ratio"} for k in k_values}

    # 收集每个 Task 的 c_i
    correct_counts: List[int] = []
    for tr in all_results:
        test_results = tr.get("test_results", [])
        c_i = 0
        for t in test_results:
            # 只统计 total > 0 且 correct=True 的样本
            # total=0 表示 test 为空，correct 未定义 (§6.3)，不计入 c
            if t.get("total", 0) > 0 and t.get("correct", False):
                c_i += 1
        correct_counts.append(c_i)

    pass_at_k_results = {}
    for k in k_values:
        if k > n:
            pass_at_k_results[f"pass@{k}"] = {
                "value": "N/A",
                "unit": "ratio",
            }
            warnings.append(f"pass@{k}: k={k} > n={n}，标记为 N/A (§6.4)")
            continue

        per_task = estimate_pass_at_k(n, correct_counts, k)
        pass_at_k_results[f"pass@{k}"] = {
            "value": float(np.mean(per_task)),
            "unit": "ratio",
        }

    return pass_at_k_results


# ===========================================================================
# §4.4 总耗时 & §4.5 API 开销与 Token
# ===========================================================================

def _extract_resource_field(all_results: List[Dict], field: str) -> Tuple[bool, float]:
    """
    从 all_results 提取资源消耗字段，返回 (has_data, total_sum)。
    """
    has_data = False
    total = 0.0
    for tr in all_results:
        rc = tr.get("resource_consumption") or {}
        val = rc.get(field)
        if val is not None:
            has_data = True
            total += float(val)
    return has_data, total


def compute_resource_metrics(all_results: List[Dict]) -> Dict:
    """
    计算资源消耗指标 (§4.4 + §4.5)。

    公式:
        total_time        = Σ task_time_i               (task_time_i = Σ sample_time_ij)
        avg_time_per_task = total_time / N
        total_api_cost    = Σ task_cost_i               (task_cost_i = Σ sample_cost_ij)
        avg_api_cost      = (1/N) * Σ task_cost_i
        total_input_tokens  = Σ task_input_tokens_i
        avg_input_tokens    = (1/N) * Σ task_input_tokens_i
        total_output_tokens = Σ task_output_tokens_i
        avg_output_tokens   = (1/N) * Σ task_output_tokens_i
    """
    N = len(all_results)
    fields = ["time_spent_sec", "api_cost", "input_tokens", "output_tokens"]

    metrics = {}

    for field in fields:
        has_data, total = _extract_resource_field(all_results, field)
        if not has_data:
            metrics[f"total_{field}"] = {"value": "N/A", "unit": _unit_for_field(field)}
            metrics[f"avg_{field}"] = {"value": "N/A", "unit": _unit_for_field(field)}
        else:
            if field == "time_spent_sec":
                key_total = "total_time"
                key_avg = "avg_time_per_task"
                unit = "seconds"
            elif field == "api_cost":
                key_total = "total_api_cost"
                key_avg = "avg_api_cost"
                unit = "USD"
            else:
                key_total = f"total_{field}"
                key_avg = f"avg_{field}"
                unit = "tokens"

            metrics[key_total] = {"value": total, "unit": unit}
            metrics[key_avg] = {
                "value": total / N if N > 0 else 0.0,
                "unit": unit,
            }

    return metrics


def _unit_for_field(field: str) -> str:
    """返回字段对应的单位字符串。"""
    mapping = {
        "time_spent_sec": "seconds",
        "api_cost": "USD",
        "input_tokens": "tokens",
        "output_tokens": "tokens",
    }
    return mapping.get(field, "")


# ===========================================================================
# §4.6 代码性能指标 (可选)
# ===========================================================================

def compute_performance_metrics(all_results: List[Dict]) -> Dict:
    """
    计算代码性能指标。

    公式:
        task_avg_exec_time_i    = (1/n) * Σ_j execution_time_sec_ij          [compile fail → 0]
        avg_execution_time_sec  = (1/N) * Σ_i task_avg_exec_time_i

        task_avg_max_mem_i     = (1/n) * Σ_j max_memory_mb_ij               [compile fail → 0]
        avg_max_memory_mb      = (1/N) * Σ_i task_avg_max_mem_i

        task_avg_total_mem_i   = (1/n) * Σ_j total_memory_mb_sec_ij         [compile fail → 0]
        avg_total_memory_mb_sec = (1/N) * Σ_i task_avg_total_mem_i

        task_avg_norm_exec_i   = (1/n) * Σ_j (exec_time_ij / canonical_exec_time_i)  [compile fail → 0]
        avg_normalized_exec_time = (1/N) * Σ_i task_avg_norm_exec_i

    若某 Task 的 canonical_perf 缺失，其归一化执行时间不参与 N（标 N/A）。
    """
    N = len(all_results)
    if N == 0:
        return {
            "avg_execution_time_sec": {"value": "N/A", "unit": "seconds"},
            "avg_max_memory_mb": {"value": "N/A", "unit": "MB"},
            "avg_total_memory_mb_sec": {"value": "N/A", "unit": "MB·s"},
            "avg_normalized_execution_time": {"value": "N/A", "unit": "ratio"},
        }

    # 累加器
    sum_task_avg_exec_time = 0.0
    sum_task_avg_max_mem = 0.0
    sum_task_avg_total_mem = 0.0
    sum_task_avg_norm_exec = 0.0
    norm_exec_valid_tasks = 0

    for tr in all_results:
        n = tr.get("n", 1)
        if n == 0:
            continue

        compile_results = tr.get("compile_results", [])
        test_results = tr.get("test_results", [])
        canonical_perf = tr.get("canonical_perf")

        # 构建 sample_index → test_result 映射
        test_by_idx = {t.get("sample_index"): t for t in test_results}

        # 构建编译成功/失败映射
        compile_status = {}
        for cr in compile_results:
            compile_status[cr.get("sample_index")] = cr.get("compile_success", False)

        sum_exec_time = 0.0
        sum_max_mem = 0.0
        sum_total_mem = 0.0
        sum_norm_exec = 0.0

        for j in range(n):
            compile_success = compile_status.get(j, False)

            if not compile_success:
                # 编译失败 → 所有性能值 = 0
                # sum_exec_time += 0.0 (implicit)
                # sum_max_mem += 0.0
                # sum_total_mem += 0.0
                # sum_norm_exec += 0.0
                continue

            tr_j = test_by_idx.get(j)
            if tr_j is None:
                continue

            exec_time = tr_j.get("execution_time_sec")
            max_mem = tr_j.get("max_memory_mb")
            total_mem = tr_j.get("total_memory_mb_sec")

            if exec_time is not None:
                sum_exec_time += exec_time
            if max_mem is not None:
                sum_max_mem += max_mem
            if total_mem is not None:
                sum_total_mem += total_mem

            # 归一化执行时间
            if (
                exec_time is not None
                and canonical_perf is not None
                and canonical_perf.get("execution_time_sec") is not None
                and canonical_perf["execution_time_sec"] > 0
            ):
                sum_norm_exec += exec_time / canonical_perf["execution_time_sec"]

        sum_task_avg_exec_time += sum_exec_time / n
        sum_task_avg_max_mem += sum_max_mem / n
        sum_task_avg_total_mem += sum_total_mem / n

        # 归一化: 只统计有 canonical_perf 的 Task
        if (
            canonical_perf is not None
            and canonical_perf.get("execution_time_sec") is not None
            and canonical_perf["execution_time_sec"] > 0
        ):
            sum_task_avg_norm_exec += sum_norm_exec / n
            norm_exec_valid_tasks += 1

    metrics = {
        "avg_execution_time_sec": {
            "value": sum_task_avg_exec_time / N if N > 0 else 0.0,
            "unit": "seconds",
        },
        "avg_max_memory_mb": {
            "value": sum_task_avg_max_mem / N if N > 0 else 0.0,
            "unit": "MB",
        },
        "avg_total_memory_mb_sec": {
            "value": sum_task_avg_total_mem / N if N > 0 else 0.0,
            "unit": "MB·s",
        },
    }

    if norm_exec_valid_tasks > 0:
        metrics["avg_normalized_execution_time"] = {
            "value": sum_task_avg_norm_exec / norm_exec_valid_tasks,
            "unit": "ratio",
        }
    else:
        metrics["avg_normalized_execution_time"] = {
            "value": "N/A",
            "unit": "ratio",
        }

    return metrics


# ===========================================================================
# score_weights 交互确认 (§4.7.4 + 入参确认流程)
# ===========================================================================

# 指标中文标签（用于交互展示）
_INDICATOR_LABELS = {
    "compilation_success_rate": "编译成功率",
    "avg_test_pass_ratio": "平均测试通过率",
    "pass_at_k": "Pass@k",
    "avg_time_per_task": "平均每任务耗时",
    "avg_input_tokens": "平均输入Token数",
    "avg_output_tokens": "平均输出Token数",
    "avg_api_cost": "平均API开销",
    "avg_execution_time_sec": "平均代码执行时间",
    "avg_max_memory_mb": "平均最大内存",
    "avg_total_memory_mb_sec": "平均总内存·秒",
    "avg_normalized_execution_time": "平均归一化执行时间",
}

# 指标方向中文标签
_DIRECTION_LABELS = {
    "positive": "正向 (越大越好)",
    "negative": "负向 (越小越好)",
    "bidirectional": "双向 (越接近1越好)",
}

# 已知的合法指标名集合
_VALID_INDICATOR_NAMES = frozenset(_INDICATOR_LABELS.keys())


def confirm_score_weights(
    score_weights: Optional[Dict[str, float]] = None,
    enable_perf_metrics: bool = False,
) -> Optional[Dict[str, float]]:
    """
    交互式确认 score_weights 权重配置。

    在执行测评前展示当前权重配置，允许用户确认或自定义修改。
    对应 SKILL.md §4.7.4 权重配置 + 入参确认流程。

    参数:
        score_weights:      用户已提供的权重配置（None 表示未指定，使用默认等权重）
        enable_perf_metrics: 是否启用完整评估体系（决定展示 basic 或 full 指标集）

    返回:
        确认后的权重字典，或 None（使用默认等权重）

    交互选项:
        - 回车 / Y:   确认当前配置，返回当前权重（未指定时返回 None）
        - D:          恢复默认等权重（返回 None）
        - JSON 字符串: 使用自定义权重，自动校验并返回
    """
    # 延迟导入，避免模块级循环依赖
    from composite_score import BASIC_WEIGHTS, FULL_WEIGHTS, INDICATOR_DIRECTION

    evaluation_system = "full" if enable_perf_metrics else "basic"
    default_weights = FULL_WEIGHTS if enable_perf_metrics else BASIC_WEIGHTS

    # 确定当前生效的权重配置（用于展示）
    if score_weights is not None:
        display_weights = dict(score_weights)
        source_desc = "用户自定义"
    else:
        display_weights = dict(default_weights)
        source_desc = "默认等权重"

    # ---- 打印权重配置表 ----
    _print_weights_table(
        display_weights=display_weights,
        default_weights=default_weights,
        evaluation_system=evaluation_system,
        source_desc=source_desc,
        indicator_direction=INDICATOR_DIRECTION,
    )

    # ---- 交互确认 ----
    _print_json_template(default_weights, evaluation_system)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            user_input = input(
                "\n确认权重配置？"
                "[Y=确认 / 输入JSON自定义 / D=恢复默认] "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[输入中断] 使用当前配置。")
            return score_weights

        # 空输入或 Y → 确认
        if user_input == "" or user_input.upper() == "Y":
            print("✓ 权重配置已确认。")
            return score_weights

        # D → 恢复默认
        if user_input.upper() == "D":
            print("✓ 已恢复默认等权重配置。")
            return None

        # 尝试解析为 JSON
        try:
            custom_weights = json.loads(user_input)
        except json.JSONDecodeError as e:
            print(f"✗ JSON 解析失败: {e}")
            if attempt < max_retries - 1:
                print(f"  请重试（剩余 {max_retries - attempt - 1} 次）...")
            continue

        if not isinstance(custom_weights, dict):
            print("✗ 输入必须是 JSON 对象 (object)，请重试。")
            continue

        # 校验权重
        valid, message = _validate_score_weights(custom_weights)
        if not valid:
            print(f"⚠ {message}")
            confirm = input("是否仍要使用此配置？[y/N] ").strip().upper()
            if confirm != "Y":
                print("  已放弃，请重新输入。")
                continue

        print("✓ 自定义权重配置已确认。")
        return custom_weights

    # 超过最大重试次数
    print(f"\n已达到最大重试次数 ({max_retries})，使用当前配置。")
    return score_weights


def _print_weights_table(
    display_weights: Dict[str, float],
    default_weights: Dict[str, float],
    evaluation_system: str,
    source_desc: str,
    indicator_direction: Dict[str, str],
) -> None:
    """打印权重配置表到终端。"""
    system_label = "完整评估体系" if evaluation_system == "full" else "基础评估体系"

    print(f"\n{'=' * 72}")
    print(f"  score_weights 权重配置 — {system_label} ({source_desc})")
    print(f"{'=' * 72}")
    print(f"  {'指标':<36} {'权重':>8}   {'方向':<24}")
    print(f"  {'-' * 36} {'-' * 8}   {'-' * 24}")

    total = 0.0
    for key in sorted(display_weights.keys()):
        w = display_weights[key]
        label = _INDICATOR_LABELS.get(key, key)
        direction = indicator_direction.get(key, "positive")
        dir_label = _DIRECTION_LABELS.get(direction, direction)
        is_default = key in default_weights
        marker = "" if is_default else " *"
        print(f"  {label:<36} {w:>8.4f}   {dir_label:<24}{marker}")
        total += w

    print(f"  {'-' * 36} {'-' * 8}")
    print(f"  {'合计':<36} {total:>8.4f}")

    if not _is_close(total, 1.0):
        print(f"  ⚠ 权重合计 ≠ 1.0 (偏差: {total - 1.0:+.4f})，"
              f"计算时将自动归一化。")

    # 列出用户自定义中不在默认权重里的指标
    extra_keys = set(display_weights.keys()) - set(default_weights.keys())
    if extra_keys:
        print(f"\n  * 标记的指标不在当前评估体系的默认指标集中，"
              f"将被忽略（权重按比例重新分配）。")

    print(f"{'=' * 72}")


def _print_json_template(
    default_weights: Dict[str, float],
    evaluation_system: str,
) -> None:
    """打印可复制的 JSON 模板，帮助用户了解输入格式。"""
    template = {
        key: round(w, 4) for key, w in sorted(default_weights.items())
    }
    json_str = json.dumps(template, indent=2, ensure_ascii=False)

    system_label = "完整评估体系" if evaluation_system == "full" else "基础评估体系"
    box_width = 52
    print(f"\n  ┌─ JSON 模板（{system_label}）{'─' * (box_width - len(system_label) - 13)}")
    for line in json_str.split("\n"):
        print(f"  │ {line}")
    print(f"  └{'─' * box_width}")
    print(f"  提示: 权重值 ≥ 0，合计无需严格等于 1（系统自动归一化），")
    print(f"        可只写关心的指标，未写入的权重视为 0。")


def _validate_score_weights(weights: Dict) -> Tuple[bool, str]:
    """
    校验自定义权重配置。

    返回:
        (is_valid, message)
    """
    if not weights:
        return False, "权重字典为空。"

    # 检查所有权重值是否为非负数
    negative_keys = []
    non_numeric_keys = []
    for key, val in weights.items():
        try:
            fval = float(val)
            if fval < 0:
                negative_keys.append(key)
        except (ValueError, TypeError):
            non_numeric_keys.append(key)

    if non_numeric_keys:
        return False, f"以下指标的值无法转为数字: {non_numeric_keys}"
    if negative_keys:
        return False, f"以下指标的权重为负数: {negative_keys}"

    # 检查是否有未知指标名
    unknown_keys = set(weights.keys()) - _VALID_INDICATOR_NAMES
    if unknown_keys:
        return False, (
            f"未知指标名: {sorted(unknown_keys)}。"
            f"合法名称: {sorted(_VALID_INDICATOR_NAMES)}"
        )

    # 权重和检查（警告但不拒绝）
    total = sum(float(v) for v in weights.values())
    if not _is_close(total, 1.0):
        return True, (
            f"权重合计 = {total:.4f} (≠ 1.0)，"
            f"计算时将自动归一化。"
        )

    return True, "OK"


def _is_close(a: float, b: float, rel_tol: float = 1e-6) -> bool:
    """比较两个浮点数是否接近相等。"""
    return abs(a - b) <= rel_tol * max(abs(a), abs(b), 1.0)


# ===========================================================================
# 总入口
# ===========================================================================

def compute_all_metrics(
    all_results: List[Dict],
    n: int,
    k_values: List[int],
    enable_perf_metrics: bool = False,
) -> Tuple[Dict, Dict, List[str]]:
    """
    从 all_results 计算所有指标。

    参数:
        all_results: Task 级原始数据列表
        n: 每个 Task 的样本数量
        k_values: pass@k 的 k 值列表
        enable_perf_metrics: 是否启用性能指标

    返回:
        (metrics, optional_metrics, warnings)
    """
    warnings: List[str] = []

    # §4.1 编译成功率
    csr = compute_compile_success_rate(all_results)

    # §4.2 平均测试通过率
    avg_tpr = compute_avg_test_pass_ratio(all_results)

    # §4.3 pass@k
    pass_at_k = compute_pass_at_k(all_results, n, k_values, warnings)

    # §4.4 + §4.5 资源消耗
    resource = compute_resource_metrics(all_results)

    # 组装 core metrics
    metrics = {
        "compilation_success_rate": {
            **csr,
            "description": "平均编译成功率（所有 Task 平均）",
        },
        "avg_test_pass_ratio": {
            **avg_tpr,
            "description": "平均测试通过率（所有 Task 平均，编译失败样本记为 0）",
        },
        "pass_at_k": pass_at_k,
    }
    # 合并资源消耗指标
    time_keys = ["total_time", "avg_time_per_task"]
    cost_keys = ["total_api_cost", "avg_api_cost"]
    token_keys = ["total_input_tokens", "avg_input_tokens", "total_output_tokens", "avg_output_tokens"]

    for k in time_keys:
        if k in resource:
            metrics[k] = {**resource[k], "description": _desc_for_key(k)}

    for k in cost_keys:
        if k in resource:
            metrics[k] = {**resource[k], "description": _desc_for_key(k)}

    for k in token_keys:
        if k in resource:
            metrics[k] = {**resource[k], "description": _desc_for_key(k)}

    # §4.6 代码性能 (可选)
    optional_metrics = {}
    if enable_perf_metrics:
        perf = compute_performance_metrics(all_results)
        optional_metrics["code_performance"] = {
            **perf,
            "description": "代码性能指标（编译失败样本记为 0，按 Task 平均后对 Task 数取平均）",
        }
        # 检查是否有 canonical_solution 缺失导致归一化 N/A
        if perf.get("avg_normalized_execution_time", {}).get("value") == "N/A":
            warnings.append(
                "部分或全部 Task 缺少 canonical_solution，"
                "avg_normalized_execution_time 标记为 N/A (§6.9)"
            )

    return metrics, optional_metrics, warnings


def _desc_for_key(key: str) -> str:
    """指标描述映射。"""
    descs = {
        "total_time": "Agent 代码生成总耗时（samples.jsonl 中 time_spent_sec 之和）",
        "avg_time_per_task": "每个 Task 平均生成耗时",
        "total_api_cost": "总 API 开销",
        "avg_api_cost": "平均每 Task API 开销",
        "total_input_tokens": "总输入 token 数",
        "avg_input_tokens": "平均每 Task 输入 token 数",
        "total_output_tokens": "总输出 token 数",
        "avg_output_tokens": "平均每 Task 输出 token 数",
    }
    return descs.get(key, "")
