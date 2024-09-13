import pika
import json
import zlib
import time
from config import RABBITMQ_HOST, RABBITMQ_QUEUE

connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
channel = connection.channel()

channel.queue_declare(queue=RABBITMQ_QUEUE)

test_message = {
    "user": "test_user",
    "script_path": "C:/Users/User/Desktop/AIBoostcamp/redis_rabbtMQ/src/test_producer.py",
    "config_path": "C:/Users/User/Desktop/AIBoostcamp/redis_rabbtMQ/src/default.yaml",
    "model_name": "test_model",
    "learning_rate": "0.001"
}

compressed_message = zlib.compress(json.dumps(test_message).encode())
channel.basic_publish(exchange='', routing_key=RABBITMQ_QUEUE, body=compressed_message)

print("Test message sent")
connection.close()

# 대신 다음 코드를 추가
# try:
#     # 연결 유지를 위해 무한 루프
#     while True:
#         time.sleep(1)
# except KeyboardInterrupt:
#     print("Closing connection")
#     connection.close()