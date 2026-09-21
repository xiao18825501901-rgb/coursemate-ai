# MINIMAL OWNER ACTION CARD — Laya round

Only what cannot be done without you. No secret is requested in chat: every item says where the
value belongs. Everything else in this round (source work, tests, dataset, calibration, the
inference service, the deployment runbook, the release rehearsal) is being done without you.

Scope note: the previous TypeSafe/Jev request in this file is **cancelled by the owner** — no
TypeSafe key will be requested or used. The semantic layer is now self-hosted Laya.

---

## 1. Alibaba Cloud: create the dedicated Laya node (blocks `REAL_LAYA_INFERENCE` + `PRODUCTION_DEPLOYMENT`)

I verified the current estate read-only and **no existing instance can host Laya**:

| Host | What it is | Spec | Region | Verdict |
|---|---|---|---|---|
| `47.114.34.175` (i-bp1f0vqhds2341pdqqiy) | **current production** (rag.qqttai.com, agent.qqttai.com, release `4ef5064`) | **2 vCPU / 3 GiB** | cn-hangzhou-k | cannot host Laya, must not be squeezed |
| `47.237.179.69` (iZt4n0k005125h6vlxoiloZ) | idle, no services | **2 vCPU / 1 GiB** | ap-southeast-1 | too small and wrong region |
| `8.210.58.22` | SRSZQ (untouched) | — | ap-southeast-1 | out of scope, must not be touched |

I also confirmed this instance has **no RAM role** and there is no `aliyun` CLI or credential file,
so I cannot create the instance myself.

**Ask — either (a) or (b):**

**(a) You create it** (paste-ready facts):

| Item | Value |
|---|---|
| Region / zone | `cn-hangzhou` / `cn-hangzhou-k` (same as production) |
| VPC | `vpc-bp1384ux5srgabb6h8se1` |
| VSwitch | `vsw-bp13nh63x221tquuysvi0` |
| Spec | 8 vCPU / 16 GiB x86 (e.g. `ecs.c7.2xlarge` or the current-generation equivalent) |
| Image | Ubuntu 24.04 64-bit |
| Disk | 60 GiB ESSD (PL0/PL1 is enough; read-heavy, no IOPS requirement) |
| Billing | **pay-as-you-go (hourly)** — no subscription, no auto-renew, no auto-scaling |
| Public IP | none preferred (private only). If SSH must come from outside, an EIP with a security group locked to your admin IP is acceptable |
| Security group | inbound `22` only from your admin IP; inbound `8105` **only** from the production private IP `172.20.170.40/32`; no `0.0.0.0/0` |
| SSH access for me | install this public key for user `ubuntu` (or `root`):<br>`ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEYARFzyVaaLpYGT3W9/DhrtIZk0iNH3+Dtko6U8Naw6 dsh-laya-node`<br>fingerprint `SHA256:yTa8DKE6txlV4Yk7/HRMUFdfkRXh3QjzJ0TjlVw/zlU` |
| Price record | the console shows the exact hourly price at order time — tell me the figure (or leave it visible) and I will record it, plus the 730 h estimate, in `LAYA_ALIYUN_DEPLOYMENT_RUNBOOK.md`. I will not invent a price |

**(b) Or grant me scoped access** so I create it: a RAM user (or STS session) limited to
`ecs:DescribeInstances`, `ecs:DescribePrice`, `ecs:RunInstances`, `ecs:CreateInstance`,
`ecs:DescribeInstanceStatus`, `ecs:DescribeSecurityGroups`, `ecs:AuthorizeSecurityGroup`,
`ecs:CreateSecurityGroup`, `vpc:DescribeVSwitchAttributes`, `vpc:DescribeVpcs`, plus read-only
`ecs:DescribeImages`. Credentials go into `~/.aliyun/config.json` on this machine (never into chat,
Git or a report).

**What it unlocks:** `REAL_LAYA_INFERENCE`, `CALIBRATION`, `BUSINESS_EFFECT`, and the backend half of
`PRODUCTION_DEPLOYMENT`.

---

## 2. DeepSeek API key (blocks `DEEPSEEK_LIVE`)

| Item | Value |
|---|---|
| What | the API key for the current DeepSeek platform account |
| Where | `/etc/coursemate/rag.env` and `/etc/coursemate/agent.env` on `47.114.34.175` (mode `640`, owner `root:coursemate`, exactly like the existing keys) — **not** in chat, Git or any report |
| Variable names | `V3_MODEL_API_KEY`, `RAG_CHAT_API_KEY`, `RAG_QA…`/`DEEPSEEK_*` equivalents as the deployed release reads them; the release wiring will be pinned to the names in `DEEPSEEK_AND_JEV_RUNTIME_CONTRACTS.md` §§A2–A3 |
| Also confirm | the model alias to pin (`deepseek-flash` per the verified contract) |
| Budget | the USD 10 cumulative test/annotation cap you set this round — I will preflight the exact call plan and refuse to exceed it |

Current production runs **Qwen/Model Studio** (`V3_MODEL=qwen3.8-max`, `AGENT_MODEL_NAME=qwen3.8-max`,
`OPENAI_CHAT_MODEL=qwen3.7-plus`, embeddings `text-embedding-v4`), so this key is what switches the
generative path to DeepSeek during the release window.

**What it unlocks:** `DEEPSEEK_LIVE` (text, structured, vision, tool replay, grading feedback).

---

## 3. Production release window (authorization already given; two confirmations)

You authorized backup, isolated rehearsal, migration, release and acceptance. Two points need a
yes/no because they change the live product:

1. **Generative model switch on the live site**: production currently answers with Qwen. Publishing
   the new release switches all generative roles to DeepSeek and adds the Laya dependency. Confirm
   the switch may happen in one window (or tell me to hold the model switch back and ship the rest
   first).
2. **Frontend publish**: the site is Netlify project `coursemate-ai-qqtt` (qqttai.com), GitHub-linked
   to `main`, current deploy `6ab02278b7fae664934df25d`. I will publish a locally built artifact with
   `netlify deploy --prod` (rollback = restore the previous deploy), unless you prefer a merge to
   `main` instead.

---

## 4. Real login for browser acceptance (blocks `BROWSER_ACCEPTANCE` / `PRODUCTION_ACCEPTANCE`)

I will not bypass Cloudflare/Clerk or create new accounts. When the release is live I need you (or a
staff account you designate) to complete one real sign-in while I drive the acceptance journey:
课程 → 知识点 → 学习进度 shows 学习中 → 开始测评 → five questions → submit → 测评结果 shows a raw
score → 详解 → history/shared/theme/qualification checks. A screen-share or a short-lived session is
enough.

---

## 5. Not requested (so you know what I am deliberately not asking for)

* No TypeSafe key, no `typesafe-sdk` install, no `TYPESAFE_API_KEY`.
* No GPU purchase, no cluster, no extra load balancer, no NAT gateway, no annual subscription.
* No new user accounts, no DNS change, no SRSZQ change, no force-push, no old-Singapore writer.
* No additional budget beyond the USD 10 test/annotation cap and the single CPU instance above.
