# 单进程服务器启动与持久化

部署文件是供审核和本地验证的候选配置，不授权修改生产服务器、DNS、账户或防火墙。容器构建/运行是否已经通过，请查看 [交付验证记录](delivery-validation.md)。

## 配置

- `HAPPYRUN_ADMIN_TOKEN`：管理 token。
- `HAPPYRUN_AGENT_TOKENS`：JSON object，canonical UUID 字符串映射到各代理的 token。不同代理及 ADMIN 的 token 必须互不相同。
- CLI `server --database PATH --host HOST --port PORT`；默认主机回环、端口 8080。数据库父目录由 CLI 创建；数据库由服务初始化，拒绝比实现更新的 schema。
- 无凭证健康检查：`GET /api/v1/health`，返回 `{"status":"ok","protocol_version":1}`。
- 无凭证就绪检查：`GET /api/v1/ready`，检查调度 ticker 活性/健康与 SQLite 轻读；成功返回 `{"status":"ready","protocol_version":1}`，失败返回安全 503。容器 HEALTHCHECK 使用此端点，`/health` 仅为进程存活检查。
- 初版只允许一个服务进程和一个调度器。不要增加 Uvicorn worker、开启 reload、复制服务或多个容器共用 SQLite。

不把 token 放在 CLI 参数或 URL。不要分享 `docker inspect`、展开后的 Compose config、shell 环境或请求头，里面可能有凭证。

## Docker Compose（Linux）

需要已安装且能访问的 Docker Engine 与 Compose v2；本项目不会替用户安装守护进程或修改组权限。仓库根目录执行：

```sh
mkdir -p "$HOME/.config/swu-happyrun"
cp deploy/.env.example "$HOME/.config/swu-happyrun/server.env"
```

在私有编辑器填写两个环境变量；用独立随机 token 和自选代理 UUID。不要把值粘贴进共享终端或 Git。环境文件只在本机保存，权限由用户按其现有安全策略管理。

```sh
docker compose --env-file "$HOME/.config/swu-happyrun/server.env" -f deploy/compose.yaml config --quiet
docker compose --env-file "$HOME/.config/swu-happyrun/server.env" -f deploy/compose.yaml build
docker compose --env-file "$HOME/.config/swu-happyrun/server.env" -f deploy/compose.yaml up -d
curl --fail http://127.0.0.1:8080/api/v1/health
curl --fail http://127.0.0.1:8080/api/v1/ready
docker compose --env-file "$HOME/.config/swu-happyrun/server.env" -f deploy/compose.yaml ps
```

映像以 UID/GID 10001 运行。新命名卷从镜像 `/data` 初始化，持久数据库为 `/data/happyrun.sqlite3`；根文件系统只读。若改为现有卷/绑定目录，需先独立确认该用户可写，不要以 root 运行绕过权限错误。

主机仅发布 `127.0.0.1:8080`。容器内部监听 `0.0.0.0` 是 Docker 转发所需，不等于服务对公网开放。远程接入须由操作者另行配置可信 HTTPS 入口及证书；不要关闭 TLS 验证，不要把 ADB/MuMu 端口暴露给服务端。此交付不修改现有代理或 DNS。

```sh
docker compose --env-file "$HOME/.config/swu-happyrun/server.env" -f deploy/compose.yaml restart server
docker compose --env-file "$HOME/.config/swu-happyrun/server.env" -f deploy/compose.yaml down
```

`down` 保留命名卷；不要加 `--volumes` 或使用 prune 删除恢复数据。重启后需查询之前创建的同一 job ID，健康返回不证明数据持久化。

## 直接运行（Windows 或 Linux）

按安装说明安装 server extra；在当前进程环境通过已有私有配置方式设置上述变量后执行：

```sh
uv run --no-sync python -m swu_happyrun server --database /absolute/private/path/server.sqlite3 --host 127.0.0.1 --port 8080
```

Windows 将 database 改为自己选定的绝对路径，例如 `$env:LOCALAPPDATA\swu-happyrun\server.sqlite3`，并用双引号包住整个路径。不要照抄 Linux 绝对路径。

## 升级、备份与故障

先停止本轮服务器并确认代理状态，保留 SQLite 完整文件集和代理 journal 的私有备份，再更新候选版本。活动 WAL 数据库不能只复制主文件；使用 SQLite 一致性备份或停服后复制文件集。恢复必须验证 schema 与任务状态，不能盲目回滚后重启可能已经运行的任务。

S2 schema 3 迁移对旧 S0 device 任务或缺失必需 session 的历史数据安全拒绝；尚未领取的 simulation 可按实现迁移。迁移失败时保留原始私有备份和错误码，交给维护者评估，不删历史任务或手改字段绕过。

数据库 busy 返回可重试 503 时检查是否误开多个进程、卷是否本地可写。不要删除数据库解决锁。401 检查私有 token 配置；403 检查角色；404 也可能是代理无权查看；409 先读取最新状态与 revision。详情见 [故障清单](fake-e2e.md)。
