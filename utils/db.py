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

# 사용 예시
def getMongoDbClient():
    client = MongoSingleton()
    return client['career']
