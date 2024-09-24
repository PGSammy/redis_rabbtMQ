import os
import logging
from typing import Dict
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# .env load
load_dotenv()

RABBITMQ_HOST: str = os.getenv('RABBITMQ_HOST', '127.0.0.1')
RABBITMQ_PORT: int = int(os.getenv('RABBITMQ_PORT', 5672))
RABBITMQ_USER: str = os.getenv('RABBITMQ_USER', 'guest')
RABBITMQ_PASSWORD: str = os.getenv('RABBITMQ_PASSWORD', 'guest')

REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT: int = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD: str = os.getenv('REDIS_PASSWORD', '')

# 사용자 이름 설정
USER_NAME: str = os.getenv('USER_NAME', 'default_user')

# 사용자별 고유 큐 생성
RABBITMQ_QUEUE: str = f'gpu_tasks_{USER_NAME}'
AUGMENTATION_QUEUE:str = 'augmentation_queue'

# 설정 그룹화
RABBITMQ_CONFIG: Dict[str, str] = {
    'HOST': RABBITMQ_HOST,
    'QUEUE': RABBITMQ_QUEUE,
    'USER': RABBITMQ_USER,
    'PASSWORD': RABBITMQ_PASSWORD,
    'PORT': RABBITMQ_PORT
}

REDIS_CONFIG: Dict[str, any] = {
    'HOST': REDIS_HOST,
    'PORT': REDIS_PORT,
    'DB': REDIS_DB,
    'PASSWORD': REDIS_PASSWORD
}

assert REDIS_PORT > 0, "REDIS_PORT must be a positive integer"
assert REDIS_DB >= 0, "REDIS_DB must be a non-negative integer"

# 로깅 설정
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 로거 생성
logger = logging.getLogger(__name__)

# 설정 로드 완료 로그
logger.info("Configuration loaded successfully")