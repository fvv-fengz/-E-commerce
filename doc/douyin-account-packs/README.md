将抖音店铺账号包 JSON 放在本目录。

前端控制台会自动读取 `doc/douyin-account-packs/*.json` 作为“抖音账号包”候选项。

建议：
- 一个 JSON 对应一套店铺账号包（结构含 `profiles.default` 数组）
- 可选填写顶层字段 `label`，前端下拉会优先显示该名称
- 文件名体现用途，例如 `v1_main.json`、`v1_test_customers.json`
