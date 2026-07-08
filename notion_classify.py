# -*- coding: utf-8 -*-
"""
Notion 段落自動分類與關鍵字擷取

使用方式：
    python notion_classify.py --first-only --dry-run   # 預覽第一篇
    python notion_classify.py --first-only             # 寫入第一篇（即時模式）
    python notion_classify.py --all                    # 全量即時模式
    python notion_classify.py --all --batch            # 全量 Batch 模式（便宜 50%）
    python notion_classify.py --batch-resume <id>      # 繼續已送出的 batch
    python notion_classify.py --apply-local <json>     # 從本地 JSON 重新寫入 Notion

本地結果儲存（results/ 目錄）：
    每個 child_database 存一份 JSON，格式：
    {
      "db_id": "...", "db_title": "...", "batch_id": "...",
      "records": [
        { "page_id": "...", "notion_id": "...", "paragraph": "...",
          "categories": [...], "reason": "...", "keywords": [...],
          "written_to_notion": false, "written_at": null, "error": null }
      ]
    }
    written_to_notion 為 true 表示已成功寫入 Notion。
    若中途失敗，用 --apply-local 只補寫 false 的列。
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from notion_client import Client

# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

load_dotenv()

claude  = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
notion  = Client(auth=os.environ["NOTION_API_KEY"])

ROOT            = Path(__file__).resolve().parent
CATEGORIES_FILE = ROOT / "This_plan" / "類別.txt"
ARCH_FILE       = ROOT / "This_plan" / "信義鄉志架構分類.txt"
BATCH_STATE_DIR = ROOT / "batch_states"
RESULTS_DIR     = ROOT / "results"

# ---------------------------------------------------------------------------
# 分類提示詞
# ---------------------------------------------------------------------------

CATEGORIES: list[str] = [
    line.strip()
    for line in CATEGORIES_FILE.read_text(encoding="utf-8").splitlines()
    if line.strip()
] + ["無法判斷"]

_ARCH_TEXT = ARCH_FILE.read_text(encoding="utf-8")

SYSTEM_PROMPT = f"""你是《南投縣信義鄉志》的編纂助理，負責對論文段落進行分類並擷取關鍵字。

【分類清單】（共 {len(CATEGORIES)} 類）：
{chr(10).join(f"- {c}" for c in CATEGORIES)}

【各篇章內容範圍參考】：
{_ARCH_TEXT[:3000]}

【任務說明】：
1. 從上方清單中選出 1～2 個最符合的分類（必須完全符合名稱）。
   - 若段落明顯跨兩個領域，可選 2 個；若只符合一個，就選 1 個。
   - 若段落完全無法判斷所屬領域（例如純統計數字、亂碼、無意義文字），選「無法判斷」。
2. 用一句話說明為什麼選這些分類（20～50 字，中文）。
3. 從段落擷取 3～5 個關鍵字（優先選：地名、人名、族群、事件、制度等專有名詞）。
4. 只輸出純 JSON，不加任何說明文字。

輸出格式範例（一個分類）：
{{"categories": ["社會篇"], "reason": "段落描述布農族耆老在部落文化健康站的日常活動，屬於社會層面。", "keywords": ["布農族", "耆老", "部落", "信義鄉", "文化健康站"]}}

