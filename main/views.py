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
from bson import ObjectId
import boto3
from django.conf import settings
from utils.auth import login_check

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

GEMINI_MODEL = genai.GenerativeModel('models/gemini-2.5-flash')

s3_client = boto3.client(
    's3',
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_S3_REGION_NAME
)

URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
GENERIC_TOKENS = {"", "제한없음", "기타", "무관"}

# 유틸리티 함수
def clean_doc_name(name):
    """서류 이름에서 괄호와 그 안의 내용을 제거 (예: '신청서(필수)' -> '신청서')"""
    if not name: return ""
    return re.sub(r'\(.*?\)', '', name).strip()


def _as_clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _is_url(value):
    return bool(URL_PATTERN.search(_as_clean_text(value)))


def _extract_first_url(text):
    match = URL_PATTERN.search(_as_clean_text(text))
    return match.group(0) if match else None


def _pick_apply_link(policy):
    application_url = _as_clean_text(policy.get("application_url"))
    if _is_url(application_url):
        return application_url
    return _extract_first_url(policy.get("how_to_apply"))


def _pick_official_homepage_link(policy):
    for key in ("reference_url1", "reference_url2", "application_url"):
        value = _as_clean_text(policy.get(key))
        if _is_url(value):
            return value
    return None


def _split_tokens(value):
    if value is None:
        return []

    raw_values = value if isinstance(value, list) else [value]
    tokens = []
    for raw in raw_values:
        text = str(raw)
        for token in re.split(r"[,/\n]", text):
            cleaned = token.strip()
            if cleaned:
                tokens.append(cleaned)
    return tokens


def _filter_informative_tokens(tokens):
    filtered = []
    seen = set()
    for token in tokens:
        normalized = token.strip()
        if normalized in GENERIC_TOKENS:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        filtered.append(normalized)
    return filtered


def _build_apply_period_label(policy):
    dates = policy.get("dates") or {}

    start = _as_clean_text(dates.get("apply_period_start"))
    end = _as_clean_text(dates.get("apply_period_end"))
    if start and end:
        return f"{start} ~ {end}"

    apply_period_type = _as_clean_text(dates.get("apply_period_type"))
    if apply_period_type == "마감":
        return "마감"

    raw_period = _as_clean_text(dates.get("apply_period"))
    if raw_period:
        normalized = raw_period.replace("\\N", "\n")
        parts = [line.strip() for line in normalized.splitlines() if line.strip()]
        if parts:
            return " / ".join(parts)

    return "공고문 확인"


def _to_positive_int(value):
    text = _as_clean_text(value)
    if not text:
        return None

    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return None

    if number <= 0:
        return None
    return number


def _build_eligibility_age_label(policy):
    eligibility = policy.get("eligibility") or {}
    age_min = _to_positive_int(eligibility.get("age_min"))
    age_max = _to_positive_int(eligibility.get("age_max"))

    if age_min is None or age_max is None:
        return "공고문 확인"
    return f"만 {age_min}세 ~ {age_max}세"


def _build_requirements_context(policy):
    support_content = _as_clean_text(policy.get("support_content"))
    eligibility_text = _as_clean_text((policy.get("eligibility") or {}).get("text"))
    restricted_target = _as_clean_text(policy.get("restricted_target"))

    structured_map = {
        "지역 조건": _filter_informative_tokens(_split_tokens(policy.get("region"))),
        "직업 상태": _filter_informative_tokens(_split_tokens(policy.get("job_type"))),
        "학력/학적 조건": _filter_informative_tokens(_split_tokens(policy.get("school_type"))),
        "특화 요건": _filter_informative_tokens(_split_tokens(policy.get("policy_specific_type"))),
    }

    lines = [
        f"[지원 요건]: {support_content}",
        f"[기타 자격]: {eligibility_text}",
        f"[신청 제외/제한]: {restricted_target}",
    ]

    structured_lines = []
    for label, values in structured_map.items():
        if values:
            structured_lines.append(f"- {label}: {', '.join(values)}")

    if structured_lines:
        lines.append("[추가 구조화 조건]")
        lines.extend(structured_lines)

    return "\n".join(lines)

# 페이지 렌더링 함수

