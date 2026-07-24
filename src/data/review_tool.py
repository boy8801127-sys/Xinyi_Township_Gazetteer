# -*- coding: utf-8 -*-
"""
本機圖片審閱小工具：取代「開 Excel 對照 images_review.csv ＋ 檔案總管切縮圖檢視」
的人工流程，改成瀏覽器介面一次看圖＋鍵盤快速標記 photo／table，加速重新審閱的
速度。純標準函式庫實作（http.server），不需要額外安裝套件。

安全設計（源自一次事故的教訓，見 extract_books.py 的 _load_existing_review
docstring）：
    - 啟動時先把當下的 output/images_review.csv 備份一份到
      output/.review_backups/，不管接下來怎麼操作都留一份起點快照。
    - 每次標記變動都是「temp 檔寫完再 os.replace」的原子寫入，不會半途中斷
      寫出壞檔；而且是逐筆存檔，不用擔心瀏覽器分頁關掉、程式當掉就整批遺失。

使用方式：
    python -m src.data.review_tool
    （會自動開瀏覽器 http://127.0.0.1:8765，Ctrl+C 結束伺服器）

鍵盤操作：
    ← / →     上一筆／下一筆（不改變標記）
    P         標成 photo（清掉 table）並前進下一筆
    T         標成 table（清掉 photo）並前進下一筆
    N / space 標成「文字，不放進系統」（兩欄都清空）並前進下一筆
    U         跳到下一筆兩欄都還空白（尚未審閱）的項目
    也可以直接點兩個 checkbox，允許同一筆圖片同時勾 photo 又勾 table。

「標題」欄可以直接在畫面上編輯（例如一張 PNG 裡塞了好幾個表格/圖片，原本的標題
不夠精確時可以自己補充說明），改完按 Enter 或點掉輸入框（blur）即存檔；輸入框
有焦點時，P/T/N/方向鍵等快捷鍵不會被搶走，可以正常打字。

    O         開關「文字圖層」——OCR 辨識目前這張圖，疊一層可選取的透明文字在
              圖片上，能直接框選、Ctrl+C 複製；也可以按「複製全部文字」一次拿到
              整張圖辨識出來的文字（依行還原）。

    R         把目前這張圖順時針轉 90 度（部分掃描檔本身是橫躺的）；旋轉狀態記在
              瀏覽器 localStorage（依圖片 ID），只是輔助檢視用，不會寫回
              images_review.csv、也不影響 extract_books.py／promote_reviewed_images.py
              的既有邏輯——換瀏覽器或清 localStorage 就會重置。

OCR 用的是本機 Tesseract（不呼叫任何付費 API，純本機運算）：
    winget install --id UB-Mannheim.TesseractOCR
繁體中文語言檔另外放在專案內的 .tessdata/（不隨 Tesseract 安裝，用
--tessdata-dir 指定，不需要系統管理員權限就能裝）：
    https://github.com/tesseract-ocr/tessdata_best/raw/main/chi_tra.traineddata
辨識結果依圖片 ID 快取在 output/.ocr_cache/，同一張圖只會真的跑一次 OCR。
"""
from __future__ import annotations

import csv
import json
import mimetypes
import os
import shutil
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Timer
from urllib.parse import parse_qs, unquote, urlparse

import pytesseract
from PIL import Image

from src.data.extract_books import IMAGES_DIR, IMAGES_REVIEW_CSV_PATH, ROOT

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

HOST, PORT = "127.0.0.1", 8765
BACKUP_DIR = ROOT / "output" / ".review_backups"
FIELDNAMES = ["ID", "頁數", "書目名稱", "卷期", "志名", "篇名", "標題", "圖片檔名", "photo", "table"]
MARK = "V"

TESSDATA_DIR = ROOT / ".tessdata"
OCR_CACHE_DIR = ROOT / "output" / ".ocr_cache"
OCR_LANG = "chi_tra+eng"
_TESSERACT_CANDIDATES = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]


def _load_rows() -> list[dict]:
    if not IMAGES_REVIEW_CSV_PATH.exists():
        raise FileNotFoundError(
            f"找不到 {IMAGES_REVIEW_CSV_PATH}，請先執行：python -m src.data.extract_books"
        )
    with IMAGES_REVIEW_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _save_rows(rows: list[dict]) -> None:
    tmp = IMAGES_REVIEW_CSV_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(IMAGES_REVIEW_CSV_PATH)


