from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.perfis import PerfilConfiguracao as Perfil
from estoque.models import Componente
from .composicao import calcular_ram_total_gb
from .forms import AtivoForm, EspecificacoesForm, ExtrasFormSet, FiltroAtivoForm, ItensFormSet, formularios_composicao
from .models import Ativo
from .perfis import CAMPOS_PERFIL
from .selectors import ativos_para_consulta, filtrar_busca_ativos, componentes_instalados_para_consulta
from .services import CAMPOS_ATIVO, cadastrar_ativo, editar_ativo
from .forms_configuracao import AlteracaoForm, EspecificacaoRapidaForm


def _adicionar_erros(form, erro):
    if hasattr(erro, "message_dict"):
        for campo, mensagens in erro.message_dict.items():
            form.add_error(campo if campo in form.fields else None, mensagens)
    else:
        form.add_error(None, erro)


@login_required
@require_http_methods(["GET"])
def ativo_listar(request):
    filtro = FiltroAtivoForm(request.GET)
    ativos = ativos_para_consulta()
    if filtro.is_valid():
        dados = filtro.cleaned_data
        ativos = filtrar_busca_ativos(ativos, dados["q"])
        for campo in ("departamento", "categoria", "situacao"):
            if dados[campo]:
                ativos = ativos.filter(**{campo: dados[campo]})
    else:
        ativos = ativos.none()
    parametros = request.GET.copy()
    parametros.pop("page", None)
    return render(request, "ativos/ativo_lista.html", {"filtro": filtro, "page_obj": Paginator(ativos, 10).get_page(request.GET.get("page")), "filtros_url": parametros.urlencode()})


def _formulario(request, ativo=None):
    post = request.POST if request.method == "POST" else None
    initial = {campo.removesuffix("_id"): getattr(ativo, campo) for campo in CAMPOS_ATIVO if campo != "nome"} if ativo else {}
    if ativo:
        initial["versao"] = ativo.versao
    form = AtivoForm(post, initial=initial, ativo=ativo)
    principal_valido = form.is_valid() if post is not None else False
    categoria = form.cleaned_data.get("categoria") if post is not None else (ativo.categoria if ativo else None)
    perfil = categoria.perfil_configuracao if categoria else Perfil.GENERICO
    computador = perfil in (Perfil.COMPUTADOR, Perfil.NOTEBOOK)
    perfis = [{"codigo": codigo, "rotulo": rotulo, "selecionado": codigo == perfil,
               "form": EspecificacoesForm(post if post is not None and codigo == perfil else None,
                       prefix=f"config-{codigo}", perfil=codigo,
                       initial=ativo.especificacoes if ativo else None)}
              for codigo, rotulo in ((Perfil.COMPUTADOR, "Computador"), (Perfil.NOTEBOOK, "Notebook"))]
    selecionado = next((g["form"] for g in perfis if g["selecionado"]), None)
    legado = ItensFormSet(post, prefix="pecas") if not ativo and post is not None and "pecas-TOTAL_FORMS" in post else None
    grupos = formularios_composicao(post if computador and not legado else None) if not ativo else []
    if post is not None:
        especificacoes_validas = selecionado.is_valid() if selecionado else True
        conjuntos = [legado] if legado is not None else ([g["formset"] for g in grupos] if computador else [])
        itens_validos = all([f.is_valid() for f in conjuntos])
        if principal_valido and especificacoes_validas and itens_validos:
            dados = {campo: form.cleaned_data[campo.removesuffix("_id")].pk if campo.endswith("_id") and form.cleaned_data[campo.removesuffix("_id")] else form.cleaned_data[campo.removesuffix("_id")] for campo in CAMPOS_ATIVO if campo != "nome"}
            mesmas_especificacoes = ativo and perfil == ativo.categoria.perfil_configuracao
            especificacoes = {**(ativo.especificacoes if mesmas_especificacoes else {}), **(selecionado.cleaned_data if selecionado else {})}
            extras = ativo.extras if mesmas_especificacoes else []
            try:
                if ativo:
                    salvo = editar_ativo(ativo_id=ativo.pk, dados=dados, especificacoes=especificacoes, extras=extras, versao=form.cleaned_data["versao"])
                    criado = False
                else:
                    itens = [{"componente_id": l["componente"].pk, "quantidade": l["quantidade"], "origem": l["origem"]} for f in conjuntos for l in f.cleaned_data if l and not l.get("DELETE")]
                    salvo, criado = cadastrar_ativo(dados=dados, itens=itens, especificacoes=especificacoes, extras=[], usuario=request.user, chave_confirmacao=form.cleaned_data["chave_confirmacao"])
            except ValidationError as erro:
                _adicionar_erros(form, erro)
            else:
                messages.success(request, "Ativo cadastrado." if criado else ("Ativo atualizado." if ativo else "Este cadastro já foi confirmado. O estoque não foi consumido novamente."))
                return redirect("ativos:ativo_detalhar", pk=salvo.pk)
    return render(request, "ativos/ativo_form.html", {"form": form, "ativo": ativo, "perfil_selecionado": perfil, "computador": computador,
                  "perfis": perfis, "grupos_composicao": grupos, "legado": legado,
                  "nova_especificacao": EspecificacaoRapidaForm(prefix="nova", use_required_attribute=False)})


