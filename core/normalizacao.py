import unicodedata


def padronizar_espacos(valor):
    return " ".join((valor or "").split())


def normalizar_identificador(valor):
    """Chave de comparação sem alterar os acentos do nome apresentado."""
    texto = unicodedata.normalize("NFKD", padronizar_espacos(valor))
    return "".join(c for c in texto if not unicodedata.combining(c)).casefold()
