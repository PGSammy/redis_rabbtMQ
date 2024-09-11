import redis
import subprocess
import time
import json

# Redis 설정
r = redis.Redis(host='localhost', port=6379, db=0)

def get_gpu_info():
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

def update_gpu_status():
    while True:
        gpu_info = get_gpu_info()
        available_gpus = [gpu['index'] for gpu in gpu_info if gpu['memory_used'] < gpu['memory_total'] * 0.1]
        r.set('available_gpus', json.dumps(available_gpus))
        print(f"Available GPUs: {available_gpus}")
        time.sleep(10)

if __name__ == "__main__":
    update_gpu_status()