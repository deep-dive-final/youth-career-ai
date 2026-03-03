from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from .recommend import build_query_text, embed_query_gemini, vector_search_policies, build_prefilter_region_only


import time, hashlib, random
import mlflow
from django.conf import settings
import os, json, uuid
from datetime import datetime, timezone
from pymongo import MongoClient
from pathlib import Path
from bson import ObjectId

from utils.cookie import get_cookie
from utils.jwt import decode_access_token, TokenError

# Create your views here.

# -------------------
# MongoDB 설정
# -------------------
MONGODB_URI = os.getenv("MONGODB_URI")
print("✅ DJANGO MONGODB_URI HOST =", (MONGODB_URI or "").split("@")[1].split("/")[0] if MONGODB_URI and "@" in MONGODB_URI else MONGODB_URI)
DB_NAME = "youth_career_ai_db"

# -------------------
# MLflow 설정 (환경변수 기반)
# -------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # manage.py 있는 폴더 기준으로 맞음
MLFLOW_ENABLED = os.getenv("MLFLOW_ENABLED", "1") == "1"      # 기본 ON
MLFLOW_EXPERIMENT = os.getenv("MLFLOW_EXPERIMENT", "policy-retrieval-gemini")
MLFLOW_SAMPLE_RATE = float(os.getenv("MLFLOW_SAMPLE_RATE", "1.0"))  # 기본 100%
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", f"file:{BASE_DIR / 'mlruns'}")

mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)


def get_db():
    return MongoClient(MONGODB_URI)[DB_NAME]

# --------------------------------------------------
# 사용자 식별 (JWT 쿠키 로그인 우선, 아니면 anon_id)
# --------------------------------------------------
def get_anon_id(request):
    """
    로그인 없을 때 사용자 구분용 ID (세션 기반)
    """
    anon_id = request.session.get("anon_id")
    if not anon_id:
        anon_id = str(uuid.uuid4())
        request.session["anon_id"] = anon_id
    return anon_id

def get_login_user_id_from_cookie(request):
    """
    JWT access 토큰(쿠키)에서 payload['sub'](user_id)를 꺼냄
    - 로그인 상태면 sub가 ObjectId 문자열로 들어있음(현재 jwt.py 기준)
    """
    access = get_cookie(request, settings.AUTH_COOKIE["ACCESS_NAME"])
    if not access:
        return None

    try:
        payload = decode_access_token(access)
        return payload.get("sub")
    except TokenError:
        return None

def get_profile_filter(request):
    """
    로그인 O  -> user_id(ObjectId) 기준
    로그인 X  -> anon_id(session) 기준
    """
    user_id = get_login_user_id_from_cookie(request)
    if user_id:
        try:
            return {"user_id": ObjectId(str(user_id))}
        except Exception:
            # 혹시 ObjectId 문자열이 아닐 경우(거의 없음)
            return {"user_id": str(user_id)}

    return {"anon_id": get_anon_id(request)}


def _hash_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:12]


# -------------------
# 기존 화면 렌더링
# -------------------
def survey(request):
    return render(request, "survey.html", {})

def result(request):
    return render(request, "survey-result.html", {})


# -------------------
# 정책 상세 페이지
# -------------------
@require_GET
def policy_detail(request):
    """
    GET /policy/detail/?id=...
    - policies 컬렉션에서 policy_id로 정책 상세 조회
    """
    policy_id = request.GET.get("id")
    if not policy_id:
        return render(request, "policy-detail.html", {"policy": None})

    db = get_db()

    # ✅ policy_id 필드로 조회 (기본)
    policy = db.policies.find_one({"policy_id": policy_id})

    # (선택) 혹시 _id로 넘어오는 경우도 대비
    if not policy:
        policy = db.policies.find_one({"_id": policy_id})
        if not policy:
            try:
                policy = db.policies.find_one({"_id": ObjectId(policy_id)})
            except Exception:
                policy = None

    if not policy:
        return render(request, "policy-detail.html", {"policy": None})

    # required_docs_text -> submit_docs 형태로 변환
    submit_docs = []
    required_docs_text = policy.get("required_docs_text")
    if required_docs_text:
        lines = [line.strip() for line in required_docs_text.split("\n") if line.strip()]
        submit_docs = [{"document_name": line} for line in lines]

    context = {
        "policy": policy,
        "submit_docs": submit_docs,
        "age_text": policy.get("age_text") or policy.get("age") or None,
        "target_text": policy.get("target_text") or policy.get("support_content") or None,
        "apply_period": policy.get("apply_period") or None,
        "link": policy.get("homepage") or policy.get("link") or policy.get("url") or None,
    }
    return render(request, "policy-detail.html", context)


