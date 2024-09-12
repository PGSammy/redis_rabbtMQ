import unittest
from unittest.mock import MagicMock, patch
import json
import consumer

class TestConsumer(unittest.TestCase):

    @patch('consumer.r')
    def test_some_function(self, mock_redis):
        # 테스트 코드
        pass

    @patch('consumer.pika.BlockingConnection')
    def test_connect_to_rabbitmq(self, mock_connection):
        mock_channel = MagicMock()
        mock_connection.return_value.channel.return_value = mock_channel
        connection, channel = consumer.connect_to_rabbitmq()
        self.assertIsNotNone(connection)
        self.assertEqual(channel, mock_channel)

    @patch('consumer.time.sleep', return_value=None)
    def test_get_available_gpu(self, mock_sleep):
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps([0, 1, 2])
        
        gpu_id = consumer.get_available_gpu(mock_redis)
        self.assertEqual(gpu_id, 0)
        mock_redis.set.assert_called_with('available_gpus', json.dumps([1, 2]))

    def test_release_gpu(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps([1, 2])
        consumer.release_gpu(mock_redis, 0)
        mock_redis.set.assert_called_with('available_gpus', json.dumps([1, 2, 0]))

    @patch('consumer.subprocess.Popen')
    @patch('consumer.get_available_gpu')
    def test_run_job(self, mock_get_gpu, mock_popen):
        mock_get_gpu.return_value = 0
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = iter(["Epoch 1/10", "Train Loss: 0.1234, Train Metric: 0.9876", "Val Loss: 0.2345, Val Metric: 0.9765"])
        mock_popen.return_value = mock_process
        
        job = {
            'user': 'test_user',
            'model_name': 'test_model',
            'script_path': 'path/to/script.py',
            'config_path': 'path/to/config.yaml',
            'learning_rate': '0.001'
        }
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps([])
        
        result = consumer.run_job(job, mock_redis)
        self.assertTrue(result)

    def test_process_output(self):
        mock_redis = MagicMock()
        job_key = "job_result:test_user:test_model"
        lines = [
            "Epoch 1/10",
            "Train Loss: 0.1234, Train Metric: 0.9876",
            "Val Loss: 0.2345, Val Metric: 0.9765"
        ]
        
        mock_redis.hget.return_value = b'1'  # current_epoch

        for line in lines:
            consumer.process_output(line, job_key, mock_redis)
        
        mock_redis.hset.assert_any_call(job_key, "current_epoch", "1")
        mock_redis.hset.assert_any_call(job_key, "total_epochs", "10")
        mock_redis.hset.assert_any_call(job_key, "epoch_1_train_loss", "0.1234")
        mock_redis.hset.assert_any_call(job_key, "epoch_1_train_metric", "0.9876")
        mock_redis.hset.assert_any_call(job_key, "epoch_1_val_loss", "0.2345")
        mock_redis.hset.assert_any_call(job_key, "epoch_1_val_metric", "0.9765")

    @patch('consumer.run_job')
    @patch('consumer.redis.Redis')
    def test_process_output(self, mock_redis_class, mock_run_job):
        mock_redis = MagicMock()
        job_key = "job_result:test_user:test_model"
        lines = [
            "Epoch 1/10",
            "Train Loss: 0.1234, Train Metric: 0.9876",
            "Val Loss: 0.2345, Val Metric: 0.9765"
        ]
        
        mock_redis.hget.return_value = b'1'  # current_epoch

        for line in lines:
            consumer.process_output(line, job_key, mock_redis)
        
        mock_redis.hset.assert_any_call(job_key, "current_epoch", "1")
        mock_redis.hset.assert_any_call(job_key, "total_epochs", "10")
        mock_redis.hset.assert_any_call(job_key, "epoch_1_train_loss", "0.1234")
        mock_redis.hset.assert_any_call(job_key, "epoch_1_train_metric", "0.9876")
        mock_redis.hset.assert_any_call(job_key, "epoch_1_val_loss", "0.2345")
        mock_redis.hset.assert_any_call(job_key, "epoch_1_val_metric", "0.9765")

        # 호출 횟수 확인
        self.assertEqual(mock_redis.hset.call_count, 6)

if __name__ == '__main__':
    unittest.main()