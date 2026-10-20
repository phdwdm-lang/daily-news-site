# 输入与浏览签收

本文件约定当前项目的 `scripts/prepare_audit.py`、`scripts/run_audit.py` 与 `daily_site.py`。先看命令 `--help`；审计属于运行材料，不嵌入页面。

## 创建输入审计

新实例使用审计 v2。在同一本次运行目录保留 `run.json`、Builders 原始返回与 `context/snapshot.json`；快照由本期实际配置、确认资料和选定来源产生。通用模式没有待办文件，也不创建假 Page／空 HTML。独立采集器会写 run 开始时间。另存 `bindings.json`：

```json
{
  "personal_bindings": [{"url": "https://example.org/article", "context_ids": ["本期快照中的真实事实ID"]}],
  "products": [{
    "url": "https://example.org/article",
    "identity": "产品缓存身份",
    "review": {
      "decision": "selected",
      "sources": [{"url": "https://example.org/article", "status": "checked", "evidence_path": "/绝对项目路径/data/runs/日期/运行标识/media/article.html"}],
      "candidates": [{"url": "https://example.org/feature.png", "decision": "selected", "reason": "实际看图确认是本条功能的界面截图", "evidence_path": "/绝对项目路径/data/runs/日期/运行标识/media/article-candidates.json"}]
    }
  }],
  "missing_avatars": []
}
```

`context.mode: "none"` 时个人栏和 `personal_bindings` 都为空。`profile`／`context` 的每条个人资讯至少对应一个本期实际可用 `context_ids`，逐条覆盖且不能引用未确认候选。若提供 `fact_types`，须与所绑定事实类型完全一致。轻资料的目标不能冒充活动项目，动态来源失败与实际降级必须保留。

素材身份是缓存索引中的实际键，不能把示例当真数据。`products` 须覆盖全部重点／个人条目，按原文 URL 绑定。已配图须有真实身份、视觉确认和唯一选中候选，其 URL 与缓存 `asset_url` 或 `resolved_url` 一致。无图时用本条具体的 `missing`（至少12字符）说明，不同时声明 `identity`，同样保留 `review`。泛泛说明不能代替实际查找。

取图过程见 [image-acquisition.md](image-acquisition.md)。`review` 字段：

- `decision`：`selected`／`no_candidates`／`all_rejected`／`download_failed`，与图片有无及实际处理一致。`no_candidates` 的候选为空；`all_rejected` 有候选且全部为 `rejected`；`download_failed` 至少包含一次实际下载失败。
- `sources`：实际检查的原文／官方／newsletter 来源，每项记录 `url`、`status: "checked" | "unavailable"` 和 `evidence_path`。必须包括条目原文 URL；若不可读，保存实际失败证据，并至少检查一个替代来源，不能用访问失败推断原文没有图。
- `candidates`：实际候选，每项有 `url`、`decision: "selected" | "rejected" | "download_failed"`、非空具体 `reason` 和 `evidence_path`；拒绝或失败原因必须与保存材料对应。

`evidence_path` 指向项目 `data/runs/` 下的真实本地文件；辅助程序转换为 `evidence: {"path": ..., "sha256": ...}`，不手填哈希。可引用原运行的已核实素材来源以保留缓存溯源，但新增查找、失败及视觉判断保存在本轮目录，不能伪装为重新抓取。批量填默认缺图理由、缺原文检查、证据变动或错绑已选 URL 会被拒绝；图像含义及理由真实性仍需人工／代理实际判断。

