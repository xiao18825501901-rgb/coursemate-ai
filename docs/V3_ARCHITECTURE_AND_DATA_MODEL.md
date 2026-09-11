# V3 Architecture / 增量决定

## 决定与边界

保留 FastAPI 单一学习状态所有者；Node Task Agent 不存成绩，不改其任务工具。HTTP 身份来自现有 Clerk verifier；模型只是提案。新增 `app/learning` 模块，不新建服务。

```text
Course → Workspace(owner,course,revision,mode,layout)
       → Canonical Node → immutable Spec → Items(REQUIRED/RECOMMENDED/OPTIONAL)
Workspace → Journey(node,spec) → Unit → Coverage(item,section)
Workspace → Problem(version) → Solution(version) → Step → Knowledge link
                         Step → Bridge(journey,conditions,return_anchor)
Workspace → Operation(request hash,status,result) → ordered Events
Workspace → Assessment → Rubric performance (separate from Coverage)
```

范围键与后端解析 ID 决定访问；从模型/用户传入的 owner、SQL、状态、官方发布声明均不接受。私人生成物保持私人。模型调用在写事务之外；每个 workspace 至多一个生成操作，revision 防止多窗格覆盖。operation 重放只取保存结果，不自动重发未知供应商请求。

## Threat model

攻击边界：Clerk→API、请求→workspace/node、资料/模型→schema/compiler、DB→文件系统、任务→最终可见内容。保护资料、题干、覆盖/成绩、身份和费用。先写跨用户、伪 ID、越界版本、重复操作和截断内容反例测试。

当前 V2 `require_course_access` 存在 admin 全私人访问特权；新增私人学习域不继承该绕过。收紧旧入口须用原回归与显式审阅快照测试确认，不将普通 Admin 等同私人记录 owner。

## 实现顺序调整

黄金闭环前置必要的 workspace、规范节点、Spec 与编译器基础，管理 UI 与完整题池随后补齐。该排序来自用户明确优先级，不改变 Q/SG。初始 feature flag 默认关闭；阶段未完成不得对外称 V3 production accepted。
