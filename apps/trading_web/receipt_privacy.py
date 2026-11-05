"""Strip authentication material before persisting broker evidence."""
import re

_LABEL = r'(?:api[_-]?key|api[_-]?secret|client[_-]?secret|access[_-]?token|refresh[_-]?token|password)'
_ASSIGNMENT = re.compile(r'(?i)(' + _LABEL + r'[\"\']?\s*[=:]\s*)(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s&,;]+)')
_BEARER = re.compile(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+')
_PRIVATE_KEY = re.compile(r'-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----.*?-----END (?:[A-Z ]+)?PRIVATE KEY-----', re.S)


def sensitive_key(key):
    name = re.sub(r'[^a-z0-9]', '', str(key).lower())
    return (any(part in name for part in ('password', 'secret', 'apikey'))
            or name.endswith('token')
            or name in {'authorization', 'proxyauthorization', 'cookie', 'setcookie',
                        'headers', 'requestheaders', 'responseheaders', 'keyid', 'credentials',
                        'username', 'login', 'loginname', 'privatekey', 'sshprivatekey',
                        'signingkey', 'sessionid', 'sessionkey', 'authentication'})


def clean_receipt(value):
    """Keep business evidence; drop credential keys and redact labelled secrets."""
    if isinstance(value, dict):
        return {key: clean_receipt(item) for key, item in value.items() if not sensitive_key(key)}
    if isinstance(value, (list, tuple)):
        return [clean_receipt(item) for item in value]
    if isinstance(value, str):
        value = _PRIVATE_KEY.sub('[REDACTED PRIVATE KEY]', value)
        value = _ASSIGNMENT.sub(r'\1[REDACTED]', value)
        return _BEARER.sub(r'\1 [REDACTED]', value)
    return value
