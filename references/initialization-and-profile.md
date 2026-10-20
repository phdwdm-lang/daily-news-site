# 首次使用与个人资料

首次使用、修改个人资料或连接动态来源时读本文件。日常更新不重新做首用问卷；公共资讯规则和素材／浏览门禁继续执行。

## 软件检查与独立实例

先定位当前 Skill 目录和用户选定的新工作区。完整分享包包含 `SKILL.md`、采集脚本、`scripts/setup.py`、`scripts/doctor.py`、参考规则及 `assets/project-template`；模板带有 Python 流程、渲染器和 `resources/vendor/alpine.min.js`。不要复制其他用户的历史站点代替初始化。

优先探测并使用宿主已有的 Python、Node.js 与 curl。下面的 `SKILL`、`PROJECT` 是应替换的路径说明，不是固定作者目录；用实际可用 Python 运行：

```sh
python3 SKILL/scripts/doctor.py
python3 SKILL/scripts/setup.py --workspace PROJECT
python3 SKILL/scripts/doctor.py --project PROJECT
```

网络诊断可额外加 `--network`；只有实际找到 Ego 命令时才传 `--ego-command`。doctor 不替用户安装软件、连接账户、托管或设置调度，也不能只凭一个命令字符串证明代理已经具备看图或浏览能力。代理须核实当前宿主工具；缺少浏览能力时只能准备材料或候选，不能伪造浏览签收。

当前首发平台为 macOS，本机实测 Node.js 24.12.0、Python 3.11.8；采集器自身最低 Node.js 18+。Windows 原生流程使用到的 `fcntl` 尚待适配，Linux／WSL 等也未完成整个流程验收。安装前报告真实探测结果，不承诺尚未验证的平台或版本。

setup 在新目录创建独立实例，默认通用模式、暖白日间主题和 `Asia/Shanghai` 时区。页面右上角按钮可切换黑夜主题并记住选择，两套主题覆盖整页和卡片。setup 仍默认 `light`，不需要命令行主题选项；时区仅使用上海，未提供时区选择界面。重复初始化已初始化实例不覆盖其资料；已有无关目录不能作为覆盖目标。每期的 `python3 scripts/workflow.py init` 只创建一期运行，不代替软件初始化。

## 最多两轮的用户流程

用户要求开始使用或初始化后，第一轮先解释并执行可用的轻量提炼：

> 我先从近期聊天标题和摘要里整理你可能关心的方向，默认看近两周、最多 20 条；你也可以直接跳过，先用通用简报。

“14 天／20 条”是可调建议。先检查当前宿主是否提供有权限的 `list_threads`／会话检索摘要工具；仅在必要时用 `read_thread` 定点展开相关片段。不得假设可以读取任意应用或全部账户的聊天，也不默认读取所有会话正文。

工具的时间信息和范围不足时，说明实际可取得范围，不称“已经检查全部近两周聊天”。会话更新时间可用于决定检查哪条摘要，不能充作项目实际活动日期。没有跨会话工具或权限不足时直接说：“当前无法读取其他聊天。我可以先用这段对话的信息；你也可以一句话告诉我最近想推进什么，或直接跳过。”不为补资料扫描私人磁盘。

随后展示少量候选，第二轮一次确认：

> 我找到这些可能的参考：①……②……③……。你可以说“保留 1、把 2 改成……、忽略 3”，也可以全部跳过。确认后才会存到本机，用于简报筛选；相关说明会出现在你的个性化成品里。

候选须区分确定与推测，带简短来源。角色默认未知，目标优先；只说其中一项也足够，不再追加职位、公司、年龄等表单。讨论、假设和一次性提问不是正在做的项目，明确不对助手说的旁边话不纳入。没有有效线索时不凑候选。

只有用户实际确认／编辑的事实可写入长期 `profile.json` 并作为推荐依据。候选可暂存本轮私有草稿，不能作为已确认资料、自动续用或进入分享包；处理后清除已处理候选原文，只保留最小确认记录与用户确认的简要事实。用户跳过就保持通用模式，不把未回复当确认。此次查看近期摘要不授权未来持续读取全部聊天；日更只用确认资料与用户选定的动态来源，新发现仍需另行确认。

## 资料命令与模式

在实例工作区执行，路径均替换为本轮真实文件：

```sh
python3 scripts/context_profile.py candidates --input CANDIDATES.json
python3 scripts/context_profile.py review --decisions DECISIONS.json
```

需要从其他目录调用时，把 `--project-root PROJECT` 放在子命令前。CLI 不自行读取宿主聊天；宿主代理负责实际检索、展示候选、接收用户确认，并据此填写输入。候选输入示意：

