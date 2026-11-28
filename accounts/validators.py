from django.core.exceptions import ValidationError


class PasswordPolicy:
    def validate(self, password, user=None):
        if len(password) < 8 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            raise ValidationError(self.get_help_text(), code="password_policy")

    def get_help_text(self):
        return "Use pelo menos oito caracteres, incluindo uma letra e um número."
