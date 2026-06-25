"""
数据加载 I/O 工具模块。

提供 Benchmark .jsonl 和 Samples .jsonl 的读取、解析、验证、分组功能。
"""

import gzip
import json
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple


def stream_jsonl(filename: str) -> Iterable[Dict]:
    """
    逐行解析 .jsonl（或 .jsonl.gz）文件，yield 每个 JSON 对象。
    跳过空行和纯空白行。
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(f"文件不存在: {filename}")

    if filename.endswith(".gz"):
        with open(filename, "rb") as gzfp:
            with gzip.open(gzfp, "rt") as fp:
                for line in fp:
                    if line.strip():
                        yield json.loads(line)
    else:
        with open(filename, "r", encoding="utf-8") as fp:
            for line in fp:
                if line.strip():
                    yield json.loads(line)


def read_problems(benchmark_path: str) -> Dict[str, Dict]:
    """
    读取 Benchmark .jsonl，以 task_id 为键构建 Task 字典。

    返回:
        Dict[str, Dict]: {task_id: task_object}
    异常:
        ValueError: Benchmark 文件为空或解析后无有效条目
        FileNotFoundError: 文件不存在
    """
    problems = {}
    try:
        for task in stream_jsonl(benchmark_path):
            task_id = task.get("task_id")
            if task_id is not None:
                problems[task_id] = task
    except FileNotFoundError:
        raise
    except Exception as e:
        raise ValueError(f"解析 Benchmark 文件失败: {e}")

    if not problems:
        raise ValueError(f"Benchmark 文件为空或不存在: {benchmark_path}")

    return problems


def write_jsonl(filename: str, data: Iterable[Dict], append: bool = False) -> None:
    """
    将可迭代的字典按行写入 .jsonl 文件。支持 .gz 压缩。

    参数:
        filename: 输出文件路径
        data: 可迭代的字典序列
        append: 是否追加模式
    """
    filename = os.path.expanduser(filename)
    mode = "ab" if append else "wb"

    if filename.endswith(".gz"):
        with open(filename, mode) as fp:
            with gzip.GzipFile(fileobj=fp, mode="wb") as gzfp:
                for x in data:
                    gzfp.write((json.dumps(x, ensure_ascii=False) + "\n").encode("utf-8"))
    else:
        mode = "a" if append else "w"
        with open(filename, mode, encoding="utf-8") as fp:
            for x in data:
                fp.write(json.dumps(x, ensure_ascii=False) + "\n")


def validate_task(task: Dict) -> Tuple[bool, Optional[str]]:
    """
    验证 Task 是否包含所有必要字段。

    必要字段: task_id, prompt, entry_point, test

    返回:
        (is_valid, missing_field_or_None)
    """
    required_fields = ["task_id", "prompt", "entry_point", "test"]
    for field in required_fields:
        if field not in task or task[field] is None:
            return False, field
    return True, None


def group_samples_by_task(
    samples: Iterable[Dict],
    n: int,
    valid_task_ids: set,
) -> Tuple[Dict[str, List[Dict]], List[str]]:
    """
    按 task_id 分组样本，并验证每组数量。

    参数:
        samples: 样本迭代器
        n: 期望的每个 Task 样本数
        valid_task_ids: Benchmark 中有效的 task_id 集合

    返回:
        (grouped_samples, warnings)
        - grouped_samples: {task_id: [sample_1, ..., sample_n]}
        - warnings: 警告信息列表
    """
    grouped: Dict[str, List[Dict]] = {}
    warnings: List[str] = []

    # 第一遍：收集所有样本
    for sample in samples:
        task_id = sample.get("task_id")
        if task_id is None:
            warnings.append("跳过缺少 task_id 的样本")
            continue

        if task_id not in valid_task_ids:
            # 尝试 4 位编号 → 原始编号映射
            # HumanEval/NNNN_lang → HumanEval/N_lang (N = NNNN // 10)
            try:
                m = re.match(r'^(HumanEval/)(\d{2,})(_.*)?$', task_id)
                if m:
                    prefix, num_str, suffix = m.groups()
                    num = int(num_str)
                    if num >= 10:
                        mapped_id = f"{prefix}{num // 10}{suffix or ''}"
                        if mapped_id in valid_task_ids:
                            task_id = mapped_id
            except (ValueError, AttributeError):
                pass

        if task_id not in valid_task_ids:
            warnings.append(
                f"跳过 task_id='{task_id}' 的样本: 该 task_id 在 Benchmark 中不存在"
            )
            continue

        if task_id not in grouped:
            grouped[task_id] = []
        grouped[task_id].append(sample)

    # 第二遍：验证每个 task_id 的样本数
    tasks_to_skip = []
    for task_id, sample_list in grouped.items():
        actual_count = len(sample_list)
        if actual_count != n:
            warnings.append(
                f"跳过 task_id='{task_id}': 期望 {n} 个样本，实际 {actual_count} 个"
            )
            tasks_to_skip.append(task_id)

    for task_id in tasks_to_skip:
        del grouped[task_id]

    if not grouped:
        raise ValueError(
            f"Samples 文件无有效条目（期望每个 Task 有 {n} 个样本），"
            f"请检查文件内容或参数 n"
        )

    return grouped, warnings


def count_total_samples(grouped: Dict[str, List[Dict]]) -> int:
    """统计总样本数。"""
    return sum(len(v) for v in grouped.values())


def count_asserts(test_code: str) -> int:
    """
    统计测试代码中的 assert( 调用次数，用于确定 total_i。

    参数:
        test_code: 测试代码字符串

    返回:
        int: assert 调用次数
    """
    if not test_code or not test_code.strip():
        return 0
    # 统计 "assert(" 出现次数（含可能的空格变体）
    import re
    return len(re.findall(r'\bassert\s*\(', test_code))


def parse_assert_result(stdout: str) -> Tuple[int, int]:
    """
    从 stdout 解析 __ASSERT_RESULT: $passed/$total 格式。

    返回:
        (passed, total)
    异常:
        ValueError: 无法解析
    """
    import re
    match = re.search(r"__ASSERT_RESULT:\s*(\d+)\s*/\s*(\d+)", stdout)
    if not match:
        raise ValueError(f"无法从 stdout 解析 __ASSERT_RESULT: {stdout[-200:]}")
    return int(match.group(1)), int(match.group(2))