```json
{"schema_version":1,"candidates":[{"type":"goal","text":"希望制作可控制阅读难度的练习","status":"candidate","sources":[{"kind":"chat-summary","reference":"实际会话引用","read_at":"实际带时区读取时间"}]}]}
```

程序按事实内容和来源生成稳定 `ctx-…` ID；展示与 review 使用本次命令返回的真实 ID，不自行编造编号。确认输入示意：

```json
{"receipt":{"method":"host-interaction","confirmed_at":"本轮实际确认时间","reference":"本轮用户确认消息引用"},"decisions":[{"id":"命令返回的真实ctx-ID","action":"confirm"}]}
```

`action` 可为 `confirm`、`edit`、`ignore`；编辑时提供用户改定的 `text`。receipt 必须对应真实用户交互，不能由模型自行签成用户同意。事实类型使用 `role`、`interest`、`goal`、`project`、`experience`、`task`；事实保存来源、确认时间和确认凭据。审计可追踪这些记录，无法从技术上证明用户确实说过某句话，因此仍须真实执行确认。

实例 `.daily-news/config.json` 使用 `schema_version: 1`，核心配置示意：

```json
{"schema_version":1,"context":{"mode":"none","profile_path":".daily-news/profile.json","sources":[],"fallback":"error"},"timezone":"Asia/Shanghai","theme":"light"}
```

- `none`：通用模式，`product.personal=[]`，无需待办或职业资料。
- `profile`：只使用确认资料；兴趣／目标匹配不能写成实际进行中项目。确认后根据用户选择启用该模式。
- `context`：使用确认资料及选定动态来源。`fallback` 为 `error`、`none` 或 `profile`，来源失败按所选政策处理并记录，不能静默伪装成功。

排除偏好中的“不读取某种资料”是读取边界；“不想看某类资讯”是编辑偏好。个人条目可以为零，不能只凭职业标签硬凑；个人化也不改变重点的独立价值排序。

## 动态来源与本期快照

仅连接用户选定的本地 Markdown／JSON 或 Page adapter。本地来源配置形如 `{"id":"work-notes","kind":"local","path":"用户选定的资料路径"}`；JSON 可为事实数组，或包含 `facts`／`tasks` 数组的对象。保留任务原有字段、状态及稳定 ID。Markdown 作为源文档证据，不把每句话冒充用户确认事实。

Page 由宿主实际可用连接读取；CLI 不联网访问 Page。配置包含 `id`、`kind: "page"`、用户自己的 `page_id`、保存证据的 `path` 和真实 `read_at`，必要时保留当次 `reference`。v2 adapter 接受保存的 JSON／Markdown；Page 工具整体 JSON 可作源文档证据，不宣称已抽出其中全部任务。旧实例的 Page＋保存 HTML／`const tasks` 协议继续走原 v1 审计，v2 不解析或执行 HTML。工具不可用时明确失败或按配置降级，不换成同名旧文件。

新实例的 `workflow.py init` 自动创建本期 `context/snapshot.json`；恢复包只显示模式、事实数量和快照指针，不默认打印事实正文。Page 需要在本次运行开始后读取；若尚无本轮证据，init 返回 `needs-input`、运行目录和续跑指引，可继续准备公开采集，但不能登记个人输入检查点已完成。宿主取得 Page 后更新配置里的 `read_at` 和证据路径，先生成快照：

```sh
python3 scripts/context_profile.py snapshot --run-dir RUN
```

已有快照后改变配置／资料或取得新证据时，显式刷新并重新走已失效检查点：

```sh
python3 scripts/context_profile.py snapshot --run-dir RUN --refresh
```

每次新运行重新读取当前配置、确认资料及选定来源。快照保存本期模式、配置与资料版本／哈希、事实 ID、真实来源状态与失败。个人条目绑定本期 `context_ids`；资料、来源或模式改变后旧签收不能沿用。分别记录获取、读取、确认和实际活动时间，未知活动时间不补造，复核期限到期不自行宣布项目结束。

## 隐私与运行边界

`.daily-news/` 保存私有配置、候选和资料；当期运行证据也可能包含个人内容，均不进入共享包、网页资源或公开仓库。分享包只取干净模板与必要程序。发布个性化成品前遵循该用户选择的访问范围；通用分享应使用通用模式生成不含个人栏的新产物，不能只删除私有源文件。

初始化只创建本地实例。托管、账号、访问范围和定时任务由每人分别选择，不继承原作者配置。电脑关闭或 App 未运行时，本地自动任务不能保证执行；不要把本地调度写成云端托管。具体发布和自动运行只在用户所选实例配置与当前授权范围内进行。
