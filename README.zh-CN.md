# azure-secret-watch

[English](README.md) | [中文](README.zh-CN.md)

Azure/Microsoft Entra ID 目前**不会**在 App Registration 的客户端密码
(client secret) 或证书到期前发送任何原生提醒 —— 凭据一旦过期，应用直接认证
失败，往往第一次"收到通知"就是生产环境报错。

**azure-secret-watch** 通过 Microsoft Graph API 的只读权限扫描你租户下所有的
App Registration，在密码/证书即将到期前通过邮件、Teams 或 Webhook 提前通知，
让你有时间在出问题之前完成轮换。

## 功能特性

- 🔍 自动扫描所有 App Registration 的 client secret 和证书到期时间
- 📬 支持多种通知渠道：Email / Microsoft Teams / 自定义 Webhook
- ⏰ 可自定义提前提醒天数（如到期前 30/14/7/1 天分级提醒）
- 🔁 自动去重 —— 每个提醒档位只发送一次，已过期的凭据会按设定周期持续提醒，
  直到完成轮换
- 🔒 只读权限接入（`Application.Read.All`），不读取、不记录、不传输密码本身
  （Graph 创建密码后本就不会再返回其明文），不做任何写操作
- 🖥️ 内置 Web 管理面板：可排序/分页的凭据表格、搜索与状态筛选、CSV 导出、
  扫描历史记录、亮/暗主题切换，并可一键手动触发扫描
- 🐳 单个 Docker Compose 服务即可部署，无需常驻 Logic App 或额外的调度服务器

## 工作原理

1. 使用自己的一个 App Registration（客户端密码或证书）向 Microsoft Graph 认证。
2. 分页调用 `GET /applications`，读取每个应用的 `passwordCredentials` 和
   `keyCredentials` 元数据（key id、描述、起止时间），不会读取密码明文。
3. 计算每个凭据距离到期的天数，与你设置的提醒档位比较。
4. 用本地的小型 SQLite 文件记录哪些"(凭据, 档位)"组合已经提醒过，避免每次
   扫描都重复发送同一档位的提醒。
5. 按已启用的通知渠道，把本次需要关注的凭据汇总成一条通知发出，并附上直达
   Azure 门户对应凭据页面的链接。

## 快速开始（Docker Compose）

### 第一步：为本工具注册一个专用的 App Registration

本工具需要一个自己的身份，并且只授予**只读** Graph 权限：

1. 在 Azure 门户中依次进入 **Microsoft Entra ID → App registrations → New
   registration**，名称和账户类型随意（一般选单租户即可）。
2. 在 **API permissions → Add a permission → Microsoft Graph → Application
   permissions** 中添加：
   - `Application.Read.All`（必需）
   - `User.Read.All`（仅在你打算启用 `NOTIFY_OWNERS` 解析所有者邮箱时需要）
3. 点击 **Grant admin consent** 授予管理员同意 —— Application 权限不同意就
   无法生效。
4. 在 **Certificates & secrets** 中，二选一：
   - **方案 A：客户端密码（Client secret）**——最简单，创建后立即记下值，
     之后无法再次查看。
   - **方案 B：证书（Certificate）**——推荐用于长期运行的部署，因为可以
     避免本工具自己也依赖一个"会过期的密码"这种自相矛盾的情况。上传证书的
     公钥，保留私钥 `.pem` 文件挂载给容器使用。
5. 从应用的 Overview 页面记下 **Application (client) ID** 和
   **Directory (tenant) ID**。

### 第二步：配置并启动

```bash
git clone <this repo>
cd azure-secret-watch
cp .env.example .env
# 编辑 .env：填写 AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
# （或 AZURE_CLIENT_CERTIFICATE_PATH），并至少启用一个通知渠道
# （邮件 / Teams / Webhook）。

docker compose up -d
```

容器会持续运行，并按 `CRON_SCHEDULE` 设定的时间扫描（默认每天 UTC 08:00），
另外启动时也会立即跑一次（`RUN_SCAN_ON_STARTUP=true` 默认开启）。状态数据
（去重数据库、最近一次运行结果）持久化在 `./data` 目录下。

打开 **http://localhost:8080** 即可访问 Web 管理面板 —— 展示所有已扫描凭据
及其到期状态的表格，支持搜索/筛选，并有"立即扫描"按钮。面板只展示凭据元数据
（名称、key id、到期时间），永远不会显示密码或证书明文。

如果想在等待调度之前先手动跑一次测试：

```bash
docker compose run --rm azure-secret-watch python -m azure_secret_watch --once
```

建议第一次运行时设置 `DRY_RUN=true`——会把本应发送的内容打印到日志，但不会
真正发出通知，也不会更新去重状态。

### 使用外部调度而非内置循环

如果你更倾向于用宿主机 cron、systemd 或 Kubernetes CronJob 来触发扫描，可以
使用 `docker-compose.once.yml`（设置了 `RUN_MODE=once`，容器扫描一次后退出）：

```bash
docker compose -f docker-compose.once.yml run --rm azure-secret-watch
```

## 配置项

所有配置均通过环境变量完成，完整且带注释的清单见
[`.env.example`](.env.example)，主要包括：

