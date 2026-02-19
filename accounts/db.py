from bson import ObjectId
from utils.db import getMongoDbClient
from datetime import datetime

# 사용자 collection 가져온다
def get_user_collection():
    db = getMongoDbClient()
    users_collection = db["users"]
    
    return users_collection

# DB 에서 사용자 조회
def get_user_by_email(email, provider):
    users_collection = get_user_collection()

    user = users_collection.find_one({ "email" : email, "provider" : provider })
    return user

# DB 에서 사용자 조회
def get_user_by_id(id):
    users_collection = get_user_collection()

    user = users_collection.find_one({ "_id" : ObjectId(id) })
    return user

# 사용자 마지막 로그인 시간 업데이트
def update_user_last_login(objectId):
    users_collection = get_user_collection()

    last_login_at = { "last_login_at" : datetime.now() }
    update_result = users_collection.update_one({ "_id" : objectId}, 
                                                { "$set": last_login_at })

    return str(objectId) if update_result.modified_count > 0 else None

# 신규 사용자 등록
def insert_user (email, provider):
    db = getMongoDbClient()
    users_collection = db["users"]
    
    new_user = {
        "email" : email,
        "provider" : provider,
        "created_at" : datetime.now(),
        "last_login_at" : datetime.now()
    }

    insert_result = users_collection.insert_one(new_user)
    return str(insert_result.inserted_id)
