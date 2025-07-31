import os
import requests
from pathlib import Path

# 다운로드할 파일들 정의
files_to_download = {
    'js': {
        'chart.js': 'https://cdn.jsdelivr.net/npm/chart.js'
    }
}

def create_directories():
    """필요한 디렉토리 생성"""
    os.makedirs('../app/static/css', exist_ok=True)
    os.makedirs('../app/static/js', exist_ok=True)
    os.makedirs('../app/static/images', exist_ok=True)
    print("디렉토리 생성 완료")

def download_file(url, filepath):
    """파일 다운로드"""
    try:
        print(f"다운로드 중: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        with open(filepath, 'wb') as f:
            f.write(response.content)
        
        print(f"저장 완료: {filepath}")
        return True
    except Exception as e:
        print(f"다운로드 실패 {url}: {str(e)}")
        return False

def main():
    """메인 함수"""
    print("정적 파일 다운로드를 시작합니다...")
    
    # 디렉토리 생성
    create_directories()
    
    # 파일 다운로드
    for file_type, files in files_to_download.items():
        print(f"\n=== {file_type.upper()} 파일 다운로드 ===")
        
        for filename, url in files.items():
            filepath = f'app/static/{file_type}/{filename}'
            download_file(url, filepath)
    
    print("\n모든 다운로드가 완료되었습니다!")
    print("\n다음 단계:")
    print("1. base.html에서 CDN 링크를 로컬 파일로 변경")
    print("2. Font Awesome 웹폰트 파일들도 필요시 추가 다운로드")

if __name__ == "__main__":
    main()