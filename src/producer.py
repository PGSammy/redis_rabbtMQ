import pika
import json
import argparse
from config import RABBITMQ_HOST, RABBITMQ_QUEUE, USER_NAME

connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
channel = connection.channel()
channel.queue_declare(queue=RABBITMQ_QUEUE)

def submit_job(job_data):
    channel.basic_publish(
        exchange='',
        routing_key=RABBITMQ_QUEUE,
        body=json.dumps(job_data),
        properties=pika.BasicProperties(delivery_mode=2)
    )
    print(f"Submitted job: {job_data}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Submit a training job to the queue')
    parser.add_argument('--script_path', type=str, required=True, help='Path to the training script')
    parser.add_argument('--model', type=str, required=True, help='Model name')
    parser.add_argument('--dataset', type=str, required=True, help='Dataset name')
    parser.add_argument('--batch_size', type=int, required=True, help='Batch size')
    parser.add_argument('--epochs', type=int, required=True, help='Number of epochs')
    parser.add_argument('--additional_args', nargs=argparse.REMAINDER, help='Additional arguments for the training script')
    args = parser.parse_args()

    job = {
        'user': USER_NAME,
        'script_path': args.script_path,
        'model': args.model,
        'dataset': args.dataset,
        'batch_size': args.batch_size,
        'epochs': args.epochs,
        'additional_args': args.additional_args if args.additional_args else []
    }

    submit_job(job)
    print(f"Job submitted to queue by user {USER_NAME}")
    connection.close()