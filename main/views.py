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
def index(request):
    try:
        db = getMongoDbClient()
        collection = db['policies'] 
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        def get_processed_data(cursor):
            data_list = json.loads(json_util.dumps(list(cursor)))
            for item in data_list:
                try:
                    clean_date = item.get('apply_end_date', '').replace('.', '-').strip()
                    if clean_date:
                        end_date = datetime.strptime(clean_date[:10], '%Y-%m-%d')
                        delta = (end_date - today).days
                        item['d_day_label'] = "마감" if delta < 0 else ("Day" if delta == 0 else str(delta))
                    else:
                        item['d_day_label'] = "-"
                except:
                    item['d_day_label'] = "-"
            return data_list

        context = {
            "recommended": get_processed_data(collection.find({}).limit(4)),
            "popular": get_processed_data(collection.find({}).sort("view_count", -1).limit(4)),
            "deadline": get_processed_data(collection.find({}).sort("apply_end_date", 1).limit(4)),
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
    
    # 대상 연령 및 자격 정보
    eligibility = policy.get('eligibility', {})
    age_text = f"만 {eligibility.get('age_min', '-')}세 ~ {eligibility.get('age_max', '-')}세"
    target_text = policy.get('participate_target', '상세 내용 확인 필요')

    # 신청 기간 및 D-Day 계산
    apply_period = policy.get('dates', {}).get('apply_period', '상세 페이지 확인')

    # 필요 서류 및 문의처
    docs_text = policy.get('required_docs_text', '공식 홈페이지를 통해 확인해 주세요.')
    agency = policy.get('supervising_agency', '담당 기관 확인 필요')
    contact = policy.get('inquiry_contact', '1600-1004') 

    context = {
        "policy": policy,
        "age_text": age_text,
        "target_text": target_text,
        "apply_period": apply_period,
        "docs_text": docs_text,
        "agency": agency,
        "contact": contact,
        "apply_url": policy.get('reference_url1') or policy.get('reference_url2') or "#"
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