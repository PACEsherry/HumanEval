# HumanEval-Cangjie 历次测评分析与改进建议

## 结论

### 核心判断

**当前的编译失败源于一个结构性矛盾，而非模型能力不足或 Skills 指导不到位。**

模型 100% 正确地使用了 `ArrayList<T>`、`HashMap<K,V>` 等 API——它知道怎么写，但 **100% 遗漏了 `import std.collection.*`**。原因：盲生成 prompt 要求模型只补完 `{ 函数体 }`，而 Cangjie 的 `import` 语句必须在函数外部、文件顶部声明，函数体内写 import 既违反语法规则又被 P0 规则禁止。这是一个 **prompt 架构与 import 机制的矛盾**，不是 Skills 覆盖不全。

### 最有效改进：自动 import 注入

在 `generate_samples_cj_v2.py` 的 `clean_completion()` 后增加自动扫描+注入步骤，按 completion 中出现的标识符自动补齐 import：

| 标识符 | 注入 import |
|--------|-------------|
| ArrayList / HashMap / HashSet | `import std.collection.*` |
| sort(...) | `import std.sort.*` |
| isUpperCase / isLowerCase / isNumber | `import std.unicode.*` |
| parse / tryParse | `import std.convert.*` |
| sqrt / abs / pow (非手动实现) | `import std.math.*` |

**预期效果**：消除 24/46 编译失败（52.2%），CSR 从 71.95% → **~86.6%**，pass@1 从 65.24% → **~80%+**。

### 补充 P0 规则（次要但有效）

1. Lambda/闭包不能捕获 var 变量（消除 5 个 lambda_capture 失败）
2. 布尔值是小写 `true`/`false`，不是 `True`/`False`（消除 1 个失败）

**预期效果**：再消除 6 个编译失败，CSR 再提升 ~3.7pp。

### 能力天花板

11 个测试失败（编译通过但逻辑错误）是模型算法推理能力的边界，Skills 无法直接改善。如 `sort_array` 的复杂排序规则、`prod_signs` 的符号计算等。

---

## 三轮演进数据

| 轮次 | 模型 | Skills 策略 | CSR | pass@1 | 编译失败数 | 编译失败主因 | 主因占比 |
|------|------|-------------|-----|--------|-----------|-------------|---------|
| R1 | DeepSeek V4 | 15 条静态规则 | 13.41% | 5.49% | 142 | 括号缺失 | 48% |
| R2 | GLM-5.1 | 6 规则 + 旧 Skills 动态注入 | 67.68% | 57.93% | 53 | 缺标准库导入 | 30.4% |
| R3 | GLM-5.1 | P0 规则 + optimize-636 双源 Skills | **71.95%** | **65.24%** | 46 | 缺标准库导入 | **52.2%** |

**趋势解读**：
- CSR 从 13.41% → 67.68% → 71.95%，累计提升 58.54pp
- pass@1 从 5.49% → 57.93% → 65.24%，累计提升 59.75pp
- 缺 import 占比从 30.4% → 52.2%**上升**，不是因为问题恶化，而是因为其他错误（括号缺失、True vs true）被 P0 规则压缩后，import 成了最后的主要堡垒
- Rune 转换问题在 R2 占 13%，在 R3 的 P0 规则中被规则9（"DO NOT write Int64(r)"）覆盖，占比大幅下降

---

## R3 编译失败 46 个 task 逐类分析

### 按错误类型分类

| 失败类型 | 数量 | 占比 | 根因判断 | Skills 可改善？ |
|----------|------|------|----------|---------------|
| ArrayList/HashMap/HashSet 缺 import | 17 | 37.0% | 结构性矛盾（详见下文） | 不能单纯靠 prompt |
| lambda 捕获 var | 5 | 10.9% | Skills 指导不够 | **可以**，补一条规则 |
| body 缺失/截断 | 4 | 8.7% | API/模型问题 | 部分（增大 max_tokens） |
| type_mismatch | 4 | 8.7% | 模型+Skills 混合 | 部分 |
| Unicode API 缺 import | 3 | 6.5% | 同 ArrayList | 同 ArrayList |
| syntax_expected（Float64 字面量等） | 3 | 6.5% | 模型语法错误 | 较难 |
| parse/sort/math 缺 import | 4 | 8.7% | 同 ArrayList | 同 ArrayList |
| True vs true | 1 | 2.2% | Skills 指导不够 | **可以**，一句话 |
| Option coalescing 误用 | 1 | 2.2% | 模型类型理解 | 较难 |
| API 名称错误（subString） | 1 | 2.2% | Skills 指导不够 | **可以** |
| stdx 不可用（Md5Digest） | 1 | 2.2% | 环境限制 | 不可改善 |
| 其他（trailing closure 等） | 2 | 4.3% | 模型语法 | 较难 |

### 汇总：缺 import = 24/46 (52.2%)

这 24 个 task 的 import 需求分布：

| 缺少的 import | 涉及 task 数 |
|---------------|-------------|
| `import std.collection.*` | 18 |
| `import std.sort.*` | 4 |
| `import std.unicode.*` | 3 |
| `import std.convert.*` | 2 |
| `import std.math.*` | 1 |

---

## 结构性矛盾的详细解释

### 问题机制

1. 盲生成 prompt 格式为 `func name(params): ReturnType // doc`，模型被要求补完 `{ 函数体 }`
2. `clean_completion()` 会剥离函数签名、确保以 `{` 开头 `}` 结尾
3. Cangjie 的 `import` 语句必须在**函数外部、文件顶部**声明（类似 Java/Kotlin）
4. P0 规则第7条明确禁止"函数体内 import"
5. 因此：模型**无法在函数体中合法地添加 import**——即使它知道需要 import

### 实证

