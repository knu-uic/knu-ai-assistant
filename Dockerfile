# 파이썬 3.10 버전을 가벼운(slim) 버전으로 가져옵니다.
FROM python:3.10-slim

# 컨테이너 안에서 작업할 기준 폴더를 /app 으로 설정합니다.
WORKDIR /app

# 필요한 파이썬 패키지 목록을 컨테이너로 복사합니다.
COPY requirements.txt .

# 패키지들을 설치합니다.
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps chromium

# Streamlit 웹 서버를 실행합니다.
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]