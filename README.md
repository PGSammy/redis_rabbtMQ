# redis_rabbtMQ
using server for deep-learning model execution


# How to Execute Redis
Redis 접속 시 사용
cd ..
cd .. 
cd Users\User\Desktop\Redis-x64-3.0.504
1. cmd를 관리자 명령으로 실행
2. Redis 설치 파일로 이동하기 (다운로드 폴더면 다운로드 폴더 등)
3. redis-server.exe --service-install redis.windows.conf --loglevel verbose 명령어로 redis server 실행
** 만약 Redis가 실행중이라면 sc delete Redis로 Redis 서버 삭제 또는 net stop Redis 사용 **
4. net start Redis 로 Redis Server 접속
5. redis-cli ping -> "Pong"으로 답변 올 시 접속 완료
   
# How to login in this program
export USER_NAME=user1 # 각자마다 고유의 user_name을 통해 QUEUE가 겹치지 않도록 설정함.
python producer.py

# To use producer.py
python producer.py --config_path path/to/your/config.yaml --script_path path/to/your/train.py
--> python producer.py --config_path C:\Users\User\Desktop\AIBoostcamp\Project\configs\default.yaml --script_path C:\Users\User\Desktop\AIBoostcamp\Project\scripts\train.py

# Error Log
1. not matching erlang cookie
- check your C\Users\Yourusername\erlang.cookie file
- fine erlang.cookie file in system32.config.systemprofile and copy/paste to user folder
- To check its working
1) rabbitmqctl status
2) rabbitmq-plugins enable rabbitmq_management (executing)
3) go to web-interface(http://localhost:PORT)
4) check the log file (C:\Users\Yourusername\AppData\Roaming\RabbitMQ\log)
5) Check queue works
rabbitmqctl add_vhost test_vhost
rabbitmqctl add_user test_user test_password
rabbitmqctl set_permissions -p test_vhost test_user ".*" ".*" ".*"
** 권한 해제 및 유저 빼기 **
rabbitmqctl clear_permissions -p test_vhost test_user
rabbitmqctl delete_user test_user
rabbitmqctl delete_vhost test_vhost
6) Run your file in python

2. To start rabbitmqctl / rabbitmq
- rabbitmqctl start_app -> rabbitmqctl status
- net start rabbitmq, net stop rabbitmq

3. 방화벽 차단 (Firewall issue)
- Windows Defender 방화벽 검색 후 실행
- 고급 설정 클릭
- 인바운드 규칙 클릭
- RabbitMQ 관련 규칙 찾기
- 규칙이 있다면 상태가 사용인지 확인
- 규칙이 없다면 새 규칙 버튼을 클릭 -> 포트 선택 -> TCP와 특정 로컬 5672 입력 -> 연결 허용 -> 프로필 선택 -> 이름 지정 후 저장
- cmd에서 확인 -> netsh advfirewall firewall show rule name=all | findstr /i "5672"

4. 방화벽 해제 cmd
- netsh advfirewall firewall add rule name="Redis" dir=in action=allow protocol=TCP localport=6379