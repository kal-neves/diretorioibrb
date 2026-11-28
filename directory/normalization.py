import unicodedata


def normalize_name(value):
    return "".join(character for character in unicodedata.normalize("NFD", value.strip().casefold())
                   if not unicodedata.combining(character))
