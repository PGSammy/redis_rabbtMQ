# redis_rabbtMQ
using server for deep-learning model execution
   
# How to login in this program
export USER_NAME=user1 # 각자마다 고유의 user_name을 통해 QUEUE가 겹치지 않도록 설정함.
python producer.py

# To use consumer.py (producer.py 실행 전에 consumer.py를 먼저 실행시켜 대기열 받는 프로그램 실행 후 producer.py 실행)
1. 터미널 창에서 경로에 따라간 후 python /경로/consumer.py 입력, Enter
2. Waiting for message 라는 메시지가 나오면 실행 완료
3. Error 메시지가 나올 경우 Error 메시지 복사해서 관리자에게 문의

# To use producer.py
python producer.py --config_path path/to/your/config.yaml --script_path path/to/your/train.py
# 로컬에서 돌릴때는 자기 경로 찾아서 넣기
--> python src/producer.py --config_path C:\Users\User\Desktop\AIBoostcamp\level1-imageclassification-cv-24\configs --script_path C:\Users\User\Desktop\AIBoostcamp\level1-imageclassification-cv-24\main.py --data_path C:\Users\User\Desktop\AIBoostcamp\level1-imageclassification-cv-24\data
# GPU 서버에서 할때의 경로 복붙해서 쓰면 됨
--> python src/producer.py --config_path /data/ephemeral/home/level1-imageclassification-cv-24/configs --script_path /data/ephemeral/home/level1-imageclassification-cv-24/main.py --data_path C:\Users\User\Desktop\AIBoostcamp\level1-imageclassification-cv-24\data

# Error Log
1.  not matching erlang cookie
    - check your C\Users\Yourusername\erlang.cookie file
    - fine erlang.cookie file in system32.config.systemprofile and copy/paste to user folder
    - To check its working
    1)  rabbitmqctl status
    2)  rabbitmq-plugins enable rabbitmq_management (executing)
    3)  go to web-interface(http://localhost:PORT)
    4)  check the log file (C:\Users\Yourusername\AppData\Roaming\RabbitMQ\log)
    5)  Check queue works
        rabbitmqctl add_vhost test_vhost
        rabbitmqctl add_user test_user test_password
        rabbitmqctl set_permissions -p test_vhost test_user ".*" ".*" ".*"
        ** 권한 해제 및 유저 빼기 **
        rabbitmqctl clear_permissions -p test_vhost test_user
        rabbitmqctl delete_user test_user
        rabbitmqctl delete_vhost test_vhost
    6)  Run your file in python

2.  To start rabbitmqctl / rabbitmq
    - rabbitmqctl start_app -> rabbitmqctl status
    - net start rabbitmq, net stop rabbitmq

3.  방화벽 차단 (Firewall issue) 풀기
    - Windows Defender 방화벽 검색 후 실행
    - 고급 설정 클릭
    - 인바운드 규칙 클릭
    - RabbitMQ 관련 규칙 찾기
    - 규칙이 있다면 상태가 사용인지 확인
    - 규칙이 없다면 새 규칙 버튼을 클릭 -> 포트 선택 -> TCP와 특정 로컬 5672 입력 -> 연결 허용 -> 프로필 선택 -> 이름 지정 후 저장
    - cmd에서 확인 -> netsh advfirewall firewall show rule name=all | findstr /i "5672"

4.  방화벽 해제 cmd
    - netsh advfirewall firewall add rule name="Redis" dir=in action=allow protocol=TCP localport=6379

### 중요!!! 설치 및 실행하는 방법 정리 ###

# 로컬 개발 환경 설정 가이드

이 가이드는 로컬 개발 환경에서 Redis와 RabbitMQ를 설치하고 실행하는 방법을 설명합니다.

## Redis 설치 및 실행

### Windows:
1. [Redis for Windows](https://github.com/microsoftarchive/redis/releases)에서 최신 버전을 다운로드합니다.
2. 다운로드한 파일을 압축 해제하고 원하는 위치에 저장합니다.
# 여기는 로컬에서 실행할 때임.
3. 명령 프롬프트를 열고 Redis가 설치된 디렉토리로 이동합니다.
4. `redis-server.exe`를 실행하여 Redis 서버를 시작합니다.

### macOS:
1. Homebrew를 사용하여 Redis를 설치합니다: brew install redis
2. Redis 서버 시작하기: brew services start redis

### Linux (Ubuntu/Debian):
1. 터미널에서 다음 명령어 실행하여 redis 설치:
    apt-get sudo
    apt-get systemctl
    sudo apt update
    sudo apt install redis-server
2. Redis 서버 시작하기
    sudo systemctl start redis-server

## RabbitMQ 설치 및 실행

### Windows:
1. [Erlang](https://www.erlang.org/downloads)을 다운로드하고 설치합니다.
2. [RabbitMQ](https://www.rabbitmq.com/install-windows.html)를 다운로드하고 설치합니다.
3. 시작 메뉴에서 RabbitMQ Command Prompt를 실행합니다.
4. 다음 명령어로 RabbitMQ 서버를 시작합니다: rabbitmq-server / net start rabbitmq

### macOS:
1. Homebrew를 사용하여 RabbitMQ를 설치합니다: brew install rabbitmq
2. RabbitMQ 서버를 시작합니다: brew services start rabbitmq

### Linux (Ubuntu/Debian):
1. RabbitMQ를 설치합니다:
    sudo apt update
    sudo apt install rabbitmq-server
2. RabbitMQ 서버를 시작합니다:
    sudo systemctl start rabbitmq-server

## 환경 설정

1. 프로젝트 루트 디렉토리에 있는 `.env.example` 파일을 복사하여 `.env` 파일을 src 밑에 만들어주면 됩니다.
2. `.env` 파일을 열고 필요한 경우 설정을 수정합니다. 기본값은 다음과 같습니다:
    RABBITMQ_HOST=localhost
    RABBITMQ_PORT=5672
    RABBITMQ_USER=guest
    RABBITMQ_PASSWORD=guest
    REDIS_HOST=localhost
    REDIS_PORT=6379
    REDIS_PASSWORD=''
    USER_NAME='your_name'

## 확인

1. Redis가 실행 중인지 확인: redis-cli ping (이건 Window나 macOS 사용 시 cmd에서 실행)
    "PONG" 응답이 오면 정상 작동 중입니다.
    # linux 환경에서 하는 경우
    sudo service redis-server status -> 확인
2. RabbitMQ가 실행 중인지 확인: rabbitmqctl status (이건 Window나 macOS 사용 시 cmd에서 실행)
    sudo service rabbitmq-server status -> 확인

상태 정보가 표시되면 정상 작동 중입니다.

문제가 발생하거나 추가 도움이 필요한 경우 프로젝트 관리자에게 문의하세요.

## 마지막으로 wandb login

1.  각자의 main.py가 있는 프로젝트를 터미널에서 새로 열어주고
2.  pip install wandb (설치가 안되어있는 경우)
    wandb login
3.  wandb: You can find your API key in your browser here: https://wandb.ai/authorize
    wandb: Paste an API key from your profile and hit enter:
    이 명령어가 나오면 https://wandb.ai/authorize 에 가서 로그인 후 나오는 API키 복사하여 터미널에 붙여넣고 Enter
4.  로그인 확인:
    wandb: Appending key for api.wandb.ai to your netrc file: /home/username/.netrc -> 성공 메시지