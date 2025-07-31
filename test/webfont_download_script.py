import os
import requests

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

# Font Awesome 웹폰트 다운로드를 위한 추가 스크립트
webfonts_to_download = {
    'fa-solid-900.woff2': 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-solid-900.woff2',
    'fa-regular-400.woff2': 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-regular-400.woff2',
    'fa-brands-400.woff2': 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/webfonts/fa-brands-400.woff2'
}

# webfonts 폴더 생성
os.makedirs('../app/static/webfonts', exist_ok=True)

# 웹폰트 파일 다운로드
for filename, url in webfonts_to_download.items():
    filepath = f'app/static/webfonts/{filename}'
    download_file(url, filepath)