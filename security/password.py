import base64
import hashlib
import hmac
import os


PBKDF2_ITERATIONS = 390_000


def _hash_with_pbkdf2(plain_password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _verify_pbkdf2(plain_password: str, password_hash: str) -> bool:
    try:
        _algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def hash_password(plain_password: str) -> str:
    if not plain_password:
        raise ValueError("Password is required")

    try:
        from argon2 import PasswordHasher

        return PasswordHasher().hash(plain_password)
    except ModuleNotFoundError:
        return _hash_with_pbkdf2(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    if not plain_password or not password_hash:
        return False

    if password_hash.startswith("pbkdf2_sha256$"):
        return _verify_pbkdf2(plain_password, password_hash)

    try:
        from argon2 import PasswordHasher
        from argon2.exceptions import VerificationError

        try:
            return PasswordHasher().verify(password_hash, plain_password)
        except VerificationError:
            return False
    except ModuleNotFoundError:
        return False
