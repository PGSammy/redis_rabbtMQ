# redis_rabbtMQ
using server for deep-learning model execution


# How to Execute Redis
1. cmd를 관리자 명령으로 실행
2. Redis 설치 파일로 이동하기 (다운로드 폴더면 다운로드 폴더 등)
3. redis-server.exe --service-install redis.windows.conf --loglevel verbose 명령어로 redis server 실행
** 만약 Redis가 실행중이라면 sc delete Redis로 Redis 서버 삭제 **
4. net start Redis 로 Redis Server 접속
5. redis-cli ping -> "Pong"으로 답변 올 시 접속 완료
   
# How to login in this program
export USER_NAME=user1 # 각자마다 고유의 user_name을 통해 QUEUE가 겹치지 않도록 설정함.
python producer.py
