# DOMAIN AND CLERK MIGRATION (task A2/A3) — read-only reconnaissance

**State of this document.** Round-44 read-only inventory of what the domain migration actually
faces. **Nothing has been changed**: no DNS record written, no Clerk setting touched, no Netlify
setting touched, no certificate issued, no production service contacted for anything but a public
HTTP HEAD/GET from this machine.

Target: `coursejesus.com` (canonical), `www.coursejesus.com` (→ apex), `rag.coursejesus.com`,
`agent.coursejesus.com`, plus whatever the Clerk Production instance requires.

## 1. Measured DNS (queried this round)

| Name | Type | Value | Note |
|---|---|---|---|
| `coursejesus.com` | NS | `dns17.hichina.com`, `dns18.hichina.com` | **Aliyun HiChina is the authoritative provider** for the new domain |
| `coursejesus.com` | SOA | primary `dns17.hichina.com` | the zone exists and is delegated |
| `www.coursejesus.com` | — | NXDOMAIN | no record yet |
| `qqttai.com` | NS | `nile.ns.cloudflare.com`, `walk.ns.cloudflare.com` | the **current** domain's authoritative provider is **Cloudflare**, not Aliyun |
| `qqttai.com` | A | `75.2.60.5`, `99.83.231.61` | Netlify's load balancer addresses (apex on Netlify) |
| `www.qqttai.com` | CNAME | `coursemate-ai-qqtt.netlify.app` | **the Netlify site's default subdomain — the same site must be reused** |
| `rag.qqttai.com` | A | `47.114.34.175` | the production API host, single address |
| `agent.qqttai.com` | A | `47.114.34.175` | same host serves both API hostnames |

Two consequences worth stating plainly:

1. The pack's warning "购买域名在阿里云不等于权威DNS一定是阿里云" is confirmed **in the other
   direction** as well: the *new* domain is on Aliyun DNS while the *old* domain is on Cloudflare.
   The migration therefore adds records in the Aliyun zone for `coursejesus.com`; it does **not**
   touch the Cloudflare zone except (later) for the old-domain compatibility window.
2. The new domain has **no records at all** today (only the zone's NS/SOA), so there is no
   half-configured state to inherit — and equally no evidence yet that the new domain is usable.

## 2. Measured live endpoints (this machine, `curl.exe`)

| URL | Result | Meaning |
|---|---|---|
| `https://qqttai.com/` | **200** | the current front end is live |
| `https://www.qqttai.com/` | **301 → `https://qqttai.com/`** | www already redirects to apex, which is the behaviour required for the new domain |
| `https://coursemate-ai-qqtt.netlify.app/` | **200** | the Netlify site is live on its default subdomain |
| `https://rag.qqttai.com/` and `/health`, `/api/health` | **no TLS handshake** (`Recv failure: Connection was reset`) | see §3 |
| `https://agent.qqttai.com/health` | **no TLS handshake** | same |
| `http://rag.qqttai.com/` | **403 Forbidden**, `Server: Beaver` | Aliyun's WAF is answering |

TCP connectivity to the API host is open on 443 and 80 (`Test-NetConnection` true), while the
service ports themselves (8100/8101) are closed to the outside, which is consistent with a
reverse proxy in front of locally bound services.

## 3. What the API result does and does not say

* **Does say:** from this machine and network, the production RAG/Agent HTTPS endpoints cannot be
  reached: the TLS handshake is reset for every variant tried (TLS 1.2, TLS 1.3, HTTP/1.1,
  verification disabled, and with the hostname pinned to the resolved origin address), and the
  plain-HTTP request is refused by Aliyun's WAF (`Server: Beaver`). A front-end 200 does **not**
  imply a working API.
* **Does not say:** that the production API is down for real users. A WAF behaviour block, a
  geo/IP policy, or an unfiled-domain rule would produce exactly this from one client while
  serving everyone else. This reconnaissance cannot distinguish those cases, and this document
  does not pretend otherwise.
* **Why it matters for the plan:** the release sequence starts from "read-only re-verify the
  production state", and this is that re-verification's first real result. It also settles a
  question the plan raises (备案/接入): the *old* domain's backend already sits behind a mainland
  WAF that refuses this client, so **the old domain being usable is not evidence that the new
  domain will be** — the new domain needs its own DNS, TLS and (if the backend stays on mainland
  infrastructure) its own filing/access status confirmed independently.
* **Not attempted:** no bypass, no proxy through the old domain, no header trick. The pack forbids
  exactly that ("不能通过旧域代理或DNS花样绕开缺失条件").

## 4. What is still unknown (needs the platform consoles)

| Item | Why it cannot be read from here |
|---|---|
| Netlify Site ID, deploy history, current production deploy, display name | needs Netlify account access |
| Which Clerk instance/issuer/JWKS the production build uses | needs the Clerk dashboard and the protected production environment |
| Whether `coursejesus.com` is filed/acknowledged for mainland access | needs the Aliyun filing console |
| Clerk's required DNS records for the new domain | generated by Clerk when the production domain is changed |
| Aliyun application-real-name (实名) status blocking DNS edits | needs the Aliyun console |

These are collected in `OWNER_ACTIONS_ONLY_COURSEJESUS.md` §2 and §4, with the exact click paths,
and the migration itself stays blocked on them rather than being faked with a text-only rename.

## 5. Planned record set for `coursejesus.com` (to be confirmed against the consoles)

| Name | Type | Target | Source of truth |
|---|---|---|---|
| `@` | A/ALIAS per Netlify's current instruction | whatever the existing Netlify site gives today | Netlify domain panel — **never** a memorised shared IP |
| `www` | CNAME | the same Netlify site | Netlify, with www → apex redirect |
| `rag` | A | the verified current API host for RAG | `qqttai.com` zone today, to be re-verified from a working vantage point |
| `agent` | A | the verified current API host for the agent | same |
| Clerk records | as Clerk specifies | from the same Production instance | Clerk, when the domain is changed |

Rules kept from the pack: no clearing of the zone, no deleting MX/TXT/other services, sensible
TTLs, SSL validation preserved, `AAAA` only where IPv6 genuinely exists, and no hard-coded
historical Netlify IPs.

## 6. Honest limits

* Every fact above is a single-vantage-point observation from one machine on one network, taken
  this round; DNS answers can differ by resolver and the TLS behaviour can differ by client.
* The NXDOMAIN for `www.coursejesus.com` and the empty record set for the apex are current-state
  observations, not a configuration. Nothing has been prepared in that zone.
* Production was not written to in any way: no deploy, no DNS change, no Clerk change, no database
  access.