def apply_steps(request):
    policy_id = str(request.GET.get('id'))
    db = getMongoDbClient()
    
    policy = db['policies'].find_one({"policy_id": policy_id})
    if not policy: return render(request, "index.html", {"error": "정책 없음"})
    
    # AI 작성본 DB 조회 및 클리닝
    completed_docs = list(db['user_policy_document'].find({"user_id": "guest_user", "policy_id": policy_id}))
    completed_names = [clean_doc_name(d.get('doc_name') or d.get('document_type')) for d in completed_docs]

    # 직접 업로드한 파일 DB 조회 및 클리닝
    uploaded_files = list(db['user_policy_file'].find({"user_id": "guest_user", "policy_id": policy_id}))
    
    submit_docs = policy.get('submit_documents', [])
    processed_docs = []
    
    exclude_keywords = ["등본", "초본", "수료증", "증명서", "확인서", "자격증", "증빙"]

    for d in submit_docs:
        raw_name = d.get('document_name', '')
        pure_name = clean_doc_name(raw_name)
        
        is_ai_possible = any(kw in pure_name for kw in ["신청서", "동의서", "계획서", "자기소개서", "서식"]) \
                         and not any(ex in pure_name for ex in exclude_keywords)

        is_completed = any(clean_doc_name(name) == pure_name for name in completed_names)
        
        # 업로드된 파일 정보 찾기
        file_info = next((f for f in uploaded_files if clean_doc_name(f.get('doc_name', '')) == pure_name), None)
        is_uploaded = file_info is not None
        file_url = file_info.get('file_url') if is_uploaded else "#"

        processed_docs.append({
            "name": raw_name,
            "is_mandatory": d.get('is_mandatory', False),
            "can_ai": is_ai_possible,
            "is_completed": is_completed,
            "is_uploaded": is_uploaded,
            "file_url": file_url  
        })

    completed_count = len([d for d in processed_docs if d['is_completed'] or d['is_uploaded']])

    return render(request, "apply_steps.html", {
        "policy": policy, 
        "required_docs": processed_docs, 
        "total_count": len(processed_docs),
        "completed_count": completed_count
    })


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
    """정책 상세 내용을 기반으로 서류별 맞춤 질문 생성"""
    policy_id = request.GET.get('id') 
    doc_name = request.GET.get('doc', '서류')
    
    db = getMongoDbClient()
    collection = db['policies']
    
    policy = collection.find_one({"policy_id": policy_id})
    if not policy:
        print(f"❌ DB 조회 실패: policy_id={policy_id}")
        return JsonResponse({"error": "정책 정보를 찾을 수 없습니다."}, status=404)
    
    content = policy.get('content', '일반 지원 사업')
    p_name = policy.get('policy_name', '해당 정책')

    prompt = f"""
    당신은 공공기관 지원사업 서류 작성 전문가이자 도우미입니다. 
    과거의 모든 데이터는 무시하고, 오직 아래 [정책 내용]에만 근거해서 [{doc_name}] 작성을 위한 맞춤형 질문 2개를 생성하세요.
    
    [정책 내용]: {content[:2000]} 
    
    지시사항:
    1. 질문은 반드시 [{doc_name}]이라는 서류의 특수성과 맥락을 반영해야 합니다. 
       (예: 신청서라면 지원 동기, 계획서라면 구체적 실행 방안 등)
    2. 사용자가 답변하기 쉽도록 구체적인 예시나 방향성을 포함한 질문을 만드세요.
    3. 정책의 지원 대상, 혜택, 목적과 직결된 질문이어야 합니다.
    4. 결과는 반드시 아래 JSON 형식을 엄격히 지켜 답변하세요. 다른 설명 텍스트는 일절 금지합니다.

    {{
      "policy_name": "{p_name}",
      "fields": [
        {{
          "id": "q_group_1",
          "label": "{doc_name} 작성을 위한 핵심 질문",
          "questions": ["질문 1 내용", "질문 2 내용"]
        }}
      ]
    }}
    """
    
    try:
        response = GEMINI_MODEL.generate_content(
            prompt,
            generation_config={ "response_mime_type": "application/json" }
        )
        
        res_text = response.text.strip()
        
        start_idx = res_text.find('{')
        end_idx = res_text.rfind('}') + 1
        \
        if start_idx != -1:
            return JsonResponse(json.loads(res_text[start_idx:end_idx]))
        
        raise ValueError("AI 응답에서 JSON 구조를 찾을 수 없습니다.")

    except Exception as e:
        print(f"🔥 AI 질문 생성 에러: {e}")
        # 에러 발생 시 질문
        return JsonResponse({
            "policy_name": p_name,
            "fields": [{
                "id": "base",
                "label": f"{doc_name} 기본 정보 확인",
                "questions": [
                    f"이 사업의 공고 내용 중 어떤 부분이 본인의 상황과 가장 잘 맞는다고 생각하시나요?",
                    f"해당 {doc_name}을(를) 통해 기관에 어필하고 싶은 본인만의 차별점은 무엇인가요?"
                ]
            }]
        })

