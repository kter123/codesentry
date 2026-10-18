# EXPECT: clean | json 解析替代 pickle
import json

def load(data: bytes):
    return json.loads(data)