def _backup_once() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"images_review_{stamp}.csv"
    shutil.copy2(IMAGES_REVIEW_CSV_PATH, dest)
    print(f"[備份] 啟動快照已存到 {dest}")


ROWS = _load_rows()
ROWS_BY_ID = {r["ID"]: r for r in ROWS}


def _stats() -> dict:
    photo = sum(1 for r in ROWS if (r.get("photo") or "").strip())
    table = sum(1 for r in ROWS if (r.get("table") or "").strip())
    neither = sum(
        1 for r in ROWS if not (r.get("photo") or "").strip() and not (r.get("table") or "").strip()
    )
    return {"total": len(ROWS), "photo": photo, "table": table, "unreviewed_or_neither": neither}


def _configure_tesseract() -> str | None:
    """設好 pytesseract 要呼叫的執行檔路徑。成功回傳 None，失敗回傳給前端顯示
    的錯誤訊息（不拋例外——OCR 是輔助功能，裝好 CSV 審閱工具本身不該因此壞掉）。"""
    if shutil.which("tesseract"):
        return None
    for candidate in _TESSERACT_CANDIDATES:
        if candidate.exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return None
    return (
        "找不到 Tesseract OCR 引擎，請先安裝："
        "winget install --id UB-Mannheim.TesseractOCR"
    )


def _run_ocr(image_path: Path) -> dict:
    img = Image.open(image_path)
    width, height = img.size
    # 用環境變數而非 --tessdata-dir 參數指定語言檔目錄：pytesseract 組 config
    # 字串時只用簡單的空白 split，不是 shlex，路徑加引號反而會把引號字元原封
    # 不動地傳進去，在 Windows 路徑上會出錯。
    os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)
    data = pytesseract.image_to_data(
        img, lang=OCR_LANG, output_type=pytesseract.Output.DICT
    )
    words = []
    lines: list[list[str]] = []
    last_key = None
    for i, raw_text in enumerate(data["text"]):
        text = raw_text.strip()
        if not text or int(data["conf"][i]) < 0:
            continue
        words.append({
            "text": text,
            "left": data["left"][i],
            "top": data["top"][i],
            "width": data["width"][i],
            "height": data["height"][i],
        })
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key != last_key:
            lines.append([])
            last_key = key
        lines[-1].append(text)
    full_text = "\n".join(" ".join(line) for line in lines)
    return {"width": width, "height": height, "words": words, "full_text": full_text}


def _ocr_for_id(image_id: str, image_filename: str) -> dict:
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = OCR_CACHE_DIR / f"{image_id}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    result = _run_ocr(IMAGES_DIR / image_filename)
    cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


