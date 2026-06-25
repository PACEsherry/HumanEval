---
name: cangjie-lang-features
description: "仓颉语言核心语法与语言特性导航。用于回答或实现语法、基本类型、表达式、函数、class/struct/interface/enum、泛型与 where 约束、类型系统、扩展、Option、match 模式匹配、错误处理、spawn、宏、反射注解、package/cjpm、CFFI/foreign/unsafe 等语言层问题；也用于修复 HumanEval/算法题仓颉编译错误中的 import 顺序、Rune/String/UInt8 字面量、Repeat/repeat 命名参数、match 关键字变量、Float64 比较、~ 按位取反等语言层坑。不用于库 API 或鸿蒙应用问题；若存在更细的仓颉专题 Skill，优先使用更细 Skill。"
---

# 仓颉语言特性导航

## 使用流程

1. 先判断问题属于语言层、标准库层还是 stdx 扩展库层。
2. 回答具体语法、规则、示例或排错前，读取下方对应 README；不要只根据本目录页回答。
3. 多主题问题只读取相关专题；需要精确 API 或版本细节时，再读取最小必要的相邻专题。
4. 遇到标准库 API、集合 API、IO、网络、进程、单元测试等问题，转用 `cangjie-std`。
5. 遇到 stdx 的 JSON、HTTP、WebSocket、TLS、加密、日志、压缩、编码等问题，转用 `cangjie-stdx`。
6. 如果本 skill 与更细的 `cangjie-option`、`cangjie-generic`、`cangjie-concurrency` 等专题 Skill 同时可用，优先使用更细 Skill；本 skill 作为总路由与兜底。

## 工具链命令护栏

- 仓颉编译器命令是 `cjc`，项目管理命令是 `cjpm`；不要尝试运行不存在的 `cj` 命令。
- 加载 SDK 环境后，用 `command -v cjc && cjc -v` 验证编译器，用 `command -v cjpm && cjpm --version` 验证项目工具；若缺失，重新 source `envsetup.sh`，不要改试 `cj`。
- 单文件编译/测试用 `cjc hello.cj -o hello`、`cjc code.cj test.cj --test -o test_binary`；标准项目构建/测试用 `cjpm build`、`cjpm test`。

## HumanEval/算法题首轮检查

- 复发错误先做 P0 自查：不得出现函数体内 `import`、`Repeat:`、变量名 `match`、`UInt32('a')`、`Rune('a')`、`Int64(r)`、`UInt8(r'.')`、`if (floatVal > 0)`、`while (intVal)` 或裸 `~x`；按下列规则替换后再生成代码。
- 保持代码顺序为 `package`、`import`、声明/函数；不要把 `import` 写到函数或类型声明之后。
- `match` 的每个 `case` 必须有表达式；空兜底写 `case _ => ()`，不要写 `case _ => {}` 或空 `case _ =>`。
- Rune 不是数值类型；转整数用 `Int64(UInt32(r))`，Rune 字面量写 `r'a'` / `r"a"`。不要写 `Rune('a')`、`UInt32('a')`、`Int64(r)` 或 `UInt8(r'.')`；普通 `'a'` / `"a"` 是 `String` 字面量，字节常量用 `b'a'` 或 ASCII 数值如 `UInt8(46)`。
- Rune 没有 `.value`；Option 也没有 `.value`，用 `UInt32(r)` 或 `match`/`??` 显式解包。
- 字符串相等用 `==`；普通 `String` 没有 Java/Python 风格的 `.equals()`。
- 数组、集合、字符串的数量统一用 `.size` 属性，不是 `.size()` 方法：`Array<T>`（包括 `Array<Float64>`）、`VArray<T, $N>`、`ArrayList<T>`、`HashMap`、`HashSet`、`String` 都没有 `.length` / `.len()` / 全局 `len(...)`；`String.size` 是 UTF-8 字节数，按字符计数先用 `s.toRuneArray().size` 或遍历 `s.runes()`。
- 为自定义 enum 实现 `==` 时使用接口扩展：`extend MyEnum <: Equatable<MyEnum> { public operator func ==(...) ... }`。
- `**` 不适合 Int64 整数幂；写循环辅助函数（如 `_he_pow(base, exp)`），或在明确需要浮点时用 `std.math.pow(Float64, Float64)`。
- 仓颉没有隐式数值类型提升；`Float64` 与字面量比较写 `0.0` / `1.0` 或显式转换，不要写 `if (f > 0)` 这类 `Float64` vs `Int64` 比较。
- 在 Cangjie 1.0.4 / HumanEval 场景中，优先用 `match` 或 `??` 解包 Option；不要假设 `Option.get()` / `getOrThrow()` 一定可用。
- 函数参数不可重新赋值；需要修改入参时先创建局部 `var` 副本。不要把 `operator`、`match` 等关键字直接用作变量名或参数名。
- 避免把返回类型写成 `Any` 后再和具体值 `==`；按测试期望返回具体类型。`Array<T>` 与 `(T, U)` 元组不能跨类型比较。
- 固定长度数组重复初始化用 `Array<T>(n, repeat: value)`，`repeat:` 必须小写；不要写 `Array(n, item: value)`、`Array(n, Repeat: value)`。
- `~x` 按位取反在部分 `UInt32` 表达式上不稳；算法题中可用 `UInt32(4294967295) - x` 表达按位取反。
- 以仓颉版测试签名和期望为准；不要照搬 Python 版返回类型或题意细节。

