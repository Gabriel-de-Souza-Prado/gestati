from collections import defaultdict
from dataclasses import asdict
import json
import uuid

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction

from cadastros.models import CategoriaAtivo, Departamento, Fornecedor
from core.perfis import PerfilConfiguracao as Perfil
from estoque.models import Componente
from estoque.services import registrar_saida_intervencao

from .composicao import DO_ESTOQUE, normalizar_itens_composicao, validar_composicao_completa
from .models import Ativo, ComponenteInstalado, IntervencaoComponente
from .perfis import normalizar_especificacoes, normalizar_extras


CAMPOS_ATIVO = (
    "dti", "patrimonio", "numero_serie", "nome", "modelo", "categoria_id", "departamento_id",
    "fornecedor_id", "data_aquisicao", "valor_aquisicao", "garantia", "inicio_garantia",
    "fim_garantia", "situacao", "observacoes",
)


def _referencia(modelo, identificador, campo):
    try:
        return modelo.objects.select_for_update().get(pk=identificador)
    except (modelo.DoesNotExist, ValueError, TypeError):
        raise ValidationError({campo: "Selecione um cadastro válido."}) from None


def _preparar_dados(dados, categoria, especificacoes, extras):
    if set(dados) - set(CAMPOS_ATIVO):
        raise ValidationError("Foram enviados campos que não pertencem ao cadastro do ativo.")
    valores = dict(dados)
    valores.setdefault("nome", f"{categoria.nome} {valores.get('modelo', '')}".strip()[:160])
    valores["especificacoes"] = normalizar_especificacoes(categoria.perfil_configuracao, especificacoes)
    valores["extras"] = normalizar_extras(categoria.perfil_configuracao, extras)
    return valores


def _erro_integridade(erro):
    if getattr(erro.__cause__, "sqlstate", None) != "23505":
        raise erro
    restricao = getattr(getattr(erro.__cause__, "diag", None), "constraint_name", "") or ""
    if "patrimonio" in restricao:
        return ValidationError({"patrimonio": "Já existe um ativo com esse patrimônio."})
    return ValidationError({"dti": "Já existe um ativo com esse DTI. Confira o cadastro existente."})


def _conferir_cadastro(existente, payload):
    if existente.dados_cadastro != payload:
        raise ValidationError("Esta confirmação já foi usada com outros dados. Abra um novo cadastro para registrar outro ativo.")
    return existente, False


