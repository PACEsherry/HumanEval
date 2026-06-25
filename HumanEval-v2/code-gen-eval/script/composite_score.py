"""
综合评分计算模块 (SKILL.md §4.7)。

基于已计算的各项指标，按归一化加权公式计算 0-100 的综合评分。

两种评估体系:
  - basic  (enable_perf_metrics=False): CSR + avg_test_pass_ratio + pass@k(min) + avg_time_per_task + avg_api_cost
  - full   (enable_perf_metrics=True):  上述 5 项 + 4 项代码性能指标

归一化规则 (§4.7.2):
  - 正向指标 (越大越好): normalized = raw_value
  - 负向指标 (越小越好): normalized = 1 / (1 + raw_value)
  - 双向指标 (越接近1越好): raw<=1 → raw; raw>1 → 1/raw
  - 标记为 N/A 的指标: 不参与评分，权重按比例重新分配

用法:
  from composite_score import compute_composite_score
  result = compute_composite_score(metrics, optional_metrics, enable_perf_metrics, score_weights)
"""

from typing import Dict, List, Optional, Tuple
import math


# ---------------------------------------------------------------------------
# 权重配置 (§4.7.4)
# ---------------------------------------------------------------------------

BASIC_WEIGHTS = {
    # 代码正确性 66% (各 0.22)
    "compilation_success_rate": 0.22,
    "avg_test_pass_ratio": 0.22,
    "pass_at_k": 0.22,
    # 资源效率 34%
    "avg_time_per_task": 0.08,
    "avg_input_tokens": 0.08,
    "avg_output_tokens": 0.08,
    "avg_api_cost": 0.10,
}

FULL_WEIGHTS = {
    # === 代码正确性 60% (各 0.20) ===
    "compilation_success_rate": 0.20,
    "avg_test_pass_ratio": 0.20,
    "pass_at_k": 0.20,
    # === 执行性能 25% (各 0.0625) ===
    "avg_execution_time_sec": 0.0625,
    "avg_max_memory_mb": 0.0625,
    "avg_total_memory_mb_sec": 0.0625,
    "avg_normalized_execution_time": 0.0625,
    # === 资源效率 15% (各 0.0375) ===
    "avg_time_per_task": 0.0375,
    "avg_input_tokens": 0.0375,
    "avg_output_tokens": 0.0375,
    "avg_api_cost": 0.0375,
}

# 指标方向: "positive" | "negative" | "bidirectional"
INDICATOR_DIRECTION = {
    "compilation_success_rate": "positive",
    "avg_test_pass_ratio": "positive",
    "pass_at_k": "positive",
    "avg_time_per_task": "negative",
    "avg_input_tokens": "negative",
    "avg_output_tokens": "negative",
    "avg_api_cost": "negative",
    "avg_execution_time_sec": "negative",
    "avg_max_memory_mb": "negative",
    "avg_total_memory_mb_sec": "negative",
    "avg_normalized_execution_time": "bidirectional",
}


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

def _normalize(raw_value: float, direction: str) -> float:
    """
    将原始指标值归一化到 [0, 1] (§4.7.2)。

    参数:
        raw_value: 原始值 (非 N/A)
        direction: "positive" | "negative" | "bidirectional"
    """
    if direction == "positive":
        return raw_value
    elif direction == "negative":
        return 1.0 / (1.0 + math.log(1.0 + raw_value))
    elif direction == "bidirectional":
        if raw_value <= 1.0:
            return raw_value
        else:
            return 1.0 / raw_value
    else:
        raise ValueError(f"未知的指标方向: {direction}")


# ---------------------------------------------------------------------------
# 提取指标值
# ---------------------------------------------------------------------------

def _extract_metrics(metrics: Dict, optional_metrics: Dict,
                     enable_perf_metrics: bool) -> Dict[str, Optional[float]]:
    """
    从 metrics 字典中提取各指标的原始值。
    N/A 或缺失的指标返回 None。
    """
    result = {}

    # ---- 必选指标 ----
    csr = metrics.get("compilation_success_rate", {})
    result["compilation_success_rate"] = _float_or_none(csr.get("value"))

    atpr = metrics.get("avg_test_pass_ratio", {})
    result["avg_test_pass_ratio"] = _float_or_none(atpr.get("value"))

    # pass@k: 取最小 k 值对应的 pass@k
    pass_at_k = metrics.get("pass_at_k", {})
    if pass_at_k:
        min_k = min(
            (int(k.replace("pass@", "")) for k in pass_at_k.keys()),
            default=None
        )
        if min_k is not None:
            pk = pass_at_k.get(f"pass@{min_k}", {})
            result["pass_at_k"] = _float_or_none(pk.get("value"))
        else:
            result["pass_at_k"] = None
    else:
        result["pass_at_k"] = None

    apt = metrics.get("avg_time_per_task", {})
    result["avg_time_per_task"] = _float_or_none(apt.get("value"))

    ac = metrics.get("avg_api_cost", {})
    result["avg_api_cost"] = _float_or_none(ac.get("value"))

    ait = metrics.get("avg_input_tokens", {})
    result["avg_input_tokens"] = _float_or_none(ait.get("value"))

    aot = metrics.get("avg_output_tokens", {})
    result["avg_output_tokens"] = _float_or_none(aot.get("value"))

    # ---- 可选指标 (仅 full 体系) ----
    if enable_perf_metrics:
        code_perf = optional_metrics.get("code_performance", {})
        for key in ["avg_execution_time_sec", "avg_max_memory_mb",
                     "avg_total_memory_mb_sec", "avg_normalized_execution_time"]:
            item = code_perf.get(key, {})
            result[key] = _float_or_none(item.get("value") if isinstance(item, dict) else item)
    else:
        for key in ["avg_execution_time_sec", "avg_max_memory_mb",
                     "avg_total_memory_mb_sec", "avg_normalized_execution_time"]:
            result[key] = None

    return result


