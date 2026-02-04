from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from bson import json_util
from utils.db import getMongoDbClient
import json
import os 
import google.generativeai as genai
from dotenv import load_dotenv 
import re
from datetime import datetime

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

GEMINI_MODEL = genai.GenerativeModel('models/gemini-2.5-flash')

# 페이지 렌더링 함수
def apply_steps(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    collection = db['policies'] 
    policy = collection.find_one({"policy_id": policy_id})
    if not policy: return render(request, "index.html", {"error": "정책 없음"})
    
    submit_docs = policy.get('submit_documents', [])
    processed_docs = [
        {
            "name": d.get('document_name', ''), 
            "is_mandatory": d.get('is_mandatory', False), 
            "can_ai": any(kw in d.get('document_name', '') for kw in ["신청서", "동의서", "계획서", "자기소개서", "서식"])
        } for d in submit_docs
    ]
    return render(request, "apply_steps.html", {"policy": policy, "required_docs": processed_docs, "total_count": len(processed_docs)})

def apply_form(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    policy = db['policies'].find_one({"policy_id": policy_id})
    return render(request, "apply_form.html", {"policy": policy})

# AI API 함수

@csrf_exempt
def ai_generate_motivation(request):
    try:
        data = json.loads(request.body)
        
        answers_list = data.get('answers', [])
        policy_name = data.get('policy_name', '해당 정책')
        doc_name = data.get('doc_name', '서류')
        section_name = data.get('section_name', '항목')

        user_context = "\n".join([f"- {ans}" for ans in answers_list])

        if not answers_list:
            return JsonResponse({"status": "error", "message": "입력된 답변이 없습니다."})

        prompt = f"""
        당신은 공공기관 및 지자체 지원사업 서류 작성 전문가입니다.
        아래 정보를 바탕으로 '{policy_name}'의 '{doc_name}' 내 '{section_name}' 섹션에 들어갈 전문적인 초안을 작성하세요.

        [사용자 입력 정보]
        {user_context}

        [작성 가이드라인]
        1. 사용자가 입력한 핵심 의도(예: 수익 창출, 목표 달성 등)를 유지하되, 서류에 적합한 전문 용어를 사용하세요.
        2. 문장은 자연스러운 단락 형태로 구성하세요.
        3. 도입부 - 본론(구체적 계획) - 결론(기대 효과)의 흐름을 갖춘 300자 내외의 초안을 만드세요.
        4. "[ ]"와 같은 빈칸은 남기지 말고 완성된 형태로 제공하세요.
        """

        response = GEMINI_MODEL.generate_content(prompt)
        
        return JsonResponse({
            "status": "success", 
            "result": response.text.strip()
        })
        
    except Exception as e:
        print(f"Draft Generation Error: {e}")
        return JsonResponse({"status": "error", "message": str(e)})

@csrf_exempt
def get_form_fields(request):
    """서류별 AI 맞춤 질문 생성"""
    doc_name = request.GET.get('doc', '서류')
    policy_name = request.GET.get('policy_name', '해당 지원 정책') 
    prompt = f"정책 {policy_name}의 {doc_name} 작성을 돕기 위한 기초 질문 2개를 JSON으로만 답해. 형식: {{'fields': [{{'id': 's1', 'label': '질문', 'questions': []}}]}}"
    
    try:
        response = GEMINI_MODEL.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text.replace('\n', ' '), re.DOTALL)
        if match:
            return JsonResponse(json.loads(match.group()))
        raise ValueError("AI 응답에서 JSON 형식을 찾을 수 없습니다.")
        
    except Exception as e:
        print(f"Form Field API Error: {e}")
        qs = ["현재 어떤 계획을 가지고 계신가요?", "구체적인 목표를 적어주세요."]
        if "영농" in doc_name:
            qs = ["현재 농사를 지으려는 지역은 어디인가요?", "가장 관심 있는 작물이나 품목은 무엇인가요?"]
        return JsonResponse({"fields": [{"id": "base", "label": f"{doc_name} 작성", "questions": qs}]})

# 공통 데이터 및 검색 함수들 
def index(request):
    try:
        db = getMongoDbClient()
        collection = db['policies']
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        def get_processed_data(cursor):
            data_list = json.loads(json_util.dumps(list(cursor)))
            for item in data_list:
                end_date_str = item.get('dates', {}).get('apply_period_end', '')
                if end_date_str and end_date_str != "99991231":
                    try:
                        delta = (datetime.strptime(end_date_str, "%Y%m%d") - today).days
                        item['d_day_label'] = f"D-{delta}" if delta > 0 else ("D-Day" if delta == 0 else "마감")
                    except: item['d_day_label'] = "-"
                else: item['d_day_label'] = "상시"
            return data_list

        return render(request, "index.html", {
            "recommended": get_processed_data(collection.find({}).limit(4)), 
            "popular": get_processed_data(collection.find({}).sort("view_count", -1).limit(4)), 
            "deadline": get_processed_data(collection.find({"apply_period_end": {"$ne": "99991231"}}).sort("apply_period_end", 1).limit(4))
        })
    except Exception as e: return render(request, "index.html", {"error": str(e)})

def simulate(request): return render(request, "simulate.html")

def policy_detail(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    policy = db['policies'].find_one({"policy_id": policy_id})
    if not policy: return render(request, "index.html")
    
    start = policy.get('dates', {}).get('apply_period_start', '')
    end = policy.get('dates', {}).get('apply_period_end', '')
    display_period = "상시 모집" if "99991231" in end else f"{start} ~ {end}"
    
    return render(request, "policy-detail.html", {
        "policy": policy, 
        "submit_docs": policy.get('submit_documents', []), 
        "apply_period": display_period, 
        "docs_info": policy.get('required_docs_text', ''), 
        "link": policy.get('application_url') or policy.get('reference_url1') or "#"
    })


def policy_list(request):
    """데이터 가공 없이 있는 그대로 861개를 화면에 쏟아냄"""
    try:
        db = getMongoDbClient()
        collection = db['policies']
        
        cursor = collection.find({}) 
        data_list = json.loads(json_util.dumps(list(cursor)))
        
        print(f"DEBUG: 현재 불러온 총 정책 개수 = {len(data_list)}")

        return render(request, "policy_list.html", {
            "policies": data_list,
            "title": "전체 정책 목록"
        })
    except Exception as e:
        import traceback
        print(f"❌ 치명적 오류:\n{traceback.format_exc()}")
        return render(request, "index.html", {"error": str(e)})
    

@csrf_exempt
def getPolicyData(request):
    try:
        p_type = "청년" if request.GET.get('type') == '1' else "취업"
        data = json.loads(json_util.dumps(list(getMongoDbClient()['test'].find({"type": p_type}))))
        return JsonResponse({"status": "success", "data": data}, json_dumps_params={'ensure_ascii': False})
    except Exception as e: 
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    
