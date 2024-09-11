import os

RABBITMQ_HOST = 'localhost'
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

# 사용자 이름 설정
USER_NAME = os.environ.get('USER_NAME', 'default_user')

# 사용자별 고유 큐 생성
RABBITMQ_QUEUE = f'gpu_tasks_{USER_NAME}'