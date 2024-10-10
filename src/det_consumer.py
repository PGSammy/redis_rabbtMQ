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
import sys
import yaml
import tempfile
import signal
import importlib
from pika.exceptions import AMQPConnectionError, AMQPChannelError
from config import RABBITMQ_CONFIG, REDIS_CONFIG, PROJECT_CONFIG

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 콘솔 핸들러 추가
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

r = redis.Redis(host=REDIS_CONFIG['HOST'], port=REDIS_CONFIG['PORT'], db=REDIS_CONFIG['DB'], password=REDIS_CONFIG['PASSWORD'])
 
# rabbitmq의 queue와 연결
def connect_to_rabbitmq():
    retries = 0
    MAX_RETRIES = 5
    RETRY_DELAY = 5  # seconds
    while retries < MAX_RETRIES:
        try:
            logger.info(f"Attempting to connect to RabbitMQ with host: {RABBITMQ_CONFIG['HOST']}, port: {RABBITMQ_CONFIG['PORT']}, user: {RABBITMQ_CONFIG['USER']}, pw: {RABBITMQ_CONFIG['PASSWORD']}")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                host=RABBITMQ_CONFIG['HOST'],
                port=RABBITMQ_CONFIG['PORT'],
                credentials=pika.PlainCredentials(RABBITMQ_CONFIG['USER'], RABBITMQ_CONFIG['PASSWORD']),
                heartbeat=600,
                blocked_connection_timeout=300
                )
            )
            channel = connection.channel()
            channel.queue_declare(queue=RABBITMQ_CONFIG['QUEUE'])
            logger.info("Successfully connected to RabbitMQ")
            return connection, channel
        except AMQPConnectionError as e:
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

def run_job(job, r, channel, gpu_id):
    env = os.environ.copy()
    env['PATH'] = f"{os.path.dirname(sys.executable)};{env['PATH']}"

    # config.py에서 MAIN_PROJECT_ROOT를 설정한대로 진행
    # 만약 설정하지 않은 경우는 script_path에 대해서 os.path.dirname(job['script_path']) 로 메인 루트 조정 가능
    main_script_dir = PROJECT_CONFIG['MAIN_PROJECT_ROOT']
    script_dir = os.path.dirname(job['script_path'])
    working_dir = main_script_dir if main_script_dir else script_dir
    os.chdir(working_dir)
   
    command = [
        sys.executable,
        job['script_path'],
        job['config_path'],
        '--work-dir', job['work_dir'],
        '--seed', str(job['seed']),
        '--device', job['device']
    ]

    if 'script_args' in job and job['script_args']:
        command.extend(job['script_args'])

    process = None

    env['PYTHONPATH'] = f"{working_dir}:{env.get('PYTHONPATH', '')}"

    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True, env=env)

        stdout, stderr = process.communicate()

        job_key = f"job_result:{job['user']}"

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
            logger.error(f"\nJob Error: {stderr}, out msg: {stdout}")
            return False
    except Exception as e:
        logger.error(f"\nError during job execution: {str(e)}")
        return False
    except KeyboardInterrupt as e:
        logger.error(f"\n Error KeyboardInterrupt")
        if process and process.poll() is None:
            process.terminate()
            process.wait
        raise
    finally:
        if process in locals() and process.poll() is None:
            process.terminate()
            process.wait()
        release_gpu(r, gpu_id)
        print(f"GPU {gpu_id} Returned\n")

