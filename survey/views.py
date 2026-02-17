from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .recommend import build_query_text
from django.views.decorators.http import require_GET
from .recommend import build_query_text, embed_query_gemini, vector_search_policies

import os, json, uuid
from datetime import datetime, timezone
from pymongo import MongoClient

# Create your views here.

# -------------------
# MongoDB 설정
# -------------------
MONGODB_URI = os.getenv("MONGODB_URI")
print("✅ DJANGO MONGODB_URI HOST =", (MONGODB_URI or "").split("@")[1].split("/")[0] if MONGODB_URI and "@" in MONGODB_URI else MONGODB_URI)
DB_NAME = "youth_career_ai_db"


def get_db():
    return MongoClient(MONGODB_URI)[DB_NAME]

def get_anon_id(request):
    """
    로그인 없을 때 사용자 구분용 ID (세션 기반)
    """
    anon_id = request.session.get("anon_id")
    if not anon_id:
        anon_id = str(uuid.uuid4())
        request.session["anon_id"] = anon_id
    return anon_id

# -------------------
# 기존 화면 렌더링
# -------------------
def survey(request):
    return render(request, "survey.html", {})

def result(request):
    return render(request, "survey-result.html", {})


# -------------------
# 설문 결과 저장 API
# -------------------
@csrf_exempt
@require_POST
def save_survey_answers(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        answers = payload.get("answers", {})

        anon_id = get_anon_id(request)

        doc = {
            "anon_id": anon_id,
            "age": answers.get("1"),
            "purpose": answers.get("2"),
            "region": answers.get("3"),
            "education_level": answers.get("4"),
            "education_status": answers.get("5"),
            "job_status": answers.get("6"),
            "income_level": answers.get("7"),
            "updated_at": datetime.now(timezone.utc),
        }


        db = get_db()

        # ✅ 연결 확인 (콘솔 로그)
        ping = db.client.admin.command("ping")
        print("✅ Mongo ping:", ping)
        print("✅ Using DB:", db.name, "Collection: user_profiles", "anon_id:", anon_id)

        # ✅ upsert 수행 + 결과 확인
        result = db.user_profiles.update_one(
            {"anon_id": anon_id},
            {
                "$set": doc,
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

        print("✅ matched:", result.matched_count, "✅ upserted_id:", result.upserted_id)

        # ✅ 프론트에서도 바로 확인 가능하게 응답 강화
        return JsonResponse({
            "ok": True,
            "db": db.name,
            "collection": "user_profiles",
            "matched": result.matched_count,
            "upserted": bool(result.upserted_id),
            "anon_id": anon_id,
        })

    except Exception as e:
        # ✅ 에러를 프론트에서 바로 볼 수 있게
        print("❌ save_survey_answers error:", repr(e))
        return JsonResponse({"ok": False, "error": str(e)}, status=500)

# -------------------
# 유저 설문 정보 가져오기
# -------------------
@require_GET
def recommend_policies(request):
    """
    GET /survey/api/recommend/?topk=5
    - user_profiles(anon_id) 기반으로 query 만들고
    - Gemini embedding -> vector search -> 정책 문서 붙여서 반환
    """
    try:
        db = get_db()
        anon_id = get_anon_id(request)

        profile = db.user_profiles.find_one({"anon_id": anon_id})
        if not profile:
            return JsonResponse({"ok": False, "error": "설문 정보가 없어요."}, status=400)

        topk = int(request.GET.get("topk", 5))

        query_text = build_query_text(profile)
        query_vec = embed_query_gemini(query_text)
        hits = vector_search_policies(db, query_vec, topk=topk)

        # 프론트가 쓰기 쉬운 형태로 가공
        items = []
        for h in hits:
            p = h.get("policy") or {}
            items.append({
                "policy_id": str(h.get("policy_id")),
                "score": float(h.get("score") or 0),
                "name": p.get("policy_name") or p.get("title") or p.get("name") or "(제목없음)",
                "category": p.get("category") or "기타",
                "region": p.get("region") or p.get("address") or "전국",
                "agency": p.get("supervising_agency") or p.get("agency") or "",
                "apply_start_date": p.get("apply_start_date"),
                "apply_end_date": p.get("apply_end_date"),
                "homepage": p.get("homepage") or p.get("link"),
                "reason_snippet": (h.get("reason_snippet") or "")[:200],
            })

        return JsonResponse({
            "ok": True,
            "anon_id": anon_id,
            "query_text": query_text,
            "items": items,
        }, json_dumps_params={"ensure_ascii": False})

    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)
