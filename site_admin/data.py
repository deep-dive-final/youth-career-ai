import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from requests.exceptions import Timeout, ConnectionError
from django.conf import settings
from utils.db import getMongoDbClient
from datetime import datetime
from bson import ObjectId
from sentence_transformers import SentenceTransformer
# from openai import OpenAI
import google.generativeai as genai

# API 정보
API_INFO = {
  "youth_center":{
    "url": "https://www.youthcenter.go.kr/go/ythip/getPlcy",
    "param": {
        "apiKeyNm": settings.YOUTH_API_KEY,
        "pageNum": 1,
        "pageSize": 5,
        "rtnType": "json",
        "lclsfNm": "일자리,교육"  # 정책대분류: 일자리,주거,교육,복지문화,참여권리
    }
  }
}

# API에서 데이터 가져오는 함수
@retry(
    # 최대 5번까지 시도
    stop=stop_after_attempt(5),
    # 대기 시간을 2초부터 시작해 2배씩 증가 (2s, 4s, 8s...) 최대 10초까지
    wait=wait_exponential(multiplier=1, min=2, max=10),
    # 특정 예외(RequestException)가 발생했을 때만 재시도
    retry=retry_if_exception_type((Timeout, ConnectionError))
)
def fetch_api_data(url, param):

    print(f"[fetch_api_data start]\nurl: {url},\nparam: {param}")

    response = requests.get(url, params=param, timeout=3)
    response.raise_for_status()

    return response.json()

# 전역 모델 캐시 변수 (이렇게 하면 시간이 적게 걸리려나..)
_model = None
def get_model(model_name):
    global _model
    if _model is None:
        print("모델을 처음 로드합니다")
        _model = SentenceTransformer(model_name)
    return _model

# E5 모델 임베딩 생성 함수
def get_Embedding_e5 (original_text_list, task_type="passage"):
    print("[get_Embedding_e5] start ")

    # E5 모델의 특성에 맞게 접두사 추가: 'passage' (저장용) 또는 'query' (검색용)
    prefixed_texts = [f"{task_type}: {text}" for text in original_text_list]
    
    # 모델 로드
    model_name = 'intfloat/multilingual-e5-large'
    model = get_model(model_name)

    # 임베딩 생성 (리스트 형태의 numpy 배열 반환)
    embedding_e5 = model.encode(prefixed_texts, normalize_embeddings=True, batch_size=64)

    return embedding_e5

# OpenAI 임베딩 생성 함수
# def get_Embedding_openai(original_text_list):
#     # OpenAI API를 통해 한 번에 임베딩 받기 (API 호출 최적화)
#     # 한 번의 호출로 리스트 전체의 벡터를 가져올 수 있다
#     client = OpenAI(api_key=settings.OPENAI_API_KEY)

#     embed_response = client.embeddings.create(
#         input=original_text_list,
#         model="text-embedding-3-small"
#     )
#     embedding_openai = [d.embedding for d in embed_response.data]
#     return embedding_openai

# Gemini 임베딩 생성 함수
def get_Embedding_gemini(original_text_list, task_type="document"):
    print("[get_Embedding_gemini] start ")

    genai.configure(api_key=settings.GEMINI_API_KEY)

    model_name = "models/gemini-embedding-001"
    result = genai.embed_content(
        model=model_name,
        content=original_text_list,
        output_dimensionality=3072,
        task_type=task_type,       # 저장용은 document, 검색용은 query 사용
        title=("Policy Data" if task_type == "document" else None)         # 선택 사항: 문서의 제목을 명시하면 품질이 좋아짐
    )
    return result['embedding']

# 임베딩 생성 함수
def get_embeddings(api_list):
    print("[get_embeddings] start ")

    original_text_list = [f"{item.get('plcyNm', '')} \n\
{item.get('plcyExplnCn', '')} \n\
{item.get('plcySprtCn', '')} \n\
{item.get('ptcpPrpTrgtCn', '')} \n\
{item.get('addAplyQlfcCndCn', '')} ".strip() for item in api_list]
    
    embedding_e5 = get_Embedding_e5(original_text_list, "passage")
    embedding_gemini = get_Embedding_gemini(original_text_list, "document")

    return original_text_list, embedding_e5, embedding_gemini

