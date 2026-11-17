# Sierra Outfitters · Customer Service Agent

一个以可用性、权限隔离和可验证结果为核心的客服 Agent MVP。在同一个对话中查询订单、取消符合条件的订单、申请退货、获取商品推荐、领取早鸟优惠，并在无法处理时创建人工工单。

> 演示系统：订单操作仅更新项目数据库。退货申请不等于退款；当前没有连接真实支付、仓储、物流 API 或外部人工客服。

## 快速启动

需要 Python 3.12+、Node.js 22.12+。无模型密钥也能运行核心业务。

```bash
git clone https://github.com/Irenezhangtt/OutfittersCustomerServiceAgent.git
cd OutfittersCustomerServiceAgent
# main 尚未合并 MVP 时：git switch codex/sierra-mvp
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
npm --prefix frontend ci
npm --prefix frontend run build
uvicorn sierra.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

打开 [聊天界面](http://localhost:8000) 或 [API 文档](http://localhost:8000/docs)。默认使用 SQLite，首次启动导入数据，重启不会重置业务状态。

前端开发可另开终端执行 `npm --prefix frontend run dev`，访问 [localhost:5173](http://localhost:5173)，API 自动代理至 8000 端口。

### PostgreSQL / Docker

```bash
cp .env.example .env
# 修改 POSTGRES_PASSWORD、COUPON_SECRET、DEMO_PASSWORD；不要提交 .env
docker compose up --build
```

Compose 启动 PostgreSQL 和完整应用，访问 [localhost:8000](http://localhost:8000)。数据库使用持久化 volume。连接现有数据库可设置 `DATABASE_URL=postgresql+psycopg://user:password@host:5432/sierra`。

### 测试账户

左下角使用 synthetic 测试账户登录，默认共享演示口令 `trail-demo`，通过 `DEMO_PASSWORD` 修改。登录、退出、开始新对话会轮换 session；切换账户不会继承上一客户的上下文。这不是生产身份认证。

| 账户 | 订单 | 场景 |
|---|---|---|
| `explorer01@example.com` | `#W001` | 已收到 → 申请退货 |
| `explorer01@example.com` | `#DEMO001` | 已下单 → 取消；额外 synthetic fixture |
| `explorer02@example.com` | `#W002` | 送货中 → 拒绝取消和退货 |
| `explorer03@example.com` | `#W003` | `fulfilled` 含义不明 → 工单 |
| `explorer04@example.com` | `#W004` | `error` → 工单 |

示例：先登录 Demo Explorer 01，然后分轮发送“帮我查订单”“explorer01@example.com”“#DEMO001”“取消这个订单”。也可尝试“推荐一个适合徒步的防雨背包”“还有更轻的吗”“我想领取早鸟优惠”“请转人工”。

优惠以服务器收到消息的时间判断。界面不能修改时钟；时间边界和夏令时由自动化测试覆盖。

## MVP workflows 与边界

### 1. 查询订单与物流

**流程：** 理解意图 → 收集邮箱和订单号 → 精确匹配 → 返回状态及物流链接 → 记录当前订单。

- 支持分轮补充信息、继续追问及切换订单。
- 两个条件必须同时匹配；已登录客户只能查看自己的订单。
- 邮箱单独不能列出订单，匹配也不等于账户认证。
- 仅返回状态、商品 SKU 和物流信息；不存在的地址字段不补写。
- 无 tracking number 则明确说明。USPS 链接由后端固定域名并编码单号生成。
- 初版不查询承运商实时状态，不打开用户提供的 URL。

### 2. 取消订单与申请退货

**流程：** 明确目标与意图 → 校验登录身份、归属 → 重读状态 → 事务更新 → 保存审计事件 → 校验后返回。

| 当前状态 | 允许操作 | 结果 |
|---|---|---|
| `placed` 已下单 | 取消 | `cancelled` 已取消 |
| `in_transit` 送货中 | 查询 | 不允许取消或退货 |
| `delivered` 已收到 | 申请退货 | `return_requested` 退货申请中 |
| `cancelled` / `return_requested` | 查询、重复请求 | 返回已有结果，不重复操作 |
| `unknown` / `error` | 人工升级 | 不自动执行售后 |

```mermaid
stateDiagram-v2
    已下单 --> 已取消: 客户明确取消
    已下单 --> 送货中: 仓储事件（未来）
    送货中 --> 已收到: 签收事件（未来）
    已收到 --> 退货申请中: 客户申请退货
    退货申请中 --> 后续人工处理: MVP 边界
```

- 模型不能授权操作；程序验证身份、归属、预期状态和版本。
- 使用事务、条件更新、版本号、请求幂等记录；重试不重复产生操作。
- “可以取消吗”只展示资格及确认入口；明确提出取消才执行。
- **不执行支付退款、生成运单、联系仓库或承诺到账。** 未定义的期限、费用、商品条件和金额政策转人工。
- 原始 `fulfilled` 不臆断为可取消；`delivered` 映射已收到，`in-transit` 映射送货中。

