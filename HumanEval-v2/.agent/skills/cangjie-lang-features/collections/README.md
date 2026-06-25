# 仓颉集合数据类型

请按需查询当前目录下的文档：

- [Array](./array/README.md)：定长数组
- [ArrayList](./arraylist/README.md)：可变长列表
- [HashMap](./hashmap/README.md)：哈希表/键值映射 
- [HashSet](./hashset/README.md)：集合

通用数量规则：仓颉集合和数组的元素数量使用 `.size` 属性，不是 `.size()` 方法；没有 `.length` / `.len()` / 全局 `len(...)`。例如 `Array<Float64>`、`ArrayList<T>`、`HashMap<K, V>`、`HashSet<T>` 都写 `xs.size`。
