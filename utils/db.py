import pymongo # pip install pymongo
from django.conf import settings

class MongoSingleton:
    __instance = None

    def __new__(cls):
        if cls.__instance is None:
            # 설정 파일(settings.py)에서 URI 가져오기
            uri = settings.MONGODB_URI
            client = pymongo.MongoClient(uri)
            cls.__instance = client
        return cls.__instance

# youth_career_ai_db 데이터베이스에 접근하는 함수
def getMongoDbClient():
    client = MongoSingleton()
    return client['youth_career_ai_db']

# db_name 데이터베이스에 접근하는 함수
def getMongoDbClientByName(db_name):
    client = MongoSingleton()
    return client[db_name]
