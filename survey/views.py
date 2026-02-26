from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from .recommend import build_query_text, embed_query_gemini, vector_search_policies, build_prefilter


import time, hashlib, random
import mlflow
from django.conf import settings
import os, json, uuid
from datetime import datetime, timezone
from pymongo import MongoClient
from pathlib import Path
from bson import ObjectId

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
# 상세정보 페이지 연결
# -------------------
@require_GET
def policy_detail(request):
    """
    GET /policy/detail/?id=...
    - survey-result에서 넘어온 policy_id로 정책 상세를 조회해서 policy-detail.html 렌더
    """
    policy_id = request.GET.get("id")
    if not policy_id:
        return render(request, "policy-detail.html", {"policy": None})

    db = get_db()

    # 1) policies 컬렉션의 _id가 ObjectId일 수도 있고, 문자열일 수도 있어서 둘 다 대응
    policy = None

    # (A) 먼저 _id가 문자열로 저장된 경우
    policy = db.policies.find_one({"_id": policy_id})
    if not policy:
        # (B) _id가 ObjectId인 경우
        try:
            policy = db.policies.find_one({"_id": ObjectId(policy_id)})
        except Exception:
            policy = None

    # (C) 혹시 policies 쪽이 policy_id 필드를 따로 쓰는 경우까지 대비
    if not policy:
        policy = db.policies.find_one({"policy_id": policy_id})

    if not policy:
        return render(request, "policy-detail.html", {"policy": None})

    # 2) submit_docs: 네 DB 구조에 맞춰 컬렉션/필드명 조정 가능
    #    (없으면 그냥 빈 리스트)
    submit_docs = list(db.submit_documents.find({"policy_id": policy_id}))

    # 3) template에서 쓰는 변수들 구성
    context = {
        "policy": policy,
        "submit_docs": submit_docs,
        # 아래 3개는 policy-detail.html이 기대하는 키라서 맞춰줌
        "age_text": policy.get("age_text") or policy.get("age") or None,
        "target_text": policy.get("target_text") or policy.get("target") or None,
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


def _hash_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:12]
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

         # --- 실험 로깅을 위한 타이밍 측정 ---
        t0 = time.perf_counter()

        query_text = build_query_text(profile)

        t1 = time.perf_counter()
        query_vec = embed_query_gemini(query_text)
        t2 = time.perf_counter()
        prefilter = build_prefilter(profile)   # ✅ 여기 추가
        hits = vector_search_policies(db, query_vec, topk=topk, prefilter=prefilter)  # ✅ 인자 추가
        t3 = time.perf_counter()

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

        # --- ✅ MLflow: 개발/샘플링 로깅 ---
        if MLFLOW_ENABLED and random.random() < MLFLOW_SAMPLE_RATE:
            mlflow.set_experiment(MLFLOW_EXPERIMENT)

            with mlflow.start_run(run_name=f"online_topk{topk}"):

                # -------------------------
                # params (비교 조건)
                # -------------------------
                mlflow.log_param("embedding_model", "models/gemini-embedding-001")
                mlflow.log_param("index", "vector_index_v2")
                mlflow.log_param("path", "embedding_gemini_v2")
                mlflow.log_param("numCandidates", 300)
                mlflow.log_param("limit_before_group", 80)
                mlflow.log_param("topk", topk)
                mlflow.log_param("db", DB_NAME)
                mlflow.log_param("collection", "policy_vectors")

                # ✅ prefilter 사용 여부
                mlflow.log_param("prefilter_on", bool(prefilter))

                # -------------------------
                # 개인정보 최소화
                # -------------------------
                mlflow.log_param("query_hash", _hash_text(query_text))
                mlflow.log_param("query_len", len(query_text))

                # -------------------------
                # metrics (지연/결과)
                # -------------------------
                mlflow.log_metric("latency_total_ms", (t3 - t0) * 1000)
                mlflow.log_metric("latency_embed_ms", (t2 - t1) * 1000)
                mlflow.log_metric("latency_search_ms", (t3 - t2) * 1000)
                mlflow.log_metric("returned_k", len(items))
                mlflow.log_metric("hits_raw_count", len(hits))

                if items:
                    mlflow.log_metric("top1_score", float(items[0]["score"]))

                # -------------------------
                # ✅ TopK 결과 artifact 저장
                # -------------------------
                mlflow.log_dict(
                    {
                        "prefilter_on": bool(prefilter),
                        "topk": topk,
                        "items": [
                            {
                                "policy_id": it["policy_id"],
                                "name": it["name"],
                                "score": it["score"],
                                "region": it["region"],
                            }
                            for it in items
                        ]
                    },
                    "retrieval_results.json"
                )


        return JsonResponse({
            "ok": True,
            "anon_id": anon_id,
            "query_text": query_text,
            "items": items,
        }, json_dumps_params={"ensure_ascii": False})

    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)

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
    
