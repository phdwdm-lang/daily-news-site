"""Complete personal stories as editorial evidence and a paired recommendation."""

PERSONAL_CSS = r'''
.personal-section>.section-heading{border-bottom-style:dashed}
.personal-article{width:min(760px,100%);margin:0 auto;padding:42px 0 46px;border-bottom:1px dashed var(--line)}
.personal-article .personal-header{margin-bottom:24px}
.personal-article .personal-header h3{font-family:'Songti SC','STSong',serif;font-size:34px;line-height:1.48;font-weight:650;letter-spacing:-.3px;color:var(--ink);line-break:strict;text-wrap:pretty;overflow-wrap:anywhere}
.personal-article .personal-title-prefix{display:inline-block;max-width:100%;text-wrap:pretty}
.personal-article .personal-title-subject{display:inline-block;max-width:100%;text-wrap:balance}
.personal-article .personal-header h3 a{color:inherit;text-decoration:none;text-underline-offset:6px;text-decoration-thickness:1px}
.personal-article .personal-title-arrow{font-family:Arial,sans-serif;font-size:18px;font-weight:400;color:var(--accent);margin-left:10px;white-space:nowrap}
.personal-article .personal-header h3 a:hover{text-decoration:underline;text-decoration-color:var(--accent)}
.personal-article .personal-header h3 a:focus-visible{outline:2px solid var(--accent);outline-offset:5px}
.personal-article .personal-facts{padding:0;background:none;border:0}
.personal-article .personal-section-label{display:flex;align-items:center;gap:8px;margin:0 0 10px;color:var(--reading-muted);font-family:'PingFang SC','Hiragino Sans GB',sans-serif;font-size:14px;font-weight:600;line-height:1.5;letter-spacing:0}
.personal-article .personal-section-label svg{width:16px;height:16px;flex-shrink:0;stroke:currentColor;stroke-width:1.4;fill:none;stroke-linecap:round;stroke-linejoin:round}
.personal-article .personal-topic-tags{display:flex;flex-wrap:wrap;gap:5px 14px;list-style:none;padding:0;margin:0 0 12px;color:var(--muted);font-size:14px;line-height:1.6}
.personal-article .personal-fact-copy{font-size:17px;line-height:1.85;color:var(--reading-copy);line-break:strict;overflow-wrap:anywhere}
.personal-article .personal-fact-copy strong{font-weight:600;color:var(--ink)}
.personal-article .personal-evidence{margin:21px 0 0;padding:0}
.personal-article .personal-evidence-image{display:flex;align-items:center;justify-content:center;min-width:0;background:transparent;border-radius:8px;overflow:hidden}
.personal-article .personal-evidence img{display:block;width:auto;max-width:100%;height:auto;max-height:320px;margin:0 auto;object-fit:contain;border-radius:8px}
.personal-article.terminal .personal-evidence img{width:100%;height:auto;max-height:none}
.personal-article.tall .personal-evidence img{width:auto;max-width:100%;max-height:360px}
.personal-article .personal-evidence figcaption{font-size:13px;line-height:1.75;color:var(--muted);margin:10px 0 0;text-align:left}
.personal-article .personal-recommendation{display:grid;grid-template-columns:1.15fr 1fr;margin-top:25px;border:1px solid var(--reading-border);background:var(--reading-surface);border-radius:var(--reading-radius);overflow:hidden}
.personal-article .personal-recommendation:has(>.personal-connection:only-child){grid-template-columns:1fr}
.personal-article .personal-connection,.personal-article .personal-verification{padding:22px 24px 24px;min-width:0}
.personal-article .personal-recommendation .personal-section-label{color:var(--accent);margin-bottom:12px}
.personal-article .personal-relation-copy,.personal-article .personal-question-copy{font-family:'Songti SC','STSong',serif;font-size:19px;font-weight:400;line-height:1.85;color:var(--ink);text-wrap:pretty;line-break:strict;overflow-wrap:anywhere}
.personal-article .personal-relation-copy strong,.personal-article .personal-question-copy strong{font-weight:inherit;color:inherit}
.personal-article .personal-verification{border-left:1px dashed var(--reading-border)}
@media(max-width:720px){
 .personal-article{padding:30px 0 34px}
 .personal-article .personal-header{margin-bottom:20px}
 .personal-article .personal-header h3{font-size:28px;line-height:1.5;letter-spacing:0;text-wrap:balance}
 .personal-article .personal-title-prefix,.personal-article .personal-title-subject{display:inline;text-wrap:inherit}
 .personal-article .personal-fact-copy{font-size:16px;line-height:1.85}
 .personal-article .personal-evidence{margin-top:17px}
 .personal-article .personal-evidence figcaption{font-size:13px;line-height:1.7}
 .personal-article .personal-recommendation{grid-template-columns:minmax(0,1fr);margin-top:22px}
 .personal-article .personal-connection,.personal-article .personal-verification{padding:18px 18px 20px}
 .personal-article .personal-relation-copy,.personal-article .personal-question-copy{font-size:18px}
 .personal-article .personal-verification{border-left:0;border-top:1px dashed var(--reading-border)}
}
'''