def process_output(line, job_key, r):
    # 실시간 출력
    # print(line.strip())
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

    if matches['epoch_pattern']:
        is_additional = matches['epoch'].group(1) is not None
        current_epoch, total_epochs = matches['epoch'].group(2), matches['epoch'].group(3)
        pipe.hset(job_key, "current_epoch", current_epoch)
        pipe.hset(job_key, "total_epochs", total_epochs)
        pipe.hset(job_key, "is_additional_training", "1" if is_additional else "0")
    
    if matches['loss_pattern']:
        train_loss, train_metric = matches['loss'].groups()
        current_epoch = r.hget(job_key, "current_epoch").decode()
        pipe.hset(job_key, f"epoch_{current_epoch}_train_loss", f"{float(train_loss):.4f}")
        pipe.hset(job_key, f"epoch_{current_epoch}_train_metric", f"{float(train_metric):.4f}")
    
    if matches['val_pattern']:
        val_loss, val_metric = matches['val'].groups()
        current_epoch = r.hget(job_key, "current_epoch").decode()
        pipe.hset(job_key, f"epoch_{current_epoch}_val_loss", f"{float(val_loss):.4f}")
        pipe.hset(job_key, f"epoch_{current_epoch}_val_metric", f"{float(val_metric):.4f}")

    for key in ['class_loss_pattern', 'class_metric_pattern', 'val_class_loss_pattern', 'val_class_metric_pattern']:
        if matches[key]:
            pipe.hset(job_key, f"epoch_{current_epoch}_{key}", matches[key].group(1))

    pipe.execute()

    required_patterns = ['loss_pattern', 'val_pattern']
    optional_patterns = ['class_loss_pattern', 'class_metric_pattern', 'val_class_loss_pattern', 'val_class_metric_pattern']

    # if all(matches[k] for k in ['loss_pattern', 'val_pattern', 'class_loss_pattern', 'class_metric_pattern', 'val_class_loss_pattern', 'val_class_metric_pattern']):
    if all(matches[k] for k in required_patterns) and any(matches[k] for k in optional_patterns):
        epoch_type = "Additional " if is_additional else ""
        current_epoch = r.hget(job_key, "current_epoch").decode()
        total_epochs = r.hget(job_key, "total_epochs").decode()

        # 메시지 변수
        log_msg = f"\n{epoch_type}Epoch {current_epoch}/{total_epochs} 완료:"
        train_msg = f" Train Loss: {train_loss:.4f}, Train Metric: {train_metric:.4f}"
        val_msg = f" Val Loss: {val_loss:.4f}, Val Metric: {val_metric:.4f}"
        train_class_loss_msg = f" Train Class Losses: {matches['class_loss_pattern'].group(1)}"
        train_class_metric_msg = f" Train Class Losses: {matches['class_loss_pattern'].group(1)}"
        val_class_loss_msg = f" Val Class Losses: {matches['val_class_loss_pattern'].group(1)}"
        val_class_metric_msg = f" Val Class Metric: {matches['val_class_metric_pattern'].group(1)}"

        # message 클래스 list
        messages = [
            log_msg,
            train_msg,
            val_msg,
            train_class_loss_msg,
            train_class_metric_msg,
            val_class_loss_msg,
            val_class_metric_msg
        ]

        # 출력과 동시에 logging
        for msg in messages:
            print(msg)
            logger.inf(msg)

def process_message(message, channel):
    try:
        try:
            decompressed_message = zlib.decompress(message)
            job = json.loads(decompressed_message.decode())
        except zlib.error:
            job = json.loads(message.decode())

        logger.info(f"Processing job: {job}")
        gpu_id = get_available_gpu(r)
        result = run_job(job, r, channel, gpu_id)

        if result:
            job_key = f"job_result:{job['user']}:{job['model_name']}"
            all_keys = r.hkeys(job_key)
            epoch_keys = [key for key in all_keys if key.startswith(b'epoch_')]
            if epoch_keys:
                last_epoch = max([int(key.split(b'_')[1]) for key in epoch_keys])
                final_metric = r.hget(job_key, f"epoch_{last_epoch}_val_metric")
                if final_metric:
                    logger.info(f"Job completed for user {job['user']}. Final accuracy: {final_metric.decode('utf-8')}")
                else:
                    logger.warning(f"Job completed for user {job['user']} but final accuracy not found")
            else:
                logger.warning(f"Job completed for user {job['user']} but no epoch data found")
        else:
            logger.error(f"Job failed for user {job['user']}")
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {e}")
        return
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        return
    except KeyboardInterrupt as e:
        logger.error(f"KeyboardInterrupt. 종료.")
        return
    finally:
        if gpu_id is not None:
            release_gpu(r, gpu_id)
        logger.info("[*] Waiting for messages. To exit press CTRL+C")

def process_batch(messages):
    for message in messages:
        process_message(message)

def callback(ch, method, properties, body):
    try:
        logger.info(f"Received message: {body[:100]}...")
        process_message(body, ch)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
    finally:
        ch.basic_ack(delivery_tag=method.delivery_tag)


def signal_handler(signum, frame):
    logger.info("Interrupt received, stopping consumer...")
    if 'channel' in globals() and channel.is_open:
        try:
            channel.queue_delete(queue=RABBITMQ_CONFIG['QUEUE'])
            logger.info("Queue is successfully deleted")
        except Exception as e:
            logger.error(f"Error deleting queue: {e}")
        channel.stop_consuming()
    if 'connection' and connection.is_open:
        try:
            connection.close()
        except Exception as e:
            logger.error(f"Error closing connection: {e}")
    sys.exit(0)

def main():
    print(f"Number of available GPUs: {torch.cuda.device_count()}")
    print(f"CUDA is available: {torch.cuda.is_available()}")

    global channel, connection

    channel = None
    connection = None

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while True:
            try:
                connection, channel = connect_to_rabbitmq()
                initialize_gpu_list(r)
                # channel.queue_declare(queue=AUGMENTATION_QUEUE)
                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(queue=RABBITMQ_CONFIG['QUEUE'], on_message_callback=callback)
                logger.info(' [*] Waiting for messages. To exit press CTRL+C')
                channel.start_consuming()
            except (AMQPConnectionError, AMQPChannelError) as e:
                logger.error(f"RabbitMQ connection error: {e}")
                logger.info("Attempting to reconnect in 5 seconds...")
                time.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                logger.info("Attempting to reconnect in 5 seconds...")
                time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Consumer 종료")
    finally:
        if channel and channel.is_open:
            channel.stop_consuming()
        if connection and not connection.is_closed:
            connection.close()
        logger.info("Connection Closed")
        sys.exit(0)


if __name__ == "__main__":
    main()