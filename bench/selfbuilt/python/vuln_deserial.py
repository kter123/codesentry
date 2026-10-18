# EXPECT: vulnerable | CWE-502 pickle 反序列化不可信数据
import pickle

def load(data: bytes):
    return pickle.loads(data)
