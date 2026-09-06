"""Browser-only image selection; never changes processing or CSV image order."""
from __future__ import annotations

import base64
from html import escape
from math import ceil
from urllib.parse import urlsplit

from comic_review_images import ALLOWED_IMAGE_HOSTS


def gallery_sources(image_urls, archived_image=None):
    sources = []
    for value in image_urls[:24]:
        try:
            url = urlsplit(value)
            valid = (url.scheme == "https" and url.hostname in ALLOWED_IMAGE_HOSTS
                     and url.port in (None, 443) and not url.username and not url.password)
        except (TypeError, ValueError):
            valid = False
        if valid and value not in sources:
            sources.append(value)
    if archived_image:
        mime = "image/png" if archived_image.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
        saved = f"data:{mime};base64,{base64.b64encode(archived_image).decode('ascii')}"
        sources = [saved, *sources[1:]] if sources else [saved]
    return sources


def build_gallery_html(image_urls, archived_image=None):
    sources = gallery_sources(image_urls, archived_image)
    if not sources:
        return "", 0
    buttons = []
    for index, source in enumerate(sources, 1):
        buttons.append(
            f'<button type="button" class="thumb" aria-label="画像{index}を大きく表示" '
            f'aria-pressed="{"true" if index == 1 else "false"}" data-index="{index}">'
            f'<img src="{escape(source, quote=True)}" alt="商品画像 {index}" referrerpolicy="no-referrer">'
            f'<span>{index}</span></button>'
        )
    document = '''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: https://static.mercdn.net https://i.ebayimg.com; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; connect-src 'none'">
<meta name="referrer" content="no-referrer"><style>
*{box-sizing:border-box}body{margin:0;font:13px system-ui,sans-serif;color:#172554}
.main-stage{width:100%;height:min(420px,calc(100vw - 8px));background:#fff9;border:1px solid #d7ddeb;border-radius:12px;padding:8px;display:flex;align-items:center;justify-content:center}
#main-image{width:100%;height:100%;object-fit:contain;border-radius:8px}
.toolbar{display:flex;justify-content:space-between;gap:8px;margin:10px 0;color:#475569;font-size:12px}
.thumbnails{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.thumb{position:relative;height:72px;padding:3px;border:2px solid #dce2ef;background:#fff9;border-radius:8px;cursor:pointer;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:contain}.thumb span{position:absolute;bottom:2px;left:2px;background:#172554db;color:white;border-radius:4px;padding:1px 4px;font-size:10px}
.thumb[aria-pressed=true]{border-color:#5145ed;background:#edeaff}.thumb:focus-visible{outline:3px solid #5145ed;outline-offset:2px}
.thumb:disabled{cursor:not-allowed;opacity:.6}.thumb:disabled span{right:2px}
#image-error{background:#fff2d5;color:#78350f;padding:8px;border-radius:8px;font-size:12px}
</style></head><body><div class="main-stage"><img id="main-image" src="__MAIN__" alt="選択中の商品画像 1" referrerpolicy="no-referrer"></div>
<div class="toolbar"><span>小さい画像をクリックして拡大</span><span id="counter">1 / __COUNT__</span></div>
<div class="thumbnails" aria-label="商品画像の選択">__BUTTONS__</div>
<p id="image-error" role="status" hidden>画像を読み込めません。元の画像URLが削除・変更されている可能性があります。</p>
<script>
const main = document.getElementById('main-image');
const error = document.getElementById('image-error');
const buttons = Array.from(document.querySelectorAll('.thumb'));
let request = 0;
main.addEventListener('error', () => { error.hidden = false; });
buttons.forEach(button => {
  const image = button.querySelector('img');
  function unavailable() { button.disabled = true; image.style.visibility = 'hidden'; button.querySelector('span').textContent = button.dataset.index + ' 読込不可'; }
  image.addEventListener('error', unavailable);
  if (image.complete && !image.naturalWidth) unavailable();
  button.addEventListener('click', () => {
    const current = ++request;
    const selected = new Image();
    selected.referrerPolicy = 'no-referrer';
    selected.onload = () => {
      if (current !== request) return;
      main.src = image.src;
      main.alt = '選択中の商品画像 ' + button.dataset.index;
      buttons.forEach(b => b.setAttribute('aria-pressed', String(b === button)));
      document.getElementById('counter').textContent = button.dataset.index + ' / ' + buttons.length;
      error.hidden = true;
    };
    selected.onerror = () => { if (current === request) error.hidden = false; };
    selected.src = image.src;
  });
});
</script></body></html>'''
    document = document.replace('__MAIN__', escape(sources[0], quote=True)).replace('__COUNT__', str(len(sources))).replace('__BUTTONS__', ''.join(buttons))
    return document, 470 + ceil(len(sources) / 4) * 80


def render_image_gallery(image_urls, archived_image=None):
    import streamlit.components.v1 as components
    document, height = build_gallery_html(image_urls, archived_image)
    if document:
        components.html(document, height=height, scrolling=False)