def _float_or_none(val) -> Optional[float]:
    """安全转换为 float，N/A 或 None 返回 None。"""
    if val is None or val == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 综合评分计算
# ---------------------------------------------------------------------------

def compute_composite_score(
    metrics: Dict,
    optional_metrics: Optional[Dict] = None,
    enable_perf_metrics: bool = False,
    score_weights: Optional[Dict[str, float]] = None,
) -> Dict:
    """
    计算综合评分 (§4.7.3)。

    参数:
        metrics:             必选指标字典 (来自 evaluation.compute_all_metrics)
        optional_metrics:    可选指标字典 (含 code_performance)
        enable_perf_metrics: 是否启用完整评估体系
        score_weights:       自定义权重 (None 则使用默认等权重)

    返回:
        {
            "value": float,              # 综合评分 (0-100)
            "unit": "score (0-100)",
            "evaluation_system": str,    # "basic" | "full"
            "description": str,
            "details": {                 # 各指标明细
                "indicator_name": {
                    "raw": float | None,
                    "normalized": float | None,
                    "direction": str,
                    "weight": float,
                    "contribution": float,
                }
            }
        }
    """
    if optional_metrics is None:
        optional_metrics = {}

    evaluation_system = "full" if enable_perf_metrics else "basic"

    # 选择权重方案
    if score_weights is not None:
        weights = dict(score_weights)
    else:
        weights = dict(FULL_WEIGHTS if enable_perf_metrics else BASIC_WEIGHTS)

    # 提取原始值
    raw_values = _extract_metrics(metrics, optional_metrics, enable_perf_metrics)

    # 过滤 N/A 指标并归一化
    valid_indicators = {}
    for key, raw in raw_values.items():
        if raw is not None and key in INDICATOR_DIRECTION:
            direction = INDICATOR_DIRECTION[key]
            normalized = _normalize(raw, direction)
            valid_indicators[key] = {
                "raw": raw,
                "normalized": normalized,
                "direction": direction,
            }

    if not valid_indicators:
        return {
            "value": "N/A",
            "unit": "score (0-100)",
            "evaluation_system": evaluation_system,
            "description": "无有效指标数据，无法计算综合评分",
            "details": {},
        }

    # 重新分配权重: 只计算有效指标的权重，按比例缩放使 Σw = 1
    effective_weights = {}
    total_raw_weight = 0.0
    for key in valid_indicators:
        w = weights.get(key, 0.0)
        effective_weights[key] = w
        total_raw_weight += w

    if total_raw_weight == 0.0:
        # 所有权重为 0 或指标都不在权重表中 → 等权重
        n = len(valid_indicators)
        for key in valid_indicators:
            effective_weights[key] = 1.0 / n
    else:
        # 按比例放大到 1
        for key in effective_weights:
            effective_weights[key] /= total_raw_weight

    # 计算加权和
    score = 0.0
    details = {}
    for key, info in valid_indicators.items():
        w = effective_weights[key]
        contribution = w * info["normalized"]
        score += contribution
        details[key] = {
            "raw": info["raw"],
            "normalized": info["normalized"],
            "direction": info["direction"],
            "weight": w,
            "contribution": contribution,
        }

    composite = round(score * 100.0, 2)

    desc = (
        f"综合评分（{'完整' if enable_perf_metrics else '基础'}评估体系，"
        f"{'自定义' if score_weights else '等'}权重），分数越高整体表现越好"
    )

    return {
        "value": composite,
        "unit": "score (0-100)",
        "evaluation_system": evaluation_system,
        "description": desc,
        "details": details,
    }


# ===================================================================
# CLI: 从 report.json 直接计算
# ===================================================================

def main():
    """从已有的 report.json 计算综合评分并输出。"""
    import argparse
    import json
    import sys

    p = argparse.ArgumentParser(description="从 report.json 计算综合评分")
    p.add_argument("report_json", help="report.json 路径")
    p.add_argument("--weights", default=None, help="自定义权重 JSON 字符串")
    p.add_argument("--quiet", action="store_true", help="仅输出数值")
    args = p.parse_args()

    with open(args.report_json, "r", encoding="utf-8") as f:
        report = json.load(f)

    metrics = report.get("metrics", {})
    optional_metrics = report.get("optional_metrics", {})

    # 从 report 推断评估体系
    enable_perf = bool(optional_metrics)

    weights = None
    if args.weights:
        weights = json.loads(args.weights)

    result = compute_composite_score(metrics, optional_metrics, enable_perf, weights)

    if args.quiet:
        print(result["value"])
    else:
        print(f"评估体系: {result['evaluation_system']}")
        print(f"综合评分: {result['value']} / 100")
        print(f"说明: {result['description']}")
        print()
        print("各指标明细:")
        print(f"{'指标':<35} {'原始值':>10} {'归一化':>8} {'方向':>12} {'权重':>8} {'贡献':>8}")
        print("-" * 85)
        for key, d in result["details"].items():
            print(f"{key:<35} {d['raw']:>10.4f} {d['normalized']:>8.4f} "
                  f"{d['direction']:>12} {d['weight']:>8.4f} {d['contribution']:>8.4f}")

    # 输出 JSON（可追加到 report.json）
    print()
    print("=== JSON patch ===")
    patch = {
        "composite_score": {
            "value": result["value"],
            "unit": result["unit"],
            "evaluation_system": result["evaluation_system"],
            "description": result["description"],
        }
    }
    print(json.dumps(patch, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
