"""Resolve phone-share URLs to a page, file, archive, or not-found response."""
from urllib.parse import unquote


def resolve_request_path(request_target, token, paths):
    """Return (action, path index) using the phone sharing route contract."""
    decoded = unquote(request_target)
    prefix = f'/{token}'
    if decoded != prefix and not decoded.startswith(prefix + '/'):
        return 'not-found', None
    remainder = decoded[len(token) + 1:].strip('/')
    if remainder == '' and not (len(paths) == 1 and paths[0].is_file()):
        return 'page', None
    if remainder == '' or remainder.startswith('f/'):
        try:
            index = 0 if remainder == '' else int(remainder[2:])
            selected = paths[index]
        except (ValueError, IndexError):
            return 'not-found', None
        return ('zip' if selected.is_dir() else 'file'), index
    if remainder == 'all.zip':
        return 'archive', None
    return 'not-found', None
