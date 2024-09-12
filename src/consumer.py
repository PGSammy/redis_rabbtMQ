import pika
import json
import redis
import subprocess
import os
import time
import re
from config import RABBITMQ_HOST, RABBITMQ_QUEUE, REDIS_HOST, REDIS_PORT, REDIS_DB
import logging

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
        time.sleep(1)

def release_gpu(r: redis.Redis, gpu_id: int):
    available_gpus = json.loads(r.get('available_gpus') or '[]')
    available_gpus.append(gpu_id)
    r.set('available_gpus', json.dumps(available_gpus))

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
            logger.info(f"Job completed successfully for user{job['user']}")
            return True
        else:
            logger.error(f"Job failed for user {job['user']}")
            return False
    except Exception as e:
        logger.error(f"Error during job execution: {str(e)}")
        return False
    finally:
        release_gpu(r, gpu_id)

def process_output(line, job_key, r):
    print(line, end='')  # 실시간 출력

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

    if loss_match and val_match:
        current_epoch = r.hget(job_key, "current_epoch").decode()
        total_epochs = r.hget(job_key, "total_epochs").decode()
        is_additional = r.hget(job_key, "is_additional_training").decode() == "1"
        epoch_type = "Additional " if is_additional else ""
        logger.info(f"{epoch_type}Epoch {current_epoch}/{total_epochs} completed. "
                    f"Train Loss: {train_loss:.4f}, Train Metric: {train_metric:.4f}, "
                    f"Val Loss: {val_loss:.4f}, Val Metric: {val_metric:.4f}")

def parse_output(output, job):
    try:
        lines = output.strip().split('\n')
        csv_path = lines[-2].strip()
        accuracy = float(lines[-1].split(':')[-1].strip())
        return {
            'csv_path': csv_path,
            'accuracy': accuracy,
            'model': job['model'],
            'dataset': job['dataset'],
            'batch_size': job['batch_size'],
            'epochs': job['epochs']
        }
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing output: {e}")
        return None

def callback(ch, method, properties, body):
    job = json.loads(body)
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

if __name__ == "__main__":
    try:
        connection, channel = connect_to_rabbitmq()
        channel.basic_consume(queue=RABBITMQ_QUEUE, on_message_callback=callback)
        logger.info('Waiting for jobs. To exit press CTRL+C')
        channel.start_consuming()
    except pika.exceptions.AMQPConnectionError:
        logger.error("Failed to connect to RabbitMQ after multiple attempts. Exiting.")
    finally:
        if 'connection' in locals() and connection.is_open:
            connection.close()