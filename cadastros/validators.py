import re

from django.core.exceptions import ValidationError


def normalizar_cnpj(valor):
    """Valida formato/DVs locais, sem consultar situação cadastral na Receita.

    Regra numérica e alfanumérica: RFB, pergunta 14 do FAQ CNPJ alfanumérico.
    Letras usam ASCII - 48; os dois dígitos verificadores continuam numéricos.
    """
    texto = (valor or "").strip()
    if not texto:
        return None
    padrao = r"[A-Za-z0-9]{12}[0-9]{2}|[A-Za-z0-9]{2}\.[A-Za-z0-9]{3}\.[A-Za-z0-9]{3}/[A-Za-z0-9]{4}-[0-9]{2}"
    if not re.fullmatch(padrao, texto):
        raise ValidationError("Informe um CNPJ com 14 caracteres, com ou sem a máscara padrão.")
    cnpj = re.sub(r"[./-]", "", texto).upper()
    if len(set(cnpj)) == 1:
        raise ValidationError("Informe um CNPJ válido.")
    base = cnpj[:12]
    for pesos in ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2),
                  (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)):
        resto = sum((ord(c) - 48) * peso for c, peso in zip(base, pesos)) % 11
        base += str(0 if resto < 2 else 11 - resto)
    if cnpj != base:
        raise ValidationError("Os dígitos verificadores do CNPJ não conferem. Revise o número.")
    return cnpj
