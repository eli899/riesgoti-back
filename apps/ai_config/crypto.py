import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

IV_BYTES = 12
TAG_BYTES = 16


class EnvelopeCryptoService:
    """
    Cifrado autenticado AES-256-GCM con llave maestra de 32 bytes.
    Formato de salida: Base64(IV_12B || AuthTag_16B || Ciphertext).
    Nota: cryptography AESGCM.encrypt(iv, plaintext, None) devuelve (Ciphertext || AuthTag_16B),
    por lo que extraemos los últimos 16 bytes como AuthTag para respetar el contrato binario.
    """

    @staticmethod
    def _get_master_key() -> bytes:
        key = settings.RIESGOTI_MASTER_KEY_BYTES
        if len(key) != 32:
            raise ValueError('RIESGOTI_MASTER_KEY debe tener exactamente 32 bytes.')
        return key

    @classmethod
    def mask_api_key(cls, raw_key: str) -> str:
        clean = raw_key.strip()
        if len(clean) <= 8:
            return '****' + clean[-2:]
        return f'{clean[:6]}...{clean[-4:]}'

    @classmethod
    def encrypt_api_key(cls, raw_key: str) -> tuple[str, str]:
        if not raw_key or not raw_key.strip():
            raise ValueError('La API Key no puede estar vacía.')
        clean_key = raw_key.strip()
        aesgcm = AESGCM(cls._get_master_key())
        iv = os.urandom(IV_BYTES)
        ct_with_tag = aesgcm.encrypt(iv, clean_key.encode('utf-8'), None)
        ciphertext = ct_with_tag[:-TAG_BYTES]
        auth_tag = ct_with_tag[-TAG_BYTES:]
        payload_b64 = base64.b64encode(iv + auth_tag + ciphertext).decode('ascii')
        return payload_b64, cls.mask_api_key(clean_key)

    @classmethod
    def decrypt_api_key(cls, payload_b64: str) -> str:
        raw = base64.b64decode(payload_b64)
        if len(raw) <= IV_BYTES + TAG_BYTES:
            raise ValueError('Payload cifrado corrupto o truncado.')
        iv = raw[:IV_BYTES]
        auth_tag = raw[IV_BYTES:IV_BYTES + TAG_BYTES]
        ciphertext = raw[IV_BYTES + TAG_BYTES:]
        aesgcm = AESGCM(cls._get_master_key())
        plaintext = aesgcm.decrypt(iv, ciphertext + auth_tag, None)
        return plaintext.decode('utf-8')
