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
from pika.exceptions import AMQPConnectionError, AMQPChannelError
from config import RABBITMQ_CONFIG, REDIS_CONFIG

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

def run_job(job, r, channel):
    gpu_id = get_available_gpu(r)
    env = os.environ.copy()
    env['CUDA_VISIBLE_DEVICES'] = str(gpu_id)
    env['PATH'] = f"{os.path.dirname(sys.executable)};{env['PATH']}"

    # 프로젝트 루트 디렉토리 설정
    project_root = os.path.dirname(job['config_path'])
    os.chdir(project_root)
    env['PROJECT_ROOT'] = project_root

    main_script_dir = os.path.dirname(job['script_path'])
    os.chdir(main_script_dir)

    config = {}
    config_dir = os.path.join(project_root, 'configs')
    for config_file in os.listdir(config_dir):
        if config_file.endswith('yaml'):
            with open(os.path.join(config_dir, config_file), 'r') as f:
                config.update(yaml.safe_load(f))

    # config 파일 읽기 (수정된 부분)
    # with open(job['config_path'], 'r') as f:
    #     config = yaml.safe_load(f)

    os.chdir(os.path.dirname(job['script_path']))

    # config 파일의 경로 업데이트
    config['data']['data_dir'] = os.path.join(project_root, 'data')
    config['data']['train_dir'] = os.path.join(project_root, 'data', 'train')
    config['data']['train_info_file'] = os.path.join(project_root, 'data', 'train.csv')
    config['data']['test_dir'] = os.path.join(project_root, 'data', 'test')
    config['data']['test_info_file'] = os.path.join(project_root, 'data', 'test.csv')
    config['data']['augmented_dir'] = os.path.join(project_root, 'data', 'augmented.csv')

    # 파일 존재 여부 확인
    for key in ['train_info_file', 'test_info_file']:
        if not os.path.exists(config['data'][key]):
            logger.error(f"{key} not found: {config['data'][key]}")
            release_gpu(r, gpu_id)
            return False
        
    # train_file과 test_file 경로 설정
    train_file = os.path.join(project_root, 'data', 'train.csv')
    test_file = os.path.join(project_root, 'data', 'test.csv')
    aug_file = os.path.join(project_root, 'data', 'augmented.csv')

    logger.info(f"Train file path: {train_file}")
    logger.info(f"Test file path: {test_file}")
    logger.info(f"Aug file path: {aug_file}")

    if not os.path.exists(train_file) or not os.path.exists(test_file):
        logger.error(f"Train file ({train_file}) or test file ({test_file}) not found")
        release_gpu(r, gpu_id)
        return False
    
    # 자동 augmentation 진행
    # if not os.path.exists(aug_file):
    #     logger.info(f"Augmented file ({aug_file}) not found. Sending job to augmentation queue")
    #     try:
    #         # 전송
    #         channel.basic_publish(
    #             exchange='',
    #             routing_key=AUGMENTATION_QUEUE,
    #             body=json.dumps({
    #                 'config_path': job['config_path'],
    #                 'script_path': job['script_path'],
    #                 'data_path': job['data_path'],
    #                 'aug_path': job['aug_path'],
    #                 'train_csv_path': train_file,
    #                 'test_csv_path': test_file
    #             }),
    #             properties=pika.BasicProperties(delivery_mode=2,)
    #         )
    #         release_gpu(r, gpu_id)
    #     except json.JSONDecodeError as je:
    #         logger.error(f"JSON encoding error: {je}")
    #         release_gpu(r, gpu_id)
    #         return False
    #     except pika.exceptions.AMQPError as ae:
    #         logger.error(f"AMQP error when sending message: {ae}")
    #         release_gpu(r, gpu_id)
    #         return False
    #     except Exception as e:
    #         logger.error(f"Unexpected error when sending message: {e}")
    #         release_gpu(r, gpu_id)
    #         return False

    config['data']['train_info_file'] = os.path.join('data', 'train.csv')
    config['data']['test_info_file'] = os.path.join('data', 'test.csv')
    config['data']['augmented_info_file'] = os.path.join('data', 'augmented.csv')

    temp_config_path = f"temp_config_{job['user']}_{job['model_name']}.yaml"

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
        temp_config_path = temp_file.name
        yaml.dump(config, temp_file)

    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Actual train file path: {os.path.abspath(config['data']['train_info_file'])}")
    logger.info(f"Augmented file path: {os.path.abspath(config['data']['augmented_info_file'])}")

    mode = config.get('mode', 'train')

    command = [
        sys.executable,
        os.path.basename(job['script_path']),
        'config_path', os.path.relpath(config_dir, main_script_dir),
        '--mode', mode,
        '--model_name', job['model_name'],
        '--learning_rate', str(job['learning_rate'])
    ]

    process = None

    try:
        # os.chdir(os.path.dirname(os.path.dirname(job['config_path'])))

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True)

        stdout, stderr = process.communicate()

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
            logger.error(f"\nJob Error: {stderr}, out msg: {stdout}")
            logger.info(f"Project root: {job['data_path']}")
            logger.info(f"Train file path: {train_file}")
            logger.info(f"Test file path: {test_file}")
            return False
    except Exception as e:
        logger.error(f"\nError during job execution: {str(e)}")
        return False
    except KeyboardInterrupt as e:
        logger.error(f"\n Error KeyboardInterrupt")
        return False
    finally:
        if process in locals() and process.poll() is None:
            process.terminate()
            process.wait()
        release_gpu(r, gpu_id)
        print(f"GPU {gpu_id} Returned\n")
        os.chdir(project_root)

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

    if all(matches[k] for k in ['loss_pattern', 'val_pattern', 'class_loss_pattern', 'class_metric_pattern', 'val_class_loss_pattern', 'val_class_metric_pattern']):
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
        
        log_message = f" Train Class Losses: {matches['class_loss_pattern'].group(1)}"
        print(log_message)
        logger.info(log_message)
        
        log_message = f" Train Class Metric: {matches['class_metric_pattern'].group(1)}"
        print(log_message)
        logger.info(log_message)
        
        log_message = f" Val Class Losses: {matches['val_class_loss_pattern'].group(1)}"
        print(log_message)
        logger.info(log_message)
        
        log_message = f" Val Class Metric: {matches['val_class_metric_pattern'].group(1)}"
        print(log_message)
        logger.info(log_message)

def process_message(message, channel):
    try:
        try:
            decompressed_message = zlib.decompress(message)
            job = json.loads(decompressed_message.decode())
        except zlib.error:
            job = json.loads(message.decode())

        logger.info(f"Processing job: {job}")
        result = run_job(job, r, channel)

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
        logger.error(f"Error processing message: {str(e)}")
    except KeyboardInterrupt as e:
        logger.error(f"KeyboardInterrupt. 종료.")

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

def main():
    print(f"Number of available GPUs: {torch.cuda.device_count()}")
    print(f"CUDA is available: {torch.cuda.is_available()}")

    channel = None
    connection = None

    def signal_handler(signum, frame):
        logger.info("Interrupt received, stopping consumer...")
        if 'channel' in globals() and channel.is_open:
            channel.stop_consuming()

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


if __name__ == "__main__":
    main()