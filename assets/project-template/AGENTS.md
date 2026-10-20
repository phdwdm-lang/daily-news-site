# 每日信息站工作区

使用本工作区 `skills/daily-news-site/SKILL.md`，先阅读 `运行说明.md`。路径以当前工作区为准。

- `.daily-news/config.json` 是本工作区配置，默认 `context.mode: none`；`.daily-news/profile.json` 仅保存用户确认的事实。
- 没有个人档案和待办时生成公共简报，隐藏个人栏，不制造关联。候选资料须先确认，外部文件只按用户明确选择读取。
- 每期材料保存在 `data/runs/`，源数据在 `data/issues/`，素材在 `resources/`。
- 使用 `scripts/workflow.py` 创建和恢复运行。候选须真实浏览、看图并签收；公开发布 CLI 必须通过审计，才切换 `site/current`。
- 不自动安装软件、改其他项目、创建调度、上传网站或发送消息。用户已经明确授权的后续动作按其范围执行。
- 本目录是私人运行工作区；分享软件请使用原始干净发行包，不分发本目录中的档案、运行日志、真实素材和历史期次。