def cadastrar_ativo(*, dados, itens, especificacoes, extras, usuario, chave_confirmacao):
    if not getattr(usuario, "pk", None) or not usuario.is_active:
        raise ValidationError("O cadastro exige usuário ativo da TI.")
    try:
        chave = uuid.UUID(str(chave_confirmacao))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Confirmação inválida. Reabra o cadastro.") from None
    itens = normalizar_itens_composicao(itens)
    payload = None
    try:
        with transaction.atomic():
            # A ordem é sempre componentes por PK, depois cadastros de apoio.
            # Entradas e saídas também bloqueiam componente antes de fornecedor.
            ids = sorted({item.componente_id for item in itens})
            componentes = {c.pk: c for c in Componente.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
            if set(componentes) != set(ids):
                raise ValidationError("Um dos componentes não existe mais. Confira a composição.")
            categoria = _referencia(CategoriaAtivo, dados.get("categoria_id"), "categoria")
            departamento = _referencia(Departamento, dados.get("departamento_id"), "departamento")
            fornecedor = _referencia(Fornecedor, dados["fornecedor_id"], "fornecedor") if dados.get("fornecedor_id") else None
            valores = _preparar_dados(dados, categoria, especificacoes, extras)
            ativo = Ativo(**valores, criado_por=usuario, chave_cadastro=chave, dados_cadastro={"preparando": True})
            ativo.full_clean(validate_unique=False)
            payload = json.loads(json.dumps({
                "dados": {campo: getattr(ativo, campo) for campo in CAMPOS_ATIVO},
                "especificacoes": ativo.especificacoes, "extras": ativo.extras,
                "itens": [asdict(item) for item in itens], "usuario": usuario.pk,
            }, cls=DjangoJSONEncoder))
            existente = Ativo.objects.filter(chave_cadastro=chave).first()
            if existente:
                return _conferir_cadastro(existente, payload)
            for registro, campo in ((categoria, "categoria"), (departamento, "departamento"), (fornecedor, "fornecedor")):
                if registro and not registro.ativo:
                    raise ValidationError({campo: "Selecione um cadastro ativo."})
            if any(not componente.ativo for componente in componentes.values()):
                raise ValidationError("A composição contém componente inativo. Selecione uma especificação ativa.")
            validar_composicao_completa(categoria.perfil_configuracao, componentes.values())
            if ativo.situacao not in (Ativo.Situacao.EM_USO, Ativo.Situacao.RESERVA):
                raise ValidationError({"situacao": "No cadastro inicial, escolha Em uso ou Em reserva."})
            ativo.dados_cadastro = payload
            ativo.full_clean()
            ativo.save()
            totais = defaultdict(int)
            for item in itens:
                totais[item.componente_id] += item.quantidade
            for componente_id, quantidade in sorted(totais.items()):
                ComponenteInstalado.objects.create(ativo=ativo, componente=componentes[componente_id], quantidade=quantidade)
            for item in itens:
                evento = IntervencaoComponente.objects.create(
                    ativo=ativo, componente=componentes[item.componente_id], quantidade=item.quantidade,
                    origem=item.origem, operacao=chave, registrado_por=usuario,
                    nome_componente=componentes[item.componente_id].nome, dti_ativo=ativo.dti,
                )
                if item.origem == DO_ESTOQUE:
                    registrar_saida_intervencao(intervencao=evento, usuario=usuario)
            return ativo, True
    except IntegrityError as erro:
        if payload is not None and getattr(erro.__cause__, "sqlstate", None) == "23505":
            existente = Ativo.objects.filter(chave_cadastro=chave).first()
            if existente:
                return _conferir_cadastro(existente, payload)
        raise _erro_integridade(erro) from None
    except ValidationError:
        if payload is not None:
            existente = Ativo.objects.filter(chave_cadastro=chave).first()
            if existente:
                return _conferir_cadastro(existente, payload)
        raise


def editar_ativo(*, ativo_id, dados, especificacoes, extras, versao):
    try:
        with transaction.atomic():
            return _editar_ativo(ativo_id=ativo_id, dados=dados, especificacoes=especificacoes, extras=extras, versao=versao)
    except IntegrityError as erro:
        raise _erro_integridade(erro) from None


@transaction.atomic
def editar_dados_computador(*, ativo_id, especificacoes, versao, usuario):
    """Alteração descritiva; não instala, retira ou movimenta componentes."""
    from core.perfis import PerfilConfiguracao as Perfil
    from .perfis import normalizar_especificacoes
    if not getattr(usuario, "pk", None) or not usuario.is_active:
        raise ValidationError("Esta alteração exige usuário ativo da TI.")
    ativo = Ativo.objects.select_for_update().select_related("categoria").get(pk=ativo_id)
    if str(ativo.versao) != str(versao):
        raise ValidationError("O ativo mudou. Reabra a configuração para conferir os dados atuais.")
    if ativo.categoria.perfil_configuracao not in (Perfil.COMPUTADOR, Perfil.NOTEBOOK):
        raise ValidationError("Nome na rede e sistema operacional pertencem a computadores e notebooks.")
    dados = normalizar_especificacoes(ativo.categoria.perfil_configuracao, especificacoes)
    campos = {"hostname", "sistema_operacional"}
    ativo.especificacoes = {**{k: v for k, v in ativo.especificacoes.items() if k not in campos}, **dados}
    ativo.versao += 1
    ativo.full_clean()
    ativo.save(update_fields=["especificacoes", "versao", "atualizado_em"])
    return ativo


def _editar_ativo(*, ativo_id, dados, especificacoes, extras, versao):
    ativo = Ativo.objects.select_for_update().get(pk=ativo_id)
    if str(ativo.versao) != str(versao):
        raise ValidationError("Este ativo foi alterado por outra pessoa. Reabra a edição para conferir os dados atuais.")
    categoria = _referencia(CategoriaAtivo, dados.get("categoria_id"), "categoria")
    departamento = _referencia(Departamento, dados.get("departamento_id"), "departamento")
    fornecedor = _referencia(Fornecedor, dados["fornecedor_id"], "fornecedor") if dados.get("fornecedor_id") else None
    for registro, campo in ((categoria, "categoria"), (departamento, "departamento"), (fornecedor, "fornecedor")):
        if registro and not registro.ativo and registro.pk != getattr(ativo, f"{campo}_id"):
            raise ValidationError({campo: "Selecione um cadastro ativo."})
    if departamento.pk != ativo.departamento_id:
        raise ValidationError({"departamento": "A mudança de departamento deve ser registrada como transferência, preservando o histórico."})
    if dados.get("situacao", ativo.situacao) != ativo.situacao and (ativo.situacao not in (Ativo.Situacao.EM_USO, Ativo.Situacao.RESERVA) or dados["situacao"] not in (Ativo.Situacao.EM_USO, Ativo.Situacao.RESERVA)):
        raise ValidationError({"situacao": "Esta mudança deve ocorrer pelo fluxo de atendimento ou baixa."})
    if categoria.pk != ativo.categoria_id:
        validar_composicao_completa(categoria.perfil_configuracao, [linha.componente for linha in ativo.componentes_instalados.select_related("componente")])
    valores = _preparar_dados({"nome": ativo.nome, **dados}, categoria, especificacoes, extras)
    for campo, valor in valores.items():
        setattr(ativo, campo, valor)
    ativo.versao += 1
    ativo.full_clean()
    ativo.save()
    return ativo