輸出格式範例（兩個分類）：
{{"categories": ["歷史篇", "人物篇"], "reason": "段落同時涉及日治時期的歷史脈絡，以及特定地方人物的事蹟。", "keywords": ["日治時期", "地方菁英", "信義鄉", "開發史"]}}"""


def build_user_prompt(paragraph: str) -> str:
    return (
        f"<段落>\n{paragraph}\n</段落>\n\n"
        f"請分類並說明原因、擷取關鍵字。只輸出 JSON："
        f'{{\"categories\": [...], \"reason\": \"...\", \"keywords\": [...]}}'
    )


# ---------------------------------------------------------------------------
# 結果解析
# ---------------------------------------------------------------------------

def _normalize_category(cat: str) -> str:
    if cat in CATEGORIES:
        return cat
    matched = next(
        (c for c in CATEGORIES if c.startswith(cat) or cat.startswith(c.rstrip("篇"))),
        None,
    )
    return matched or "無法判斷"


def _parse_claude_json(raw: str) -> dict:
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    result = json.loads(raw[start:end])

    if "category" in result and "categories" not in result:
        result["categories"] = [result.pop("category")]

    cats = result.get("categories", [])
    if not isinstance(cats, list):
        cats = [cats]
    cats = [_normalize_category(c) for c in cats[:2]]
    result["categories"] = cats or ["無法判斷"]
    result["reason"]   = str(result.get("reason", "")).strip()[:200]
    kws = result.get("keywords", [])
    result["keywords"] = (kws[:5] if len(kws) > 5 else kws) if isinstance(kws, list) else []
    return result


# ---------------------------------------------------------------------------
# 本地 JSON 儲存
# ---------------------------------------------------------------------------

def _results_path(db_title: str, db_id: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in db_title)[:60]
    return RESULTS_DIR / f"{safe or db_id[:8]}.json"


def load_result_file(db_title: str, db_id: str) -> dict:
    """載入既有結果檔；若不存在則回傳空結構。"""
    path = _results_path(db_title, db_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "db_id": db_id,
        "db_title": db_title,
        "batch_id": None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "records": [],
    }


def save_result_file(data: dict, db_title: str, db_id: str) -> Path:
    data["updated_at"] = datetime.now().isoformat()
    path = _results_path(db_title, db_id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _make_record(page: dict) -> dict:
    return {
        "page_id":           page["page_id"],
        "notion_id":         page["notion_id"],
        "paragraph":         page["paragraph"],
        "categories":        [],
        "reason":            "",
        "keywords":          [],
        "written_to_notion": False,
        "written_at":        None,
        "error":             None,
    }


# ---------------------------------------------------------------------------
# 即時模式：逐筆呼叫 Claude
# ---------------------------------------------------------------------------

def classify_paragraph(paragraph: str) -> dict:
    response = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(paragraph)}],
    )
    return _parse_claude_json(response.content[0].text.strip())


# ---------------------------------------------------------------------------
# Batch 模式
# ---------------------------------------------------------------------------

def build_batch_requests(pages: list[dict]) -> list[dict]:
    requests = []
    for page in pages:
        if not page["paragraph"].strip():
            continue
        requests.append({
            "custom_id": page["page_id"],
            "params": {
                "model": "claude-haiku-4-5",
                "max_tokens": 400,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": build_user_prompt(page["paragraph"])}],
            },
        })
    return requests


def submit_batch(requests: list[dict], label: str = "") -> str:
    BATCH_STATE_DIR.mkdir(exist_ok=True)
    batch    = claude.messages.batches.create(requests=requests)
    batch_id = batch.id
    state    = {
        "batch_id":     batch_id,
        "label":        label,
        "submitted_at": datetime.now().isoformat(),
        "total":        len(requests),
        "page_ids":     [r["custom_id"] for r in requests],
    }
    (BATCH_STATE_DIR / f"{batch_id}.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  Batch 已送出：{batch_id}（共 {len(requests)} 筆）")
    return batch_id


def poll_batch(batch_id: str, poll_interval: int = 30) -> None:
    print(f"  輪詢中（每 {poll_interval} 秒）…")
    while True:
        batch  = claude.messages.batches.retrieve(batch_id)
        status = batch.processing_status
        c      = batch.request_counts
        done   = c.succeeded + c.errored
        total  = done + c.processing
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {status} | "
              f"完成 {done}/{total}（成功 {c.succeeded}，錯誤 {c.errored}）")
        if status == "ended":
            break
        time.sleep(poll_interval)


def collect_batch_results(batch_id: str, records_by_page_id: dict[str, dict]) -> None:
    """把 batch 結果填入 records_by_page_id（in-place）。"""
    for result in claude.messages.batches.results(batch_id):
        page_id = result.custom_id
        rec     = records_by_page_id.get(page_id)
        if rec is None:
            continue
        if result.result.type == "errored":
            rec["error"] = str(result.result.error)
            continue
        try:
            parsed           = _parse_claude_json(result.result.message.content[0].text.strip())
            rec["categories"] = parsed["categories"]
            rec["reason"]     = parsed["reason"]
            rec["keywords"]   = parsed["keywords"]
        except Exception as e:
            rec["error"] = f"解析失敗：{e}"


# ---------------------------------------------------------------------------
# Notion：欄位與資料操作
# ---------------------------------------------------------------------------

PROP_CATEGORY = "分類"
PROP_REASON   = "分類原因"
PROP_KEYWORDS = "關鍵字"


def list_child_databases(page_id: str) -> list[dict]:
    results, cursor = [], None
    while True:
        kwargs: dict = {"block_id": page_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.blocks.children.list(**kwargs)
        for block in resp.get("results", []):
            if block.get("type") == "child_database":
                results.append({
                    "db_id":  block["id"],
                    "title":  block.get("child_database", {}).get("title", ""),
                })
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def get_data_source_id(database_id: str) -> str:
    db      = notion.databases.retrieve(database_id=database_id)
    ds_list = db.get("data_sources", [])
    if not ds_list:
        raise ValueError(f"資料庫 {database_id} 沒有 data_sources")
    return ds_list[0]["id"]


def ensure_data_source_properties(ds_id: str) -> None:
    ds       = notion.data_sources.retrieve(ds_id)
    existing = ds.get("properties", {})
    to_add: dict = {}
    if PROP_CATEGORY not in existing:
        to_add[PROP_CATEGORY] = {"multi_select": {}}
        print(f"    -> 新增欄位：{PROP_CATEGORY}（Multi-select）")
    if PROP_REASON not in existing:
        to_add[PROP_REASON] = {"rich_text": {}}
        print(f"    -> 新增欄位：{PROP_REASON}（Text）")
    if PROP_KEYWORDS not in existing:
        to_add[PROP_KEYWORDS] = {"multi_select": {}}
        print(f"    -> 新增欄位：{PROP_KEYWORDS}（Multi-select）")
    if to_add:
        notion.data_sources.update(ds_id, properties=to_add)
        print("    欄位建立完成。[!] 請在 Notion UI 手動拖移欄位位置。")
    else:
        print(f"    欄位「{PROP_CATEGORY}」、「{PROP_REASON}」、「{PROP_KEYWORDS}」已存在。")


def _extract_text(rt: list) -> str:
    return "".join(b.get("plain_text", "") for b in rt)


def _is_unclassified(page: dict) -> bool:
    prop      = page.get("properties", {}).get(PROP_CATEGORY, {})
    prop_type = prop.get("type", "")
    if prop_type == "select":
        return not prop.get("select")
    if prop_type == "multi_select":
        return len(prop.get("multi_select", [])) == 0
    return True


def get_unclassified_pages(ds_id: str) -> list[dict]:
    results, cursor = [], None
    while True:
        kwargs: dict = {"page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.data_sources.query(ds_id, **kwargs)
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return [p for p in results if _is_unclassified(p)]


def parse_page(page: dict) -> dict:
    props = page["properties"]

    def get_rich(name: str) -> str:
        return _extract_text(props.get(name, {}).get("rich_text", []))

    def get_title(name: str) -> str:
        return _extract_text(props.get(name, {}).get("title", []))

    return {
        "page_id":   page["id"],
        "notion_id": get_title("ID"),
        "paragraph": get_rich("段落"),
        "page_num":  get_rich("頁數"),
    }


def _sanitize_option(name: str) -> str:
    """Notion multi_select 不允許逗號，將逗號替換為空格。"""
    return name.replace(",", " ").strip()


def write_record_to_notion(rec: dict, dry_run: bool) -> bool:
    """把單筆 record 寫入 Notion。成功回傳 True。"""
    if dry_run:
        return True
    try:
        cats = [_sanitize_option(c) for c in rec["categories"]]
        kws  = [_sanitize_option(kw) for kw in rec["keywords"]]
        notion.pages.update(
            page_id=rec["page_id"],
            properties={
                PROP_CATEGORY: {"multi_select": [{"name": c} for c in cats]},
                PROP_REASON:   {"rich_text":    [{"type": "text", "text": {"content": rec["reason"]}}]},
                PROP_KEYWORDS: {"multi_select": [{"name": kw} for kw in kws]},
            },
        )
        time.sleep(0.35)
        return True
    except Exception as e:
        rec["error"] = f"Notion 寫入失敗：{e}"
        return False


def write_all_records(result_data: dict, dry_run: bool) -> tuple[int, int]:
    """把 result_data["records"] 中 written_to_notion=False 的全部寫入 Notion。"""
    db_id    = result_data["db_id"]
    db_title = result_data["db_title"]
    success  = 0
    errors   = 0

    pending = [r for r in result_data["records"]
               if not r.get("written_to_notion") and not r.get("error") and r.get("categories")]

    for rec in pending:
        cats   = rec["categories"]
        reason = rec["reason"]
        kws    = rec["keywords"]
        print(f"      {rec['notion_id']} -> {' / '.join(cats)}")
        print(f"         原因：{reason}")
        print(f"         關鍵字：{', '.join(kws)}")

        ok = write_record_to_notion(rec, dry_run)
        if ok:
            if not dry_run:
                rec["written_to_notion"] = True
                rec["written_at"]        = datetime.now().isoformat()
            success += 1
        else:
            print(f"         x {rec.get('error', '未知錯誤')}")
            errors += 1

        # 每筆存檔，確保中途中斷也有記錄
        save_result_file(result_data, db_title, db_id)

    return success, errors


# ---------------------------------------------------------------------------
# 對單一 child_database 執行分類
# ---------------------------------------------------------------------------

def process_child_database(
    db_info:    dict,
    dry_run:    bool,
    idx:        int,
    batch_mode: bool = False,
) -> tuple[int, int]:
    db_id  = db_info["db_id"]
    title  = db_info["title"] or db_id
    print(f"\n  [{idx}] {title}")

    try:
        ds_id = get_data_source_id(db_id)
        print(f"      ds_id: {ds_id}")
    except Exception as e:
        print(f"      x 無法取得 data_source_id：{e}")
        return 0, 1

    ensure_data_source_properties(ds_id)

    raw_pages = get_unclassified_pages(ds_id)
    pages     = [parse_page(p) for p in raw_pages]
    pages     = [p for p in pages if p["paragraph"].strip()]
    print(f"      待處理：{len(pages)} 筆")

    if not pages:
        return 0, 0

    # 建立 / 載入本地結果檔
    result_data = load_result_file(title, db_id)
    existing_ids = {r["page_id"] for r in result_data["records"]}

    # 加入本次新取得的頁面
    for page in pages:
        if page["page_id"] not in existing_ids:
            result_data["records"].append(_make_record(page))

    save_result_file(result_data, title, db_id)

    # ---- Batch 模式 ----
    if batch_mode:
        requests = build_batch_requests(pages)
        batch_id = submit_batch(requests, label=title)
        result_data["batch_id"] = batch_id
        save_result_file(result_data, title, db_id)

        poll_batch(batch_id)

        records_by_id = {r["page_id"]: r for r in result_data["records"]}
        collect_batch_results(batch_id, records_by_id)
        save_result_file(result_data, title, db_id)  # 先存：Claude 結果已落地

        s, e = write_all_records(result_data, dry_run)
        return s, e

    # ---- 即時模式 ----
    records_by_id = {r["page_id"]: r for r in result_data["records"]}
    success = 0
    errors  = 0

    for i, page in enumerate(pages, 1):
        rec     = records_by_id[page["page_id"]]
        preview = page["paragraph"][:45].replace("\n", " ")
        print(f"      [{i:>3}] {page['notion_id']} | {preview}...")

        try:
            parsed           = classify_paragraph(page["paragraph"])
            rec["categories"] = parsed["categories"]
            rec["reason"]     = parsed["reason"]
            rec["keywords"]   = parsed["keywords"]
            save_result_file(result_data, title, db_id)  # Claude 結果落地

            cats   = rec["categories"]
            reason = rec["reason"]
            kws    = rec["keywords"]
            print(f"             -> {' / '.join(cats)}")
            print(f"                原因：{reason}")
            print(f"                關鍵字：{', '.join(kws)}")

            ok = write_record_to_notion(rec, dry_run)
            if ok:
                if not dry_run:
                    rec["written_to_notion"] = True
                    rec["written_at"]        = datetime.now().isoformat()
                success += 1
            else:
                print(f"                x {rec.get('error')}")
                errors += 1

            save_result_file(result_data, title, db_id)

        except Exception as e:
            rec["error"] = str(e)
            save_result_file(result_data, title, db_id)
            print(f"             x 失敗：{e}")
            errors += 1
            time.sleep(1)

    return success, errors


# ---------------------------------------------------------------------------
# 對一個頁面（含多個 child_database）執行
# ---------------------------------------------------------------------------

def process_page(
    page_id:    str,
    dry_run:    bool,
    label:      str,
    first_only: bool = False,
    batch_mode: bool = False,
) -> tuple[int, int]:
    print(f"\n{'='*60}")
    print(f"頁面：{label}（{page_id}）")

    child_dbs = list_child_databases(page_id)
    print(f"發現 {len(child_dbs)} 個 child_database")

    if first_only:
        child_dbs = child_dbs[:1]
        print("（first-only 模式：只處理第 1 個）")

    total_s = total_e = 0
    for idx, db_info in enumerate(child_dbs, 1):
        s, e     = process_child_database(db_info, dry_run, idx, batch_mode=batch_mode)
        total_s += s
        total_e += e

    print(f"\n  頁面小計：成功 {total_s} 筆，失敗 {total_e} 筆")
    return total_s, total_e


# ---------------------------------------------------------------------------
# --apply-local：從本地 JSON 補寫 Notion
# ---------------------------------------------------------------------------

def apply_local(json_path: str, dry_run: bool) -> None:
    path = Path(json_path)
    if not path.exists():
        print(f"找不到檔案：{json_path}")
        return

    result_data = json.loads(path.read_text(encoding="utf-8"))
    db_id    = result_data["db_id"]
    db_title = result_data["db_title"]

    pending = [r for r in result_data["records"]
               if not r.get("written_to_notion") and r.get("categories")]
    errored = [r for r in result_data["records"] if r.get("error")]

    print(f"檔案：{path.name}")
    print(f"資料庫：{db_title}")
    print(f"待補寫：{len(pending)} 筆，有錯誤記錄：{len(errored)} 筆")

    if not pending:
        print("沒有需要補寫的記錄。")
        return

    # 確認 Notion 欄位存在
    try:
        ds_id = get_data_source_id(db_id)
        ensure_data_source_properties(ds_id)
    except Exception as e:
        print(f"x 無法連接 Notion：{e}")
        return

    s, e = write_all_records(result_data, dry_run)
    print(f"\n補寫完成：成功 {s} 筆，失敗 {e} 筆。")
    if dry_run:
        print("（Dry-run 模式，未實際寫入）")


# ---------------------------------------------------------------------------
# --batch-resume：繼續輪詢並寫回
# ---------------------------------------------------------------------------

def resume_batch(batch_id: str, dry_run: bool) -> None:
    state_file = BATCH_STATE_DIR / f"{batch_id}.json"
    if not state_file.exists():
        print(f"找不到狀態檔：{state_file}")
        return

    state = json.loads(state_file.read_text(encoding="utf-8"))
    print(f"Batch：{batch_id}，標籤：{state.get('label', '')}，共 {state['total']} 筆")

    # 嘗試從 results/ 找對應的結果檔
    result_data = None
    for f in RESULTS_DIR.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("batch_id") == batch_id:
            result_data = data
            print(f"找到本地結果檔：{f.name}")
            break

    if result_data is None:
        print("找不到對應的本地結果檔，只能重建基本資訊（無段落文字）。")
        result_data = {
            "db_id":    "",
            "db_title": state.get("label", ""),
            "batch_id": batch_id,
            "created_at": state.get("submitted_at", ""),
            "updated_at": datetime.now().isoformat(),
            "records": [
                {"page_id": pid, "notion_id": pid[:8], "paragraph": "",
                 "categories": [], "reason": "", "keywords": [],
                 "written_to_notion": False, "written_at": None, "error": None}
                for pid in state["page_ids"]
            ],
        }

    poll_batch(batch_id)

    records_by_id = {r["page_id"]: r for r in result_data["records"]}
    collect_batch_results(batch_id, records_by_id)

    db_id    = result_data["db_id"]
    db_title = result_data["db_title"]
    if db_id:
        save_result_file(result_data, db_title, db_id)

    s, e = write_all_records(result_data, dry_run)
    print(f"\n完成：成功 {s} 筆，失敗 {e} 筆。")


# ---------------------------------------------------------------------------
# 新模式：統一送出 + 統一收結果
# ---------------------------------------------------------------------------

def _get_all_page_ids() -> list[tuple[str, str]]:
    page_id_1 = (
        os.environ.get("NOTION_PAGE_ID_1")
        or os.environ.get("NOTION_DATABASE_ID_1")
        or os.environ.get("NOTION_DATABASE_ID", "")
    )
    page_id_2 = (
        os.environ.get("NOTION_PAGE_ID_2")
        or os.environ.get("NOTION_DATABASE_ID_2", "")
    )
    pages = []
    if page_id_1:
        pages.append((page_id_1, "_1 頁面"))
    if page_id_2:
        pages.append((page_id_2, "_2 頁面"))
    return pages


def submit_all_mode(dry_run: bool) -> None:
    """對所有未完成的論文一次送出 batch，不等待結果。"""
    submitted: list[tuple[str, str, int]] = []
    skipped:   list[str] = []

    for page_id, label in _get_all_page_ids():
        print(f"\n{'='*60}")
        print(f"頁面：{label}")
        child_dbs = list_child_databases(page_id)

        for idx, db_info in enumerate(child_dbs, 1):
            db_id = db_info["db_id"]
            title = db_info["title"] or db_id
            print(f"\n  [{idx}] {title}")

            try:
                ds_id = get_data_source_id(db_id)
                ensure_data_source_properties(ds_id)

                raw_pages = get_unclassified_pages(ds_id)
                pages     = [parse_page(p) for p in raw_pages]
                pages     = [p for p in pages if p["paragraph"].strip()]

                if not pages:
                    print("      跳過：無待處理頁面")
                    skipped.append(title)
                    continue

                print(f"      待處理：{len(pages)} 筆")

                result_data  = load_result_file(title, db_id)
                existing_ids = {r["page_id"] for r in result_data["records"]}
                for page in pages:
                    if page["page_id"] not in existing_ids:
                        result_data["records"].append(_make_record(page))

                if dry_run:
                    print("      (Dry-run：略過送出)")
                    continue

                requests = build_batch_requests(pages)
                batch_id = submit_batch(requests, label=title)
                result_data["batch_id"] = batch_id
                save_result_file(result_data, title, db_id)
                submitted.append((title, batch_id, len(pages)))

            except Exception as e:
                print(f"      x 失敗：{e}")

    print(f"\n{'='*60}")
    print(f"送出完成：{len(submitted)} 個 batch，跳過（已完成）：{len(skipped)} 個")
    for title, bid, count in submitted:
        print(f"  {title}: {bid}（{count} 筆）")
    if submitted:
        print("\n等所有 batch 處理完後，執行：")
        print("  python notion_classify.py --collect-all")


def collect_all_mode(dry_run: bool) -> None:
    """輪詢所有待收的 batch，全部完成後統一寫入 Notion。
    同時補寫已有結果但尚未寫入 Notion 的記錄（如中途暫停的篇章）。"""
    RESULTS_DIR.mkdir(exist_ok=True)
    pending_batches: list[tuple[dict, Path, str]] = []  # (data, path, batch_id)
    write_only:      list[tuple[dict, Path]]       = []  # 已有結果，待寫 Notion

    for f in sorted(RESULTS_DIR.glob("*.json")):
        data     = json.loads(f.read_text(encoding="utf-8"))
        batch_id = data.get("batch_id")
        records  = data.get("records", [])

        has_uncollected = batch_id and any(
            not r.get("categories") and not r.get("error")
            for r in records
        )
        has_unwritten = any(
            not r.get("written_to_notion") and r.get("categories") and not r.get("error")
            for r in records
        )

        if has_uncollected:
            pending_batches.append((data, f, batch_id))
            print(f"  待收結果：{data['db_title']}（{batch_id}）")
        elif has_unwritten:
            write_only.append((data, f))
            print(f"  待寫 Notion：{data['db_title']}")

    if not pending_batches and not write_only:
        print("沒有待處理的 batch 或待寫入記錄。")
        return

    # --- 輪詢所有 pending batch，直到全部 ended ---
    if pending_batches:
        print(f"\n輪詢 {len(pending_batches)} 個 batch（每 30 秒）…")
        active = list(pending_batches)
        while active:
            still_active = []
            for data, f, batch_id in active:
                batch  = claude.messages.batches.retrieve(batch_id)
                status = batch.processing_status
                c      = batch.request_counts
                done   = c.succeeded + c.errored
                total  = done + c.processing
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] {data['db_title']}: "
                      f"{status} {done}/{total}（成功 {c.succeeded}，錯誤 {c.errored}）")
                if status != "ended":
                    still_active.append((data, f, batch_id))
            if still_active:
                active = still_active
                print(f"  --- {len(active)} 個仍處理中，30 秒後再查 ---\n")
                time.sleep(30)
            else:
                break

        # 收結果，加入 write_only
        for data, f, batch_id in pending_batches:
            records_by_id = {r["page_id"]: r for r in data["records"]}
            collect_batch_results(batch_id, records_by_id)
            save_result_file(data, data["db_title"], data["db_id"])
            write_only.append((data, f))
            print(f"  結果已收：{data['db_title']}")

    # --- 統一寫入 Notion ---
    print(f"\n開始寫入 Notion（共 {len(write_only)} 個資料庫）…")
    total_s = total_e = 0
    for data, f in write_only:
        print(f"\n  {data['db_title']}")
        try:
            ds_id = get_data_source_id(data["db_id"])
            ensure_data_source_properties(ds_id)
        except Exception as e:
            print(f"    x 無法連接 Notion：{e}")
            continue
        s, e     = write_all_records(data, dry_run)
        total_s += s
        total_e += e
        print(f"    成功 {s} 筆，失敗 {e} 筆")

    print(f"\n{'='*60}")
    print(f"全部完成！成功 {total_s} 筆，失敗 {total_e} 筆。")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Notion 段落分類與關鍵字擷取")
    parser.add_argument("--dry-run",      action="store_true",  help="只印出結果，不寫回 Notion")
    parser.add_argument("--first-only",   action="store_true",  help="只跑第一個 child_database")
    parser.add_argument("--all",          action="store_true",  help="跑兩個頁面中的全部論文")
    parser.add_argument("--batch",        action="store_true",  help="使用 Batch API（省 50% 費用）")
    parser.add_argument("--batch-resume", metavar="BATCH_ID",   help="繼續已送出的 batch")
    parser.add_argument("--apply-local",  metavar="JSON_FILE",  help="從本地 JSON 補寫 Notion")
    parser.add_argument("--submit-all",   action="store_true",  help="一次送出所有論文的 batch，不等待")
    parser.add_argument("--collect-all",  action="store_true",  help="輪詢所有 batch 並統一寫入 Notion")
    args = parser.parse_args()

    if args.apply_local:
        apply_local(args.apply_local, dry_run=args.dry_run)
        return

    if args.batch_resume:
        resume_batch(args.batch_resume, dry_run=args.dry_run)
        return

    if args.submit_all:
        print("※ 模式：統一送出所有 batch")
        submit_all_mode(dry_run=args.dry_run)
        return

    if args.collect_all:
        print("※ 模式：統一收結果並寫入 Notion")
        collect_all_mode(dry_run=args.dry_run)
        return

    flags = []
    if args.dry_run:    flags.append("Dry-run")
    if args.first_only: flags.append("First-only")
    if args.batch:      flags.append("Batch API（省 50% 費用）")
    if flags:
        print("※ 模式：" + "、".join(flags))

    page_id_1 = (
        os.environ.get("NOTION_PAGE_ID_1")
        or os.environ.get("NOTION_DATABASE_ID_1")
        or os.environ.get("NOTION_DATABASE_ID", "")
    )
    page_id_2 = (
        os.environ.get("NOTION_PAGE_ID_2")
        or os.environ.get("NOTION_DATABASE_ID_2", "")
    )

    if args.all:
        if not page_id_1 or not page_id_2:
            print("錯誤：--all 需要 NOTION_DATABASE_ID_1 與 NOTION_DATABASE_ID_2")
            return
        pages = [(page_id_1, "_1 頁面"), (page_id_2, "_2 頁面")]
    else:
        if not page_id_1:
            print("錯誤：請在 .env 設定 NOTION_DATABASE_ID 或 NOTION_PAGE_ID_1")
            return
        pages = [(page_id_1, "_1 頁面")]

    total_s = total_e = 0
    for page_id, label in pages:
        s, e    = process_page(page_id, args.dry_run, label,
                               first_only=args.first_only, batch_mode=args.batch)
        total_s += s
        total_e += e

    print(f"\n{'='*60}")
    print(f"全部完成！成功 {total_s} 筆，失敗 {total_e} 筆。")
    if args.dry_run:
        print("（Dry-run 模式，結果已存本地但未寫入 Notion）")


if __name__ == "__main__":
    main()
