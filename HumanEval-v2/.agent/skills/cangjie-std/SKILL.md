---
name: cangjie-std
description: "仓颉标准库 std API 速查与示例导航。用于查询 std.core、std.collection、std.sort、std.unicode、std.convert、std.crypto.digest、std.sync、std.fs、std.io、std.net、std.process、std.regex、std.time、std.math、std.unittest、std.stdio、std.args、std.env 等标准库类型、函数、接口、构造方式和常见用法；也用于修复 HumanEval/算法题仓颉编译错误中的 Array.append/add、ArrayList.append、Array.sort、Repeat/repeat、String.toLower/toUpper、String.fromRune/String(Rune)、UInt8==Rune、parse()??、StringBuilder.add 等 API 误用。不用于语言语法、扩展库或鸿蒙应用问题。"
---

# 仓颉标准库导航

## 使用流程

1. 先判断问题是否是标准库 API、构造方式、导入、示例或常见陷阱。
2. 回答具体 API 前，读取对应文档；不要只根据本目录页回答。
3. 如果问题同时涉及语法规则和标准库 API，先用 `cangjie-lang-features` 确认语言规则，再用本 skill 查询 API。
4. 如果问题涉及 stdx 包（JSON、HTTP、WebSocket、TLS、加密、日志、压缩、Base64/Hex/URL 等），转用 `cangjie-stdx`。
5. 网络问题先读 [std.net](./net/README.md)，再按 TCP/UDP/UDS 读取细分文档。
6. 类型转换与格式化问题直接读 `convert/parsable.md` 或 `convert/formattable.md`，不要把目录路径当作完整文档。

## 工具链命令护栏

- 标准库示例编译/测试时使用 `cjc` 或 `cjpm`，不要使用不存在的 `cj` 命令。
- 单文件测试用 `cjc code.cj test.cj --test -o test_binary`；cjpm 项目用 `cjpm test`。若报 `command not found: cj`，改为验证 `command -v cjc` 和 `command -v cjpm`。

## HumanEval/算法题 API 检查

- 复发错误先做 P0 自查：不得出现 `Array().append`、`arr.append(`、`list.append(`、`arr.sort()`、`let sorted = sort(...)`、`Repeat:`、`String.toLower()`、`String.fromRune(...)`、`String(rune)`、`parse(...) ??`、`StringBuilder.add(...)`；按下列规则替换后再生成代码。
- 动态构建序列用 `ArrayList<T>` 和 `.add()`，最后按需要 `.toArray()`；`Array<T>` 是固定长度数组，不支持 `.add()` / `.append()`，`ArrayList<T>` 也用 `.add()` 而不是 `.append()`。
- 长度/元素数量统一用 `.size` 属性，不是 `.size()` 方法：`Array<T>`（包括 `Array<Float64>`）、`ArrayList<T>`、`HashMap`、`HashSet`、`String` 都没有 `.length` / `.len()` / 全局 `len(...)`；`String.size` 是 UTF-8 字节数，按字符处理用 `toRuneArray()` 或 `runes()`。
- 使用 `ArrayList`、`HashMap`、`HashSet` 时显式写 `import std.collection.*`。
- 固定长度数组初始化命名参数是小写 `repeat:`，例如 `Array<Int64>(n, repeat: 0)`；不要写 `Repeat:` / `item:`。
- `HashMap` 插入/更新用 `.add(k, v)` 或 `map[k] = v`；`HashSet` 添加用 `.add(v)`，没有 `.put()`。
- `ArrayList.get(i)` 返回 `Option<T>`；确定下标有效时用 `list[i]` 取值，修改用 `list[i] = v`，删除用 `list.remove(at: i)`，不是 `set()` / `removeAt()`。
- Rune 分类/转换需要 `import std.unicode.*`；方法是 `isLowerCase()`、`isUpperCase()`、`isNumber()`、`toLowerCase()`、`toUpperCase()`，不是 `isLower()`、`isUpper()`、`isDigit()`、`toLower()`、`toUpper()`。
- `String` 按下标或 `for (b in s)` 处理的是 `UInt8` 字节；`UInt8.toString()` 输出数字字符串。ASCII 字节比较用 `b'a'` 这类字节字面量；按字符处理时用 `s.runes()` 或 `s.toRuneArray()`。
- 普通 `String` 没有 `.toLower()` / `.toUpper()`；ASCII 大小写用 `toAsciiLower()` / `toAsciiUpper()`，单个 `Rune` 用 `toLowerCase()` / `toUpperCase()`。
- `String.fromRune()`、`String.fromRuneArray()`、`String.substring()`、`String(rune)` 不存在；单个 Rune 转字符串用 `String([r])`，Rune 数组用 `String(runes)`，`ArrayList<Rune>` 先 `.toArray()` 再写 `String(runeList.toArray())`，字节切片用 `s[start..end]`。
- 数字转字符串用 `"${n}"` 或 `n.toString()`；不要写 `String(n)`。
- `Int64.parse()`、`Float64.parse()` 需要 `import std.convert.*`，返回普通数值，失败抛异常；安全解析 + 默认值用 `tryParse() ?? fallback`。不要写 `parse() ?? fallback`，也不要对 `parse()` 结果调用 `.get()` 或 `.getOrThrow()`。
- 排序优先 `import std.sort.*` 后使用全局 `sort(data)`；排序原地修改并返回 `Unit`，不要写 `let sorted = arr.sort()`。`by` 比较器返回 `Ordering`，若想返回 Bool 请用 `lessThan` 参数。
- `Int64.MAX`、`Float64.MAX` 这类常量不可依赖；算法题可用明确字面量或从输入初始化边界值。
- 数学函数在 `std.math.*`；整数幂自己写循环辅助函数（如 `_he_pow(base, exp)`），浮点幂用 `pow()` 并注意近似误差回查。
- `StringBuilder` 追加内容用 `append()`，不是 `add()`。
- `Byte`/`UInt8` 转整数用数值转换（如 `Int64(b)`），不要生造 `toInt32()`。
- MD5/SHA/HMAC 等具体摘要算法在 `stdx.crypto.digest`；依赖可配置时用库实现，不要手写密码学算法。HumanEval 单文件不能配置 stdx 时再选择纯仓颉实现或补齐 `--import-path` / `cjpm.toml`。