## 专题路由

- 基础语法、关键字、变量、作用域、if/while/match/main、项目入门：读 [basic_concepts](./basic_concepts/README.md)。
- 整数、浮点、Bool、Rune、String 字面量、Unit、Nothing、Tuple、Array/VArray、Range、运算符优先级：读 [basic_data_type](./basic_data_type/README.md)。
- for-in、Iterable/Iterator、Range 迭代、where 过滤、元组解构、自定义迭代器：读 [for](./for/README.md)。
- 函数、Lambda、闭包、默认/命名参数、重载、运算符重载、尾随 Lambda、管道运算符：读 [function](./function/README.md)。
- const 变量、const 表达式、const func、const init：读 [const](./const/README.md)。
- class、抽象类、继承、override/redef、init/~init、prop、访问修饰符、This 类型：读 [class](./class/README.md)。
- struct、值语义、mut 函数、成员修改限制：读 [struct](./struct/README.md)。
- interface、接口实现、接口继承、默认实现、sealed interface、接口属性、菱形继承：读 [interface](./interface/README.md)。
- enum、构造器、非穷举枚举、递归枚举、枚举成员、Equatable：读 [enum](./enum/README.md)。
- 泛型函数/类型、where 约束、泛型静态成员限制、泛型子类型关系：读 [generic](./generic/README.md)。
- 子类型、型变、is/as、数值转换、类型别名：读 [type_system](./type_system/README.md)。
- extend、直接扩展、接口扩展、泛型扩展、孤儿规则、导出与导入：读 [extend](./extend/README.md)。
- Option、`?T`、`Some`/`None`、`?.`、`??`、`getOrThrow()`、if-let、while-let：读 [option](./option/README.md)。
- match、模式守卫、穷举性、绑定模式、类型模式、枚举模式、可反驳性：读 [pattern_match](./pattern_match/README.md)。
- Error/Exception、throw、try/catch/finally、try-with-resources、CatchPattern、Option 错误处理：读 [error_handle](./error_handle/README.md)。
- spawn、M:N 线程模型、sleep、Future、Atomic、Mutex、Condition、synchronized、ThreadLocal、线程取消：读 [concurrency](./concurrency/README.md)。
- macro、Token/Tokens、quote、属性/非属性宏、std.ast、宏调试与项目组织：读 [macro](./macro/README.md)；宏包构建再读 [macro/build](./macro/build/README.md)。
- 反射、TypeInfo、自定义注解、整数溢出注解：读 [reflect_and_annotation](./reflect_and_annotation/README.md)。
- package、import/public import、main、顶层访问修饰符：读 [package](./package/README.md)。
- cjpm、cjpm.toml、workspace、build/run/test/bench、依赖、构建脚本、交叉编译：读 [project_management](./project_management/README.md)。
- CFFI、foreign、CFunc、inout、unsafe、CPointer、CString、LibC、C 回调仓颉：读 [cffi](./cffi/README.md)；编译链接再读 [cffi/build](./cffi/build/README.md)。

## 边界提醒

- `String`、`Array`、`ArrayList`、`HashMap`、`HashSet` 的完整 API 用法优先查 `cangjie-std`；本 skill 只覆盖语言层基础和必要导航。
- HTTP/HTTPS、JSON、WebSocket、TLS、Base64、证书和加密若属于 stdx 包，优先查 `cangjie-stdx`。
- 需要权威原始文档或本地摘要不足时，使用 `cangjie-original-docs` 兜底核对。