@login_required
@require_http_methods(["GET", "POST"])
def ativo_criar(request):
    return _formulario(request)


@login_required
@require_http_methods(["GET", "POST"])
def ativo_editar(request, pk):
    return _formulario(request, get_object_or_404(ativos_para_consulta(), pk=pk))


@login_required
@require_http_methods(["GET"])
def ativo_detalhar(request, pk):
    ativo = get_object_or_404(ativos_para_consulta(), pk=pk)
    instalados = list(componentes_instalados_para_consulta(ativo))
    rotulos = {chave: rotulo for chave, rotulo, _ in CAMPOS_PERFIL[ativo.categoria.perfil_configuracao]}
    especificacoes = [{"campo": rotulos[chave], "valor": {"sim": "Sim", "nao": "Não"}.get(str(valor), valor)} for chave, valor in ativo.especificacoes.items() if chave in rotulos]
    return render(request, "ativos/ativo_detalhe.html", {"ativo": ativo, "computador": ativo.categoria.perfil_configuracao in (Perfil.COMPUTADOR, Perfil.NOTEBOOK), "instalados": instalados, "ram_total": calcular_ram_total_gb([(linha.componente, linha.quantidade) for linha in instalados]), "especificacoes": especificacoes, "intervencoes": ativo.intervencoes.select_related("registrado_por").filter(operacao=ativo.chave_cadastro, registro_os__isnull=True), "ordens": ativo.ordens_servico.all(), "os_aberta": ativo.ordens_servico.exclude(status="encerrada").first(), "em_garantia": ativo.esta_em_garantia(), "emprestimo_atual": next(iter(ativo.emprestimos_em_aberto), None)})


@login_required
@require_http_methods(["GET"])
def catalogo_componentes(request):
    return JsonResponse({"componentes": list(Componente.objects.filter(ativo=True).values("pk", "nome", "tipo", "capacidade"))})


@login_required
@require_http_methods(["POST"])
def especificacao_criar(request):
    from core.normalizacao import normalizar_identificador
    from estoque.services import salvar_componente

    form = EspecificacaoRapidaForm(request.POST, prefix="nova")
    if not form.is_valid():
        return JsonResponse({"erros": form.errors}, status=400)
    dados = form.cleaned_data
    def conferir(existente):
        if not existente.ativo:
            raise ValidationError("Esta especificação já existe e está inativa. Reative-a no catálogo.")
        if any(getattr(existente, c) != dados[c] for c in ("tipo", "capacidade", "unidade_capacidade")):
            raise ValidationError("Esse nome já identifica outra especificação. Informe um nome que diferencie capacidade/tipo.")
        return existente
    try:
        existente = Componente.objects.filter(chave_nome=normalizar_identificador(dados["nome"])).first()
        if existente:
            componente = conferir(existente)
        else:
            try:
                componente = salvar_componente(**dados, acompanhar_estoque=False)
            except ValidationError:
                existente = Componente.objects.filter(chave_nome=normalizar_identificador(dados["nome"])).first()
                if not existente:
                    raise
                componente = conferir(existente)
    except ValidationError as erro:
        return JsonResponse({"erros": erro.messages}, status=400)
    return JsonResponse({"componente": {"pk": componente.pk, "nome": componente.nome, "tipo": componente.tipo, "capacidade": componente.capacidade}})


