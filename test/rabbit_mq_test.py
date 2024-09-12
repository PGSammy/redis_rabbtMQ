import pika

try:
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()
    print("RabbitMQ에 성공적으로 연결되었습니다.")
    connection.close()
except pika.exceptions.AMQPConnectionError as e:
    print(f"RabbitMQ 연결 실패: {e}")