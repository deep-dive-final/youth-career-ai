from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from site_admin.data import fetch_policy_data, get_semantic_search_gemini, get_semantic_search_e5
import json
from bson import json_util
import boto3
from django.conf import settings

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

# 파일 업로드
@csrf_exempt
def upload_file(request):
    if request.method != 'POST' or 'document_file' not in request.FILES:
        return JsonResponse({"status": "error", "message": "Invalid request (file doesn't exist)"}, status=400)
    
    try:
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        region_name = settings.AWS_S3_REGION_NAME

        s3 = boto3.client(
            service_name="s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=region_name,
        )
        
        document_file = request.FILES.get("document_file")
        
        s3.upload_fileobj(
            document_file,
            bucket_name,
            f"documents/{document_file.name}",
            ExtraArgs={"ContentType": document_file.content_type},
        )

        uploaded_url = f"https://{bucket_name}.s3.{region_name}.amazonaws.com/documents/{document_file.name}"
        
        print(f"Uploaded file URL: {uploaded_url}")
        return JsonResponse({"status": "success", "data": {"uploaded_url": uploaded_url}}, json_dumps_params={'ensure_ascii': False}, safe=False)
    except Exception as e:
        print(f"[upload_file] exception {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)