| 分类 | 关键变量 |
| --- | --- |
| Azure 认证 | `AZURE_TENANT_ID`、`AZURE_CLIENT_ID`、`AZURE_CLIENT_SECRET` 或 `AZURE_CLIENT_CERTIFICATE_PATH` |
| 扫描行为 | `WARNING_THRESHOLDS_DAYS`、`INCLUDE_SECRETS`、`INCLUDE_CERTIFICATES`、`NOTIFY_OWNERS`、`EXPIRED_REMINDER_INTERVAL_DAYS` |
| 调度 | `RUN_MODE`（`loop`/`once`）、`CRON_SCHEDULE` |
| 邮件 | `NOTIFY_EMAIL_ENABLED`、`SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`SMTP_PASSWORD`、`EMAIL_FROM`、`EMAIL_TO` |
| Teams | `NOTIFY_TEAMS_ENABLED`、`TEAMS_WEBHOOK_URL`、`TEAMS_WEBHOOK_FORMAT` |
| 自定义 Webhook | `NOTIFY_WEBHOOK_ENABLED`、`CUSTOM_WEBHOOK_URL`、`CUSTOM_WEBHOOK_METHOD`、`CUSTOM_WEBHOOK_HEADERS` |
| Web 面板 | `WEB_UI_ENABLED`、`WEB_UI_PORT`、`WEB_UI_USERNAME`、`WEB_UI_PASSWORD` |
| 安全 | `DRY_RUN`、`LOG_LEVEL` |

### Web 管理面板

只要 `RUN_MODE=loop`，默认会在 `http://<host>:8080` 启用。它读取每次扫描后
写入本地的 JSON 缓存文件渲染，不会额外调用 Graph API，也不影响通知/去重逻辑。

**在把端口暴露到本机以外之前，请先设置 `WEB_UI_USERNAME` 和
`WEB_UI_PASSWORD`。** 留空的话面板不做任何身份验证 —— 仅本机访问（
`localhost`）没问题，但如果这个端口能被你的内网或公网访问到就不安全了。
要么把这两个变量都设置好（会启用 HTTP Basic Auth），要么把端口放在你自己的
反向代理 / VPN / 防火墙规则后面。无论如何，面板都不会显示密码或证书明文
——只有名称、key id 和到期时间——但它确实会暴露你的 App Registration 清单，
仍然值得做好访问控制。

设置 `WEB_UI_ENABLED=false` 可以完全禁用它。

#### Monitoring（监控设置）页面

侧边栏的 **Monitoring** 页面可以直接开关每个通知渠道、编辑收件邮箱列表、
调整提醒档位——全程不需要修改 `.env` 或重新部署容器。只有当某个渠道的底层
连接信息（SMTP 主机、Teams/Webhook URL）已经通过环境变量配置好时，才能在
页面里把它打开；出于安全考虑，页面本身从不显示这些 URL（它们通常携带了
鉴权 token）。修改会保存到 `SETTINGS_FILE_PATH`（默认 `/data/settings.json`）
并立即生效，容器下次启动时也会在 `.env` 配置之上重新应用这些覆盖项。

#### 所有者（Owners）列

设置 `NOTIFY_OWNERS=true` 后面板会多出一列"所有者"，数据来自 Microsoft
Graph 的 `/applications/{id}/owners`——也就是 Entra ID 里真实的所有者关系，
不是本工具凭空生成或代替你分配的。这需要额外授予 `User.Read.All` 权限（在
`Application.Read.All` 之外）并完成管理员同意；没有这个权限的话，所有者查询
会静默失败（日志里能看到，但不影响扫描），表现就是每个应用都查不到所有者。
如果某个应用在 Entra ID 里确实没有设置所有者——这在通过 CI/CD 或 Terraform
创建的服务类应用里很常见——面板会把它标记为"无所有者"，并在顶部用一个提示
标签汇总数量。这种情况建议直接去 Entra ID（App registrations → 该应用 →
Owners）补上真实的所有者，而不是在本工具里绕过去。

### Microsoft Teams Webhook 配置

在目标 Teams 频道中：**⋯ → Workflows →
"Post to a channel when a webhook request is received"**（这是微软用来替代
已废弃的 Office 365 Connector webhook 的新方式）。将生成的 URL 填入
`TEAMS_WEBHOOK_URL`。如果你仍在使用旧版 Office 365 Connector webhook，则将
`TEAMS_WEBHOOK_FORMAT` 设为 `messagecard`。

### 自定义 Webhook 的请求体

```json
{
  "summary": {"total": 2, "expired": 1, "expiring_soon": 1},
  "alerts": [
    {
      "severity": "expired",
      "app_display_name": "Billing Service",
      "app_id": "00000000-0000-0000-0000-000000000000",
      "credential_type": "secret",
      "days_until_expiry": -3,
      "portal_url": "https://portal.azure.com/...",
      "owners": []
    }
  ]
}
```

可以接入 Slack、PagerDuty、ntfy 或你自己的系统；如果接收端需要鉴权，可通过
`CUSTOM_WEBHOOK_HEADERS` 设置 Bearer Token / API Key 等请求头。

## 数据与隐私

本工具在 `/data` 下持久化的状态仅包括：

- `state.db` —— 一个 SQLite 文件，记录"(凭据 key id, 提醒档位)"上次提醒的
  时间，仅用于避免重复提醒。
- `last_run.json` —— 最近一次扫描的结果，供 Docker healthcheck 使用。
- `inventory.json` —— Web 面板展示用的完整凭据清单及到期状态。
- `settings.json` —— 从 Monitoring 页面保存的通知渠道/提醒档位覆盖项（见
  上文）；在你第一次于该页面保存修改之前，这个文件不存在。

无论是这些文件还是任何日志输出，都不会包含真实的密码明文或证书私钥。

## 开发

运行测试、lint 以及本地构建镜像的方法见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)