已配头像继续使用作者身份缓存。头像缓存未命中须按 [取图流程](image-acquisition.md#头像缓存未命中) 回查本人／机构来源；仍缺失才添加如下记录。`missing` 是本人的具体原因（至少12字符），`review.sources` 至少一个实际检查来源，URL 不重复，证据文件非空；辅助程序同样将 `evidence_path` 转换成路径和哈希：

```json
{"missing_avatars": [{
  "author": "确实缺图的人物",
  "missing": "本人资料页访问受限，机构页没有可核实的本人头像",
  "review": {"sources": [{
    "url": "https://example.org/team/person",
    "status": "checked",
    "evidence_path": "/绝对项目路径/data/runs/日期/运行标识/media/person-profile.html"
  }]}
}]}
```

```sh
python3 scripts/prepare_audit.py create --issue data/issues/YYYY-MM-DD.json --run-dir RUN --builders-raw RUN/builders/raw.json --context-snapshot RUN/context/snapshot.json --bindings RUN/bindings.json --output RUN/audit.json
python3 scripts/daily_site.py validate data/issues/YYYY-MM-DD.json --audit RUN/audit.json --preview-root RUN/previews
```

辅助程序从真实文件计算哈希，绑定本期快照。它不抓取 Page、不判断个人相关性，也不编造用户确认或浏览动作。远程获取、本地读取、用户确认和项目活动时间分别记录，生成审计的当前时间不能证明远程来源本轮重新读取。来源及资料变动后须刷新快照、重走检查点与签收。

旧实例及历史 v1 审计继续使用原 `--todo-page`、`--todo-source`、`task_ids` 协议，绑定当次 Page 及其保存 HTML，安全读取唯一 `const tasks` JSON，不执行 HTML。不得把旧证据改标为 v2 或在通用模式伪造待办来通过。v2 的 Page adapter 接受宿主真实保存的 JSON／Markdown 文档证据，不宣称支持 HTML 任务抽取。

## 实际验收后签收

使用Ego Lite对命令返回的候选实际操作，保留检查JSON与实际PNG。检查至少包含：`tool: "ego-browser"`、`passed: true`、实际候选`generation`、真实完成时间`reviewed_at`和具体检查结果。逐条切换全部重点并查看个人内容后，`media_checks` 须完整且唯一覆盖全部重点／个人的原文 URL：

```json
{"media_checks": [
  {"url": "https://example.org/article", "image_path": "assets/products/example.png", "rendered_count": 1, "loaded": true},
  {"url": "https://example.org/without-image", "image_path": null, "rendered_count": 0, "loaded": null}
]}
```

有图的路径必须等于当期 `image.path`，实际配图渲染一张且成功加载；无图记录 `null`、零张及 `loaded: null`。保存覆盖改动图片的桌面及窄屏截图，确认含义与裁切合适。没有这些证据不能写通过；检查清单或 JSON 正确不能代替浏览动作。签收命令只接受已有检查，不自动填验收时间：

```sh
python3 scripts/prepare_audit.py signoff --issue data/issues/YYYY-MM-DD.json --audit RUN/audit.json --preview-dir PREVIEW --ego-check RUN/ego-check.json --screenshot RUN/ego-page.png
python3 scripts/daily_site.py publish data/issues/YYYY-MM-DD.json --audit RUN/audit.json
```

同日修订另加`--replace`。所有占位符换为命令返回或本次真实路径。

门禁精确对比源人物、原帖和时间；模式、确认资料／选定来源与个人绑定；逐条取图证据、素材身份与内容；验收候选文件树、模板、数据和来源。签收的来源摘要包括上下文与 `media`，资料、模式、取图检查或其证据变动同样使旧签收失效。改变输入、正文、素材或候选后，要重新核对并签收，不能复用旧的 passed 标记。失败不切入口。

## 分支和保证边界

X分支成功而播客/博客失败时，可保留完整有效X内容并记录缺失；X失败不能当成无更新。真正成功但空的X结果允许产品资讯独立存在。来源的语义、图像人物首次身份、文章完整性与视觉质量仍需实际判断；程序只校验可证明的文件和对应关系。保存的Ego签收可追踪，不能从技术上证明人或代理确实浏览过，因此仍必须实际验收，不得伪造证据。

已验收的历史归档沿用，不重新采集；公开CLI只提交带当前审计的本次数据，低层渲染函数仅供内部回归和归档维护。