# API 필드와 DB 필드 매핑 처리
def set_nested_value(dic, keys, value):
    """중첩된 키 경로를 따라 값을 할당하는 보조 함수"""
    for key in keys[:-1]:
        dic = dic.setdefault(key, {})
    dic[keys[-1]] = value

# API 데이터 리스트를 몽고DB 저장 형식으로 변환하는 함수
def transform_api_data_for_db_insert(api_list):
    print("[transform_api_data_for_db_insert] start ")

    # API 필드명과 DB 필드명 매핑 가져오기
    field_map = get_api_db_field_map()

    # 임베딩 값 가져오기
    original_text_list, embedding_e5, embedding_gemini = get_embeddings(api_list)

    current_time = datetime.now()
    data_docs = []
    vector_docs = []
    
    for i, item in enumerate(api_list):
        # 1. 파이썬에서 미리 ObjectId 생성
        doc_id = ObjectId()

        # 2. 고정값 및 기본 구조 설정
        doc = {
            "_id": doc_id,
            "source": "YOUTH_CENTER",
            "inquiry_contact": "",
            "inserted_at": current_time,
            "updated_at": current_time
        }
        
        # 3. 매핑 규칙에 따라 데이터 변환
        for api_key, mongo_path in field_map.items():
            if api_key in item:
                # 점(.)을 기준으로 경로 분리 (예: 'dates.apply_period' -> ['dates', 'apply_period'])
                keys = mongo_path.split('.')
                set_nested_value(doc, keys, item[api_key])
        
        data_docs.append(doc)
    
        vector_doc = {
                "policy_id": doc_id,  # 위와 동일한 ID 사용
                "chunk_id": 1,
                "content_chunk": original_text_list[i],
                "embedding_e5": embedding_e5[i].tolist(),
                "embedding_gemini": embedding_gemini[i],
                "metadata":{
                    "source":doc.get('source', ''),
                    "policy_name":item.get('plcyNm', ''),
                    "content":item.get('plcyExplnCn', ''),
                    "category":item.get('lclsfNm', ''),
                    "sub_category":item.get('mclsfNm', ''),
                    "support_content":item.get('plcySprtCn', ''),
                    "supervising_agency":item.get('sprvsnInstCdNm', ''),
                },
                "inserted_at": current_time
            }
        vector_docs.append(vector_doc)

    return data_docs, vector_docs

# 몽고DB에 데이터 저장하는 함수
def save_data_to_mongodb(data_docs, vector_docs):
    print("[save_data_to_mongodb] start ")

    db = getMongoDbClient()
    data_collection = db["policies"]
    vector_collection = db["policy_vectors"]

    data_result = data_collection.insert_many(data_docs)
    vector_result = vector_collection.insert_many(vector_docs)

    print(f"[save_data_to_mongodb] result: {data_result.acknowledged}, {vector_result.acknowledged}")

    return data_result.acknowledged

# 정책 데이터 가져와서 DB에 저장하는 함수
def fetch_policy_data(page_num, page_size):
    print(f"[fetch_policy_data start] page_num:{page_num}, page_size:{page_size}")
    
    try:
        # 페이지 번호와 사이즈를 API 파라미터에 반영
        API_INFO["youth_center"]["param"]["pageNum"] = int(page_num) if page_num else 1
        API_INFO["youth_center"]["param"]["pageSize"] = int(page_size) if page_size else 5

        # 정책 데이터를 api 에서 가져오기
        data = fetch_api_data(API_INFO["youth_center"]["url"], API_INFO["youth_center"]["param"])

        if data.get("resultCode") != 200:
            raise Exception(f"API Error: {data.get('resultMessage')}")
        
        # 데이터를 몽고DB 형식에 맞게 변환
        data_docs, vector_docs = transform_api_data_for_db_insert(data["result"]["youthPolicyList"])

        # 몽고 DB에 저장
        insert_result = save_data_to_mongodb(data_docs, vector_docs)

        print(f"[fetch_policy_data] success : {insert_result}")

        return 1
    except Exception as e:
        print(f"[fetch_policy_data] exception : {e}")
        return -1

