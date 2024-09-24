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

logger = logging.getLogger(__name__)

# config.yaml 가져오기
def get_config(yaml_path):
    config = {}

    yaml_files = [f for f in os.listdir(yaml_path) if f.endswith('.yaml')]

    for files in yaml_files:
        file_path = os.path.join(yaml_path, files)
        try:
            with open(file_path, 'r') as f:
                yaml_content = yaml.safe_load(f)
                if yaml_content:
                    config.update(yaml_content)
            logger.info(f"Loaded config file: {files}")
        except Exception as e:
            logger.warning(f"Failed loading config file {files} as {e}")
    
    if not config:
        logger.warning(f"No valid YAML files found in {yaml_path}")

    return config

# config 정보 추출 (추후 추가 예정)
def extract_info(config):
    model_name = config['model']['name']
    learning_rate = config['training']['learning_rate']
    return model_name, learning_rate

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
    parser = argparse.ArgumentParser(description='Submit a training job to the queue')
    parser.add_argument('--config_path', type=str, required=True, help='Path to the YAML config file')
    parser.add_argument('--script_path', type=str, required=True, help='Path to the training script')
    parser.add_argument('--data_path', type=str, required=True, help='Path to the data directory')
    # parser.add_argument('--aug_path', type=str, required=True, help='Path to the aug directory')
    args = parser.parse_args()

    try:
        connection, channel = connect_to_rabbitmq()

        config = get_config(args.config_path)
        model_name, learning_rate = extract_info(config)

        job = {
            'user': USER_NAME,
            'script_path': args.script_path,
            'config_path': args.config_path,
            'data_path': args.data_path,
            # 'aug_path': args.aug_path,
            'model_name': model_name,
            'learning_rate': learning_rate
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