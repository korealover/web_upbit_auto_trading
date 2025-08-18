#!/bin/bash
# backup_users_db_compressed.sh

# 설정
DB_PATH="/data/web/blrr/database/users.db"
BACKUP_DIR="/data/backups/db"
DATE=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="users_${DATE}.db.gz"

# 백업 디렉토리 생성
mkdir -p $BACKUP_DIR

if [ -f "$DB_PATH" ]; then
    # 데이터베이스를 압축하여 백업
    gzip -c "$DB_PATH" > "$BACKUP_DIR/$BACKUP_FILE"

    if [ $? -eq 0 ]; then
        echo "$(date): 압축 백업 완료 - $BACKUP_FILE" >> "$BACKUP_DIR/backup.log"

        # 30일 이전 백업 파일 삭제
        find $BACKUP_DIR -name "users_*.db.gz" -type f -mtime +30 -delete
    else
        echo "$(date): 오류 - 압축 백업 실패" >> "$BACKUP_DIR/backup.log"
    fi
else
    echo "$(date): 오류 - 데이터베이스 파일을 찾을 수 없습니다: $DB_PATH" >> "$BACKUP_DIR/backup.log"
fi