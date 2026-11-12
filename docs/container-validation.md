# 容器与 Python 代理交付验收

范围：现有 `/api/v1`、SQLite schema 3、单调度器、Docker Compose 与 Python fake
agent 的真实 HTTP 链路。不接生产、真实设备、学校账号或学校记录。

## 如何判断已经通过

独立 `container-smoke` Actions 在一次性官方 Ubuntu runner 执行现有
`deploy/Dockerfile` / `deploy/compose.yaml`，不是只检查 Compose 语法。
只有对应不可变提交的 job 成功且 `container-smoke-<SHA>/report.json` 中
`container_verified=true` 才能称该提交容器通过。构建失败、Docker 不可用、
端口占用或超时均失败，不自动装守护进程、修改组权限或提升权限。
本云没有 Docker，本地 HTTP/单测证据不得写成容器实测。
探针要求显式opt-in、[GitHub-hosted运行环境标志](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)、
默认Docker context和本地unix socket；拒绝远端Docker环境覆盖。

检查包括：

- 新建独占 Compose project 与命名卷，使用仅本轮存在的合成随机 token。
- 实际 build/up、health/ready、ADMIN/AGENT 分离和其他代理隐藏任务。
- 现有 Python agent CLI 的 `--backend fake --once` 经 TCP 完成合成路线；
  `completed` 且无学校记录 evidence，不得变成 `succeeded`。
- 真实 30 秒租约过期、重新领取时 fence 增长、旧租约拒绝。
- running 的取消仍为 cancelling；只有 stop-ack 才 cancelled，回执可重放。
- 下一分钟的日程生成一次；销毁容器但保留卷，再创建新容器后任务、日程、
  幂等记录与设备 fence 保留，日程不重复，旧租约/旧回执仍被拒绝。
- 实际 UID10001、只读根文件系统、drop ALL、非 privileged、
  no-new-privileges、仅 127.0.0.1:8080 映射及 SQLite integrity/schema。
- 两次容器日志只在内存检查 token 不泄漏；不上传日志、inspect、环境、
  配置、数据库或代理 journal。只上传固定字段的合成结果摘要，以及严格校验的本地image ID（sha256）/Docker服务版本。
  image ID是本地构建配置digest；镜像未推送registry，不虚构registry manifest digest。

清理只针对本轮随机 project 的容器、网络、卷，不执行全局 prune。
测试命名卷可删除，因为它只含本轮生成的合成资料；日常部署不应照抄该清理。
进程被强制杀死/runner取消时，Python finally 不保证执行；runner本身一次性销毁。

## 给初次使用者的本地部署步骤

需要已安装且当前用户可访问的 Docker Engine 和 Compose v2。先运行
`docker version` 与 `docker compose version`；不通过就停止，不以 sudo、
放宽 socket 权限或关闭安全检查解决。

1. 在仓库外的私有目录复制 `deploy/.env.example`。两个值刻意留空，启动会拒绝；
   自己在私有编辑器设置独立 ADMIN token，以及 UUID→不同 AGENT token 的 JSON。
   本说明不生成/配置长期凭据。别公开环境文件、展开的 Compose config 或 inspect。
2. 之后所有命令使用同一配置文件、同一项目名。将下面配置路径替换为自己的私有路径。

```sh
docker compose --project-name happyrun --env-file "$HOME/.config/swu-happyrun/server.env" -f deploy/compose.yaml config --quiet
docker compose --project-name happyrun --env-file "$HOME/.config/swu-happyrun/server.env" -f deploy/compose.yaml build
docker compose --project-name happyrun --env-file "$HOME/.config/swu-happyrun/server.env" -f deploy/compose.yaml up -d
curl --fail http://127.0.0.1:8080/api/v1/health
curl --fail http://127.0.0.1:8080/api/v1/ready
```

