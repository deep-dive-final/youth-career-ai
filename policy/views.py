from django.shortcuts import render
from utils.db import getMongoDbClient
from django.views.decorators.http import require_GET
from pymongo import MongoClient
from bson import ObjectId
import os

def policy(request):
    policy_id = request.GET.get('id')
    
    db = getMongoDbClient()
    
    policy_data = db.policies.find_one({"policy_id": policy_id})
    
    return render(request, "policy-detail.html", {"policy": policy_data})

MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = "youth_career_ai_db"

def get_db():
    return MongoClient(MONGODB_URI)[DB_NAME]

@require_GET
def policy_detail_page(request):
    policy_id = request.GET.get("id")
    if not policy_id:
        return render(request, "policy-detail.html", {"policy": None})

    db = get_db()

    # ✅ 네 policies 문서는 policy_id가 문자열이므로 이게 1순위
    policy = db.policies.find_one({"policy_id": policy_id})

    # 혹시 추천에서 ObjectId가 넘어오는 경우도 대비 (2순위)
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
    "pid": str(policy.get("policy_id") or policy.get("_id")),  # ✅ 추가
    "submit_docs": submit_docs,
    "age_text": None,
    "target_text": policy.get("support_content"),
    "apply_period": None,
    "link": policy.get("reference_url") or policy.get("evaluation_method") or policy.get("homepage"),
    }
    return render(request, "policy-detail.html", context)