INDEX_HTML = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>圖片審閱工具</title>
<style>
  :root {
    --bg: #1c1d21; --panel: #26272c; --border: #3a3b42;
    --text: #e8e8ec; --muted: #9a9ba5; --accent: #6ea8fe;
    --photo: #4fb477; --table: #d9a441;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: "Segoe UI", "Microsoft JhengHei", sans-serif;
    background: var(--bg); color: var(--text); height: 100vh;
    display: flex; flex-direction: column; overflow: hidden;
  }
  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 18px; background: var(--panel); border-bottom: 1px solid var(--border);
    font-size: 14px; flex-wrap: wrap; gap: 8px;
  }
  header .id { color: var(--accent); font-weight: 600; font-family: Consolas, monospace; }
  header .stats { color: var(--muted); font-variant-numeric: tabular-nums; }
  #cur-title {
    font: inherit; color: var(--text); background: transparent; border: 1px solid transparent;
    border-radius: 4px; padding: 3px 6px; width: 46em; max-width: 62vw;
  }
  #cur-title:hover { border-color: var(--border); }
  #cur-title:focus { outline: none; border-color: var(--accent); background: #1c1d21; }
  #cur-title.saved { border-color: var(--photo); }
  main {
    flex: 1; display: flex; align-items: center; justify-content: center;
    padding: 12px; min-height: 0; min-width: 0; overflow: hidden;
  }
  #imgwrap {
    width: 100%; height: 100%; min-height: 0; min-width: 0; display: flex;
    align-items: center; justify-content: center; overflow: hidden; position: relative;
  }
  #img {
    display: block; border-radius: 4px;
    box-shadow: 0 4px 24px rgba(0,0,0,.4); transform-origin: center center;
  }
  #ocr-layer { position: absolute; left: 0; top: 0; pointer-events: none; transform-origin: center center; }
  #ocr-layer span {
    position: absolute; color: transparent; white-space: pre; line-height: 1;
    user-select: text; cursor: text; pointer-events: auto;
  }
  #ocr-layer span:hover { background: rgba(110,168,254,.16); }
  #ocr-layer span::selection { background: rgba(110,168,254,.5); color: transparent; }
  button.ocr-active { background: var(--accent); border-color: var(--accent); color: #10203a; font-weight: 600; }
  #zoom-controls {
    position: absolute; right: 10px; bottom: 10px; display: flex; align-items: center; gap: 4px;
    background: rgba(38,39,44,.88); border: 1px solid var(--border); border-radius: 8px; padding: 4px;
  }
  #zoom-controls button {
    padding: 4px 10px; font-size: 13px; border-radius: 5px;
  }
  #zoom-label {
    font-size: 12px; color: var(--muted); min-width: 3.5em; text-align: center;
    font-variant-numeric: tabular-nums;
  }
  .meta {
    padding: 8px 18px; background: var(--panel); border-top: 1px solid var(--border);
    font-size: 13px; color: var(--muted); display: flex; gap: 18px; flex-wrap: wrap;
  }
  .meta b { color: var(--text); font-weight: 500; }
  footer {
    display: flex; align-items: center; justify-content: center; gap: 10px;
    padding: 14px 18px calc(14px + env(safe-area-inset-bottom)); background: var(--panel);
    border-top: 1px solid var(--border); flex-wrap: wrap;
  }
  button {
    font-size: 14px; padding: 10px 16px; border-radius: 6px; border: 1px solid var(--border);
    background: #2f3036; color: var(--text); cursor: pointer;
  }
  button:hover { border-color: var(--accent); }
  button.nav { color: var(--muted); }
  button.mark-photo.active { background: var(--photo); border-color: var(--photo); color: #10230f; font-weight: 600; }
  button.mark-table.active { background: var(--table); border-color: var(--table); color: #2a1e00; font-weight: 600; }
  button.mark-neither.active { background: #55565f; border-color: #55565f; }
  .hint { width: 100%; text-align: center; font-size: 12px; color: var(--muted); margin-top: 4px; }
  kbd { background: #35363d; border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px; font-family: Consolas, monospace; }
</style>
</head>
<body>
<header>
  <div><span class="id" id="cur-id">-</span> <input type="text" id="cur-title" placeholder="標題（可編輯，例如一張圖裡有好幾個表格時加註）"></div>
  <div class="stats" id="stats">載入中…</div>
</header>
<main>
  <div id="imgwrap">
    <img id="img" alt="審閱圖片">
    <div id="ocr-layer"></div>
    <div id="zoom-controls">
      <button id="btn-zoom-out" title="縮小 (-)">－</button>
      <span id="zoom-label">100%</span>
      <button id="btn-zoom-in" title="放大 (+)">＋</button>
      <button id="btn-zoom-reset" title="還原 (0)">還原</button>
      <button id="btn-rotate" title="旋轉 90 度 (R)">⟳ 旋轉</button>
    </div>
  </div>
</main>
<div class="meta" id="meta"></div>
<footer>
  <button class="nav" id="btn-prev">◀ 上一筆</button>
  <button class="mark-photo" id="btn-photo">P 圖片</button>
  <button class="mark-table" id="btn-table">T 表格</button>
  <button class="mark-neither" id="btn-neither">N 文字／略過</button>
  <button class="nav" id="btn-next">下一筆 ▶</button>
  <button class="nav" id="btn-unreviewed">U 跳到未標記</button>
  <button class="nav" id="btn-ocr">O 文字圖層</button>
  <button class="nav" id="btn-copy-all" style="display:none;">複製全部文字</button>
  <div class="hint">快捷鍵：<kbd>&larr;</kbd><kbd>&rarr;</kbd> 換頁　<kbd>P</kbd> 圖片　<kbd>T</kbd> 表格　<kbd>N</kbd>/<kbd>space</kbd> 文字略過　<kbd>U</kbd> 跳到下一筆未標記　<kbd>O</kbd> 開關文字圖層　<kbd>+</kbd>/<kbd>-</kbd> 縮放　<kbd>0</kbd> 還原縮放　<kbd>R</kbd> 旋轉90度　滾輪縮放、放大後可拖曳移動</div>
</footer>
<script>
let items = [];
let idx = 0;

async function loadItems() {
  const res = await fetch('/api/items');
  items = await res.json();
  const savedIdx = parseInt(localStorage.getItem('review_idx') || '0', 10);
  idx = Math.min(Math.max(savedIdx, 0), items.length - 1);
  render();
}

function stats() {
  const total = items.length;
  const photo = items.filter(r => (r.photo || '').trim()).length;
  const table = items.filter(r => (r.table || '').trim()).length;
  return `${idx + 1} / ${total} 　已標記 photo:${photo} table:${table}`;
}

function render() {
  const it = items[idx];
  loadRotationForCurrentItem();
  document.getElementById('cur-id').textContent = it.ID;
  const titleInput = document.getElementById('cur-title');
  titleInput.value = it['標題'] || '';
  titleInput.classList.remove('saved');
  document.getElementById('img').src = '/images/' + encodeURIComponent(it['圖片檔名']) + '?v=' + idx;
  document.getElementById('meta').innerHTML =
    `<span><b>書目</b>${it['書目名稱'] || ''}</span>` +
    `<span><b>卷期</b>${it['卷期'] || ''}</span>` +
    `<span><b>志名</b>${it['志名'] || ''}</span>` +
    `<span><b>篇名</b>${it['篇名'] || ''}</span>` +
    `<span><b>頁數</b>${it['頁數'] || ''}</span>`;
  document.getElementById('stats').textContent = stats();
  document.getElementById('btn-photo').classList.toggle('active', !!(it.photo || '').trim());
  document.getElementById('btn-table').classList.toggle('active', !!(it.table || '').trim());
  document.getElementById('btn-neither').classList.toggle(
    'active', !(it.photo || '').trim() && !(it.table || '').trim()
  );
  localStorage.setItem('review_idx', String(idx));
  layoutImage();
  applyTransform();
  updateOcrLayer();
}

let ocrCache = {};   // id -> {width, height, words, full_text}，同一分頁內重複切換不用重打 API
let ocrVisible = false;

// --- 縮放／平移／旋轉 ---
// #img 跟 #ocr-layer 永遠套同一個 transform，圖片跟文字圖層才會對齊。
// layoutImage() 決定「轉正之前」#img 自己該多大（配合 rotation 讓轉完剛好
// 塞滿容器），applyTransform() 只疊縮放/平移/旋轉；平移是最外層的螢幕座標
// 位移（跟旋轉無關），滑鼠游標縮放的算法才不會被旋轉角度打亂。
// 旋轉狀態存在 localStorage、依圖片 ID 分開記——只是輔助檢視用，刻意不寫回
// images_review.csv，不去動那份 CSV 的既有欄位／流程。
let zoom = 1, panX = 0, panY = 0, rotation = 0;
const MIN_ZOOM = 1, MAX_ZOOM = 6;
let rotations = {};
try { rotations = JSON.parse(localStorage.getItem('review_rotations') || '{}'); } catch (e) { rotations = {}; }

function loadRotationForCurrentItem() {
  rotation = rotations[items[idx].ID] || 0;
}

function rotateImage() {
  rotation = (rotation + 90) % 360;
  rotations[items[idx].ID] = rotation;
  localStorage.setItem('review_rotations', JSON.stringify(rotations));
  layoutImage();
  applyTransform();
}

function computeFitRect() {
  const wrap = document.getElementById('imgwrap').getBoundingClientRect();
  const img = document.getElementById('img');
  const nw = img.naturalWidth, nh = img.naturalHeight;
  if (!nw || !nh || !wrap.width || !wrap.height) return null;
  const swapped = (rotation % 180) !== 0;
  const effRatio = swapped ? (nh / nw) : (nw / nh);
  const wrapRatio = wrap.width / wrap.height;
  let dispW, dispH;  // 旋轉「之後」畫面上看到的大小
  if (effRatio > wrapRatio) { dispW = wrap.width; dispH = wrap.width / effRatio; }
  else { dispH = wrap.height; dispW = wrap.height * effRatio; }
  // elementWidth/Height 是 #img 元素轉正之前自己要設的尺寸，轉完才會變成 dispW × dispH
  const elementWidth = swapped ? dispH : dispW;
  const elementHeight = swapped ? dispW : dispH;
  return {
    elementWidth, elementHeight,
    left: (wrap.width - elementWidth) / 2,
    top: (wrap.height - elementHeight) / 2,
  };
}

function layoutImage() {
  const fit = computeFitRect();
  if (!fit) return;
  const img = document.getElementById('img');
  img.style.width = fit.elementWidth + 'px';
  img.style.height = fit.elementHeight + 'px';
  renderOcrLayer();
}

function applyTransform() {
  const t = `translate(${panX}px, ${panY}px) rotate(${rotation}deg) scale(${zoom})`;
  document.getElementById('img').style.transform = t;
  document.getElementById('ocr-layer').style.transform = t;
  document.getElementById('imgwrap').style.cursor = zoom > MIN_ZOOM ? 'grab' : 'default';
  document.getElementById('zoom-label').textContent = Math.round(zoom * 100) + '%';
}

function resetZoom() {
  zoom = 1; panX = 0; panY = 0;
  applyTransform();
}

function zoomAt(cx, cy, factor) {
  const oldZoom = zoom;
  const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * factor));
  if (newZoom === oldZoom) return;
  const imagePointX = (cx - panX) / oldZoom;
  const imagePointY = (cy - panY) / oldZoom;
  zoom = newZoom;
  panX = cx - zoom * imagePointX;
  panY = cy - zoom * imagePointY;
  if (zoom <= MIN_ZOOM) { panX = 0; panY = 0; }
  applyTransform();
}

function currentImgReady() {
  const img = document.getElementById('img');
  return img.complete && img.naturalWidth > 0;
}

document.getElementById('img').addEventListener('load', layoutImage);

function renderOcrLayer() {
  const it = items[idx];
  const data = ocrCache[it.ID];
  const layer = document.getElementById('ocr-layer');
  layer.innerHTML = '';
  if (!data || !ocrVisible || !currentImgReady()) return;
  const fit = computeFitRect();
  if (!fit) return;
  layer.style.left = fit.left + 'px';
  layer.style.top = fit.top + 'px';
  layer.style.width = fit.elementWidth + 'px';
  layer.style.height = fit.elementHeight + 'px';
  const scaleX = fit.elementWidth / data.width;
  const scaleY = fit.elementHeight / data.height;
  const frag = document.createDocumentFragment();
  for (const w of data.words) {
    const span = document.createElement('span');
    span.textContent = w.text;
    span.style.left = (w.left * scaleX) + 'px';
    span.style.top = (w.top * scaleY) + 'px';
    span.style.width = (w.width * scaleX) + 'px';
    span.style.height = (w.height * scaleY) + 'px';
    span.style.fontSize = Math.max(6, w.height * scaleY * 0.9) + 'px';
    frag.appendChild(span);
  }
  layer.appendChild(frag);
  applyTransform();  // 圖層重建後套用目前的縮放/平移狀態，跟 #img 保持對齊
}

async function ensureOcrLoaded() {
  const it = items[idx];
  if (ocrCache[it.ID]) return ocrCache[it.ID];
  const btn = document.getElementById('btn-ocr');
  const prevLabel = btn.textContent;
  btn.textContent = 'OCR 辨識中…';
  btn.disabled = true;
  try {
    const res = await fetch('/api/ocr?id=' + encodeURIComponent(it.ID));
    const data = await res.json();
    if (!data.ok) {
      alert(data.error || 'OCR 失敗');
      ocrVisible = false;
      document.getElementById('btn-ocr').classList.remove('ocr-active');
      return null;
    }
    ocrCache[it.ID] = data;
    return data;
  } finally {
    btn.textContent = prevLabel;
    btn.disabled = false;
  }
}

async function updateOcrLayer() {
  const layer = document.getElementById('ocr-layer');
  document.getElementById('btn-copy-all').style.display = ocrVisible ? '' : 'none';
  if (!ocrVisible) { layer.innerHTML = ''; return; }
  const it = items[idx];
  const data = await ensureOcrLoaded();
  if (!data || items[idx] !== it) return;  // 等 API 回來時可能已經換頁了，放棄過期結果
  // 圖片若還沒載入，renderOcrLayer() 內的 currentImgReady() 檢查會先跳過，
  // 之後靠上面註冊的 #img 'load' → layoutImage() 補上（layoutImage 內部會呼叫
  // renderOcrLayer()），這裡不用另外重複註冊一次性的 load listener。
  renderOcrLayer();
}

async function toggleOcr() {
  ocrVisible = !ocrVisible;
  document.getElementById('btn-ocr').classList.toggle('ocr-active', ocrVisible);
  await updateOcrLayer();
}

document.getElementById('btn-ocr').onclick = toggleOcr;
document.getElementById('btn-copy-all').onclick = async () => {
  const it = items[idx];
  const data = ocrCache[it.ID];
  if (!data || !data.full_text) return;
  await navigator.clipboard.writeText(data.full_text);
  const btn = document.getElementById('btn-copy-all');
  const orig = btn.textContent;
  btn.textContent = '已複製 ✓';
  setTimeout(() => { btn.textContent = orig; }, 1200);
};
window.addEventListener('resize', renderOcrLayer);

async function mark(photo, table) {
  const it = items[idx];
  it.photo = photo; it.table = table;
  render();
  await fetch('/api/mark', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: it.ID, photo, table }),
  });
}