### 3. 商品咨询与推荐

**流程：** 识别品类、用途和偏好 → 查询扩展 → 目录向量检索与品类筛选 → 排序 → 展示依据。

- 初版为中英文领域词表 + TF-IDF + 品类/库存筛选，无外部权重下载。
- 可选 LLM 对未命中本地路径的复杂请求做结构化意图及查询分析。
- 推荐特点来自商品描述，库存从数据库读取。保留本轮偏好，支持继续比较。
- 当前目录只有一款背包，不虚构多款对比；价格、重量、容量数值和尺码缺失时明确说明。
- 未训练独立排序模型，未实现跨会话个性化或目录外商品搜索。

### 4. Early Risers 优惠

**流程：** 明确申请 → 读取身份 → 查已有领取 → 检查消息接收时间 → 原子保存 → 返回优惠码。

- `America/Los_Angeles`，`08:00 ≤ t < 10:00`，自动处理夏令时。
- 每位已认证客户在 `early-risers-v1` 活动中领取一次九折码，不按天重置。
- `HMAC-SHA256(secret, campaign_id:customer_id)`，不信任客户端用户 ID。
- 数据库对客户活动和代码设置唯一约束，截断码碰撞会重试。
- 已有码可在窗口外查询；新码只能在有效时间生成。
- 初版不接结账核销、不支持优惠叠加、有效期管理或其他活动。

### 5. 人工升级

- 明确要求人工、订单异常、状态不明或政策未覆盖时创建真实持久化工单。
- 保存工单号、原因、必要摘要、证据和状态，按会话隔离。
- 只有事务成功后才告知工单已保存。
- 初版工单在项目数据库，**不是实时转接**，不承诺人工响应时间。
- 明显提示注入或无关问题先拒绝并引导回客服范围。
- 数据库故障时返回可重试错误，不假报工单或业务操作成功。

### 6. 会话记忆与 Grounding

- 上下文包含近期原始消息、结构化摘要和业务状态，绑定服务器 session。
- 状态保存当前订单、缺失参数、待确认操作、偏好和最近推荐 SKU。
- 按保守字符预算限制上下文，为证据和输出预留空间；旧消息删除，业务审计单独保留。
- 摘要只从允许的结构化字段生成，不将旧消息中的指令提炼为系统规则。
- 摘要不授予权限，不作为最新订单状态；操作前重新读数据库。
- 每条业务结果关联订单、目录、政策、时钟或已保存事件，并在提交前校验事实及归属。
- 业务文案由可信模板生成，初版不额外调用第二个 LLM 审核每个回答。`grounded=true` 表示通过已实现的字段和持久化校验，不是通用正确性证明。

## Harness、安全与可用性

```mermaid
flowchart TD
    A[消息接收时间 / Session / 输入限制] --> B[近期消息 + 摘要 + 状态]
    B --> C[本地快路径 / 有限时 LLM 规划]
    C --> D[工具权限 / 参数 / 状态机]
    D --> E[业务工具 + SQL 事务]
    E --> F[模板回复 + 结构化证据]
    F --> G[Grounding 校验]
    G -->|成功提交| H[最终结果]
    G -->|失败| I[回滚 / 可重试错误]
```

| 要求 | 实现 |
|---|---|
| 品牌语气 | 友好、简洁、有探索精神，适量户外 emoji |
| 身份隔离 | 随机 HttpOnly / SameSite=Strict cookie，服务器存 token hash，不接受客户端 customer ID |
| 工具边界 | 参数、归属和状态校验；模型不能执行 SQL、读取任意客户或抓取 URL |
| 提示注入 | 明显攻击拒绝；模型输出仍受程序权限约束；不保证完全消除注入 |
| Web 安全 | 同源检查、长度限制、进程内限流、CSP、no-store |
| 低延迟 | 常见业务无模型调用，目录索引预计算，摘要无模型调用 |
| 超时 | LLM 默认 2.5 秒，总体处理期限默认 8 秒，PostgreSQL statement/lock timeout |
| 幂等重试 | 同 `request_id` 和同消息返回已有结果，换消息复用 ID 返回 409 |
| 流式回复 | 先输出进度；事实经校验和提交后统一返回 |
| 可观测性 | 健康接口展示最近成功请求 P95、样本数、存储类型及 Pacific 时间 |

目标为常见查询与推荐完整回复 **P95 ≤ 5 秒**，实测见 [验证记录](docs/verification.md)，不代表生产负载或远程模型服务承诺。

SQLite 适合单进程演示，多实例使用 PostgreSQL。进程内限流需在部署时增加网关限制。连接断开可能发生在提交之后，客户端使用相同请求 ID 重试确认结果。

