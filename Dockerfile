# 1. 베이스 이미지 설정
FROM python:3.11-slim

# 2. 필수 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 생성 및 설정
WORKDIR /app

# 4. 환경 변수 설정
# Python이 .pyc 파일을 생성하지 않도록 설정
ENV PYTHONDONTWRITEBYTECODE=1
# 로그가 버퍼링 없이 즉시 출력되도록 설정 (디버깅 용이)
ENV PYTHONUNBUFFERED=1

# 5. 종속성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. 프로젝트 코드 복사
COPY . .

# 7. 정적 파일 수집
RUN python manage.py collectstatic --noinput

# 8. 포트 노출
EXPOSE 8000

# 9. Gunicorn을 이용한 서버 실행
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "config.wsgi:application"]
