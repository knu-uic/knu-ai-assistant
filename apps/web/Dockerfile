# 2-stage: node로 빌드 → caddy로 정적 파일 서빙.
# 1단계에서 dist/만 만들고, 2단계 caddy 이미지엔 빌드 결과물만 남겨 작게 유지.
FROM node:20-alpine AS build
WORKDIR /app
# 의존성 레이어 캐시: lockfile만 먼저 복사해 npm ci.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build      # → dist/

FROM caddy:2-alpine
# 빌드 산출물 + 설정만 이미지에 굽는다.
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 80
# caddy:2-alpine 기본 CMD가 /etc/caddy/Caddyfile로 실행.
