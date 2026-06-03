FROM python:3.12-slim

WORKDIR /app

ENV HF_HOME=/root/.cache/huggingface

# 시스템 패키지:
#   - poppler-utils: pdf2image가 PDF 페이지를 이미지로 렌더링할 때 필요 (스캔 PDF VLM 폴백 경로)
#   - fonts-noto-cjk: PDF 안에 한글 폰트가 임베드 안 돼 있을 때 렌더링 깨짐 방지
#   - libreoffice: HWP 첨부를 headless PDF로 변환한 뒤 기존 PDF 파이프라인에 태움
#   - default-jre-headless: opendataloader-pdf(ODL)가 Java 11+ 런타임을 요구
# playwright는 아래에서 --with-deps로 자체 시스템 의존성을 설치하므로 여기서는 PDF 쪽만 챙긴다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        fonts-noto-cjk \
        libreoffice \
        libreoffice-h2orestart \
        default-jre-headless \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# playwright 브라우저 + 시스템 의존성 설치 (크롬리움만)
RUN python -m playwright install --with-deps chromium

# 앱 소스 복사 (docker-compose에서 bind mount로 덮어쓰지만, mount 없이 단독 실행해도 동작하게)
COPY . .

EXPOSE 8501

# Streamlit 웹 서버 실행
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
