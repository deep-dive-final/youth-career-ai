from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from bson import json_util
from utils.db import getMongoDbClient
import json
from datetime import datetime

def index(request):
    try:
        db = getMongoDbClient()
        collection = db['policies_sample'] 
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        def get_processed_data(cursor):
            data_list = json.loads(json_util.dumps(list(cursor)))
            for item in data_list:
                try:
                    # 날짜 형식 보정 
                    clean_date = item.get('apply_end_date', '').replace('.', '-').strip()
                    if clean_date:
                        end_date = datetime.strptime(clean_date[:10], '%Y-%m-%d')
                        delta = (end_date - today).days
                        
                        if delta < 0:
                            item['d_day_label'] = "마감"
                        elif delta == 0:
                            item['d_day_label'] = "Day"
                        else:
                            item['d_day_label'] = str(delta) 
                    else:
                        item['d_day_label'] = "-"
                except Exception as e:
                    print(f"계산 에러: {e}")
                    item['d_day_label'] = "-"
            return data_list

        context = {
            "recommended": get_processed_data(collection.find({}).limit(4)),
            "popular": get_processed_data(collection.find({}).sort("view_count", -1).limit(4)),
            "deadline": get_processed_data(collection.find({}).sort("apply_end_date", 1).limit(4)),
        }
        return render(request, "index.html", context)
    except Exception as e:
        print(f"Index 에러: {e}")
        return render(request, "index.html", {"error": str(e)})

@csrf_exempt
def getPolicyData(request):
    try:
        policy_type = "청년" if request.GET.get('type') == '1' else "취업"
        db = getMongoDbClient()
        collection = db['test']
        filtered = list(collection.find({"type": policy_type}))
        sanitized_data = json.loads(json_util.dumps(filtered))
        return JsonResponse({"status": "success", "data": sanitized_data}, json_dumps_params={'ensure_ascii': False})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    
    # 서류 준비 페이지
def apply_steps(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    collection = db['policies_sample']
    
    policy = collection.find_one({"policy_id": policy_id})
    
    # 서류 목록(임의)
    context = {
        "policy": policy,
        "required_docs": [
            {"name": "신분증 사본", "status": "필수"},
            {"name": "임대차 계약서 사본", "status": "필수"},
            {"name": "통장 사본", "status": "필수"},
            {"name": "소득 증빙 서류", "status": "필수"},
            {"name": "가족관계증명서", "status": "필수"},
            {"name": "신청서", "status": "필수", "ai": True}, # 신청서만 AI 작성 버튼 필요
        ]
    }
    return render(request, "apply_steps.html", context)

# 시뮬레이션 페이지
def simulate(request):
    return render(request, "simulate.html")