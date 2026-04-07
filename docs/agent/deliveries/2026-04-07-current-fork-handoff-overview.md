# 当前 Fork 交接总览

**日期：** 2026-04-07  
**仓库：** ClawTeam-OpenClaw  
**分支：** `feature/coding-agent-callback-runtime`  
**当前基线提交：** `83cf97f`  
**文档定位：** 这不是任务单，也不是 review 记录。这是一份面向后续接手者的项目状态说明，回答三个问题：

1. 当前这个 fork 在做什么
2. 已经做到了什么程度
3. 下一步真正应该做什么

---

## 1. 一句话说明当前 Fork 在做什么

这个 fork 的目标，不是单纯把 ClawTeam 变成“能多开几个 worker”的工具，而是把它演进成一套更专业的、可观测的、可回调的、可控的多层级运行时。

目标链路是：

```text
用户 / 主领导
  -> team leader
  -> worker
  -> coding agent runtime（Claude / Codex / OpenClaw 承载的执行层）
  -> worker callback
  -> team leader 汇总
  -> 上报主领导
  -> board / CLI / durable state 可观测
```

这个 fork 当前正在把上面这条链路从“prompt 驱动的多 agent 协作”推进成“有 durable truth、有 callback closure、有错误感知、有 operator surface 的运行时系统”。

核心理念已经明确：

- durable state 是 authority
- tmux / session / stdout 只是 evidence
- live transport 可以有，但不能成为 truth
- nickname 只是给人看的，不是 machine-facing identity
- worker 完成不等于 team 完成
- team 完成不等于主领导已收到 closure

---

## 2. 这个 Fork 为什么存在

原始 ClawTeam / OpenClaw 组合可以做到团队、角色、session、tmux、多 worker 等能力，但对本项目真正重要的几个点并不充分：

1. callback closure 不完整
2. 故障感知太依赖失败进程自己还能发消息
3. team leader -> 主领导 的上行闭环不够强
4. operator 对真实状态的观测不够可靠
5. 固定 team / 固定角色 / 固定 session identity 的模型不够强

因此这个 fork 的存在意义是：

- 保留 ClawTeam/OpenClaw 的 team/session/tmux 基础
- 叠加一层更强的 coding-runtime、callback-runtime、runtime-console、board/CLI truth model
- 最终把系统做成一套闭环、自感知、自上报的团队执行运行时

---

## 3. 目前已经做完了什么

下面不是“所有 commit 列表”，而是按能力层来总结已经完成的工作。

### 3.1 Coding Runtime 和 Worker Callback 基础已经打通

已完成：

- `clawteam coding exec/wait/result/callback-report` 这一整条 durable 路径
- coding job / result / events / artifacts 的持久化
- worker callback report 的持久化
- callback decision matrix
  - `continue`
  - `report_progress`
  - `escalate`
  - `complete`
  - `blocked`
- callback 进入 task metadata、runtime-console、board/API/CLI 的链路

这意味着当前系统已经不是“worker 自己说自己干完了就算完”，而是有结构化 callback record。

### 3.2 Runtime Console / Board / CLI 基础观察面已经建立

已完成：

- provider session / callback / fault / timeline 的 durable 模型
- runtime-console CLI
- board collector / board server / board web UI 基础观察面
- callback chain 的可视化
- task read fault / runtime fault 的显式呈现
- evidence honesty 改造
  - board 不再把 bounded evidence 伪装成完整历史
  - authority 与 evidence 的边界已经比较清楚

这一步非常关键，因为它把“系统真实状态”和“tmux 里看到的过程输出”分开了。

### 3.3 Spawn / Workspace / First-install 路径已经大幅硬化

已完成：

- OpenClaw worker 默认 tmux 启动路径修正
- `--deliver` 默认补齐
- workspace auto / always / no-workspace 的语义清晰化
- worktree preflight
  - git repo 检查
  - HEAD 检查
  - base ref 检查
  - bare repo / worktree capability 检查
- 结构化 workspace failure 诊断
- first-install smoke
- OpenClaw scratch workspace 风险文档化