async function saveTitle() {
  const titleInput = document.getElementById('cur-title');
  const it = items[idx];
  const value = titleInput.value;
  if (value === (it['標題'] || '')) return;
  it['標題'] = value;
  await fetch('/api/update-title', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: it.ID, title: value }),
  });
  titleInput.classList.add('saved');
}

const titleInputEl = document.getElementById('cur-title');
titleInputEl.addEventListener('blur', saveTitle);
titleInputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); titleInputEl.blur(); }
  e.stopPropagation();  // 打字時（含 p/t/n/space/方向鍵）不要觸發下面全域快捷鍵
});

function go(delta) {
  idx = Math.min(Math.max(idx + delta, 0), items.length - 1);
  resetZoom();
  render();
}

function jumpToUnreviewed() {
  for (let i = 1; i <= items.length; i++) {
    const j = (idx + i) % items.length;
    const it = items[j];
    if (!(it.photo || '').trim() && !(it.table || '').trim()) {
      idx = j; resetZoom(); render(); return;
    }
  }
  alert('全部項目都已經標記過了');
}

document.getElementById('btn-prev').onclick = () => go(-1);
document.getElementById('btn-next').onclick = () => go(1);
document.getElementById('btn-unreviewed').onclick = jumpToUnreviewed;
document.getElementById('btn-photo').onclick = () => mark('V', '');
document.getElementById('btn-table').onclick = () => mark('', 'V');
document.getElementById('btn-neither').onclick = () => mark('', '');
document.getElementById('btn-zoom-in').onclick = () => zoomAt(0, 0, 1.3);
document.getElementById('btn-zoom-out').onclick = () => zoomAt(0, 0, 1 / 1.3);
document.getElementById('btn-zoom-reset').onclick = resetZoom;
document.getElementById('btn-rotate').onclick = rotateImage;

