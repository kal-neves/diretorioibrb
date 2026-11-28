import re

import phonenumbers
from django.core.exceptions import ValidationError


def normalize_phone(value, country=None, *, mobile_only=False):
    value = value.strip()
    country = country.upper() if country else None
    if country and country not in phonenumbers.SUPPORTED_REGIONS:
        raise ValidationError("Selecione um país válido.", code="invalid_country")
    if not re.fullmatch(r"\+?[0-9\s().-]+", value):
        raise ValidationError("Informe um telefone válido, sem ramal.", code="invalid_phone")
    if not value.startswith("+") and not country:
        raise ValidationError("Selecione o país do telefone.", code="country_required")
    try:
        number = phonenumbers.parse(value, country)
    except phonenumbers.NumberParseException:
        raise ValidationError("Informe um telefone válido.", code="invalid_phone") from None
    if not phonenumbers.is_valid_number(number):
        raise ValidationError("Confira o telefone e o código de área.", code="invalid_phone")
    regions = [region for region in phonenumbers.region_codes_for_country_code(number.country_code)
               if phonenumbers.is_valid_number_for_region(number, region)]
    if country:
        if country not in regions:
            raise ValidationError("O telefone não corresponde ao país selecionado.", code="country_mismatch")
    elif len(regions) != 1:
        raise ValidationError("Confirme o país do telefone.", code="country_required")
    if mobile_only and phonenumbers.number_type(number) not in {
        phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
    }:
        raise ValidationError("Informe um número de celular.", code="mobile_required")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