这部分把“安装能不能起起来”“spawn 为什么失败”从黑盒变成了可诊断问题。

### 3.4 Standalone Smoke 和 OpenClaw Integration Smoke 已建立

已完成：

- standalone full-chain smoke baseline
- fake Claude / fake worker / fake OpenClaw smoke harness
- default spawn -> tmux -> openclaw tui --deliver 路径 smoke
- callback 持久化 smoke
- board/API durable read smoke
- workspace healthy / unhealthy 路径 smoke

这意味着当前 fork 已经不只是靠手工 tmux 点点点来验证，而是有自动化回归底座。

### 3.5 Fixed Team Identity / Handoff / Lifecycle 这层已经落地到 durable model

已完成：

- team profile / product key / reuse policy 字段
- member identity 拆分：
  - machine-facing：`memberId` / `agentId` / `preferredSessionKey`
  - human-facing：`memberNickname` / `memberDisplayName` / `memberRole`
- explicit handoff contract
- task lifecycle / callback lifecycle / review lifecycle 拆分
- incomplete handoff 检测
- callback expectation
- lifecycle / handoff 信息进入 task metadata、runtime-console、board/CLI

这部分对应借鉴了外部 skill 里的优点，但没有破坏 authority 模型。

### 3.6 Identity Precision 和 Session Bridge Prep 已完成第一轮硬化

已完成：

- nickname 不参与 machine identity
- 同名不同 user 场景的 identity precision 修复
- `update-member` 的 fail-safe 歧义拒绝
- `remove_member()` 的 fail-safe 歧义拒绝
- `preferredSessionKey` 与 `sessionRouting` 一致性修复
- session bridge prep notice 改为 machine identity 优先
- machine identity 不足且 name 歧义时，显式跳过 notice，而不是猜测绑定

这一步的意义是：

- 当前系统已经明确知道“什么可以猜，什么不能猜”
- 在 identity-sensitive 路径上开始宁可少做，也不乱做

### 3.7 文档体系已经整理

已完成：

- `docs/design/specs/` 放设计文档
- `docs/agent/plans/` 放 tasking / 计划
- `docs/agent/reviews/` 放 review / rereview
- `docs/agent/deliveries/` 放交付记录
- `docs/README.md` 说明文档分类规则

这解决了之前文档混杂、路径语义不清的问题。

---

## 4. 当前这个 Fork 已经具备什么能力

从“可用”角度看，当前 fork 已经具备以下能力：

1. 能创建 team / worker / task
2. 能以 durable state 为核心记录 coding runtime 的执行结果
3. 能记录 worker callback，并在 board / CLI / JSON / API 上观察
4. 能在 spawn / workspace / first-install 路径出错时给结构化诊断
5. 能表达固定 team identity、nickname、role、session key、routing metadata
6. 能表达 handoff completeness 和 task/callback/review lifecycle
7. 能通过 smoke/integration test 回归多数当前 V1 范围内的关键行为

换句话说：

这个 fork 已经不是“原始脚本拼接”，也不是“只有 tmux 才看得懂”的状态了。

---

## 5. 当前这个 Fork 明确还没有完成什么

这里非常重要。下面这些不是 bug，而是当前明确还没有做完的范围。

### 5.1 还没有真正完成 multi-level callback closure

当前较强的是：

- worker -> durable callback

当前仍然不强的是：

- team leader 聚合 worker 结果后形成 team callback
- team leader -> 主领导 / orchestrator 的 durable upward closure

也就是说，当前“worker callback”已经比较像样，但“team callback”还没有被完整实现为强约束闭环。

### 5.2 还没有真正完成 lifecycle hook bridge

当前虽然已经有：

- watchdog / degradation / some fault surfacing
- lifecycle cleanup capture

但真正缺的仍然是：

- OpenClaw lifecycle hooks 到 durable fault / timeline / upward visibility 的正式桥接
- worker / team leader 异常结束时，不依赖其自报的自动上报机制

这件事是下一阶段最重要的能力缺口之一。

