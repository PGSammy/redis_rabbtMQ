import redis
import json
from config import REDIS_HOST, REDIS_PORT, REDIS_DB

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

def get_result(model):
    result = r.get(f"result:{model}")
    if result:
        return json.loads(result)
    else:
        return None

def get_result_name(name):
    result = r.get(f"result:{name}")
    if result:
        return json.loads(result)
    else:
        return None

if __name__ == "__main__":
    model = 'eff4'
    result = get_result(model)
    if result:
        print(f"Result for {model}: {result}")
    else:
        print(f"No result found for {model}")