17 个 ArrayList 失败的 task 中，模型**全部正确使用了 `ArrayList<T>` 语法**（如 `var result = ArrayList<String>()`），说明模型完全知道 Cangjie 的动态列表 API。但**100% 没有 `import std.collection.*`**。

这不是"模型不懂 import"，而是"模型只能生成函数体，而 import 必须在函数外"。

---

## R3 测试失败 11 个 task 分析

| task_id | entry_point | 题目特点 | 失败原因 |
|---------|------------|---------|---------|
| 103 | rounded_avg | enum 类型匹配 | 题意理解偏差 |
| 105 | by_length | 排序+数字转英文 | 排序规则逻辑错误 |
| 108 | count_nums | 数组统计 | 统计逻辑偏差 |
| 115 | max_fill | 二维数组+容量计算 | 计算逻辑偏差 |
| 116 | sort_array | 条件排序 | 排序规则理解错误 |
| 122 | add_elements | 条件求和 | 条件逻辑偏差 |
| 128 | prod_signs | 符号计算+Option | 符号逻辑+Option 处理 |
| 140 | fix_spaces | 空格替换规则 | 替换规则理解偏差 |
| 142 | sum_squares | 条件平方求和 | 条件理解偏差 |
| 160 | do_algebra | 运算符+数值 | 运算符映射逻辑错误 |
| 88 | sort_array | 条件排序 | 排序规则理解错误 |

**共同特征**：这些 task 的题意都包含**非直觉的条件/规则**（如"按某条件排序"、"数字转英文单词"），模型实现了看似合理但不符合精确题意的逻辑。这是模型推理能力的边界，Skills 无法直接改善。

---

## 模型做得好的 task 模式

107 个完全通过的 task 按类型分布：

| 题目类型 | 通过数 | 特点 |
|----------|--------|------|
| 纯数值 + 基础 Array | 27 | Int64/Float64 运算 + 固定长度 Array |
| 纯数值 | 23 | 无需任何外部 import 的数学运算 |
| String + Bool | 12 | 字符串基础操作 |
| 数值 + String | 11 | 混合运算 |
| 数值 + Array + Bool | 8 | 含条件判断的数组操作 |
| String + Array | 7 | 字符串数组处理 |
| 其他 | 20 | 混合类型 |

**规律**：凡是**不需要任何 std import** 的 task，模型几乎全部做对了。模型的核心算法能力很强，瓶颈只在 import 和少数语言特性。

---

## 改进建议详细说明

### 建议 A：自动 import 注入机制（最高优先级）

**实现方式**：在 `generate_samples_cj_v2.py` 的 `clean_completion()` 之后新增 `inject_imports()` 函数：

```python
IMPORT_MAP = {
    "ArrayList": "import std.collection.*",
    "HashMap": "import std.collection.*",
    "HashSet": "import std.collection.*",
    "sort(": "import std.sort.*",
    "isUpperCase": "import std.unicode.*",
    "isLowerCase": "import std.unicode.*",
    "isNumber": "import std.unicode.*",
    "Int64.parse": "import std.convert.*",
    "Float64.parse": "import std.convert.*",
    "tryParse": "import std.convert.*",
    "sqrt(": "import std.math.*",
    "pow(": "import std.math.*",
}

def inject_imports(completion: str) -> str:
    imports = set()
    for identifier, import_stmt in IMPORT_MAP.items():
        if identifier in completion:
            imports.add(import_stmt)
    if not imports:
        return completion
    import_block = "\n".join(sorted(imports)) + "\n"
    # 在 completion 的 { 开头之前插入 import
    # completion 格式: {\n ...body... \n}
    # 改为: import lines\n func body {\n ...body... \n}
    body = completion.lstrip("{\n")
    return import_block + "{\n" + body
```

**注意**：注入的 import 行需要在最终代码组装时（prompt + completion 拼接）出现在函数签名之前。需要确认 `compile_check.py` 和 `test_execution.py` 的代码组装逻辑是否允许 completion 中包含 import 行。

### 建议 B：补充两条 P0 规则

在 SYSTEM_PROMPT_BASE 末尾增加：

```
29. Lambda/闭包不能捕获 var 变量。若需修改外部数据，用函数参数传递，或
    先 let copy = var_value 再在闭包中使用 copy。
    不要写 { var counter = 0; arr.map({ item => counter += 1 }) }。
30. Cangjie 布尔值是小写 true / false，不是 Python 的 True / False。
    不要写 if (True) 或 return True。
```

### 建议 C：增大 max_tokens（可选）

当前 `max_tokens=2048`，4 个 body_missing 中有截断导致的失败。尝试 `max_tokens=4096`。

### 建议 D：改变 prompt 格式（探索性，风险较高）

允许模型生成 "import + 函数体" 而非仅函数体，需要修改 `clean_completion()` 和代码组装逻辑。风险在于模型输出格式不稳定。

---

## 预期效果汇总

| 改进措施 | 消除编译失败数 | CSR 预估 | pass@1 预估 |
|----------|-------------|---------|-----------|
| 仅 P0 规则（已实施） | — | 71.95% | 65.24% |
| + 自动 import 注入 | +24 | ~86.6% | ~80%+ |
| + Lambda/True 规则补充 | +6 | ~90%+ | ~83%+ |
| + max_tokens 增大 | +2~3 | ~92% | ~84%+ |

**最终天花板**：11 个算法逻辑错误 task 是模型推理能力边界，短期无法突破。理论最高 pass@1 ≈ (107+24+6) / 164 ≈ **83.5%**。

---

*分析基于三轮测评数据：R1(0623_mem_cc.md DeepSeekV4)、R2(0623_mem_op.md GLM-5.1+旧Skills)、R3(本轮 optimize-636 Skills)*
