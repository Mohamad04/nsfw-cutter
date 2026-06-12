import re

import pycountry


LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}$")
EXTERNAL_SUBTITLE_FLAG_TOKENS = {"cc", "forced", "sdh"}


def resolve_language_name(raw_code: str | None) -> str | None:
    code = _clean_code(raw_code)
    if not code:
        return None

    language = _exact_language(code)
    if language is not None:
        return language.name

    try:
        return pycountry.languages.lookup(code).name
    except LookupError:
        return None


def resolve_external_language_token(raw_token: str | None) -> tuple[str | None, str | None]:
    code = _clean_code(raw_token)
    if (
        not code
        or code in EXTERNAL_SUBTITLE_FLAG_TOKENS
        or LANGUAGE_CODE_PATTERN.fullmatch(code) is None
    ):
        return None, None

    language_name = resolve_language_name(code)
    if language_name is None:
        return None, None
    return code, language_name


def _clean_code(raw_code: str | None) -> str | None:
    if raw_code is None:
        return None

    code = raw_code.strip().casefold()
    return code or None


def _exact_language(code: str):
    if len(code) == 2:
        return pycountry.languages.get(alpha_2=code)
    if len(code) == 3:
        return pycountry.languages.get(alpha_3=code)
    return None
