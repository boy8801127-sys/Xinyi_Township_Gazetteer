# -*- coding: utf-8 -*-
"""信義鄉誌論文分類流程設定。"""
from pathlib import Path

# 專案根目錄（config 在 src/ 時，上層為根）
ROOT = Path(__file__).resolve().parent.parent

# 輸入（學位論文 PDF，來源代碼 98；期刊論文另外走 export_paragraphs_journal.py，
# 見 CLAUDE.md「id／source 欄位格式」段落）
PAPER_DIR = ROOT / "paper" / "碩博士論文"
CATEGORY_FILE = ROOT / "This_plan" / "類別.txt"
KEYWORDS_FILE = ROOT / "This_plan" / "類別關鍵字.json"

# 輸出
OUTPUT_DIR = ROOT / "output"
OUTPUT_ALL_CSV = OUTPUT_DIR / "總類別.csv"

# 註腳分離：頁面高度比例，y 大於此視為註腳區（預設頁底 20%）
FOOTNOTE_Y_RATIO = 0.80

# 註腳規則辨識：True 時，內容符合規則（《、〈、註腳編號等）也視為註腳，不只看位置
USE_FOOTNOTE_CONTENT_RULES = True

# 句號切分：視為句尾的符號
SENTENCE_END_CHARS = ("。", ".", "．")

# ===== 以下為段落與區段偵測相關設定 =====

# 摘要開始與結束關鍵字
ABSTRACT_START_KEYWORDS = ("中文摘要", "摘 要", "摘要", "Abstract")
ABSTRACT_END_KEYWORDS = ("關鍵字", "關鍵詞", "Keywords")

# 內文開始與結束關鍵字（實務上可視需要再增補）
BODY_START_KEYWORDS = ("第一章", "壹、緒論", "壹、前言", "緒論", "前言")
BODY_END_KEYWORDS = ("參考文獻", "Reference", "REFERENCES", "附錄")

# 小標題＋冒號視為新段落起點的關鍵詞
PARAGRAPH_HEADING_KEYWORDS = ("背景", "目的", "方法", "結果", "結論", "建議", "研究限制")

# 段落行距閾值倍數（相鄰兩行 gap > 行高中位數 * 此值 視為新段落）
PARAGRAPH_GAP_FACTOR = 1.5

# 段落合併：字數少於此值或僅含章節標題（第、章、節）時與下一段合併
MIN_PARAGRAPH_LENGTH = 10

# 段落長度上限：超過此字數則依句號再切分
MAX_PARAGRAPH_LENGTH = 200

# 章節截斷：符合任一 pattern 即視為新段落起點（內文用）
# 依優先順序：章 > 節 > 小節
SECTION_BREAK_PATTERNS = (
    r"第[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾\d]+[章篇]",  # 章級
    r"第[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾\d]+節",   # 節級
    r"[壹貳參肆伍陸柒捌玖拾][、．.]",                       # 大寫小節 壹、貳、
    r"(?<=[。\n])[一二三四五六七八九十][、．.]",             # 一、二、 需前有句號
    r"[（(](?:[一二三四五六七八九十]|\d{1,2})[）)]",        # （一）(1) 排除年份如(2003)
)

# 期刊論文（代碼 97）專用：章節編號習慣跟學位論文不同（常用「一、」而非「壹、」），
# 且標題常因 PDF 排版被拆成多行（例如「一、前」與「言」變兩行），BODY_START 除了
# 關鍵字比對，還會用「阿拉伯數字章節編號」正則輔助判斷起點，見
# src/export_paragraphs_journal.py。純新增，不影響既有 BODY_START_KEYWORDS 等常數
# 服務的學位論文流程。
JOURNAL_BODY_START_KEYWORDS = ("前言", "緒論", "研究背景", "研究動機", "Introduction")
JOURNAL_BODY_END_KEYWORDS = ("參考文獻", "Reference", "REFERENCES", "引用文獻", "附錄")
JOURNAL_SECTION_HEADING_RE = r"^([一二三四五六七八九十]+[、．.]|\d{1,2}[、．.](?!\d))"
