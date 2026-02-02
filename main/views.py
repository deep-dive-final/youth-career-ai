from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from bson import json_util
from utils.db import getMongoDbClient
import json
from datetime import datetime
import os 
import google.generativeai as genai 
from dotenv import load_dotenv 
import re
from datetime import datetime
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# 서류 준비 페이지 (DB에서 required_docs_text 파싱)
def apply_steps(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    collection = db['policies'] 
    policy = collection.find_one({"policy_id": policy_id})
    
    docs_text = policy.get('required_docs_text', '')
    
    parts = re.split(r'\d+\.', docs_text)
    
    processed_docs = []
    for part in parts:
        sub_items = re.split(r'[\n,]', part)
        for item in sub_items:
            clean = re.sub(r'\([^\)]+\)', '', item).strip()
            
            if len(clean) >= 2:
                processed_docs.append({
                    "name": clean,
                    "can_ai": any(kw in clean for kw in ["신청서", "동의서", "계획서", "자기소개서"])
                })

    return render(request, "apply_steps.html", {
        "policy": policy,
        "required_docs": processed_docs,
        "total_count": len(processed_docs)
    })

# 신청서 작성 페이지
def apply_form(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    collection = db['policies']
    policy = collection.find_one({"policy_id": policy_id})
    return render(request, "apply_form.html", {"policy": policy})

# AI가 답변을 생성하는 API 
@csrf_exempt
def ai_generate_motivation(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            user_name = data.get('name', '신청자')
            policy_name = data.get('policy_name', '해당 정책')
            
            model = genai.GenerativeModel('gemini-1.5-flash') 
            prompt = f"{user_name}님이 '{policy_name}' 정책에 신청하려고 합니다. 성실함이 느껴지는 신청 동기를 300자 내외로 정중하게 작성해줘."
            
            response = model.generate_content(prompt)
            return JsonResponse({"status": "success", "result": response.text})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})

# 메인 페이지 (인덱스)
from datetime import datetime

def index(request):
    try:
        db = getMongoDbClient()
        collection = db['policies']
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        def get_processed_data(cursor):
            import json
            from bson import json_util
            from datetime import datetime
            
            # 오늘 날짜 설정 (시간 제외)
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            data_list = json.loads(json_util.dumps(list(cursor)))
            
            for item in data_list:
                # 1. dates라는 이름의 객체(dict)를 먼저 가져옵니다.
                dates_obj = item.get('dates', {})
                
                # 2. 그 안에서 apply_period_end 값을 꺼냅니다.
                end_date_str = dates_obj.get('apply_period_end', '')
                
                # 3. 값이 있고, '상시'를 뜻하는 99991231이 아닐 때만 D-Day 계산
                if end_date_str and end_date_str != "99991231":
                    try:
                        # DB 날짜 형식(YYYYMMDD)을 파이썬 날짜로 변환
                        end_date = datetime.strptime(end_date_str, "%Y%m%d")
                        delta = (end_date - today).days
                        
                        if delta > 0:
                            item['d_day_label'] = f"D-{delta}"
                        elif delta == 0:
                            item['d_day_label'] = "D-Day"
                        else:
                            item['d_day_label'] = "마감"
                    except Exception as e:
                        # 날짜 형식이 이상하면 그냥 마감일 날짜라도 보여줌
                        item['d_day_label'] = "-"
                else:
                    # 데이터가 아예 없거나 99991231일 때만 '상시'로 표시
                    item['d_day_label'] = "상시"
                    
            return data_list

        context = {
            "recommended": get_processed_data(collection.find({}).limit(4)),
            "popular": get_processed_data(collection.find({}).sort("view_count", -1).limit(4)),
            "deadline": get_processed_data(collection.find({"apply_period_end": {"$ne": "99991231"}}).sort("apply_period_end", 1).limit(4)),
        }
        return render(request, "index.html", context)
    except Exception as e:
        return render(request, "index.html", {"error": str(e)})

# 시뮬레이션 페이지
def simulate(request):
    return render(request, "simulate.html")

# 정책 상세 페이지 함수 추가
def policy_detail(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    collection = db['policies']
    policy = collection.find_one({"policy_id": policy_id})
    
    if not policy:
        return render(request, "index.html", {"error": "DB에서 정책을 찾을 수 없습니다."})

    app_url = policy.get('application_url')
    ref_url1 = policy.get('reference_url1')
    ref_url2 = policy.get('reference_url2')
    
    target_link = app_url or ref_url1 or ref_url2 or "https://www.youthcenter.go.kr"

    context = {
        "policy": policy,
        "docs_info": policy.get('required_docs_text'), 
        "link": target_link, 
        "age_range": f"만 {policy.get('eligibility', {}).get('age_min', '-')}세 ~ {policy.get('eligibility', {}).get('age_max', '-')}세",
        "target_info": policy.get('participate_target', ''),
        "apply_period": policy.get('dates', {}).get('apply_period', '상시모집') 
    }
    return render(request, "policy_detail.html", context)

# D-Day 계산 로직

def policy_detail(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    collection = db['policies']
    policy = collection.find_one({"policy_id": policy_id})
    
    if not policy:
        return render(request, "index.html", {"error": "DB에서 정책을 찾을 수 없습니다."})

    d_day_text = "상시모집"
    end_date_str = policy.get('apply_end_date') 
    
    if end_date_str and end_date_str != "99991231": 
        try:
            end_date = datetime.strptime(end_date_str, "%Y%m%d")
            today = datetime.now()
            delta = end_date - today
            
            if delta.days > 0:
                d_day_text = f"D-{delta.days}"
            elif delta.days == 0:
                d_day_text = "D-Day"
            else:
                d_day_text = "모집 마감"
        except ValueError:
            d_day_text = "기간 확인 필요"

    context = {
        "policy": policy,
        "d_day": d_day_text,  
        "link": policy.get('application_url') or policy.get('reference_url1') or "#",
        "docs_info": policy.get('required_docs_text'),
        "age_range": f"만 {policy.get('eligibility', {}).get('age_min', '-')}세 ~ {policy.get('eligibility', {}).get('age_max', '-')}세",
        "target_info": policy.get('participate_target', ''),
        "apply_period": f"{policy.get('apply_start_date', '-')} ~ {policy.get('apply_end_date', '-')}" 
    }
    return render(request, "policy_detail.html", context)




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