# API 필드명과 DB 필드명 매핑 반환 함수
def get_api_db_field_map() :
    # 매핑 정의 (API 키: 몽고DB 경로)
    field_map = {
        "plcyNo" : "policy_id",
        "plcyNm" : "policy_name",
        "plcyKywdNm" : "keywords",
        "plcyExplnCn" : "content",
        "lclsfNm" : "category",
        "mclsfNm" : "sub_category",
        "plcySprtCn" : "support_content",
        "sprvsnInstCdNm" : "supervising_agency",
        "operInstCdNm" : "operating_agency",
        "aplyYmd" : "dates.apply_period",
        "bizPrdBgngYmd" : "dates.biz_period_start",
        "bizPrdEndYmd" : "dates.biz_period_end",
        "plcyAplyMthdCn" : "how_to_apply",
        "srngMthdCn" : "evaluation_method",
        "aplyUrlAddr" : "application_url",
        "sbmsnDcmntCn" : "required_docs_text",
        "etcMttrCn" : "etc_content",
        "refUrlAddr1" : "reference_url1",
        "refUrlAddr2" : "reference_url2",
        "sprtSclCnt" : "selection_count",
        "sprtTrgtMinAge" : "eligibility.age_min",
        "sprtTrgtMaxAge" : "eligibility.age_max",
        "addAplyQlfcCndCn" : "eligibility.text",
        "earnMinAmt" : "earn.min_amt",
        "earnMaxAmt" : "earn.max_amt",
        "earnEtcCn" : "earn.etc_content",
        "ptcpPrpTrgtCn" : "participate_target",
        "inqCnt" : "view_count",
        "frstRegDt" : "registered_at",
        "lastMdfcnDt" : "modified_at"
    }

    return field_map

# Gemini 임베딩 기반 검색 함수
def get_semantic_search_gemini (search_text):

    print("[get_semantic_search_gemini] start", search_text)

    # 1. 검색어에 대한 임베딩 생성
    query_vector = get_Embedding_gemini(search_text, "query")

    # 2. $vectorSearch 파이프라인 정의
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index_v2",     # 설정한 인덱스 이름
                "path": "embedding_gemini_v2",  # 벡터 필드
                "queryVector": query_vector,    # 검색용 벡터
                "numCandidates": 20,            # 후보군 수
                "limit": 10                     # 최종 반환 결과 수
            }
        },
        {
            # 유사도 점수와 함께 필요한 필드만 가져오기
            "$project": {
                "metadata": 1,
                "content_chunk_v2":1,
                "score": { "$meta": "vectorSearchScore" }
            }
        }
    ]

    # 3. 검색 수행
    db = getMongoDbClient()
    collection = db['policy_vectors']
    results = collection.aggregate(pipeline)

    return results

# E5 임베딩 기반 검색 함수
def get_semantic_search_e5 (search_text):

    print("[get_semantic_search_e5] start", search_text)

    search_test_list = []
    search_test_list.append(search_text)

    # 1. 검색어에 대한 임베딩 생성
    query_vector = get_Embedding_e5(search_test_list, "query")[0].tolist()

    # 2. $vectorSearch 파이프라인 정의
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",    # 설정한 인덱스 이름
                "path": "embedding_e5",     # 벡터 필드
                "queryVector": query_vector,    # 검색용 벡터
                "numCandidates": 20,            # 후보군 수
                "limit": 10                     # 최종 반환 결과 수
            }
        },
        {
            # 유사도 점수와 함께 필요한 필드만 가져오기
            "$project": {
                "metadata": 1,
                "content_chunk_v2":1,
                "score": { "$meta": "vectorSearchScore" }
            }
        }
    ]

    # 3. 검색 수행
    db = getMongoDbClient()
    collection = db['policy_vectors']
    results = collection.aggregate(pipeline)

    return results