## 标准库路由

- 核心包、自动导入、基本类型 API、StringBuilder、Duration、print/println/spawn/sleep/min/max、异常体系：读 [std.core](./core/README.md)。
- ArrayList、HashMap、HashSet、TreeMap、TreeSet、LinkedList、ArrayDeque、ArrayQueue、ArrayStack、filter/map/fold/reduce、collectArray/collectHashMap：读 [std.collection](./collection/README.md)。
- ConcurrentHashMap、ArrayBlockingQueue、LinkedBlockingQueue、ConcurrentLinkedQueue：读 [std.collection.concurrent](./collection_concurrent/README.md)。
- Atomic、Mutex、Condition、synchronized、Timer、Barrier、Semaphore、SyncCounter：读 [std.sync](./sync/README.md)。
- DateTime、MonoTime、Duration、Month、DayOfWeek、时间格式化与解析：读 [std.time](./time/README.md)。
- abs/sqrt/pow/log、三角函数、ceil/floor/round、gcd/lcm、NaN/Inf 检查：读 [std.math](./math/README.md)。
- BigInt、Decimal、任意精度数值、parse/divAndMod/modPow/bitLen：读 [std.math.numeric](./math_numeric/README.md)。
- Regex、matches/find/findAll、replace/replaceAll、split、捕获组：读 [std.regex](./regex/README.md)。
- File、Directory、Path、FileInfo、读写追加、遍历、软硬链接：读 [std.fs](./fs/README.md)。
- InputStream/OutputStream、ByteBuffer、Buffered 流、StringReader/StringWriter、copy/readToEnd/readString：读 [std.io](./io/README.md)。
- Socket 总览、地址类型、Socket 选项、异常：读 [std.net](./net/README.md)；TCP 读 [net/TCP](./net/TCP.md)，UDP 读 [net/UDP](./net/UDP.md)，Unix Domain Socket 读 [net/UDS](./net/UDS.md)。
- launch、execute、executeWithOutput、SubProcess、标准流重定向、进程等待与终止：读 [std.process](./process/README.md)。
- 环境变量、进程信息、工作目录、标准流、exit/atExit：读 [std.env](./env/README.md)。
- Array/ArrayList/List 排序、自定义比较器、稳定排序、降序排序：读 [std.sort](./sort/README.md)。
- Random、nextInt/nextFloat/nextBool、范围随机数、正态分布、种子：读 [std.random](./random/README.md)。
- BigEndianOrder、LittleEndianOrder、网络字节序、二进制读写：读 [std.binary](./binary/README.md)。
- CheckedOp、SaturatingOp、ThrowingOp、WrappingOp、CarryingOp：读 [std.overflow](./overflow/README.md)。
- Rune 分类、大小写转换、语言特定转换：读 [std.unicode](./unicode/README.md)。
- @Derive、ToString、Hashable、Equatable、Comparable、字段控制：读 [std.deriving](./deriving/README.md)。
- TypeInfo、ClassTypeInfo、StructTypeInfo、ConstructorInfo、InstanceFunctionInfo：读 [std.reflect](./reflect/README.md)。
- Digest、digest()、摘要接口、BlockCipher 基础接口：读 [std.crypto.digest](./crypto_digest/README.md)。
- 字符串解析、Parsable、整数/浮点/布尔解析、进制转换：读 [std.convert parsable](./convert/parsable.md)。
- 数值格式化、Formattable、宽度、对齐、精度、进制格式：读 [std.convert formattable](./convert/formattable.md)。
- @Test、@TestCase、@Assert、@Expect、@PowerAssert、生命周期、参数化、Bench、Mock/Spy：读 [std.unittest](./unittest/README.md)。
- print/println/eprint/eprintln、readln/read、ConsoleReader/ConsoleWriter：读 [std.stdio](./stdio/README.md)。
- main(args)、std.argopt、短选项、长选项、组合选项、ParsedArguments：读 [std.args](./args/README.md)。
- WeakRef、CleanupPolicy、弱引用缓存：读 [std.ref](./ref/README.md)。

## 边界提醒

- 语言规则、语法、类型系统、Option/match 语义、CFFI、cjpm 配置属于 `cangjie-lang-features`。
- stdx JSON、HTTP/HTTPS、WebSocket、TLS、证书、加密、Base64/Hex/URL、日志、压缩、序列化属于 `cangjie-stdx`。
- 鸿蒙项目构建、UI、ArkTS 互操作和应用诊断属于 `cangjie-hmos-*` 或相关互操作 skill。
