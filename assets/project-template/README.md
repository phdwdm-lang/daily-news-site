# 我的每日信息站

此目录由干净发行包首次初始化。个人化默认跳过，未接入任何 Page 或原作者资料。运行规则见 `skills/daily-news-site/SKILL.md`。

信息站默认白天主题；页面右上角按钮可以切换夜间主题，并记住本机偏好。

首次检查：`python3 scripts/doctor.py --project . --network`。

请向代理提供此工作区路径并请求 `$daily-news-site 更新今天的简报`。需要个人化时，在对话中要求填写职业档案，或选择你自己的参考材料并审核候选。配置及档案保存在 `.daily-news/`，本工作区的真实运行数据默认排除在 Git 跟踪之外。
