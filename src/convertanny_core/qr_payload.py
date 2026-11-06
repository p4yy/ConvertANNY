"""Interpret QR contents for the result dialog without opening any links."""
import re
from itertools import chain
from urllib.parse import urlsplit


def _wifi_fields(payload):
    # Tokenize separators and escaped characters together so escaped separators
    # are decoded only after the field boundaries have been identified.
    fields = {}
    pieces = []
    for token in chain(re.finditer(r'\\(.)|([^;\\]+)|(;)', payload, re.DOTALL), [None]):
        escaped, plain, separator = token.groups() if token is not None else (None, None, ';')
        if separator:
            key, colon, value = ''.join(pieces).partition(':')
            if colon:
                fields[key.upper()] = value
            pieces.clear()
        else:
            pieces.append(escaped if escaped is not None else plain)
    return fields


def interpret_payload(payload, translate=lambda value: value):
    text = payload.strip()
    scheme, colon, body = text.partition(':')
    scheme = scheme.casefold() if colon else ''
    if scheme in ('http', 'https') and body.startswith('//'):
        return translate('Link'), text, [(translate('Website'), urlsplit(text).netloc)], text
    if scheme == 'wifi':
        fields = _wifi_fields(body)
        details = [(translate(label), fields[key]) for key, label in
                   [('S', 'Network'), ('P', 'Password')] if fields.get(key)]
        return translate('Wi-Fi network'), fields.get('S', ''), details, None
    labels = {'mailto': 'Email', 'tel': 'Phone number'}
    if scheme in labels:
        return translate(labels[scheme]), body, [], text
    return translate('Text'), text, [], None