# Emphasis is markup only: every original character is retained in its original order.
_FACT_HIGHLIGHTS = {
    'Muse': ('改变人数与主持人时间', '本次未实测。'),
    'Jev': ('减少29.6%的主模型调用', '曾略降正确率'),
    'OJO': ('探索设计、生成交互原型和代码', '内测候补阶段'),
}
_RELATION_HIGHLIGHTS = {
    'Muse': ('检查AI是否理解需求、输出能否验收',),
    'Jev': ('十月初已有Jev视频成片与投稿经验',),
    'OJO': ('UI收集站、素材整理和插件官网',),
}


def _emphasize(value, phrases, text):
    """Escape the full original text, inserting emphasis around exact substrings."""
    rendered = text(value)
    for phrase in phrases:
        escaped = text(phrase)
        rendered = rendered.replace(escaped, f'<strong>{escaped}</strong>', 1)
    return rendered


def render_personal(item, idx, media_info, image_size, text, esc, asset_prefix=""):
    """Render all original fields in full, without abridgment or hidden reading."""
    filename, caption, kind = media_info or ("", "", "")
    width, height = image_size or (1, 1)
    story_id = f'story-{idx + 1}'
    path = asset_prefix + filename
    prefix, separator, subject = item['title'].partition('：')
    arrow = '<span class="personal-title-arrow" aria-hidden="true">↗</span>'
    title = (f'<span class="personal-title-prefix">{text(prefix + separator)}</span>'
             f'<span class="personal-title-subject">{text(subject)}{arrow}</span>') if separator else text(item['title']) + arrow
    key = next((name for name in _FACT_HIGHLIGHTS if item['title'].startswith(name)), '')
    core = _emphasize(item['core'], _FACT_HIGHLIGHTS.get(key, ()), text)
    relation = _emphasize(item['relation'], _RELATION_HIGHLIGHTS.get(key, ()), text)
    # These are source classifications, not labels inferred from the prose.
    label = item.get('label', '').strip()
    tags = item.get('tags') or []
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split('、') if tag.strip()]
    classification = (f'<h4 class="personal-section-label" id="{story_id}-facts"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 2.5h7l3 3v12H5z"/><path d="M12 2.5v3h3M7.5 9h5M7.5 12h5M7.5 15h3"/></svg>{text(label)}</h4>') if label else ''
    topics = ('<ul class="personal-topic-tags" aria-label="内容主题">' + ''.join(f'<li>{text(tag)}</li>' for tag in tags) + '</ul>') if tags else ''
    facts_label = f' aria-labelledby="{story_id}-facts"' if label else ''
    figure = f'''<figure class="personal-evidence"><div class="personal-evidence-image"><img src="{esc(path)}" alt="{esc(caption)}" width="{esc(str(width))}" height="{esc(str(height))}" loading="eager"></div><figcaption>{esc(caption)}</figcaption></figure>''' if media_info else ''
    verification = f'''<section class="personal-verification" aria-labelledby="{story_id}-question">
          <h4 class="personal-section-label" id="{story_id}-question"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7.3"/><path d="M7.8 7.5a2.3 2.3 0 014.5.5c0 1.7-2.3 2-2.3 3.5M10 14.5h.01"/></svg>值得验证</h4>
          <p class="personal-question-copy">{text(item['question'])}</p>
        </section>''' if item.get('question','').strip() else ''
    return f'''<article class="personal-article {esc(kind)}" id="{story_id}" aria-labelledby="{story_id}-title">
      <header class="personal-header"><h3 id="{story_id}-title"><a href="{esc(item['url'])}" target="_blank" rel="noopener noreferrer">{title}</a></h3></header>
      <section class="personal-facts"{facts_label}>
        {classification}{topics}
        <p class="personal-fact-copy">{core}</p>
        {figure}
      </section>
      <div class="personal-recommendation">
        <section class="personal-connection" aria-labelledby="{story_id}-relation">
          <h4 class="personal-section-label" id="{story_id}-relation"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8 12l4-4M6.7 13.3l-1 1a3 3 0 01-4.2-4.2l3-3a3 3 0 014.2 0M13.3 6.7l1-1a3 3 0 014.2 4.2l-3 3a3 3 0 01-4.2 0"/></svg>与你的关联</h4>
          <p class="personal-relation-copy">{relation}</p>
        </section>
        {verification}
      </div>
    </article>'''
