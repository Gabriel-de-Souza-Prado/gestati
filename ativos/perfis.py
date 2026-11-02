from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from core.normalizacao import normalizar_identificador, padronizar_espacos
from core.perfis import PerfilConfiguracao as Perfil


# (chave, rótulo, tipo). Campos específicos são opcionais nesta primeira versão;
# PCs/notebooks exigem a composição completa no serviço, independentemente destes.
CAMPOS_PERFIL = {
    Perfil.GENERICO: (),
    Perfil.COMPUTADOR: (("hostname", "Nome do computador na rede", "texto"), ("sistema_operacional", "Sistema operacional", "texto")),
    Perfil.NOTEBOOK: (("hostname", "Nome do notebook na rede", "texto"), ("sistema_operacional", "Sistema operacional", "texto")),
    Perfil.MONITOR: (("tamanho_polegadas", "Tamanho em polegadas", "decimal"), ("resolucao", "Resolução", "texto")),
    Perfil.NOBREAK: (("potencia_va", "Potência em VA", "inteiro"), ("tensao", "Tensão de entrada/saída", "texto")),
    Perfil.IMPRESSORA: (("tecnologia", "Tecnologia de impressão", "texto"), ("conexao", "Conexão", "texto")),
    Perfil.SWITCH: (("portas", "Quantidade de portas", "inteiro"), ("velocidade", "Velocidade das portas", "texto"), ("gerenciavel", "Gerenciável", "sim_nao")),
}


def normalizar_especificacoes(perfil, dados):
    if perfil not in CAMPOS_PERFIL or not isinstance(dados, dict):
        raise ValidationError("Perfil ou especificações inválidas.")
    permitidas = {chave for chave, _, _ in CAMPOS_PERFIL[perfil]}
    if set(dados) - permitidas:
        raise ValidationError("As especificações contêm campos que não pertencem ao perfil selecionado.")
    resultado = {}
    for chave, rotulo, tipo in CAMPOS_PERFIL[perfil]:
        valor = dados.get(chave)
        if valor is None or valor == "":
            continue
        if tipo == "texto":
            if not isinstance(valor, str) or len(valor) > 160:
                raise ValidationError(f"{rotulo}: informe um texto com até 160 caracteres.")
            valor = padronizar_espacos(valor)
        elif tipo == "inteiro":
            if isinstance(valor, bool) or not str(valor).isascii() or not str(valor).isdigit() or not 1 <= int(valor) <= 2147483647:
                raise ValidationError(f"{rotulo}: informe um inteiro positivo.")
            valor = int(valor)
        elif tipo == "decimal":
            try:
                valor = Decimal(str(valor).replace(",", "."))
                if not valor.is_finite() or not 0 < valor <= Decimal("9999999.99") or valor != valor.quantize(Decimal("0.01")):
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                raise ValidationError(f"{rotulo}: informe um número positivo com até duas casas decimais.") from None
            valor = format(valor.normalize(), "f")
        elif tipo == "sim_nao" and valor not in ("sim", "nao"):
            raise ValidationError(f"{rotulo}: selecione Sim ou Não.")
        if valor != "":
            resultado[chave] = valor
    return resultado


def normalizar_extras(perfil, extras):
    if not isinstance(extras, list) or len(extras) > 30:
        raise ValidationError("Informe até 30 informações extras.")
    if extras and perfil != Perfil.GENERICO:
        raise ValidationError("Informações extras são usadas no perfil Genérico.")
    vistos, resultado = set(), []
    reservadas = {"dti", "patrimonio", "numero de serie", "modelo", "departamento", "garantia", "estoque", "ram total"}
    for item in extras:
        if not isinstance(item, dict) or set(item) != {"campo", "valor"} or not all(isinstance(v, str) for v in item.values()):
            raise ValidationError("Cada informação extra deve ter campo e valor em texto.")
        campo, valor = padronizar_espacos(item["campo"]), item["valor"].strip()
        chave = normalizar_identificador(campo)
        if not campo or not valor or len(campo) > 80 or len(valor) > 500:
            raise ValidationError("Preencha campo (até 80 caracteres) e valor (até 500) nas informações extras.")
        if chave in vistos or chave in reservadas:
            raise ValidationError("Não repita campos extras nem substitua dados gerais do ativo por informações extras.")
        vistos.add(chave)
        resultado.append({"campo": campo, "valor": valor})
    return sorted(resultado, key=lambda item: normalizar_identificador(item["campo"]))
