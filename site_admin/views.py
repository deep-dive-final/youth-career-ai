from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from site_admin.data import fetch_policy_data
import json
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from utils.db import getMongoDbClient
from bson import json_util

def data(request):
    return render(request, "data.html", {})

@csrf_exempt
def importData(request):
    try:
        page_num = request.GET.get('num')
        page_size = request.GET.get('size')
        fetch_policy_data(page_num, page_size)
        return JsonResponse({"status": "success", "data": {"count":1}}, json_dumps_params={'ensure_ascii': False})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
def getDataE5(request):
    try:
        search_text = request.GET.get('search-text')

        # 1. 검색어도 동일한 모델로 임베딩 변환
        model = SentenceTransformer('snunlp/KR-SBERT-V40K-klueNLI-augSTS')
        query_vector = model.encode(search_text).tolist()

        # 2. $vectorSearch 파이프라인 정의
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",           # 설정한 인덱스 이름
                    "path": "embedding_sbert",          # 벡터 필드
                    "queryVector": query_vector,  # 검색용 벡터
                    "numCandidates": 20,         # 후보군 수
                    "limit": 10                    # 최종 반환 결과 수
                }
            },
            {
                # 유사도 점수와 함께 필요한 필드만 가져오기
                "$project": {
                    "metadata": 1,
                    "score": { "$meta": "vectorSearchScore" }
                }
            }
        ]

        # 3. 검색 수행
        db = getMongoDbClient()
        collection = db['policy_vectors']
        results = collection.aggregate(pipeline)
        json_data = json.loads(json_util.dumps(list(results)))

        return JsonResponse({"status": "success", "data": json_data}, json_dumps_params={'ensure_ascii': False}, safe=False)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@csrf_exempt
def getDataGemini(request):
    try:
        search_text = request.GET.get('search-text')

        # 1. 검색어도 동일한 모델로 임베딩 변환
        model = SentenceTransformer('snunlp/KR-SBERT-V40K-klueNLI-augSTS')
        query_vector = model.encode(search_text).tolist()

        # 2. $vectorSearch 파이프라인 정의
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",           # 설정한 인덱스 이름
                    "path": "embedding_sbert",          # 벡터 필드
                    "queryVector": query_vector,  # 검색용 벡터
                    "numCandidates": 20,         # 후보군 수
                    "limit": 10                    # 최종 반환 결과 수
                }
            },
            {
                # 유사도 점수와 함께 필요한 필드만 가져오기
                "$project": {
                    "metadata": 1,
                    "score": { "$meta": "vectorSearchScore" }
                }
            }
        ]

        # 3. 검색 수행
        db = getMongoDbClient()
        collection = db['policy_vectors']
        results = collection.aggregate(pipeline)
        json_data = json.loads(json_util.dumps(list(results)))

        return JsonResponse({"status": "success", "data": json_data}, json_dumps_params={'ensure_ascii': False}, safe=False)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    