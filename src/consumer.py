import pika
import json
import pika.exceptions
import redis
import subprocess
import os
import time
import re
import logging
import zlib
import torch
import signal
from config import RABBITMQ_HOST, RABBITMQ_QUEUE, REDIS_HOST, REDIS_PORT, REDIS_DB


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 콘솔 핸들러 추가
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

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

def initialize_gpu_list(r):
    available_gpus = []
    for i in range(torch.cuda.device_count()):
        available_gpus.append(i)
    r.set('available_gpus', json.dumps(available_gpus))
    print(f"Initialized available GPUs: {available_gpus}")


# gpu 가능한거 백그라운드로 찾기
def get_available_gpu(r):
    max_attempts = 10
    attempts = 0
    while attempts < max_attempts:
        available_gpus = json.loads(r.get('available_gpus') or '[]')
        if available_gpus:
            gpu_id = available_gpus.pop(0)
            r.set('available_gpus', json.dumps(available_gpus))
            return gpu_id
        else:
            print("No available GPU, waiting...")
            time.sleep(0.5)
            attempts += 1
    raise Exception("No GPU available after maximum attempts")

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

    process = None

    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True)

        job_key = f"job_result:{job['user']}:{job['model_name']}"

        def signal_handler(signum, frame):
            if process:
                process.terminate()
            raise KeyboardInterrupt
        
        signal.signal(signal.SIGINT, signal_handler)

        while process.poll() is None:
            line = process.stdout.readline()
            if line:
                process_output(line, job_key, r)

        if process.returncode == 0:
            logger.info(f"\nJob completed successfully for user{job['user']}")
            return True
        else:
            logger.error(f"\nJob failed for user {job['user']}")
            return False
    except Exception as e:
        logger.error(f"\nError during job execution: {str(e)}")
        return False
    except KeyboardInterrupt as e:
        logger.error(f"\n Error KeyboardInterrupt")
        return False
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait()
        release_gpu(r, gpu_id)
        print(f"GPU {gpu_id} Returned\n")

def process_output(line, job_key, r):
    # 실시간 출력
    print(line.strip())
    logger.info(line.strip())

    # 에폭 결과 파싱
    patterns = {
        'epoch_pattern': r"(Additional )?Epoch (\d+)/(\d+)",
        'loss_pattern': r"Train Loss: ([\d.]+), Train Metric: ([\d.]+)",
        'val_pattern': r"Val Loss: ([\d.]+), Val Metric: ([\d.]+)",
        'class_loss_pattern': r"Train Class Losses: (.+)",
        'class_metric_pattern': r"Train Class metric: (.+)",
        'val_class_loss_pattern': r"Val Class Losses: (.+)",
        'val_class_metric_pattern': r"Val Class metric: (.+)"
    }

    matches = {k: re.search(v, line) for k, v in patterns.items()}

    pipe = r.pipeline()

    if matches['epoch']:
        is_additional = matches['epoch'].group(1) is not None
        current_epoch, total_epochs = matches['epoch'].group(2), matches['epoch'].group(3)
        pipe.hset(job_key, "current_epoch", current_epoch)
        pipe.hset(job_key, "total_epochs", total_epochs)
        pipe.hset(job_key, "is_additional_training", "1" if is_additional else "0")
    
    if matches['loss']:
        train_loss, train_metric = matches['loss'].groups()
        current_epoch = r.hget(job_key, "current_epoch").decode()
        pipe.hset(job_key, f"epoch_{current_epoch}_train_loss", f"{float(train_loss):.4f}")
        pipe.hset(job_key, f"epoch_{current_epoch}_train_metric", f"{float(train_metric):.4f}")
    
    if matches['val']:
        val_loss, val_metric = matches['val'].groups()
        current_epoch = r.hget(job_key, "current_epoch").decode()
        pipe.hset(job_key, f"epoch_{current_epoch}_val_loss", f"{float(val_loss):.4f}")
        pipe.hset(job_key, f"epoch_{current_epoch}_val_metric", f"{float(val_metric):.4f}")

    for key in ['class_loss', 'class_metric', 'val_class_loss', 'val_class_metric']:
        if matches[key]:
            pipe.hset(job_key, f"epoch_{current_epoch}_{key}", matches[key].group(1))

    pipe.execute()

    if all(matches[k] for k in ['loss', 'val', 'class_loss', 'class_metric', 'val_class_loss', 'val_class_metric']):
        epoch_type = "Additional " if is_additional else ""
        log_message = f"\n{epoch_type}Epoch {current_epoch}/{total_epochs} 완료:"
        print(log_message)
        logger.info(log_message)
        
        log_message = f" Train Loss: {train_loss:.4f}, Train Metric: {train_metric:.4f}"
        print(log_message)
        logger.info(log_message)
        
        log_message = f" Val Loss: {val_loss:.4f}, Val Metric: {val_metric:.4f}"
        print(log_message)
        logger.info(log_message)
        
        log_message = f" Train Class Losses: {matches['class_loss'].group(1)}"
        print(log_message)
        logger.info(log_message)
        
        log_message = f" Train Class Metric: {matches['class_metric'].group(1)}"
        print(log_message)
        logger.info(log_message)
        
        log_message = f" Val Class Losses: {matches['val_class_loss'].group(1)}"
        print(log_message)
        logger.info(log_message)
        
        log_message = f" Val Class Metric: {matches['val_class_metric'].group(1)}"
        print(log_message)
        logger.info(log_message)

def process_message(message):
    try:
        decompressed_message = zlib.decompress(message)
        job = json.loads(decompressed_message.decode())
        logger.info(f"Processing job: {job}")
        result = run_job(job, r)
        if result:
            job_key = f"job_result:{job['user']}:{job['model_name']}"
            all_keys = r.hkeys(job_key)
            epoch_keys = [key for key in all_keys if key.startswith(b'epoch_')]
            last_epoch = max([int(key.split(b'_')[1]) for key in epoch_keys])
            final_metric = r.hget(job_key, f"epoch_{last_epoch}_val_metric")
            if final_metric:
                logger.info(f"Job completed for user {job['user']}. Final accuracy: {final_metric.decode('utf-8')}")
            else:
                logger.warning(f"Job completed for user {job['user']} but final accuracy not found")
        else:
            logger.error(f"Job failed for user {job['user']}")
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
    except KeyboardInterrupt as e:
        logger.error(f"KeyboardInterrupt. 종료.")

def process_batch(messages):
    for message in messages:
        process_message(message)

def callback(ch, method, properties, body):
    try:
        process_message(body)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
    finally:
        ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    print(f"Number of available GPUs: {torch.cuda.device_count()}")
    print(f"CUDA is available: {torch.cuda.is_available()}")
    try:
        connection, channel = connect_to_rabbitmq()
        initialize_gpu_list(r)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=callback)
        logger.info(' [*] Waiting for messages. To exit press CTRL+C')
        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Consumer 종료")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        if connection and not connection.is_closed:
            connection.close()

if __name__ == "__main__":
    main()