const imgwrapEl = document.getElementById('imgwrap');

imgwrapEl.addEventListener('wheel', (e) => {
  e.preventDefault();
  const wrap = imgwrapEl.getBoundingClientRect();
  const cx = e.clientX - wrap.left - wrap.width / 2;
  const cy = e.clientY - wrap.top - wrap.height / 2;
  zoomAt(cx, cy, e.deltaY < 0 ? 1.15 : 1 / 1.15);
}, { passive: false });

let dragging = false, dragStartX = 0, dragStartY = 0, panStartX = 0, panStartY = 0;

imgwrapEl.addEventListener('mousedown', (e) => {
  // 點在辨識出來的文字上要留給瀏覽器原生選字，不要搶成拖曳平移
  if (zoom <= MIN_ZOOM || e.target.closest('#ocr-layer') || e.target.closest('#zoom-controls')) return;
  dragging = true;
  dragStartX = e.clientX; dragStartY = e.clientY;
  panStartX = panX; panStartY = panY;
  imgwrapEl.style.cursor = 'grabbing';
  e.preventDefault();
});
window.addEventListener('mousemove', (e) => {
  if (!dragging) return;
  panX = panStartX + (e.clientX - dragStartX);
  panY = panStartY + (e.clientY - dragStartY);
  applyTransform();
});
window.addEventListener('mouseup', () => {
  if (!dragging) return;
  dragging = false;
  imgwrapEl.style.cursor = zoom > MIN_ZOOM ? 'grab' : 'default';
});