### 5.3 Session Bridge 仍然只是 prep-only，不是完整 live transport

当前已有：

- session bridge notice 的 durable placeholder
- machine-facing identity 精度
- fail-safe 语义

当前没有：

- 真实 live session-native delivery
- delivery success/failure evidence
- retry / fallback / reconciliation
- leader/main leader 上层真正使用 bridge notice 进行快速协同

所以现在不能把 session bridge 说成“已经完成”。

### 5.4 还没有真正完成 closed-loop E2E 验证

当前已有：

- unit / integration / smoke 覆盖

当前没有：

- mandatory E2E proving:
  - 主领导
  - team leader
  - worker
  - coding runtime
  - worker callback
  - team callback
  - upward visibility

因此当前项目不能宣称“完整闭环已经被正式证明”。

### 5.5 Reconciliation / recovery 还只是设计

当前还没有：

- missing callback repair
- duplicate callback reconciliation
- late callback reconciliation
- operator repair record

所以当前系统仍然偏向“实时 durable truth + fail-safe”，而不是“强恢复型控制系统”。

### 5.6 provider orchestration 不在当前范围

当前不做：

- Claude / Codex provider config orchestration
- account/profile/model 自动管理
- 跨 provider 的强 control plane

这些仍然是外部依赖。

---

## 6. 当前最重要的设计约束

下面这些约束不应该被后续工作破坏。

### 6.1 Durable state 是 authority

不要让以下东西成为 truth：

- tmux pane 输出
- live session 文本
- Discord channel/thread 消息
- board convenience UI 本身

truth 仍然必须来自：

- task record
- callback record
- runtime fault record
- timeline
- coding job/result/artifact

### 6.2 Nickname 只是给人看的

不要用 nickname 做：

- callback linkage
- session routing authority
- member resolution authority
- fault attribution

machine-facing identity 应继续基于：

- `memberId`
- `agentId`
- `preferredSessionKey`
- `taskId/jobId/sessionId/callbackId/faultId`

### 6.3 Live transport 只能做 acceleration，不能做 authority

如果未来实现真实 session bridge 或 Discord binding：

- 可以加速通知
- 可以提升实时性
- 可以提供额外 evidence

但不能直接替代：

- durable callback
- durable fault
- task state
- timeline

### 6.4 Fail-safe 优先于“猜测成功”

当前 fork 已经在 identity-sensitive 路径上建立了一条重要原则：

- 不能准确绑定时，宁可拒绝 / 跳过
- 不能靠猜测把 notice 写到错误目标

后续新功能应继续保持这一原则。

---

## 7. 当前推荐的理解方式

不要把当前系统理解成“一个自动化 prompt 框架”。

更准确的理解是：

```text
ClawTeam-OpenClaw fork
  = team/task/runtime substrate
  + coding execution runtime
  + worker callback persistence
  + runtime-console observability
  + board/CLI operator surface
  + reusable team identity model
  + early session-bridge preparation
```

或者更直白一点：

这不是“多 agent 聊天系统”。

这是在往“多层级团队执行运行时”方向走。

---

## 8. 当前项目状态判断

如果要给一个诚实判断：

### 已经比较稳的部分

- coding runtime durable path
- worker callback durable path
- runtime-console data model
- spawn/workspace first-install hardening
- standalone/openclaw smoke baseline
- board/CLI/JSON operator truth surfaces
- fixed team identity metadata
- lifecycle/handoff metadata

### 仍然是主要缺口的部分

- lifecycle hook bridge
- team-level upward callback closure
- stronger E2E proof
- reconciliation / repair
- real session bridge delivery

因此当前项目状态可以概括为：

> 已经具备比较强的 V1 durable runtime 基础，但还没有达到真正闭环自治团队系统的终局形态。

---

## 9. 下一步真正应该做什么

接下来不是继续补零散小优化，而是要围绕闭环做实质推进。

### 9.1 第一优先级：lifecycle hook bridge

原因：

