FROM python:3.12-slim AS hwp2hwpx-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        git patch default-jdk-headless \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --target /tmp/hwp2hwpx-package hwp2hwpx==1.0.1
RUN git init /tmp/hwp2hwpx-source \
    && git -C /tmp/hwp2hwpx-source remote add origin https://github.com/neolord0/hwp2hwpx.git \
    && git -C /tmp/hwp2hwpx-source fetch --depth 1 origin edc05278506b663d5bdd98050a51f54b7ff5e0bc \
    && git -C /tmp/hwp2hwpx-source checkout --detach FETCH_HEAD \
    && cp /tmp/hwp2hwpx-source/src/main/java/kr/dogfoot/hwp2hwpx/ForContentHPFFile.java \
        /tmp/ForContentHPFFile.java
COPY third_party/hwp2hwpx/null-extension.patch /tmp/null-extension.patch
RUN patch /tmp/ForContentHPFFile.java < /tmp/null-extension.patch \
    && mkdir -p /tmp/classes /out \
    && javac -encoding UTF-8 \
        -cp /tmp/hwp2hwpx-package/hwp2hwpx/jars/hwp2hwpx.jar \
        -d /tmp/classes /tmp/ForContentHPFFile.java \
    && cp /tmp/hwp2hwpx-package/hwp2hwpx/jars/hwp2hwpx.jar /out/hwp2hwpx-patched.jar \
    && jar uf /out/hwp2hwpx-patched.jar \
        -C /tmp/classes kr/dogfoot/hwp2hwpx/ForContentHPFFile.class

FROM python:3.12-slim

WORKDIR /app

COPY --from=hwp2hwpx-builder /out/hwp2hwpx-patched.jar /opt/hwp2hwpx/hwp2hwpx-patched.jar

ENV HF_HOME=/root/.cache/huggingface

# 시스템 패키지:
#   - poppler-utils: pdf2image가 PDF 페이지를 이미지로 렌더링할 때 필요 (스캔 PDF VLM 폴백 경로)
#   - fonts-noto-cjk: PDF 안에 한글 폰트가 임베드 안 돼 있을 때 렌더링 깨짐 방지
#   - default-jre-headless: opendataloader-pdf(ODL)가 Java 11+ 런타임을 요구
# playwright는 아래에서 --with-deps로 자체 시스템 의존성을 설치하므로 여기서는 PDF 쪽만 챙긴다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        fonts-noto-cjk \
        default-jre-headless \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# playwright 브라우저 + 시스템 의존성 설치 (크롬리움만)
RUN python -m playwright install --with-deps chromium

# 앱 소스 복사. 기본 이미지는 Playwright·문서 변환이 필요한 ARQ 워커용이다.
COPY . .

# ARQ 워커 실행
CMD ["arq", "workers.arq_worker.WorkerSettings"]
