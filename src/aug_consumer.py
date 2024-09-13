import pika
import json
import redis
import yaml
import os
import sys
import subprocess
import logging
from config import RABBITMQ_HOST, AUGMENTATION_QUEUE, REDIS_HOST, REDIS_PORT, REDIS_DB

def augment_data(job):
    with open(job['config_path'], 'r') as f:
        config = yaml.safe_load(f)

    env = os.environ.copy()
    env['TRAIN_CSV_PATH'] = job['train_csv_path']
    env['TEST_CSV_PATH'] = job['test_csv_path']

    os.chdir(os.path.dirname(job['script_path']))

    command = [
        sys.executable,
        job['script_path'],
        '--aug_path', job['aug_path'],
        '--config_path', job['config_path']
    ]

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()

    if process.returncode == 0:
        logging.info("Augmentation completed successfully")
        return True
    else:
        logging.error(f"Augmentation failed: {stderr}")
        return False
    
def callback(ch, method, properties, body):
    job = json.loads(body)
    result = augment_data(job)
    if result:
        # 원래 작업 큐로 다시 전송
        ch.basic_publish(
            exchange='',
            routing_key='original_queue',
            body=body
        )
    ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()
    channel.queue_declare(queue=AUGMENTATION_QUEUE)
    channel.basic_consume(queue=AUGMENTATION_QUEUE, on_message_callback=callback)
    logging.info("Waiting for augmentation messages, To exit press CTRL+C")
    channel.start_consuming()

if __name__ == "__main__":
    main()