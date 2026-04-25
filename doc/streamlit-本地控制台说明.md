# Streamlit 本地控制台说明

## 一、首次安装（客户电脑）

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_local.ps1
```

可选：注册每天 09:00 自动启动

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_local.ps1 -RegisterDailyTask -TaskTime "09:00"
```

## 二、启动方式

- 双击桌面快捷方式：`电商采集控制台`
- 或手动运行：`scripts\start_streamlit_console.bat`

该脚本现已支持**一键启动入口**（推荐）：
- 自动检查并拉起绑定浏览器（CDP Chrome，默认 `127.0.0.1:9222`）
- 自动启动 Streamlit 控制台
- 自动打开控制台页面：<http://127.0.0.1:8502>

## 三、界面能力

- 选择内置配置（拼多多 / 抖店）
- 上传新的配置 JSON（即时使用）
- 选择抖音用户配置文件（`app/account_configs/*.json`），自动注入 `--global-accounts`
- 选择运行模块（page ids）
- 设置 CDP 地址、输出目录、Excel 输出
- 文件名备注（会拼到输出目录与输出文件名，便于区分批次）
- 可选覆盖 `accountCredentialCsv`
- 配置里的 `dynamic_params` 仍生效：按各项 `default`（及预设里的 `dynamic_params_override`）自动拼 CLI，页面不再展示动态参数表单
- 实时查看采集与后处理日志

### 动态参数配置格式（`dynamic_params`，仅默认值生效）

控制台不再渲染表单；改默认值请编辑 `builtin_configs.json`（或预设覆盖）。每个参数项示例：

```json
{
  "id": "interaction_timeout_ms",
  "label": "交互超时(ms)",
  "type": "number",
  "default": 30000,
  "help": "显示在表单的提示",
  "cli": {
    "target": "trial",
    "flag": "--interaction-timeout-ms"
  }
}
```

- `type` 支持：`text` / `number` / `bool` / `select` / `multiselect`
- `cli.target`：`trial`（给 `run_template_trial.py`）或 `postprocess`
- `cli.mode`（仅 bool 可选）：
  - `store_true`：勾选才追加 `flag`
  - `store_false`：不勾选才追加 `flag`

## 四、异常提示

若出现影响使用的报错，界面会提示：

> 出现影响使用的错误，请联系管理员维护。

