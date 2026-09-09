#!/usr/bin/env python3
"""Render the maintained Markdown article as a local, image-safe HTML draft.

Supports the article's deliberately small Markdown subset. Does not upload assets
or promise that a third-party editor will retain localhost/relative image URLs.
"""
import html
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/modelscope-article-final.md'
DEST = ROOT / 'docs/publish/20260909/article.html'

def inline(text):
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    return re.sub(r'\[([^\]]+)\]\((https://[^)]+)\)', r'<a href="\2">\1</a>', text)

def render():
    blocks=[]
    for block in re.split(r'\n\s*\n', SOURCE.read_text(encoding='utf-8').strip()):
        match=re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)',block)
        if match:
            alt, target=match.groups()
            image=(SOURCE.parent/target).resolve()
            if not image.is_relative_to(DEST.parent.resolve()):raise ValueError(target)
            relative=image.relative_to(DEST.parent.resolve()).as_posix()
            blocks.append(f'<figure><img src="{html.escape(relative)}" alt="{html.escape(alt)}"><figcaption>{html.escape(alt)}</figcaption></figure>')
        elif block.startswith('#'):
            level=len(block)-len(block.lstrip('#'))
            blocks.append(f'<h{level}>{inline(block[level:].strip())}</h{level}>')
        elif block.startswith('> '):blocks.append('<blockquote>'+inline(block[2:])+'</blockquote>')
        elif all(re.match(r'(?:- |\d+\. )',line) for line in block.splitlines()):
            tag='ul' if block.startswith('- ') else 'ol'
            items=''.join('<li>'+inline(re.sub(r'^(?:- |\d+\. )','',line))+'</li>' for line in block.splitlines())
            blocks.append(f'<{tag}>{items}</{tag}>')
        else:blocks.append('<p>'+inline(block.replace('\n',' '))+'</p>')
    body='\n'.join(blocks)
    css='''*{box-sizing:border-box}body{margin:0;background:#f0f3f0;color:#233b39;font:18px/1.85 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}aside,article{max-width:880px;margin:28px auto;padding:28px 38px;background:white;border-radius:12px}aside{font-size:14px;background:#e1eee6}h1{font-size:34px;line-height:1.35;margin:16px 0 28px}h2{font-size:25px;line-height:1.5;margin:40px 0 18px;border-top:1px solid #d6e2da;padding-top:28px}figure{margin:26px 0;clear:both}img{display:block;width:100%;max-width:100%;height:auto;float:none}figcaption{font-size:13px;color:#6a7c75;line-height:1.6;margin-top:8px}blockquote{border-left:4px solid #337a68;margin:24px 0;padding:6px 20px;background:#f3f7f2}li{margin:12px 0}a{color:#267260}code{font-size:.88em;background:#edf1ec;padding:2px 5px;overflow-wrap:anywhere}p{overflow-wrap:anywhere}button{font:inherit;padding:8px 14px;border:1px solid #36735f;border-radius:6px;background:white;color:#285c4c;cursor:pointer}@media(max-width:600px){article,aside{margin:8px;padding:20px}h1{font-size:27px}h2{font-size:22px}}'''
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ClaimLedger · 文章审阅稿</title><style>'+css+'</style></head><body><aside>本地审阅稿，尚未发布。配图独立成块，避免标题与图片串行错位。发布时先把六张图上传到平台，再插入正文对应位置；直接粘贴本地 HTML 不保证平台保留图片。<br><button id="select">选择正文以复制</button></aside><article id="article">'+body+'</article><script>document.getElementById("select").onclick=()=>{let r=document.createRange();r.selectNodeContents(document.getElementById("article"));let s=window.getSelection();s.removeAllRanges();s.addRange(r);};</script></body></html>'
    DEST.parent.mkdir(parents=True,exist_ok=True)
    DEST.write_text(page,encoding='utf-8')
    print(DEST)

if __name__=='__main__':render()
