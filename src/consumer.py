import pika
import json
import redis
import subprocess
import os
import time
from config import RABBITMQ_HOST, RABBITMQ_QUEUE, REDIS_HOST, REDIS_PORT, REDIS_DB

connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
channel = connection.channel()
channel.queue_declare(queue=RABBITMQ_QUEUE)

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

def get_available_gpu():
    while True:
        available_gpus = json.loads(r.get('available_gpus') or '[]')
        if available_gpus:
            gpu_id = available_gpus.pop(0)
            r.set('available_gpus', json.dumps(available_gpus))
            return gpu_id
        time.sleep(5)  # 5초 대기 후 다시 확인

def run_job(job):
    gpu_id = get_available_gpu()
    os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu_id)

    command = [
        'python', job['script_path'],
        '--model', job['model'],
        '--dataset', job['dataset'],
        '--batch_size', str(job['batch_size']),
        '--epochs', str(job['epochs'])
    ] + job['additional_args']

    try:
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        return parse_output(result.stdout, job)
    except subprocess.CalledProcessError as e:
        print(f"Error during job execution: {e.stderr}")
        return None
    finally:
        # GPU 사용 가능 목록 업데이트
        available_gpus = json.loads(r.get('available_gpus') or '[]')
        available_gpus.append(gpu_id)
        r.set('available_gpus', json.dumps(available_gpus))
    
def parse_output(output, job):
    #CSV 파일 경로와 accuracy 파싱
    lines = output.strip().split('\n')
    csv_path = lines[-2].strip() # [ ] Check the output line
    accuracy = float(lines[-1].split(':')[-1].strip()) # [ ] Check the accuracy line

    return {
        'csv_path': csv_path,
        'accuracy': accuracy,
        'model': job['model'],
        'dataset': job['dataset'],
        'batch_size': job['batch_size'],
        'epochs': job['epochs']
    }

def callback(ch, method, properties, body):
    job = json.loads(body)
    print(f"Received job: {job}")

    result = run_job(job)

    if result:
        # 결과를 Redis에 저장
        job_key = f"job_result:{job['user']}:{job['model']}:{job['dataset']}"
        for epoch, epoch_result in enumerate(result['training_history'], start=1):
            r.hset(job_key, f"epoch_{epoch}_loss", epoch_result['train_loss'])
            r.hset(job_key, f"epoch_{epoch}_val_loss", epoch_result['val_loss'])
        r.hset(job_key, "final_accuracy", result['accuracy'])
        print(f"Job completed and results stored for user {job['user']}")
    else:
        print(f"Job failed for user {job['user']}")

    channel.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=callback)

if __name__ == "__main__":
    print('Waiting for jobs. To exit press CTRL+C')
    channel.start_consuming()

# python producer.py --script_path /path/to/train.py 
# --model resnet50 --dataset imagenet --batch_size 32 --epochs 10 --additional_args --learning_rate 0.001 --optimizer adam
