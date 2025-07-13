#!/bin/bash
# start_gunicorn.sh

# 가상환경 활성화 (경로는 실제 환경에 맞게 수정)
source .venv/bin/activate

# 로그 디렉토리 생성
mkdir -p logs

# Gunicorn 실행
gunicorn -c gunicorn_config.py app:app