3. 在本机打开 `http://127.0.0.1:8080/console/`，管理 token 仅输入自己的页面。
   health/ready 成功不代表代理在线或设备支持。Python agent 所用 agent_id、token、
   device登记及本地profile revision必须匹配；见 [代理安装](installation.md)。
4. 停止保留数据：使用相同前缀执行 `stop server`；需要移除容器时执行 `down`。
   不加 `--volumes`。恢复启动仍使用相同项目名与卷。

默认仅回环发布、一个server进程、一个scheduler、本地命名卷。不要增加worker、
复制服务共享SQLite或暴露公网；HTTPS入口、生产部署和真实凭据配置需另行安排。

## 备份与恢复

SQLite可能使用WAL。运行中仅复制 `happyrun.sqlite3` 不是可靠备份。
使用自己已批准的存储备份工具按以下顺序操作：

1. 先确认/停止代理任务，暂停新任务，然后 `stop server`，确认容器停止。
2. 备份整个该项目数据卷（包括SQLite主文件及现存WAL/SHM），保留原文件所有者
   UID/GID10001；同时独立保存私有代理journal与profile。不要把备份提交Git或上传CI。
3. 恢复到另一个停服的数据卷，不覆盖唯一原始副本。核对同一schema/版本及UID10001
   可写，然后配置该恢复卷启动单个server；不以root运行绕过错误。
4. 查询已知job/schedule并核对状态与revision；对可能曾运行的任务保持needs_attention，
   不因为恢复成功就重放运行。不要手工改数据库状态或清空租约绕过安全条件。

命令示例（Linux，本地已审核镜像；备份路径必须在仓库外且由你私有保管）：

```sh
CFG="$HOME/.config/swu-happyrun/server.env"
BACKUP="$HOME/.config/swu-happyrun/data-backup.tar"
# 先自行确认BACKUP不是需要保留的已有文件，再执行。
docker compose --project-name happyrun --env-file "$CFG" -f deploy/compose.yaml stop server
docker compose --project-name happyrun --env-file "$CFG" -f deploy/compose.yaml run --rm -T --no-deps --entrypoint tar server -C /data -cf - . > "$BACKUP"
# 首先核对备份非空且列出数据库及所有WAL/SHM（若存在）。
tar -tf "$BACKUP"
# 必须选择从未使用的新项目名；以下happyrun-restore仅为示例。
# 若该项目的数据卷已存在，停止并另选名字，不能覆盖。
docker compose --project-name happyrun-restore --env-file "$CFG" -f deploy/compose.yaml run --rm -T --no-deps --entrypoint tar server -C /data --no-same-owner -xf - < "$BACKUP"
docker compose --project-name happyrun-restore --env-file "$CFG" -f deploy/compose.yaml up -d
```

原服务保持停止，恢复服务使用新项目的独立卷。helper以镜像UID10001运行，
不发布端口、不开privileged，不安装额外备份软件。任何命令失败就停止；不要修改
文件权限或用root重试。恢复检查通过后也保留原卷；不要同时启动两个服务占用8080。
本轮自动测试验证命名卷重建容器持久化，不声称上述归档恢复命令已在Docker实测。

## 原生 Android APK 尚未连接服务的部分

目前APK `simulation_local` 完全离线，拥有独立本地任务DTO。它不是已有AGENT客户端。
Python agent↔容器通过，也不能据此声称APK↔容器通过。原生接入需复用同一v1协议并补：

- 用户可控的可信服务器配置、TLS验证、独立AGENT身份凭据的安全存储与撤销；
- AgentHello/heartbeat、已登记device归属、实际能力观测；
- claim/renew/fence/expected_revision/event幂等、lease丢失停止、取消stop-ack；
- 持久intent/journal与重启恢复批准，禁止含糊运行后自动再跑；
- 精确profile/route revision解析、共享schema/canonical向量的跨语言验证；
- 真设备适配器和独立验收证据，学校协议/记录验证仍是另一道门槛。

不新建第二套协议，不把本地Root或自身hook诊断当作这些能力已具备。
