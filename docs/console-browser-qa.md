# 中文控制台浏览器验收

此检查只使用临时回环 HTTP 服务、合成身份/凭证和模拟任务；不连接真实设备或学校账号。测试脚本、页面/API 和 CI 必须来自同一个完整集成候选。

## 独立 Linux CI job

`.github/workflows/checks.yml` 的 `console-browser-qa` job 使用 Ubuntu / Python 3.11，并与原有 Windows/Linux 单元检查独立运行。GitHub 权限保持 `contents: read`，checkout 不保存凭证，没有新增部署或账号权限。

- `browser-test` extra 固定 `playwright==1.62.0`，直接与传递依赖由 `uv.lock` 冻结。
- 正常 core/server/agent 安装无需此 extra，也不引入 Playwright、pyee 或 greenlet。
- 常规矩阵显式安装 server/agent/dev；浏览器 job 另装 browser-test。
- 用官方 Playwright 包的安装命令下载 Chromium 和所需系统依赖。
- 从 Ubuntu 官方软件源安装 `fonts-noto-cjk`，确保中文截图显示实际字形；不使用未知下载脚本。

```sh
uv sync --extra server --extra agent --extra dev --extra browser-test --frozen
uv run --no-sync python -m playwright install --with-deps chromium
sudo apt-get install --no-install-recommends -y fonts-noto-cjk
uv run --no-sync python scripts/check_console_browser.py --output-dir qa/console-browser
```

系统安装命令面向临时 CI runner；不代表授权修改用户电脑或生产主机。本地无法启动浏览器时保留具体限制，不关闭浏览器/系统保护，也不绕过隔离 IPC 或网络边界。

## 证据与保密

job 开启 `HAPPYRUN_EMIT_QA_SCREENSHOTS=1`，脚本仅将受控 PNG 输出为固定 BEGIN/END 标记之间的 base64，供无法下载二进制 artifact 的审核端查看。标记包含文件名和 SHA256；每行120字符、每图上限700KB。只对本轮纯合成数据开启，不在真实账号/路线/凭证环境复用此日志导出。

上传 artifact `console-browser-qa-${{ github.sha }}`，保留7天，白名单为：

- `desktop-1440.png`
- `mobile-390.png`
- `failure-*.png`
- `results.json`

不上传数据库、journal、原始请求、浏览器存储、trace、私有配置或完整环境。失败时也收集受控截图/报告，CI 仍保持失败；缺少证据文件不会被当作通过。PR事件的 `github.sha` 可能是临时 merge SHA，最终候选验收应核对实际测试提交，不能把旧 artifact 归给新提交。

## 状态解释

依赖安装、锁校验、lint、构建和源测试通过，不等于 Chromium 已打开页面。只有实际 browser job 的脚本退出0、报告通过且桌面/手机截图经检查后，才记录浏览器验收结果。

本次准备环境的 Chromium 受 IPC 限制，云浏览器也不能访问隔离 loopback；没有尝试绕过。真实浏览器脚本仍待正常 GitHub runner 执行，不宣称浏览器通过，更不推断真实设备/学校记录验证。
