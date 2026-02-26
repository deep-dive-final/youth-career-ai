"""
json 관련 util
"""
from django.http import JsonResponse
import json

def json_response(data: dict, status: int = 200) -> JsonResponse:
    return_json = {"status": "success", "data": data}
    return JsonResponse(return_json, json_dumps_params={'ensure_ascii': False}, safe=False)


def error_response(message: str, status: int = 400) -> JsonResponse:
    return json_response({"status": "error", "message": message}, status=status)


def parse_json_body(request) -> tuple[dict | None, JsonResponse | None]:
    """
    요청 바디를 JSON으로 파싱.
    성공 시 (data, None), 실패 시 (None, error_response) 반환.
    """
    try:
        data = json.loads(request.body or '{}')
        return data, None
    except json.JSONDecodeError:
        return None, error_response('유효하지 않은 JSON 형식입니다.')