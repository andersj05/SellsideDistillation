"""Evidence inspection pages. No inferred company workflow or automatic verification."""

from html import escape
from pathlib import Path
from typing import Any

from .serde import atomic_write, encode

STYLE = """
body{margin:0;background:#eef2f6;color:#172338;font:15px/1.6 system-ui,sans-serif}
main{max-width:1280px;margin:auto;padding:28px}a{color:#175ca0}h1{line-height:1.2}
.panel{background:white;border:1px solid #ccd6e1;border-radius:8px;padding:20px;margin:16px 0}
.grid{display:grid;grid-template-columns:1.4fr 1fr;gap:18px;align-items:start}
.source{position:relative}.source img{width:100%;display:block}.word{position:absolute;border:1px solid #e24f24;background:#fa9a5020}
.native{border-color:#167ac2;background:#469ee620}.small{color:#596b80;font-size:12px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 Consolas,monospace}
table{width:100%;border-collapse:collapse}td,th{padding:10px;text-align:left;border-bottom:1px solid #d6dfe8}
summary{cursor:pointer;font-weight:600}details{margin:14px 0}.scroll{overflow:auto}
button{padding:8px 12px;margin:4px;border:1px solid #b8c7d7;border-radius:5px;background:#fff;cursor:pointer}
@media(max-width:850px){.grid{grid-template-columns:1fr}main{padding:16px}}
"""


def html_page(title: str, body: str) -> bytes:
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{STYLE}</style><main>{body}</main></html>"
    ).encode()


def render_page(destination: Path, record: dict[str, Any], tables: list[dict[str, Any]]) -> None:
    number = record["page_index"] + 1
    safe_words = encode(record["words"]).decode().replace("<", "\\u003c")
    issues = "".join(f"<li>{escape(i['message'])}</li>" for i in record["issues"])
    table_markup = []
    for table in tables:
        rows = "".join(
            "<tr>" + "".join(f"<td>{escape(cell or '')}</td>" for cell in row) + "</tr>"
            for row in table["rows"]
        )
        table_markup.append(
            f"<details><summary>Unreviewed table candidate {table['table_index'] + 1}</summary>"
            f"<p class='small'>Merged headers and cell meanings require review.</p>"
            f"<div class='scroll'><table>{rows}</table></div></details>"
        )
    body = (
        f"<a href='../review.html'>All pages</a><h1>PDF page {number}</h1>"
        "<p>Blue boxes: native text. Orange boxes: OCR. Hover or select a word to inspect its "
        "source ID and transcription. Both channels are unverified; repeated text is retained.</p>"
        "<button onclick=\"show('native')\">Native words</button>"
        "<button onclick=\"show('ocr')\">OCR words</button>"
        "<button onclick=\"show('none')\">Clean source</button>"
        f"<div class='grid'><div class='panel'><div class='source' id='source'>"
        f"<img src='page_{number:03d}.png' alt='Source PDF page {number}'></div>"
        "<p id='selection' class='small'>Select a source word.</p></div><div class='panel'>"
        f"<h2>Extraction issues</h2><ul>{issues or '<li>No mechanical issue detected.</li>'}</ul>"
        f"<details open><summary>Native text</summary><pre>{escape(record['native_text'])}</pre></details>"
        f"<details><summary>OCR text</summary><pre>{escape(record['ocr_text'])}</pre></details>"
        f"{''.join(table_markup)}<a href='page_{number:03d}.json'>Page JSON and geometry</a>"
        "</div></div><script>const words=" + safe_words + ";"
        "function show(channel){document.querySelectorAll('.word').forEach(e=>e.remove());"
        "words.filter(w=>w.channel===channel).forEach(w=>{const el=document.createElement('span');"
        "el.className='word '+channel;const b=w.bbox;"
        "el.style.cssText=`left:${100*b[0]}%;top:${100*b[1]}%;width:${100*(b[2]-b[0])}%;height:${100*(b[3]-b[1])}%;`;"
        "el.title=w.text+' | '+w.word_id;el.onclick=()=>{document.getElementById('selection').textContent=el.title;};"
        "document.getElementById('source').appendChild(el);});}show('native');</script>"
    )
    atomic_write(destination, html_page(f"PDF page {number}", body))


def render_index(destination: Path, document: dict, pages: list[dict], recipe: dict) -> None:
    rows = "".join(
        f"<tr><td><a href='pages/page_{p['page_index'] + 1:03d}.html'>"
        f"{p['page_index'] + 1}</a></td><td>{p['native_word_count']}</td>"
        f"<td>{p['ocr_word_count']}</td><td>{p['image_count']}</td>"
        f"<td>{escape(', '.join(i['code'] for i in p['issues'])) or 'None detected'}</td></tr>"
        for p in pages
    )
    body = (
        f"<h1>{escape(document['original_filename'])}</h1>"
        "<p>Local source extraction: native text, OCR, table candidates, geometry, and page visuals. "
        "No analytical pattern is inferred. No extracted value is automatically a verified fact "
        "or an evaluator answer.</p><div class='panel'><h2>Coverage</h2>"
        f"<p>{len(pages)} pages; {sum(p['native_word_count'] for p in pages):,} native words; "
        f"{sum(p['ocr_word_count'] for p in pages):,} OCR words.</p>"
        "<p>Charts remain source images with label transcriptions; unlabeled data points are not "
        "reconstructed. Table semantics, reading order, OCR corrections, source contradictions, "
        "and analytical usefulness require separate review.</p>"
        "<a href='extraction.txt'>Combined transcription</a> · "
        "<a href='spans.jsonl'>Evidence spans</a> · <a href='tables.jsonl'>Table candidates</a> · "
        "<a href='manifest.json'>Integrity manifest</a></div><div class='panel scroll'>"
        "<table><thead><tr><th>PDF page</th><th>Native words</th><th>OCR words</th>"
        f"<th>Images</th><th>Review flags</th></tr></thead><tbody>{rows}</tbody></table></div>"
        f"<details><summary>Parser and OCR recipe</summary><pre>{escape(encode(recipe).decode())}</pre>"
        "</details>"
    )
    atomic_write(destination, html_page("Report extraction review", body))
