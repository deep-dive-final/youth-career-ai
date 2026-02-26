"""
검색 앱 뷰
- 검색 화면 렌더링
- 정책 검색 API 응답
"""

from collections import Counter

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .services import search_policies
from utils.db import getMongoDbClient

MIN_JOB_STATUS_COUNT = 20


# ============================================================================
# 공통 유틸 함수
# ============================================================================

def _to_int(value, default):
    """
    쿼리 파라미터 값을 정수로 변환합니다.
    변환 실패 시 기본값을 반환합니다.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ============================================================================
# 1️⃣ 화면 렌더링
# ============================================================================

def index(request):
    """정책 검색 페이지를 렌더링합니다."""
    return render(request, "search.html", {})


# ============================================================================
# 2️⃣ 필터 옵션 API
# ============================================================================

@require_http_methods(["GET"])
def filter_options_api(request):
    """
    카테고리/서브카테고리/지역/직업상태 필터 옵션을 반환합니다.
    현재 UI 정책상 상위 카테고리는 일자리/교육으로 고정합니다.
    """
    try:
        db = getMongoDbClient()
        policies = db["policies"]

        def split_tokens(value):
            if value is None:
                return []
            if isinstance(value, list):
                raw = value
            else:
                raw = str(value).split(",")

            tokens = []
            for item in raw:
                token = str(item).strip()
                if token:
                    tokens.append(token)
            return tokens

        categories = ["일자리", "교육"]
        sub_categories = {}

        for category in categories:
            raw_values = policies.distinct(
                "sub_category",
                {"category": {"$regex": category}}
            )

            cleaned = set()
            for value in raw_values:
                for token in split_tokens(value):
                    cleaned.add(token)

            sub_categories[category] = sorted(cleaned)

        job_counter = Counter()
        region_counter = Counter()
        for doc in policies.find({}, {"job_type": 1, "region": 1, "_id": 0}):
            for token in split_tokens(doc.get("job_type")):
                job_counter[token] += 1
            for token in split_tokens(doc.get("region")):
                region_counter[token] += 1

        # UI에서는 이미 fallback OR(제한없음)을 사용하므로 직업 상태 옵션에서는 제외
        job_statuses = [
            token for token, _count in sorted(
                job_counter.items(),
                key=lambda x: (-x[1], x[0])
            )
            if token != "제한없음" and _count >= MIN_JOB_STATUS_COUNT
        ]

        # UI에서 특정 지역 선택 시 '전국'은 자동 포함되므로 옵션 목록에서는 제외
        regions = [
            token for token, _count in sorted(
                region_counter.items(),
                key=lambda x: (-x[1], x[0])
            )
            if token != "전국"
        ]

        return JsonResponse({
            "categories": categories,
            "sub_categories": sub_categories,
            "job_statuses": job_statuses,
            "regions": regions,
        })
    except Exception as error:
        print(f"Filter Options API Error: {error}", flush=True)
        return JsonResponse({"error": "Failed to load filter options."}, status=500)


# ============================================================================
# 3️⃣ 검색 API
# ============================================================================

@require_http_methods(["GET"])
def search_policies_api(request):
    """검색어/필터/페이지 정보를 받아 정책 검색 결과를 반환합니다."""
    try:
        query = request.GET.get("query", "").strip()
        filters = {}

        # 프론트 필터 값이 있을 때만 검색 조건에 포함합니다.
        category = request.GET.get("category")
        if category:
            filters["category"] = category

        # 개인 조건 필터
        age = _to_int(request.GET.get("age"), None)
        if age is not None:
            filters["age"] = age

        sub_category = request.GET.get("subCategory")
        if sub_category:
            filters["sub_category"] = sub_category

        region = request.GET.get("region")
        if region:
            filters["region"] = region

        job_status = request.GET.get("jobStatus")
        if job_status:
            filters["jobStatus"] = job_status

        # 마감여부 (openOnly=true → 모집중인 정책만)
        open_only = request.GET.get("openOnly")
        if open_only and open_only.lower() in ("true", "1"):
            filters["openOnly"] = True

        # 페이지네이션 기본값: page=1, page_size=20
        page = _to_int(request.GET.get("page"), 1)
        page_size = _to_int(request.GET.get("page_size"), 20)

        result = search_policies(query=query, filters=filters, page=page, page_size=page_size)

        if "error" in result:
            return JsonResponse(result, status=500)

        return JsonResponse(result)

    except Exception as error:
        print(f"Search API Error: {error}", flush=True)
        return JsonResponse({"error": "Internal Server Error"}, status=500)