- 这是 worker / leader 异常时的第一真实感知入口
- 没有它，系统仍然太依赖失败进程还能自报
- 这直接关系到“自感知、自处理、自上报”是否成立

要点：

- hook event -> durable fault / timeline
- hook idempotency
- hook 与 watchdog 的关系
- 上层可见性

### 9.2 第二优先级：team-level upward callback closure

原因：

- 当前 worker callback 已经存在
- 但 team leader 还没有形成对主领导的强闭环上报

要点：

- team result aggregation
- team callback record
- reported / reported_upward 的真实持久化闭环
- leader failure path

### 9.3 第三优先级：真正的 E2E 闭环验证

原因：

- 当前 smoke/integration 已经很多
- 但还没有正式证明：
  - 主领导
  - team leader
  - worker
  - coding runtime
  - callback
  - upward closure

要点：

- durable authority 作为 pass/fail
- tmux/session 只能做辅助 evidence

### 9.4 第四优先级：fixed-team reuse 的运行态验证

当前 identity metadata 已经有了，但缺：

- run-1 -> run-2 的 reuse smoke
- stable session binding reuse
- fixed product team operational proof

### 9.5 第五优先级：reconciliation / repair

这一步不是当前最早要做的，但后面迟早要做：

- callback missing
- callback duplicate
- late callback
- operator repair action

### 9.6 更后面的能力

这些不是当前最先做的：

- real session-native bridge delivery
- Discord channel/thread binding
- ACP / 更强 provider control plane

这些都应该在核心闭环稳定后再做。

---

## 10. 当前不建议优先做什么

为了避免后续继续发散，下面这些方向当前不建议抢先做：

1. 不要先做 ACP 扩张
2. 不要先做 Discord/channel binding
3. 不要先做大规模 UI 美化
4. 不要把 board convenience UI 当 control plane
5. 不要让 live transport 越权成为 authority
6. 不要重新发明一套新的 prompt-only orchestration

这些都不是当前项目最核心的缺口。

---

## 11. 关键文档入口

如果只允许读少量文档，优先读这些。

### 设计主线

1. `docs/design/specs/2026-04-06-multi-level-task-callback-system-design.md`
2. `docs/design/specs/2026-04-06-openclaw-native-failure-reporting-integration-design.md`
3. `docs/design/specs/2026-04-06-worker-leader-failure-auto-report-design.md`
4. `docs/design/specs/2026-04-07-external-skill-borrowing-integration-design.md`
5. `docs/design/specs/2026-04-07-session-bridge-and-channel-binding-design.md`
6. `docs/design/specs/2026-04-07-runtime-test-matrix-and-acceptance-plan.md`

### 最近交付与收尾

1. `docs/agent/deliveries/2026-04-07-identity-precision-and-session-bridge-fixes-delivery-report.md`

### operator / 运行说明

1. `docs/runtime-console-operator-guide.md`
2. `docs/upgrade-and-rollback-guide.md`

---

## 12. 当前建议的回归基线

如果需要快速验证当前基线是否仍然健康，建议至少跑：

```bash
python -m pytest \
  tests/test_smoke_clawteam_full_chain.py \
  tests/test_smoke_openclaw_integration.py \
  tests/test_callback_decision_matrix.py \
  tests/test_coding_integration.py \
  tests/test_spawn_backends.py \
  tests/test_spawn_cli.py \
  tests/test_manager.py -q
```

更完整的当前 V1 baseline，应参考：

- `docs/design/specs/2026-04-07-runtime-test-matrix-and-acceptance-plan.md`

---

## 13. 最后一句话

当前这个 fork 已经把“多 worker + tmux + provider 执行”这件事，从一套易碎的 prompt 流程，推进到了“有 durable truth、有 callback persistence、有 operator surface、有 identity discipline”的运行时基线。

但它还没有完成最后那一段最重要的升级：

> 从“worker callback 做得不错”，升级到“team 级闭环、异常自动上报、真正可依赖的多层级团队系统”。

接下来的工作，应该围绕这个闭环继续推进，而不是重新发散到新的方向。
