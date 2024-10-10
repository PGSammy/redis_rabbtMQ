import pika
import json
import argparse
import pika.exceptions
import yaml
import time
from config import RABBITMQ_CONFIG, USER_NAME
import sys
import logging
import zlib
import os
import importlib

logger = logging.getLogger(__name__)

# config.yaml 가져오기
def get_config(config_path):
    config = {}

    config_files = [f for f in os.listdir(config_path) if f.endswith(('.yaml', '.py'))]

    for files in config_files:
        file_path = os.path.join(config_path, files)
        try:
            if files.endswith('.yaml'):
                with open(file_path, 'r') as f:
                    yaml_content = yaml.safe_load(f)
                    if yaml_content:
                        config.update(yaml_content)
                logger.info(f"Loaded config file: {files}")
            elif files.endswith('.py'):
                # Python 파일 로드
                spec = importlib.util.spec_from_file_location(files[:-3], file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # 모듈에서 대문자로 시작하는 모든 변수를 설정으로 간주
                py_config = {k: v for k, v in module.__dict__.items() if not k.startswith('__') and not callable(v) and not k.startswith('_')}
                config.update(py_config)
                logger.info(f"Loaded Python config file: {files}")
        except Exception as e:
            logger.warning(f"Failed loading config file {files} as {e}")
    
    if not config:
        logger.warning(f"No valid YAML/py files found in {file_path}")

    return config

# config 정보 추출 (추후 추가 예정)
def extract_info(config):
    model_name = config.get('model', {}).get('name', 'default_model')
    learning_rate = config.get('training', {}).get('learning_rate', 0.001)
    return model_name, learning_rate

# config validate
def validate_config(config):
    required_keys = ['model', 'training']
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required key in config: {key}")

# rabbitmq 연결
def connect_to_rabbitmq():
    retries = 0
    MAX_RETRIES = 5
    RETRY_DELAY = 5  # seconds
    while retries < MAX_RETRIES:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(
                host=RABBITMQ_CONFIG['HOST'],
                port=RABBITMQ_CONFIG['PORT'],
                credentials=pika.PlainCredentials(RABBITMQ_CONFIG['USER'], RABBITMQ_CONFIG['PASSWORD'])
            ))
            channel = connection.channel()
            channel.queue_declare(queue=RABBITMQ_CONFIG['QUEUE'])
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

# job 입력
def submit_job(channel, job_data):
    channel.basic_publish(
        exchange='',
        routing_key=RABBITMQ_CONFIG['QUEUE'],
        body=json.dumps(job_data),
        properties=pika.BasicProperties(delivery_mode=2)
    )
    logger.info(f"Submitted job: {job_data}")

# main
def main():
    print("Script is starting...")
    print("Python version:", sys.version)
    print("Command line arguments:", sys.argv)
    
    parser = argparse.ArgumentParser(description='Submit a training job to the queue')
    parser.add_argument('--config_path', type=str, required=True, help='Path to the config file')
    parser.add_argument('--work-dir', type=str, required=True, help='Work directory')
    parser.add_argument('--script_path', type=str, required=True, help='Path to the training script')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--device', type=str, default='cuda', help='Device to use')
    parser.add_argument('script_args', nargs=argparse.REMAINDER, help='Additional arguments for the script')

    args = parser.parse_args()
    print("Parsed arguments:", args)

    try:
        connection, channel = connect_to_rabbitmq()

        # config = get_config(args.config_path)
        # model_name, learning_rate = extract_info(config)

        job = {
            'user': USER_NAME,
            'config_path': args.config_path,
            'work_dir': args.work_dir,
            'seed': args.seed,
            'device': args.device,
            'script_path': args.script_path,
            'script_args': args.script_args
        }

        compressed_message = zlib.compress(json.dumps(job).encode())

        channel.basic_publish(
            exchange='',
            routing_key=RABBITMQ_CONFIG['QUEUE'],
            body=compressed_message,
            properties=pika.BasicProperties(delivery_mode=2)
        )

        # submit_job(channel, job)
        logger.info(f"Job submitted to queue by user {USER_NAME}")
    except pika.exceptions.AMQPConnectionError:
        logger.error("Failed to connect to RabbitMQ after multiple attempts. Exiting.")
        sys.exit(1)
    finally:
        if 'connection' in locals() and connection.is_open:
            connection.close()


if __name__ == "__main__":
    main()    