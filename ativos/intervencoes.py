"""Aplicação física compartilhada por OS e alteração avulsa.

Chamador mantém transação e locks componentes por PK → ativo → OS, quando houver.
"""
from collections import defaultdict
from django.core.exceptions import ValidationError
from estoque.services import registrar_saida_intervencao, registrar_retorno_intervencao
from .models import ComponenteInstalado, IntervencaoComponente


def aplicar_itens_fisicos(*, ativo, itens, componentes, chave, usuario, registro_os=None, alteracao=None, baixa=None):
    instalados = {i.componente_id: i for i in ativo.componentes_instalados.all()}
    retiradas = defaultdict(int)
    for item in itens:
        if item["acao"] != "instalar":
            retiradas[item["componente_id"]] += item["quantidade"]
    for componente_id, quantidade in retiradas.items():
        if componente_id not in instalados or quantidade > instalados[componente_id].quantidade:
            raise ValidationError(f'Não há essa quantidade instalada de "{componentes[componente_id].nome}". Confira a configuração atual.')
    # Retirar antes de instalar permite trocar uma peça por outra de mesma especificação.
    for item in sorted(itens, key=lambda i: i["acao"] == "instalar"):
        componente_id, quantidade = item["componente_id"], item["quantidade"]
        componente = componentes[componente_id]
        instalar = item["acao"] == "instalar"
        origem = "estoque" if instalar else ("retorno_estoque" if item["acao"] == "retirar_reutilizar" else "sem_retorno")
        linha = instalados.get(componente_id)
        nova_quantidade = (linha.quantidade if linha else 0) + (quantidade if instalar else -quantidade)
        if nova_quantidade >= 2**31:
            raise ValidationError("Quantidade instalada acima do limite permitido.")
        evento = IntervencaoComponente.objects.create(
            ativo=ativo, componente=componente, quantidade=quantidade, operacao=chave,
            origem=origem, registro_os=registro_os, alteracao=alteracao, baixa=baixa, registrado_por=usuario,
            nome_componente=componente.nome, dti_ativo=ativo.dti,
        )
        if instalar:
            registrar_saida_intervencao(intervencao=evento, usuario=usuario)
        elif origem == "retorno_estoque":
            registrar_retorno_intervencao(intervencao=evento, usuario=usuario)
        if nova_quantidade:
            if linha:
                linha.quantidade = nova_quantidade
                linha.save(update_fields=["quantidade"])
            else:
                linha = ComponenteInstalado.objects.create(ativo=ativo, componente=componente, quantidade=nova_quantidade)
                instalados[componente_id] = linha
        elif linha:
            linha.delete()
            instalados.pop(componente_id)
