import redis
import subprocess
import time
import json
import logging
from typing import List, Dict

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Redis 설정
r = redis.Redis(host='localhost', port=6379, db=0)

# 설정 파일 임계값 있으면 확인
def read_config(config_path: str = "settings.json") -> Dict:
    try:
        with open(config_path, 'r') as file:
            config = json.load(file)
        return config
    except FileNotFoundError:
        logger.warning(f"Configuration file {config_path} not found. Using default settings")
        return {"THRESHHOLD_MEMORY_USAGE": 0.1, "UPDATE_INTERVAL": 10}
    
config = read_config()
THRESHOLD_MEMORY_USAGE = config.get("THRESHOLD_MEMORY_USAGE", 0.1)
UPDATE_INTERVAL = config.get("UPDATE_INTERVAL", 10)

def get_gpu_info():
    try:
        # nvidia-smi 명령어 실행
        result = subprocess.run(['nvidia-smi', '--query-gpu=index, memory.used, memory.total, utilization.gpu',
                                '--format=csv, noheader, nounits'], stdout=subprocess.PIPE, text=True)
        gpus = result.stdout.strip().split('\n')
        gpu_info = []
        for gpu in gpus:
            index, memory_used, memory_total, gpu_util = map(int, gpu.split(','))
            gpu_info.append({
                'index': index,
                'memory_used': memory_used,
                'memory_total': memory_total,
                'gpu_util': gpu_util
            })
        return gpu_info
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to execute nvidia-smi command: {e}")
        return []

def update_gpu_status() -> None:
    while True:
        try:
            gpu_info = get_gpu_info()
            if not gpu_info:
                logger.warning("No GPU information available. Retrying...")
                time.sleep(UPDATE_INTERVAL)
                continue
            available_gpus = [gpu['index'] for gpu in gpu_info if gpu['memory_used'] < gpu['memory_total'] * 0.1]
            r.set('available_gpus', json.dumps(available_gpus))
            logger.info(f"Available GPUs: {available_gpus}")
            time.sleep(10)
        except redis.RedisError as e:
            logger.error(f"Failed to update Redis": {e})
        except Exception as e:
            logger.error(f"Unexpected error occured: {e}")

if __name__ == "__main__":
    logger.info(f"Starting GPU monitoring with memory usage threshold:{THRESHOLD_MEMORY_USAGE}")
    update_gpu_status()