## 可选 LLM

设置 `.env` 中的 `ANTHROPIC_API_KEY` 和可用的 `ANTHROPIC_MODEL`，复杂且未命中本地路径的消息会调用有限时的 Anthropic Messages API。System prompt 位于 `backend/sierra/planner.py`。

- LLM 仅返回受 Pydantic 约束的意图和查询，不决定身份、时间、状态或业务事实。
- 超时或非法输出安全降级；常见业务不依赖模型。
- 模型将收到当前会话必要上下文，接入真实客户前需确定第三方数据处理政策。
- 当前没有使用真实模型密钥完成在线质量评估；故障降级路径有测试。

## API

先 `GET /api/session` 创建 cookie，会话不接受客户端指定身份或接收时间。

| 接口 | 用途 |
|---|---|
| `GET /api/session` | 会话、身份、近期消息；缺失/过期时创建匿名会话 |
| `GET /api/demo/accounts` | 仅 demo 模式可用的 synthetic 账户 |
| `POST /api/auth/demo` | `{email,password}` 测试登录，轮换 session |
| `POST /api/auth/logout` | 退出并开始匿名会话 |
| `POST /api/session/reset` | 新对话，保留测试身份 |
| `POST /api/chat` | `{message,request_id}`，返回验证后的结果 |
| `POST /api/chat/stream` | NDJSON：`phase` / `result` / `error` |
| `GET /api/tickets` | 当前会话工单 |
| `GET /api/health` | 数据库健康及近期成功请求延迟 |

```bash
curl -c /tmp/sierra-cookies http://localhost:8000/api/session
curl -b /tmp/sierra-cookies -H 'Content-Type: application/json' \
  -d '{"message":"Track #W001 for explorer01@example.com","request_id":"demo-request-0001"}' \
  http://localhost:8000/api/chat
```

## 数据与目录

```text
backend/sierra/    API、身份、编排、工具、状态机、校验、检索和记忆
backend/tests/     订单、优惠边界、并发、权限、注入、压缩与降级测试
frontend/          React / Vite 界面与前端测试
data/             原始订单/目录、额外 demo 订单、版本化 MVP 政策
docs/             验证记录
scripts/          性能测量和提交包生成
```

公开仓库的 `CustomerOrders.json` 是独立生成的 synthetic 演示数据（`Demo Explorer NN` / `explorerNN@example.com` / `DEMO_TRACK_NNN`），不含原附件的客户记录；物流单号不可用于真实投递查询。商品目录保留题目提供的商品资料。`DemoOrders.json` 单独标记额外 placed 订单，仅 demo 模式导入。原附件保留在本地，可通过 `ORDER_DATA_PATH` 指向 gitignore 的私有文件进行本地测试；切换数据集请使用新的数据库，已有库不会自动覆盖。

表包括 `customers`、`orders`、`products`、`conversations`、`messages`、`chat_runs`、`order_events`、`coupons`、`tickets`。首次使用 SQLAlchemy 建表，后续正式 schema 演进需增加 migration。

## 测试与提交包

```bash
pytest -q
npm --prefix frontend test
npm --prefix frontend run build
# 启动后端后：
npm --prefix frontend run test:e2e
python scripts/benchmark.py
python scripts/package.py
```

GitHub Actions 配置 SQLite / PostgreSQL service 回归及前端构建。浏览器测试需安装 Chromium：`npm --prefix frontend exec -- playwright install chromium`。

## 未来 add-ons

| 方向 | 功能 |
|---|---|
| 正式身份 | OIDC/登录或邮箱验证码、账户级权限 |
| 真实售后 | 完整退货政策、仓储、运单、支付退款和到账跟踪 |
| 实时物流 | 承运商 API、配送异常、主动通知 |
| 推荐升级 | 神经网络 embedding、更多商品、行为反馈、学习排序 |
| 优惠体系 | 核销、有效期、使用次数、叠加和多个活动 |
| 人工客服 | 外部平台、客服工作台、实时接管和 SLA |
| 记忆升级 | 授权后的跨会话偏好、保留和删除策略 |
| 运营可靠性 | migration、分布式限流、审计导出、负载测试和告警 |
| 模型评估 | 真实模型基准、对抗测试、复杂生成选择性审核 |

## 实施阶段

1. 数据与订单：数据库、测试身份、精确查询、状态机、幂等审计。
2. 推荐与优惠：检索和依据、Pacific 时间、唯一发码。
3. Harness：隔离、摘要、权限、证据、人工工单。
4. 界面与交付：品牌界面、失败重试、性能记录、启动说明和 ZIP。

真实支付退款、正式账户认证和真实人工接管属于后续集成；仅关闭 `DEMO_MODE` 并不能视为可生产上线。
