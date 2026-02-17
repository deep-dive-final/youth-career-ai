from django.shortcuts import render
from utils.db import getMongoDbClient

def policy(request):
    policy_id = request.GET.get('id')
    
    db = getMongoDbClient()
    
    policy_data = db.policies.find_one({"policy_id": policy_id})
    
    return render(request, "policy-detail.html", {"policy": policy_data})