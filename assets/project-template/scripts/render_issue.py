"""Render validated daily data with the accepted editorial template; no model calls."""
import copy
import calendar as monthcalendar
from personal_renderer import PERSONAL_CSS, render_personal
import html
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse


def render_issue(issue, issue_dates, asset_prefix="", issue_href_prefix=""):
    data = copy.deepcopy(issue)
    data['product'] = data.get('product') or {}
    for key in ('featured', 'personal', 'quick', 'unselected'):
        data['product'][key] = data['product'].get(key) or []
    data['builders'] = data.get('builders') or []
    issue_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    issue_date_label = f'{issue_date.year}年{issue_date.month}月{issue_date.day}日'
    issue_title = f'{issue_date_label} AI简报'
    display = [item['display'] for item in data['product']['featured']]
    publication_times = {'builders':[item.get('publication') for item in data['builders']], 'podcast':(data.get('podcast') or {}).get('publication')}
    issue_dates = sorted(set(issue_dates) | {data['date']})
    def issue_href(value):
        return issue_href_prefix + value + '.html'


    def esc(value):
        return html.escape(str(value), quote=True)


    def text(value):
        value = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', value).replace('**', '')
        value = re.sub(r'([A-Za-z0-9%])([\u4e00-\u9fff])', r'\1 \2', value)
        value = re.sub(r'([\u4e00-\u9fff])([A-Za-z0-9])', r'\1 \2', value)
        return esc(value)


    def host(url):
        return urlparse(url).netloc.removeprefix('www.')


    def source(item, label='阅读原文'):
        return f'<a class="source-link" href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">{label}<span aria-hidden="true">↗</span></a>'


    def article(item, idx, personal=False):
        image = item.get('image')
        media_info = (image['path'], image.get('caption',''), image.get('kind','')) if image else None
        image_size = (image['width'],image['height']) if image else None
        return render_personal(item, idx, media_info, image_size, text, esc, asset_prefix)


    feature_panels = []
    feature_tabs = []
    for idx, item in enumerate(data['product']['featured']):
        image = item.get('image')
        kind = image.get('kind','') if image else ''
        picture = (f'<div class="feature-picture"><img src="{esc(asset_prefix + image["path"])}" alt="{esc(image.get("caption",""))}" width="{image["width"]}" height="{image["height"]}"></div>') if image else ''
        name, _, headline = item['title'].partition('：')
        brief = display[idx]
        feature_panels.append(f'''<article class="feature-panel {kind} {'muse-panel' if image and image.get('focus')=='muse' else ''}" id="featured-panel-{idx+1}" role="tabpanel" aria-labelledby="featured-tab-{idx+1}" :class="{{'is-active':featureIndex==={idx}}}" :aria-hidden="featureIndex!=={idx}" :inert="featureIndex!=={idx}">
          {picture}
          <h2><a class="feature-title-link" href="{esc(item['url'])}" target="_blank" rel="noopener noreferrer">{text(item['title'])}</a></h2>
          <div class="feature-body">{''.join(f'<p>{text(point)}</p>' for _,point in brief['points'])}<p class="feature-judgment">{text(brief['judgment'])}</p></div>
        </article>''')
        feature_tabs.append(f'''<button class="feature-choice" id="featured-tab-{idx+1}" role="tab" aria-controls="featured-panel-{idx+1}" :aria-selected="featureIndex==={idx}" :tabindex="featureIndex==={idx}?0:-1" :class="{{'is-current':featureIndex==={idx}}}" @click="selectFeatured({idx})"><span class="choice-number">0{idx+1}</span><span class="choice-copy"><b>{text(name)}</b><span>{text(headline)}</span></span><span class="choice-arrow" aria-hidden="true">←</span></button>''')
    featured = ''.join(feature_panels)
    personal = ''.join(article(x, n + len(data['product']['featured']), True) for n, x in enumerate(data['product']['personal']))


    def short_rows(key):
        return ''.join(f'''<li><span class="quick-category">{esc(x['label'])}</span><div><a href="{esc(x['url'])}" target="_blank" rel="noopener noreferrer">{esc(x['title'])}<span aria-hidden="true">↗</span></a><p>{text(x['core'])}</p></div></li>''' for x in data['product'][key])


    def publication_markup(record):
        if not record:
            return ''
        dates = sorted(datetime.fromisoformat(post['published_at'].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8))) for post in record['posts']) if 'posts' in record else [datetime.fromisoformat(record['published_at'].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8)))]
        first, last = dates[0], dates[-1]
        clock = first.strftime('%H:%M')
        if last != first:
            clock += '–' + (last.strftime('%H:%M') if last.date() == first.date() else f'{last.month}月{last.day}日 ' + last.strftime('%H:%M'))
        return f'<time class="identity-time" datetime="{first.isoformat()}"><span>{first.month}月{first.day}日</span><span>{clock}</span></time>'


    def source_links(items):
        links = '、'.join(f'<a href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">{esc(item["text"])}</a>' for item in items)
        return f'<p class="reading-sources">来源：{links}</p>' if links else ''


    def disclosure_button(body_id, label):
        return f'''<summary class="reading-toggle" aria-controls="{body_id}" :aria-label="expanded?'收起{label}':'展开{label}'" :title="expanded?'收起{label}':'展开{label}'"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"/><path class="toggle-vertical" d="M12 5v14"/></svg></summary>'''


    slides = []
    for idx, item in enumerate(data['builders']):
        links = source_links(item['links'])
        avatar = (f'<img class="avatar" src="{esc(asset_prefix + item["avatar"])}" alt="{esc(item["author"])} 的公开头像" width="80" height="80">') if item.get('avatar') else f'<span class="avatar avatar-placeholder" aria-hidden="true">{esc(item["author"][:1])}</span>'
        sentences = [s.strip() for paragraph in item['paragraphs'] for s in re.findall(r'.+?(?:[。！？][”」]?|$)', paragraph) if s.strip()]
        paragraphs = '<ul class="builder-facts">' + ''.join(f'<li>{text(sentence)}</li>' for sentence in sentences) + '</ul>'
        slides.append(f'''<article class="builder-slide" id="builder-{idx + 1}" role="group" aria-roledescription="资讯卡片" aria-label="第{idx + 1}张，共{len(data['builders'])}张" :class="{{'is-current':index==={idx}}}" :inert="index!=={idx}" :aria-hidden="index!=={idx}">
          <div class="builder-identity">{avatar}<h3>{esc(item['author'])}</h3><p>{esc(item.get('role',''))}</p>{publication_markup(publication_times['builders'][idx])}</div>
          <div class="builder-reading"><h4>{esc(item['one_sentence'])}</h4><details class="builder-details" x-data="{{expanded:false}}" @toggle="expanded=$el.open;detailsToggled($event)">{disclosure_button(f'builder-full-{idx+1}', '完整动态')}<div class="builder-full" id="builder-full-{idx+1}"><div class="builder-body">{paragraphs}</div>{links}</div></details></div>
        </article>''')
    podcast_markup = ''
    podcast = data.get('podcast')
    if podcast and podcast.get('paragraphs'):
        podcast_title = podcast.get('title_zh') or podcast['title']
        podcast_markup = f'''<section class="podcast-section" id="podcast" aria-labelledby="podcast-heading"><div class="section-heading"><h2 id="podcast-heading">播客精选</h2></div>
        <article class="podcast-card" aria-labelledby="podcast-title"><header class="podcast-header"><div class="podcast-mark" aria-hidden="true">ⅡıⅡı</div><div><p class="podcast-series">{esc(podcast.get('series',''))}</p>{publication_markup(publication_times['podcast'])}</div></header>
        <h3 id="podcast-title">{text(podcast_title)}</h3><details class="podcast-details" x-data="{{expanded:false}}" @toggle="expanded=$el.open">{disclosure_button('podcast-full', '完整访谈')}<div class="podcast-full" id="podcast-full">
        <p class="podcast-lead">{text(podcast.get('lead',''))}</p>
        <div class="podcast-body">{''.join(f'<p>{text(x)}</p>' for x in podcast['paragraphs'])}</div>{source_links(podcast['links'])}</div></details>
        </article></section>'''

    months = sorted({value[:7] for value in issue_dates})
    archive_month = months.index(data['date'][:7])
    month_labels = [f'{int(value[:4])} 年 {int(value[5:])} 月' for value in months]
    calendar_parts = []
    for month_idx, month in enumerate(months):
        year, number = map(int, month.split('-'))
        first_weekday, days = monthcalendar.monthrange(year, number)
        days_markup = '<span></span>' * first_weekday
        for day in range(1, days+1):
            value = f'{year:04d}-{number:02d}-{day:02d}'
            if value in issue_dates:
                selected = ' class="selected"' if value == data['date'] else ''
                days_markup += f'<button{selected} @click="location.href=\'{issue_href(value)}\'" aria-label="{year}年{number}月{day}日">{day}</button>'
            else:
                days_markup += f'<span class="calendar-unavailable" aria-label="{number}月{day}日无简报">{day}</span>'
        calendar_parts.append(f'<div class="calendar-grid" x-show="archiveMonth==={month_idx}"><span class="dow">一</span><span class="dow">二</span><span class="dow">三</span><span class="dow">四</span><span class="dow">五</span><span class="dow">六</span><span class="dow">日</span>{days_markup}</div>')
    calendar = ''.join(calendar_parts)
    position = issue_dates.index(data['date'])
    previous_date = issue_dates[position-1] if position else None
    next_date = issue_dates[position+1] if position+1 < len(issue_dates) else None
    def date_arrow(value, label, glyph):
        action = f' @click="location.href=\'{issue_href(value)}\'"' if value else ' disabled aria-disabled="true"'
        return f'<button class="date-arrow"{action} aria-label="{label}">{glyph}</button>'
    weekday_label = '星期' + '一二三四五六日'[issue_date.weekday()]
    date_controls = date_arrow(previous_date,'前一期','‹') + f'<button class="date-main" @click="state=\'archive\'" aria-label="切换日期"><b>{issue_date.month} 月 {issue_date.day} 日</b><small>{issue_date.year} · {weekday_label}</small></button>' + date_arrow(next_date,'后一期','›')

    page = r'''<!doctype html>
    <html lang="zh-CN">
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#fcf9f7"><title>__ISSUE_TITLE__</title>
    <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%2347403a'/%3E%3Ctext x='4' y='23' fill='white' font-size='20'%3EAI%3C/text%3E%3C/svg%3E">
    <script>
    (()=>{let theme='light';try{if(localStorage.getItem('daily-news-theme')==='dark')theme='dark';}catch{}document.documentElement.dataset.theme=theme;})();
    document.addEventListener('alpine:init', () => {
      Alpine.data('dailyNews', () => ({
        theme:document.documentElement.dataset.theme||'light', state:new URLSearchParams(location.search).get('state') || 'idle', active:'featured', archiveMonth:__ARCHIVE_MONTH__, archiveMonths:__ARCHIVE_MONTHS__, showBackToTop:false, sections:__NAV_IDS__, 
        sidebarPinned:innerWidth<=900||!['sidebar-collapsed','sidebar-preview'].includes(new URLSearchParams(location.search).get('state')),
        sidebarOpen:new URLSearchParams(location.search).get('state')==='sidebar-preview', sidebarHideTimer:null,
        init() { this.$watch('state',value=>{if(value!=='archive')this.hideSidebar();}); this.$nextTick(()=>{this.updateSection();if(document.readyState==='complete')requestAnimationFrame(()=>this.restoreAnchor());else window.addEventListener('load',()=>requestAnimationFrame(()=>this.restoreAnchor()),{once:true});}); },
        restoreAnchor() { const id=location.hash.slice(1); const target=id&&document.getElementById(id); if(target)target.scrollIntoView({block:'start',behavior:'instant'});this.updateSection(); },
        toggleTheme() { this.theme=this.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=this.theme;try{localStorage.setItem('daily-news-theme',this.theme);}catch{}document.querySelector('meta[name="theme-color"]').content=this.theme==='dark'?'#070908':'#fcf9f7'; },
        backToTop() { window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'}); },
        showSidebar() { clearTimeout(this.sidebarHideTimer); if(!this.sidebarPinned)this.sidebarOpen=true; },
        hideSidebar() { clearTimeout(this.sidebarHideTimer); if(!this.sidebarPinned)this.sidebarHideTimer=setTimeout(()=>{if(this.state!=='archive'&&!this.$refs.sidebar.matches(':hover')&&!this.$refs.sidebarEdge.matches(':hover'))this.sidebarOpen=false;},160); },
        toggleSidebar() { clearTimeout(this.sidebarHideTimer); this.sidebarPinned=!this.sidebarPinned; this.sidebarOpen=false; },
        destroy() { clearTimeout(this.sidebarHideTimer); },
        updateSection() { this.showBackToTop=window.scrollY>320; const visible=this.sections.filter(id=>document.getElementById(id)); this.active=(window.scrollY+window.innerHeight>=document.documentElement.scrollHeight-8)?(visible.at(-1)||''):(visible.filter(id=>document.getElementById(id).getBoundingClientRect().top<(innerWidth>900?90:Math.max(170,this.$refs.sidebar.getBoundingClientRect().bottom+80))).pop()||visible[0]||''); }
      }));
      Alpine.data('featuredSwitcher', () => ({
        count:__FEATURE_COUNT__, featureIndex:Math.max(0,Math.min(__FEATURE_COUNT__-1,Number(new URLSearchParams(location.search).get('state')?.match(/^feature-(\d)$/)?.[1])||0)),
        selectFeatured(next, focus=false) { this.featureIndex=Math.max(0,Math.min(this.count-1,next)); if(focus) this.$nextTick(()=>this.$refs.choices.querySelectorAll('[role="tab"]')[this.featureIndex].focus({preventScroll:true})); }
      }));
      Alpine.data('builderCarousel', () => ({
        index:Math.max(0,Math.min(__BUILDER_COUNT__-1,Number(new URLSearchParams(location.search).get('builder'))||0)), count:__BUILDER_COUNT__, settleTimer:null, trackWidth:0, ready:false, heightTarget:null,
        init() { this.$nextTick(() => { this.trackWidth=this.$refs.track.clientWidth; this.align(); this.fit(); requestAnimationFrame(()=>{this.ready=true;this.$dispatch('brief-layout-ready');}); this.resizeObserver=new ResizeObserver(()=>{const width=this.$refs.track.clientWidth;if(Math.abs(width-this.trackWidth)>1){this.trackWidth=width;this.align();}this.fit();}); this.resizeObserver.observe(this.$refs.track); Array.from(this.$refs.track.children).forEach(slide=>this.resizeObserver.observe(slide)); }); },
        isDetailsMoving(slide) { const details=slide?.querySelector('details'); return Boolean(details?._readingTimer); },
        fit() {
          const track=this.$refs.track, slide=track.children[this.heightTarget??this.index]; if(!slide)return;
          let height=Math.ceil(slide.getBoundingClientRect().height);
          const inset=parseFloat(getComputedStyle(track).paddingLeft)||0, mainLeft=track.scrollLeft+inset, mainRight=track.scrollLeft+track.clientWidth-inset;
          for(const visible of track.children){if(Math.min(mainRight,visible.offsetLeft+visible.offsetWidth)-Math.max(mainLeft,visible.offsetLeft)>1)height=Math.max(height,Math.ceil(visible.getBoundingClientRect().height));}
          const centered=Math.abs(slide.offsetLeft-(track.clientWidth-slide.offsetWidth)/2-track.scrollLeft)<2;
          const moving=this.heightTarget===null&&centered&&this.isDetailsMoving(slide)&&slide.querySelector('details')._directFollow;
          track.classList.toggle('is-unfolding',moving);
          if(Math.abs(track.clientHeight-height)>0.5)track.style.height=height+'px';
        },
        detailsToggled(event) {
          const details=event.target, slide=details.closest('.builder-slide'), track=this.$refs.track;
          clearTimeout(details._readingTimer);
          details._directFollow=track.classList.contains('is-unfolding')||Math.abs(track.clientHeight-slide.getBoundingClientRect().height)<3;
          const duration=matchMedia('(prefers-reduced-motion:reduce)').matches?0:parseFloat(getComputedStyle(details).getPropertyValue('--reading-motion'))||240;
          details._readingTimer=setTimeout(()=>{details._readingTimer=null;this.settle();},duration+32);
          this.fit(); requestAnimationFrame(()=>this.fit());
        },
        align() { this.heightTarget=null; const track=this.$refs.track, slide=track.children[this.index]; if(slide)track.scrollTo({left:slide.offsetLeft-(track.clientWidth-slide.offsetWidth)/2,top:0,behavior:'instant'}); },
        go(next) { const target=Math.max(0,Math.min(this.count-1,next)); const current=this.$refs.track.children[this.index].querySelector('details'); if(current?._readingTimer)current._directFollow=false; this.heightTarget=target; this.fit(); const track=this.$refs.track; const left=track.children[target].offsetLeft-(track.clientWidth-track.children[target].offsetWidth)/2; track.scrollTo({left,top:0,behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'}); if(Math.abs(track.scrollLeft-left)<2&&!this.isDetailsMoving(track.children[target]))this.settle(); },
        releaseTarget() { const track=this.$refs.track; if(this.heightTarget!==null)track.scrollTo({left:track.scrollLeft,top:0,behavior:'instant'}); this.heightTarget=null; this.fit(); },
        sync() { const track=this.$refs.track, center=track.scrollLeft+track.clientWidth/2;this.index=Array.from(track.children).reduce((best,slide,i,all)=>Math.abs(slide.offsetLeft+slide.offsetWidth/2-center)<Math.abs(all[best].offsetLeft+all[best].offsetWidth/2-center)?i:best,0); this.fit(); clearTimeout(this.settleTimer); this.settleTimer=setTimeout(()=>this.settle(),120); },
        settle() { clearTimeout(this.settleTimer); const track=this.$refs.track, target=this.heightTarget; if(target!==null){const slide=track.children[target], left=slide.offsetLeft-(track.clientWidth-slide.offsetWidth)/2;if(Math.abs(track.scrollLeft-left)>2||this.isDetailsMoving(slide))return;} this.heightTarget=null; this.fit(); },
        destroy() { this.resizeObserver?.disconnect(); clearTimeout(this.settleTimer); this.$refs.track.querySelectorAll('details').forEach(details=>clearTimeout(details._readingTimer)); }

      }));
    });
    </script>
    <script defer src="__ASSET_PREFIX__vendor/alpine.min.js"></script>
    <style>
    :root{color-scheme:light;--ink:#282422;--muted:#756e68;--accent:#47403a;--line:#d7d0ca;--paper:#fcf9f7;--wash:#f3eeea;--warm:#8b5d45;--reading-surface:#fffdfb;--reading-border:#d8d1ca;--reading-copy:#423b36;--reading-muted:#777069;--surface-hover:#f2ece6;--surface-active:#eae2db;--sidebar-surface:#f8f4f0;--image-mat:#f2ede8;--focus:#776454;--button-ink:#fffdfb;--ease:cubic-bezier(.22,.75,.3,1)}
    :root[data-theme=dark]{color-scheme:dark;--ink:#f4f3ee;--muted:#a2ada4;--accent:#a2e5f3;--line:#364038;--paper:#070908;--wash:#111613;--warm:#e7b990;--reading-surface:#101914;--reading-border:#3c5146;--reading-copy:#d2dcd2;--reading-muted:#aabdaf;--surface-hover:#18291e;--surface-active:#203428;--sidebar-surface:#0b0f0c;--image-mat:#0c100d;--focus:#99d7e3;--button-ink:#152519}
    .theme-toggle{display:inline-flex;align-items:center;justify-content:center;gap:7px;flex-shrink:0;min-width:44px;min-height:40px;padding:7px 12px;border:1px solid var(--line);border-radius:24px;background:var(--reading-surface);color:var(--ink);font-size:13px;line-height:1.4}.theme-toggle:hover{background:var(--surface-hover);border-color:var(--muted)}.theme-toggle:focus-visible{outline:2px solid var(--focus);outline-offset:4px}.theme-toggle svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.featured-topline h1{min-width:0}@media(max-width:480px){.theme-toggle{padding:8px;min-height:40px}.theme-toggle .theme-toggle-label{display:none}.featured-topline{gap:12px}}
    *{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:32px}body{margin:0;background:var(--paper);color:var(--ink);font-family:'PingFang SC','Hiragino Sans GB',sans-serif;font-size:16px;line-height:1.8;-webkit-font-smoothing:antialiased}a{color:inherit;text-decoration:none}button,input{font:inherit;color:inherit}button,a{touch-action:manipulation}button{cursor:pointer}button:disabled{cursor:default}button,a{transition:background .18s,color .18s,opacity .18s,transform .18s}button:active:not(:disabled){transform:translateY(1px)}:focus-visible{outline:3px solid var(--focus);outline-offset:4px}h1,h2,h3,h4,p,figure{margin:0}img{display:block;max-width:100%}[x-cloak]{display:none!important}::selection{background:var(--surface-active)}.shell{width:min(1160px,calc(100% - 96px));margin:auto}.brand{font-size:25px;font-weight:750;letter-spacing:-1px;display:flex;align-items:center;gap:10px}.brand-dot{width:9px;height:9px;border-radius:50%;background:var(--accent)}
    main{padding-top:34px}.section-heading{display:flex;justify-content:space-between;align-items:baseline;gap:24px;padding-bottom:20px;border-bottom:2px solid var(--ink)}.section-heading h1,.section-heading h2{font-size:26px;line-height:1.4;letter-spacing:-.5px}.section-heading>p{font-size:13px;color:var(--muted)}.story{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:58px;padding:36px 0 40px;border-bottom:1px solid var(--line);align-items:start}.story-meta{display:flex;gap:12px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:12px;line-height:1.5;margin-bottom:12px}.story-meta>span:first-child{color:var(--accent);font-weight:600}.story-meta>span+span:before{content:'·';margin-right:12px;color:var(--line)}.story h3{font-size:25px;line-height:1.48;letter-spacing:-.5px;font-weight:650;text-wrap:pretty}.story-core{font-size:16px;line-height:1.9;margin-top:17px}.judgment{margin-top:18px}.judgment h4,.verify h4{font-size:12px;color:var(--muted);font-weight:550;margin-bottom:4px}.judgment>p{font-size:15px;line-height:1.85;color:var(--reading-copy)}.personal-judgment{border-left:2px solid var(--warm);padding-left:16px}.personal-judgment h4{color:var(--warm)}.verify{margin-top:18px}.verify>p{font-size:15px;line-height:1.8;color:var(--reading-copy)}.fact-note{font-size:12px;line-height:1.8;color:var(--muted);margin-top:15px}.source-link{display:inline-flex;gap:9px;align-items:center;color:var(--accent);font-size:13px;font-weight:550;margin-top:14px;min-height:30px}.source-link:hover{text-decoration:underline}.story-figure{padding-top:3px;min-width:0}.picture{position:relative;border:0;padding:0;background:transparent;display:block;width:100%;text-align:left;border-radius:3px;overflow:hidden}.picture>img{width:100%;height:auto}.picture-zoom{position:absolute;bottom:10px;right:10px;padding:4px 9px;background:rgba(252,249,247,.96);border-radius:3px;color:var(--accent);font-size:11px;opacity:0;transition:opacity .18s}.picture:hover .picture-zoom,.picture:focus-visible .picture-zoom{opacity:1}.story-figure figcaption{font-size:12px;color:var(--muted);line-height:1.8;margin-top:11px}.diagram .picture>img{width:auto;max-height:430px;margin:auto}.tall .picture>img{width:auto;max-height:550px;margin:auto}.terminal .story-figure{grid-column:1/-1;width:100%;display:grid;grid-template-columns:minmax(0,1fr) 210px;gap:26px;align-items:end;padding-top:0;margin-top:0}.terminal .story-copy{grid-column:1/-1;max-width:780px}.terminal{gap:20px}.terminal .picture{width:100%}.terminal .story-figure figcaption{margin:0 0 8px}.terminal .picture>img{max-height:none;object-fit:contain}.personal-section{margin-top:50px}.personal-section .section-heading h2{color:var(--accent)}.text-section{margin-top:50px}.text-list{list-style:none;padding:0;margin:0}.text-list li{display:grid;grid-template-columns:84px minmax(0,1fr);gap:24px;padding:20px 0;border-bottom:1px solid var(--line)}.quick-category{font-size:12px;color:var(--muted);padding-top:4px}.text-list a{font-size:18px;line-height:1.6;font-weight:600;display:inline}.text-list a>span{font-size:12px;color:var(--muted);margin-left:9px}.text-list a:hover{color:var(--accent)}.text-list p{font-size:14px;line-height:1.8;color:var(--muted);margin-top:5px}.unselected{margin-top:22px;border-bottom:1px solid var(--line)}.unselected>summary{padding:14px 0;min-height:54px;list-style:none;display:flex;align-items:center;gap:15px;cursor:pointer;font-size:14px}.unselected>summary::-webkit-details-marker{display:none}.unselected>summary>span{font-size:12px;color:var(--muted)}.unselected>summary>i{font-style:normal;font-size:22px;margin-left:auto;transition:transform .2s}.unselected[open]>summary>i{transform:rotate(45deg)}
    .builders-section{margin-top:52px}.builders-heading{border-bottom:0;padding-bottom:0;align-items:center}.builders-heading>div>p{color:var(--muted);font-size:13px;margin-top:7px}.builder-track{--card-inset:96px;display:flex;position:relative;gap:20px;padding-inline:var(--card-inset);scroll-padding-inline:var(--card-inset);overflow-x:auto;overflow-y:hidden;scroll-snap-type:x mandatory;scrollbar-width:none;overscroll-behavior-x:contain;align-items:flex-start;margin-top:23px;height:400px;border-radius:var(--reading-radius)}.builder-track.is-ready{transition:height .22s var(--ease)}.builder-track.is-unfolding{transition:none}.builder-track::-webkit-scrollbar{display:none}.builder-slide{flex:0 0 100%;min-width:0;scroll-snap-align:center;scroll-snap-stop:always;display:block;padding:22px 24px;background:var(--reading-surface);border:1px solid var(--reading-border);border-radius:var(--reading-radius);align-self:flex-start;grid-template-rows:auto;opacity:.55;transition:opacity .18s var(--ease),border-color .18s}.builder-slide.is-current{opacity:1;border-color:var(--muted)}.builder-identity{display:grid;grid-template-columns:44px minmax(0,1fr) auto;column-gap:12px;row-gap:2px;align-items:center;margin-bottom:16px;min-width:0}.builder-identity>.avatar{width:44px;height:44px;grid-row:1/3}.builder-identity>h3{grid-column:2;grid-row:1;margin:0}.builder-identity>p{grid-column:2;grid-row:2;margin:0}.builder-identity>.identity-time{grid-column:3;grid-row:1/3;margin:0;justify-content:flex-end;text-align:right}.identity-time{display:flex;flex-wrap:wrap;gap:3px 9px;margin-top:12px;color:var(--reading-muted);font-size:13px;line-height:1.7;font-variant-numeric:tabular-nums}.identity-time span{white-space:nowrap}.avatar{width:64px;height:64px;border-radius:50%;object-fit:cover;border:1px solid var(--reading-border);background:var(--reading-surface)}.builder-identity h3{font-size:18px;line-height:1.4;letter-spacing:-.3px;font-weight:600;color:var(--ink)}.builder-identity>p{font-size:13px;color:var(--reading-muted)}.builder-reading h4{font-family:Georgia,'Songti SC','STSong',serif;font-size:23px;line-height:1.55;font-weight:600;letter-spacing:-.3px;color:var(--ink);text-wrap:pretty;line-break:strict;overflow-wrap:anywhere}.builder-reading{min-width:0}.builder-full{padding-top:16px}.builder-body{margin:0;min-width:0}.builder-body>p{font-size:15px;line-height:1.9;color:var(--reading-copy);margin-top:14px}.builder-body>p:first-child{margin-top:0}.reading-sources{margin-top:20px;font-size:14px;line-height:1.85;color:var(--reading-muted)}.reading-sources>a{color:var(--accent);text-decoration:underline;text-decoration-color:var(--muted);text-underline-offset:4px}.reading-sources>a:hover{text-decoration-color:currentColor}.reading-sources>a:focus-visible{outline:2px solid var(--accent);outline-offset:4px}.podcast-mark{width:76px;height:76px;display:grid;place-items:center;background:var(--wash);color:var(--ink);border-radius:8px;font-size:29px;letter-spacing:1px}.podcast-title{font-size:13px;line-height:1.8;color:var(--muted);margin-top:14px}.carousel-dots{display:flex;justify-content:center;gap:0;margin-top:8px}.carousel-dots button{width:32px;max-width:calc(100% / __BUILDER_COUNT__);height:40px;border:0;background:transparent;display:grid;place-items:center;padding:0}.carousel-dots button:after{content:'';width:6px;height:6px;border-radius:50%;background:var(--line);transition:width .22s,background .22s}.carousel-dots button.is-current:after{width:20px;border-radius:4px;background:var(--accent)}.carousel-status{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
    .site-footer{border-top:1px solid var(--line);padding:25px 0 38px;color:var(--muted);font-size:11px;line-height:1.9}.footer-row{display:flex;justify-content:space-between;gap:30px}.empty-banner{padding:16px 20px;background:var(--wash);border:1px solid var(--line);margin-bottom:25px;border-radius:4px;display:flex;justify-content:space-between;gap:20px;align-items:center}.empty-banner h2{font-size:18px}.empty-banner p{font-size:13px;color:var(--muted)}.empty-banner button{border:1px solid var(--line);border-radius:4px;background:var(--reading-surface);padding:8px 12px;font-size:13px}.overlay{position:fixed;inset:0;z-index:40;background:rgba(40,34,29,.35);backdrop-filter:blur(4px);padding:105px 24px 30px;display:flex;align-items:flex-start;justify-content:center}.panel{width:min(440px,100%);max-height:calc(100dvh - 150px);overflow:auto;background:var(--reading-surface);border-radius:10px;padding:24px 28px;box-shadow:0 20px 80px rgba(60,45,32,.08)}.panel-head{display:flex;justify-content:space-between;align-items:center;gap:15px}.panel-head h2{font-size:21px}.panel-close{width:40px;height:40px;border:0;background:transparent;border-radius:50%;font-size:24px;color:var(--muted)}.panel-close:hover{background:var(--wash)}.calendar-top{display:flex;justify-content:space-between;gap:12px;margin-top:16px;font-size:14px}.calendar-top span{font-size:12px;color:var(--muted)}.calendar-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin:17px 0}.calendar-grid>span,.calendar-grid>button{height:40px;display:grid;place-items:center;border:0;background:transparent;padding:0;font-size:14px;border-radius:5px}.calendar-grid .dow{color:var(--muted);font-size:12px}.calendar-grid button{color:var(--muted)}.calendar-grid button:hover{background:var(--wash)}.calendar-grid button.selected{background:var(--accent);color:white;font-weight:650}.calendar-note{font-size:13px;color:var(--muted);padding-top:12px;border-top:1px solid var(--line)}.panel-action{width:100%;margin-top:16px;background:var(--accent);color:white;border:0;border-radius:5px;padding:10px 12px;font-size:14px}.image-overlay{padding:25px;align-items:center}.image-panel{width:min(1200px,100%);max-height:calc(100dvh - 50px);overflow:auto;padding:15px;background:var(--reading-surface);border-radius:8px}.image-panel .panel-head{padding:0 8px 10px}.image-panel h2{font-size:15px;font-weight:500;line-height:1.6}.image-panel img{max-width:100%;max-height:calc(100dvh - 160px);width:auto;height:auto;margin:auto;object-fit:contain}
    .reading-content{overflow-anchor:none}.builders-section{overflow-anchor:none}.site-footer{overflow-anchor:none}.builder-track{overflow-anchor:none}
    #story-1 .picture{aspect-ratio:1160/750}#story-1 .picture>img{position:absolute;width:165.52%;max-width:none;height:auto;left:-10%;top:-22.667%}
    .story-meta{font-size:13px;margin-bottom:11px;gap:14px}.story-meta>span.story-name{font-size:15px;font-weight:650;color:var(--accent)}.story-meta>span+span:before{margin-right:14px}.story h3{font-size:32px;line-height:1.4;font-weight:750;letter-spacing:-.65px}.story-core{font-size:17px;line-height:1.9}.judgment h4,.verify h4{font-size:14px;line-height:1.6;font-weight:650;color:var(--accent);margin-bottom:7px}.judgment>p,.verify>p{font-size:16px;line-height:1.85;color:var(--muted)}.personal-judgment h4{color:var(--warm)}.fact-note{font-size:13px;line-height:1.85;color:var(--muted);margin-top:17px}.fact-note>b{font-weight:650;margin-right:10px}.source-link{font-size:14px}.text-list .quick-category{font-size:13px}.text-list a{font-size:19px}.text-list p{font-size:15px;color:var(--muted)}.story-figure figcaption{font-size:13px;color:var(--muted)}.takeaway{font-size:19px;line-height:1.7;font-weight:600;color:var(--accent);margin-top:17px}.story-points{list-style:none;padding:0;margin:15px 0 0}.story-points li{font-size:17px;line-height:1.85;position:relative;padding-left:15px;margin-top:10px}.story-points li:before{content:'';position:absolute;width:4px;height:4px;left:0;top:14px;background:var(--muted);border-radius:50%}.story-points strong{font-weight:650}.story{padding-top:40px;padding-bottom:42px}.verify-line{font-size:15px;line-height:1.85;color:var(--muted);margin-top:17px}.verify-line strong{font-size:13px;font-weight:600;color:var(--muted);margin-right:10px}
    .builder-facts{list-style:none;padding:0;margin:0}.builder-facts>li{font-size:15px;line-height:1.9;color:var(--reading-copy);position:relative;padding-left:17px;margin-top:14px}.builder-facts>li:first-child{margin-top:0}.builder-facts>li:before{content:'';width:4px;height:4px;position:absolute;left:0;top:14px;border-radius:50%;background:var(--muted)}
    .story-body{margin-top:17px}.story-body>p{font-size:17px;line-height:1.85;margin-top:10px}.story-body>p:first-child{margin-top:0}
    @media(min-width:1500px){.shell{width:min(1200px,calc(100% - 120px))}.story{grid-template-columns:minmax(0,1fr) 410px;gap:65px}}
    @media(max-width:1050px){.shell{width:calc(100% - 48px)}.story{grid-template-columns:minmax(0,1fr) 310px;gap:34px}.story h3{font-size:23px}.terminal .story-copy{max-width:none}}
    @media(max-width:720px){html{scroll-padding-top:125px}.shell{width:calc(100% - 36px)}.brand{font-size:20px;gap:7px}.brand-dot{width:7px;height:7px}main{padding-top:25px}.section-heading{gap:12px;padding-bottom:15px}.section-heading h1,.section-heading h2{font-size:23px}.section-heading>p{font-size:11px;text-align:right}.story{grid-template-columns:1fr;gap:22px;padding:26px 0 29px}.story h3{font-size:23px}.story-core{font-size:15px;line-height:1.9;margin-top:14px}.story-figure{padding:0}.story-figure figcaption{font-size:11px}.diagram .picture>img{max-height:390px}.tall .picture>img{max-height:580px}.terminal .story-copy,.terminal .story-figure{grid-column:auto}.terminal .story-figure{display:block;margin:0}.terminal .story-figure figcaption{margin-top:10px}.personal-section,.text-section{margin-top:35px}.text-list li{grid-template-columns:1fr;gap:4px;padding:17px 0}.quick-category{padding:0;font-size:11px}.text-list a{font-size:17px}.text-list p{font-size:13px}.builders-section{margin-top:35px;margin-right:0}.builders-heading{align-items:flex-start}.builders-heading>div>p{font-size:11px}.builder-track{--card-inset:30px;gap:10px;margin-top:18px}.builder-slide{padding:18px 16px}.builder-identity{grid-template-columns:40px minmax(0,1fr);column-gap:10px;margin-bottom:16px}.builder-identity>.avatar{width:40px;height:40px}.avatar,.podcast-mark{width:52px;height:52px;grid-row:span 2}.podcast-mark{font-size:22px}.builder-identity h3{font-size:16px}.builder-identity>.identity-time{grid-column:2;grid-row:3;justify-content:flex-start;text-align:left;font-size:12px;gap:2px 8px}.builder-reading h4{font-size:20px}.podcast-title{font-size:12px}.footer-row{display:block}.overlay{padding:80px 18px 25px}.panel{padding:20px;max-height:calc(100dvh - 105px)}.image-overlay{padding:12px}.image-panel{padding:10px}.empty-banner{display:block}.empty-banner button{margin-top:12px}}
    @media(max-width:1050px) and (min-width:721px){.story h3{font-size:29px}.story-points li{font-size:16px}}
    @media(max-width:720px){.story h3{font-size:27px;line-height:1.4}.story-meta>span.story-name{font-size:14px}.story-points li{font-size:16px;line-height:1.9}.story-body>p{font-size:16px}.takeaway{font-size:17px}.judgment>p,.verify>p{font-size:15px}}
    /* Warm paper reading palette: the same roles cover all editions and cards. */
    :root{--reading-radius:12px;--reading-motion:240ms}
    body{background:var(--paper);color:var(--ink)}.shell{width:min(1260px,calc(100% - 96px))}.brand{font-family:Georgia,'Songti SC',serif;font-size:31px;font-weight:600;letter-spacing:-.8px}.brand-dot{background:var(--accent);width:7px;height:7px}.section-heading{border-bottom:1px solid var(--line)}.section-heading h1,.section-heading h2{font-size:26px;color:var(--ink)}.section-heading>p{font-size:14px}main{padding-top:30px}.featured-topline{display:flex;align-items:baseline;justify-content:space-between;gap:24px;border-bottom:1px solid var(--line);margin-bottom:25px;padding-bottom:18px}.featured-topline h1{font-size:24px;line-height:1.5;letter-spacing:.4px;font-weight:550;overflow-wrap:anywhere}.featured-topline h1>span{display:inline-block;max-width:100%}.featured-topline>span{color:var(--muted);font-size:14px}.featured-showcase{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:36px;align-items:start}.featured-display{display:grid;min-width:0}.feature-panel{grid-area:1/1;visibility:hidden;opacity:0;pointer-events:none;min-width:0;transition:opacity .18s ease}.feature-panel.is-active{visibility:visible;opacity:1;pointer-events:auto}.feature-picture{position:relative;width:100%;height:420px;display:flex;align-items:center;justify-content:center;padding:0;border:0;background:var(--image-mat);overflow:hidden}.feature-picture>img{width:100%;height:100%;object-fit:contain;max-width:100%}.feature-picture>span{position:absolute;bottom:14px;right:14px;background:var(--reading-surface);border:1px solid var(--reading-border);color:var(--ink);font-size:13px;padding:5px 10px;opacity:0;transition:opacity .18s}.feature-picture:hover>span,.feature-picture:focus-visible>span{opacity:1}.muse-panel .feature-picture{height:420px}.muse-panel .feature-picture>img{position:absolute;width:165.52%;max-width:none;height:auto;left:-10%;top:50%;transform:translateY(-50%);object-fit:initial}.feature-panel.diagram .feature-picture{background:var(--image-mat)}.feature-panel.diagram .feature-picture>img{width:auto;height:100%;max-width:100%;object-fit:contain}.feature-panel h2{font-family:Georgia,'Songti SC','STSong',serif;font-size:41px;font-weight:650;line-height:1.38;letter-spacing:-.8px;margin:25px 0 18px;text-wrap:pretty;color:var(--ink)}.feature-body{max-width:820px}.feature-body>p{font-size:18px;line-height:1.85;margin-top:12px;color:var(--reading-copy)}.feature-body>.feature-judgment{border-left:2px solid var(--focus);padding-left:16px;margin-top:20px;color:var(--reading-copy);font-size:17px}.feature-panel>.source-link{margin-top:15px;font-size:15px;color:var(--accent)}.featured-index{border-left:1px dashed var(--line);padding-left:25px;position:sticky;top:155px}.featured-index h2{font-size:17px;line-height:1.5;letter-spacing:.4px;font-weight:550;padding-bottom:15px;border-bottom:1px solid var(--line)}.feature-choice{width:100%;display:grid;grid-template-columns:22px minmax(0,1fr);gap:10px;text-align:left;align-items:start;background:transparent;border:0;border-bottom:1px dashed var(--line);padding:22px 8px 23px 0;color:var(--ink);min-height:128px}.feature-choice:hover{background:var(--surface-hover)}.feature-choice.is-current{background:var(--surface-active)}.choice-number{font-family:Georgia,serif;font-size:16px;color:var(--muted);padding-top:1px}.choice-copy{display:block;min-width:0}.choice-copy>b{font-size:16px;font-weight:600;line-height:1.4;display:block;color:var(--reading-copy);margin-bottom:8px}.choice-copy>span{font-family:'Songti SC','STSong',serif;font-size:21px;font-weight:600;line-height:1.55;display:block;text-wrap:pretty}.choice-arrow{display:none}.is-current .choice-number,.is-current .choice-copy>b{color:var(--accent)}.is-current .choice-arrow{opacity:1}.feature-choice:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.personal-section{margin-top:58px}.personal-section .section-heading h2{color:var(--ink)}.personal-section .takeaway{color:var(--reading-copy);font-size:19px}.story-body>p,.judgment>p,.verify-line{color:var(--reading-copy);font-size:17px}.personal-judgment h4{color:var(--warm)}.personal-judgment{border-color:var(--warm)}.verify-line strong{color:var(--muted);font-size:14px}.source-link{color:var(--accent)}.text-list p{color:var(--reading-copy);font-size:16px}.quick-category{color:var(--muted)!important}.text-list a{color:var(--ink);font-size:19px}.text-list a:hover{color:var(--accent)}.text-list li{border-color:var(--line)}.text-list a>span{color:var(--reading-copy)}.unselected{border-color:var(--line)}.unselected>summary{font-size:16px;color:var(--ink)}.unselected>summary>span{font-size:14px;color:var(--muted)}.carousel-dots button:after{background:var(--muted)}.carousel-dots button.is-current:after{background:var(--accent)}.builders-heading>div>p{font-size:15px}.site-footer{color:var(--muted);font-size:13px;border-color:var(--line)}.panel,.image-panel{color:var(--ink)}.panel h2{color:var(--ink)}.panel .calendar-top span,.panel .calendar-note,.panel .calendar-grid .dow,.panel.panel input{color:var(--ink);background:var(--wash)}.panel-action,.calendar-grid button.selected{color:var(--button-ink);background:var(--accent)}.panel-close{color:var(--muted)}.panel-close:hover{background:var(--wash)}.empty-banner{color:var(--ink)}.empty-banner p{color:var(--muted)}.image-panel h2{color:var(--ink)}.story-figure .picture-zoom{background:var(--reading-surface);color:var(--ink)}
    @keyframes featured-arrive{from{opacity:.35;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}.featured-showcase{animation:featured-arrive .6s ease-out both}@media(prefers-reduced-motion:reduce){.featured-showcase{animation:none}.feature-panel{transition:none}}
    .feature-title-link{color:inherit;text-decoration:none;text-underline-offset:7px;text-decoration-thickness:1px}.feature-title-link:hover{text-decoration:underline;text-decoration-color:var(--accent)}.feature-title-link:focus-visible{outline:2px solid var(--accent);outline-offset:5px}
    main{padding-top:20px}.featured-topline{margin-bottom:20px;padding-bottom:13px}.feature-choice{padding-top:14px;padding-bottom:16px;min-height:108px}.choice-copy>span{font-size:19px;line-height:1.45}.choice-copy>b{margin-bottom:6px}
    @media(min-width:1600px){.shell{width:min(1360px,calc(100% - 120px))}.featured-showcase{grid-template-columns:minmax(0,1fr) 320px;gap:40px}.feature-picture,.muse-panel .feature-picture{height:470px}.feature-panel h2{font-size:45px}}
    @media(max-width:1100px) and (min-width:721px){.shell{width:calc(100% - 48px)}.featured-showcase{grid-template-columns:minmax(0,1fr) 255px;gap:25px}.featured-index{padding-left:18px}.choice-copy>span{font-size:19px}.feature-panel h2{font-size:34px}.feature-picture,.muse-panel .feature-picture{height:345px}.feature-body>p{font-size:17px}.feature-choice{padding-top:18px;padding-bottom:18px}.feature-choice .choice-number{display:none}.feature-choice{grid-template-columns:minmax(0,1fr) 14px}}
    @media(max-width:720px){.shell{width:calc(100% - 36px)}.brand{font-size:23px}.featured-topline{margin-bottom:18px;padding-bottom:13px}.featured-topline h1{font-size:23px}.featured-topline>span{font-size:12px}.featured-showcase{display:flex;flex-direction:column;gap:23px}.featured-index{order:0;position:static;border-left:0;padding:0;width:100%}.featured-index h2{display:none}.featured-choices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.feature-choice{display:block;min-height:0;border:1px solid var(--line);padding:12px;text-align:left}.choice-number,.choice-arrow{display:none}.choice-copy>b{font-size:14px;margin:0}.choice-copy>span{font-size:15px;line-height:1.5;margin-top:5px}.feature-choice.is-current{border-color:var(--focus)}.featured-display{order:1;width:100%}.feature-picture,.muse-panel .feature-picture{height:240px}.feature-panel h2{font-size:29px;line-height:1.45;margin:20px 0 15px}.feature-body>p{font-size:16px}.feature-body>.feature-judgment{font-size:16px}.personal-section .takeaway{font-size:17px}.story-body>p,.judgment>p,.verify-line{font-size:16px}.builders-heading>div>p{font-size:12px}.site-footer{font-size:12px}.featured-index .feature-choice:hover{background:var(--surface-hover)}}

    :root{--sidebar-width:192px}
    .reading-sidebar{position:fixed;inset:0 auto 0 0;width:var(--sidebar-width);padding:35px 21px;z-index:20;background:var(--sidebar-surface);border-right:1px solid var(--line);display:flex;flex-direction:column;overflow-y:auto}
    .reading-sidebar .brand{font-size:28px;letter-spacing:-.6px;gap:9px;white-space:nowrap;line-height:1.5}
    .reading-sidebar .date-control{display:grid;grid-template-columns:24px minmax(0,1fr) 24px;align-items:center;gap:0;margin-top:37px;padding-top:23px;border-top:1px solid var(--line)}
    .reading-sidebar .date-control button{border:0;background:transparent;padding:0;color:var(--ink)}
    .reading-sidebar .date-arrow{width:24px;height:48px;font-size:24px;color:var(--muted)}
    .reading-sidebar .date-main{display:flex;flex-direction:column;align-items:center;gap:4px;min-height:52px;justify-content:center;border-radius:4px}
    .reading-sidebar .date-main b{font-size:16px;font-weight:550;white-space:nowrap;font-variant-numeric:tabular-nums}
    .reading-sidebar .date-main small{font-size:11px;color:var(--muted);white-space:nowrap}
    .reading-sidebar .date-control button:hover{color:var(--accent);background:var(--surface-hover)}
    .reading-nav{display:flex;flex-direction:column;gap:8px;margin-top:37px}
    .reading-nav a{position:relative;display:flex;align-items:center;gap:11px;padding:13px 9px;min-height:50px;font-size:15px;line-height:1.5;color:var(--muted);white-space:nowrap}
    .reading-nav a>span{font-family:Georgia,serif;font-size:13px;color:var(--muted);width:18px;flex-shrink:0}
    .reading-nav a:hover{color:var(--ink);background:var(--surface-hover)}
    .reading-nav a.active{color:var(--accent);background:var(--surface-active)}
    .reading-nav a.active:before{content:'';position:absolute;width:2px;inset:11px auto 11px 0;background:var(--accent)}
    .reading-nav a.active>span{color:var(--accent)}
    .reading-content{margin-left:var(--sidebar-width);min-width:0}
    .reading-content>.shell,.reading-content .site-footer>.shell{width:min(1260px,calc(100% - 128px))}
    .reading-content>main{padding-top:36px}
    .featured-showcase{grid-template-columns:minmax(0,1fr) 264px;gap:32px}
    .featured-index{top:32px;padding-left:22px}
    .feature-panel h2{font-size:39px}

    @media(min-width:1600px){.feature-panel h2{font-size:43px}.featured-showcase{grid-template-columns:minmax(0,1fr) 300px;gap:36px}}
    @media(min-width:901px) and (max-width:1300px){:root{--sidebar-width:180px}.reading-sidebar{padding:29px 16px}.reading-content>.shell,.reading-content .site-footer>.shell{width:calc(100% - 128px)}.featured-showcase{grid-template-columns:minmax(0,1fr) 264px;gap:26px}.featured-index{padding-left:18px}.feature-panel h2{font-size:35px}.feature-picture,.muse-panel .feature-picture{height:360px}.choice-copy>span{font-size:18px}}
    @media(max-width:900px){html{scroll-padding-top:126px}.reading-sidebar{position:sticky;inset:auto;top:0;width:100%;padding:14px 20px 0;display:grid;grid-template-columns:1fr auto;gap:8px;border-right:0;border-bottom:1px solid var(--line);overflow:visible}.reading-sidebar .brand{font-size:25px}.reading-sidebar .date-control{margin:0;padding:0;border:0;grid-template-columns:24px 92px 24px}.reading-sidebar .date-main{min-height:45px}.reading-sidebar .date-main b{font-size:14px}.reading-sidebar .date-main small{font-size:10px}.reading-nav{grid-column:1/-1;flex-direction:row;justify-content:space-between;gap:7px;margin:0;overflow-x:auto}.reading-nav a{padding:10px 2px;min-height:43px;font-size:13px;gap:5px}.reading-nav a>span{display:none}.reading-nav a.active{background:transparent}.reading-nav a.active:before{width:auto;height:2px;inset:auto 0 0}.reading-content{margin-left:0}.reading-content>.shell,.reading-content .site-footer>.shell{width:auto;margin-left:18px;margin-right:18px}.reading-content>main{padding-top:25px}.feature-panel h2{font-size:29px}.featured-index{top:155px}.featured-showcase{gap:23px}}



    .sidebar-head{display:flex;align-items:center;justify-content:space-between;gap:7px}
    .reading-sidebar .brand{font-size:26px}
    .sidebar-toggle{width:28px;height:32px;flex-shrink:0;display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:4px;background:transparent;color:var(--muted);padding:0}
    .sidebar-toggle:hover{color:var(--accent);background:var(--surface-hover)}
    .sidebar-edge{display:none}
    @media(min-width:901px){
    .reading-sidebar{transition:transform .22s var(--ease),visibility 0s;will-change:transform}
    .reading-content{transition:margin-left .22s var(--ease)}
    .sidebar-collapsed .reading-sidebar{transform:translateX(-100%);visibility:hidden;transition:transform .22s var(--ease),visibility 0s .22s}
    .sidebar-collapsed .reading-content{margin-left:0}
    .sidebar-collapsed .sidebar-edge{display:block;position:fixed;inset:0 auto 0 0;width:8px;padding:0;border:0;background:transparent;z-index:31;cursor:e-resize}
    .sidebar-edge:focus-visible{outline:0;border-left:2px solid var(--accent)}
    .sidebar-collapsed.sidebar-peeking .reading-sidebar{transform:translateX(0);visibility:visible;transition:transform .22s var(--ease),visibility 0s;box-shadow:14px 0 35px rgba(60,45,32,.15)}
    }
    @media(max-width:900px){.sidebar-toggle{display:none}.sidebar-head{display:block}}

    .podcast-section{margin-top:48px}.podcast-card{width:min(940px,100%);margin:24px auto 0;padding:22px 24px;background:var(--reading-surface);border:1px solid var(--reading-border);border-radius:var(--reading-radius)}.podcast-header{display:flex;align-items:center;gap:12px;margin-bottom:16px}.podcast-header .podcast-mark{width:44px;height:44px;font-size:20px;flex-shrink:0}.podcast-series{font-size:14px;color:var(--muted)}.podcast-header .identity-time{margin-top:5px}.podcast-card h3{font-family:Georgia,'Songti SC',serif;font-size:23px;font-weight:600;line-height:1.55;overflow-wrap:anywhere}.podcast-card h3 a:hover{text-decoration:underline;text-underline-offset:5px}.podcast-lead{font-family:'Songti SC',serif;font-size:18px;line-height:1.7;color:var(--reading-copy);margin-top:20px}.podcast-body{font-size:15px;line-height:1.9;color:var(--reading-copy);margin-top:20px}.podcast-body p+p{margin-top:16px}@media(max-width:720px){.podcast-section{margin-top:35px}.podcast-card{padding:22px 20px}.podcast-card h3{font-size:20px}.podcast-header{gap:12px}.podcast-header .podcast-mark{width:40px;height:40px;font-size:18px}.podcast-series{font-size:13px}.podcast-lead{font-size:17px}}
    .builder-details,.podcast-details{min-width:0}.builder-details>summary,.podcast-details>summary{list-style:none;cursor:pointer}.builder-details>summary::-webkit-details-marker,.podcast-details>summary::-webkit-details-marker{display:none}.reading-toggle{display:grid;place-items:center;width:44px;height:44px;padding:0;margin:14px 0 0 auto;border:1px solid var(--reading-border);border-radius:50%;background:var(--surface-hover);color:var(--accent);transition:background .18s var(--ease),border-color .18s var(--ease),transform .18s var(--ease)}.reading-toggle:hover{background:var(--surface-active);border-color:var(--focus)}.reading-toggle:active{transform:scale(.94)}.reading-toggle:focus-visible{outline:2px solid var(--accent);outline-offset:4px}.reading-toggle>svg{display:block;pointer-events:none}.toggle-vertical{transform-origin:12px 12px;transition:transform .18s var(--ease)}details[open]>.reading-toggle{background:var(--surface-active);border-color:var(--focus)}details[open]>.reading-toggle .toggle-vertical{transform:scaleY(0)}.podcast-full{padding-top:1px}.builder-full,.podcast-full{margin-top:16px;border-top:1px dashed var(--reading-border)}
    @supports(interpolate-size:allow-keywords){.builder-details,.podcast-details{interpolate-size:allow-keywords}.builder-details::details-content,.podcast-details::details-content{display:flow-root;block-size:0;content-visibility:hidden;overflow:clip;transition:block-size var(--reading-motion) var(--ease),content-visibility var(--reading-motion) allow-discrete}.builder-details[open]::details-content,.podcast-details[open]::details-content{block-size:auto;content-visibility:visible}}
    .back-to-top{position:fixed;right:14px;bottom:22px;z-index:18;display:grid;place-items:center;width:44px;height:44px;padding:0;border:1px solid var(--reading-border);border-radius:50%;background:var(--reading-surface);color:var(--accent);box-shadow:0 3px 15px rgba(60,45,32,.08)}
    .back-to-top:hover{background:var(--surface-active);border-color:var(--accent);transform:translateY(-2px)}
    .back-to-top:focus-visible{outline:2px solid var(--accent);outline-offset:4px}
    @media(max-width:480px){.reading-content>.shell,.reading-content .site-footer>.shell{margin-left:28px;margin-right:28px}.back-to-top{width:28px;height:44px;right:0;border-radius:8px 0 0 8px;border-right:0}.back-to-top svg{width:18px;height:18px}.section-heading{flex-direction:column;align-items:flex-start;gap:6px}.section-heading>p{text-align:left}}
    @media(max-width:900px){.back-to-top{width:28px;height:44px;right:0;bottom:18px;border-radius:8px 0 0 8px;border-right:0}.back-to-top svg{width:18px;height:18px}.builders-heading>div>p{font-size:12px}}
    @media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*:before,*:after,.builder-details::details-content,.podcast-details::details-content{transition:none!important;animation:none!important}}
    </style></head>
    <body id="top"><div class="daily-app" x-data="dailyNews" :class="{'sidebar-collapsed':!sidebarPinned,'sidebar-peeking':sidebarOpen&&!sidebarPinned}" @brief-layout-ready.window="restoreAnchor()" @scroll.window.throttle.100ms="updateSection()" @resize.window.debounce.120ms="if(innerWidth<=900){sidebarPinned=true;sidebarOpen=false}" @keydown.escape.window="state='idle';if(!sidebarPinned)sidebarOpen=false">
    <button id="sidebar-edge" class="sidebar-edge" x-ref="sidebarEdge" :disabled="sidebarPinned" :tabindex="sidebarPinned?-1:0" aria-label="从左侧边缘展开导航" aria-controls="reading-sidebar" :aria-expanded="sidebarPinned||sidebarOpen" @mouseenter="showSidebar()" @mouseleave="hideSidebar()" @focus="showSidebar()" @blur="hideSidebar()" @click="showSidebar()"></button><aside id="reading-sidebar" class="reading-sidebar" x-ref="sidebar" aria-label="阅读导航" :aria-hidden="!sidebarPinned&&!sidebarOpen" :inert="!sidebarPinned&&!sidebarOpen" @mouseenter="showSidebar()" @mouseleave="hideSidebar()" @focusin="showSidebar()" @focusout="if(!$el.contains($event.relatedTarget))hideSidebar()"><div class="sidebar-head"><a class="brand" href="#top"><span class="brand-dot"></span>每日 AI</a><button class="sidebar-toggle" @click="toggleSidebar()" :aria-label="sidebarPinned?'收起侧栏':'固定展开侧栏'" aria-controls="reading-sidebar" :aria-expanded="sidebarPinned||sidebarOpen"><svg viewBox="0 0 20 20" width="19" height="19" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true"><rect x="2" y="3" width="16" height="14" rx="1.8"/><path d="M7 3v14"/><path :d="sidebarPinned?'M13 7l-3 3 3 3':'M11 7l3 3-3 3'"/></svg></button></div><div class="date-control">__DATE_CONTROLS__</div><nav class="reading-nav" aria-label="本期目录"><a href="#featured" @click="active='featured'" :class="{active:active==='featured'}" :aria-current="active==='featured'?'location':null"><span aria-hidden="true">01</span>本期重点</a><a href="#builders" @click="active='builders'" :class="{active:active==='builders'}" :aria-current="active==='builders'?'location':null"><span aria-hidden="true">02</span>Builders 动态</a><a href="#personal" @click="active='personal'" :class="{active:active==='personal'}" :aria-current="active==='personal'?'location':null"><span aria-hidden="true">03</span>与我相关</a><a href="#quick" @click="active='quick'" :class="{active:active==='quick'}" :aria-current="active==='quick'?'location':null"><span aria-hidden="true">04</span>资讯速览</a></nav></aside><div class="reading-content">
    <main class="shell">
    <section id="featured" x-data="featuredSwitcher"><div class="featured-topline"><h1><span>__ISSUE_DATE__</span> <span>AI简报</span></h1><button class="theme-toggle" type="button" @click="toggleTheme()" :aria-pressed="theme==='dark'" :aria-label="theme==='dark'?'切换为白天主题':'切换为黑夜主题'" :title="theme==='dark'?'切换为白天主题':'切换为黑夜主题'"><svg x-show="theme==='light'" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.8A8.5 8.5 0 0 1 8.2 3.8a8.5 8.5 0 1 0 12 12Z"/></svg><svg x-show="theme==='dark'" x-cloak viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><span class="theme-toggle-label" x-text="theme==='dark'?'日间':'夜间'"></span></button></div><div class="featured-showcase"><div class="featured-display">__FEATURED__</div><aside class="featured-index"><h2>本期四条</h2><div class="featured-choices" x-ref="choices" role="tablist" aria-label="选择本期重点" aria-orientation="vertical" @keydown.down.prevent="selectFeatured((featureIndex+1)%count,true)" @keydown.up.prevent="selectFeatured((featureIndex+count-1)%count,true)" @keydown.home.prevent="selectFeatured(0,true)" @keydown.end.prevent="selectFeatured(count-1,true)">__FEATURE_TABS__</div></aside></div></section>
    <section class="builders-section" id="builders" x-data="builderCarousel" role="region" aria-roledescription="轮播" aria-label="Builders 动态"><div class="section-heading builders-heading"><div><h2>Builders 动态</h2><p>7 位人物 · 发布时间为北京时间</p></div></div>
    <div class="builder-track" :class="{'is-ready':ready}" x-ref="track" @wheel.passive="releaseTarget()" @pointerdown.passive="releaseTarget()" @scroll.passive="sync()" @scrollend="settle()" @keydown.right.prevent="go(index+1)" @keydown.left.prevent="go(index-1)" @keydown.home.prevent="go(0)" @keydown.end.prevent="go(count-1)" tabindex="0" aria-label="左右滑动查看人物">__SLIDES__</div>
    <div class="carousel-dots" aria-label="选择人物">__DOTS__</div><p class="carousel-status" aria-live="polite" aria-atomic="true" x-text="'第'+(index+1)+'张，共__BUILDER_COUNT__张'"></p></section>
    __PODCAST__
    <section class="personal-section" id="personal"><div class="section-heading"><h2>与我相关</h2><p>3 条 · 连接正在做的事</p></div>__PERSONAL__</section>
    <section class="text-section" id="quick"><div class="section-heading"><h2>资讯速览</h2><p>7 条</p></div><ul class="text-list">__QUICK__</ul></section>
    <details class="unselected" id="unselected"><summary>未选条目<span>23 条</span><i aria-hidden="true">＋</i></summary><ul class="text-list">__UNSELECTED__</ul></details>

    </main>
    <footer class="site-footer"><div class="shell footer-row"><div><p>__SOURCE_NOTE__</p></div></div></footer></div>
    <button class="back-to-top" x-cloak x-show="showBackToTop" x-transition.opacity.duration.180ms @click="backToTop()" aria-label="回到顶部" title="回到顶部"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5.5 11.5L12 5l6.5 6.5"/></svg></button>
    <div class="overlay" x-cloak x-show="state==='archive'" @click.self="state='idle'" x-transition.opacity.duration.180ms><section class="panel" role="dialog" aria-modal="true" aria-label="切换日期"><div class="panel-head"><h2>切换日期</h2><button class="panel-close" @click="state='idle'" aria-label="关闭日期">×</button></div><div class="calendar-top"><button class="date-arrow" @click="archiveMonth--" :disabled="archiveMonth===0" aria-label="上一个归档月份">‹</button><b x-text="archiveMonths[archiveMonth]"></b><button class="date-arrow" @click="archiveMonth++" :disabled="archiveMonth===archiveMonths.length-1" aria-label="下一个归档月份">›</button></div>__CALENDAR__<p class="calendar-note">高亮日期已有内容。</p></section></div>
    </div></body></html>'''

    # Empty collections omit the complete module, including its heading and navigation entry.
    nav_entries = []
    for key, label in [('featured', '本期重点'), ('builders', 'Builders 动态'), ('personal', '与我相关'), ('quick', '资讯速览')]:
        present = bool(data['builders']) if key == 'builders' else bool(data['product'][key])
        if present:
            nav_entries.append((key, label))
        elif key == 'builders' and podcast_markup:
            nav_entries.append(('podcast', '播客精选'))
    nav_links = ''.join(f'''<a href="#{key}" @click="active='{key}'" :class="{{'active':active==='{key}'}}" :aria-current="active==='{key}'?'location':null"><span aria-hidden="true">{idx:02d}</span>{label}</a>''' for idx, (key, label) in enumerate(nav_entries, 1))
    nav_markup = f'<nav class="reading-nav" aria-label="本期目录">{nav_links}</nav>' if nav_links else ''
    page = re.sub(r'<nav class="reading-nav".*?</nav>', lambda _: nav_markup, page, count=1, flags=re.S)
    for key in ('featured', 'builders', 'personal', 'quick'):
        present = bool(data['builders']) if key == 'builders' else bool(data['product'][key])
        if not present:
            replacement = '<div class="featured-topline"><h1><span>__ISSUE_DATE__</span> <span>AI简报</span></h1></div>' if key == 'featured' else ''
            page = re.sub(r'<section\b[^>]*id="' + key + r'".*?</section>', lambda _: replacement, page, count=1, flags=re.S)
    if not data['product']['unselected']:
        page = re.sub(r'<details class="unselected".*?</details>', '', page, count=1, flags=re.S)
    if not any(data['product'].values()) and not data['builders'] and not podcast_markup:
        page = re.sub(r'<footer class="site-footer".*?</footer>', '', page, count=1, flags=re.S)
    page = page.replace('7 位人物 ·', str(len(data['builders'])) + ' 位人物 ·')
    page = page.replace('3 条 · 连接正在做的事', str(len(data['product']['personal'])) + ' 条 · 连接正在做的事')
    page = page.replace('<p>7 条</p>', '<p>' + str(len(data['product']['quick'])) + ' 条</p>')
    page = page.replace('<span>23 条</span>', '<span>' + str(len(data['product']['unselected'])) + ' 条</span>')
    if len(data['product']['featured']) != 4:
        page = page.replace('本期四条', '本期' + str(len(data['product']['featured'])) + '条')

    names = [x['author'] for x in data['builders']]
    dots = ''.join(f'<button id="builder-selector-{idx+1}" @click="go({idx})" :class="{{\'is-current\':index==={idx}}}" :aria-current="index==={idx}?\'true\':null" aria-label="查看{esc(name)}"></button>' for idx, name in enumerate(names))
    for key, value in [('ASSET_PREFIX', esc(asset_prefix)), ('SOURCE_NOTE',esc(data.get('source_note',''))), ('ARCHIVE_MONTH',str(archive_month)), ('ARCHIVE_MONTHS',json.dumps(month_labels,ensure_ascii=False)), ('DATE_CONTROLS',date_controls), ('NAV_IDS', json.dumps([key for key, _ in nav_entries])), ('FEATURE_COUNT', str(len(feature_panels))), ('ISSUE_DATE', esc(issue_date_label)), ('ISSUE_TITLE', esc(issue_title)), ('FEATURED', featured), ('FEATURE_TABS', ''.join(feature_tabs)), ('PERSONAL', personal), ('QUICK', short_rows('quick')), ('UNSELECTED', short_rows('unselected')), ('SLIDES', ''.join(slides)), ('PODCAST', podcast_markup), ('BUILDER_COUNT', str(len(slides))), ('DOTS', dots), ('CALENDAR', calendar)]:
        page = page.replace('__' + key + '__', value)
    page = page.replace('</style></head>', PERSONAL_CSS + '\n.avatar-placeholder{display:grid;place-items:center;font-size:20px;color:var(--reading-copy)}.calendar-unavailable{opacity:.3}.date-arrow:disabled{opacity:.25;cursor:default}\n</style></head>')
    return page
