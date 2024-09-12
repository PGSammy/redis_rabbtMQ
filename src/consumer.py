import pika
import json
import pika.exceptions
import redis
import subprocess
import os
import time
import re
from config import RABBITMQ_HOST, RABBITMQ_QUEUE, REDIS_HOST, REDIS_PORT, REDIS_DB
import sys
import logging
import zlib

logger = logging.getLogger(__name__)

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

# rabbitmq의 queue와 연결
def connect_to_rabbitmq():
    retries = 0
    MAX_RETRIES = 5
    RETRY_DELAY = 5  # seconds
    while retries < MAX_RETRIES:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
            channel = connection.channel()
            channel.queue_declare(queue=RABBITMQ_QUEUE)
            logger.info("Successfully connected to RabbitMQ")
            return connection, channel
        except pika.exceptions.AMQPConnectionError as e:
            retries += 1
            logger.warning(f"Failed to connect to RabbitMQ (attempt {retries}/{MAX_RETRIES}): {e}")
            if retries < MAX_RETRIES:
                logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                logger.error("Max retries reached. Unable to connect to RabbitMQ.")
                raise

# gpu 가능한거 백그라운드로 찾기
def get_available_gpu(r):
    while True:
        available_gpus = json.loads(r.get('available_gpus') or '[]')
        if available_gpus:
            gpu_id = available_gpus.pop(0)
            r.set('available_gpus', json.dumps(available_gpus))
            return gpu_id
        else:
            print("No available GPU, waiting...")
            time.sleep(0.5)

def release_gpu(r: redis.Redis, gpu_id: int):
    available_gpus = json.loads(r.get('available_gpus') or '[]')
    available_gpus.append(gpu_id)
    r.set('available_gpus', json.dumps(available_gpus))
    print(f"GPU {gpu_id} released.")

def run_job(job, r):
    gpu_id = get_available_gpu(r)
    os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu_id)

    command = [
        'python', job['script_path'],
        'config_path', job['config_path'],
        '--model_name', job['model_name'],
        '--learning_rate', job['learning_rate']
    ]

    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True)

        job_key = f"job_result:{job['user']}:{job['model_name']}"

        for line in process.stdout:
            process_output(line, job_key, r)

        process.wait()

        if process.returncode == 0:
            logger.info(f"\nJob completed successfully for user{job['user']}")
            return True
        else:
            logger.error(f"\nJob failed for user {job['user']}")
            return False
    except Exception as e:
        logger.error(f"\nError during job execution: {str(e)}")
        return False
    finally:
        release_gpu(r, gpu_id)
        print(f"GPU {gpu_id} Returned\n")

