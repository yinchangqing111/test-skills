# 本地订单验收夹具

该夹具独立于被评估技能。服务只使用 Python 标准库、SQLite 和 `127.0.0.1` 上由操作系统分配的端口。每次启动使用独立临时数据库，关闭时删除；不存在外部支付客户端、扣款 API 或生产凭据配置。

## 运行方式

在仓库根目录执行：

```sh
cd business-self-test/tests
qa_tmp=$(mktemp -d /tmp/qa-test-acceptance.XXXXXX)
python3 -B acceptance.py --output "$qa_tmp/run"

qa_browser_tmp=$(mktemp -d /tmp/qa-test-browser.XXXXXX)
python3 -B acceptance.py --browser --output "$qa_browser_tmp/run"
```

第二条命令使用已经安装的 `agent-browser` 和 Chromium，不执行安装。两条命令都会自行启动并停止服务；浏览器会话使用唯一名称并在 `finally` 中关闭。产物写入传给 `--output` 的新 `/tmp` 目录，不进入插件目录。

只有健康路径通过且注入缺陷被预期业务断言捕获时，夹具才以 0 退出。输出中的 `DETECTED` 表示成功发现缺陷，不表示缺陷行为通过。意外失败或漏检会以 1 退出；`summary.json` 分别保存实际值和预期值。

## 技能行为评估

[场景定义](skill-evals/scenarios.md)同时保存候选回归场景和本轮正式计分场景。每个纳入行为结论的措辞变体都必须执行两组：无指导对照和有技能样本，每组至少 5 个独立 fresh-context runner。未完成对称 5+5 样本的候选场景不得纳入统计，也不得据此声称行为改善。两组保持模型、推理等级、用户请求和最小输入一致；不得向 runner 提供通过标准、夹具缺陷开关、`acceptance.py`、旧回答或参考结果。

原始回复保存到 `/tmp`，逐份人工阅读并把样本级决定、直接引文和方差记录到[行为评估记录](skill-evals/with-skill.md)。控制组没有暴露目标失败时，不得宣称技能产生了行为提升；只能说明有技能样本符合当前规则。

行为评估检查确认、路由、分页、时间边界、快照失效和授权决策；`acceptance.py` 检查可观察的 HTTP/浏览器行为。门禁未满足时的拒绝是预期行为，不能转换成业务 TP 的 `BLOCKED`。

### 复现一个行为评估批次

1. 创建临时目录：`qa_eval_tmp=$(mktemp -d /tmp/qa-test-skill-eval.XXXXXX)`。
2. 为每个样本启动 `fork_turns: none` 的全新代理，记录模型和推理等级。
3. 无指导组不得读取插件技能；有技能组只读取指定技能及其明确要求的引用。
4. 两组传入完全相同的用户请求和最小原始材料；不得传入场景评分标准、旧输出、fixture 缺陷名或 evaluator 源码。
5. 要求 runner 不修改仓库、不执行真实外部副作用，把完整用户可见回复写入 `$qa_eval_tmp` 下的唯一文件。
6. 每组至少运行 5 次。逐份人工评分，不用关键词命中代替阅读；记录组内不同解释和绕过理由。
7. 保留所有失败样本；后续重跑使用新批次标识，不覆盖旧证据。

## 独立运行夹具

```sh
python3 -B src/service.py
python3 -B src/service.py --duplicate-stock-bug
python3 -B src/service.py --double-submit-bug
python3 -B src/service.py --payment-credentials missing
```

stdout 第一行给出实际 URL；使用 Ctrl-C 或 SIGTERM 停止。缺陷开关可以组合。页面支持创建订单、沙箱支付、查看库存/支付流水/订单状态，以及重放最近一次回调。

## 供独立测试者使用的业务契约

- 初始库存 10，杯子单价 500 分；数量必须为 1 至 5。
- 创建数量 2 的订单得到金额 1000 分的 pending 订单，不扣库存。
- 使用相同 request key 重试创建，返回同一订单。
- 沙箱支付后订单变为 paid，库存变为 8，新增一条 1000 分支付流水和一条 -2 库存流水。
- 重放同一回调应被识别为重复，不再改变库存或支付；两次送达均可审计。
- 创建请求仍在处理中时，浏览器连续真实点击两次只能创建一个订单。
- 无论是否存在凭据，真实支付都返回 403；缺少沙箱凭据时返回 503，且不改变业务状态。
- 缺少夹具专用请求头的回调返回 401，且不改变状态。公开测试头为 `X-Fixture-Callback: local-test-only`。

## HTTP 接口

| 方法 | 路径 | 请求或结果 |
|---|---|---|
| GET | `/` | 真实 HTML 结算页 |
| GET | `/api/health` | 沙箱能力和凭据模式 |
| GET | `/api/state` | 库存、订单、支付、回调、库存流水 |
| POST | `/api/orders` | `{"quantity":2,"request_key":"unique-intent"}` |
| POST | `/api/payments` | `{"order_id":1,"mode":"sandbox"}` |
| POST | `/api/callback` | `{"order_id":1,"event_id":"sandbox-event-1"}` 加夹具请求头 |

## 范围与证据

`--duplicate-stock-bug` 会让每次已接受回调都扣库存，同时只保留一条支付流水，用于证明只检查状态或支付流水会漏掉库存回归。独立的库存、回调效果和库存流水断言必须捕获该问题。

`--double-submit-bug` 会移除前端请求中的点击保护，使两次快速真实点击产生两个不同 intent key 的 HTTP 请求；仅有 HTTP 幂等检查无法发现此前端缺陷。

日志只包含合成响应数据、路由和状态，不记录请求头、凭据、卡信息或个人数据。截图只展示合成订单。页面或 API 声称“沙箱”不能证明真实提供商未扣款；可执行夹具本身没有任何外部支付集成，因此只能作为受控本地回归环境。

进行盲测时，只把业务契约和运行 URL 提供给 fresh-context runner；`acceptance.py`、缺陷开关及参考 `summary.json` 必须保留在 evaluator 一侧，防止 runner 复制标准答案。