@login_required
@require_http_methods(["GET", "POST"])
def configuracao_alterar(request, pk):
    from django.core import signing
    from .alteracoes import alterar_configuracao
    from .models import AlteracaoConfiguracao
    from ordens.forms import PecasFormSet

    ativo = get_object_or_404(ativos_para_consulta(), pk=pk)
    if ativo.categoria.perfil_configuracao not in (Perfil.COMPUTADOR, Perfil.NOTEBOOK):
        raise Http404("Configuração disponível somente para computadores e notebooks.")
    post = request.POST if request.method == "POST" else None
    dados_form = EspecificacoesForm(post if post is not None and post.get("acao") == "dados" else None,
        prefix="dados", perfil=ativo.categoria.perfil_configuracao, initial=ativo.especificacoes)
    versao_dados = post.get("versao_dados", "") if post is not None else ativo.versao
    if post is not None and post.get("acao") == "dados":
        if dados_form.is_valid():
            from .services import editar_dados_computador
            try:
                editar_dados_computador(ativo_id=ativo.pk, especificacoes=dados_form.cleaned_data,
                    versao=versao_dados, usuario=request.user)
            except ValidationError as erro:
                _adicionar_erros(dados_form, erro)
            else:
                messages.success(request, "Nome na rede e sistema operacional atualizados.")
                return redirect("ativos:configuracao_alterar", pk=ativo.pk)
        post = None
    erro_confirmacao = None
    if post is not None and "confirmacao" in post:
        try:
            assinado = signing.loads(post["confirmacao"], salt="configuracao-ativo", max_age=1800)
            if assinado["usuario_id"] != request.user.pk or assinado["dados"]["ativo_id"] != ativo.pk:
                raise signing.BadSignature()
            registro, criado = alterar_configuracao(**assinado["dados"], usuario=request.user, previa=assinado["previa"])
        except (signing.BadSignature, KeyError, TypeError):
            erro_confirmacao = "A prévia expirou ou é inválida. Preencha novamente para conferir os saldos atuais."
        except ValidationError as erro:
            erro_confirmacao = " ".join(erro.messages)
        else:
            messages.success(request, "Configuração alterada com registro de origem e estoque." if criado else "Esta alteração já foi confirmada. Nenhuma peça foi movimentada novamente.")
            return redirect("ativos:ativo_detalhar", pk=ativo.pk)
        post = None
    form = AlteracaoForm(post, ativo_id=ativo.pk, initial={"versao": ativo.versao})
    if erro_confirmacao:
        form.cleaned_data = {}
        form.add_error(None, erro_confirmacao)
    tipo = post.get("tipo") if post is not None else "fisica"
    pecas = PecasFormSet(post if tipo == "fisica" else None, prefix="pecas", form_kwargs={"ativo_id": ativo.pk})
    if post is not None:
        valido = form.is_valid()
        pecas_validas = pecas.is_valid() if tipo == "fisica" else True
        if valido and pecas_validas:
            d = form.cleaned_data
            dados = {"ativo_id": ativo.pk, "tipo": d["tipo"], "justificativa": d["justificativa"],
                     "versao": d["versao"], "chave_confirmacao": str(d["chave_confirmacao"]),
                     "intervencao_id": d["intervencao"].pk if d.get("intervencao") else None,
                     "componente_id": d["componente"].pk if d.get("componente") else None,
                     "quantidade": d.get("quantidade"),
                     "itens": [{"componente_id": l["componente"].pk, "quantidade": l["quantidade"], "acao": l["acao"]} for l in pecas.cleaned_data if l and not l.get("DELETE")] if tipo == "fisica" else []}
            try:
                previa, _ = alterar_configuracao(**dados, usuario=request.user)
            except ValidationError as erro:
                _adicionar_erros(form, erro)
            else:
                if isinstance(previa, AlteracaoConfiguracao):
                    return redirect("ativos:ativo_detalhar", pk=ativo.pk)
                token = signing.dumps({"dados": dados, "previa": previa, "usuario_id": request.user.pk}, salt="configuracao-ativo", compress=True)
                return render(request, "ativos/configuracao_previa.html", {"ativo": ativo, "previa": previa, "token": token, "tipo": tipo, "justificativa": d["justificativa"]})
    return render(request, "ativos/configuracao_form.html", {"ativo": ativo, "form": form, "pecas": pecas, "dados_form": dados_form, "versao_dados": versao_dados,
                  "instalados": componentes_instalados_para_consulta(ativo)})
