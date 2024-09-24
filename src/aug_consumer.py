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
    try:
        project_root = os.path.dirname(job['config_path'])
        os.chdir(project_root)

        config = {}
        config_dir = os.path.join(project_root, 'configs')
        for config_file in os.listdir(config_dir):
            if config_file.endswith('yaml'):
                with open(os.path.join(config_dir, config_file), 'r') as f:
                    config.update(yaml.safe_load(f))

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
    except Exception as e:
        logging.exception(f"An error occurred during augmentation:{str(e)}")
        return False    
    
    
def callback(ch, method, properties, body):
    try:
        job = json.loads(body)
        result = augment_data(job)
        if result:
            # 원래 작업 큐로 다시 전송
            ch.basic_publish(
                exchange='',
                routing_key='original_queue',
                body=body
            )
        else:
            logging.error("Augmentation failed, not sending job back to original queue")
    except Exception as e:
        logging.exception(f"An error occurred in callback: {str(e)}")
    finally:
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