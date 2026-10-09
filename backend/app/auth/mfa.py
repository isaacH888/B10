"""Application TOTP for federated administrators; counters are persisted atomically."""

import hmac
import re

import pyotp


def new_secret():
    return pyotp.random_base32()


def provisioning_uri(secret, identity_id):
    return pyotp.TOTP(secret).provisioning_uri(
        name="Administrator " + identity_id, issuer_name="Popssibilities admin Google")


def matching_counter(secret, code, now):
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        return None
    totp = pyotp.TOTP(secret)
    # Accept one adjacent 30-second interval for clock drift. The database
    # requires a strictly increasing counter shared by all concurrent logins.
    for counter in range(max(0, now // 30 - 1), now // 30 + 2):
        if hmac.compare_digest(totp.at(counter * 30), code):
            return counter
    return None