@csrf_exempt
def save_application(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            db = getMongoDbClient()
            collection = db['user_policy_document']
        
            pure_doc_name = clean_doc_name(data.get('doc_name'))
            
            save_data = {
                "policy_id": str(data.get('policy_id')), 
                "user_id": data.get('user_id', "guest_user"),
                "doc_name": pure_doc_name, 
                "document_content": data.get('content'),
                "insert_at": datetime.now()
            }
            
            collection.update_one(
                {"policy_id": save_data["policy_id"], "user_id": save_data["user_id"], "doc_name": pure_doc_name},
                {"$set": save_data},
                upsert=True
            )
            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

        
def get_saved_document(request):
    policy_id = request.GET.get('id')
    raw_doc = request.GET.get('doc')
    pure_doc = clean_doc_name(raw_doc)
    
    db = getMongoDbClient()
    
    saved_doc = db['user_policy_document'].find_one(
        {
            "doc_name": pure_doc, 
            "user_id": "guest_user", 
            "policy_id": str(policy_id) 
        },
        sort=[("insert_at", -1)]
    )
    
    if saved_doc:
        return JsonResponse({
            "status": "success",
            "content": saved_doc.get('document_content', ''),
            "is_current": True
        })
    
    legacy_doc = db['user_policy_document'].find_one(
        {
            "document_type": pure_doc, 
            "user_id": "guest_user", 
            "policy_id": str(policy_id)
        },
        sort=[("insert_at", -1)]
    )
    
    if legacy_doc:
        return JsonResponse({
            "status": "success",
            "content": legacy_doc.get('document_content', ''),
            "is_current": True
        })

    return JsonResponse({"status": "error"})


@csrf_exempt
def upload_to_s3(request):
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        policy_id = request.POST.get('id')
        incoming_doc_name = request.POST.get('doc')
        user_id = request.POST.get('user_id', 'guest_user')
        
        doc_name = clean_doc_name(incoming_doc_name) 
        db = getMongoDbClient()

        try:
            bucket_name = settings.AWS_STORAGE_BUCKET_NAME
            file_path = f"policy_{policy_id}/{user_id}/{doc_name}_{file.name}"
            
            s3_client.upload_fileobj(
                file,
                bucket_name,
                file_path,
                ExtraArgs={'ContentType': file.content_type}
            )
            
            file_url = f"https://{bucket_name}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{file_path}"
            
            db['user_policy_file'].update_one(
                {"policy_id": policy_id, "user_id": user_id, "doc_name": doc_name},
                {"$set": {
                    "policy_id": policy_id,
                    "user_id": user_id,
                    "doc_name": doc_name,
                    "file_name": file.name,
                    "file_url": file_url,
                    "insert_at": datetime.now()
                }},
                upsert=True
            )
            
            return JsonResponse({"status": "success", "url": file_url})
            
        except Exception as e:
            print(f"S3 Upload Error: {e}")
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "error", "message": "잘못된 요청입니다."})

@csrf_exempt
def get_policy_requirements(request):
    policy_id = request.GET.get('id')
    if not policy_id:
        return JsonResponse({"status": "error", "message": "policy_id가 필요합니다."}, status=400)

    db = getMongoDbClient()
    policy = db['policies'].find_one({"policy_id": policy_id})

    if not policy:
        return JsonResponse({"status": "error", "message": "정책 정보를 찾을 수 없습니다."}, status=404)

    context = _build_requirements_context(policy)
