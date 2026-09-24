# QA-test

`QA-test`（调用入口：`$qatest`）是一个面向研发提测前的业务自测插件。它把需求、代码改动和测试结果串成一条可确认、可执行、可追溯的流程，适用于后端、前端和全栈改动。

QA-test 不是正式 QA 验收、发布审批或上线批准，也不会自动修改产品代码。

## 快速开始

对当前改动发起一次完整业务自测：

```text
使用 $qatest 对本次改动做提测前业务自测，先生成并确认业务测试点，确认后继续执行并输出 Markdown 报告。
```

一次调用包含两个阶段：

1. 生成并展示本轮业务测试点，等待用户确认范围、预期和确认载荷。
2. 确认通过后执行自测，验证业务终态并输出 Markdown 报告。

如果测试点、范围、预期或代码快照发生变化，旧确认自动失效，需要重新生成和确认，不能沿用旧报告取得通过结论。

## 内部 Skills

### `make-business-test-points`

负责测试设计和确认：

- 从需求、代码、diff、截图或已有测试点建立影响地图
- 识别 `GENERAL`、`BI` 或 `MIXED` 项目类型
- 生成带稳定 `TP-###` 的业务测试点
- 将静态代码问题记录为 `OBS-###`
- 记录纳入/排除范围、待澄清项和相对历史的变化摘要

测试点以业务终态为中心，不能只写 HTTP 200、方法调用或队列入队等技术结果。该阶段不会执行产品测试。

### `check-code-with-business-tests`

负责执行已确认的业务测试点：

- 校验当前交互确认、payload SHA-256 和代码快照 manifest
- 检查运行时激活链、环境、权限、配置和最终观察点
- 按真实业务链路选择 API、集成、浏览器或 E2E 验证方式
- 覆盖时间边界、异步消费、权限、幂等和必要邻接回归
- 为每个 `TP-###` 记录 `PASS`、`FAIL`、`BLOCKED` 或 `NOT_RUN`
- 保存脱敏证据、清理结果和可复现 Markdown 报告

缺少本轮确认、快照不匹配或产物路径未被忽略时，执行阶段必须停止并回到测试点设计阶段。

## 测试范围路由

| 类型 | 适用场景 |
| --- | --- |
| `GENERAL` | 订单、用户、支付、库存、状态流转、权限、通知等普通业务 |
| `BI` | 报表、看板、指标、统计、聚合、数据查询或导出 API |
| `MIXED` | 同一轮同时涉及普通业务模块和 BI/数据模块，分别套用对应规则 |

无法确认是否包含 BI 模块时，先记录 `BI_UNCERTAIN` 并询问一次，不凭数据库或 SQL 的存在直接判为 BI。

## 确认与产物

两个 skill 共用 [`skills/business-test-contract.md`](skills/business-test-contract.md)。默认产物根目录为 `.self-test/<scope>/`：

```text
.self-test/<scope>/
└── runs/<confirmation-run-id>/
    ├── test-points.md
    ├── confirmation.md
    └── executions/<run-id>/
        ├── test-report.md
        ├── evidence/
        └── scripts/
```

产物按确认轮次和执行轮次写入不可变目录，不覆盖历史文件。Git 项目默认使用 `.git/info/exclude` 管理产物忽略规则；执行 skill 只校验忽略状态，不会替用户修改忽略配置。QA-test 不执行 `git add`、`git commit` 或 `git push`。

## 结果边界

- 默认目标等级为 `L2`，即用户、下游系统或业务负责人可观察的最终结果。
- `L1` 只在用户明确确认测试止于入口或中间状态时使用，并必须写明排除的下游边界。
- `PROD` 和无法确认的 `UNKNOWN` 环境只允许只读检查，禁止真实写入、支付、通知、删除或外部副作用。
- HTTP 200、单测全绿、任务入队或数据库中间状态不能单独证明业务 PASS。
- mock 只能替代用户明确批准的外部边界，不能替代被测业务逻辑。

## 目录结构

```text
business-self-test/
├── .codex-plugin/plugin.json
├── skills/
│   ├── business-test-contract.md
│   ├── make-business-test-points/SKILL.md
│   └── check-code-with-business-tests/SKILL.md
├── references/
│   └── bi-report-api-testing.md
└── tests/
    ├── acceptance.py
    ├── README.md
    └── test_validate_plugin.py
```

## 本地验证

在仓库根目录运行插件校验：

```sh
python3 -m unittest discover -s business-self-test/tests -p 'test_*.py'
```

运行本地订单验收夹具：

```sh
cd business-self-test/tests
qa_tmp=$(mktemp -d /tmp/qa-test-acceptance.XXXXXX)
python3 -B acceptance.py --output "$qa_tmp/run"
```

需要浏览器交互时，按 [`tests/README.md`](tests/README.md) 的说明追加 `--browser`。本地夹具使用合成数据、SQLite 和临时端口，不连接外部支付服务或生产环境。

## 相关文件

- [插件清单](.codex-plugin/plugin.json)
- [业务测试点设计 skill](skills/make-business-test-points/SKILL.md)
- [业务自测执行 skill](skills/check-code-with-business-tests/SKILL.md)
- [共享契约](skills/business-test-contract.md)
- [测试与验收说明](tests/README.md)
