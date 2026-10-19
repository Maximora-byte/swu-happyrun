# 西大第一、第二、第四运动场：地图输入准备

2026-10-19，用户指定使用 OpenStreetMap、高德和腾讯地图，优先西南大学第一、第二、第四运动场。按三个场地的公开名称和校园位置，本轮处理**北碚校区**。Codex采集与独立校验；产品接入交ChatGPT Dot，任务 [#64](https://github.com/Maximora-byte/swu-happyrun/issues/64)，关联 [#9](https://github.com/Maximora-byte/swu-happyrun/issues/9) / [#41](https://github.com/Maximora-byte/swu-happyrun/issues/41)。

已有三条可供离线审核的本地RouteProfile候选。地图来源与结构可用，不表示已具备当前乐跑规则、动态打卡点或有效记录；本轮没有修改产品、学校配置、MuMu或乐跑。

## 已取得的OSM来源

一次Nominatim名称查询确认北碚校区 `amenity=university` / way413071891；未选择同名地铁站。随后一次Overpass请求返回502，改用官方OSM API0.6 map export成功取得校园范围原始XML。查询bbox取自Nominatim校园结果，未猜测校区范围。原始XML、所有精确几何与本地RouteProfile均留 `local/swu-map-20261019/`；公开[来源清单](2026-10-19-swu-map-sources.json)仅记录对象ID/版本、点数、关系检查与源哈希，没有坐标、个人信息或私有路线ID。

| 场地 | 命名依据 | 跑道候选 | 版本 / 最后编辑 | 折线点数（含闭合端点） |
| --- | --- | --- | --- | --- |
| 第一运动场 | [way843421786](https://www.openstreetmap.org/way/843421786)，原名“西南大学第一运动场” | [way843421789](https://www.openstreetmap.org/way/843421789) | v1 / 2020-09-02 | 29 |
| 第二运动场 | [way368605818](https://www.openstreetmap.org/way/368605818)，原名“西南大学第2运动场” | [way846878928](https://www.openstreetmap.org/way/846878928) | v2 / 2026-07-16 | 39 |
| 第四运动场 | [node3724521740](https://www.openstreetmap.org/node/3724521740)，原名“西南大学第４运动场” | [way368577141](https://www.openstreetmap.org/way/368577141) | v3 / 2018-01-24 | 22 |

OSM原始数据使用WGS84；WebMercator底图投影不能当作原始经纬度坐标系。[OSM投影说明](https://wiki.openstreetmap.org/wiki/Projection)。数据署名 **© OpenStreetMap contributors**，许可 **ODbL-1.0**，见[来源与许可](https://www.openstreetmap.org/copyright)。本轮没有将其他地图数据写回OSM，也没有把第三方数据许可当作项目代码许可证。

学校[校园规划](https://fgb.swu.edu.cn/info/1014/1131.htm)也记载第一、第二及相邻第三/第四运动场，作为名称背景参考；该规划历史较早，不用它证明2026年的场地几何、开放状态或乐跑规则。OSM各对象的最后编辑日同样不代表现场精度，尤其一、四运仍需后续图源/现场复核。

## 本地检查及边界

Windows / Python3.13.15，复用当前共享 `RouteProfile` 与 `core.canonical.profile_revision`，本地QA转换命令 `python local/swu-map-20261019/prepare_candidates.py`，exit0。脚本仅转换已下载地图，不联网、不调用设备或业务接口。

- 三条候选原始node均在校园XML中存在；沿OSM既定node顺序保留几何，首尾node相同，至少三个不同顶点，数值有限。
- 第一运动场的28个不同跑道顶点全部落在其命名场地多边形内；第二运动场38个不同顶点同样在其命名场地内。第四运动场的命名POI点位于21个不同顶点的候选跑道环内。未将POI中心扩成猜测椭圆，也未误选附近第三/第五运动场。
- 三条候选所有顶点位于OSM校园way413071891 v21内。这是顶点关系检查，**未证明每个线段的完整包含、当前通行性或学校认可区域**。
- 三个JSON均通过RouteProfile结构校验，canonical revision重算一致；GeoJSON采用`[longitude,latitude]`，RouteProfile使用命名的latitude/longitude字段，输入CRS明确WGS84。
- 球面折线长度约421.5m、432.2m、451.1m，仅用于审核原始几何；OSM环线可能描绘不同跑道边缘，不能称正式中心线或强改成标准400m。没有增加圈数、抖动、速度或虚构跑步记录。
- 没有生成SchoolProfile、confirmed规则或执行任务；`device_execution_enabled=false`、`record_verified=false`。结构有效不能替代既有学校规则/整段边界校验、坐标校准或实际记录核验。

冻结校园XML SHA256：`0d974b582d0883c2d4a23dc95d8177c5af3da95379560c6db649fd41f044f354`。源文件、GeoJSON、三个RouteProfile及其完整UUID/revision只保留本地；公开元数据不能用于重放用户路线。Dot可通过官方 `/api/0.6/way/ID/full` 获取当前几何，核对版本；节点也有独立版本，若要复现本轮冻结必须核对完整几何摘要，不能仅凭way版本相同认定字节一致。

## 高德与腾讯：已尝试，尚未完成交叉核验

| 来源 | 本轮实际结果 | 当前用途 |
| --- | --- | --- |
| 高德地图网页 | 检索第一运动场时提示登录 | 未取得精确POI，不作已核实输入 |
| [高德官方拾取器](https://lbs.amap.com/tools/picker) | 官方界面能显示北碚校园，实际提示游客/未认证开发者只显示经纬度小数点后2位；检索不能提供本轮所需精确结果 | 仅作图面参考，不能用两位小数生成或校准跑道 |
| [腾讯地图](https://map.qq.com/) | 输入第一运动场后仅搜索栏可见，地图/结果区空白；旧getPoint入口返回位置服务首页 | 没有取得POI/几何，标记not_cross_verified |

没有绕过登录、CAPTCHA、精度限制或TLS；没有访问账户Key管理、创建付费服务、复制网页内部Key或改变全局网络设置。高德/腾讯没有数据时继续推进OSM和离线接入，不标“三图一致”。

来源接入必须保留各接口正式声明的CRS、轴顺序、精度和时间；OSM WGS84不能直接叠到国内坐标图层，不平均混合不同坐标。实际可用的高德/腾讯SDK/API需由组件可选的本地配置提供授权，不将Key放入仓库或错误输出。高德官方转换接口也明确要求Key并区分输入坐标来源，见[坐标转换文档](https://lbs.amap.com/api/webservice/guide/api/convert)；当前没有执行该接口或推断转换精度。

## Dot实现与Codex接续验收

任务已写入 [#64](https://github.com/Maximora-byte/swu-happyrun/issues/64)：

1. 在现有本地profile/路线流程增加一、二、四运动场地图候选入口和来源审核；消费可追溯几何，保持原有RouteProfile与wire合同，不能自动将学校配置改成confirmed。
2. 三个来源分开接入，OSM先支持；高德/腾讯未授权、无结果、超时或精度不足时标缺失。原始路线留本地，地图凭证可选且私有。
3. 用合成回归覆盖名称数字/全角归一化、校区及命名对象/跑道区别、单POI不能变路线、缺node/未闭合、轴和CRS错误、版本/源摘要变化、图源冲突，以及缺规则仍不能执行device任务。
4. 地图输入的完成不依赖实际乐跑页面；真实客户端适配仍需准确package/version、规则、页面和本次动态点。地图不提供这些业务事实，不将通用路跑活动通知当作本学期乐跑规则。
5. Dot小PR完成后，由Codex用本地三个真实候选做离线回放、图源差异与现场校验；执行能力和最终记录另行接受。[后续计划](../superpowers/plans/2026-10-19-post-e490-device-delivery.md)任务2–4继续推进，#57联网问题保持优先。
