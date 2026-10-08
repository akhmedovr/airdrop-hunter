import subprocess
import sys
from pathlib import Path

from src.core.logger import get_logger

log = get_logger(__name__)

PASSWORD_FILE = Path.home() / ".backup_pass"

def encrypt_file(input_path: str, output_path: str) -> bool:
    """
    Шифрует файл через openssl AES-256-CBC + PBKDF2.
    Возвращает True если ок.
    """
    if not PASSWORD_FILE.exists():
        log.error(f"Файл пароля не найден: {PASSWORD_FILE}")
        return False

    password = PASSWORD_FILE.read_text().strip()
    if not password:
        log.error("Пароль пустой")
        return False

    try:
        result = subprocess.run(
            [
                "openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
                "-salt", "-in", input_path, "-out", output_path,
                "-pass", "fd:0",
            ],
            input=password.encode(),
            capture_output=True,
            timeout=60,
        )
    except Exception as e:
        log.exception(f"Ошибка запуска openssl: {e}")
        return False

    if result.returncode != 0:
        log.error(f"openssl вернул ошибку: {result.stderr.decode()[:200]}")
        return False

    log.success(f"Зашифровано: {output_path}")
    return True

def decrypt_file(input_path: str, output_path: str) -> bool:
    """Расшифровывает файл. Для восстановления из бэкапа."""
    if not PASSWORD_FILE.exists():
        log.error(f"Файл пароля не найден: {PASSWORD_FILE}")
        return False

    password = PASSWORD_FILE.read_text().strip()

    try:
        result = subprocess.run(
            [
                "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
                "-in", input_path, "-out", output_path,
                "-pass", "fd:0",
            ],
            input=password.encode(),
            capture_output=True,
            timeout=60,
        )
    except Exception as e:
        log.exception(f"Ошибка: {e}")
        return False

    if result.returncode != 0:
        log.error(f"openssl: {result.stderr.decode()[:200]}")
        return False

    log.success(f"Расшифровано: {output_path}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python -m src.core.backup_encrypt enc <input> <output>")
        sys.exit(1)
    mode, inp, out = sys.argv[1], sys.argv[2], sys.argv[3]
    if mode == "enc":
        ok = encrypt_file(inp, out)
    elif mode == "dec":
        ok = decrypt_file(inp, out)
    else:
        ok = False
    sys.exit(0 if ok else 1)
