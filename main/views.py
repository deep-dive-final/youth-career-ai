from django import db
from django.shortcuts import render
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from bson import json_util
from utils.db import getMongoDbClient
import json

def index(request):
    return render(request, "index.html", {})

@csrf_exempt
def getPolicyData(request):
    try:
        type = "청년" if request.GET.get('type') == 1 else "취업"

        db = getMongoDbClient()
        collection = db['policy']   # 컬렉션(테이블 개념) 이름

        # MongoDB 쿼리 실행
        filtered = list(collection.find({"type": type}))

        # json_util.dumps를 사용하여 BSON을 JSON 문자열로 변환 후, 다시 Python 딕셔너리로 로드
        sanitized_data = json.loads(json_util.dumps(filtered))

        return JsonResponse({"status": "success", "data": sanitized_data}, json_dumps_params={'ensure_ascii': False})
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    