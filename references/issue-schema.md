# 单期数据与资源约定

适用于 `schema_version: 1`。以项目 `scripts/daily_site.py validate` 的实际校验为准；本参考描述内容含义，不替代可运行校验。

## 单期结构

保存为项目 `data/issues/YYYY-MM-DD.json`。四个产品数组始终存在，空项使用 `[]`；`builders` 可为空，`podcast` 无新期时为 `null`。日期使用用户时区的整理日期，来源日期另记。

```json
{
  "schema_version": 1,
  "date": "2026-10-20",
  "product": {"featured": [], "personal": [], "quick": [], "unselected": []},
  "builders": [],
  "podcast": null,
  "source_note": "说明实际检查的来源、期次及任何覆盖缺失。"
}
```

上例全空只说明结构，不能作为可发布简报。不要为了绕过全空检查塞入“暂无更新”的假资讯。

通用模式 `context.mode: "none"` 时 `product.personal` 必须为 `[]`，渲染时空个人栏连同导航隐藏；不要求创建个人 Page 或空待办。轻资料／动态上下文模式也允许没有个人匹配。职业默认未知，只有确认资料或当期选定来源存在具体关联时才写 `personal`，并在独立审计绑定中使用 `context_ids`，不把内部事实 ID 塞进正文。

## 产品条目

共同字段：`title`（完整中文资讯标题）、`label`（源 Skill 的唯一内容性质分类）、`url`（原文）、`core`（忠实事实概括）。`emoji` 可沿用源分类；`tags` 沿用源数据，不凭排版需要补写。

| 数组 | 额外内容 |
|---|---|
| `featured` | 最多四条；保留 `tags`、`core`、`why` 及必要事实边界；`display` 为该条自己的展示段落，不能与另一条位置匹配；`image` 为对应真实配图或允许的无图值 |
| `personal` | `tags` 可为空；保留完整 `core`、`relation`；有明确问题才填写 `question`，否则空字符串；`image` 对应本条 |
| `quick` | 只有标题、分类、来源与一句事实概括，不放图片或额外推荐分析 |
| `unselected` | 只有标题、分类、来源与一句事实概括，不放图片、不写未选原因 |

`featured[].display`：

```json
{
  "points": [["", "第一个自然短段。"], ["", "第二个自然短段，保留必要条件。"]],
  "judgment": "资讯自身的价值判断，保留自述或未实测边界。"
}
```

每个 `points` 项为两个字符串；第一项可为空。网站已取消“能力、入口”这类分点标签，优先用空字符串和自然短段。`core`、展示短段和判断必须来自本条工作稿，不能互相篡改事实或添加亲测结论。条目间不以数组位置共享 `display` 或 `image`。

## 图片与头像

配图对象：

```json
{
  "path": "assets/products/example-identity.png",
  "caption": "说明画面实际展示的内容。",
  "kind": "screenshot",
  "width": 1600,
  "height": 1000
}
```

`path` 是发布资源根内 `assets/` 下的相对路径，禁止 `..`、绝对路径或指向其他用户文件。`width`、`height` 为正整数且与文件一致；`kind` 如实标示 screenshot/photo/illustration 等素材形态。已有模板特定 `focus: "muse"` 仅适用于其原本绑定的那张图，不复制到新资讯。无合适配图时 `image: null` 仅在当前渲染器与校验器明确支持时使用。

头像以 `avatar: "assets/avatars/<stable-person-id>.<ext>"` 绑定作者；缺图只用当前渲染器明确支持的真实缺省状态，不将另一人的头像复用为该作者。默认资源根是项目 `resources/`，按 CLI 的 `--assets-root` 可显式换用本次材料根；以往设计资源库可用于复用已核对的同一身份，不按旧期排序分配。

在本次运行记录中维护最小素材清单：条目 `url` 或作者身份、资源路径、来源页面、原图地址、取得时间及核对结果。同一个文件服务多个条目时，关系必须真实。

重点／个人无图也是逐条查找后的结果：不能由 newsletter 候选为空直接写 `image: null`。按 [取图流程](image-acquisition.md) 检查本条原文／官方页，并在 [审计绑定](run-audit.md) 保存有图／无图的 `review` 与证据；素材审计放在运行目录，不把内部检查字段塞入成品文案。候选页签收的 `media_checks` 按 URL 核对该条 `image.path` 及真实加载结果。

## Builders

每张人物卡包含：

| 字段 | 含义 |
|---|---|
| `author` | 获取结果中的人物姓名 |
| `role` | 获取结果 `bio` 可证实的职务；不明时空字符串 |
| `avatar` | 与该作者绑定的真实本地头像 |
| `one_sentence` | 完整中文一句重点，不能改造成吸睛但失真的标题 |
| `paragraphs` | 完整中文摘要段落数组，按获取结果中的改写提示生成 |
| `links` | 本卡对应的所有真实原文链接，保留项目既有链接对象格式 |
| `publication` | 下述真实发表时间对象，未知时为 `null` |

多个帖子合成一张卡时，`publication.posts` 逐条对应来源 URL 和原始时间；不能用抓取时间或日报日期当发布时间：

```json
{
  "posts": [
    {"url": "https://x.com/author/status/123", "published_at": "2026-10-19T22:30:00+08:00"}
  ]
}
```

单条也可使用 `{"published_at":"2026-10-19T22:30:00+08:00"}`，按校验器所支持的形态填写。时间字符串必须有时区；原始元数据缺失时先核对可证明的来源记录，仍未知则 `publication: null` 并在工作稿说明，不造时间或套用旧期时间。未知日期不在页面强塞推测小字。

## 播客／访谈

无新一期时 `podcast: null`；有内容时包含 `title`、`title_zh`、`series`、`lead`、`paragraphs`、`links`、`publication`。

- `title`：获取 JSON 提供的原始标题，不从转录稿猜测。
- `title_zh`：准确中文标题，作为页面显示标题；专有名词可保留，不能整句仍为英文。
- `series`：获取 JSON 的节目名；`lead` 和 `paragraphs` 为中文概括，保留事实归属和完整要点。
- `links`：原节目链接；`publication`：真实节目发表时间，带时区；未知时为 `null`，不能拿日报日期替代。

## 来源覆盖与重跑

`source_note` 提供读者需要知道的实际覆盖限制；原始采集结果和完整性依据另存 `data/runs/`，不往页面加入冗长核查小字。工作稿分别记录来源期次日期、抓取时间、全文／部分／失败范围；部分获取不因四栏数量相加正确而变成获取完整。

同一期可以修订，新期必须由本次真实来源形成。对已归档条目做去重比较，只保留新事件、实质新进展或明确注明旧日期的有价值推荐；不能仅把历史 JSON 的 `date` 改成今天。
