from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from estoque.models import Componente, MovimentoEstoque
from estoque.selectors import componentes_com_saldo
from estoque.services import registrar_entrada, salvar_componente
from ordens.services import abrir_os
from .alteracoes import alterar_configuracao
from .forms import formularios_composicao
from .models import Ativo, AlteracaoConfiguracao, IntervencaoComponente
from .selectors import ativos_para_consulta, filtrar_busca_ativos
from .services import cadastrar_ativo
from .tests_integracao import preparar_cadastros


class RevisaoAtivosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario, cls.categoria, cls.departamento, cls.componentes = preparar_cadastros()
        cls.outro = salvar_componente(nome="RAM DDR4 16 GB", tipo="ram", capacidade=16, unidade_capacidade="GB")

    def entrada(self, comp, q):
        registrar_entrada(componente_id=comp.pk, quantidade=q, origem="compra", data=timezone.localdate(), usuario=self.usuario, chave_confirmacao=uuid.uuid4())

    def ativo(self, estoque=False, **alteracoes):
        return cadastrar_ativo(dados={"dti":"REV-0010", "modelo":"Dell OptiPlex 5090", "categoria_id":self.categoria.pk, "departamento_id":self.departamento.pk, **alteracoes}, itens=[{"componente_id":c.pk,"quantidade":1,"origem":"estoque" if estoque and c.tipo == "ram" else "no_equipamento"} for c in self.componentes.values()], especificacoes={"hostname":"PC-RH-01"}, extras=[],usuario=self.usuario,chave_confirmacao=uuid.uuid4())[0]

    def dados(self, ativo, **alteracoes):
        return {"ativo_id":ativo.pk,"tipo":"fisica","justificativa":"Demanda de upgrade", "usuario":self.usuario,"chave_confirmacao":uuid.uuid4(),"versao":ativo.versao, "itens":[{"componente_id":self.componentes["ram"].pk,"acao":"instalar","quantidade":1}], **alteracoes}

    def corrigir(self, ativo, **alteracoes):
        original=ativo.intervencoes.get(componente=self.componentes["ram"])
        return self.dados(ativo,tipo="correcao",itens=[],intervencao_id=original.pk,componente_id=self.outro.pk,quantidade=1,**alteracoes)

    def test_busca_unica_modelo_hostname_parcial_e_prioridade_exata(self):
        ativo=self.ativo()
        self.assertEqual(list(filtrar_busca_ativos(ativos_para_consulta(),"rh")),[ativo])
        self.assertEqual(list(filtrar_busca_ativos(ativos_para_consulta(),"dell opti")),[ativo])
        self.client.force_login(self.usuario)
        resposta=self.client.get(reverse("ativos:ativo_listar"),{"q":"rh"})
        self.assertNotIn("identificador",resposta.context["filtro"].fields)
        self.assertContains(resposta,"Dell OptiPlex 5090")

    def test_catalogo_rapido_nao_cria_estoque_e_reutiliza_especificacao(self):
        self.client.force_login(self.usuario)
        dados={"nova-nome":"Processador Novo", "nova-tipo":"processador"}
        url=reverse("ativos:especificacao_criar")
        um=self.client.post(url,dados); dois=self.client.post(url,dados)
        self.assertEqual(um.status_code,200)
        self.assertEqual(um.json()["componente"]["pk"],dois.json()["componente"]["pk"])
        componente=Componente.objects.get(pk=um.json()["componente"]["pk"])
        self.assertFalse(componente.acompanhar_estoque)
        self.assertFalse(componentes_com_saldo().get(pk=componente.pk).estoque_baixo)
        self.assertFalse(MovimentoEstoque.objects.exists())
        stock=self.client.get(reverse("estoque:componente_listar"))
        self.assertNotContains(stock,"Processador Novo")
        catalogo=self.client.get(reverse("estoque:componente_listar"),{"visao":"catalogo"})
        self.assertNotContains(catalogo,"Processador Novo")
        self.assertNotContains(catalogo,"Catálogo completo de especificações")
        self.assertNotIn("acompanhar_estoque", self.client.get(reverse("estoque:componente_criar")).context["form"].fields)
        self.client.post(reverse("estoque:componente_editar", args=[componente.pk]), {"nome":componente.nome,"tipo":componente.tipo,"quantidade_minima":0})
        componente.refresh_from_db()
        self.assertFalse(componente.acompanhar_estoque)
        self.entrada(componente,2)
        componente.refresh_from_db()
        self.assertTrue(componente.acompanhar_estoque)

    def test_catalogo_rapido_rejeita_mesmo_nome_com_capacidade_diferente(self):
        self.client.force_login(self.usuario)
        dados={"nova-nome":self.outro.nome,"nova-tipo":"ram","nova-capacidade":"8","nova-unidade_capacidade":"GB"}
        self.assertEqual(self.client.post(reverse("ativos:especificacao_criar"),dados).status_code,400)

    def test_formulario_simplificado_agrupa_pecas_e_nao_exige_cadastro_rapido(self):
        self.client.force_login(self.usuario)
        resposta=self.client.get(reverse("ativos:ativo_criar"))
        self.assertNotIn("nome",resposta.context["form"].fields)
        self.assertNotContains(resposta,'name="extras-TOTAL_FORMS"')
        self.assertNotContains(resposta,'name="nova-nome" maxlength="160" required')
        grupos=formularios_composicao()
        armazenamento=next(g for g in grupos if g["codigo"]=="armazenamento")
        self.assertEqual(set(armazenamento["formset"].forms[0].fields["componente"].queryset.values_list("tipo",flat=True)),{"ssd"})

    def test_previa_fisica_nao_grava_nada_e_confirma_upgrade_sem_os(self):
        self.entrada(self.componentes["ram"],2)
        ativo=self.ativo()
        dados=self.dados(ativo)
        antes=IntervencaoComponente.objects.count()
        previa,_=alterar_configuracao(**dados)
        self.assertEqual(previa["saldos"][0]["depois"],1)
        self.assertEqual(IntervencaoComponente.objects.count(),antes)
        self.assertFalse(AlteracaoConfiguracao.objects.exists())
        registro,criado=alterar_configuracao(**dados,previa=previa)
        self.assertTrue(criado)
        self.assertFalse(ativo.ordens_servico.exists())
        self.assertEqual(ativo.componentes_instalados.get(componente=self.componentes["ram"]).quantidade,2)
        self.assertEqual(registro.efeitos_estoque[0]["quantidade"],1)

    def test_reenvio_nao_repete_e_dados_diferentes_sao_rejeitados(self):
        self.entrada(self.componentes["ram"],2); ativo=self.ativo(); dados=self.dados(ativo)
        previa,_=alterar_configuracao(**dados)
        um,_=alterar_configuracao(**dados,previa=previa)
        dois,criado=alterar_configuracao(**dados,previa=previa)
        self.assertFalse(criado); self.assertEqual(um.pk,dois.pk)
        with self.assertRaisesMessage(ValidationError,"outros dados"):
            alterar_configuracao(**{**dados,"justificativa":"Outra demanda"},previa=previa)

    def test_saldo_mudou_apos_previa_exige_nova_conferencia(self):
        self.entrada(self.componentes["ram"],2); ativo=self.ativo(); dados=self.dados(ativo)
        previa,_=alterar_configuracao(**dados)
        self.entrada(self.componentes["ram"],1)
        with self.assertRaisesMessage(ValidationError,"mudaram após a prévia"):
            alterar_configuracao(**dados,previa=previa)
        self.assertFalse(AlteracaoConfiguracao.objects.exists())
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo,3)

    def test_previa_falsa_nao_autoriza_mutacao(self):
        self.entrada(self.componentes["ram"],1); ativo=self.ativo()
        with self.assertRaisesMessage(ValidationError,"mudaram após a prévia"):
            alterar_configuracao(**self.dados(ativo),previa={})
        self.assertFalse(AlteracaoConfiguracao.objects.exists())

    def test_correcao_documental_nao_movimenta_estoque(self):
        ativo=self.ativo(); dados=self.corrigir(ativo)
        previa,_=alterar_configuracao(**dados)
        self.assertEqual(previa["movimentos"],[])
        registro,_=alterar_configuracao(**dados,previa=previa)
        self.assertFalse(MovimentoEstoque.objects.exists())
        self.assertTrue(ativo.componentes_instalados.filter(componente=self.outro).exists())
        self.assertEqual(registro.intervencao_corrigida.nome_componente,self.componentes["ram"].nome)

    def test_correcao_de_consumo_compensa_original_e_consume_especificacao_correta(self):
        self.entrada(self.componentes["ram"],2); self.entrada(self.outro,3)
        ativo=self.ativo(estoque=True); dados=self.corrigir(ativo)
        previa,_=alterar_configuracao(**dados)
        self.assertEqual([m["tipo"] for m in previa["movimentos"]],["entrada","saida"])
        registro,_=alterar_configuracao(**dados,previa=previa)
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo,2)
        self.assertEqual(componentes_com_saldo().get(pk=self.outro.pk).saldo,2)
        self.assertEqual(registro.intervencao_corrigida.movimento_estoque.origem,"aplicacao")
        self.assertEqual(MovimentoEstoque.objects.filter(origem="correcao").count(),2)

    def test_correcao_sem_saldo_correto_reverte_compensacao(self):
        self.entrada(self.componentes["ram"],1); ativo=self.ativo(estoque=True)
        with self.assertRaisesMessage(ValidationError,"Estoque insuficiente"):
            alterar_configuracao(**self.corrigir(ativo))
        self.assertFalse(MovimentoEstoque.objects.filter(origem="correcao").exists())
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo,0)
        self.assertTrue(ativo.componentes_instalados.filter(componente=self.componentes["ram"]).exists())

    def test_original_com_intervencoes_posteriores_nao_e_compensado(self):
        self.entrada(self.componentes["ram"],2); ativo=self.ativo(); antigo=self.corrigir(ativo)
        dados=self.dados(ativo); previa,_=alterar_configuracao(**dados)
        alterar_configuracao(**dados,previa=previa); ativo.refresh_from_db()
        with self.assertRaisesMessage(ValidationError,"intervenções posteriores"):
            alterar_configuracao(**{**antigo,"versao":ativo.versao})

    def test_retirada_util_sem_os_volta_ao_estoque_automaticamente(self):
        ativo=self.ativo()
        dados=self.dados(ativo,itens=[{"componente_id":self.componentes["ram"].pk,"acao":"retirar_reutilizar","quantidade":1},{"componente_id":self.outro.pk,"acao":"instalar","quantidade":1}])
        self.entrada(self.outro,1)
        previa,_=alterar_configuracao(**dados); alterar_configuracao(**dados,previa=previa)
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo,1)
        self.assertEqual(MovimentoEstoque.objects.get(origem="retorno_os").intervencao.alteracao.tipo,"fisica")

    def test_os_aberta_impede_trabalho_avulso_paralelo(self):
        ativo=self.ativo(); abrir_os(ativo_id=ativo.pk,entregue_por="Entregador",problema="Falha",usuario=self.usuario,chave_confirmacao=uuid.uuid4()); ativo.refresh_from_db()
        with self.assertRaisesMessage(ValidationError,"OS aberta"):
            alterar_configuracao(**self.dados(ativo))

    def test_justificativa_e_configuracao_completa_obrigatorias(self):
        ativo=self.ativo()
        with self.assertRaises(ValidationError):
            alterar_configuracao(**self.dados(ativo,justificativa=" "))
        with self.assertRaisesMessage(ValidationError,"configuração deve estar completa"):
            alterar_configuracao(**self.dados(ativo,itens=[{"componente_id":self.componentes["ram"].pk,"acao":"retirar_sem_retorno","quantidade":1}]))

    def test_http_confirmacao_assinada_usuario_csrf_e_reenvio(self):
        self.entrada(self.componentes["ram"],2); ativo=self.ativo(); self.client.force_login(self.usuario)
        url=reverse("ativos:configuracao_alterar",args=[ativo.pk])
        dados={"tipo":"fisica","justificativa":"Upgrade solicitado","versao":ativo.versao,"chave_confirmacao":uuid.uuid4(),"pecas-TOTAL_FORMS":2,"pecas-INITIAL_FORMS":0,"pecas-0-componente":self.componentes["ram"].pk,"pecas-0-acao":"instalar","pecas-0-quantidade":1,"pecas-1-acao":"instalar","pecas-1-quantidade":1}
        resposta=self.client.post(url,dados)
        self.assertEqual(resposta.status_code,200)
        token=resposta.context["token"]
        self.assertFalse(AlteracaoConfiguracao.objects.exists())
        outro=get_user_model().objects.create_user(username="outro_revisao")
        self.client.force_login(outro)
        self.assertContains(self.client.post(url,{"confirmacao":token}),"prévia expirou ou é inválida")
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.post(url,{"confirmacao":token}).status_code,302)
        self.assertEqual(self.client.post(url,{"confirmacao":token}).status_code,302)
        self.assertEqual(AlteracaoConfiguracao.objects.count(),1)
        cliente=Client(enforce_csrf_checks=True); cliente.force_login(self.usuario)
        self.assertEqual(cliente.post(url,{"confirmacao":token}).status_code,403)
        self.assertContains(self.client.post(url,{"confirmacao":token+'x'}),"prévia expirou ou é inválida")

    def test_ficha_mostra_historico_apenas_uma_vez_e_nome_antigo_preservado(self):
        self.entrada(self.componentes["ram"],2); ativo=self.ativo(nome="Nome antigo de referência")
        dados=self.dados(ativo); previa,_=alterar_configuracao(**dados)
        alterar_configuracao(**dados,previa=previa)
        self.client.force_login(self.usuario)
        resposta=self.client.get(reverse("ativos:ativo_detalhar",args=[ativo.pk]))
        self.assertContains(resposta,"Alterações de configuração sem OS",count=1)
        self.assertContains(resposta,"Demanda de upgrade",count=1)
        ativo.refresh_from_db(); self.assertEqual(ativo.nome,"Nome antigo de referência")

    def test_estoque_acompanhado_permanece_quando_zera(self):
        self.entrada(self.componentes["ram"],1); ativo=self.ativo(); dados=self.dados(ativo)
        previa,_=alterar_configuracao(**dados); alterar_configuracao(**dados,previa=previa)
        ram=componentes_com_saldo().get(pk=self.componentes["ram"].pk)
        self.assertEqual(ram.saldo,0); self.assertTrue(ram.estoque_baixo)
        self.client.force_login(self.usuario)
        resposta=self.client.get(reverse("estoque:componente_listar"))
        self.assertContains(resposta,ram.nome)


    def test_sistema_operacional_restaurado_no_formulario_e_preservado_na_edicao(self):
        ativo=self.ativo()
        self.client.force_login(self.usuario)
        url=reverse("ativos:ativo_editar",args=[ativo.pk])
        resposta=self.client.get(url)
        self.assertContains(resposta,'name="config-computador-sistema_operacional"')
        dados={"dti":ativo.dti,"modelo":ativo.modelo,"categoria":ativo.categoria_id,"departamento":ativo.departamento_id,"situacao":ativo.situacao,"garantia":ativo.garantia,"versao":ativo.versao,"config-computador-hostname":"PC-RH-01","config-computador-sistema_operacional":"Windows 11 Pro"}
        self.assertEqual(self.client.post(url,dados).status_code,302)
        ativo.refresh_from_db()
        self.assertEqual(ativo.especificacoes["sistema_operacional"],"Windows 11 Pro")
        self.assertContains(self.client.get(url),'value="Windows 11 Pro"')
        self.assertEqual(ativo.componentes_instalados.count(),5)



