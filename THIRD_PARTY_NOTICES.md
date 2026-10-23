# 第三方来源与复用记录

截至 2026-10-18，本仓库包含原创实现及下方注明的 MIT 坐标公式改编；未复制 APK 或视频。Python 依赖及其版本见 pyproject.toml / uv.lock，其许可继续适用。


## Offline coordinate formula adaptation

`src/swu_happyrun/core/coordinates.py` adapts the transform delta formulas,
iterative inverse and BD09 angular inverse from
[EdmundMad0309/budao-lepao-runner src/lepao/geo.py](https://github.com/EdmundMad0309/budao-lepao-runner/blob/53715ec80b3c5f0f99ef963e6cf5ed7be1a31e25/src/lepao/geo.py).
Modifications: strict types/finite/range checks, explicit CRS, bounded convergence,
fail-closed domain handling, detached WGS84 points. No MuMu code or compensation
is copied. Upstream license at that commit:

The 2026-10-23 local tool in `src/swu_happyrun/desktop/mumu_mapping.py`
composes the same WGS84-to-GCJ02 formulas with the BD09 angular forward
transform. This is a version-pinned input hypothesis checked against two fresh
own-APK GPS observations per session, not a general MuMu or school capability.
The notices below also cover this formula composition.

MIT License

Copyright (c) 2026 EdmundMad0309

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Test vectors are numeric examples from
[wandergis/coordtransform README](https://github.com/wandergis/coordtransform/blob/606c6f3b57b6f1d60458793fea39928d2b11b637/README.md),
README blob `6b2022737a73584a4016aca42953c68078d8a128`.
The separate project is an algorithm cross-check, not independent geodetic truth.
Its MIT notice is retained below:

The MIT License (MIT)

Copyright (c) 2015 记忆的残骸

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.



| 项目 | 评估版本 | 许可证/状态 | 使用范围 |
| --- | --- | --- | --- |
| [HuangZhuoRui/LocationSpoofer](https://github.com/HuangZhuoRui/LocationSpoofer) | `43ebe9dc89082c4ebe45056c1806cc713effc589` | GPL-3.0，文件声明允许 v3 或更新版本 | 可选 Root 后端的研究来源；未复制源码 |
| [hyper152/happy_run](https://github.com/hyper152/happy_run) | `efda3c5530aa3c220415c55865d4c1f493f55fdf` | 未声明开源许可证 | 仅引用项目和操作思路；不分发原文、APK、视频 |
| [EdmundMad0309/budao-lepao-runner](https://github.com/EdmundMad0309/budao-lepao-runner) | `53715ec80b3c5f0f99ef963e6cf5ed7be1a31e25` | MIT | 离线坐标公式已改编；上方保留版权、许可、原路径与修改说明 |
| [Chao-superw/sportxcli](https://github.com/Chao-superw/sportxcli) | 2026-10-18 读取 main | MIT | 评估后不作为可用跑步 API 基础 |
| [XXXXBully/LePaoReverse](https://github.com/XXXXBully/LePaoReverse) | 2026-10-18 读取 main | 未声明开源许可证 | 其他院校小程序协议研究线索；未复制源码或密钥 |

作者报告的兼容性与精度不代表本项目已取得同样结果。引入 GPL 衍生实现时必须先明确其源码、分发和许可边界，不能用本仓库其他文件的许可覆盖上游要求。
