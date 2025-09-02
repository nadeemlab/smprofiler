
from os import environ as os_environ
from json import loads as json_loads
from base64 import urlsafe_b64decode

from requests import get as requests_get  # type: ignore
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization import PublicFormat

def base64_to_int(string: str) -> int:
    b64 = urlsafe_b64decode(bytes(string.encode('ascii')) + b'==')
    return int(''.join([f'{b:02x}' for b in b64]), 16)

def jwks_to_pem(jwks: dict) -> str:
    e = jwks['keys'][0]['e']
    n = jwks['keys'][0]['n']
    numbers = RSAPublicNumbers(base64_to_int(e), base64_to_int(n))
    public_key = numbers.public_key(backend=default_backend())
    return public_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo
    ).decode('ascii')

def pem_from_url(url: str) -> str:
    k = 'ORCID_JWKS_PAYLOAD'
    if k in os_environ:
        jwk = json_loads(os_environ[k])
    else:
        jwk = requests_get(url=url).json()
    return jwks_to_pem(jwk)
