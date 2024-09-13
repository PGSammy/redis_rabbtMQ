import os
import logging
from typing import Dict

RABBITMQ_HOST: str = os.environ.get('RABBITMQ_HOST', '127.0.0.1')
REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
REDIS_PORT: int = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))

# 사용자 이름 설정
USER_NAME: str = os.environ.get('USER_NAME', 'default_user')

# 사용자별 고유 큐 생성
RABBITMQ_QUEUE: str = f'gpu_tasks_{USER_NAME}'

AUGMENTATION_QUEUE:str = 'augmentation_queue'

# 설정 그룹화
RABBITMQ_CONFIG: Dict[str, str] = {
    'HOST': RABBITMQ_HOST,
    'QUEUE': RABBITMQ_QUEUE
}

REDIS_CONFIG: Dict[str, any] = {
    'HOST': REDIS_HOST,
    'PORT': REDIS_PORT,
    'DB': REDIS_DB
}

assert REDIS_PORT > 0, "REDIS_PORT must be a positive integer"
assert REDIS_DB >= 0, "REDIS_DB must be a non-negative integer"

# 로깅 설정
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 로거 생성
logger = logging.getLogger(__name__)

# 설정 로드 완료 로그
logger.info("Configuration loaded successfully")