class ConcorrenciaRevisaoTests(TransactionTestCase):
    def test_mesma_correcao_concorrente_compensa_uma_vez(self):
        usuario,categoria,departamento,componentes=preparar_cadastros()
        ativo=cadastrar_ativo(dados={"dti":"RACE-01","categoria_id":categoria.pk,"departamento_id":departamento.pk},itens=[{"componente_id":c.pk,"quantidade":1,"origem":"no_equipamento"} for c in componentes.values()],especificacoes={},extras=[],usuario=usuario,chave_confirmacao=uuid.uuid4())[0]
        outro=salvar_componente(nome="RAM alternativa 16 GB",tipo="ram",capacidade=16,unidade_capacidade="GB")
        dados={"ativo_id":ativo.pk,"tipo":"correcao","justificativa":"Especificação incorreta", "chave_confirmacao":uuid.uuid4(),"versao":ativo.versao,"intervencao_id":ativo.intervencoes.get(componente=componentes["ram"]).pk,"componente_id":outro.pk,"quantidade":1}
        previa,_=alterar_configuracao(**dados,usuario=usuario)
        barreira=Barrier(2)
        def executar(_):
            close_old_connections()
            try:
                u=get_user_model().objects.get(pk=usuario.pk); barreira.wait(timeout=10)
                return alterar_configuracao(**dados,usuario=u,previa=previa)[1]
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultado=list(pool.map(executar,range(2)))
        self.assertCountEqual(resultado,[True,False])
        self.assertEqual(AlteracaoConfiguracao.objects.count(),1)


    def test_dois_ativos_disputam_ultima_peca_avulsa(self):
        usuario,categoria,departamento,componentes=preparar_cadastros()
        ativos=[cadastrar_ativo(dados={"dti":f"MANUAL-{i}","categoria_id":categoria.pk,"departamento_id":departamento.pk},itens=[{"componente_id":c.pk,"quantidade":1,"origem":"no_equipamento"} for c in componentes.values()],especificacoes={},extras=[],usuario=usuario,chave_confirmacao=uuid.uuid4())[0] for i in range(2)]
        registrar_entrada(componente_id=componentes["ram"].pk,quantidade=1,origem="compra",data=timezone.localdate(),usuario=usuario,chave_confirmacao=uuid.uuid4())
        dados=[{"ativo_id":a.pk,"tipo":"fisica","justificativa":"Upgrade avulso","versao":a.versao,"chave_confirmacao":uuid.uuid4(),"itens":[{"componente_id":componentes["ram"].pk,"acao":"instalar","quantidade":1}]} for a in ativos]
        previas=[alterar_configuracao(**d,usuario=usuario)[0] for d in dados]
        barreira=Barrier(2)
        def executar(i):
            close_old_connections()
            try:
                u=get_user_model().objects.get(pk=usuario.pk); barreira.wait(timeout=10)
                alterar_configuracao(**dados[i],usuario=u,previa=previas[i]); return "confirmado"
            except ValidationError:
                return "rejeitado"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultado=list(pool.map(executar,range(2)))
        self.assertCountEqual(resultado,["confirmado","rejeitado"])
        self.assertEqual(componentes_com_saldo().get(pk=componentes["ram"].pk).saldo,0)
        self.assertEqual(AlteracaoConfiguracao.objects.count(),1)
