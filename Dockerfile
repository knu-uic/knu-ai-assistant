# db.py에서 f-string 안에 중첩 쌍따옴표를 쓰고 있어서 Python 3.12 이상 필요 (PEP 701)
FROM python:3.12-slim

WORKDIR /app

# 시스템 패키지:
#   - poppler-utils: pdf2image가 PDF 페이지를 이미지로 렌더링할 때 필요 (스캔 PDF VLM 폴백 경로)
#   - fonts-noto-cjk: PDF 안에 한글 폰트가 임베드 안 돼 있을 때 렌더링 깨짐 방지
# playwright는 아래에서 --with-deps로 자체 시스템 의존성을 설치하므로 여기서는 PDF 쪽만 챙긴다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# BGE-reranker 모델 캐시 경로. bind mount(.:/app)로 호스트에 보존되어
# 컨테이너 재빌드/재기동에도 모델 재다운로드(~600MB) 발생 안 함.
ENV HF_HOME=/app/.hf_cache

# torch는 CPU-only 휠을 먼저 설치한다. torch 2.12부터 기본 manylinux 휠이
# CUDA 라이브러리(cuBLAS/cuDNN/nccl 등 ~2GB)를 dep로 끌어와서, 그냥 pip install
# torch 하면 이미지가 ~3GB 부풀고 우리한테는 무용지물(CPU 추론만 함).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

# 파이썬 패키지 설치 (위에서 torch가 이미 깔려 있어 sentence-transformers는 CPU torch를 재사용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# playwright 브라우저 + 시스템 의존성 설치 (크롬리움만)
RUN python -m playwright install --with-deps chromium

# 앱 소스 복사 (docker-compose에서 bind mount로 덮어쓰지만, mount 없이 단독 실행해도 동작하게)
COPY . .

EXPOSE 8501

# Streamlit 웹 서버 실행
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
