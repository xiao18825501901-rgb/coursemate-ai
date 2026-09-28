# OpenJev installation and resource report

Date: 2026-09-29 (Asia/Shanghai)

## Outcome

The self-hosted OpenJev runtime is installed and running on the verified CourseJesus
production ECS. It is a private, loopback-only service and is not exposed through
Nginx or to browsers.

This report distinguishes a successful installation from quality qualification.
The runtime installation passed; the four Question Engine hard gates did not pass
the scoped quality evaluation and therefore remain disabled.

## Verified production identity

| Item | Verified value |
|---|---|
| SSH target | `coursemate-prod-new` -> `47.114.34.175` |
| Hostname | `iZbp1f0vqhds2341pdqqiyZ` |
| Private address | `172.20.170.40` |
| Host key | `SHA256:TWqeYbYv83dw67sg6BWf3gv3C4LjRWeioaA5/qbq4k4` |
| OS | Ubuntu 22.04.5 LTS |
| Capacity | 2 vCPU, 3,664,912,384 bytes RAM, no swap |
| CourseJesus app release | `/srv/coursemate/releases/b63401e` |
| OpenJev release | `/srv/coursemate/openjev/releases/openjev-5266719-hf7c79f25-r5` |
| Listener | `127.0.0.1:28765`, backlog 8 |

## Frozen software and model identity

| Component | Frozen value |
|---|---|
| Source repository | `nico-martin/open-jev` |
| Reviewed source commit | `52667199e8a55553e1865a41f43fcb7d4dd92779` |
| Locally built package | `open-jev-0.1.2.tgz` |
| Package SHA-256 | `387d9acd4531356375f13d3a3c3a94b12f370a7e6e1017a1c110b7829ea1a8fd` |
| Transformers.js | `4.3.0` |
| Model | `onnx-community/open-jev-deberta-v3-large-ONNX` |
| Model revision | `7c79f25b5ac496089f448a969c801872ad59d31c` |
| Dtype | `q4` |
| Weights aggregate SHA-256 | `e98c3e9eec070edbbbe61ada626916654528ff75fef72f841025e83b8e85024d` |
| Tokenizer aggregate SHA-256 | `89d3a6c7f78e5fee3bb448522f588d4e782f7210c1726ddb9dd973d80a604ba9` |
| Input transform | `coursejesus-openjev-input.v1` |

The npm registry artifact with version `0.1.2` declared a different `gitHead`
than the reviewed source commit. The deployment therefore uses a tarball built
from the exact reviewed commit rather than trusting the same-version registry
artifact.

The runtime loads only the frozen local snapshot. Remote model access is disabled,
and restart does not follow `latest` or download from Hugging Face. The downloader
has the five expected file sizes and SHA-256 values embedded, and runtime startup
rejects missing, changed, extra, symlinked, or non-regular snapshot entries.

Deployed `r5` source archive SHA-256:

`face3f67eb18afa3b289518eda3100d0f3ec45938c3398874c3c30f2d3d94d16`

## Service controls

- systemd unit: `/etc/systemd/system/coursejesus-openjev.service`
- service account: `coursejev`; supplementary group: `coursemate`
- single model instance; one inference at a time; admission queue limited to 8
- `MemoryHigh=1650M`, `MemoryMax=1800M`, `CPUWeight=25`
- `NoNewPrivileges`, private devices/temp, protected system/home/kernel settings
- bearer secret: root-owned `/etc/coursemate/secrets/openjev.env`; never printed
- fixed `512` total model tokens, `256` state tokens
- `truncation=error`; over-limit inputs are rejected rather than silently cut
- one HTTP attempt per decision; no SDK or transport auto-retry

## Runtime evidence

Final probes returned:

- `/health`: `alive`
- `/ready`: `ready`, not saturated
- `/version`: provider `open-jev-selfhost` and the exact model manifest above
- systemd: `coursejesus-openjev`, `coursemate-rag`, and `coursemate-agent` all active
- public RAG health: HTTP 200, `{"status":"ok","service":"rag-api"}`
- post-cleanup synthetic decision: `COMPLETED`, revision/hash identities matched,
  no truncation, 399 ms inference

Measured on the real 2C4G host:

| Measurement | Result |
|---|---|
| Simple English inference | about 445 ms native / 458 ms wall |
| Three simultaneous client requests | completed serially in 1,264 ms |
| Per-request latency in that run | 396-443 ms |
| Stable service memory after inference | about 1.48-1.61 GiB |
| Observed memory peak | 1,730,150,400 bytes |
| Host available memory after load | about 1.04 GiB |

The first `MemoryHigh=1400M` trial caused sustained reclaim pressure while the
model loaded. The service was stopped safely, the real peak was measured, and
the high watermark was raised without increasing `MemoryMax` beyond 1800M.

## Capacity and campus-course decision

Campus courses were **not removed**. Evidence did not show that course data was
the cause of the memory pressure: OpenJev's native ONNX load accounted for the
large resident-memory change, while the other production services remained
active with over 1 GiB available memory.

Disk space was reclaimed only from generated OpenJev installation staging:

- deleted `/tmp/openjev-model-hf7c79f25.tar` (486,685,696 bytes);
- deleted the obsolete first OpenJev release directory;
- retained current `r5` and rollback releases `r2`, `r3`, and `r4`;
- retained all courses, databases, attachments, backups, and owner source files.

Root filesystem state after cleanup: about 5.5 GiB free, 86% used.

The production dependency lock also passed `npm audit --omit=dev` with zero
known vulnerabilities across the installed production dependency graph at the
time of this release check.

## TypeSafe isolation and recovery material

All `TYPESAFE_*` entries were removed from current and inactive CourseJesus RAG
environment files. The current RAG service was restarted and passed health checks.
No new normal path or automatic fallback can call TypeSafe.

Root-only pre-change copies are held under:

`/srv/coursemate/backups/20260929T005000-openjev-takeover`

They exist for audit, not as a recommended fallback. Historical decision receipts
keep their original provider identity and UNKNOWN state.

## Rollback

Runtime-only rollback does not require restoring a database:

1. Keep all four hard-gate definitions off.
2. Stop `coursejesus-openjev` if it harms host capacity.
3. Point `/srv/coursemate/openjev/current` to retained `r3` or `r2`, reload
   systemd, start, and verify `/ready` and `/version` before use.
4. If no retained version is healthy, leave semantic decisions safely pending;
   do not restore TypeSafe as an automatic fallback.

No course, chat, answer, grade, file, or receipt is overwritten by this rollback.
