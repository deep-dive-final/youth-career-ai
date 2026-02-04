from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from site_admin.data import fetch_policy_data, get_semantic_search_gemini, get_semantic_search_e5
import json
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
def getSearchData(request):
    try:
        search_text = request.GET.get('search_text')
        search_type = request.GET.get('search_type')

        results = {}
        if search_type == 'gemini':
            results = get_semantic_search_gemini(search_text)
        elif search_type == 'e5':
            results = get_semantic_search_e5(search_text)

        json_data = json.loads(json_util.dumps(list(results)))

        return JsonResponse({"status": "success", "data": json_data}, json_dumps_params={'ensure_ascii': False}, safe=False)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    