# AI 프롬프트
    prompt = f"""
    당신은 정책 자격 진단 전문가입니다. 아래의 [정책 데이터]를 분석하여 신청 자격 목록을 생성하세요.

    [정책 데이터]
    {context}

    [지시사항]
    1. 사용자가 본인의 자격을 확인할 수 있는 핵심 항목을 3~5개 추출하세요.
    2. **[중요] 나이 조건(최소~최대 연령)은 별개로 나누지 말고 "만 00세~00세"와 같이 하나의 항목으로 통합하여 작성하세요.**
    3. 상세페이지용 'text'는 원문의 핵심 요건을 변형하지 말고 그대로(예: 대전광역시 거주자) 추출하세요.
    4. 시뮬레이션용 'question'은 반드시 사용자에게 묻는 질문 형태(예: 현재 대전광역시에 거주하고 계신가요?)로 만드세요.
    5. 일반 요건은 "condition", 신청 제외 대상은 "exclusion" 타입으로 분류하세요.
    6. 결과는 반드시 아래 JSON 형식을 엄격히 지켜 답변하세요. (다른 설명은 일절 배제)

{{
  "status": "success",
  "questions": [
    {{
      "type": "condition", 
      "text": "만 18세~39세 청년",
      "question": "현재 만 18세에서 39세 사이의 청년이신가요?"
    }},
    {{
      "type": "exclusion", 
      "text": "공무원 제외",
      "question": "현재 공무원으로 재직 중이신가요?"
    }}
  ]
}}
"""

    try:
        response = GEMINI_MODEL.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        result = json.loads(response.text.strip())
        return JsonResponse(result)

    except Exception as e:
        print(f"🔥 자격 요건 분석 에러: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


# 공통 데이터 및 검색 함수들 
@login_check
def index(request):
    print(f"로그인 여부: {request.is_authenticated}, 로그인 email: {request.email}")

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

        user_name = request.user_name if request.is_authenticated else "게스트"

        return render(request, "index.html", {
            "recommended": get_processed_data(collection.find({}).limit(4)), 
            "popular": get_processed_data(collection.find({}).sort("view_count", -1).limit(4)), 
            "deadline": get_processed_data(collection.find({"apply_period_end": {"$ne": "99991231"}}).sort("apply_period_end", 1).limit(4)),
            "is_login": request.is_authenticated,
            "user_name": user_name,
        })
    except Exception as e: return render(request, "index.html", {"error": str(e)})

def simulate(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    policy = db['policies'].find_one({"policy_id": policy_id})
    
    user_info = {
        "age": 28,         
        "region": "대전",    
        "is_student": True  
    }
    
    return render(request, "simulate.html", {
        "policy": policy,
        "policy_id": policy_id,
        "user_info": json.dumps(user_info) 
    })

def policy_detail(request):
    policy_id = request.GET.get('id')
    db = getMongoDbClient()
    policy = db['policies'].find_one({"policy_id": policy_id})
    if not policy: return render(request, "index.html")

    apply_period_label = _build_apply_period_label(policy)
    eligibility_age_label = _build_eligibility_age_label(policy)
    apply_link = _pick_apply_link(policy)
    official_homepage_link = _pick_official_homepage_link(policy)

    return render(request, "policy-detail.html", {
        "policy": policy, 
        "submit_docs": policy.get('submit_documents', []), 
        "apply_period_label": apply_period_label,
        "eligibility_age_label": eligibility_age_label,
        "apply_period": apply_period_label,  # 기존 템플릿/호출부 호환성 유지
        "apply_link": apply_link,
        "official_homepage_link": official_homepage_link,
        "docs_info": policy.get('required_docs_text', ''), 
        "link": official_homepage_link,  # 기존 템플릿 변수명 호환
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
        print(f"❌ 오류:\n{traceback.format_exc()}")
        return render(request, "index.html", {"error": str(e)})

def calendar_view(request):
    try:
        db = getMongoDbClient()
        collection = db['policies']
        
        policies_cursor = collection.find({
            "dates.apply_period_type": {"$ne": "상시"},
            "dates.apply_period": {"$regex": "~"}
        })
        
        calendar_events = []
        seen_ids = set()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        current_month = today.month
        current_year = today.year

        for p in policies_cursor:
            pid = str(p.get('policy_id'))
            if pid in seen_ids: continue

            apply_period = str(p.get('dates', {}).get('apply_period', ''))
            if "상시" in apply_period: continue

            import re
            match = re.search(r'~\s*(\d{8})(?!.*\d{8})', apply_period)
            
            if match:
                end_date = match.group(1)
                try:
                    formatted_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
                    end_dt = datetime.strptime(end_date, "%Y%m%d")
                    delta = (end_dt - today).days
            
                    if delta > 0: dday_label = f"D-{delta}"
                    elif delta == 0: dday_label = "D-Day"
                    else: dday_label = "마감됨"

                    calendar_events.append({
                        "id": pid,
                        "name": p.get('policy_name'),
                        "date": formatted_date,
                        "cat": p.get('category', '일반'),
                        "dday": dday_label,
                        "is_current_month": (end_dt.year == current_year and end_dt.month == current_month)
                    })
                    seen_ids.add(pid)
                except: continue
        this_month_count = len([e for e in calendar_events if e.get('is_current_month')])
        events_json = json.dumps(calendar_events, ensure_ascii=False)
        
        return render(request, "calendar.html", {
            "events_json": events_json,
            "total_count": this_month_count 
        })
    except Exception as e:
        print(f"Calendar Error: {e}") 
        return render(request, "calendar.html", {"events_json": "[]", "total_count": 0})

@csrf_exempt
def getPolicyData(request):
    try:
        p_type = "청년" if request.GET.get('type') == '1' else "취업"
        data = json.loads(json_util.dumps(list(getMongoDbClient()['test'].find({"type": p_type}))))
        return JsonResponse({"status": "success", "data": data}, json_dumps_params={'ensure_ascii': False})
    except Exception as e: 
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    
