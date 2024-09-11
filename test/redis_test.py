import redis

r = redis.Redis(host='localhost', port=6379, db=0)

# Key-Value Pair
r.set('test_key', 'Hello, Redis!')

# Getting Value
value = r.get('test_key')
print(value.decode('utf-8')) # Printing Hello Redis!