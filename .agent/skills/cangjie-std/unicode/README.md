# 仓颉语言 Unicode 字符处理 Skill

## 1. Rune 字符分类

- 来自 `std.unicode.*`
- `UnicodeRuneExtension` 扩展接口，为 `Rune` 类型添加 Unicode 分类方法

| 方法 | 说明 |
|------|------|
| `isLetter(): Bool` | 是否为字母（包括中文等） |
| `isNumber(): Bool` | 是否为数字 |
| `isLowerCase(): Bool` | 是否为小写字母 |
| `isUpperCase(): Bool` | 是否为大写字母 |
| `isTitleCase(): Bool` | 是否为标题大小写 |
| `isWhiteSpace(): Bool` | 是否为空白字符 |

---

## 2. Rune 大小写转换

| 方法 | 说明 |
|------|------|
| `toLowerCase(): Rune` | 转小写 |
| `toUpperCase(): Rune` | 转大写 |
| `toTitleCase(): Rune` | 转标题大小写 |

```cangjie
package test_proj
import std.unicode.*

main() {
    let ch: Rune = r"A"
    println(ch.isLetter())        // true
    println(ch.isUpperCase())     // true
    println(ch.toLowerCase())     // a

    let digit: Rune = r"5"
    println(digit.isNumber())     // true

    let space: Rune = r" "
    println(space.isWhiteSpace()) // true
}
```

---

## 3. String 大小写与空白处理

HumanEval/普通算法题中不要写 `str.toLower()` / `str.toUpper()`；普通 `String` 的 ASCII 大小写方法是 `toAsciiLower()` / `toAsciiUpper()`。需要逐字符 Unicode 处理时，遍历 `str.runes()` 或 `str.toRuneArray()`，对每个 `Rune` 调用 `toLowerCase()` / `toUpperCase()` 后再用 `String(runes)` 组回字符串。

| 方法 | 说明 |
|------|------|
| `toAsciiLower(): String` | ASCII 字母整体转小写 |
| `toAsciiUpper(): String` | ASCII 字母整体转大写 |
| `trimAscii(): String` | 去除首尾 ASCII 空白 |

```cangjie
package test_proj
import std.unicode.*

main() {
    let text = "Hello, 仓颉!"
    println(text.toAsciiLower())  // hello, 仓颉!
    println(text.toAsciiUpper())  // HELLO, 仓颉!
    println("  hello  ".trimAscii()) // hello
}
```

---

## 4. 语言特定转换

- `CasingOption` 枚举，用于语言相关的大小写转换

| 枚举值 | 语言 |
|--------|------|
| `TR` | 土耳其语 |
| `AZ` | 阿塞拜疆语 |
| `LT` | 立陶宛语 |
| `Other` | 默认规则 |

- Rune 调用方式：`ch.toLowerCase(CasingOption.TR)`
- 字符串需要语言特定大小写时，优先逐 `Rune` 处理并明确测试；HumanEval 中通常只需要 ASCII 的 `toAsciiLower()` / `toAsciiUpper()`。
- 土耳其语中 `I` → `ı`（无点小写 i），与默认规则不同

---

## 5. 关键规则速查

1. `isLetter()` 覆盖所有 Unicode 字母类别（含 CJK 字符），仅 Rune 可用
2. Rune 使用 `toLowerCase()` / `toUpperCase()`；普通 String 使用 `toAsciiLower()` / `toAsciiUpper()`，不要写 `toLower()` / `toUpper()`
3. 需要语言特定转换时使用 `CasingOption` 参数（如土耳其语 I/İ 问题）
4. 空白裁剪优先用核心 String 的 `trimAscii()` / `trimAsciiStart()` / `trimAsciiEnd()`
5. 字符串级 Unicode 逻辑需要先明确 SDK 是否提供对应扩展；不确定时按 Rune 数组处理
6. Rune 字面量使用 `r"字符"` 语法
7. 不要使用常见语言惯性写法 `isDigit()`、`isLower()`、`isUpper()`、`toLower()`、`toUpper()` 处理 Rune；对应写法是 `isNumber()`、`isLowerCase()`、`isUpperCase()`、`toLowerCase()`、`toUpperCase()`
