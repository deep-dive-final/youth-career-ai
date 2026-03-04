import os
import re
from pymongo import MongoClient, UpdateOne
from dotenv import load_dotenv

load_dotenv()

ALLOWED = ["취업", "창업", "교육", "지원금", "심리/재도전"]

# ✅ 지원금은 별도 판정(오탐 방지)
MONEY_SIGNAL_WORDS = [
    "지원금", "수당", "장려금", "보조금", "바우처", "포인트", "현금",
    "지급", "환급", "입금", "지급액", "지원금액", "지급금", "지원비",
    "응시료 지원", "참가비 지원", "교육비 지원", "교통비 지원", "생활비 지원",
]
# "100,000원", "10만원" 같은 패턴만 인정 (⚠️ '원' 단독 키워드 금지)
MONEY_AMOUNT_REGEX = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원|(\d+)\s*만원")

RULES = {
    "취업": ["취업","구직","일자리","채용","고용","인턴","면접","직무","취직","취업연계","취업지원","취업성공","재취업"],
    "창업": ["창업","스타트업","사업화","예비창업","창업자","창업지원","시제품","아이디어","액셀러","엑셀러"],
    "교육": ["교육","훈련","강의","과정","프로그램","캠프","부트캠프","아카데미","연수","직업훈련","역량강화","자격증","기술교육","인력양성","수료"],
    "심리/재도전": ["심리","상담","자신감","회복","치유","스트레스","우울","불안","고립","은둔","쉬고","구직단념","니트","neet","재도전","재기","코칭","정서","사회복귀","동기","의욕"],
}

def norm(s: str) -> str:
    return (s or "").strip().lower()

def build_text(item: dict) -> str:

    parts = [
        item.get("plcyNm", ""),
        item.get("plcyKywdNm", ""),
        item.get("lclsfNm", ""),
        item.get("mclsfNm", ""), 
        item.get("plcyExplnCn", ""),
        item.get("plcySprtCn", "")
    ]
    return " ".join([p for p in parts if isinstance(p, str) and p.strip()])

def has_money_support(text: str) -> bool:
    t = norm(text)
    if any(norm(w) in t for w in MONEY_SIGNAL_WORDS):
        return True
    if MONEY_AMOUNT_REGEX.search(text):
        return True
    return False

def classify_sub_categories(text: str) -> list[str]:
    t = norm(text)
    tags = []

    # 취업/창업/교육/심리/재도전: 키워드 기반
    for cat in ["취업", "창업", "교육", "심리/재도전"]:
        keys = RULES.get(cat, [])
        if any(norm(k) in t for k in keys):
            tags.append(cat)

    # 지원금: 강한 증거 있을 때만
    if has_money_support(text):
        tags.append("지원금")

    # 중복 제거 + 순서 유지
    seen = set()
    tags = [x for x in tags if not (x in seen or seen.add(x))]

    # 안전장치: 5개 외 제거
    tags = [x for x in tags if x in ALLOWED]
    return tags
