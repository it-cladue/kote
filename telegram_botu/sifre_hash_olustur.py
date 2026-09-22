#!/usr/bin/env python3
"""Yonetici parolasini duz metin saklamadan PBKDF2-SHA256 ozetine donusturur."""

import base64
import getpass
import hashlib
import secrets
import sys

ITERATIONS = 600_000
MIN_LENGTH = 14


def main():
    print("Yonetici parolasi bu cihazda ozetlenecek; parola hicbir dosyaya yazilmaz.")
    password = getpass.getpass("Guclu parola: ")
    confirmation = getpass.getpass("Parolayi tekrar girin: ")
    if password != confirmation:
        print("HATA: Parolalar ayni degil.")
        return 1
    if len(password) < MIN_LENGTH:
        print(f"HATA: Parola en az {MIN_LENGTH} karakter olmalidir.")
        return 1
    classes = [
        any(ch.islower() for ch in password),
        any(ch.isupper() for ch in password),
        any(ch.isdigit() for ch in password),
        any(not ch.isalnum() for ch in password),
    ]
    if sum(classes) < 3:
        print("HATA: Buyuk/kucuk harf, rakam ve ozel karakter siniflarindan en az ucunu kullanin.")
        return 1

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    value = "pbkdf2_sha256${}${}${}".format(
        ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )
    print("\nAsagidaki satirin tamamini config.txt icindeki PASSWORD_HASH alanina yapistirin:")
    print("PASSWORD_HASH=" + value)
    print("PASSWORD= alani bos kalmalidir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