def process_output(line, job_key, r):
    # 실시간 출력
    print(line.strip())

    # 에폭 결과 파싱
    epoch_pattern = r"(Additional )?Epoch (\d+)/(\d+)"
    loss_pattern = r"Train Loss: ([\d.]+), Train Metric: ([\d.]+)"
    val_pattern = r"Val Loss: ([\d.]+), Val Metric: ([\d.]+)"
    class_loss_pattern = r"Train Class Losses: (.+)"
    class_metric_pattern = r"Train Class metric: (.+)"
    val_class_loss_pattern = r"Val Class Losses: (.+)"
    val_class_metric_pattern = r"Val Class metric: (.+)"

    epoch_match = re.search(epoch_pattern, line)
    loss_match = re.search(loss_pattern, line)
    val_match = re.search(val_pattern, line)
    class_loss_match = re.search(class_loss_pattern, line)
    class_metric_match = re.search(class_metric_pattern, line)
    val_class_loss_match = re.search(val_class_loss_pattern, line)
    val_class_metric_match = re.search(val_class_metric_pattern, line)

    pipe = r.pipeline()

    if epoch_match:
        is_additional = epoch_match.group(1) is not None
        current_epoch, total_epochs = epoch_match.group(2), epoch_match.group(3)
        r.hset(job_key, "current_epoch", current_epoch)
        r.hset(job_key, "total_epochs", total_epochs)
        r.hset(job_key, "is_additional_training", "1" if is_additional else "0")
    
    if loss_match:
        train_loss, train_metric = loss_match.groups()
        current_epoch = r.hget(job_key, "current_epoch").decode()
        r.hset(job_key, f"epoch_{current_epoch}_train_loss", f"{float(train_loss):.4f}")
        r.hset(job_key, f"epoch_{current_epoch}_train_metric", f"{float(train_metric):.4f}")
    
    if val_match:
        val_loss, val_metric = val_match.groups()
        current_epoch = r.hget(job_key, "current_epoch").decode()
        r.hset(job_key, f"epoch_{current_epoch}_val_loss", f"{float(val_loss):.4f}")
        r.hset(job_key, f"epoch_{current_epoch}_val_metric", f"{float(val_metric):.4f}")

    if class_loss_match:
        r.hset(job_key, f"epoch_{current_epoch}_class_losses", class_loss_match.group(1))

    if class_metric_match:
        r.hset(job_key, f"epoch_{current_epoch}_class_metric", class_metric_match.group(1))

    if val_class_loss_match:
        r.hset(job_key, f"epoch_{current_epoch}_val_class_losses", val_class_loss_match.group(1))

    if val_class_metric_match:
        r.hset(job_key, f"epoch_{current_epoch}_val_class_metric", val_class_metric_match.group(1))

    pipe.execute()

    if loss_match and val_match:
        epoch_type = "Additional " if is_additional else ""
        print(f"\n{epoch_type}Epoch {current_epoch}/{total_epochs} 완료:")
        print(f"  Train Loss: {train_loss:.4f}, Train Metric: {train_metric:.4f}")
        print(f"  Val Loss: {val_loss:.4f}, Val Metric: {val_metric:.4f}")
        if class_loss_match and class_metric_match and val_class_loss_match and val_class_metric_match:
            print(f"  Train Class Losses: {class_loss_match.group(1)}")
            print(f"  Train Class Metric: {class_metric_match.group(1)}")
            print(f"  Val Class Losses: {val_class_loss_match.group(1)}")
            print(f"  Val Class Metric: {val_class_metric_match.group(1)}")
        print()

def callback(ch, method, properties, body):
    decompressed_message = zlib.decompress(body)
    job = json.loads(decompressed_message.decode())
    
    logger.info(f"Received job: {job}")

    result = run_job(job, r)

    if result:
        job_key = f"job_result:{job['user']}:{job['model_name']}"

        # last epoch
        all_keys = r.hkeys(job_key)
        epoch_keys = [key for key in all_keys if key.startswith(b'epoch_')]
        last_epoch = max([int(key.split(b'_')[1]) for key in epoch_keys])

        final_metric = r.hget(job_key, f"epoch_{last_epoch}_val_metric")
        if final_metric:
            logger.info(f"Job completed and results stored for user {job['user']}. Final accuracy: {final_metric.decode('utf-8')}")
        else:
            logger.warning(f"Job completed for user {job['user']} but final accuracy not found")
    else:
        logger.error(f"Job failed for user {job['user']}")

    ch.basic_ack(delivery_tag=method.delivery_tag)

def process_batch(messages):
    for message in messages:
        print(f"Processing message: {message}")

def main():
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
        channel = connection.channel()

        # Queue
        channel.queue_declare(queue='Executed')

        batch_size = 10
        batch = []

        def callback(ch, method, properties, body):
            nonlocal batch
            batch.append(body)
            if len(batch) >= batch_size:
                process_batch(batch)
                batch = []
                ch.basic_ack(delivery_tag=method.delivery_tag, multiple=True)

        channel.basic_qos(prefetch_count=batch_size)
        channel.basic_consume(queue='Executed', on_message_callback=callback, auto_ack=True)

        print(' [*] Waiting for messages. To exit press CTRL+C')
        channel.start_consuming()

    except pika.exceptions.AMQPConnectionError as e:
        logger.error(f"RabbitMQ 연결 실패: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("Consumer 종료")
        sys.exit(0)

if __name__ == "__main__":
    main()