# -------------------
# 설문 결과 저장 API
# -------------------
@csrf_exempt
@require_POST
def save_survey_answers(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        answers = payload.get("answers", {})

        db = get_db()
        profile_filter = get_profile_filter(request)

        doc = {
            **profile_filter,  # ✅ user_id 또는 anon_id가 들어감
            "age": answers.get("1"),
            "purpose": answers.get("2"),  
            "region": answers.get("3"),
            "education_level": answers.get("4"),
            "education_status": answers.get("5"),
            "job_status": answers.get("6"),
            "income_level": answers.get("7"),
            "updated_at": datetime.now(timezone.utc),
        }

        # ✅ 연결 확인 로그
        ping = db.client.admin.command("ping")
        print("✅ Mongo ping:", ping)
        print("✅ user_profiles filter:", profile_filter)

        result = db.user_profiles.update_one(
            profile_filter,
            {"$set": doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

        return JsonResponse(
            {
                "ok": True,
                "db": db.name,
                "collection": "user_profiles",
                "matched": result.matched_count,
                "upserted": bool(result.upserted_id),
                "profile_key": "user_id" if "user_id" in profile_filter else "anon_id",
                "profile_value": str(
                    profile_filter.get("user_id") or profile_filter.get("anon_id")
                ),
            },
            json_dumps_params={"ensure_ascii": False},
        )

    except Exception as e:
        print("❌ save_survey_answers error:", repr(e))
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


def _hash_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:12]
# -------------------
# 유저 설문 정보 가져오기
# -------------------
@require_GET
def recommend_policies(request):
    try:
        db = get_db()
        profile_filter = get_profile_filter(request)

        # ✅ 가장 최근 프로필 1개 가져오기 (updated_at 우선, 없으면 created_at)
        profile = db.user_profiles.find_one(
            profile_filter, sort=[("updated_at", -1), ("created_at", -1)]
        )
        if not profile:
            return JsonResponse({"ok": False, "error": "설문 정보가 없어요."}, status=400)

        topk = int(request.GET.get("topk", 10))

        t0 = time.perf_counter()
        query_text = build_query_text(profile)
        t1 = time.perf_counter()

        query_vec = embed_query_gemini(query_text)
        t2 = time.perf_counter()

        prefilter = build_prefilter_region_only(profile)
        hits = vector_search_policies(db, query_vec, topk=topk, prefilter=prefilter)
        t3 = time.perf_counter()

        items = []
        for h in hits:
            p = h.get("policy") or {}
            items.append(
                {
                    "policy_id": str(h.get("policy_id")),
                    "score": float(h.get("score") or 0),
                    "name": p.get("policy_name")
                    or p.get("title")
                    or p.get("name")
                    or "(제목없음)",
                    "category": p.get("category") or "기타",
                    "region": p.get("region") or p.get("address") or "전국",
                    "agency": p.get("supervising_agency") or p.get("agency") or "",
                    "apply_start_date": p.get("apply_start_date"),
                    "apply_end_date": p.get("apply_end_date"),
                    "homepage": p.get("homepage") or p.get("link"),
                    "reason_snippet": (h.get("reason_snippet") or "")[:200],
                }
            )

        return JsonResponse({
            "ok": True,
            # ✅ 어떤 프로필을 사용했는지 확인용으로 같이 내려주면 디버깅 쉬움
            "used_profile": {
                "anon_id": profile.get("anon_id"),
                "region": profile.get("region"),
                "age": profile.get("age"),
                "updated_at": profile.get("updated_at"),
            },
            "query_text": query_text,
            "items": items,
        }, json_dumps_params={"ensure_ascii": False})

    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)
    
    #---------------------
    #     MLFLOW 로깅
    #----------------------

    #      if MLFLOW_ENABLED and random.random() < MLFLOW_SAMPLE_RATE:
    #         mlflow.set_experiment(MLFLOW_EXPERIMENT)
    #         with mlflow.start_run(run_name=f"online_topk{topk}"):
    #             mlflow.log_param("embedding_model", "models/gemini-embedding-001")
    #             mlflow.log_param("db", DB_NAME)
    #             mlflow.log_param("collection", "policy_vectors")
    #             mlflow.log_param("topk", topk)
    #             mlflow.log_param("prefilter_on", bool(prefilter))
    #             mlflow.log_param("query_hash", _hash_text(query_text))
    #             mlflow.log_param("query_len", len(query_text))

    #             mlflow.log_metric("latency_total_ms", (t3 - t0) * 1000)
    #             mlflow.log_metric("latency_build_query_ms", (t1 - t0) * 1000)
    #             mlflow.log_metric("latency_embed_ms", (t2 - t1) * 1000)
    #             mlflow.log_metric("latency_search_ms", (t3 - t2) * 1000)
    #             mlflow.log_metric("returned_k", len(items))
    #             mlflow.log_metric("hits_raw_count", len(hits))
    #             if items:
    #                 mlflow.log_metric("top1_score", float(items[0]["score"]))

    #             mlflow.log_dict(
    #                 {
    #                     "prefilter_on": bool(prefilter),
    #                     "topk": topk,
    #                     "items": [
    #                         {
    #                             "policy_id": it["policy_id"],
    #                             "name": it["name"],
    #                             "score": it["score"],
    #                             "region": it["region"],
    #                         }
    #                         for it in items
    #                     ],
    #                 },
    #                 "retrieval_results.json",
    #             )

    #     return JsonResponse(
    #         {
    #             "ok": True,
    #             "used_profile": {
    #                 "profile_key": "user_id" if profile.get("user_id") else "anon_id",
    #                 "user_id": str(profile.get("user_id")) if profile.get("user_id") else None,
    #                 "anon_id": profile.get("anon_id"),
    #                 "region": profile.get("region"),
    #                 "age": profile.get("age"),
    #                 "updated_at": profile.get("updated_at"),
    #             },
    #             "query_text": query_text,
    #             "items": items,
    #         },
    #         json_dumps_params={"ensure_ascii": False},
    #     )

    # except Exception as e:
    #     print("❌ recommend_policies error:", repr(e))
    #     return JsonResponse({"ok": False, "error": str(e)}, status=500)

@require_GET
def policy_detail(request):
    """
    GET /policy/detail/?id=...
    survey-result에서 넘어온 policy_id로 정책 상세 조회
    """
    policy_id = request.GET.get("id")
    if not policy_id:
        return render(request, "policy-detail.html", {"policy": None})

    db = get_db()

    # ✅ 여기 핵심: policy_id 필드로 조회 (ObjectId 아님!)
    policy = db.policies.find_one({"policy_id": policy_id})

    if not policy:
        return render(request, "policy-detail.html", {"policy": None})

    # required_docs_text를 split해서 submit_docs처럼 사용
    submit_docs = []
    required_docs_text = policy.get("required_docs_text")

    if required_docs_text:
        # 줄바꿈 기준 분리
        lines = [line.strip() for line in required_docs_text.split("\n") if line.strip()]
        submit_docs = [{"document_name": line} for line in lines]

    context = {
        "policy": policy,
        "submit_docs": submit_docs,

        # policy-detail.html에서 쓰는 키들 매핑
        "age_text": None,  # DB에 없음
        "target_text": policy.get("support_content"),
        "apply_period": None,  # dates object 구조에 따라 추후 확장 가능
        "link": policy.get("homepage"),
    }

    return render(request, "policy-detail.html", context)
    