window.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') { go(-1); }
  else if (e.key === 'ArrowRight') { go(1); }
  else if (e.key === 'p' || e.key === 'P') { mark('V', ''); go(1); }
  else if (e.key === 't' || e.key === 'T') { mark('', 'V'); go(1); }
  else if (e.key === 'n' || e.key === 'N' || e.key === ' ') { e.preventDefault(); mark('', ''); go(1); }
  else if (e.key === 'u' || e.key === 'U') { jumpToUnreviewed(); }
  else if (e.key === 'o' || e.key === 'O') { toggleOcr(); }
  else if (e.key === '+' || e.key === '=') { zoomAt(0, 0, 1.3); }
  else if (e.key === '-' || e.key === '_') { zoomAt(0, 0, 1 / 1.3); }
  else if (e.key === '0') { resetZoom(); }
  else if (e.key === 'r' || e.key === 'R') { rotateImage(); }
});

loadItems();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 靜音預設的 access log，改由 API 自己印進度
        pass

    def do_GET(self):
        if self.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/items":
            body = json.dumps(ROWS, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/images/"):
            self._serve_image()
        elif self.path.startswith("/api/ocr"):
            self._handle_ocr()
        else:
            self.send_error(404)

    def _serve_image(self):
        filename = unquote(urlparse(self.path).path[len("/images/"):])
        path = (IMAGES_DIR / Path(filename).name).resolve()
        if IMAGES_DIR.resolve() not in path.parents or not path.exists():
            self.send_error(404)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path == "/api/mark":
            self._handle_mark()
        elif self.path == "/api/update-title":
            self._handle_update_title()
        else:
            self.send_error(404)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _handle_mark(self):
        payload = self._read_json()
        row = ROWS_BY_ID.get(payload.get("id"))
        if row is None:
            self.send_error(400, "unknown id")
            return
        row["photo"] = payload.get("photo", "")
        row["table"] = payload.get("table", "")
        _save_rows(ROWS)
        s = _stats()
        print(f"\r[已存檔] {row['ID']} → photo={row['photo'] or '-'} table={row['table'] or '-'}"
              f"　（累計 photo:{s['photo']} table:{s['table']} 未標記:{s['unreviewed_or_neither']}）",
              end="", flush=True)
        self._send_json({"ok": True, "stats": s})

    def _handle_update_title(self):
        payload = self._read_json()
        row = ROWS_BY_ID.get(payload.get("id"))
        if row is None:
            self.send_error(400, "unknown id")
            return
        row["標題"] = payload.get("title", "")
        _save_rows(ROWS)
        print(f"\r[已存檔] {row['ID']} → 標題「{row['標題']}」" + " " * 20, end="", flush=True)
        self._send_json({"ok": True})

    def _handle_ocr(self):
        image_id = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
        row = ROWS_BY_ID.get(image_id)
        if row is None:
            self.send_error(400, "unknown id")
            return
        err = _configure_tesseract()
        if err:
            self._send_json({"ok": False, "error": err})
            return
        try:
            result = _ocr_for_id(image_id, row["圖片檔名"])
        except Exception as e:  # OCR 失敗不該讓伺服器整個掛掉，回傳錯誤訊息給前端
            self._send_json({"ok": False, "error": f"OCR 失敗：{e}"})
            return
        print(f"\r[OCR] {image_id}　（{len(result['words'])} 個詞）" + " " * 20, end="", flush=True)
        self._send_json({"ok": True, **result})

    def _send_json(self, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    _backup_once()
    s = _stats()
    print(f"共 {s['total']} 筆，目前已標記 photo:{s['photo']} table:{s['table']}，"
          f"未標記/文字:{s['unreviewed_or_neither']}")
    url = f"http://{HOST}:{PORT}/"
    Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"審閱工具已啟動：{url}（Ctrl+C 結束）")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止，最新標記已即時存檔於", IMAGES_REVIEW_CSV_PATH)


if __name__ == "__main__":
    main()
