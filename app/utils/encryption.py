import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import logging

logger = logging.getLogger(__name__)


class EncryptionService:
    """API 키 암호화/복호화 서비스"""

    def __init__(self, encryption_key=None):
        """
        암호화 서비스 초기화

        Args:
            encryption_key: 암호화 키 (없으면 환경변수에서 가져옴)
        """
        self.encryption_key = encryption_key or os.environ.get('ENCRYPTION_KEY')
        if not self.encryption_key:
            raise ValueError("ENCRYPTION_KEY 환경변수가 설정되지 않았습니다.")

        self.fernet = Fernet(self._derive_key(self.encryption_key))

    def _derive_key(self, password: str) -> bytes:
        """비밀번호로부터 암호화 키 생성"""
        password_bytes = password.encode()
        salt = b'upbit_trading_salt'  # 실제 운영에서는 랜덤 salt 사용 권장

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password_bytes))
        return key

    def encrypt(self, plaintext: str) -> str:
        """문자열 암호화"""
        if not plaintext:
            return plaintext

        try:
            encrypted_data = self.fernet.encrypt(plaintext.encode())
            return base64.urlsafe_b64encode(encrypted_data).decode()
        except Exception as e:
            logger.error(f"암호화 실패: {str(e)}")
            raise

    def decrypt(self, encrypted_text: str) -> str:
        """문자열 복호화"""
        if not encrypted_text:
            return encrypted_text

        try:
            encrypted_data = base64.urlsafe_b64decode(encrypted_text.encode())
            decrypted_data = self.fernet.decrypt(encrypted_data)
            return decrypted_data.decode()
        except Exception as e:
            logger.error(f"복호화 실패: {str(e)}")
            raise


# 전역 암호화 서비스 인스턴스
encryption_service = EncryptionService()