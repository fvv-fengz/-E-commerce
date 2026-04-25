将拼多多店铺账号包 JSON 放在本目录。

前端控制台会自动读取 `doc/pdd-account-packs/*.json` 作为“拼多多账号包”候选项。

建议：
- 一个 JSON 对应一套店铺账号包（结构与 `pdd-accounts.json` 相同，含 `profiles`）
- 可选填写顶层字段 `label`，前端下拉会优先显示该名称
- 文件名体现用途，例如 `pdd-accounts.json`、`pdd-test-users.json`
- 优先维护本目录；旧路径 `doc/pdd-accounts.json` 仅做兼容
