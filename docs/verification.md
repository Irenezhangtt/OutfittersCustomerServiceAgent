# MVP 验证记录

本文件记录实际执行的验证，不将配置完成等同于验证通过。

## 本地记录

- 环境：macOS arm64、Python 3.12、Node.js 24。
- 后端：`pytest -q`，56 项通过。覆盖订单匹配、身份隔离、状态机、幂等、并发优惠、时间边界与夏令时、摘要压缩、证据失败回滚和模型超时降级。
- Python 静态检查：`ruff check backend scripts` 通过。
- 前端流处理及链接校验：3 项 Node 测试通过。
- React / Vite production build：通过。
- 前端运行时依赖：`npm audit --omit=dev`，0 项漏洞。
- 本地性能：临时 SQLite、FastAPI TestClient、无模型调用、100 次顺序请求。P50 2.92 ms、P95 7.77 ms、最大 22.15 ms。

该性能测量不覆盖真实网络、并发负载、远程模型、冷启动或生产 PostgreSQL，不能推导生产 SLA。

## 待补充的集成记录

- Chromium / Chrome 浏览器端到端验证：执行后更新。
- PostgreSQL：本机没有 PostgreSQL 或 Docker，使用仓库 CI 的 PostgreSQL service 验证，执行后更新。
- Docker 镜像：本机没有 Docker，当前提供配置，未在本机构建运行。
- 真实 LLM：没有提供 API 密钥，未执行在线模型测试；仅验证模拟故障和降级路径。

## 依赖审计边界

当前 npm registry 的 `picomatch` 最新版本为 4.0.7；审计报告指出其 extglob 匹配存在 ReDoS，尚未提供修复版本。它属于 Vite 的开发/构建依赖，生产界面为静态文件，不在浏览器运行该匹配器。

保留已修复开发服务器其他问题的 Vite 当前版本；开发服务器仅监听本机，不将客户输入传给构建 glob。完整 `npm audit` 仍会报告这一构建依赖及其受影响的上层包；运行时审计为零。修复版发布后需要更新锁文件。
