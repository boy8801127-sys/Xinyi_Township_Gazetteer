# -*- coding: utf-8 -*-
"""
修復 6 筆寫入失敗的記錄：
  - 逗號錯誤（4 筆）：關鍵字逗號改空格，重新寫入 Notion
  - 網路斷線（2 筆）：重新送 Claude 分類，再寫入 Notion
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from notion_client import Client

# 從 notion_classify 引入共用函式
from notion_classify import (
    RESULTS_DIR,
    SYSTEM_PROMPT,
    build_user_prompt,
    _parse_claude_json,
    _sanitize_option,
    write_record_to_notion,
    save_result_file,
    PROP_CATEGORY, PROP_REASON, PROP_KEYWORDS,
)

load_dotenv()
claude  = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
notion  = Client(auth=os.environ["NOTION_API_KEY"])

# ---------------------------------------------------------------------------
# 分類
# ---------------------------------------------------------------------------

COMMA_IDS   = {"P14-150", "P41-223", "P6-361", "P8-18"}
NETWORK_IDS = {"P16-330", "P52-135"}
ALL_TARGET  = COMMA_IDS | NETWORK_IDS


def reclassify(paragraph: str) -> dict:
    resp = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(paragraph)}],
    )
    return _parse_claude_json(resp.content[0].text.strip())


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    remaining = set(ALL_TARGET)

    for f in sorted(RESULTS_DIR.glob("*.json")):
        data    = json.loads(f.read_text(encoding="utf-8"))
        changed = False

        for rec in data.get("records", []):
            nid = rec.get("notion_id", "")
            if nid not in remaining:
                continue

            print(f"\n處理 {nid}（{data['db_title']}）")
            print(f"  原 error：{rec.get('error', '')[:80]}")

            if nid in COMMA_IDS:
                # 逗號改空格，不需要重新分類
                rec["keywords"]   = [kw.replace(",", " ").strip() for kw in rec.get("keywords", [])]
                rec["categories"] = [c.replace(",", " ").strip()  for c  in rec.get("categories", [])]
                rec["error"]      = None
                print(f"  關鍵字修正後：{rec['keywords']}")

            elif nid in NETWORK_IDS:
                # 重新呼叫 Claude
                paragraph = rec.get("paragraph", "")
                if not paragraph.strip():
                    print("  x 段落為空，跳過")
                    continue
                try:
                    parsed            = reclassify(paragraph)
                    rec["categories"] = parsed["categories"]
                    rec["reason"]     = parsed["reason"]
                    rec["keywords"]   = parsed["keywords"]
                    rec["error"]      = None
                    print(f"  重新分類：{rec['categories']}")
                    print(f"  關鍵字：{rec['keywords']}")
                except Exception as e:
                    print(f"  x 重新分類失敗：{e}")
                    continue

            # 寫入 Notion
            ok = write_record_to_notion(rec, dry_run=False)
            if ok:
                rec["written_to_notion"] = True
                rec["written_at"]        = datetime.now().isoformat()
                print(f"  -> Notion 寫入成功")
                remaining.discard(nid)
            else:
                print(f"  x Notion 寫入失敗：{rec.get('error', '')}")

            changed = True
            time.sleep(0.35)

        if changed:
            save_result_file(data, data["db_title"], data["db_id"])

    print(f"\n{'='*50}")
    if not remaining:
        print("全部 6 筆修復完成。")
    else:
        print(f"仍有 {len(remaining)} 筆未完成：{remaining}")


if __name__ == "__main__":
    main()
